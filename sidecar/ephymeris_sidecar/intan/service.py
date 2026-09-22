"""`IntanService` -- the long-lived recording subsystem `Application` owns.

Shaped like `UtilityBaseline` and `BackupManager`: built in `Application.start`,
driven by commands, publishing a full status snapshot on every change. It owns
three sockets to a local Intan RHX (`client.py`, `streams.py`) and the live
views computed from them (`analysis.py`).

THE RULE, which is the Backup mirror's: RHX may be slow, absent or dead and
none of that may stall or fail a behavior session. Concretely --

  * nothing on the session path awaits RHX except `start_recording`, which is
    the one place a failure must be loud: a recording that cannot start refuses
    before any box is started, because a behavior session silently missing its
    electrophysiology cannot be re-run;
  * `stop_recording` swallows every RHX failure. By the time it runs the
    animals are done; the only thing a raise could do is strand the session as
    `running`;
  * the data sockets are a convenience. Losing them costs the live views and
    never the recording, which RHX writes to disk on its own;
  * closing the command socket does not stop RHX recording, so neither a
    reconnect nor the sidecar exiting ever ends a recording.

STROBES ARRIVE FROM ANOTHER THREAD. `SessionRunner._on_strobe` runs on a port's
session thread; `on_strobe` hops to the loop and everything else here is
loop-only, so there are no locks.

SYNTHETIC DATA HAS NO SYNC LINE. RHX's demo mode (`synthetic`, no controller
attached) generates its own digital inputs, which no box's pin drives, so the
edge matcher would report every real strobe missed and every generated edge
stray -- a wiring diagnosis of wiring that does not exist. In synthetic mode
the matcher is bypassed: `sync` is published empty, and a strobe is placed on
the recording clock by ARRIVAL -- the newest sample seen when the serial line
delivered it, tens of milliseconds late -- so the PSTH still draws, labelled
as approximate. Real data never takes this path; there, an unmatched strobe is
a fact about the wiring and is reported as one.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..settings import IntanEndpoints, SidecarSettings
from . import probemap
from .analysis import (
    EdgeDetector,
    EdgeMatcher,
    MatchedEvent,
    SpikeRing,
    WaveformRing,
    isi_histogram,
    psth,
)
from .client import (
    RhxCommandClient,
    RhxCommandFailed,
    RhxError,
    RhxUnavailable,
    parse_bool,
    rhx_path,
)
from .streams import FrameLayout, SpikeParser, WaveformParser, to_microvolts

log = logging.getLogger(__name__)

#: Status poll and reconnect cadence. A reconnect attempt against a closed port
#: costs one refused connect on loopback.
POLL_S = 1.0
#: How often the socket is LOOKED AT between polls. A closed socket is known
#: without sending anything (`RhxCommandClient.peer_closed`), so this is what
#: makes "RHX disconnected" appear in the UI at once rather than at the next
#: poll. It costs an attribute read.
WATCH_S = 0.25
#: Consecutive unanswered polls before an OPEN socket is given up on. One
#: silence can be RHX busy -- loading a settings file, starting the controller;
#: two, four seconds apart, is a link that is not coming back on its own.
SILENT_POLLS = 2
#: Acquisition runs this long before any box is started, so every channel has a
#: baseline on disk ahead of the first event -- and likewise after the last.
PRE_ROLL_S = 1.0
POST_ROLL_S = 1.0
#: Live views are published this often; the histograms every other tick.
PUBLISH_S = 0.2
#: A scope nobody has touched for this long belonged to a window that is gone.
SCOPE_TTL_S = 15.0
#: Channels whose highpass band may stream at once. Intan's own note: around
#: ten channels at 30 kS/s is where TCP stops keeping up with acquisition.
MAX_SCOPED_CHANNELS = 4
#: SpikeScope snippets are always cut at the widest window RHX offers (6 ms,
#: one third before the crossing) and cropped by the window that draws them.
SNIPPET_PRE_MS = 2.0
SNIPPET_POST_MS = 4.0
SNIPPETS_KEPT = 500
TRIGGERS_KEPT = 2000

FILE_FORMATS = ("Traditional", "OneFilePerSignalType", "OneFilePerChannel")
DOWNSAMPLE = (1, 2, 4, 8, 16, 32, 64, 128)

Broadcast = Callable[[dict[str, Any]], Awaitable[None]]


class IntanNotReady(Exception):
    """RHX is reachable, but this cannot be done now. The message is the
    operator's next step."""


# --------------------------------------------------------------------------- #
# The plan: a validated RecordingConfig
# --------------------------------------------------------------------------- #


@dataclass
class BoxPlan:
    box: int
    digital_in: int
    port: str
    channels: list[str]
    probe_map: dict[str, Any] | None = None
    probe_map_file: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "box": self.box,
            "digitalIn": self.digital_in,
            "port": self.port,
            "channels": list(self.channels),
            "probeMap": self.probe_map_file,
        }


@dataclass
class Recording:
    session_id: str
    group_id: str
    path: str
    base_filename: str
    file_format: str
    sample_rate: int
    boxes: dict[int, BoxPlan]
    file_timestamp: str | None = None
    started_at: str | None = None
    ended_at: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "groupId": self.group_id,
            "path": self.path,
            "baseFilename": self.base_filename,
            "fileTimestamp": self.file_timestamp,
            "fileFormat": self.file_format,
            "sampleRate": self.sample_rate,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "boxes": [self.boxes[b].to_json() for b in sorted(self.boxes)],
        }


def channel_name(port: str, number: int) -> str:
    return f"{port.upper()}-{number:03d}"


def digital_in_name(digital_in: int, controller: str | None) -> str:
    """RHX's name for the Nth digital input (1-based, as Ephymeris binds them).

    The USB Interface Board counts from zero (DIGITAL-IN-00 … 15); both
    controllers count from one. Two digits either way, as Intan's own streaming
    example spells them.
    """
    if controller == "ControllerRecordUSB2":
        return f"DIGITAL-IN-{digital_in - 1:02d}"
    return f"DIGITAL-IN-{digital_in:02d}"


def _int(value: Any, name: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise IntanNotReady(f"{name} must be a whole number from {lo} to {hi}.")
    return value


# --------------------------------------------------------------------------- #
# Scopes
# --------------------------------------------------------------------------- #


@dataclass
class Scope:
    id: str
    kind: str
    box: int
    channel: str | None
    params: dict[str, Any]
    touched: float
    #: spikescope: sequence number of the last snippet sent.
    sent: int = 0
    reset: bool = True
    #: spikescope: the `streaming` flag last sent. A flip is sent on its own,
    #: or a quiet channel -- waveform arriving, no crossing yet -- would read
    #: as "waiting for RHX" until its first spike.
    streaming: bool = False
    #: isi/psth/probemap: the payload last sent, so an unchanged one -- a PSTH
    #: between trials is unchanged for seconds at a time -- is not re-sent.
    last: Any = None
    #: spikescope: the discarded-byte count last sent. A GATE, not a record: a
    #: layout RHX and the sidecar disagree on parses as nothing, so there are
    #: no snippets to send and the window would sit on a stale count showing a
    #: quiet channel -- the one case the count exists to expose. A change in it
    #: is therefore reason enough to send on its own.
    discarded: int = 0


@dataclass
class _Snippets:
    ring: WaveformRing
    pending: list[int] = field(default_factory=list)
    #: (sequence, sample, microvolts)
    cut: list[tuple[int, int, list[float]]] = field(default_factory=list)
    sequence: int = 0


# --------------------------------------------------------------------------- #
# The service
# --------------------------------------------------------------------------- #


class IntanService:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        broadcast: Broadcast,
        settings: SidecarSettings,
        rig_has_sync: Callable[[], bool],
        *,
        pre_roll_s: float = PRE_ROLL_S,
        post_roll_s: float = POST_ROLL_S,
        poll_s: float = POLL_S,
    ) -> None:
        self._loop = loop
        self._broadcast = broadcast
        self._settings = settings
        self._rig_has_sync = rig_has_sync
        self._pre_roll_s = pre_roll_s
        self._post_roll_s = post_roll_s
        self._poll_s = poll_s

        self._client = RhxCommandClient(settings.intan.command_port)
        self._state = "disconnected"
        self._message: str | None = None
        self._info: dict[str, Any] = {}
        self._run_mode: str | None = None
        self._recording: Recording | None = None
        self._waiting_on: list[int] = []
        self._force_stop = asyncio.Event()
        self._last_status: dict[str, Any] | None = None
        self._silent_polls = 0
        #: One connect at a time. The background attempt and an operator
        #: pressing Connect share ONE client, and `connect()` begins by closing
        #: whatever is open -- so two at once close each other's fresh socket
        #: and leave the service holding one RHX has already dropped.
        self._connecting = asyncio.Lock()

        self._tasks: list[asyncio.Task] = []
        self._stream_tasks: list[asyncio.Task] = []
        self._stream_writers: list[asyncio.StreamWriter] = []
        self._waveform: WaveformParser | None = None
        self._live = False

        self._detectors: dict[int, EdgeDetector] = {}
        self._matchers: dict[int, EdgeMatcher] = {}
        self._matched: dict[int, int] = {}
        self._triggers: dict[int, dict[int, list[int]]] = {}
        self._spikes: dict[str, SpikeRing] = {}
        self._snippets: dict[str, _Snippets] = {}
        self._newest_sample = 0
        #: Set when the data sockets (re)open; the first block then tells every
        #: spike ring where its coverage restarts.
        self._reopened = False
        self._scopes: dict[str, Scope] = {}
        #: One scoped-channel sync at a time. `_sync_scoped_channels` reads
        #: `_snippets` and acts on it three awaits later, so two overlapping
        #: calls -- a window opening while another opens or changes channel --
        #: both see the state from before either ran. Observed against a real
        #: RHX on 2026-09-22: `[] -> ['A-000']` logged twice 5 ms apart, and
        #: two layout switches announced with different markers. Harmless
        #: there (both reached the same layout), silent data loss in general:
        #: the second `set_layout` overwrites `_switch_at` with a LATER
        #: marker, and a same-size change then drops blocks that were already
        #: written in the new shape. Invisible against the fake, whose command
        #: round-trips return at once.
        self._scoping = asyncio.Lock()
        self._thresholds: dict[str, int] = {}

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self._tasks = [
            self._loop.create_task(self._poll_loop(), name="intan-poll"),
            self._loop.create_task(self._publish_loop(), name="intan-publish"),
        ]

    async def stop(self) -> None:
        """Close our sockets. NEVER stops RHX: a recording outlives the sidecar."""
        for task in [*self._tasks, *self._stream_tasks]:
            task.cancel()
        for task in [*self._tasks, *self._stream_tasks]:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks, self._stream_tasks = [], []
        self._close_streams()
        await self._client.close()

    def update_settings(self, settings: SidecarSettings) -> None:
        """`settings.push` fires on every reconnect, so an unchanged endpoint
        must not cost the connection."""
        moved = settings.intan != self._settings.intan
        self._settings = settings
        if moved and self._recording is None:
            self._loop.create_task(self._rebind(settings.intan))

    async def _rebind(self, endpoints: IntanEndpoints) -> None:
        await self._client.close()
        self._client = RhxCommandClient(endpoints.command_port)
        self._set_state("disconnected", None)
        await self.publish()

    # --- status -----------------------------------------------------------

    @property
    def recording(self) -> Recording | None:
        return self._recording

    @property
    def is_recording(self) -> bool:
        return self._state in ("recording", "stopping")

    @property
    def force_stop(self) -> asyncio.Event:
        return self._force_stop

    def status_json(self) -> dict[str, Any]:
        info = self._info
        return {
            "state": self._state,
            "message": self._message,
            "connected": self._client.connected,
            "controller": info.get("controller"),
            "version": info.get("version"),
            "sampleRate": info.get("sampleRate"),
            "synthetic": bool(info.get("synthetic", False)),
            "headstagePresent": bool(info.get("headstagePresent", False)),
            "runMode": self._run_mode,
            "ports": dict(info.get("ports", {})),
            "confirmsWrites": self._client.confirms_writes,
            "rigHasSync": self._rig_has_sync(),
            "liveStreams": self._live,
            "recording": self._recording.to_json() if self._recording else None,
            "waitingOn": list(self._waiting_on),
            # Synthetic data drives no sync line; the counters would diagnose
            # wiring that does not exist, so they are not published at all.
            "sync": [] if self.synthetic else [
                {
                    "box": box,
                    "matched": self._matched.get(box, 0),
                    "spuriousEdges": matcher.spurious_edges,
                    "unmatchedStrobes": matcher.unmatched_strobes,
                }
                for box, matcher in sorted(self._matchers.items())
            ],
        }

    @property
    def synthetic(self) -> bool:
        """RHX is generating its data: no controller, and no box's pin on any
        digital input."""
        return bool(self._info.get("synthetic", False))

    async def publish(self, *, force: bool = False) -> None:
        from ..protocol import Evt, event

        status = self.status_json()
        if not force and status == self._last_status:
            return
        self._last_status = status
        await self._broadcast(event(Evt.INTAN_STATUS, status))

    def _set_state(self, state: str, message: str | None) -> None:
        self._state, self._message = state, message

    # --- connection -------------------------------------------------------

    async def connect(self) -> None:
        """Connect now. Raises `RhxUnavailable`, whose message names the click."""
        async with self._connecting:
            if self._client.connected:
                return
            await self._client.connect()
            await self._after_connect()

    async def disconnect(self) -> None:
        if self.is_recording:
            raise IntanNotReady("A recording is running; end it first.")
        self._close_streams()
        await self._client.close()
        self._recording = None
        self._set_state("disconnected", None)
        await self.publish()

    async def _after_connect(self) -> None:
        await self._refresh_info()
        if self._state == "error" and self._recording is not None and self._run_mode == "record":
            # RHX kept recording while we were away; pick the run back up.
            self._set_state("recording", None)
            await self._open_streams()
        elif self._state in ("disconnected", "error"):
            self._recording = None
            self._set_state("idle", None)
        await self.publish()

    async def _refresh_info(self) -> None:
        client = self._client
        self._info = {
            "controller": await client.get("type"),
            "version": await client.get("version"),
            "sampleRate": int(float(await client.get("sampleratehertz"))),
            "synthetic": parse_bool(await client.get("synthetic")),
            "headstagePresent": parse_bool(await client.get("headstagepresent")),
        }
        ports: dict[str, int] = {}
        for letter in "ABCDEFGH":
            try:
                ports[letter] = int(await client.get(f"{letter.lower()}.numberamplifierchannels"))
            except (RhxCommandFailed, ValueError):
                break  # a 512-channel controller has no ports E–H
        self._info["ports"] = ports
        self._run_mode = await client.run_mode()

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must not die
                log.exception("intan poll failed")
            # Sleep in slices, watching the socket: a hang-up ends the sleep.
            waited = 0.0
            while waited < self._poll_s:
                await asyncio.sleep(min(WATCH_S, self._poll_s))
                waited += WATCH_S
                if self._client.peer_closed:
                    break

    async def _poll_once(self) -> None:
        if self._client.peer_closed:
            await self._lost("RHX closed the connection.")
            await self.publish()
            return
        if not self._client.connected:
            try:
                async with self._connecting:
                    if not self._client.connected:
                        await self._client.connect(timeout_s=0.5)
                        await self._after_connect()
            except RhxError:
                if self._state not in ("disconnected", "error"):
                    await self._lost("RHX is not reachable.")
                    await self.publish()
            return
        try:
            self._run_mode = await self._client.run_mode()
            self._silent_polls = 0
        except RhxError as exc:
            # A socket that is still open but did not answer: allow one.
            if self._client.connected:
                self._silent_polls += 1
                if self._silent_polls < SILENT_POLLS:
                    return
            await self._lost(str(exc))
            await self.publish()
            return
        if self._state == "recording" and self._run_mode != "record":
            self._set_state(
                "error",
                f"RHX is no longer recording (run mode is {self._run_mode!r}) — it was "
                "stopped from RHX itself. The behavior session is unaffected.",
            )
        await self.publish()

    async def _lost(self, why: str) -> None:
        """The link is gone. ALWAYS closes our end, and that is the point: the
        UI's `connected` is the socket's, so a link declared lost while the
        socket stayed open went on reading "connected" on the Recording tab and the
        Dashboard -- which is exactly how a silent RHX was reported."""
        self._close_streams()
        self._silent_polls = 0
        await self._client.close()
        self._run_mode = None
        if self.is_recording:
            self._set_state(
                "error",
                f"Lost contact with RHX ({why}) RHX keeps recording on its own; "
                "reconnecting. The behavior session is unaffected.",
            )
        else:
            self._recording = None
            self._set_state("disconnected", None)

    # --- configure --------------------------------------------------------

    async def configure(
        self,
        session_id: str,
        group_id: str,
        config: dict[str, Any],
        base_filename: str,
        notes: tuple[str, str, str] = ("", "", ""),
    ) -> None:
        if self.is_recording:
            raise IntanNotReady("A recording is already running.")
        if not self._client.connected:
            await self.connect()
        client = self._client

        await self._refresh_info()
        if self._run_mode == "record" or self._run_mode == "trigger":
            raise IntanNotReady("RHX is already recording. Stop it in RHX first.")
        if self._run_mode == "run":
            # Left running for a look at the signals, almost always. Every
            # saving parameter is ignored while the board runs, so stop it.
            await client.set_run_mode("stop")
            self._run_mode = "stop"

        plan = self._plan(session_id, group_id, config, base_filename)
        controller = self._info.get("controller")

        directory = Path(plan.path)
        try:
            await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        except OSError as exc:
            raise IntanNotReady(f"Couldn't create {directory}: {exc.strerror or exc}") from exc

        await client.execute("clearalldataoutputs")
        # Where, as what, under what name: the three a recording cannot be
        # wrong about, each read back. `verify` is also the only thing that
        # catches RHX accepting a path and storing it cut at its first space.
        await client.set("fileformat", plan.file_format, verify=True)
        try:
            await client.set("filename.path", rhx_path(plan.path), verify=True)
        except RhxCommandFailed as exc:
            raise RhxCommandFailed(
                exc.command,
                f"{exc.reply}. RHX did not keep the save location as given — if it "
                "contains a space, choose one that does not.",
            ) from exc
        await client.set("filename.basefilename", plan.base_filename, verify=True)

        snapshot_pre = _int(config.get("snapshotPreMs", 1), "Snapshot pre-detect", 0, 3)
        snapshot_post = _int(config.get("snapshotPostMs", 2), "Snapshot post-detect", 1, 6)
        downsample = config.get("lowpassDownsample", 1)
        if downsample not in DOWNSAMPLE:
            raise IntanNotReady("Lowpass downsample must be a power of two up to 128.")
        commands = [
            "set createnewdirectory true",
            f"set savewidebandamplifierwaveforms {_b(config.get('saveWideband'))}",
            f"set savespikedata {_b(config.get('saveSpikes'))}",
            f"set savespikesnapshots {_b(config.get('saveSpikeSnapshots'))}",
            f"set spikesnapshotpredetectmilliseconds {-snapshot_pre}",
            f"set spikesnapshotpostdetectmilliseconds {snapshot_post}",
            f"set savelowpassamplifierwaveforms {_b(config.get('saveLowpass'))}",
            f"set lowpasswaveformdownsamplerate {downsample}",
            f"set savehighpassamplifierwaveforms {_b(config.get('saveHighpass'))}",
        ]
        minutes = config.get("newFileMinutes")
        if minutes is not None and plan.file_format == "Traditional":
            commands.append(f"set newsavefileperiodminutes {_int(minutes, 'New file period', 1, 999)}")

        # Amplifier channels: exactly the ranges the boxes claim are saved and
        # spike-streamed; everything else present is switched off, so a
        # headstage nobody assigned does not fill the disk.
        wanted = {name for box in plan.boxes.values() for name in box.channels}
        for letter, count in self._info.get("ports", {}).items():
            for number in range(count):
                name = channel_name(letter, number).lower()
                on = name.upper() in wanted
                commands.append(f"set {name}.enabled {_b(on)}")
                if on:
                    commands.append(f"set {name}.tcpdataoutputenabledspike true")

        for box in plan.boxes.values():
            din = digital_in_name(box.digital_in, controller).lower()
            commands += [
                f"set {din}.enabled true",
                f"set {din}.customchannelname BOX{box.box}_EVENTS",
                f"set {din}.tcpdataoutputenabled true",
            ]
        for index, note in enumerate(notes, start=1):
            commands.append(f"set note{index} {_note(note)}")
        await client.send(commands)

        await self._apply_thresholds(config.get("threshold") or {})
        await self._copy_probe_maps(plan)

        self._recording = plan
        self._reset_live(plan)
        self._set_state("configured", None)
        await self._open_streams()
        await self.publish()

    def _plan(
        self, session_id: str, group_id: str, config: dict[str, Any], base_filename: str
    ) -> Recording:
        if not self._rig_has_sync():
            raise IntanNotReady(
                "This rig's wiring declares no sync channel, so no box pulses on its "
                "events. Add one on the Rig tab's wiring page, then reflash."
            )
        directory = str(config.get("saveDirectory") or "").strip()
        if not directory:
            raise IntanNotReady("Choose where the recording is saved.")
        file_format = config.get("fileFormat")
        if file_format not in FILE_FORMATS:
            raise IntanNotReady("Unknown file format.")
        if not any(config.get(k) for k in ("saveWideband", "saveSpikes", "saveLowpass", "saveHighpass")):
            raise IntanNotReady("Nothing would be saved: turn on wideband, spikes, lowpass or highpass.")

        present: dict[str, int] = self._info.get("ports", {})
        boxes: dict[int, BoxPlan] = {}
        claimed: dict[str, int] = {}
        for raw in config.get("boxes") or []:
            box = _int(raw.get("box"), "Box", 1, 6)
            if box in boxes:
                raise IntanNotReady(f"Box {box} is listed twice.")
            binding = self._settings.binding_for(box)
            digital_in = binding.intan_digital_in if binding else None
            if digital_in is None:
                raise IntanNotReady(
                    f"Box {box} has no Intan digital input. Bind one on the Recording tab."
                )
            port = str(raw.get("port") or "").strip().upper()
            count = present.get(port, 0)
            if count <= 0:
                raise IntanNotReady(f"Box {box}: no headstage is present on port {port or '?'}.")
            first = _int(raw.get("firstChannel"), f"Box {box} first channel", 0, count - 1)
            last = _int(raw.get("lastChannel"), f"Box {box} last channel", first, count - 1)
            channels = [channel_name(port, n) for n in range(first, last + 1)]
            for name in channels:
                if name in claimed:
                    raise IntanNotReady(
                        f"{name} is claimed by box {claimed[name]} and box {box}."
                    )
                claimed[name] = box
            plan = BoxPlan(box=box, digital_in=digital_in, port=port, channels=channels)
            map_path = raw.get("probeMapPath")
            if isinstance(map_path, str) and map_path.strip():
                try:
                    plan.probe_map = probemap.parse_file(map_path)
                except probemap.ProbeMapError as exc:
                    raise IntanNotReady(f"Box {box}: {exc}") from exc
                plan.probe_map_file = map_path
            boxes[box] = plan
        if not boxes:
            raise IntanNotReady("No box is assigned to a headstage port.")

        return Recording(
            session_id=session_id,
            group_id=group_id,
            path=directory,
            base_filename=base_filename,
            file_format=file_format,
            sample_rate=int(self._info["sampleRate"]),
            boxes=boxes,
        )

    async def _apply_thresholds(self, threshold: dict[str, Any]) -> None:
        mode = threshold.get("mode", "keep")
        if mode == "keep":
            return
        client = self._client
        if mode == "absolute":
            microvolts = _int(threshold.get("microvolts"), "Threshold", -5000, 5000)
            await client.send(
                ["set absolutethresholdsenabled true", f"set absolutethresholdmicrovolts {microvolts}"]
            )
        elif mode == "rms":
            multiple = threshold.get("rmsMultiple")
            if isinstance(multiple, bool) or not isinstance(multiple, (int, float)) or not 3.0 <= multiple <= 20.0:
                raise IntanNotReady("The RMS multiple must be from 3.0 to 20.0.")
            await client.send(
                [
                    "set absolutethresholdsenabled false",
                    f"set rmsmultiplethreshold {float(multiple):g}",
                    f"set negativerelativethreshold {_b(threshold.get('negative', True))}",
                ]
            )
        else:
            raise IntanNotReady("Unknown threshold mode.")
        # The parameters above change nothing until this runs, and it applies
        # to ENABLED channels only -- which is why it follows the enables.
        await client.execute("setspikedetectionthresholds")

    async def _copy_probe_maps(self, plan: Recording) -> None:
        """Keep the map beside the data it describes. Best effort: a copy that
        fails costs a convenience, not the recording."""
        for box in plan.boxes.values():
            if not box.probe_map_file:
                continue
            source = Path(box.probe_map_file)
            target = Path(plan.path) / f"box{box.box}_{source.name}"
            try:
                await asyncio.to_thread(shutil.copyfile, source, target)
                box.probe_map_file = target.name
            except OSError as exc:
                log.warning("couldn't copy probe map %s: %s", source, exc)
                box.probe_map_file = source.name

    def release(self) -> None:
        """The session let go without recording (abandon, or a group that
        never started). Refuses nothing; a running recording is left alone."""
        if self.is_recording:
            return
        if self._recording is not None:
            self._recording = None
            self._close_streams()
            if self._state == "configured":
                self._set_state("idle", None)
            self._loop.create_task(self.publish())

    def configured_for(self, session_id: str, group_id: str) -> bool:
        r = self._recording
        return (
            r is not None
            and r.session_id == session_id
            and r.group_id == group_id
            and self._state in ("configured", "recording")
        )

    # --- record -----------------------------------------------------------

    async def start_recording(self) -> None:
        """Begin saving. THE ONE PLACE RHX MAY FAIL THE SESSION PATH."""
        if self._state == "recording":
            return
        if self._state != "configured" or self._recording is None:
            raise IntanNotReady("No recording is configured for this group.")
        client = self._client
        await client.set_run_mode("record")
        self._run_mode = "record"

        # "Record" is a request; samples arriving is the fact.
        deadline = self._loop.time() + 5.0
        while int(float(await client.get("currenttimestamp"))) <= 0:
            if self._loop.time() >= deadline:
                await self._abort_start()
                raise RhxCommandFailed("set runmode record", "RHX entered Record but no samples are arriving")
            await asyncio.sleep(0.05)

        stamp = await client.get("filename.activefiletimestamp")
        self._recording.file_timestamp = None if stamp == "RecordingNotStarted" else stamp
        self._recording.started_at = _now()
        self._force_stop.clear()
        self._set_state("recording", None)
        await self.publish()
        await asyncio.sleep(self._pre_roll_s)

    async def _abort_start(self) -> None:
        try:
            await self._client.set_run_mode("stop")
        except RhxError:
            pass

    def note_waiting(self, boxes: list[int]) -> None:
        """Graceful-end progress from the runner: who is still mid-trial."""
        self._waiting_on = sorted(boxes)
        if self._state == "recording" and boxes:
            self._set_state("stopping", None)
        self._loop.create_task(self.publish())

    async def stop_recording(self) -> dict[str, Any] | None:
        """Stop saving and hand back the run's record. NEVER RAISES."""
        recording = self._recording
        if recording is None or recording.started_at is None:
            self.release()
            return None
        self._set_state("stopping", None)
        self._waiting_on = []
        await self.publish()
        message: str | None = None
        try:
            await asyncio.sleep(self._post_roll_s)
            await self._client.set_run_mode("stop")
            self._run_mode = "stop"
        except Exception as exc:  # noqa: BLE001 - the animals are done; never raise
            log.error("couldn't stop the RHX recording: %s", exc)
            message = (
                f"Ephymeris could not stop the RHX recording ({exc}). "
                "Stop it from RHX; the data it has written is safe."
            )
        recording.ended_at = _now()
        self._recording = None
        self._close_streams()
        self._force_stop.clear()
        if message:
            self._set_state("error", message)
        else:
            self._set_state("idle" if self._client.connected else "disconnected", None)
        await self.publish()
        return recording.to_json()

    # --- what the runner tells us ----------------------------------------

    def recording_fields(self, box: int) -> dict[str, Any]:
        """Flat `intan_*` fields for one animal's session document."""
        recording = self._recording
        if recording is None or box not in recording.boxes or not self.is_recording:
            return {}
        plan = recording.boxes[box]
        name = recording.base_filename
        if recording.file_timestamp:
            name = f"{name}_{recording.file_timestamp}"
        return {
            "intan_recording": name,
            "intan_path": recording.path,
            "intan_digital_in": plan.digital_in,
            "intan_port": plan.port,
            "intan_channels": f"{plan.channels[0]}:{plan.channels[-1]}",
            "intan_sample_rate": recording.sample_rate,
        }

    def box_started(self, box: int, animal: str) -> None:
        """Thread-safe. The Mega's clock restarts at START, so the box gets a
        fresh matcher -- an anchor carried over would be measured against a
        clock that no longer exists."""
        self._loop.call_soon_threadsafe(self._box_started, box, animal)

    def _box_started(self, box: int, animal: str) -> None:
        recording = self._recording
        if recording is None or box not in recording.boxes or not self.is_recording:
            return
        self._matchers[box] = EdgeMatcher(float(recording.sample_rate))
        self._matched[box] = 0
        self._triggers[box] = {}
        self._loop.create_task(self._livenote(f"BOX{box} START {animal}"))

    def box_ended(self, box: int, animal: str, reason: str) -> None:
        if self._recording is not None and box in self._recording.boxes and self.is_recording:
            self._loop.create_task(self._livenote(f"BOX{box} END {animal} ({reason})"))

    async def _livenote(self, note: str) -> None:
        try:
            await self._client.livenote(note)
        except RhxError as exc:
            log.debug("livenote dropped: %s", exc)

    def on_strobe(self, box: int, code: int, ms: int) -> None:
        """Thread-safe: called from a port's session thread on every strobe."""
        if box in self._matchers:
            self._loop.call_soon_threadsafe(self._strobe, box, code, ms)

    def _strobe(self, box: int, code: int, ms: int) -> None:
        matcher = self._matchers.get(box)
        if matcher is None:
            return
        if self.synthetic:
            # No sync line to match against: place the strobe where the
            # recording clock stood when the serial line delivered it.
            if self._live and self._newest_sample > 0:
                self._take(box, [MatchedEvent(code, ms, self._newest_sample)])
            return
        self._take(box, matcher.add_strobe(code, ms))

    def _take(self, box: int, events: list) -> None:
        triggers = self._triggers.setdefault(box, {})
        for event in events:
            if event.sample is None:
                continue
            self._matched[box] = self._matched.get(box, 0) + 1
            samples = triggers.setdefault(event.code, [])
            samples.append(event.sample)
            if len(samples) > TRIGGERS_KEPT:
                del samples[: len(samples) - TRIGGERS_KEPT]

    # --- data sockets -----------------------------------------------------

    def _reset_live(self, plan: Recording) -> None:
        self._detectors = {b: EdgeDetector(p.digital_in) for b, p in plan.boxes.items()}
        self._matchers, self._matched, self._triggers = {}, {}, {}
        self._spikes = {name: SpikeRing() for p in plan.boxes.values() for name in p.channels}
        self._snippets = {}
        self._newest_sample = 0
        self._thresholds = {}

    def _layout(self) -> FrameLayout:
        return FrameLayout(
            amplifier=tuple((name, "high") for name in self._snippets), digital_in=True
        )

    async def _open_streams(self) -> None:
        """Best effort. The recording does not depend on these."""
        self._close_streams()
        endpoints = self._settings.intan
        client = self._client
        try:
            for socket_name in ("tcpwaveformdatasocket", "tcpspikedatasocket"):
                if (await client.get(f"{socket_name}.status")).lower() == "disconnected":
                    await client.set(f"{socket_name}.status", "Pending")
            waveform = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", endpoints.waveform_port), 2.0
            )
            spike = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", endpoints.spike_port), 2.0
            )
        except (RhxError, OSError, asyncio.TimeoutError) as exc:
            log.warning("live views unavailable: couldn't open RHX's data sockets: %s", exc)
            self._live = False
            return
        self._waveform = WaveformParser(self._layout())
        self._reopened = True
        self._stream_writers = [waveform[1], spike[1]]
        self._stream_tasks = [
            self._loop.create_task(self._read_waveform(waveform[0]), name="intan-waveform"),
            self._loop.create_task(self._read_spikes(spike[0]), name="intan-spikes"),
        ]
        self._live = True

    def _close_streams(self) -> None:
        for task in self._stream_tasks:
            task.cancel()
        for writer in self._stream_writers:
            writer.close()
        self._stream_tasks, self._stream_writers = [], []
        self._waveform = None
        self._live = False

    async def _read_waveform(self, reader: asyncio.StreamReader) -> None:
        parser = self._waveform
        assert parser is not None
        try:
            while data := await reader.read(1 << 16):
                for block in parser.feed(data):
                    self._on_block(block)
        except (OSError, asyncio.CancelledError):
            return
        finally:
            self._live = False

    def _on_block(self, block: Any) -> None:
        stamps = block.timestamps
        self._newest_sample = stamps[-1]
        if self._reopened:
            self._reopened = False
            for ring in self._spikes.values():
                ring.reopened(stamps[0])
        if block.digital_in is not None and not self.synthetic:
            for box, detector in self._detectors.items():
                edges = detector.feed(stamps, block.digital_in)
                matcher = self._matchers.get(box)
                if edges and matcher is not None:
                    self._take(box, matcher.add_edges(edges))
        for (name, _band), raw in block.amplifier.items():
            store = self._snippets.get(name)
            if store is None:
                continue
            store.ring.extend(stamps[0], raw)
            self._cut(store)

    def _cut(self, store: _Snippets) -> None:
        rate = self._recording.sample_rate if self._recording else 30000
        before = int(SNIPPET_PRE_MS * rate / 1000)
        after = int(SNIPPET_POST_MS * rate / 1000)
        newest = store.ring.newest
        if newest is None:
            return
        still: list[int] = []
        for sample in store.pending:
            if sample + after > newest:
                still.append(sample)  # its tail has not arrived yet
                continue
            raw = store.ring.cut(sample, before, after)
            if raw is None:
                continue  # aged out, or the ring was emptied by a gap
            store.sequence += 1
            store.cut.append((store.sequence, sample, [round(to_microvolts(v), 1) for v in raw]))
        store.pending = still
        if len(store.cut) > SNIPPETS_KEPT:
            del store.cut[: len(store.cut) - SNIPPETS_KEPT]

    async def _read_spikes(self, reader: asyncio.StreamReader) -> None:
        parser = SpikeParser()
        try:
            while data := await reader.read(1 << 16):
                for spike in parser.feed(data):
                    ring = self._spikes.get(spike.channel)
                    if ring is None:
                        continue
                    ring.add(spike.timestamp)
                    if spike.timestamp > self._newest_sample:
                        self._newest_sample = spike.timestamp
                    store = self._snippets.get(spike.channel)
                    if store is not None:
                        store.pending.append(spike.timestamp)
                        # The two sockets are not in lockstep: if the waveform
                        # tail is already here, cut now rather than at the
                        # next block.
                        self._cut(store)
        except (OSError, asyncio.CancelledError):
            return
        finally:
            self._live = False

    # --- scopes -----------------------------------------------------------

    async def open_scope(self, kind: str, box: int, channel: str | None, params: dict[str, Any]) -> str:
        recording = self._recording
        if recording is None or box not in recording.boxes:
            raise IntanNotReady(f"Box {box} is not part of a configured recording.")
        channel = self._check_channel(box, channel, required=kind != "probemap")
        scope = Scope(
            id=uuid.uuid4().hex[:12], kind=kind, box=box, channel=channel,
            params=dict(params), touched=time.monotonic(),
        )
        self._scopes[scope.id] = scope
        try:
            await self._sync_scoped_channels()
        except Exception:
            self._scopes.pop(scope.id, None)
            raise
        return scope.id

    async def update_scope(self, scope_id: str, channel: Any, params: dict[str, Any] | None) -> bool:
        scope = self._scopes.get(scope_id)
        if scope is None:
            return False
        scope.touched = time.monotonic()
        if params:
            scope.params.update(params)
            scope.last = None
        if channel is not None and channel != scope.channel:
            previous = scope.channel
            scope.channel = self._check_channel(scope.box, channel, required=True)
            scope.sent, scope.reset, scope.last, scope.streaming = 0, True, None, False
            try:
                await self._sync_scoped_channels()
            except Exception:
                scope.channel = previous
                raise
        return True

    async def close_scope(self, scope_id: str) -> None:
        if self._scopes.pop(scope_id, None) is not None:
            await self._sync_scoped_channels()

    def _check_channel(self, box: int, channel: Any, *, required: bool) -> str | None:
        if channel is None:
            if required:
                raise IntanNotReady("Pick a channel.")
            return None
        name = str(channel).upper()
        assert self._recording is not None
        if name not in self._recording.boxes[box].channels:
            raise IntanNotReady(f"{name} is not one of box {box}'s channels.")
        return name

    async def _sync_scoped_channels(self) -> None:
        """Make RHX's streamed highpass channels match the open SpikeScopes.

        SERIALIZED, and the whole body is inside the lock on purpose: both
        `wanted` and `current` must be read after any call already in flight
        has finished mutating `_snippets`, or the second caller plans its
        change against a world that no longer exists (see `_scoping`). Every
        caller has already updated `_scopes` before getting here, so a
        duplicate call re-reads `wanted`, finds it equal to `current`, and
        falls out as the no-op it should always have been.
        """
        async with self._scoping:
            wanted = {s.channel for s in self._scopes.values() if s.kind == "spikescope" and s.channel}
            current = set(self._snippets)
            if wanted == current:
                return
            if len(wanted) > MAX_SCOPED_CHANNELS:
                raise IntanNotReady(
                    f"At most {MAX_SCOPED_CHANNELS} channels can stream to a SpikeScope at once — "
                    "more and TCP falls behind acquisition."
                )
            commands = [f"set {n.lower()}.tcpdataoutputenabledhigh true" for n in sorted(wanted - current)]
            commands += [f"set {n.lower()}.tcpdataoutputenabledhigh false" for n in sorted(current - wanted)]
            await self._client.send(commands)
            log.info("scoped highpass channels: %s -> %s", sorted(current), sorted(wanted))
            # Read AFTER the change is acknowledged: a block stamped at or past
            # this was written in the new shape. It is what a same-size change
            # (one channel swapped for another) is switched on, since the framing
            # cannot tell those apart -- `streams.py`, module doc.
            marker: int | None = None
            if self._waveform is not None:
                try:
                    marker = int(float(await self._client.get("currenttimestamp")))
                except (RhxError, ValueError):
                    marker = None
            rate = self._recording.sample_rate if self._recording else 30000
            for name in wanted - current:
                self._snippets[name] = _Snippets(ring=WaveformRing(capacity=2 * rate))
                try:
                    self._thresholds[name] = int(float(await self._client.get(f"{name.lower()}.spikethresholdmicrovolts")))
                except (RhxError, ValueError):
                    pass
            for name in current - wanted:
                self._snippets.pop(name, None)
            if self._waveform is not None:
                log.info("waveform layout switches at sample %s", marker)
                self._waveform.set_layout(self._layout(), from_timestamp=marker)

    async def set_threshold(self, channel: str, microvolts: int) -> int:
        name = channel.upper()
        value = _int(microvolts, "Threshold", -5000, 5000)
        await self._client.set(f"{name.lower()}.spikethresholdmicrovolts", value, verify=True)
        self._thresholds[name] = value
        return value

    def probe_map_for(self, box: int) -> dict[str, Any] | None:
        recording = self._recording
        if recording is None or box not in recording.boxes:
            return None
        return recording.boxes[box].probe_map

    async def _publish_loop(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(PUBLISH_S)
            tick += 1
            try:
                await self._publish_scopes(slow=tick % 3 == 0)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("scope publish failed")

    async def _publish_scopes(self, *, slow: bool) -> None:
        from ..protocol import Evt, event

        now = time.monotonic()
        stale = [s.id for s in self._scopes.values() if now - s.touched > SCOPE_TTL_S]
        for scope_id in stale:
            await self.close_scope(scope_id)
        recording = self._recording
        if recording is None:
            return
        for scope in list(self._scopes.values()):
            # Snippets and site rates every tick; the histograms every third.
            if scope.kind in ("isi", "psth") and not slow:
                continue
            data = self._scope_payload(scope, recording)
            if data is None:
                continue
            if scope.kind != "spikescope":
                if data == scope.last:
                    continue
                scope.last = data
            await self._broadcast(
                event(
                    Evt.INTAN_SCOPE_DATA,
                    {"scopeId": scope.id, "kind": scope.kind, "box": scope.box,
                     "channel": scope.channel, "data": data},
                )
            )

    def _scope_payload(self, scope: Scope, recording: Recording) -> dict[str, Any] | None:
        rate = float(recording.sample_rate)
        params = scope.params
        if scope.kind == "spikescope":
            store = self._snippets.get(scope.channel or "")
            added = [] if store is None else [c for c in store.cut if c[0] > scope.sent]
            reset, scope.reset = scope.reset, False
            streaming = store is not None and store.ring.newest is not None
            parser = self._waveform
            discarded = 0 if parser is None else parser.discarded
            if (
                not added
                and not reset
                and streaming == scope.streaming
                and discarded == scope.discarded
            ):
                return None
            if added:
                scope.sent = added[-1][0]
            scope.streaming = streaming
            scope.discarded = discarded
            return {
                "reset": reset,
                "added": [{"sample": sample, "microvolts": uv} for _, sample, uv in added],
                "sampleRate": recording.sample_rate,
                "preMs": SNIPPET_PRE_MS,
                "postMs": SNIPPET_POST_MS,
                "thresholdMicrovolts": self._thresholds.get(scope.channel or ""),
                "streaming": streaming,
                # Bytes the parser threw away hunting for a block boundary.
                # CUMULATIVE for the recording and never reset, so it is not
                # an error level: a deliberate layout change (opening a scope,
                # swapping its channel) pays a one-off resync of whatever was
                # in flight, and that is a healthy stream's normal cost. Only
                # a number that KEEPS climbing is a frame shape RHX and this
                # sidecar disagree on, which is the distinction the window
                # draws before it says anything.
                "discardedBytes": discarded,
            }
        if scope.kind == "isi":
            ring = self._spikes.get(scope.channel or "")
            return isi_histogram(
                ring.snapshot() if ring else [], rate,
                float(params.get("spanMs", 200)), float(params.get("binMs", 5)),
            )
        if scope.kind == "psth":
            ring = self._spikes.get(scope.channel or "")
            codes = params.get("triggerCodes") or []
            by_code = self._triggers.get(scope.box, {})
            triggers = sorted(s for code in codes for s in by_code.get(int(code), []))
            data = psth(
                ring.snapshot() if ring else [], triggers, rate,
                float(params.get("preMs", 500)), float(params.get("postMs", 500)),
                float(params.get("binMs", 5)), int(params.get("maxTrials", 50)),
                self._newest_sample,
                ring.complete_since if ring else 0,
            )
            # How each trigger was placed on the recording clock: by its sync
            # edge, or -- synthetic data only -- by when its strobe arrived.
            data["alignment"] = "arrival" if self.synthetic else "sync"
            return data
        if scope.kind == "probemap":
            since = self._newest_sample - int(rate)
            return {
                "rates": {
                    name: self._spikes[name].count_since(since)
                    for name in recording.boxes[scope.box].channels
                    if name in self._spikes
                }
            }
        return None


def _b(value: Any) -> str:
    return "true" if value else "false"


def _note(text: str) -> str:
    """A note is one `set` value: no `;` (it would end the command)."""
    return (text.replace(";", ",").replace("\n", " ").strip() or "-")[:200]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

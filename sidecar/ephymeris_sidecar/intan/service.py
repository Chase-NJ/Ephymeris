"""`IntanService` -- the long-lived recording subsystem `Application` owns.

Shaped like `UtilityBaseline` and `BackupManager`: built in `Application.start`,
driven by commands, publishing a full status snapshot on every change. It owns
three sockets to a local Intan RHX (`client.py`, `streams.py`), and from the
two data sockets feeds the sync check and the live firing map (`analysis.py`).

THE RULE, which is the Backup mirror's: RHX may be slow, absent or dead and
none of that may stall or fail a behavior session. Concretely --

  * nothing on the session path awaits RHX except `start_recording`, which is
    the one place a failure must be loud: a recording that cannot start refuses
    before any box is started, because a behavior session silently missing its
    electrophysiology cannot be re-run;
  * `stop_recording` swallows every RHX failure, and is bounded
    (`STOP_TIMEOUT_S`). By the time it runs the animals are done; the only
    thing a raise could do is strand the session as `running`. A stop that
    could not reach RHX is OWED, and sent once RHX answers again -- only if
    RHX is still writing that run's file (`Filename.ActiveFileTimestamp`), so
    a recording started by hand meanwhile is never stopped;
  * a run, once started, is kept until it is stopped -- through a lost link or
    a Stop pressed in RHX -- so the End that follows still waits for the
    boxes, stops it and records it (`run_open_for`);
  * the data sockets are a convenience. Losing them costs the sync check and
    the firing map, never the recording, which RHX writes to disk on its own;
  * closing the command socket does not stop RHX recording, so neither a
    reconnect nor the sidecar exiting ever ends a recording.

STROBES ARRIVE FROM ANOTHER THREAD. `SessionRunner._on_strobe` runs on a port's
session thread; `on_strobe` hops to the loop and everything else here is
loop-only, so there are no locks.

SYNTHETIC DATA HAS NO SYNC LINE. RHX's demo mode (`synthetic`, no controller
attached) generates its own digital inputs, which no box's pin drives, so the
edge matcher would report every real strobe missed and every generated edge
stray -- a wiring diagnosis of wiring that does not exist. In synthetic mode
the matcher is bypassed and `sync` is published empty. Real data never takes
this path; there, an unmatched strobe is a fact about the wiring and is
reported as one.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..settings import IntanEndpoints, SidecarSettings
from . import probemap
from .impedance import ImpedanceFile, parse_csv
from .yield_store import RunSpikes
from .analysis import (
    EdgeDetector,
    EdgeMatcher,
    SampleClock,
)
from .client import (
    RhxCommandClient,
    RhxCommandFailed,
    RhxError,
    RhxUnavailable,
    parse_bool,
    rhx_path,
)
from .streams import FrameLayout, SpikeParser, WaveformParser

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
#: The longest `set runmode stop` may take before the stop is given up on and
#: owed. Covers the client's own wait for the change to take, with room.
STOP_TIMEOUT_S = 12.0
#: The frequency impedances are measured at: the field's convention, so one
#: animal's measurements compare across sessions.
IMPEDANCE_FREQ_HZ = 1000
#: `MeasureImpedance` holds RHX until every channel of every headstage is
#: measured: seconds in demo mode, up to about a minute on a full rig.
MEASURE_TIMEOUT_S = 180.0
#: How long the saved CSV may take to appear after the measurement, when RHX's
#: writes cannot be confirmed (`confirmsWrites: false`) and so nothing says
#: when the measurement ended.
IMPEDANCE_FILE_WAIT_S = 30.0
#: Spikes are sent as `intan.spikes` this often: a frame at 30 fps, so the
#: firing map's flash is never more than one frame behind the sidecar.
SPIKES_PUBLISH_S = 1 / 30
#: RHX writes to its data sockets every this many 128-sample blocks (its
#: `TCPNumberDataBlocksPerWrite`, default 10: 43 ms at 30 kS/s). Two is 8.5 ms,
#: and costs nothing here now that only spikes and one digital word stream.
BLOCKS_PER_WRITE = 2

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
    #: The mapping confirmation this was set up for (`SessionLifecycle.confirmations`).
    #: None for a setup made without one, which never starts a recording.
    confirmation: int | None = None
    #: `RecordingConfig.threshold` as configured: what each run's spike
    #: counts were detected under (`RECORDING.md#active-site-yield`).
    threshold: dict[str, Any] | None = None
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


@dataclass
class _RunCount:
    started: float
    samples_at_start: int
    counts: dict[str, int] = field(default_factory=dict)


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
        stop_timeout_s: float = STOP_TIMEOUT_S,
    ) -> None:
        self._loop = loop
        self._broadcast = broadcast
        self._settings = settings
        self._rig_has_sync = rig_has_sync
        self._pre_roll_s = pre_roll_s
        self._post_roll_s = post_roll_s
        self._poll_s = poll_s
        self._stop_timeout_s = stop_timeout_s

        self._client = RhxCommandClient(settings.intan.command_port)
        self._state = "disconnected"
        self._message: str | None = None
        self._info: dict[str, Any] = {}
        self._run_mode: str | None = None
        self._recording: Recording | None = None
        #: A run whose stop could not reach RHX: it ended in the session, and
        #: RHX may still be writing it. Stopped once RHX answers again, if RHX
        #: is still writing THIS run's file (`_send_owed_stop`).
        self._stop_owed: Recording | None = None
        #: RHX is known to be writing the open run: true from a start that took,
        #: or a reconnect that found RHX on this run's file; false once the link
        #: is lost or RHX is seen out of Record. Only a confirmed run is
        #: stopped outright; any other goes through the owed-stop check.
        self._run_confirmed = False
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
        #: The live firing map's feed: channel → its box, spikes counted per
        #: box since the last `intan.spikes`, and the slowest of them.
        self._box_of: dict[str, int] = {}
        self._fired: dict[int, dict[str, int]] = {}
        self._fired_lag: dict[int, float] = {}
        self._clock: SampleClock | None = None
        #: Each running box's spike counts since its START, and the samples
        #: the waveform socket had delivered then (`RECORDING.md#active-site-yield`).
        self._runs: dict[int, _RunCount] = {}
        self._samples_seen = 0

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self._tasks = [
            self._loop.create_task(self._poll_loop(), name="intan-poll"),
            self._loop.create_task(self._spikes_loop(), name="intan-spikes-publish"),
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
        """RHX is recording, as far as the link can tell right now."""
        return self._state in ("recording", "stopping")

    @property
    def _run_open(self) -> bool:
        """A recording this service started and has not stopped, whatever the
        link says now: lost, or Stop pressed in RHX, it is still a run."""
        recording = self._recording
        return recording is not None and recording.started_at is not None

    def run_open_for(self, session_id: str) -> bool:
        """This session has a recording running, or one it started and has not
        stopped yet -- which an End must still wait for, stop and record
        (`RECORDING.md#when-rhx-goes-away`)."""
        recording = self._recording
        return self._run_open and recording is not None and recording.session_id == session_id

    def may_still_record_for(self, session_id: str) -> bool:
        """RHX may still be writing this session's run: false only once RHX is
        SEEN out of Record (Stop pressed in RHX), when an End's grace period
        would keep nothing inside the recording. Unsure -- the link lost, a
        file stamp unread -- is true: End now is the escape, and a cut trial
        is not. Whether to STOP RHX is a separate, stricter question
        (`_send_owed_stop`)."""
        return self.run_open_for(session_id) and self._run_mode in (None, "record", "trigger")

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

    def _trouble(self, message: str) -> None:
        """RHX is in trouble with a run open: `error`, unless an End is waiting
        on boxes, which stays `stopping` -- the state Mission Control offers
        End now in -- with the message saying why."""
        if self._run_open and self._waiting_on:
            self._set_state("stopping", message)
        else:
            self._set_state("error", message)

    # --- connection -------------------------------------------------------

    async def connect(self) -> None:
        """Connect now. Raises `RhxUnavailable`, whose message names the click."""
        async with self._connecting:
            if self._client.connected:
                return
            await self._client.connect()
            await self._after_connect()

    async def disconnect(self) -> None:
        if self._run_open:
            raise IntanNotReady(
                "A recording Ephymeris started is still open. Switch Group or End the "
                "session to close it out first."
            )
        self._close_streams()
        await self._client.close()
        self._recording = None
        self._set_state("disconnected", None)
        await self.publish()

    async def _after_connect(self) -> None:
        await self._refresh_info()
        recording = self._recording
        if self._run_open and recording is not None:
            if self._run_mode != "record":
                self._trouble(_stopped_in_rhx(self._run_mode))
            else:
                writes = await self._try_adopt()
                # Unless End closed the run, or something else confirmed it, during the read.
                if not writes and self._recording is recording and not self._run_confirmed:
                    self._trouble(_not_this_run(writes, recording))
        elif self._state in ("disconnected", "error"):
            self._recording = None
            self._set_state("idle", None)
        await self._send_owed_stop()
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
            await self._read_clock()
            await self._send_owed_stop()
        except RhxError as exc:
            # A socket that is still open but did not answer: allow one.
            if self._client.connected:
                self._silent_polls += 1
                if self._silent_polls < SILENT_POLLS:
                    return
            await self._lost(str(exc))
            await self.publish()
            return
        if (
            self._state in ("recording", "stopping")
            and self._run_confirmed
            and self._run_mode != "record"
        ):
            # Stop pressed in RHX -- during End's grace too, or a Record
            # pressed after it would be stopped as ours.
            self._run_confirmed = False
            self._trouble(_stopped_in_rhx(self._run_mode))
        elif self._run_open and not self._run_confirmed and self._run_mode == "record":
            await self._try_adopt()  # a stamp unread at the reconnect: try again
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
        if self._run_open:
            self._run_confirmed = False
        if self.is_recording:
            # `stopping` survives while End waits on boxes: End now stays.
            self._trouble(
                f"Lost contact with RHX ({why}) RHX keeps recording on its own; "
                "reconnecting. The behavior session is unaffected."
            )
        elif self._run_open:
            pass  # already `error`, stopped from RHX: still a run to close out
        elif self._stop_owed is not None:
            # Still `error`, still saying a stop is owed: that outlives the link.
            self._recording = None
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
        *,
        confirmation: int | None = None,
    ) -> None:
        """Set RHX up for this group's recording. `confirmation` is the mapping
        confirmation the boxes in `config` were read from: a recording only
        starts for that one (`refuse_unless_ready`)."""
        if self._run_open:
            raise IntanNotReady("A recording is already running.")
        if not self._client.connected:
            await self.connect()
        client = self._client

        await self._refresh_info()
        await self._send_owed_stop()
        if self._run_mode == "record" or self._run_mode == "trigger":
            raise IntanNotReady("RHX is already recording. Stop it in RHX first.")
        if self._run_mode == "run":
            # Left running for a look at the signals, almost always. Every
            # saving parameter is ignored while the board runs, so stop it.
            await client.set_run_mode("stop")
            self._run_mode = "stop"

        plan = self._plan(session_id, group_id, config, base_filename)
        plan.confirmation = confirmation
        plan.threshold = dict(config.get("threshold") or {}) or None
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
            f"set tcpnumberdatablocksperwrite {BLOCKS_PER_WRITE}",
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

    async def measure_impedance(self, directory: str, base_filename: str) -> tuple[ImpedanceFile, Path]:
        """Measure every channel's impedance and read RHX's CSV of them back
        (`RECORDING.md#impedance-tracking`). RHX must be stopped: one left in
        Run is stopped, as `configure` does; one recording is refused.

        RHX saves the file itself (`SaveImpedance`); it goes in `directory`,
        beside the recording, and stays there as the durable copy.
        """
        if self._run_open:
            raise IntanNotReady("A recording is running; impedances are measured before it starts.")
        if not self._client.connected:
            await self.connect()
        client = self._client
        await self._refresh_info()
        if self._run_mode in ("record", "trigger"):
            raise IntanNotReady("RHX is recording. Stop it in RHX first.")
        if self._run_mode == "run":
            await client.set_run_mode("stop")
            self._run_mode = "stop"
        if not self._info.get("headstagePresent"):
            raise IntanNotReady("RHX sees no headstage to measure.")

        folder = Path(directory)
        target = folder / f"{base_filename}.csv"
        try:
            await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(target.unlink, missing_ok=True)
        except OSError as exc:
            raise IntanNotReady(f"Couldn't prepare {folder}: {exc.strerror or exc}") from exc

        await client.set("desiredimpedancefreqhertz", IMPEDANCE_FREQ_HZ)
        await client.set("impedancefilename.path", rhx_path(str(folder)), verify=True)
        await client.set("impedancefilename.basefilename", base_filename, verify=True)
        # RHX measures before it reads on, so this returns when it is done.
        await client.execute("measureimpedance", timeout_s=MEASURE_TIMEOUT_S)
        await client.execute("saveimpedance")
        text = await self._wait_for_file(target)
        try:
            return parse_csv(text), target
        except ValueError as exc:
            raise IntanNotReady(f"RHX's impedance file {target.name} couldn't be read: {exc}") from exc

    async def _wait_for_file(self, path: Path) -> str:
        """The CSV, once it is there and whole. At once when writes are
        confirmed; otherwise polled, since nothing says when RHX is done."""
        loop = asyncio.get_running_loop()
        # Unconfirmed, the measurement itself may still be running.
        wait = 2.0 if self._client.confirms_writes else MEASURE_TIMEOUT_S + IMPEDANCE_FILE_WAIT_S
        deadline = loop.time() + wait
        while True:
            try:
                text = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
                if text.strip() and text.endswith("\n"):  # RHX ends every row with one
                    return text
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise IntanNotReady(f"Couldn't read {path}: {exc.strerror or exc}") from exc
            if loop.time() >= deadline:
                raise IntanNotReady(
                    f"RHX did not save the impedances to {path}. Check that RHX can write there."
                )
            await asyncio.sleep(0.25)

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
        never started). Refuses nothing; a started recording is left alone."""
        if self._run_open:
            return
        if self._recording is not None:
            self._recording = None
            self._close_streams()
            if self._state == "configured":
                self._set_state("idle", None)
            self._loop.create_task(self.publish())

    def refuse_unless_ready(self, session_id: str, group_id: str, confirmation: int) -> None:
        """Raise unless this group's recording is set up for this mapping
        confirmation and RHX can be told to start it, or is recording it
        already. The refusal says what is actually wrong: a lost link sends the
        operator to RHX, not back to a Recording step they finished."""
        r = self._recording
        ours = r is not None and r.session_id == session_id and r.group_id == group_id
        if ours and self._state == "recording":
            return
        if ours and self._state == "configured":
            if r.confirmation == confirmation:
                return
            # RHX holds the notes, channels and digital inputs of the boxes
            # the earlier mapping had (`RECORDING.md#record-step`).
            raise IntanNotReady(
                "The mapping was confirmed again after the Record step set this "
                "recording up, so RHX is set up for the old boxes. Go through the "
                "Record step again."
            )
        if ours and self._run_open and not self._client.connected:
            raise RhxUnavailable(
                "Lost contact with RHX, which keeps recording this group on its own. "
                "No box can start until it is back: Ephymeris is reconnecting, and if it "
                "does not, open Network → Remote TCP Control in RHX and press Connect."
            )
        if ours and self._run_open:
            raise IntanNotReady(
                "RHX is no longer recording this group — it was stopped from RHX itself. "
                "Switch Group or End the session to close the recording out."
            )
        if not self._client.connected:
            raise RhxUnavailable(
                "RHX is not reachable, so this group's recording cannot start. Once it "
                "is connected again, set the recording up on the Recording step."
            )
        raise IntanNotReady(
            "This is a recording session, but no recording is set up for this "
            "group. Finish the Recording step first."
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
        self._run_confirmed = True
        self._set_state("recording", None)
        await self.publish()
        await asyncio.sleep(self._pre_roll_s)

    async def _abort_start(self) -> None:
        try:
            await self._client.set_run_mode("stop")
        except RhxError:
            pass

    def note_waiting(self, boxes: list[int]) -> None:
        """Graceful-end progress from the runner: who is still mid-trial.

        `stopping` whenever a run is open, so Mission Control offers End now
        even with the link lost; the message saying why RHX is in trouble
        stays."""
        self._waiting_on = sorted(boxes)
        if self._run_open and boxes and self._state != "stopping":
            self._set_state("stopping", self._message)
        self._loop.create_task(self.publish())

    async def stop_recording(self) -> dict[str, Any] | None:
        """Stop saving and hand back the run's record. NEVER RAISES, and is
        bounded: with RHX unreachable the run is still handed back, and the
        stop is owed until RHX answers again (`_send_owed_stop`).

        Only a CONFIRMED run is stopped outright. One whose link was lost, or
        that RHX was seen not writing, goes through the owed-stop check, which
        stops RHX only on this run's own file.
        """
        recording = self._recording
        if recording is None or recording.started_at is None:
            self.release()
            return None
        self._waiting_on = []
        message: str | None = None
        owed = False
        attempted = self._run_confirmed and self._client.connected
        if attempted:
            self._set_state("stopping", None)
            await self.publish()
            try:
                await asyncio.sleep(self._post_roll_s)
                await self._stop_rhx()
            except Exception as exc:  # noqa: BLE001 - the animals are done; never raise
                log.error("couldn't stop the RHX recording: %s", _why(exc))
                owed = True
                message = _owed_message(_why(exc))
        else:
            owed = True
            message = _owed_message(
                "RHX is not reachable" if not self._client.connected
                else "RHX was not seen writing this run"
            )
        recording.ended_at = _now()
        self._recording = None
        self._run_confirmed = False
        self._close_streams()
        self._force_stop.clear()
        if owed:
            self._stop_owed = recording
            self._set_state("error", message)
            # Not after a stop that just failed: that already cost its bound,
            # and the next poll retries. An unconfirmed run is checked now.
            if not attempted and self._client.connected:
                try:
                    self._run_mode = await self._client.run_mode()
                except RhxError:
                    pass  # still owed; the next poll tries
                else:
                    await self._send_owed_stop()
        else:
            self._set_state("idle" if self._client.connected else "disconnected", None)
        await self.publish()
        return recording.to_json()

    async def _stop_rhx(self) -> None:
        """`set runmode stop`, bounded by `stop_timeout_s`. Raises on failure."""
        await asyncio.wait_for(self._client.set_run_mode("stop"), self._stop_timeout_s)
        self._run_mode = "stop"

    async def _rhx_writes(self, recording: Recording) -> bool | None:
        """Whether RHX's active file is this run's (`Filename.ActiveFileTimestamp`,
        read at its start). False on another file, or when no stamp was read
        at the start, so it never can be told; None when the read failed, which
        a later poll may answer."""
        if recording.file_timestamp is None:
            return False
        try:
            stamp = (await self._client.get("filename.activefiletimestamp")).strip()
        except RhxError:
            return None
        return stamp == recording.file_timestamp

    async def _try_adopt(self) -> bool | None:
        """Pick an open run back up if RHX is writing its file (`_rhx_writes`'s
        answer is returned). Never adopted, a recording restarted by hand is
        never stopped as ours. Nothing is picked up once End has closed the run,
        or something else confirmed it, during the stamp read."""
        recording = self._recording
        if recording is None:
            return False
        writes = await self._rhx_writes(recording)
        if writes and self._recording is recording and not self._run_confirmed:
            self._run_confirmed = True
            self._set_state("stopping" if self._waiting_on else "recording", None)
            await self._open_streams()
        return writes

    async def _send_owed_stop(self) -> None:
        """Stop the run an earlier stop could not reach, once RHX answers.

        Only while RHX is still in Record ON THAT RUN'S FILE. Stopped by hand
        meanwhile settles the debt; another file, or one that can't be read,
        is a recording someone may want, so it is left alone and said so --
        `configure` then refuses it as "already recording". Never while a run
        of ours is open: `configure` sends the owed stop before one can start.
        """
        owed = self._stop_owed
        if owed is None or self._run_open or not self._client.connected:
            return
        if self._run_mode not in ("record", "trigger"):
            self._stop_owed = None
            if self._state == "error":
                self._set_state("idle", None)
            return
        writes = await self._rhx_writes(owed)
        if writes is None:
            # The read failed: no verdict. Still owed; the next poll asks again.
            self._set_state(
                "error",
                "RHX is still recording, and Ephymeris could not read which file, so it "
                "has left it alone for now and asks again at the next poll. Stop it from "
                "RHX to stop it sooner.",
            )
            return
        if not writes:
            self._stop_owed = None
            self._set_state(
                "error",
                "RHX is recording, but "
                + ("not the run whose session ended" if owed.file_timestamp is not None
                   else "no file stamp was read when the ended run started, so nothing "
                   "tells them apart")
                + ". Ephymeris left it alone; stop it from RHX if it should not be running.",
            )
            return
        try:
            await self._stop_rhx()
        except Exception as exc:  # noqa: BLE001 - still owed; the next poll retries
            log.error("couldn't send the owed RHX stop: %s", _why(exc))
            if not self._run_open:
                self._set_state(
                    "error",
                    "RHX is still recording a run whose session has ended, and Ephymeris "
                    f"could not stop it ({_why(exc)}). Stop it from RHX.",
                )
            return
        log.info("sent the RHX stop an unreachable End owed")
        self._stop_owed = None
        if not self._run_open:
            self._set_state(
                "idle",
                "Stopped the RHX recording a session ended while RHX was out of reach.",
            )

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

    def box_started(self, box: int, animal: str, tick_pulsed: bool = False) -> None:
        """Thread-safe. The Mega's clock restarts at START, so the box gets a
        fresh matcher -- an anchor carried over would be measured against a
        clock that no longer exists. `tick_pulsed`: the board announced one
        pulse per tick that strobes (`SYNC=TICK`), not one per strobe."""
        self._loop.call_soon_threadsafe(self._box_started, box, animal, tick_pulsed)

    def _box_started(self, box: int, animal: str, tick_pulsed: bool) -> None:
        recording = self._recording
        if recording is None or box not in recording.boxes or not self.is_recording:
            return
        self._matchers[box] = EdgeMatcher(float(recording.sample_rate), tick_pulsed=tick_pulsed)
        self._matched[box] = 0
        self._runs[box] = _RunCount(self._loop.time(), self._samples_seen)
        self._loop.create_task(self._livenote(f"BOX{box} START {animal}"))

    def box_ended(self, box: int, animal: str, reason: str) -> RunSpikes | None:
        """On the loop, as the run is finalized. Returns the run's spike counts
        for every site the box records, or None when it was not counted (a
        behavior-only box, or one started before the recording)."""
        recording = self._recording
        if recording is not None and box in recording.boxes and self.is_recording:
            self._loop.create_task(self._livenote(f"BOX{box} END {animal} ({reason})"))
        run = self._runs.pop(box, None)
        if run is None or recording is None or box not in recording.boxes:
            return None
        return RunSpikes(
            counts={name: run.counts.get(name, 0) for name in recording.boxes[box].channels},
            counted_seconds=round((self._samples_seen - run.samples_at_start) / recording.sample_rate, 3),
            run_seconds=round(self._loop.time() - run.started, 3),
            threshold=recording.threshold,
        )

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
            return  # no sync line to match against (module docstring)
        self._take(box, matcher.add_strobe(code, ms))

    def _take(self, box: int, events: list) -> None:
        matched = sum(1 for event in events if event.sample is not None)
        if matched:
            self._matched[box] = self._matched.get(box, 0) + matched

    # --- data sockets -----------------------------------------------------

    def _reset_live(self, plan: Recording) -> None:
        self._detectors = {b: EdgeDetector(p.digital_in) for b, p in plan.boxes.items()}
        self._matchers, self._matched = {}, {}
        self._runs = {}
        self._box_of = {name: b for b, p in plan.boxes.items() for name in p.channels}
        self._fired, self._fired_lag = {}, {}
        self._clock = SampleClock(float(plan.sample_rate))

    def _layout(self) -> FrameLayout:
        """Fixed for the recording: the digital-input word, nothing else."""
        return FrameLayout(digital_in=True)

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
        self._samples_seen += len(stamps)
        if block.digital_in is not None and not self.synthetic:
            for box, detector in self._detectors.items():
                edges = detector.feed(stamps, block.digital_in)
                matcher = self._matchers.get(box)
                if edges and matcher is not None:
                    self._take(box, matcher.add_edges(edges))

    async def _read_spikes(self, reader: asyncio.StreamReader) -> None:
        parser = SpikeParser()
        try:
            while data := await reader.read(1 << 16):
                arrived = self._loop.time()
                for spike in parser.feed(data):
                    self._count_spike(spike.channel, spike.timestamp, arrived)
        except (OSError, asyncio.CancelledError):
            return
        finally:
            self._live = False

    # --- live firing map ---------------------------------------------------

    def probe_map_for(self, box: int) -> dict[str, Any] | None:
        recording = self._recording
        if recording is None or box not in recording.boxes:
            return None
        return recording.boxes[box].probe_map

    async def _read_clock(self) -> None:
        """One `currenttimestamp` read per poll while RHX acquires and the
        sockets are open: what spike lags are measured against."""
        if self._clock is None or not self._live or (self._run_mode or "") not in ("run", "record"):
            return
        reply = await self._client.get("currenttimestamp")
        try:
            self._clock.read(int(reply), self._loop.time())
        except ValueError:
            log.debug("unreadable currenttimestamp %r", reply)

    def _count_spike(self, channel: str, sample: int, arrived: float) -> None:
        box = self._box_of.get(channel)
        if box is None:
            return
        counts = self._fired.setdefault(box, {})
        counts[channel] = counts.get(channel, 0) + 1
        run = self._runs.get(box)
        if run is not None:
            run.counts[channel] = run.counts.get(channel, 0) + 1
        lag = self._clock.lag_ms(sample, arrived) if self._clock is not None else None
        if lag is not None and lag > self._fired_lag.get(box, float("-inf")):
            self._fired_lag[box] = lag

    async def _spikes_loop(self) -> None:
        while True:
            await asyncio.sleep(SPIKES_PUBLISH_S)
            try:
                await self._publish_spikes()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must not die
                log.exception("spike publish failed")

    async def _publish_spikes(self) -> None:
        from ..protocol import Evt, event

        if not self._fired:
            return
        fired, lags = self._fired, self._fired_lag
        self._fired, self._fired_lag = {}, {}
        sent_at = time.time() * 1000.0
        for box, counts in sorted(fired.items()):
            lag = lags.get(box)
            await self._broadcast(
                event(
                    Evt.INTAN_SPIKES,
                    {"box": box, "counts": counts,
                     "lagMs": None if lag is None else round(lag, 1), "sentAt": sent_at},
                )
            )


def _b(value: Any) -> str:
    return "true" if value else "false"


def _note(text: str) -> str:
    """A note is one `set` value: no `;` (it would end the command)."""
    return (text.replace(";", ",").replace("\n", " ").strip() or "-")[:200]


def _owed_message(why: str) -> str:
    return (
        f"Ephymeris could not stop the RHX recording ({why}). It stops it as soon as "
        "RHX answers again, if RHX is still writing this run. Stop it from RHX to stop "
        "it sooner; the data it has written is safe."
    )


def _not_this_run(writes: bool | None, recording: Recording) -> str:
    if writes is None:
        return (
            "RHX is recording, but Ephymeris could not read which file, so the run is not "
            "picked back up yet; it asks again at the next poll. The behavior session is "
            "unaffected."
        )
    if recording.file_timestamp is None:
        return (
            "RHX is recording, but no file stamp was read when this run started, so "
            "nothing tells it is this run; Ephymeris leaves it alone. The behavior "
            "session is unaffected."
        )
    return (
        "RHX is recording, but not this run (its file stamp changed) — it was "
        "restarted from RHX itself. Ephymeris leaves that recording alone. The behavior "
        "session is unaffected."
    )


def _stopped_in_rhx(run_mode: str | None) -> str:
    return (
        f"RHX is no longer recording (run mode is {run_mode!r}) — it was "
        "stopped from RHX itself. The behavior session is unaffected."
    )


def _why(exc: BaseException) -> str:
    """An exception as words. A timeout's own text is empty."""
    if isinstance(exc, asyncio.TimeoutError):
        return "RHX did not answer in time"
    return str(exc) or type(exc).__name__


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

"""A recorded run read back after the session (`RECORDING.md#event-psth`).

One animal's run document says where its recording is (`intan_path`,
`intan_recording`), which digital input its sync line reached and which
channels were its. From those and RHX's own files this builds:

  * the run's **events on the recording's clock** -- every strobe, named,
    placed by its sync edge, and assigned to its trial -- written once beside
    the session as `events/<run>.events.json` and `.mat` for the lab's own
    scripts and spike sorters. The app never reads it back: like every trial,
    it is re-derived from the files each time;
  * PSTHs around any named event, split by trial condition or outcome, with
    each site's responsiveness.

Loading is the expensive part (a recording's whole digital-input file), so a
loaded run is kept in memory, keyed by its files' sizes and times.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..analytics import reader
from ..analytics.stream.summary import trial_table_of
from ..sessions import run_document as rd
from ..sessions.writer import write_atomic
from ..tasks.profile import embedded_profile
from . import events as ev
from .rhx_files import RhxFileError, parse_spike_header, read_spikes, rising_edges
from .rhx_names import channel_names

log = logging.getLogger(__name__)

#: Loaded runs kept in memory: a session's animals, looked at one after another.
CACHED_RUNS = 6
#: Responsiveness compares this long before and after each event, at most.
RESPONSE_WINDOW_MS = 500


class NotRecorded(Exception):
    """The run has no recording this can read. The message says why, for the operator."""


@dataclass
class LoadedRun:
    run_path: Path
    folder: Path
    rate: float
    tick_pulsed: bool
    channels: list[str]
    alignment: ev.Alignment
    names: dict[int, str]
    trials: list[ev.TrialStart]
    #: Each event's trial index, parallel to `alignment.events`.
    event_trials: list[int | None]
    spikes: dict[str, Any]
    first_stamp: int
    last_stamp: int
    events_file: Path | None
    #: The run's own document already holds an alignment (`recording.sync`),
    #: so nothing is left for the pass that fills it (`intan/alignment.py`).
    filled: bool = True


def _strobes(document: dict[str, Any]) -> list[tuple[int, int]]:
    out = []
    for pair in rd.strobes_of(document) or []:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            code, ms = pair[0], pair[1]
            if isinstance(code, int) and isinstance(ms, int) and not isinstance(code, bool):
                out.append((code, ms))
    return out


def _trial_starts(document: dict[str, Any], strobes: list[tuple[int, int]]) -> list[ev.TrialStart]:
    """Each trial's start on the run's own ms clock. A replayed (spine) run's
    trials are timed on the board's clock already; a decoded one's from the
    run's earliest timestamp (`legacy/decode.py`), so that is added back."""
    profile = embedded_profile(document)
    table = trial_table_of(document, profile)
    if not table:
        return []
    origin = 0 if table.get("kind") == "replay" else min((ms for _, ms in strobes), default=0)
    starts = []
    for row in table.get("trials") or []:
        at = row.get("atMs")
        if isinstance(at, int):
            condition = row.get("rowName") or row.get("row")
            starts.append(ev.TrialStart(origin + at, str(condition) if condition else None, row.get("outcome")))
    return sorted(starts, key=lambda s: s.ms)


def _time_span(folder: Path) -> tuple[int, int]:
    path = folder / "time.dat"
    size = path.stat().st_size
    if size < 4:
        raise RhxFileError("time.dat is empty")
    with path.open("rb") as handle:
        first = int.from_bytes(handle.read(4), "little", signed=True)
        handle.seek(size - size % 4 - 4)
        last = int.from_bytes(handle.read(4), "little", signed=True)
    return first, last


def align_run(
    run_path: str | Path,
    names_fallback: Callable[[int], str | None] = lambda _c: None,
    *,
    need_spikes: bool = False,
) -> LoadedRun:
    """One recorded run placed on its recording's clock, with its events file
    written: THE alignment, shared by the first view of a run (`load_run`) and
    the pass a recording's end runs (`intan/alignment.py`), so the two can
    never disagree. Reads RHX's digital input and never its spikes, which only
    a PSTH needs. `NotRecorded` says why a run cannot be aligned."""
    path = Path(run_path)
    result = reader.read_run(path)
    if not result.ok or result.document is None:
        raise NotRecorded(f"The run's file could not be read: {result.detail or result.status}.")
    document = result.document
    recording = rd.recording_name_of(document)
    if not recording or not rd.recording_path_of(document):
        raise NotRecorded("This run was not recorded with Intan.")
    folder = Path(str(rd.recording_path_of(document))) / str(recording)
    if not folder.is_dir():
        raise NotRecorded(f"RHX's recording folder is not where the run says: {folder}")
    if need_spikes and not (folder / "spike.dat").is_file():
        raise NotRecorded(
            "No spike.dat beside the recording. Spikes are saved only in the "
            "“per signal type” and “per channel” formats, with Save spikes on."
        )
    digital_in = rd.recording_digital_in_of(document)
    channels = channel_names(rd.recording_channels_of(document))
    if not isinstance(digital_in, int) or not channels:
        raise NotRecorded("The run does not say which digital input or channels were its.")

    try:
        edges = rising_edges(folder, digital_in)
        rate = float(rd.recording_sample_rate_of(document) or _spike_rate(folder))
    except (RhxFileError, OSError) as exc:
        raise NotRecorded(f"RHX's files could not be read: {exc}") from exc

    strobes = _strobes(document)
    alignment = ev.align(strobes, edges, rate, tick_pulsed=rd.sync_of(document) == "tick")
    profile = embedded_profile(document)
    names = dict(profile.strobes) if profile is not None else {}
    for code, _ms in strobes:
        if code not in names and (name := names_fallback(code)):
            names[code] = name
    trials = _trial_starts(document, strobes)
    aligned = LoadedRun(
        run_path=path,
        folder=folder,
        rate=rate,
        tick_pulsed=rd.sync_of(document) == "tick",
        channels=channels,
        alignment=alignment,
        names=names,
        trials=trials,
        event_trials=[ev.trial_of(trials, e.ms) for e in alignment.events],
        spikes={},
        first_stamp=0,
        last_stamp=0,
        events_file=None,
        filled=rd.recording_sync_of(document) is not None,
    )
    aligned.events_file = _write_events(aligned)
    return aligned


def _spike_rate(folder: Path) -> float:
    """The sample rate RHX wrote into spike.dat, for a run that records none."""
    with (folder / "spike.dat").open("rb") as handle:
        return parse_spike_header(handle.read(1 << 16)).sample_rate


def load_run(run_path: str | Path, names_fallback: Callable[[int], str | None] = lambda _c: None) -> LoadedRun:
    """Everything a PSTH needs from one run, or `NotRecorded` saying why not:
    its alignment (`align_run`), then its spikes."""
    aligned = align_run(run_path, names_fallback, need_spikes=True)
    try:
        _header, spikes = read_spikes(aligned.folder / "spike.dat", set(aligned.channels))
        first, last = _time_span(aligned.folder)
    except (RhxFileError, OSError) as exc:
        raise NotRecorded(f"RHX's files could not be read: {exc}") from exc
    aligned.spikes, aligned.first_stamp, aligned.last_stamp = spikes, first, last
    return aligned


def events_path(run_path: Path) -> Path:
    """`<session folder>/events/<run file's stem>.events.json`."""
    return reader.session_folder_of(run_path) / "events" / f"{run_path.stem}.events.json"


def _write_events(run: LoadedRun) -> Path | None:
    """Best effort: a failure costs the file, never the PSTH."""
    target = events_path(run.run_path)
    payload = {
        "source": str(run.run_path),
        "recording": str(run.folder),
        "sampleRate": run.rate,
        "sync": {"matched": run.alignment.matched, "missed": run.alignment.missed, "stray": run.alignment.stray},
        "events": [
            {
                "code": e.code,
                "name": run.names.get(e.code),
                "ms": e.ms,
                "sample": e.sample,
                "trial": trial,
            }
            for e, trial in zip(run.alignment.events, run.event_trials)
        ],
        "trials": [{"ms": t.ms, "condition": t.condition, "outcome": t.outcome} for t in run.trials],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(target, json.dumps(payload, indent=1))
    except OSError as exc:
        log.warning("couldn't write %s: %s", target, exc)
        return None
    try:
        _write_mat(target.with_suffix("").with_suffix(".events.mat"), payload)
    except Exception as exc:  # noqa: BLE001 - scipy is fenced: the .mat is a convenience
        log.warning("couldn't write the events .mat beside %s: %s", target, exc)
    return target


def _write_mat(path: Path, payload: dict[str, Any]) -> None:
    import numpy as np
    import scipy.io

    events = payload["events"]
    nan = float("nan")
    data = {
        "source": payload["source"],
        "recording": payload["recording"],
        "sample_rate": float(payload["sampleRate"]),
        "event_code": np.asarray([e["code"] for e in events], dtype=np.float64),
        "event_ms": np.asarray([e["ms"] for e in events], dtype=np.float64),
        "event_sample": np.asarray([nan if e["sample"] is None else e["sample"] for e in events], dtype=np.float64),
        # 1-based, as MATLAB indexes; NaN before the first trial.
        "event_trial": np.asarray([nan if e["trial"] is None else e["trial"] + 1 for e in events], dtype=np.float64),
        "event_name": np.asarray([e["name"] or "" for e in events], dtype=object),
        "trial_ms": np.asarray([t["ms"] for t in payload["trials"]], dtype=np.float64),
        "trial_condition": np.asarray([t["condition"] or "" for t in payload["trials"]], dtype=object),
        "trial_outcome": np.asarray([t["outcome"] or "" for t in payload["trials"]], dtype=object),
    }
    write_atomic(path, lambda part: scipy.io.savemat(str(part), data, appendmat=False))


# --- the view -----------------------------------------------------------------


def psth_view(
    run: LoadedRun,
    code: int | None,
    *,
    pre_ms: int,
    post_ms: int,
    bin_ms: int,
    split: str,
    raster_channel: str | None,
) -> dict[str, Any]:
    """One event's PSTH for every site of the run, as the wire's `EventPsth`."""
    per_ms = run.rate / 1000.0
    pre, post, bin_ = int(pre_ms * per_ms), int(post_ms * per_ms), max(1, int(bin_ms * per_ms))
    available = _available(run)
    code = code if code is not None and any(a["code"] == code for a in available) else (
        available[0]["code"] if available else None
    )

    groups: dict[str, list[int]] = {}
    if code is not None:
        for event, trial in zip(run.alignment.events, run.event_trials):
            if event.code != code or event.sample is None:
                continue
            groups.setdefault(_label(run, trial, split), []).append(event.sample)
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] == "no trial", kv[0]))
    windows = {
        label: ev.whole_windows(samples, pre, post, run.first_stamp, run.last_stamp)
        for label, samples in ordered
    }
    respond = int(min(RESPONSE_WINDOW_MS, pre_ms, post_ms) * per_ms)
    every = sorted(t for ts in windows.values() for t in ts)
    sites = []
    for channel in run.channels:
        spikes = run.spikes.get(channel) or []
        response = ev.responsiveness(spikes, every, respond, run.rate) if respond > 0 else None
        sites.append(
            {
                "channel": channel,
                "counts": [ev.psth_counts(spikes, windows[label], pre, post, bin_) for label, _ in ordered],
                "deltaHz": None if response is None else round(response.delta_hz, 3),
                "t": None if response is None or response.t is None else round(response.t, 2),
                "responsive": "none" if response is None else response.verdict,
            }
        )
    rasters = None
    if raster_channel and raster_channel.upper() in run.channels:
        spikes = run.spikes.get(raster_channel.upper()) or []
        rasters = [ev.raster(spikes, windows[label], pre, post, per_ms) for label, _ in ordered]
    return {
        "runPath": str(run.run_path),
        "eventsFile": str(run.events_file) if run.events_file else None,
        "sync": {
            "matched": run.alignment.matched,
            "missed": run.alignment.missed,
            "stray": run.alignment.stray,
            "tickPulsed": run.tick_pulsed,
        },
        "events": available,
        "code": code,
        "preMs": pre_ms,
        "postMs": post_ms,
        "binMs": bin_ms,
        "responseMs": min(RESPONSE_WINDOW_MS, pre_ms, post_ms),
        "split": split,
        "groups": [{"label": label, "trials": len(windows[label])} for label, _ in ordered],
        "sites": sites,
        "rasterChannel": raster_channel.upper() if rasters is not None and raster_channel else None,
        "rasters": rasters,
    }


def _available(run: LoadedRun) -> list[dict[str, Any]]:
    """Every event code the run has, with how many were placed, by name."""
    counts: dict[int, list[int]] = {}
    for event in run.alignment.events:
        tally = counts.setdefault(event.code, [0, 0])
        tally[0] += 1
        tally[1] += event.sample is not None
    return [
        {"code": code, "name": run.names.get(code) or f"code {code}", "count": n, "placed": placed}
        for code, (n, placed) in sorted(counts.items(), key=lambda kv: (run.names.get(kv[0]) or "", kv[0]))
    ]


def _label(run: LoadedRun, trial: int | None, split: str) -> str:
    if split == "none":
        return "all"
    if trial is None:
        return "no trial"
    start = run.trials[trial]
    value = start.condition if split == "condition" else start.outcome
    return value or "unknown"


class OfflineRuns:
    """Loaded runs, kept while their files are unchanged. Thread-safe: loads
    run in worker threads (`asyncio.to_thread`)."""

    def __init__(self, names_fallback: Callable[[int], str | None] = lambda _c: None) -> None:
        self._names_fallback = names_fallback
        self._runs: OrderedDict[str, tuple[tuple, LoadedRun]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, run_path: str) -> LoadedRun:
        key = self._key(run_path)
        with self._lock:
            hit = self._runs.get(run_path)
            if hit is not None and hit[0] == key:
                self._runs.move_to_end(run_path)
                return hit[1]
        loaded = load_run(run_path, self._names_fallback)
        with self._lock:
            self._runs[run_path] = (self._key(run_path), loaded)
            while len(self._runs) > CACHED_RUNS:
                self._runs.popitem(last=False)
        return loaded

    def get_cached_filled(self, run_path: str) -> bool:
        """Whether the run as last loaded already held its alignment in its own
        document; True when it is not loaded, so nothing is assumed missing."""
        with self._lock:
            hit = self._runs.get(run_path)
        return hit[1].filled if hit is not None else True

    @staticmethod
    def _key(run_path: str) -> tuple:
        """The run's file and RHX's, by size and time: a change in any reloads."""
        stamps: list[Any] = []
        path = Path(run_path)
        try:
            stat = path.stat()
            stamps.append((stat.st_size, stat.st_mtime_ns))
            document = json.loads(path.read_text(encoding="utf-8"))
            folder = Path(str(rd.recording_path_of(document))) / str(rd.recording_name_of(document))
            for name in ("spike.dat", "digitalin.dat", "time.dat"):
                s = (folder / name).stat()
                stamps.append((s.st_size, s.st_mtime_ns))
        except (OSError, ValueError, TypeError):
            stamps.append(None)
        return tuple(stamps)

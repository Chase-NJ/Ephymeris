"""The spike export for Plexon Offline Sorter — `RECORDING.md#the-sort-export`.

Sorting stays in Offline Sorter (ADR 0009). Each recorded animal gets
`sort/<run>.spikes.mat`, holding the three variables the lab's own
`save_extracted_spikes.m` writes per port, so the sorter's import is set up as
it is now:

    spiketimes   K×1 cell, each n×1 double: spike times, seconds
    spikewaves   K×1 cell, each n×30 double: waveforms, µV, rows are spikes
    unique_ch    K×1 cell, each one whole native channel name (`A-016`)

K is the animal's channels that fired at least once, in RHX's own channel
order; a channel with no spikes is left out, since an empty cell breaks the
sorter's import. The lab's readers are the reference for every detail
(`Hart-Lab Vault/Python/Intan/ExtractIntanSpikes.py`), and a test compares
this file with theirs, value for value, on a real recording.

**The window is counted from the crossing**: the 30 samples from 6 before it
to 24 after, which are samples 25:54 of a snapshot that keeps 30 samples
before a detection, the part of the spike the lab has always sorted on. A
spike RHX flagged as an artifact (id 128) is kept, as the lab's scripts keep
it.

**Memory is bounded by the animal's own spikes.** `spike.dat` is read twice
in chunks, never whole: once to count each channel's spikes, once to fill
arrays of exactly that size (about 250 bytes a spike). `savemat` then holds
each variable two or three times over while it compresses it, so the peak is
about four times the arrays: 2.4 GB for the 2.36 million spikes of one
animal in the lab's 2.8-hour recording of April 2026, in 20 s.

numpy and scipy are imported on use only (`DATA.md#the-mat-mirror`).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from ..sessions import run_document as rd
from ..sessions.writer import write_atomic
from .rhx_files import RhxFileError, parse_spike_header
from .rhx_names import channel_names

log = logging.getLogger(__name__)

#: The waveform kept for sorting, counted from the threshold crossing.
SAMPLES_BEFORE = 6
SAMPLES_AFTER = 24

#: ADC counts to microvolts: µV = 0.195 × (count − 32768).
UV_PER_COUNT = 0.195
ADC_ZERO = 32768.0

#: The folder, beside a session's `behavior.json`, the exports are written to.
SORT_DIR = "sort"

#: Records read at a time: about 8 MB of a file with 60-sample snapshots.
CHUNK_RECORDS = 1 << 16


@dataclass(frozen=True)
class SortExport:
    """What one export did. `reason` says why nothing was written."""

    status: Literal["written", "skipped", "failed"]
    reason: str | None = None
    path: Path | None = None
    #: Channels with at least one spike, and spikes written.
    channels: int = 0
    spikes: int = 0


def sort_path(run_json: Path) -> Path:
    """Where a run's export goes: `<session folder>/sort/<run>.spikes.mat`."""
    return run_json.parent.parent / SORT_DIR / f"{run_json.stem}.spikes.mat"


def export_spikes(
    spike_path: Path,
    out_path: Path,
    channels: Iterable[str],
    *,
    chunk_records: int = CHUNK_RECORDS,
) -> SortExport:
    """Write `out_path` from RHX's `spike.dat`, for these native channels.

    Never raises: a file that cannot be read or written is a `failed` export
    with its reason, and a recording with nothing to sort is a `skipped` one.
    The file is whole or absent (`write_atomic`).
    """
    try:
        return _export(spike_path, out_path, list(channels), chunk_records)
    except RhxFileError as exc:
        return SortExport("failed", f"{spike_path.name} could not be read: {exc}")
    except OSError as exc:
        return SortExport("failed", f"{spike_path.name} could not be exported: {exc}")
    except Exception as exc:  # noqa: BLE001 - an export never costs anything but itself
        log.exception("the spike export of %s failed", spike_path)
        return SortExport("failed", f"the export failed: {exc!r}")


def _export(spike_path: Path, out_path: Path, channels: list[str], chunk_records: int) -> SortExport:
    import numpy as np
    import scipy.io

    with spike_path.open("rb") as handle:
        header = parse_spike_header(handle.read(1 << 16))
        before = header.samples_before
        after = header.snapshot_samples - before
        if before + after == 0:
            return SortExport("skipped", "the recording saved no spike snapshots, so there is "
                              "nothing to sort: spike.dat holds timestamps only")
        if before < SAMPLES_BEFORE or after < SAMPLES_AFTER:
            return SortExport(
                "skipped",
                f"each snapshot keeps {before} samples before a detection and {after} after; sorting "
                f"needs {SAMPLES_BEFORE} samples before and {SAMPLES_AFTER} after",
            )
        record = np.dtype([("name", "S5"), ("timestamp", "<i4"), ("spike_id", "u1"),
                           ("snapshot", "<u2", (before + after,))])
        window = slice(before - SAMPLES_BEFORE, before + SAMPLES_AFTER)
        # RHX's own channel order, as the lab's reader keeps it.
        wanted = {name.strip().upper() for name in channels}
        keys = [name.encode("latin-1") for name in header.native_names if name in wanted]

        def chunks():  # noqa: ANN202
            handle.seek(header.data_offset)
            while True:
                data = np.fromfile(handle, dtype=record, count=chunk_records)
                if data.size == 0:
                    return
                yield data

        counts = dict.fromkeys(keys, 0)
        for data in chunks():
            names, tallies = np.unique(data["name"], return_counts=True)
            for name, tally in zip(names.tolist(), tallies.tolist()):
                if name in counts:
                    counts[name] += tally
        fired = [key for key in keys if counts[key] > 0]
        if not fired:
            return SortExport("skipped", "no spikes were detected on this animal's channels")

        times = {key: np.empty((counts[key], 1), dtype=np.float64) for key in fired}
        waves = {key: np.empty((counts[key], SAMPLES_BEFORE + SAMPLES_AFTER), dtype=np.float64)
                 for key in fired}
        filled = dict.fromkeys(fired, 0)
        for data in chunks():
            for key in np.unique(data["name"]).tolist():
                if key not in filled:
                    continue
                rows = data[data["name"] == key]
                at, n = filled[key], rows.shape[0]
                times[key][at:at + n, 0] = rows["timestamp"].astype(np.float64) / header.sample_rate
                waves[key][at:at + n] = UV_PER_COUNT * (rows["snapshot"][:, window].astype(np.float64) - ADC_ZERO)
                filled[key] = at + n

    variables = {
        "spiketimes": _cell_column(np, [times[key] for key in fired]),
        "spikewaves": _cell_column(np, [waves[key] for key in fired]),
        "unique_ch": _cell_column(np, [key.decode("latin-1") for key in fired]),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_atomic(out_path, lambda part: scipy.io.savemat(
            str(part), variables, appendmat=False, do_compression=True))
    except BaseException:
        # A `sort/` this export made for nothing is not left behind.
        try:
            out_path.parent.rmdir()
        except OSError:
            pass
        raise
    return SortExport("written", None, out_path, len(fired), sum(counts[key] for key in fired))


def _cell_column(np: Any, items: list[Any]) -> Any:
    """K items as a K×1 object array, which `savemat` writes as a K×1 cell."""
    column = np.empty((len(items), 1), dtype=object)
    for k, item in enumerate(items):
        column[k, 0] = item
    return column


# --- one run, and a session's runs ----------------------------------------------- #

def export_run(run_json: Path, recording: str | None = None) -> SortExport | None:
    """Export one run's spikes beside its session files, from what its own
    document says: its recording's folder and its channels. Never raises.

    With `recording`, a run that is inside another recording (an earlier
    round's) is passed over, and None comes back."""
    try:
        document = rd.lifted(json.loads(run_json.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        return SortExport("failed", f"{run_json.name} could not be read: {exc}")
    except Exception as exc:  # noqa: BLE001 - not a run's document at all
        return SortExport("failed", f"{run_json.name} is not a run's document: {exc!r}")
    name, path = rd.recording_name_of(document), rd.recording_path_of(document)
    if recording is not None and name and name != recording:
        return None
    if not name or not path:
        return SortExport("skipped", "the run was not recorded with Intan")
    listed = rd.channels_of(document)
    natives = ([row.get("native") for row in listed if isinstance(row, dict)]
               if isinstance(listed, list) else channel_names(rd.recording_channels_of(document)))
    natives = [n for n in natives if isinstance(n, str)]
    if not natives:
        return SortExport("skipped", "the run does not say which channels were its")
    return export_spikes(Path(str(path)) / str(name) / "spike.dat", sort_path(run_json), natives)


def export_runs(run_files: Iterable[str | Path | None], recording: str | None = None) -> list[SortExport]:
    """Export each of these runs, logging what each did; with `recording`,
    only the runs inside that recording. One that fails or has nothing to
    export stops no other. Blocking; call it off the loop."""
    results = []
    for run_file in run_files:
        if not run_file:
            continue
        result = export_run(Path(run_file), recording)
        if result is None:
            continue
        if result.status == "written":
            log.info("spike export: wrote %s (%d channels, %d spikes)", result.path, result.channels, result.spikes)
        elif result.status == "failed":
            log.warning("spike export: nothing written for %s: %s", run_file, result.reason)
        else:
            log.info("spike export: nothing to write for %s: %s", run_file, result.reason)
        results.append(result)
    return results

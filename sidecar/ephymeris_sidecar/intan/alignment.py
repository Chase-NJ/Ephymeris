"""Alignment at session end — `RECORDING.md#alignment-at-session-end`.

Once RHX has closed a recording's files, each recorded run is aligned without
anyone opening Analytics: its events file is written, its `recording.sync`
gets the matched, missed and stray counts, and its trial table's `*_s`
columns get each event's time in seconds on the recording's clock.

**One alignment.** `offline.align_run` is what the first view of a run uses
too, so the two can never disagree; this module only writes what it found
into the run's own `.json` and `.mat`.

**A finished run's files are rewritten, carefully.** The `.json` is read, two
blocks are replaced (`recording.sync`, `trials`) and every other block is
written back as it was read, whole or not at all (`write_atomic`). The `.tsv`
is never opened. A run whose recording cannot be read is left exactly as
finalization wrote it, and the pass can be run again: it writes nothing for a
run that already holds this alignment.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Callable, Iterable

from ..analytics import reader
from ..analytics.stream.document import _pairs_of
from ..sessions import derived, matwriter
from ..sessions import run_document as rd
from ..sessions.writer import write_atomic
from . import events as ev
from . import offline

log = logging.getLogger(__name__)


def seconds_by_strobe(document: dict[str, Any], alignment: ev.Alignment, rate: float) -> dict[int, float]:
    """Each placed strobe's time on the recording's clock, in seconds, by its
    index in the run's stream (`document._pairs_of`'s indexing, which the
    trial table is read with). A strobe whose pulse never came is absent.

    The matcher hands events back as it settles them, not in stream order, so
    they are paired by code and board time, first come first.
    """
    samples: dict[tuple[int, int], deque[int | None]] = defaultdict(deque)
    for event in alignment.events:
        samples[(event.code, event.ms)].append(event.sample)
    out: dict[int, float] = {}
    for index, (code, ms) in enumerate(_pairs_of(document)):
        queue = samples.get((code, ms)) if ms is not None else None
        sample = queue.popleft() if queue else None
        if sample is not None:
            out[index] = sample / rate
    return out


def align_file(json_path: Path) -> dict[str, Any]:
    """Align one run and write what was found into its own files. Never raises.

    `status` is `aligned` (files written, listed under `written`), `current`
    (the files already hold this alignment), `skipped` (nothing to align) or
    `failed` (its recording could not be read; the files are untouched).
    """
    entry: dict[str, Any] = {"jsonPath": str(json_path), "status": "failed", "reason": None, "written": []}
    try:
        return _align(json_path, entry)
    except offline.NotRecorded as exc:
        entry["reason"] = str(exc)
    except OSError as exc:
        entry["reason"] = f"couldn't write {json_path.name}: {exc}"
    except Exception as exc:  # noqa: BLE001 - one run's failure is that run's entry
        log.exception("couldn't align %s", json_path)
        entry["reason"] = f"couldn't align it: {exc!r}"
    return entry


def _align(json_path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    try:
        document = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        entry["reason"] = f"{json_path.name} could not be read: {exc}"
        return entry
    if not isinstance(document, dict) or rd.unreadable_reason(document) is not None:
        entry.update(status="skipped", reason=f"{json_path.name} is not a run document this build reads")
        return entry
    if not rd.recording_name_of(document):
        entry.update(status="skipped", reason="the run was not recorded with Intan")
        return entry
    if not rd.is_version_2(document):
        # A flat file has no place for the counts, and is never rewritten in
        # another shape: its events file, at first view, is its alignment.
        entry.update(status="skipped", reason="a version-1 file is aligned when it is first viewed")
        return entry

    aligned = offline.align_run(json_path)
    counts = {"matched": aligned.alignment.matched, "missed": aligned.alignment.missed,
              "stray": aligned.alignment.stray}
    updated = rd.with_recording_sync(document, counts)
    rest = rd.without_trial_table(updated)
    stored = rd.trial_table_of(document)
    block = derived.derive(rest, seconds_by_strobe(rest, aligned.alignment, aligned.rate))
    if block is not None and derived.kept(stored, block) is None:
        updated = rd.with_trial_table(rest, block)
    # A table a newer replay derived is left alone, counts and all the rest written.

    if updated == document:
        entry["status"] = "current"
        return entry
    write_atomic(json_path, json.dumps(updated, indent=2))
    entry["written"].append(str(json_path))
    if aligned.events_file is not None:
        entry["written"].append(str(aligned.events_file))
    mat_path = reader.sibling_mat(reader.sibling_tsv(json_path))
    try:
        if matwriter.refusal(updated) is None:
            mat_path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(mat_path, lambda part: matwriter.savemat(str(part), updated))
            entry["written"].append(str(mat_path))
    except Exception as exc:  # noqa: BLE001 - the .mat never holds the .json back
        log.error("couldn't write %s: %s", mat_path, exc)
        entry["reason"] = f"couldn't write {mat_path.name}: {exc}"
    entry["status"] = "aligned"
    return entry


def align_runs(
    run_files: Iterable[str | Path | None],
    recording: str | None = None,
    *,
    stop: Callable[[], bool] = lambda: False,
) -> list[dict[str, Any]]:
    """Align each of these runs, logging what each did; with `recording`, only
    the runs inside that recording. `stop` is asked before each run: once it
    says so (a box has started), the rest are left for later. Blocking."""
    entries = []
    for run_file in run_files:
        if not run_file:
            continue
        path = Path(run_file)
        if recording is not None and _recording_of(path) not in (None, recording):
            continue
        if stop():
            entries.append({"jsonPath": str(path), "status": "skipped", "written": [],
                            "reason": "a box started running; it is aligned when first viewed"})
            continue
        entry = align_file(path)
        if entry["status"] == "failed":
            log.warning("alignment: %s left as it was: %s", path.name, entry["reason"])
        else:
            log.info("alignment: %s %s%s", path.name, entry["status"],
                     f" ({entry['reason']})" if entry["reason"] else "")
        entries.append(entry)
    return entries


def _recording_of(json_path: Path) -> str | None:
    """The recording a run says it is inside; None when its file cannot say."""
    try:
        document = json.loads(json_path.read_text(encoding="utf-8"))
        name = rd.recording_name_of(rd.lifted(document)) if isinstance(document, dict) else None
    except (OSError, ValueError):
        return None
    return str(name) if name else ""

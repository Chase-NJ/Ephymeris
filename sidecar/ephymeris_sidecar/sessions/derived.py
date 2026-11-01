"""A spine run's derived trial table, written into its `.json` and `.mat`
(`DATA.md#the-derived-trial-table`).

Finalization and recovery replay a spine run once (`analytics/stream/spine.py`'s
`replayed`) and write what it gives into the document as one block, last:

    "derived": {"status": "ok", "detail": null, "interp": 3, "replay_version": 1,
                "phases": [...], "trials": [{"index": 0, "at_ms": 0, ...}, ...]}

stamped with the `INTERP` the run was replayed under and `spine.REPLAY_VERSION`.
A diverged or unreplayable run gets the block with its status, why, and no
trials; a legacy or profile-less run gets none. **The app never reads it**:
`analytics/reader.py` drops it, and Analytics replays. Re-derive
(`rederive_cohort`) rewrites it, and nothing else, after the replay changes.

A trial row is written by walking `ReplayTrial`'s dataclass fields, so a column
added there is written here with no change. Its `.mat` class comes from each
field's type hint (`_kind`): a number is a `double` (null is `NaN`, never `[]`,
so `[trials.latency_ms]` stays one value per trial), a bool a `logical`, a
string `char` (null is `''`), a tuple of numbers a row vector, and a tuple of
dataclasses an N×1 struct array.

numpy is imported on use only (`DATA.md#the-mat-mirror`).
"""

from __future__ import annotations

import dataclasses
import functools
import json
import logging
import math
import types
import typing
from pathlib import Path
from typing import Any

from ..analytics import reader
from ..analytics.stream import spine
from ..analytics.stream import trial_table as tt
from ..tasks.profile import DERIVED_KEY

log = logging.getLogger(__name__)


# --- the block ------------------------------------------------------------------


def derive(document: dict[str, Any]) -> dict[str, Any] | None:
    """The derived block for a run's document, or None for a run replay does
    not describe: a legacy run, or one with no profile. Replays it once.

    A stored block in `document` is never read: the run is replayed afresh.
    """
    if not spine.is_spine_run(document):
        return None
    try:
        result = spine.replayed(document)
    except spine.SpineDecodeError as exc:
        interp = document.get("interp")
        return _block("unreplayable", str(exc), interp if _is_int(interp) else None, (), ())
    if result.divergence is not None:
        return _block("diverged", result.divergence.detail, result.interp, result.phases, ())
    return _block("ok", None, result.interp, result.phases, result.trials)


def with_derived(document: dict[str, Any]) -> dict[str, Any]:
    """`document` with its derived block as its last key, or with none.

    Never raises: a derivation that fails is logged and the document is
    returned without a block, so it can never cost a run its `.json`.
    Re-derive fills it in later.
    """
    out = {key: value for key, value in document.items() if key != DERIVED_KEY}
    try:
        block = derive(out)
    except Exception:  # noqa: BLE001 - a derivation never costs the run its files
        log.exception("couldn't derive the trial table of %s", document.get("rat"))
        return out
    if block is not None:
        out[DERIVED_KEY] = block
    return out


def _block(status: str, detail: str | None, interp: int | None, phases: Any, trials: Any) -> dict[str, Any]:
    return {
        "status": status,
        "detail": detail,
        "interp": interp,
        "replay_version": spine.REPLAY_VERSION,
        "phases": [str(p) for p in phases],
        "trials": [_plain(t) for t in trials],
    }


def _plain(value: Any) -> Any:
    """A dataclass as JSON values, field by field, by its own field names."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return value


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --- the .mat -------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Kind:
    """How one field is written to a `.mat`."""

    #: number | bool | text | numbers | record | records | json
    name: str
    #: For `record` and `records`: each field's name and kind.
    fields: tuple[tuple[str, _Kind], ...] = ()


def _kind(hint: Any) -> _Kind:
    """A field's `.mat` kind, from its type hint. `json` for anything else:
    written as JSON text rather than not at all (a test keeps it unused)."""
    origin, args = typing.get_origin(hint), typing.get_args(hint)
    if origin in (typing.Union, types.UnionType):
        present = [a for a in args if a is not type(None)]
        return _kind(present[0]) if len(present) == 1 else _Kind("json")
    if hint is bool:
        return _Kind("bool")
    if hint in (int, float):
        return _Kind("number")
    if hint is str:
        return _Kind("text")
    if dataclasses.is_dataclass(hint):
        return _Kind("record", fields_of(hint))
    if origin is tuple and len(args) == 2 and args[1] is Ellipsis:
        inner = _kind(args[0])
        if inner.name == "number":
            return _Kind("numbers")
        if inner.name == "record":
            return _Kind("records", inner.fields)
    return _Kind("json")


@functools.cache
def fields_of(cls: type) -> tuple[tuple[str, _Kind], ...]:
    """Each field of a dataclass, with its `.mat` kind."""
    hints = typing.get_type_hints(cls)
    return tuple((f.name, _kind(hints[f.name])) for f in dataclasses.fields(cls))


def to_matlab(block: dict[str, Any]) -> dict[str, Any]:
    """The derived block as `savemat` should write it: a scalar struct whose
    `trials` is an N×1 struct array (`struct2table(S.derived.trials)`)."""
    import numpy as np

    phases = block.get("phases") or []
    cells = np.empty((1, len(phases)), dtype=object)
    for i, phase in enumerate(phases):
        cells[0, i] = _mat(_Kind("text"), phase)
    return {
        "status": _mat(_Kind("text"), block.get("status")),
        "detail": _mat(_Kind("text"), block.get("detail")),
        "interp": _mat(_Kind("number"), block.get("interp")),
        "replay_version": _mat(_Kind("number"), block.get("replay_version")),
        "phases": cells,
        "trials": _mat(_Kind("records", fields_of(tt.ReplayTrial)), block.get("trials") or []),
    }


def _mat(kind: _Kind, value: Any) -> Any:
    import numpy as np

    if kind.name == "number":
        return math.nan if value is None else float(value)
    if kind.name == "bool":
        return bool(value)
    if kind.name == "text":
        text = "" if value is None else str(value)
        if any(ord(c) > 0xFFFF for c in text):
            # As `matwriter.to_matlab` refuses: savemat would size it wrongly.
            raise ValueError(f"{text!r} has a character outside the BMP, which savemat would size wrongly")
        return text
    if kind.name == "numbers":
        return np.asarray([math.nan if v is None else float(v) for v in value or []],
                          dtype=np.float64).reshape(1, -1)
    if kind.name == "record":
        row = value if isinstance(value, dict) else {}
        return {name: _mat(k, row.get(name)) for name, k in kind.fields}
    if kind.name == "records":
        rows = list(value or [])
        out = np.empty((len(rows), 1), dtype=[(name, object) for name, _ in kind.fields])
        for i, row in enumerate(rows):
            for name, k in kind.fields:
                out[name][i, 0] = _mat(k, row.get(name) if isinstance(row, dict) else None)
        return out
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


# --- Re-derive ------------------------------------------------------------------


def rederive_file(json_path: Path) -> dict[str, Any] | None:
    """Re-derive one run's block (`DATA.md#re-derive`), as a `RederivedRun`
    entry, or None for a file that is not a spine run (or does not parse).

    Rewrites the `.mat` and then the `.json` only when the stored block
    differs from what this build derives; every other key is written back as
    read. A write that fails leaves the run failed, to try again. The `.tsv`
    is never opened.
    """
    # Here, not at the top: both import this module.
    from . import matwriter
    from .writer import write_atomic

    try:
        document = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # a torn or unreadable file is Recover's, and the rescan reports it
    if not isinstance(document, dict) or not spine.is_spine_run(document):
        return None
    entry: dict[str, Any] = {"jsonPath": str(json_path), "status": "failed", "reason": None}
    rest = {key: value for key, value in document.items() if key != DERIVED_KEY}
    try:
        block = derive(rest)
    except Exception as exc:  # noqa: BLE001 - one run's failure is that run's entry
        log.exception("couldn't re-derive %s", json_path)
        entry["reason"] = f"couldn't replay it: {exc!r}"
        return entry
    if document.get(DERIVED_KEY) == block:
        entry["status"] = "current"
        return entry
    rewritten = {**rest, DERIVED_KEY: block}
    # The `.mat` first: were the `.json` rewritten past a `.mat` that failed,
    # the run would read as current from then on and the `.mat` keep the old
    # table. This way a failure leaves both as they were, to try again.
    mat_path = reader.sibling_mat(reader.sibling_tsv(json_path))
    try:
        mat_path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(mat_path, lambda part: matwriter.savemat(str(part), rewritten))
    except Exception as exc:  # noqa: BLE001 - scipy missing, a full disk, a value it can't write
        log.error("couldn't write %s: %s", mat_path, exc)
        entry["reason"] = f"couldn't write {mat_path.name}: {exc}"
        return entry
    try:
        write_atomic(json_path, json.dumps(rewritten, indent=2))
    except OSError as exc:
        entry["reason"] = f"couldn't write {json_path.name}: {exc}"
        return entry
    entry["status"] = "rewritten"
    return entry


def rederive_cohort(data_folder: str) -> dict[str, Any]:
    """Re-derive every spine run under one cohort's data folder, as the
    `RederiveResult` wire shape minus `cohortId`. Current runs are counted,
    not listed."""
    folder_exists = Path(data_folder).expanduser().is_dir()
    paths = reader.walk_session_files(data_folder) if folder_exists else []
    entries = [e for e in (rederive_file(p) for p in paths) if e is not None]

    def count(status: str) -> int:
        return sum(1 for e in entries if e["status"] == status)

    return {
        "scanned": len(entries),
        "rewritten": count("rewritten"),
        "current": count("current"),
        "failed": count("failed"),
        "entries": [e for e in entries if e["status"] != "current"],
        "dataFolder": data_folder,
        "folderMissing": not folder_exists,
    }

"""The `.mat` mirror of a session document (`DATA.md#the-mat-mirror`), via `scipy.io.savemat`.

What this module owns is the mapping from the document's Python values to the
MATLAB classes the lab's code expects, which `savemat` alone gets wrong in
three places:

- **Numbers are doubles.** `savemat` keeps a Python int as `int64`, and MATLAB
  integer arithmetic saturates and refuses to mix with doubles. Every number in
  the file, `ts_data` included, is a `double`, as it always has been.
- **An empty `ts_data` is `0×2`**, not the `0×0` an empty list becomes, so
  `size(ts_data, 2)` is 2 whether or not the board said anything.
- **Nothing is dropped or mis-sized silently.** `savemat` skips a name starting
  with `_` with only a warning, and sizes a char array in code points where
  MATLAB counts UTF-16 code units, so a character outside the BMP would yield
  a char array whose dimensions disagree with its data. Both raise here
  instead, for a top-level string such as an animal name. The fields that
  carry operator-written labels can't trip the second: the task profile is
  ASCII-escaped JSON, and the trial table escapes each such character the same way
  (`derived._bmp`).

scipy is imported on first use, never at module scope, so a broken install
costs the `.mat` and nothing else; `preload` takes that first-use cost at
startup instead of at the end of someone's run.
"""

from __future__ import annotations

import json
import logging
import warnings
from typing import Any

from . import derived, run_document

log = logging.getLogger(__name__)


def preload() -> None:
    """Import scipy now, off the session path. A failure is logged, not raised."""
    try:
        import scipy.io  # noqa: F401
    except Exception:  # noqa: BLE001 - the first savemat will report it properly
        log.exception("scipy.io failed to import; .mat files will not be written")


#: How `refusal` names a field to the operator.
_FIELD_NAMES = {"rat": "the animal name", "animal": "the animal name"}


def refusal(data: dict[str, Any]) -> str | None:
    """Why `data` can never be written to a `.mat`, on any build, or None.

    A string with a character outside the BMP, such as an animal name with an
    emoji: `to_matlab` refuses it rather than mis-size it. Top-level strings,
    and those in a version-2 document's value blocks.
    """
    for name, value in _values(data):
        if isinstance(value, str) and any(ord(c) > 0xFFFF for c in value):
            return f"{_FIELD_NAMES.get(name, repr(name))} can't be written to a .mat"
    return None


def _values(data: dict[str, Any]) -> list[tuple[str, Any]]:
    """Every `(name, value)` `to_matlab` writes as a scalar or a string."""
    out = list(data.items())
    if run_document.is_version_2(data):
        for block in run_document.VALUE_BLOCKS:
            if isinstance(data.get(block), dict):
                out.extend(data[block].items())
    return out


#: The fields of a version-2 block that are text, so one with no value is `''`
#: where a number's is `NaN` (`DATA.md#the-mat-mirror`): never `[]`, and never
#: a class that changes from one run's file to the next.
_TEXT_FIELDS = frozenset({
    "animal", "cohort", "session_id", "date", "started_at", "serial_port", "stop_reason",
    "sketch", "sync", "channel_set_hash", "path", "name", "port", "channels",
})


def to_matlab(data: dict[str, Any]) -> dict[str, Any]:
    """The document with every value converted to what `savemat` should write."""
    return _to_matlab(data, nulls=False)


def _to_matlab(data: dict[str, Any], *, nulls: bool) -> dict[str, Any]:
    """`to_matlab`; with `nulls`, for a version-2 block, where None is a value
    the run does not have."""
    import math

    import numpy as np

    table_key = run_document.trial_table_key(data)
    blocks = run_document.VALUE_BLOCKS if run_document.is_version_2(data) else ()
    out: dict[str, Any] = {}
    for name, value in data.items():
        if isinstance(value, dict) and name in blocks:
            # A version-2 block of plain values (`S.run.animal`, `S.params.<key>`):
            # a struct, each field by the same rules as a top-level one.
            out[name] = _to_matlab(value, nulls=True)
            continue
        if name == run_document.ODORS_KEY and blocks and isinstance(value, list):
            # The odors table (`DATA.md#the-odors-table`): an N×1 struct array,
            # one field per column, so `struct2table(S.odors)` is the table.
            out[name] = derived.odors_to_matlab(value)
            continue
        if name == run_document.IMPLANT_KEY and blocks:
            # The run's copy of the implant: a struct, its targets an N×1 struct
            # array. A null one is the same struct, empty, so the class holds.
            out[name] = derived.implant_to_matlab(value)
            continue
        if name == run_document.CHANNELS_KEY and blocks and isinstance(value, list):
            out[name] = derived.channels_to_matlab(value)
            continue
        if isinstance(value, dict) and nulls:
            # A block inside a block (`S.recording.sync.matched`): a struct too.
            out[name] = _to_matlab(value, nulls=True)
            continue
        if value is None and nulls:
            out[name] = "" if name in _TEXT_FIELDS else math.nan
        elif isinstance(value, bool):
            out[name] = value  # bool before int: a MATLAB `logical`
        elif isinstance(value, (int, float)):
            out[name] = float(value)
        elif isinstance(value, (list, tuple)):
            # The only array in the schema is ts_data: [[code, ts], …] → N×2.
            out[name] = np.asarray(value, dtype=np.float64).reshape(-1, 2)
        elif isinstance(value, dict) and name == table_key:
            # The run's trial table (`DATA.md#the-trial-table`): a
            # struct whose `trials` is an N×1 struct array, since this one is
            # read as a table.
            out[name] = derived.to_matlab(value)
            continue
        elif isinstance(value, dict):
            # Any other dict is the task profile snapshot (`DATA.md#the-embedded-task-profile`): a
            # deep, ragged tree nobody reads as a struct, so JSON text that
            # `jsondecode(...)` gives straight back. ASCII (json's default
            # `ensure_ascii`), so no label in it can trip the BMP check below.
            out[name] = json.dumps(value, sort_keys=True, separators=(",", ":"))
        else:
            # Strings, and a string rather than a failed write for anything else.
            out[name] = value if isinstance(value, str) else str(value)
        if isinstance(out[name], str) and any(ord(c) > 0xFFFF for c in out[name]):
            raise ValueError(
                f"{name!r} has a character outside the BMP, which savemat would size wrongly"
            )
    return out


def savemat(path: str, data: dict[str, Any]) -> None:
    import scipy.io
    from scipy.io.matlab import MatWriteWarning

    converted = to_matlab(data)
    with warnings.catch_warnings():
        warnings.simplefilter("error", MatWriteWarning)
        # Long field names: a parameter's key is a struct field in version 2,
        # and savemat's default caps those at 31 characters where MATLAB allows 63.
        scipy.io.savemat(path, converted, appendmat=False, long_field_names=True)

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
  instead. The task profile, the one field carrying operator-written labels,
  is ASCII-escaped JSON and can't trip the second.

scipy is imported on first use, never at module scope, so a broken install
costs the `.mat` and nothing else; `preload` takes that first-use cost at
startup instead of at the end of someone's run.
"""

from __future__ import annotations

import json
import logging
import warnings
from typing import Any

log = logging.getLogger(__name__)


def preload() -> None:
    """Import scipy now, off the session path. A failure is logged, not raised."""
    try:
        import scipy.io  # noqa: F401
    except Exception:  # noqa: BLE001 - the first savemat will report it properly
        log.exception("scipy.io failed to import; .mat files will not be written")


def to_matlab(data: dict[str, Any]) -> dict[str, Any]:
    """The document with every value converted to what `savemat` should write."""
    import numpy as np

    out: dict[str, Any] = {}
    for name, value in data.items():
        if isinstance(value, bool):
            out[name] = value  # bool before int: a MATLAB `logical`
        elif isinstance(value, (int, float)):
            out[name] = float(value)
        elif isinstance(value, (list, tuple)):
            # The only array in the schema is ts_data: [[code, ts], …] → N×2.
            out[name] = np.asarray(value, dtype=np.float64).reshape(-1, 2)
        elif isinstance(value, dict):
            # The task profile snapshot (`DATA.md#the-embedded-task-profile`): a
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
        scipy.io.savemat(path, converted, appendmat=False)

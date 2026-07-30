"""Minimal MATLAB Level-5 MAT-file writer — pure Python, no numpy/scipy.

`data.md` §4.3 names `scipy.io.savemat`, but scipy pulls in numpy and is
the single heaviest dependency the sidecar would carry — a real setup-error risk
for a non-technical lab and a burden on the eventual Windows packaging. Since the
session file needs only a handful of value shapes (an `N×2` double array plus
scalar strings / bools / ints), a small hand-written serializer covers it with
zero runtime dependencies. This deviation from §5.1 is recorded in that doc's
§11.

Format reference: the MAT-File Format spec (Level 5). Everything is written
little-endian; MATLAB and scipy both read that via the header's endian
indicator. Validated against `scipy.io.loadmat` during development.
"""

from __future__ import annotations

import struct
from datetime import datetime, timezone
from typing import Any

# --- data type codes (miXXX) ---------------------------------------------
_MI_INT8 = 1
_MI_UINT8 = 2
_MI_UINT16 = 4
_MI_INT32 = 5
_MI_UINT32 = 6
_MI_DOUBLE = 9
_MI_MATRIX = 14

# --- array class codes (mxXXX) -------------------------------------------
_MX_CHAR = 4
_MX_DOUBLE = 6
_MX_UINT8 = 9

_LOGICAL_FLAG = 0x02  # set in the array-flags byte for a MATLAB `logical`


def _pad8(data: bytes) -> bytes:
    """Pad to the 8-byte boundary every MAT data element must sit on."""
    remainder = len(data) % 8
    return data if remainder == 0 else data + b"\x00" * (8 - remainder)


def _element(mtype: int, data: bytes) -> bytes:
    """A full (non-compressed) data element: 8-byte tag + padded data."""
    return struct.pack("<ii", mtype, len(data)) + _pad8(data)


def _array_flags(mx_class: int, logical: bool = False) -> bytes:
    flags = _LOGICAL_FLAG if logical else 0
    class_and_flags = mx_class | (flags << 8)
    return _element(_MI_UINT32, struct.pack("<II", class_and_flags, 0))


def _dims(dimensions: tuple[int, ...]) -> bytes:
    return _element(_MI_INT32, struct.pack(f"<{len(dimensions)}i", *dimensions))


def _name(name: str) -> bytes:
    return _element(_MI_INT8, name.encode("ascii"))


def _matrix(name: str, mx_class: int, dimensions: tuple[int, ...], pr: bytes,
            logical: bool = False) -> bytes:
    body = (
        _array_flags(mx_class, logical)
        + _dims(dimensions)
        + _name(name)
        + pr
    )
    return _element(_MI_MATRIX, body)


def _double_scalar(name: str, value: float) -> bytes:
    pr = _element(_MI_DOUBLE, struct.pack("<d", float(value)))
    return _matrix(name, _MX_DOUBLE, (1, 1), pr)


def _logical_scalar(name: str, value: bool) -> bytes:
    pr = _element(_MI_UINT8, struct.pack("<B", 1 if value else 0))
    return _matrix(name, _MX_UINT8, (1, 1), pr, logical=True)


def _char_row(name: str, value: str) -> bytes:
    # MATLAB char arrays are 1×N of UTF-16 code units. Empty string → 1×0.
    units = value.encode("utf-16-le")
    pr = _element(_MI_UINT16, units)
    return _matrix(name, _MX_CHAR, (1, len(value)), pr)


def _double_matrix_2col(name: str, rows: list[tuple[float, float]]) -> bytes:
    """An N×2 double array, stored column-major as MATLAB expects.

    `ts_data` is `[[code, ts], …]` row-major in Python; MATLAB wants all of
    column 1 (codes) then all of column 2 (timestamps).
    """
    n = len(rows)
    col0 = struct.pack(f"<{n}d", *(float(r[0]) for r in rows))
    col1 = struct.pack(f"<{n}d", *(float(r[1]) for r in rows))
    pr = _element(_MI_DOUBLE, col0 + col1)
    return _matrix(name, _MX_DOUBLE, (n, 2), pr)


def _field(name: str, value: Any) -> bytes:
    """Serialize one top-level field, choosing the MAT class by Python type."""
    if isinstance(value, bool):
        return _logical_scalar(name, value)
    if isinstance(value, (int, float)):
        return _double_scalar(name, value)
    if isinstance(value, str):
        return _char_row(name, value)
    if isinstance(value, (list, tuple)):
        # The only array in the schema is ts_data: a list of [code, ts] pairs.
        pairs = [(float(p[0]), float(p[1])) for p in value]
        return _double_matrix_2col(name, pairs)
    # Fall back to a JSON-ish string rather than failing the whole write.
    return _char_row(name, str(value))


def _header() -> bytes:
    text = (
        f"MATLAB 5.0 MAT-file, written by Ephymeris "
        f"on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    header = text.encode("ascii")[:116].ljust(116, b" ")
    header += b"\x00" * 8  # subsystem data offset (unused)
    header += struct.pack("<H", 0x0100)  # version
    header += b"IM"  # endian indicator
    return header


def dumps(data: dict[str, Any]) -> bytes:
    """Serialize a flat dict of scalars + one `ts_data` array to MAT-5 bytes."""
    out = bytearray(_header())
    for name, value in data.items():
        out += _field(name, value)
    return bytes(out)


def savemat(path: str, data: dict[str, Any]) -> None:
    with open(path, "wb") as fh:
        fh.write(dumps(data))

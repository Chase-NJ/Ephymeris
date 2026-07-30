"""Pure-Python MAT-5 writer — `data.md` §4.3 (scipy-free deviation).

No scipy at runtime, so these assert the file's own structural invariants: a
valid 128-byte header, 8-byte-aligned elements, and correct dimensions/values
for the shapes the session schema uses. Compatibility with `scipy.io.loadmat`
was verified against a throwaway install during development.
"""

from __future__ import annotations

import struct

from ephymeris_sidecar.sessions import matwriter


def _read_header(blob: bytes) -> None:
    assert len(blob) >= 128
    # Version + endian indicator sit at fixed offsets.
    assert struct.unpack("<H", blob[124:126])[0] == 0x0100
    assert blob[126:128] == b"IM"
    # The first four bytes must be non-zero text, so a v4 reader won't misparse.
    assert blob[0:4] != b"\x00\x00\x00\x00"


def _elements(blob: bytes) -> list[tuple[int, bytes]]:
    """Walk the top-level data elements after the 128-byte header."""
    out: list[tuple[int, bytes]] = []
    offset = 128
    while offset < len(blob):
        mtype, nbytes = struct.unpack("<ii", blob[offset : offset + 8])
        data = blob[offset + 8 : offset + 8 + nbytes]
        out.append((mtype, data))
        padded = nbytes + (-nbytes % 8)
        offset += 8 + padded
    return out


def test_header_is_well_formed() -> None:
    _read_header(matwriter.dumps({"rat": "remy1"}))


def test_every_element_sits_on_an_eight_byte_boundary() -> None:
    blob = matwriter.dumps(
        {"rat": "remy1", "n_events": 3, "ts_data": [[221, 0], [246, 99]]}
    )
    offset = 128
    while offset < len(blob):
        assert offset % 8 == 0, f"element at {offset} is misaligned"
        _, nbytes = struct.unpack("<ii", blob[offset : offset + 8])
        offset += 8 + nbytes + (-nbytes % 8)
    assert offset == len(blob)


def test_one_matrix_element_per_field() -> None:
    blob = matwriter.dumps({"a": 1, "b": "x", "c": True})
    elements = _elements(blob)
    assert len(elements) == 3
    assert all(mtype == 14 for mtype, _ in elements)  # miMATRIX


def test_ts_data_is_stored_column_major_n_by_2() -> None:
    rows = [[221, 0], [222, 1000], [246, 3523555]]
    blob = matwriter.dumps({"ts_data": rows})
    (_, body) = _elements(blob)[0]

    # Sub-elements: array flags (16B), dims, name, then the double payload.
    # Dims sit right after the 16-byte array-flags element.
    dims_type, dims_len = struct.unpack("<ii", body[16:24])
    assert dims_type == 5  # miINT32
    dims = struct.unpack("<2i", body[24 : 24 + dims_len])
    assert dims == (3, 2)  # N×2

    # The payload is column-major: all codes, then all timestamps.
    doubles = struct.unpack("<6d", body[-48:])
    assert doubles == (221.0, 222.0, 246.0, 0.0, 1000.0, 3523555.0)


def test_a_bool_is_flagged_logical() -> None:
    blob = matwriter.dumps({"lazy": True})
    (_, body) = _elements(blob)[0]
    # Array flags element: type miUINT32(6), then class_and_flags uint32.
    ftype, _flen = struct.unpack("<ii", body[0:8])
    assert ftype == 6
    class_and_flags = struct.unpack("<I", body[8:12])[0]
    mx_class = class_and_flags & 0xFF
    flags = (class_and_flags >> 8) & 0xFF
    assert mx_class == 9  # mxUINT8_CLASS
    assert flags & 0x02  # logical bit set


def test_empty_ts_data_is_zero_by_two() -> None:
    blob = matwriter.dumps({"ts_data": []})
    (_, body) = _elements(blob)[0]
    dims = struct.unpack("<2i", body[24:32])
    assert dims == (0, 2)

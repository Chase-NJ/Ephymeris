"""The `.mat` mirror — `DATA.md#the-mat-mirror`.

Round-trips through `scipy.io.loadmat`/`whosmat`, pinning the MATLAB class and
shape of every value shape a session document carries: the parts `savemat`
would get wrong unaided are exactly what these guard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import scipy.io

from ephymeris_sidecar.sessions import matwriter


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "run.mat"
    matwriter.savemat(str(path), data)
    return path


def _classes(path: Path) -> dict[str, tuple[tuple[int, ...], str]]:
    return {name: (shape, cls) for name, shape, cls in scipy.io.whosmat(str(path))}


def test_every_number_is_a_double(tmp_path: Path) -> None:
    """`savemat` alone keeps a Python int as int64; MATLAB integer arithmetic
    saturates and won't mix with doubles."""
    path = _write(tmp_path, {"n_events": 3, "rate": 2.5, "big": 2**40})
    assert _classes(path) == {
        "n_events": ((1, 1), "double"),
        "rate": ((1, 1), "double"),
        "big": ((1, 1), "double"),
    }
    assert scipy.io.loadmat(str(path))["big"][0, 0] == float(2**40)


def test_a_bool_is_logical(tmp_path: Path) -> None:
    path = _write(tmp_path, {"lazy": True, "off": False})
    assert _classes(path) == {"lazy": ((1, 1), "logical"), "off": ((1, 1), "logical")}
    loaded = scipy.io.loadmat(str(path))
    assert (loaded["lazy"][0, 0], loaded["off"][0, 0]) == (1, 0)


def test_ts_data_is_n_by_2_doubles(tmp_path: Path) -> None:
    rows = [[221, 0], [222, 1000], [246, 3523555]]
    path = _write(tmp_path, {"ts_data": rows})
    assert _classes(path) == {"ts_data": ((3, 2), "double")}
    assert scipy.io.loadmat(str(path))["ts_data"].tolist() == rows


def test_empty_ts_data_is_zero_by_two(tmp_path: Path) -> None:
    """Not the 0×0 an empty list becomes, so `size(ts_data, 2)` is always 2."""
    path = _write(tmp_path, {"ts_data": []})
    assert _classes(path) == {"ts_data": ((0, 2), "double")}


def test_strings_round_trip(tmp_path: Path) -> None:
    path = _write(tmp_path, {"rat": "remy1", "note": "5 µL"})
    loaded = scipy.io.loadmat(str(path))
    assert (loaded["rat"][0], loaded["note"][0]) == ("remy1", "5 µL")


def test_a_nested_field_is_ascii_json_text(tmp_path: Path) -> None:
    """The task profile snapshot (`DATA.md#the-embedded-task-profile`) is the
    one nested value. `jsondecode` in MATLAB has to give it straight back, and
    an operator-written label outside the BMP must survive it: escaped, the
    text is ASCII, so its char dimensions can't disagree with its data."""
    profile = {"taskName": "GRGL 4-Odor \U0001F42D", "liveMetrics": [{"id": "p_correct_1"}]}
    path = _write(tmp_path, {"task_profile": profile})
    text = scipy.io.loadmat(str(path))["task_profile"][0]
    assert text.isascii()
    assert json.loads(text) == profile


def test_anything_else_is_written_as_text(tmp_path: Path) -> None:
    path = _write(tmp_path, {"missing": None})
    assert scipy.io.loadmat(str(path))["missing"][0] == "None"


def test_a_character_outside_the_bmp_refuses_rather_than_mis_sizing(tmp_path: Path) -> None:
    """`savemat` sizes a char array in code points; MATLAB counts UTF-16 code
    units. A file whose dimensions disagree with its data reads as truncated."""
    with pytest.raises(ValueError, match="outside the BMP"):
        _write(tmp_path, {"rat": "remy\U0001F42D"})


def test_a_name_savemat_would_drop_refuses_rather_than_vanishing(tmp_path: Path) -> None:
    with pytest.raises(Warning):
        _write(tmp_path, {"_private": 1})

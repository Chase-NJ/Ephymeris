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


# --- a version-2 document (`DATA.md#the-mat-mirror`) ---------------------------

V2 = {
    "schema_version": 2,
    "run": {"animal": "remy1", "cohort": "The Remy's", "box": 2, "session_id": "8O-Bdisc_09",
            "date": "2026-10-30", "run_of_day": 1, "started_at": "2026-10-30T11:29:26-05:00",
            "serial_port": "COM5", "stop_reason": "BF_END_SESSION received", "n_events": 2},
    "task": {"sketch": "GRGL 8-Odor EZ", "interp": 1, "trial_seed": 1987552345},
    "params": {"num_trials": 1000, "lazy_escalation": True, "reward_scale": 0.5, "mode": "easy"},
    "recording": {"path": "D:/rhx", "name": "0423_7", "port": "A", "channels": "A-016:A-031",
                  "digital_in": 1, "sample_rate": 30000},
    "ts_data": [[221, 0], [222, 1001]],
    "task_profile": {"taskName": "GRGL 8-Odor EZ"},
}


def _field(struct, name):  # noqa: ANN001, ANN202
    return struct[name][0, 0]


def test_a_version_2_document_is_a_struct_per_block(tmp_path: Path) -> None:
    path = _write(tmp_path, V2)
    classes = _classes(path)
    assert classes.pop("task_profile")[1] == "char"
    assert classes == {
        "schema_version": ((1, 1), "double"),
        "run": ((1, 1), "struct"),
        "task": ((1, 1), "struct"),
        "params": ((1, 1), "struct"),
        "recording": ((1, 1), "struct"),
        "ts_data": ((2, 2), "double"),
    }
    loaded = scipy.io.loadmat(str(path))
    assert json.loads(loaded["task_profile"][0]) == V2["task_profile"]
    assert loaded["ts_data"].tolist() == V2["ts_data"]


def test_a_version_2_blocks_fields_follow_the_same_class_rules(tmp_path: Path) -> None:
    loaded = scipy.io.loadmat(str(_write(tmp_path, V2)), mat_dtype=True)  # a logical reads as bool
    run, params, recording = loaded["run"], loaded["params"], loaded["recording"]
    assert list(run.dtype.names) == list(V2["run"]), "S.run's fields, in the document's order"
    # S.run.box and S.run.run_of_day are doubles; names and dates are chars.
    assert _field(run, "box").dtype == float and _field(run, "box")[0, 0] == 2.0
    assert _field(run, "run_of_day").dtype == float and _field(run, "n_events")[0, 0] == 2.0
    assert _field(run, "animal")[0] == "remy1" and _field(run, "date")[0] == "2026-10-30"
    assert _field(run, "started_at")[0] == "2026-10-30T11:29:26-05:00"
    # S.params.<key>: a number is a double, a bool a logical, a string a char.
    assert _field(params, "num_trials").dtype == float and _field(params, "num_trials")[0, 0] == 1000.0
    assert _field(params, "lazy_escalation").dtype == bool and _field(params, "lazy_escalation")[0, 0]
    assert _field(params, "reward_scale")[0, 0] == 0.5 and _field(params, "mode")[0] == "easy"
    assert _field(recording, "sample_rate")[0, 0] == 30000.0 and _field(recording, "name")[0] == "0423_7"


def test_a_fact_the_run_does_not_have_is_nan_or_empty_text_never_missing(tmp_path: Path) -> None:
    """A recovered run from before version 2 has no box, cohort or start time.
    Its struct keeps every field, in the class the field always has."""
    unknown = {**V2["run"], "cohort": None, "box": None, "date": None, "run_of_day": None,
               "started_at": None}
    run = scipy.io.loadmat(str(_write(tmp_path, {**V2, "run": unknown})))["run"]
    assert list(run.dtype.names) == list(V2["run"])
    for name in ("box", "run_of_day"):
        assert _field(run, name).dtype == float and str(_field(run, name)[0, 0]) == "nan", name
    for name in ("cohort", "date", "started_at"):
        assert _field(run, name).size == 0 and _field(run, name).dtype.kind == "U", name


def test_a_long_parameter_name_is_a_field_like_any_other(tmp_path: Path) -> None:
    """`savemat` caps a struct's field names at 31 characters unless told
    otherwise; a generated task's parameter keys run longer."""
    name = "block_b1_criterion_window_of_correct_trials"
    params = scipy.io.loadmat(str(_write(tmp_path, {**V2, "params": {name: 8}})))["params"]
    assert _field(params, name)[0, 0] == 8.0

"""What changed since an animal's previous run — `DATA.md#what-changed`."""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.logbook.diff import changes_for_runs, param_changes
from ephymeris_sidecar.protocol import validate
from ephymeris_sidecar.sessions.models import SessionAnimalRun
from ephymeris_sidecar.tasks.profile import params_hash
from tests.test_analytics_service import Rig


def run(
    rid: str,
    *,
    animal: str = "a1",
    box: int = 1,
    profile: str | None = "h1",
    config: dict | None = None,
    session: str = "s",
    sketch: str = "/lib/GRGL_2-Odor",
) -> SessionAnimalRun:
    return SessionAnimalRun(
        id=rid,
        session_id=session,
        animal_id=animal,
        box_number=box,
        sketch_path=sketch,
        started_at="2026-07-22T09:00:00+00:00",
        profile_hash=profile,
        config=config,
        params_hash=params_hash(config),
    )


NAMES = {"h1": "GRGL", "h2": "Shaping", "h1b": "GRGL"}


def test_a_first_run_has_nothing_to_compare() -> None:
    change = changes_for_runs([run("r1", config={"holdMs": 200})], NAMES)["r1"]
    assert change["first"] is True
    assert change["task"] == "GRGL"
    assert change["taskChange"] is None and change["boxChange"] is None
    assert change["params"] == []
    assert validate(("ref", "RunChange"), change) == []


def test_task_box_and_params_changes_are_each_reported() -> None:
    out = changes_for_runs(
        [
            run("r1", config={"holdMs": 200, "itiMs": 4000}),
            run("r2", box=3, profile="h2", config={"holdMs": 300, "rewardUl": 20}),
        ],
        NAMES,
    )
    change = out["r2"]
    assert change["previousRunId"] == "r1"
    assert change["taskChange"] == {"from": "GRGL", "to": "Shaping"}
    assert change["boxChange"] == {"from": 1, "to": 3}
    assert change["params"] == [
        {"key": "holdMs", "from": 200, "to": 300},
        {"key": "itiMs", "from": 4000, "to": None},
        {"key": "rewardUl", "from": None, "to": 20},
    ]
    assert validate(("ref", "RunChange"), change) == []


def test_a_revised_definition_of_the_same_task_is_a_change() -> None:
    out = changes_for_runs([run("r1", config={}), run("r2", profile="h1b", config={})], NAMES)
    assert out["r2"]["taskChange"] == {"from": "GRGL", "to": "GRGL"}


def test_unchanged_runs_report_nothing() -> None:
    out = changes_for_runs([run("r1", config={"a": 1}), run("r2", config={"a": 1})], NAMES)
    assert out["r2"]["params"] == [] and out["r2"]["taskChange"] is None


def test_unrecorded_parameters_are_unknown_not_changed() -> None:
    out = changes_for_runs([run("r1", config=None), run("r2", config={"a": 1})], NAMES)
    assert out["r2"]["paramsKnown"] is False
    assert out["r2"]["params"] == []


def test_animals_are_compared_only_with_themselves() -> None:
    out = changes_for_runs(
        [run("r1", animal="a1", config={"a": 1}), run("r2", animal="a2", config={"a": 2})],
        NAMES,
    )
    assert out["r2"]["first"] is True


def test_a_snapshotless_run_falls_back_to_its_sketch() -> None:
    out = changes_for_runs(
        [run("r1", profile=None, config={}), run("r2", profile=None, sketch="/lib/Other", config={})],
        NAMES,
    )
    assert out["r2"]["taskChange"] == {"from": "GRGL_2-Odor", "to": "Other"}


def test_param_values_compare_by_value_not_identity() -> None:
    assert param_changes({"a": [1, 2]}, {"a": [1, 2]}) == []
    assert param_changes({"a": 1}, {"a": 1.5}) == [{"key": "a", "from": 1, "to": 1.5}]


@pytest.fixture
def rig(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    database.connect()
    r = Rig(database, tmp_path)
    r.write_sketch()
    try:
        yield r
    finally:
        database.close()


def test_order_is_chronological_never_by_session_number(rig: Rig) -> None:
    """Session "10" on the 23rd follows "9" on the 22nd — as strings, "10" < "9"."""
    nine = rig.add_session("9", "2026-07-22")
    ten = rig.add_session("10", "2026-07-23")
    for sid, hold in ((ten, 300), (nine, 200)):
        rig.sessions.record_animal_run(
            SessionAnimalRun(
                id=f"r-{sid}",
                session_id=sid,
                animal_id="a1",
                box_number=1,
                sketch_path=str(rig.sketch),
                started_at="2026-07-22T09:00:00+00:00",
                config={"holdMs": hold},
                params_hash=params_hash({"holdMs": hold}),
            )
        )
    out = changes_for_runs(rig.sessions.runs_for_cohort(rig.cohort.id), {})
    assert out[f"r-{nine}"]["first"] is True
    assert out[f"r-{ten}"]["params"] == [{"key": "holdMs", "from": 200, "to": 300}]

"""An animal's implant — `DATA.md#implants`.

Entered once on the animal: a device, its targets (each a group of the
device's channels at one place in the brain) and the dated lowerings of its
drive. It lives in its own table, keyed by the animal's id, so nothing a
roster save, a removal or a move does to the `animals` rows can lose it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts import implants
from ephymeris_sidecar.cohorts.db import SCHEMA_VERSION, Database
from ephymeris_sidecar.cohorts.implants import ImplantError, depth_on, parse_channels, parse_implant
from ephymeris_sidecar.cohorts.models import ValidationError
from ephymeris_sidecar.protocol import validate_command_result
from tests.test_cohort_move import Lab, give_b


def target(name: str, channels: str, **edits) -> dict:  # noqa: ANN003
    return {"name": name, "region": "orbitofrontal cortex", "hemisphere": "left",
            "apMm": 3.2, "mlMm": 2.4, "dvMm": 4.6, "channels": channels, **edits}


def implant(**edits) -> dict:  # noqa: ANN003
    """The lab's custom 32-channel electrode: two bundles of 16, 3 mm apart."""
    return {
        "device": "custom 32-channel electrode",
        "surgeryDate": "2026-11-30",
        "probeMapPath": None,
        "targets": [target("OFC", "0-15"),
                    target("DMS", "16-31", region="dorsomedial striatum", apMm=0.2, dvMm=4.0)],
        "lowerings": [],
        **edits,
    }


# --- channels ------------------------------------------------------------------ #

@pytest.mark.parametrize(("spec", "channels"), [
    ("0-15", list(range(16))),
    ("16-31", list(range(16, 32))),
    ("0, 2,4", [0, 2, 4]),
    ("0-3,8,10-11", [0, 1, 2, 3, 8, 10, 11]),
    (" 7 ", [7]),
    ("5-5", [5]),
])
def test_a_range_and_a_list_both_name_channels(spec: str, channels: list[int]) -> None:
    assert parse_channels(spec) == channels


@pytest.mark.parametrize("spec", ["", " ", "a", "5-2", "-1", "1,1", "0-3,2", "1-", "1.5", "0-2000"])
def test_channels_that_name_nothing_or_one_twice_are_refused(spec: str) -> None:
    with pytest.raises(ImplantError):
        parse_channels(spec)


# --- validation ----------------------------------------------------------------- #

def test_a_whole_implant_is_kept_as_entered_with_its_lowerings_in_date_order() -> None:
    raw = implant(lowerings=[{"date": "2026-12-20", "mm": 0.5}, {"date": "2026-12-14", "mm": 0.25}])
    parsed = parse_implant(raw)
    assert parsed == {**raw, "lowerings": [{"date": "2026-12-14", "mm": 0.25},
                                           {"date": "2026-12-20", "mm": 0.5}]}
    assert parse_implant(parsed) == parsed
    assert parse_implant({**raw, "probeMapPath": "  C:/maps/a.xml "})["probeMapPath"] == "C:/maps/a.xml"


def test_two_targets_may_not_claim_one_channel() -> None:
    with pytest.raises(ImplantError, match="OFC and DMS both.*15"):
        parse_implant(implant(targets=[target("OFC", "0-15"), target("DMS", "15-31")]))
    assert parse_implant(implant(targets=[target("OFC", "0-15"), target("DMS", "16,18,20")]))


@pytest.mark.parametrize(("edits", "says"), [
    ({"device": " "}, "device"),
    ({"surgeryDate": "30/11/2026"}, "surgery date"),
    ({"targets": []}, "at least one target"),
    ({"targets": [target("", "0-15")]}, "name"),
    ({"targets": [target("OFC", "0-7"), target("ofc", "8-15")]}, "two targets called"),
    ({"targets": [target("OFC", "0-15", hemisphere="both")]}, "hemisphere"),
    ({"targets": [target("OFC", "0-15", dvMm="deep")]}, "DV"),
    ({"targets": [target("OFC", "0-15", apMm=float("nan"))]}, "AP"),
    ({"targets": [target("OFC", "x")]}, "channels"),
    ({"lowerings": [{"date": "2026-11-01", "mm": 0.25}]}, "before the surgery"),
    ({"lowerings": [{"date": "soon", "mm": 0.25}]}, "date"),
    ({"lowerings": [{"date": "2026-12-14", "mm": 0}]}, "distance"),
])
def test_an_implant_that_cannot_be_meant_says_why(edits: dict, says: str) -> None:
    with pytest.raises(ImplantError, match=says):
        parse_implant(implant(**edits))
    with pytest.raises(ImplantError):
        parse_implant("not an implant")


# --- depth ---------------------------------------------------------------------- #

def test_depth_on_a_date_is_the_surgery_depth_plus_every_lowering_by_then() -> None:
    """One drive carries the whole electrode, so a lowering moves every target."""
    entered = parse_implant(implant(lowerings=[{"date": "2026-12-14", "mm": 0.25},
                                               {"date": "2026-12-20", "mm": 0.5}]))
    ofc, dms = entered["targets"]
    assert depth_on(entered, ofc, "2026-12-01") == (4.6, "2026-11-30"), "the surgery set it"
    assert depth_on(entered, ofc, "2026-12-14") == (4.85, "2026-12-14"), "a lowering counts on its own day"
    assert depth_on(entered, ofc, "2026-12-19") == (4.85, "2026-12-14")
    assert depth_on(entered, ofc, "2026-12-25") == (5.35, "2026-12-20")
    assert depth_on(entered, dms, "2026-12-25") == (4.75, "2026-12-20")
    # Two lowerings on one day are one move of their sum; a raise is negative.
    twice = parse_implant(implant(lowerings=[{"date": "2026-12-14", "mm": 0.25},
                                             {"date": "2026-12-14", "mm": -0.125}]))
    assert depth_on(twice, twice["targets"][0], "2026-12-14") == (4.725, "2026-12-14")


# --- it persists, and travels with the animal ----------------------------------- #

@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "app" / "ephymeris.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def lab(db: Database, tmp_path: Path) -> Lab:
    """Cohort A: remy1, remy2 and slow1, each with runs; cohort B, empty."""
    return Lab(db, tmp_path)


def roster(lab: Lab, cohort_id: str | None = None) -> list[dict]:
    return [a.to_json() for a in lab.cohorts.get(cohort_id or lab.a.id).animals]


def implant_of(lab: Lab, animal_id: str, cohort_id: str | None = None) -> dict | None:
    return next(a["implant"] for a in roster(lab, cohort_id) if a["id"] == animal_id)


def give(lab: Lab, animal_id: str, value: dict | None) -> None:
    posted = [{**a, "implant": value} if a["id"] == animal_id else a for a in roster(lab)]
    lab.cohorts.update(lab.a.id, {"animals": posted})


def test_an_implant_is_saved_with_the_roster_and_read_back(lab: Lab) -> None:
    give(lab, "remy1", implant())
    assert implant_of(lab, "remy1") == implant()
    assert implant_of(lab, "remy2") is None
    cohort = lab.cohorts.get(lab.a.id).to_json()
    validate_command_result("cohorts.get", {"cohort": cohort})


def test_a_rename_and_a_roster_resave_keep_it(lab: Lab) -> None:
    give(lab, "remy1", implant())
    renamed = [{**a, "name": "Remy the First"} if a["id"] == "remy1" else a for a in roster(lab)]
    lab.cohorts.update(lab.a.id, {"animals": renamed})
    assert implant_of(lab, "remy1") == implant()
    # An older client's roster names no implant at all: nothing is cleared.
    bare = [{k: v for k, v in a.items() if k != "implant"} for a in roster(lab)]
    lab.cohorts.update(lab.a.id, {"animals": bare})
    lab.cohorts.update(lab.a.id, {"name": "A, renamed"})
    assert implant_of(lab, "remy1") == implant()


def test_posting_null_removes_it_and_posting_a_new_one_replaces_it(lab: Lab) -> None:
    give(lab, "remy1", implant())
    lowered = implant(lowerings=[{"date": "2026-12-14", "mm": 0.25}])
    give(lab, "remy1", lowered)
    assert implant_of(lab, "remy1") == lowered
    give(lab, "remy1", None)
    assert implant_of(lab, "remy1") is None


def test_an_implant_that_cannot_be_meant_is_refused_against_its_animal(lab: Lab) -> None:
    with pytest.raises(ValidationError) as refused:
        give(lab, "remy1", implant(targets=[target("OFC", "0-15"), target("DMS", "15-31")]))
    assert "both" in refused.value.errors["animal:remy1"]
    assert implant_of(lab, "remy1") is None, "nothing of a refused save lands"


def test_a_former_member_keeps_its_implant_and_brings_it_back(lab: Lab) -> None:
    give(lab, "slow1", implant())
    lab.cohorts.update(lab.a.id, {"animals": [a for a in roster(lab) if a["id"] != "slow1"]})
    [former] = [f for f in lab.cohorts.get(lab.a.id).former_animals if f.id == "slow1"]
    assert former.to_json()["implant"] == implant()

    restored = [*roster(lab), {"id": "slow1", "name": "slow1"}]
    lab.cohorts.update(lab.a.id, {"animals": restored})
    assert implant_of(lab, "slow1") == implant()


def test_an_animal_deleted_outright_takes_its_implant_with_it(lab: Lab, db: Database) -> None:
    """One with no run, adoption or note is not kept as a former member."""
    lab.cohorts.update(lab.a.id, {"animals": [*roster(lab), {"id": "typo", "name": "typo",
                                                              "implant": implant()}]})
    assert implant_of(lab, "typo") == implant()
    lab.cohorts.update(lab.a.id, {"animals": [a for a in roster(lab) if a["id"] != "typo"]})
    with db.read() as q:
        assert q.execute("SELECT COUNT(*) FROM implants WHERE animal_id = 'typo'").fetchone()[0] == 0


def test_a_new_cohort_can_be_created_with_an_implanted_animal(lab: Lab, tmp_path: Path) -> None:
    made = lab.cohorts.create("C", str(tmp_path / "data" / "C"),
                              animals=[{"id": "c1", "name": "c1", "implant": implant()}])
    assert made.animals[0].implant == implant()


def test_a_move_carries_the_implant_with_the_animal(lab: Lab) -> None:
    give(lab, "slow1", implant())
    lab.apply("slow1")
    assert implant_of(lab, "slow1", lab.b.id) == implant()


def test_a_move_that_joins_an_animal_gives_it_the_implant_unless_it_has_its_own(lab: Lab) -> None:
    give(lab, "slow1", implant())
    give(lab, "remy1", implant(device="probe"))
    give_b(lab, "slow1", "b-slow")
    lab.cohorts.update(lab.b.id, {"animals": [
        *roster(lab, lab.b.id), {"id": "b-remy", "name": "remy1", "implant": implant(device="its own")}]})

    lab.apply("slow1", "remy1")

    assert implant_of(lab, "b-slow", lab.b.id) == implant(), "the joined animal had none"
    assert implant_of(lab, "b-remy", lab.b.id)["device"] == "its own", "the destination's own stands"
    with lab.db.read() as q:
        left = {row[0] for row in q.execute("SELECT animal_id FROM implants")}
    assert left == {"b-slow", "b-remy"}, "no row is left under an id nobody has"


# --- the schema ----------------------------------------------------------------- #

def test_the_implants_table_is_in_a_fresh_database_at_this_version(db: Database, tmp_path: Path) -> None:
    assert SCHEMA_VERSION >= 18
    conn = sqlite3.connect(tmp_path / "app" / "ephymeris.db")
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(implants)")]
        foreign = conn.execute("PRAGMA foreign_key_list(implants)").fetchall()
    finally:
        conn.close()
    assert columns == ["animal_id", "implant_json", "updated_at"]
    assert foreign == [], "no foreign key: the animals rows are deleted on every roster save"
    assert implants.TABLE == "implants"

"""Former members — `DATA.md#former-members`.

The bug this file exists to prevent: `cohorts.update` replaced the roster
wholesale, so an animal taken off it lost its row while its runs, adoptions and
notes kept its id. Every view names animals through the roster, so that history
came back as a bare id — or, in the animal rail, not at all.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.cohorts.members import name_from_paths
from ephymeris_sidecar.cohorts.models import ValidationError
from ephymeris_sidecar.cohorts.repository import CohortRepository

SESSION = "2O-Bdisc_25_2026-07-22"


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def repo(db: Database) -> CohortRepository:
    return CohortRepository(db)


def run_file(name: str, time: str = "113123") -> str:
    return f"/data/Batch A/2O-Bdisc/{SESSION}/behavior.json/{name}_{SESSION}_{time}.json"


def add_run(db: Database, cohort_id: str, animal_id: str, file_path: str | None) -> None:
    """A recorded run of `animal_id`, in a session of its own."""
    session_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO sessions (id, cohort_id, prefix_id, prefix_name, session_number, date,"
        " started_at, status, folder_path) VALUES (?, ?, 'p', '2O-Bdisc', '25', '2026-07-22',"
        " '2026-07-22T11:31:00+00:00', 'completed', ?)",
        (session_id, cohort_id, f"/data/Batch A/2O-Bdisc/{SESSION}"),
    )
    db.conn.execute(
        "INSERT INTO session_animal_runs (id, session_id, animal_id, box_number, sketch_path,"
        " file_path, started_at) VALUES (?, ?, ?, 1, 'GRGL', ?, '2026-07-22T11:31:23+00:00')",
        (str(uuid.uuid4()), session_id, animal_id, file_path),
    )
    db.conn.commit()


def cohort_with(repo: CohortRepository, *names: str):
    groups = [{"id": "g1", "name": "Morning", "order": 0}]
    animals = [{"id": n, "name": n, "groupId": "g1"} for n in names]
    return repo.create("Batch A", "/data/Batch A", animals=animals, groups=groups)


def roster(cohort) -> list[dict]:
    return [a.to_json() for a in cohort.animals]


# --- removal ----------------------------------------------------------------


def test_removing_an_animal_with_history_keeps_it_as_a_former_member(db, repo) -> None:
    cohort = cohort_with(repo, "remy1", "remy2")
    add_run(db, cohort.id, "remy2", run_file("remy2"))

    updated = repo.update(cohort.id, {"animals": [a for a in roster(cohort) if a["id"] != "remy2"]})

    assert [a.name for a in updated.animals] == ["remy1"]
    [former] = updated.former_animals
    assert (former.id, former.name, former.source) == ("remy2", "remy2", "removed")
    assert former.run_count == 1
    # By name: the group's id is gone by the next roster edit.
    assert former.group_name == "Morning"
    assert former.removed_at


def test_removing_an_animal_with_no_history_deletes_it(repo) -> None:
    """A typo'd row would otherwise sit under Former members for good."""
    cohort = cohort_with(repo, "remy1", "typo")
    updated = repo.update(cohort.id, {"animals": [a for a in roster(cohort) if a["id"] != "typo"]})
    assert updated.former_animals == []


def test_a_note_alone_is_history(db, repo) -> None:
    cohort = cohort_with(repo, "remy1", "remy2")
    add_run(db, cohort.id, "remy1", run_file("remy1"))
    session_id = db.conn.execute("SELECT id FROM sessions").fetchone()[0]
    db.conn.execute(
        "INSERT INTO session_notes (id, session_id, cohort_id, at, created_at, tag, scope_kind,"
        " animal_id, body) VALUES ('n1', ?, ?, 'now', 'now', 'observation', 'animal', 'remy2',"
        " 'Lethargic')",
        (session_id, cohort.id),
    )
    db.conn.commit()

    updated = repo.update(cohort.id, {"animals": [a for a in roster(cohort) if a["id"] != "remy2"]})

    [former] = updated.former_animals
    assert former.id == "remy2" and former.run_count == 0


def test_posting_a_former_members_id_restores_it(db, repo) -> None:
    cohort = cohort_with(repo, "remy1", "remy2")
    add_run(db, cohort.id, "remy2", run_file("remy2"))
    removed = repo.update(cohort.id, {"animals": [a for a in roster(cohort) if a["id"] != "remy2"]})

    restored = repo.update(
        cohort.id, {"animals": [*roster(removed), {"id": "remy2", "name": "remy2", "groupId": "g1"}]}
    )

    assert sorted(a.name for a in restored.animals) == ["remy1", "remy2"]
    assert restored.former_animals == []


def test_a_former_member_survives_its_group_being_deleted(db, repo) -> None:
    """Why former members are a table of their own: `animals.group_id`
    cascades from `groups`, which every roster edit rewrites."""
    cohort = cohort_with(repo, "remy1", "remy2")
    add_run(db, cohort.id, "remy2", run_file("remy2"))
    repo.update(cohort.id, {"animals": [a for a in roster(cohort) if a["id"] != "remy2"]})

    regrouped = repo.update(
        cohort.id,
        {
            "groups": [{"id": "g2", "name": "Evening", "order": 0}],
            "animals": [{"id": "remy1", "name": "remy1", "groupId": "g2"}],
        },
    )

    assert [f.id for f in regrouped.former_animals] == ["remy2"]


def test_a_name_held_by_a_former_member_can_be_reused(db, repo) -> None:
    """Names are unique among the roster only (`DATA.md#validation`)."""
    cohort = cohort_with(repo, "remy1", "remy2")
    add_run(db, cohort.id, "remy2", run_file("remy2"))
    removed = repo.update(cohort.id, {"animals": [a for a in roster(cohort) if a["id"] != "remy2"]})

    again = repo.update(
        cohort.id, {"animals": [*roster(removed), {"id": "new-2", "name": "remy2", "groupId": "g1"}]}
    )

    assert sorted(a.id for a in again.animals) == ["new-2", "remy1"]
    assert [f.id for f in again.former_animals] == ["remy2"]


def test_another_cohorts_animal_id_is_refused_by_name(repo) -> None:
    """It used to surface as an integrity error with no reason given."""
    other = repo.create(
        "Batch B", "/data/Batch B", animals=[{"id": "x1", "name": "x1", "groupId": "g"}],
        groups=[{"id": "g", "name": "G", "order": 0}],
    )
    cohort = cohort_with(repo, "remy1")
    with pytest.raises(ValidationError) as caught:
        repo.update(cohort.id, {"animals": [*roster(cohort), {"id": "x1", "name": "x1", "groupId": "g1"}]})
    assert "Batch B" in caught.value.errors["animal:x1"]
    assert [a.id for a in repo.get(other.id).animals] == ["x1"]


# --- ids with no row at all -------------------------------------------------


def test_an_id_history_names_with_no_row_is_named_from_its_files(db, repo) -> None:
    """The split the lab actually did: the row was deleted before former
    members existed, and only the runs still carry the id."""
    cohort = cohort_with(repo, "remy1")
    add_run(db, cohort.id, "gone-id", run_file("remy9", "100000"))
    add_run(db, cohort.id, "gone-id", run_file("remy9", "110000"))

    [former] = repo.get(cohort.id).former_animals

    assert (former.id, former.name, former.source) == ("gone-id", "remy9", "files")
    assert former.run_count == 2
    assert former.removed_at is None


def test_restoring_a_file_named_id_reconnects_its_history(db, repo) -> None:
    cohort = cohort_with(repo, "remy1")
    add_run(db, cohort.id, "gone-id", run_file("remy9"))

    restored = repo.update(
        cohort.id, {"animals": [*roster(cohort), {"id": "gone-id", "name": "remy9", "groupId": "g1"}]}
    )

    assert "gone-id" in {a.id for a in restored.animals}
    assert restored.former_animals == []


def test_a_listing_does_not_pay_for_former_members(db, repo) -> None:
    cohort = cohort_with(repo, "remy1")
    add_run(db, cohort.id, "gone-id", run_file("remy9"))
    [listed] = repo.list_cohorts()
    assert listed.former_animals == []
    assert repo.get(cohort.id).former_animals


def test_the_name_is_the_majority_of_the_stems() -> None:
    paths = [run_file("remy9", "100000"), run_file("remy9", "110000"), run_file("Remy-9", "120000")]
    assert name_from_paths(paths) == "remy9"


def test_a_stem_not_in_the_naming_convention_names_nothing() -> None:
    assert name_from_paths(["/data/x/behavior.json/notes.json", "/data/x/behavior.json/a_b.json"]) is None

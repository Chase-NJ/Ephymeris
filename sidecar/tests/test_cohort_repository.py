"""Cohort persistence and validation — `cohorts.md` §1, §2, §9."""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.cohorts.models import (
    CohortNotFound,
    NameTaken,
    NotArchived,
    ValidationError,
)
from ephymeris_sidecar.cohorts.repository import CohortRepository


@pytest.fixture
def repo(tmp_path: Path) -> CohortRepository:
    db = Database(tmp_path / "test.db")
    db.connect()
    try:
        yield CohortRepository(db)
    finally:
        db.close()


def animal(name: str, group_id: str, **kwargs) -> dict:
    return {"name": name, "groupId": group_id, **kwargs}


# --- creation -------------------------------------------------------------


def test_a_new_cohort_gets_an_implicit_default_group(repo) -> None:
    """§2 — groups always exist, keeping grouped/ungrouped one code path."""
    cohort = repo.create("Batch A", "/tmp/batch-a")
    assert len(cohort.groups) == 1
    assert cohort.animals == []
    assert cohort.archived is False


def test_a_cohort_can_start_empty(repo) -> None:
    """§1 — real lab setup is rarely a single sitting."""
    cohort = repo.create("Batch A", "/tmp/a")
    assert repo.get(cohort.id).animals == []


def test_a_blank_name_is_rejected(repo) -> None:
    with pytest.raises(ValidationError):
        repo.create("   ", "/tmp/a")


# --- §2 name uniqueness ---------------------------------------------------


def test_active_names_must_be_unique(repo) -> None:
    repo.create("Batch A", "/tmp/a")
    with pytest.raises(NameTaken):
        repo.create("Batch A", "/tmp/b")


def test_name_uniqueness_ignores_case(repo) -> None:
    repo.create("Batch A", "/tmp/a")
    with pytest.raises(NameTaken):
        repo.create("batch a", "/tmp/b")


def test_archiving_frees_the_name_for_reuse(repo) -> None:
    """§2 — archived cohorts don't block name reuse."""
    first = repo.create("Batch A", "/tmp/a")
    repo.archive(first.id)
    reused = repo.create("Batch A", "/tmp/b")
    assert reused.id != first.id


def test_restore_is_refused_when_the_name_was_reclaimed(repo) -> None:
    first = repo.create("Batch A", "/tmp/a")
    repo.archive(first.id)
    repo.create("Batch A", "/tmp/b")
    with pytest.raises(NameTaken):
        repo.restore(first.id)


def test_renaming_onto_another_active_name_is_refused(repo) -> None:
    repo.create("Batch A", "/tmp/a")
    second = repo.create("Batch B", "/tmp/b")
    with pytest.raises(NameTaken):
        repo.update(second.id, {"name": "Batch A"})


def test_a_cohort_can_keep_its_own_name_on_update(repo) -> None:
    cohort = repo.create("Batch A", "/tmp/a")
    assert repo.update(cohort.id, {"name": "Batch A"}).name == "Batch A"


# --- §2 animal validation -------------------------------------------------


def test_animal_names_are_unique_within_a_cohort(repo) -> None:
    cohort = repo.create("Batch A", "/tmp/a")
    gid = cohort.groups[0].id
    with pytest.raises(ValidationError) as exc:
        repo.update(cohort.id, {"animals": [animal("R1", gid), animal("R1", gid)]})
    assert exc.value.errors


def test_the_same_animal_name_may_exist_in_another_cohort(repo) -> None:
    """§2 — uniqueness is per cohort, not global."""
    a = repo.create("A", "/tmp/a")
    b = repo.create("B", "/tmp/b")
    repo.update(a.id, {"animals": [animal("R1", a.groups[0].id)]})
    repo.update(b.id, {"animals": [animal("R1", b.groups[0].id)]})
    assert len(repo.get(b.id).animals) == 1


def test_box_numbers_are_unique_within_a_group(repo) -> None:
    cohort = repo.create("Batch A", "/tmp/a")
    gid = cohort.groups[0].id
    with pytest.raises(ValidationError):
        repo.update(
            cohort.id,
            {"animals": [animal("R1", gid, boxNumber=3), animal("R2", gid, boxNumber=3)]},
        )


def test_box_numbers_may_repeat_across_groups(repo) -> None:
    """§2 — groups run consecutively, so the slot is legitimately reused."""
    cohort = repo.create("Batch A", "/tmp/a")
    groups = [
        {"id": "g1", "name": "Group 1", "order": 0},
        {"id": "g2", "name": "Group 2", "order": 1},
    ]
    saved = repo.update(
        cohort.id,
        {
            "groups": groups,
            "animals": [animal("R1", "g1", boxNumber=3), animal("R2", "g2", boxNumber=3)],
        },
    )
    assert sorted(a.box_number for a in saved.animals) == [3, 3]


def test_unassigned_boxes_never_collide(repo) -> None:
    cohort = repo.create("Batch A", "/tmp/a")
    gid = cohort.groups[0].id
    saved = repo.update(
        cohort.id, {"animals": [animal("R1", gid), animal("R2", gid), animal("R3", gid)]}
    )
    assert all(a.box_number is None for a in saved.animals)


@pytest.mark.parametrize("box", [0, 7, -1, 99])
def test_box_numbers_outside_one_to_six_are_rejected(repo, box: int) -> None:
    cohort = repo.create("Batch A", "/tmp/a")
    with pytest.raises(ValidationError):
        repo.update(
            cohort.id, {"animals": [animal("R1", cohort.groups[0].id, boxNumber=box)]}
        )


def test_an_animal_must_belong_to_one_of_the_cohorts_groups(repo) -> None:
    cohort = repo.create("Batch A", "/tmp/a")
    with pytest.raises(ValidationError):
        repo.update(cohort.id, {"animals": [animal("R1", "not-a-group")]})


def test_extended_animal_metadata_round_trips(repo) -> None:
    """§1/§11 — sex, idNumber and notes."""
    cohort = repo.create("Batch A", "/tmp/a")
    gid = cohort.groups[0].id
    saved = repo.update(
        cohort.id,
        {
            "animals": [
                animal("R1", gid, sex="F", idNumber="0421", notes="left ear notch")
            ]
        },
    )
    got = saved.animals[0]
    assert (got.sex, got.id_number, got.notes) == ("F", "0421", "left ear notch")


def test_an_unrecognised_sex_value_is_discarded_rather_than_stored(repo) -> None:
    cohort = repo.create("Batch A", "/tmp/a")
    saved = repo.update(
        cohort.id, {"animals": [animal("R1", cohort.groups[0].id, sex="banana")]}
    )
    assert saved.animals[0].sex is None


# --- §9 archive / delete --------------------------------------------------


def test_archive_is_reversible(repo) -> None:
    cohort = repo.create("Batch A", "/tmp/a")
    assert repo.archive(cohort.id).archived is True
    assert repo.restore(cohort.id).archived is False


def test_permanent_delete_requires_archiving_first(repo) -> None:
    """§9 — the deliberate two-step guard."""
    cohort = repo.create("Batch A", "/tmp/a")
    with pytest.raises(NotArchived):
        repo.delete(cohort.id)

    repo.archive(cohort.id)
    repo.delete(cohort.id)
    with pytest.raises(CohortNotFound):
        repo.get(cohort.id)


def test_deleting_a_cohort_removes_its_animals_and_groups(repo) -> None:
    cohort = repo.create("Batch A", "/tmp/a")
    repo.update(cohort.id, {"animals": [animal("R1", cohort.groups[0].id)]})
    repo.archive(cohort.id)
    repo.delete(cohort.id)
    assert repo.list_cohorts() == []


def test_purge_bypasses_the_archive_guard_for_rollback_only(repo) -> None:
    """Used when a create half-succeeded; never reachable from the wire."""
    cohort = repo.create("Batch A", "/tmp/a")
    repo.purge(cohort.id)
    with pytest.raises(CohortNotFound):
        repo.get(cohort.id)
    # The name is free again, so a retry isn't blocked by the failed attempt.
    assert repo.create("Batch A", "/tmp/a").name == "Batch A"


def test_missing_cohorts_raise_rather_than_returning_none(repo) -> None:
    for call in (repo.get, repo.archive, repo.restore, repo.delete):
        with pytest.raises(CohortNotFound):
            call("nope")


# --- §8 data folder decoupling -------------------------------------------


def test_renaming_does_not_change_the_data_folder(repo) -> None:
    """§8 — name and dataFolder are deliberately decoupled after creation."""
    cohort = repo.create("Batch A", "/tmp/batch-a")
    renamed = repo.update(cohort.id, {"name": "Renamed Entirely"})
    assert renamed.data_folder == "/tmp/batch-a"


def test_the_data_folder_changes_only_through_its_own_action(repo) -> None:
    cohort = repo.create("Batch A", "/tmp/batch-a")
    moved = repo.set_data_folder(cohort.id, "/tmp/elsewhere")
    assert moved.data_folder == "/tmp/elsewhere"
    assert moved.name == "Batch A"


# --- summaries ------------------------------------------------------------


def test_summary_carries_counts_without_animal_detail(repo) -> None:
    cohort = repo.create("Batch A", "/tmp/a")
    gid = cohort.groups[0].id
    repo.update(cohort.id, {"animals": [animal("R1", gid), animal("R2", gid)]})

    summary = repo.get(cohort.id).to_summary()

    assert summary["animalCount"] == 2
    assert summary["groupCount"] == 1
    assert summary["archived"] is False
    assert "animals" not in summary


def test_groups_are_returned_in_run_order(repo) -> None:
    cohort = repo.create("Batch A", "/tmp/a")
    repo.update(
        cohort.id,
        {
            "groups": [
                {"id": "g2", "name": "Second", "order": 1},
                {"id": "g1", "name": "First", "order": 0},
            ]
        },
    )
    assert [g.name for g in repo.get(cohort.id).groups] == ["First", "Second"]

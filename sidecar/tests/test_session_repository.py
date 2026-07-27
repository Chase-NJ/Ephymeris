"""Prefix / session persistence — `data-saving.md` §3–§4."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.cohorts.repository import CohortRepository
from ephymeris_sidecar.sessions.models import (
    GroupRun,
    PrefixNameTaken,
    SessionAnimalRun,
    SessionNotFound,
)
from ephymeris_sidecar.sessions.paths import (
    parse_name_date,
    resolve_animal_files,
    resolve_session_folder,
    session_folder_name,
)
from ephymeris_sidecar.sessions.repository import SessionRepository


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def repo(db: Database) -> SessionRepository:
    return SessionRepository(db)


# --- §3 prefixes ----------------------------------------------------------


def test_prefixes_are_created_and_listed(repo) -> None:
    repo.create_prefix("2O-Bdisc")
    repo.create_prefix("Shaping")
    assert [p.name for p in repo.list_prefixes()] == ["2O-Bdisc", "Shaping"]


def test_prefix_names_are_unique(repo) -> None:
    repo.create_prefix("2O-Bdisc")
    with pytest.raises(PrefixNameTaken):
        repo.create_prefix("2O-Bdisc")


def test_prefix_uniqueness_ignores_case(repo) -> None:
    repo.create_prefix("2O-Bdisc")
    with pytest.raises(PrefixNameTaken):
        repo.create_prefix("2o-bdisc")


def test_deleting_a_prefix_frees_the_name(repo) -> None:
    p = repo.create_prefix("2O-Bdisc")
    repo.delete_prefix(p.id)
    assert repo.create_prefix("2O-Bdisc").name == "2O-Bdisc"


# --- §2.2 session number suggestion --------------------------------------


def test_no_history_yields_no_suggestion(repo) -> None:
    p = repo.create_prefix("2O-Bdisc")
    assert repo.suggest_session_number(p.id) is None


def test_suggestion_is_highest_numeric_plus_one(db, repo) -> None:
    cohort = CohortRepository(db).create("C", "/tmp/c")
    p = repo.create_prefix("2O-Bdisc")
    for number in ("25", "23", "not-a-number", "24"):
        repo.create_session(cohort.id, p, number, "2026-07-22", "/tmp/f")
    assert repo.suggest_session_number(p.id) == "26"


def test_suggestion_degrades_when_history_is_all_non_numeric(db, repo) -> None:
    cohort = CohortRepository(db).create("C", "/tmp/c")
    p = repo.create_prefix("2O-Bdisc")
    repo.create_session(cohort.id, p, "pilot-a", "2026-07-22", "/tmp/f")
    assert repo.suggest_session_number(p.id) is None


def test_aborted_sessions_do_not_claim_their_number(db, repo) -> None:
    """An abandoned session wrote nothing, so its number stays claimable."""
    cohort = CohortRepository(db).create("C", "/tmp/c")
    p = repo.create_prefix("2O-Bdisc")
    kept = repo.create_session(cohort.id, p, "25", "2026-07-22", "/tmp/f")
    backed_out = repo.create_session(cohort.id, p, "26", "2026-07-22", "/tmp/f")
    repo.set_status(backed_out.id, "aborted")
    assert repo.suggest_session_number(p.id) == "26"
    assert repo.session_numbers_on(p.id, "2026-07-22") == [kept.session_number]


def test_same_day_numbers_are_scoped_to_prefix_and_date(db, repo) -> None:
    cohort = CohortRepository(db).create("C", "/tmp/c")
    p = repo.create_prefix("2O-Bdisc")
    other = repo.create_prefix("Shaping")
    repo.create_session(cohort.id, p, "25", "2026-07-22", "/tmp/f")
    repo.create_session(cohort.id, p, "24", "2026-07-21", "/tmp/f")
    repo.create_session(cohort.id, other, "9", "2026-07-22", "/tmp/f")
    assert repo.session_numbers_on(p.id, "2026-07-22") == ["25"]


# --- §4 sessions ----------------------------------------------------------


def test_a_new_session_starts_configuring(db, repo) -> None:
    cohort = CohortRepository(db).create("C", "/tmp/c")
    p = repo.create_prefix("2O-Bdisc")
    session = repo.create_session(cohort.id, p, "25", "2026-07-22", "/tmp/f")
    assert session.status == "configuring"
    assert session.ended_at is None
    # The prefix name is snapshotted so a later prefix delete doesn't blank it.
    assert session.prefix_name == "2O-Bdisc"


def test_status_transitions_stamp_ended_at_on_completion(db, repo) -> None:
    cohort = CohortRepository(db).create("C", "/tmp/c")
    p = repo.create_prefix("2O-Bdisc")
    session = repo.create_session(cohort.id, p, "25", "2026-07-22", "/tmp/f")

    running = repo.set_status(session.id, "running")
    assert running.ended_at is None

    done = repo.set_status(session.id, "completed")
    assert done.status == "completed"
    assert done.ended_at is not None


def test_group_runs_round_trip_as_json(db, repo) -> None:
    cohort = CohortRepository(db).create("C", "/tmp/c")
    p = repo.create_prefix("2O-Bdisc")
    session = repo.create_session(cohort.id, p, "25", "2026-07-22", "/tmp/f")

    saved = repo.set_group_runs(
        session.id, [GroupRun(group_id="g1", order=0, started_at="t0")]
    )
    assert saved.group_runs[0].group_id == "g1"
    assert saved.group_runs[0].order == 0


def test_a_prefix_can_be_deleted_without_touching_its_sessions(db, repo) -> None:
    """§3 — removing a prefix doesn't destroy history, just the dropdown entry."""
    cohort = CohortRepository(db).create("C", "/tmp/c")
    p = repo.create_prefix("2O-Bdisc")
    session = repo.create_session(cohort.id, p, "25", "2026-07-22", "/tmp/f")
    repo.delete_prefix(p.id)
    # The session record survives with its snapshotted prefix name intact.
    assert repo.get_session(session.id).prefix_name == "2O-Bdisc"


def test_missing_session_raises(repo) -> None:
    with pytest.raises(SessionNotFound):
        repo.get_session("nope")


def test_animal_runs_are_recorded_and_read_back(db, repo) -> None:
    cohort = CohortRepository(db).create("C", "/tmp/c")
    p = repo.create_prefix("2O-Bdisc")
    session = repo.create_session(cohort.id, p, "25", "2026-07-22", "/tmp/f")

    repo.record_animal_run(
        SessionAnimalRun(
            id="run1",
            session_id=session.id,
            animal_id="a1",
            box_number=3,
            sketch_path="/sk/GRGL",
            started_at="t0",
            file_path="/f/remy1.json",
            ended_at="t1",
            stop_reason="BF_END_SESSION received",
        )
    )
    runs = repo.runs_for(session.id)
    assert len(runs) == 1
    assert runs[0].box_number == 3
    assert runs[0].stop_reason == "BF_END_SESSION received"


def test_deleting_a_cohort_cascades_to_its_sessions(db, repo) -> None:
    cohorts = CohortRepository(db)
    cohort = cohorts.create("C", "/tmp/c")
    p = repo.create_prefix("2O-Bdisc")
    session = repo.create_session(cohort.id, p, "25", "2026-07-22", "/tmp/f")
    cohorts.archive(cohort.id)
    cohorts.delete(cohort.id)
    with pytest.raises(SessionNotFound):
        repo.get_session(session.id)


# --- §1–§2 naming ---------------------------------------------------------


def test_session_folder_name_matches_the_convention() -> None:
    when = datetime(2026, 7, 22, 11, 31, 23)
    assert session_folder_name("2O-Bdisc", "25", when) == "2O-Bdisc_25_2026-07-22"


def test_session_folder_nests_under_cohort_and_prefix() -> None:
    when = datetime(2026, 7, 22, 11, 31, 23)
    folder = resolve_session_folder("/data/RemyCohort", "2O-Bdisc", "25", when)
    assert folder == Path("/data/RemyCohort/2O-Bdisc/2O-Bdisc_25_2026-07-22")


def test_animal_files_share_a_timestamped_basename() -> None:
    when = datetime(2026, 7, 22, 11, 31, 23)
    folder = Path("/data/RemyCohort/2O-Bdisc/2O-Bdisc_25_2026-07-22")
    files = resolve_animal_files(folder, "remy1", "2O-Bdisc", "25", when)

    assert files.tsv.name == "remy1_2O-Bdisc_25_2026-07-22_113123.tsv"
    assert files.json.name == "remy1_2O-Bdisc_25_2026-07-22_113123.json"
    assert files.mat.name == "remy1_2O-Bdisc_25_2026-07-22_113123.mat"
    # Three format subfolders, one shared stem.
    assert files.tsv.parent.name == "behavior.tsv"
    assert files.json.parent.name == "behavior.json"
    assert files.basename == "remy1_2O-Bdisc_25_2026-07-22_113123"


# --- §2 the ISO date change and its legacy compatibility ------------------


def test_session_folders_sort_chronologically_across_a_year_boundary() -> None:
    """The whole reason MM_DD_YY was replaced (TODO item 17)."""
    december = session_folder_name("2O-Bdisc", "25", datetime(2026, 12, 31))
    january = session_folder_name("2O-Bdisc", "26", datetime(2027, 1, 1))
    assert sorted([january, december]) == [december, january]


def test_the_date_is_one_token_so_a_positional_parser_breaks_loudly() -> None:
    """Hyphenated, not `YYYY_MM_DD`.

    `MM_DD_YY` and `YYYY_MM_DD` split into the *same* number of underscore
    tokens, so an existing analysis script parsing by position would have kept
    running and silently misread every date. One hyphenated token changes the
    count, which is a failure someone notices.
    """
    when = datetime(2026, 7, 22, 11, 31, 23)
    new = resolve_animal_files(Path("/s"), "remy1", "2O-Bdisc", "25", when).tsv.stem
    legacy = "remy1_2O-Bdisc_25_07_22_26_113123"
    assert len(new.split("_")) != len(legacy.split("_"))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Current spelling, folder and per-animal file.
        ("2O-Bdisc_25_2026-07-22", date(2026, 7, 22)),
        ("remy1_2O-Bdisc_25_2026-07-22_113123", date(2026, 7, 22)),
        ("remy1_2O-Bdisc_25_2026-07-22_113123.json", date(2026, 7, 22)),
        # Legacy spelling — still on disk, still has to be readable.
        ("2O-Bdisc_25_07_22_26", date(2026, 7, 22)),
        ("remy1_2O-Bdisc_25_07_22_26_113123", date(2026, 7, 22)),
        ("remy1_2O-Bdisc_25_07_22_26_113123.tsv", date(2026, 7, 22)),
        # Nothing date-shaped at the end.
        ("behavior.tsv", None),
        ("2O-Bdisc", None),
    ],
)
def test_parse_name_date_reads_both_spellings(name: str, expected: date | None) -> None:
    assert parse_name_date(name) == expected


def test_legacy_parsing_is_not_fooled_by_the_session_number() -> None:
    """`2O-Bdisc_25_07_22_26` is number 25 then 07_22_26, not 25_07_22.

    An unanchored search for `NN_NN_NN` finds the wrong three tokens first,
    which is exactly the ambiguity the old format carried. Anchoring at the end
    of the name is what resolves it.
    """
    assert parse_name_date("2O-Bdisc_25_07_22_26") == date(2026, 7, 22)
    assert parse_name_date("2O-Bdisc_25_07_22_26_113123") == date(2026, 7, 22)

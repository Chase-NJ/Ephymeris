"""Orphan adoption against a legacy, hand-managed archive — `analytics.md` §8.1.

Models the lab's real pre-Ephymeris layout, which differs from the current
writer's in every way that matters: format folders named `behavior_json` /
`recovery_tsv` (underscores), session folders dated `MM_DD_YY`, an extra
prefix-grouping level managed by hand, and no database rows pointing at any of
it. Adoption is the only path by which that data can ever reach Analytics.

The invariant these protect: adoption **adds** payload rows, and never writes
a `sessions` or `session_animal_runs` row. A fabricated session row would
corrupt session-number suggestion and the same-day reuse warning.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import AnalyticsService, reader
from ephymeris_sidecar.analytics.repository import AnalyticsRepository
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.cohorts.repository import CohortRepository
from ephymeris_sidecar.protocol import validate_command_result
from ephymeris_sidecar.sessions.paths import parse_name_time, parse_session_folder
from ephymeris_sidecar.sessions.repository import SessionRepository

GRGL = {
    "taskName": "GRGL 2-Odor Discrimination",
    "strobes": {
        "101": "ODOR_1_ON",
        "103": "ODOR_3_ON",
        "248": "WATER_POKE_L",
        "249": "WATER_POKE_R",
        "246": "END_SESSION",
    },
    "liveMetrics": [
        {"id": "p_r_odor1", "label": "P(R | Odor 1)", "triggerCode": 101,
         "successCode": 249, "alternateCode": 248, "windowSize": 20},
        {"id": "p_l_odor3", "label": "P(L | Odor 3)", "triggerCode": 103,
         "successCode": 248, "alternateCode": 249, "windowSize": 20},
    ],
}

HIT_1 = [101, 249]
MISS_1 = [101, 248]
HIT_3 = [103, 248]


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "app" / "ephymeris.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


class LegacyRig:
    """A cohort pointed at a hand-managed archive, with no run records at all."""

    def __init__(self, db: Database, tmp_path: Path) -> None:
        self.db = db
        self.root = tmp_path / "data" / "The Remy's"
        self.cohorts = CohortRepository(db)
        self.sessions = SessionRepository(db)
        self.repo = AnalyticsRepository(db)
        self.sketch = tmp_path / "sketches" / "GRGL_2-Odor"
        self.sketch.mkdir(parents=True, exist_ok=True)
        (self.sketch / "task.json").write_text(json.dumps(GRGL), encoding="utf-8")

        self.root.mkdir(parents=True, exist_ok=True)
        self.cohort = self.cohorts.create("The Remy's", str(self.root))
        group = self.cohort.groups[0].id
        self.cohorts.update(
            self.cohort.id,
            {
                "animals": [
                    {"id": "a1", "name": "remy1", "groupId": group, "boxNumber": 1},
                    {"id": "a2", "name": "remy2", "groupId": group, "boxNumber": 2},
                ]
            },
        )
        self.cohort = self.cohorts.get(self.cohort.id)

        async def broadcast(message: dict) -> None:
            pass

        self.service = AnalyticsService(
            db=db,
            cohorts=self.cohorts,
            sessions=self.sessions,
            broadcast=broadcast,
            sketch_lookup=lambda name: (
                str(self.sketch) if name == "GRGL_2-Odor" else None
            ),
        )

    def add_legacy_run(
        self,
        animal: str,
        codes: list[int],
        *,
        prefix: str = "2O-Bdisc",
        number: str = "01",
        folder_date: str = "06_16_26",
        time: str = "120022",
        sketch: str | None = "GRGL_2-Odor",
        json_dir: str = "behavior_json",
        with_tsv: bool = False,
        group: str | None = None,
    ) -> Path:
        """One per-animal file in the lab's real on-disk shape.

        `group` is the hand-made top-level folder, which is **not** always the
        prefix: the real archive files the same sessions under `01_2O-Bdisc/`
        and again under a consolidated `ALL/`, with identical session-folder
        and file names underneath. `sketch=None` omits the key entirely, as the
        older per-prefix copies do.
        """
        session = self.root / (group or prefix) / f"{prefix}_{number}_{folder_date}"
        stem = f"{animal}_{prefix}_{number}_{folder_date}_{time}"
        path = session / json_dir / f"{stem}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "rat": animal,
            "serial_port": "COM6",
            "session_id": f"{prefix}_{number}",
            "stop_reason": "BF_END_SESSION received",
            "trial_seed": 451299704,
            "n_events": len(codes),
            "ts_data": [[c, i * 1000] for i, c in enumerate(codes)],
        }
        if sketch is not None:
            document["sketch"] = sketch
        path.write_text(json.dumps(document), encoding="utf-8")
        if with_tsv:
            tsv = session / "recovery_tsv" / f"{stem}.tsv"
            tsv.parent.mkdir(parents=True, exist_ok=True)
            tsv.write_text("101\t0\n", encoding="utf-8")
        return path


@pytest.fixture
def rig(db: Database, tmp_path: Path) -> LegacyRig:
    return LegacyRig(db, tmp_path)


# --- name parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    "name, prefix, number, when",
    [
        ("2O-Bdisc_01_06_16_26", "2O-Bdisc", "01", date(2026, 6, 16)),
        ("2O-Bdisc_25_2026-07-22", "2O-Bdisc", "25", date(2026, 7, 22)),
        ("shaping_07_04_22_26", "shaping", "07", date(2026, 4, 22)),
        # An underscored prefix must not be mistaken for the session number.
        ("2O_bdisc_01_05_29_26", "2O_bdisc", "01", date(2026, 5, 29)),
        ("Test_00_07_24_26", "Test", "00", date(2026, 7, 24)),
    ],
)
def test_session_folder_names_split_into_prefix_number_date(
    name: str, prefix: str, number: str, when: date
) -> None:
    parsed = parse_session_folder(name)
    assert (parsed.prefix, parsed.session_number, parsed.date) == (prefix, number, when)


def test_a_folder_with_no_date_is_not_split_at_all() -> None:
    """Inventing a split would attribute data to a session that never was."""
    parsed = parse_session_folder("miscellaneous")
    assert (parsed.prefix, parsed.session_number, parsed.date) == ("miscellaneous", "", None)


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("remy1_2O-Bdisc_01_06_16_26_120022", "12:00:22"),
        ("remy1_2O-Bdisc_25_2026-07-22_093015", "09:30:15"),
        ("2O-Bdisc_01_06_16_26", None),  # a session folder carries no time
        ("remy1_shaping_01_06_16_26_997799", None),  # not a real clock time
    ],
)
def test_per_animal_time_suffix(stem: str, expected: str | None) -> None:
    assert parse_name_time(stem) == expected


# --- the walk --------------------------------------------------------------


def test_walk_finds_both_layouts(rig: LegacyRig) -> None:
    legacy = rig.add_legacy_run("remy1", HIT_1 * 5)
    current = rig.add_legacy_run(
        "remy2", HIT_1 * 5, number="25", folder_date="2026-07-22",
        json_dir="behavior.json",
    )
    found = reader.walk_session_files(rig.root)
    assert set(found) == {legacy, current}


def test_walk_still_ignores_a_stray_json(rig: LegacyRig) -> None:
    """Scoping to format folders is what keeps an unrelated file out (§8.1)."""
    rig.add_legacy_run("remy1", HIT_1 * 5)
    (rig.root / "2O-Bdisc" / "notes.json").write_text("{}", encoding="utf-8")
    assert len(reader.walk_session_files(rig.root)) == 1


def test_sibling_tsv_follows_the_layout_it_found(rig: LegacyRig) -> None:
    """A legacy `.json` has its write-ahead log in `recovery_tsv/`, not
    `behavior.tsv/` — so a missing-file report says "recoverable" correctly."""
    path = rig.add_legacy_run("remy1", HIT_1 * 5, with_tsv=True)
    assert reader.sibling_tsv(path).is_file()

    current = rig.add_legacy_run(
        "remy2", HIT_1 * 5, number="25", folder_date="2026-07-22",
        json_dir="behavior.json",
    )
    assert reader.sibling_tsv(current).parent.name == "behavior.tsv"


# --- adoption --------------------------------------------------------------


async def test_rescan_adopts_a_legacy_archive(rig: LegacyRig) -> None:
    rig.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5)
    rig.add_legacy_run("remy2", HIT_1 * 10 + MISS_1 * 10)

    result = await rig.service.rescan(rig.cohort.id)

    assert result["scanned"] == 2
    assert result["adopted"] == 2
    assert {o["animalId"] for o in result["orphans"]} == {"a1", "a2"}
    assert validate_command_result("analytics.rescan", result) == []


async def test_adopted_runs_reach_the_summary_and_are_scored(rig: LegacyRig) -> None:
    """The whole point: real data with no run records still scores."""
    rig.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5)
    await rig.service.rescan(rig.cohort.id)

    payload = await rig.service.summary(rig.cohort.id)

    assert payload["counts"]["runs"] == 1
    assert payload["counts"]["decoded"] == 1
    run = payload["runs"][0]
    assert run["animalId"] == "a1"
    assert run["metrics"][0]["pSession"] == 0.75
    # Decoded with today's task.json, which is exactly as trustworthy as that
    # sounds — never reported as a snapshot (§8.2).
    assert run["profileSource"] == "sketch-current"
    assert run["boxNumber"] is None, "a filename carries no box number"
    assert validate_command_result("analytics.summary", payload) == []


async def test_adoption_synthesizes_sessions_without_writing_rows(
    rig: LegacyRig,
) -> None:
    rig.add_legacy_run("remy1", HIT_1 * 5, number="01", folder_date="06_16_26")
    rig.add_legacy_run("remy2", HIT_1 * 5, number="01", folder_date="06_16_26")
    rig.add_legacy_run("remy1", HIT_1 * 5, number="02", folder_date="06_17_26")

    await rig.service.rescan(rig.cohort.id)
    payload = await rig.service.summary(rig.cohort.id)

    # Two folders → two sessions, six animals-worth of files → three runs.
    assert [s["sessionNumber"] for s in payload["sessions"]] == ["01", "02"]
    assert [s["date"] for s in payload["sessions"]] == ["2026-06-16", "2026-06-17"]
    assert [s["ordinal"] for s in payload["sessions"]] == [1, 2]
    assert len(payload["runs"]) == 3
    # …and nothing was written to the real tables.
    assert rig.sessions.list_sessions(rig.cohort.id) == []


async def test_rescan_stays_idempotent_when_the_winning_copy_changes(
    rig: LegacyRig,
) -> None:
    """The adopted id is keyed on run identity, not path.

    Which copy of a duplicated run wins can legitimately change between scans.
    A path-keyed id would mint a *second* row for a run that already had one
    and leave both — the exact double-counting deduplication exists to prevent.
    """
    thin = rig.add_legacy_run("remy1", HIT_1 * 5, group="00_SHAPING", sketch=None)
    await rig.service.rescan(rig.cohort.id)
    first = rig.repo.adopted_for_cohort(rig.cohort.id)
    assert [e.file_path for e in first] == [str(thin)]

    # The consolidated copy appears later — richer, so it now wins.
    rich = rig.add_legacy_run("remy1", HIT_1 * 5, group="ALL")
    await rig.service.rescan(rig.cohort.id)

    second = rig.repo.adopted_for_cohort(rig.cohort.id)
    assert len(second) == 1, "one run, not one row per copy ever preferred"
    assert second[0].id == first[0].id, "same run, same row"
    assert second[0].file_path == str(rich)

    payload = await rig.service.summary(rig.cohort.id)
    assert len(payload["runs"]) == 1


async def test_a_sketch_is_resolved_at_read_time_not_frozen_at_adoption(
    rig: LegacyRig,
) -> None:
    """A run adopted while the Arduino Directory was unset must not stay
    permanently undecodable — the recorded path is a cache of a lookup, not a
    fact about the run."""
    rig.service._sketch_lookup = lambda name: None  # directory unavailable
    rig.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5)
    await rig.service.rescan(rig.cohort.id)

    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["status"] == "no-metrics"

    # The directory comes back. No re-adoption, just another summary.
    rig.service._sketch_lookup = lambda name: (
        str(rig.sketch) if name == "GRGL_2-Odor" else None
    )
    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["status"] == "ok"
    assert payload["runs"][0]["metrics"][0]["pSession"] == 0.75


async def test_rescan_is_idempotent(rig: LegacyRig) -> None:
    """The synthetic id is derived from the path, so a second walk refreshes
    rather than duplicating — a user may click Rescan twice."""
    rig.add_legacy_run("remy1", HIT_1 * 5)
    await rig.service.rescan(rig.cohort.id)
    await rig.service.rescan(rig.cohort.id)

    payload = await rig.service.summary(rig.cohort.id)
    assert len(payload["runs"]) == 1
    assert len(rig.repo.adopted_for_cohort(rig.cohort.id)) == 1


async def test_a_recorded_run_is_never_adopted_twice(rig: LegacyRig) -> None:
    """Database-first: a file a run record already points at is skipped."""
    from ephymeris_sidecar.sessions.models import SessionAnimalRun

    path = rig.add_legacy_run("remy1", HIT_1 * 5)
    prefix = rig.sessions.create_prefix("2O-Bdisc")
    session = rig.sessions.create_session(
        rig.cohort.id, prefix, "01", "2026-06-16", str(path.parent.parent)
    )
    rig.sessions.record_animal_run(
        SessionAnimalRun(
            id="r1",
            session_id=session.id,
            animal_id="a1",
            box_number=1,
            sketch_path=str(rig.sketch),
            file_path=str(path),
            started_at="2026-06-16T12:00:22+00:00",
        )
    )

    result = await rig.service.rescan(rig.cohort.id)
    assert result["scanned"] == 1
    assert result["adopted"] == 0

    payload = await rig.service.summary(rig.cohort.id)
    assert len(payload["runs"]) == 1, "the recorded run, not a duplicate"
    assert payload["runs"][0]["runId"] == "r1"


async def test_an_unmatched_file_is_reported_but_not_adopted(rig: LegacyRig) -> None:
    rig.add_legacy_run("remy9", HIT_1 * 5)  # not on the roster

    result = await rig.service.rescan(rig.cohort.id)
    assert result["adopted"] == 0
    assert result["orphans"][0]["animalName"] == "remy9"
    assert result["orphans"][0]["animalId"] is None

    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"] == []


async def test_an_unresolvable_sketch_says_why_it_scored_nothing(
    rig: LegacyRig,
) -> None:
    """A sketch name that no longer exists in the Arduino Directory has no
    task.json to fall back to — honest "unavailable", not a crash (§8.2).

    The lab's real archive hits this: the old software recorded human labels
    ("Shape - L") where the directory holds folder names (`shaping_GL`). The
    run must name the sketch it wanted, or the operator has nothing to act on.
    """
    rig.add_legacy_run("remy1", HIT_1 * 5, sketch="Shape - L")

    await rig.service.rescan(rig.cohort.id)
    payload = await rig.service.summary(rig.cohort.id)

    run = payload["runs"][0]
    assert run["profileSource"] == "unavailable"
    assert run["status"] == "no-metrics"
    assert payload["counts"]["noProfile"] == 1
    assert "Shape - L" in (run["detail"] or ""), "must name the sketch it wanted"


async def test_a_declared_legacy_name_makes_an_old_run_scorable(
    rig: LegacyRig, tmp_path: Path
) -> None:
    """`legacyNames` is the declared bridge from an old human label to the
    sketch that can decode it (`data-saving.md` §6.7) — the lab's shaping
    archive is recorded as "Shape - L", not `shaping_GL`."""
    shaping = tmp_path / "sketches" / "shaping_GL"
    shaping.mkdir(parents=True, exist_ok=True)
    (shaping / "task.json").write_text(
        json.dumps({**GRGL, "taskName": "Shaping — Go-Left", "legacyNames": ["Shape - L"]}),
        encoding="utf-8",
    )

    # A lookup that consults declared legacy names, as `app.py` does.
    def lookup(name: str) -> str | None:
        from ephymeris_sidecar.tasks.profile import load_profile

        for candidate in (rig.sketch, shaping):
            if candidate.name == name:
                return str(candidate)
            profile = load_profile(candidate)
            if profile is not None and name in profile.legacy_names:
                return str(candidate)
        return None

    rig.service._sketch_lookup = lookup
    rig.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5, sketch="Shape - L")

    await rig.service.rescan(rig.cohort.id)
    payload = await rig.service.summary(rig.cohort.id)

    run = payload["runs"][0]
    assert run["status"] == "ok", "the declared name resolved a decodable profile"
    assert run["metrics"][0]["pSession"] == 0.75


def test_legacy_names_default_to_empty_and_reject_junk() -> None:
    from ephymeris_sidecar.tasks.profile import TaskProfileError, parse_profile

    assert parse_profile({"taskName": "T"}).legacy_names == []
    assert parse_profile({"taskName": "T", "legacyNames": ["A", " B "]}).legacy_names == [
        "A",
        "B",
    ]
    with pytest.raises(TaskProfileError):
        parse_profile({"taskName": "T", "legacyNames": [1]})


async def test_fallback_decoded_runs_still_label_their_profile_group(
    rig: LegacyRig,
) -> None:
    """A comparability group needs a `taskName` to label itself with, and an
    archive that predates snapshots has *only* fallback decodes — so the
    fallback profile is stored too. Storing it must not promote the run's
    trust level (§8.2)."""
    rig.add_legacy_run("remy1", HIT_1 * 5)
    await rig.service.rescan(rig.cohort.id)

    payload = await rig.service.summary(rig.cohort.id)

    group = payload["profileGroups"][0]
    assert group["taskName"] == "GRGL 2-Odor Discrimination"
    assert group["runCount"] == 1
    assert payload["runs"][0]["profileSource"] == "sketch-current", "still a fallback"


async def test_a_cache_hit_pass_leaves_no_open_transaction(rig: LegacyRig) -> None:
    """The second summary is all cache hits, so nothing calls `store` — the
    remembered profiles must still be committed rather than held in an open
    write transaction."""
    rig.add_legacy_run("remy1", HIT_1 * 5)
    await rig.service.rescan(rig.cohort.id)
    await rig.service.summary(rig.cohort.id)
    await rig.service.summary(rig.cohort.id)

    assert not rig.db.conn.in_transaction


# --- a real archive's shape (see docs/analytics.md §8.1) -------------------


def test_applesingle_sidecars_are_not_data(rig: LegacyRig) -> None:
    """macOS writes `._name.json` beside every file when copying to a USB stick
    or share. They hold a resource fork, not JSON — the real Remy archive has
    454 of them against 586 real files, so leaving them in would make junk the
    *majority* of what the walk reported."""
    real = rig.add_legacy_run("remy1", HIT_1 * 5)
    sidecar = real.parent / f"._{real.name}"
    sidecar.write_bytes(b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X" + b"\x00" * 32)

    found = reader.walk_session_files(rig.root)
    assert found == [real]


async def test_a_consolidated_copy_does_not_double_every_run(
    rig: LegacyRig,
) -> None:
    """The real archive keeps an `ALL/` copy of every session beside the
    per-prefix originals. Adopting both would double every animal in the
    heatmap and put two points per session on every curve — silently."""
    rig.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5, group="01_2O-Bdisc")
    rig.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5, group="ALL")

    result = await rig.service.rescan(rig.cohort.id)

    assert result["scanned"] == 2
    assert result["adopted"] == 1, "one run, found twice"
    assert result["duplicates"] == 1

    payload = await rig.service.summary(rig.cohort.id)
    assert len(payload["runs"]) == 1
    assert len(payload["sessions"]) == 1


async def test_the_richer_copy_of_a_duplicated_run_wins(rig: LegacyRig) -> None:
    """In the real archive 30 runs carry `sketch` only in the consolidated
    copy — "first one found" would have discarded the only decodable version."""
    thin = rig.add_legacy_run("remy1", HIT_1 * 5, group="00_SHAPING", sketch=None)
    rich = rig.add_legacy_run("remy1", HIT_1 * 5, group="ALL")
    # The thin copy sorts first, so preference must be by content, not order.
    assert str(thin) < str(rich)

    await rig.service.rescan(rig.cohort.id)
    payload = await rig.service.summary(rig.cohort.id)

    assert len(payload["runs"]) == 1
    assert payload["runs"][0]["status"] == "ok", "kept the decodable copy"
    assert payload["runs"][0]["metrics"][0]["pSession"] == 1.0


async def test_a_missing_data_folder_says_so_rather_than_reading_as_empty(
    db: Database, tmp_path: Path
) -> None:
    """An unplugged drive or a re-lettered volume otherwise produces a
    perfectly well-formed empty result, which reads as "this cohort has no
    data" when it means "I can't see where its data is"."""
    rig = LegacyRig(db, tmp_path)
    gone = tmp_path / "D_drive_that_isnt_there" / "The Remy's"
    rig.cohorts.set_data_folder(rig.cohort.id, str(gone))

    result = await rig.service.rescan(rig.cohort.id)
    assert result["folderMissing"] is True
    assert result["dataFolder"] == str(gone)
    assert result["scanned"] == 0

    payload = await rig.service.summary(rig.cohort.id)
    codes = [w["code"] for w in payload["warnings"]]
    assert "data-folder-missing" in codes
    # The message is the bare path — the advice belongs to whatever renders it.
    assert payload["warnings"][0]["message"] == str(gone)
    assert validate_command_result("analytics.summary", payload) == []


async def test_adopted_runs_serve_series(rig: LegacyRig) -> None:
    """The learning curve has to work for adopted runs too — they have no
    session_animal_runs row, so `series` must fall back to the adoption table."""
    rig.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5)
    result = await rig.service.rescan(rig.cohort.id)
    await rig.service.summary(rig.cohort.id)

    run_id = next(
        r.id for r in rig.repo.adopted_for_cohort(rig.cohort.id)
    )
    payload = await rig.service.series([run_id])

    assert payload["warnings"] == []
    assert payload["series"][0]["runId"] == run_id
    assert payload["series"][0]["metrics"][0]["values"]
    assert validate_command_result("analytics.series", payload) == []
    assert result["adopted"] == 1

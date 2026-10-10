"""Analytics orchestration — `DATA.md#reading-the-archive`, `DATA.md#derived-metrics`.

Where `test_analytics_derive.py` covers the maths, this covers everything
around it: which profile decodes a run, what happens when a file is missing or
corrupt, whether the cache actually saves work and actually invalidates, and
the archive walk.

The service's job is to be honest about damaged data rather than to fail on it,
so a good half of these are about files that are wrong in some way.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import AnalyticsService
from ephymeris_sidecar.analytics import derive, reader
from ephymeris_sidecar.analytics.repository import AnalyticsRepository
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.cohorts.repository import CohortRepository
from ephymeris_sidecar.sessions.models import Prefix, SessionAnimalRun
from ephymeris_sidecar.sessions.repository import SessionRepository
from ephymeris_sidecar.tasks import profile as task_profile
from ephymeris_sidecar.tasks.profile import parse_profile, profile_hash

GRGL = {
    "taskName": "GRGL 2-Odor Discrimination",
    "strobes": {"101": "ODOR_1_ON", "103": "ODOR_3_ON", "248": "WATER_POKE_L",
                "249": "WATER_POKE_R", "246": "END_SESSION"},
    "liveMetrics": [
        {"id": "p_r_odor1", "label": "P(R | Odor 1)", "triggerCode": 101,
         "successCode": 249, "alternateCode": 248, "windowSize": 20},
        {"id": "p_l_odor3", "label": "P(L | Odor 3)", "triggerCode": 103,
         "successCode": 248, "alternateCode": 249, "windowSize": 20},
    ],
}
PROFILE = parse_profile(GRGL)


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "app" / "ephymeris.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


class Rig:
    """A cohort with real files on disk, wired to a real service."""

    def __init__(self, db: Database, tmp_path: Path) -> None:
        self.db = db
        self.root = tmp_path / "data" / "Batch A"
        self.cohorts = CohortRepository(db)
        self.sessions = SessionRepository(db)
        self.profiles = AnalyticsRepository(db)
        self.events: list[dict] = []
        self.sketch = tmp_path / "sketches" / "GRGL_2-Odor"

        # The real `cohorts.create` handler makes the folder as well as the
        # record (`app.py`), and a cohort whose folder is absent is now a
        # reported condition in its own right — so the rig has to be faithful
        # about it or every test here carries that warning.
        self.root.mkdir(parents=True, exist_ok=True)
        self.cohort = self.cohorts.create("Batch A", str(self.root))
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
        self.prefix = self.sessions.create_prefix("2O-Bdisc")

        async def broadcast(message: dict) -> None:
            self.events.append(message)

        self.service = AnalyticsService(
            db=db, cohorts=self.cohorts, sessions=self.sessions, broadcast=broadcast
        )

    def write_sketch(self, profile: dict | None = GRGL) -> None:
        self.sketch.mkdir(parents=True, exist_ok=True)
        if profile is not None:
            (self.sketch / "task.json").write_text(json.dumps(profile), encoding="utf-8")

    def add_session(self, number: str, date: str) -> str:
        folder = self.root / "2O-Bdisc" / f"2O-Bdisc_{number}_{date}"
        session = self.sessions.create_session(
            self.cohort.id, self.prefix, number, date, str(folder)
        )
        self.sessions.set_status(session.id, "completed")
        return session.id

    def add_run(
        self,
        session_id: str,
        animal_id: str,
        codes: list[int],
        *,
        run_id: str | None = None,
        snapshot: bool = True,
        write_file: bool = True,
        stop_reason: str = derive.CLEAN_STOP_REASON,
        name: str | None = None,
    ) -> str:
        rid = run_id or f"r-{session_id[:6]}-{animal_id}"
        session = self.sessions.get_session(session_id)
        path = Path(session.folder_path) / "behavior.json" / f"{name or animal_id}.json"
        if write_file:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "rat": name or _animal_name(self.cohort, animal_id),
                        "sketch": "GRGL_2-Odor",
                        "stop_reason": stop_reason,
                        "n_events": len(codes),
                        "ts_data": [[c, i * 1000] for i, c in enumerate(codes)],
                    }
                ),
                encoding="utf-8",
            )
        digest = self.profiles.remember_profile(PROFILE) if snapshot else None
        self.sessions.record_animal_run(
            SessionAnimalRun(
                id=rid,
                session_id=session_id,
                animal_id=animal_id,
                box_number=1,
                sketch_path=str(self.sketch),
                file_path=str(path),
                started_at="2026-07-22T10:00:00+00:00",
                ended_at="2026-07-22T10:40:00+00:00",
                stop_reason=stop_reason,
                profile_hash=digest,
            )
        )
        return rid


def _animal_name(cohort, animal_id: str) -> str:
    return next(a.name for a in cohort.animals if a.id == animal_id)


@pytest.fixture
def rig(db: Database, tmp_path: Path) -> Rig:
    r = Rig(db, tmp_path)
    r.write_sketch()
    return r


HIT_1 = [101, 249]
MISS_1 = [101, 248]
HIT_3 = [103, 248]


# --- the summary (`DATA.md#derived-metrics`) -------------------------------


async def test_summary_scores_every_run(rig: Rig) -> None:
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 15 + MISS_1 * 5)
    rig.add_run(session, "a2", HIT_1 * 10 + MISS_1 * 10)

    payload = await rig.service.summary(rig.cohort.id)

    assert payload["counts"]["runs"] == 2
    assert payload["counts"]["decoded"] == 2
    assert payload["warnings"] == []
    # Verbatim, not normalized: the open-folder button hands this to the OS.
    assert payload["dataFolder"] == str(rig.root)
    by_animal = {r["animalId"]: r for r in payload["runs"]}
    assert by_animal["a1"]["metrics"][0]["pSession"] == 0.75
    assert by_animal["a2"]["metrics"][0]["pSession"] == 0.5


async def test_summary_carries_the_roster_and_groups(rig: Rig) -> None:
    rig.add_session("1", "2026-07-22")
    payload = await rig.service.summary(rig.cohort.id)
    assert [a["name"] for a in payload["animals"]] == ["remy1", "remy2"]
    assert len(payload["groups"]) == 1


async def test_a_removed_animal_with_runs_is_listed_as_a_former_member(rig: Rig) -> None:
    """`DATA.md#former-members` — appended after the roster, so removing one
    animal never shifts another's colour, and named rather than an id."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 10)
    rig.add_run(session, "a2", HIT_1 * 10)
    group = rig.cohort.groups[0].id
    rig.cohorts.update(
        rig.cohort.id, {"animals": [{"id": "a2", "name": "remy2", "groupId": group}]}
    )

    payload = await rig.service.summary(rig.cohort.id)

    assert [(a["id"], a["name"], a["former"]) for a in payload["animals"]] == [
        ("a2", "remy2", False),
        ("a1", "remy1", True),
    ]
    assert {r["animalId"] for r in payload["runs"]} == {"a1", "a2"}


async def test_a_run_whose_animal_has_no_row_is_named_from_its_file(rig: Rig) -> None:
    """The lab's split as it happened, before former members existed: the
    row is gone, the run still carries the id, and the file names the rat."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "deleted-id", HIT_1 * 10, name="remy9_2O-Bdisc_1_2026-07-22_100000")

    payload = await rig.service.summary(rig.cohort.id)

    former = [a for a in payload["animals"] if a["former"]]
    assert [(a["id"], a["name"]) for a in former] == [("deleted-id", "remy9")]


async def test_a_former_member_with_no_runs_here_is_left_off(rig: Rig) -> None:
    rig.add_session("1", "2026-07-22")
    group = rig.cohort.groups[0].id
    # A note-free, run-free removal is deleted outright, so give it a run in
    # a session the summary is then filtered away from.
    other = rig.add_session("2", "2026-07-23")
    rig.add_run(other, "a1", HIT_1 * 10)
    rig.cohorts.update(
        rig.cohort.id, {"animals": [{"id": "a2", "name": "remy2", "groupId": group}]}
    )
    first = (await rig.service.summary(rig.cohort.id))["sessions"][0]["id"]

    payload = await rig.service.summary(rig.cohort.id, session_ids=[first])

    assert [a["id"] for a in payload["animals"]] == ["a2"]


async def test_a_stray_file_is_adopted_for_a_former_member(rig: Rig) -> None:
    """A file written while the animal was on the roster is still its file."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 10)
    group = rig.cohort.groups[0].id
    rig.cohorts.update(
        rig.cohort.id, {"animals": [{"id": "a2", "name": "remy2", "groupId": group}]}
    )
    stray = rig.root / "2O-Bdisc" / "2O-Bdisc_2_2026-07-23" / "behavior.json"
    stray.mkdir(parents=True)
    (stray / "remy1_2O-Bdisc_2_2026-07-23_100000.json").write_text(
        json.dumps({"rat": "remy1", "sketch": "GRGL_2-Odor", "ts_data": [[101, 0]]}),
        encoding="utf-8",
    )

    result = await rig.service.rescan(rig.cohort.id)

    assert [o["animalId"] for o in result["orphans"]] == ["a1"]


async def test_a_former_members_name_on_the_roster_wins_adoption(rig: Rig) -> None:
    """Once the name is back on the roster under a new animal, a file with
    that name means the animal on the roster."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 10)
    group = rig.cohort.groups[0].id
    rig.cohorts.update(
        rig.cohort.id,
        {
            "animals": [
                {"id": "a2", "name": "remy2", "groupId": group},
                {"id": "a1-new", "name": "remy1", "groupId": group},
            ]
        },
    )
    stray = rig.root / "2O-Bdisc" / "2O-Bdisc_2_2026-07-23" / "behavior.json"
    stray.mkdir(parents=True)
    (stray / "remy1_2O-Bdisc_2_2026-07-23_100000.json").write_text(
        json.dumps({"rat": "remy1", "sketch": "GRGL_2-Odor", "ts_data": [[101, 0]]}),
        encoding="utf-8",
    )

    result = await rig.service.rescan(rig.cohort.id)

    assert [o["animalId"] for o in result["orphans"]] == ["a1-new"]


async def test_sessions_are_chronological_with_a_1_based_ordinal(rig: Rig) -> None:
    rig.add_session("10", "2026-07-24")
    rig.add_session("9", "2026-07-22")
    payload = await rig.service.summary(rig.cohort.id)
    # Ordered by date, not by the free-text session number where "10" < "9".
    assert [s["date"] for s in payload["sessions"]] == ["2026-07-22", "2026-07-24"]
    assert [s["ordinal"] for s in payload["sessions"]] == [1, 2]
    assert [s["sessionNumber"] for s in payload["sessions"]] == ["9", "10"]


async def test_profile_groups_report_comparability(rig: Rig) -> None:
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    rig.add_run(session, "a2", HIT_3 * 5)
    payload = await rig.service.summary(rig.cohort.id)

    assert len(payload["profileGroups"]) == 1
    group = payload["profileGroups"][0]
    assert group["runCount"] == 2
    assert group["taskName"] == "GRGL 2-Odor Discrimination"
    # The pooled figure is offered first, ahead of the declared metrics — it is
    # the only one that can tell learning from a side bias (`DATA.md#pooled-accuracy`).
    assert [m["id"] for m in group["metrics"]] == [
        "__overall__",
        "p_r_odor1",
        "p_l_odor3",
    ]


async def test_summary_can_be_filtered_to_one_session(rig: Rig) -> None:
    first = rig.add_session("1", "2026-07-22")
    second = rig.add_session("2", "2026-07-23")
    rig.add_run(first, "a1", HIT_1 * 5)
    rig.add_run(second, "a1", HIT_1 * 5)

    payload = await rig.service.summary(rig.cohort.id, session_ids=[second])
    assert len(payload["sessions"]) == 1
    assert {r["sessionId"] for r in payload["runs"]} == {second}


# --- which profile decodes a run (`DATA.md#which-profile-decodes-a-run`) ---


async def test_a_snapshotted_run_decodes_from_the_snapshot(rig: Rig) -> None:
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["profileSource"] == "snapshot"


async def test_a_snapshot_survives_the_sketch_being_deleted(rig: Rig) -> None:
    """The whole point of snapshotting: the archive stays decodable."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    (rig.sketch / "task.json").unlink()

    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["profileSource"] == "snapshot"
    assert payload["runs"][0]["metrics"][0]["pSession"] == 1.0


async def test_a_legacy_run_falls_back_to_the_current_sketch_and_says_so(rig: Rig) -> None:
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5, snapshot=False)
    payload = await rig.service.summary(rig.cohort.id)
    # Decoded, but flagged: the task.json may have changed since the run.
    assert payload["runs"][0]["profileSource"] == "sketch-current"
    assert payload["runs"][0]["status"] == "ok"


async def test_a_run_with_no_declaration_left_is_scored_from_its_strobes(rig: Rig) -> None:
    """The ladder's last rung (`DATA.md#which-profile-decodes-a-run`): a deleted `task.json` used to strand a
    run at "no-metrics"; the stream itself now scores it, flagged `inferred`
    so the reader knows no declaration survives."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 15 + MISS_1 * 5, snapshot=False)
    (rig.sketch / "task.json").unlink()

    payload = await rig.service.summary(rig.cohort.id)
    run = payload["runs"][0]
    assert run["profileSource"] == "inferred"
    assert run["status"] == "ok"
    assert run["metrics"][0]["pSession"] == 0.75


async def test_a_stream_with_no_conditions_is_honestly_unavailable(rig: Rig) -> None:
    """Inference is a rung, not a promise — a stream presenting no recognisable
    condition (a utility sketch's log) still ends at `unavailable`, because
    inventing a condition would be worse than saying nothing (`DATA.md#which-profile-decodes-a-run`)."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", [222, 224, 226, 233], snapshot=False)
    (rig.sketch / "task.json").unlink()

    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["profileSource"] == "unavailable"
    assert payload["runs"][0]["status"] == "no-metrics"


async def test_a_malformed_task_json_degrades_rather_than_raising(rig: Rig) -> None:
    """Degrades to inference now, not to nothing — the stream is GRGL-shaped,
    so the run keeps scoring while the operator fixes the file."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5, snapshot=False)
    (rig.sketch / "task.json").write_text("{not json", encoding="utf-8")

    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["status"] == "ok"
    assert payload["runs"][0]["profileSource"] == "inferred"


def test_identical_profiles_snapshot_once(rig: Rig) -> None:
    first = rig.profiles.remember_profile(PROFILE)
    second = rig.profiles.remember_profile(parse_profile(GRGL))
    assert first == second == profile_hash(PROFILE)


def test_a_snapshotted_profile_round_trips(rig: Rig) -> None:
    digest = rig.profiles.remember_profile(PROFILE)
    restored = rig.profiles.load_profile(digest)
    assert restored is not None
    assert restored.to_json() == PROFILE.to_json()


# --- damaged data is data, not an error (`DATA.md#caching`) ----------------


async def test_a_missing_file_is_reported_not_raised(rig: Rig) -> None:
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5, write_file=False)

    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["status"] == "missing"
    assert payload["counts"]["missing"] == 1
    assert payload["warnings"][0]["code"] == "missing"


async def test_one_bad_file_does_not_blank_the_others(rig: Rig) -> None:
    """A year of history must survive a single unreadable `.json`."""
    session = rig.add_session("1", "2026-07-22")
    good = rig.add_run(session, "a1", HIT_1 * 5)
    bad = rig.add_run(session, "a2", HIT_1 * 5)
    Path(rig.sessions.runs_for(session)[1].file_path).write_text("{{{", encoding="utf-8")

    payload = await rig.service.summary(rig.cohort.id)
    by_id = {r["runId"]: r for r in payload["runs"]}
    assert by_id[good]["status"] == "ok"
    assert by_id[bad]["status"] == "unreadable"
    assert by_id[good]["metrics"][0]["pSession"] == 1.0


async def test_a_vanished_file_keeps_its_last_good_summary_as_stale(rig: Rig) -> None:
    """A briefly unreachable share must not erase history from Analytics."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    first = await rig.service.summary(rig.cohort.id)
    assert first["runs"][0]["metrics"][0]["pSession"] == 1.0

    Path(rig.sessions.runs_for(session)[0].file_path).unlink()

    second = await rig.service.summary(rig.cohort.id)
    run = second["runs"][0]
    assert run["stale"] is True
    assert run["metrics"][0]["pSession"] == 1.0, "the last good value is kept"


async def test_a_run_with_no_file_path_at_all(rig: Rig) -> None:
    session = rig.add_session("1", "2026-07-22")
    rig.sessions.record_animal_run(
        SessionAnimalRun(
            id="r-nofile", session_id=session, animal_id="a1", box_number=1,
            sketch_path=str(rig.sketch), file_path=None, started_at="t",
        )
    )
    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["status"] == "missing"


async def test_a_missing_json_with_a_surviving_tsv_says_so(rig: Rig) -> None:
    """The disk-full-at-finalization case — actionable, so name it."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    run = rig.sessions.runs_for(session)[0]
    tsv = Path(run.file_path).parent.parent / "behavior.tsv" / f"{Path(run.file_path).stem}.tsv"
    tsv.parent.mkdir(parents=True, exist_ok=True)
    tsv.write_text("# rat: remy1\n101\t0\n", encoding="utf-8")
    Path(run.file_path).unlink()

    payload = await rig.service.summary(rig.cohort.id)
    assert "recoverable" in (payload["warnings"][0]["message"] or "")


# --- caching (`DATA.md#caching`) -------------------------------------------


async def test_a_second_summary_reuses_the_cache(rig: Rig) -> None:
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    await rig.service.summary(rig.cohort.id)

    # Corrupt the file: a cached read would still return the good numbers.
    Path(rig.sessions.runs_for(session)[0].file_path).write_text(
        json.dumps({"ts_data": [], "stop_reason": "x"}), encoding="utf-8"
    )
    # ...but the mtime and size changed, so the cache must *not* be reused.
    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["metrics"][0]["pSession"] is None


async def test_the_cache_key_includes_the_codec_version(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without this, a fixed bug keeps serving the old definition forever."""
    session = rig.add_session("1", "2026-07-22")
    run_id = rig.add_run(session, "a1", HIT_1 * 5)
    await rig.service.summary(rig.cohort.id)

    cached = rig.profiles.load_cached([run_id])[run_id]
    assert cached.key.codec_version == derive.CODEC_VERSION

    monkeypatch.setattr(derive, "CODEC_VERSION", derive.CODEC_VERSION + 1)
    await rig.service.summary(rig.cohort.id)
    recomputed = rig.profiles.load_cached([run_id])[run_id]
    assert recomputed.key.codec_version == derive.CODEC_VERSION


async def test_a_cache_hit_never_reopens_the_file(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache key is answerable from a stat, so a warm pass reads no bytes.

    This is what a networked archive actually feels: before, a persisted cache
    saved the arithmetic and still pulled every file across the wire.
    """
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    first = await rig.service.summary(rig.cohort.id)

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("a cache hit must not open the file")

    monkeypatch.setattr(reader, "parse_run", boom)
    assert await rig.service.summary(rig.cohort.id) == first


async def test_a_vanished_file_still_goes_stale_without_being_parsed(rig: Rig) -> None:
    """The missing branch has to stay ahead of the key comparison: there is no
    stat to build a key from, and the cache (`DATA.md#caching`) keeps the last good summary either way."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    good = await rig.service.summary(rig.cohort.id)

    Path(rig.sessions.runs_for(session)[0].file_path).unlink()
    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["stale"] is True
    assert payload["runs"][0]["metrics"] == good["runs"][0]["metrics"]


async def test_the_profile_is_resolved_once_per_pass(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No snapshots, so every run has to fall back to today's `task.json` —
    # which is the path that pays a disk read per run without the memo.
    session = rig.add_session("1", "2026-07-22")
    for animal in ("a1", "a2"):
        rig.add_run(session, animal, HIT_1 * 5, snapshot=False)

    reads = 0
    real = task_profile.load_profile

    def counted(path: str) -> object:
        nonlocal reads
        reads += 1
        return real(path)

    monkeypatch.setattr(task_profile, "load_profile", counted)
    await rig.service.summary(rig.cohort.id)
    assert reads == 1

    # ...and the memo does not survive the pass. Profiles resolve at read time
    # on purpose (`DATA.md#caching`) — a memo that outlived one indexing job
    # would freeze an edited task.json.
    reads = 0
    await rig.service.summary(rig.cohort.id)
    assert reads == 1


async def test_progress_is_published_while_indexing(rig: Rig) -> None:
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    await rig.service.summary(rig.cohort.id)

    progress = [e for e in rig.events if e.get("evt") == "analytics.progress"]
    assert progress, "expected at least one analytics.progress event"
    assert progress[-1]["data"]["done"] == progress[-1]["data"]["total"]


# --- the series command (`PROTOCOL.md#cmd-analytics.series`) ---------------


async def test_series_returns_a_trajectory_per_run(rig: Rig) -> None:
    session = rig.add_session("1", "2026-07-22")
    run_id = rig.add_run(session, "a1", HIT_1 * 3 + MISS_1)

    result = await rig.service.series([run_id])
    metrics = result["series"][0]["metrics"]
    first = next(m for m in metrics if m["id"] == "p_r_odor1")
    assert first["values"] == [1.0, 1.0, 1.0, 0.75]
    assert first["n"] == [1, 2, 3, 4], "n is the window length behind each point"


async def test_series_carries_the_strategy_walk_alongside_the_metrics(rig: Rig) -> None:
    """One call feeds both the per-metric curves and the within-session
    strategy panel — the file is already open and decoded here."""
    session = rig.add_session("1", "2026-07-22")
    run_id = rig.add_run(session, "a1", (HIT_1 + HIT_3) * 12)

    entry = (await rig.service.series([run_id]))["series"][0]
    assert entry["trail"], "a two-condition profile has a walk"
    assert entry["trail"][-1] == {"trial": 24, "x": 1.0, "y": 1.0, "n": 12}


async def test_the_walk_is_empty_for_a_profile_that_has_no_plane(rig: Rig) -> None:
    """One condition is a coordinate, not a position."""
    rig.write_sketch({**GRGL, "liveMetrics": [GRGL["liveMetrics"][0]]})
    session = rig.add_session("1", "2026-07-22")
    run_id = rig.add_run(session, "a1", HIT_1 * 20)

    entry = (await rig.service.series([run_id]))["series"][0]
    assert entry["metrics"], "the run still decodes — it just has no second axis"
    assert entry["trail"] == []


async def test_series_refuses_an_oversized_request(rig: Rig) -> None:
    with pytest.raises(ValueError):
        await rig.service.series([f"r{i}" for i in range(50)])


async def test_series_reports_a_missing_run_rather_than_failing(rig: Rig) -> None:
    result = await rig.service.series(["nope"])
    assert result["series"] == []
    assert result["warnings"][0]["runId"] == "nope"


# --- the archive walk (`DATA.md#orphan-adoption`) --------------------------


async def test_rescan_finds_a_file_no_run_record_points_at(rig: Rig) -> None:
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    # A file that arrived from elsewhere — restored from backup, say.
    folder = Path(rig.sessions.get_session(session).folder_path) / "behavior.json"
    (folder / "stray.json").write_text(
        json.dumps({"rat": "remy2", "ts_data": [[101, 0]], "stop_reason": "x"}),
        encoding="utf-8",
    )

    result = await rig.service.rescan(rig.cohort.id)
    assert result["scanned"] == 2
    assert len(result["orphans"]) == 1
    assert result["orphans"][0]["animalId"] == "a2", "matched to remy2 by name"
    assert result["adopted"] == 1


async def test_rescan_keeps_an_unmatched_file_rather_than_guessing(rig: Rig) -> None:
    """A rename permanently breaks name matching — so never guess (`DATA.md#orphan-adoption`)."""
    session = rig.add_session("1", "2026-07-22")
    folder = Path(rig.sessions.get_session(session).folder_path) / "behavior.json"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ghost.json").write_text(
        json.dumps({"rat": "someone-else", "ts_data": [], "stop_reason": "x"}),
        encoding="utf-8",
    )

    result = await rig.service.rescan(rig.cohort.id)
    orphan = result["orphans"][0]
    assert orphan["animalId"] is None
    assert orphan["animalName"] == "someone-else"
    assert result["adopted"] == 0


async def test_rescan_does_not_fabricate_session_rows(rig: Rig) -> None:
    """Inventing sessions would corrupt session-number suggestion (`DATA.md#orphan-adoption`)."""
    session = rig.add_session("1", "2026-07-22")
    folder = Path(rig.sessions.get_session(session).folder_path) / "behavior.json"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "stray.json").write_text(
        json.dumps({"rat": "remy1", "ts_data": [], "stop_reason": "x"}), encoding="utf-8"
    )

    before = len(rig.sessions.list_sessions(rig.cohort.id))
    await rig.service.rescan(rig.cohort.id)
    assert len(rig.sessions.list_sessions(rig.cohort.id)) == before


async def test_rescan_ignores_files_outside_a_behavior_json_folder(rig: Rig) -> None:
    session = rig.add_session("1", "2026-07-22")
    stray = Path(rig.sessions.get_session(session).folder_path) / "notes.json"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("{}", encoding="utf-8")

    result = await rig.service.rescan(rig.cohort.id)
    assert result["scanned"] == 0


# --- pruning: records the disk no longer has (`DATA.md#pruning`) ------------
#
# The mirror image of adoption, and the one direction nothing else in the app
# covers. Deleting a session's folder used to leave its rows behind forever,
# and the cache's keep-the-last-good-summary rule (`DATA.md#caching`) then went on charting it — which
# is what these protect against, in both directions.


async def test_a_deleted_session_stops_appearing_after_a_rescan(rig: Rig) -> None:
    """The whole point: a session thrown away on disk leaves Analytics."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    rig.add_run(session, "a2", HIT_1 * 5)
    before = await rig.service.summary(rig.cohort.id)
    assert before["counts"]["decoded"] == 2

    shutil.rmtree(rig.sessions.get_session(session).folder_path)
    result = await rig.service.rescan(rig.cohort.id)

    assert result["pruned"] == {"runs": 2, "sessions": 1, "adopted": 0}
    after = await rig.service.summary(rig.cohort.id)
    assert after["runs"] == []
    assert after["sessions"] == []


async def test_pruning_clears_the_cached_summary_too(rig: Rig) -> None:
    """The cache is what was actually still serving the numbers (`DATA.md#caching`), so a
    surviving cache row would leave a deleted run's scores in the database
    under an id nothing points at."""
    session = rig.add_session("1", "2026-07-22")
    run_id = rig.add_run(session, "a1", HIT_1 * 5)
    await rig.service.summary(rig.cohort.id)
    assert rig.profiles.load_cached([run_id])

    shutil.rmtree(rig.sessions.get_session(session).folder_path)
    await rig.service.rescan(rig.cohort.id)

    assert rig.profiles.load_cached([run_id]) == {}


async def test_a_run_whose_file_went_but_whose_folder_stayed_keeps_its_session(
    rig: Rig,
) -> None:
    """Both halves are required. A folder that is still there is a session that
    still happened, whatever became of one animal's file."""
    session = rig.add_session("1", "2026-07-22")
    kept = rig.add_run(session, "a1", HIT_1 * 5)
    lost = rig.add_run(session, "a2", HIT_1 * 5)
    Path(rig.sessions.runs_for(session)[1].file_path).unlink()

    result = await rig.service.rescan(rig.cohort.id)

    assert result["pruned"]["runs"] == 1
    assert result["pruned"]["sessions"] == 0
    assert [s.id for s in rig.sessions.list_sessions(rig.cohort.id)] == [session]
    assert [r.id for r in rig.sessions.runs_for(session)] == [kept]
    assert lost not in {r.id for r in rig.sessions.runs_for(session)}


async def test_an_aborted_session_survives_while_its_folder_does(rig: Rig) -> None:
    """No-runs alone would delete every aborted session — one never wrote a
    file, and its folder is real."""
    folder = rig.root / "2O-Bdisc" / "2O-Bdisc_2_2026-07-23"
    folder.mkdir(parents=True)
    aborted = rig.sessions.create_session(
        rig.cohort.id, rig.prefix, "2", "2026-07-23", str(folder)
    )
    rig.sessions.set_status(aborted.id, "aborted")

    result = await rig.service.rescan(rig.cohort.id)

    assert result["pruned"]["sessions"] == 0
    assert len(rig.sessions.list_sessions(rig.cohort.id, include_aborted=True)) == 1


async def test_an_open_session_is_never_pruned(rig: Rig) -> None:
    """`configuring` and `running` describe a session the runner is holding
    right now, whose folder legitimately does not exist yet."""
    open_session = rig.sessions.create_session(
        rig.cohort.id, rig.prefix, "3", "2026-07-24", str(rig.root / "nope" / "gone")
    )

    result = await rig.service.rescan(rig.cohort.id)
    assert result["pruned"]["sessions"] == 0

    rig.sessions.set_status(open_session.id, "running")
    result = await rig.service.rescan(rig.cohort.id)
    assert result["pruned"]["sessions"] == 0
    assert rig.sessions.get_session(open_session.id).status == "running"


async def test_a_recoverable_run_is_not_pruned(rig: Rig) -> None:
    """A `.json` whose write-ahead `.tsv` survives is the crash case (`DATA.md#crash-recovery`), and
    its record carries the animal, profile and parameters that make recovery
    worth more than re-adopting the file from its filename."""
    session = rig.add_session("1", "2026-07-22")
    run_id = rig.add_run(session, "a1", HIT_1 * 5)
    path = Path(rig.sessions.runs_for(session)[0].file_path)
    tsv = path.parent.parent / "behavior.tsv" / f"{path.stem}.tsv"
    tsv.parent.mkdir(parents=True, exist_ok=True)
    tsv.write_text("# rat: remy1\n101\t0\n", encoding="utf-8")
    path.unlink()

    result = await rig.service.rescan(rig.cohort.id)

    assert result["pruned"]["runs"] == 0
    assert [r.id for r in rig.sessions.runs_for(session)] == [run_id]


async def test_a_run_with_no_recorded_path_is_not_pruned(rig: Rig) -> None:
    """Nothing was observed, so nothing is concluded. The summary already
    reports this run with its own distinct reason."""
    session = rig.add_session("1", "2026-07-22")
    rig.sessions.record_animal_run(
        SessionAnimalRun(
            id="r-nofile", session_id=session, animal_id="a1", box_number=1,
            sketch_path=str(rig.sketch), file_path=None, started_at="t",
        )
    )
    result = await rig.service.rescan(rig.cohort.id)
    assert result["pruned"]["runs"] == 0
    assert len(rig.sessions.runs_for(session)) == 1


async def test_an_unreachable_data_folder_prunes_nothing(rig: Rig) -> None:
    """The guard that holds on every platform: with the archive unreachable,
    every file under it reads as absent, and a rescan there would erase the
    cohort. `folderMissing` already says so — it must also stop the prune."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    await rig.service.summary(rig.cohort.id)
    shutil.rmtree(rig.root)

    result = await rig.service.rescan(rig.cohort.id)

    assert result["folderMissing"] is True
    assert result["pruned"] == {"runs": 0, "sessions": 0, "adopted": 0}
    assert len(rig.sessions.runs_for(session)) == 1
    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["stale"] is True, "still serving the last good value"


async def test_a_read_only_rescan_prunes_nothing(rig: Rig) -> None:
    """`adoptOrphans: false` means *don't change the index* — both ways."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 5)
    shutil.rmtree(rig.sessions.get_session(session).folder_path)

    result = await rig.service.rescan(rig.cohort.id, adopt_orphans=False)

    assert result["pruned"] == {"runs": 0, "sessions": 0, "adopted": 0}
    assert len(rig.sessions.runs_for(session)) == 1


@pytest.mark.skipif(os.name != "nt", reason="drive letters are a Windows shape")
async def test_a_record_on_an_unmounted_volume_is_left_alone(rig: Rig) -> None:
    """A record pointing *outside* the cohort folder can't lean on
    `folderMissing`, so absence there has to prove the storage is reachable.
    An unplugged or re-lettered volume leaves no readable ancestor at all —
    which is the lab machines' version of this failure (`DATA.md#pruning`)."""
    letter = next(
        (c for c in "ZYXWVU" if not Path(f"{c}:\\").exists()), None
    )
    if letter is None:  # pragma: no cover - every letter in use
        pytest.skip("no unused drive letter to stand in for an unplugged one")

    session = rig.add_session("1", "2026-07-22")
    rig.sessions.record_animal_run(
        SessionAnimalRun(
            id="r-elsewhere", session_id=session, animal_id="a1", box_number=1,
            sketch_path=str(rig.sketch),
            file_path=f"{letter}:\\Archive\\Batch A\\behavior.json\\remy1.json",
            started_at="t",
        )
    )

    result = await rig.service.rescan(rig.cohort.id)

    assert result["pruned"]["runs"] == 0
    assert len(rig.sessions.runs_for(session)) == 1


# --- listing ---------------------------------------------------------------


def test_list_sessions_excludes_aborted_by_default(rig: Rig) -> None:
    kept = rig.add_session("1", "2026-07-22")
    aborted = rig.sessions.create_session(
        rig.cohort.id, rig.prefix, "2", "2026-07-23", "/f"
    )
    rig.sessions.set_status(aborted.id, "aborted")

    assert [s.id for s in rig.sessions.list_sessions(rig.cohort.id)] == [kept]
    assert len(rig.sessions.list_sessions(rig.cohort.id, include_aborted=True)) == 2


def test_runs_for_cohort_spans_every_session(rig: Rig) -> None:
    first = rig.add_session("1", "2026-07-22")
    second = rig.add_session("2", "2026-07-23")
    rig.add_run(first, "a1", HIT_1)
    rig.add_run(second, "a1", HIT_1)
    assert len(rig.sessions.runs_for_cohort(rig.cohort.id)) == 2


# --- analytics.recentSessions ------------------------------------------------


async def test_recent_sessions_sees_unrecorded_archive_folders(rig: Rig) -> None:
    """A session another machine wrote into the shared archive is real history:
    it must appear, marked `recorded: False`, ahead of an older local one."""
    local = rig.add_session("1", "2026-07-20")
    rig.add_run(local, "a1", HIT_1 * 15)

    foreign = rig.root / "2O-Bdisc" / "2O-Bdisc_2_2026-07-28" / "behavior.json"
    foreign.mkdir(parents=True)
    (foreign / "remy9_2O-Bdisc_2_2026-07-28_101010.json").write_text(
        "{}", encoding="utf-8"
    )

    payload = await rig.service.recent_sessions()
    sessions = payload["sessions"]
    assert [(s["date"], s["recorded"]) for s in sessions] == [
        ("2026-07-28", False),
        ("2026-07-20", True),
    ]
    assert sessions[0]["prefixName"] == "2O-Bdisc"
    assert sessions[0]["sessionNumber"] == "2"
    assert sessions[0]["cohortName"] == "Batch A"


async def test_recent_sessions_marks_adopted_folders_recorded(rig: Rig) -> None:
    """Adoption writes `adopted_runs`, never a `sessions` row (`DATA.md#orphan-adoption`) — but an
    adopted folder is indexed on this machine, and reporting it `recorded:
    False` forever told the user to run the rescan they had already run."""
    foreign = rig.root / "2O-Bdisc" / "2O-Bdisc_2_2026-07-28" / "behavior.json"
    foreign.mkdir(parents=True)
    (foreign / "remy2_2O-Bdisc_2_2026-07-28_101010.json").write_text(
        json.dumps({"rat": "remy2", "ts_data": [[101, 0]], "stop_reason": "x"}),
        encoding="utf-8",
    )

    before = await rig.service.recent_sessions()
    assert [s["recorded"] for s in before["sessions"]] == [False]

    result = await rig.service.rescan(rig.cohort.id)
    assert result["adopted"] == 1

    after = await rig.service.recent_sessions()
    assert [s["recorded"] for s in after["sessions"]] == [True]


async def test_recent_sessions_honours_limit_and_skips_dateless_folders(rig: Rig) -> None:
    for number, date in (("1", "2026-07-01"), ("2", "2026-07-02"), ("3", "2026-07-03")):
        session = rig.add_session(number, date)
        rig.add_run(session, "a1", HIT_1 * 15)
    # A format folder whose session folder carries no date tail: real archives
    # have them (a notes/ or plots/ level) and inventing an order would be a lie.
    stray = rig.root / "2O-Bdisc" / "notes" / "behavior.json"
    stray.mkdir(parents=True)

    payload = await rig.service.recent_sessions(limit=2)
    assert [s["date"] for s in payload["sessions"]] == ["2026-07-03", "2026-07-02"]

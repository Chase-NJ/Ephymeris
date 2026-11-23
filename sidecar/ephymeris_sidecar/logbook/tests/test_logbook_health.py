"""Weigh-ins — `DATA.md#weigh-ins`.

One per animal per day, written from the Logbook: validated against the
cohort, kept under the animal alone, sent with the cohort's log, announced to
the day's sessions and printed in their folder's `notes.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.cohorts.models import CohortNotFound
from ephymeris_sidecar.logbook import mirror
from ephymeris_sidecar.logbook.models import HealthEntry, NoteInvalid
from ephymeris_sidecar.logbook.service import LogbookService
from ephymeris_sidecar.protocol import validate_command_result
from ephymeris_sidecar.analytics.tests.test_analytics_service import Rig
from ephymeris_sidecar.logbook.tests.test_logbook_mirror import _session

DAY = "2026-07-22"


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def rig(db: Database, tmp_path: Path) -> Rig:
    r = Rig(db, tmp_path)
    r.write_sketch()
    return r


@pytest.fixture
def logbook(rig: Rig) -> LogbookService:
    async def broadcast(message: dict) -> None:
        rig.events.append(message)

    return LogbookService(
        db=rig.db,
        cohorts=rig.cohorts,
        sessions=rig.sessions,
        profiles=rig.profiles,
        archive=rig.archive,
        broadcast=broadcast,
    )


async def health(logbook: LogbookService, rig: Rig) -> list[dict]:
    cohort = await logbook.cohort(rig.cohort.id)
    assert validate_command_result("logbook.cohort", cohort) == []
    return cohort["health"]


async def test_a_weigh_in_round_trips_and_matches_the_wire(rig: Rig, logbook: LogbookService) -> None:
    sid = rig.add_session("1", DAY)
    other = rig.add_session("2", "2026-07-23")

    reply = await logbook.set_health(rig.cohort.id, "a1", DAY, 312.4)
    assert validate_command_result("logbook.setHealth", reply) == []
    entry = reply["entry"]
    assert (entry["animalId"], entry["date"], entry["weightG"], entry["baseline"]) == ("a1", DAY, 312.4, False)
    assert entry["recordedAt"]

    assert await health(logbook, rig) == [entry]
    # The day's sessions are named, and only they: their pages and notes.md show it.
    assert rig.events[-1]["evt"] == "logbook.updated"
    assert rig.events[-1]["data"] == {"cohortId": rig.cohort.id, "sessionIds": [sid]}
    assert other not in rig.events[-1]["data"]["sessionIds"]


async def test_a_day_with_no_session_still_announces(rig: Rig, logbook: LogbookService) -> None:
    await logbook.set_health(rig.cohort.id, "a1", "2026-07-25", 300)
    assert rig.events[-1]["data"] == {"cohortId": rig.cohort.id, "sessionIds": []}
    assert [e["weightG"] for e in await health(logbook, rig)] == [300.0]


async def test_a_second_write_replaces_the_day_and_keeps_its_baseline_mark(
    rig: Rig, logbook: LogbookService
) -> None:
    await logbook.set_health(rig.cohort.id, "a1", DAY, 312.4, True)
    reply = await logbook.set_health(rig.cohort.id, "a1", DAY, 310.0)  # baseline absent: kept
    assert (reply["entry"]["weightG"], reply["entry"]["baseline"]) == (310.0, True)
    reply = await logbook.set_health(rig.cohort.id, "a1", DAY, 310.0, False)
    assert reply["entry"]["baseline"] is False
    assert len(await health(logbook, rig)) == 1


async def test_a_new_weigh_in_starts_unmarked(rig: Rig, logbook: LogbookService) -> None:
    await logbook.set_health(rig.cohort.id, "a1", "2026-07-21", 320.0, True)
    reply = await logbook.set_health(rig.cohort.id, "a1", DAY, 300.0)
    assert reply["entry"]["baseline"] is False


async def test_a_null_weight_removes_the_day_and_its_mark(rig: Rig, logbook: LogbookService) -> None:
    rig.add_session("1", DAY)
    await logbook.set_health(rig.cohort.id, "a1", DAY, 312.4, True)
    reply = await logbook.set_health(rig.cohort.id, "a1", DAY, None)
    assert reply == {"entry": None}
    assert validate_command_result("logbook.setHealth", reply) == []
    assert await health(logbook, rig) == []
    # Weighed again, the day starts over: the mark went with the row.
    again = await logbook.set_health(rig.cohort.id, "a1", DAY, 311.0)
    assert again["entry"]["baseline"] is False
    # Removing a day that has none is not an error.
    assert await logbook.set_health(rig.cohort.id, "a2", DAY, None) == {"entry": None}


async def test_the_cohort_s_weigh_ins_come_oldest_first_by_day_then_animal(
    rig: Rig, logbook: LogbookService
) -> None:
    await logbook.set_health(rig.cohort.id, "a2", DAY, 290.0)
    await logbook.set_health(rig.cohort.id, "a1", DAY, 312.0)
    await logbook.set_health(rig.cohort.id, "a2", "2026-07-20", 295.0)
    assert [(e["date"], e["animalId"]) for e in await health(logbook, rig)] == [
        ("2026-07-20", "a2"), (DAY, "a1"), (DAY, "a2"),
    ]


@pytest.mark.parametrize(
    ("animal", "date", "weight", "baseline", "message"),
    [
        ("stranger", DAY, 300.0, None, "isn't in this cohort"),
        ("a1", "22/07/2026", 300.0, None, "YYYY-MM-DD"),
        ("a1", "2026-02-30", 300.0, None, "YYYY-MM-DD"),
        ("a1", "20260722", 300.0, None, "YYYY-MM-DD"),
        ("a1", None, 300.0, None, "YYYY-MM-DD"),
        ("a1", DAY, 0.5, None, "between 1 and 2000"),
        ("a1", DAY, 2000.5, None, "between 1 and 2000"),
        ("a1", DAY, float("nan"), None, "number of grams"),
        ("a1", DAY, float("inf"), None, "number of grams"),
        ("a1", DAY, True, None, "number of grams"),
        ("a1", DAY, "312", None, "number of grams"),
        ("a1", DAY, 300.0, "yes", "true or false"),
    ],
)
async def test_refusals(
    rig: Rig, logbook: LogbookService, animal, date, weight, baseline, message: str
) -> None:
    with pytest.raises(NoteInvalid, match=message):
        await logbook.set_health(rig.cohort.id, animal, date, weight, baseline)
    assert await health(logbook, rig) == []
    assert rig.events == [], "a refused weigh-in announces nothing"


async def test_an_unknown_cohort_is_refused(logbook: LogbookService) -> None:
    with pytest.raises(CohortNotFound):
        await logbook.set_health("nope", "a1", DAY, 300.0)


async def test_the_bounds_themselves_are_weights(rig: Rig, logbook: LogbookService) -> None:
    assert (await logbook.set_health(rig.cohort.id, "a1", DAY, 1))["entry"]["weightG"] == 1.0
    assert (await logbook.set_health(rig.cohort.id, "a2", DAY, 2000))["entry"]["weightG"] == 2000.0


async def test_a_former_member_keeps_its_weigh_ins_and_can_still_be_weighed(
    rig: Rig, logbook: LogbookService
) -> None:
    """`DATA.md#former-members`: off the roster, still an animal of the cohort."""
    await logbook.set_health(rig.cohort.id, "a2", DAY, 290.0)
    cohort = rig.cohorts.get(rig.cohort.id)
    rig.cohorts.update(
        cohort.id, {"animals": [a.to_json() for a in cohort.animals if a.id != "a2"]}
    )
    assert [f.id for f in rig.cohorts.get(cohort.id).former_animals] == ["a2"]

    assert [e["animalId"] for e in await health(logbook, rig)] == ["a2"]
    reply = await logbook.set_health(cohort.id, "a2", "2026-07-23", 288.0)
    assert reply["entry"]["weightG"] == 288.0
    assert len(await health(logbook, rig)) == 2


async def test_another_cohort_s_weigh_ins_are_not_sent(rig: Rig, logbook: LogbookService) -> None:
    other = rig.cohorts.create("Batch B", str(rig.root.parent / "Batch B"))
    rig.cohorts.update(other.id, {"animals": [{"id": "b1", "name": "slow1"}]})
    await logbook.set_health(other.id, "b1", DAY, 280.0)
    await logbook.set_health(rig.cohort.id, "a1", DAY, 312.0)
    assert [e["animalId"] for e in await health(logbook, rig)] == ["a1"]
    with pytest.raises(NoteInvalid, match="isn't in this cohort"):
        await logbook.set_health(rig.cohort.id, "b1", DAY, 280.0)


# --- the notes.md mirror (DATA.md#the-notesmd-mirror) -------------------------


def test_the_mirror_prints_the_day_s_weights_by_name() -> None:
    from datetime import datetime, timezone

    session = _session("s1", "2026-07-22T09:00:00+00:00", "2026-07-22T10:00:00+00:00")
    text = mirror.render_markdown(
        cohort_name="Batch A",
        sessions=[session],
        logs=[],
        notes=[],
        changes=[],
        animal_names={"a1": "remy1", "a2": "remy2"},
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
        weights=[
            HealthEntry("a2", DAY, 298.0),
            HealthEntry("a1", DAY, 312.4, baseline=True),
            HealthEntry("gone", DAY, 250.25),
        ],
    )
    assert "## Weights\n\n- **gone**: 250.25 g\n- **remy1**: 312.4 g (baseline)\n- **remy2**: 298 g\n" in text
    assert text.index("## Weights") < text.index("## Notes")


def test_the_mirror_has_no_weights_section_without_any() -> None:
    from datetime import datetime, timezone

    session = _session("s1", "2026-07-22T09:00:00+00:00", "2026-07-22T10:00:00+00:00")
    text = mirror.render_markdown(
        cohort_name="", sessions=[session], logs=[], notes=[], changes=[], animal_names={},
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    assert "Weights" not in text


async def test_a_weigh_in_alone_writes_the_day_s_notes_md(rig: Rig, logbook: LogbookService) -> None:
    """A weigh-in is something the operator wrote: the folder gets its file,
    and only the folder of that day."""
    sid = rig.add_session("1", DAY)
    other = rig.add_session("2", "2026-07-23")
    for session_id in (sid, other):
        Path(rig.sessions.get_session(session_id).folder_path).parent.mkdir(parents=True, exist_ok=True)

    await logbook.set_health(rig.cohort.id, "a1", DAY, 312.4, True)
    await logbook.drain()

    written = Path(rig.sessions.get_session(sid).folder_path) / mirror.FILENAME
    assert "- **remy1**: 312.4 g (baseline)" in written.read_text(encoding="utf-8")
    assert logbook.write_mirror(other) is None
    assert not (Path(rig.sessions.get_session(other).folder_path) / mirror.FILENAME).exists()

    # Removed again, the file is rewritten without it rather than left stale.
    await logbook.set_health(rig.cohort.id, "a1", DAY, None)
    await logbook.drain()
    assert "Weights" not in written.read_text(encoding="utf-8")

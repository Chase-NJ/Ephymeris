"""Orphan adoption against a legacy, hand-managed archive — `DATA.md#orphan-adoption`.

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
import os
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
        nest: bool = True,
        rat: str | None = None,
        profile: dict | None = None,
        params: dict | None = None,
    ) -> Path:
        """One per-animal file in the lab's real on-disk shape.

        `group` is the hand-made top-level folder, which is **not** always the
        prefix: the real archive files the same sessions under `01_2O-Bdisc/`
        and again under a consolidated `ALL/`, with identical session-folder
        and file names underneath. `sketch=None` omits the key entirely, as the
        older per-prefix copies do.

        `nest=False` is the *other* real archive shape: session folders sitting
        straight under the cohort root with no grouping level, and the session
        number written before the prefix rather than after it.

        `rat` overrides the document's animal name, which is how a real archive
        carries a typo in one file while its filename stays correct.
        """
        if nest:
            folder = f"{prefix}_{number}_{folder_date}"
            session = self.root / (group or prefix) / folder
        else:
            folder = f"{number}_{prefix}_{folder_date}"
            session = self.root / folder
        stem = f"{animal}_{folder}_{time}"
        path = session / json_dir / f"{stem}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "rat": animal if rat is None else rat,
            "serial_port": "COM6",
            "session_id": f"{prefix}_{number}",
            "stop_reason": "BF_END_SESSION received",
            "trial_seed": 451299704,
            "n_events": len(codes),
            "ts_data": [[c, i * 1000] for i, c in enumerate(codes)],
        }
        if sketch is not None:
            document["sketch"] = sketch
        if params is not None:
            # Flat at the top level, exactly as `finalize` writes them (`DATA.md#the-json-document`).
            document.update(params)
        if profile is not None:
            # The snapshot a modern file carries with it (`DATA.md#the-embedded-task-profile`).
            document["task_profile"] = profile
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
        # Software older than this app wrote the number *first*. Taking the
        # trailing token whatever it was read these as prefix `00_01_shaping`,
        # number `gr`.
        ("00_01_shaping_gr_06_17_26", "shaping_gr", "00_01", date(2026, 6, 17)),
        ("29_30_shaping_gr_07_28_26", "shaping_gr", "29_30", date(2026, 7, 28)),
        # Same archive, one folder typed with hyphens. Reported as written —
        # folding `-` to `_` would also merge `2O-Bdisc` with `2O_bdisc`, which
        # are two real and distinct prefixes above.
        ("18-19-shaping-gr_07_13_26", "shaping-gr", "18-19", date(2026, 7, 13)),
        # The degradation that protects a digit-leading *prefix*: no numeric
        # token at either end, so nothing is split off. A bare `^\d+` would
        # report the prefix here as `O-Bdisc_gr`.
        ("2O-Bdisc_gr_07_13_26", "2O-Bdisc_gr", "", date(2026, 7, 13)),
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
    """Scoping to format folders is what keeps an unrelated file out (`DATA.md#database-first`)."""
    rig.add_legacy_run("remy1", HIT_1 * 5)
    (rig.root / "2O-Bdisc" / "notes.json").write_text("{}", encoding="utf-8")
    assert len(reader.walk_session_files(rig.root)) == 1


def test_walk_finds_sessions_sitting_straight_under_the_cohort(rig: LegacyRig) -> None:
    """The other lab archive has no grouping level at all. Matching a format
    folder by name rather than by depth is what reads it."""
    flat = rig.add_legacy_run(
        "remy1", HIT_1 * 5, prefix="shaping_gr", number="00_01", nest=False
    )
    assert reader.walk_session_files(rig.root) == [flat]


def test_walk_reads_a_flat_and_a_nested_archive_in_one_pass(rig: LegacyRig) -> None:
    """Depths are a property of the folder, not of the cohort — one archive can
    carry both, and a rescan must not have to be told which."""
    nested = rig.add_legacy_run("remy1", HIT_1 * 5)
    flat = rig.add_legacy_run(
        "remy2", HIT_1 * 5, prefix="shaping_gr", number="00_01", nest=False
    )
    assert set(reader.walk_session_files(rig.root)) == {nested, flat}


def test_a_folder_inside_a_format_folder_is_not_data(rig: LegacyRig) -> None:
    """Real archives keep plots in `behavior_json/analytics/`. A format
    folder's data is exactly its direct children — the walk stops at one."""
    run = rig.add_legacy_run("remy1", HIT_1 * 5)
    nested = run.parent / "analytics"
    nested.mkdir()
    (nested / "rolling_accuracy.png").write_bytes(b"\x89PNG")
    (nested / "notes.json").write_text("{}", encoding="utf-8")
    assert reader.walk_session_files(rig.root) == [run]


def test_a_report_folder_beside_the_format_folders_is_not_data(rig: LegacyRig) -> None:
    """`00_session_analytics/` and friends sit *in* the session folder, where
    nothing marks them as not-data except that they aren't a format folder."""
    run = rig.add_legacy_run("remy1", HIT_1 * 5)
    reports = run.parent.parent / "00_session_analytics"
    reports.mkdir()
    (reports / "cumulative.json").write_text("{}", encoding="utf-8")
    assert reader.walk_session_files(rig.root) == [run]


def test_the_walk_stops_at_the_depth_cap(rig: LegacyRig) -> None:
    """A cohort's data folder is user-settable and could be a drive root."""
    deep = rig.root
    for level in range(reader.MAX_FORMAT_DEPTH + 1):
        deep = deep / f"level{level}"
    buried = deep / "behavior_json"
    buried.mkdir(parents=True)
    (buried / "remy1_2O-Bdisc_01_06_16_26_120022.json").write_text("{}", encoding="utf-8")
    assert reader.walk_session_files(rig.root) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads anything")
def test_an_unreadable_directory_does_not_blank_the_cohort(rig: LegacyRig) -> None:
    """A bad directory is data too (`DATA.md#caching`'s corrupt-file rule, one
    level up). Losing a year of
    history to one bad permission bit is the failure worth ruling out."""
    run = rig.add_legacy_run("remy1", HIT_1 * 5)
    walled = rig.root / "locked"
    walled.mkdir()
    walled.chmod(0o000)
    try:
        assert reader.walk_session_files(rig.root) == [run]
    finally:
        walled.chmod(0o755)


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
    # sounds — never reported as a snapshot (`DATA.md#which-profile-decodes-a-run`).
    assert run["profileSource"] == "sketch-current"
    assert run["boxNumber"] is None, "a filename carries no box number"
    assert validate_command_result("analytics.summary", payload) == []


async def test_a_run_from_another_rig_still_names_its_program(
    rig: LegacyRig,
) -> None:
    """THE CROSS-MACHINE CASE. A session recorded on the Windows rig and copied
    into this cohort's data folder names a task profile this install has never
    seen, so nothing resolves a `task.json` and `sketchPath` is empty — the run
    scores by inference. It still recorded what it ran, and that is what the
    Program column has to be able to say: read off the path alone every such
    run displays as "unknown", which claims the record is silent when it is
    not."""
    rig.service._sketch_lookup = lambda name: None  # this rig has no such task
    rig.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5, sketch="GRGL 4-Odor")
    await rig.service.rescan(rig.cohort.id)

    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert run["sketchPath"] == ""
    assert run["sketchName"] == "GRGL 4-Odor"
    assert run["profileSource"] == "inferred"
    assert run["status"] == "ok"
    # And it can still say when it finished: nothing records an end time for a
    # file that arrived as an orphan, but the stream's own span is one, which
    # is what the session table's `~` end reads.
    assert run["endedAt"] is None
    assert run["durationMs"] == 39000


async def test_a_file_that_carries_its_profile_decodes_as_a_snapshot(
    rig: LegacyRig,
) -> None:
    """THE POINT OF THE EMBEDDED SNAPSHOT (`DATA.md#the-embedded-task-profile`), end to end.

    A session recorded on the Windows rig and copied here: this install has no
    run record for it and no sketch by that name, so every rung of the ladder
    above inference is out — except the one the file brought with it. It scores
    as a `snapshot`, on the profile it actually ran, and lands on the same
    profile hash the recording rig computed.
    """
    from ephymeris_sidecar.tasks.profile import parse_profile, profile_hash

    rig.service._sketch_lookup = lambda name: None
    rig.add_legacy_run(
        "remy1", HIT_1 * 15 + MISS_1 * 5, sketch="GRGL 4-Odor", profile=GRGL
    )
    await rig.service.rescan(rig.cohort.id)

    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert run["profileSource"] == "snapshot"
    assert run["profileHash"] == profile_hash(parse_profile(GRGL))
    assert run["metrics"][0]["pSession"] == 0.75
    # And the group it lands in is labelled by the profile, not by a guess.
    assert run["profileHash"] in {g["hash"] for g in
                                  (await rig.service.summary(rig.cohort.id))["profileGroups"]}


async def test_the_files_own_profile_outranks_a_same_named_sketch_here(
    rig: LegacyRig,
) -> None:
    """Both are "a declaration for this sketch"; only one of them is the
    declaration this run used. Ranked the other way, a rig that happens to hold
    a same-named task scores a visiting file against its own edit of it —
    silently, and under a hash claiming the two are comparable."""
    from ephymeris_sidecar.tasks.profile import parse_profile, profile_hash

    # This rig's `GRGL_2-Odor` has been retuned since: one odor renamed, which
    # is enough to change the hash and every chart title.
    edited = json.loads(json.dumps(GRGL))
    edited["liveMetrics"][0]["label"] = "P(R | Something Else)"
    (rig.sketch / "task.json").write_text(json.dumps(edited), encoding="utf-8")

    rig.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5, profile=GRGL)
    await rig.service.rescan(rig.cohort.id)

    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert run["profileSource"] == "snapshot"
    assert run["profileHash"] == profile_hash(parse_profile(GRGL))
    assert run["metrics"][0]["label"] == "P(R | Odor 1)"


async def test_a_copied_run_reports_the_parameters_its_file_records(
    rig: LegacyRig,
) -> None:
    """Comparability is the PAIR (`DATA.md#which-profile-decodes-a-run`). An adopted run has no row here to
    carry `paramsHash`, so without the snapshot naming which of the document's
    fields are parameters, two differently-tuned runs of one task pool
    silently."""
    from ephymeris_sidecar.tasks.profile import params_hash

    # Which of the document's flat fields are PARAMETERS is a question only the
    # profile answers, so the snapshot has to declare one for there to be
    # anything to hash.
    tuned = {**GRGL, "config": [
        {"metadataKey": "odor_poke_hold", "wireKey": "OPH", "label": "Odor poke hold",
         "type": "int", "default": 500},
    ]}
    rig.add_legacy_run(
        "remy1", HIT_1 * 10, profile=tuned, params={"odor_poke_hold": 500}
    )
    rig.add_legacy_run(
        "remy2", HIT_1 * 10, profile=tuned, params={"odor_poke_hold": 10}
    )
    await rig.service.rescan(rig.cohort.id)

    runs = (await rig.service.summary(rig.cohort.id))["runs"]
    hashes = {r["animalId"]: r["paramsHash"] for r in runs}
    assert hashes["a1"] == params_hash({"odor_poke_hold": 500})
    assert hashes["a2"] == params_hash({"odor_poke_hold": 10})
    assert hashes["a1"] != hashes["a2"], "one task, two tunings, one hash"


async def test_a_scored_profile_hash_survives_the_cache(rig: LegacyRig) -> None:
    """The digest a run is SCORED with is not the one resolution reached.

    For a profile read out of the file or inferred from its strobes, resolution
    reaches nothing — so the cache used to persist NULL and the run served its
    hash on the pass that computed it and none afterward, leaving its own
    profile group the moment the cache warmed. Both rungs are checked: they
    reach a scoring profile by the same road and would break together.
    """
    rig.service._sketch_lookup = lambda name: None
    rig.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5)                  # inferred
    rig.add_legacy_run("remy2", HIT_1 * 15 + MISS_1 * 5, profile=GRGL)    # embedded
    await rig.service.rescan(rig.cohort.id)

    def hashes(payload):
        return {r["animalId"]: r["profileHash"] for r in payload["runs"]}

    first = hashes(await rig.service.summary(rig.cohort.id))
    second = hashes(await rig.service.summary(rig.cohort.id))
    assert first == second
    assert all(value is not None for value in first.values())
    # And the groups those hashes name are still there on the cached pass.
    groups = {g["hash"] for g in (await rig.service.summary(rig.cohort.id))["profileGroups"]}
    assert set(first.values()) <= groups


async def test_a_four_odor_run_from_another_rig_can_be_put_on_the_plane(
    rig: LegacyRig,
) -> None:
    """THE USER-FACING PATH, end to end.

    A four-odor task authored on the Windows rig, run there, copied here. This
    install has no sketch by that name and no run record, so the conditions are
    INFERRED from the strobes — and the strategy plane needs each one to say
    which well it rewards. Inference resolves that from `checkResponse()`'s own
    codes, so the answer is there; what has to hold is that it survives the
    whole path — inference, summarize, the cache, the payload — and lands on
    the two axes as two-and-two rather than as four blanks.
    """
    from ephymeris_sidecar.analytics import derive
    from ephymeris_sidecar.tasks.profile import parse_profile

    rig.service._sketch_lookup = lambda name: None
    # Odors 1 and 2 answered right, 3 and 4 answered left — with the codes
    # `checkResponse()` actually emits. The poke codes alone are NOT evidence:
    # inference votes on FLUID_x / WATER_POKE_ERROR_x, because those are the
    # ones the firmware only ever emits at the correct (or only at the wrong)
    # well. A stream of bare pokes leaves every condition unevidenced.
    right = [249, 253]   # WATER_POKE_R then FLUID_R
    left = [248, 252]    # WATER_POKE_L then FLUID_L
    stream = (
        [101, *right] * 8
        + [102, *right] * 8
        + [103, *left] * 8
        + [104, *left] * 8
    )
    rig.add_legacy_run("remy1", stream, sketch="GRGL 4-Odor")
    await rig.service.rescan(rig.cohort.id)

    payload = await rig.service.summary(rig.cohort.id)
    run = payload["runs"][0]
    assert run["profileSource"] == "inferred"
    assert len(run["metrics"]) == 4

    sides = {m["id"]: m["answerSide"] for m in run["metrics"]}
    assert sorted(sides.values()) == ["left", "left", "right", "right"], sides
    # Every metric must also carry the integer the plane pools over.
    assert all(isinstance(m["hits"], int) for m in run["metrics"])

    # And the group the picker reads carries the same, so a panel can work out
    # its axes without opening a run.
    group = next(g for g in payload["profileGroups"] if g["hash"] == run["profileHash"])
    assert sorted(m["answerSide"] for m in group["metrics"] if m["answerSide"]) == [
        "left", "left", "right", "right",
    ]

    # ...which is what the plane actually asks for.
    stored = rig.repo.load_profile(run["profileHash"])
    axes = derive.strategy_axes(stored)
    assert axes is not None
    assert len(axes.x_metrics) == 2 and len(axes.y_metrics) == 2
    assert parse_profile is not None  # imported for the fixture's sake


async def test_a_warm_cache_cannot_answer_with_an_older_payload_shape(
    rig: LegacyRig,
) -> None:
    """The regression that produced "this profile doesn't record which well
    each condition rewards" on an archive whose profiles say exactly that.

    A cached row is served verbatim, so a payload written before a field existed
    goes on being returned after it does — silently, because nothing about a
    cache hit looks wrong. `CODEC_VERSION` is the only thing standing between
    that and a panel drawing the wrong conclusion, which is why adding a FIELD
    counts as a codec change even when the arithmetic never moved.
    """
    from ephymeris_sidecar.analytics import derive

    rig.service._sketch_lookup = lambda name: None
    rig.add_legacy_run("remy1", ([101, 249] + [103, 248]) * 12)
    await rig.service.rescan(rig.cohort.id)
    await rig.service.summary(rig.cohort.id)

    # Forge exactly the stale row: the cache as an older codec left it.
    with rig.db.lock:
        rig.db.conn.execute(
            "UPDATE run_metrics_cache SET codec_version = ?", (derive.CODEC_VERSION - 1,)
        )
        rig.db.conn.commit()

    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert all(m["answerSide"] for m in run["metrics"]), (
        "a row from an older codec must be recomputed, not served"
    )


async def test_a_damaged_snapshot_falls_through_rather_than_failing(
    rig: LegacyRig,
) -> None:
    """A file with a broken snapshot is still a file full of real strobes."""
    rig.service._sketch_lookup = lambda name: None
    path = rig.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["task_profile"] = {"taskName": "GRGL", "liveMetrics": "not a list"}
    path.write_text(json.dumps(document), encoding="utf-8")
    await rig.service.rescan(rig.cohort.id)

    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert run["status"] == "ok"
    assert run["profileSource"] == "inferred"


async def test_a_program_name_falls_back_to_the_path_it_resolved(
    rig: LegacyRig,
) -> None:
    """A recorded run carries no name of its own — the row stores a path — so
    the last segment is the name, split on both separators because a path
    written on one platform is read on the other."""
    from ephymeris_sidecar.analytics.service import _program_name
    from ephymeris_sidecar.sessions.models import SessionAnimalRun

    run = SessionAnimalRun(
        id="r1",
        session_id="s1",
        animal_id="a1",
        box_number=1,
        sketch_path=r"C:\Users\Khase\Documents\Ephymeris\tasks\GRGL 4-Odor",
        file_path="",
        started_at="2026-08-24T12:00:22",
    )
    assert _program_name(run) == "GRGL 4-Odor"


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
    """A run adopted while the library was unavailable must not stay decoded
    second-hand — the recorded path is a cache of a lookup, not a fact about
    the run. With the inference rung the run *scores* meanwhile (same stream,
    same maths), so what upgrades on the next summary is the SOURCE."""
    rig.service._sketch_lookup = lambda name: None  # directory unavailable
    rig.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5)
    await rig.service.rescan(rig.cohort.id)

    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["status"] == "ok"
    assert payload["runs"][0]["profileSource"] == "inferred"
    assert payload["runs"][0]["metrics"][0]["pSession"] == 0.75

    # The directory comes back. No re-adoption, just another summary — and the
    # declared profile takes over from the inference.
    rig.service._sketch_lookup = lambda name: (
        str(rig.sketch) if name == "GRGL_2-Odor" else None
    )
    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["status"] == "ok"
    assert payload["runs"][0]["profileSource"] == "sketch-current"
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


async def test_a_second_rescan_does_not_read_the_files_again(
    rig: LegacyRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`DATA.md#carrying-adoptions-forward`. Adoption used to be redone in full on every click — every file
    opened, parsed and written back — to recompute the first scan's answer from
    the same inputs. On the machine whose archive is a network share that was
    the whole archive pulled over the wire per click."""
    for n in range(3):
        rig.add_legacy_run("remy1", HIT_1 * 5, number=f"0{n + 1}")
    first = await rig.service.rescan(rig.cohort.id)
    assert first["adopted"] == 3

    reads: list[Path] = []
    real_read = reader.read_run
    monkeypatch.setattr(
        reader, "read_run", lambda p: (reads.append(Path(p)), real_read(p))[1]
    )
    second = await rig.service.rescan(rig.cohort.id)

    assert reads == [], "not one file was opened"
    assert second["scanned"] == 3, "still reported honestly"
    assert second["adopted"] == 0, "nothing new was decided"
    assert len(rig.repo.adopted_for_cohort(rig.cohort.id)) == 3


async def test_a_carried_row_is_not_rewritten(rig: LegacyRig) -> None:
    """Every commit marks the database dirty for backup (`DATA.md#the-database-copy`), so rewriting an
    archive's worth of identical rows is a whole-file copy to a possibly
    networked target per click."""
    rig.add_legacy_run("remy1", HIT_1 * 5)
    await rig.service.rescan(rig.cohort.id)
    [before] = rig.repo.adopted_for_cohort(rig.cohort.id)

    commits: list[int] = []
    rig.db.conn.on_commit = lambda: commits.append(1)
    await rig.service.rescan(rig.cohort.id)
    rig.db.conn.on_commit = None

    assert commits == [], "no write at all when nothing changed"
    [after] = rig.repo.adopted_for_cohort(rig.cohort.id)
    assert after == before


async def test_an_edited_file_is_read_again_and_refreshes_its_row(
    rig: LegacyRig,
) -> None:
    """The skip is a cache with a stat key, not a do-it-once flag. A document
    edited on disk — or rewritten by crash recovery — must be picked up."""
    path = rig.add_legacy_run("remy1", HIT_1 * 5, sketch=None)
    await rig.service.rescan(rig.cohort.id)
    [before] = rig.repo.adopted_for_cohort(rig.cohort.id)
    assert before.sketch_name is None

    document = json.loads(path.read_text(encoding="utf-8"))
    document["sketch"] = "GRGL_2-Odor"
    path.write_text(json.dumps(document), encoding="utf-8")
    os.utime(path, ns=(before.file_mtime_ns + 10**9, before.file_mtime_ns + 10**9))

    result = await rig.service.rescan(rig.cohort.id)

    assert result["adopted"] == 1
    [after] = rig.repo.adopted_for_cohort(rig.cohort.id)
    assert after.id == before.id, "refreshed in place, never duplicated"
    assert after.sketch_name == "GRGL_2-Odor"


async def test_a_duplicate_copy_is_still_judged_against_a_carried_row(
    rig: LegacyRig,
) -> None:
    """The one thing the skip must not assume. Which copy of a duplicated run
    wins is a *content* decision (`_prefer`), so a second copy is read and
    judged rather than losing by default to whichever was adopted first — the
    real archive has 30 runs whose only decodable version is the consolidated
    copy."""
    rig.add_legacy_run("remy1", HIT_1 * 5, group="ZZ_per-prefix", sketch=None)
    await rig.service.rescan(rig.cohort.id)
    [poor] = rig.repo.adopted_for_cohort(rig.cohort.id)
    assert poor.sketch_name is None

    richer = rig.add_legacy_run("remy1", HIT_1 * 5, group="ALL", sketch="GRGL_2-Odor")
    result = await rig.service.rescan(rig.cohort.id)

    assert result["duplicates"] == 1
    [winner] = rig.repo.adopted_for_cohort(rig.cohort.id)
    assert winner.id == poor.id, "one run, one row"
    assert winner.file_path == str(richer)
    assert winner.sketch_name == "GRGL_2-Odor"


async def test_a_carried_row_still_beats_a_poorer_duplicate(rig: LegacyRig) -> None:
    """The other direction of the same rule: holding the slot is what stops a
    later, poorer copy quietly replacing an adopted row by being the only
    candidate the scan happened to read."""
    kept = rig.add_legacy_run("remy1", HIT_1 * 5, group="ALL", sketch="GRGL_2-Odor")
    await rig.service.rescan(rig.cohort.id)

    rig.add_legacy_run("remy1", HIT_1 * 5, group="ZZ_per-prefix", sketch=None)
    result = await rig.service.rescan(rig.cohort.id)

    assert result["duplicates"] == 1
    assert result["adopted"] == 0
    [winner] = rig.repo.adopted_for_cohort(rig.cohort.id)
    assert winner.file_path == str(kept)


async def test_an_adoption_yields_to_a_run_record_that_claims_its_file(
    rig: LegacyRig,
) -> None:
    """Database-first (`DATA.md#database-first`), enforced in both directions.

    The walk skips a path a run record claims, so an adoption made *before*
    that record existed was never revisited — and the file then reached the
    summary twice, once as `r1` and once as its adoption. Silent double-counting
    of a run, which is the exact failure deduplication exists to prevent,
    arriving from the side it doesn't watch."""
    from ephymeris_sidecar.sessions.models import SessionAnimalRun

    path = rig.add_legacy_run("remy1", HIT_1 * 5)
    await rig.service.rescan(rig.cohort.id)
    assert len(rig.repo.adopted_for_cohort(rig.cohort.id)) == 1

    prefix = rig.sessions.create_prefix("2O-Bdisc")
    session = rig.sessions.create_session(
        rig.cohort.id, prefix, "01", "2026-06-16", str(path.parent.parent)
    )
    rig.sessions.record_animal_run(
        SessionAnimalRun(
            id="r1", session_id=session.id, animal_id="a1", box_number=1,
            sketch_path=str(rig.sketch), file_path=str(path),
            started_at="2026-06-16T12:00:22+00:00",
        )
    )

    result = await rig.service.rescan(rig.cohort.id)
    assert result["adopted"] == 0
    assert result["pruned"]["adopted"] == 1, "the superseded adoption is dropped"
    assert rig.repo.adopted_for_cohort(rig.cohort.id) == []
    payload = await rig.service.summary(rig.cohort.id)
    assert [r["runId"] for r in payload["runs"]] == ["r1"], "the record, not a copy"


async def test_an_adoption_is_dropped_when_its_file_goes(rig: LegacyRig) -> None:
    """The prune (`DATA.md#pruning`) reaches adoptions too, and this is the easy half: an
    adopted row holds nothing that isn't re-derivable from the file it names,
    so a row deleted in error costs exactly one rescan."""
    kept = rig.add_legacy_run("remy1", HIT_1 * 5, number="01")
    gone = rig.add_legacy_run("remy2", HIT_1 * 5, number="02")
    await rig.service.rescan(rig.cohort.id)
    assert len(rig.repo.adopted_for_cohort(rig.cohort.id)) == 2

    gone.unlink()
    result = await rig.service.rescan(rig.cohort.id)

    assert result["pruned"]["adopted"] == 1
    surviving = rig.repo.adopted_for_cohort(rig.cohort.id)
    assert [entry.file_path for entry in surviving] == [str(kept)]
    # The synthetic session it was the only run of goes with it — those are
    # grouped from the surviving rows rather than stored, so nothing else has
    # to be cleaned up for that to be true.
    payload = await rig.service.summary(rig.cohort.id)
    assert len(payload["sessions"]) == 1
    assert result["pruned"]["sessions"] == 0, "no session row ever existed to delete"


async def test_a_moved_archive_is_re_adopted_rather_than_lost(rig: LegacyRig) -> None:
    """Pruning runs *before* the walk, so a run whose file moved is re-adopted
    in the same pass. Ordered the other way this would delete the row the walk
    had just refreshed."""
    path = rig.add_legacy_run("remy1", HIT_1 * 5)
    await rig.service.rescan(rig.cohort.id)
    [before] = rig.repo.adopted_for_cohort(rig.cohort.id)

    moved = rig.root / "moved" / path.parent.parent.name / path.parent.name / path.name
    moved.parent.mkdir(parents=True, exist_ok=True)
    path.replace(moved)

    result = await rig.service.rescan(rig.cohort.id)

    [after] = rig.repo.adopted_for_cohort(rig.cohort.id)
    assert after.id == before.id, "same run identity, same row"
    assert after.file_path == str(moved)
    assert result["adopted"] == 1
    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"][0]["status"] == "ok"


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
    assert result["orphans"][0]["animalSource"] is None

    payload = await rig.service.summary(rig.cohort.id)
    assert payload["runs"] == []


async def test_a_typo_in_the_rat_field_falls_back_to_the_filename(
    rig: LegacyRig,
) -> None:
    """The lab's real archive carries exactly this: one document recording
    `HmM103` beside a filename that says `HM103`. Losing the run leaves a hole
    that reads as "this animal didn't run", which is worse than the typo."""
    rig.add_legacy_run("remy1", HIT_1 * 5, rat="rrremy1")

    result = await rig.service.rescan(rig.cohort.id)
    assert validate_command_result("analytics.rescan", result) == []
    assert result["adopted"] == 1
    orphan = result["orphans"][0]
    assert orphan["animalId"] == "a1"
    # The document is still reported as written — the correction is visible,
    # never silent.
    assert orphan["animalName"] == "rrremy1"
    assert orphan["animalSource"] == "filename"

    payload = await rig.service.summary(rig.cohort.id)
    assert [r["animalId"] for r in payload["runs"]] == ["a1"]


async def test_a_document_match_is_never_overridden_by_the_filename(
    rig: LegacyRig,
) -> None:
    """The document is the primary recording; the filename is only consulted
    when it fails."""
    path = rig.add_legacy_run("remy1", HIT_1 * 5, rat="remy2")

    result = await rig.service.rescan(rig.cohort.id)
    assert path.stem.startswith("remy1_")
    assert result["orphans"][0]["animalId"] == "a2"
    assert result["orphans"][0]["animalSource"] == "document"


async def test_the_filename_fallback_still_demands_an_exact_roster_match(
    rig: LegacyRig,
) -> None:
    """Structural, not fuzzy. A name off the roster stays off it."""
    rig.add_legacy_run("ghost", HIT_1 * 5, rat="also-nobody")

    result = await rig.service.rescan(rig.cohort.id)
    assert result["adopted"] == 0
    assert result["orphans"][0]["animalId"] is None
    assert result["orphans"][0]["animalSource"] is None


async def test_the_filename_fallback_demands_the_stem_match_its_folder(
    rig: LegacyRig,
) -> None:
    """This is what makes it a naming *rule* rather than a first-token guess:
    the stem has to be `<animal>_<the folder it is in>_<HHMMSS>`, checked
    against the folder on disk."""
    real = rig.add_legacy_run("remy2", HIT_1 * 5)
    # `remy1` is on the roster, and this file leads with it — but the rest of
    # the stem is not the session folder it is sitting in, so it is not a
    # per-animal file and the leading token is not an attribution.
    stray = real.parent / "remy1_something_else_120000.json"
    stray.write_text(json.dumps({"rat": "nobody", "ts_data": []}), encoding="utf-8")

    result = await rig.service.rescan(rig.cohort.id)
    assert result["scanned"] == 2
    assert result["adopted"] == 1, "the real run, matched on its document"
    by_path = {o["path"]: o for o in result["orphans"]}
    assert by_path[str(stray)]["animalId"] is None
    assert by_path[str(stray)]["animalSource"] is None


async def test_an_unresolvable_sketch_still_scores_from_its_strobes(
    rig: LegacyRig,
) -> None:
    """A sketch name that resolves nothing used to strand the run at
    "no-metrics". The lab's real archive hits this — human labels ("Shape -
    L") where the library holds folder names — and those streams are exactly
    what the inference rung exists for: same firmware lineage, same registry,
    so the run scores, flagged `inferred`, and its profile group is labelled
    with the name the document recorded."""
    rig.add_legacy_run("remy1", HIT_1 * 5, sketch="Shape - L")

    await rig.service.rescan(rig.cohort.id)
    payload = await rig.service.summary(rig.cohort.id)

    run = payload["runs"][0]
    assert run["profileSource"] == "inferred"
    assert run["status"] == "ok"
    assert payload["counts"]["decoded"] == 1
    group = next(g for g in payload["profileGroups"] if g["hash"] == run["profileHash"])
    assert group["taskName"] == "Shape - L"


async def test_an_unresolvable_sketch_with_nothing_to_infer_says_why(
    rig: LegacyRig,
) -> None:
    """When the stream ALSO presents no recognisable condition, the run must
    name the sketch it wanted — that is the one thing the operator can act on
    (`DATA.md#which-profile-decodes-a-run`), and "no metrics" alone offers nothing to fix."""
    rig.add_legacy_run("remy1", [222, 224, 226, 233], sketch="Shape - L")

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
    sketch that can decode it (`TASKS.md#legacy-names`) — the lab's shaping
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
    trust level (`DATA.md#which-profile-decodes-a-run`)."""
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


# --- a real archive's shape (see DATA.md#orphan-adoption) -------------------


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
    analytics views and put two points per session on every curve — silently."""
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

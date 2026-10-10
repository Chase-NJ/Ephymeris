"""The strobe vocabulary: one document, its edits, and the evidence they need.

`TASKS.md#strobe-vocabulary`. Every rule here guards against a mistake that
produces plausible data rather than an error: a reissued number decodes two
events as one, a removed code that a recorded file contains leaves that file
unlabelled, and a stale header strobes numbers the app decodes differently.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from ephymeris_sidecar.app import Application
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.hardware.store import HardwareStore
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.rig.definition import RigDefinition
from ephymeris_sidecar.server import CommandError
from ephymeris_sidecar.strobes import store as strobe_store
from ephymeris_sidecar.strobes.store import StrobeRefused
from ephymeris_sidecar.strobes.usage import ArchiveScanner, firmware_refs
from ephymeris_sidecar.taskdef import generate
from ephymeris_sidecar.taskdef import store as task_store_mod
from ephymeris_sidecar.tasks import profile as task_profile
from tests.fixtures import task_definitions as presets


@pytest.fixture(autouse=True)
def _default_vocabulary():
    registry.set_vocabulary_source(None)
    registry.set_rig_source(None)
    yield
    registry.set_vocabulary_source(None)
    registry.set_rig_source(None)


def seed() -> dict:
    return registry.default_vocabulary_document()


def install(doc: dict) -> None:
    registry.set_vocabulary_source(lambda: copy.deepcopy(doc))


# --------------------------------------------------------------------------- #
# The document
# --------------------------------------------------------------------------- #


def test_the_seed_is_written_once_and_never_over_an_existing_document(tmp_path):
    vocab_store = strobe_store.VocabularyStore(tmp_path)
    assert vocab_store.ensure_seeded()
    doc = vocab_store.load_strict()
    doc = strobe_store.add(doc, "LASER_ON", 300, rationale="Optogenetic light on.")
    vocab_store.save(doc)

    # A second start must not "repair" the machine back to the default: that
    # would forget LASER_ON and free 300 for something else.
    assert not vocab_store.ensure_seeded()
    assert "LASER_ON" in vocab_store.load_strict()["codes"]


def test_a_damaged_document_refuses_edits_but_still_decodes(tmp_path):
    vocab_store = strobe_store.VocabularyStore(tmp_path)
    vocab_store.ensure_seeded()
    vocab_store.path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(StrobeRefused) as refused:
        vocab_store.load_strict()
    assert refused.value.reason == "unreadable"

    registry.set_vocabulary_source(vocab_store.load)
    assert registry.vocabulary().code_of("LIGHTS_ON") == 222


def test_validation_catches_a_number_issued_twice_across_live_and_retired():
    doc = seed()
    doc["codes"]["NEW_THING"] = {"code": 110, "rationale": "x"}  # 110 is retired
    problems = strobe_store.validate(doc)
    assert any(msg.startswith("110 is already") for _loc, msg in problems)


def test_a_version_2_export_is_read_as_version_3():
    v2 = seed()
    v2["vocab_version"] = 2
    v2.pop("reserved")
    v2["free_ranges"] = [[117, 220]]
    for entry in v2["retired"].values():
        if isinstance(entry, dict):
            entry["retired"] = True
    upgraded = strobe_store.upgrade(v2)
    assert strobe_store.validate(upgraded) == []
    assert "free_ranges" not in upgraded


# --------------------------------------------------------------------------- #
# Edits
# --------------------------------------------------------------------------- #


def test_add_issues_a_free_code_and_records_who_added_it():
    doc = strobe_store.add(seed(), "LASER_ON", 300, rationale="Light on.", emitted_on="pulse start")
    entry = doc["codes"]["LASER_ON"]
    assert entry["code"] == 300 and entry["origin"] == "operator"
    assert registry.Vocabulary(doc).code_of("LASER_ON") == 300


@pytest.mark.parametrize(
    ("name", "code", "fragment"),
    [
        ("LIGHTS_ON", 300, "already code 222"),
        ("DUMMY_SOLENOID_CLICK_1", 300, "Reinstate it"),
        ("LASER_ON", 222, "it is LIGHTS_ON"),
        ("LASER_ON", 110, "it is DUMMY_SOLENOID_CLICK_1"),
        ("LASER_ON", 50, "reserved"),
        ("LASER_ON", 1000, "outside"),
        ("BF_LASER_ON", 300, "without the BF_ prefix"),
        ("laser on", 300, "upper snake case"),
    ],
)
def test_add_refuses_a_name_or_number_that_cannot_be_issued(name, code, fragment):
    with pytest.raises(StrobeRefused, match=fragment):
        strobe_store.add(seed(), name, code, rationale="x")


def test_add_refuses_a_code_with_no_meaning():
    with pytest.raises(StrobeRefused, match="say what the code means"):
        strobe_store.add(seed(), "LASER_ON", 300, rationale="   ")


def test_editing_a_meaning_never_touches_the_name_or_number():
    doc = strobe_store.edit(seed(), "LIGHTS_ON", rationale="Cue light on.", emitted_on="")
    assert doc["codes"]["LIGHTS_ON"]["code"] == 222
    assert doc["codes"]["LIGHTS_ON"]["rationale"] == "Cue light on."
    assert "emitted_on" not in doc["codes"]["LIGHTS_ON"]


def test_retire_then_reinstate_round_trips_the_code():
    doc = strobe_store.retire(seed(), "ODOR_12_ON")
    vocab = registry.Vocabulary(doc)
    assert "ODOR_12_ON" not in vocab and vocab.retired_name(116) == "ODOR_12_ON"
    assert not vocab.is_free(116), "a retired number is never free"

    back = strobe_store.reinstate(doc, "ODOR_12_ON")
    entry = back["codes"]["ODOR_12_ON"]
    assert entry["code"] == 116 and entry["origin"] == "ephymeris"


def test_a_port_slot_code_can_be_neither_retired_nor_removed():
    """A response port whose slot names a missing code reports nothing — the
    silent failure RIG104 exists for."""
    with pytest.raises(StrobeRefused) as refused:
        strobe_store.retire(seed(), "WATER_POKE_L")
    assert refused.value.reason == "required"
    with pytest.raises(StrobeRefused):
        strobe_store.remove(seed(), "WATER_POKE_L", sessions_containing=0)


def test_remove_is_refused_outright_once_any_session_contains_the_code():
    with pytest.raises(StrobeRefused) as refused:
        strobe_store.remove(seed(), "ODOR_12_ON", sessions_containing=1)
    assert refused.value.reason == "in_recorded_session"
    assert "Retire it instead" in str(refused.value)


def test_remove_frees_the_number_when_nothing_ever_recorded_it():
    doc = strobe_store.remove(seed(), "ODOR_12_ON", sessions_containing=0)
    assert registry.Vocabulary(doc).is_free(116)
    # A retired code that turns out never to have been recorded may go too.
    doc = strobe_store.remove(seed(), "DUMMY_SOLENOID_CLICK_4", sessions_containing=0)
    assert registry.Vocabulary(doc).is_free(113)


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #


def test_an_import_brings_over_new_codes_and_retirements_only():
    here = strobe_store.add(seed(), "HERE_ONLY", 301, rationale="mine")
    there = strobe_store.add(seed(), "LASER_ON", 300, rationale="theirs")
    there = strobe_store.retire(there, "ODOR_12_ON")
    there = strobe_store.retire(strobe_store.add(there, "OLD_THING", 302, rationale="x"), "OLD_THING")

    plan = strobe_store.plan_merge(here, there)
    assert [a["name"] for a in plan.adds] == ["LASER_ON", "OLD_THING"]
    assert plan.adds[1]["retired"] is True
    assert plan.retires == [{"name": "ODOR_12_ON", "code": 116}]
    assert plan.only_here == ["HERE_ONLY"], "absence there is not a request to delete"

    merged = strobe_store.apply_merge(here, there, plan)
    vocab = registry.Vocabulary(merged)
    assert vocab.code_of("LASER_ON") == 300 and vocab.code_of("HERE_ONLY") == 301
    assert vocab.retired_name(116) == "ODOR_12_ON" and vocab.retired_name(302) == "OLD_THING"


def test_an_import_with_any_conflict_writes_nothing():
    here = strobe_store.add(seed(), "LASER_ON", 300, rationale="here")
    there = strobe_store.add(seed(), "LASER_ON", 301, rationale="there")
    there = strobe_store.add(there, "PUFF", 300 + 2, rationale="x")
    there_code = strobe_store.add(seed(), "OTHER", 300, rationale="x")

    plan = strobe_store.plan_merge(here, there)
    assert [c["name"] for c in plan.conflicts] == ["LASER_ON"]
    assert [c["name"] for c in strobe_store.plan_merge(here, there_code).conflicts] == ["OTHER"]
    with pytest.raises(StrobeRefused) as refused:
        strobe_store.apply_merge(here, there, plan)
    assert refused.value.reason == "import_conflict"


# --------------------------------------------------------------------------- #
# The registry and the generated firmware
# --------------------------------------------------------------------------- #


def test_the_registry_reads_whatever_document_is_installed():
    install(strobe_store.add(seed(), "LASER_ON", 300, rationale="x"))
    assert registry.vocabulary().code_of("LASER_ON") == 300
    assert registry.vocabulary().code_map()[110] == "DUMMY_SOLENOID_CLICK_1"


def test_every_generated_header_defines_every_live_code_and_no_retired_one():
    doc = strobe_store.retire(strobe_store.add(seed(), "LASER_ON", 300, rationale="x"), "ODOR_12_ON")
    install(doc)
    task = generate.task_pins_h(presets.instantiate("grgl_2odor", "t", "T"))
    bundled = generate.bundled_pins_h("GRGL_Sim")
    for header in (task, bundled):
        assert "#define BF_LASER_ON 300" in header
        assert "#define BF_LIGHTS_ON 222" in header
        assert "BF_ODOR_12_ON" not in header
        assert "BF_DUMMY_SOLENOID_CLICK_1" not in header
        assert f"Strobes: vocabulary {registry.vocabulary().content_hash()}" in header


def test_a_meaning_edit_does_not_move_the_header_stamp():
    before = registry.Vocabulary(seed()).content_hash()
    after = registry.Vocabulary(strobe_store.edit(seed(), "LIGHTS_ON", rationale="reworded")).content_hash()
    assert before == after


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #


def test_a_generated_profile_carries_no_strobe_map_and_names_its_metric_codes():
    raw = generate.profile_json(presets.instantiate("grgl_2odor", "t", "T"))
    assert "strobes" not in raw
    metric = raw["liveMetrics"][0]
    assert "triggerCode" not in metric and metric["trigger"].endswith("_ON")

    built = generate.build_profile(presets.instantiate("grgl_2odor", "t", "T"))
    assert built.strobes == registry.vocabulary().code_map()
    assert built.live_metrics[0].trigger_code == registry.vocabulary().code_of(metric["trigger"])


def test_a_sketch_s_own_strobes_map_is_ignored(tmp_path):
    (tmp_path / "task.json").write_text(json.dumps({
        "taskName": "Hand-written",
        "strobes": {"222": "SOMETHING_ELSE"},
        "liveMetrics": [{"id": "m", "trigger": "ODOR_1_ON", "success": "WATER_POKE_R",
                         "alternate": "WATER_POKE_L"}],
    }), encoding="utf-8")
    loaded = task_profile.load_profile(tmp_path)
    assert loaded.strobes[222] == "LIGHTS_ON"
    assert loaded.live_metrics[0].trigger_code == 101


def test_a_metric_naming_an_unknown_code_is_a_profile_error(tmp_path):
    (tmp_path / "task.json").write_text(json.dumps({
        "taskName": "Bad",
        "liveMetrics": [{"id": "m", "trigger": "NOPE", "success": "WATER_POKE_R",
                         "alternate": "WATER_POKE_L"}],
    }), encoding="utf-8")
    with pytest.raises(task_profile.TaskProfileError, match="NOPE"):
        task_profile.load_profile(tmp_path)


def test_a_snapshot_keeps_the_map_it_was_recorded_with():
    """An embedded profile is the record of what decoded a run, and must not be
    rewritten by a vocabulary edited after the run."""
    snapshot = {"taskName": "Old run", "strobes": {"110": "DUMMY_SOLENOID_CLICK_1"}}
    assert task_profile.parse_profile(snapshot).strobes == {110: "DUMMY_SOLENOID_CLICK_1"}


def test_the_profile_hash_ignores_the_strobe_map_and_the_metric_spelling():
    base = {
        "taskName": "T",
        "liveMetrics": [{"id": "m", "triggerCode": 101, "successCode": 249, "alternateCode": 248}],
    }
    by_number = task_profile.parse_profile({**base, "strobes": {"101": "ODOR_1_ON"}})
    by_name = task_profile.parse_profile(
        {"taskName": "T", "liveMetrics": [
            {"id": "m", "trigger": "ODOR_1_ON", "success": "WATER_POKE_R", "alternate": "WATER_POKE_L"}
        ]},
        vocabulary=registry.vocabulary(),
    )
    assert by_number.strobes != by_name.strobes
    assert task_profile.profile_hash(by_number) == task_profile.profile_hash(by_name)


# --------------------------------------------------------------------------- #
# The v13 re-key
# --------------------------------------------------------------------------- #


def test_v13_rekeys_stored_profiles_and_every_run_follows(tmp_path):
    path = tmp_path / "ephymeris.db"
    db = Database(path)
    db.connect()
    db.close()

    profile = {"taskName": "T", "kind": "behavior", "config": [], "liveMetrics": [],
               "controls": [], "legacyNames": []}
    old_a = json.dumps({**profile, "strobes": {"101": "ODOR_1_ON"}}, sort_keys=True)
    old_b = json.dumps({**profile, "strobes": {"101": "ODOR_1_ON", "222": "LIGHTS_ON"}}, sort_keys=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    for digest, blob, seen in (("aaaa", old_a, "2026-02-01"), ("bbbb", old_b, "2026-01-01")):
        conn.execute(
            "INSERT INTO task_profiles (hash, task_name, kind, profile_json, first_seen_at)"
            " VALUES (?, 'T', 'behavior', ?, ?)", (digest, blob, seen),
        )
    for run, digest in (("r1", "aaaa"), ("r2", "bbbb")):
        conn.execute(
            "INSERT INTO run_metrics_cache (run_id, file_path, profile_hash, scored_profile_hash,"
            " profile_source, codec_version, computed_at, status, summary_json)"
            " VALUES (?, '/x', ?, ?, 'snapshot', 1, 'now', 'ok', '{}')", (run, digest, digest),
        )
    conn.execute("PRAGMA user_version = 12")
    conn.commit()
    conn.close()

    db = Database(path)
    db.connect()
    rows = db.conn.execute("SELECT hash, first_seen_at FROM task_profiles").fetchall()
    cached = db.conn.execute("SELECT DISTINCT profile_hash, scored_profile_hash FROM run_metrics_cache").fetchall()
    db.close()

    expected = task_profile.profile_hash(task_profile.parse_profile(json.loads(old_a)))
    assert [tuple(r) for r in rows] == [(expected, "2026-01-01")]
    assert [tuple(r) for r in cached] == [(expected, expected)]


# --------------------------------------------------------------------------- #
# Usage: firmware and the archive
# --------------------------------------------------------------------------- #


def test_firmware_refs_classify_by_kind_and_ignore_comments_and_generated_headers(tmp_path):
    lib = tmp_path / "libraries" / "BehaviorBox"
    lib.mkdir(parents=True)
    (lib / "BehaviorBox.h").write_text(
        "emitStrobe(c, BF_LIGHTS_ON);\n// BF_IN_A_COMMENT\n/* BF_ALSO_PROSE */\n", encoding="utf-8"
    )
    sketch = tmp_path / "Cat" / "Sk"
    sketch.mkdir(parents=True)
    (sketch / "Sk.ino").write_text("emitStrobe(c, BF_LASER_ON);\n", encoding="utf-8")
    (sketch / "TaskPins.h").write_text("#define BF_EVERYTHING 1\n", encoding="utf-8")
    host_test = lib / "extras" / "host_test"
    host_test.mkdir(parents=True)
    (host_test / "strobe_fixture.h").write_text("#define BF_FIXTURE 1\n", encoding="utf-8")

    refs = firmware_refs([(tmp_path, "sketch")])
    assert [r.kind for r in refs["LIGHTS_ON"]] == ["library"]
    assert [r.kind for r in refs["LASER_ON"]] == ["sketch"]
    assert "IN_A_COMMENT" not in refs and "ALSO_PROSE" not in refs
    assert "EVERYTHING" not in refs
    assert "FIXTURE" not in refs, "a library's host tests are not compiled into a sketch"


def _write_run(folder: Path, name: str, codes: list[int]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps({"rat": name, "ts_data": [[c, i] for i, c in enumerate(codes)]}),
                    encoding="utf-8")
    return path


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


def test_the_archive_scan_finds_codes_in_json_and_orphaned_tsvs(tmp_path, db):
    cohort = tmp_path / "cohort"
    _write_run(cohort / "P" / "S1" / "behavior.json", "rat1", [221, 116, 246])
    tsv_dir = cohort / "P" / "S2" / "behavior.tsv"
    tsv_dir.mkdir(parents=True)
    (tsv_dir / "rat2.tsv").write_text("# rat: rat2\n221\t0\n300\t5\n", encoding="utf-8")

    index = ArchiveScanner(db).scan([str(cohort), str(tmp_path / "gone")])
    assert index.count(116) == 1 and index.count(300) == 1 and index.count(221) == 2
    assert index.files == 2
    assert index.unreachable_roots == [str(tmp_path / "gone")]


def test_a_second_scan_is_answered_from_the_cache(tmp_path, db, monkeypatch):
    cohort = tmp_path / "cohort"
    _write_run(cohort / "P" / "S1" / "behavior.json", "rat1", [116])
    ArchiveScanner(db).scan([str(cohort)])

    from ephymeris_sidecar.analytics import reader

    def explode(_path):  # noqa: ANN001, ANN202
        raise AssertionError("re-read a file whose stat had not changed")

    monkeypatch.setattr(reader, "read_run", explode)
    assert ArchiveScanner(db).scan([str(cohort)]).count(116) == 1


# --------------------------------------------------------------------------- #
# The handlers
# --------------------------------------------------------------------------- #


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "library"
    sketch = root / "Olfactory Behavior" / "GRGL"
    sketch.mkdir(parents=True)
    (sketch / "GRGL.ino").write_text("// root sketch\n", encoding="utf-8")
    return root


@pytest.fixture
def app(tmp_path, db, library, monkeypatch):
    from ephymeris_sidecar import discovery

    monkeypatch.setattr(discovery, "library_root", lambda: (library, "override"))
    events: list[dict] = []
    rebuilds: list[int] = []

    async def broadcast(message: dict) -> None:
        events.append(message)

    async def rescan() -> None:
        rebuilds.append(1)

    async def after_rebuild(_tasks: int, _pinned: int) -> None:
        pass

    vocab_store = strobe_store.VocabularyStore(tmp_path / "data")
    vocab_store.ensure_seeded()
    tasks = task_store_mod.TaskStore(tmp_path / "data", library_root=library)
    cohort_root = tmp_path / "cohort"
    stub = SimpleNamespace(
        vocab_store=vocab_store,
        task_store=tasks,
        strobe_scanner=ArchiveScanner(db),
        _running_session_id=None,
        runner=None,
        server=SimpleNamespace(broadcast=broadcast),
        _cohort_roots=lambda: [str(cohort_root)],
        events=events,
        rebuilds=rebuilds,
        cohort_root=cohort_root,
    )
    stub.rig_definition = RigDefinition(
        hardware=HardwareStore(tmp_path / "data"),
        vocabulary=vocab_store,
        tasks=tasks,
        repin=lambda: 0,
        in_use=lambda: Application._rig_in_use(stub),
        rescan=rescan,
        after_rebuild=after_rebuild,
        broadcast=broadcast,
    )
    for name in (
        "_edit_vocabulary",
        "_strobe_impact",
        "_refuse_unconfirmed",
        "_scan_archive",
        "_strobe_name_arg",
    ):
        setattr(stub, name, getattr(Application, name).__get__(stub))
    return stub


async def call(app, handler: str, **args):  # noqa: ANN001, ANN003, ANN201
    return await getattr(Application, handler)(app, None, None, args, None)


async def test_an_added_code_is_written_installed_rebuilt_and_announced(app):
    reply = await call(app, "_strobes_add", name="LASER_ON", code=300, rationale="Light on.")
    assert {"name": "LASER_ON", "code": 300, "origin": "operator", "rationale": "Light on."} in reply["codes"]
    assert reply["editable"] is True
    assert app.rebuilds == [1]
    assert app.events[-1]["evt"] == "strobes.updated"
    assert registry.vocabulary().code_of("LASER_ON") == 300
    assert "LASER_ON" in app.vocab_store.load_strict()["codes"]


async def test_removing_a_recorded_code_is_refused_and_writes_nothing(app):
    _write_run(app.cohort_root / "P" / "S1" / "behavior.json", "rat1", [116])
    with pytest.raises(CommandError) as refused:
        await call(app, "_strobes_remove", name="ODOR_12_ON", confirm=True)
    assert refused.value.code == "STROBE_IN_RECORDED_SESSION"
    assert refused.value.detail["count"] == 1
    assert "ODOR_12_ON" in app.vocab_store.load_strict()["codes"]
    assert app.rebuilds == []


async def test_removing_an_unrecorded_code_frees_its_number(app):
    reply = await call(app, "_strobes_remove", name="ODOR_12_ON", confirm=False)
    assert any(lo <= 116 <= hi for lo, hi in reply["freeRanges"])


async def test_retiring_a_code_a_saved_task_uses_needs_confirm(app):
    app.task_store.save(presets.instantiate("grgl_2odor", "probe", "Probe"))
    onset = presets.instantiate("grgl_2odor", "probe", "Probe").trials[0].onset_strobe

    usage = await call(app, "_strobes_usage", name=onset)
    assert usage["breaks"] and usage["breaks"][0]["specId"] == "probe"
    assert usage["retireBlocker"] is None

    with pytest.raises(CommandError) as refused:
        await call(app, "_strobes_retire", name=onset, confirm=False)
    assert refused.value.code == "STROBE_WOULD_BREAK_TASKS"

    reply = await call(app, "_strobes_retire", name=onset, confirm=True)
    assert onset in {r["name"] for r in reply["retired"]}


async def test_a_port_slot_code_reports_its_blocker_and_is_refused(app):
    usage = await call(app, "_strobes_usage", name="WATER_POKE_L", scan=True)
    assert usage["portSlot"] == 1 and usage["retireBlocker"] and usage["removeBlocker"]
    assert usage["sessions"]["scanned"]["roots"] == [str(app.cohort_root)]
    with pytest.raises(CommandError) as refused:
        await call(app, "_strobes_retire", name="WATER_POKE_L", confirm=True)
    assert refused.value.code == "STROBE_REQUIRED"


async def test_no_edit_while_a_session_is_set_up(app):
    app._running_session_id = "s1"
    with pytest.raises(CommandError) as refused:
        await call(app, "_strobes_add", name="LASER_ON", code=300, rationale="x")
    assert refused.value.code == "STROBE_SESSION_RUNNING"


async def test_no_edit_while_a_box_runs_a_task_from_debug_mode(app):
    """No session, but a box is running: its sketch was generated from the
    vocabulary an edit would replace."""
    app.runner = SimpleNamespace(running_boxes=lambda: [3])
    with pytest.raises(CommandError) as refused:
        await call(app, "_strobes_add", name="LASER_ON", code=300, rationale="x")
    assert refused.value.code == "STROBE_SESSION_RUNNING"


async def test_a_remove_is_refused_before_its_archive_scan(app, monkeypatch):
    app._running_session_id = "s1"

    async def scan():
        pytest.fail("scanned the archive for an edit that was always going to be refused")

    app._scan_archive = scan
    with pytest.raises(CommandError) as refused:
        await call(app, "_strobes_remove", name="ODOR_12_ON", confirm=True)
    assert refused.value.code == "STROBE_SESSION_RUNNING"


async def test_import_previews_then_applies(app):
    other = strobe_store.add(seed(), "LASER_ON", 300, rationale="theirs")
    preview = await call(app, "_strobes_import", document=other, apply=False)
    assert preview["vocabulary"] is None and preview["plan"]["adds"][0]["name"] == "LASER_ON"
    assert "LASER_ON" not in app.vocab_store.load_strict()["codes"]

    applied = await call(app, "_strobes_import", document=other, apply=True)
    assert any(c["name"] == "LASER_ON" for c in applied["vocabulary"]["codes"])


async def test_export_travels_without_this_machine_s_stamps(app):
    reply = await call(app, "_strobes_export")
    assert reply["filename"].startswith("strobe-vocabulary-") and reply["filename"].endswith(".json")
    assert "seeded_at" not in reply["document"] and "edited_at" not in reply["document"]
    assert strobe_store.validate(reply["document"]) == []


def test_a_legacy_three_column_log_is_read_not_reported_empty(tmp_path, db):
    """The lab's pre-Ephymeris `recovery_tsv/` dialect: a header, CRLF, and a
    name column. Read with this app's two-column rule it holds nothing — and a
    removal check would then pass over a file full of the code."""
    folder = tmp_path / "cohort" / "P" / "S1" / "recovery_tsv"
    folder.mkdir(parents=True)
    (folder / "rat1.tsv").write_bytes(
        b"event_code\tevent_ms\tevent_name\r\n# trial_seed\t935\r\n"
        b"221\t0\tBF_START_SESSION\r\n233\t1500\tBF_LIGHTS_OFF\r\n"
    )
    index = ArchiveScanner(db).scan([str(tmp_path / "cohort")])
    assert index.count(233) == 1 and index.unreadable == 0


def test_a_log_with_lines_it_cannot_read_is_unreadable_not_empty(tmp_path, db):
    folder = tmp_path / "cohort" / "P" / "S1" / "behavior.tsv"
    folder.mkdir(parents=True)
    (folder / "rat1.tsv").write_text("221,0\n233,15\n246,20\n", encoding="utf-8")
    index = ArchiveScanner(db).scan([str(tmp_path / "cohort")])
    assert index.files == 0 and index.unreadable == 1


def test_a_row_cached_by_an_older_reader_is_read_again(tmp_path, db):
    cohort = tmp_path / "cohort"
    path = _write_run(cohort / "P" / "S1" / "behavior.json", "rat1", [233])
    stat = path.stat()
    db.conn.execute(
        "INSERT INTO strobe_scan_cache VALUES (?, ?, ?, '[]')",
        (str(path), stat.st_mtime_ns, stat.st_size),
    )
    assert ArchiveScanner(db).scan([str(cohort)]).count(233) == 1


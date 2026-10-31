"""The channel set, the pin map, and the edge codes a save allocates
(TASKS.md#the-channel-set-and-the-pin-map, TASKS.md#edge-codes).

The channel set says what each channel IS (type, role, its edges and their code
names) and is meant to be shared by the lab; the pin map says where each one is
on this box and never leaves it. Both are new fields BESIDE today's kinds,
slots, wells and onset codes, so the generator is untouched: the proof of that
is the byte-identical regeneration at the bottom of this file.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from ephymeris_sidecar.hardware import service, store
from ephymeris_sidecar.rig import allocation, definition, registry
from ephymeris_sidecar.strobes import store as strobe_store
from ephymeris_sidecar.taskdef import bundled, generate, utility
from tests.fixtures import task_definitions as presets

#: `ChannelMap.content_hash()` of the shipped wiring, as `main` computed it
#: before the channel set existed. It is stamped into every generated header,
#: so a channel-set field leaking into it would rebuild every sketch.
SHIPPED_PINOUT_HASH = "bfa89f7d62bf622f"

NEW_FIELDS = ("type", "role", "active_level", "debounce_ms", "serves", "edges")


@pytest.fixture(autouse=True)
def _shipped_rig_definition():
    registry.set_rig_source(None)
    registry.set_vocabulary_source(None)
    yield
    registry.set_rig_source(None)
    registry.set_vocabulary_source(None)


def legacy(doc: dict) -> dict:
    """The document as a rig saved before the channel set existed: no new fields."""
    out = copy.deepcopy(doc)
    for entry in out["channels"].values():
        for key in NEW_FIELDS:
            entry.pop(key, None)
    return out


def rule_codes(doc: dict) -> set[str]:
    return {p["code"] for p in service.problems_for(doc) if p["code"]}


class NoTasks:
    def list_entries(self):
        return []

    def failures(self, task_id):
        return set()

    def regenerate_all(self) -> int:
        return 0


class Rig:
    def __init__(self, tmp_path) -> None:
        self.events: list[str] = []
        self.vocabulary = strobe_store.VocabularyStore(tmp_path)
        self.vocabulary.ensure_seeded()
        self.hardware = store.HardwareStore(tmp_path)
        self.definition = definition.RigDefinition(
            hardware=self.hardware,
            vocabulary=self.vocabulary,
            tasks=NoTasks(),
            repin=lambda: 0,
            in_use=lambda: False,
            rescan=self._nothing,
            after_rebuild=self._after,
            broadcast=self._broadcast,
        )

    async def _nothing(self) -> None:
        return None

    async def _after(self, tasks: int, pinned: int) -> None:
        return None

    async def _broadcast(self, message) -> None:
        self.events.append(message["evt"])

    def save(self, doc: dict) -> dict:
        return asyncio.run(self.definition.save_wiring(doc, confirm=True))


# --------------------------------------------------------------------------- #
# What a channel declares
# --------------------------------------------------------------------------- #


def test_every_shipped_channel_declares_a_type_and_a_role():
    chans = registry.shipped_channels()
    for c in chans:
        assert c.type in registry.EDGES, c.name
        assert c.role in registry.ROLES, c.name
        assert registry.TYPE_DIRECTION[c.type] == c.direction, c.name


def test_inputs_declare_level_and_debounce_and_a_reward_line_serves_its_well():
    chans = registry.shipped_channels()
    port = chans.get("odor_port")
    assert (port.type, port.role, port.active_level, port.debounce_ms) == (
        "digital_in", "port", "low", 0,
    )
    fluid = chans.get("fluid_2")
    assert (fluid.type, fluid.role, fluid.serves) == ("digital_out", "reward", "right_well")
    assert fluid.active_level is None and fluid.debounce_ms is None
    assert chans.get("vacuum").role == "routing"


def test_a_rig_saved_before_the_channel_set_existed_composes_with_defaults(tmp_path):
    s = store.HardwareStore(tmp_path)
    s.root.mkdir(parents=True)
    s.path.write_text(json.dumps(legacy(store.default_document())), encoding="utf-8")
    loaded = s.load()
    assert loaded["channels"]["left_well"]["type"] == "digital_in"
    assert loaded["channels"]["fluid_0"]["serves"] == "left_well"
    chans = registry.ChannelMap(*registry.split_rig(loaded))
    assert chans.channel_set.content_hash() == registry.shipped_channels().channel_set.content_hash()


# --------------------------------------------------------------------------- #
# The content hash
# --------------------------------------------------------------------------- #


def _set_hash(doc: dict) -> str:
    return registry.ChannelMap(*registry.split_rig(doc)).channel_set.content_hash()


def test_the_channel_set_carries_a_content_hash_over_what_channels_are():
    doc = store.default_document()
    base = _set_hash(doc)
    assert len(base) == 16

    relabelled = copy.deepcopy(doc)
    relabelled["channels"]["odor_port"]["label"] = "nose poke"
    relabelled["channels"]["odor_port"]["rationale"] = "reworded"
    assert _set_hash(relabelled) == base

    repinned = copy.deepcopy(doc)
    repinned["pins"]["odor_port"]["index"] = 12
    assert _set_hash(repinned) == base, "a pin is the local half, never the shared one"

    for field, value in (("role", "cue"), ("debounce_ms", 5), ("active_level", "high"),
                         ("edges", {"enter": "ODOR_PORT_ENTER", "exit": "ODOR_PORT_EXIT"})):
        changed = copy.deepcopy(doc)
        changed["channels"]["odor_port"][field] = value
        assert _set_hash(changed) != base, field


def test_the_new_fields_never_move_the_pinout_hash():
    doc = store.default_document()
    doc["channels"]["odor_port"].update(role="cue", debounce_ms=5,
                                        edges={"enter": "X_ENTER", "exit": "X_EXIT"})
    assert registry.ChannelMap(*registry.split_rig(doc)).content_hash() == SHIPPED_PINOUT_HASH
    assert registry.shipped_channels().content_hash() == SHIPPED_PINOUT_HASH


# --------------------------------------------------------------------------- #
# Allocation
# --------------------------------------------------------------------------- #


def test_every_edge_without_a_code_is_allocated_a_fresh_one_in_declaration_order():
    vocab = registry.vocabulary()
    doc = store.default_document()
    filled, allocations = allocation.plan(doc, vocab)

    expected = [
        (name, edge)
        for name, entry in doc["channels"].items()
        for edge in registry.EDGES[entry["type"]]
    ]
    assert [(a.channel, a.edge) for a in allocations] == expected
    assert allocations[0].name == "ODOR_PORT_ENTER"
    assert {a.name for a in allocations if a.channel == "fluid_2"} == {"FLUID_2_ON", "FLUID_2_OFF"}

    numbers = [a.code for a in allocations]
    assert numbers == sorted(numbers) and len(set(numbers)) == len(numbers)
    assert numbers[0] == vocab.next_free()
    assert all(vocab.is_free(n) for n in numbers)
    assert filled["channels"]["odor_port"]["edges"] == {
        "enter": "ODOR_PORT_ENTER", "exit": "ODOR_PORT_EXIT",
    }
    assert "edges" not in doc["channels"]["odor_port"], "the plan never edits its input"


def test_a_name_ever_issued_to_something_else_gets_a_suffix():
    raw = registry.default_vocabulary_document()
    vocab = registry.Vocabulary(raw)
    free = vocab.next_free()
    raw = strobe_store.add(raw, "VACUUM_ON", free, rationale="Something else entirely.")
    _, allocations = allocation.plan(store.default_document(), registry.Vocabulary(raw))
    names = {a.name for a in allocations if a.channel == "vacuum"}
    assert names == {"VACUUM_ON_2", "VACUUM_OFF"}


def test_an_edge_that_already_names_its_code_allocates_nothing():
    doc = store.default_document()
    filled, _ = allocation.plan(doc, registry.vocabulary())
    again, allocations = allocation.plan(filled, registry.vocabulary())
    assert allocations == [] and again == filled


def test_a_retired_or_deleted_channel_s_code_is_never_reissued(tmp_path):
    rig = Rig(tmp_path)
    doc = store.default_document()
    rig.save(doc)
    raw = rig.vocabulary.load_strict()
    raw = strobe_store.retire(raw, "TRIAL_LIGHT_ON")
    rig.vocabulary.save(raw)
    registry.set_vocabulary_source(rig.vocabulary.load)

    stored = rig.hardware.load()
    stored["channels"]["trial_light"].pop("edges")
    _, allocations = allocation.plan(stored, registry.vocabulary())
    assert [a.name for a in allocations] == ["TRIAL_LIGHT_ON_2"]


# --------------------------------------------------------------------------- #
# The save: one rig definition write
# --------------------------------------------------------------------------- #


def test_the_preview_lists_the_codes_a_save_would_allocate_and_writes_nothing(tmp_path):
    rig = Rig(tmp_path)
    before = rig.vocabulary.path.read_bytes()
    reply = service.preview_payload(rig.hardware, store.default_document(), [])
    names = [a["name"] for a in reply["allocations"]]
    assert names[:2] == ["ODOR_PORT_ENTER", "ODOR_PORT_EXIT"]
    assert set(reply["allocations"][0]) == {"channel", "edge", "name", "code"}
    assert rig.vocabulary.path.read_bytes() == before
    assert not rig.hardware.exists()


def test_a_save_issues_the_codes_and_writes_them_into_the_channel_set(tmp_path):
    rig = Rig(tmp_path)
    preview = service.preview_payload(rig.hardware, store.default_document(), [])
    payload = rig.save(store.default_document())

    assert payload["allocations"] == preview["allocations"]
    vocab = registry.vocabulary()
    for a in payload["allocations"]:
        assert vocab.code_of(a["name"]) == a["code"]
        assert vocab.get(a["name"]).origin == allocation.CHANNEL_SET_ORIGIN
    stored = rig.hardware.load()
    assert stored["channels"]["fluid_2"]["edges"] == {"on": "FLUID_2_ON", "off": "FLUID_2_OFF"}
    assert rig.events == ["strobes.updated", "hardware.updated"]
    assert payload["status"]["channelSetHash"] == registry.channels().channel_set.content_hash()

    rig.events.clear()
    second = rig.save(rig.hardware.load())
    assert second["allocations"] == []
    assert rig.events == ["hardware.updated"]


def test_renaming_a_channel_never_renames_its_codes(tmp_path):
    rig = Rig(tmp_path)
    rig.save(store.default_document())
    doc = rig.hardware.load()
    codes = dict(doc["channels"]["trial_light"]["edges"])

    doc["channels"] = {
        ("house_light" if name == "trial_light" else name): entry
        for name, entry in doc["channels"].items()
    }
    doc["pins"] = {
        ("house_light" if name == "trial_light" else name): entry
        for name, entry in doc["pins"].items()
    }
    payload = rig.save(doc)

    assert payload["allocations"] == []
    assert rig.hardware.load()["channels"]["house_light"]["edges"] == codes
    assert "HOUSE_LIGHT_ON" not in registry.vocabulary()


def test_a_channel_added_again_under_a_freed_name_reclaims_its_own_codes(tmp_path):
    """Reset, then Save, must not issue the whole set a second time."""
    rig = Rig(tmp_path)
    first = rig.save(store.default_document())
    asyncio.run(rig.definition.reset_wiring())
    again = rig.save(store.default_document())
    assert again["allocations"] == []
    assert rig.hardware.load()["channels"]["odor_port"]["edges"]["enter"] == "ODOR_PORT_ENTER"
    assert len(first["allocations"]) == 2 * len(store.default_document()["channels"])


def test_an_unreadable_vocabulary_refuses_a_save_that_needs_codes(tmp_path):
    rig = Rig(tmp_path)
    rig.vocabulary.path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(strobe_store.StrobeRefused):
        rig.save(store.default_document())
    assert not rig.hardware.exists()


# --------------------------------------------------------------------------- #
# RIG107
# --------------------------------------------------------------------------- #


def test_the_shipped_wiring_trips_no_channel_set_rule():
    assert "RIG107" not in rule_codes(store.default_document())


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"type": "digital_out"}, "RIG107"),  # an engagement port that is an output
        ({"edges": {"enter": "ODOR_1_ON", "on": "ODOR_2_ON"}}, "RIG107"),  # `on` is no input edge
        ({"edges": {"enter": "NOT_A_CODE_ANYWHERE"}}, "RIG107"),
        ({"active_level": "high", "type": "digital_out"}, "RIG107"),
        ({"role": "valve"}, None),  # not a role at all: the schema
    ],
)
def test_rig107_a_declaration_that_contradicts_itself_is_reported(change, code):
    doc = store.default_document()
    doc["channels"]["odor_port"].update(change)
    assert code in {p["code"] for p in service.problems_for(doc)}, change


def test_rig107_two_edges_on_one_code_are_reported():
    doc = store.default_document()
    doc["channels"]["odor_port"]["edges"] = {"enter": "ODOR_1_ON"}
    doc["channels"]["left_well"]["edges"] = {"enter": "ODOR_1_ON"}
    assert "RIG107" in rule_codes(doc)


# --------------------------------------------------------------------------- #
# On disk: two documents, one file
# --------------------------------------------------------------------------- #


def test_a_save_writes_both_documents_into_one_file(tmp_path):
    s = store.HardwareStore(tmp_path)
    stored = s.save(store.default_document())
    on_disk = json.loads(s.path.read_text(encoding="utf-8"))
    assert s.path.name == store.WIRING_FILENAME
    assert on_disk["channels"] == stored["channels"] and on_disk["pins"] == stored["pins"]
    channel_set, pin_map = store.split(s.load())
    assert "pins" not in channel_set and "channels" not in pin_map
    assert s.load() == stored


def _legacy_rig_json(s: store.HardwareStore, doc: dict) -> None:
    s.root.mkdir(parents=True, exist_ok=True)
    s.legacy_rig_path.write_text(json.dumps(doc), encoding="utf-8")


def _main_era_pair(s: store.HardwareStore, doc: dict, *, torn: bool = False) -> None:
    """What `main` wrote between #123 and this fix: two files, the pin map
    naming its channel set by a digest that included `edited_at`."""
    doc = {**doc, "edited_at": "2026-10-31T05:00:00Z"}
    channel_set, pin_map = store.split(doc)
    pin_map["channel_set_digest"] = store.legacy_pair_digest(channel_set)
    if torn:
        channel_set = copy.deepcopy(channel_set)
        channel_set["channels"]["left_well"]["port_slot"] = 2
    s.root.mkdir(parents=True, exist_ok=True)
    s.channel_set_path.write_text(json.dumps(channel_set), encoding="utf-8")
    s.pin_map_path.write_text(json.dumps(pin_map), encoding="utf-8")


def test_a_rig_saved_as_rig_json_migrates_losslessly(tmp_path):
    s = store.HardwareStore(tmp_path)
    doc = store.default_document()
    doc["pins"]["left_well"]["index"] = 12
    _legacy_rig_json(s, doc)
    before = s.load()
    assert before["pins"]["left_well"]["index"] == 12 and s.load_problems() == []

    s.save(before)
    assert not s.legacy_rig_path.exists()
    after = s.load()
    assert after["channels"] == before["channels"] and after["pins"] == before["pins"]


def test_a_main_era_pair_migrates_losslessly(tmp_path):
    s = store.HardwareStore(tmp_path)
    doc = store.default_document()
    doc["pins"]["left_well"]["index"] = 12
    doc["channels"]["odor_port"]["label"] = "nose poke"
    _main_era_pair(s, doc)
    before = s.load()
    assert before["pins"]["left_well"]["index"] == 12
    assert before["channels"]["odor_port"]["label"] == "nose poke"

    s.save(before)
    assert not (s.channel_set_path.exists() or s.pin_map_path.exists())
    after = s.load()
    assert after["channels"] == before["channels"] and after["pins"] == before["pins"]


def test_a_torn_main_era_pair_blocks_rather_than_loading(tmp_path):
    s = store.HardwareStore(tmp_path)
    _main_era_pair(s, store.default_document(), torn=True)
    assert s.load() is None
    assert s.load_problems()


def test_the_one_file_wins_over_anything_older_left_beside_it(tmp_path):
    """A migrating save writes the file first and deletes the old ones after,
    so a stop in between must leave the new wiring in force."""
    s = store.HardwareStore(tmp_path)
    new = store.default_document()
    new["pins"]["left_well"]["index"] = 12
    s.save(new)
    _main_era_pair(s, store.default_document())
    _legacy_rig_json(s, store.default_document())
    assert s.load()["pins"]["left_well"]["index"] == 12


def test_reset_removes_every_stored_wiring(tmp_path):
    s = store.HardwareStore(tmp_path)
    s.save(store.default_document())
    _main_era_pair(s, store.default_document())
    _legacy_rig_json(s, store.default_document())
    s.reset()
    assert not s.exists()
    assert s.load() is None and s.load_problems() == []


# --------------------------------------------------------------------------- #
# Every saved task and bundled sketch regenerates as before
# --------------------------------------------------------------------------- #


def _every_generated_file() -> dict[str, str]:
    out: dict[str, str] = {}
    for preset in presets.PRESETS:
        task = presets.instantiate(preset["id"], f"t_{preset['id']}")
        out[f"{preset['id']}/TaskPins.h"] = generate.task_pins_h(task)
        out[f"{preset['id']}/TaskTrials.h"] = generate.task_trials_h(task)
        out[f"{preset['id']}/task.json"] = json.dumps(generate.profile_json(task), sort_keys=True)
    from ephymeris_sidecar import discovery

    for sketch in discovery.discover().sketches:
        folder = Path(sketch.path)
        if sketch.source != "bundled" or not bundled.wants_pinning(folder):
            continue
        out[f"{sketch.name}/TaskPins.h"] = generate.bundled_pins_h(sketch.name)
        if utility.wants_utility(folder):
            out[f"{sketch.name}/UtilityChannels.h"] = utility.utility_channels_h(sketch.name)
            template = json.loads((folder / "task.json").read_text(encoding="utf-8"))
            out[f"{sketch.name}/task.json"] = json.dumps(
                utility.utility_profile(template), sort_keys=True
            )
    return out


def test_the_channel_set_fields_change_no_generated_byte():
    """Expand only: every new field set, and every header byte-identical to a
    rig that has none of them -- hash stamps included."""
    expanded = store.default_document()
    expanded, _ = allocation.plan(expanded, registry.vocabulary())
    for entry in expanded["channels"].values():
        if entry["type"] == "digital_in":
            entry["debounce_ms"] = 3

    registry.set_rig_source(lambda: legacy(expanded))
    before = _every_generated_file()
    registry.set_rig_source(lambda: expanded)
    after = _every_generated_file()

    assert len(before) > len(presets.PRESETS)
    assert before == after


def test_after_allocation_a_header_differs_only_by_the_new_codes_and_the_stamp(tmp_path):
    before = _every_generated_file()
    rig = Rig(tmp_path)
    payload = rig.save(store.default_document())
    after = _every_generated_file()
    issued = {f"#define BF_{a['name']} {a['code']}" for a in payload["allocations"]}

    assert before.keys() == after.keys()
    for path in before:
        old = before[path].splitlines()
        new = after[path].splitlines()
        removed = [line for line in old if line not in new]
        added = [line for line in new if line not in old]
        assert all("vocabulary" in line.lower() or "Strobes:" in line for line in removed), (path, removed)
        assert all(line in issued or "vocabulary" in line.lower() or "Strobes:" in line
                   for line in added), (path, added)


# --------------------------------------------------------------------------- #
# A save commits whole or not at all; stored wiring that will not load blocks
# --------------------------------------------------------------------------- #


def _swapped_ports() -> dict:
    """Left and right swapped in BOTH halves: the slots in the channel set and
    the pins in the pin map. Either half alone records a left poke under the
    right family -- the torn pair round 1's reviewer built."""
    doc = store.default_document()
    left, right = doc["channels"]["left_well"], doc["channels"]["right_well"]
    left["port_slot"], right["port_slot"] = right["port_slot"], left["port_slot"]
    lp, rp = doc["pins"]["left_well"], doc["pins"]["right_well"]
    lp["index"], rp["index"] = rp["index"], lp["index"]
    return doc


def _fail_replacing(monkeypatch, target_name: str) -> None:
    real = store.os.replace

    def replace(src, dst):
        if Path(dst).name == target_name:
            raise PermissionError(f"{target_name} is held open")
        return real(src, dst)

    monkeypatch.setattr(store.os, "replace", replace)


@pytest.mark.parametrize("step", ["write", "fsync", "replace", "directory"])
def test_a_failure_at_any_write_step_never_leaves_a_torn_or_lost_wiring(tmp_path, monkeypatch, step):
    s = store.HardwareStore(tmp_path)
    s.save(store.default_document())
    before = s.load()
    new = _swapped_ports()
    fsyncs = {"n": 0}

    if step == "write":
        def boom(fd, data):
            raise OSError("disk full")
        monkeypatch.setattr(store.os, "write", boom)
    elif step == "fsync":
        def boom(fd):
            raise OSError("fsync failed")
        monkeypatch.setattr(store.os, "fsync", boom)
    elif step == "replace":
        _fail_replacing(monkeypatch, store.WIRING_FILENAME)
    else:
        real_fsync = store.os.fsync

        def boom(fd):
            fsyncs["n"] += 1
            if fsyncs["n"] == 2:  # the file's fsync passes; the directory's fails
                raise OSError("directory fsync failed")
            return real_fsync(fd)
        monkeypatch.setattr(store.os, "fsync", boom)

    if step == "directory" and store.os.name == "nt":
        pytest.skip("Windows cannot fsync a directory")
    with pytest.raises(OSError):
        s.save(new)
    monkeypatch.undo()

    after = s.load()
    assert s.load_problems() == []
    whole = [(after["channels"], after["pins"])]
    assert whole[0] in [(before["channels"], before["pins"]), (new["channels"], new["pins"])]
    if step != "directory":
        assert (after["channels"], after["pins"]) == (before["channels"], before["pins"])
    assert not list(s.root.glob("*.part")), "a failed save leaves nothing staged behind"


def test_a_save_fsyncs_the_file_and_the_folder(tmp_path, monkeypatch):
    s = store.HardwareStore(tmp_path)
    synced: list[int] = []
    real = store.os.fsync
    monkeypatch.setattr(store.os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])
    s.save(store.default_document())
    assert len(synced) == (1 if store.os.name == "nt" else 2)


def test_two_failed_saves_then_a_good_one_lose_nothing(tmp_path, monkeypatch):
    """Round 2's commit record could be deleted by the next save. There is no
    record now: every save is whole or absent."""
    s = store.HardwareStore(tmp_path)
    s.save(store.default_document())
    _fail_replacing(monkeypatch, store.WIRING_FILENAME)
    for _ in range(2):
        with pytest.raises(PermissionError):
            s.save(_swapped_ports())
    monkeypatch.undo()
    s.save(_swapped_ports())
    assert s.load()["channels"]["left_well"]["port_slot"] == 2
    assert s.load()["pins"]["left_well"]["index"] == 3


def test_an_identical_copy_from_another_machine_loads_and_compares_equal(tmp_path):
    a = store.HardwareStore(tmp_path / "a")
    b = store.HardwareStore(tmp_path / "b")
    doc = _swapped_ports()
    a.save(doc)
    copied = json.loads(a.path.read_text(encoding="utf-8"))
    copied["edited_at"] = "2020-01-01T00:00:00Z"
    b.root.mkdir(parents=True)
    b.path.write_text(json.dumps(copied), encoding="utf-8")

    assert b.load_problems() == []
    composed = [registry.ChannelMap(*registry.split_rig(x.load())) for x in (a, b)]
    assert composed[0].content_hash() == composed[1].content_hash()
    assert composed[0].channel_set.content_hash() == composed[1].channel_set.content_hash()


def test_a_hand_edited_label_still_loads(tmp_path):
    s = store.HardwareStore(tmp_path)
    s.save(_swapped_ports())
    doc = json.loads(s.path.read_text(encoding="utf-8"))
    doc["channels"]["right_well"]["label"] = "right"
    s.path.write_text(json.dumps(doc), encoding="utf-8")
    assert s.load_problems() == []
    assert s.load()["pins"]["right_well"]["index"] == 4


@pytest.mark.parametrize(
    "damage",
    [
        lambda text: text[: len(text) // 2],  # cut off mid-write by something else
        lambda text: text.replace('"index": 4', '"index": "four"', 1),  # hand-edited out of shape
        lambda text: "[]",
    ],
)
def test_stored_wiring_that_will_not_load_is_a_problem_never_the_shipped_pins(tmp_path, damage):
    rig = Rig(tmp_path)
    rig.save(_swapped_ports())
    rig.hardware.path.write_text(damage(rig.hardware.path.read_text(encoding="utf-8")), encoding="utf-8")
    registry.set_rig_source(rig.hardware.load)

    assert rig.hardware.load() is None
    problem = rig.definition.wiring_problem()
    assert problem and "did not load" in problem
    payload = service.document_payload(rig.hardware)
    assert payload["problems"][0]["location"] == store.WIRING_FILENAME
    assert payload["status"]["custom"] is True, "Reset must stay reachable"


def test_a_parseable_but_broken_wiring_is_what_hardware_get_shows(tmp_path):
    s = store.HardwareStore(tmp_path)
    s.save(_swapped_ports())
    doc = json.loads(s.path.read_text(encoding="utf-8"))
    doc["pins"]["left_well"]["index"] = "three"
    s.path.write_text(json.dumps(doc), encoding="utf-8")
    payload = service.document_payload(s)
    assert payload["document"]["pins"]["left_well"]["index"] == "three"
    assert payload["document"]["channels"]["left_well"]["port_slot"] == 2


def test_a_wiring_save_that_fails_after_issuing_codes_still_rebuilds(tmp_path, monkeypatch):
    """The codes stay (append only); the rebuild that every vocabulary edit
    owes the generated folders still runs, and the next save reclaims them."""
    rig = Rig(tmp_path)
    rebuilt: list[int] = []
    rig.definition._tasks.regenerate_all = lambda: rebuilt.append(1) or 0
    _fail_replacing(monkeypatch, store.WIRING_FILENAME)
    with pytest.raises(PermissionError):
        rig.save(store.default_document())
    monkeypatch.undo()

    assert "ODOR_PORT_ENTER" in registry.vocabulary()
    assert rebuilt and rig.events == ["strobes.updated"]
    assert not rig.hardware.exists()
    assert rig.save(store.default_document())["allocations"] == []


def test_a_code_is_reclaimed_only_by_a_channel_of_the_same_kind_and_role(tmp_path):
    rig = Rig(tmp_path)
    doc = store.default_document()
    rig.save(doc)
    stored = rig.hardware.load()
    issued = stored["channels"]["fluid_1"]["edges"]

    # fluid_1 deleted, then a cue added back under its name.
    stored["channels"]["fluid_1"] = {
        "kind": "cue", "label": "fluid 1", "type": "digital_out", "role": "cue",
    }
    stored["channels"]["fluid_0"].pop("well")  # keep RIG rules about wells out of it
    _, allocations = allocation.plan(stored, registry.vocabulary())
    assert [a.name for a in allocations] == ["FLUID_1_ON_2", "FLUID_1_OFF_2"]

    # Back as a reward line again: its own codes return.
    stored["channels"]["fluid_1"] = {
        "kind": "reward", "label": "fluid 1", "well": "left_well",
        "type": "digital_out", "role": "reward", "serves": "left_well",
    }
    filled, allocations = allocation.plan(stored, registry.vocabulary())
    assert allocations == [] and filled["channels"]["fluid_1"]["edges"] == issued

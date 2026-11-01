"""Moving a task between machines (TASKS.md#moving-a-task-between-machines).

A task exported on one lab machine imports on the other, where it compiles
against that machine's pins and the shared channel set. The file carries the
definition verbatim, the channels it names and the number of each code it
strobes, never a pin. An import whose channels or code numbers disagree with
this machine's is refused whole, naming each difference, and writes nothing.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from ephymeris_sidecar.hardware import store as rig_store
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.taskdef import transfer
from ephymeris_sidecar.taskdef.model import TaskDefinition, TaskDefinitionError
from ephymeris_sidecar.taskdef.store import TaskStore
from tests.fixtures import spine as fixture
from tests.live_sidecar import Refused, live_sidecar

FIRMWARE = Path(__file__).resolve().parents[2] / "firmware"


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


def tracer(**edits) -> dict:
    return fixture.tracer(**edits)


def export(document: dict | None = None) -> dict:
    return transfer.export_document(document or tracer(), registry.channels(), registry.vocabulary())


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def test_the_export_carries_the_definition_verbatim_and_the_channels_it_names():
    raw = tracer()
    # A field this build's model does not know: another build's contingency map.
    raw["rows"][0]["contingency"] = {"poke": {"class": "correct", "line": "reward"}}
    raw["futureKey"] = [1, {"x": None}]

    exported = export(raw)

    assert exported["task_export_version"] == 1
    assert exported["definition"] == raw
    # In this machine's declaration order, not the row's binding order.
    assert list(exported["channels"]) == ["odor_port", "trial_light", "odor_line_1", "fluid_2"]
    assert exported["channels"]["fluid_2"] == {
        "kind": "reward", "type": "digital_out", "role": "reward", "serves": "right_well",
        "well": "right_well", "edges": {"on": "FLUID_2_ON", "off": "FLUID_2_OFF"},
    }
    assert exported["channel_set_hash"] == registry.channel_set().content_hash()
    assert exported["channel_set_hash_version"] == registry.CHANNEL_SET_HASH_VERSION


def test_the_export_numbers_every_code_the_task_strobes_from_this_vocabulary():
    vocab = registry.vocabulary()
    names = {
        # the edges of the four channels the tracer binds
        "ODOR_PORT_ENTER", "ODOR_PORT_EXIT", "TRIAL_LIGHT_ON", "TRIAL_LIGHT_OFF",
        "ODOR_LINE_1_ON", "ODOR_LINE_1_OFF", "FLUID_2_ON", "FLUID_2_OFF",
        # odor_line_1's declared onset, and a spine's structural codes
        "ODOR_1_ON", "START_SESSION", "TRIAL_START", "END_SESSION",
    }
    assert export()["codes"] == {name: vocab.code_of(name) for name in sorted(names)}


def test_a_task_naming_a_code_this_vocabulary_lacks_is_not_exported():
    def edit(rig: dict) -> None:
        rig["channels"]["fluid_2"]["edges"]["on"] = "NO_SUCH_CODE"

    rig_with(edit)
    with pytest.raises(transfer.TaskTransferInvalid, match="NO_SUCH_CODE"):
        export()


# --------------------------------------------------------------------------- #
# Import: the plan
# --------------------------------------------------------------------------- #


def plan(file: dict, tmp_path, *, bundled: frozenset[str] = frozenset()) -> transfer.ImportPlan:
    return transfer.plan_import(
        file,
        channels=registry.channels(),
        vocabulary=registry.vocabulary(),
        tasks=TaskStore(tmp_path, library_root=FIRMWARE),
        bundled_named=lambda name: name in bundled,
    )


def rig_with(edit=None, vocabulary=None) -> None:  # noqa: ANN001
    """Put in force the issued rig after `edit(rig)` and `vocabulary(vocab)`:
    another machine."""
    rig, vocab = fixture.issued_rig()
    if edit:
        edit(rig)
    if vocabulary:
        vocabulary(vocab)
    fixture.install(rig, vocab)


def without(name: str):  # noqa: ANN201
    def edit(rig: dict) -> None:
        del rig["channels"][name]
        del rig["pins"][name]
    return edit


def test_an_import_onto_the_same_channel_set_is_clean(tmp_path):
    planned = plan(export(), tmp_path)
    assert planned.conflicts == []
    assert planned.same_channel_set and not planned.replaces and not planned.identical
    assert planned.task_id == "spine_tracer" and planned.name == "Spine Tracer"


def test_a_channel_this_rig_lacks_is_named(tmp_path):
    file = export()
    rig_with(without("odor_line_1"))
    planned = plan(file, tmp_path)
    assert planned.conflicts == [{
        "kind": "not_here",
        "channel": "odor_line_1",
        "message": "odor_line_1 is named by that task and not on this rig, so it has no pin here.",
    }]
    assert not planned.same_channel_set


def test_a_channel_that_differs_names_each_field_and_both_sides(tmp_path):
    file = export()

    def edit(rig: dict) -> None:
        rig["channels"]["fluid_2"]["role"] = "routing"
        rig["channels"]["fluid_2"]["edges"] = {"on": "FLUID_3_ON", "off": "FLUID_2_OFF"}
        rig["channels"]["fluid_2"]["label"] = "Another label entirely"  # not compared

    rig_with(edit)
    [conflict] = plan(file, tmp_path).conflicts
    assert conflict["kind"] == "differs" and conflict["channel"] == "fluid_2"
    assert conflict["message"] == (
        "fluid_2 differs: role is routing here and reward in that task's channel set; "
        "edges.on is FLUID_3_ON here and FLUID_2_ON in that task's channel set."
    )


def test_a_channel_of_another_kind_is_named(tmp_path):
    file = export()

    def edit(rig: dict) -> None:
        rig["channels"]["odor_line_1"]["kind"] = "cue"
        rig["channels"]["odor_line_1"]["role"] = "cue"

    rig_with(edit)
    [conflict] = plan(file, tmp_path).conflicts
    assert conflict["kind"] == "differs" and conflict["channel"] == "odor_line_1"
    assert conflict["message"].startswith(
        "odor_line_1 differs: kind is cue here and emitter in that task's channel set; "
        "role is cue here and stimulus in that task's channel set"
    )


def test_channels_declared_in_another_order_are_an_order_conflict(tmp_path):
    file = export()

    def edit(rig: dict) -> None:
        # trial_light moved ahead of odor_port; no channel is added or lost.
        channels = rig["channels"]
        rig["channels"] = {"trial_light": channels.pop("trial_light"), **channels}

    rig_with(edit)
    conflicts = plan(file, tmp_path).conflicts
    assert [(c["kind"], c["channel"]) for c in conflicts] == [
        ("order", "trial_light"), ("order", "odor_port"),
    ]
    assert conflicts[0]["message"] == (
        "trial_light is the task's channel 1 here and 2 in that task's channel set, counting "
        "only the 4 channels both have. Declaration order is the odor index, so the two must "
        "list their channels in one order."
    )


def test_a_difference_in_a_channel_the_task_does_not_name_is_no_conflict(tmp_path):
    file = export()
    rig_with(without("odor_line_12"))
    planned = plan(file, tmp_path)
    assert planned.conflicts == [] and not planned.same_channel_set


def test_a_code_numbered_differently_here_is_a_code_conflict_naming_both_numbers(tmp_path):
    file = export()
    here = file["codes"]["FLUID_2_ON"]
    file["codes"]["FLUID_2_ON"] = 999  # the other machine's number for it
    [conflict] = plan(file, tmp_path).conflicts
    assert conflict == {
        "kind": "code",
        "channel": None,
        "message": f"FLUID_2_ON is code 999 in that task's vocabulary and {here} here. "
        "Import the other machine's channel set first, so both give it one number.",
    }


def test_a_code_this_vocabulary_lacks_is_a_code_conflict(tmp_path):
    file = export()
    number = file["codes"]["TRIAL_START"]

    def drop(vocab: dict) -> None:
        del vocab["codes"]["TRIAL_START"]

    rig_with(vocabulary=drop)
    conflicts = [c for c in plan(file, tmp_path).conflicts if c["kind"] == "code"]
    assert [c["message"] for c in conflicts] == [
        f"TRIAL_START is code {number} in that task's vocabulary and not a live code here. "
        "Import the other machine's channel set first, so both give it one number.",
    ]


def test_a_code_the_task_would_strobe_here_and_the_file_does_not_number_is_a_conflict(tmp_path):
    file = export()
    del file["codes"]["END_SESSION"]
    [conflict] = plan(file, tmp_path).conflicts
    assert conflict["kind"] == "code"
    assert conflict["message"].startswith(
        "That task would strobe END_SESSION here, and the file gives it no number."
    )


def test_a_name_another_task_or_a_shipped_sketch_has_is_refused(tmp_path):
    TaskStore(tmp_path, library_root=FIRMWARE).save_document(tracer(id="mine", name="spine TRACER"))
    conflicts = plan(export(), tmp_path, bundled=frozenset({"Spine Tracer"})).conflicts
    assert [c["kind"] for c in conflicts] == ["bundled_name", "name_taken"]
    assert conflicts[1]["message"].startswith("Another task here is already called 'spine TRACER'.")


def test_a_stored_file_under_the_same_id_that_will_not_read_is_still_replaced_with_confirm(tmp_path):
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "spine_tracer.json").write_text("{ not json", encoding="utf-8")
    planned = plan(export(), tmp_path)
    assert planned.replaces and planned.replaces_unreadable and planned.replaces_name is None


def test_the_fields_a_channel_carries_are_the_fields_the_channel_set_hash_covers():
    """`CHANNEL_FIELDS` restates what `ChannelSet.content_hash` covers: a field
    the hash gains must travel, or two machines agreeing on every carried
    field could still hash apart."""
    base = registry.channels().get("odor_port")
    changed = {
        "name": "other", "index": 99, "direction": "out", "kind": "response",
        "watch_bit": 7, "well": "left_well", "port_slot": 2, "onset_strobe": "ODOR_9_ON",
        "rationale": "x", "label": "x", "pin_note": "x", "pin_source": "x",
        "type": "digital_out", "role": "cue", "active_level": "high", "debounce_ms": 9,
        "serves": "left_well", "edges": (("enter", "OTHER"),),
    }
    assert set(changed) == {f.name for f in dataclasses.fields(registry.Channel)}, (
        "a Channel field was added: give it a changed value here"
    )

    def hashed(field: str) -> bool:
        other = dataclasses.replace(base, **{field: changed[field]})
        return registry.ChannelSet([other]).content_hash() != registry.ChannelSet([base]).content_hash()

    assert {f for f in changed if hashed(f)} == {"name", *transfer.CHANNEL_FIELDS}


def test_a_task_saved_here_under_the_same_id_is_replaced_and_an_identical_one_is_not(tmp_path):
    store = TaskStore(tmp_path, library_root=FIRMWARE)
    store.save_document(tracer(notes="an older version"))
    store.save_document(tracer(name="Old Tracer", notes="an older version"))
    planned = plan(export(), tmp_path)
    assert planned.conflicts == [] and planned.replaces and not planned.identical
    assert planned.replaces_name == "Old Tracer"

    store.save_document(tracer())
    planned = plan(export(), tmp_path)
    assert planned.replaces and planned.identical


@pytest.mark.parametrize(
    ("edit", "says"),
    [
        (lambda f: f.update(task_export_version=2), "It is version 2"),
        (lambda f: f.pop("codes"), "It needs a definition"),
        (lambda f: f["definition"].update(id="Not An Id"), "will not read"),
        (lambda f: f["channels"].pop("fluid_2"), "names fluid_2, which the file does not describe"),
        (lambda f: f.update(channel_set_hash_version=9), "made by a newer build"),
    ],
)
def test_a_file_that_is_not_an_export_is_refused(tmp_path, edit, says):
    file = export()
    edit(file)
    with pytest.raises(transfer.TaskTransferInvalid, match=says):
        plan(file, tmp_path)



# --------------------------------------------------------------------------- #
# Two machines, over the wire
# --------------------------------------------------------------------------- #


FOLDER = Path("tasks") / "Tasks" / "Spine Tracer"


def newer_build_tracer() -> dict:
    """The tracer as a newer build stores it, with fields this one does not know."""
    raw = tracer()
    raw["rows"][0]["contingency"] = {"poke": {"class": "correct", "line": "reward"}}
    raw["futureKey"] = [1, {"x": None}]
    return raw


def tree(root: Path) -> dict[str, bytes | None]:
    """Every path under `root`, with each file's bytes (None for a folder)."""
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    } if root.exists() else {}


def defines(header: str) -> dict[str, int]:
    return {m[1]: int(m[2]) for m in re.finditer(r"^#define (BF_\w+) (\d+)$", header, re.M)}


def swapped_pins() -> dict:
    """The shipped wiring with odor lines 1 and 2 on each other's pins."""
    doc = rig_store.default_document()
    pins = doc["pins"]
    pins["odor_line_1"]["index"], pins["odor_line_2"]["index"] = (
        pins["odor_line_2"]["index"], pins["odor_line_1"]["index"],
    )
    return doc


async def machine_a_exports(tmp_path) -> tuple[dict, dict, Path]:
    """Machine A: its own wiring saved, the tracer stored by a newer build.
    Returns (A's channel set export, A's task export, A's data dir)."""
    data = tmp_path / "a"
    (data / "tasks").mkdir(parents=True)
    # As the app stores one (`TaskStore`), so the bytes can be compared on B.
    (data / "tasks" / "spine_tracer.json").write_text(
        json.dumps(newer_build_tracer(), indent=2) + "\n", encoding="utf-8"
    )
    async with live_sidecar(data) as a:
        await a.call("hardware.save", document=rig_store.default_document(), confirm=True)
        channel_set = (await a.call("hardware.exportChannelSet"))["document"]
        task = await a.call("tasks.export", taskId="spine_tracer")
    assert task["filename"].startswith("task-spine_tracer-") and task["filename"].endswith(".json")
    return channel_set, task["document"], data


async def test_a_task_exported_on_one_machine_strobes_identical_codes_on_another(tmp_path):
    channel_set, exported, a = await machine_a_exports(tmp_path)

    async with live_sidecar(tmp_path / "b") as b:
        await b.call("hardware.save", document=swapped_pins(), confirm=True)
        await b.call("hardware.importChannelSet", document=channel_set, apply=True, confirm=True)
        plan = (await b.call("tasks.import", document=exported, apply=False))["plan"]
        assert plan["conflicts"] == [] and plan["sameChannelSet"] and not plan["replaces"]
        assert not (tmp_path / "b" / "tasks" / "spine_tracer.json").exists(), "a plan wrote"

        reply = await b.call("tasks.import", document=exported, apply=True)
        assert reply["applied"] is True
        assert [t["id"] for t in (await b.call("tasks.list"))["tasks"]] == ["spine_tracer"]
        assert b.latest("tasks.updated")["tasks"][0]["id"] == "spine_tracer"

    b_dir = tmp_path / "b"
    # The definition arrived verbatim, byte for byte, fields this build does
    # not know included.
    stored = "tasks/spine_tracer.json"
    assert (b_dir / stored).read_bytes() == (a / stored).read_bytes()
    assert json.loads((b_dir / stored).read_text()) == newer_build_tracer()
    # Identical codes: every code number compiled in, and the profile with the
    # spine snapshot replay reads code names from, are the same on both...
    a_pins = (a / FOLDER / "TaskPins.h").read_text()
    b_pins = (b_dir / FOLDER / "TaskPins.h").read_text()
    assert defines(a_pins) == defines(b_pins) and "BF_FLUID_2_ON" in defines(a_pins)
    a_profile = json.loads((a / FOLDER / "task.json").read_text())
    assert a_profile == json.loads((b_dir / FOLDER / "task.json").read_text())
    assert a_profile["spine"]["outputs"][1]["channel"] == "odor_line_1"
    # ...on the other machine's own pins.
    assert (a / FOLDER / "TaskSpine.h").read_text() != (b_dir / FOLDER / "TaskSpine.h").read_text()


async def test_an_import_naming_a_missing_or_differing_channel_writes_nothing_and_says_why(tmp_path):
    _channel_set, exported, _a = await machine_a_exports(tmp_path)

    b_dir = tmp_path / "b"
    # B already has a task of its own, so "nothing written" has bytes to keep.
    (b_dir / "tasks").mkdir(parents=True)
    (b_dir / "tasks" / "b_own.json").write_text(
        json.dumps(tracer(id="b_own", name="B Own", rows=[])), encoding="utf-8"
    )
    async with live_sidecar(b_dir) as b:
        doc = rig_store.default_document()
        del doc["channels"]["odor_line_1"], doc["pins"]["odor_line_1"]
        doc["channels"]["fluid_2"]["role"] = "routing"
        await b.call("hardware.save", document=doc, confirm=True)
        before = tree(b_dir / "tasks")

        plan = (await b.call("tasks.import", document=exported, apply=False))["plan"]
        with pytest.raises(Refused) as refused:
            await b.call("tasks.import", document=exported, apply=True, confirm=True)

    assert refused.value.code == "TASK_IMPORT_CONFLICT"
    named = {(c["kind"], c["channel"]): c["message"] for c in refused.value.detail["conflicts"]}
    assert named[("not_here", "odor_line_1")] == (
        "odor_line_1 is named by that task and not on this rig, so it has no pin here."
    )
    assert named[("differs", "fluid_2")].startswith(
        "fluid_2 differs: role is routing here and reward in that task's channel set"
    )
    assert refused.value.detail["conflicts"] == plan["conflicts"]
    assert "odor_line_1" in refused.value.message
    assert tree(b_dir / "tasks") == before and before  # every path and every byte
    assert not (b_dir / "tasks" / "spine_tracer.json").exists()


async def test_replacing_a_saved_task_needs_confirm(tmp_path):
    _channel_set, exported, a = await machine_a_exports(tmp_path)
    async with live_sidecar(a) as again:  # the same machine, importing its own task
        same = await again.call("tasks.import", document=exported, apply=True)
        assert same["plan"]["identical"] and same["applied"] is False

        exported["definition"]["notes"] = "changed on the other machine"
        with pytest.raises(Refused) as refused:
            await again.call("tasks.import", document=exported, apply=True)
        assert refused.value.code == "TASK_IMPORT_REPLACES"
        assert "notes" not in json.loads((a / "tasks" / "spine_tracer.json").read_text())

        replaced = await again.call("tasks.import", document=exported, apply=True, confirm=True)
        assert replaced["applied"] and replaced["plan"]["replaces"]
    stored = json.loads((a / "tasks" / "spine_tracer.json").read_text())
    assert stored["notes"] == "changed on the other machine" and stored["futureKey"] == [1, {"x": None}]


async def test_a_stored_task_that_will_not_read_is_not_found_for_export(tmp_path):
    (tmp_path / "b" / "tasks").mkdir(parents=True)
    (tmp_path / "b" / "tasks" / "broken.json").write_text('{"id": "Not An Id"}', encoding="utf-8")
    async with live_sidecar(tmp_path / "b") as b:
        await b.call("hardware.save", document=rig_store.default_document(), confirm=True)
        with pytest.raises(Refused) as refused:
            await b.call("tasks.export", taskId="broken")
    assert refused.value.code == "TASK_NOT_FOUND"


async def test_a_file_that_is_not_an_export_is_task_transfer_invalid(tmp_path):
    async with live_sidecar(tmp_path / "b") as b:
        with pytest.raises(Refused) as refused:
            await b.call("tasks.import", document={"x": 1}, apply=False)
    assert refused.value.code == "TASK_TRANSFER_INVALID"



@pytest.mark.parametrize(
    "category",
    ["../../victim", "/tmp/victim", "C:\\victim", "C:victim", "a\\..\\..\\victim", "a/b", "..", "."],
)
def test_a_category_that_is_not_one_plain_folder_name_is_refused_and_nothing_written(tmp_path, category):
    root = tmp_path / "data"
    with pytest.raises(transfer.TaskTransferInvalid, match="category"):
        export(tracer(category=category))

    file = export()
    file["definition"]["category"] = category
    with pytest.raises(transfer.TaskTransferInvalid, match="category"):
        plan(file, root)

    store = TaskStore(root, library_root=FIRMWARE)
    with pytest.raises(TaskDefinitionError, match="category"):
        store.save_document(tracer(category=category))
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == []


def test_a_sketch_folder_outside_the_tasks_root_is_never_touched(tmp_path):
    """Belt and braces under the parse: a definition built in code, never
    parsed, still cannot send a write or a delete outside `tasks/`."""
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("mine", encoding="utf-8")
    store = TaskStore(tmp_path / "data", library_root=FIRMWARE)
    escaping = dataclasses.replace(TaskDefinition.from_json(tracer()), category="../../victim")
    with pytest.raises(TaskDefinitionError, match="outside"):
        store.regenerate(escaping)
    assert (victim / "keep.txt").read_text() == "mine" and sorted(victim.iterdir()) == [victim / "keep.txt"]


@pytest.mark.parametrize("task_id", ["../../victim", "..", "a/b"])
def test_a_task_id_that_is_not_an_id_reads_and_deletes_nothing(tmp_path, task_id):
    (tmp_path / "victim.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data" / "tasks").mkdir(parents=True)  # so `..` resolves through it
    store = TaskStore(tmp_path / "data", library_root=FIRMWARE)
    assert store.document(task_id) is None and store.get(task_id) is None
    assert store.delete(task_id) is False
    assert (tmp_path / "victim.json").exists()


# --------------------------------------------------------------------------- #
# Folder names that are safe on Windows and macOS
# --------------------------------------------------------------------------- #


UNSAFE_FOLDER_NAMES = [
    "..", ".", "a/b", "a\\b", "C:victim", "\\\\server\\share", "nul\x00byte", "tab\there",
    "trailing.", "trailing ", "CON", "con.txt", "Lpt1", "COM9.json", "aux.v2", "what?",
]


def test_a_free_text_category_still_reads_lists_and_saves(tmp_path):
    store = TaskStore(tmp_path, library_root=FIRMWARE)
    store.save_document(tracer(category="Shaping (old)"))
    [entry] = store.list_entries()
    assert entry["category"] == "Shaping (old)" and entry["unreadable"] is None
    assert (tmp_path / "tasks" / "Shaping (old)" / "Spine Tracer" / "task.json").is_file()


@pytest.mark.parametrize("value", UNSAFE_FOLDER_NAMES)
def test_a_category_or_name_that_is_not_a_safe_folder_name_is_not_a_definition(value):
    with pytest.raises(TaskDefinitionError, match="category"):
        TaskDefinition.from_json(tracer(category=value))
    if value.strip() == value:  # a name is trimmed first, which makes it safe
        with pytest.raises(TaskDefinitionError, match="name"):
            TaskDefinition.from_json(tracer(name=value))


def test_a_stored_task_that_will_not_read_is_listed_as_unreadable_with_its_reason(tmp_path):
    store = TaskStore(tmp_path, library_root=FIRMWARE)
    store.save_document(tracer())
    (tmp_path / "tasks" / "old_one.json").write_text(
        json.dumps(tracer(id="old_one", name="Old One", category="Shaping/old")), encoding="utf-8"
    )
    (tmp_path / "tasks" / "garbled.json").write_text("{ not json", encoding="utf-8")
    entries = {e["id"]: e for e in store.list_entries()}
    assert entries["spine_tracer"]["unreadable"] is None
    assert "category" in entries["old_one"]["unreadable"] and entries["old_one"]["name"] == "Old One"
    assert "JSON" in entries["garbled"]["unreadable"]


def test_a_symlinked_category_folder_still_lists_and_regenerates(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "data" / "tasks").mkdir(parents=True)
    (tmp_path / "data" / "tasks" / "Tasks").symlink_to(elsewhere, target_is_directory=True)
    store = TaskStore(tmp_path / "data", library_root=FIRMWARE)
    store.save_document(tracer())
    [entry] = store.list_entries()
    assert entry["unreadable"] is None
    assert store.regenerate_all() == 1
    assert (elsewhere / "Spine Tracer" / "task.json").is_file()


def test_a_name_another_task_holds_as_windows_sees_it_is_taken(tmp_path):
    """Windows drops a trailing dot or space, so "Spine Tracer." and "Spine
    Tracer" are one folder there. A stored task that no longer reads still
    holds its folder."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "older.json").write_text(
        json.dumps(tracer(id="older", name="SPINE TRACER.")), encoding="utf-8"
    )
    conflicts = plan(export(), tmp_path).conflicts
    assert [c["kind"] for c in conflicts] == ["name_taken"]

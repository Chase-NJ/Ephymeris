"""Moving the channel set between machines (TASKS.md#moving-the-channel-set-between-machines).

Two lab machines must hold one channel set and emit identical codes. One edits
it and exports it with its vocabulary; the other imports both. An import that
disagrees with this machine is refused whole and names each difference, and a
clean one is one rig definition write.

Each `Machine` is its own data folder. The registry's sources are process-wide,
so the machine built (or `use`d) last is the one in force.
"""

from __future__ import annotations

import asyncio
import copy
import json

import pytest

from ephymeris_sidecar.hardware import store
from ephymeris_sidecar.rig import definition, registry, transfer
from ephymeris_sidecar.strobes import store as strobe_store


@pytest.fixture(autouse=True)
def _shipped_rig_definition():
    registry.set_rig_source(None)
    registry.set_vocabulary_source(None)
    yield
    registry.set_rig_source(None)
    registry.set_vocabulary_source(None)


class Tasks:
    """A task store with one task once `needs` is set: it fails (TSK101) under
    any channel set where that channel is missing or is not a cue line."""

    def __init__(self) -> None:
        self.needs: str | None = None

    def list_entries(self):
        return [{"id": "t1", "label": "Task one"}] if self.needs else []

    def failures(self, task_id):
        channel = registry.channels().get(self.needs) if self.needs else None
        if self.needs and (channel is None or channel.role != "cue"):
            return {"TSK101"}
        return set()

    def regenerate_all(self) -> int:
        return 0


class Machine:
    def __init__(self, folder) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.events: list[str] = []
        self.rebuilds = 0
        self.tasks = Tasks()
        self.vocabulary = strobe_store.VocabularyStore(folder)
        self.vocabulary.ensure_seeded()
        self.hardware = store.HardwareStore(folder)
        self.in_use = False
        self.use()

    def use(self) -> None:
        self.definition = definition.RigDefinition(
            hardware=self.hardware,
            vocabulary=self.vocabulary,
            tasks=self.tasks,
            repin=lambda: 0,
            in_use=lambda: self.in_use,
            rescan=self._nothing,
            after_rebuild=self._after,
            broadcast=self._broadcast,
        )

    async def _nothing(self) -> None:
        return None

    async def _after(self, tasks: int, pinned: int) -> None:
        self.rebuilds += 1

    async def _broadcast(self, message) -> None:
        self.events.append(message["evt"])

    def save(self, doc: dict | None = None) -> dict:
        return asyncio.run(
            self.definition.save_wiring(doc or store.default_document(), confirm=True)
        )

    def export(self) -> dict:
        return self.definition.export_channel_set()["document"]

    def plan(self, document) -> dict:
        return asyncio.run(self.definition.import_channel_set(document, apply=False))["plan"]

    def import_(self, document, *, confirm: bool = False) -> dict:
        return asyncio.run(
            self.definition.import_channel_set(document, apply=True, confirm=confirm)
        )

    def files(self) -> tuple[bytes | None, bytes]:
        wiring = self.hardware.path
        return (wiring.read_bytes() if wiring.exists() else None, self.vocabulary.path.read_bytes())


def hash_in_force() -> str:
    return registry.channel_set().content_hash()


# --------------------------------------------------------------------------- #
# Acceptance 1: importing A's export on B makes their hashes equal
# --------------------------------------------------------------------------- #


def test_importing_a_machines_export_makes_the_two_channel_set_hashes_equal(tmp_path):
    a = Machine(tmp_path / "a")
    a.save()
    doc = a.save(_with_lever_as_cue(a.hardware.load()))  # a channel set B has never seen
    exported = a.export()
    a_hash = hash_in_force()
    assert exported["channel_set_hash"] == a_hash == doc["status"]["channelSetHash"]

    b = Machine(tmp_path / "b")
    # B has the lever too, on its own pin, but calls it a routing line.
    b.save(_with_lever_as_cue(store.default_document(), role="routing", pin=51))
    assert hash_in_force() != a_hash
    b.events.clear()
    b.rebuilds = 0

    reply = b.import_(exported)

    assert reply["applied"] is True
    assert hash_in_force() == a_hash
    assert reply["plan"]["thereHash"] == a_hash
    # The vocabulary moved with it: B now strobes A's numbers for A's codes.
    vocab = registry.vocabulary()
    for code_name, entry in exported["vocabulary"]["codes"].items():
        assert vocab.code_of(code_name) == entry["code"]
    # The pin map is B's own, untouched.
    assert b.hardware.load()["pins"] == _with_lever_as_cue(store.default_document(), pin=51)["pins"]
    assert b.hardware.load()["channels"] == exported["channel_set"]["channels"]
    assert b.events == ["hardware.updated"]
    assert b.rebuilds == 1

    # And it survives a restart.
    b.use()
    assert hash_in_force() == a_hash


def _with_lever_as_cue(doc: dict, *, role: str = "cue", pin: int = 50) -> dict:
    """The document with one more channel, `lever`, on a free pin."""
    out = copy.deepcopy(doc)
    out["channels"]["lever"] = {"kind": "cue", "label": "lever", "type": "digital_out", "role": role}
    out["pins"]["lever"] = {"index": pin}
    return out


# --------------------------------------------------------------------------- #
# Acceptance 2: a conflicting import writes nothing and lists each conflict
# --------------------------------------------------------------------------- #


def _machine_b_that_disagrees(tmp_path) -> Machine:
    """B issued its own code first, so its edge codes sit one number later than
    A's; it never added the lever; and it has a channel A does not."""
    b = Machine(tmp_path / "b")
    raw = b.vocabulary.load_strict()
    raw = strobe_store.add(
        raw, "DOOR_NOTE", registry.Vocabulary(raw).next_free(), rationale="B's own code."
    )
    b.vocabulary.save(raw)
    b.use()
    doc = store.default_document()
    doc["channels"]["door"] = {"kind": "cue", "label": "door", "type": "digital_out", "role": "cue"}
    doc["pins"]["door"] = {"index": 52}
    b.save(doc)
    return b


def test_a_conflicting_import_writes_nothing_and_lists_each_conflict(tmp_path):
    a = Machine(tmp_path / "a")
    a.save()
    a.save(_with_lever_as_cue(a.hardware.load()))
    exported = a.export()

    b = _machine_b_that_disagrees(tmp_path)
    before, hash_before = b.files(), hash_in_force()
    b.events.clear()
    b.rebuilds = 0

    plan = b.plan(exported)
    kinds = {(c["kind"], c["channel"]) for c in plan["conflicts"]}
    assert ("not_here", "lever") in kinds
    assert ("only_here", "door") in kinds
    vocabulary = [c["message"] for c in plan["conflicts"] if c["kind"] == "vocabulary"]
    assert any(m.startswith("ODOR_PORT_ENTER is") for m in vocabulary), vocabulary
    # Every disagreement, not just the first.
    assert len(vocabulary) == len(plan["vocabulary"]["conflicts"]) > 1
    assert plan["identical"] is False

    with pytest.raises(transfer.ChannelSetImportConflict) as refused:
        b.import_(exported, confirm=True)
    assert refused.value.conflicts == plan["conflicts"]

    assert b.files() == before
    assert hash_in_force() == hash_before
    assert b.events == [] and b.rebuilds == 0


def test_a_code_retired_here_that_the_file_names_is_a_conflict(tmp_path):
    """A merge never reinstates, so the channel would announce a retired code."""
    a = Machine(tmp_path / "a")
    a.save()
    exported = a.export()

    b = Machine(tmp_path / "b")
    b.save()
    _retire_trial_light_on(b)
    before = b.files()

    plan = b.plan(exported)
    assert [(c["kind"], c["channel"]) for c in plan["conflicts"]] == [("rule", "trial_light")]
    assert "RIG107" in plan["conflicts"][0]["message"]
    with pytest.raises(transfer.ChannelSetImportConflict):
        b.import_(exported)
    assert b.files() == before


def _retire_trial_light_on(m: Machine) -> None:
    """Retire TRIAL_LIGHT_ON here the way a rig gets there: retired, then the
    light saved again, which issues it TRIAL_LIGHT_ON_2. This machine's own
    wiring stays loadable; another machine's still names the old code."""
    asyncio.run(m.definition.edit_vocabulary(lambda d: strobe_store.retire(d, "TRIAL_LIGHT_ON")))
    # The file now breaks RIG107 and would not load; the wiring in force holds.
    doc = m.definition.in_force().document
    doc["channels"]["trial_light"].pop("edges")
    m.save(doc)
    assert m.hardware.load()["channels"]["trial_light"]["edges"]["on"] == "TRIAL_LIGHT_ON_2"


def test_a_file_changed_after_export_is_refused_by_its_hash(tmp_path):
    a = Machine(tmp_path / "a")
    a.save()
    exported = a.export()
    exported["channel_set"]["channels"]["odor_port"]["debounce_ms"] = 5

    b = Machine(tmp_path / "b")
    b.save()
    assert [c["kind"] for c in b.plan(exported)["conflicts"]] == ["hash"]


def test_an_edge_with_no_code_is_refused_at_export_and_at_import(tmp_path):
    a = Machine(tmp_path / "a")  # the shipped set: no edge has a code yet
    with pytest.raises(transfer.ChannelSetInvalid, match="Save the wiring"):
        a.export()

    a.save()
    exported = a.export()
    exported["channel_set"]["channels"]["vacuum"].pop("edges")
    b = Machine(tmp_path / "b")
    conflicts = b.plan(exported)["conflicts"]
    assert {(c["kind"], c["channel"]) for c in conflicts} == {("no_code", "vacuum")}


@pytest.mark.parametrize(
    "document",
    [None, [], {"channel_set_export_version": 2}, {"vocab_version": 3, "codes": {}}],
)
def test_a_file_that_is_not_an_export_is_invalid(tmp_path, document):
    b = Machine(tmp_path / "b")
    with pytest.raises(transfer.ChannelSetInvalid):
        b.plan(document)


# --------------------------------------------------------------------------- #
# What a clean import writes, and when it refuses
# --------------------------------------------------------------------------- #


def test_the_vocabulary_travels_with_the_channel_set(tmp_path):
    a = Machine(tmp_path / "a")
    a.save()
    raw = a.vocabulary.load_strict()
    free = registry.Vocabulary(raw).next_free()
    a.vocabulary.save(strobe_store.add(raw, "LEVER_NOTE", free, rationale="A's own code."))
    a.use()
    exported = a.export()

    b = Machine(tmp_path / "b")
    b.save()
    b.events.clear()
    plan = b.plan(exported)
    assert plan["vocabulary"]["adds"] == [{"name": "LEVER_NOTE", "code": free, "retired": False}]
    assert plan["changed"] == [] and plan["conflicts"] == []

    assert b.import_(exported)["applied"] is True
    assert registry.vocabulary().code_of("LEVER_NOTE") == free
    assert b.events == ["strobes.updated", "hardware.updated"]


def test_an_identical_import_writes_nothing(tmp_path):
    a = Machine(tmp_path / "a")
    a.save()
    exported = a.export()
    b = Machine(tmp_path / "b")
    b.save()
    before = b.files()
    b.events.clear()

    reply = b.import_(exported)
    assert reply["plan"]["identical"] is True and reply["applied"] is False
    assert b.files() == before and b.events == []


def test_an_import_that_would_break_a_saved_task_needs_confirm(tmp_path):
    a = Machine(tmp_path / "a")
    a.save()
    a.save(_with_lever_as_cue(a.hardware.load(), role="routing"))
    exported = a.export()

    b = Machine(tmp_path / "b")
    b.save(_with_lever_as_cue(store.default_document(), pin=51))
    b.tasks.needs = "lever"  # a task that needs the lever to be a cue line
    before = b.files()

    plan = b.plan(exported)
    assert plan["conflicts"] == []
    assert plan["breaks"] == [{"specId": "t1", "label": "Task one", "codes": ["TSK101"]}]
    with pytest.raises(definition.WiringWouldBreakTasks):
        b.import_(exported)
    assert b.files() == before

    assert b.import_(exported, confirm=True)["applied"] is True
    assert registry.channels().get("lever").role == "routing"


def test_an_import_reorders_the_channels_as_the_file_declares_them(tmp_path):
    a = Machine(tmp_path / "a")
    a.save()
    doc = a.hardware.load()
    doc["channels"] = dict(reversed(list(doc["channels"].items())))
    a.save(doc)
    exported = a.export()

    b = Machine(tmp_path / "b")
    b.save()
    plan = b.plan(exported)
    assert plan["reordered"] is True and plan["changed"] == []
    b.import_(exported)
    assert list(b.hardware.load()["channels"]) == list(doc["channels"])


def test_an_import_is_refused_while_a_session_is_set_up(tmp_path):
    a = Machine(tmp_path / "a")
    a.save()
    exported = a.export()
    b = Machine(tmp_path / "b")
    b.in_use = True
    with pytest.raises(definition.RigInUse):
        b.import_(exported)


def test_an_import_is_refused_while_stored_wiring_did_not_load(tmp_path):
    a = Machine(tmp_path / "a")
    a.save()
    exported = a.export()
    b = Machine(tmp_path / "b")
    b.save()
    b.hardware.path.write_text("{ not json")
    b.use()
    before = b.files()
    with pytest.raises(definition.WiringNotLoaded):
        b.plan(exported)
    with pytest.raises(definition.WiringNotLoaded):
        b.export()
    assert b.files() == before


def test_a_wiring_that_fails_to_write_keeps_the_vocabulary_union_and_still_rebuilds(
    tmp_path, monkeypatch
):
    a = Machine(tmp_path / "a")
    a.save()
    a.save(_with_lever_as_cue(a.hardware.load()))
    raw = a.vocabulary.load_strict()
    free = registry.Vocabulary(raw).next_free()
    a.vocabulary.save(strobe_store.add(raw, "LEVER_NOTE", free, rationale="A's own code."))
    a.use()
    exported = a.export()

    b = Machine(tmp_path / "b")
    b.save(_with_lever_as_cue(store.default_document(), role="routing", pin=51))
    wiring_before = b.files()[0]
    b.events.clear()
    b.rebuilds = 0

    def full_disk(self, doc):
        raise OSError("no space left on device")

    monkeypatch.setattr(store.HardwareStore, "save", full_disk)
    with pytest.raises(OSError):
        b.import_(exported)

    assert b.files()[0] == wiring_before
    assert registry.vocabulary().code_of("LEVER_NOTE") == free
    assert b.rebuilds == 1 and b.events == ["strobes.updated"]

    monkeypatch.undo()
    b.events.clear()
    plan = b.plan(exported)
    assert plan["vocabulary"]["adds"] == [] and plan["changed"] == ["lever"]
    assert b.import_(exported)["applied"] is True
    assert b.events == ["hardware.updated"]


# --------------------------------------------------------------------------- #
# On the wire
# --------------------------------------------------------------------------- #


async def test_export_and_import_over_the_wire(sidecar) -> None:  # noqa: ANN001
    from tests.live_sidecar import Refused

    with pytest.raises(Refused) as refused:
        await sidecar.call("hardware.exportChannelSet")
    assert refused.value.code == "CHANNEL_SET_INVALID"

    saved = await sidecar.call("hardware.save", document=store.default_document(), confirm=True)
    reply = await sidecar.call("hardware.exportChannelSet")
    assert reply["filename"].startswith("channel-set-") and reply["filename"].endswith(".json")
    exported = reply["document"]
    assert exported["channel_set_hash"] == saved["status"]["channelSetHash"]
    assert "pins" not in exported["channel_set"]

    same = await sidecar.call("hardware.importChannelSet", document=exported, apply=True)
    assert same["applied"] is False and same["plan"]["identical"] is True

    lacking = copy.deepcopy(exported)
    del lacking["channel_set"]["channels"]["vacuum"]
    plan = (await sidecar.call("hardware.importChannelSet", document=lacking, apply=False))["plan"]
    assert [(c["kind"], c["channel"]) for c in plan["conflicts"]] == [("only_here", "vacuum")]
    with pytest.raises(Refused) as refused:
        await sidecar.call("hardware.importChannelSet", document=lacking, apply=True)
    assert refused.value.code == "CHANNEL_SET_IMPORT_CONFLICT"
    assert refused.value.detail["conflicts"] == plan["conflicts"]

    with pytest.raises(Refused) as refused:
        await sidecar.call("hardware.importChannelSet", document={"x": 1}, apply=False)
    assert refused.value.code == "CHANNEL_SET_INVALID"


def test_conflicts_of_different_kinds_are_listed_together(tmp_path):
    """A code in conflict is left out of the merge the rules are judged
    against, so a rule it breaks is still reported beside it."""
    a = Machine(tmp_path / "a")
    a.save()
    exported = a.export()
    exported["channel_set"]["channels"]["vacuum"].pop("edges")
    exported["channel_set_hash"] = "tampered"

    b = _machine_b_that_disagrees(tmp_path)
    doc = b.hardware.load()
    del doc["channels"]["door"], doc["pins"]["door"]
    b.save(doc)
    _retire_trial_light_on(b)

    kinds = {(c["kind"], c["channel"]) for c in b.plan(exported)["conflicts"]}
    assert ("vocabulary", None) in kinds
    assert ("no_code", "vacuum") in kinds
    assert ("rule", "trial_light") in kinds
    # The hash is not judged over a conflict that already names the edit.
    assert ("hash", None) not in kinds


def test_an_import_is_refused_while_a_stored_file_waits_for_its_pins_to_be_confirmed(tmp_path):
    """RIG108: an import would otherwise replace a copied-in file unseen."""
    a = Machine(tmp_path / "a")
    a.save()
    exported = a.export()

    b = Machine(tmp_path / "b")
    b.save()
    copied_in = b.hardware.load()
    copied_in["pins"]["vacuum"]["index"] = 53
    b.hardware.path.write_text(json.dumps(copied_in))  # by hand, not installed
    before = b.files()

    with pytest.raises(definition.WiringSaveBlocked):
        b.plan(exported)
    with pytest.raises(definition.WiringSaveBlocked):
        b.import_(exported)
    assert b.files() == before


def test_a_file_whose_vocabulary_or_channel_set_is_out_of_shape_is_invalid(tmp_path):
    a = Machine(tmp_path / "a")
    a.save()
    exported = a.export()
    b = Machine(tmp_path / "b")

    bad_vocabulary = copy.deepcopy(exported)
    bad_vocabulary["vocabulary"]["codes"]["ODOR_PORT_ENTER"]["code"] = "one"
    with pytest.raises(transfer.ChannelSetInvalid, match="vocabulary"):
        b.plan(bad_vocabulary)

    bad_channels = copy.deepcopy(exported)
    bad_channels["channel_set"]["channels"]["vacuum"]["kind"] = "teleporter"
    with pytest.raises(transfer.ChannelSetInvalid, match="channel set"):
        b.plan(bad_channels)

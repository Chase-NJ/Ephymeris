"""Wiring nobody saved or confirmed on this machine is held (#131,
TASKS.md#the-channel-set-and-the-pin-map).

ONE RULE. The store keeps the digest of the last wiring saved here, or
confirmed with "I've checked every pin". Stored wiring whose content differs
from it is held behind RIG108: not in force, every box refused, until it is
confirmed and saved. A restart never confirms anything, so each case below is
checked across one. A machine with no digest yet (an upgrade from main, or a
fresh install) records the wiring it would have run anyway, and asks nothing.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from ephymeris_sidecar.hardware import service, store
from ephymeris_sidecar.rig import definition, registry
from ephymeris_sidecar.strobes import store as strobe_store

SHIPPED_PINOUT_HASH = "bfa89f7d62bf622f"


@pytest.fixture(autouse=True)
def _shipped_rig_definition():
    registry.set_rig_source(None)
    registry.set_vocabulary_source(None)
    yield
    registry.set_rig_source(None)
    registry.set_vocabulary_source(None)


class NoTasks:
    def list_entries(self):
        return []

    def failures(self, task_id):
        return set()

    def regenerate_all(self) -> int:
        return 0


class Rig:
    """One run of the sidecar on `tmp_path`: constructing another is a restart."""

    def __init__(self, tmp_path, tasks=None) -> None:
        self.vocabulary = strobe_store.VocabularyStore(tmp_path)
        self.vocabulary.ensure_seeded()
        self.hardware = store.HardwareStore(tmp_path)
        self.definition = definition.RigDefinition(
            hardware=self.hardware,
            vocabulary=self.vocabulary,
            tasks=tasks or NoTasks(),
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
        return None

    def save(self, doc: dict, *, confirmed_pins: bool = False, confirm: bool = True) -> dict:
        return asyncio.run(
            self.definition.save_wiring(doc, confirm=confirm, confirmed_pins=confirmed_pins)
        )

    def get(self) -> dict:
        return service.document_payload(self.hardware, in_force=self.definition.in_force())

    def preview(self, draft: dict, *, confirmed: bool = False) -> dict:
        return service.preview_payload(
            self.hardware, draft, [], in_force=self.definition.in_force(), confirmed_pins=confirmed
        )

    def notices(self) -> str:
        return " ".join(n["message"] for n in self.get()["status"]["notices"])


def moved(index: int = 12, doc: dict | None = None) -> dict:
    """A wiring with left_well on `index`: the pin a box would get wrong."""
    doc = copy.deepcopy(doc or store.default_document())
    doc["pins"]["left_well"]["index"] = index
    return doc


def write_wiring(s: store.HardwareStore, doc: dict) -> None:
    s.root.mkdir(parents=True, exist_ok=True)
    s.path.write_text(json.dumps(doc), encoding="utf-8")


def write_rig_json(s: store.HardwareStore, doc: dict) -> None:
    s.root.mkdir(parents=True, exist_ok=True)
    s.legacy_rig_path.write_text(json.dumps(doc), encoding="utf-8")


def write_pair(s: store.HardwareStore, doc: dict) -> None:
    """The two-file layout main wrote after #123."""
    doc = {**doc, "edited_at": "2026-10-31T05:00:00Z"}
    channel_set, pin_map = store.split(doc)
    pin_map["channel_set_digest"] = store.legacy_pair_digest(channel_set)
    s.root.mkdir(parents=True, exist_ok=True)
    s.channel_set_path.write_text(json.dumps(channel_set), encoding="utf-8")
    s.pin_map_path.write_text(json.dumps(pin_map), encoding="utf-8")


LAYOUTS = {"wiring.json": write_wiring, "rig.json": write_rig_json, "pair": write_pair}


def assert_held(rig: Rig) -> None:
    """Not in force, every box refused, the draft the held file with RIG108."""
    problem = rig.definition.wiring_problem()
    assert problem and "not saved or confirmed" in problem
    assert registry.channels().content_hash() == SHIPPED_PINOUT_HASH
    payload = rig.get()
    assert "RIG108" in {p["code"] for p in payload["problems"]}
    assert payload["status"]["needsPinConfirmation"] is True
    assert payload["status"]["canSave"] is False
    assert payload["status"]["custom"] is False
    assert payload["status"]["notices"], "held wiring is never silent"


# --------------------------------------------------------------------------- #
# 1. Held across a restart
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_wiring_copied_in_is_held_after_a_restart_until_confirmed(tmp_path, layout):
    Rig(tmp_path)  # this machine, running the shipped pins
    LAYOUTS[layout](store.HardwareStore(tmp_path), moved(12))

    rig = Rig(tmp_path)  # a restart never confirms
    assert_held(rig)
    draft = rig.get()["document"]
    assert draft["pins"]["left_well"]["index"] == 12, "the copy's pins, for the operator to check"
    with pytest.raises(definition.WiringSaveBlocked):
        rig.save(draft)

    rig.save(draft, confirmed_pins=True)
    assert rig.definition.wiring_problem() is None
    assert registry.channels().get("left_well").index == 12
    again = Rig(tmp_path)
    assert again.definition.wiring_problem() is None, "confirmed once, in force from then on"
    assert again.get()["status"]["notices"] == []


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d["pins"]["left_well"].update(index=12),
        lambda d: d["channels"]["right_well"].update(label="right"),
    ],
    ids=["a pin", "a label"],
)
def test_a_hand_edit_is_held_after_a_restart(tmp_path, edit):
    Rig(tmp_path).save(store.default_document())
    s = store.HardwareStore(tmp_path)
    doc = json.loads(s.path.read_text(encoding="utf-8"))
    edit(doc)
    s.path.write_text(json.dumps(doc), encoding="utf-8")

    assert_held(Rig(tmp_path))
    assert_held(Rig(tmp_path))  # and a second restart still does not confirm it


def test_a_file_fixed_by_hand_after_a_failed_load_is_held(tmp_path):
    Rig(tmp_path).save(moved(12))
    s = store.HardwareStore(tmp_path)
    good = s.path.read_text(encoding="utf-8")
    s.path.write_text("{ damaged", encoding="utf-8")
    assert "did not load" in Rig(tmp_path).definition.wiring_problem()

    fixed = json.loads(good)
    fixed["pins"]["left_well"]["index"] = 13  # fixed, but not to what was saved
    s.path.write_text(json.dumps(fixed), encoding="utf-8")
    assert_held(Rig(tmp_path))


def test_a_file_put_back_exactly_as_it_was_saved_loads(tmp_path):
    Rig(tmp_path).save(moved(12))
    s = store.HardwareStore(tmp_path)
    good = s.path.read_text(encoding="utf-8")
    s.path.write_text("{ damaged", encoding="utf-8")
    Rig(tmp_path)
    s.path.write_text(good, encoding="utf-8")

    rig = Rig(tmp_path)
    assert rig.definition.wiring_problem() is None
    assert registry.channels().get("left_well").index == 12


def test_an_identical_copy_from_another_machine_with_another_stamp_is_not_held(tmp_path):
    Rig(tmp_path).save(moved(12))
    s = store.HardwareStore(tmp_path)
    doc = json.loads(s.path.read_text(encoding="utf-8"))
    doc["edited_at"] = "2020-01-01T00:00:00Z"
    s.path.write_text(json.dumps(doc), encoding="utf-8")
    rig = Rig(tmp_path)
    assert rig.definition.wiring_problem() is None
    assert rig.get()["status"]["notices"] == []


def test_a_repaired_draft_must_be_confirmed_and_the_confirmation_survives_a_restart(tmp_path):
    Rig(tmp_path).save(moved(12))
    s = store.HardwareStore(tmp_path)
    broken = json.loads(s.path.read_text(encoding="utf-8"))
    broken["pins"].pop("odor_port")
    s.path.write_text(json.dumps(broken), encoding="utf-8")

    rig = Rig(tmp_path)
    draft = rig.get()["document"]
    draft["pins"]["odor_port"] = {"index": 2, "watch_bit": 0}
    with pytest.raises(definition.WiringSaveBlocked):
        rig.save(draft)
    rig.save(draft, confirmed_pins=True)
    assert Rig(tmp_path).definition.wiring_problem() is None


def test_the_digest_is_kept_outside_the_hardware_folder(tmp_path):
    """Copying `hardware/` from the other machine must never bring its
    confirmation along."""
    other = tmp_path / "other"
    store.HardwareStore(other).save(moved(12))  # saved there, with no edge code to carry
    Rig(tmp_path / "here")
    here = store.HardwareStore(tmp_path / "here")
    here.root.mkdir(parents=True)
    for f in (other / "hardware").iterdir():
        (here.root / f.name).write_bytes(f.read_bytes())
    assert_held(Rig(tmp_path / "here"))


# --------------------------------------------------------------------------- #
# The upgrade from main: no digest yet
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_an_upgrade_from_main_keeps_the_wiring_it_ran_and_asks_nothing(tmp_path, layout):
    LAYOUTS[layout](store.HardwareStore(tmp_path), moved(12))

    rig = Rig(tmp_path)
    assert rig.definition.wiring_problem() is None
    assert registry.channels().get("left_well").index == 12
    payload = rig.get()
    assert payload["status"]["notices"] == []
    assert payload["status"]["needsPinConfirmation"] is False
    assert Rig(tmp_path).definition.wiring_problem() is None


@pytest.mark.parametrize("layout", ["rig.json", "pair"])
def test_the_migrating_save_records_its_wiring(tmp_path, layout):
    LAYOUTS[layout](store.HardwareStore(tmp_path), moved(12))
    rig = Rig(tmp_path)
    rig.save(rig.get()["document"])
    assert not rig.hardware.legacy_rig_path.exists() and not rig.hardware.pin_map_path.exists()
    restarted = Rig(tmp_path)
    assert restarted.definition.wiring_problem() is None
    assert registry.channels().get("left_well").index == 12


def test_a_fresh_install_records_that_nothing_is_confirmed(tmp_path):
    Rig(tmp_path)
    write_wiring(store.HardwareStore(tmp_path), moved(12))
    assert_held(Rig(tmp_path))


def test_an_upgrade_never_trusts_a_file_that_would_not_load(tmp_path):
    s = store.HardwareStore(tmp_path)
    broken = moved(12)
    broken["pins"].pop("odor_port")
    write_wiring(s, broken)
    Rig(tmp_path)
    broken["pins"]["odor_port"] = {"index": 2, "watch_bit": 0}
    write_wiring(s, broken)  # fixed by hand after the upgrade
    assert_held(Rig(tmp_path))


def test_a_digest_file_that_will_not_read_holds_everything(tmp_path):
    Rig(tmp_path).save(moved(12))
    s = store.HardwareStore(tmp_path)
    s.confirmed_path.write_text("{ damaged", encoding="utf-8")
    assert_held(Rig(tmp_path))


# --------------------------------------------------------------------------- #
# The digest is written with the save: no crash trusts or loses a wiring
# --------------------------------------------------------------------------- #


def _fail_replacing(monkeypatch, name: str) -> None:
    real = store.os.replace

    def replace(src, dst):
        if Path(dst).name == name:
            raise PermissionError(f"{name} is held open")
        return real(src, dst)

    monkeypatch.setattr(store.os, "replace", replace)


def _fail_after_n_replaces(monkeypatch, n: int) -> None:
    """The save dies (a crash, as far as the disk knows) after `n` renames."""
    real, calls = store.os.replace, {"n": 0}

    def replace(src, dst):
        if calls["n"] == n:
            raise OSError("power cut")
        calls["n"] += 1
        return real(src, dst)

    monkeypatch.setattr(store.os, "replace", replace)


@pytest.mark.parametrize("renames", [0, 1, 2])
def test_a_save_cut_off_at_any_step_leaves_a_stored_wiring_that_loads(tmp_path, monkeypatch, renames):
    Rig(tmp_path).save(moved(12))
    rig = Rig(tmp_path)
    _fail_after_n_replaces(monkeypatch, renames)
    try:
        rig.save(moved(13))
    except OSError:
        pass  # the last rename only records the save, which has landed
    monkeypatch.undo()

    restarted = Rig(tmp_path)
    assert restarted.definition.wiring_problem() is None
    assert registry.channels().get("left_well").index in (12, 13)
    assert restarted.get()["status"]["notices"] == []


def test_a_reset_forgets_the_confirmation_before_it_removes_a_file(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    rig.save(moved(12))
    real = Path.unlink

    def unlink(self, *a, **k):
        if self.name == store.WIRING_FILENAME:
            raise PermissionError("held open")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(OSError):
        asyncio.run(rig.definition.reset_wiring())
    monkeypatch.undo()

    assert registry.channels().get("left_well").index == 12, "a failed reset changes nothing in force"
    text = rig.notices()
    assert "Reset" in text and "restart" in text
    assert_held(Rig(tmp_path))


# --------------------------------------------------------------------------- #
# 2. A wiring rule is checked at load
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "rule, change",
    [
        ("RIG103", lambda d: d["pins"]["trial_light"].update(index=3)),
        ("RIG102", lambda d: d["pins"]["trial_light"].update(index=60)),
    ],
)
def test_a_stored_file_breaking_a_wiring_rule_is_never_put_in_force(tmp_path, rule, change):
    doc = store.default_document()
    change(doc)
    write_wiring(store.HardwareStore(tmp_path), doc)  # the upgrade: nothing recorded yet

    rig = Rig(tmp_path)
    problem = rig.definition.wiring_problem()
    assert problem and rule in problem
    assert registry.channels().content_hash() == SHIPPED_PINOUT_HASH
    payload = rig.get()
    assert payload["document"]["pins"]["trial_light"] == doc["pins"]["trial_light"], "to repair"
    assert rule in {p["code"] for p in payload["problems"]}


# --------------------------------------------------------------------------- #
# 3. Every notice says truthfully what is in force and what the editor shows
# --------------------------------------------------------------------------- #


def _assert_truthful(rig: Rig) -> None:
    """A notice that says the editor shows the wiring in force is only ever
    beside a draft that IS the wiring in force."""
    payload = rig.get()
    in_force = rig.definition.in_force().document or store.default_document()
    shows_in_force = service._content(payload["document"]) == service._content(in_force)
    text = " ".join(n["message"] for n in payload["status"]["notices"])
    if not shows_in_force:
        assert "wiring shown is the one in force" not in text
        assert "editor shows the wiring in force" not in text
        assert "not in force" in text


def test_a_pin_map_copied_beside_the_pair_in_force_is_described_as_the_draft(tmp_path):
    write_pair(store.HardwareStore(tmp_path), moved(12))
    rig = Rig(tmp_path)
    other = store.HardwareStore(tmp_path / "other")
    other_doc = moved(13)
    other_doc["channels"]["odor_port"]["label"] = "another channel set"
    write_pair(other, other_doc)
    rig.hardware.pin_map_path.write_bytes(other.pin_map_path.read_bytes())

    payload = rig.get()
    assert payload["document"]["pins"]["left_well"]["index"] == 13
    assert "RIG108" in {p["code"] for p in payload["problems"]}
    _assert_truthful(rig)
    assert registry.channels().get("left_well").index == 12


@pytest.mark.parametrize("stuck", [store.CHANNEL_SET_FILENAME, store.PIN_MAP_FILENAME, store.WIRING_FILENAME])
def test_a_reset_that_fails_halfway_is_described_truthfully(tmp_path, monkeypatch, stuck):
    s = store.HardwareStore(tmp_path)
    if stuck == store.WIRING_FILENAME:
        Rig(tmp_path).save(moved(12))
    else:
        write_pair(s, moved(12))
    rig = Rig(tmp_path)
    real = Path.unlink

    def unlink(self, *a, **k):
        if self.name == stuck:
            raise PermissionError("held open")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(OSError):
        asyncio.run(rig.definition.reset_wiring())
    monkeypatch.undo()

    _assert_truthful(rig)
    assert rig.get()["status"]["canReset"] is True


def test_a_held_file_beside_the_wiring_in_force_names_what_a_restart_does(tmp_path):
    rig = Rig(tmp_path)
    rig.save(moved(12))
    write_wiring(rig.hardware, moved(13))
    text = rig.notices()
    assert "not in force" in text and "restart" in text
    _assert_truthful(rig)


# --------------------------------------------------------------------------- #
# 4. A copy shadowed by wiring.json is shown, and no save deletes it
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("layout", ["rig.json", "pair"])
def test_a_copy_shadowed_by_wiring_json_is_shown_and_never_deleted_by_a_save(tmp_path, layout):
    rig = Rig(tmp_path)
    rig.save(moved(12))
    LAYOUTS[layout](rig.hardware, moved(13))
    shadow = rig.hardware.legacy_rig_path if layout == "rig.json" else rig.hardware.channel_set_path

    payload = rig.get()
    text = " ".join(n["message"] for n in payload["status"]["notices"])
    assert shadow.name in text and "not read" in text
    assert payload["status"]["canSave"] is False, "a save would not clear it"
    assert payload["status"]["canReset"] is True

    rig.save(moved(14))
    assert shadow.exists(), "a copy nobody has looked at is never deleted silently"
    assert registry.channels().get("left_well").index == 14
    assert shadow.name in rig.notices()


def test_the_leftover_of_a_migration_the_app_made_is_removed_by_the_next_save(tmp_path, monkeypatch):
    s = store.HardwareStore(tmp_path)
    write_rig_json(s, moved(12))
    rig = Rig(tmp_path)  # the upgrade: rig.json is in force and recorded
    real = Path.unlink

    def unlink(self, *a, **k):
        if self.name == store.RIG_FILENAME:
            raise PermissionError("held open")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    rig.save(moved(13))  # migrates, but cannot remove rig.json
    monkeypatch.undo()
    assert s.legacy_rig_path.exists()
    assert store.RIG_FILENAME not in rig.notices(), "the app's own leftover, not a copy"

    rig.save(moved(14))
    assert not s.legacy_rig_path.exists()


def test_half_a_pair_left_by_a_save_is_the_app_s_own_and_the_next_save_removes_it(tmp_path, monkeypatch):
    s = store.HardwareStore(tmp_path)
    write_pair(s, moved(12))
    rig = Rig(tmp_path)  # the upgrade: the pair is in force and recorded
    real = Path.unlink

    def unlink(self, *a, **k):
        if self.name == store.CHANNEL_SET_FILENAME:
            raise PermissionError("held open")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)
    rig.save(moved(13))  # migrates; pin_map.json goes, channel_set.json stays
    monkeypatch.undo()
    assert s.channel_set_path.exists() and not s.pin_map_path.exists()
    assert store.CHANNEL_SET_FILENAME not in rig.notices(), "the app's own leftover, not a copy"

    rig.save(moved(14))
    assert not s.channel_set_path.exists()


def test_a_record_lost_while_running_never_trusts_a_file_copied_in_after(tmp_path):
    """Only a start records unrecorded wiring; a read never does, so the
    copy is held for as long as this run lasts and no record is written."""
    rig = Rig(tmp_path)
    rig.save(moved(12))
    rig.hardware.confirmed_path.unlink()  # lost while the app runs
    write_wiring(rig.hardware, moved(13))  # and another machine's wiring copied in
    for _ in range(2):
        payload = rig.get()
        assert "RIG108" in {p["code"] for p in payload["problems"]}
        assert payload["status"]["needsPinConfirmation"] is True
    assert not rig.hardware.confirmed_path.exists(), "a read never records anything"
    assert registry.channels().get("left_well").index == 12


# --------------------------------------------------------------------------- #
# 5. A save refused for a rule never asks about breaks first
# --------------------------------------------------------------------------- #


class BreakingTasks(NoTasks):
    """One task, broken by any wiring other than the shipped one."""

    def list_entries(self):
        return [{"id": "probe", "label": "Probe"}]

    def failures(self, task_id):
        return set() if registry.channels().content_hash() == SHIPPED_PINOUT_HASH else {"TSK999"}


def test_a_save_that_breaks_a_rule_is_refused_before_it_asks_about_breaks(tmp_path):
    rig = Rig(tmp_path, tasks=BreakingTasks())
    draft = store.default_document()
    draft["pins"]["trial_light"]["index"] = 3  # on left_well's pin: RIG103
    with pytest.raises(definition.WiringSaveBlocked, match="RIG103"):
        rig.save(draft, confirm=False)
    with pytest.raises(definition.WiringWouldBreakTasks):
        rig.save(moved(12), confirm=False)  # a good draft still asks

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
    """One run of the sidecar on `tmp_path`: constructing another is a restart.

    `first_start` is what the database says (`app.py`): True for a data dir
    it has never marked. Seeding is a no-op once a record exists, so only a
    test that loses the record says False."""

    def __init__(self, tmp_path, tasks=None, *, first_start: bool = True) -> None:
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
            first_start=first_start,
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


def assert_held(rig: Rig, *, why: str = "not saved or confirmed") -> None:
    """Not in force, every box refused, the draft the held file with RIG108."""
    problem = rig.definition.wiring_problem()
    assert problem and why in problem
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
    rig = Rig(tmp_path, first_start=False)
    assert_held(rig)
    assert store.CONFIRMED_FILENAME in rig.notices() and "will not read" in rig.notices()


def test_a_record_lost_between_starts_holds_every_stored_wiring(tmp_path):
    """Only the machine's first start may record unrecorded wiring; a lost
    record at any later start is not that (`app.py` asks the database)."""
    Rig(tmp_path).save(moved(12))
    s = store.HardwareStore(tmp_path)
    s.confirmed_path.unlink()
    write_wiring(s, moved(13))  # copied in while the record was gone

    rig = Rig(tmp_path, first_start=False)
    assert_held(rig)
    assert store.CONFIRMED_FILENAME in rig.notices() and "missing" in rig.notices()
    rig.save(rig.get()["document"], confirmed_pins=True)
    assert Rig(tmp_path, first_start=False).definition.wiring_problem() is None


def test_a_record_the_first_start_cannot_write_is_trusted_that_run_only(tmp_path, monkeypatch):
    write_wiring(store.HardwareStore(tmp_path), moved(12))
    real = store._write_atomic

    def refuse(path, text):
        if path.name == store.CONFIRMED_FILENAME:
            raise PermissionError("read-only")
        return real(path, text)

    monkeypatch.setattr(store, "_write_atomic", refuse)
    assert Rig(tmp_path).definition.wiring_problem() is None, "the upgrade asks nothing"
    monkeypatch.undo()
    assert_held(Rig(tmp_path, first_start=False))


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


@pytest.mark.parametrize(
    "renames, in_force",
    [
        (0, 12),  # the pending record never landed: nothing changed
        (1, None),  # dies at the commit, too dead to put the record back: held
        (2, 13),  # committed; only the final record is lost: finished at start
    ],
)
def test_a_save_cut_off_at_any_step_never_trusts_wiring_it_was_not_saving(
    tmp_path, monkeypatch, renames, in_force
):
    """While a save is pending only the wiring it was saving is trusted: a
    death at the commit holds the last wiring once."""
    Rig(tmp_path).save(moved(12))
    rig = Rig(tmp_path)
    _fail_after_n_replaces(monkeypatch, renames)
    try:
        rig.save(moved(13))
    except OSError:
        pass
    monkeypatch.undo()

    restarted = Rig(tmp_path, first_start=False)
    if in_force is None:
        assert_held(restarted, why="did not finish")
        return
    assert restarted.definition.wiring_problem() is None
    assert registry.channels().get("left_well").index == in_force
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


def _stuck(monkeypatch, name: str) -> None:
    real = Path.unlink

    def unlink(self, *a, **k):
        if self.name == name:
            raise PermissionError("held open")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)


def test_a_superseded_layout_a_save_left_behind_is_never_put_back_in_force(tmp_path, monkeypatch):
    write_rig_json(store.HardwareStore(tmp_path), moved(12))
    rig = Rig(tmp_path)  # the upgrade: rig.json is in force and recorded
    _stuck(monkeypatch, store.RIG_FILENAME)
    rig.save(moved(13))  # cannot remove rig.json
    monkeypatch.undo()
    rig.hardware.path.unlink()  # and wiring.json is deleted by hand

    restarted = Rig(tmp_path, first_start=False)
    assert_held(restarted)
    assert restarted.get()["document"]["pins"]["left_well"]["index"] == 12, "shown, never in force"


class PowerCut(BaseException):
    """The process dies here: nothing after it in the save runs."""


def _cut_at_removing(monkeypatch, name: str) -> None:
    """A crash after `wiring.json` landed, before the save removed `name`."""
    real = Path.unlink

    def unlink(self, *a, **k):
        if self.name == name:
            raise PowerCut()
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink)


def _rig_json_then_cut_save(tmp_path, monkeypatch) -> None:
    write_rig_json(store.HardwareStore(tmp_path), moved(12))
    Rig(tmp_path)  # the upgrade: rig.json in force and recorded
    s = store.HardwareStore(tmp_path)
    _cut_at_removing(monkeypatch, store.RIG_FILENAME)
    with pytest.raises(PowerCut):
        s.save(moved(13))
    monkeypatch.undo()
    assert s.path.exists() and s.legacy_rig_path.exists()


def test_a_save_cut_off_before_its_record_never_revives_the_wiring_it_replaced(tmp_path, monkeypatch):
    _rig_json_then_cut_save(tmp_path, monkeypatch)
    store.HardwareStore(tmp_path).path.unlink()  # deleted by hand before the next start

    restarted = Rig(tmp_path, first_start=False)
    assert_held(restarted, why="did not finish")
    assert restarted.get()["document"]["pins"]["left_well"]["index"] == 12, "shown, never in force"


def test_a_save_cut_off_before_its_record_is_finished_at_the_next_start(tmp_path, monkeypatch):
    _rig_json_then_cut_save(tmp_path, monkeypatch)

    restarted = Rig(tmp_path, first_start=False)
    assert restarted.definition.wiring_problem() is None
    assert registry.channels().get("left_well").index == 13
    assert store.RIG_FILENAME not in restarted.notices(), "the replaced layout is the save's own"
    restarted.hardware.path.unlink()  # finished, so the old layout is superseded
    assert_held(Rig(tmp_path, first_start=False))


def test_an_upgrade_adopts_the_older_layout_main_left_beside_wiring_json(tmp_path):
    """Main's own save wrote wiring.json and then removed the older layouts;
    one stopped between leaves them, and main's next save would have removed
    them. So the first start adopts them as leftovers, never as copies."""
    s = store.HardwareStore(tmp_path)
    write_wiring(s, moved(12))
    write_rig_json(s, moved(9))
    rig = Rig(tmp_path)
    assert rig.get()["status"]["notices"] == []
    rig.save(moved(14))
    assert not s.legacy_rig_path.exists()


async def test_the_app_records_unrecorded_wiring_only_at_the_machine_s_first_start(tmp_path):
    from tests.wire import running_app

    data = tmp_path / "data"
    write_wiring(store.HardwareStore(data), moved(12))  # main's wiring, before the upgrade
    async with running_app(data) as app:
        assert app.rig_definition.wiring_problem() is None, "the upgrade asks nothing"
        assert registry.channels().get("left_well").index == 12

    s = store.HardwareStore(data)
    s.confirmed_path.unlink()  # the record is lost
    write_wiring(s, moved(13))  # and another machine's wiring copied in
    async with running_app(data) as app:
        problem = app.rig_definition.wiring_problem()
        assert problem and "not saved or confirmed" in problem
        assert registry.channels().content_hash() == SHIPPED_PINOUT_HASH


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


def test_the_first_start_mark_is_read_before_the_database_connects(tmp_path):
    from ephymeris_sidecar.cohorts.db import Database, has_mark

    path = tmp_path / "ephymeris.db"
    assert has_mark(path, store.FIRST_START_MARK) is False, "no database: a first start"
    db = Database(path)
    db.connect()
    assert has_mark(path, store.FIRST_START_MARK) is False, "a database that never marked it"
    db.set_mark(store.FIRST_START_MARK)
    db.set_mark(store.FIRST_START_MARK)  # idempotent
    db.close()
    assert has_mark(path, store.FIRST_START_MARK) is True
    path.write_bytes(b"not a database at all, and long enough to be read as one" * 4)
    assert has_mark(path, store.FIRST_START_MARK) is True, "unreadable: never seed twice"


def _old_record(s: store.HardwareStore, *docs: dict) -> None:
    """The record #132 wrote: a list of digests, any of which it trusted."""
    s.confirmed_path.write_text(
        json.dumps({"version": 1, "digests": [store.order_blind_digest(d) for d in docs]}),
        encoding="utf-8",
    )


def test_a_first_start_trusts_only_what_an_earlier_record_names(tmp_path):
    """#132's record named pin 12; the 13 beside it was copied in and held.
    The upgrade must not put 13 in force."""
    s = store.HardwareStore(tmp_path)
    write_wiring(s, moved(13))
    _old_record(s, moved(12))
    rig = Rig(tmp_path)
    assert_held(rig)
    assert rig.get()["document"]["pins"]["left_well"]["index"] == 13


def test_a_first_start_keeps_the_wiring_an_earlier_record_names(tmp_path):
    s = store.HardwareStore(tmp_path)
    write_wiring(s, moved(12))
    _old_record(s, moved(9), moved(12))
    rig = Rig(tmp_path)
    assert rig.definition.wiring_problem() is None, "the upgrade asks nothing"
    assert rig.get()["status"]["notices"] == []
    assert Rig(tmp_path, first_start=False).definition.wiring_problem() is None


def test_a_record_that_will_not_parse_holds_even_at_the_first_start(tmp_path):
    s = store.HardwareStore(tmp_path)
    write_wiring(s, moved(12))
    s.confirmed_path.write_text("{ damaged", encoding="utf-8")
    assert_held(Rig(tmp_path))


def test_a_cut_off_save_completes_only_for_the_wiring_it_was_saving(tmp_path, monkeypatch):
    """Save 13 over 12, the final record write fails; then a wiring.json
    holding 12 is put back. 12 was replaced: it is held, never revived."""
    rig = Rig(tmp_path)
    rig.save(moved(12))
    twelve = rig.hardware.path.read_bytes()
    real, writes = store._write_atomic, {"n": 0}

    def fail_final_record(path, text):
        if path.name == store.CONFIRMED_FILENAME:
            writes["n"] += 1
            if writes["n"] == 2:  # the pending record lands; the final one does not
                raise PermissionError("held open")
        return real(path, text)

    monkeypatch.setattr(store, "_write_atomic", fail_final_record)
    rig.save(moved(13))
    monkeypatch.undo()
    rig.hardware.path.write_bytes(twelve)

    assert_held(Rig(tmp_path, first_start=False), why="did not finish")


def test_a_save_that_fails_before_its_commit_leaves_the_last_wiring_recorded(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    rig.save(moved(12))
    _fail_replacing(monkeypatch, store.WIRING_FILENAME)
    with pytest.raises(OSError):
        rig.hardware.save(moved(13))
    monkeypatch.undo()
    restarted = Rig(tmp_path, first_start=False)
    assert restarted.definition.wiring_problem() is None
    assert registry.channels().get("left_well").index == 12


def test_a_database_restored_from_before_the_upgrade_is_not_a_first_start(tmp_path):
    """The record is lost and the database comes back from a snapshot taken
    before the mark existed: wiring copied in meanwhile is held."""
    Rig(tmp_path).save(moved(12))  # this machine has run this build
    s = store.HardwareStore(tmp_path)
    s.confirmed_path.unlink()
    write_wiring(s, moved(13))
    assert_held(Rig(tmp_path, first_start=True))  # what an unmarked database says


async def test_the_app_holds_after_a_database_restored_from_before_the_upgrade(tmp_path):
    import shutil

    from ephymeris_sidecar.cohorts.db import DB_FILENAME, Database
    from tests.wire import running_app

    data = tmp_path / "data"
    data.mkdir()
    before = Database(data / DB_FILENAME)  # main's database, before the upgrade
    before.connect()
    before.close()
    snapshot = tmp_path / "db-snapshot.db"
    shutil.copy(data / DB_FILENAME, snapshot)
    write_wiring(store.HardwareStore(data), moved(12))
    async with running_app(data) as app:
        assert app.rig_definition.wiring_problem() is None, "the upgrade asks nothing"

    s = store.HardwareStore(data)
    s.confirmed_path.unlink()
    shutil.copy(snapshot, data / DB_FILENAME)  # restored from before the mark
    write_wiring(s, moved(13))
    async with running_app(data) as app:
        problem = app.rig_definition.wiring_problem()
        assert problem and "not saved or confirmed" in problem


def test_a_first_start_shows_an_older_layout_beside_the_pair(tmp_path):
    """Only wiring.json's own migration leaves older layouts the app owns;
    a rig.json beside the pair is shown, and no save deletes it."""
    s = store.HardwareStore(tmp_path)
    write_pair(s, moved(12))
    write_rig_json(s, moved(9))
    rig = Rig(tmp_path)
    assert rig.definition.wiring_problem() is None
    assert store.RIG_FILENAME in rig.notices()
    rig.save(moved(14))
    assert s.legacy_rig_path.exists()


def _reordered(doc: dict, a: str, b: str) -> dict:
    """`doc` with channels `a` and `b` swapped in declaration order only:
    every key and value the same, so a key-sorted digest cannot see it."""
    names = list(doc["channels"])
    i, j = names.index(a), names.index(b)
    names[i], names[j] = names[j], names[i]
    return {**doc, "channels": {n: doc["channels"][n] for n in names}}


def _reorder_on_disk(s: store.HardwareStore) -> None:
    on_disk = json.loads(s.path.read_text(encoding="utf-8"))
    s.path.write_text(json.dumps(_reordered(on_disk, "odor_line_1", "odor_line_2")), encoding="utf-8")


def test_a_hand_reordered_channel_set_is_held(tmp_path):
    """Declaration order is the odor index (TASKS.md#order-is-meaning): odor
    lines swapped by hand would fire line 2 under line 1's onset code."""
    Rig(tmp_path).save(store.default_document())
    _reorder_on_disk(store.HardwareStore(tmp_path))
    assert_held(Rig(tmp_path, first_start=False))


def _order_blind_record(s: store.HardwareStore) -> None:
    """The record #134 wrote for the file on disk: one digest, blind to
    declaration order."""
    on_disk = json.loads(s.path.read_text(encoding="utf-8"))
    s.confirmed_path.write_text(
        json.dumps({"version": 1, "digest": store.order_blind_digest(on_disk), "leftovers": []}),
        encoding="utf-8",
    )


def _first_start_of_this_build(tmp_path) -> Rig:
    """The machine's first start: no database mark and no
    `wiring-record-started`. The only start that reads an order-blind record."""
    store.HardwareStore(tmp_path).started_path.unlink(missing_ok=True)
    return Rig(tmp_path, first_start=True)


def test_a_record_with_the_order_blind_digest_still_confirms_its_file(tmp_path):
    """An unswapped #134-era file under its #134 record, at a genuine first
    start: the upgrade asks nothing."""
    s = store.HardwareStore(tmp_path)
    write_wiring(s, {**moved(12), "edited_at": "2026-10-31T05:00:00Z"})
    _order_blind_record(s)

    rig = _first_start_of_this_build(tmp_path)
    assert rig.definition.wiring_problem() is None, "the upgrade asks nothing"
    assert rig.get()["status"]["notices"] == []
    assert registry.channels().get("left_well").index == 12
    _reorder_on_disk(s)  # from then on, order counts
    assert_held(Rig(tmp_path, first_start=False))


def test_a_machine_that_ran_134_holds_its_unswapped_file_once(tmp_path):
    """#134 set the database's mark but never wrote `wiring-record-started`,
    so its next start is not a first start: the order-blind record confirms
    nothing, and the unswapped file is held until one confirm."""
    s = store.HardwareStore(tmp_path)
    write_wiring(s, {**moved(12), "edited_at": "2026-10-31T05:00:00Z"})
    _order_blind_record(s)
    assert not s.started_path.exists()

    rig = Rig(tmp_path, first_start=False)  # a machine on #134, upgrading
    assert_held(rig)
    rig.save(rig.get()["document"], confirmed_pins=True)
    restarted = Rig(tmp_path, first_start=False)
    assert restarted.definition.wiring_problem() is None, "one confirm is enough"
    assert registry.channels().get("left_well").index == 12


def _swap_odor_lines(s: store.HardwareStore, doc: dict) -> None:
    s.path.write_text(json.dumps(_reordered(doc, "odor_line_1", "odor_line_2")), encoding="utf-8")


def test_a_carry_over_that_could_not_be_written_trusts_nothing_at_a_later_start(tmp_path, monkeypatch):
    """The first start converts #134's record of X but cannot write it: X is
    trusted that run only. At the next start the order-blind record is still
    on disk, and it must confirm nothing: X with its odor lines swapped least
    of all."""
    s = store.HardwareStore(tmp_path)
    x = {**moved(12), "edited_at": "2026-10-31T05:00:00Z"}
    write_wiring(s, x)
    _order_blind_record(s)
    real = store._write_atomic

    def refuse(path, text):
        if path.name == store.CONFIRMED_FILENAME:
            raise PermissionError("read-only")
        return real(path, text)

    monkeypatch.setattr(store, "_write_atomic", refuse)
    assert _first_start_of_this_build(tmp_path).definition.wiring_problem() is None, "trusted this run"
    monkeypatch.undo()

    _swap_odor_lines(s, x)
    assert_held(Rig(tmp_path, first_start=False))
    write_wiring(s, x)  # nor anything else the unwritten carry trusted
    assert_held(Rig(tmp_path, first_start=False))


def test_an_order_blind_digest_an_earlier_start_left_never_confirms_swapped_lines(tmp_path):
    """A machine that already ran #136, which left #134's digest of X
    unmatched. X with its odor lines swapped is on disk at this build's start,
    which is not the machine's first."""
    Rig(tmp_path).save(moved(12))
    s = store.HardwareStore(tmp_path)
    x = json.loads(s.path.read_text(encoding="utf-8"))
    _write_134_record(s, _blind(x))
    _swap_odor_lines(s, x)
    assert_held(Rig(tmp_path, first_start=False))
    write_wiring(s, x)
    assert_held(Rig(tmp_path, first_start=False))


def test_a_save_made_after_a_downgrade_to_134_never_confirms_swapped_lines(tmp_path):
    """Downgrade to #134, save Y there (an order-blind record), copy in Y with
    its odor lines swapped, upgrade again: that start is not a first start."""
    Rig(tmp_path).save(moved(12))  # this build has run here
    s = store.HardwareStore(tmp_path)
    y = {**moved(13), "edited_at": "2026-10-31T05:00:00Z"}
    write_wiring(s, y)  # #134's save of Y
    _write_134_record(s, _blind(y))
    _swap_odor_lines(s, y)
    assert_held(Rig(tmp_path, first_start=False))  # the upgrade again


def test_an_earlier_record_never_confirms_a_reordered_file_after_the_upgrade(tmp_path):
    s = store.HardwareStore(tmp_path)
    write_wiring(s, moved(12))
    _old_record(s, moved(12))
    assert Rig(tmp_path).definition.wiring_problem() is None
    _reorder_on_disk(s)
    assert_held(Rig(tmp_path, first_start=False))


def _blind(doc_or_path) -> str:
    if isinstance(doc_or_path, Path):
        doc_or_path = json.loads(doc_or_path.read_text(encoding="utf-8"))
    return store.order_blind_digest(doc_or_path)


def _write_134_record(s: store.HardwareStore, digest: str, pending: str | None = None) -> None:
    s.confirmed_path.write_text(
        json.dumps({"version": 1, "digest": digest, **({"pending": pending} if pending else {}), "leftovers": []}),
        encoding="utf-8",
    )


def test_an_order_blind_digest_unmatched_at_the_upgrade_never_confirms_later(tmp_path):
    """#134's record names X; at the upgrade a copy is on disk instead, so X
    is not carried over. X with two odor lines swapped, copied in after,
    must never match the order-blind digest left behind."""
    Rig(tmp_path).save(moved(12))
    s = store.HardwareStore(tmp_path)
    x = json.loads(s.path.read_text(encoding="utf-8"))
    _write_134_record(s, _blind(x))
    write_wiring(s, moved(13))  # copied in before the upgrade
    assert_held(_first_start_of_this_build(tmp_path))  # the upgrade

    s.path.write_text(json.dumps(_reordered(x, "odor_line_1", "odor_line_2")), encoding="utf-8")
    assert_held(Rig(tmp_path, first_start=False))


def test_a_broken_file_at_the_upgrade_drops_the_order_blind_digest(tmp_path):
    Rig(tmp_path).save(moved(12))
    s = store.HardwareStore(tmp_path)
    x = json.loads(s.path.read_text(encoding="utf-8"))
    _write_134_record(s, _blind(x))
    s.path.write_text("{ damaged", encoding="utf-8")
    _first_start_of_this_build(tmp_path)  # the upgrade

    s.path.write_text(json.dumps(_reordered(x, "odor_line_1", "odor_line_2")), encoding="utf-8")
    assert_held(Rig(tmp_path, first_start=False))


def test_an_order_blind_pending_save_unmatched_at_the_upgrade_never_confirms_later(tmp_path):
    """#134 crashed saving Y over X: X is on disk, Y pending. After the
    upgrade, Y with two odor lines swapped must never be taken as that save."""
    Rig(tmp_path).save(moved(12))
    s = store.HardwareStore(tmp_path)
    x = json.loads(s.path.read_text(encoding="utf-8"))
    y = {**moved(13), "edited_at": "2026-10-31T05:00:00Z"}
    _write_134_record(s, _blind(x), _blind(y))
    assert_held(_first_start_of_this_build(tmp_path), why="did not finish")  # the upgrade

    s.path.write_text(json.dumps(_reordered(y, "odor_line_1", "odor_line_2")), encoding="utf-8")
    assert_held(Rig(tmp_path, first_start=False))


def test_a_save_that_died_at_its_commit_is_described_as_saved_here(tmp_path, monkeypatch):
    """The held wiring.json IS the last wiring saved here: the notice says so,
    and that the save after it did not finish -- never 'not saved here'."""
    rig = Rig(tmp_path)
    rig.save(moved(12))
    real = store._write_atomic

    def die(path, text):
        if path.name == store.WIRING_FILENAME:
            raise PowerCut()
        return real(path, text)

    monkeypatch.setattr(store, "_write_atomic", die)
    with pytest.raises(PowerCut):
        rig.hardware.save(moved(13))
    monkeypatch.undo()

    restarted = Rig(tmp_path, first_start=False)
    assert_held(restarted, why="did not finish")
    payload = restarted.get()
    text = " ".join([n["message"] for n in payload["status"]["notices"]] + [p["message"] for p in payload["problems"]])
    assert "saved here, but a save after it did not finish" in text
    assert "not saved or confirmed" not in text
    assert "copied in" not in text


def test_a_pair_a_save_died_over_is_described_as_two_files(tmp_path, monkeypatch):
    write_pair(store.HardwareStore(tmp_path), moved(12))
    rig = Rig(tmp_path)  # the upgrade records the pair
    real = store._write_atomic

    def die(path, text):
        if path.name == store.WIRING_FILENAME:
            raise PowerCut()
        return real(path, text)

    monkeypatch.setattr(store, "_write_atomic", die)
    with pytest.raises(PowerCut):
        rig.hardware.save(moved(13))
    monkeypatch.undo()

    restarted = Rig(tmp_path, first_start=False)
    assert_held(restarted, why="did not finish")
    pair = f"{store.CHANNEL_SET_FILENAME} and {store.PIN_MAP_FILENAME}"
    assert f"{pair} were saved here, but a save after them did not finish" in restarted.definition.wiring_problem()
    payload = restarted.get()
    text = " ".join([n["message"] for n in payload["status"]["notices"]] + [p["message"] for p in payload["problems"]])
    assert f"These pins come from {pair}, saved here, but a save after them did not finish" in text
    assert "cannot vouch for them" in text
    assert "Now channel_set.json and pin_map.json are on disk: saved here, but a save after them" in text


def test_a_rig_json_left_by_a_134_migration_cut_off_is_the_app_s_own(tmp_path):
    """#134 was saving P (wiring.json) over rig.json (D) and died before
    removing rig.json. After the upgrade P is in force and rig.json is a
    leftover the next save removes; neither is trusted wrongly."""
    s = store.HardwareStore(tmp_path)
    d, p = moved(12), {**moved(13), "edited_at": "2026-10-31T05:00:00Z"}
    write_rig_json(s, d)
    s.path.write_text(json.dumps(p), encoding="utf-8")
    _write_134_record(s, _blind(d), _blind(p))

    rig = _first_start_of_this_build(tmp_path)
    assert rig.definition.wiring_problem() is None
    assert registry.channels().get("left_well").index == 13
    assert rig.get()["status"]["notices"] == []
    s.path.unlink()  # the leftover is never trusted
    assert_held(Rig(tmp_path, first_start=False))


def test_the_next_save_removes_a_rig_json_left_by_a_134_migration(tmp_path):
    s = store.HardwareStore(tmp_path)
    d, p = moved(12), {**moved(13), "edited_at": "2026-10-31T05:00:00Z"}
    write_rig_json(s, d)
    s.path.write_text(json.dumps(p), encoding="utf-8")
    _write_134_record(s, _blind(d), _blind(p))
    rig = _first_start_of_this_build(tmp_path)
    rig.save(moved(14))
    assert not s.legacy_rig_path.exists()


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

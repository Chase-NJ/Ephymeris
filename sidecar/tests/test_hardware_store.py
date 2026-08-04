"""The rig wiring document: the store, the composition, and TG227-229.

Everything here was unreachable until the pinout became editable. The shipped
pair is a transcription of BehaviorBox.h that lives inside the package and is
read-only in a frozen build, so "what if the operator types pin 300" was not a
question anyone could ask. Each of these tests is a way of asking it.

The three new rules all fail QUIETLY in the absence of a check, which is why
they are errors rather than warnings:

  TG227  a pin in the binding range is read by the board as a per-trial binding
  TG228  two channels on one pin makes every reverse lookup arbitrary
  TG229  a response port with no slot has no strobes, and compiles anyway
"""

from __future__ import annotations

import copy
import json

import pytest

from ephymeris_sidecar.hardware import store
from ephymeris_sidecar.specs import compiler
from ephymeris_sidecar.taskgraph import paradigms, registries


@pytest.fixture(autouse=True)
def _shipped_wiring():
    """Every test starts and ends on the shipped pinout.

    `set_rig_source` mutates module state and clears an `lru_cache` the whole
    compiler reads, so a test that left one installed would change what every
    later test compiles -- silently, and only when run in the same session.
    """
    registries.set_rig_source(None)
    yield
    registries.set_rig_source(None)


def rig(**edits) -> dict:
    """The shipped wiring as a rig document, with edits applied."""
    doc = store.default_document()
    for section, changes in edits.items():
        for name, value in changes.items():
            if value is None:
                doc[section].pop(name, None)
            else:
                doc[section].setdefault(name, {}).update(value)
    return doc


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


def test_an_unedited_rig_reads_as_the_shipped_pinout(tmp_path):
    s = store.HardwareStore(tmp_path)
    assert not s.exists()
    assert s.load() is None
    assert s.status().custom is False


def test_the_default_document_is_the_shipped_wiring_and_composes_back(tmp_path):
    """The seed is READ from the shipped files, never written out by hand.

    A hand-written default would be a third description of the same box, which
    is the mirroring this whole area exists to avoid.
    """
    doc = store.default_document()
    assert store.validate(doc) == []

    registries.set_rig_source(lambda: doc)
    composed = registries.channels()
    shipped_names = {c.name for c in registries.ChannelMap(
        registries._load("channels.v1.json"), registries._pinout()
    )}
    assert {c.name for c in composed} == shipped_names
    assert composed.disagreements() == []
    assert composed.pin_problems() == []
    assert composed.duplicate_pins() == []
    assert composed.slot_problems(registries.vocabulary()) == []


def test_a_document_that_fails_validation_is_not_written(tmp_path):
    """Validation happens BEFORE the write, so there is no state in which the
    file on disk is one the compiler refuses."""
    s = store.HardwareStore(tmp_path)
    with pytest.raises(store.RigInvalid):
        s.save({"rig_version": 1, "channels": {}, "pins": {}})  # minProperties
    assert not s.exists()


def test_save_reports_every_problem_not_just_the_first(tmp_path):
    doc = rig()
    doc["channels"]["odor_port"]["kind"] = "not_a_kind"
    doc["pins"]["odor_port"]["index"] = -1
    with pytest.raises(store.RigInvalid) as exc:
        store.HardwareStore(tmp_path).save(doc)
    assert len(exc.value.problems) >= 2


def test_a_saved_document_round_trips_and_carries_a_stamp(tmp_path):
    s = store.HardwareStore(tmp_path)
    stored = s.save(rig())
    assert s.exists()
    assert stored["edited_at"]
    assert json.loads(s.path.read_text())["channels"] == stored["channels"]
    assert s.status().custom is True

    s.reset()
    assert not s.exists()
    assert s.status().custom is False


def test_an_unparseable_document_falls_back_rather_than_raising(tmp_path):
    """A rig running the wiring its box shipped with beats a sidecar that will
    not start with six serial ports open."""
    s = store.HardwareStore(tmp_path)
    s.root.mkdir(parents=True, exist_ok=True)
    s.path.write_text("{ not json")
    assert s.load() is None


def test_a_path_traversing_channel_name_dies_at_the_schema(tmp_path):
    doc = rig()
    doc["channels"]["../../evil"] = {"kind": "cue"}
    doc["pins"]["../../evil"] = {"index": 12}
    problems = store.validate(doc)
    assert problems, "a channel name is written into specs by hand; it needs a shape"


# --------------------------------------------------------------------------- #
# The compiler reads the rig
# --------------------------------------------------------------------------- #


def test_a_repin_changes_the_bytes_and_not_the_spec_hash():
    """D15, demonstrated rather than asserted.

    A spec names channels, never numbers, so re-wiring a box changes what every
    task compiles to and moves no spec_hash. That is correct and it is also the
    provenance hole: without a pinout stamp these two tables are
    indistinguishable in the record.
    """
    text = paradigms.to_yaml(paradigms.skeleton(paradigms.get("two_afc"), spec_id="probe"))

    before = compiler.compile(text, spec_id="probe")
    bytes_before, _ = compiler.table_bytes(before)

    moved = rig(pins={"left_well": {"index": 12}})
    registries.set_rig_source(lambda: moved)
    after = compiler.compile(text, spec_id="probe")
    bytes_after, _ = compiler.table_bytes(after)

    assert after.ok
    assert before.table.spec_hash == after.table.spec_hash
    assert bytes_before != bytes_after
    assert [p.channel for p in after.table.ports] != [p.channel for p in before.table.ports]


def test_the_cache_is_cleared_on_a_rig_change_within_one_process():
    """`channels()` is lru_cached and read on every keystroke compile. Without
    invalidation the second compile here would return the first one's table."""
    text = paradigms.to_yaml(paradigms.skeleton(paradigms.get("two_afc"), spec_id="probe"))
    first, _ = compiler.table_bytes(compiler.compile(text, spec_id="probe"))

    moved = rig(pins={"right_well": {"index": 11}})
    registries.set_rig_source(lambda: moved)
    second, _ = compiler.table_bytes(compiler.compile(text, spec_id="probe"))

    assert first != second


# --------------------------------------------------------------------------- #
# TG227 / TG228 / TG229
# --------------------------------------------------------------------------- #


def codes_for(doc: dict) -> set[str]:
    registries.set_rig_source(lambda: doc)
    text = paradigms.to_yaml(paradigms.skeleton(paradigms.get("two_afc"), spec_id="probe"))
    result = compiler.compile(text, spec_id="probe")
    return {d.code for d in result.bag if d.severity.name == "ERROR"}


def test_tg227_a_pin_in_the_binding_range_is_refused():
    """0xF0 up is how `lower.py` encodes "@stim[0].emitter" in the same byte.

    A channel placed there is not rejected by the board — it is READ as a
    per-trial binding, which is the quietest possible way to be wrong.
    """
    assert "TG227" in codes_for(rig(pins={"trial_light": {"index": 0xF2}}))


def test_tg227_a_pin_this_board_does_not_have_is_refused():
    assert "TG227" in codes_for(rig(pins={"trial_light": {"index": 200}}))


def test_tg228_two_channels_on_one_pin_are_refused():
    """Legal on a breadboard, never legal here: `watch_port` inverts pin to port
    and the bench card inverts pin to name, and both would pick arbitrarily."""
    both = registries.channels().get("trial_light").index
    assert "TG228" in codes_for(rig(pins={"vacuum": {"index": both}}))


def test_tg229_a_response_port_without_a_slot_is_refused():
    """The failure the slot table was built to end.

    It used to happen by NAME and in silence: a well not called `left_well` or
    `right_well` got no per-port codes at all and compiled, surfacing later as
    TG506 the first time a shape change reached for one.
    """
    doc = rig()
    doc["channels"]["left_well"].pop("port_slot")
    assert "TG229" in codes_for(doc)


def test_tg229_two_ports_on_one_slot_are_refused():
    doc = rig()
    doc["channels"]["left_well"]["port_slot"] = 2  # right_well already holds 2
    assert "TG229" in codes_for(doc)


def test_tg229_a_slot_the_vocabulary_does_not_define_is_refused():
    doc = rig()
    doc["channels"]["left_well"]["port_slot"] = 9  # seven slots exist
    assert "TG229" in codes_for(doc)


def test_the_shipped_wiring_trips_none_of_them():
    """The regression guard for all four: if any rule fires on the wiring the
    app ships with, it is the rule that is wrong."""
    chans = registries.channels()
    assert chans.disagreements() == []
    assert chans.pin_problems() == []
    assert chans.duplicate_pins() == []
    assert chans.slot_problems(registries.vocabulary()) == []


def test_the_binding_constant_has_not_drifted():
    """`CH_BIND_RESERVED_FROM` is a second copy of `table.CH_BIND_BASE`, taken
    to avoid an import cycle. This is what stops it drifting silently."""
    from ephymeris_sidecar.taskgraph.table import CH_BIND_BASE

    assert registries.CH_BIND_RESERVED_FROM == CH_BIND_BASE


def test_the_default_document_is_the_shipped_wiring_even_with_a_rig_installed():
    """`default_document()` must read the SHIPPED pair, not the wiring in force.

    Reading `registries.channels()` would make "default" mean "whatever you last
    saved" — so Reset would reset to itself — and it recurses, because
    `channels()` consults the rig source and the rig source is what asks for a
    default. Caught by a test whose lambda happened to be lazy.
    """
    shipped = store.default_document()
    registries.set_rig_source(lambda: rig(pins={"left_well": {"index": 12}}))
    assert store.default_document() == shipped

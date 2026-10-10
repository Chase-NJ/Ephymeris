"""The rig wiring document: the store, the composition, and RIG101-106.

Everything here was unreachable until the pinout became editable. The shipped
pair is a transcription of BehaviorBox.h that lives inside the package and is
read-only in a frozen build, so "what if the operator types pin 300" was not a
question anyone could ask. Each of these tests is a way of asking it.

The four rules all fail QUIETLY in the absence of a check, which is why they are
errors rather than warnings:

  RIG101  two halves describing different boxes, or a non-dense watch_bit
  RIG102  a pin the board does not have compiles fine and never fires
  RIG103  two channels on one pin makes every reverse lookup arbitrary
  RIG104  a response port with no slot has no strobes, and generates anyway
  RIG105  a second sync line is a wire believed to carry events that carries none
  RIG106  an odor line with no onset code of its own records its odor as another
"""

from __future__ import annotations

import json

import pytest

from ephymeris_sidecar.hardware import service, store
from ephymeris_sidecar.rig import registry


@pytest.fixture(autouse=True)
def _shipped_wiring():
    """Every test starts and ends on the shipped pinout.

    `set_rig_source` mutates module state and clears a cache every reader
    shares, so a test that left one installed would change what every later test
    resolves -- silently, and only when run in the same session.
    """
    registry.set_rig_source(None)
    yield
    registry.set_rig_source(None)


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


def codes_for(doc: dict) -> set[str]:
    """The rule codes this document trips, through the path the editor uses."""
    return {p["code"] for p in service.problems_for(doc) if p["code"]}


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

    registry.set_rig_source(lambda: doc)
    composed = registry.channels()
    shipped_names = {c.name for c in registry.shipped_channels()}
    assert {c.name for c in composed} == shipped_names
    assert composed.disagreements() == []
    assert composed.pin_problems() == []
    assert composed.duplicate_pins() == []
    assert composed.slot_problems(registry.vocabulary()) == []


def test_a_document_that_fails_validation_is_not_written(tmp_path):
    """Validation happens BEFORE the write, so there is no state in which the
    file on disk is one the app refuses."""
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
    assert json.loads(s.path.read_text(encoding="utf-8"))["channels"] == stored["channels"]
    assert s.status().custom is True

    s.reset()
    assert not s.exists()
    assert s.status().custom is False


def test_an_unparseable_document_falls_back_rather_than_raising(tmp_path):
    """A rig running the wiring its box shipped with beats a sidecar that will
    not start with six serial ports open."""
    s = store.HardwareStore(tmp_path)
    s.root.mkdir(parents=True, exist_ok=True)
    s.path.write_text("{ not json", encoding="utf-8")
    assert s.load() is None


def test_a_path_traversing_channel_name_dies_at_the_schema(tmp_path):
    doc = rig()
    doc["channels"]["../../evil"] = {"kind": "cue"}
    doc["pins"]["../../evil"] = {"index": 12}
    problems = store.validate(doc)
    assert problems, "a channel name reaches a generated header; it needs a shape"


# --------------------------------------------------------------------------- #
# The registries read the rig
# --------------------------------------------------------------------------- #


def test_a_repin_resolves_to_the_new_pin():
    """A task profile names channels, never numbers, so re-wiring a box changes
    what every task compiles to and moves no `profile_hash`. That is correct and
    it is also the provenance hole `content_hash` exists to close."""
    assert registry.channels().get("left_well").index != 12

    registry.set_rig_source(lambda: rig(pins={"left_well": {"index": 12}}))
    assert registry.channels().get("left_well").index == 12


def test_the_cache_is_cleared_on_a_rig_change_within_one_process():
    """`channels()` is cached. Without invalidation the second read here
    would return the first one's map."""
    first = registry.channels().get("right_well").index

    registry.set_rig_source(lambda: rig(pins={"right_well": {"index": 11}}))
    assert registry.channels().get("right_well").index == 11 != first


# --------------------------------------------------------------------------- #
# RIG101 / RIG102 / RIG103 / RIG104
# --------------------------------------------------------------------------- #


def test_rig102_a_pin_this_board_does_not_have_is_refused():
    assert "RIG102" in codes_for(rig(pins={"trial_light": {"index": 200}}))


def test_rig103_two_channels_on_one_pin_are_refused():
    """Legal on a breadboard, never legal here: the pin table inverts pin to
    name, and two names on one pin makes that answer arbitrary."""
    both = registry.channels().get("trial_light").index
    assert "RIG103" in codes_for(rig(pins={"vacuum": {"index": both}}))


def test_rig104_a_response_port_without_a_slot_is_refused():
    """The failure the slot table was built to end.

    It used to happen by NAME and in silence: a well not called `left_well` or
    `right_well` got no per-port codes at all, so a trial answered there reported
    nothing.
    """
    doc = rig()
    doc["channels"]["left_well"].pop("port_slot")
    assert "RIG104" in codes_for(doc)


def test_rig104_two_ports_on_one_slot_are_refused():
    doc = rig()
    doc["channels"]["left_well"]["port_slot"] = 2  # right_well already holds 2
    assert "RIG104" in codes_for(doc)


def test_rig104_a_slot_the_vocabulary_does_not_define_is_refused():
    doc = rig()
    doc["channels"]["left_well"]["port_slot"] = 9  # seven slots exist
    assert "RIG104" in codes_for(doc)


def test_rig101_halves_that_describe_different_boxes_are_refused():
    doc = rig()
    doc["pins"].pop("vacuum")
    assert "RIG101" in codes_for(doc)


def test_rig106_an_odor_line_without_an_onset_is_reported():
    doc = rig()
    doc["channels"]["odor_line_2"].pop("onset_strobe")
    assert "RIG106" in codes_for(doc)


def test_rig106_two_lines_announcing_one_code_are_reported():
    doc = rig()
    doc["channels"]["odor_line_2"]["onset_strobe"] = "ODOR_1_ON"
    assert "RIG106" in codes_for(doc)


def test_rig106_an_onset_the_vocabulary_lacks_is_reported():
    doc = rig()
    doc["channels"]["odor_line_2"]["onset_strobe"] = "ODOR_99_ON"
    assert "RIG106" in codes_for(doc)


def test_rig106_a_code_that_is_not_an_onset_is_reported():
    """LIGHTS_ON is a live code and the wrong kind of one."""
    doc = rig()
    doc["channels"]["odor_line_2"]["onset_strobe"] = "LIGHTS_ON"
    assert "RIG106" in codes_for(doc)


def test_rig106_an_onset_on_a_channel_that_is_not_an_emitter_is_reported():
    doc = rig()
    doc["channels"]["trial_light"]["onset_strobe"] = "ODOR_2_ON"
    assert "RIG106" in codes_for(doc)


def test_an_onset_declaration_does_not_move_the_pinout_hash():
    """It changes no compiled byte — the generator emits the row's code — so a
    hash that moved with it would churn every rig's provenance for nothing."""
    baseline = registry.channels().content_hash()
    doc = rig()
    doc["channels"]["odor_line_1"]["onset_strobe"] = "ODOR_9_ON"
    doc["channels"]["odor_line_9"]["onset_strobe"] = "ODOR_1_ON"
    registry.set_rig_source(lambda: doc)
    assert registry.channels().content_hash() == baseline


def test_a_rig_saved_before_onsets_existed_is_filled_from_the_shipped_wiring(tmp_path):
    """By name and kind only: a line this rig added stays undeclared, and RIG106
    asks the operator rather than anything guessing."""
    doc = rig()
    for channel in doc["channels"].values():
        channel.pop("onset_strobe", None)
    doc["channels"]["channel_99"] = {"kind": "emitter", "label": "channel 99"}
    doc["pins"]["channel_99"] = {"index": 53}
    s = store.HardwareStore(tmp_path)
    s.root.mkdir(parents=True)
    s.path.write_text(json.dumps(doc), encoding="utf-8")

    loaded = s.load()
    assert loaded["channels"]["odor_line_3"]["onset_strobe"] == "ODOR_3_ON"
    assert "onset_strobe" not in loaded["channels"]["channel_99"]
    assert "RIG106" in codes_for(loaded)


def test_the_shipped_wiring_trips_none_of_them():
    """The regression guard for all of them: if any rule fires on the wiring the
    app ships with, it is the rule that is wrong."""
    chans = registry.channels()
    assert chans.disagreements() == []
    assert chans.pin_problems() == []
    assert chans.duplicate_pins() == []
    assert chans.slot_problems(registry.vocabulary()) == []
    assert chans.sync_problems() == []
    assert chans.onset_problems(registry.vocabulary()) == []


def test_rig105_a_second_sync_line_is_refused_and_none_at_all_is_not():
    """The firmware pulses ONE line, so a second sync channel is a wire that is
    believed to carry events and carries nothing.

    Zero is legal, and deliberately: a box with no recording controller has no
    sync line. It is the recording walkthrough that refuses such a rig, because
    only there is the absence a problem.
    """
    doc = rig(channels={"sync_two": {"kind": "sync"}}, pins={"sync_two": {"index": 47}})
    assert "RIG105" in codes_for(doc)

    doc = rig(channels={"sync_out": None}, pins={"sync_out": None})
    assert codes_for(doc) == set()


def test_the_default_document_is_the_shipped_wiring_even_with_a_rig_installed():
    """`default_document()` must read the SHIPPED pair, not the wiring in force.

    Reading `registry.channels()` would make "default" mean "whatever you last
    saved" — so Reset would reset to itself — and it recurses, because
    `channels()` consults the rig source and the rig source is what asks for a
    default. Caught by a test whose lambda happened to be lazy.
    """
    shipped = store.default_document()
    registry.set_rig_source(lambda: rig(pins={"left_well": {"index": 12}}))
    assert store.default_document() == shipped


# --------------------------------------------------------------------------- #
# The pinout hash — what makes a re-pin visible in the record
# --------------------------------------------------------------------------- #


def test_the_pinout_hash_moves_on_wiring_and_not_on_prose():
    """It answers "could these produce different bytes?", so a reworded
    rationale must not move it — a hash that changed on a typo fix would train
    people to ignore it."""
    baseline = registry.channels().content_hash()

    registry.set_rig_source(lambda: rig(channels={"odor_port": {"rationale": "reworded"}}))
    assert registry.channels().content_hash() == baseline

    registry.set_rig_source(lambda: rig(channels={"odor_port": {"label": "nose port"}}))
    assert registry.channels().content_hash() == baseline

    registry.set_rig_source(lambda: rig(pins={"odor_port": {"index": 7}}))
    assert registry.channels().content_hash() != baseline


def test_a_kind_change_moves_the_hash_even_though_no_pin_did():
    """`direction` comes from the kind, and a reward line that became an input
    is a real difference the pins alone cannot show."""
    baseline = registry.channels().content_hash()
    registry.set_rig_source(lambda: rig(channels={"fluid_3": {"kind": "cue"}}))
    assert registry.channels().content_hash() != baseline


# --------------------------------------------------------------------------- #
# The strobe vocabulary
# --------------------------------------------------------------------------- #


def test_the_vocabulary_never_reissues_a_taken_or_retired_code():
    """Append-only is a DATA guarantee: tens of thousands of recorded events
    carry these numbers, and reissuing one merges two unrelated event types in
    any analysis spanning the change."""
    vocab = registry.vocabulary()

    for entry in vocab:
        assert not vocab.is_free(entry.code), entry.name
    for code in vocab.retired:
        assert not vocab.is_free(code), code

    free = vocab.next_free()
    assert free is not None
    assert vocab.is_free(free)
    assert vocab.name_of(free) is None
    assert vocab.retired_name(free) is None


def test_a_response_port_resolves_its_six_codes_by_slot_not_by_name():
    """The historical `_L`/`_R` families are slots 1 and 2, so a recorded session
    decodes exactly as it always did."""
    vocab = registry.vocabulary()
    left = registry.channels().get("left_well")
    right = registry.channels().get("right_well")

    assert vocab.port_slot(left.port_slot)["enter_code"] == "WATER_POKE_L"
    assert vocab.port_slot(right.port_slot)["enter_code"] == "WATER_POKE_R"
    assert vocab.port_slot(right.port_slot)["reward_code"] == "FLUID_R"

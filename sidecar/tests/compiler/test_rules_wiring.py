"""The wiring rules — TG227, TG228, TG229 — called directly.

A THIRD REASON A RULE CANNOT HAVE A BROKEN-SPEC FIXTURE. The two the registry
guard already knew about are graph rules (which fire on template bugs, so they
take a GraphView) and rules the JSON Schema shadows (which reject the document
before binding runs). These three are neither: they fire on a *different
document entirely*. The spec is fine; the RIG is wrong. A spec cannot express a
duplicate pin, because a spec never mentions a pin.

So the negative case is a `ChannelMap` composed from a deliberately broken
wiring document, checked through the same `SpecContext` the pipeline builds.

All three fail quietly without a check, which is why they are errors:

  TG227  a pin at 0xF0 or above is encoded exactly like "@stim[0].emitter",
         so the board READS it as a per-trial binding rather than refusing it
  TG228  `watch_port` inverts pin→port and the bench card inverts pin→name;
         two channels on one pin makes both answers arbitrary
  TG229  a response port with no slot has no per-port strobes at all, and
         compiles, because each of those fields is individually optional
"""

from __future__ import annotations

import copy

import pytest

from ephymeris_sidecar.taskgraph import registries
from ephymeris_sidecar.taskgraph.context import SpecContext
from ephymeris_sidecar.taskgraph.lint import load_all_rules
from ephymeris_sidecar.taskgraph.lint.rules_spec import (
    duplicate_pin,
    pin_out_of_range,
    port_slot,
)
from ephymeris_sidecar.taskgraph.loader import bind
from tests.compiler.helpers import base_document

load_all_rules()


def context_for(**edits) -> SpecContext:
    """A SpecContext whose channel map is the shipped wiring, edited.

    The spec is the ordinary base document throughout: none of these rules
    reads it, which is the point.
    """
    logical = copy.deepcopy(registries._load("channels.v1.json"))
    pinout = copy.deepcopy(registries._pinout())
    for name, index in edits.get("pins", {}).items():
        pinout["pins"].setdefault(name, {})["index"] = index
    for name, patch in edits.get("channels", {}).items():
        if patch is None:
            logical["channels"][name].pop("port_slot", None)
        else:
            logical["channels"][name].update(patch)

    return SpecContext(
        spec=bind(base_document()),
        vocab=registries.vocabulary(),
        channels=registries.ChannelMap(logical, pinout),
        limits=registries.limits(),
    )


def codes(rule, ctx) -> list[str]:
    return [d.code for d in rule(ctx)]


# --------------------------------------------------------------------------- #
# TG227 — pin out of range
# --------------------------------------------------------------------------- #


def test_a_pin_in_the_binding_range_is_reported():
    """The dangerous half. `lower.py::channel_index` packs a runtime binding
    into the same byte as a pin, relying on pins staying below 0xF0."""
    ctx = context_for(pins={"trial_light": registries.CH_BIND_RESERVED_FROM})
    assert codes(pin_out_of_range, ctx) == ["TG227"]


def test_a_pin_the_board_does_not_have_is_reported():
    """The useful half: pin 200 on a Mega is a typo, and saying so beats
    letting it reach a table."""
    ctx = context_for(pins={"trial_light": 200})
    assert codes(pin_out_of_range, ctx) == ["TG227"]
    assert "0-53" in next(iter(pin_out_of_range(ctx))).message


def test_the_shipped_wiring_has_no_pin_problems():
    assert codes(pin_out_of_range, context_for()) == []


# --------------------------------------------------------------------------- #
# TG228 — duplicate pin
# --------------------------------------------------------------------------- #


def test_two_channels_on_one_pin_are_reported():
    shared = registries.channels().get("trial_light").index
    ctx = context_for(pins={"vacuum": shared})
    found = list(duplicate_pin(ctx))
    assert [d.code for d in found] == ["TG228"]
    assert "trial_light" in found[0].message and "vacuum" in found[0].message


def test_the_shipped_wiring_has_no_duplicate_pins():
    assert codes(duplicate_pin, context_for()) == []


# --------------------------------------------------------------------------- #
# TG229 — port slot
# --------------------------------------------------------------------------- #


def test_a_response_port_with_no_slot_is_reported():
    """The failure the slot table was built to end.

    It used to happen by NAME: `_SIDE` mapped `left_well`/`right_well` to
    `_L`/`_R` and returned nothing for anything else, so a differently-named
    well got a port with no codes and compiled anyway.
    """
    ctx = context_for(channels={"left_well": None})
    found = list(port_slot(ctx))
    assert [d.code for d in found] == ["TG229"]
    assert "left_well" in found[0].message


def test_two_ports_on_one_slot_are_reported():
    ctx = context_for(channels={"left_well": {"port_slot": 2}})
    found = list(port_slot(ctx))
    assert [d.code for d in found] == ["TG229"]
    assert "indistinguishable" in found[0].message


def test_a_slot_the_vocabulary_does_not_define_is_reported():
    ctx = context_for(channels={"left_well": {"port_slot": 99}})
    assert codes(port_slot, ctx) == ["TG229"]


def test_the_shipped_wiring_has_no_slot_problems():
    assert codes(port_slot, context_for()) == []


@pytest.mark.parametrize("slot", [1, 2])
def test_the_historical_slots_keep_their_families(slot):
    """Slots 1 and 2 must stay the `_L`/`_R` codes. Anything else silently
    re-decodes every recorded session."""
    codes_ = registries.vocabulary().port_slot(slot)
    suffix = "_L" if slot == 1 else "_R"
    assert all(name.endswith(suffix) for name in codes_.values())

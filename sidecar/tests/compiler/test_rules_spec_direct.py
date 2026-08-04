"""Spec rules that no YAML document can reach.

Most TG2xx rules are exercised by a fixture in tests/broken/. A few cannot be,
because the JSON Schema rejects the document first and binding never runs -- so
the rule never sees the input it exists to reject.

That is not a reason to delete the rule. The schema and the linter overlap on
purpose: the schema says what is well-formed, the linter owns the SEMANTIC, and a
safety-critical bound that lives only in the schema is a bound that quietly
disappears the day someone relaxes the schema. But it does mean the negative test
has to construct the spec in memory and call the rule directly.
"""

from __future__ import annotations

from ephymeris_sidecar.taskgraph.context import SpecContext
from ephymeris_sidecar.taskgraph.lint import load_all_rules
from ephymeris_sidecar.taskgraph.lint.rules_spec import duration_out_of_range
from ephymeris_sidecar.taskgraph.loader import bind
from tests.compiler.helpers import base_document
from tests.compiler.tgpaths import SCHEMA_DIR

load_all_rules()


def test_TG204_rejects_a_duration_above_uint16():
    """A duration the timing vector cannot hold.

    Unreachable from YAML: task_spec.v1.json caps `ms` at 65535, so the schema
    errors and load() returns None before the linter runs.

    The rule matters anyway. Firmware stored timings as signed int and used 32767
    as the StageStep "never" sentinel, putting a legal duration one step from a
    magic one; uint16 removed that collision. Wrapping instead of rejecting would
    reintroduce it in a worse form -- a 70-second delay silently becoming 4.5
    seconds is a session that looks fine and is not. See docs/decisions.md D6.
    """
    doc = base_document()
    doc["timing"][10]["ms"] = 70000
    spec = bind(doc)

    found = list(duration_out_of_range(SpecContext(spec=spec)))

    assert len(found) == 1
    assert found[0].code == "TG204"
    assert "70000" in found[0].message
    assert found[0].location == "timing[10].ms"


def test_TG204_rejects_an_over_range_stage_rewrite():
    """The same bound, on the other side of the ramp.

    A stage row rewrites the timing vector at runtime, so an over-range value here
    lands in the same uint16 slot -- and this path has no schema check at all once
    the value is computed rather than authored.
    """
    doc = base_document()
    doc["policy"]["stage_schedule"] = [{"at_trial": 0, "set": {"t_commit_hold": 99999}}]
    spec = bind(doc)

    found = list(duration_out_of_range(SpecContext(spec=spec)))

    assert [d.code for d in found] == ["TG204"]
    assert "99999" in found[0].message


def test_TG204_accepts_the_boundary():
    """65535 is legal; 65536 is not. Off-by-one here would reject a valid task."""
    doc = base_document()
    doc["timing"][10]["ms"] = 65535
    assert not list(duration_out_of_range(SpecContext(spec=bind(doc))))


def test_TG225_requires_exactly_one_engagement_channel():
    """The engagement port is resolved by KIND, not by name.

    No spec names it -- an engagement port is a structural fact of the epoch model,
    not a per-task choice -- so the template asks the registry for "the engagement
    channel". With zero or two, that resolution picks wrong or crashes, and EVERY
    trial in EVERY task routes through it.

    Unreachable from a YAML fixture: the defect is in schema/channels.v1.json, not
    in any spec. See docs/decisions.md D15.
    """
    import copy
    import json
    from pathlib import Path

    from ephymeris_sidecar.taskgraph.lint.rules_spec import engagement_channel_unresolvable
    from ephymeris_sidecar.taskgraph.registries import ChannelMap, _pinout

    raw = json.loads((SCHEMA_DIR / "channels.v1.json").read_text(encoding="utf-8"))
    # The pinout is the second half of a ChannelMap now; these cases mangle the
    # LOGICAL half only, so the real pinout rides along unchanged.
    pinout = _pinout()
    spec = bind(base_document())

    # The real registry is well-formed.
    ctx = SpecContext(spec=spec, channels=ChannelMap(raw, pinout))
    assert not list(engagement_channel_unresolvable(ctx))

    # Two engagement channels: ambiguous.
    two = copy.deepcopy(raw)
    two["channels"]["right_well"]["kind"] = "engagement"
    found = list(engagement_channel_unresolvable(SpecContext(spec=spec, channels=ChannelMap(two, pinout))))
    assert [d.code for d in found] == ["TG225"]
    assert "found 2" in found[0].message

    # None at all: nothing to watch.
    none = copy.deepcopy(raw)
    none["channels"]["odor_port"]["kind"] = "response"
    found = list(engagement_channel_unresolvable(SpecContext(spec=spec, channels=ChannelMap(none, pinout))))
    assert [d.code for d in found] == ["TG225"]
    assert "found 0" in found[0].message


def test_TG226_reports_every_way_the_pinout_and_the_registry_disagree():
    """Unreachable from a YAML document: no spec can misconfigure the registries.

    The three cases are the three shapes of "these two files describe different
    boxes", and they are reported together rather than one at a time -- bringing
    up a new pinout should be one pass over a list, not whack-a-mole.
    """
    import copy
    import json

    from ephymeris_sidecar.taskgraph.lint.rules_spec import pinout_disagrees_with_registry
    from ephymeris_sidecar.taskgraph.registries import ChannelMap, _pinout

    raw = json.loads((SCHEMA_DIR / "channels.v1.json").read_text(encoding="utf-8"))
    pins = _pinout()
    spec = bind(base_document())

    def codes(logical, pinout):
        ctx = SpecContext(spec=spec, channels=ChannelMap(logical, pinout))
        return list(pinout_disagrees_with_registry(ctx))

    # The shipped pair agree.
    assert not codes(raw, pins)

    # 1. A channel the pinout gives no pin.
    unplaced = copy.deepcopy(pins)
    del unplaced["pins"]["odor_line_12"]
    found = codes(raw, unplaced)
    assert [d.code for d in found] == ["TG226"]
    assert "odor_line_12" in found[0].message
    assert found[0].location.startswith("hardware/")

    # 2. A pin for a channel nobody declares.
    extra = copy.deepcopy(pins)
    extra["pins"]["odor_line_13"] = {"index": 35}
    found = codes(raw, extra)
    assert [d.code for d in found] == ["TG226"]
    assert found[0].location == "schema/channels.v1.json"

    # 3. A watch_bit gap. This one is the reason the split was worth making:
    #    watchMask is a uint8 and watch_bit is a BIT POSITION, so a hole does not
    #    fail -- it silently watches a different beam.
    gapped = copy.deepcopy(pins)
    gapped["pins"]["left_well"]["watch_bit"] = 5
    found = codes(raw, gapped)
    assert [d.code for d in found] == ["TG226"]
    assert "dense" in found[0].message and "[0, 1, 5]" in found[0].message

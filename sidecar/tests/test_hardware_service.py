"""`hardware.*` — the payloads, and the impact check that gates a save.

The rule this module inherits from `specs/service.py`: a document that is
WELL-FORMED and describes an impossible box is not a command error. It is a
successful reply carrying located problems, exactly as a spec that will not
compile is a successful `specs.compile`. `RIG_INVALID` is for a document that is
not a document.

`conftest.py` sets `EPHYMERIS_WIRE_VALIDATE=1` globally, so every payload built
here is checked against `protocol/schema.py` on the way out. That is what makes
these tests cover the wire shape and not just the values.
"""

from __future__ import annotations

import pytest

from ephymeris_sidecar.hardware import service, store
from ephymeris_sidecar.specs import store as spec_store
from ephymeris_sidecar.taskgraph import paradigms, registries


@pytest.fixture(autouse=True)
def _shipped_wiring():
    registries.set_rig_source(None)
    yield
    registries.set_rig_source(None)


@pytest.fixture
def rig_store(tmp_path):
    return store.HardwareStore(tmp_path)


@pytest.fixture
def specs(tmp_path):
    """A spec library with one task in it, saved against the shipped wiring."""
    s = spec_store.SpecStore(tmp_path)
    text = paradigms.to_yaml(paradigms.skeleton(paradigms.get("two_afc"), spec_id="grgl"))
    s.save("grgl", text)
    return s


def rig(**edits) -> dict:
    doc = store.default_document()
    for section, changes in edits.items():
        for name, value in changes.items():
            if value is None:
                doc[section].pop(name, None)
            else:
                doc[section].setdefault(name, {}).update(value)
    return doc


# --------------------------------------------------------------------------- #
# hardware.get
# --------------------------------------------------------------------------- #


def test_an_unedited_rig_gets_the_shipped_wiring_as_an_editable_document(rig_store):
    """The editor always opens something real rather than a blank form."""
    payload = service.document_payload(rig_store)
    assert payload["status"]["custom"] is False
    assert payload["problems"] == []
    assert payload["document"]["channels"]["odor_port"]["kind"] == "engagement"
    assert payload["status"]["pinoutHash"] == registries.channels().content_hash()


def test_a_broken_document_is_still_served(rig_store):
    """Refusing to show a broken document would be refusing to show the one
    that needs fixing."""
    rig_store.root.mkdir(parents=True, exist_ok=True)
    doc = rig()
    doc["pins"]["trial_light"]["index"] = 200
    rig_store.path.write_text(__import__("json").dumps(doc), encoding="utf-8")

    payload = service.document_payload(rig_store)
    assert payload["document"]["pins"]["trial_light"]["index"] == 200
    assert [p["code"] for p in payload["problems"]] == ["TG227"]


# --------------------------------------------------------------------------- #
# problems: schema and rules, merged
# --------------------------------------------------------------------------- #


def test_a_shape_violation_is_located_on_its_field():
    problems = service.problems_for(rig(channels={"odor_port": {"kind": "nonsense"}}))
    assert problems
    assert problems[0]["location"].startswith("channels.odor_port")
    assert problems[0]["code"] is None, "a schema violation has no rule number"


def test_a_sense_violation_carries_its_rule():
    """Pin 200 is a legal integer and not a pin a Mega has — schema-clean,
    rule-dirty, which is exactly the split."""
    problems = service.problems_for(rig(pins={"trial_light": {"index": 200}}))
    assert [p["code"] for p in problems] == ["TG227"]
    assert "0-53" in problems[0]["message"]


def test_the_binding_range_is_bounded_twice_and_the_schema_wins():
    """`CH_BIND_RESERVED_FROM` is 0xF0 and the schema caps `index` at 239, so a
    pin in the binding range never reaches TG227 through this path.

    That is the overlap `rules_spec_direct.py` describes and it is deliberate:
    the schema says what is well-formed, the rule owns the SEMANTIC, and a
    safety-critical bound living only in the schema is one that disappears the
    day someone relaxes the schema. The rule's own coverage is direct, in
    tests/compiler/test_rules_wiring.py.
    """
    problems = service.problems_for(rig(pins={"trial_light": {"index": 0xF5}}))
    assert problems
    assert all(p["code"] is None for p in problems)
    assert problems[0]["location"] == "pins.trial_light.index"


def test_shape_is_reported_before_sense():
    """A document that failed the schema may not have the sections the rules
    read, and "channels is not an object" beats a KeyError from a rule."""
    problems = service.problems_for({"rig_version": 1, "channels": "nope", "pins": {}})
    assert problems and all(p["code"] is None for p in problems)


def test_every_problem_is_reported_not_just_the_first():
    doc = rig(pins={"trial_light": {"index": 200}, "vacuum": {"index": 200}})
    codes = {p["code"] for p in service.problems_for(doc)}
    assert codes == {"TG227", "TG228"}


# --------------------------------------------------------------------------- #
# The impact check — the whole reason save has a confirm flag
# --------------------------------------------------------------------------- #


def test_deleting_a_bound_channel_names_the_task_it_breaks(rig_store, specs):
    """Full channel authoring means an operator can delete a channel a saved
    task binds. TG223 catches it at compile — by which time the wiring is
    written and the task is broken."""
    doc = rig()
    doc["channels"].pop("left_well")
    doc["pins"].pop("left_well")

    breaks = service.impact_of(doc, specs)
    assert [b["specId"] for b in breaks] == ["grgl"]
    assert "TG223" in breaks[0]["codes"]
    assert breaks[0]["label"]


def test_a_harmless_repin_breaks_nothing(rig_store, specs):
    assert service.impact_of(rig(pins={"left_well": {"index": 12}}), specs) == []


def test_a_task_already_failing_is_not_blamed_on_the_wiring(rig_store, specs):
    """NEWLY is load-bearing: listing a task that was already broken would bury
    the ones this change actually broke."""
    specs.save("broken", "spec_version: 1\nspec_id: broken\n")  # missing everything

    doc = rig()
    doc["channels"].pop("left_well")
    doc["pins"].pop("left_well")

    assert [b["specId"] for b in service.impact_of(doc, specs)] == ["grgl"]


def test_the_impact_check_leaves_the_wiring_it_found(rig_store, specs):
    """It installs a HYPOTHETICAL wiring to answer a question. Leaving it
    installed would mean a preview silently changed what the app compiles."""
    before = registries.channels().content_hash()
    service.impact_of(rig(pins={"left_well": {"index": 12}}), specs)
    assert registries.channels().content_hash() == before
    assert registries.current_rig_source() is None


def test_the_impact_check_restores_even_when_a_compile_explodes(rig_store, specs, monkeypatch):
    from ephymeris_sidecar.specs import compiler

    calls = {"n": 0}

    def boom(*a, **kw):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("compiler exploded")
        return compiler.compile(*a, **kw)

    before = registries.channels().content_hash()
    monkeypatch.setattr(compiler, "compile", boom)
    service.impact_of(rig(pins={"left_well": {"index": 12}}), specs)
    assert registries.channels().content_hash() == before


def test_an_empty_library_costs_nothing(rig_store, tmp_path):
    empty = spec_store.SpecStore(tmp_path / "empty")
    assert service.impact_of(rig(), empty) == []


# --------------------------------------------------------------------------- #
# preview / saved payloads
# --------------------------------------------------------------------------- #


def test_preview_describes_the_wiring_in_force_not_the_draft(rig_store, specs):
    """The operator is comparing a draft against what the rig is doing now; a
    status echoing the draft back would answer a question nobody asked."""
    payload = service.preview_payload(rig_store, rig(pins={"left_well": {"index": 12}}), specs)
    assert payload["status"]["custom"] is False
    assert payload["status"]["pinoutHash"] == registries.channels().content_hash()
    assert payload["problems"] == []
    assert payload["breaks"] == []


def test_preview_writes_nothing(rig_store, specs):
    service.preview_payload(rig_store, rig(pins={"left_well": {"index": 12}}), specs)
    assert not rig_store.exists()


def test_a_saved_rig_reports_itself_as_custom(rig_store):
    stored = rig_store.save(rig(pins={"left_well": {"index": 12}}))
    registries.set_rig_source(rig_store.load)

    payload = service.saved_payload(rig_store, stored)
    assert payload["status"]["custom"] is True
    assert payload["status"]["derivedFrom"] == "behaviorbox_mega2560.v1"
    assert payload["status"]["editedAt"]
    assert payload["problems"] == []

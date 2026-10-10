"""`hardware.*` — the payloads. The impact check that gates a save is
`rig/definition.py`'s, tested in `test_rig_definition.py`.

The rule this module rests on: a document that is WELL-FORMED and describes an
impossible box is not a command error. It is a successful reply carrying located
problems. `RIG_INVALID` is for a document that is not a document.

`conftest.py` sets `EPHYMERIS_WIRE_VALIDATE=1` globally, so every payload built
here is checked against `protocol/schema.py` on the way out. That is what makes
these tests cover the wire shape and not just the values.
"""

from __future__ import annotations

import json

import pytest

from ephymeris_sidecar.hardware import service, store
from ephymeris_sidecar.rig import registry


@pytest.fixture(autouse=True)
def _shipped_wiring():
    registry.set_rig_source(None)
    yield
    registry.set_rig_source(None)


@pytest.fixture
def rig_store(tmp_path):
    return store.HardwareStore(tmp_path)


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
    assert payload["status"]["pinoutHash"] == registry.channels().content_hash()


def test_a_broken_document_is_still_served(rig_store):
    """Refusing to show a broken document would be refusing to show the one
    that needs fixing."""
    rig_store.root.mkdir(parents=True, exist_ok=True)
    doc = rig()
    doc["pins"]["trial_light"]["index"] = 200
    rig_store.path.write_text(json.dumps(doc), encoding="utf-8")

    payload = service.document_payload(rig_store)
    assert payload["document"]["pins"]["trial_light"]["index"] == 200
    assert [p["code"] for p in payload["problems"]] == ["RIG102"]


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
    assert [p["code"] for p in problems] == ["RIG102"]
    assert "0-53" in problems[0]["message"]


def test_shape_is_reported_before_sense():
    """A document that failed the schema may not have the sections the rules
    read, and "channels is not an object" beats a KeyError from a rule."""
    problems = service.problems_for({"rig_version": 1, "channels": "nope", "pins": {}})
    assert problems and all(p["code"] is None for p in problems)


def test_every_problem_is_reported_not_just_the_first():
    doc = rig(pins={"trial_light": {"index": 200}, "vacuum": {"index": 200}})
    codes = {p["code"] for p in service.problems_for(doc)}
    assert codes == {"RIG102", "RIG103"}


# --------------------------------------------------------------------------- #
# preview / saved payloads
# --------------------------------------------------------------------------- #


def test_preview_describes_the_wiring_in_force_not_the_draft(rig_store):
    """The operator is comparing a draft against what the rig is doing now; a
    status echoing the draft back would answer a question nobody asked."""
    payload = service.preview_payload(rig_store, rig(pins={"left_well": {"index": 12}}), [])
    assert payload["status"]["custom"] is False
    assert payload["status"]["pinoutHash"] == registry.channels().content_hash()
    assert payload["problems"] == []
    assert payload["breaks"] == []


def test_preview_writes_nothing(rig_store):
    service.preview_payload(rig_store, rig(pins={"left_well": {"index": 12}}), [])
    assert not rig_store.exists()


def test_a_saved_rig_reports_itself_as_custom(rig_store):
    stored = rig_store.save(rig(pins={"left_well": {"index": 12}}))
    registry.set_rig_source(rig_store.load)

    payload = service.saved_payload(rig_store, stored)
    assert payload["status"]["custom"] is True
    assert payload["status"]["derivedFrom"] == "behaviorbox_mega2560.v1"
    assert payload["status"]["editedAt"]
    assert payload["problems"] == []

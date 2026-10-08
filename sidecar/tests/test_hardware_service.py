"""`hardware.*` — the payloads, and the impact check that gates a save.

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


class FakeTaskStore:
    """The contract `impact_of` needs from a task-profile store.

    Two methods: `list_entries()` and `failures(id)`. `failures` MUST read the
    wiring currently in force rather than a cached answer — that is the whole
    mechanism by which installing a hypothetical wiring and asking again
    produces a before/after difference. Binding a set of channel names and
    reporting the missing ones is exactly what the real store does, minus the
    generation.
    """

    def __init__(self, tasks: dict[str, set[str]]) -> None:
        self._tasks = tasks

    def list_entries(self):
        return [{"id": tid, "label": tid.upper()} for tid in sorted(self._tasks)]

    def failures(self, task_id: str) -> set[str]:
        bound = self._tasks.get(task_id, set())
        present = registry.channels().names()
        return {f"missing:{name}" for name in sorted(bound - present)}


@pytest.fixture
def tasks():
    """A profile library with one task in it, saved against the shipped wiring."""
    return FakeTaskStore({"grgl": {"odor_port", "left_well", "right_well", "fluid_2"}})


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
# The impact check — the whole reason save has a confirm flag
# --------------------------------------------------------------------------- #


def test_deleting_a_bound_channel_names_the_task_it_breaks(rig_store, tasks):
    """Full channel authoring means an operator can delete a channel a saved
    task binds. Catching it at generation would be too late — by then the wiring
    is written and the task is broken."""
    doc = rig()
    doc["channels"].pop("left_well")
    doc["pins"].pop("left_well")

    breaks = service.impact_of(doc, tasks)
    assert [b["specId"] for b in breaks] == ["grgl"]
    assert "missing:left_well" in breaks[0]["codes"]
    assert breaks[0]["label"]


def test_a_harmless_repin_breaks_nothing(rig_store, tasks):
    assert service.impact_of(rig(pins={"left_well": {"index": 12}}), tasks) == []


def test_a_task_already_failing_is_not_blamed_on_the_wiring(rig_store):
    """NEWLY is load-bearing: listing a task that was already broken would bury
    the ones this change actually broke."""
    two = FakeTaskStore({
        "grgl": {"odor_port", "left_well"},
        "broken": {"a_channel_that_never_existed"},
    })

    doc = rig()
    doc["channels"].pop("left_well")
    doc["pins"].pop("left_well")

    assert [b["specId"] for b in service.impact_of(doc, two)] == ["grgl"]


def test_the_impact_check_leaves_the_wiring_it_found(rig_store, tasks):
    """It installs a HYPOTHETICAL wiring to answer a question. Leaving it
    installed would mean a preview silently changed what the app generates."""
    before = registry.channels().content_hash()
    service.impact_of(rig(pins={"left_well": {"index": 12}}), tasks)
    assert registry.channels().content_hash() == before
    assert registry.current_rig_source() is None


def test_the_impact_check_restores_even_when_a_task_explodes(rig_store):
    """The restore is in a `finally` precisely because the thing it wraps can
    raise. A hypothetical wiring surviving a crash is the worst outcome here:
    every later generation would silently use it."""
    class Exploding(FakeTaskStore):
        def __init__(self):
            super().__init__({"grgl": {"left_well"}})
            self.calls = 0

        def failures(self, task_id):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("task store exploded")
            return super().failures(task_id)

    before = registry.channels().content_hash()
    with pytest.raises(RuntimeError):
        service.impact_of(rig(pins={"left_well": {"index": 12}}), Exploding())
    assert registry.channels().content_hash() == before
    assert registry.current_rig_source() is None


def test_an_empty_library_costs_nothing(rig_store):
    assert service.impact_of(rig(), FakeTaskStore({})) == []


def test_a_rig_with_no_task_store_yet_reports_no_breaks(rig_store):
    """None is "none stored yet", which is the honest empty answer rather than a
    special case the caller has to know about."""
    assert service.impact_of(rig(), None) == []


# --------------------------------------------------------------------------- #
# preview / saved payloads
# --------------------------------------------------------------------------- #


def test_preview_describes_the_wiring_in_force_not_the_draft(rig_store, tasks):
    """The operator is comparing a draft against what the rig is doing now; a
    status echoing the draft back would answer a question nobody asked."""
    payload = service.preview_payload(rig_store, rig(pins={"left_well": {"index": 12}}), tasks)
    assert payload["status"]["custom"] is False
    assert payload["status"]["pinoutHash"] == registry.channels().content_hash()
    assert payload["problems"] == []
    assert payload["breaks"] == []


def test_preview_writes_nothing(rig_store, tasks):
    service.preview_payload(rig_store, rig(pins={"left_well": {"index": 12}}), tasks)
    assert not rig_store.exists()


def test_a_saved_rig_reports_itself_as_custom(rig_store):
    stored = rig_store.save(rig(pins={"left_well": {"index": 12}}))
    registry.set_rig_source(rig_store.load)

    payload = service.saved_payload(rig_store, stored)
    assert payload["status"]["custom"] is True
    assert payload["status"]["derivedFrom"] == "behaviorbox_mega2560.v1"
    assert payload["status"]["editedAt"]
    assert payload["problems"] == []


def test_rewiring_a_line_s_onset_names_the_task_it_would_mislabel(rig_store):
    """An onset declaration changes no compiled byte, so nothing at generation
    would catch it. Through the definitions' own validation, a saved task whose
    rows still carry the old pairing reports TSK114 before the write."""
    from ephymeris_sidecar.taskdef.validate import validate
    from tests.fixtures import task_definitions as presets

    definition = presets.instantiate("grgl_2odor", "probe")

    class Definitions:
        def list_entries(self):
            return [{"id": "probe", "label": "Probe"}]

        def failures(self, task_id):
            return {d.code for d in validate(definition)}

    doc = rig()
    doc["channels"]["odor_line_1"]["onset_strobe"] = "ODOR_9_ON"
    doc["channels"]["odor_line_9"]["onset_strobe"] = "ODOR_1_ON"
    breaks = service.impact_of(doc, Definitions())
    assert [b["specId"] for b in breaks] == ["probe"]
    assert "TSK114" in breaks[0]["codes"]

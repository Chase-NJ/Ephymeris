"""The rig definition (`rig/definition.py`, TASKS.md#the-rig-definition).

The rig wiring plus the strobe vocabulary in force. Everything that carries a
pin number or a strobe code into a generated `TaskPins.h` reads it, so the rules
here are the ones whose failure compiles: a hypothetical seen by anyone but its
asker, or a write that interleaves with another.
"""

from __future__ import annotations

import copy
import threading

import pytest

from ephymeris_sidecar.hardware import store
from ephymeris_sidecar.rig import definition, registry
from ephymeris_sidecar.strobes import store as strobe_store

TIMEOUT_S = 5


@pytest.fixture(autouse=True)
def _shipped_rig_definition():
    registry.set_rig_source(None)
    registry.set_vocabulary_source(None)
    yield
    registry.set_rig_source(None)
    registry.set_vocabulary_source(None)


@pytest.fixture
def vocabulary_document():
    """The seed, installed as this machine's own document."""
    document = registry.default_vocabulary_document()
    registry.set_vocabulary_source(lambda: copy.deepcopy(document))
    return document


def rig(**edits) -> dict:
    doc = store.default_document()
    for section, changes in edits.items():
        for name, value in changes.items():
            if value is None:
                doc[section].pop(name, None)
            else:
                doc[section].setdefault(name, {}).update(value)
    return doc


class WiringTasks:
    """The contract `impact_of` needs from a task-profile store, for the wiring
    half: `list_entries()` and `failures(id)`, where `failures` reads the wiring
    in force. Binding channel names and reporting the missing ones is what the
    real store does, minus the generation."""

    def __init__(self, tasks: dict[str, set[str]]) -> None:
        self._tasks = tasks

    def list_entries(self):
        return [{"id": tid, "label": tid.upper()} for tid in sorted(self._tasks)]

    def failures(self, task_id: str) -> set[str]:
        present = registry.channels().names()
        return {f"missing:{name}" for name in sorted(self._tasks.get(task_id, set()) - present)}


class VocabularyTasks(WiringTasks):
    """The same, for the vocabulary half: each task emits strobe names."""

    def failures(self, task_id: str) -> set[str]:
        live = registry.vocabulary().names()
        return {f"missing:{name}" for name in sorted(self._tasks.get(task_id, set()) - live)}


@pytest.fixture
def tasks():
    """One task, saved against the shipped wiring."""
    return WiringTasks({"grgl": {"odor_port", "left_well", "right_well", "fluid_2"}})


# --------------------------------------------------------------------------- #
# A hypothetical is never seen by anyone but its asker
# --------------------------------------------------------------------------- #
#
# Each test pauses an impact check while its hypothetical is installed, reads
# the rig definition from the test thread exactly as a concurrent rebuild would,
# then lets the check finish. Events, not sleeps, so the interleaving is the
# same every run.


class PausingTasks:
    """One task, whose second `failures` call -- the pass made under the
    hypothetical -- holds until the test has looked."""

    def __init__(self) -> None:
        self.hypothetical_installed = threading.Event()
        self.release = threading.Event()
        self._calls = 0

    def list_entries(self):
        return [{"id": "grgl", "label": "GRGL"}]

    def failures(self, task_id: str) -> set[str]:
        self._calls += 1
        if self._calls == 2:
            self.hypothetical_installed.set()
            self.release.wait(TIMEOUT_S)
        return set()


def read_during_impact(read, **hypothetical):
    """Run `impact_of` on a worker thread and return what `read()` sees from this
    thread while the hypothetical is installed."""
    tasks = PausingTasks()
    worker = threading.Thread(target=definition.impact_of, args=(tasks,), kwargs=hypothetical)
    worker.start()
    try:
        assert tasks.hypothetical_installed.wait(TIMEOUT_S), "the impact check never evaluated"
        return read()
    finally:
        tasks.release.set()
        worker.join(TIMEOUT_S)


def free_code(vocabulary: dict) -> int:
    taken = {entry["code"] for name, entry in vocabulary["codes"].items() if not name.startswith("_")}
    taken |= {entry["code"] for name, entry in vocabulary["retired"].items() if not name.startswith("_")}
    for code in range(vocabulary["code_min"], vocabulary["code_max"] + 1):
        if code not in taken and not any(lo <= code <= hi for lo, hi in vocabulary["reserved"]):
            return code
    raise AssertionError("the seed vocabulary has no free code")


def test_a_wiring_preview_is_invisible_to_a_concurrent_rebuild():
    in_force = registry.channels().content_hash()
    hypothetical = rig(pins={"left_well": {"index": 12}})
    assert registry.ChannelMap(*registry.split_rig(hypothetical)).content_hash() != in_force

    seen = read_during_impact(lambda: registry.channels().content_hash(), wiring=hypothetical)

    assert seen == in_force


def test_a_vocabulary_preview_is_invisible_to_a_concurrent_rebuild(vocabulary_document):
    in_force = registry.vocabulary().content_hash()
    hypothetical = copy.deepcopy(vocabulary_document)
    hypothetical["codes"]["PREVIEW_ONLY"] = {
        "code": free_code(vocabulary_document),
        "origin": "task",
        "since": 1,
        "emitted_on": "never; a preview's hypothetical",
        "rationale": "Exists only to make the hypothetical differ from the vocabulary in force.",
    }
    assert registry.Vocabulary(hypothetical).content_hash() != in_force

    seen = read_during_impact(lambda: registry.vocabulary().content_hash(), vocabulary=hypothetical)

    assert seen == in_force


def test_the_asker_does_see_its_hypothetical():
    """The other half of the rule: inside `hypothetical`, the hypothetical."""
    in_force = registry.channels().content_hash()
    hypothetical = rig(pins={"left_well": {"index": 12}})
    with registry.hypothetical(rig=hypothetical):
        assert registry.channels().content_hash() != in_force
    assert registry.channels().content_hash() == in_force


def test_an_exception_inside_the_check_leaves_no_hypothetical(tasks):
    """A hypothetical surviving a crash is the worst outcome here: every later
    generation would silently use it."""

    class Exploding(WiringTasks):
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
        definition.impact_of(Exploding(), wiring=rig(pins={"left_well": {"index": 12}}))
    assert registry.channels().content_hash() == before


def test_a_compute_that_began_before_a_clear_is_not_cached():
    """A reader composing from the old document while a write installs the new
    one must not store the old value for the write's own rebuild to read."""
    old = rig()
    new = rig(pins={"left_well": {"index": 12}})
    reading = threading.Event()
    release = threading.Event()

    def slow_old_source():
        reading.set()
        release.wait(TIMEOUT_S)
        return copy.deepcopy(old)

    registry.set_rig_source(slow_old_source)
    reader = threading.Thread(target=registry.channels)
    reader.start()
    assert reading.wait(TIMEOUT_S)
    registry.set_rig_source(lambda: copy.deepcopy(new))
    release.set()
    reader.join(TIMEOUT_S)

    assert registry.channels().content_hash() == registry.ChannelMap(*registry.split_rig(new)).content_hash()


# --------------------------------------------------------------------------- #
# The impact check -- the whole reason a save has a confirm flag
# --------------------------------------------------------------------------- #


def test_deleting_a_bound_channel_names_the_task_it_breaks(tasks):
    """Full channel authoring means an operator can delete a channel a saved
    task binds. Catching it at generation would be too late -- by then the wiring
    is written and the task is broken."""
    doc = rig()
    doc["channels"].pop("left_well")
    doc["pins"].pop("left_well")

    breaks = definition.impact_of(tasks, wiring=doc)
    assert [b["specId"] for b in breaks] == ["grgl"]
    assert "missing:left_well" in breaks[0]["codes"]
    assert breaks[0]["label"]


def test_a_harmless_repin_breaks_nothing(tasks):
    assert definition.impact_of(tasks, wiring=rig(pins={"left_well": {"index": 12}})) == []


def test_a_task_already_failing_is_not_blamed_on_the_wiring():
    """NEWLY is load-bearing: listing a task that was already broken would bury
    the ones this change actually broke."""
    two = WiringTasks({
        "grgl": {"odor_port", "left_well"},
        "broken": {"a_channel_that_never_existed"},
    })

    doc = rig()
    doc["channels"].pop("left_well")
    doc["pins"].pop("left_well")

    assert [b["specId"] for b in definition.impact_of(two, wiring=doc)] == ["grgl"]


def test_retiring_an_emitted_code_names_the_task_it_breaks(vocabulary_document):
    emitting = VocabularyTasks({"grgl": {"LIGHTS_ON", "START_SESSION"}})

    breaks = definition.impact_of(
        emitting, vocabulary=strobe_store.retire(vocabulary_document, "LIGHTS_ON")
    )
    assert [b["specId"] for b in breaks] == ["grgl"]
    assert breaks[0]["codes"] == ["missing:LIGHTS_ON"]


def test_a_task_already_failing_is_not_blamed_on_the_vocabulary(vocabulary_document):
    two = VocabularyTasks({
        "grgl": {"LIGHTS_ON"},
        "broken": {"A_CODE_THAT_NEVER_EXISTED"},
    })

    breaks = definition.impact_of(two, vocabulary=strobe_store.retire(vocabulary_document, "LIGHTS_ON"))
    assert [b["specId"] for b in breaks] == ["grgl"]


def test_an_empty_library_costs_nothing():
    assert definition.impact_of(WiringTasks({}), wiring=rig()) == []


def test_a_rig_with_no_task_store_yet_reports_no_breaks():
    """None is "none stored yet", which is the honest empty answer rather than a
    special case the caller has to know about."""
    assert definition.impact_of(None, wiring=rig()) == []


def test_rewiring_a_line_s_onset_names_the_task_it_would_mislabel():
    """An onset declaration changes no compiled byte, so nothing at generation
    would catch it. Through the definitions' own validation, a saved task whose
    rows still carry the old pairing reports TSK114 before the write."""
    from ephymeris_sidecar.taskdef.validate import validate
    from tests.fixtures import task_definitions as presets

    probe = presets.instantiate("grgl_2odor", "probe")

    class Definitions:
        def list_entries(self):
            return [{"id": "probe", "label": "Probe"}]

        def failures(self, task_id):
            return {d.code for d in validate(probe)}

    doc = rig()
    doc["channels"]["odor_line_1"]["onset_strobe"] = "ODOR_9_ON"
    doc["channels"]["odor_line_9"]["onset_strobe"] = "ODOR_1_ON"
    breaks = definition.impact_of(Definitions(), wiring=doc)
    assert [b["specId"] for b in breaks] == ["probe"]
    assert "TSK114" in breaks[0]["codes"]

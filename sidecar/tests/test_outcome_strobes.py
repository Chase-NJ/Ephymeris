"""A spine run strobes each trial's outcome class, from INTERP 8
(0005-spine-runs-strobe-each-trials-outcome.md).

The board strobes the class of each state it entered that carries one, last in
the tick; replay predicts the same strobe from the same entered states, so a
wrong verdict is a divergence. A run recorded under INTERP 7 or earlier carries
none and replays as it always did. The end-to-end proof, a generated task's
real BoxSpine.h played through the session path, is `test_spine_run.py`.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import scoring
from ephymeris_sidecar.analytics.stream import replay
from ephymeris_sidecar.analytics.stream import spine as spine_stream
from ephymeris_sidecar.analytics.stream.summary import summarize
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.taskdef import generate, lowering
from ephymeris_sidecar.taskdef.model import TaskDefinition
from ephymeris_sidecar.taskdef.validate import validate
from tests.fixtures import spine as fixture
from tests.test_spine_analytics import recorded_document

BOX_SPINE_H = Path(__file__).resolve().parents[2] / "firmware" / "libraries" / "BehaviorBox" / "BoxSpine.h"


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    scoring.forget_canary()
    yield
    scoring.forget_canary()
    fixture.uninstall()


def names(document: dict) -> list[str]:
    strobes = document["task_profile"]["strobes"]
    return [strobes[str(c)] for c, _ in document["ts_data"]]


def as_interp_7(document: dict) -> dict:
    """`document` as an INTERP 7 board would have recorded it: no outcome codes."""
    old = copy.deepcopy(document)
    strobes = old["task_profile"]["strobes"]
    old["ts_data"] = [s for s in old["ts_data"] if strobes[str(s[0])] not in lowering.OUTCOME_CODES]
    old["n_events"] = len(old["ts_data"])
    old["interp"] = old["task_profile"]["spine"]["interp"] = 7
    del old["task_profile"]["spine"]["outcomes"]
    return old


def test_the_firmware_numbers_the_classes_as_lowering_does():
    """BoxSpine.h's `kOutcomeCodes`, by class number less one, is `OUTCOME_CODES`."""
    body = re.search(r"kOutcomeCodes\[\][^=]*=\s*\{([^}]*)\}", BOX_SPINE_H.read_text(encoding="utf-8"))
    assert body is not None
    assert tuple(re.findall(r"BF_(\w+)", body.group(1))) == lowering.OUTCOME_CODES
    assert lowering.OUTCOME_CODES == tuple(f"OUTCOME_{c.upper()}" for c in lowering.OUTCOME_CLASSES)


def test_the_shipped_vocabulary_has_every_outcome_code():
    vocab = registry.vocabulary()
    assert all(vocab.code_of(name) is not None for name in lowering.OUTCOME_CODES)


def test_each_marked_trial_strobes_its_class_last_in_its_tick():
    document = recorded_document()
    stream = names(document)
    assert [n for n in stream if n in lowering.OUTCOME_CODES] == \
        ["OUTCOME_CORRECT", "OUTCOME_ABORT_DURING_SAMPLING", "OUTCOME_CORRECT"]
    for k, (code, tick) in enumerate(document["ts_data"]):
        if stream[k] in lowering.OUTCOME_CODES:
            later = [stream[j] for j, (_, t) in enumerate(document["ts_data"]) if t == tick and j > k]
            assert all(n in lowering.OUTCOME_CODES or n == "END_SESSION" for n in later), \
                f"{stream[k]}@{tick} is followed in its tick by {later}"


def test_a_paid_trial_strobes_its_class_after_the_reward_opens():
    stream = names(recorded_document())
    first = stream.index("OUTCOME_CORRECT")
    assert stream[first - 1] == "FLUID_2_ON", "the outputs, then the verdict"


def test_a_wrong_verdict_is_a_divergence():
    document = recorded_document()
    vocab = registry.vocabulary()
    k = next(i for i, n in enumerate(names(document)) if n == "OUTCOME_CORRECT")
    document["ts_data"][k][0] = vocab.code_of("OUTCOME_OMISSION")
    summary = summarize(document, None)
    assert summary.divergence is not None and summary.divergence.index == k
    assert "OUTCOME_CORRECT" in summary.divergence.expected


def test_an_interp_7_run_strobes_no_outcome_and_replays_as_before():
    document = recorded_document()
    old = as_interp_7(document)
    record = spine_stream.decode(old)
    assert record.outcomes == ()
    assert spine_stream.expected_stream(record) == [tuple(s) for s in old["ts_data"]]
    assert summarize(old, None).divergence is None
    tables = [spine_stream.trial_table(d)["trials"] for d in (document, old)]
    assert tables[0] == tables[1], "the verdicts are read off the replay, never the strobes"


def test_an_interp_8_snapshot_that_names_no_outcome_codes_cannot_be_replayed():
    document = recorded_document()
    del document["task_profile"]["spine"]["outcomes"]
    with pytest.raises(spine_stream.SpineDecodeError, match="names no outcome codes"):
        spine_stream.decode(document)


def test_a_vocabulary_without_an_outcome_code_is_diagnosed_and_refuses_to_compile():
    rig, vocab = fixture.issued_rig()
    del vocab["codes"]["OUTCOME_WITHHELD"]
    fixture.install(rig, vocab)
    definition = TaskDefinition.from_json(fixture.tracer())
    assert ("SPN104", "vocabulary.OUTCOME_WITHHELD") in {(d.code, d.location) for d in validate(definition)}
    assert '#error "the strobe vocabulary has no OUTCOME_WITHHELD' in generate.task_spine_h(definition)


def test_replay_runs_interp_8():
    assert replay.OUTCOMES_SINCE == 8 in replay.INTERP_VERSIONS

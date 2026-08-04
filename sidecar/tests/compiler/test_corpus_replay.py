"""The backward check: does the graph accept what real boxes actually emitted?

THE CHEAPEST CONFIDENCE IN THE PROJECT, and the only test here that validates the
MODEL rather than the code. Everything else asserts the compiler does what it was
told; this asserts what it was told is true.

It runs against `tests/fixtures/grgl_2odor_asbuilt.yaml`, not against the target
spec. The as-built fixture pins template v1 and reproduces what the boxes emit
today, quirks included. The target spec has moved ahead of the firmware (D21), so
replaying yesterday's recordings against it would measure the size of the pending
firmware change, not the correctness of the model.

SKIPS WHEN THERE IS NO CORPUS. Behavioural data lives outside this repo. A
checkout on a machine without it is not a broken checkout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph.corpus import corpus_root, load_corpus
from ephymeris_sidecar.taskgraph.pipeline import compile_spec
from ephymeris_sidecar.taskgraph.replay import GraphAcceptor

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, SPEC_DIR, all_specs, spec,
)


pytestmark = pytest.mark.skipif(
    corpus_root() is None,
    reason="no recorded corpus on this machine (set TASKGRAPH_CORPUS)",
)


@pytest.fixture(scope="module")
def acceptor():
    r = compile_spec(AS_BUILT)
    assert r.ok, r.bag.render()
    return GraphAcceptor(r.spec, r.table)


@pytest.fixture(scope="module")
def grgl():
    return load_corpus(sketch="GRGL_2-Odor")


def test_the_corpus_is_actually_there(grgl):
    assert len(grgl) > 100, "corpus looks truncated; the assertions below would be vacuous"


def test_every_recorded_grgl_session_is_accepted(acceptor, grgl):
    """The exit criterion.

    A rejection means the hand-written spec disagrees with a box that really ran.
    That is worth failing a build over: it is the model being wrong, and the whole
    point of doing this before any firmware exists is that it costs nothing to fix
    here and a great deal to fix in Phase 5.
    """
    bad = []
    for s in grgl:
        res = acceptor.accept(list(s.events))
        if not res.accepted:
            bad.append(f"{s.path.name}\n    {res.divergence.format()}")
    assert not bad, (
        f"{len(bad)} of {len(grgl)} recorded sessions are not explainable by the graph:\n\n"
        + "\n\n".join(bad[:5])
    )


def test_the_corpus_reaches_every_state(acceptor, grgl):
    """Full coverage is a stronger result than acceptance.

    Acceptance says nothing contradicts the model. Reaching all 24 states says no
    part of the model is speculative -- every branch has been driven by a real
    animal at least once.
    """
    seen: set[int] = set()
    for s in grgl:
        seen |= acceptor.accept(list(s.events)).visited
    missing = [acceptor.label(i) for i in acceptor.unreached(seen)]
    assert not missing, "states no recorded session ever entered:\n  " + "\n  ".join(missing)


def test_retired_codes_are_named_not_merely_unknown(acceptor, grgl):
    """29 sessions carry codes 110-113: dummy solenoid clicks.

    They masked the audible cue of the real odor valve, so a subject could not use
    valve noise to predict the trial. No firmware in this repository emits them.

    THE NUMBERS ARE BURNED. Append-only applies just as much to a code whose emitter
    is gone: ~24,600 recorded events carry these, and reissuing one would silently
    merge two unrelated event types in any analysis spanning the boundary. They are
    listed under `retired` in the vocabulary and cut out of `free_ranges`.

    They are reported separately from a divergence and from an unknown code, because
    all three are different findings: retired is explained, unknown is a question,
    and a divergence is a gap in the graph.
    """
    seen_retired: set[str] = set()
    seen_unknown: set[int] = set()
    for s in grgl:
        res = acceptor.accept(list(s.events))
        seen_retired |= set(res.retired)
        seen_unknown |= set(res.unknown)

    assert not seen_unknown, f"unexplained codes in the corpus: {sorted(seen_unknown)}"
    assert seen_retired <= {f"DUMMY_SOLENOID_CLICK_{i}" for i in (1, 2, 3, 4)}


def test_retired_numbers_are_not_offered_as_free(acceptor):
    """A future code must not be able to reuse 110-113."""
    from ephymeris_sidecar.taskgraph.registries import vocabulary

    v = vocabulary()
    free = {n for lo, hi in v.free_ranges for n in range(lo, hi + 1)}
    assert not (free & set(v.retired)), "a retired code is being offered as free"


def test_a_second_start_session_restarts_the_walk(acceptor):
    """START_SESSION means "recording start, timestamp 0", so a file holding two of
    them holds two runs. Skipping the second would leave the walk mid-trial when the
    next run's first LIGHTS_ON arrived and reject a session for something that is
    not a modelling error."""
    from ephymeris_sidecar.taskgraph.registries import vocabulary

    v = vocabulary()
    one = [(v.code_of("START_SESSION"), 0), (v.code_of("LIGHTS_ON"), 10),
           (v.code_of("LAZY_RAT"), 20)]
    # Cut a trial off mid-flight, then start a fresh recording.
    stream = one + [(v.code_of("START_SESSION"), 0), (v.code_of("LIGHTS_ON"), 10)]
    assert acceptor.accept(stream).accepted


def test_the_model_spec_has_moved_ahead_of_the_firmware(grgl):
    """Not a failure — a measurement.

    The model spec emits RESP_OMIT and orders cue-off consistently. Firmware now
    does too, but these sessions were recorded before it did, so the corpus SHOULD
    be rejected by the model graph and always will be. That is why the as-built
    fixture stays: it is the graph that produced these recordings, and retiring it
    would leave 907 sessions with nothing to validate against.

    What this measures now is the OTHER side of the cutover. When sessions recorded
    on the fixed firmware are added and the corpus stops being uniformly legacy,
    this starts failing — and at that point the suite wants splitting by firmware
    generation rather than pointing wholesale at either graph.
    """
    r = compile_spec(spec("grgl_2odor"))
    model = GraphAcceptor(r.spec, r.table)
    accepted = sum(1 for s in grgl if model.accept(list(s.events)).accepted)
    assert accepted < len(grgl), (
        "the model graph now accepts the whole corpus, so it is no longer the "
        "legacy corpus — split the sessions by firmware generation (the CAP line's "
        "FW=<name>/<version>) and validate each against the graph that produced it."
    )

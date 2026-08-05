"""The backward check: does the graph accept what real boxes actually emitted?

THE CHEAPEST CONFIDENCE IN THE PROJECT, and the only test here that validates the
MODEL rather than the code. Everything else asserts the compiler does what it was
told; this asserts what it was told is true.

IT NOW RUNS AGAINST TWO GRAPHS, because the corpus spans two firmware generations.
The model-conformance patch landed on 2026-08-03 and the boxes were reflashed
before the 2026-08-04 sessions, so recordings from either side of that cutover are
explained by different graphs and neither one explains both:

  * **v1** — `tests/fixtures/grgl_2odor_asbuilt.yaml`, template v1 frozen as-built,
    quirks included. Every session recorded before the reflash.
  * **v2** — the model spec, which the firmware now conforms to (D21).

Pointing the whole corpus at either graph fails, and that is not a modelling error:
it is the measurement D21 predicted, arriving. Which graph a session belongs to is
read off the session itself (`Session.generation`) rather than its date, because
the recordings carry no firmware version and their names must never be sorted as
strings.

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
    SCHEMA_DIR, all_specs, grgl_equivalent, spec,
)


pytestmark = pytest.mark.skipif(
    corpus_root() is None,
    reason="no recorded corpus on this machine (set TASKGRAPH_CORPUS)",
)


def _acceptor(path: Path) -> GraphAcceptor:
    r = compile_spec(path)
    assert r.ok, r.bag.render()
    return GraphAcceptor(r.spec, r.table)


@pytest.fixture(scope="module")
def acceptor():
    """The v1 graph: template v1, frozen as-built."""
    return _acceptor(AS_BUILT)


@pytest.fixture(scope="module")
def model():
    """The v2 graph: the model the firmware now conforms to.

    `grgl_equivalent()` rather than a bare `two_afc` skeleton, for the reason its
    own docstring gives — the corpus is a specific experiment (odor 1 right, odor 3
    left) and a skeleton's default stimulus lines are the first two the registry
    offers. Replaying GRGL against those measures the default, not the model.
    """
    return _acceptor(grgl_equivalent())


@pytest.fixture(scope="module")
def grgl():
    return load_corpus(sketch="GRGL_2-Odor")


@pytest.fixture(scope="module")
def by_generation(grgl):
    """The corpus split into the graph that produced each session."""
    out: dict[str, list] = {"v1": [], "v2": []}
    for s in grgl:
        out[s.generation].append(s)
    return out


def _graph_for(generation, acceptor, model):
    return model if generation == "v2" else acceptor


def test_the_corpus_is_actually_there(grgl):
    assert len(grgl) > 100, "corpus looks truncated; the assertions below would be vacuous"


def test_every_recorded_grgl_session_is_accepted(acceptor, model, grgl):
    """The exit criterion.

    A rejection means the hand-written spec disagrees with a box that really ran.
    That is worth failing a build over: it is the model being wrong, and the whole
    point of doing this before any firmware exists is that it costs nothing to fix
    here and a great deal to fix in Phase 5.

    Each session is replayed through the graph of its own generation. A session
    failing here is still the old finding — the graph cannot explain a real box —
    but check `Session.generation` first, because a session filed under the wrong
    generation fails with a divergence that reads exactly like a modelling gap.
    """
    bad = []
    for s in grgl:
        res = _graph_for(s.generation, acceptor, model).accept(list(s.events))
        if not res.accepted:
            bad.append(f"{s.path.name} [{s.generation}]\n    {res.divergence.format()}")
    assert not bad, (
        f"{len(bad)} of {len(grgl)} recorded sessions are not explainable by the "
        f"graph of their own generation:\n\n" + "\n\n".join(bad[:5])
    )


@pytest.mark.parametrize("generation", ["v1", "v2"])
def test_the_corpus_reaches_every_state(generation, acceptor, model, by_generation):
    """Full coverage is a stronger result than acceptance.

    Acceptance says nothing contradicts the model. Reaching every state says no
    part of the model is speculative -- every branch has been driven by a real
    animal at least once.

    BOTH GRAPHS HAVE TO EARN THIS SEPARATELY. Pooling the two generations would let
    the 217 v1 sessions cover states the model graph has never actually had driven
    through it, which is the claim this test exists to refuse. The five v2 sessions
    do reach all of theirs on their own.
    """
    graph = _graph_for(generation, acceptor, model)
    sessions = by_generation[generation]
    assert sessions, f"no {generation} sessions in the corpus; the split has gone stale"
    seen: set[int] = set()
    for s in sessions:
        seen |= graph.accept(list(s.events)).visited
    missing = [graph.label(i) for i in graph.unreached(seen)]
    assert not missing, (
        f"states no recorded {generation} session ever entered:\n  " + "\n  ".join(missing)
    )


def test_retired_codes_are_named_not_merely_unknown(acceptor, model, grgl):
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

    Replayed through each session's own graph, because the walk stops at a
    divergence: a session read against the wrong generation reports only the codes
    that appear before the first abort, and the unknown code this is hunting for
    would go unseen rather than reported.
    """
    seen_retired: set[str] = set()
    seen_unknown: set[int] = set()
    for s in grgl:
        res = _graph_for(s.generation, acceptor, model).accept(list(s.events))
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


def test_both_graphs_are_load_bearing(acceptor, model, by_generation):
    """Not a failure — a measurement.

    This used to measure how far the model had moved ahead of the firmware, and
    predicted that it would need splitting once sessions recorded on the fixed
    firmware arrived. They have: the model-conformance patch landed on 2026-08-03
    and the 2026-08-04 sessions are the first recorded after the reflash.

    So what it measures now is that the cutover is real in both directions — that
    each graph explains sessions the other rejects. That is the thing that would
    quietly stop being true if someone retired the as-built fixture (v1 recordings
    would lose the only graph that explains them) or filed every session under one
    generation (the split would survive as dead code while proving nothing).

    Both halves are permanent. The archive is append-only, so the v1 sessions never
    leave, and the model will not move back.
    """
    v1, v2 = by_generation["v1"], by_generation["v2"]
    assert v1 and v2, (
        f"the corpus no longer spans both generations (v1={len(v1)}, v2={len(v2)}); "
        "the split is proving nothing"
    )
    assert any(not model.accept(list(s.events)).accepted for s in v1), (
        "the model graph now accepts every v1 session, so the as-built fixture is "
        "no longer the only graph that explains them — check whether it can be retired"
    )
    stale = [s.path.name for s in v2 if acceptor.accept(list(s.events)).accepted]
    assert not stale, (
        "the as-built (v1) graph accepts sessions filed as v2, so the generation "
        f"split is misreading them: {stale[:3]}"
    )

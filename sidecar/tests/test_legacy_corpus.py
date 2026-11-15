"""The recorded corpus, pinned per sketch (`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`).

`fixtures/legacy_corpus.json` was captured on 2b851fd, the scorer before the
legacy adapter, from the archive on the development Mac
(`~/Documents/Hart-Lab/DATA/Behavior`: 732 runs, 13 sketch names). Per sketch
it holds the run count, a digest over every run's summary, series, trail and
tape, and summed counts. No run file and no per-run number is committed.

The archive is not in the repo, so this runs only when `EPHYMERIS_CORPUS`
names it. On a lab machine, pin that machine's own archive with
`python -m tests.legacy_corpus` (`capture` on 2b851fd, `check` here), and point
`EPHYMERIS_CORPUS_PIN` at the capture to run this test against it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from .legacy_corpus import corpus

ARCHIVE = os.environ.get("EPHYMERIS_CORPUS")
PIN = Path(os.environ.get("EPHYMERIS_CORPUS_PIN")
           or Path(__file__).parent / "fixtures" / "legacy_corpus.json")

pytestmark = pytest.mark.skipif(not ARCHIVE, reason="EPHYMERIS_CORPUS names no archive")


@pytest.fixture(scope="module")
def scored() -> dict:
    assert ARCHIVE is not None
    return corpus(Path(ARCHIVE))


WANT = json.loads(PIN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("sketch", sorted(WANT), ids=lambda s: s or "(no sketch)")
def test_every_sketch_in_the_corpus_scores_as_it_did_before_the_adapter(scored: dict, sketch: str) -> None:
    want, got = WANT[sketch], scored.get(sketch)
    assert got is not None, f"no run of {sketch!r} in the archive"
    assert got["runs"] == want["runs"]
    assert got["totals"] == want["totals"]
    assert got["digest"] == want["digest"], "a run's outputs moved; the totals above did not"


def test_the_corpus_holds_no_sketch_the_pin_does_not(scored: dict) -> None:
    assert sorted(scored) == sorted(WANT)

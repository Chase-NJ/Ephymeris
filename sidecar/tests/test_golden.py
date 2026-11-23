"""Every golden run file still reads and scores exactly as captured (`tests/golden.py`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .golden import EXPECTED, cases, expected_path, fingerprint


@pytest.mark.parametrize("run", cases(), ids=lambda p: p.name)
def test_a_golden_run_reads_and_scores_as_captured(run: Path) -> None:
    want = json.loads(expected_path(run).read_text(encoding="utf-8"))
    got = json.loads(json.dumps(fingerprint(run)))
    moved = sorted(key for key in want.keys() | got.keys() if want.get(key) != got.get(key))
    assert not moved, f"{run.name} moved in: {', '.join(moved)}"


def test_every_expectation_has_its_run() -> None:
    assert sorted(p.name for p in EXPECTED.iterdir()) == sorted(f"{p.name}.json" for p in cases())

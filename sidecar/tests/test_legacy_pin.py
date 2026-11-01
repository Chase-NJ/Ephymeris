"""The legacy adapter reproduces the scorer it replaced, exactly
(`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`).

`fixtures/legacy_pin.json` holds documents, the profiles they are scored with
and what the scorer before the adapter (2b851fd) reported for each: the
summary payload, both series, the strategy trail and the tape. Every case must
come out the same to the last field. Regenerate it only from that commit
(`python -m tests.legacy_corpus pin`), never from the code under test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ephymeris_sidecar.tasks.profile import parse_profile

from .legacy_corpus import outputs, seed_vocabulary

PIN = json.loads((Path(__file__).parent / "fixtures" / "legacy_pin.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", PIN["cases"], ids=lambda c: c["name"])
def test_a_legacy_run_reports_what_it_did_before_the_adapter(case: dict) -> None:
    raw = case["profile"]
    profile = parse_profile(raw) if raw is not None else None
    got = outputs(case["document"], profile, seed_vocabulary())
    for key, want in case["expected"].items():
        assert got[key] == want, key

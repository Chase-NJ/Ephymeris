"""The legacy adapter reproduces the scorer it replaced, exactly
(`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`).

`fixtures/legacy_pin.json` holds documents, the profiles they are scored with
and what the scorer before the adapter (2b851fd) reported for each: the
summary payload, both series, the strategy trail and the tape. Every case must
come out the same to the last field. Regenerate it only from that commit
(`python -m tests.legacy_corpus pin`), never from the code under test.

A field added since that commit (response accuracy and the spine-only buckets,
#167) is not compared: the pin says what the old scorer reported, and every
field it holds must still come out the same.
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
        assert pinned(got[key], want) == want, key


def pinned(got, want):  # noqa: ANN001, ANN201
    """`got` with only the fields `want` holds, at every depth."""
    if isinstance(want, dict) and isinstance(got, dict):
        return {k: pinned(got[k], v) if k in got else got.get(k) for k, v in want.items()}
    if isinstance(want, list) and isinstance(got, list) and len(want) == len(got):
        return [pinned(g, w) for g, w in zip(got, want)]
    return got

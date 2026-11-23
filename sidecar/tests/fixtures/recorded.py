"""A recorded GRGL run, for tests that need one whole document.

A stream-grammar-2 run of the generated go-right, go-left and no-go task
(`test_grammar2.py`'s reference sequences), with its snapshot, header fields
and parameters, as a finalized `.json` holds them flat.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import scoring
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.tasks import profile as task_profile
from ephymeris_sidecar.analytics.tests.test_analytics_service import Rig
from ephymeris_sidecar.analytics.tests.test_grammar2 import EVERY, document, generated_profile


def recorded_document(*, trials: list[str] | None = None, seed: int = 99) -> dict:
    """The reference run's document: every strobe a board running the task sends."""
    snapshot = generated_profile().to_json()
    config = {f["metadataKey"]: f["default"] for f in snapshot["config"]}
    out = document(EVERY if trials is None else trials, stream=2, interp=1, channel_set_hash="abc123",
                   **{task_profile.SNAPSHOT_KEY: snapshot}, **config)
    return {**out, "rat": "remy1", "trial_seed": seed, "n_events": len(out["ts_data"])}


@pytest.fixture
def rig(tmp_path: Path):
    scoring.forget_canary()
    database = Database(tmp_path / "app" / "ephymeris.db")
    database.connect()
    try:
        r = Rig(database, tmp_path)
        # The worst case: today's task.json for the recorded sketch DOES score,
        # so a run that fell through the ladder would be scored against it.
        r.write_sketch()
        yield r
    finally:
        database.close()
        scoring.forget_canary()


def write_document(rig: Rig, document_: dict) -> str:
    """Put `document_` on disk as one recorded run of the rig's cohort; its run id."""
    session = rig.add_session("1", "2026-10-30")
    run_id = rig.add_run(session, "a1", [code for code, _ in document_["ts_data"]], snapshot=False)
    path = Path(rig.sessions.runs_for(session)[0].file_path)
    path.write_text(json.dumps(document_), encoding="utf-8")
    return run_id

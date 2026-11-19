"""Each recorded run's site measurements, and a cohort's recorded runs as the
Logbook reads them (`RECORDING.md#unit-like-sites`).

The `run_site_quality` table, keyed by run as `run_spike_counts` is
(`yield_store`): the run record says which animal and session, and already
follows the animal through a cohort move or a tidy. One row is one
`site_quality.RunQuality`, written once the recording has stopped and its
spike export has read RHX's file.

`cohort_signals` joins it with the live counts into the wire's `RunSignal`:
either source may be missing (a recording that saved no snapshots has counts
only; a run whose spike stream was down has measurements only), and what a
source lacks is null, never zero.

Raw measurements only. What makes a site unit-like is judged in the webview.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from ..cohorts.db import Database, Tx
from .site_quality import SNR_EDGES, RunQuality


class SiteQualityStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, run_id: str, quality: RunQuality, *, tx: Tx | None = None) -> None:
        with self._db.write(tx) as unit:
            unit.execute(
                "INSERT OR REPLACE INTO run_site_quality"
                " (run_id, measured_at, recorded_seconds, edges_json, sites_json)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    quality.recorded_seconds,
                    json.dumps(list(quality.edges)),
                    json.dumps([site.to_json() for site in quality.sites]),
                ),
            )

    def cohort_signals(self, cohort_id: str) -> list[dict[str, Any]]:
        """Every run of the cohort with a live count or measured sites, oldest
        first, as the wire's `RunSignal`."""
        with self._db.read() as q:
            rows = q.execute(
                "SELECT r.id, r.session_id, r.animal_id, r.box_number, r.started_at,"
                " c.counted_seconds, c.run_seconds, c.threshold_json, c.counts_json,"
                " m.recorded_seconds, m.edges_json, m.sites_json"
                " FROM session_animal_runs r"
                " JOIN sessions s ON s.id = r.session_id"
                " LEFT JOIN run_spike_counts c ON c.run_id = r.id"
                " LEFT JOIN run_site_quality m ON m.run_id = r.id"
                " WHERE s.cohort_id = ? AND (c.run_id IS NOT NULL OR m.run_id IS NOT NULL)"
                " ORDER BY r.started_at, r.id",
                (cohort_id,),
            ).fetchall()
        return [_signal(row) for row in rows]


def _signal(row: Any) -> dict[str, Any]:
    counts: dict[str, int] | None = json.loads(row["counts_json"]) if row["counts_json"] else None
    measured: list[dict[str, Any]] | None = json.loads(row["sites_json"]) if row["sites_json"] else None
    by_channel = {site["channel"]: site for site in measured or []}
    channels = sorted({*(counts or {}), *by_channel}, key=_rhx_order)
    return {
        "runId": row["id"],
        "sessionId": row["session_id"],
        "animalId": row["animal_id"],
        "box": row["box_number"],
        "startedAt": row["started_at"],
        "countedSeconds": row["counted_seconds"] if counts is not None else None,
        "runSeconds": row["run_seconds"] if counts is not None else None,
        "threshold": json.loads(row["threshold_json"]) if row["threshold_json"] else None,
        "recordedSeconds": row["recorded_seconds"] if measured is not None else None,
        # A stored row is read against the edges it was binned by.
        "snrEdges": json.loads(row["edges_json"]) if row["edges_json"] else list(SNR_EDGES),
        "sites": [
            {
                "channel": channel,
                "crossings": None if counts is None else counts.get(channel),
                "spikes": by_channel.get(channel, {}).get("spikes"),
                "artifacts": by_channel.get(channel, {}).get("artifacts"),
                "noiseUv": by_channel.get(channel, {}).get("noiseUv"),
                "snrCounts": by_channel.get(channel, {}).get("snrCounts"),
            }
            for channel in channels
        ],
    }


def _rhx_order(channel: str) -> tuple[Any, ...]:
    """RHX's own channel order: by port, then by number (`A-002` before `A-010`
    before `B-000`), whatever the padding."""
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", channel))

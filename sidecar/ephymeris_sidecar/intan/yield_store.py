"""Each recorded run's spike counts per site, the basis of an animal's
active-site yield (`RECORDING.md#active-site-yield`).

The `run_spike_counts` table, keyed by run: the run record says which animal,
and it already follows the animal through a cohort move or a tidy. Counted
live from RHX's spike socket, so a run carries how much of it the stream
covered (`counted_seconds`); a gap makes a site look quieter than it was, and
the webview says so rather than judging the run as complete.

Raw counts only. What counts as an *active* site is judged in the webview, by
the recording default (`RecordingDefaults.activeSiteHz`), so changing it
re-judges history with nothing to migrate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..cohorts.db import Database, Tx


@dataclass(frozen=True)
class RunSpikes:
    """One box's run: threshold crossings per recorded site."""

    counts: dict[str, int]
    #: Spike-stream coverage: the samples RHX's waveform socket delivered during the run.
    counted_seconds: float
    #: Wall time from START to the run's end.
    run_seconds: float
    #: The recording's threshold setup (`RecordingConfig.threshold`); counts
    #: under different thresholds do not compare.
    threshold: dict[str, Any] | None = field(default=None)


class SpikeYieldStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, run_id: str, spikes: RunSpikes, *, tx: Tx | None = None) -> None:
        with self._db.write(tx) as unit:
            unit.execute(
                "INSERT OR REPLACE INTO run_spike_counts"
                " (run_id, counted_seconds, run_seconds, threshold_json, counts_json)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    spikes.counted_seconds,
                    spikes.run_seconds,
                    None if spikes.threshold is None else json.dumps(spikes.threshold, sort_keys=True),
                    json.dumps(spikes.counts, sort_keys=True),
                ),
            )

    def history(self, animal_id: str, *, limit: int) -> list[dict[str, Any]]:
        """The animal's most recent counted runs, oldest first, as the wire's `RunYield`."""
        with self._db.read() as q:
            rows = q.execute(
                "SELECT r.id, r.session_id, r.box_number, r.started_at, c.counted_seconds,"
                " c.run_seconds, c.threshold_json, c.counts_json"
                " FROM run_spike_counts c JOIN session_animal_runs r ON r.id = c.run_id"
                " WHERE r.animal_id = ? ORDER BY r.started_at DESC LIMIT ?",
                (animal_id, limit),
            ).fetchall()
        return [
            {
                "runId": row["id"],
                "sessionId": row["session_id"],
                "box": row["box_number"],
                "startedAt": row["started_at"],
                "countedSeconds": row["counted_seconds"],
                "runSeconds": row["run_seconds"],
                "threshold": json.loads(row["threshold_json"]) if row["threshold_json"] else None,
                "counts": json.loads(row["counts_json"]),
            }
            for row in reversed(rows)
        ]

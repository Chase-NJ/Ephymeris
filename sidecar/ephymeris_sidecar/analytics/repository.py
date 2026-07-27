"""Profile snapshots and the derived-metrics cache — `analytics.md` §8.2, §8.3.

Synchronous, like every other repository here; callers wrap in
`asyncio.to_thread`. Shares the cohort database and its lock.

Two tables, both new at schema v3:

* `task_profiles` — content-addressed snapshots, so a run stays decodable
  years later even if its `task.json` is edited or deleted.
* `run_metrics_cache` — derived summaries. Pure cache: every row is
  recomputable from the file on disk, so losing it costs time and nothing else.
  It is persisted rather than held in memory because the sidecar restarts on
  every app launch (there is deliberately no auto-respawn), and re-replaying a
  whole archive on each launch is the cost that buys.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..cohorts.db import Database
from ..tasks.profile import TaskProfile, TaskProfileError, parse_profile, profile_hash

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheKey:
    """What makes a cached summary still valid (§8.3)."""

    file_path: str
    mtime_ns: int | None
    size: int | None
    profile_hash: str | None
    codec_version: int


@dataclass(frozen=True)
class CachedRun:
    run_id: str
    status: str
    detail: str | None
    profile_hash: str | None
    profile_source: str
    summary: dict[str, Any]
    key: CacheKey
    #: A file that has gone missing keeps its last good summary rather than
    #: being dropped — a briefly unreachable share must not erase history.
    stale: bool = False


class AnalyticsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- profile snapshots -------------------------------------------------

    def remember_profile(self, profile: TaskProfile) -> str:
        """Store a profile if unseen, and return its hash.

        Content-addressed, so the hundredth run of the same task adds nothing.
        Does **not** commit — the caller batches (§8.4).
        """
        digest = profile_hash(profile)
        with self._db.lock:
            self._db.conn.execute(
                "INSERT OR IGNORE INTO task_profiles"
                " (hash, task_name, kind, profile_json, first_seen_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    digest,
                    profile.task_name,
                    profile.kind,
                    json.dumps(profile.to_json(), sort_keys=True),
                    _now(),
                ),
            )
        return digest

    def flush(self) -> None:
        """Commit whatever `remember_profile` left pending.

        `remember_profile` deliberately doesn't commit so an indexing pass
        commits once (§8.4). When that pass turns out to be all cache hits
        there is no `store` to ride along with, and the inserts would sit in an
        open transaction until the connection closed — holding a write lock and
        then discarding work that would just be redone next pass.
        """
        with self._db.lock:
            if self._db.conn.in_transaction:
                self._db.conn.commit()

    def load_profile(self, digest: str) -> TaskProfile | None:
        """Rebuild a snapshotted profile. `to_json` round-trips through the parser."""
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT profile_json FROM task_profiles WHERE hash = ?", (digest,)
            ).fetchone()
        if row is None:
            return None
        try:
            return parse_profile(json.loads(row["profile_json"]))
        except (ValueError, TaskProfileError) as exc:  # pragma: no cover
            log.warning("stored profile %s is unparseable: %s", digest, exc)
            return None

    def profile_meta(self, hashes: list[str]) -> dict[str, dict[str, Any]]:
        """Task name and kind per hash, for labelling profile groups."""
        if not hashes:
            return {}
        marks = ",".join("?" * len(hashes))
        with self._db.lock:
            rows = self._db.conn.execute(
                f"SELECT hash, task_name, kind FROM task_profiles WHERE hash IN ({marks})",
                tuple(hashes),
            ).fetchall()
        return {
            row["hash"]: {"taskName": row["task_name"], "kind": row["kind"]}
            for row in rows
        }

    # --- the derived cache -------------------------------------------------

    def load_cached(self, run_ids: list[str]) -> dict[str, CachedRun]:
        if not run_ids:
            return {}
        out: dict[str, CachedRun] = {}
        # Chunked so a cohort with thousands of runs can't blow SQLite's
        # variable limit (999 by default on older builds).
        for chunk in _chunks(run_ids, 400):
            marks = ",".join("?" * len(chunk))
            with self._db.lock:
                rows = self._db.conn.execute(
                    f"SELECT * FROM run_metrics_cache WHERE run_id IN ({marks})",
                    tuple(chunk),
                ).fetchall()
            for row in rows:
                try:
                    summary = json.loads(row["summary_json"])
                except ValueError:  # pragma: no cover - corrupt cache row
                    continue
                out[row["run_id"]] = CachedRun(
                    run_id=row["run_id"],
                    status=row["status"],
                    detail=row["detail"],
                    profile_hash=row["profile_hash"],
                    profile_source=row["profile_source"],
                    summary=summary,
                    key=CacheKey(
                        file_path=row["file_path"],
                        mtime_ns=row["file_mtime_ns"],
                        size=row["file_size"],
                        profile_hash=row["profile_hash"],
                        codec_version=row["codec_version"],
                    ),
                )
        return out

    # --- adopted orphans (analytics.md §8.1) --------------------------------

    def store_adopted(self, entries: list["AdoptedRun"]) -> None:
        """Record adoptions in one transaction — same commit discipline as
        `store`, and `INSERT OR REPLACE` on the deterministic id makes a
        re-run refresh rather than duplicate."""
        if not entries:
            return
        with self._db.lock:
            self._db.conn.executemany(
                "INSERT OR REPLACE INTO adopted_runs"
                " (id, cohort_id, animal_id, file_path, prefix_name,"
                "  session_number, date, started_at, sketch_name, sketch_path,"
                "  adopted_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        entry.id,
                        entry.cohort_id,
                        entry.animal_id,
                        entry.file_path,
                        entry.prefix_name,
                        entry.session_number,
                        entry.date,
                        entry.started_at,
                        entry.sketch_name,
                        entry.sketch_path,
                        _now(),
                    )
                    for entry in entries
                ],
            )
            self._db.conn.commit()

    def adopted_for_cohort(self, cohort_id: str) -> list["AdoptedRun"]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT * FROM adopted_runs WHERE cohort_id = ?"
                " ORDER BY date, started_at, file_path",
                (cohort_id,),
            ).fetchall()
        return [_hydrate_adopted(row) for row in rows]

    def adopted_by_id(self, run_id: str) -> "AdoptedRun | None":
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT * FROM adopted_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return _hydrate_adopted(row) if row is not None else None

    def store(self, entries: list[CachedRun]) -> None:
        """Write cache rows in **one transaction**.

        Every commit marks the whole database dirty for backup
        (`data-saving.md` §8.3), so committing per row would trigger repeated
        whole-file copies to a possibly-networked target during a single
        indexing pass.
        """
        if not entries:
            return
        with self._db.lock:
            self._db.conn.executemany(
                "INSERT OR REPLACE INTO run_metrics_cache"
                " (run_id, file_path, file_mtime_ns, file_size, profile_hash,"
                "  profile_source, codec_version, computed_at, status, detail,"
                "  summary_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        entry.run_id,
                        entry.key.file_path,
                        entry.key.mtime_ns,
                        entry.key.size,
                        entry.key.profile_hash,
                        entry.profile_source,
                        entry.key.codec_version,
                        _now(),
                        entry.status,
                        entry.detail,
                        json.dumps(entry.summary),
                    )
                    for entry in entries
                ],
            )
            self._db.conn.commit()


@dataclass(frozen=True)
class AdoptedRun:
    """A file the archive walk matched to an animal (`analytics.md` §8.1).

    Deliberately not a `sessions` or `session_animal_runs` row — a fabricated
    session row would corrupt session-number suggestion and the same-day
    warning. What a folder and document name can honestly carry is here;
    what they can't (box number, stop reason, end time) stays unknown.
    """

    id: str
    cohort_id: str
    animal_id: str
    file_path: str
    prefix_name: str
    session_number: str
    date: str | None
    started_at: str
    sketch_name: str | None
    sketch_path: str | None


def _hydrate_adopted(row: sqlite3.Row) -> AdoptedRun:
    return AdoptedRun(
        id=row["id"],
        cohort_id=row["cohort_id"],
        animal_id=row["animal_id"],
        file_path=row["file_path"],
        prefix_name=row["prefix_name"],
        session_number=row["session_number"],
        date=row["date"],
        started_at=row["started_at"],
        sketch_name=row["sketch_name"],
        sketch_path=row["sketch_path"],
    )


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

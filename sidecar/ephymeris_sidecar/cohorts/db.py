"""SQLite connection and schema — `cohorts.md` §3.

One connection guarded by a lock rather than a pool: the write volume here is a
handful of statements per user action, and a single serialized connection is far
easier to reason about than concurrent writers. Callers run operations through
`asyncio.to_thread` so the event loop — which also owns six serial ports — never
blocks on disk.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

DB_FILENAME = "ephymeris.db"

#: Bumped when the schema changes; `PRAGMA user_version` records what a given
#: file was created with, so a future migration has something to branch on.
#: v2 added prefixes / sessions / session_animal_runs (data-saving.md §3–4).
SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS cohorts (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    data_folder  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    archived_at  TEXT
);

CREATE TABLE IF NOT EXISTS groups (
    id         TEXT PRIMARY KEY,
    cohort_id  TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    "order"    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS animals (
    id          TEXT PRIMARY KEY,
    cohort_id   TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    group_id    TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    box_number  INTEGER,
    sex         TEXT,
    id_number   TEXT,
    notes       TEXT
);

CREATE INDEX IF NOT EXISTS idx_groups_cohort  ON groups(cohort_id);
CREATE INDEX IF NOT EXISTS idx_animals_cohort ON animals(cohort_id);

-- Name uniqueness applies to active cohorts only (§2): archived ones release
-- their name. A partial index expresses that directly, so the database enforces
-- the rule rather than trusting every code path to remember it.
CREATE UNIQUE INDEX IF NOT EXISTS idx_cohorts_active_name
    ON cohorts(name COLLATE NOCASE) WHERE archived_at IS NULL;

-- Session prefixes (data-saving.md §3): global, shared across all cohorts.
-- Delete is non-destructive on disk — it only removes the dropdown entry — so
-- there's no soft-delete column, just a hard row delete.
CREATE TABLE IF NOT EXISTS prefixes (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

-- One Starting-a-Session invocation (data-saving.md §4).
CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    cohort_id      TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    -- Prefix is kept even if the prefix row is later deleted (§3), so this
    -- reference is intentionally *not* enforced with a foreign key.
    prefix_id      TEXT NOT NULL,
    prefix_name    TEXT NOT NULL,
    session_number TEXT NOT NULL,
    date           TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    ended_at       TEXT,
    status         TEXT NOT NULL,
    folder_path    TEXT NOT NULL,
    group_runs     TEXT NOT NULL DEFAULT '[]'   -- JSON array, small and read whole
);

-- One animal's run within a session (data-saving.md §4). Forward-looking
-- infrastructure for Analytics; written at finalization.
CREATE TABLE IF NOT EXISTS session_animal_runs (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    animal_id   TEXT NOT NULL,
    box_number  INTEGER NOT NULL,
    sketch_path TEXT NOT NULL,
    file_path   TEXT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    stop_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_cohort ON sessions(cohort_id);
CREATE INDEX IF NOT EXISTS idx_runs_session    ON session_animal_runs(session_id);
"""


class _TrackedConnection(sqlite3.Connection):
    """A connection that reports every successful commit.

    Backup triggering hangs off this rather than off a call in each repository
    method (`data-saving.md` §8). Two reasons: there is no write path that can
    forget to announce itself, and the trigger is genuinely "the database
    changed" rather than the narrower "a cohort changed" — `session_animal_runs`
    is written at finalization during an unattended overnight run, and is not a
    cohort edit by any reading.
    """

    on_commit: Callable[[], None] | None = None

    def commit(self) -> None:
        super().commit()
        if self.on_commit is not None:
            self.on_commit()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._on_commit: Callable[[], None] | None = None

    def on_commit(self, callback: Callable[[], None] | None) -> None:
        """Register a post-commit hook (the backup manager's dirty mark)."""
        self._on_commit = callback
        if self._conn is not None:
            self._conn.on_commit = callback  # type: ignore[attr-defined]

    def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.path,
            # Safe because every access goes through `self._lock`.
            check_same_thread=False,
            factory=_TrackedConnection,
        )
        conn.on_commit = self._on_commit
        conn.row_factory = sqlite3.Row
        # Not on by default in SQLite; without it the ON DELETE CASCADE above
        # is silently inert and deleting a cohort would orphan its animals.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        self._conn = conn
        log.info("cohort database ready at %s", self.path)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def snapshot_to(self, destination: Path) -> None:
        """Write a consistent copy of the database to `destination`.

        Uses SQLite's own online backup API rather than copying the file, so
        this is safe with the live connection open and mid-transaction — a
        plain file copy could capture a torn page. Stdlib only; no dependency.

        `destination` should be **local**. The lock is held for the duration,
        so pointing this straight at a network share would let that share's
        latency block every cohort read in the app; the backup manager
        snapshots locally and does the slow copy afterwards with nothing held.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(destination)
        try:
            with self._lock:
                self.conn.backup(target)
        finally:
            target.close()
        # Trim the WAL/journal companions a fresh connect may have left behind,
        # so what gets mirrored out is a single self-contained file.
        for suffix in ("-wal", "-shm"):
            companion = destination.with_name(destination.name + suffix)
            try:
                os.unlink(companion)
            except OSError:
                pass

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("database is not connected")
        return self._conn

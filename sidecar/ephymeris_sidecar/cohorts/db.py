"""SQLite connection and schema — `DATA.md#sqlite-database`.

One connection guarded by a lock rather than a pool: the write volume here is a
handful of statements per user action, and a single serialized connection is far
easier to reason about than concurrent writers. It is reached only through units
of work, `Database.write` and `Database.read` (`DATA.md#transactions`). Callers run operations through
`asyncio.to_thread` so the event loop — which also owns six serial ports — never
blocks on disk.

**Changing the schema.** `SCHEMA` is the final shape and is applied to every
database on connect, so adding a *table* needs nothing else — `CREATE TABLE IF
NOT EXISTS` covers both the fresh and the existing case. Adding a **column**
does not work that way: the same statement leaves an existing table untouched,
so the column would appear only on databases created after the change. That is
what `MIGRATIONS` is for, and why `connect` reads `PRAGMA user_version` before
it writes it. Bump `SCHEMA_VERSION`, update `SCHEMA`, add the migration, and
extend `tests/test_migrations.py`.

Indexes live in their own `INDEXES` block, applied *after* migrations rather
than alongside the tables. An index on a column a migration is about to add
would otherwise fail on exactly the databases the migration exists for.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

log = logging.getLogger(__name__)

DB_FILENAME = "ephymeris.db"

#: Bumped when the schema changes. `PRAGMA user_version` records what a given
#: file is at, and `connect` reads it before touching anything so migrations
#: have something to branch on.
#: v2 added prefixes / sessions / session_animal_runs (DATA.md#sessions-and-runs).
#: v3 added task_profiles / run_metrics_cache and session_animal_runs.profile_hash
#: (DATA.md#tables) — the first change to need a real migration.
#: v4 added sessions.duration_minutes (`ARCHITECTURE.md#configuration`) — the
#: optional per-box time limit.
#: v5 added animals.cage (`DATA.md#data-model`) — the home-cage grouping label.
#: v6 added session_animal_runs.config_json / params_hash (`TASKS.md#three-layer-merge`)
#: — the task parameters a run actually used, now that they are operator-set.
#: v7 added adopted_runs.file_mtime_ns / file_size
#: (`DATA.md#carrying-adoptions-forward`) — the stat
#: an adoption was taken from, so a rescan can skip a file it has already read.
#: v8 added run_metrics_cache.params_hash and .scored_profile_hash
#: (`DATA.md#the-embedded-task-profile`, `DATA.md#which-profile-decodes-a-run`)
#: — the parameters a run recorded in its own file, and
#: the profile it was actually scored with when that came from the file rather
#: than from resolution.
#: (`ARCHITECTURE.md#cohort-browser`) — the operator's tuning of a cohort's
#: world. NULL on every
#: cohort that has never been tuned, which is the normal state: the whole record
#: is derived from a hash of the cohort's `id` when absent.
#: v10 added sessions.recording_json (`RECORDING.md#what-is-written`) --
#: whether a session is
#: also an electrophysiology recording, and what each group run's recording was.
#: NULL on every behavior-only session, which is every session before this.
#: v11 added session_notes / session_logs (`DATA.md#the-session-log`) — new
#: tables only, so no migration; the bump marks a file a v10 build should know
#: was written by something newer.
#: v12 added run_metrics_cache.config_json (`DATA.md#what-changed`) — the
#: parameter values a recovered run's own file records, so the session log can
#: compare a run this database never recorded.
#: v13 re-keyed every stored profile hash (`TASKS.md#profile-and-params-hashes`)
#: — `profile_hash` stopped covering the `strobes` map once every profile's map
#: became the machine's whole vocabulary — and added `strobe_scan_cache`
#: (`TASKS.md#strobe-vocabulary`) and `run_flags` (`DATA.md#false-starts`).
#: v14 added former_animals (`DATA.md#former-members`) and animal_moves
#: (`DATA.md#moving-animals-between-cohorts`) — new tables only, so no
#: migration, v11's pattern.
#: v15 added folder_moves (`DATA.md#data-folder`) — the journal that lets a
#: relocate move a cohort's files and its records' paths together. A table only.
SCHEMA_VERSION = 15

SCHEMA = """
CREATE TABLE IF NOT EXISTS cohorts (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    data_folder     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    archived_at     TEXT,
    appearance_json TEXT
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
    cage        INTEGER,
    sex         TEXT,
    id_number   TEXT,
    notes       TEXT
);

-- Animals taken off a roster that still have history in the cohort
-- (DATA.md#former-members). A table of their own rather than a removed_at
-- column on `animals`: that table's group_id cascades from `groups`, which
-- every roster edit deletes and re-inserts, so a former member kept there
-- would be deleted along with its old group. The group is kept by name.
CREATE TABLE IF NOT EXISTS former_animals (
    id          TEXT PRIMARY KEY,
    cohort_id   TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    cage        INTEGER,
    sex         TEXT,
    id_number   TEXT,
    notes       TEXT,
    group_name  TEXT,
    removed_at  TEXT NOT NULL
);

-- The journal of a move of animals between cohorts
-- (DATA.md#moving-animals-between-cohorts): written before the first file is
-- copied, so a move a crash interrupted is finished, or undone, at the next
-- start. No foreign keys: the record of a move outlives either cohort.
CREATE TABLE IF NOT EXISTS animal_moves (
    id                TEXT PRIMARY KEY,
    source_cohort_id  TEXT NOT NULL,
    dest_cohort_id    TEXT NOT NULL,
    state             TEXT NOT NULL,   -- copying | committed | done | rolled-back
    plan_json         TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    error             TEXT
);

-- The journal of a "move existing contents" relocate (DATA.md#data-folder):
-- written before the folder moves, so a crash between the files moving and
-- the records following them is finished, or undone, at the next start.
CREATE TABLE IF NOT EXISTS folder_moves (
    id          TEXT PRIMARY KEY,
    cohort_id   TEXT NOT NULL,
    source      TEXT NOT NULL,
    target      TEXT NOT NULL,
    state       TEXT NOT NULL,   -- moving | copying | committed | done | rolled-back
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    error       TEXT
);

-- Session prefixes (DATA.md#prefixes): global, shared across all cohorts.
-- Delete is non-destructive on disk — it only removes the dropdown entry — so
-- there's no soft-delete column, just a hard row delete.
CREATE TABLE IF NOT EXISTS prefixes (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

-- One Starting-a-Session invocation (DATA.md#session-records).
CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    cohort_id      TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    -- Prefix is kept even if the prefix row is later deleted
    -- (DATA.md#prefixes), so this
    -- reference is intentionally *not* enforced with a foreign key.
    prefix_id      TEXT NOT NULL,
    prefix_name    TEXT NOT NULL,
    session_number TEXT NOT NULL,
    date           TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    ended_at       TEXT,
    status         TEXT NOT NULL,
    folder_path    TEXT NOT NULL,
    group_runs     TEXT NOT NULL DEFAULT '[]',  -- JSON array, small and read whole
    -- Optional per-box time limit (ARCHITECTURE.md#configuration). NULL = no
    -- limit; the runner STOPs each box this many minutes after ITS OWN start.
    duration_minutes INTEGER,
    -- Set when the session is also an Intan recording
    -- (RECORDING.md#what-is-written): a JSON
    -- object holding one entry per group run -- where RHX saved it, under what
    -- name, at what sample rate, and which digital input and headstage port
    -- each box was on. NULL = behavior only.
    recording_json TEXT
);

-- One animal's run within a session (DATA.md#run-records). Forward-looking
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
    stop_reason TEXT,
    -- Which Task Profile actually decoded this run
    -- (DATA.md#which-profile-decodes-a-run). NULL
    -- means the run predates snapshotting and must fall back to whatever
    -- task.json currently sits at its sketch_path — which may have changed.
    profile_hash TEXT,
    -- The task parameters this run actually ran on, as authored JSON
    -- (TASKS.md#three-layer-merge), plus a hash of them for indexed comparison.
    --
    -- profile_hash alone stopped being enough to say two runs are comparable
    -- once parameters became operator-set: the profile is the DECLARATION, so
    -- a 10 ms poke hold and a 500 ms one hash identically and would be pooled
    -- onto one axis. The values are already written into every session file;
    -- these two columns are what make them queryable. NULL on any run that
    -- predates the change, which is honest — those values are only on disk.
    config_json TEXT,
    params_hash TEXT
);

-- Content-addressed Task Profile snapshots
-- (DATA.md#which-profile-decodes-a-run). Keyed by
-- a hash of the canonical JSON, so identical profiles across hundreds of runs
-- store once and comparability is an indexed equality test rather than a blob
-- comparison.
CREATE TABLE IF NOT EXISTS task_profiles (
    hash          TEXT PRIMARY KEY,
    task_name     TEXT NOT NULL,
    kind          TEXT NOT NULL,
    profile_json  TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
);

-- Derived per-run metrics (DATA.md#caching). Pure cache: every row can be
-- recomputed from the .json on disk, so losing it costs time and nothing else.
-- Deliberately NO foreign key on run_id — adopted orphans
-- (DATA.md#orphan-adoption) have no
-- session_animal_runs row and carry a synthetic id instead.
CREATE TABLE IF NOT EXISTS run_metrics_cache (
    run_id         TEXT PRIMARY KEY,
    file_path      TEXT NOT NULL,
    file_mtime_ns  INTEGER,
    file_size      INTEGER,
    -- The digest RESOLUTION reached, and half of the freshness key. NULL is
    -- normal and means nothing resolved before the file was opened.
    profile_hash   TEXT,
    profile_source TEXT NOT NULL,   -- 'snapshot' | 'sketch-current' | 'unavailable'
    -- The digest the run was actually SCORED with, which is a different
    -- question: a profile read out of the file itself or inferred from its
    -- strobes is reached after resolution and never appears above. Keeping only
    -- the column above meant such a run reported its hash on the pass that
    -- computed it and NULL on every cached pass after -- so it silently left
    -- its own profile group the moment the cache warmed.
    scored_profile_hash TEXT,
    -- The parameters the FILE recorded, hashed
    -- (DATA.md#the-embedded-task-profile). Only ever read
    -- for a run with no session_animal_runs row of its own -- an adopted
    -- orphan, which is what a session copied from another rig arrives as.
    -- NULL for a run whose file carries no profile snapshot to name them.
    params_hash    TEXT,
    -- Those parameters' values, as JSON — what `params_hash` hashes. Like it,
    -- only ever read for a run with no session_animal_runs row of its own:
    -- the session log compares it with the animal's previous run
    -- (DATA.md#what-changed). NULL when the file names no parameters.
    config_json    TEXT,
    codec_version  INTEGER NOT NULL,
    computed_at    TEXT NOT NULL,
    status         TEXT NOT NULL,   -- 'ok' | 'no-metrics' | 'missing' | 'unreadable'
    detail         TEXT,
    summary_json   TEXT NOT NULL
);

-- Which strobe codes each recorded file contains (TASKS.md#strobe-vocabulary),
-- for the scan that decides whether a code may be removed. Pure cache keyed
-- on the same (path, mtime, size) freshness key as run_metrics_cache: a row
-- whose file changed is simply re-read.
CREATE TABLE IF NOT EXISTS strobe_scan_cache (
    file_path     TEXT PRIMARY KEY,
    file_mtime_ns INTEGER NOT NULL,
    file_size     INTEGER NOT NULL,
    codes_json    TEXT NOT NULL      -- sorted JSON array of distinct codes
);

-- A person's word on one run, overriding the false-start rule
-- (DATA.md#false-starts): 1 = set it aside, 0 = count it whatever the rule
-- says. No row means the rule decides. Keyed by run id, which for an adopted
-- run is the id its cohort holds it under, so the decision survives a rescan.
-- No FK, like run_metrics_cache: an adopted run has no run record.
CREATE TABLE IF NOT EXISTS run_flags (
    run_id      TEXT PRIMARY KEY,
    false_start INTEGER NOT NULL,
    set_at      TEXT NOT NULL
);

-- Orphans adopted by the archive walk (DATA.md#orphan-adoption) — files no
-- session_animal_runs row points at, matched to an animal by the document's
-- `rat` name. Deliberately NOT a sessions or session_animal_runs row: a
-- fabricated session row would corrupt session-number suggestion and the
-- same-day reuse warning. The id is minted from the cohort and the run
-- identity and kept once stored, so re-running the rescan is idempotent.
-- No foreign key on animal_id, same as session_animal_runs — the roster is
-- deleted and re-inserted wholesale on every edit, and adoption storing the
-- *id* is what makes an adopted run survive the animal being renamed
-- afterward.
CREATE TABLE IF NOT EXISTS adopted_runs (
    id             TEXT PRIMARY KEY,
    cohort_id      TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    animal_id      TEXT NOT NULL,
    file_path      TEXT NOT NULL,
    prefix_name    TEXT NOT NULL,
    session_number TEXT NOT NULL,
    date           TEXT,            -- ISO; NULL when the folder name carries none
    started_at     TEXT NOT NULL,
    sketch_name    TEXT,            -- the document's `sketch` field, verbatim
    sketch_path    TEXT,            -- that name resolved against the sketch library at adoption
    adopted_at     TEXT NOT NULL,
    -- The stat this row was adopted from, so the next rescan can tell an
    -- already-adopted file from one it still has to read
    -- (`DATA.md#carrying-adoptions-forward`).
    -- Same freshness key `run_metrics_cache` uses, for the same reason: it is
    -- answerable without opening the file. NULL on rows adopted before v7,
    -- which simply re-read once and then carry a stat like everything else.
    file_mtime_ns  INTEGER,
    file_size      INTEGER
);

-- The session log's timestamped notes (DATA.md#the-session-log). The
-- operator's own words, so — unlike every other table here — user data, not
-- bookkeeping: tidy and prune keep a session that carries one.
CREATE TABLE IF NOT EXISTS session_notes (
    id                  TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    -- Denormalized from the session so a cohort's open flags are one indexed
    -- lookup rather than a join.
    cohort_id           TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    -- The moment the note is about, UTC ISO. Defaults to when it was written
    -- and is editable; a note's T+ offset is derived from it on every read,
    -- never stored, so a tidy merge cannot leave one stale.
    at                  TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    edited_at           TEXT,
    deleted_at          TEXT,           -- soft delete: hidden, never erased
    tag                 TEXT NOT NULL,  -- observation | intervention | hardware | animal-health | protocol-deviation
    scope_kind          TEXT NOT NULL DEFAULT 'session',  -- session | animal | box
    -- No foreign key, for the reason session_animal_runs has none: the roster
    -- is deleted and re-inserted on every cohort edit.
    animal_id           TEXT,
    box_number          INTEGER,
    body                TEXT NOT NULL,
    carry_forward       INTEGER NOT NULL DEFAULT 0,
    resolved_at         TEXT,
    -- The session a flag was resolved during, when there was one. No foreign
    -- key: tidy may delete that session, and the resolution still stands.
    resolved_in_session TEXT
);

-- The session log's free fields (DATA.md#the-session-log): who ran it and what
-- they made of it. A table of its own rather than columns on `sessions`, so
-- the Session wire shape and every session code path stay untouched.
CREATE TABLE IF NOT EXISTS session_logs (
    session_id  TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    operator    TEXT,
    summary     TEXT,
    updated_at  TEXT NOT NULL
);
"""


#: Applied *after* migrations, never with the tables. An index on a column a
#: migration is about to add would otherwise fail on exactly the databases the
#: migration exists for — `CREATE INDEX` does not honour a column that isn't
#: there yet, and `executescript(SCHEMA)` runs before `_migrate`.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_groups_cohort  ON groups(cohort_id);
CREATE INDEX IF NOT EXISTS idx_animals_cohort ON animals(cohort_id);
CREATE INDEX IF NOT EXISTS idx_former_cohort  ON former_animals(cohort_id);
-- Name uniqueness applies to active cohorts only (DATA.md#validation):
-- archived ones release
-- their name. A partial index expresses that directly, so the database enforces
-- the rule rather than trusting every code path to remember it.
CREATE UNIQUE INDEX IF NOT EXISTS idx_cohorts_active_name
    ON cohorts(name COLLATE NOCASE) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_cohort ON sessions(cohort_id);
CREATE INDEX IF NOT EXISTS idx_runs_session    ON session_animal_runs(session_id);
-- Per-animal cross-session history was a full scan before this
-- (DATA.md#indexes). An index, never a foreign key: `cohorts.update` deletes and
-- re-inserts the whole animal set on every roster edit, so ON DELETE CASCADE
-- would destroy every historical run on a single rename.
CREATE INDEX IF NOT EXISTS idx_runs_animal     ON session_animal_runs(animal_id);
CREATE INDEX IF NOT EXISTS idx_runs_profile    ON session_animal_runs(profile_hash);
-- Comparability is (profile_hash, params_hash) now, so the pair is what gets
-- looked up (DATA.md#indexes).
CREATE INDEX IF NOT EXISTS idx_runs_params     ON session_animal_runs(profile_hash, params_hash);
-- The chronological session axis, index-ordered rather than sorted per read.
CREATE INDEX IF NOT EXISTS idx_sessions_cohort_dt ON sessions(cohort_id, date);
CREATE INDEX IF NOT EXISTS idx_adopted_cohort ON adopted_runs(cohort_id);
-- One row per file even if a re-scan races a path-normalization change.
CREATE UNIQUE INDEX IF NOT EXISTS idx_adopted_file ON adopted_runs(cohort_id, file_path);
CREATE INDEX IF NOT EXISTS idx_notes_session ON session_notes(session_id, at);
CREATE INDEX IF NOT EXISTS idx_notes_cohort  ON session_notes(cohort_id);
-- Step 1 asks for a cohort's open carry-forward flags on every set-up.
CREATE INDEX IF NOT EXISTS idx_notes_open_flags ON session_notes(cohort_id)
    WHERE carry_forward = 1 AND resolved_at IS NULL AND deleted_at IS NULL;
"""

#: Every column that stores where a file or folder lies inside a data folder,
#: so a relocate must rebase it (`relocate.rewrite_paths`,
#: `DATA.md#data-folder`). `recording_json` carries one per recorded group
#: run, as `runs[].path`. A new column that names a path goes here or in
#: `OTHER_PATHS`; `test_relocate.py` fails until it does.
DATA_PATHS: tuple[tuple[str, str], ...] = (
    ("sessions", "folder_path"),
    ("sessions", "recording_json"),
    ("session_animal_runs", "file_path"),
    ("adopted_runs", "file_path"),
    ("run_metrics_cache", "file_path"),
    ("strobe_scan_cache", "file_path"),
)

#: Columns that look like they could hold such a path, and why a relocate
#: leaves them alone.
OTHER_PATHS: dict[tuple[str, str], str] = {
    ("cohorts", "data_folder"): "the folder itself; the relocate sets it",
    ("session_animal_runs", "sketch_path"): "the sketch library, not a data folder",
    ("adopted_runs", "sketch_path"): "the sketch library, not a data folder",
    ("folder_moves", "source"): "a relocate's own journal",
    ("folder_moves", "target"): "a relocate's own journal",
    ("animal_moves", "plan_json"): "a move's own journal",
    ("cohorts", "appearance_json"): "no paths",
    ("run_metrics_cache", "config_json"): "no paths",
    ("run_metrics_cache", "summary_json"): "no paths",
    ("session_animal_runs", "config_json"): "no paths",
    ("strobe_scan_cache", "codes_json"): "no paths",
    ("task_profiles", "profile_json"): "no paths",
}


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Column names on `table`, or an empty set if it doesn't exist."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> bool:
    """`ALTER TABLE ADD COLUMN`, skipped when the column is already there.

    Returns whether it actually ran. Idempotent on purpose: a migration
    interrupted halfway — power loss, a kill during startup — must be safe to
    re-run rather than fatal on the next launch.

    New columns must be nullable or carry a constant default; SQLite cannot add
    a `NOT NULL` column without one to an existing table.
    """
    if column in table_columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    log.info("migration: added %s.%s", table, column)
    return True


def _to_v3(conn: sqlite3.Connection) -> None:
    """v2 → v3: the Task Profile snapshot link (`DATA.md#which-profile-decodes-a-run`).

    `task_profiles` and `run_metrics_cache` are new *tables*, so `SCHEMA`'s
    `CREATE TABLE IF NOT EXISTS` already made them — only the column needs
    doing here.
    """
    add_column(conn, "session_animal_runs", "profile_hash", "TEXT")


def _to_v4(conn: sqlite3.Connection) -> None:
    """v3 → v4: the per-box session time limit (`ARCHITECTURE.md#configuration`).

    NULL on every pre-existing session is exactly right — they ran without one.
    """
    add_column(conn, "sessions", "duration_minutes", "INTEGER")


def _to_v6(conn: sqlite3.Connection) -> None:
    """v5 → v6: the task parameters a run used (`TASKS.md#three-layer-merge`).

    NULL on every pre-existing run and correct that way: those runs took their
    parameters from firmware constants, so there is nothing per-run to record.
    """
    add_column(conn, "session_animal_runs", "config_json", "TEXT")
    add_column(conn, "session_animal_runs", "params_hash", "TEXT")


def _to_v7(conn: sqlite3.Connection) -> None:
    """v6 → v7: the stat an adoption was taken from
    (`DATA.md#carrying-adoptions-forward`).

    NULL on every pre-existing adoption, and that is the safe direction: a row
    with no recorded stat is never treated as fresh, so the first rescan after
    this migration re-reads exactly as it always did and records a stat on the
    way through. The saving starts one scan later rather than on a guess.
    """
    add_column(conn, "adopted_runs", "file_mtime_ns", "INTEGER")
    add_column(conn, "adopted_runs", "file_size", "INTEGER")


def _to_v8(conn: sqlite3.Connection) -> None:
    """v7 → v8: what a run's own file records
    (`DATA.md#the-embedded-task-profile`, `DATA.md#which-profile-decodes-a-run`).

    Two columns on the derived cache. `params_hash` is pure gain and NULL costs
    nothing — it fills in on the next pass that recomputes a row.

    `scored_profile_hash` needs one repair on top of the column, and it is the
    reason this migration deletes anything. A row scored from an *inferred*
    profile recorded its digest nowhere: the existing `profile_hash` column
    holds what resolution reached, which for those rows is NULL by definition.
    So they served a hash on the pass that computed them and NULL forever
    after, dropping out of their own profile group once the cache warmed. The
    new column fixes that going forward, but only for rows that recompute — and
    those rows never will, because their freshness key still matches. Deleting
    exactly them is what un-sticks it. It is a pure cache: the cost is re-reading
    those files once.
    """
    add_column(conn, "run_metrics_cache", "params_hash", "TEXT")
    if add_column(conn, "run_metrics_cache", "scored_profile_hash", "TEXT"):
        conn.execute("DELETE FROM run_metrics_cache WHERE profile_source = 'inferred'")


def _to_v9(conn: sqlite3.Connection) -> None:
    """v8 → v9: the cohort's world (`ARCHITECTURE.md#cohort-browser`).

    NULL on every existing cohort and correct that way. An absent appearance is
    not a missing value to be backfilled — it means "derive it from the id",
    which is what every cohort did before this column and what the client still
    does when it reads NULL. Writing a derived record into the column here would
    freeze each cohort against every later correction to the palette or the
    default type, for no gain.
    """
    add_column(conn, "cohorts", "appearance_json", "TEXT")


def _to_v12(conn: sqlite3.Connection) -> None:
    """v11 → v12: a recovered run's recorded parameter values
    (`DATA.md#what-changed`).

    The column alone would never fill for rows already in the cache: their
    freshness key still matches, so they are never re-read. So the rows of
    recovered runs — the only ones the column is read for — are dropped, the
    v8 repair's pattern. It is a pure cache: the cost is reading those files
    once more on the next summary.
    """
    if add_column(conn, "run_metrics_cache", "config_json", "TEXT"):
        conn.execute(
            "DELETE FROM run_metrics_cache WHERE run_id IN (SELECT id FROM adopted_runs)"
        )


def _to_v5(conn: sqlite3.Connection) -> None:
    """v4 → v5: the home-cage grouping label (`DATA.md#data-model`).

    NULL means "cage unknown", which is true of every animal entered before
    the field existed.
    """
    add_column(conn, "animals", "cage", "INTEGER")


def _to_v10(conn: sqlite3.Connection) -> None:
    """v9 → v10: the session's recording record (`RECORDING.md#what-is-written`).

    NULL is "behavior only", which is true of every session recorded before
    this column existed, so there is nothing to backfill.
    """
    add_column(conn, "sessions", "recording_json", "TEXT")


def _to_v13(conn: sqlite3.Connection) -> None:
    """v12 → v13: every stored profile hash, recomputed without `strobes`
    (`TASKS.md#profile-and-params-hashes`).

    WHY THE HASH MOVED. A profile's `strobes` map is now filled from the
    machine's whole vocabulary at load time, so hashing it would have split
    every task's history in Analytics the first time anyone added a code. Codes
    are never renumbered or repurposed, so the map never said anything about
    comparability that the rest of the profile did not.

    Rows re-keyed in place: each stored profile is re-parsed and re-hashed, and
    every column holding the old digest follows it. Two profiles that differed
    ONLY in their strobe maps collapse to one, which is the point — they were
    the same task split by a map that differed between generator versions. The
    first-seen date of the merged row is the earlier of the two.
    """
    import json

    from ..tasks.profile import TaskProfileError, parse_profile, profile_hash

    rows = conn.execute(
        "SELECT hash, task_name, kind, profile_json, first_seen_at FROM task_profiles"
    ).fetchall()
    remap: dict[str, str] = {}
    for old, task_name, kind, profile_json, first_seen in rows:
        try:
            new = profile_hash(parse_profile(json.loads(profile_json)))
        except (ValueError, TaskProfileError) as exc:
            # Unparseable rows were already unusable; leaving them keyed as
            # they were costs nothing and invents nothing.
            log.warning("v13: stored profile %s left as it was: %s", old, exc)
            continue
        if new == old:
            continue
        remap[old] = new
        conn.execute(
            "INSERT OR IGNORE INTO task_profiles"
            " (hash, task_name, kind, profile_json, first_seen_at) VALUES (?, ?, ?, ?, ?)",
            (new, task_name, kind, profile_json, first_seen),
        )
        conn.execute(
            "UPDATE task_profiles SET first_seen_at = MIN(first_seen_at, ?) WHERE hash = ?",
            (first_seen, new),
        )
        conn.execute("DELETE FROM task_profiles WHERE hash = ?", (old,))
    for old, new in remap.items():
        conn.execute(
            "UPDATE session_animal_runs SET profile_hash = ? WHERE profile_hash = ?", (new, old)
        )
        conn.execute(
            "UPDATE run_metrics_cache SET profile_hash = ? WHERE profile_hash = ?", (new, old)
        )
        conn.execute(
            "UPDATE run_metrics_cache SET scored_profile_hash = ? WHERE scored_profile_hash = ?",
            (new, old),
        )
    if remap:
        log.info("v13: re-keyed %d stored task profile(s)", len(remap))


#: Migrations, keyed by the version they upgrade **to**, applied in ascending
#: order.
#:
#: **Adding a column needs an entry here.** `SCHEMA` above must carry the final
#: shape — so a fresh database is correct without running anything — and the
#: entry below brings an existing database to the same shape. Without both, a
#: new column silently never appears on any database that already exists, while
#: `user_version` still gets stamped to the new number. Adding a *table* needs
#: no entry: `CREATE TABLE IF NOT EXISTS` covers both cases on its own.
MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    3: _to_v3,
    4: _to_v4,
    5: _to_v5,
    6: _to_v6,
    7: _to_v7,
    8: _to_v8,
    9: _to_v9,
    10: _to_v10,
    12: _to_v12,
    13: _to_v13,
}


def _existing_version(conn: sqlite3.Connection) -> int | None:
    """The version of the database already in this file, or `None` if fresh.

    Freshness is decided by whether `cohorts` exists, **not** by
    `PRAGMA user_version` — a file written by a build that predates versioning
    would report 0 while holding real tables, and skipping migrations on it is
    exactly the silent failure this function exists to prevent. Such a file is
    treated as v1, the earliest shape, so every migration applies.
    """
    present = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cohorts'"
    ).fetchone()
    if present is None:
        return None
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    return version if version > 0 else 1


def _migrate(conn: sqlite3.Connection, found: int) -> None:
    """Bring an existing database up to `SCHEMA_VERSION`. Never commits."""
    if found > SCHEMA_VERSION:
        # Someone opened a newer database with an older build. Every change so
        # far is additive, so the extra tables and columns are inert here and
        # continuing is safer than refusing to start — but say so loudly,
        # because the reverse assumption would corrupt data silently.
        log.error(
            "database is schema v%d but this build expects v%d; continuing, but "
            "it was written by a newer version of Ephymeris",
            found,
            SCHEMA_VERSION,
        )
        return
    if found == SCHEMA_VERSION:
        return

    log.info("migrating database from schema v%d to v%d", found, SCHEMA_VERSION)
    for target in sorted(MIGRATIONS):
        if found < target <= SCHEMA_VERSION:
            MIGRATIONS[target](conn)


class NestedWrite(RuntimeError):
    """A unit of work was opened inside another on the same thread, or a unit
    was joined, or used, other than on its thread while it is open
    (`DATA.md#transactions`). Pass the open unit (`tx=`) to share it."""


class WriteInProgress(RuntimeError):
    """A write is open on the connection where none may be: a snapshot taken
    inside a unit of work, or a write begun outside any unit. Refused rather
    than waited on forever or adopted (`DATA.md#the-database-copy`,
    `DATA.md#transactions`)."""


class TransactionAborted(RuntimeError):
    """SQLite rolled this unit's transaction back itself -- a full disk, an
    I/O error, an interrupt -- so nothing more runs in it: a statement after
    that would commit on its own, half a unit. The unit raises this and
    commits nothing (`DATA.md#transactions`)."""


class Query:
    """Statements under the database lock. No commit and no rollback: the
    unit of work that opened it decides those."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn: sqlite3.Connection | None = conn

    def execute(self, sql: str, params: Any = ()) -> sqlite3.Cursor:
        return self._open().execute(sql, params)

    def executemany(self, sql: str, rows: Iterable[Any]) -> sqlite3.Cursor:
        return self._open().executemany(sql, rows)

    def _open(self) -> sqlite3.Connection:
        if self._conn is None:
            raise NestedWrite("this unit of work has already ended")
        return self._conn

    def _close(self) -> None:
        self._conn = None


class Tx(Query):
    """One unit of work (`Database.write`)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__(conn)
        self._thread = threading.get_ident()
        self._after: list[Callable[[], None]] = []

    def on_commit(self, callback: Callable[[], None]) -> None:
        """Run `callback` once this unit has committed, after the lock is
        released, so it may use the database. Dropped if the unit rolls back."""
        self._open()
        self._after.append(callback)

    def _open(self) -> sqlite3.Connection:
        conn = super()._open()
        if not conn.in_transaction:
            raise TransactionAborted("SQLite rolled this unit of work back")
        return conn


def _undo(conn: sqlite3.Connection) -> None:
    """Roll back one unit of work. Never raises over the error that brought
    it here; SQLite may already have rolled the transaction back itself."""
    if conn.in_transaction:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:  # pragma: no cover - nothing left to try
            log.exception("couldn't roll back a unit of work")


class Database:
    """The one connection, its lock, and the units of work on it
    (`DATA.md#transactions`)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._on_commit: Callable[[], None] | None = None
        #: The open unit of work, and so the thread holding the lock for it.
        self._tx: Tx | None = None

    def on_commit(self, callback: Callable[[], None] | None) -> None:
        """Register a post-commit hook (the backup manager's dirty mark).
        When it fires: `DATA.md#transactions`."""
        self._on_commit = callback

    # --- the unit of work (DATA.md#transactions) ---------------------------

    @contextmanager
    def write(self, tx: Tx | None = None) -> Iterator[Tx]:
        """A unit of work: the lock, a transaction, `COMMIT` when the block
        ends and `ROLLBACK` if it raises. Only the opener commits.

        Pass an open unit as `tx` to join it instead: the block runs inside
        that unit and commits nothing. A unit is joined only on the thread
        that opened it, and opening a second one there raises `NestedWrite`
        rather than deadlocking on the lock or committing early.
        """
        if tx is not None:
            if tx is not self._tx or tx._thread != threading.get_ident():
                raise NestedWrite("only this thread's open unit of work can be joined")
            yield tx
            return
        if self._tx is not None and self._tx._thread == threading.get_ident():
            raise NestedWrite("a unit of work is already open on this thread; pass it as tx=")

        follow_ups: list[Callable[[], None]] = []
        with self._lock:
            conn = self._connected()
            if conn.in_transaction:
                # Only a unit begins a transaction, and every unit ends its
                # own before the lock is free; one open here is a bug, and its
                # rows are not this unit's to commit or roll back.
                raise WriteInProgress("a write is open outside any unit of work")
            conn.execute("BEGIN IMMEDIATE")
            before = conn.total_changes
            unit = Tx(conn)
            self._tx = unit
            try:
                try:
                    yield unit
                finally:
                    self._tx = None
                    unit._close()
                changed = conn.total_changes != before
                if not conn.in_transaction:
                    raise TransactionAborted("SQLite rolled this unit of work back")
                conn.execute("COMMIT")
            except BaseException:
                _undo(conn)
                raise
            if changed and self._on_commit is not None:
                try:
                    self._on_commit()
                except Exception:  # noqa: BLE001 - committed regardless
                    log.exception("the database's commit hook failed")
            follow_ups = unit._after
        for callback in follow_ups:
            try:
                callback()
            except Exception:  # noqa: BLE001 - the unit is committed regardless
                log.exception("a follow-up to a committed unit of work failed")

    @contextmanager
    def read(self) -> Iterator[Query]:
        """Statements under the lock, for reading. Inside this thread's own
        unit of work, that unit -- so a read sees the unit's own rows.

        Outside a unit the connection is `query_only` for the block, so a
        read cannot write; one that begins a transaction is rolled back and
        refused, so the lock is never free with a transaction open.
        """
        if self._tx is not None and self._tx._thread == threading.get_ident():
            yield self._tx
            return
        with self._lock:
            conn = self._connected()
            # Open already is a bug outside this read (the snapshot refuses it);
            # not this read's to roll back.
            already_open = conn.in_transaction
            conn.execute("PRAGMA query_only = ON")
            query = Query(conn)
            try:
                yield query
            finally:
                query._close()
                left_open = conn.in_transaction and not already_open
                if left_open:
                    _undo(conn)
                conn.execute("PRAGMA query_only = OFF")
            if left_open:
                raise WriteInProgress("a read began a transaction")

    @property
    def in_transaction(self) -> bool:
        """Whether a transaction is open on the connection: only ever inside
        a unit of work (`DATA.md#transactions`)."""
        return self._connected().in_transaction

    def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.path,
            # Safe because every access goes through `self._lock`.
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        # Not on by default in SQLite; without it the ON DELETE CASCADE above
        # is silently inert and deleting a cohort would orphan its animals.
        conn.execute("PRAGMA foreign_keys = ON")

        # Read the version *before* anything touches the file. `executescript`
        # is all `CREATE TABLE IF NOT EXISTS`, so it silently leaves an existing
        # table alone — including one missing a column this build expects.
        found = _existing_version(conn)
        conn.executescript(SCHEMA)
        if found is not None:
            _migrate(conn, found)
        # Indexes last: one of them covers a column a migration just added, and
        # `CREATE INDEX` cannot name a column that doesn't exist yet.
        conn.executescript(INDEXES)

        # One commit for the whole of startup, announced once like a unit of
        # work's (`DATA.md#the-database-copy`): a migration committing per step
        # would trigger repeated whole-file copies to a possibly-networked
        # target before the app has even finished starting.
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        if self._on_commit is not None:
            self._on_commit()
        # From here the only transactions are the ones `write` begins
        # (`DATA.md#transactions`): no statement opens one implicitly.
        conn.isolation_level = None
        self._conn = conn
        log.info("cohort database ready at %s (schema v%d)", self.path, SCHEMA_VERSION)

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

        Waits for any unit of work on another thread to end. Raises
        `WriteInProgress`, copying nothing, inside this thread's own unit, or
        if a bug left a write open (`DATA.md#the-database-copy`).
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.read():
            conn = self._connected()
            if conn.in_transaction:
                raise WriteInProgress("a write is still open; snapshot later")
            target = sqlite3.connect(destination)
            try:
                conn.backup(target)
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

    def _connected(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("database is not connected")
        return self._conn

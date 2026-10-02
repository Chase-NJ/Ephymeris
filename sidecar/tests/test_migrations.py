"""Schema migration — `DATA.md#changing-the-schema`.

The bug this file exists to prevent: `connect()` used to stamp
`PRAGMA user_version` without ever reading it, and `SCHEMA` is entirely
`CREATE TABLE IF NOT EXISTS`. So a new **column** was silently skipped on any
database that already existed, while the version was bumped anyway — leaving a
file that *claimed* the new version and lacked the column. The next query
against it would raise `OperationalError` on a lab machine, mid-session, at
finalization.

New tables were always fine, which is why this never bit: every schema change
so far has added tables. That makes this branch permanently under-exercised by
normal use, so the tests below drive it directly.

`SCHEMA_V1` is pinned as a literal on purpose. Importing the current schema and
mutating it would test today's code against itself and drift the moment someone
edits `db.py`; a frozen copy of what v1 actually looked like is the only thing
that keeps proving the upgrade path works.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts.db import (
    MIGRATIONS,
    SCHEMA_VERSION,
    Database,
    add_column,
    table_columns,
)

#: The schema exactly as it stood at v1 — cohorts, groups, animals, and nothing
#: else. v2 added prefixes / sessions / session_animal_runs.
SCHEMA_V1 = """
CREATE TABLE cohorts (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    data_folder  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    archived_at  TEXT
);
CREATE TABLE groups (
    id         TEXT PRIMARY KEY,
    cohort_id  TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    "order"    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE animals (
    id          TEXT PRIMARY KEY,
    cohort_id   TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    group_id    TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    box_number  INTEGER,
    sex         TEXT,
    id_number   TEXT,
    notes       TEXT
);
CREATE UNIQUE INDEX idx_cohorts_active_name
    ON cohorts(name COLLATE NOCASE) WHERE archived_at IS NULL;
"""


def write_v1_database(path: Path, *, version: int = 1) -> None:
    """A real v1 file with a cohort in it, so migrations have data to preserve."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_V1)
        conn.execute(
            "INSERT INTO cohorts (id, name, data_folder, created_at, updated_at)"
            " VALUES ('c1', 'Batch A', '/data/Batch A', 'then', 'then')",
        )
        conn.execute(
            'INSERT INTO groups (id, cohort_id, name, "order") VALUES ("g1", "c1", "Group 1", 0)'
        )
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    finally:
        conn.close()


def user_version(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()


# --- the fresh case -------------------------------------------------------


def test_a_fresh_database_lands_at_the_current_version(tmp_path: Path) -> None:
    path = tmp_path / "ephymeris.db"
    db = Database(path)
    db.connect()
    db.close()

    assert user_version(path) == SCHEMA_VERSION
    # SCHEMA carries the final shape, so a fresh file is correct with no migration.
    assert {"cohorts", "groups", "animals", "prefixes", "sessions", "session_animal_runs"} <= tables(path)


# --- the upgrade case -----------------------------------------------------


def test_a_v1_database_is_upgraded_in_place(tmp_path: Path) -> None:
    path = tmp_path / "ephymeris.db"
    write_v1_database(path)
    assert "sessions" not in tables(path)

    db = Database(path)
    db.connect()
    db.close()

    assert user_version(path) == SCHEMA_VERSION
    assert {"prefixes", "sessions", "session_animal_runs"} <= tables(path)


def test_a_v1_database_gains_the_columns_later_versions_added(tmp_path: Path) -> None:
    """The column path, driven by the real registry rather than a stand-in.

    v3 added `session_animal_runs.profile_hash` — but on a v1 file that table
    is created whole by SCHEMA, so the one column an upgraded v1 database
    genuinely gains by ALTER is v5's `animals.cage`.
    """
    path = tmp_path / "ephymeris.db"
    write_v1_database(path)

    db = Database(path)
    db.connect()
    try:
        assert "cage" in table_columns(db.conn, "animals")
        runs = table_columns(db.conn, "session_animal_runs")
        assert "profile_hash" in runs
        assert "config_json" in runs and "params_hash" in runs
        assert "duration_minutes" in table_columns(db.conn, "sessions")
        assert "cage" in table_columns(db.conn, "animals")
    finally:
        db.close()


def test_upgrading_preserves_existing_rows(tmp_path: Path) -> None:
    """A migration that loses the lab's cohorts is worse than one that fails."""
    path = tmp_path / "ephymeris.db"
    write_v1_database(path)

    db = Database(path)
    db.connect()
    try:
        row = db.conn.execute("SELECT name, data_folder FROM cohorts").fetchone()
    finally:
        db.close()

    assert row["name"] == "Batch A"
    assert row["data_folder"] == "/data/Batch A"


def test_a_versionless_database_is_treated_as_v1(tmp_path: Path) -> None:
    """`user_version = 0` plus real tables means a build that predates versioning.

    Trusting the 0 and skipping migrations would be the same silent failure in
    a different costume, so freshness is decided by whether `cohorts` exists.
    """
    path = tmp_path / "ephymeris.db"
    write_v1_database(path, version=0)

    db = Database(path)
    db.connect()
    db.close()

    assert user_version(path) == SCHEMA_VERSION
    assert "sessions" in tables(path)


# --- the branch itself, driven directly -----------------------------------


def test_a_registered_migration_adds_a_column_to_an_existing_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact case that was broken, exercised end to end.

    `MIGRATIONS` is empty today because every schema change so far added
    tables. This registers one so the column path is actually driven — without
    it, nothing in the suite would touch the branch until the next column
    lands, which is precisely when a latent bug would surface.
    """
    path = tmp_path / "ephymeris.db"
    write_v1_database(path)

    def add_a_column(conn: sqlite3.Connection) -> None:
        add_column(conn, "cohorts", "experimenter", "TEXT")

    monkeypatch.setitem(MIGRATIONS, SCHEMA_VERSION, add_a_column)

    db = Database(path)
    db.connect()
    try:
        assert "experimenter" in table_columns(db.conn, "cohorts")
        # The column is real and writable, not just present in the metadata.
        db.conn.execute("UPDATE cohorts SET experimenter = 'CJ' WHERE id = 'c1'")
        assert db.conn.execute("SELECT experimenter FROM cohorts").fetchone()[0] == "CJ"
    finally:
        db.close()


def test_a_fresh_database_does_not_run_migrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SCHEMA already carries the final shape, so migrations are upgrade-only."""
    ran: list[str] = []

    def record(conn: sqlite3.Connection) -> None:
        ran.append("migrated")

    monkeypatch.setitem(MIGRATIONS, SCHEMA_VERSION, record)

    db = Database(tmp_path / "ephymeris.db")
    db.connect()
    db.close()

    assert ran == []


def test_an_already_current_database_does_not_run_migrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "ephymeris.db"
    Database(path).connect()  # bring it to current

    ran: list[str] = []
    monkeypatch.setitem(MIGRATIONS, SCHEMA_VERSION, lambda conn: ran.append("x"))

    db = Database(path)
    db.connect()
    db.close()
    assert ran == []


def test_add_column_is_idempotent(tmp_path: Path) -> None:
    """A migration interrupted halfway must be safe to re-run, not fatal."""
    path = tmp_path / "ephymeris.db"
    write_v1_database(path)
    conn = sqlite3.connect(path)
    try:
        assert add_column(conn, "cohorts", "experimenter", "TEXT") is True
        conn.execute("UPDATE cohorts SET experimenter = 'CJ'")
        # Second run is a no-op and leaves the written value alone.
        assert add_column(conn, "cohorts", "experimenter", "TEXT") is False
        assert conn.execute("SELECT experimenter FROM cohorts").fetchone()[0] == "CJ"
    finally:
        conn.close()


def test_table_columns_on_a_missing_table_is_empty(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "x.db")
    try:
        assert table_columns(conn, "nope") == set()
    finally:
        conn.close()


# --- the real v2 -> v3 migration ------------------------------------------


def write_v2_database(path: Path) -> None:
    """A v2 file: the v1 tables plus sessions, with **no** `profile_hash`.

    Pinned as a literal for the same reason `SCHEMA_V1` is — this must keep
    proving the upgrade works even after `db.py` moves on.
    """
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_V1)
        conn.executescript(
            """
            CREATE TABLE prefixes (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE);
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                cohort_id TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
                prefix_id TEXT NOT NULL, prefix_name TEXT NOT NULL,
                session_number TEXT NOT NULL, date TEXT NOT NULL,
                started_at TEXT NOT NULL, ended_at TEXT, status TEXT NOT NULL,
                folder_path TEXT NOT NULL, group_runs TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE session_animal_runs (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                animal_id TEXT NOT NULL, box_number INTEGER NOT NULL,
                sketch_path TEXT NOT NULL, file_path TEXT,
                started_at TEXT NOT NULL, ended_at TEXT, stop_reason TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO cohorts (id, name, data_folder, created_at, updated_at)"
            " VALUES ('c1', 'Batch A', '/data/Batch A', 'then', 'then')"
        )
        conn.execute(
            "INSERT INTO sessions (id, cohort_id, prefix_id, prefix_name, session_number,"
            " date, started_at, status, folder_path) VALUES"
            " ('s1','c1','p1','2O-Bdisc','25','2026-07-22','then','completed','/f')"
        )
        conn.execute(
            "INSERT INTO session_animal_runs (id, session_id, animal_id, box_number,"
            " sketch_path, started_at) VALUES ('r1','s1','a1',1,'/sk','then')"
        )
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
    finally:
        conn.close()


def test_v2_gains_the_profile_hash_column(tmp_path: Path) -> None:
    """The first change that actually needed this branch (`DATA.md#changing-the-schema`).

    Before the migration branch existed, `CREATE TABLE IF NOT EXISTS` would
    have silently skipped this column on every existing database while
    `user_version` was bumped regardless — and the next finalization would
    raise `OperationalError` mid-session.
    """
    path = tmp_path / "ephymeris.db"
    write_v2_database(path)

    db = Database(path)
    db.connect()
    try:
        assert "profile_hash" in table_columns(db.conn, "session_animal_runs")
        # Writable, not merely present in the metadata.
        db.conn.execute("UPDATE session_animal_runs SET profile_hash = '3f8a' WHERE id = 'r1'")
        assert db.conn.execute(
            "SELECT profile_hash FROM session_animal_runs"
        ).fetchone()[0] == "3f8a"
    finally:
        db.close()

    assert user_version(path) == SCHEMA_VERSION


def test_v2_gains_the_analytics_tables(tmp_path: Path) -> None:
    """New *tables* need no migration entry — `SCHEMA` alone covers them."""
    path = tmp_path / "ephymeris.db"
    write_v2_database(path)

    db = Database(path)
    db.connect()
    db.close()

    assert {"task_profiles", "run_metrics_cache"} <= tables(path)


def test_upgrading_from_v2_preserves_existing_runs(tmp_path: Path) -> None:
    path = tmp_path / "ephymeris.db"
    write_v2_database(path)

    db = Database(path)
    db.connect()
    try:
        row = db.conn.execute("SELECT animal_id, profile_hash FROM session_animal_runs").fetchone()
    finally:
        db.close()

    assert row["animal_id"] == "a1"
    assert row["profile_hash"] is None, "a legacy run's NULL hash is the flag Analytics reads"


def test_the_v2_upgrade_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "ephymeris.db"
    write_v2_database(path)
    for _ in range(3):
        db = Database(path)
        db.connect()
        db.close()
    conn = sqlite3.connect(path)
    try:
        names = [row[1] for row in conn.execute("PRAGMA table_info(session_animal_runs)")]
    finally:
        conn.close()
    assert names.count("profile_hash") == 1


# --- the real v3 -> v4 migration ------------------------------------------


def write_v3_database(path: Path) -> None:
    """A v3 file: the v2 tables plus `profile_hash`, with **no**
    `duration_minutes`. Pinned as a literal like its siblings above.
    """
    write_v2_database(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("ALTER TABLE session_animal_runs ADD COLUMN profile_hash TEXT")
        conn.execute("PRAGMA user_version = 3")
        conn.commit()
    finally:
        conn.close()


def test_v3_gains_the_duration_minutes_column(tmp_path: Path) -> None:
    """The per-box time limit (`ARCHITECTURE.md#configuration`)."""
    path = tmp_path / "ephymeris.db"
    write_v3_database(path)

    db = Database(path)
    db.connect()
    try:
        assert "duration_minutes" in table_columns(db.conn, "sessions")
        # Writable, not merely present in the metadata.
        db.conn.execute("UPDATE sessions SET duration_minutes = 60 WHERE id = 's1'")
        assert db.conn.execute(
            "SELECT duration_minutes FROM sessions"
        ).fetchone()[0] == 60
    finally:
        db.close()

    assert user_version(path) == SCHEMA_VERSION


def test_upgrading_from_v3_leaves_old_sessions_unlimited(tmp_path: Path) -> None:
    """NULL on a pre-existing session is correct — it ran without a limit."""
    path = tmp_path / "ephymeris.db"
    write_v3_database(path)

    db = Database(path)
    db.connect()
    try:
        row = db.conn.execute("SELECT duration_minutes FROM sessions").fetchone()
    finally:
        db.close()

    assert row["duration_minutes"] is None


# --- the real v5 -> v6 migration ------------------------------------------


def write_v5_database(path: Path) -> None:
    """A v5 file: everything through `animals.cage`, with **no** `config_json` /
    `params_hash`. Pinned as a literal like its siblings above.
    """
    write_v3_database(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN duration_minutes INTEGER")
        conn.execute("ALTER TABLE animals ADD COLUMN cage INTEGER")
        conn.execute("PRAGMA user_version = 5")
        conn.commit()
    finally:
        conn.close()


def test_v5_gains_the_run_parameter_columns(tmp_path: Path) -> None:
    """The task parameters a run used (`TASKS.md#profile-and-params-hashes`).

    Two columns in one migration, so this checks both -- a half-applied
    migration would leave finalization raising `OperationalError` on the second.
    """
    path = tmp_path / "ephymeris.db"
    write_v5_database(path)

    db = Database(path)
    db.connect()
    try:
        columns = table_columns(db.conn, "session_animal_runs")
        assert "config_json" in columns
        assert "params_hash" in columns
        # Writable, not merely present in the metadata.
        db.conn.execute(
            "UPDATE session_animal_runs SET config_json = ?, params_hash = ? WHERE id = 'r1'",
            ('{"odor_poke_hold": 500}', "abc123"),
        )
        row = db.conn.execute(
            "SELECT config_json, params_hash FROM session_animal_runs"
        ).fetchone()
        assert row["config_json"] == '{"odor_poke_hold": 500}'
        assert row["params_hash"] == "abc123"
    finally:
        db.close()

    assert user_version(path) == SCHEMA_VERSION


def test_upgrading_from_v5_leaves_old_runs_without_parameters(tmp_path: Path) -> None:
    """NULL on a pre-existing run is honest: it ran on firmware constants, so
    there are no per-run parameters to record. Defaulting it to `{}` instead
    would claim the run is comparable to a modern default-valued one."""
    path = tmp_path / "ephymeris.db"
    write_v5_database(path)

    db = Database(path)
    db.connect()
    try:
        row = db.conn.execute(
            "SELECT config_json, params_hash FROM session_animal_runs"
        ).fetchone()
    finally:
        db.close()

    assert row["config_json"] is None
    assert row["params_hash"] is None


def test_the_params_index_applies_after_the_migration(tmp_path: Path) -> None:
    """Indexes live in their own block applied AFTER migrations, and this is the
    case that proves why: `idx_runs_params` names a column that v6 is adding, so
    creating it with the rest of `SCHEMA` would fail on exactly the databases the
    migration exists for."""
    path = tmp_path / "ephymeris.db"
    write_v5_database(path)

    db = Database(path)
    db.connect()
    try:
        names = {
            row["name"]
            for row in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
    finally:
        db.close()

    assert "idx_runs_params" in names


def test_a_v2_database_gets_both_column_migrations(tmp_path: Path) -> None:
    """A lab machine two versions behind runs the chain in one startup."""
    path = tmp_path / "ephymeris.db"
    write_v2_database(path)

    db = Database(path)
    db.connect()
    try:
        runs = table_columns(db.conn, "session_animal_runs")
        assert "profile_hash" in runs
        assert "config_json" in runs and "params_hash" in runs
        assert "duration_minutes" in table_columns(db.conn, "sessions")
        assert "cage" in table_columns(db.conn, "animals")
        assert "file_mtime_ns" in table_columns(db.conn, "adopted_runs")
    finally:
        db.close()

    assert user_version(path) == SCHEMA_VERSION


# --- the real v6 -> v7 migration ------------------------------------------


def write_v6_database(path: Path) -> None:
    """A v6 file: everything through the run-parameter columns, with an
    `adopted_runs` table that carries **no** stat columns. Pinned as a literal
    like its siblings above — importing today's `SCHEMA` would test this code
    against itself."""
    write_v5_database(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("ALTER TABLE session_animal_runs ADD COLUMN config_json TEXT")
        conn.execute("ALTER TABLE session_animal_runs ADD COLUMN params_hash TEXT")
        conn.execute(
            """
            CREATE TABLE adopted_runs (
                id             TEXT PRIMARY KEY,
                cohort_id      TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
                animal_id      TEXT NOT NULL,
                file_path      TEXT NOT NULL,
                prefix_name    TEXT NOT NULL,
                session_number TEXT NOT NULL,
                date           TEXT,
                started_at     TEXT NOT NULL,
                sketch_name    TEXT,
                sketch_path    TEXT,
                adopted_at     TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO adopted_runs (id, cohort_id, animal_id, file_path,"
            " prefix_name, session_number, date, started_at, sketch_name,"
            " sketch_path, adopted_at) VALUES"
            " ('adopted:abc', 'c1', 'a1', '/data/x.json', '2O-Bdisc', '01',"
            "  '2026-06-16', '2026-06-16T12:00:22', 'GRGL', NULL, '2026-06-16T13:00:00')"
        )
        conn.execute("PRAGMA user_version = 6")
        conn.commit()
    finally:
        conn.close()


def test_v6_gains_the_adoption_stat_columns(tmp_path: Path) -> None:
    """The freshness key that lets a rescan skip a file it already read
    (`DATA.md#carrying-adoptions-forward`). Two columns in one migration, so both are checked."""
    path = tmp_path / "ephymeris.db"
    write_v6_database(path)

    db = Database(path)
    db.connect()
    try:
        columns = table_columns(db.conn, "adopted_runs")
        assert "file_mtime_ns" in columns
        assert "file_size" in columns
        # Writable, not merely present in the metadata.
        db.conn.execute(
            "UPDATE adopted_runs SET file_mtime_ns = ?, file_size = ?"
            " WHERE id = 'adopted:abc'",
            (1234567890, 4096),
        )
        row = db.conn.execute(
            "SELECT file_mtime_ns, file_size FROM adopted_runs"
        ).fetchone()
        assert (row["file_mtime_ns"], row["file_size"]) == (1234567890, 4096)
    finally:
        db.close()

    assert user_version(path) == SCHEMA_VERSION


def test_an_adoption_from_before_v7_is_never_treated_as_fresh(tmp_path: Path) -> None:
    """NULL is the safe direction: a row with no recorded stat cannot be
    recognised as unchanged, so the first rescan after the migration re-reads
    the file exactly as it always did and records a stat on the way through.
    Defaulting these to 0 instead would carry every old row forward on a
    freshness claim nothing ever checked."""
    path = tmp_path / "ephymeris.db"
    write_v6_database(path)

    db = Database(path)
    db.connect()
    try:
        row = db.conn.execute(
            "SELECT file_mtime_ns, file_size FROM adopted_runs"
        ).fetchone()
    finally:
        db.close()

    assert row["file_mtime_ns"] is None
    assert row["file_size"] is None


# --- the real v7 -> v8 migration ------------------------------------------


def write_v7_database(path: Path) -> None:
    """A v7 file, carrying a `run_metrics_cache` in its **pre-v8** shape.

    The cache table has to be spelled out here rather than left to `SCHEMA`:
    `CREATE TABLE IF NOT EXISTS` would build it with `params_hash` already on
    it, and the migration this exercises would then be a no-op against a table
    that never lacked the column — which is precisely the class of database it
    exists for.
    """
    write_v6_database(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("ALTER TABLE adopted_runs ADD COLUMN file_mtime_ns INTEGER")
        conn.execute("ALTER TABLE adopted_runs ADD COLUMN file_size INTEGER")
        conn.execute(
            """
            CREATE TABLE run_metrics_cache (
                run_id         TEXT PRIMARY KEY,
                file_path      TEXT NOT NULL,
                file_mtime_ns  INTEGER,
                file_size      INTEGER,
                profile_hash   TEXT,
                profile_source TEXT NOT NULL,
                codec_version  INTEGER NOT NULL,
                computed_at    TEXT NOT NULL,
                status         TEXT NOT NULL,
                detail         TEXT,
                summary_json   TEXT NOT NULL
            )
            """
        )
        # Two rows, because v8 treats them differently: one scored from a
        # profile that resolved (its digest is in `profile_hash` and survives),
        # one scored from an inferred profile (whose digest was recorded
        # nowhere, which is what the migration repairs).
        conn.execute(
            "INSERT INTO run_metrics_cache (run_id, file_path, profile_hash,"
            " profile_source, codec_version, computed_at, status, summary_json)"
            " VALUES ('r1', '/data/r1.json', 'aaaabbbbccccdddd', 'snapshot', 6,"
            "  '2026-06-16T13:00:00', 'ok', '{}')"
        )
        conn.execute(
            "INSERT INTO run_metrics_cache (run_id, file_path, profile_source,"
            " codec_version, computed_at, status, summary_json) VALUES"
            " ('adopted:abc', '/data/x.json', 'inferred', 6,"
            "  '2026-06-16T13:00:00', 'ok', '{}')"
        )
        conn.execute("PRAGMA user_version = 7")
        conn.commit()
    finally:
        conn.close()


def test_v7_gains_the_recorded_run_columns(tmp_path: Path) -> None:
    """What a run's own file records (`DATA.md#the-embedded-task-profile`,
    `DATA.md#which-profile-decodes-a-run`). Two columns in one
    migration, so both are checked — a half-applied one would leave the second
    raising `OperationalError` on the next indexing pass."""
    path = tmp_path / "ephymeris.db"
    write_v7_database(path)

    db = Database(path)
    db.connect()
    try:
        columns = table_columns(db.conn, "run_metrics_cache")
        assert "params_hash" in columns
        assert "scored_profile_hash" in columns
        # Writable, not merely present in the metadata.
        db.conn.execute(
            "UPDATE run_metrics_cache SET params_hash = ?, scored_profile_hash = ?"
            " WHERE run_id = 'r1'",
            ("deadbeefdeadbeef", "1111222233334444"),
        )
        row = db.conn.execute(
            "SELECT params_hash, scored_profile_hash FROM run_metrics_cache"
            " WHERE run_id = 'r1'"
        ).fetchone()
        assert row["params_hash"] == "deadbeefdeadbeef"
        assert row["scored_profile_hash"] == "1111222233334444"
    finally:
        db.close()

    assert user_version(path) == SCHEMA_VERSION


def test_a_resolved_cache_row_survives_the_migration(tmp_path: Path) -> None:
    """It is a pure cache, so a NULL new column costs only a recomputation —
    but a row that still answers correctly must not be dropped: clearing the
    cache wholesale would re-read every file in the archive on the first
    dashboard open after an update."""
    path = tmp_path / "ephymeris.db"
    write_v7_database(path)

    db = Database(path)
    db.connect()
    try:
        row = db.conn.execute(
            "SELECT profile_hash, scored_profile_hash, params_hash"
            " FROM run_metrics_cache WHERE run_id = 'r1'"
        ).fetchone()
    finally:
        db.close()

    assert row is not None, "a row whose digest resolved still answers correctly"
    assert row["profile_hash"] == "aaaabbbbccccdddd"
    assert row["scored_profile_hash"] is None
    assert row["params_hash"] is None


def test_an_inferred_cache_row_is_dropped_so_it_recomputes(tmp_path: Path) -> None:
    """The one thing this migration deletes, and why.

    An inferred row recorded its scoring digest nowhere — `profile_hash` holds
    what *resolution* reached, which for those rows is NULL by definition. So
    it served a hash on the pass that computed it and NULL forever after,
    dropping the run out of its own profile group. The new column fixes that
    only for rows that recompute, and this row never would: its freshness key
    still matches. Deleting exactly these un-sticks it, at the cost of
    re-reading those files once.
    """
    path = tmp_path / "ephymeris.db"
    write_v7_database(path)

    db = Database(path)
    db.connect()
    try:
        rows = db.conn.execute("SELECT run_id FROM run_metrics_cache").fetchall()
    finally:
        db.close()

    assert [row["run_id"] for row in rows] == ["r1"]


# --- the downgrade case ---------------------------------------------------


def test_a_newer_database_still_opens(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Opened by an older build. Every change is additive, so continuing is safe.

    Refusing to start would strand a lab machine that merely ran an older
    installer; the error in the log is what makes it diagnosable.
    """
    path = tmp_path / "ephymeris.db"
    write_v1_database(path, version=SCHEMA_VERSION + 5)

    db = Database(path)
    with caplog.at_level("ERROR"):
        db.connect()
    try:
        assert db.conn.execute("SELECT COUNT(*) FROM cohorts").fetchone()[0] == 1
    finally:
        db.close()

    assert any("newer version" in record.getMessage() for record in caplog.records)


def test_a_newer_database_does_not_run_migrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[str] = []
    monkeypatch.setitem(MIGRATIONS, SCHEMA_VERSION, lambda conn: ran.append("x"))

    path = tmp_path / "ephymeris.db"
    write_v1_database(path, version=SCHEMA_VERSION + 5)
    db = Database(path)
    db.connect()
    db.close()

    assert ran == []


# --- the real v8 -> v9 migration ------------------------------------------


def write_v8_database(path: Path) -> None:
    """A v8 file: everything through the recorded-run columns, with a `cohorts`
    table that carries **no** `appearance_json`.

    Built from the v7 fixture rather than from today's `SCHEMA`, like every
    fixture above it: `CREATE TABLE IF NOT EXISTS` would build `cohorts` with
    the column already on it, and the migration this exercises would then be a
    no-op against a table that never lacked it — precisely the class of database
    it exists for.
    """
    write_v7_database(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("ALTER TABLE run_metrics_cache ADD COLUMN params_hash TEXT")
        conn.execute(
            "ALTER TABLE run_metrics_cache ADD COLUMN scored_profile_hash TEXT"
        )
        conn.execute("PRAGMA user_version = 8")
        conn.commit()
    finally:
        conn.close()


def test_v8_gains_the_cohort_appearance_column(tmp_path: Path) -> None:
    """The operator's tuning of a cohort's world (`ARCHITECTURE.md#cohort-browser`).

    A column on `cohorts` rather than a table, so `CREATE TABLE IF NOT EXISTS`
    does nothing for it: without the registered migration it would appear only
    on databases created after this build, while `user_version` was stamped to 9
    regardless — and the first save of an appearance on a lab machine would
    raise `OperationalError` mid-run.
    """
    path = tmp_path / "ephymeris.db"
    write_v8_database(path)

    db = Database(path)
    db.connect()
    try:
        assert "appearance_json" in table_columns(db.conn, "cohorts")
        # Writable, not merely present in the metadata.
        db.conn.execute(
            "UPDATE cohorts SET appearance_json = ? WHERE id = 'c1'",
            ('{"type": "gas", "hue": 41, "ring": true, "seed": 7734}',),
        )
        row = db.conn.execute(
            "SELECT appearance_json FROM cohorts WHERE id = 'c1'"
        ).fetchone()
        assert row["appearance_json"].startswith('{"type": "gas"')
    finally:
        db.close()

    assert user_version(path) == SCHEMA_VERSION


def test_a_cohort_from_before_v9_has_no_stored_appearance(tmp_path: Path) -> None:
    """NULL is the answer, not a gap to backfill.

    An absent appearance means "derive the world from the cohort's id", which is
    what every cohort did before this column and what the client still does when
    it reads NULL. Writing a derived record in during the migration would freeze
    each existing cohort against every later correction to the palette or the
    default type, for no gain — and would make a cohort that had never been
    touched indistinguishable from one deliberately tuned to today's defaults.
    """
    path = tmp_path / "ephymeris.db"
    write_v8_database(path)

    db = Database(path)
    db.connect()
    try:
        row = db.conn.execute(
            "SELECT name, appearance_json FROM cohorts WHERE id = 'c1'"
        ).fetchone()
        assert row["name"] == "Batch A"          # the row survived
        assert row["appearance_json"] is None    # and carries no world
    finally:
        db.close()


# --- backup amplification -------------------------------------------------


def test_startup_commits_at_most_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each commit marks the database dirty for backup (`DATA.md#the-database-copy`).

    A migration committing per step would trigger repeated whole-file copies to
    a possibly-networked target before the app has finished starting.
    """
    path = tmp_path / "ephymeris.db"
    write_v1_database(path)

    commits: list[int] = []
    db = Database(path)
    db.on_commit(lambda: commits.append(1))

    def noisy(conn: sqlite3.Connection) -> None:
        add_column(conn, "cohorts", "a", "TEXT")
        add_column(conn, "cohorts", "b", "TEXT")

    # `monkeypatch.setitem`, NOT a bare assignment with a `pop` in the finally.
    # The pop this replaced deleted whatever real migration was registered at
    # SCHEMA_VERSION -- permanently, for every test that ran after it in the
    # same process. It was invisible for as long as no later test exercised
    # that migration, and the first one that did failed here rather than where
    # the damage was done.
    monkeypatch.setitem(MIGRATIONS, SCHEMA_VERSION, noisy)
    try:
        db.connect()
    finally:
        db.close()

    assert len(commits) <= 1, f"startup committed {len(commits)} times"


# --- the real v9 -> v10 migration -----------------------------------------


def write_v9_database(path: Path) -> None:
    """A v9 file: a `sessions` table with **no** `recording_json`.

    Built up from the v8 fixture for the reason every fixture here is: today's
    `SCHEMA` would create `sessions` with the column already on it, and the
    migration would be exercised against a table that never lacked it.
    """
    write_v8_database(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("ALTER TABLE cohorts ADD COLUMN appearance_json TEXT")
        conn.execute(
            "INSERT INTO sessions (id, cohort_id, prefix_id, prefix_name, session_number,"
            " date, started_at, status, folder_path) VALUES"
            " ('s-old', 'c1', 'p1', 'GRGL', '7', '2026-09-01', '2026-09-01T09:00:00+00:00',"
            " 'completed', 'C:/data/GRGL/GRGL_7_2026-09-01')"
        )
        conn.execute("PRAGMA user_version = 9")
        conn.commit()
    finally:
        conn.close()


def test_v9_gains_the_session_recording_column(tmp_path: Path) -> None:
    """Whether a session is also an Intan recording (`RECORDING.md#what-is-written`).

    A column, so `CREATE TABLE IF NOT EXISTS` does nothing for it. Without the
    registered migration the first "Start Recording" on a lab machine would
    raise `OperationalError` at `sessions.create` -- on exactly the databases
    that hold the lab's history, and on no developer's fresh one.
    """
    from ephymeris_sidecar.sessions.repository import SessionRepository

    path = tmp_path / "ephymeris.db"
    write_v9_database(path)

    db = Database(path)
    db.connect()
    try:
        assert "recording_json" in table_columns(db.conn, "sessions")
        repo = SessionRepository(db)
        # A session from before the column is behavior-only: NULL, not {}.
        assert repo.get_session("s-old").recording is None
        assert repo.get_session("s-old").to_json()["recording"] is None
        # ...and the column is writable, not merely present in the metadata.
        updated = repo.set_recording("s-old", {"runs": [{"groupId": "g1"}]})
        assert updated.recording == {"runs": [{"groupId": "g1"}]}
    finally:
        db.close()

    assert user_version(path) == SCHEMA_VERSION

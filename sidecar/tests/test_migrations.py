"""Schema migration — `analytics.md` §10.1.

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
        assert "profile_hash" in table_columns(db.conn, "session_animal_runs")
        assert "duration_minutes" in table_columns(db.conn, "sessions")
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
    """The first change that actually needed this branch (`analytics.md` §10.2).

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
    """The per-box time limit (`starting-a-session.md` §2.3)."""
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


def test_a_v2_database_gets_both_column_migrations(tmp_path: Path) -> None:
    """A lab machine two versions behind runs the chain in one startup."""
    path = tmp_path / "ephymeris.db"
    write_v2_database(path)

    db = Database(path)
    db.connect()
    try:
        assert "profile_hash" in table_columns(db.conn, "session_animal_runs")
        assert "duration_minutes" in table_columns(db.conn, "sessions")
    finally:
        db.close()

    assert user_version(path) == SCHEMA_VERSION


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


# --- backup amplification -------------------------------------------------


def test_startup_commits_at_most_once(tmp_path: Path) -> None:
    """Each commit marks the database dirty for backup (`data-saving.md` §8.3).

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

    MIGRATIONS[SCHEMA_VERSION] = noisy
    try:
        db.connect()
    finally:
        MIGRATIONS.pop(SCHEMA_VERSION, None)
        db.close()

    assert len(commits) <= 1, f"startup committed {len(commits)} times"

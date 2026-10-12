"""The database unit of work — `cohorts/db.py`'s `write` / `read`,
`DATA.md#transactions`.

Over a real SQLite file. Committed state is read through a second, plain
connection: it sees only what a commit made durable, which is the question
every test here is asking.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics.repository import AnalyticsRepository
from ephymeris_sidecar.cohorts.db import Database, NestedWrite, WriteInProgress
from ephymeris_sidecar.tasks.profile import parse_profile


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "ephymeris.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


def committed(db: Database, sql: str) -> list[tuple]:
    """What another connection would read: committed rows only."""
    conn = sqlite3.connect(db.path)
    try:
        return [tuple(row) for row in conn.execute(sql)]
    finally:
        conn.close()


def prefixes(db: Database) -> list[str]:
    return [name for (name,) in committed(db, "SELECT name FROM prefixes ORDER BY name")]


def add_prefix(q, name: str) -> None:  # noqa: ANN001
    q.execute("INSERT INTO prefixes (id, name) VALUES (?, ?)", (name, name))


def commits_of(db: Database) -> list[int]:
    seen: list[int] = []
    db.on_commit(lambda: seen.append(1))
    return seen


# --- commit and rollback ------------------------------------------------------


def test_a_unit_commits_when_it_ends(db: Database) -> None:
    with db.write() as tx:
        add_prefix(tx, "a")
        add_prefix(tx, "b")
        assert prefixes(db) == [], "nothing is visible until the unit ends"
    assert prefixes(db) == ["a", "b"]
    assert not db.conn.in_transaction


def test_a_unit_that_raises_leaves_nothing_behind(db: Database) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        with db.write() as tx:
            add_prefix(tx, "a")
            raise RuntimeError("boom")
    assert prefixes(db) == []
    assert not db.conn.in_transaction


def test_a_rollback_undoes_only_its_own_work(db: Database) -> None:
    """B14's guarantee: a writer's failed unit leaves another's committed
    unit alone."""
    digest = AnalyticsRepository(db).remember_profile(parse_profile({"taskName": "Kept"}))

    with pytest.raises(sqlite3.IntegrityError):
        with db.write() as tx:
            add_prefix(tx, "a")
            add_prefix(tx, "a")  # the name is unique

    assert prefixes(db) == []
    assert committed(db, "SELECT hash FROM task_profiles") == [(digest,)]


def leave_a_write_open(db: Database) -> None:
    """A write begun outside any unit of work, as only a bug could now."""
    db._conn.execute("BEGIN")
    db._conn.execute("INSERT INTO prefixes (id, name) VALUES ('open', 'open')")


def test_a_unit_that_commits_over_a_write_left_open_makes_both_durable(db: Database) -> None:
    """As any commit on the one connection does, and it says so."""
    leave_a_write_open(db)
    seen = commits_of(db)
    with db.write() as tx:
        add_prefix(tx, "a")
    assert prefixes(db) == ["a", "open"]
    assert seen == [1]
    assert not db.conn.in_transaction


# --- one unit, shared ---------------------------------------------------------


def test_a_method_given_the_unit_joins_it_and_commits_nothing(db: Database) -> None:
    with db.write() as tx:
        with db.write(tx) as joined:
            assert joined is tx
            add_prefix(joined, "a")
        assert prefixes(db) == [], "only the unit's opener commits"
        add_prefix(tx, "b")
    assert prefixes(db) == ["a", "b"]


def test_a_failure_in_a_joined_method_undoes_the_whole_unit(db: Database) -> None:
    with pytest.raises(RuntimeError):
        with db.write() as tx:
            add_prefix(tx, "a")
            with db.write(tx) as joined:
                add_prefix(joined, "b")
                raise RuntimeError("inner")
    assert prefixes(db) == []


def test_a_nested_unit_is_refused(db: Database) -> None:
    """Rather than a deadlock on the lock, or a commit that isn't the outermost."""
    with db.write() as tx:
        add_prefix(tx, "a")
        with pytest.raises(NestedWrite):
            with db.write():
                pass
    assert prefixes(db) == ["a"]


def test_a_unit_is_joined_only_on_its_own_thread_while_it_is_open(db: Database) -> None:
    errors: list[BaseException] = []
    with db.write() as tx:

        def join() -> None:
            try:
                with db.write(tx):
                    pass
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        worker = threading.Thread(target=join)
        worker.start()
        worker.join(5)
    assert len(errors) == 1 and isinstance(errors[0], NestedWrite)

    with pytest.raises(NestedWrite):
        with db.write(tx):
            pass


# --- reads --------------------------------------------------------------------


def test_a_read_inside_a_unit_sees_the_units_own_rows(db: Database) -> None:
    with db.write() as tx:
        add_prefix(tx, "a")
        with db.read() as q:
            assert [r[0] for r in q.execute("SELECT name FROM prefixes")] == ["a"]


def test_a_read_holds_the_lock(db: Database) -> None:
    with db.read() as q:
        assert db.lock.locked()
        q.execute("SELECT 1")
    assert not db.lock.locked()


# --- what commits announce (DATA.md#the-database-copy) ------------------------


def test_the_database_hook_fires_once_per_unit_after_it_commits(db: Database) -> None:
    seen: list[bool] = []
    db.on_commit(lambda: seen.append(bool(prefixes(db))))
    with db.write() as tx:
        add_prefix(tx, "a")
        add_prefix(tx, "b")
        assert seen == []
    assert seen == [True], "once, and the rows were durable when it fired"


def test_a_rolled_back_unit_announces_nothing(db: Database) -> None:
    seen = commits_of(db)
    with pytest.raises(RuntimeError):
        with db.write() as tx:
            add_prefix(tx, "a")
            raise RuntimeError
    assert seen == []


def test_a_unit_that_changed_nothing_announces_nothing(db: Database) -> None:
    """A backup copy of an unchanged file is a whole-file copy to a possibly
    networked share for nothing."""
    with db.write() as tx:
        add_prefix(tx, "a")
    seen = commits_of(db)
    with db.write() as tx:
        tx.execute("INSERT OR IGNORE INTO prefixes (id, name) VALUES ('a', 'a')")
        tx.execute("SELECT * FROM prefixes").fetchall()
    assert seen == []


def test_a_units_own_follow_up_runs_once_after_the_lock_is_free(db: Database) -> None:
    ran: list[list[str]] = []

    def follow_up() -> None:
        assert not db.lock.locked()
        with db.read() as q:  # free to use the database
            ran.append([r[0] for r in q.execute("SELECT name FROM prefixes")])

    with db.write() as tx:
        add_prefix(tx, "a")
        tx.on_commit(follow_up)
        assert ran == []
    assert ran == [["a"]]

    with pytest.raises(RuntimeError):
        with db.write() as tx:
            tx.on_commit(follow_up)
            raise RuntimeError
    assert ran == [["a"]], "dropped with the unit"


# --- the snapshot (DATA.md#the-database-copy) ---------------------------------


def test_a_snapshot_refuses_a_write_left_open_rather_than_waiting_on_it(
    db: Database, tmp_path: Path
) -> None:
    """`Connection.backup` retries a busy source forever, and here it would
    do so holding the lock that every way out of the write needs (#55)."""
    leave_a_write_open(db)
    done = threading.Event()
    raised: list[BaseException] = []

    def snapshot() -> None:
        try:
            db.snapshot_to(tmp_path / "copy.db")
        except BaseException as exc:  # noqa: BLE001
            raised.append(exc)
        done.set()

    threading.Thread(target=snapshot, daemon=True).start()
    if not done.wait(3):
        db.conn.rollback()  # free the stuck thread, which holds the lock
        pytest.fail("the snapshot waited on the open write")
    assert len(raised) == 1 and isinstance(raised[0], WriteInProgress)


def test_a_snapshot_inside_a_unit_is_refused(db: Database, tmp_path: Path) -> None:
    with db.write() as tx:
        add_prefix(tx, "a")
        with pytest.raises(WriteInProgress):
            db.snapshot_to(tmp_path / "copy.db")

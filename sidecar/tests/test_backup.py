"""Backup Directory mirroring — `data.md` §7.

Two things are worth stating about what these tests are for, because the
mechanism is easy to test shallowly:

* The **layout** tests exist because mirror paths can't be derived from
  `dataDirectory` — a relocated cohort folder isn't under it — so the anchoring
  rule is load-bearing rather than cosmetic.
* The **isolation** tests exist because the entire design constraint is that a
  slow or dead backup target may never affect a session. A mirror that works
  but blocks finalization would pass a naive "did the file appear" test and
  still be wrong.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from ephymeris_sidecar.backup.manager import (
    DB_MIRROR_NAME,
    DB_SNAPSHOT_DIR,
    DB_SNAPSHOT_KEEP,
    BackupManager,
    BackupNotConfigured,
    copy_if_stale,
)
from ephymeris_sidecar.backup.paths import MirrorLayout, mirror_segments
from ephymeris_sidecar.cohorts.db import Database


# --- §8 mirror layout ------------------------------------------------------


def resolve_mirror_path(source: Path, roots: list[Path], backup_root: Path) -> Path | None:
    return MirrorLayout(roots, backup_root).resolve(source)


def test_a_file_mirrors_under_its_cohort_folder_basename(tmp_path: Path) -> None:
    root = tmp_path / "data" / "Batch A"
    source = root / "2O-Bdisc" / "2O-Bdisc_25_2026-07-22" / "behavior.tsv" / "remy1.tsv"
    backup = tmp_path / "mirror"

    assert resolve_mirror_path(source, [root], backup) == (
        backup / "Batch A" / "2O-Bdisc" / "2O-Bdisc_25_2026-07-22" / "behavior.tsv" / "remy1.tsv"
    )


def test_a_relocated_cohort_folder_still_resolves(tmp_path: Path) -> None:
    """The reason the layout is anchored on the cohort folder at all.

    `cohorts.setDataFolder` can put a cohort anywhere, including somewhere with
    no relationship to `Settings.dataDirectory` — so subtracting the data
    directory from the source path is not an option (§8).
    """
    root = tmp_path / "somewhere" / "else" / "Batch A"
    source = root / "prefix" / "file.tsv"
    assert resolve_mirror_path(source, [root], tmp_path / "mirror") == (
        tmp_path / "mirror" / "Batch A" / "prefix" / "file.tsv"
    )


def test_a_file_outside_every_cohort_folder_is_not_mirrored(tmp_path: Path) -> None:
    """Nothing outside a cohort's own data folder is ours to place."""
    assert (
        resolve_mirror_path(
            tmp_path / "unrelated" / "notes.txt",
            [tmp_path / "data" / "Batch A"],
            tmp_path / "mirror",
        )
        is None
    )


def test_colliding_basenames_are_disambiguated_stably(tmp_path: Path) -> None:
    first = tmp_path / "drive-one" / "Batch A"
    second = tmp_path / "drive-two" / "Batch A"

    segments = mirror_segments([first, second])
    assert segments[first.resolve()] != segments[second.resolve()]
    # Both suffixed, so the layout doesn't depend on enumeration order.
    assert all(name.startswith("Batch A-") for name in segments.values())
    # And it's deterministic across calls.
    assert mirror_segments([second, first]) == segments


def test_a_lone_cohort_folder_is_not_suffixed(tmp_path: Path) -> None:
    root = tmp_path / "data" / "Batch A"
    assert mirror_segments([root]) == {root.resolve(): "Batch A"}


def test_the_longest_matching_cohort_folder_wins(tmp_path: Path) -> None:
    outer = tmp_path / "Outer"
    inner = outer / "Inner"
    source = inner / "file.tsv"
    assert resolve_mirror_path(source, [outer, inner], tmp_path / "m") == (
        tmp_path / "m" / "Inner" / "file.tsv"
    )


# --- copy semantics --------------------------------------------------------


def test_copy_is_skipped_when_the_mirror_is_already_current(tmp_path: Path) -> None:
    source = tmp_path / "a.tsv"
    source.write_text("221\t0\n", encoding="utf-8")
    destination = tmp_path / "mirror" / "a.tsv"

    assert copy_if_stale(source, destination) is True
    assert copy_if_stale(source, destination) is False
    assert destination.read_text(encoding="utf-8") == "221\t0\n"


def test_a_growing_tsv_is_re_copied_whole(tmp_path: Path) -> None:
    """Whole-file, not incremental append.

    A partial append to a slow or networked target could leave the mirrored
    write-ahead log torn; copying whole makes that impossible, and the files
    are tens of kilobytes (§8).
    """
    source = tmp_path / "a.tsv"
    source.write_text("221\t0\n", encoding="utf-8")
    destination = tmp_path / "mirror" / "a.tsv"
    copy_if_stale(source, destination)

    source.write_text("221\t0\n222\t1000\n", encoding="utf-8")
    assert copy_if_stale(source, destination) is True
    assert destination.read_text(encoding="utf-8") == "221\t0\n222\t1000\n"


def test_a_vanished_source_is_not_an_error(tmp_path: Path) -> None:
    """The mirror preserves what it has; it doesn't chase deletions (§8)."""
    assert copy_if_stale(tmp_path / "gone.tsv", tmp_path / "mirror" / "gone.tsv") is False


def test_no_part_file_is_left_behind(tmp_path: Path) -> None:
    source = tmp_path / "a.tsv"
    source.write_text("x", encoding="utf-8")
    destination = tmp_path / "mirror" / "a.tsv"
    copy_if_stale(source, destination)
    assert list(destination.parent.iterdir()) == [destination]


# --- the manager -----------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "app" / "ephymeris.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


def make_manager(db: Database, roots: list[str], **kwargs) -> BackupManager:
    async def broadcast(_message: dict) -> None:
        return None

    return BackupManager(
        loop=asyncio.get_event_loop(),
        db=db,
        cohort_roots=lambda: roots,
        broadcast=broadcast,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_nothing_is_mirrored_without_a_backup_directory(
    db: Database, tmp_path: Path
) -> None:
    root = tmp_path / "Batch A"
    root.mkdir()
    (root / "a.tsv").write_text("221\t0\n", encoding="utf-8")

    manager = make_manager(db, [str(root)])
    manager.enqueue(root / "a.tsv")
    await manager._pass()

    assert not (tmp_path / "mirror").exists()
    assert manager.status()["configured"] is False
    assert manager.status()["state"] == "disabled"


@pytest.mark.asyncio
async def test_a_queued_file_is_mirrored_on_the_next_pass(
    db: Database, tmp_path: Path
) -> None:
    root = tmp_path / "Batch A"
    root.mkdir()
    (root / "a.json").write_text("{}", encoding="utf-8")
    backup = tmp_path / "mirror"

    manager = make_manager(db, [str(root)])
    await manager.configure(str(backup))
    manager.enqueue(root / "a.json")
    await manager._pass()

    assert (backup / "Batch A" / "a.json").read_text(encoding="utf-8") == "{}"
    assert manager.status()["state"] == "ok"
    assert manager.status()["pending"] == 0


@pytest.mark.asyncio
async def test_a_tracked_file_is_mirrored_on_every_pass(
    db: Database, tmp_path: Path
) -> None:
    root = tmp_path / "Batch A"
    root.mkdir()
    live = root / "live.tsv"
    live.write_text("221\t0\n", encoding="utf-8")
    backup = tmp_path / "mirror"

    manager = make_manager(db, [str(root)])
    await manager.configure(str(backup))
    manager.track(live)

    await manager._pass()
    assert (backup / "Batch A" / "live.tsv").read_text(encoding="utf-8") == "221\t0\n"

    live.write_text("221\t0\n222\t1000\n", encoding="utf-8")
    await manager._pass()
    assert (backup / "Batch A" / "live.tsv").read_text(encoding="utf-8") == "221\t0\n222\t1000\n"

    manager.untrack(live)
    live.write_text("221\t0\n222\t1000\n223\t2000\n", encoding="utf-8")
    await manager._pass()
    # Untracked: the mirror keeps what it had rather than following further.
    assert (backup / "Batch A" / "live.tsv").read_text(encoding="utf-8") == "221\t0\n222\t1000\n"


@pytest.mark.asyncio
async def test_an_unwritable_target_reports_failed_and_keeps_the_queue(
    db: Database, tmp_path: Path
) -> None:
    """A dead backup share must be visible, and must not lose the file (§8)."""
    root = tmp_path / "Batch A"
    root.mkdir()
    (root / "a.json").write_text("{}", encoding="utf-8")

    # A *file* where the backup directory should be: every copy under it fails.
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")

    manager = make_manager(db, [str(root)])
    await manager.configure(str(blocker))
    manager.enqueue(root / "a.json")
    await manager._pass()

    status = manager.status()
    assert status["state"] == "failed"
    assert status["lastError"]
    # Requeued rather than dropped — a finalized file isn't lost to a blip.
    assert status["pending"] == 1


@pytest.mark.asyncio
async def test_a_recovered_target_clears_the_failure(db: Database, tmp_path: Path) -> None:
    root = tmp_path / "Batch A"
    root.mkdir()
    (root / "a.json").write_text("{}", encoding="utf-8")
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")

    manager = make_manager(db, [str(root)])
    await manager.configure(str(blocker))
    manager.enqueue(root / "a.json")
    await manager._pass()
    assert manager.status()["state"] == "failed"

    await manager.configure(str(tmp_path / "mirror"))
    await manager._pass()
    status = manager.status()
    assert status["state"] == "ok"
    assert status["lastError"] is None


# --- §8 the database backup ------------------------------------------------


@pytest.mark.asyncio
async def test_the_database_is_backed_up_and_is_a_readable_copy(
    db: Database, tmp_path: Path
) -> None:
    db.conn.execute(
        "INSERT INTO prefixes (id, name) VALUES ('p1', '2O-Bdisc')"
    )
    db.conn.commit()
    backup = tmp_path / "mirror"

    manager = make_manager(db, [], db_debounce=0.0)
    await manager.configure(str(backup))
    await manager._pass()

    mirrored = backup / DB_MIRROR_NAME
    assert mirrored.is_file()
    # Not just present — actually a usable database.
    conn = sqlite3.connect(mirrored)
    try:
        assert conn.execute("SELECT name FROM prefixes").fetchone()[0] == "2O-Bdisc"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_every_commit_marks_the_database_dirty(db: Database, tmp_path: Path) -> None:
    """The trigger is "the database changed", not "a cohort changed" (§8).

    `session_animal_runs` is written at finalization during an unattended
    overnight run and is not a cohort edit by any reading — hooking commit
    itself means no write path can be forgotten.
    """
    manager = make_manager(db, [], db_debounce=0.0)
    db.on_commit(manager.mark_db_dirty)
    await manager.configure(str(tmp_path / "mirror"))
    await manager._pass()

    (tmp_path / "mirror" / DB_MIRROR_NAME).unlink()
    await manager._pass()
    # Clean: nothing committed since, so nothing was re-copied.
    assert not (tmp_path / "mirror" / DB_MIRROR_NAME).exists()

    db.conn.execute("INSERT INTO prefixes (id, name) VALUES ('p2', 'x')")
    db.conn.commit()
    await manager._pass()
    assert (tmp_path / "mirror" / DB_MIRROR_NAME).is_file()


@pytest.mark.asyncio
async def test_the_database_backup_is_debounced(db: Database, tmp_path: Path) -> None:
    """Editing a roster commits many times a second; each mustn't hit the share."""
    manager = make_manager(db, [], db_debounce=3600.0)
    db.on_commit(manager.mark_db_dirty)
    await manager.configure(str(tmp_path / "mirror"))

    db.conn.execute("INSERT INTO prefixes (id, name) VALUES ('p3', 'y')")
    db.conn.commit()
    await manager._pass()

    assert not (tmp_path / "mirror" / DB_MIRROR_NAME).exists()


@pytest.mark.asyncio
async def test_a_dated_snapshot_is_kept_alongside_the_live_mirror(
    db: Database, tmp_path: Path
) -> None:
    """The live mirror alone would reproduce an accidental deletion (§8)."""
    backup = tmp_path / "mirror"
    manager = make_manager(db, [], db_debounce=0.0)
    await manager.configure(str(backup))
    await manager._pass()

    snapshots = sorted((backup / DB_SNAPSHOT_DIR).glob("ephymeris_*.db"))
    assert len(snapshots) == 1
    assert snapshots[0].is_file()


@pytest.mark.asyncio
async def test_the_days_first_snapshot_wins(db: Database, tmp_path: Path) -> None:
    """A later backup must not overwrite the state a user may be undoing."""
    backup = tmp_path / "mirror"
    manager = make_manager(db, [], db_debounce=0.0)
    await manager.configure(str(backup))
    await manager._pass()

    snapshot = next((backup / DB_SNAPSHOT_DIR).glob("ephymeris_*.db"))
    snapshot.write_bytes(b"the original day's copy")

    db.conn.execute("INSERT INTO prefixes (id, name) VALUES ('p4', 'z')")
    db.conn.commit()
    await manager._pass()

    assert snapshot.read_bytes() == b"the original day's copy"
    # The live mirror did move on, though — it's the snapshot that's frozen.
    assert (backup / DB_MIRROR_NAME).stat().st_size > len(b"the original day's copy")


@pytest.mark.asyncio
async def test_old_snapshots_are_pruned_to_the_retention_window(
    db: Database, tmp_path: Path
) -> None:
    backup = tmp_path / "mirror"
    folder = backup / DB_SNAPSHOT_DIR
    folder.mkdir(parents=True)
    # Names are ISO-dated, so a plain sort is a chronological sort — a payoff
    # of the same date decision that fixed the session folders.
    for day in range(1, DB_SNAPSHOT_KEEP + 6):
        (folder / f"ephymeris_2026-06-{day:02d}.db").write_bytes(b"old")

    manager = make_manager(db, [], db_debounce=0.0)
    await manager.configure(str(backup))
    await manager._pass()

    remaining = sorted(folder.glob("ephymeris_*.db"))
    assert len(remaining) == DB_SNAPSHOT_KEEP
    # The oldest went, the newest stayed.
    assert not (folder / "ephymeris_2026-06-01.db").exists()


# --- §8 explicit sync ------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_now_refuses_without_a_directory(db: Database) -> None:
    manager = make_manager(db, [])
    with pytest.raises(BackupNotConfigured):
        await manager.sync_now()


@pytest.mark.asyncio
async def test_setting_a_directory_does_not_backfill_on_its_own(
    db: Database, tmp_path: Path
) -> None:
    """Picking a folder must not kick off an unannounced archive-sized copy."""
    root = tmp_path / "Batch A"
    (root / "old").mkdir(parents=True)
    (root / "old" / "history.json").write_text("{}", encoding="utf-8")
    backup = tmp_path / "mirror"

    manager = make_manager(db, [str(root)], db_debounce=0.0)
    await manager.configure(str(backup))
    await manager._pass()

    assert not (backup / "Batch A" / "old" / "history.json").exists()


@pytest.mark.asyncio
async def test_sync_now_backfills_the_whole_archive(db: Database, tmp_path: Path) -> None:
    root = tmp_path / "Batch A"
    (root / "old").mkdir(parents=True)
    (root / "old" / "history.json").write_text("{}", encoding="utf-8")
    (root / "old" / "history.tsv").write_text("221\t0\n", encoding="utf-8")
    backup = tmp_path / "mirror"

    manager = make_manager(db, [str(root)], db_debounce=0.0)
    await manager.configure(str(backup))
    result = await manager.sync_now()

    assert (backup / "Batch A" / "old" / "history.json").read_text(encoding="utf-8") == "{}"
    assert (backup / "Batch A" / "old" / "history.tsv").read_text(encoding="utf-8") == "221\t0\n"
    assert result["copied"] == 2
    assert result["failed"] == 0
    # It backs the database up too, so one action verifies the whole target.
    assert (backup / DB_MIRROR_NAME).is_file()


@pytest.mark.asyncio
async def test_sync_now_skips_what_is_already_current(db: Database, tmp_path: Path) -> None:
    root = tmp_path / "Batch A"
    root.mkdir()
    (root / "a.json").write_text("{}", encoding="utf-8")
    backup = tmp_path / "mirror"

    manager = make_manager(db, [str(root)], db_debounce=0.0)
    await manager.configure(str(backup))
    await manager.sync_now()
    second = await manager.sync_now()

    assert second["copied"] == 0
    assert second["skipped"] == 1

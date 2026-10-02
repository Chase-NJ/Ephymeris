"""Backup Directory mirroring — `DATA.md#backup-mirroring`.

Two guarantees protect two different failures, and conflating them is the
mistake this module exists to avoid:

* The `.tsv` write-ahead log (`DATA.md#crash-safety`) protects against the app
  or the power dying mid-session, on the **same** disk. It is already built, and per-line
  `fsync` is what makes it real.
* This module protects against losing that disk entirely — drive failure or
  accidental deletion — by mirroring to a **different** location.

Everything here is therefore deliberately kept off the critical path. The
backup target may be a slow or networked volume, and no failure of it may ever
slow, stall, or fail a session:

* The strobe thread never touches this module beyond a lock-free `track()`.
* Session finalization *queues* files; it never waits for a copy
  (`DATA.md#session-files`).
* `.tsv` mirroring is periodic (every ~10s), not per-line, and the interval is
  measured from the end of the previous pass — a slow target stretches the
  cadence instead of queuing overlapping passes.
* Every copy is whole-file, so a mirrored `.tsv` can never be a torn partial
  append; and every copy lands via a `.part` file plus `os.replace`, so a
  crash mid-copy can't leave a half-written file where a good one was.

The mirror is **additive**. Nothing is ever deleted from the backup directory
because something disappeared from the source — a mirror that faithfully
reproduces a deletion is no protection against one.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from .paths import MirrorLayout

log = logging.getLogger(__name__)

#: Seconds between `.tsv` mirror passes, measured from the end of the previous
#: pass (`DATA.md#session-files`). At the real session rate of well under one event
#: per second this leaves at most ~10 strobes unmirrored, against a local file
#: that is already `fsync`'d per line.
MIRROR_INTERVAL_S = 10.0

#: How long the database must be quiet before it is backed up. Editing a cohort
#: roster commits many times in quick succession; without this every keystroke's
#: save would copy the whole file to a network share.
DB_DEBOUNCE_S = 5.0

DB_MIRROR_NAME = "ephymeris.db"
DB_SNAPSHOT_DIR = "db-snapshots"
#: Dated snapshots retained. The live mirror alone would faithfully reproduce an
#: accidental cohort deletion within seconds, which defeats half the point; a
#: fortnight of dailies is a real undo window and costs a few MB.
DB_SNAPSHOT_KEEP = 14


class BackupNotConfigured(Exception):
    """A backup operation was requested with no usable backup directory."""


class BackupManager:
    """Owns the mirror: what to copy, when, and what the UI is told about it.

    Lifecycle: ``start`` → ``configure`` (on every settings push) → ``stop``.
    ``track``/``untrack``/``enqueue``/``mark_db_dirty`` are safe to call from
    any thread; everything else runs on the event loop.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        db: Any,
        cohort_roots: Callable[[], list[str]],
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        interval: float = MIRROR_INTERVAL_S,
        db_debounce: float = DB_DEBOUNCE_S,
    ) -> None:
        self._loop = loop
        self._db = db
        self._cohort_roots = cohort_roots
        self._broadcast = broadcast
        self._interval = interval
        self._db_debounce = db_debounce

        # Cross-thread state. `track` and `enqueue` are called from session
        # threads; the worker reads them from the loop.
        self._lock = threading.Lock()
        self._target: Path | None = None
        self._live: set[Path] = set()
        self._queue: list[Path] = []
        self._db_dirty_at: float | None = None

        # Loop-thread only.
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._state = "disabled"
        self._last_error: str | None = None
        self._last_success_at: str | None = None
        self._mirrored = 0
        self._syncing = False

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._task is None:
            self._task = self._loop.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def configure(self, directory: str | None) -> None:
        """Point the mirror at a new directory (or nowhere), from a settings push.

        Re-pointing deliberately does **not** backfill: the user chooses when to
        copy an existing archive across, via `backup.syncNow`
        (`DATA.md#no-automatic-backfill`). What it does do is back the
        database up promptly, which is what gives a backup "on every app
        start" — settings arrive immediately after the sidecar comes
        up, so a fresh launch always produces one.
        """
        target = Path(directory).expanduser() if directory else None
        with self._lock:
            unchanged = target == self._target
            self._target = target
            if not unchanged:
                # A new target has none of this one's history; a stale error
                # from the old path would be a lie about the new one.
                self._db_dirty_at = time.monotonic() - self._db_debounce
        if unchanged:
            return

        self._last_error = None
        self._state = "disabled" if target is None else "pending"
        if target is None:
            log.info("backup directory cleared; mirroring is off")
        else:
            log.info("backup directory set to %s", target)
        await self._publish()
        self._wake.set()

    # --- work registration (safe from any thread) -------------------------

    def track(self, path: str | Path) -> None:
        """Mirror this file on every pass until it's untracked (the live `.tsv`)."""
        with self._lock:
            self._live.add(Path(path))

    def untrack(self, path: str | Path) -> None:
        with self._lock:
            self._live.discard(Path(path))

    def enqueue(self, *paths: str | Path) -> None:
        """Mirror these files once, on the next pass (`.json`/`.mat` at finalize)."""
        with self._lock:
            for path in paths:
                candidate = Path(path)
                if candidate not in self._queue:
                    self._queue.append(candidate)

    def mark_db_dirty(self) -> None:
        """Note that `ephymeris.db` changed. Debounced, not immediate."""
        with self._lock:
            self._db_dirty_at = time.monotonic()

    # --- status -----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """The `backup.status` payload (`PROTOCOL.md#evt-backup.status`)."""
        with self._lock:
            target = self._target
            pending = len(self._queue)
            live = len(self._live)
        return {
            "configured": target is not None,
            "directory": str(target) if target is not None else None,
            "state": self._state,
            "pending": pending,
            "tracking": live,
            "mirroredFiles": self._mirrored,
            "lastSuccessAt": self._last_success_at,
            "lastError": self._last_error,
            "syncing": self._syncing,
            "intervalSeconds": self._interval,
        }

    async def _publish(self) -> None:
        from ..protocol import Evt, event

        await self._broadcast(event(Evt.BACKUP_STATUS, self.status()))

    # --- the worker -------------------------------------------------------

    async def _run(self) -> None:
        while True:
            try:
                await self._pass()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the mirror must never die
                log.exception("backup pass failed unexpectedly")
            # Self-paced: the interval starts when the pass *finishes*, so a
            # slow target stretches the cadence rather than piling up passes.
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _pass(self) -> None:
        with self._lock:
            target = self._target
            queued = list(self._queue)
            self._queue.clear()
            live = sorted(self._live)

        if target is None:
            return
        if not queued and not live and not self._db_due():
            return

        layout = MirrorLayout(await asyncio.to_thread(self._roots), target)
        failures: list[str] = []
        copied = 0

        # Queued one-shots first: those are finished files someone is waiting
        # on, where a live .tsv will come round again in ten seconds anyway.
        for source in [*queued, *live]:
            destination = layout.resolve(source)
            if destination is None:
                continue
            try:
                if await asyncio.to_thread(copy_if_stale, source, destination):
                    copied += 1
            except OSError as exc:
                failures.append(f"{Path(source).name}: {exc}")
                if source in queued:
                    # Don't drop a finalized file because the share blinked.
                    self.enqueue(source)

        try:
            await self._back_up_database(target)
        except OSError as exc:
            failures.append(f"{DB_MIRROR_NAME}: {exc}")

        await self._record_pass(copied, failures)

    async def _record_pass(self, copied: int, failures: list[str]) -> None:
        previous_state, previous_error = self._state, self._last_error
        self._mirrored += copied

        if failures:
            self._state = "failed"
            self._last_error = failures[0] if len(failures) == 1 else (
                f"{failures[0]} (and {len(failures) - 1} more)"
            )
            log.warning("backup mirroring failed: %s", self._last_error)
        else:
            self._state = "ok"
            self._last_error = None
            self._last_success_at = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )

        # Publish on a state change or on any real work, not on every quiet
        # tick — six idle boxes shouldn't produce an event every ten seconds.
        if self._state != previous_state or self._last_error != previous_error or copied:
            await self._publish()

    def _roots(self) -> list[str]:
        try:
            return list(self._cohort_roots())
        except Exception:  # noqa: BLE001 - a DB hiccup mustn't kill the mirror
            log.exception("couldn't list cohort folders for mirroring")
            return []

    # --- database ---------------------------------------------------------

    def _db_due(self) -> bool:
        with self._lock:
            marked = self._db_dirty_at
        return marked is not None and (time.monotonic() - marked) >= self._db_debounce

    async def _back_up_database(self, target: Path) -> None:
        if not self._db_due():
            return
        with self._lock:
            marked = self._db_dirty_at
        await asyncio.to_thread(self._write_db_backup, target)
        with self._lock:
            # A commit landing during the copy re-dirties it; only clear the
            # mark we actually acted on, so that write isn't silently lost.
            if self._db_dirty_at == marked:
                self._db_dirty_at = None

    def _write_db_backup(self, target: Path) -> None:
        """Snapshot locally, then copy out. Runs in a worker thread.

        The two steps are separate on purpose. `sqlite3`'s online backup holds
        the database lock for its duration; running it straight onto a network
        share would let that share's latency block every cohort read and write
        in the app. Snapshotting to a local temp file keeps the lock held for
        milliseconds, and the slow copy happens with nothing locked.
        """
        local = Path(self._db.path).with_name(Path(self._db.path).name + ".backup-tmp")
        self._db.snapshot_to(local)
        try:
            _place(local, Path(target) / DB_MIRROR_NAME)
            self._write_daily_snapshot(Path(target), local)
        finally:
            try:
                local.unlink()
            except OSError:  # pragma: no cover - best effort cleanup
                log.debug("couldn't remove temporary db snapshot %s", local)

    def _write_daily_snapshot(self, target: Path, local: Path) -> None:
        """One dated copy per day, kept `DB_SNAPSHOT_KEEP` deep
        (`DATA.md#the-database-copy`).

        First backup of the day wins — later ones would only overwrite the
        snapshot with the very state a user might be trying to undo.
        """
        folder = target / DB_SNAPSHOT_DIR
        stamp = datetime.now().strftime("%Y-%m-%d")
        destination = folder / f"ephymeris_{stamp}.db"
        if destination.exists():
            return
        _place(local, destination)

        # Names are ISO-dated, so a plain sort is a chronological sort.
        existing = sorted(folder.glob("ephymeris_*.db"))
        for stale in existing[:-DB_SNAPSHOT_KEEP]:
            try:
                stale.unlink()
            except OSError:  # pragma: no cover
                log.debug("couldn't prune old db snapshot %s", stale)

    # --- explicit sync ----------------------------------------------------

    async def sync_now(self) -> dict[str, Any]:
        """Copy anything missing from the mirror — the Settings "Sync now"
        (`DATA.md#no-automatic-backfill`).

        Setting a backup directory deliberately doesn't backfill on its own: it
        could mean an unannounced multi-gigabyte copy to a network share the
        moment someone picks a folder. This is the explicit version, and it
        doubles as the way to prove the target actually works before trusting
        it with anything.
        """
        with self._lock:
            target = self._target
        if target is None:
            raise BackupNotConfigured(
                "No backup directory is set. Choose one in Settings first."
            )
        if self._syncing:
            raise BackupNotConfigured("A sync is already running.")

        self._syncing = True
        await self._publish()
        try:
            roots = await asyncio.to_thread(self._roots)
            result = await asyncio.to_thread(self._walk_and_copy, roots, target)
            self.mark_db_dirty()
            try:
                await asyncio.to_thread(self._write_db_backup, target)
            except OSError as exc:
                result["failed"] += 1
                result["errors"].append(f"{DB_MIRROR_NAME}: {exc}")
            else:
                with self._lock:
                    self._db_dirty_at = None
        finally:
            self._syncing = False

        self._mirrored += result["copied"]
        if result["failed"]:
            self._state = "failed"
            self._last_error = result["errors"][0]
        else:
            self._state = "ok"
            self._last_error = None
            self._last_success_at = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
        await self._publish()
        log.info(
            "backup sync: %d copied, %d already current, %d failed",
            result["copied"],
            result["skipped"],
            result["failed"],
        )
        return result

    def _walk_and_copy(self, roots: Iterable[str], target: Path) -> dict[str, Any]:
        copied = skipped = failed = 0
        errors: list[str] = []
        roots = list(roots)
        layout = MirrorLayout(roots, target)

        for root in roots:
            base = Path(root).expanduser()
            if not base.is_dir():
                continue
            for source in sorted(base.rglob("*")):
                if not source.is_file() or source.name.endswith(".part"):
                    continue
                destination = layout.resolve(source)
                if destination is None:
                    continue
                try:
                    if copy_if_stale(source, destination):
                        copied += 1
                    else:
                        skipped += 1
                except OSError as exc:
                    failed += 1
                    if len(errors) < 5:
                        errors.append(f"{source.name}: {exc}")

        return {
            "copied": copied,
            "skipped": skipped,
            "failed": failed,
            "errors": errors,
            "directory": str(target),
        }


# --- filesystem primitives -------------------------------------------------


def _part_name(destination: Path) -> Path:
    """A temp name unique to this thread, so a sync and a mirror pass touching
    the same file can't clobber each other's half-written copy."""
    return destination.with_name(
        f"{destination.name}.{os.getpid()}-{threading.get_ident()}.part"
    )


def _place(source: Path, destination: Path) -> None:
    """Copy `source` over `destination` without ever leaving it half-written."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = _part_name(destination)
    try:
        shutil.copy2(source, part)
        os.replace(part, destination)
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise


def copy_if_stale(source: str | Path, destination: str | Path) -> bool:
    """Mirror `source` onto `destination` unless it's already current.

    Returns whether a copy actually happened. A source that has vanished is not
    an error — a session folder can be moved or removed between passes, and the
    mirror's job is to preserve what it already has, not to chase deletions.
    """
    src, dst = Path(source), Path(destination)
    try:
        source_stat = src.stat()
    except FileNotFoundError:
        return False

    try:
        destination_stat = dst.stat()
    except FileNotFoundError:
        pass
    else:
        # A live .tsv only ever grows, so size alone catches every real change;
        # mtime covers a rewrite that happened to land on the same length.
        if (
            destination_stat.st_size == source_stat.st_size
            and destination_stat.st_mtime >= source_stat.st_mtime
        ):
            return False

    _place(src, dst)
    return True

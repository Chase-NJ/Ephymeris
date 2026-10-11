"""Moving a cohort's data folder, records and all — `DATA.md#data-folder`.

Run records, recovered runs and session records store **absolute** paths. A
"move existing contents" relocate that moved the files and only repointed the
cohort left every one of those paths at the old place — and the next Rescan,
finding the files gone and the storage reachable, pruned the records
(`DATA.md#pruning`), losing the box, stop reason and parameters that only a
recorded run carries.

So the paths move with the files, in the order that makes it safe:

* **Same volume** — one atomic `rename` of the folder, journalled first; the
  records follow in one transaction. A crash between the two is rolled forward
  at the next start: the folder is demonstrably at the target, so the records
  are what's behind.
* **Another volume** — copy, fsync and verify, commit the records, then
  delete the originals; the animal move's order
  (`DATA.md#moving-animals-between-cohorts`). A crash while copying is undone,
  after the commit finished.

Neither starts while a session of the cohort is open, and the copy checks
again at commit: a session recorded while it ran has its files at the old
place, so its records must not move. A rename is over before anyone could set
one up, and `moving` lets `sessions.create` refuse meanwhile.

Either way the cache and adoption rows carry their freshness keys to the
moved files (`freshness.carry`): a copy's mtime is rounded on a coarser
volume, and a key left at the original's would send every recovered run back
to being matched by name.

And for cohorts relocated before this existed, `rehome` re-points records left
at an old folder to the files now under the cohort's — run by Rescan before it
prunes, so the repair happens instead of the loss.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import folders, freshness
from .db import Database
from .folders import DataFolderError, relative_below, resolved
from .models import CohortNotFound

log = logging.getLogger(__name__)

#: How many trailing path parts `rehome` will try to find under the cohort
#: folder: a run file sits at most a prefix, a session folder and a format
#: folder below it in any layout the walk accepts, with room for a level more.
_MAX_TAIL = 8


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- rewriting the records ------------------------------------------------------


def rewrite_paths(
    conn: sqlite3.Connection,
    cohort_id: str,
    old_root: str | Path,
    new_root: str | Path,
    *,
    only_existing: bool = False,
) -> int:
    """Point every path this cohort's records store below `old_root` at the
    same place below `new_root`. Never commits; returns how many rows changed.

    That includes where each recorded group run told RHX to save: by default
    `<session folder>/ephys`, which moves with the folder
    (`RECORDING.md#what-is-written`), whichever cohort's session it now is. A
    save location elsewhere is left alone.

    `only_existing` is the repair's caution: a path moves only when what it
    names is there — the file, or for a run its write-ahead `.tsv`, which
    recovery rebuilds the rest from (`DATA.md#crash-recovery`).
    """
    from ..analytics import reader  # analytics imports cohorts

    new_base = Path(new_root)

    def rebased(path: str | None) -> str | None:
        if not path:
            return None
        rel = relative_below(path, old_root)
        return None if rel is None else str(new_base / rel)

    def present(path: str, *, run: bool) -> bool:
        target = Path(path)
        try:
            return target.exists() or (run and reader.sibling_tsv(target).is_file())
        except OSError:
            return False

    changed = 0
    for session_id, folder in conn.execute(
        "SELECT id, folder_path FROM sessions WHERE cohort_id = ?", (cohort_id,)
    ).fetchall():
        new = rebased(folder)
        if new and (not only_existing or present(new, run=False)):
            conn.execute("UPDATE sessions SET folder_path = ? WHERE id = ?", (new, session_id))
            changed += 1
    # Every cohort's: a session moved to another cohort keeps its recording
    # where RHX wrote it, in this folder (`DATA.md#moving-animals-between-cohorts`).
    for session_id, recording_json in conn.execute(
        "SELECT id, recording_json FROM sessions WHERE recording_json IS NOT NULL"
    ).fetchall():
        recording = _rebased_recording(recording_json, rebased, present, only_existing)
        if recording is not None:
            conn.execute(
                "UPDATE sessions SET recording_json = ? WHERE id = ?", (recording, session_id)
            )
            changed += 1
    for run_id, path in conn.execute(
        "SELECT r.id, r.file_path FROM session_animal_runs r"
        " JOIN sessions s ON s.id = r.session_id WHERE s.cohort_id = ?",
        (cohort_id,),
    ).fetchall():
        new = rebased(path)
        if new and (not only_existing or present(new, run=True)):
            conn.execute("UPDATE session_animal_runs SET file_path = ? WHERE id = ?", (new, run_id))
            conn.execute("UPDATE run_metrics_cache SET file_path = ? WHERE run_id = ?", (new, run_id))
            changed += 1
    for adopted_id, path in conn.execute(
        "SELECT id, file_path FROM adopted_runs WHERE cohort_id = ?", (cohort_id,)
    ).fetchall():
        new = rebased(path)
        if new and (not only_existing or present(new, run=True)):
            conn.execute("UPDATE adopted_runs SET file_path = ? WHERE id = ?", (new, adopted_id))
            conn.execute(
                "UPDATE run_metrics_cache SET file_path = ? WHERE run_id = ?", (new, adopted_id)
            )
            changed += 1
    # A pure cache keyed by path, shared by every cohort: only rows below the
    # old root can be this cohort's files.
    for (path,) in conn.execute("SELECT file_path FROM strobe_scan_cache").fetchall():
        new = rebased(path)
        if new:
            conn.execute(
                "UPDATE OR REPLACE strobe_scan_cache SET file_path = ? WHERE file_path = ?",
                (new, path),
            )
    return changed


def _rebased_recording(
    recording_json: str | None,
    rebased: Callable[[str | None], str | None],
    present: Callable[..., bool],
    only_existing: bool,
) -> str | None:
    """The session's recording with each run's save location rebased, or None
    when none of them moves."""
    if not recording_json:
        return None
    try:
        recording = json.loads(recording_json)
        runs = recording.get("runs", [])
    except (ValueError, AttributeError):
        return None
    moved = False
    for run in runs if isinstance(runs, list) else []:
        path = run.get("path") if isinstance(run, dict) else None
        new = rebased(path) if isinstance(path, str) else None
        if new and (not only_existing or present(new, run=False)):
            run["path"] = new
            moved = True
    return json.dumps(recording) if moved else None


# --- the relocate ------------------------------------------------------------------


def relocate_cohort(db: Database, cohort_id: str, destination: str, move_existing: bool) -> Path:
    """The "Change data folder…" action, with the records following the files.

    Pointing without moving (`move_existing=False`) writes nothing on disk and
    rewrites nothing: the cohort is attached to data that is already there,
    and whatever the records named stays where it was.
    """
    with db.lock:
        row = db.conn.execute(
            "SELECT data_folder FROM cohorts WHERE id = ?", (cohort_id,)
        ).fetchone()
    if row is None:
        raise CohortNotFound(cohort_id)
    source = Path(row[0]).expanduser()
    target = Path(destination).expanduser()

    if not move_existing or not source.exists() or _same(source, target):
        final = folders.relocate(source, target, move_existing)
        _set_folder(db, cohort_id, final)
        return final

    _check_destination(source, target)
    same_volume = _same_volume(source, target)
    # Taken before anything moves: after a rename there is no original left
    # to stat, and a key is carried only if it was fresh for the original.
    before = _stats(source)
    journal = str(uuid.uuid4())
    with db.lock:
        _refuse_open_sessions(db.conn, cohort_id)
        known = _record_ids(db.conn, cohort_id)
        db.conn.execute(
            "INSERT INTO folder_moves (id, cohort_id, source, target, state, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (journal, cohort_id, str(source), str(target),
             "moving" if same_volume else "copying", _now(), _now()),
        )
        db.conn.commit()

    try:
        if same_volume:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target.rmdir()  # checked empty; a rename needs the name free
            os.rename(source, target)
        else:
            _copy_tree(source, target)
    except OSError as exc:
        if not same_volume:
            _remove_copies(source, target)
        _finish(db, journal, "rolled-back", str(exc))
        raise DataFolderError(f"Couldn't move data to {target}: {exc}") from exc

    failure: BaseException | None = None
    with db.lock:
        try:
            if not same_volume:
                _refuse_records_since(db.conn, cohort_id, known)
            _commit_records(db.conn, cohort_id, source, target, before)
            db.conn.execute(
                "UPDATE folder_moves SET state = ?, updated_at = ? WHERE id = ?",
                ("done" if same_volume else "committed", _now(), journal),
            )
            db.conn.commit()
        except Exception as exc:
            db.conn.rollback()
            failure = exc
    if failure is not None:
        # The records never moved, so neither may the files.
        try:
            if same_volume:
                os.rename(target, source)
            else:
                _remove_copies(source, target)
        except OSError:
            log.exception("relocate: couldn't put %s back at %s", target, source)
        _finish(db, journal, "rolled-back", str(failure))
        raise failure

    if not same_volume:
        _delete_sources(source, target)
        _finish(db, journal, "done")
    log.info("relocate: moved cohort %s from %s to %s", cohort_id, source, target)
    return target


def resume(db: Database) -> int:
    """Finish or undo every relocate a crash interrupted. Run once at start-up,
    before anything may read or rescan the archive."""
    with db.lock:
        rows = db.conn.execute(
            "SELECT id, cohort_id, source, target, state FROM folder_moves"
            " WHERE state IN ('moving', 'copying', 'committed')"
        ).fetchall()
    for journal, cohort_id, source_s, target_s, state in rows:
        source, target = Path(source_s), Path(target_s)
        if state == "moving":
            if not source.exists() and target.exists():
                # The originals' stats went with the crash, so the keys stay
                # as they were; a rename keeps mtimes, so they still hold.
                log.warning("relocate %s: the folder moved before a crash; finishing", journal)
                with db.lock:
                    _commit_records(db.conn, cohort_id, source, target)
                    db.conn.commit()
                _finish(db, journal, "done")
            else:
                _finish(db, journal, "rolled-back", "interrupted before the folder moved")
        elif state == "copying":
            log.warning("relocate %s: interrupted while copying; removing the copy", journal)
            _remove_copies(source, target)
            _finish(db, journal, "rolled-back", "interrupted while copying")
        else:
            log.warning("relocate %s: interrupted after it committed; finishing", journal)
            _delete_sources(source, target)
            _finish(db, journal, "done")
    return len(rows)


def _commit_records(
    conn: sqlite3.Connection,
    cohort_id: str,
    source: Path,
    target: Path,
    before: dict[tuple[str, ...], freshness.Stat] | None = None,
) -> None:
    rewrite_paths(conn, cohort_id, source, target)
    if before:
        _carry_keys(conn, target, before)
    conn.execute(
        "UPDATE cohorts SET data_folder = ?, updated_at = ? WHERE id = ?",
        (str(target), _now(), cohort_id),
    )


def _carry_keys(
    conn: sqlite3.Connection, target: Path, before: dict[tuple[str, ...], freshness.Stat]
) -> None:
    """Re-key every row below `target` from its original's stat. The target
    was empty, so whatever lies below it is this relocate's."""
    paths = {
        p
        for table in freshness.KEYED_TABLES
        for (p,) in conn.execute(f"SELECT file_path FROM {table}")
        if p
    }
    moved = []
    for path in paths:
        rel = relative_below(path, target)
        if rel is not None:
            moved.append((path, before.get(_key(rel))))
    freshness.carry(conn, moved)


def _stats(root: Path) -> dict[tuple[str, ...], freshness.Stat]:
    """Every file's stat below `root`, by its case-folded relative path —
    how `relative_below` compares the records' spellings."""
    out: dict[tuple[str, ...], freshness.Stat] = {}
    for path in _files(root):
        stat = freshness.stat_of(path)
        if stat is not None:
            out[_key(path.relative_to(root))] = stat
    return out


def _key(rel: Path) -> tuple[str, ...]:
    return tuple(part.casefold() for part in rel.parts)


def _set_folder(db: Database, cohort_id: str, folder: Path) -> None:
    with db.lock:
        db.conn.execute(
            "UPDATE cohorts SET data_folder = ?, updated_at = ? WHERE id = ?",
            (str(folder), _now(), cohort_id),
        )
        db.conn.commit()


def _finish(db: Database, journal: str, state: str, error: str | None = None) -> None:
    with db.lock:
        db.conn.execute(
            "UPDATE folder_moves SET state = ?, error = ?, updated_at = ? WHERE id = ?",
            (state, error[:500] if error else None, _now(), journal),
        )
        db.conn.commit()


def _check_destination(source: Path, target: Path) -> None:
    if target.exists() and not target.is_dir():
        raise DataFolderError(f"{target} exists but isn't a folder.")
    if target.exists() and any(target.iterdir()):
        raise DataFolderError(
            f"{target} isn't empty. Choose an empty folder to move this "
            f"cohort's data into — Ephymeris won't merge into or overwrite "
            f"existing data. To use the data already in {target.name}, "
            f"change the folder without moving."
        )
    if relative_below(target, source) is not None:
        raise DataFolderError(f"{target} is inside the folder being moved.")


def moving(db: Database, cohort_id: str) -> bool:
    """Whether this cohort's folder is part-way through a relocate, so a new
    session must not be set up in it: its folder would be made at the old
    place while the records move to the new one."""
    with db.lock:
        row = db.conn.execute(
            "SELECT 1 FROM folder_moves WHERE cohort_id = ?"
            " AND state IN ('moving', 'copying', 'committed') LIMIT 1",
            (cohort_id,),
        ).fetchone()
    return row is not None


def _refuse_open_sessions(conn: sqlite3.Connection, cohort_id: str) -> None:
    """A session still open writes into the folder, or will: its runner was
    given a path below the old place, which the records are about to leave."""
    row = conn.execute(
        "SELECT prefix_name, session_number, date FROM sessions WHERE cohort_id = ?"
        " AND status IN ('configuring', 'running') ORDER BY date LIMIT 1",
        (cohort_id,),
    ).fetchone()
    if row is not None:
        raise DataFolderError(
            f"{row[0]}_{row[1]} ({row[2]}) is still open. Close it out, or run Tidy "
            "records, then move the data folder."
        )


def _record_ids(conn: sqlite3.Connection, cohort_id: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT id FROM sessions WHERE cohort_id = ?"
            " UNION ALL SELECT r.id FROM session_animal_runs r"
            " JOIN sessions s ON s.id = r.session_id WHERE s.cohort_id = ?",
            (cohort_id, cohort_id),
        )
    }


def _refuse_records_since(conn: sqlite3.Connection, cohort_id: str, known: set[str]) -> None:
    """The copy's own check at commit: a session or run recorded while it ran
    wrote its files at the old place, after the copy had passed them. Moving
    its records would point them at files that are not there, and the next
    Rescan would prune them (`DATA.md#pruning`)."""
    _refuse_open_sessions(conn, cohort_id)
    if _record_ids(conn, cohort_id) - known:
        raise DataFolderError(
            "A session was recorded in this cohort while its data was being copied. "
            "Nothing was moved; move the data folder again."
        )


def _same(a: Path, b: Path) -> bool:
    return str(resolved(a)).casefold() == str(resolved(b)).casefold()


def _same_volume(source: Path, target: Path) -> bool:
    """Whether a rename can move the folder — the target's nearest existing
    ancestor on the same device as the source."""
    probe = target
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return os.stat(source).st_dev == os.stat(probe).st_dev
    except OSError:
        return False


def _files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()] if root.is_dir() else []


def _counterpart_matches(path: Path, mirror: Path) -> bool:
    try:
        return mirror.is_file() and mirror.stat().st_size == path.stat().st_size
    except OSError:
        return False


def _copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, copy_function=_copy_durably, dirs_exist_ok=True)
    for path in _files(source):
        if not _counterpart_matches(path, target / path.relative_to(source)):
            raise OSError(f"{target / path.relative_to(source)} did not copy intact")


def _copy_durably(src: str, dst: str) -> str:
    """`copy2`, then fsync: the originals are deleted right after the commit,
    and a copy still in the OS cache is not yet a copy."""
    out = shutil.copy2(src, dst)
    with open(out, "rb+") as handle:
        os.fsync(handle.fileno())
    return out


def _remove_copies(source: Path, target: Path) -> None:
    """Undo a copy: a file goes only when its original is still there, the
    same size — never anything that is the only copy."""
    for path in _files(target):
        if _counterpart_matches(path, source / path.relative_to(target)):
            try:
                path.unlink()
            except OSError:
                pass
    _prune_empty_dirs(target, keep_root=True)


def _delete_sources(source: Path, target: Path) -> None:
    """After the commit: an original goes only once its copy is in place."""
    for path in _files(source):
        if _counterpart_matches(path, target / path.relative_to(source)):
            try:
                path.unlink()
            except OSError as exc:
                log.warning("relocate: couldn't remove %s: %s", path, exc)
    _prune_empty_dirs(source, keep_root=False)


def _prune_empty_dirs(root: Path, *, keep_root: bool) -> None:
    """Bottom-up `rmdir`, which refuses anything non-empty — never `rmtree`."""
    if not root.is_dir():
        return
    for current, _dirs, _files_here in os.walk(root, topdown=False):
        if keep_root and Path(current) == root:
            continue
        try:
            os.rmdir(current)
        except OSError:
            pass


# --- repairing an earlier relocate ---------------------------------------------------


def rehome(db: Database, cohort_id: str) -> int:
    """Re-point records an earlier relocate left at the old folder.

    A record is stale when its path is outside the cohort's folder and nothing
    is there. The old folder is found by asking, for each stale path, which
    tail of it exists under the cohort's folder — and taking the root most
    stale paths agree on, so one coincidence cannot redirect a cohort. Only
    paths whose files are actually there are rewritten. Returns how many
    records moved.
    """
    with db.lock:
        row = db.conn.execute(
            "SELECT data_folder FROM cohorts WHERE id = ?", (cohort_id,)
        ).fetchone()
        if row is None:
            return 0
        folder = Path(row[0]).expanduser()
        paths = [
            p
            for (p,) in db.conn.execute(
                "SELECT folder_path FROM sessions WHERE cohort_id = ?"
                " UNION ALL SELECT r.file_path FROM session_animal_runs r"
                " JOIN sessions s ON s.id = r.session_id WHERE s.cohort_id = ?"
                " UNION ALL SELECT file_path FROM adopted_runs WHERE cohort_id = ?",
                (cohort_id, cohort_id, cohort_id),
            )
            if p
        ]
    if not folder.is_dir():
        return 0

    votes: Counter[str] = Counter()
    for path in paths:
        if relative_below(path, folder) is not None or Path(path).exists():
            continue
        parts = resolved(path).parts
        for k in range(1, min(len(parts) - 1, _MAX_TAIL) + 1):
            if (folder / Path(*parts[-k:])).exists():
                votes[str(Path(*parts[:-k]))] += 1
                break
    if not votes:
        return 0
    old_root = votes.most_common(1)[0][0]
    with db.lock:
        changed = rewrite_paths(db.conn, cohort_id, old_root, folder, only_existing=True)
        if changed:
            db.conn.commit()
    if changed:
        log.info("rescan: re-pointed %d record(s) of cohort %s from %s", changed, cohort_id, old_root)
    return changed

"""Carrying out a move of animals between cohorts —
`DATA.md#moving-animals-between-cohorts`.

The order is what makes it safe, and every step is idempotent:

1. **Journal.** The plan's file list goes into `animal_moves` (`copying`)
   before anything is touched.
2. **Copy.** Every file to its destination, verified (`transfer`, the
   relocate's too): through `<name>.part`, fsync'd, renamed into place,
   re-read and hash-checked. Nothing in the database
   changes here, so a crash leaves the source exactly as it was — the start-up
   pass deletes the copies this move made and marks it `rolled-back`.
3. **Commit.** One transaction: the record half is re-planned against the
   database as it is *now*, and abandoned if it no longer matches what was
   copied; otherwise every record moves and the journal says `committed`.
   From here each run belongs to exactly one cohort, and every record points
   at a file that exists.
4. **Clean up.** Each original whose hash still matches is deleted, emptied
   folders are removed bottom-up with `rmdir` (never `rmtree`), and the
   journal says `done`. A crash here is finished at the next start.

Synchronous throughout; the analytics service runs it in a worker thread under
its lock, so no rescan, tidy or summary index sees a move half-done.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..sessions.models import GroupRun
from ..sessions.repository import SessionRepository
from ..sessions.tidy import Merge, merged_fields
from . import freshness, relocate, transfer
from .db import Database, Tx
from .move import (
    MovePlan,
    MoveRequest,
    SessionMove,
    _norm,
    plan_files_json,
    plan_move,
)

log = logging.getLogger(__name__)


class MoveRefused(Exception):
    """The plan has refusals, or changed under the copy. Nothing was moved."""

    def __init__(self, plan: MovePlan, message: str | None = None) -> None:
        reasons = "; ".join(r["message"] for r in plan.refused)
        super().__init__(message or reasons or "the move was refused")
        self.plan = plan


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def preview(db: Database, request: MoveRequest, *, busy: str | None = None) -> MovePlan:
    with db.read() as q:
        return plan_move(q, request, busy=busy)


def apply(
    db: Database,
    request: MoveRequest,
    *,
    busy: str | None = None,
    on_copied: Callable[[int, int], None] | None = None,
) -> MovePlan:
    """Move, in the four steps above. Raises `MoveRefused` with nothing moved.

    Returns the plan as applied, whose `files` the caller queues for backup.
    """
    with db.write() as unit:
        plan = plan_move(unit, request, busy=busy)
        if plan.refused:
            raise MoveRefused(plan)
        journal = str(uuid.uuid4())
        unit.execute(
            "INSERT INTO animal_moves (id, source_cohort_id, dest_cohort_id, state, plan_json,"
            " created_at, updated_at) VALUES (?, ?, ?, 'copying', ?, ?, ?)",
            (
                journal,
                request.source_id,
                request.dest_id,
                json.dumps({"request": request.to_json(), "files": json.loads(plan_files_json(plan))}),
                _now(),
                _now(),
            ),
        )

    try:
        _copy_files(plan, on_copied)
    except Exception as exc:
        _roll_back(db, journal, plan_files(plan), str(exc))
        raise

    failure: BaseException | None = None
    try:
        # The records and the journal's `committed`, in one unit of work.
        with db.write() as tx:
            again = plan_move(tx, request, busy=busy)
            if again.refused or again.identity() != plan.identity():
                raise MoveRefused(
                    again,
                    "Something changed while the files were being copied. Nothing was moved; "
                    "try again.",
                )
            _apply_records(tx, again, SessionRepository(db))
            tx.execute(
                "UPDATE animal_moves SET state = 'committed', updated_at = ? WHERE id = ?",
                (_now(), journal),
            )
    except Exception as exc:
        failure = exc
    if failure is not None:
        # After the unit ended: undoing is a unit of its own.
        _roll_back(db, journal, plan_files(plan), str(failure))
        raise failure
    plan = again

    _clean_up(db, journal, plan_files(plan), plan.source.data_folder, plan.source.id)
    log.info(
        "cohorts: moved %d animal(s), %d run(s), %d file(s) from %s to %s",
        len(plan.animals),
        len(plan.run_paths) + len(plan.adopted),
        len(plan.files),
        plan.source.id,
        plan.dest.id,
    )
    return plan


def plan_files(plan: MovePlan) -> list[dict[str, Any]]:
    return json.loads(plan_files_json(plan))


# --- step 2: copy -------------------------------------------------------------


def _copy_files(plan: MovePlan, on_copied: Callable[[int, int], None] | None) -> None:
    transfer.copy(_copies(plan_files(plan), "copy"), on_copied)


def _copies(files: list[dict[str, Any]], *actions: str) -> list[transfer.FileCopy]:
    """The journal's file list, as the transfer takes it."""
    return [
        transfer.FileCopy(Path(f["src"]), Path(f["dst"]), f["sha256"])
        for f in files
        if f["action"] in actions
    ]


# --- step 3: the records ------------------------------------------------------


def _apply_records(conn: Tx, plan: MovePlan, sessions: SessionRepository) -> None:
    source, dest = plan.source, plan.dest
    now = _now()
    mapped = {a.source_id: a.dest_id for a in plan.animals}

    # Animals: the destination gains what it doesn't already have, then the
    # source lets go — in that order, so a carried id is never in two cohorts.
    for animal in plan.animals:
        if animal.outcome == "carried":
            old = conn.execute(
                "SELECT * FROM animals WHERE id = ? AND cohort_id = ?",
                (animal.source_id, source.id),
            ).fetchone()
            former = conn.execute(
                "SELECT * FROM former_animals WHERE id = ? AND cohort_id = ?",
                (animal.source_id, source.id),
            ).fetchone()
            row = old or former
            conn.execute("DELETE FROM animals WHERE id = ?", (animal.source_id,))
            conn.execute("DELETE FROM former_animals WHERE id = ?", (animal.source_id,))
            if animal.status == "active":
                conn.execute(
                    "INSERT INTO animals (id, cohort_id, group_id, name, box_number, cage, sex,"
                    " id_number, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        animal.source_id,
                        dest.id,
                        animal.dest_group_id,
                        animal.name,
                        animal.dest_box,
                        row["cage"] if row else None,
                        row["sex"] if row else None,
                        row["id_number"] if row else None,
                        row["notes"] if row else None,
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO former_animals (id, cohort_id, name, cage, sex, id_number,"
                    " notes, group_name, removed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        animal.source_id,
                        dest.id,
                        animal.name,
                        row["cage"] if row else None,
                        row["sex"] if row else None,
                        row["id_number"] if row else None,
                        row["notes"] if row else None,
                        row["group_name"] if former else None,
                        (former["removed_at"] if former else None) or now,
                    ),
                )
        else:
            conn.execute(
                "DELETE FROM animals WHERE id = ? AND cohort_id = ?", (animal.source_id, source.id)
            )
            conn.execute(
                "DELETE FROM former_animals WHERE id = ? AND cohort_id = ?",
                (animal.source_id, source.id),
            )

    for entry in plan.sessions:
        _apply_session(conn, plan, entry, mapped, now, sessions)

    for run_id, new_path in plan.run_paths.items():
        conn.execute(
            "UPDATE session_animal_runs SET file_path = ?, animal_id = ? WHERE id = ?",
            (new_path, plan.run_animals[run_id], run_id),
        )
        if new_path is not None:
            conn.execute(
                "UPDATE run_metrics_cache SET file_path = ? WHERE run_id = ?", (new_path, run_id)
            )

    for adopted_id, (new_path, animal_id) in plan.adopted.items():
        # A destination adoption of the same file under another id would trip
        # `idx_adopted_file`; the row being moved is the one that stands.
        conn.execute(
            "DELETE FROM adopted_runs WHERE cohort_id = ? AND file_path = ? AND id != ?",
            (dest.id, new_path, adopted_id),
        )
        held = _held_adoption_of(conn, dest.id, adopted_id, new_path)
        if held is not None:
            _join_held_adoption(conn, adopted_id, held)
            continue
        conn.execute(
            "UPDATE adopted_runs SET cohort_id = ?, file_path = ?, animal_id = ? WHERE id = ?",
            (dest.id, new_path, animal_id, adopted_id),
        )
        conn.execute(
            "UPDATE run_metrics_cache SET file_path = ? WHERE run_id = ?", (new_path, adopted_id)
        )

    for f in plan.files:
        conn.execute(
            "UPDATE OR REPLACE strobe_scan_cache SET file_path = ? WHERE file_path = ?",
            (f.dst, f.src),
        )

    # The content is hash-verified identical, so a row that was fresh for the
    # original is fresh for the copy; the originals are still there to ask.
    originals = {_norm(f.dst): f.src for f in plan.files if f.action != "already"}
    stored = {
        *(p for p in plan.run_paths.values() if p),
        *(p for p, _ in plan.adopted.values()),
        *(f.dst for f in plan.files),
    }
    freshness.carry(
        conn, ((p, freshness.stat_of(originals.get(_norm(p)))) for p in stored)
    )

    conn.execute("UPDATE cohorts SET updated_at = ? WHERE id IN (?, ?)", (now, source.id, dest.id))


def _held_adoption_of(conn: Tx, dest_id: str, adopted_id: str, new_path: str) -> str | None:
    """The destination's own adoption of the same run as `adopted_id`, at
    another place -- one run copied into both cohorts -- or None."""
    from ..analytics import reader  # analytics imports cohorts

    identity = reader.run_identity(Path(new_path))
    for held_id, path in conn.execute(
        "SELECT id, file_path FROM adopted_runs WHERE cohort_id = ? AND id != ? ORDER BY id",
        (dest_id, adopted_id),
    ).fetchall():
        if path and reader.run_identity(Path(path)) == identity:
            return held_id
    return None


def _join_held_adoption(conn: Tx, adopted_id: str, held_id: str) -> None:
    """Fold a moved adoption into the destination's row for the same run
    (`DATA.md#moving-animals-between-cohorts`): the held row stands, since
    its scores are keyed by its id, and the moved row's ruling comes with it
    unless the held row has one of its own. The moved file is still copied;
    the next rescan sees two copies of one run, as it would in any cohort."""
    conn.execute(
        "UPDATE OR IGNORE run_flags SET run_id = ? WHERE run_id = ?", (held_id, adopted_id)
    )
    conn.execute("DELETE FROM run_flags WHERE run_id = ?", (adopted_id,))
    conn.execute("DELETE FROM run_metrics_cache WHERE run_id = ?", (adopted_id,))
    conn.execute("DELETE FROM adopted_runs WHERE id = ?", (adopted_id,))


def _apply_session(
    conn: Tx,
    plan: MovePlan,
    entry: SessionMove,
    mapped: dict[str, str],
    now: str,
    sessions: SessionRepository,
) -> None:
    source, dest = plan.source, plan.dest
    session = entry.source

    def remap_animal_notes(session_id: str) -> None:
        for old, new in mapped.items():
            conn.execute(
                "UPDATE session_notes SET animal_id = ? WHERE session_id = ? AND animal_id = ?",
                (new, session_id, old),
            )

    if entry.kind == "whole" and entry.dest_session_id is None:
        # The record itself goes, with everything hanging off it.
        conn.execute(
            "UPDATE sessions SET cohort_id = ?, folder_path = ?, group_runs = ? WHERE id = ?",
            (dest.id, entry.dest_folder, _group_runs_json(entry.dest_group_runs), session.id),
        )
        conn.execute("UPDATE session_notes SET cohort_id = ? WHERE session_id = ?", (dest.id, session.id))
        remap_animal_notes(session.id)
        return

    if entry.dest_session_id is None:
        target = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO sessions (id, cohort_id, prefix_id, prefix_name, session_number, date,"
            " started_at, ended_at, status, folder_path, group_runs, duration_minutes,"
            " recording_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                target,
                dest.id,
                session.prefix_id,
                session.prefix_name,
                session.session_number,
                session.date,
                session.started_at,
                session.ended_at,
                session.status,
                entry.dest_folder,
                _group_runs_json(entry.dest_group_runs),
                session.duration_minutes,
            ),
        )
    else:
        target = entry.dest_session_id
        _fold_into(conn, target, entry, sessions)

    if entry.run_ids:
        marks = ",".join("?" * len(entry.run_ids))
        conn.execute(
            f"UPDATE session_animal_runs SET session_id = ? WHERE id IN ({marks})",
            (target, *entry.run_ids),
        )
    for note_id in entry.notes_moved:
        conn.execute(
            "UPDATE session_notes SET session_id = ?, cohort_id = ? WHERE id = ?",
            (target, dest.id, note_id),
        )
    remap_animal_notes(target)
    for note_id in entry.notes_copied:
        conn.execute(
            "INSERT INTO session_notes (id, session_id, cohort_id, at, created_at, edited_at,"
            " deleted_at, tag, scope_kind, animal_id, box_number, body, carry_forward,"
            " resolved_at, resolved_in_session)"
            " SELECT ?, ?, ?, at, created_at, edited_at, deleted_at, tag, scope_kind, animal_id,"
            " box_number, body, carry_forward, resolved_at, NULL"
            " FROM session_notes WHERE id = ?",
            (str(uuid.uuid4()), target, dest.id, note_id),
        )
    log_row = conn.execute(
        "SELECT operator, summary, updated_at FROM session_logs WHERE session_id = ?",
        (session.id,),
    ).fetchone()
    if log_row is not None:
        conn.execute(
            "INSERT OR IGNORE INTO session_logs (session_id, operator, summary, updated_at)"
            " VALUES (?, ?, ?, ?)",
            (target, log_row["operator"], log_row["summary"], log_row["updated_at"] or now),
        )

    if entry.kind == "whole":
        # Folded into the destination's record of the same day: the source
        # record has nothing left to stand for.
        conn.execute(
            "UPDATE session_notes SET session_id = ?, cohort_id = ? WHERE session_id = ?",
            (target, dest.id, session.id),
        )
        conn.execute(
            "UPDATE session_notes SET resolved_in_session = ? WHERE resolved_in_session = ?",
            (target, session.id),
        )
        conn.execute("DELETE FROM sessions WHERE id = ?", (session.id,))
    else:
        sessions.set_group_runs(session.id, list(entry.source_group_runs), tx=conn)


def _fold_into(
    conn: Tx, target_id: str, entry: SessionMove, sessions: SessionRepository
) -> None:
    """Merge the moved half's group runs (and, for a whole record, its
    recording) into the destination's record of the same day — tidy's rule."""
    keep = sessions.get_session(target_id)
    moved = entry.source
    moved.group_runs = list(entry.dest_group_runs)
    if entry.kind == "split":
        moved.recording = None
    fields = merged_fields(Merge(keep=keep, absorb=[moved]))
    conn.execute(
        "UPDATE sessions SET group_runs = ?, recording_json = ?, started_at = ?, ended_at = ?,"
        " status = ? WHERE id = ?",
        (
            _group_runs_json(fields["group_runs"]),
            json.dumps(fields["recording"]) if fields["recording"] is not None else None,
            fields["started_at"],
            fields["ended_at"],
            fields["status"],
            target_id,
        ),
    )


def _group_runs_json(runs: list[GroupRun]) -> str:
    return json.dumps([r.to_json() for r in runs])


# --- step 4 and the restart pass ----------------------------------------------


def _clean_up(
    db: Database, journal: str, files: list[dict[str, Any]], source_folder: str, source_id: str
) -> None:
    """Delete the originals the commit made redundant, and the folders that
    leaves empty. A file whose content changed since it was planned is left
    where it is — it is not the file that was copied. While any original
    can't be reached, nothing is deleted and the journal stays `committed`
    for the next start: an unreadable original is not a deleted one."""
    copies = _copies(files, "copy", "present")
    unreached = next((f.src for f in copies if relocate.out_of_reach(f.src)), None)
    if unreached is not None:
        log.warning(
            "move %s: %s can't be reached; its originals are left for the next start",
            journal, unreached,
        )
        return
    touched = transfer.delete_originals(copies)
    _remove_emptied(db, touched, source_folder, source_id)
    with db.write() as unit:
        unit.execute(
            "UPDATE animal_moves SET state = 'done', updated_at = ? WHERE id = ?", (_now(), journal)
        )


def _remove_emptied(db: Database, format_dirs: set[Path], source_folder: str, source_id: str) -> None:
    """Format folders the move emptied go; so does a session folder no source
    record still points at, once all it holds is its derived `notes.md` — the
    log moved with the records and is re-rendered at the destination."""
    from ..analytics import reader  # analytics imports cohorts

    with db.read() as q:
        still_used = {
            _norm(row[0])
            for row in q.execute(
                "SELECT folder_path FROM sessions WHERE cohort_id = ?", (source_id,)
            )
            if row[0]
        }
    sessions: set[Path] = set()
    for folder in sorted(format_dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            folder.rmdir()
        except OSError:
            pass
        sessions.add(reader.session_folder_of(folder / "x"))
    root = _norm(source_folder)
    for session in sessions:
        if _norm(str(session)) in still_used or _norm(str(session)) == root:
            continue
        try:
            leftovers = [p for p in session.rglob("*") if p.is_file()]
        except OSError:
            continue
        if any(p.name != "notes.md" or p.parent != session for p in leftovers):
            continue
        for p in leftovers:
            try:
                p.unlink()
            except OSError:
                pass
        for current, _dirs, files in os.walk(session, topdown=False):
            if files:
                break
            try:
                os.rmdir(current)
            except OSError:
                break


def _roll_back(db: Database, journal: str, files: list[dict[str, Any]], reason: str) -> None:
    """Undo a copy the records never followed: delete the destination files
    this move made — a copy that was already there before it (`present`) is
    never touched — and any `.part` left half-written."""
    transfer.undo(_copies(files, "copy"))
    with db.write() as unit:
        unit.execute(
            "UPDATE animal_moves SET state = 'rolled-back', error = ?, updated_at = ? WHERE id = ?",
            (reason[:500], _now(), journal),
        )


def resume(db: Database) -> int:
    """Finish or undo every move a crash interrupted. Run once at start-up,
    before anything else may read or rescan the archive."""
    with db.read() as q:
        rows = q.execute(
            "SELECT id, source_cohort_id, state, plan_json FROM animal_moves"
            " WHERE state IN ('copying', 'committed')"
        ).fetchall()
        folders = {
            row[0]: row[1]
            for row in q.execute("SELECT id, data_folder FROM cohorts")
        }
    for row in rows:
        files = json.loads(row["plan_json"]).get("files", [])
        if row["state"] == "copying":
            log.warning("move %s was interrupted while copying; undoing the copy", row["id"])
            _roll_back(db, row["id"], files, "interrupted while copying")
        else:
            log.warning("move %s was interrupted after it committed; finishing it", row["id"])
            source = row["source_cohort_id"]
            _clean_up(db, row["id"], files, folders.get(source, ""), source)
    return len(rows)

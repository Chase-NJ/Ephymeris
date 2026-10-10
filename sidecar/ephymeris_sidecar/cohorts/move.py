"""Planning a move of animals between cohorts —
`DATA.md#moving-animals-between-cohorts`.

A cohort is its folder as much as its records: the two lab machines keep
separate databases over one shared archive, so the files are the only fact both
agree on. Moving an animal therefore moves **its files** into the destination's
data folder, and its run records, adoptions and notes with them, so its whole
history is the destination's and none of it is the source's.

This module only plans. It reads the database through a connection the caller
holds the lock for, and the disk through stats and hashes; it writes nothing.
`move_apply` carries a plan out, and re-plans inside its final transaction so a
roster edited between the preview and the apply cannot be acted on stale.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..sessions.models import GroupRun, Session
from ..sessions.tidy import session_key
from .folders import relative_below, resolved
from .models import Cohort, CohortNotFound

#: How a moved animal arrives. `joins` reuses a same-named animal the
#: destination already has — the split the lab did by hand, where cohort B was
#: given a new animal with the old name. `carried` keeps the animal's own id.
Outcome = Literal["joins", "carried"]
AnimalStatus = Literal["active", "former", "files"]

#: What happens to one file.
#: `copy` — there, and the destination slot is free: copied, verified, then the
#: original deleted. `present` — an identical copy is already at the
#: destination: only the original is deleted. `already` — gone here and present
#: there: the other lab machine moved it first, so only records follow.
FileAction = Literal["copy", "present", "already"]


@dataclass
class AnimalMove:
    source_id: str
    name: str
    status: AnimalStatus
    outcome: Outcome
    dest_id: str
    #: Where a carried animal lands: on the destination's roster in this group,
    #: or (a former member, or one known only from files) as a former member.
    dest_group_id: str | None
    dest_box: int | None
    runs: int = 0
    files: int = 0


@dataclass
class FileMove:
    src: str
    dst: str
    action: FileAction
    size: int
    sha256: str


@dataclass
class SessionMove:
    source: Session
    #: `whole`: only moved animals ran in it, so the record itself goes.
    #: `split`: animals that stay ran in it too, so the destination gets a
    #: record of its own and the shared notes are copied.
    kind: Literal["whole", "split"]
    dest_folder: str
    #: The destination's record with the same prefix, number and date, if it
    #: has one — runs join it rather than standing beside it.
    dest_session_id: str | None
    run_ids: list[str] = field(default_factory=list)
    notes_moved: list[str] = field(default_factory=list)
    notes_copied: list[str] = field(default_factory=list)
    #: The destination record's group runs, already in its groups.
    dest_group_runs: list[GroupRun] = field(default_factory=list)
    #: The source record's group runs after the move, for a split.
    source_group_runs: list[GroupRun] = field(default_factory=list)


@dataclass
class MovePlan:
    source: Cohort
    dest: Cohort
    animals: list[AnimalMove] = field(default_factory=list)
    sessions: list[SessionMove] = field(default_factory=list)
    #: Recorded run id → its new file path (None when it never had one).
    run_paths: dict[str, str | None] = field(default_factory=dict)
    #: Recorded run id → the animal id it takes.
    run_animals: dict[str, str] = field(default_factory=dict)
    #: Adopted run id → (new file path, the animal id it takes).
    adopted: dict[str, tuple[str, str]] = field(default_factory=dict)
    files: list[FileMove] = field(default_factory=list)
    #: Runs whose file is in neither place — moved as records, reported.
    missing: int = 0
    #: Synthetic (recovered-files-only) sessions touched, for the preview.
    recovered_sessions: int = 0
    refused: list[dict[str, str]] = field(default_factory=list)
    #: The destination group carried animals land in, and the group a session
    #: record is filed under when none of its moved animals has one.
    dest_group_id: str | None = None

    def refuse(self, code: str, message: str) -> None:
        # A file is met once as a run's and again by the walk for stray ones;
        # one reason is one line, however often it is found.
        entry = {"code": code, "message": message}
        if entry not in self.refused:
            self.refused.append(entry)

    def identity(self) -> Any:
        """What must not change between the preview and the apply: who moves,
        where, which runs and which files. File *actions* may — a copy made
        between the two is `present` on the second pass."""
        return (
            sorted((a.source_id, a.dest_id, a.outcome) for a in self.animals),
            sorted(self.run_paths.items(), key=lambda kv: kv[0]),
            sorted((k, v) for k, v in self.adopted.items()),
            sorted((f.src, f.dst, f.sha256) for f in self.files),
            sorted((s.source.id, s.kind, s.dest_session_id or "") for s in self.sessions),
        )

    def to_json(self, *, applied: bool) -> dict[str, Any]:
        moved_files = [f for f in self.files if f.action != "already"]
        return {
            "sourceCohortId": self.source.id,
            "destinationCohortId": self.dest.id,
            "applied": applied,
            "animals": [
                {
                    "animalId": a.source_id,
                    "name": a.name,
                    "status": a.status,
                    "outcome": a.outcome,
                    "destinationAnimalId": a.dest_id,
                    "runs": a.runs,
                    "files": a.files,
                }
                for a in self.animals
            ],
            "sessions": [
                {
                    "sessionId": s.source.id,
                    "label": f"{s.source.prefix_name}_{s.source.session_number}",
                    "date": s.source.date,
                    "kind": s.kind,
                    "joinsExisting": s.dest_session_id is not None,
                    "notesMoved": len(s.notes_moved),
                    "notesCopied": len(s.notes_copied),
                }
                for s in self.sessions
            ],
            "recoveredSessions": self.recovered_sessions,
            "files": {
                "count": len(moved_files),
                "bytes": sum(f.size for f in moved_files),
                "alreadyThere": sum(1 for f in self.files if f.action != "copy"),
                "missing": self.missing,
            },
            "refused": list(self.refused),
        }


@dataclass
class MoveRequest:
    source_id: str
    animal_ids: list[str]
    dest_id: str
    dest_group_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "animalIds": list(self.animal_ids),
            "destId": self.dest_id,
            "destGroupId": self.dest_group_id,
        }

    @staticmethod
    def from_json(raw: dict[str, Any]) -> "MoveRequest":
        return MoveRequest(
            source_id=str(raw["sourceId"]),
            animal_ids=[str(a) for a in raw["animalIds"]],
            dest_id=str(raw["destId"]),
            dest_group_id=raw.get("destGroupId"),
        )


# --- the planner ------------------------------------------------------------


def plan_move(
    conn: sqlite3.Connection, request: MoveRequest, *, busy: str | None = None
) -> MovePlan:
    """What moving `request.animal_ids` would do, and every reason it can't.

    `busy` is the caller's: a session the runner holds, or a box running,
    anywhere in the app. Copying a cohort's files competes with the
    write-ahead log's per-strobe fsync, so a move waits for the rig to be idle.
    """
    from .repository import CohortRepository  # the repository imports members

    source = CohortRepository._load_one(conn, request.source_id)
    dest = CohortRepository._load_one(conn, request.dest_id)
    if source is None:
        raise CohortNotFound(request.source_id)
    if dest is None:
        raise CohortNotFound(request.dest_id)

    plan = MovePlan(source=source, dest=dest)
    if busy:
        plan.refuse("busy", busy)
    if source.id == dest.id:
        plan.refuse("same-cohort", "Choose a different cohort to move to.")
        return plan
    if dest.archived:
        plan.refuse("archived", f"“{dest.name}” is archived. Restore it first.")
    if not request.animal_ids:
        plan.refuse("nothing", "Choose at least one animal to move.")
        return plan

    _plan_animals(plan, request)
    if plan.refused and any(r["code"] in ("unknown-animal", "bad-group") for r in plan.refused):
        return plan

    src_root = Path(source.data_folder).expanduser()
    dst_root = Path(dest.data_folder).expanduser()
    unreachable = [(c, r) for c, r in ((source, src_root), (dest, dst_root)) if not _is_dir(r)]
    for cohort, root in unreachable:
        plan.refuse(
            "folder-unreachable",
            f"“{cohort.name}”'s data folder can't be reached ({root}). Connect the drive and try again.",
        )
    if unreachable:
        return plan
    if _nested(src_root, dst_root):
        plan.refuse(
            "same-folder",
            "The two cohorts' data folders are the same folder, or one is inside the other, so "
            "nothing can be moved between them.",
        )
        return plan

    sessions = _sessions(conn, source.id)
    dest_sessions = _sessions(conn, dest.id)
    for session in [*sessions, *dest_sessions]:
        if session.status in ("configuring", "running"):
            owner = source if session.cohort_id == source.id else dest
            plan.refuse(
                "unfinished-session",
                f"{session.prefix_name}_{session.session_number} ({session.date}) in “{owner.name}” "
                "is still open. Close it out, or run Tidy records, first.",
            )

    moving = {a.source_id: a for a in plan.animals}
    _plan_sessions_and_runs(conn, plan, moving, sessions, dest_sessions, src_root, dst_root)
    _plan_unrecorded_files(plan, moving, src_root, dst_root)
    for animal in plan.animals:
        animal.files = sum(1 for f in plan.files if _file_animal(f, plan) == animal.source_id)
    return plan


def _plan_animals(plan: MovePlan, request: MoveRequest) -> None:
    source, dest = plan.source, plan.dest
    active = {a.id: a for a in source.animals}
    former = {f.id: f for f in source.former_animals}
    groups = sorted(dest.groups, key=lambda g: g.order)
    group_id = request.dest_group_id or (groups[0].id if groups else None)
    if group_id not in {g.id for g in dest.groups}:
        plan.refuse("bad-group", "That group isn't one of the destination cohort's.")
        return
    plan.dest_group_id = group_id

    dest_active = {a.name.casefold(): a for a in dest.animals}
    dest_former = {f.name.casefold(): f for f in dest.former_animals if f.name}
    seen: dict[str, str] = {}
    for animal_id in dict.fromkeys(request.animal_ids):
        if animal_id in active:
            name, status = active[animal_id].name, "active"
        elif animal_id in former:
            f = former[animal_id]
            if f.name is None:
                plan.refuse(
                    "unnamed",
                    "An animal with no name in its files can't be matched to anything, so it "
                    "can't be moved.",
                )
                continue
            name, status = f.name, ("former" if f.source == "removed" else "files")
        else:
            plan.refuse("unknown-animal", f"{animal_id} isn't an animal of “{source.name}”.")
            continue

        folded = name.casefold()
        if folded in seen:
            plan.refuse(
                "name-clash",
                f"“{seen[folded]}” and “{name}” would be the same animal in “{dest.name}”. "
                "Move them one at a time.",
            )
            continue
        seen[folded] = name

        if folded in dest_active:
            target = dest_active[folded]
            plan.animals.append(
                AnimalMove(animal_id, name, status, "joins", target.id, target.group_id, None)
            )
        elif folded in dest_former:
            target_former = dest_former[folded]
            plan.animals.append(
                AnimalMove(animal_id, name, status, "joins", target_former.id, None, None)
            )
        elif status == "active":
            mover = active[animal_id]
            taken = {
                a.box_number for a in dest.animals if a.group_id == group_id and a.box_number
            }
            box = mover.box_number if mover.box_number not in taken else None
            plan.animals.append(
                AnimalMove(animal_id, name, status, "carried", animal_id, group_id, box)
            )
        else:
            plan.animals.append(AnimalMove(animal_id, name, status, "carried", animal_id, None, None))


def _plan_sessions_and_runs(
    conn: sqlite3.Connection,
    plan: MovePlan,
    moving: dict[str, AnimalMove],
    sessions: list[Session],
    dest_sessions: list[Session],
    src_root: Path,
    dst_root: Path,
) -> None:
    runs = conn.execute(
        "SELECT r.id, r.session_id, r.animal_id, r.box_number, r.file_path, r.started_at"
        " FROM session_animal_runs r JOIN sessions s ON s.id = r.session_id"
        " WHERE s.cohort_id = ?",
        (plan.source.id,),
    ).fetchall()
    adopted = conn.execute(
        "SELECT id, animal_id, file_path, prefix_name, session_number, date"
        " FROM adopted_runs WHERE cohort_id = ?",
        (plan.source.id,),
    ).fetchall()
    by_session: dict[str, list[sqlite3.Row]] = {}
    for run in runs:
        by_session.setdefault(run["session_id"], []).append(run)
    adopted_by_key: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
    for entry in adopted:
        key = session_key(entry["prefix_name"], entry["session_number"], entry["date"] or "")
        adopted_by_key.setdefault(key, []).append(entry)
    dest_by_key = {
        session_key(s.prefix_name, s.session_number, s.date): s for s in dest_sessions
    }
    recorded_keys = set()

    for session in sessions:
        key = session_key(session.prefix_name, session.session_number, session.date)
        recorded_keys.add(key)
        own = by_session.get(session.id, [])
        attributed = adopted_by_key.get(key, [])
        moved = [r for r in own if r["animal_id"] in moving]
        moved_adopted = [a for a in attributed if a["animal_id"] in moving]
        if not moved and not moved_adopted:
            continue
        staying = [r for r in own if r["animal_id"] not in moving]
        staying_adopted = [a for a in attributed if a["animal_id"] not in moving]

        rel = _relative(session.folder_path, src_root)
        if rel is None:
            plan.refuse(
                "outside-folder",
                f"{session.prefix_name}_{session.session_number} ({session.date}) is recorded "
                f"outside “{plan.source.name}”'s data folder. Run Rescan first.",
            )
            continue
        dest_folder = str(dst_root / rel)
        existing = dest_by_key.get(key)
        if existing is not None and _norm(existing.folder_path) != _norm(dest_folder):
            plan.refuse(
                "session-folder",
                f"“{plan.dest.name}” already has {session.prefix_name}_{session.session_number} "
                f"({session.date}) in another folder ({existing.folder_path}).",
            )
            continue

        whole = not staying and not staying_adopted
        entry = SessionMove(
            source=session,
            kind="whole" if whole else "split",
            dest_folder=dest_folder,
            dest_session_id=existing.id if existing is not None else None,
            run_ids=[r["id"] for r in moved],
        )
        _plan_notes(conn, entry, moving, moved, staying, whole)
        _plan_group_runs(entry, moving, moved, staying, plan.dest_group_id)
        plan.sessions.append(entry)

    # Recovered-files-only sessions need no record: their runs group by folder.
    plan.recovered_sessions = sum(
        1
        for key, entries in adopted_by_key.items()
        if key not in recorded_keys and any(e["animal_id"] in moving for e in entries)
    )

    for run in runs:
        if run["animal_id"] not in moving:
            continue
        plan.run_animals[run["id"]] = moving[run["animal_id"]].dest_id
        moving[run["animal_id"]].runs += 1
        if not run["file_path"]:
            plan.run_paths[run["id"]] = None
            plan.missing += 1
            continue
        new_path = _plan_run_files(plan, run["file_path"], src_root, dst_root)
        plan.run_paths[run["id"]] = new_path
    for entry in adopted:
        if entry["animal_id"] not in moving:
            continue
        moving[entry["animal_id"]].runs += 1
        new_path = _plan_run_files(plan, entry["file_path"], src_root, dst_root)
        if new_path is not None:
            plan.adopted[entry["id"]] = (new_path, moving[entry["animal_id"]].dest_id)


def _plan_notes(
    conn: sqlite3.Connection,
    entry: SessionMove,
    moving: dict[str, AnimalMove],
    moved: list[sqlite3.Row],
    staying: list[sqlite3.Row],
    whole: bool,
) -> None:
    """Who keeps which note (`DATA.md#moving-animals-between-cohorts`).

    A note about a moved animal moves with it. A note about the whole session
    belongs to both halves of it, so it is copied. A note about a box follows
    the animals that used that box: only moved ones, it moves; only staying
    ones, it stays; both (a box reused across groups) or neither (a recovered
    run's box is unknown), it is copied.
    """
    rows = conn.execute(
        "SELECT id, scope_kind, animal_id, box_number, deleted_at FROM session_notes"
        " WHERE session_id = ?",
        (entry.source.id,),
    ).fetchall()
    if whole:
        entry.notes_moved = [r["id"] for r in rows]
        return
    moved_boxes = {r["box_number"] for r in moved}
    staying_boxes = {r["box_number"] for r in staying}
    for note in rows:
        kind = note["scope_kind"]
        if kind == "animal":
            if note["animal_id"] in moving:
                entry.notes_moved.append(note["id"])
            continue
        if note["deleted_at"]:
            continue  # hidden; it stays where it was written
        if kind == "box":
            box = note["box_number"]
            if box in moved_boxes and box not in staying_boxes:
                entry.notes_moved.append(note["id"])
            elif box in staying_boxes and box not in moved_boxes:
                continue
            else:
                entry.notes_copied.append(note["id"])
            continue
        entry.notes_copied.append(note["id"])


def _plan_group_runs(
    entry: SessionMove,
    moving: dict[str, AnimalMove],
    moved: list[sqlite3.Row],
    staying: list[sqlite3.Row],
    plan_group: str | None,
) -> None:
    """The destination record's group runs, and what the source keeps.

    A group run the moved animals ran in becomes one in each destination group
    they now belong to. Which ran in which is read from recorded start times
    only — a recovered run's start comes from its filename, local time, and is
    not comparable — and when none places them, one group run spans the
    source's whole day.
    """
    source = entry.source
    dest_groups = {
        moving[r["animal_id"]].dest_group_id for r in moved if moving[r["animal_id"]].dest_group_id
    }
    if not dest_groups:
        dest_groups = {plan_group} if plan_group else set()

    def inside(run: sqlite3.Row, group_run: GroupRun) -> bool:
        started = run["started_at"] or ""
        return group_run.started_at <= started and (
            group_run.ended_at is None or started <= group_run.ended_at
        )

    out: list[GroupRun] = []
    for group_run in source.group_runs:
        if any(inside(r, group_run) for r in moved):
            for group in sorted(dest_groups):
                out.append(GroupRun(group, 0, group_run.started_at, group_run.ended_at))
    if not out and source.group_runs:
        first = min(g.started_at for g in source.group_runs)
        ends = [g.ended_at for g in source.group_runs]
        last = None if any(e is None for e in ends) else max(e for e in ends if e)
        out = [GroupRun(group, 0, first, last) for group in sorted(dest_groups)]
    out.sort(key=lambda g: (g.started_at, g.group_id))
    entry.dest_group_runs = [
        GroupRun(g.group_id, index, g.started_at, g.ended_at) for index, g in enumerate(out)
    ]

    # The source keeps every group run some staying animal ran in. One only the
    # moved animals ran is theirs and goes — unless the session is a recording,
    # whose entries are per group run and must keep matching it.
    if source.recording is not None or entry.kind == "whole":
        entry.source_group_runs = list(source.group_runs)
        return
    kept = [
        g
        for g in source.group_runs
        if any(inside(r, g) for r in staying) or not any(inside(r, g) for r in moved)
    ]
    entry.source_group_runs = [
        GroupRun(g.group_id, index, g.started_at, g.ended_at) for index, g in enumerate(kept)
    ]


def _plan_run_files(plan: MovePlan, file_path: str, src_root: Path, dst_root: Path) -> str | None:
    """Plan every file of one run — its `.json`, `.tsv` and `.mat`, current or
    legacy spelling — and return the run's new primary path.

    The run identity is the stem (`reader.run_identity`), so the files of a
    run are the stem's entries in the session folder's format folders, here or
    — when another machine moved them first — already at the destination.
    """
    from ..analytics import reader  # analytics imports cohorts

    rel = _relative(file_path, src_root)
    if rel is None:
        already = _relative(file_path, dst_root)
        if already is not None:
            return str(dst_root / already)  # the record already points there
        plan.refuse(
            "outside-folder",
            f"{Path(file_path).name} is outside “{plan.source.name}”'s data folder. "
            "Run Rescan first.",
        )
        return None
    src = src_root / rel
    dst = dst_root / rel
    identity = reader.run_identity(src)
    src_session = reader.session_folder_of(src)
    dst_session = reader.session_folder_of(dst)
    names: set[tuple[str, str]] = set()
    for session_folder in (src_session, dst_session):
        for fmt in reader.FORMAT_DIRS:
            folder = session_folder / fmt
            try:
                children = list(folder.iterdir()) if folder.is_dir() else []
            except OSError:
                children = []
            for child in children:
                if (
                    child.is_file()
                    and not reader.is_sidecar_file(child)
                    and reader.run_identity(child) == identity
                ):
                    names.add((fmt, child.name))
    found_primary = False
    for fmt, name in sorted(names):
        before = len(plan.files)
        _plan_file(plan, src_session / fmt / name, dst_session / fmt / name)
        if len(plan.files) > before and _norm(str(src_session / fmt / name)) == _norm(str(src)):
            found_primary = True
    if not found_primary and not any(
        _norm(f.dst) == _norm(str(dst)) for f in plan.files
    ):
        plan.missing += 1
    return str(dst)


def _plan_unrecorded_files(
    plan: MovePlan, moving: dict[str, AnimalMove], src_root: Path, dst_root: Path
) -> None:
    """Files in the source naming a moved animal that no record points at — a
    crash's lone `.tsv`, a second copy of a legacy run. History is the files as
    much as the records, so they move too. Never a file whose name an animal
    staying on the source's roster now holds: that name is that animal's."""
    from ..analytics import reader  # analytics imports cohorts

    names = {a.name.casefold() for a in moving.values()}
    staying = {a.name.casefold() for a in plan.source.animals if a.id not in moving}
    names -= staying
    if not names:
        return
    planned = {_norm(f.src) for f in plan.files}
    for folder, filenames in reader._walk_format_dirs(src_root):
        for filename in sorted(filenames):
            path = folder / filename
            if reader.is_sidecar_file(path) or _norm(str(path)) in planned:
                continue
            token = reader.animal_token(path)
            if token is None or token.casefold() not in names:
                continue
            rel = _relative(str(path), src_root)
            if rel is None:  # pragma: no cover - the walk is under the root
                continue
            _plan_file(plan, path, dst_root / rel)


def _plan_file(plan: MovePlan, src: Path, dst: Path) -> None:
    if any(_norm(f.src) == _norm(str(src)) for f in plan.files):
        return
    src_hash = _digest(src)
    dst_hash = _digest(dst)
    if src_hash is not None and dst_hash is None:
        action: FileAction = "copy"
        size, digest = src_hash
    elif src_hash is not None and dst_hash is not None:
        if src_hash[1] != dst_hash[1]:
            plan.refuse(
                "collision",
                f"{dst} already exists in “{plan.dest.name}” and differs from the file being "
                "moved. Nothing has been changed.",
            )
            return
        action, (size, digest) = "present", src_hash
    elif dst_hash is not None:
        action, (size, digest) = "already", dst_hash
    else:
        return
    plan.files.append(FileMove(str(src), str(dst), action, size, digest))


def _file_animal(f: FileMove, plan: MovePlan) -> str | None:
    """Which moved animal a file is, by its stem — for the preview's counts."""
    from ..analytics import reader  # analytics imports cohorts

    token = reader.animal_token(Path(f.src))
    if token is None:
        return None
    folded = token.casefold()
    return next((a.source_id for a in plan.animals if a.name.casefold() == folded), None)


# --- helpers ----------------------------------------------------------------


def _sessions(conn: sqlite3.Connection, cohort_id: str) -> list[Session]:
    from ..sessions.repository import SessionRepository

    rows = conn.execute(
        "SELECT * FROM sessions WHERE cohort_id = ? ORDER BY date, started_at", (cohort_id,)
    ).fetchall()
    return [SessionRepository._hydrate(row) for row in rows]


def _digest(path: Path) -> tuple[int, str] | None:
    """Size and SHA-256, or None when there is nothing readable there."""
    try:
        if not path.is_file():
            return None
        h = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                h.update(chunk)
                size += len(chunk)
        return size, h.hexdigest()
    except OSError:
        return None


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _resolved(path: str | Path) -> Path:
    return resolved(path)


def _norm(path: str) -> str:
    return str(_resolved(path)).casefold()


_relative = relative_below


def _nested(a: Path, b: Path) -> bool:
    ra = [p.casefold() for p in _resolved(a).parts]
    rb = [p.casefold() for p in _resolved(b).parts]
    shorter = min(len(ra), len(rb))
    return ra[:shorter] == rb[:shorter]


def plan_files_json(plan: MovePlan) -> str:
    """The journal's copy of the file half — what a restart needs to finish or
    undo the copy without re-planning against a database it can't trust yet."""
    return json.dumps(
        [
            {"src": f.src, "dst": f.dst, "action": f.action, "size": f.size, "sha256": f.sha256}
            for f in plan.files
        ]
    )

"""Tidying a cohort's session records — `data.md` §8.8.

Two kinds of leftover pile up when a day goes wrong:

* **Split records.** Before groups could be chosen on the fly, closing the app
  between groups (or ending a session too early) left the operator starting a
  *second* session under the same number to finish the day. Both records write
  into the one folder — the folder name is `<prefix>_<number>_<date>` — and
  Analytics shows the day twice. They are merged into the earliest record.
* **Empty records.** A set-up nobody started, a session closed out before a box
  ran, an abandoned one: rows with no run, no recording and no file behind
  them. They are deleted, with their folder when it holds nothing.

Everything here is planning, and pure: it is handed the facts (the rows, their
run counts, what each folder holds) and returns what to do. Applying the plan is
the analytics service's (`AnalyticsService.tidy`), under the same lock a rescan
takes, and **it only ever changes the database** — a merge moves run records
between session rows and never touches a data file, and a folder is removed
only when it contains no file at all. Records are merged only when they share
prefix, number and date, which is exactly when they share a folder, so no file
ever ends up belonging to a session whose folder it is not in.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from ..cohorts.folders import sanitize_name
from .models import GroupRun, Session

#: What a folder holds, as far as the planner can honestly say. `None` is
#: "unreachable" — an unmounted drive — and is never read as empty.
FolderState = bool | None


def session_key(prefix_name: str, session_number: str, date: str) -> tuple[str, str, str]:
    """The identity two records share when they write into the same folder.

    Folded through `sanitize_name` because that is what the folder name is
    built from (`paths.session_folder_name`) — two spellings that make one
    folder are one session — and case-folded because the lab machines'
    filesystem is case-insensitive.
    """
    return (
        sanitize_name(prefix_name).casefold(),
        sanitize_name(session_number.strip()).casefold(),
        date,
    )


@dataclass
class Merge:
    keep: Session
    absorb: list[Session]


@dataclass
class Empty:
    session: Session
    #: Whether the folder exists and holds no file, so it goes too.
    removes_folder: bool


@dataclass
class Skipped:
    session: Session
    reason: str


@dataclass
class TidyPlan:
    merges: list[Merge] = field(default_factory=list)
    empty: list[Empty] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.merges or self.empty)


def plan(
    sessions: Iterable[Session],
    *,
    run_counts: dict[str, int],
    folder_state: Callable[[str], FolderState],
    protect: set[str],
    today: str,
) -> TidyPlan:
    """What a tidy would do to these records.

    `run_counts` counts every run a record owns — recorded runs, and recovered
    files attributed to it (`service._adoption_owners`). `protect` holds the
    session the runner is holding; a group containing it is left whole, since
    moving runs under a live session could strand what it is about to write.

    **Today's set-ups are protected too.** A `configuring` record exists from
    the moment Step 1 creates it, well before the mapping holds the rig, so one
    created today may be sitting under an operator's hands. An older one is an
    abandoned set-up, and fair game.
    """
    result = TidyPlan()
    groups: dict[tuple[str, str, str], list[Session]] = {}
    for session in sorted(sessions, key=lambda s: (s.date, s.started_at, s.id)):
        groups.setdefault(
            session_key(session.prefix_name, session.session_number, session.date), []
        ).append(session)

    def guarded(session: Session) -> str | None:
        if session.id in protect:
            return "in progress"
        if session.status == "configuring" and session.date == today:
            return "set-up started today"
        return None

    def has_data(session: Session) -> bool:
        recording = session.recording or {}
        return run_counts.get(session.id, 0) > 0 or bool(recording.get("runs"))

    for members in groups.values():
        reasons = {m.id: guarded(m) for m in members}
        if any(reasons.values()):
            # Leave the whole group alone — but say so only where there was
            # something to do, so a lone live session is not reported.
            if len(members) > 1:
                for member in members:
                    result.skipped.append(
                        Skipped(member, reasons[member.id] or "shares a folder with a session in use")
                    )
            continue

        states = {m.id: folder_state(m.folder_path) for m in members}
        empties = [m for m in members if not has_data(m) and states[m.id] is False]

        if len(empties) == len(members):
            # Nothing anywhere: every record goes, and the folder with them.
            for member in members:
                result.empty.append(Empty(member, removes_folder=_folder_exists(member)))
            continue

        if len(members) > 1:
            # The earliest record that holds something is the day's session;
            # failing that (the files are on disk but no record points at them
            # yet), simply the earliest.
            with_data = [m for m in members if has_data(m)]
            keep = (with_data or members)[0]
            result.merges.append(Merge(keep, [m for m in members if m is not keep]))
            continue

        # A lone record: empty or left alone. An unreachable folder (`None`)
        # is never empty — it is somewhere the planner cannot see.
        if empties:
            result.empty.append(Empty(members[0], removes_folder=_folder_exists(members[0])))

    return result


def _folder_exists(session: Session) -> bool:
    from pathlib import Path

    try:
        return Path(session.folder_path).expanduser().is_dir()
    except OSError:
        return False


def merged_fields(merge: Merge) -> dict[str, Any]:
    """The kept record after absorbing the others.

    * **Group runs** from every record, in the order they started, renumbered —
      the order a group ran in is the order it started in.
    * **Recording runs** likewise; a session is a recording if any part was.
    * **started_at** the earliest, **ended_at** the latest, so the record spans
      the whole day it now stands for.
    * **completed** — every record merged is closed by construction (a live one
      protects its group), and a crash-orphaned `running` record is what a
      tidy exists to close out. A same-day completed session can still be
      continued with another group (`sessions.resume`).
    """
    everyone = [merge.keep, *merge.absorb]
    runs: list[GroupRun] = sorted(
        (run for s in everyone for run in s.group_runs), key=lambda r: r.started_at
    )
    runs = [replace(run, order=index) for index, run in enumerate(runs)]

    recording: dict[str, Any] | None = None
    if any(s.recording is not None for s in everyone):
        recorded = sorted(
            (run for s in everyone for run in (s.recording or {}).get("runs", [])),
            key=lambda run: str(run.get("startedAt", "")),
        )
        recording = {**(merge.keep.recording or {}), "runs": recorded}

    ended = [s.ended_at for s in everyone if s.ended_at]
    return {
        "group_runs": runs,
        "recording": recording,
        "started_at": min(s.started_at for s in everyone),
        "ended_at": max(ended) if ended else None,
        "status": "completed",
    }


def session_json(session: Session, run_count: int) -> dict[str, Any]:
    """The `TidySession` wire shape — enough for the operator to recognise it."""
    return {
        "sessionId": session.id,
        "label": f"{session.prefix_name}_{session.session_number}",
        "date": session.date,
        "status": session.status,
        "startedAt": session.started_at,
        "runCount": run_count,
        "groupIds": [run.group_id for run in session.group_runs],
    }


def plan_json(
    tidy: TidyPlan, run_counts: dict[str, int], *, cohort_id: str, applied: bool
) -> dict[str, Any]:
    def one(session: Session) -> dict[str, Any]:
        return session_json(session, run_counts.get(session.id, 0))

    return {
        "cohortId": cohort_id,
        "applied": applied,
        "merges": [
            {"keep": one(m.keep), "absorb": [one(s) for s in m.absorb]} for m in tidy.merges
        ],
        "empty": [
            {"session": one(e.session), "removesFolder": e.removes_folder} for e in tidy.empty
        ],
        "skipped": [{"session": one(s.session), "reason": s.reason} for s in tidy.skipped],
    }

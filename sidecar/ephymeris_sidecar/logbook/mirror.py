"""The session folder's `notes.md` — `DATA.md#the-notesmd-mirror`.

A plain-text copy of the session log written next to the data it describes, so
the notes travel with the folder: to the backup mirror, to a colleague's
machine, to whoever opens the archive in ten years without Ephymeris. The
database stays the source of truth; this file is derived from it, rewritten
whole on every change, and never read back.

`render_markdown` is pure. `write_mirror` is the only part that touches disk,
and it never raises: a failure is logged and costs only a stale copy.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from ..sessions.models import Session
from .models import SessionLog, SessionNote, offset_ms, parse_iso

log = logging.getLogger(__name__)

FILENAME = "notes.md"

TAG_LABELS = {
    "observation": "Observation",
    "intervention": "Intervention",
    "hardware": "Hardware",
    "animal-health": "Animal health",
    "protocol-deviation": "Protocol deviation",
}


def clock(value: str | None) -> str:
    """Local wall-clock `HH:MM:SS` — the lab's time, not UTC."""
    moment = parse_iso(value)
    return moment.astimezone().strftime("%H:%M:%S") if moment else "—"


def duration(seconds: float) -> str:
    whole = max(0, int(seconds))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def offset_label(ms: int | None) -> str:
    return "" if ms is None else f"T+{duration(ms / 1000)}"


def _scope(note: SessionNote, names: dict[str, str]) -> str:
    if note.scope_kind == "animal" and note.animal_id:
        return names.get(note.animal_id, note.animal_id)
    if note.scope_kind == "box" and note.box_number is not None:
        return f"Box {note.box_number}"
    return "Session"


def _value(value: Any) -> str:
    return "—" if value is None else f"`{value}`"


def change_lines(changes: Iterable[dict[str, Any]], names: dict[str, str]) -> list[str]:
    lines = []
    for change in changes:
        box = "recovered" if change["box"] is None else f"box {change['box']}"
        who = f"{names.get(change['animalId'], change['animalId'])} ({box})"
        if change.get("falseStart"):
            # Listed, not compared (`DATA.md#false-starts`).
            how = "marked by hand" if change.get("falseStartSource") == "marked" else "restarted"
            lines.append(f"- **{who}**: false start, set aside ({how})")
            continue
        parts = []
        if change["first"]:
            parts.append(f"first run — {change['task']}")
        if change.get("taskChange"):
            before, after = change["taskChange"]["from"], change["taskChange"]["to"]
            parts.append(
                f"task definition revised ({after})" if before == after else f"task {before} → {after}"
            )
        if change.get("boxChange"):
            parts.append(f"box {change['boxChange']['from']} → {change['boxChange']['to']}")
        # As on screen (`lib/logbook/changes.ts`): changed values in full, a
        # setting only one side has counted — across a task change most are.
        params = change.get("params", [])
        added = [p["key"] for p in params if p["from"] is None and p["to"] is not None]
        dropped = [p["key"] for p in params if p["from"] is not None and p["to"] is None]
        for param in params:
            if param["key"] in added or param["key"] in dropped:
                continue
            parts.append(f"{param['key']} {_value(param['from'])} → {_value(param['to'])}")
        for keys, what in ((added, "new"), (dropped, "dropped")):
            if keys:
                parts.append(
                    f"{', '.join(keys)} {what}" if len(keys) <= 3 else f"{len(keys)} settings {what}"
                )
        if parts:
            lines.append(f"- **{who}**: " + "; ".join(parts))
    return lines


def render_markdown(
    *,
    cohort_name: str,
    sessions: list[Session],
    logs: list[SessionLog],
    notes: list[SessionNote],
    changes: list[dict[str, Any]],
    animal_names: dict[str, str],
    now: datetime,
) -> str:
    """One folder's log. `sessions` are every record sharing the folder."""
    ordered = sorted(sessions, key=lambda s: (s.clock_started_at, s.id))
    first = ordered[0]
    start = first.clock_started_at
    ends = [s.clock_ended_at for s in ordered]
    end = max(e for e in ends if e) if ends and all(ends) else None
    start_at, end_at = parse_iso(start), parse_iso(end)
    elapsed = (
        duration((end_at - start_at).total_seconds())
        if start_at is not None and end_at is not None
        else "in progress"
    )

    title = f"{first.prefix_name}_{first.session_number}"
    out = [f"# {title} · {first.date}", ""]
    if cohort_name:
        out += [f"Cohort **{cohort_name}**", ""]
    out += [
        "| Started | Ended | Elapsed |",
        "|---|---|---|",
        f"| {clock(start)} | {clock(end)} | {elapsed} |",
        "",
    ]

    operators = [entry.operator for entry in logs if entry.operator]
    if operators:
        out += [f"Operator: {', '.join(dict.fromkeys(operators))}", ""]
    summaries = [entry.summary for entry in logs if entry.summary]
    if summaries:
        out += ["## Summary", "", *("\n\n".join(summaries).splitlines()), ""]

    lines = change_lines(changes, animal_names)
    unknown = sum(
        1 for c in changes
        if not c["first"] and not c.get("falseStart") and not c.get("paramsKnown", True)
    )
    if unknown:
        lines.append(
            f"_Parameters aren't on record for {unknown} of these runs, so only the task "
            "is compared for them._"
        )
    if lines:
        out += ["## What changed", "", *lines, ""]

    by_id = {s.id: s for s in ordered}
    out += ["## Notes", ""]
    if not notes:
        out += ["_No notes._", ""]
    for note in sorted(notes, key=lambda n: (n.at, n.created_at)):
        owner = by_id.get(note.session_id)
        offset = (
            offset_ms(note.at, owner.clock_started_at, owner.clock_ended_at, now)
            if owner is not None
            else None
        )
        stamp = " · ".join(
            part
            for part in (offset_label(offset), clock(note.at), TAG_LABELS.get(note.tag, note.tag))
            if part
        )
        flags = []
        if note.carry_forward:
            flags.append("resolved" if note.resolved_at else "carry forward")
        if note.edited_at:
            flags.append("edited")
        suffix = f" _({', '.join(flags)})_" if flags else ""
        body = note.body.strip().replace("\n", "\n  ")
        out += [f"- **{stamp}** — {_scope(note, animal_names)}{suffix}", f"  {body}"]
    out += [
        "",
        "---",
        "",
        "_Written by Ephymeris from its session log. Edits here are not read "
        "back; change notes in the app's Log tab. Times are local._",
        "",
    ]
    return "\n".join(out)


def write_mirror(folder: Path, text: str) -> Path | None:
    """Write `notes.md` atomically; `None` when unchanged or on any failure.

    Creates the session folder itself if only it is missing (a session noted
    before its first box wrote anything), but never a parent: a missing prefix
    folder means an unmounted or moved archive, and recreating its path on
    whatever drive is mounted now would scatter notes away from their data.
    """
    target = folder / FILENAME
    part = folder / f"{FILENAME}.part"
    try:
        if target.is_file() and target.read_text(encoding="utf-8") == text:
            return None
        folder.mkdir(exist_ok=True)
        part.write_text(text, encoding="utf-8", newline="\n")
        os.replace(part, target)
        return target
    except OSError as exc:
        log.warning("logbook: couldn't write %s (%s); the database copy is intact", target, exc)
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        return None

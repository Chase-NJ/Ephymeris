"""The session log's data model — `DATA.md#the-session-log`.

`to_json` produces exactly the payload shapes documented in
`PROTOCOL.md#shape-sessionnote` and `PROTOCOL.md#shape-sessionlog`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

NoteTag = Literal["observation", "intervention", "hardware", "animal-health", "protocol-deviation"]
ScopeKind = Literal["session", "animal", "box"]

NOTE_TAGS: tuple[str, ...] = (
    "observation",
    "intervention",
    "hardware",
    "animal-health",
    "protocol-deviation",
)
SCOPE_KINDS: tuple[str, ...] = ("session", "animal", "box")

#: Generous for a lab note, small enough that a pasted log file is refused
#: rather than written into the database and every PDF.
MAX_BODY = 20_000
MAX_FIELD = 4_000


@dataclass
class SessionNote:
    id: str
    session_id: str
    cohort_id: str
    at: str
    created_at: str
    tag: str
    body: str
    scope_kind: str = "session"
    animal_id: str | None = None
    box_number: int | None = None
    edited_at: str | None = None
    deleted_at: str | None = None
    carry_forward: bool = False
    resolved_at: str | None = None
    resolved_in_session: str | None = None

    def to_json(self, offset_ms: int | None) -> dict[str, Any]:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "cohortId": self.cohort_id,
            "at": self.at,
            "createdAt": self.created_at,
            "editedAt": self.edited_at,
            "tag": self.tag,
            "scope": {
                "kind": self.scope_kind,
                "animalId": self.animal_id,
                "box": self.box_number,
            },
            "body": self.body,
            "offsetMs": offset_ms,
            "carryForward": self.carry_forward,
            "resolvedAt": self.resolved_at,
            "resolvedInSessionId": self.resolved_in_session,
        }


@dataclass
class SessionLog:
    session_id: str
    operator: str | None = None
    summary: str | None = None
    updated_at: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "operator": self.operator,
            "summary": self.summary,
            "updatedAt": self.updated_at,
        }

    @property
    def is_blank(self) -> bool:
        return not (self.operator or "").strip() and not (self.summary or "").strip()


class NoteNotFound(Exception):
    pass


class NoteInvalid(Exception):
    pass


def parse_iso(value: str | None) -> datetime | None:
    """An ISO timestamp, or `None` for absent or unreadable — never raises."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def offset_ms(at: str, clock_start: str, clock_end: str | None, now: datetime) -> int | None:
    """A note's offset into its session's clock (`DATA.md#the-session-clock`).

    Only for a note whose moment falls inside the session's running window —
    a note written the morning after, about the session, has no T+ and must
    not claim one. An open session's window runs to `now`.
    """
    moment, start = parse_iso(at), parse_iso(clock_start)
    if moment is None or start is None:
        return None
    end = parse_iso(clock_end) if clock_end else now
    if end is None or moment < start or moment > end:
        return None
    return int((moment - start).total_seconds() * 1000)


def merge_logs(keep_id: str, logs: list[SessionLog]) -> SessionLog | None:
    """The kept session's log after a tidy merge (`DATA.md#tidy-records`).

    `logs` is every merged record's log, the kept record's first and the rest
    in record order. The operator is the first one given; summaries are joined
    in that order so nothing anyone wrote is lost. `None` when nobody wrote
    anything.
    """
    everyone = [log for log in logs if not log.is_blank]
    if not everyone:
        return None
    operator = next((log.operator for log in everyone if (log.operator or "").strip()), None)
    summaries = [log.summary.strip() for log in everyone if (log.summary or "").strip()]
    updated = max((log.updated_at for log in everyone if log.updated_at), default=None)
    return SessionLog(
        session_id=keep_id,
        operator=operator,
        summary="\n\n".join(summaries) or None,
        updated_at=updated,
    )

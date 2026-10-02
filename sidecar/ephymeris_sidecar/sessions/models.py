"""Session data model — `DATA.md#sessions-and-runs`.

`to_json` produces exactly the payload shapes documented in
`PROTOCOL.md#shape-session` and `PROTOCOL.md#shape-prefix`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SessionStatus = Literal["configuring", "running", "completed", "aborted"]


@dataclass(frozen=True)
class Prefix:
    id: str
    name: str

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name}


@dataclass
class GroupRun:
    group_id: str
    order: int
    started_at: str
    ended_at: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "groupId": self.group_id,
            "order": self.order,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "GroupRun":
        return cls(
            group_id=str(raw.get("groupId", "")),
            order=int(raw.get("order", 0)),
            started_at=str(raw.get("startedAt", "")),
            ended_at=raw.get("endedAt"),
        )


@dataclass
class Session:
    id: str
    cohort_id: str
    prefix_id: str
    prefix_name: str
    session_number: str
    date: str
    started_at: str
    status: SessionStatus
    folder_path: str
    ended_at: str | None = None
    group_runs: list[GroupRun] = field(default_factory=list)
    #: Per-box time limit in whole minutes (`ARCHITECTURE.md#configuration`);
    #: None means the session runs until stopped by the operator or board.
    duration_minutes: int | None = None
    #: Set when the session is also an Intan recording (`RECORDING.md#what-is-written`):
    #: `{"runs": [...]}`, one entry per group run. None = behavior only. Kept as
    #: the JSON it is stored as -- nothing in the sidecar branches on its
    #: contents, only on its presence.
    recording: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cohortId": self.cohort_id,
            "prefixId": self.prefix_id,
            "prefixName": self.prefix_name,
            "sessionNumber": self.session_number,
            "date": self.date,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "status": self.status,
            "folderPath": self.folder_path,
            "groupRuns": [g.to_json() for g in self.group_runs],
            "durationMinutes": self.duration_minutes,
            "recording": self.recording,
        }

    def to_list_item(self, ordinal: int, run_count: int | None = None) -> dict[str, Any]:
        """The `SessionListItem` wire shape — the one listing form shared by
        `sessions.list` and `analytics.summary`.

        `ordinal` is the 1-based chronological position from (date, startedAt)
        — never from `session_number`, which is free text and would sort "10"
        before "9".
        """
        item = {
            "id": self.id,
            "cohortId": self.cohort_id,
            "prefixName": self.prefix_name,
            "sessionNumber": self.session_number,
            "date": self.date,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "status": self.status,
            "folderPath": self.folder_path,
            "ordinal": ordinal,
            "groupRuns": [g.to_json() for g in self.group_runs],
        }
        if run_count is not None:
            item["runCount"] = run_count
        return item


@dataclass
class SessionAnimalRun:
    id: str
    session_id: str
    animal_id: str
    box_number: int
    sketch_path: str
    started_at: str
    file_path: str | None = None
    ended_at: str | None = None
    stop_reason: str | None = None
    #: The Task Profile this run actually used (`DATA.md#run-records`). `None`
    #: for runs recorded before snapshotting existed — which is exactly the
    #: flag Analytics needs to mark them decoded with a possibly-changed
    #: profile, so it is meaningful rather than merely absent.
    profile_hash: str | None = None
    #: The task parameters this run actually ran on (`TASKS.md#profile-and-params-hashes`),
    #: keyed by `metadataKey`, and a hash of them. `profile_hash` covers the
    #: profile DECLARATION only, so two runs of one sketch on wildly different
    #: parameters hash identically — which stopped being a safe assumption the
    #: moment those parameters became operator-set. `None` on runs recorded
    #: before this existed, which is honest: they ran on firmware constants.
    config: dict[str, Any] | None = None
    params_hash: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "animalId": self.animal_id,
            "boxNumber": self.box_number,
            "sketchPath": self.sketch_path,
            "filePath": self.file_path,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "stopReason": self.stop_reason,
            "profileHash": self.profile_hash,
            "config": self.config,
            "paramsHash": self.params_hash,
        }


class PrefixNameTaken(Exception):
    pass


class SessionNotFound(Exception):
    pass


class SessionInvalid(Exception):
    def __init__(self, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.detail = detail

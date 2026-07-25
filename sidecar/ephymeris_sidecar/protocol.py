"""Canonical wire protocol between the frontend and this sidecar.

`docs/websocket-protocol.md` is the source of truth; this module and
`src/lib/ws/protocol.ts` are hand-maintained mirrors of it. `tests/test_protocol_contract.py`
asserts the two mirrors agree on command and event names.

Envelope shapes:

    client -> server   {"v", "id", "cmd", "args"}
    server -> client   {"v", "corr", "ok": true,  "result"}      (reply)
                       {"v", "corr", "ok": false, "error"}       (reply)
                       {"v", "evt", "ts", "data", "corr"?}       (event)
"""

from __future__ import annotations

import time
from typing import Any, Final

PROTOCOL_VERSION: Final = 1


# --- Commands (client -> server) ------------------------------------------

class Cmd:
    AUTH: Final = "auth"
    PING: Final = "ping"
    SETTINGS_PUSH: Final = "settings.push"
    SKETCHES_REFRESH: Final = "sketches.refresh"
    PORT_PASSTHROUGH_OPEN: Final = "port.passthrough.open"
    PORT_PASSTHROUGH_CLOSE: Final = "port.passthrough.close"
    PORT_SEND: Final = "port.send"
    PORT_FLASH: Final = "port.flash"
    PORT_RESET: Final = "port.reset"
    PORT_ERROR_ACK: Final = "port.error.ack"

    # Cohorts (cohorts.md §10, merged into websocket-protocol.md §3.1)
    COHORTS_LIST: Final = "cohorts.list"
    COHORTS_GET: Final = "cohorts.get"
    COHORTS_CREATE: Final = "cohorts.create"
    COHORTS_UPDATE: Final = "cohorts.update"
    COHORTS_ARCHIVE: Final = "cohorts.archive"
    COHORTS_RESTORE: Final = "cohorts.restore"
    COHORTS_DELETE: Final = "cohorts.delete"
    COHORTS_SET_DATA_FOLDER: Final = "cohorts.setDataFolder"
    COHORTS_SUGGEST_GROUPS: Final = "cohorts.suggestGroups"

    # Prefixes, task profiles, sessions
    # (data-saving.md §9 + starting-a-session.md §9, merged into
    # websocket-protocol.md §3.2)
    PREFIXES_LIST: Final = "prefixes.list"
    PREFIXES_CREATE: Final = "prefixes.create"
    PREFIXES_DELETE: Final = "prefixes.delete"
    TASKS_GET_PROFILE: Final = "tasks.getProfile"
    SESSIONS_SUGGEST_NUMBER: Final = "sessions.suggestNumber"
    SESSIONS_CREATE: Final = "sessions.create"
    SESSIONS_ABANDON: Final = "sessions.abandon"
    SESSIONS_CONFIRM_MAPPING: Final = "sessions.confirmMapping"
    SESSIONS_STATUS: Final = "sessions.status"
    SESSIONS_START_ALL: Final = "sessions.startAll"
    SESSIONS_SWITCH_GROUP: Final = "sessions.switchGroup"
    SESSIONS_END: Final = "sessions.end"
    PORT_START_SESSION: Final = "port.startSession"
    PORT_STOP_SESSION: Final = "port.stopSession"


ALL_COMMANDS: Final[frozenset[str]] = frozenset(
    v for k, v in vars(Cmd).items() if not k.startswith("_") and isinstance(v, str)
)


# --- Events (server -> client) --------------------------------------------

class Evt:
    SERVER_HELLO: Final = "server.hello"
    PORT_STATE: Final = "port.state"
    PORT_OUTPUT: Final = "port.output"
    BOARDS_PRESENCE: Final = "boards.presence"
    FLASH_PROGRESS: Final = "flash.progress"
    SKETCHES_UPDATED: Final = "sketches.updated"
    COHORTS_UPDATED: Final = "cohorts.updated"
    PREFIXES_UPDATED: Final = "prefixes.updated"
    SESSION_TELEMETRY: Final = "session.telemetry"
    SESSION_ANIMAL_ENDED: Final = "session.animalEnded"
    SIDECAR_ERROR: Final = "sidecar.error"


ALL_EVENTS: Final[frozenset[str]] = frozenset(
    v for k, v in vars(Evt).items() if not k.startswith("_") and isinstance(v, str)
)


# --- Error codes ----------------------------------------------------------

class ErrCode:
    BAD_MESSAGE: Final = "BAD_MESSAGE"
    UNKNOWN_COMMAND: Final = "UNKNOWN_COMMAND"
    UNAUTHORIZED: Final = "UNAUTHORIZED"
    PROTOCOL_VERSION_MISMATCH: Final = "PROTOCOL_VERSION_MISMATCH"
    ILLEGAL_TRANSITION: Final = "ILLEGAL_TRANSITION"
    SEND_NOT_PASSTHROUGH: Final = "SEND_NOT_PASSTHROUGH"
    PORT_NOT_BOUND: Final = "PORT_NOT_BOUND"
    PORT_OPEN_FAILED: Final = "PORT_OPEN_FAILED"
    FLASH_FAILED: Final = "FLASH_FAILED"
    SKETCH_UNKNOWN: Final = "SKETCH_UNKNOWN"
    COHORT_NOT_FOUND: Final = "COHORT_NOT_FOUND"
    COHORT_NAME_TAKEN: Final = "COHORT_NAME_TAKEN"
    COHORT_INVALID: Final = "COHORT_INVALID"
    COHORT_NOT_ARCHIVED: Final = "COHORT_NOT_ARCHIVED"
    DATA_FOLDER_INVALID: Final = "DATA_FOLDER_INVALID"
    PREFIX_NAME_TAKEN: Final = "PREFIX_NAME_TAKEN"
    SESSION_INVALID: Final = "SESSION_INVALID"
    SESSION_NOT_READY: Final = "SESSION_NOT_READY"
    TASK_PROFILE_INVALID: Final = "TASK_PROFILE_INVALID"
    DIR_INVALID: Final = "DIR_INVALID"
    INTERNAL: Final = "INTERNAL"


ALL_ERROR_CODES: Final[frozenset[str]] = frozenset(
    v for k, v in vars(ErrCode).items() if not k.startswith("_") and isinstance(v, str)
)


# --- Envelope builders ----------------------------------------------------

def reply_ok(corr: str, result: Any = None) -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "corr": corr, "ok": True, "result": result}


def reply_err(
    corr: str, code: str, message: str, detail: Any = None
) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION,
        "corr": corr,
        "ok": False,
        "error": {"code": code, "message": message, "detail": detail},
    }


def event(name: str, data: Any = None, corr: str | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "v": PROTOCOL_VERSION,
        "evt": name,
        "ts": time.time(),
        "data": data,
    }
    if corr is not None:
        msg["corr"] = corr
    return msg

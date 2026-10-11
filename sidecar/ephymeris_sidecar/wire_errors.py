"""Every exception a command can raise, and the error reply it becomes
(`ARCHITECTURE.md#dispatch`).

ONE TABLE. Domain modules raise their own exceptions and know nothing of the
wire; this is the only module that imports both them and `ErrCode`, and the
server answers every handler's exception from it. The first entry whose type
matches and whose mapper answers wins, so a subclass goes above its base. An
exception nothing here answers is reported as INTERNAL and logged.

`args` are the command's own, already checked against the schema. A mapper
reads the box from the exception when it carries one and from `args`
otherwise, so a port refusal names its box however it was reached.
"""

from __future__ import annotations

from typing import Any

from .analytics import ArchiveBusy
from .backup import BackupNotConfigured
from .cohorts.folders import DataFolderError
from .cohorts.models import CohortNotFound, NameTaken, NotArchived, ValidationError
from .cohorts.move_apply import MoveRefused
from .hardware.store import RigInvalid
from .intan.client import RhxCommandFailed, RhxError, RhxUnavailable
from .intan.probemap import ProbeMapError
from .intan.service import IntanNotReady
from .logbook.models import NoteInvalid, NoteNotFound
from .ports.handler import PortBusy
from .ports.manager import BoardNotDetected, PortNotBound
from .ports.states import IllegalTransition
from .protocol import ErrCode
from .rig.definition import RigInUse, VocabularyInUse, WiringWouldBreakTasks
from .server import Args, CommandError, ErrorTable, resolve_error
from .sessions.lifecycle import BoxRefused, MappingRefused, SessionRefused, SketchNotCarried
from .sessions.models import PrefixNameTaken, SessionNotFound
from .strobes.store import StrobeRefused
from .taskdef.model import TaskDefinitionError
from .tasks.profile import TaskProfileError
from .utility import UtilityUnavailable


def _box(exc: BaseException, args: Args) -> int | None:
    box = getattr(exc, "box", None)
    if isinstance(box, int) and not isinstance(box, bool):
        return box
    box = args.get("box")
    return box if isinstance(box, int) and not isinstance(box, bool) else None


def _boxed(code: str) -> Any:
    """`code` with `{"box": n}` -- or `{}`-less when no box is to be had."""

    def mapper(exc: BaseException, args: Args) -> CommandError:
        box = _box(exc, args)
        return CommandError(code, str(exc), {"box": box} if box is not None else None)

    return mapper


def _fixed(code: str, message: str | None = None) -> Any:
    def mapper(exc: BaseException, _args: Args) -> CommandError:
        return CommandError(code, message if message is not None else str(exc))

    return mapper


def _box_refused(exc: BoxRefused, args: Args) -> CommandError | None:
    """A box that couldn't start or stop: its cause, answered for that box.

    A refused console write (`PortBusy`) is a console code everywhere else;
    here the port was asked to start or stop a run, which its state didn't
    allow."""
    cause = exc.__cause__
    if cause is None:
        return None
    if isinstance(cause, PortBusy):
        return CommandError(ErrCode.ILLEGAL_TRANSITION, str(cause), {"box": exc.box})
    if isinstance(cause, KeyError):
        # `SessionRunner.start_box`'s: the box is outside the confirmed mapping.
        return CommandError(
            ErrCode.SESSION_INVALID,
            f"Box {exc.box} hasn't had its mapping confirmed yet.",
            {"box": exc.box},
        )
    return resolve_error(ERRORS, cause, {**args, "box": exc.box})


def _illegal_transition(exc: IllegalTransition, args: Args) -> CommandError:
    return CommandError(
        ErrCode.ILLEGAL_TRANSITION,
        str(exc),
        {"box": _box(exc, args), "from": exc.current.value, "to": exc.requested.value},
    )


def _port_os_error(exc: OSError, args: Args) -> CommandError | None:
    """A serial port the OS wouldn't open: `PermissionError` for a COM port
    another program holds, `FileNotFoundError` for one that went away. Only on
    a box's command; a socket's `ConnectionError` or `TimeoutError` is never a
    serial port's."""
    box = _box(exc, args)
    if box is None or isinstance(exc, (ConnectionError, TimeoutError)):
        return None
    return CommandError(ErrCode.PORT_OPEN_FAILED, str(exc), {"box": box})


def _task_profile(exc: TaskProfileError, args: Args) -> CommandError:
    box = _box(exc, args)
    if box is not None:
        return CommandError(ErrCode.TASK_PROFILE_INVALID, str(exc), {"box": box})
    return CommandError(
        ErrCode.TASK_PROFILE_INVALID,
        f"This sketch's task.json couldn't be read: {exc}",
        {"sketchPath": args.get("sketchPath")},
    )


_STROBE_CODES = {
    "invalid": ErrCode.STROBE_INVALID,
    "required": ErrCode.STROBE_REQUIRED,
    "in_recorded_session": ErrCode.STROBE_IN_RECORDED_SESSION,
    "would_break_tasks": ErrCode.STROBE_WOULD_BREAK_TASKS,
    "import_conflict": ErrCode.STROBE_IMPORT_CONFLICT,
    "unreadable": ErrCode.STROBE_VOCABULARY_UNREADABLE,
}


def _strobe_refused(exc: StrobeRefused, _args: Args) -> CommandError:
    code = _STROBE_CODES.get(exc.reason, ErrCode.STROBE_INVALID)
    return CommandError(code, str(exc), exc.detail or None)


ERRORS: ErrorTable = [
    # --- ports (ARCHITECTURE.md#port-state-machine) ---
    (BoxRefused, _box_refused),
    (PortNotBound, _boxed(ErrCode.PORT_NOT_BOUND)),
    (BoardNotDetected, _boxed(ErrCode.PORT_OPEN_FAILED)),
    (PortBusy, _boxed(ErrCode.SEND_NOT_PASSTHROUGH)),
    (IllegalTransition, _illegal_transition),
    (UtilityUnavailable, _boxed(ErrCode.UTILITY_UNAVAILABLE)),
    # --- sessions ---
    (SketchNotCarried, lambda e, _a: CommandError(ErrCode.SESSION_INVALID, str(e), {"boxes": e.boxes})),
    (SessionRefused, _fixed(ErrCode.SESSION_INVALID)),
    (MappingRefused, _boxed(ErrCode.TASK_PROFILE_INVALID)),
    (SessionNotFound, _fixed(ErrCode.SESSION_INVALID, "That session no longer exists.")),
    (PrefixNameTaken, lambda _e, a: CommandError(
        ErrCode.PREFIX_NAME_TAKEN,
        f"A prefix called “{str(a.get('name', '')).strip()}” already exists.",
        {"field": "name"},
    )),
    (NoteInvalid, _fixed(ErrCode.SESSION_INVALID)),
    (NoteNotFound, _fixed(ErrCode.SESSION_INVALID, "That note no longer exists.")),
    # --- cohorts and the archive (DATA.md) ---
    (CohortNotFound, _fixed(ErrCode.COHORT_NOT_FOUND, "That cohort no longer exists.")),
    (NameTaken, lambda e, _a: CommandError(
        ErrCode.COHORT_NAME_TAKEN,
        f"Another active cohort is already called “{e}”.",
        {"field": "name"},
    )),
    (NotArchived, _fixed(
        ErrCode.COHORT_NOT_ARCHIVED, "Archive this cohort before deleting it permanently."
    )),
    # Per-field, so the editor can render each against its row.
    (ValidationError, lambda e, _a: CommandError(
        ErrCode.COHORT_INVALID, "Some entries need fixing.", e.errors
    )),
    (DataFolderError, _fixed(ErrCode.DATA_FOLDER_INVALID)),
    (MoveRefused, lambda e, _a: CommandError(
        ErrCode.ANIMAL_MOVE_REFUSED, str(e), e.plan.to_json(applied=False)
    )),
    (ArchiveBusy, _fixed(ErrCode.ARCHIVE_BUSY)),
    (BackupNotConfigured, _fixed(ErrCode.BACKUP_UNAVAILABLE)),
    # --- the rig definition (TASKS.md#the-rig-definition) ---
    (VocabularyInUse, _fixed(ErrCode.STROBE_SESSION_RUNNING)),
    (RigInUse, _fixed(ErrCode.RIG_IN_USE)),
    (WiringWouldBreakTasks, lambda e, _a: CommandError(
        ErrCode.RIG_WOULD_BREAK_TASKS, str(e), {"breaks": e.breaks}
    )),
    (RigInvalid, lambda e, _a: CommandError(
        ErrCode.RIG_INVALID,
        "This wiring document could not be saved.",
        {"problems": [{"location": loc, "message": msg} for loc, msg in e.problems]},
    )),
    (StrobeRefused, _strobe_refused),
    (TaskDefinitionError, _fixed(ErrCode.TASK_INVALID)),
    (TaskProfileError, _task_profile),
    # --- recording (RECORDING.md) ---
    # Three codes, because the operator's next step differs: click Connect in
    # RHX (UNAVAILABLE), fix the setup (NOT_READY), or read what RHX said.
    (IntanNotReady, _fixed(ErrCode.INTAN_NOT_READY)),
    (ProbeMapError, _fixed(ErrCode.INTAN_NOT_READY)),
    (RhxUnavailable, _fixed(ErrCode.INTAN_UNAVAILABLE)),
    (RhxCommandFailed, lambda e, _a: CommandError(
        ErrCode.INTAN_COMMAND_FAILED, str(e), {"command": e.command}
    )),
    (RhxError, _fixed(ErrCode.INTAN_COMMAND_FAILED)),
    # Last: the broadest type here, and only ever a box's serial port.
    (OSError, _port_os_error),
]

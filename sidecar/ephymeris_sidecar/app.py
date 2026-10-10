"""Application state and command handlers.

Keeps `__main__` thin, owns the hardware layer, and is the only place that
knows both the wire protocol and the port manager — the `ports/` package stays
protocol-free and this module does the translating.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import discovery
from .analytics import AnalyticsBusy, AnalyticsService
from .analytics.repository import AnalyticsRepository
from .backup import BackupManager, BackupNotConfigured
from .boards import create_board_tool
from .boards.tool import FlashFailed
from .cohorts import folders, grouping, move_apply, relocate
from .cohorts.move import MoveRequest
from .cohorts.db import DB_FILENAME, Database
from .cohorts.folders import DataFolderError
from .cohorts.models import (
    CohortNotFound,
    NameTaken,
    NotArchived,
    ValidationError,
)
from .cohorts.repository import CohortRepository
from .sessions.models import (
    GroupRun,
    PrefixNameTaken,
    Session,
    SessionAnimalRun,
    SessionInvalid,
    SessionNotFound,
)
from .sessions import recovery
from .sessions.paths import resolve_session_folder
from .hardware import service as hardware_service
from .hardware import store as hardware_store
from .intan.client import RhxCommandFailed, RhxError, RhxUnavailable
from .intan import probemap as intan_probemap
from .intan.service import IntanNotReady, IntanService
from .logbook.models import NoteInvalid, NoteNotFound
from .logbook.service import LogbookService
from .rig import registry as rig_registry
from .sessions.repository import SessionRepository
from .sessions.runner import ActiveRun, BoxConfig, SessionRunner
from .strobes import store as strobe_store
from .strobes.usage import ArchiveScanner, firmware_refs
from .taskdef import bundled as bundled_sketches
from .taskdef import store as taskdef_store
from .taskdef.model import TaskDefinition, TaskDefinitionError
from .taskdef.validate import validate as validate_task
from .tasks import profile as task_profile
from .tasks.start_command import build_start_command
from .debug_run import DebugRuns
from .ports.handler import DEFAULT_LINE_ENDING, LINE_ENDINGS, OutputLine, PortBusy
from .ports.manager import BoardNotDetected, PortManager, PortNotBound
from .ports.states import IllegalTransition, PortState
from .protocol import Cmd, ErrCode, Evt, event
from .server import CommandError, SidecarServer
from .settings import SidecarSettings
from .utility import UtilityBaseline, UtilityUnavailable

log = logging.getLogger(__name__)


def build_active_payload(
    running_id: str | None,
    runner: SessionRunner | None,
    unfinished: list[Session],
) -> dict[str, Any]:
    """The `ActiveSessions` shape — reconcile live app state against the DB.

    The running slot is keyed off `running_id` (the runner-held session), never
    a bare DB status query: a runner-held session can still read `configuring`
    (post-confirmMapping, pre-startAll) and belongs in `running`, while a
    `running` DB row nobody holds is a crash orphan and lands in `stale` —
    surfaced for honesty, never offered for resume.
    """
    running = None
    if running_id is not None and runner is not None:
        held = next((s for s in unfinished if s.id == running_id), None)
        if held is not None:
            running = {
                "session": held.to_json(),
                "groupId": runner.group_id or None,
                "boxes": runner.snapshot(),
            }
    # Only a session that actually made it into the running slot is excluded
    # from the lists — a held id with no runner behind it proves nothing.
    held_id = running_id if running is not None else None
    return {
        "running": running,
        "configuring": [
            s.to_json()
            for s in unfinished
            if s.status == "configuring" and s.id != held_id
        ],
        "stale": [
            s.to_json()
            for s in unfinished
            if s.status == "running" and s.id != held_id
        ],
    }


class Application:
    def __init__(self, server: SidecarServer, data_dir: Path) -> None:
        self.server = server
        self.settings = SidecarSettings()
        # A real scan, not a placeholder: the library ships with the app, so
        # there is no "not configured yet" to wait out — a fresh launch either
        # has its sketches or is damaged, and both are knowable immediately.
        #: This rig's task profiles, and the sketches generated from them.
        #: Built before the first scan, because `discover()` reads its root.
        self.task_store = taskdef_store.TaskStore(data_dir)
        #: Where the bundled sketches are rebuilt against this rig's wiring
        #: (`taskdef/bundled.py`). A separate root from the profiles: one holds
        #: what the operator authored, the other a build output the app can
        #: throw away and remake.
        self.pinned_root = data_dir / "rig" / "sketches"
        self.discovery = discovery.discover(self.task_store.root, self.pinned_root)
        # `legacyNames` → sketch path, built lazily by `_sketch_path_for_name`
        # and tied to the discovery it was built from. Read from an analytics
        # worker thread while `_rescan` runs on the loop, hence the lock.
        self._legacy_names: dict[str, str] = {}
        self._legacy_names_from: object | None = None
        self._legacy_names_lock = threading.Lock()
        # data_dir is where the bundled arduino data seed gets its writable
        # copy in a packaged install (`boards/cli_tool.py`). The factory picks
        # the gRPC daemon backend when grpcio is importable, the subprocess
        # backend otherwise (`boards/__init__.py`).
        self.tool = create_board_tool(app_data_dir=data_dir)
        self.ports: PortManager | None = None
        self.utility: UtilityBaseline | None = None
        #: Tasks started by hand from Debug Mode, scored live (`debug_run.py`).
        self.debug_runs = DebugRuns()

        self.db = Database(data_dir / DB_FILENAME)
        self.cohorts = CohortRepository(self.db)
        self.sessions = SessionRepository(self.db)
        self.runner: SessionRunner | None = None
        self.backup: BackupManager | None = None
        self.analytics: AnalyticsService | None = None
        #: The session log (`DATA.md#the-session-log`). Off the session path:
        #: the runner never calls it, and its `notes.md` writes never block a reply.
        self.logbook: LogbookService | None = None
        #: The Intan RHX recording subsystem (`RECORDING.md`). Never on the
        #: session path except at `start_recording`.
        self.intan: IntanService | None = None
        self.profiles = AnalyticsRepository(self.db)
        self._running_session_id: str | None = None
        #: One rig operation at a time. `hardware.preview` fires on every
        #: keystroke in the wiring editor and re-validates every stored task
        #: profile; overlapping runs would also fight over the module-level rig
        #: source `impact_of` installs and restores.
        self._rig_gate = asyncio.Semaphore(1)
        #: The rig's own wiring, if it has one. Pointed at the registries here
        #: rather than read by them, so `rig` never learns about data_dir.
        self.hardware_store = hardware_store.HardwareStore(data_dir)
        self._install_rig_wiring()
        #: This machine's strobe vocabulary — the one source of every code
        #: (`TASKS.md#strobe-vocabulary`). Seeded from the shipped default on
        #: first start, then pointed at the registry exactly as the wiring is.
        self.vocab_store = strobe_store.VocabularyStore(data_dir)
        try:
            self.vocab_store.ensure_seeded()
        except OSError as exc:
            log.error("could not seed the strobe vocabulary (%s); decoding with the default", exc)
        rig_registry.set_vocabulary_source(self.vocab_store.load)
        #: Which recorded files contain which codes, for `strobes.remove`.
        self.strobe_scanner = ArchiveScanner(self.db)
        #: `hardware.preview`/`save` ask it which profiles a rewiring would
        #: newly break — before the write, which is the whole point of asking.
        self._task_store: Any = self.task_store
        #: hardware_id → detected interpreter baud. Detection costs a boot
        #: cycle per candidate rate, so the answer is kept for the app's
        #: lifetime — and invalidated on any flash to that box, since flashing
        #: is precisely what changes it.
        self._board_bauds: dict[str, int] = {}

    # --- lifecycle --------------------------------------------------------

    def register(self) -> None:
        self.server.register(Cmd.SETTINGS_PUSH, self._settings_push)
        self.server.register(Cmd.SKETCHES_REFRESH, self._sketches_refresh)
        self.server.register(Cmd.PORT_PASSTHROUGH_OPEN, self._passthrough_open)
        self.server.register(Cmd.PORT_PASSTHROUGH_CLOSE, self._passthrough_close)
        self.server.register(Cmd.PORT_SEND, self._port_send)
        self.server.register(Cmd.PORT_SEND_START, self._port_send_start)
        self.server.register(Cmd.PORT_FLASH, self._port_flash)
        self.server.register(Cmd.PORT_RESET, self._port_reset)
        self.server.register(Cmd.PORT_ERROR_ACK, self._port_error_ack)
        self.server.register(Cmd.UTILITY_ENSURE, self._utility_ensure)
        self.server.register(Cmd.UTILITY_IDENTIFY, self._utility_identify)

        self.server.register(Cmd.COHORTS_LIST, self._cohorts_list)
        self.server.register(Cmd.COHORTS_GET, self._cohorts_get)
        self.server.register(Cmd.COHORTS_CREATE, self._cohorts_create)
        self.server.register(Cmd.COHORTS_UPDATE, self._cohorts_update)
        self.server.register(Cmd.COHORTS_ARCHIVE, self._cohorts_archive)
        self.server.register(Cmd.COHORTS_RESTORE, self._cohorts_restore)
        self.server.register(Cmd.COHORTS_DELETE, self._cohorts_delete)
        self.server.register(Cmd.COHORTS_SET_DATA_FOLDER, self._cohorts_set_data_folder)
        self.server.register(Cmd.COHORTS_MOVE_ANIMALS, self._cohorts_move_animals)
        self.server.register(Cmd.PREFIXES_LIST, self._prefixes_list)
        self.server.register(Cmd.PREFIXES_CREATE, self._prefixes_create)
        self.server.register(Cmd.PREFIXES_DELETE, self._prefixes_delete)
        self.server.register(Cmd.TASKS_GET_PROFILE, self._tasks_get_profile)
        self.server.register(Cmd.TASKS_LIST, self._tasks_list)
        self.server.register(Cmd.TASKS_GET, self._tasks_get)
        self.server.register(Cmd.TASKS_PREVIEW, self._tasks_preview)
        self.server.register(Cmd.TASKS_SAVE, self._tasks_save)
        self.server.register(Cmd.TASKS_DELETE, self._tasks_delete)
        self.server.register(Cmd.STROBES_GET, self._strobes_get)
        self.server.register(Cmd.STROBES_USAGE, self._strobes_usage)
        self.server.register(Cmd.STROBES_ADD, self._strobes_add)
        self.server.register(Cmd.STROBES_EDIT, self._strobes_edit)
        self.server.register(Cmd.STROBES_RETIRE, self._strobes_retire)
        self.server.register(Cmd.STROBES_REINSTATE, self._strobes_reinstate)
        self.server.register(Cmd.STROBES_REMOVE, self._strobes_remove)
        self.server.register(Cmd.STROBES_EXPORT, self._strobes_export)
        self.server.register(Cmd.STROBES_IMPORT, self._strobes_import)
        self.server.register(Cmd.COHORTS_SUGGEST_GROUPS, self._cohorts_suggest_groups)

        self.server.register(Cmd.SESSIONS_SUGGEST_NUMBER, self._sessions_suggest_number)
        self.server.register(Cmd.SESSIONS_CREATE, self._sessions_create)
        self.server.register(Cmd.SESSIONS_ABANDON, self._sessions_abandon)
        self.server.register(Cmd.SESSIONS_CONFIRM_MAPPING, self._sessions_confirm_mapping)
        self.server.register(Cmd.SESSIONS_STATUS, self._sessions_status)
        self.server.register(Cmd.SESSIONS_START_ALL, self._sessions_start_all)
        self.server.register(Cmd.SESSIONS_END_GROUP, self._sessions_end_group)
        self.server.register(Cmd.SESSIONS_RESUME, self._sessions_resume)
        self.server.register(Cmd.SESSIONS_END, self._sessions_end)
        self.server.register(Cmd.SESSIONS_ACTIVE, self._sessions_active)
        self.server.register(Cmd.PORT_START_SESSION, self._port_start_session)
        self.server.register(Cmd.PORT_STOP_SESSION, self._port_stop_session)
        self.server.register(Cmd.BACKUP_SYNC_NOW, self._backup_sync_now)

        self.server.register(Cmd.SESSIONS_LIST, self._sessions_list)
        self.server.register(Cmd.ANALYTICS_SUMMARY, self._analytics_summary)
        self.server.register(Cmd.ANALYTICS_SERIES, self._analytics_series)
        self.server.register(Cmd.ANALYTICS_SET_FALSE_START, self._analytics_set_false_start)
        self.server.register(Cmd.ANALYTICS_RESCAN, self._analytics_rescan)
        self.server.register(Cmd.ANALYTICS_RECENT_SESSIONS, self._analytics_recent_sessions)
        self.server.register(Cmd.SESSIONS_RECOVER, self._sessions_recover)
        self.server.register(Cmd.SESSIONS_TIDY, self._sessions_tidy)

        self.server.register(Cmd.LOGBOOK_COHORT, self._logbook_cohort)
        self.server.register(Cmd.LOGBOOK_ADD_NOTE, self._logbook_add_note)
        self.server.register(Cmd.LOGBOOK_EDIT_NOTE, self._logbook_edit_note)
        self.server.register(Cmd.LOGBOOK_DELETE_NOTE, self._logbook_delete_note)
        self.server.register(Cmd.LOGBOOK_RESOLVE_FLAG, self._logbook_resolve_flag)
        self.server.register(Cmd.LOGBOOK_SET_SESSION_LOG, self._logbook_set_session_log)
        self.server.register(Cmd.LOGBOOK_OPEN_FLAGS, self._logbook_open_flags)

        self.server.register(Cmd.HARDWARE_GET, self._hardware_get)
        self.server.register(Cmd.HARDWARE_PREVIEW, self._hardware_preview)
        self.server.register(Cmd.HARDWARE_SAVE, self._hardware_save)
        self.server.register(Cmd.HARDWARE_RESET, self._hardware_reset)

        self.server.register(Cmd.INTAN_STATUS, self._intan_status)
        self.server.register(Cmd.INTAN_CONNECT, self._intan_connect)
        self.server.register(Cmd.INTAN_DISCONNECT, self._intan_disconnect)
        self.server.register(Cmd.INTAN_CONFIGURE, self._intan_configure)
        self.server.register(Cmd.INTAN_PARSE_PROBE_MAP, self._intan_parse_probe_map)
        self.server.register(Cmd.INTAN_PROBE_MAP, self._intan_probe_map)
        self.server.register(Cmd.INTAN_SET_THRESHOLD, self._intan_set_threshold)
        self.server.register(Cmd.INTAN_SCOPE_OPEN, self._intan_scope_open)
        self.server.register(Cmd.INTAN_SCOPE_UPDATE, self._intan_scope_update)
        self.server.register(Cmd.INTAN_SCOPE_CLOSE, self._intan_scope_close)
        self.server.register(Cmd.INTAN_FORCE_STOP, self._intan_force_stop)

        self.server.on_client_ready(self._replay_state)

    def start(self) -> None:
        self.db.connect()
        # scipy is NOT imported here: `__main__._run` preloads it before the
        # parent-watch thread exists, and importing it any later than that
        # deadlocks the frozen build (`DATA.md#the-mat-mirror`).
        self._log_rig_wiring()
        # Rebuild the bundled sketches against this rig's wiring before anything
        # can flash one. Synchronous and on the startup path on purpose: it is a
        # few small file copies, and doing it lazily would mean the FIRST flash
        # after a launch could serve the shipped pins while every later one
        # served the rig's -- a difference nobody would connect to a restart.
        pinned = bundled_sketches.repin_all(self.pinned_root)
        # The stored task profiles too, for a different reason: their folders
        # were written by whichever version of the generator last saved them.
        # When the generator's output changes shape -- the TrialType
        # constructor grew a reward-volume argument, FL keys became RW keys --
        # an old folder stops compiling (loud) or sends keys the firmware no
        # longer parses (silent: the session runs on the compiled-in value).
        # Regenerating on every start is a few file writes per profile and
        # makes what is on disk always what THIS version would write.
        regenerated = self.task_store.regenerate_all()
        if pinned or regenerated:
            self.discovery = discovery.discover(self.task_store.root, self.pinned_root)
            log.info(
                "%d bundled sketch(es) and %d task profile(s) rebuilt at startup",
                pinned,
                regenerated,
            )
        loop = asyncio.get_running_loop()
        self.backup = BackupManager(
            loop=loop,
            db=self.db,
            cohort_roots=self._cohort_roots,
            broadcast=self.server.broadcast,
        )
        # Every commit marks the database for backup — no write path can forget
        # to, and `session_animal_runs` written overnight counts just as much as
        # a cohort edit (`DATA.md#the-database-copy`).
        self.db.on_commit(self.backup.mark_db_dirty)
        self.backup.start()
        self.analytics = AnalyticsService(
            db=self.db,
            cohorts=self.cohorts,
            sessions=self.sessions,
            broadcast=self.server.broadcast,
            sketch_lookup=self._sketch_path_for_name,
        )
        # A move a crash interrupted is finished or undone before anything can
        # read the archive (`DATA.md#moving-animals-between-cohorts`). Never
        # fatal: the journal stays, and the next start tries again.
        try:
            move_apply.resume(self.db)
        except Exception:  # noqa: BLE001
            log.exception("couldn't finish an interrupted move of animals")
        # Likewise a data-folder relocate (`DATA.md#data-folder`).
        try:
            relocate.resume(self.db)
        except Exception:  # noqa: BLE001
            log.exception("couldn't finish an interrupted data-folder move")
        self.logbook = LogbookService(
            db=self.db,
            cohorts=self.cohorts,
            sessions=self.sessions,
            profiles=self.profiles,
            broadcast=self.server.broadcast,
            enqueue_backup=self.backup.enqueue,
        )
        self.ports = PortManager(
            loop=loop,
            tool=self.tool,
            on_state_change=self._handle_state_change,
            on_output=self._handle_output,
            on_presence=self._handle_presence,
        )
        self.ports.start()
        self.utility = UtilityBaseline(
            loop=loop,
            ports=self.ports,
            discovery=lambda: self.discovery,
            broadcast=self.server.broadcast,
        )
        self.runner = SessionRunner(
            loop=loop,
            ports=self.ports,
            broadcast=self.server.broadcast,
            on_animal_ended=self._on_animal_ended,
            backup=self.backup,
        )
        self.intan = IntanService(
            loop=loop,
            broadcast=self.server.broadcast,
            settings=self.settings,
            rig_has_sync=lambda: rig_registry.channels().unique_of_kind("sync") is not None,
        )
        self.intan.start()
        # The runner's three taps. They run on a port's session thread, which
        # is why the service's side of each is a `call_soon_threadsafe`.
        self.runner.recording_fields = self.intan.recording_fields
        self.runner.on_box_started = self.intan.box_started
        self.runner.on_strobe_tap = self.intan.on_strobe

    async def stop(self) -> None:
        # First, and it only closes OUR sockets: a recording in progress belongs
        # to RHX and outlives the sidecar (`RECORDING.md#when-rhx-goes-away`).
        if self.intan is not None:
            await self.intan.stop()
        # Before the ports go: a lit box has a console open that must be closed
        # through the state machine rather than yanked out from under it.
        if self.utility is not None:
            await self.utility.stop()
        if self.ports is not None:
            await self.ports.stop()
        # After ports: nothing may be mid-flash once the manager has stopped,
        # so the daemon child (if the gRPC backend is active) can go too.
        await self.tool.close()
        # Before backup stops, so the last notes.md it writes is still mirrored.
        if self.logbook is not None:
            await self.logbook.drain()
        if self.backup is not None:
            await self.backup.stop()
        self.db.close()

    def _install_rig_wiring(self) -> None:
        """Point the registries at this rig's wiring document.

        Called once at construction and again after every `hardware.save`.
        `set_rig_source` clears the channel cache, which is why this must NOT be
        hung off `settings.push` -- that fires on every reconnect, and throwing
        the registries away several times a session for no reason is a real cost
        on a call that also does a library rescan.
        """
        from ephymeris_sidecar.rig import registry

        registry.set_rig_source(self.hardware_store.load)

    async def _rebuild_generated(self) -> None:
        """Everything that carries a pin number or a strobe code, rebuilt. THE
        one call site, for a wiring change and a vocabulary edit alike.

        Two outputs, deliberately. Pins and codes are compiled into every
        generated `TaskPins.h` — a task profile's and a bundled sketch's alike —
        so a change that rebuilt only one of them would leave the other flashing
        the old pins or the old codes. It would still compile, still run, and
        the only symptom would be a valve that never fires or an event decoded
        under the wrong name. Splitting this into two calls is how one of them
        eventually gets forgotten.

        Ordering: rebuild first, then rescan, so discovery sees the new folders
        rather than reporting the ones it is about to replace.
        """
        tasks = await asyncio.to_thread(self.task_store.regenerate_all)
        pinned = await asyncio.to_thread(bundled_sketches.repin_all, self.pinned_root)
        if tasks or pinned:
            log.info(
                "wiring changed: rebuilt %d task profile(s) and %d bundled sketch(es)",
                tasks,
                pinned,
            )
        await self._rescan()
        if tasks:
            await self._broadcast_tasks()
        # The box utility was rebuilt with the rest, so every idle box is
        # carrying an old build of it — old pins, old codes, old channel names.
        if pinned and self.utility is not None:
            self.utility.rebuilt()

    def _log_rig_wiring(self) -> None:
        """Say once, at startup, which wiring is in force.

        The pin numbers this names are the ones written into every task
        profile's generated firmware, so a box running the wrong wiring is a
        real failure with no other symptom -- the valves simply fire on pins
        nothing is plumbed to. The log line is the cheapest place to catch it.
        """
        from ephymeris_sidecar.rig.registry import active_pinout_id, channels

        status = self.hardware_store.status()
        wiring = (
            f"this rig's own wiring (derived from {status.derived_from or 'the shipped pinout'})"
            if status.custom
            else f"the shipped pinout {active_pinout_id()}"
        )
        log.info("wiring: %s, %s", wiring, channels().content_hash())

    def _cohort_roots(self) -> list[str]:
        """Every cohort's data folder — the anchors for mirror paths
        (`DATA.md#mirror-layout`).

        Archived cohorts are included deliberately: archival is a bookkeeping
        state, and their data is exactly as worth protecting as anyone else's.
        """
        return [c.data_folder for c in self.cohorts.list_cohorts()]

    def _require_ports(self) -> PortManager:
        if self.ports is None:
            raise CommandError(ErrCode.INTERNAL, "hardware layer isn't running")
        return self.ports

    # --- replay -----------------------------------------------------------

    async def _replay_state(self, conn) -> None:  # noqa: ANN001
        """Give a freshly-connected client the current picture.

        Without this, a client connecting during a quiet period would show six
        boxes in whatever state it assumed rather than what they're actually in.
        """
        if self.ports is None:
            return

        async def send(message: dict[str, Any]) -> None:
            await conn.send(json.dumps(message))

        for box, state in self.ports.current_states().items():
            await send(
                event(
                    Evt.PORT_STATE,
                    {
                        "box": box,
                        "state": state.value,
                        "prev": state.value,
                        "reason": "initial state",
                    },
                )
            )
        await send(event(Evt.BOARDS_PRESENCE, {"boards": self.ports.presence_json()}))
        await send(event(Evt.SKETCHES_UPDATED, self.discovery.to_json()))
        await send(event(Evt.TASKS_UPDATED, {"tasks": self.task_store.list_entries()}))
        await send(event(Evt.COHORTS_UPDATED, {"cohorts": await self._cohort_summaries()}))
        await send(event(Evt.PREFIXES_UPDATED, {"prefixes": await self._prefix_list()}))
        if self.utility is not None:
            await send(event(Evt.UTILITY_UPDATED, self.utility.status()))
        if self.backup is not None:
            await send(event(Evt.BACKUP_STATUS, self.backup.status()))
        if self.intan is not None:
            await send(event(Evt.INTAN_STATUS, self.intan.status_json()))

    # --- hardware callbacks ----------------------------------------------

    def _handle_state_change(
        self, box: int, previous: PortState, current: PortState, reason: str
    ) -> None:
        """Always runs on the loop thread — `PortHandler` guarantees it."""
        asyncio.create_task(
            self.server.broadcast(
                event(
                    Evt.PORT_STATE,
                    {
                        "box": box,
                        "state": current.value,
                        "prev": previous.value,
                        "reason": reason,
                    },
                )
            )
        )
        # Hard stop (`ARCHITECTURE.md#board-drop`): a box dropping out of
        # IN_SESSION into ERROR means the
        # board vanished mid-run. Finalize whatever the write-ahead log durably
        # captured, with stop_reason "board disconnected". The ERROR itself
        # clears the normal way, via port.error.ack.
        if (
            previous == PortState.IN_SESSION
            and current == PortState.ERROR
            and self.runner is not None
        ):
            self.runner.board_dropped(box)
        # `ARCHITECTURE.md#when-a-restore-happens`: a box that has just become
        # nobody's is a box that should go back
        # to baseline. Driving this off the transition rather than off each
        # command means every way a port can fall idle — a run ending, a
        # console closing, an error acknowledged — is covered by one hook.
        if current == PortState.IDLE and self.utility is not None:
            self.utility.ensure([box])
        # A hand-started task is only being listened to while the console is
        # open; a reset or a flash has rebooted the board besides.
        if current != PortState.PASSTHROUGH:
            closing = self.debug_runs.drop(box)
            if closing is not None:
                asyncio.create_task(
                    self.server.broadcast(event(Evt.PORT_TELEMETRY, closing))
                )

    async def _handle_output(self, box: int, lines: list[OutputLine]) -> None:
        await self.server.broadcast(
            event(Evt.PORT_OUTPUT, {"box": box, "lines": [line.to_json() for line in lines]})
        )
        # After the lines themselves, so a client never holds a metric for a
        # trial whose strobes it has not been shown yet.
        scored = self.debug_runs.offer(box, lines)
        if scored is not None:
            await self.server.broadcast(event(Evt.PORT_TELEMETRY, scored))

    async def _handle_presence(self, boards: list[dict[str, object]]) -> None:
        await self.server.broadcast(event(Evt.BOARDS_PRESENCE, {"boards": boards}))
        if self.utility is not None:
            # This is also the startup path: the first poll that finds the rig
            # is what triggers the first baseline restore
            # (`ARCHITECTURE.md#when-a-restore-happens`).
            self.utility.note_presence(
                str(b.get("hardwareId")) for b in boards if b.get("hardwareId")
            )
            self.utility.ensure()
            await self.utility.publish()

    # --- handlers ---------------------------------------------------------

    async def _settings_push(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """Accept the shell's settings and answer with the library's state.

        The bundled library no longer depends on anything in the settings, but
        the reply still carries its status so a client learns it on connect
        without a second round trip — the same moment it used to learn the old
        directory validation.
        """
        self.settings = SidecarSettings.from_payload(args.get("settings", args))
        log.info(
            "settings received (defaultBaud=%d, backupDirectory=%r)",
            self.settings.default_baud,
            self.settings.backup_directory,
        )
        self.tool.set_binary(self.settings.arduino_cli_path)
        if self.backup is not None:
            await self.backup.configure(self.settings.backup_directory)
        if self.ports is not None:
            self.ports.update_settings(self.settings)
            # Bindings may have changed, so the boxId on each board can differ
            # even when the detected set didn't.
            await self._handle_presence(self.ports.presence_json())

        # Rescan unconditionally, even though the library path can't be
        # reconfigured: an install can still lose files underneath a running
        # app, and a dev checkout restages between pushes.
        await self._rescan()
        # After the rescan, so a newly-chosen utility sketch resolves against
        # the library as it is now rather than as it was one push ago.
        if self.intan is not None:
            self.intan.update_settings(self.settings)
        if self.utility is not None:
            self.utility.update_settings(self.settings)
            self.utility.ensure()
            await self.utility.publish()
        return {"library": self.discovery.library.to_json()}

    async def _sketches_refresh(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        await self._rescan()
        return self.discovery.to_json()

    async def _passthrough_open(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        box = _box_arg(args)
        baud = args.get("baud")
        with _mapped_errors(box):
            state = self._require_ports().open_passthrough(
                box, int(baud) if isinstance(baud, (int, str)) and str(baud).isdigit() else None
            )
        return {"state": state.value}

    async def _passthrough_close(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        box = _box_arg(args)
        with _mapped_errors(box):
            state = self._require_ports().close_passthrough(box)
        return {"state": state.value}

    async def _port_send(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        box = _box_arg(args)
        text = args.get("text")
        if not isinstance(text, str):
            raise CommandError(ErrCode.BAD_MESSAGE, "`text` must be a string")

        line_ending = args.get("lineEnding", DEFAULT_LINE_ENDING)
        if line_ending not in LINE_ENDINGS:
            raise CommandError(
                ErrCode.BAD_MESSAGE,
                f"unknown lineEnding {line_ending!r}",
                {"allowed": sorted(LINE_ENDINGS)},
            )

        with _mapped_errors(box):
            written = self._require_ports().send(box, text, line_ending)
        return {"bytesWritten": written}

    async def _port_send_start(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """Start a behaviour sketch by hand from the Debug console.

        The line is built here rather than in the client for the reason a
        session's is: `build_start_command` is the one place that knows the
        profile's wire keys and the firmware's line cap, and a `START` the board
        silently truncates is the failure this whole path exists to avoid.
        """
        box = _box_arg(args)
        path = args.get("sketchPath")
        sketch = next((s for s in self.discovery.sketches if s.path == path), None)
        if sketch is None:
            raise CommandError(
                ErrCode.SKETCH_UNKNOWN,
                "That sketch isn't in the sketch library — refresh the list and "
                "flash it again.",
                {"sketchPath": path},
            )
        config = args.get("config")
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise CommandError(ErrCode.BAD_MESSAGE, "`config` must be an object")

        try:
            profile = await asyncio.to_thread(task_profile.load_profile, sketch.path)
        except task_profile.TaskProfileError:
            profile = None  # profile-less: bare START, as in a session
        try:
            command = build_start_command(profile, config)
        except task_profile.TaskProfileError as exc:
            raise CommandError(ErrCode.TASK_PROFILE_INVALID, str(exc), {"box": box}) from exc

        with _mapped_errors(box):
            written = self._require_ports().send(box, command, DEFAULT_LINE_ENDING)
        # Armed only once the line is really on the wire, and only here: this is
        # the one moment the sidecar knows which profile the strobes that follow
        # should be scored against (`debug_run.py`).
        await self.server.broadcast(
            event(Evt.PORT_TELEMETRY, self.debug_runs.arm(box, profile))
        )
        return {"command": command, "bytesWritten": written}

    async def _port_flash(self, _server, _conn, args, corr) -> dict[str, Any]:  # noqa: ANN001
        box = _box_arg(args)
        path = args.get("sketchPath")

        # Only a discovered sketch is flashable (`TASKS.md#sketch-library`) —
        # enforced here, not just by the picker only listing discovered sketches.
        sketch = next((s for s in self.discovery.sketches if s.path == path), None)
        if sketch is None:
            raise CommandError(
                ErrCode.SKETCH_UNKNOWN,
                "That sketch isn't in the sketch library — "
                "refresh the list and pick again.",
                {"sketchPath": path},
            )

        def on_progress(phase: str, stream: str, text: str) -> None:
            # Called from loop context; each line rides out as its own event,
            # tagged with the command that caused it.
            asyncio.create_task(
                self.server.broadcast(
                    event(
                        Evt.FLASH_PROGRESS,
                        {"box": box, "phase": phase, "stream": stream, "text": text},
                        corr=corr,
                    )
                )
            )

        # `ARCHITECTURE.md#exclusivity`: the session flash sequence needs every
        # box to land in IDLE so the
        # runner can claim it, overriding the usual passthrough auto-resume.
        suppress = args.get("suppressPassthroughResume") is True

        with _mapped_errors(box):
            state, resumed = await self._require_ports().flash(
                box,
                sketch.path,
                sketch.name,
                self.discovery.libraries_path,
                on_progress,
                suppress_passthrough_resume=suppress,
            )
        # Whatever the app just put on that board is now what's on it — the one
        # place every deliberate flash passes through, so the baseline belief
        # can't be left claiming a utility sketch a session flash overwrote.
        #
        # A flash that is NOT the session sequence is one the operator asked for
        # by hand, and it is pinned (`utility.py`): this port is about to fall
        # IDLE, the idle hook is about to ask for a restore, and without the pin
        # that restore overwrote the task within seconds of it landing.
        if self.utility is not None:
            self.utility.note_flashed(box, sketch.path, pin=not suppress)
            await self.utility.publish()
        # Flashing is precisely what changes a board's interpreter baud, so the
        # cached detection result dies with the old firmware.
        hardware_id = self.settings.hardware_id_for(box)
        if hardware_id is not None:
            self._board_bauds.pop(hardware_id, None)
        return {"state": state.value, "resumedPassthrough": resumed}

    async def _port_reset(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        box = _box_arg(args)
        with _mapped_errors(box):
            state, resumed = await self._require_ports().reset(box)
        return {"state": state.value, "resumedPassthrough": resumed}

    async def _port_error_ack(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        box = _box_arg(args)
        with _mapped_errors(box):
            state = self._require_ports().acknowledge_error(box)
        return {"state": state.value}

    # --- utility baseline (ARCHITECTURE.md#hardware-utility-baseline) ---

    def _require_utility(self) -> UtilityBaseline:
        if self.utility is None:
            raise CommandError(ErrCode.INTERNAL, "hardware layer isn't running")
        return self.utility

    async def _utility_ensure(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """Schedule a baseline restore and return the picture as it stands.

        Deliberately doesn't await the flashing: six boxes take minutes, and
        the client watches `utility.updated` instead of holding a reply open.
        """
        utility = self._require_utility()
        boxes = args.get("boxes")
        targets = (
            [b for b in boxes if isinstance(b, int) and not isinstance(b, bool)]
            if isinstance(boxes, list)
            else None
        )
        # Arriving over the wire means a person asked: that is what releases a
        # Debug Mode pin. The automatic triggers call `ensure` directly.
        utility.unpin(targets)
        utility.ensure(targets, force=args.get("force") is True)
        return utility.status()

    async def _utility_identify(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        box = _box_arg(args)
        on = args.get("on")
        if not isinstance(on, bool):
            raise CommandError(ErrCode.BAD_MESSAGE, "`on` must be a boolean")
        try:
            delivered, state = await self._require_utility().identify(box, on)
        except UtilityUnavailable as exc:
            raise CommandError(ErrCode.UTILITY_UNAVAILABLE, str(exc), {"box": box}) from exc
        return {"delivered": delivered, "state": state}

    # --- cohorts (DATA.md#cohorts-animals-and-groups) --------------------

    async def _cohorts_list(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        return {"cohorts": await self._cohort_summaries()}

    async def _cohorts_get(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        cohort_id = _str_arg(args, "id")
        with _cohort_errors():
            cohort = await asyncio.to_thread(self.cohorts.get, cohort_id)
        return {"cohort": cohort.to_json()}

    async def _cohorts_create(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        name = str(args.get("name") or "").strip()
        override = args.get("dataFolder")

        with _cohort_errors():
            # `DATA.md#data-folder`: an explicit folder wins; otherwise derive
            # one from the
            # configured data directory, suffixing until the path is unused.
            # Resolving is side-effect free — nothing is created yet.
            if isinstance(override, str) and override.strip():
                target = Path(override.strip()).expanduser()
            else:
                target = await asyncio.to_thread(
                    folders.resolve_default_folder, self.settings.data_directory, name
                )

            # The record goes in first so a duplicate name fails *before* any
            # directory is made — otherwise a rejected create would litter the
            # user's data directory with orphaned folders. The roster rides
            # along when the editor has one, making creation a single call
            # rather than a create plus a patch that could fail on its own.
            cohort = await asyncio.to_thread(
                self.cohorts.create,
                name,
                str(target),
                args.get("animals"),
                args.get("groups"),
            )
            try:
                await asyncio.to_thread(folders.ensure_folder, target)
            except Exception:
                # Roll back rather than leave a cohort pointing at a folder
                # that couldn't be created.
                await asyncio.to_thread(self.cohorts.purge, cohort.id)
                raise

        log.info("cohort created: %s at %s", cohort.name, cohort.data_folder)
        await self._broadcast_cohorts()
        return {"cohort": cohort.to_json()}

    async def _cohorts_update(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        cohort_id = _str_arg(args, "id")
        patch = args.get("patch")
        if not isinstance(patch, dict):
            raise CommandError(ErrCode.BAD_MESSAGE, "`patch` must be an object")

        with _cohort_errors():
            cohort = await asyncio.to_thread(self.cohorts.update, cohort_id, patch)
        await self._broadcast_cohorts()
        return {"cohort": cohort.to_json()}

    async def _cohorts_archive(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        cohort_id = _str_arg(args, "id")
        with _cohort_errors():
            cohort = await asyncio.to_thread(self.cohorts.archive, cohort_id)
        await self._broadcast_cohorts()
        return {"cohort": cohort.to_json()}

    async def _cohorts_restore(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        cohort_id = _str_arg(args, "id")
        with _cohort_errors():
            cohort = await asyncio.to_thread(self.cohorts.restore, cohort_id)
        await self._broadcast_cohorts()
        return {"cohort": cohort.to_json()}

    async def _cohorts_delete(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """Permanent delete (`DATA.md#archive-and-delete`). Removes bookkeeping
        only, never data files."""
        cohort_id = _str_arg(args, "id")
        if args.get("confirm") is not True:
            raise CommandError(
                ErrCode.BAD_MESSAGE, "Permanent delete requires `confirm: true`."
            )
        with _cohort_errors():
            await asyncio.to_thread(self.cohorts.delete, cohort_id)
        log.info("cohort deleted: %s (data folder left on disk)", cohort_id)
        await self._broadcast_cohorts()
        return {"deleted": True}

    async def _cohorts_set_data_folder(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """The explicit relocate (`DATA.md#data-folder`). Moving the contents
        moves the records' paths with them, so it waits for an idle rig: a
        session writing into the folder would be writing into one that moves."""
        cohort_id = _str_arg(args, "id")
        path = _str_arg(args, "path")
        move_existing = args.get("moveExisting") is True
        if move_existing and (
            self._running_session_id or (self.runner is not None and self.runner.running_boxes())
        ):
            raise CommandError(
                ErrCode.DATA_FOLDER_INVALID,
                "A session is set up or running. Finish it, then move the data folder.",
            )

        with _cohort_errors():
            try:
                await self._require_analytics().relocate(cohort_id, path, move_existing)
            except AnalyticsBusy as exc:
                raise CommandError(ErrCode.INTERNAL, str(exc)) from exc
            cohort = await asyncio.to_thread(self.cohorts.get, cohort_id)
        await self._broadcast_cohorts()
        return {"cohort": cohort.to_json()}

    async def _cohorts_move_animals(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """Move animals, their files and their history to another cohort
        (`DATA.md#moving-animals-between-cohorts`). `apply` false is a preview.

        Refused while the rig is in use anywhere, not just in these cohorts:
        copying an archive competes with the write-ahead log's per-strobe
        fsync, and one session runs at a time app-wide.
        """
        animal_ids = _opt_str_list(args.get("animalIds")) or []
        request = MoveRequest(
            source_id=_str_arg(args, "cohortId"),
            animal_ids=animal_ids,
            dest_id=_str_arg(args, "destinationCohortId"),
            dest_group_id=args.get("destinationGroupId")
            if isinstance(args.get("destinationGroupId"), str)
            else None,
        )
        busy = None
        if self._running_session_id or (self.runner is not None and self.runner.running_boxes()):
            busy = "A session is set up or running. Finish it, then move the animals."
        with _cohort_errors():
            try:
                result, copied = await self._require_analytics().move_animals(
                    request, apply=args.get("apply") is True, busy=busy
                )
            except AnalyticsBusy as exc:
                raise CommandError(ErrCode.INTERNAL, str(exc)) from exc
            except move_apply.MoveRefused as exc:
                raise CommandError(
                    ErrCode.ANIMAL_MOVE_REFUSED, str(exc), exc.plan.to_json(applied=False)
                ) from exc
        if result["applied"]:
            if self.backup is not None and copied:
                self.backup.enqueue(*copied)
            await self._broadcast_cohorts()
            await self._broadcast_lifecycle()
            if self.logbook is not None:
                # Notes moved and copied, and both folders' notes.md re-render —
                # including a source session whose every note moved away, which
                # has none left to be found by but still a stale notes.md.
                annotated = await asyncio.to_thread(
                    self.logbook.repo.annotated_session_ids, request.source_id
                )
                touched = {s["sessionId"] for s in result["sessions"]}
                await self.logbook.refresh(request.source_id, sorted(set(annotated) | touched))
                await self.logbook.refresh(request.dest_id)
        return result

    async def _cohorts_suggest_groups(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """Auto-Balance preview (`DATA.md#auto-balance`). Computes only — the
        client applies via `cohorts.update`."""
        cohort_id = _str_arg(args, "id")
        with _cohort_errors():
            cohort = await asyncio.to_thread(self.cohorts.get, cohort_id)

        proposal = grouping.suggest_groups(
            cohort.animals,
            group_count=_opt_int(args.get("groupCount")),
            max_group_size=_opt_int(args.get("maxGroupSize")),
            balance_by_sex=args.get("balanceBySex") is True,
        )
        return proposal.to_json()

    async def _cohort_summaries(self) -> list[dict[str, Any]]:
        cohorts = await asyncio.to_thread(self.cohorts.list_cohorts)
        return [c.to_summary() for c in cohorts]

    async def _broadcast_cohorts(self) -> None:
        await self.server.broadcast(
            event(Evt.COHORTS_UPDATED, {"cohorts": await self._cohort_summaries()})
        )

    # --- prefixes (DATA.md#prefixes) ----------------------------------

    async def _prefixes_list(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        return {"prefixes": await self._prefix_list()}

    async def _prefixes_create(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        name = str(args.get("name") or "").strip()
        try:
            prefix = await asyncio.to_thread(self.sessions.create_prefix, name)
        except PrefixNameTaken as exc:
            raise CommandError(
                ErrCode.PREFIX_NAME_TAKEN,
                f"A prefix called “{name}” already exists.",
                {"field": "name"},
            ) from exc
        await self._broadcast_prefixes()
        return {"prefix": prefix.to_json()}

    async def _prefixes_delete(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        prefix_id = _str_arg(args, "id")
        await asyncio.to_thread(self.sessions.delete_prefix, prefix_id)
        await self._broadcast_prefixes()
        return {"deleted": True}

    async def _prefix_list(self) -> list[dict[str, Any]]:
        prefixes = await asyncio.to_thread(self.sessions.list_prefixes)
        return [p.to_json() for p in prefixes]

    async def _broadcast_prefixes(self) -> None:
        await self.server.broadcast(
            event(Evt.PREFIXES_UPDATED, {"prefixes": await self._prefix_list()})
        )

    # --- task profiles (TASKS.md#task-profile) -----------------------

    async def _tasks_get_profile(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        sketch_path = _str_arg(args, "sketchPath")
        try:
            profile = await asyncio.to_thread(task_profile.load_profile, sketch_path)
        except task_profile.TaskProfileError as exc:
            # A malformed task.json is surfaced so it can be fixed; the sketch is
            # otherwise treated as profile-less (bare START, raw strobe log).
            raise CommandError(
                ErrCode.TASK_PROFILE_INVALID,
                f"This sketch's task.json couldn't be read: {exc}",
                {"sketchPath": sketch_path},
            ) from exc
        return profile.to_json() if profile is not None else {"profile": None}

    # -- task profiles ------------------------------------------------------ #
    #
    # OFF-LOOP, because saving one writes four files and validating one composes
    # the whole channel map, and the event loop owns six serial ports and a
    # 20 Hz output flush. They share the rig gate rather than taking their own:
    # `hardware.preview` installs a hypothetical wiring at module scope, and a
    # task validating against it at the same moment would read the wrong rig.

    async def _tasks_list(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        async with self._rig_gate:
            return {"tasks": await asyncio.to_thread(self.task_store.list_entries)}

    async def _tasks_get(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        task_id = _str_arg(args, "taskId")
        definition = await asyncio.to_thread(self.task_store.get, task_id)
        if definition is None:
            raise CommandError(
                ErrCode.TASK_NOT_FOUND,
                f"No task profile called {task_id!r} on this rig.",
                {"taskId": task_id},
            )
        async with self._rig_gate:
            diagnostics = await asyncio.to_thread(validate_task, definition)
        return {
            "definition": definition.to_json(),
            "diagnostics": [d.to_json() for d in diagnostics],
        }

    async def _tasks_preview(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        definition = self._definition_arg(args)
        async with self._rig_gate:
            return await asyncio.to_thread(self._preview_payload, definition)

    def _preview_payload(self, definition: TaskDefinition) -> dict[str, Any]:
        """Compile without writing, and report the line budget.

        The `START` length is carried because it is the one budget an operator
        can exhaust without noticing: the firmware truncates an overlong line in
        silence and runs on whichever values happened to fit. Showing the number
        as it grows is cheaper than explaining the failure afterward.
        """
        from .taskdef import generate
        from .tasks.start_command import START_LINE_MAX, build_start_command, with_trial_seed

        diagnostics = validate_task(definition)
        profile = generate.build_profile(definition)
        config = {field.metadata_key: field.default for field in profile.config}
        try:
            line = with_trial_seed(build_start_command(profile, config), 2147483646)
            length = len(line)
        except task_profile.TaskProfileError:
            # Over the cap. TSK107 already says so with the real numbers; the
            # length is reported as the max so the meter reads full rather than
            # empty, which is the honest rendering of "it does not fit".
            length = START_LINE_MAX
        # The same profile compiled with the overrides stripped. Two compiles
        # rather than one because "what does this profile PIN" is not derivable
        # from the merged result: a value equal to the catalogue's is
        # indistinguishable from one that was never set, and storing it would
        # freeze the field against a later correction.
        from dataclasses import replace as _replace

        bare = generate.build_profile(_replace(definition, params={}))
        return {
            "diagnostics": [d.to_json() for d in diagnostics],
            "startLineLength": length,
            "startLineMax": START_LINE_MAX,
            "profile": profile.to_json(),
            "catalogueDefaults": {f.metadata_key: f.default for f in bare.config},
        }

    async def _tasks_save(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        definition = self._definition_arg(args)
        # A generated sketch and a bundled one sharing a name makes the picker
        # ambiguous and the flash a coin flip, so this is refused rather than
        # reported: it is the one problem saving cannot leave for later.
        collision = next(
            (s for s in self.discovery.sketches
             if s.source == "bundled" and s.name == definition.name),
            None,
        )
        if collision is not None:
            raise CommandError(
                ErrCode.TASK_INVALID,
                f"A sketch that ships with Ephymeris is already called "
                f"{definition.name!r}. Give this task another name.",
                {"sketchPath": collision.path},
            )
        # Two saved tasks sharing a name share a sketch folder: saving one
        # overwrites the other's firmware and deleting either removes both.
        # Duplicating a task makes this the easy mistake, so it is refused too.
        # Case-folded because the lab machines' filesystem is case-insensitive.
        twin = next(
            (e for e in await asyncio.to_thread(self.task_store.list_entries)
             if e["id"] != definition.id
             and str(e["name"]).casefold() == definition.name.casefold()),
            None,
        )
        if twin is not None:
            raise CommandError(
                ErrCode.TASK_INVALID,
                f"Another task is already called {twin['name']!r}. "
                "Give this task another name.",
                {"taskId": twin["id"]},
            )

        async with self._rig_gate:
            diagnostics = await asyncio.to_thread(self.task_store.save, definition)
        # The folder is a sketch from this moment, so the library must be
        # rescanned before anyone can flash it. `_rescan` broadcasts
        # `sketches.updated`; the task list rides alongside it.
        await self._rescan()
        await self._broadcast_tasks()

        entry = next(
            (e for e in self.task_store.list_entries() if e["id"] == definition.id), None
        )
        sketch_dir = self.task_store.sketch_dir(definition)
        return {
            "entry": entry,
            "diagnostics": diagnostics,
            "sketchPath": str(sketch_dir) if sketch_dir.is_dir() else None,
        }

    async def _tasks_delete(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        task_id = _str_arg(args, "taskId")
        deleted = await asyncio.to_thread(self.task_store.delete, task_id)
        if deleted:
            await self._rescan()
            await self._broadcast_tasks()
        return {"deleted": deleted}

    def _definition_arg(self, args: dict[str, Any]) -> TaskDefinition:
        """`TASK_INVALID` is for a document that is not a definition.

        A well-formed definition describing an impossible task — a channel this
        rig lacks, a reward line serving the wrong well — is NOT this. It is a
        successful reply carrying located diagnostics, exactly as a wiring
        document is.
        """
        raw = args.get("definition")
        if not isinstance(raw, dict):
            raise CommandError(ErrCode.TASK_INVALID, "`definition` must be an object.")
        if len(json.dumps(raw).encode()) > taskdef_store.MAX_DEFINITION_BYTES:
            raise CommandError(
                ErrCode.TASK_INVALID,
                f"The definition is over "
                f"{taskdef_store.MAX_DEFINITION_BYTES // 1024} KB — that is not a task.",
            )
        try:
            return TaskDefinition.from_json(raw)
        except TaskDefinitionError as exc:
            raise CommandError(ErrCode.TASK_INVALID, str(exc)) from exc

    async def _broadcast_tasks(self) -> None:
        await self.server.broadcast(
            event(Evt.TASKS_UPDATED, {"tasks": self.task_store.list_entries()})
        )

    # -- strobe vocabulary (TASKS.md#strobe-vocabulary) ------------------- #
    #
    # Every edit takes `_rig_gate` — it rebuilds the same generated folders a
    # wiring change does, and `_strobe_impact` installs a hypothetical
    # vocabulary exactly as `impact_of` installs a hypothetical wiring — then
    # leaves it for `_rebuild_generated`, which rescans and so cannot run inside.

    def _vocabulary_payload(self) -> dict[str, Any]:
        payload = rig_registry.vocabulary().to_json()
        try:
            self.vocab_store.load_strict()
            payload["editable"], payload["problem"] = True, None
        except strobe_store.StrobeRefused as exc:
            payload["editable"], payload["problem"] = False, str(exc)
        return payload

    async def _strobes_get(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        return await asyncio.to_thread(self._vocabulary_payload)

    async def _strobes_usage(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        name = self._strobe_name_arg(args)
        scan = bool(args.get("scan"))
        async with self._rig_gate:
            usage = await asyncio.to_thread(self._strobe_impact, name)
        if scan:
            index = await self._scan_archive()
            sessions = index.usage_of(usage["code"])
            usage["sessions"] = sessions
            if sessions["count"] and usage["removeBlocker"] is None:
                usage["removeBlocker"] = (
                    f"{name} is in {sessions['count']} recorded "
                    f"session{'' if sessions['count'] == 1 else 's'}; retire it instead."
                )
        return usage

    async def _strobes_add(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        name = self._strobe_name_arg(args)
        code = args.get("code")
        return await self._edit_vocabulary(
            lambda doc: strobe_store.add(
                doc,
                name,
                code,
                rationale=str(args.get("rationale") or ""),
                emitted_on=str(args.get("emittedOn") or ""),
            )
        )

    async def _strobes_edit(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        name = self._strobe_name_arg(args)
        return await self._edit_vocabulary(
            lambda doc: strobe_store.edit(
                doc,
                name,
                rationale=str(args.get("rationale") or ""),
                emitted_on=str(args.get("emittedOn") or ""),
            )
        )

    async def _strobes_retire(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        name = self._strobe_name_arg(args)
        confirm = bool(args.get("confirm"))

        def check(usage: dict[str, Any]) -> None:
            self._refuse_unconfirmed(usage, confirm, "Retiring")

        return await self._edit_vocabulary(
            lambda doc: strobe_store.retire(doc, name), name=name, check=check
        )

    async def _strobes_reinstate(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        name = self._strobe_name_arg(args)
        return await self._edit_vocabulary(lambda doc: strobe_store.reinstate(doc, name))

    async def _strobes_remove(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        name = self._strobe_name_arg(args)
        confirm = bool(args.get("confirm"))
        # The scan runs BEFORE the gate: it can take minutes on a cold cache
        # over a share, and holding the gate that long would stall the wiring
        # editor's previews. It is re-checked against the document inside the
        # gate by code, and a file recorded in the gap is the one race left —
        # which is why a running session refuses every edit outright.
        index = await self._scan_archive()

        def check(usage: dict[str, Any]) -> None:
            sessions = index.usage_of(usage["code"])
            if sessions["count"]:
                raise CommandError(
                    ErrCode.STROBE_IN_RECORDED_SESSION,
                    f"{name} is in {sessions['count']} recorded "
                    f"session{'' if sessions['count'] == 1 else 's'}, so its number can "
                    "never be reissued. Retire it instead.",
                    sessions,
                )
            self._refuse_unconfirmed(usage, confirm, "Removing")

        return await self._edit_vocabulary(
            lambda doc: strobe_store.remove(
                doc, name, sessions_containing=index.count(_code_in(doc, name))
            ),
            name=name,
            check=check,
        )

    async def _strobes_export(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        doc = await asyncio.to_thread(self._load_vocabulary_strict)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {
            "document": strobe_store.export_document(doc),
            "filename": f"strobe-vocabulary-{stamp}.json",
        }

    async def _strobes_import(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        other = args.get("document")
        if not isinstance(other, dict):
            raise CommandError(ErrCode.STROBE_INVALID, "That file is not a strobe vocabulary.")
        if len(json.dumps(other).encode()) > strobe_store.MAX_VOCAB_BYTES:
            raise CommandError(ErrCode.STROBE_INVALID, "That file is too large to be a vocabulary.")
        doc = await asyncio.to_thread(self._load_vocabulary_strict)
        try:
            plan = strobe_store.plan_merge(doc, other)
        except strobe_store.StrobeRefused as exc:
            raise _strobe_error(exc) from exc
        if not args.get("apply"):
            return {"plan": plan.to_json(), "vocabulary": None}
        vocabulary = await self._edit_vocabulary(
            lambda current: strobe_store.apply_merge(
                current, other, strobe_store.plan_merge(current, other)
            )
        )
        return {"plan": plan.to_json(), "vocabulary": vocabulary}

    # -- strobe helpers ---------------------------------------------------- #

    async def _edit_vocabulary(
        self,
        edit: Any,
        *,
        name: str | None = None,
        check: Any = None,
    ) -> dict[str, Any]:
        """Load, judge, edit, write, install, rebuild, announce — in that order.

        `check` sees the code's usage under the gate, so a task saved a moment
        after the page last looked is still counted. Nothing is written on any
        refusal path.
        """
        if self._running_session_id is not None:
            raise CommandError(
                ErrCode.STROBE_SESSION_RUNNING,
                "A session is running. Edit the vocabulary between sessions: every "
                "edit regenerates the sketches the boxes were flashed from.",
            )
        async with self._rig_gate:
            doc = await asyncio.to_thread(self._load_vocabulary_strict)
            if name is not None and check is not None:
                check(await asyncio.to_thread(self._strobe_impact, name))
            try:
                updated = edit(doc)
                await asyncio.to_thread(self.vocab_store.save, updated)
            except strobe_store.StrobeRefused as exc:
                raise _strobe_error(exc) from exc
            rig_registry.set_vocabulary_source(self.vocab_store.load)
            payload = await asyncio.to_thread(self._vocabulary_payload)
        await self._rebuild_generated()
        await self.server.broadcast(event(Evt.STROBES_UPDATED, payload))
        return payload

    def _load_vocabulary_strict(self) -> dict[str, Any]:
        try:
            return self.vocab_store.load_strict()
        except strobe_store.StrobeRefused as exc:
            raise _strobe_error(exc) from exc

    def _strobe_impact(self, name: str) -> dict[str, Any]:
        """`StrobeUsage` minus the archive: firmware, slots, tasks it would break.

        The task half is `impact_of`'s method with a vocabulary in place of a
        wiring: every saved task validated with and without the code, and only
        what is NEWLY broken reported. The hypothetical vocabulary is installed
        and restored in a `finally`, for the reason `impact_of` gives.
        """
        vocab = rig_registry.vocabulary()
        live = vocab.get(name)
        retired = vocab.retired_entry(name)
        if live is None and retired is None:
            raise CommandError(ErrCode.STROBE_INVALID, f"{name} is not in the strobe vocabulary.")
        code = live.code if live is not None else retired.code

        library_root, _source = discovery.library_root()
        refs = firmware_refs([
            (library_root, "sketch"),
            (self.task_store.root, "task"),
        ]).get(name, [])
        slot = vocab.slot_of(name)

        breaks: list[dict[str, Any]] = []
        if live is not None:
            doc = self._load_vocabulary_strict()
            try:
                hypothetical = strobe_store.retire(doc, name)
            except strobe_store.StrobeRefused:
                hypothetical = None
            if hypothetical is not None:
                breaks = _impact_under_vocabulary(hypothetical, self._task_store)

        blocker: str | None = None
        if slot is not None:
            blocker = (
                f"{name} is how a response port on slot {slot} reports; a port with "
                "a missing code records nothing, silently."
            )
        elif any(r.kind == "library" for r in refs):
            blocker = (
                f"the shared firmware library emits BF_{name}, so every sketch would "
                "stop compiling. Remove it from the library first."
            )
        return {
            "name": name,
            "code": code,
            "status": "live" if live is not None else "retired",
            "firmware": [r.to_json() for r in refs],
            "portSlot": slot,
            "breaks": breaks,
            "sessions": None,
            "retireBlocker": blocker if live is not None else f"{name} is already retired.",
            "removeBlocker": blocker,
        }

    def _refuse_unconfirmed(self, usage: dict[str, Any], confirm: bool, verb: str) -> None:
        name = usage["name"]
        blocker = usage["retireBlocker"] if verb == "Retiring" else usage["removeBlocker"]
        if blocker is not None:
            raise CommandError(ErrCode.STROBE_REQUIRED, f"{verb} {name} is refused: {blocker}")
        named_by = usage["breaks"] or usage["firmware"]
        if named_by and not confirm:
            raise CommandError(
                ErrCode.STROBE_WOULD_BREAK_TASKS,
                f"{verb} {name} would stop firmware that names it compiling.",
                {"breaks": usage["breaks"], "firmware": usage["firmware"]},
            )

    async def _scan_archive(self):  # noqa: ANN202
        """Every recorded file this machine can reach, reduced to code sets.

        Off the loop, progress broadcast every few dozen files so a cold scan
        over a share reads as working rather than hung.
        """
        loop = asyncio.get_running_loop()

        def progress(done: int, total: int) -> None:
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    self.server.broadcast(
                        event(Evt.STROBES_SCAN_PROGRESS, {"done": done, "total": total})
                    )
                )
            )

        roots = self._cohort_roots()
        return await asyncio.to_thread(self.strobe_scanner.scan, roots, progress)

    def _strobe_name_arg(self, args: dict[str, Any]) -> str:
        name = args.get("name")
        if not isinstance(name, str) or not name.strip():
            raise CommandError(ErrCode.STROBE_INVALID, "`name` must be a code name.")
        return name.strip()

    # -- rig wiring -------------------------------------------------------- #
    #
    # OFF-LOOP, all four. Preview and save re-validate every stored task profile
    # against the proposed wiring, and the event loop also owns six serial ports
    # and a 20 Hz output flush. They share one gate rather than taking one each,
    # because they are the same work -- several at once.

    async def _hardware_get(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        return await asyncio.to_thread(hardware_service.document_payload, self.hardware_store)

    async def _hardware_preview(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        document = self._rig_document_arg(args)
        async with self._rig_gate:
            return await asyncio.to_thread(
                hardware_service.preview_payload,
                self.hardware_store,
                document,
                self._task_store,
            )

    async def _hardware_save(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        document = self._rig_document_arg(args)
        confirm = bool(args.get("confirm"))

        async with self._rig_gate:
            breaks = await asyncio.to_thread(
                hardware_service.impact_of, document, self._task_store
            )
            if breaks and not confirm:
                # Not an error the operator cannot pass -- it is the "shown
                # loudly" half of "a pin change applies to everything". The app
                # does not veto a rewiring; it refuses to let one happen
                # unnoticed. Nothing is written on this path.
                raise CommandError(
                    ErrCode.RIG_WOULD_BREAK_TASKS,
                    f"This wiring would stop {len(breaks)} saved "
                    f"task{'' if len(breaks) == 1 else 's'} compiling.",
                    {"breaks": breaks},
                )
            try:
                stored = await asyncio.to_thread(self.hardware_store.save, document)
            except hardware_store.RigInvalid as exc:
                raise CommandError(
                    ErrCode.RIG_INVALID,
                    "This wiring document could not be saved.",
                    {"problems": [
                        {"location": loc, "message": msg} for loc, msg in exc.problems
                    ]},
                ) from exc

            # The write landed, so every later read must see it. Ordering
            # matters: install first, then report, or the reply would describe
            # the wiring that was in force a moment ago.
            self._install_rig_wiring()
            payload = await asyncio.to_thread(
                hardware_service.saved_payload, self.hardware_store, stored
            )
            payload["breaks"] = breaks

        # EVERY GENERATED SKETCH IS NOW STALE -- see `_rebuild_generated`. This
        # is what makes "a pin change applies to everything" true rather than a
        # claim, and it runs outside the gate because a rescan takes it.
        await self._rebuild_generated()
        await self._announce_rig(payload["status"])
        return payload

    async def _hardware_reset(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        async with self._rig_gate:
            await asyncio.to_thread(self.hardware_store.reset)
            self._install_rig_wiring()
            payload = await asyncio.to_thread(
                hardware_service.document_payload, self.hardware_store
            )
        # Reset is a wiring change like any other -- see `_hardware_save`.
        await self._rebuild_generated()
        await self._announce_rig(payload["status"])
        return payload

    def _rig_document_arg(self, args: dict[str, Any]) -> dict[str, Any]:
        """`RIG_INVALID` is for a document that is not a document.

        A well-formed document describing an impossible box is NOT this -- it
        is a successful reply carrying located problems.
        """
        document = args.get("document")
        if not isinstance(document, dict):
            raise CommandError(ErrCode.RIG_INVALID, "`document` must be an object.")
        if len(json.dumps(document).encode()) > hardware_store.MAX_RIG_BYTES:
            raise CommandError(
                ErrCode.RIG_INVALID,
                f"The document is over {hardware_store.MAX_RIG_BYTES // 1024} KB — "
                "that is not a pin map.",
            )
        return document

    async def _announce_rig(self, status: dict[str, Any]) -> None:
        """Tell every client the wiring moved.

        The composed channel map used to be a fact about the build, cached at
        module scope on the frontend under a comment saying it could not change
        while the app ran. It can now, and this is what keeps that cache honest.
        """
        await self.server.broadcast(event(Evt.HARDWARE_UPDATED, status))

    # --- backup (DATA.md#backup-mirroring) --------------------------

    async def _backup_sync_now(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """Copy anything the mirror is missing, on demand.

        Setting a backup directory doesn't backfill by itself — that could mean
        an unannounced multi-gigabyte copy the moment someone picks a folder on
        a network share. This is the deliberate version, and it's also how a
        user proves the target works before trusting it.
        """
        if self.backup is None:
            raise CommandError(ErrCode.INTERNAL, "backup manager isn't running")
        try:
            return await self.backup.sync_now()
        except BackupNotConfigured as exc:
            raise CommandError(ErrCode.BACKUP_UNAVAILABLE, str(exc)) from exc

    # --- analytics (PROTOCOL.md#analytics) ---------------------------------

    def _require_analytics(self) -> AnalyticsService:
        if self.analytics is None:
            raise CommandError(ErrCode.INTERNAL, "analytics isn't running")
        return self.analytics

    def _sketch_path_for_name(self, name: str) -> str | None:
        """A document's `sketch` field resolved against the sketch library —
        how an adopted orphan finds a `task.json` to decode with
        (`DATA.md#orphan-adoption`). Name collisions across categories are possible
        in principle; first discovery-order match wins, same as the picker.

        Falls back to profiles that *declare* the name in `legacyNames`
        (`TASKS.md#legacy-names`), which is how a run recorded by older software
        under a human label ("Shape - L") reaches the sketch that can decode it.
        Declared, never inferred: resemblance is not evidence, and decoding
        real data with the wrong strobe map is worse than not decoding it.

        The fallback index is built on first use rather than in `_rescan`,
        which runs on every settings push: a directory whose legacy names
        nobody asks about should cost no reads at all. It is keyed on the
        discovery object it was built from, so a re-scan invalidates it whether
        or not the code below remembered to.
        """
        match = next((s for s in self.discovery.sketches if s.name == name), None)
        if match is not None:
            return match.path

        with self._legacy_names_lock:
            if self._legacy_names_from is not self.discovery:
                self._legacy_names = task_profile.build_legacy_name_index(
                    self.discovery.sketches
                )
                self._legacy_names_from = self.discovery
            return self._legacy_names.get(name)

    async def _sessions_list(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """A cohort's sessions, chronologically. **Never touches the filesystem.**

        Deliberately cheap so the dashboard's selectors populate instantly
        while `analytics.summary` is still reading files.
        """
        cohort_id = _str_arg(args, "cohortId")
        include_aborted = args.get("includeAborted") is True
        sessions = await asyncio.to_thread(
            self.sessions.list_sessions, cohort_id, include_aborted=include_aborted
        )
        counts = await asyncio.to_thread(self.sessions.run_counts_by_session, cohort_id)
        # Adopted orphans (DATA.md#orphan-adoption) appear as payload-only synthetic
        # sessions so the Analytics selectors cover the whole archive. Both
        # sources are database reads — the no-filesystem rule holds.
        synthetic, synthetic_counts = await asyncio.to_thread(
            self._require_analytics().adopted_session_entries, cohort_id, sessions
        )
        merged = sorted(
            [*sessions, *synthetic], key=lambda s: (s.date, s.started_at, s.id)
        )
        return {
            "sessions": [
                session.to_list_item(
                    index + 1,
                    # Added, not either-or: a recorded session also counts
                    # the recovered files attributed to it (DATA.md#tidy-records).
                    run_count=counts.get(session.id, 0)
                    + synthetic_counts.get(session.id, 0),
                )
                for index, session in enumerate(merged)
            ]
        }

    async def _analytics_summary(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        cohort_id = _str_arg(args, "cohortId")
        with _cohort_errors():
            return await self._require_analytics().summary(
                cohort_id,
                session_ids=_opt_str_list(args.get("sessionIds")),
                animal_ids=_opt_str_list(args.get("animalIds")),
                min_counted=_opt_int(args.get("minCountedTrials")),
            )

    async def _analytics_set_false_start(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """A person's ruling on one run (`DATA.md#false-starts`)."""
        cohort_id = _str_arg(args, "cohortId")
        run_id = _str_arg(args, "runId")
        value = args.get("falseStart")
        if value is not None and not isinstance(value, bool):
            raise CommandError(ErrCode.BAD_MESSAGE, "`falseStart` must be true, false or null")
        analytics = self._require_analytics()
        with _cohort_errors():
            try:
                await asyncio.to_thread(analytics.set_false_start, cohort_id, run_id, value)
            except KeyError as exc:
                raise CommandError(
                    ErrCode.BAD_MESSAGE, f"run {run_id} is not in this cohort"
                ) from exc
        # The log's what-changed is recomputed around the run — the run after
        # it now compares with a different predecessor — so every session of
        # the cohort's log is re-announced, not only this one.
        if self.logbook is not None:
            await self.logbook.refresh(cohort_id)
        return {"runId": run_id}

    async def _analytics_series(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        run_ids = _opt_str_list(args.get("runIds")) or []
        if not run_ids:
            raise CommandError(ErrCode.BAD_MESSAGE, "`runIds` must be a non-empty list")
        mode = args.get("mode") if args.get("mode") in ("rolling", "cumulative") else "rolling"
        try:
            return await self._require_analytics().series(
                run_ids, mode=mode, metric_ids=_opt_str_list(args.get("metricIds"))
            )
        except ValueError as exc:
            raise CommandError(ErrCode.BAD_MESSAGE, str(exc)) from exc

    async def _analytics_rescan(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """The explicit archive walk (`DATA.md#database-first`) — never a side
        effect of opening a view."""
        cohort_id = _str_arg(args, "cohortId")
        with _cohort_errors():
            try:
                return await self._require_analytics().rescan(
                    cohort_id, adopt_orphans=args.get("adoptOrphans") is not False
                )
            except AnalyticsBusy as exc:
                raise CommandError(ErrCode.INTERNAL, str(exc)) from exc

    async def _sessions_tidy(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """Merge a day's split session records and drop empty ones
        (`DATA.md#tidy-records`).

        `apply` false (the default) is a preview. The held session is never
        touched, whatever the plan says; everything else the planner decides.
        """
        cohort_id = _str_arg(args, "cohortId")
        protect = {self._running_session_id} if self._running_session_id else set()
        with _cohort_errors():
            try:
                result = await self._require_analytics().tidy(
                    cohort_id,
                    apply=args.get("apply") is True,
                    protect=protect,
                    today=datetime.now().date().isoformat(),
                )
            except AnalyticsBusy as exc:
                raise CommandError(ErrCode.INTERNAL, str(exc)) from exc
        if result["applied"]:
            # Stale and set-up rows may have gone from the Dashboard's dock.
            await self._broadcast_lifecycle()
            # Notes may have moved to the kept record (`DATA.md#tidy-records`).
            if self.logbook is not None:
                await self.logbook.refresh(cohort_id)
        return result

    async def _analytics_recent_sessions(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """Folder-name recency across every active cohort — cheap on purpose,
        so the Dashboard can ask without the rescan's cost or its ceremony."""
        return await self._require_analytics().recent_sessions(_opt_int(args.get("limit")))

    async def _sessions_recover(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """The crash-recovery backfill (`DATA.md#crash-recovery`).

        Guarded against a running session: a live box's `.tsv` legitimately
        has no `.json` yet, and "recovering" it would mint a half-session
        document the real finalization then overwrites. One session runs at a
        time app-wide, so any running box means hands off every archive.
        """
        cohort_id = _str_arg(args, "cohortId")
        if self.runner is not None and self.runner.running_boxes():
            raise CommandError(
                ErrCode.SESSION_INVALID,
                "a session is running — its live .tsv files would look like "
                "orphans. End the session, then recover.",
            )
        with _cohort_errors():
            cohort = await asyncio.to_thread(self.cohorts.get, cohort_id)
        result = await asyncio.to_thread(recovery.recover_cohort, cohort.data_folder)
        return {**result, "cohortId": cohort_id}

    # --- sessions (PROTOCOL.md#prefixes-and-sessions) ---------------------

    def _require_runner(self) -> SessionRunner:
        if self.runner is None:
            raise CommandError(ErrCode.INTERNAL, "session runner isn't running")
        return self.runner

    async def _sessions_suggest_number(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        prefix_id = _str_arg(args, "prefixId")
        suggestion = await asyncio.to_thread(
            self.sessions.suggest_session_number, prefix_id
        )
        same_day = await asyncio.to_thread(
            self.sessions.session_numbers_on, prefix_id, datetime.now().date().isoformat()
        )
        return {"suggestion": suggestion, "sameDayNumbers": same_day}

    async def _sessions_create(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        cohort_id = _str_arg(args, "cohortId")
        prefix_id = _str_arg(args, "prefixId")
        session_number = str(args.get("sessionNumber") or "").strip()
        if not session_number:
            raise CommandError(ErrCode.SESSION_INVALID, "A session number is required.")
        duration = args.get("durationMinutes")
        if duration is not None and (
            isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0
        ):
            raise CommandError(
                ErrCode.SESSION_INVALID,
                "durationMinutes must be a positive whole number of minutes.",
            )

        try:
            cohort = await asyncio.to_thread(self.cohorts.get, cohort_id)
        except CohortNotFound as exc:
            raise CommandError(ErrCode.SESSION_INVALID, "That cohort no longer exists.") from exc

        # Readiness (`ARCHITECTURE.md#configuration`): at least one group with
        # a box-assigned animal.
        if not _is_ready_to_run(cohort):
            raise CommandError(
                ErrCode.SESSION_NOT_READY,
                "This cohort has no group with a box-assigned animal yet.",
            )

        prefix = await asyncio.to_thread(self.sessions.get_prefix, prefix_id)
        if prefix is None:
            raise CommandError(ErrCode.SESSION_INVALID, "Unknown session prefix.")

        when = datetime.now()
        folder = resolve_session_folder(
            cohort.data_folder, prefix.name, session_number, when
        )
        try:
            await asyncio.to_thread(folders.ensure_folder, folder)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(
                ErrCode.SESSION_INVALID, f"Couldn't create the session folder: {exc}"
            ) from exc

        session = await asyncio.to_thread(
            self.sessions.create_session,
            cohort_id,
            prefix,
            session_number,
            when.date().isoformat(),
            str(folder),
            duration,
            args.get("recording") is True,
        )
        await self._broadcast_lifecycle()
        return {"session": session.to_json()}

    async def _sessions_abandon(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        session_id = _str_arg(args, "sessionId")
        try:
            session = await asyncio.to_thread(self.sessions.get_session, session_id)
        except SessionNotFound as exc:
            raise CommandError(ErrCode.SESSION_INVALID, str(exc)) from exc
        # Once a group has run the record holds real history; only a session
        # still in Step 2 limbo may be discarded.
        if session.status != "configuring":
            raise CommandError(
                ErrCode.SESSION_INVALID,
                f"session is {session.status}; only a configuring session can be abandoned",
            )
        # A confirmed-but-unstarted mapping may already sit in the runner —
        # drop it so the next session can't inherit this one's boxes.
        if self._running_session_id == session_id:
            self._require_runner().clear()
            self._running_session_id = None
        if self.intan is not None:
            # A recording that was set up and never started. One that IS
            # running is left alone -- `release` refuses nothing and stops
            # nothing.
            self.intan.release()
        session = await asyncio.to_thread(self.sessions.set_status, session_id, "aborted")
        await self._release_baseline()
        await self._broadcast_lifecycle()
        return {"session": session.to_json()}

    async def _sessions_confirm_mapping(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        session_id = _str_arg(args, "sessionId")
        group_id = _str_arg(args, "groupId")
        boxes = args.get("boxes")
        if not isinstance(boxes, list):
            raise CommandError(ErrCode.SESSION_INVALID, "`boxes` must be a list")

        try:
            session = await asyncio.to_thread(self.sessions.get_session, session_id)
            cohort = await asyncio.to_thread(self.cohorts.get, session.cohort_id)
        except (SessionNotFound, CohortNotFound) as exc:
            raise CommandError(ErrCode.SESSION_INVALID, str(exc)) from exc

        names = {a.id: a.name for a in cohort.animals}
        label = f"{session.prefix_name}_{session.session_number}"
        box_configs: list[BoxConfig] = []
        for entry in boxes:
            if not isinstance(entry, dict):
                continue
            box = entry.get("box")
            animal_id = str(entry.get("animalId") or "")
            sketch_path = str(entry.get("sketchPath") or "")
            config = entry.get("config") if isinstance(entry.get("config"), dict) else {}
            if not isinstance(box, int) or animal_id not in names or not sketch_path:
                raise CommandError(
                    ErrCode.SESSION_INVALID,
                    "A box mapping is missing its box, animal, or sketch.",
                )
            profile = None
            try:
                profile = await asyncio.to_thread(task_profile.load_profile, sketch_path)
            except task_profile.TaskProfileError:
                profile = None  # profile-less: bare START, raw log
            try:
                start_command = build_start_command(profile, config)
            except task_profile.TaskProfileError as exc:
                # The profile declares more than the firmware's line buffer can
                # hold. Refusing the mapping is the point: the board cannot
                # report a truncated START, so letting this through would run
                # the session on whichever parameters happened to fit.
                raise CommandError(
                    ErrCode.TASK_PROFILE_INVALID, str(exc), {"box": box}
                ) from exc
            box_configs.append(
                BoxConfig(
                    box=box,
                    animal_id=animal_id,
                    animal_name=names[animal_id],
                    sketch_path=sketch_path,
                    sketch_name=Path(sketch_path).name,
                    start_command=start_command,
                    config_metadata=dict(config),
                    profile=profile,
                )
            )

        self._require_runner().configure(
            Path(session.folder_path),
            label,
            group_id,
            box_configs,
            duration_s=(
                session.duration_minutes * 60.0
                if session.duration_minutes is not None
                else None
            ),
        )
        self._running_session_id = session_id
        # From here until the session ends the boxes belong to the runner: they
        # will carry task sketches and fall idle between flashes, and a
        # baseline restore landing in that window would erase the very sketch
        # this mapping just chose
        # (`ARCHITECTURE.md#three-rules-it-never-breaks`). Also extinguishes
        # the placement walk's
        # lights, in case the client didn't.
        if self.utility is not None:
            self.utility.hold()
        await self._broadcast_lifecycle()
        return {"ok": True}

    async def _sessions_status(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        session_id = _str_arg(args, "sessionId")
        try:
            session = await asyncio.to_thread(self.sessions.get_session, session_id)
        except SessionNotFound as exc:
            raise CommandError(ErrCode.SESSION_INVALID, str(exc)) from exc
        runner = self._require_runner()
        return {
            "session": session.to_json(),
            "groupId": runner.group_id,
            "boxes": runner.snapshot(),
        }

    async def _sessions_active(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        unfinished = await asyncio.to_thread(self.sessions.list_unfinished)
        return build_active_payload(self._running_session_id, self.runner, unfinished)

    async def _broadcast_lifecycle(self) -> None:
        """Push the fresh `ActiveSessions` snapshot to every client.

        Called from each handler that changes session identity or status —
        never from per-box transitions, which stay on `port.state`.
        """
        unfinished = await asyncio.to_thread(self.sessions.list_unfinished)
        await self.server.broadcast(
            event(
                Evt.SESSION_LIFECYCLE,
                build_active_payload(self._running_session_id, self.runner, unfinished),
            )
        )

    async def _sessions_start_all(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        session_id = _str_arg(args, "sessionId")
        runner = self._require_runner()
        await self._begin_recording_if_any(session_id)
        for box in runner.configured_boxes():
            # `start_box` is a no-op for a box already running
            # (`ARCHITECTURE.md#running-boxes`).
            with _session_errors(box):
                runner.start_box(box)
        await asyncio.to_thread(self._open_group_run, session_id, runner.group_id)
        session = await asyncio.to_thread(self.sessions.set_status, session_id, "running")
        await self._broadcast_lifecycle()
        return {"session": session.to_json()}

    async def _sessions_end_group(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """End the group on the rig and wait BETWEEN GROUPS
        (`ARCHITECTURE.md#group-step`).

        The session stays `running` and held, with an empty runner: which group
        runs next is the operator's choice, made on the group step, and a
        session is only ever finished by an explicit `sessions.end`. The sidecar
        used to pick the next group by cohort order and auto-complete after the
        last one; both were retired with the order itself.
        """
        session_id = _str_arg(args, "sessionId")
        await self._end_all_boxes(session_id)
        session = await asyncio.to_thread(self._close_group_run, session_id)
        self._clear_runner()
        # The boxes are idle and the operator is about to walk the rig again for
        # the next group, so the baseline comes back now rather than after the
        # whole session — that walk is the one that needs the lights.
        await self._release_baseline()
        await self._broadcast_lifecycle()
        return {"session": session.to_json()}

    async def _sessions_resume(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """Continue one of today's sessions with another group.

        Deliberately NOT session resumption
        (`DATA.md#continuing-between-groups`): nothing is picked
        up mid-group. A group that was running when the app died is closed as
        it stands -- its animals' `.tsv` files are the record, and `sessions.recover`
        backfills them -- and the session re-enters the between-groups state
        `sessions.endGroup` leaves, as if the operator had pressed Switch Group.

        Same day only: the session folder carries its date in its name, and a
        run appended to it tomorrow would be filed under the wrong day.
        """
        session_id = _str_arg(args, "sessionId")
        try:
            session = await asyncio.to_thread(self.sessions.get_session, session_id)
        except SessionNotFound as exc:
            raise CommandError(ErrCode.SESSION_INVALID, str(exc)) from exc
        if session.status not in ("running", "completed"):
            raise CommandError(
                ErrCode.SESSION_INVALID,
                f"session is {session.status}; only one that ran a group can be continued",
            )
        if not session.group_runs:
            raise CommandError(
                ErrCode.SESSION_INVALID,
                "this session never ran a group — start a new session instead",
            )
        if session.date != datetime.now().date().isoformat():
            raise CommandError(
                ErrCode.SESSION_INVALID,
                "only today's sessions can be continued — its folder is named for "
                f"{session.date}",
            )
        held = self._running_session_id
        if held is not None and held != session_id:
            raise CommandError(
                ErrCode.SESSION_INVALID,
                "another session is open — end it before continuing this one",
            )
        if held == session_id and self._require_runner().configured_boxes():
            # Already held with a mapping loaded: nothing to resume.
            return {"session": session.to_json()}
        await asyncio.to_thread(self._close_group_run, session_id)
        session = await asyncio.to_thread(self.sessions.set_status, session_id, "running")
        self._clear_runner()
        self._running_session_id = session_id
        await self._broadcast_lifecycle()
        return {"session": session.to_json()}

    def _clear_runner(self) -> None:
        """Drop the finished group's mapping so the runner holds no boxes.

        Between groups the runner must not still describe the previous group:
        a reload would otherwise offer Start All on animals already carried
        home. `clear` refuses while a run is active, which after `end_all`
        cannot be the case -- but a refusal is logged rather than raised,
        because the group HAS ended and the session must not be stranded.
        """
        if self.runner is None:
            return
        try:
            self.runner.clear()
        except RuntimeError:
            log.warning("runner still holds active runs after the group ended")

    async def _sessions_end(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        session_id = _str_arg(args, "sessionId")
        held = self._running_session_id == session_id
        # Close Out on a crash-orphaned session reaches here too, and must not
        # stop whichever OTHER session the runner is holding.
        if held or self._running_session_id is None:
            await self._end_all_boxes(session_id)
        await asyncio.to_thread(self._close_group_run, session_id)
        session = await asyncio.to_thread(self.sessions.set_status, session_id, "completed")
        if held:
            self._clear_runner()
            self._running_session_id = None
        if held or self._running_session_id is None:
            await self._release_baseline()
        await self._broadcast_lifecycle()
        # The session's clock just closed; its log's end time and elapsed did too.
        if self.logbook is not None:
            await self.logbook.refresh(session.cohort_id, [session.id])
        return {"session": session.to_json()}

    # --- recording (RECORDING.md#start-and-end) ---------------------------

    #: How long a recording waits for each box to finish the trial it is in
    #: after STOP. Longer than any trial the lab runs -- a 20 s error delay plus
    #: a 4 s ITI plus the holds -- and the operator can cut it short.
    RECORDING_GRACE_S = 45.0

    async def _is_recording_session(self, session_id: str) -> bool:
        try:
            session = await asyncio.to_thread(self.sessions.get_session, session_id)
        except SessionNotFound:
            return False
        return session.recording is not None

    async def _begin_recording_if_any(self, session_id: str) -> None:
        """Start RHX recording BEFORE any box starts, or refuse.

        The one place the recording may fail the session path, and on purpose:
        a behavior session quietly missing its electrophysiology cannot be
        re-run, so this raises while no animal has seen a trial yet.
        """
        if self.intan is None or not await self._is_recording_session(session_id):
            return
        runner = self._require_runner()
        if not self.intan.configured_for(session_id, runner.group_id):
            raise CommandError(
                ErrCode.INTAN_NOT_READY,
                "This is a recording session, but no recording is set up for this "
                "group. Finish the Recording step first.",
            )
        with _intan_errors():
            await self.intan.start_recording()

    async def _end_all_boxes(self, session_id: str) -> None:
        """End every box, and the recording around them if there is one.

        Order is the whole point: STOP the boxes, WAIT for each to close its
        trial, and only then stop RHX -- so the last event of every animal is
        inside the recording, with a post-roll after it.
        """
        runner = self._require_runner()
        intan = self.intan
        if intan is None or not intan.is_recording:
            await runner.end_all("operator stop")
            if intan is not None:
                intan.release()
            return
        await runner.end_all(
            "operator stop",
            graceful_timeout_s=self.RECORDING_GRACE_S,
            force=intan.force_stop,
            on_waiting=intan.note_waiting,
        )
        run = await intan.stop_recording()
        if run is not None:
            await asyncio.to_thread(self._record_recording_run, session_id, run)

    def _record_recording_run(self, session_id: str, run: dict[str, Any]) -> None:
        session = self.sessions.get_session(session_id)
        recording = dict(session.recording or {"runs": []})
        recording["runs"] = [*recording.get("runs", []), run]
        self.sessions.set_recording(session_id, recording)

    async def _release_baseline(self) -> None:
        """Hand the rig back to the utility baseline once a session lets go."""
        if self.utility is None:
            return
        self.utility.release()
        self.utility.ensure()
        await self.utility.publish()

    def _open_group_run(self, session_id: str, group_id: str) -> None:
        """Record that a group started running.

        What the group step reads to badge a group "ran 10:42", and what
        `sessions.resume` requires before a session can be continued. Deduped
        only against an OPEN run of the same group: running a group a second
        time is allowed and appends a second entry, while Start All after a
        per-box start (both in one group run) does not.
        """
        session = self.sessions.get_session(session_id)
        if any(
            run.group_id == group_id and run.ended_at is None
            for run in session.group_runs
        ):
            return
        runs = [*session.group_runs, GroupRun(group_id=group_id, order=len(session.group_runs), started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))]
        self.sessions.set_group_runs(session_id, runs)

    def _close_group_run(self, session_id: str) -> Session:
        """Close the open group run, if there is one."""
        session = self.sessions.get_session(session_id)
        runs = list(session.group_runs)
        for index, run in enumerate(runs):
            if run.ended_at is None:
                runs[index] = replace(run, ended_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                return self.sessions.set_group_runs(session_id, runs)
        return session

    async def _port_start_session(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        box = _box_arg(args)
        session_id = self._running_session_id
        if session_id is not None:
            await self._begin_recording_if_any(session_id)
        runner = self._require_runner()
        with _session_errors(box):
            runner.start_box(box)
        if session_id is not None and runner.group_id:
            # A group started one box at a time has run exactly as much as one
            # started with Start All. Without this it was never recorded: the
            # group step could not say it had run, and the session sat in
            # `configuring`, where Back on the next mapping discarded it.
            await asyncio.to_thread(self._open_group_run, session_id, runner.group_id)
            session = await asyncio.to_thread(self.sessions.get_session, session_id)
            if session.status != "running":
                await asyncio.to_thread(self.sessions.set_status, session_id, "running")
                await self._broadcast_lifecycle()
        return {"state": self._require_ports().handler(box).state.value}

    async def _port_stop_session(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        box = _box_arg(args)
        with _session_errors(box):
            self._require_runner().stop_box(box)
        return {"state": self._require_ports().handler(box).state.value}

    async def _on_animal_ended(self, run: ActiveRun, reason: str) -> None:
        """Record the run and tell the frontend (`session.animalEnded`)."""
        if self._running_session_id is not None:
            # Snapshot the profile that actually decoded this run
            # (`DATA.md#which-profile-decodes-a-run`). A
            # `task.json` lives beside its sketch and can be edited or deleted
            # long after a session, so without this the run would silently be
            # re-interpreted years later with whatever codes are current.
            profile_hash = None
            if run.config.profile is not None:
                try:
                    profile_hash = await asyncio.to_thread(
                        self.profiles.remember_profile, run.config.profile
                    )
                except Exception:  # noqa: BLE001 - never fail a finalization over this
                    log.exception("couldn't snapshot the task profile for box %d", run.box)
            # The parameters this run actually ran on (`TASKS.md#three-layer-merge`).
            # They already reach
            # the session file; recording them here is what makes them
            # queryable, and what lets Analytics tell two differently-tuned runs
            # of the same sketch apart — `profile_hash` cannot, it covers only
            # the declaration.
            run_config = dict(run.config.config_metadata) or None
            await asyncio.to_thread(
                self.sessions.record_animal_run,
                SessionAnimalRun(
                    id=run.run_id,
                    session_id=self._running_session_id,
                    animal_id=run.config.animal_id,
                    box_number=run.box,
                    sketch_path=run.config.sketch_path,
                    file_path=run.file_json,
                    started_at=run.started_at,
                    ended_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    stop_reason=reason,
                    profile_hash=profile_hash,
                    config=run_config,
                    params_hash=task_profile.params_hash(run_config),
                ),
            )
        if self.intan is not None:
            self.intan.box_ended(run.box, run.config.animal_name, reason)
        await self.server.broadcast(
            event(
                Evt.SESSION_ANIMAL_ENDED,
                {
                    "box": run.box,
                    "animalId": run.config.animal_id,
                    "stopReason": reason,
                    "filePath": run.file_json,
                },
            )
        )
        # The run's what-changed entry exists now (`DATA.md#what-changed`).
        # After the event above, and never able to fail a finalization.
        if self.logbook is not None and self._running_session_id is not None:
            try:
                session = await asyncio.to_thread(
                    self.sessions.get_session, self._running_session_id
                )
                await self.logbook.refresh(session.cohort_id, [session.id])
            except Exception:  # noqa: BLE001
                log.exception("logbook: couldn't announce box %d's run", run.box)

    # --- the session log (DATA.md#the-session-log) ---------------------------

    def _require_logbook(self) -> LogbookService:
        if self.logbook is None:
            raise CommandError(ErrCode.INTERNAL, "the session log isn't running")
        return self.logbook

    async def _logbook_cohort(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        cohort_id = _str_arg(args, "cohortId")
        with _cohort_errors():
            return await self._require_logbook().cohort(cohort_id)

    async def _logbook_open_flags(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        cohort_id = _str_arg(args, "cohortId")
        with _cohort_errors():
            return await self._require_logbook().open_flags(cohort_id)

    async def _logbook_add_note(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        session_id = _str_arg(args, "sessionId")
        with _logbook_errors():
            return await self._require_logbook().add_note(session_id, args)

    async def _logbook_edit_note(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        note_id = _str_arg(args, "noteId")
        fields = {k: v for k, v in args.items() if k != "noteId"}
        with _logbook_errors():
            return await self._require_logbook().edit_note(note_id, fields)

    async def _logbook_delete_note(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        note_id = _str_arg(args, "noteId")
        with _logbook_errors():
            return await self._require_logbook().delete_note(note_id)

    async def _logbook_resolve_flag(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        note_id = _str_arg(args, "noteId")
        session_id = args.get("sessionId")
        with _logbook_errors():
            return await self._require_logbook().resolve_flag(
                note_id,
                args.get("resolved") is True,
                session_id if isinstance(session_id, str) and session_id else None,
            )

    async def _logbook_set_session_log(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        session_id = _str_arg(args, "sessionId")
        fields = {k: args[k] for k in ("operator", "summary") if k in args}
        with _logbook_errors():
            return await self._require_logbook().set_session_log(session_id, fields)

    # --- Intan recording (RECORDING.md) -----------------------------------

    def _require_intan(self) -> IntanService:
        if self.intan is None:
            raise CommandError(ErrCode.INTERNAL, "the recording layer isn't running")
        return self.intan

    async def _intan_status(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        return self._require_intan().status_json()

    async def _intan_connect(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        intan = self._require_intan()
        with _intan_errors():
            await intan.connect()
        return intan.status_json()

    async def _intan_disconnect(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        intan = self._require_intan()
        with _intan_errors():
            await intan.disconnect()
        return intan.status_json()

    async def _intan_configure(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        intan = self._require_intan()
        session_id = _str_arg(args, "sessionId")
        group_id = _str_arg(args, "groupId")
        config = args.get("config")
        if not isinstance(config, dict):
            raise CommandError(ErrCode.BAD_MESSAGE, "`config` must be an object")
        try:
            session = await asyncio.to_thread(self.sessions.get_session, session_id)
            cohort = await asyncio.to_thread(self.cohorts.get, session.cohort_id)
        except (SessionNotFound, CohortNotFound) as exc:
            raise CommandError(ErrCode.SESSION_INVALID, "That session no longer exists.") from exc
        if session.recording is None:
            raise CommandError(ErrCode.SESSION_INVALID, "That session is not a recording.")

        group = next((g for g in cohort.groups if g.id == group_id), None)
        group_name = group.name if group is not None else group_id
        # `<prefix>_<number>_<date>_<group>`, RHX appends its own timestamp. No
        # spaces: the name is one token of a `set` command.
        base = "_".join(
            _filename_token(part)
            for part in (session.prefix_name, session.session_number, session.date, group_name)
        )
        runner = self.runner
        animals = {
            cfg.box: cfg.animal_name for cfg in (runner.box_configs() if runner else [])
        }
        mapping = ", ".join(
            f"box {b['box']}={animals.get(b['box'], '?')} port {b.get('port')}"
            for b in config.get("boxes") or []
            if isinstance(b, dict)
        )
        notes = (
            f"Ephymeris {session.prefix_name} {session.session_number} {session.date}",
            f"cohort {cohort.name} group {group_name}",
            mapping,
        )
        with _intan_errors():
            await intan.configure(session_id, group_id, config, base, notes)
        return intan.status_json()

    async def _intan_parse_probe_map(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        path = _str_arg(args, "path")
        try:
            parsed = await asyncio.to_thread(intan_probemap.parse_file, path)
        except intan_probemap.ProbeMapError as exc:
            raise CommandError(ErrCode.INTAN_NOT_READY, str(exc)) from exc
        return {"probeMap": parsed}

    async def _intan_probe_map(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        return {"probeMap": self._require_intan().probe_map_for(_box_arg(args))}

    async def _intan_set_threshold(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        channel = _str_arg(args, "channel")
        with _intan_errors():
            value = await self._require_intan().set_threshold(channel, args.get("microvolts"))
        return {"channel": channel.upper(), "microvolts": value}

    async def _intan_scope_open(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        kind = _str_arg(args, "kind")
        params = args.get("params") if isinstance(args.get("params"), dict) else {}
        with _intan_errors():
            scope_id = await self._require_intan().open_scope(
                kind, _box_arg(args), args.get("channel"), params
            )
        return {"scopeId": scope_id}

    async def _intan_scope_update(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        params = args.get("params") if isinstance(args.get("params"), dict) else None
        with _intan_errors():
            ok = await self._require_intan().update_scope(
                _str_arg(args, "scopeId"), args.get("channel"), params
            )
        return {"ok": ok}

    async def _intan_scope_close(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        with _intan_errors():
            await self._require_intan().close_scope(_str_arg(args, "scopeId"))
        return {"ok": True}

    async def _intan_force_stop(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_intan().force_stop.set()
        return {"ok": True}

    # --- internals --------------------------------------------------------

    async def _rescan(self) -> None:
        self.discovery = discovery.discover(self.task_store.root, self.pinned_root)
        result = self.discovery
        log.info(
            "sketch library %s (%s): %d sketches, %d skipped",
            result.library.state,
            result.library.path,
            len(result.sketches),
            len(result.skipped),
        )
        await self.server.broadcast(event(Evt.SKETCHES_UPDATED, result.to_json()))


def _is_ready_to_run(cohort: Any) -> bool:
    """`ARCHITECTURE.md#configuration` — ready if any group holds a
    box-assigned animal."""
    return any(a.box_number is not None for a in cohort.animals)


class _session_errors:
    """Map runner/port errors onto typed session protocol codes."""

    def __init__(self, box: int) -> None:
        self.box = box

    def __enter__(self) -> "_session_errors":
        return self

    def __exit__(self, _exc_type, exc, _tb) -> bool:  # noqa: ANN001
        if exc is None:
            return False
        if isinstance(exc, KeyError):
            raise CommandError(
                ErrCode.SESSION_INVALID,
                f"Box {self.box} hasn't had its mapping confirmed yet.",
                {"box": self.box},
            ) from exc
        if isinstance(exc, PortNotBound):
            raise CommandError(ErrCode.PORT_NOT_BOUND, str(exc), {"box": self.box}) from exc
        if isinstance(exc, BoardNotDetected):
            raise CommandError(ErrCode.PORT_OPEN_FAILED, str(exc), {"box": self.box}) from exc
        if isinstance(exc, PortBusy):
            raise CommandError(
                ErrCode.ILLEGAL_TRANSITION, str(exc), {"box": self.box}
            ) from exc
        if isinstance(exc, IllegalTransition):
            raise CommandError(
                ErrCode.ILLEGAL_TRANSITION,
                str(exc),
                {"box": self.box, "from": exc.current.value, "to": exc.requested.value},
            ) from exc
        return False


class _intan_errors:
    """Map the recording layer's failures onto its three protocol codes.

    Three, because the operator's next step differs: click Connect in RHX
    (UNAVAILABLE), fix the setup (NOT_READY), or read what RHX said
    (COMMAND_FAILED).
    """

    def __enter__(self) -> "_intan_errors":
        return self

    def __exit__(self, _exc_type, exc, _tb) -> bool:  # noqa: ANN001
        if exc is None:
            return False
        if isinstance(exc, IntanNotReady):
            raise CommandError(ErrCode.INTAN_NOT_READY, str(exc)) from exc
        if isinstance(exc, RhxUnavailable):
            raise CommandError(ErrCode.INTAN_UNAVAILABLE, str(exc)) from exc
        if isinstance(exc, RhxCommandFailed):
            raise CommandError(
                ErrCode.INTAN_COMMAND_FAILED, str(exc), {"command": exc.command}
            ) from exc
        if isinstance(exc, RhxError):
            raise CommandError(ErrCode.INTAN_COMMAND_FAILED, str(exc)) from exc
        return False


def _filename_token(text: str) -> str:
    """One piece of an RHX base filename: no spaces (the name is a single
    token of a `set` command) and nothing a filesystem objects to."""
    cleaned = "".join(c if c.isalnum() or c in "-." else "-" for c in str(text).strip())
    return cleaned.strip("-") or "x"


def _str_arg(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CommandError(ErrCode.BAD_MESSAGE, f"`{key}` must be a non-empty string")
    return value


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _opt_str_list(value: Any) -> list[str] | None:
    """A list of strings, or `None` for absent. An empty list is not absent."""
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, str)]


class _cohort_errors:
    """Map cohort-layer exceptions onto the typed protocol codes."""

    def __enter__(self) -> "_cohort_errors":
        return self

    def __exit__(self, _exc_type, exc, _tb) -> bool:  # noqa: ANN001
        if exc is None:
            return False
        if isinstance(exc, CohortNotFound):
            raise CommandError(ErrCode.COHORT_NOT_FOUND, "That cohort no longer exists.")
        if isinstance(exc, NameTaken):
            raise CommandError(
                ErrCode.COHORT_NAME_TAKEN,
                f"Another active cohort is already called “{exc}”.",
                {"field": "name"},
            )
        if isinstance(exc, NotArchived):
            raise CommandError(
                ErrCode.COHORT_NOT_ARCHIVED,
                "Archive this cohort before deleting it permanently.",
            )
        if isinstance(exc, ValidationError):
            # Per-field so the editor can render errors against the right row.
            raise CommandError(
                ErrCode.COHORT_INVALID, "Some entries need fixing.", exc.errors
            )
        if isinstance(exc, DataFolderError):
            raise CommandError(ErrCode.DATA_FOLDER_INVALID, str(exc))
        return False


class _logbook_errors:
    """Map session-log refusals onto `SESSION_INVALID`, the code every other
    'that session command can't apply' already uses."""

    def __enter__(self) -> "_logbook_errors":
        return self

    def __exit__(self, _exc_type, exc, _tb) -> bool:  # noqa: ANN001
        if exc is None:
            return False
        if isinstance(exc, NoteInvalid):
            raise CommandError(ErrCode.SESSION_INVALID, str(exc)) from exc
        if isinstance(exc, NoteNotFound):
            raise CommandError(ErrCode.SESSION_INVALID, "That note no longer exists.") from exc
        if isinstance(exc, SessionNotFound):
            raise CommandError(ErrCode.SESSION_INVALID, "That session no longer exists.") from exc
        if isinstance(exc, CohortNotFound):
            raise CommandError(ErrCode.COHORT_NOT_FOUND, "That cohort no longer exists.") from exc
        return False


def _box_arg(args: dict[str, Any]) -> int:
    box = args.get("box")
    if not isinstance(box, int) or isinstance(box, bool):
        raise CommandError(ErrCode.BAD_MESSAGE, "`box` must be an integer 1–6")
    return box


class _mapped_errors:
    """Translate hardware-layer exceptions into typed protocol errors.

    The frontend renders whatever comes back here; it never decides for itself
    whether an operation was legal (`ARCHITECTURE.md#port-state-machine`).
    """

    def __init__(self, box: int) -> None:
        self.box = box

    def __enter__(self) -> "_mapped_errors":
        return self

    def __exit__(self, exc_type, exc, _tb) -> bool:  # noqa: ANN001
        if exc is None:
            return False
        if isinstance(exc, PortNotBound):
            raise CommandError(ErrCode.PORT_NOT_BOUND, str(exc), {"box": self.box}) from exc
        if isinstance(exc, BoardNotDetected):
            raise CommandError(ErrCode.PORT_OPEN_FAILED, str(exc), {"box": self.box}) from exc
        if isinstance(exc, PortBusy):
            raise CommandError(
                ErrCode.SEND_NOT_PASSTHROUGH, str(exc), {"box": self.box}
            ) from exc
        if isinstance(exc, IllegalTransition):
            raise CommandError(
                ErrCode.ILLEGAL_TRANSITION,
                str(exc),
                {"box": self.box, "from": exc.current.value, "to": exc.requested.value},
            ) from exc
        if isinstance(exc, FlashFailed):
            raise CommandError(
                ErrCode.FLASH_FAILED,
                exc.message,
                {"box": self.box, "phase": exc.phase, "output": exc.detail},
            ) from exc
        if isinstance(exc, OSError):
            raise CommandError(ErrCode.PORT_OPEN_FAILED, str(exc), {"box": self.box}) from exc
        return False


def _strobe_error(exc: strobe_store.StrobeRefused) -> CommandError:
    code = {
        "invalid": ErrCode.STROBE_INVALID,
        "required": ErrCode.STROBE_REQUIRED,
        "in_recorded_session": ErrCode.STROBE_IN_RECORDED_SESSION,
        "would_break_tasks": ErrCode.STROBE_WOULD_BREAK_TASKS,
        "import_conflict": ErrCode.STROBE_IMPORT_CONFLICT,
        "unreadable": ErrCode.STROBE_VOCABULARY_UNREADABLE,
    }.get(exc.reason, ErrCode.STROBE_INVALID)
    return CommandError(code, str(exc), exc.detail or None)


def _code_in(doc: dict[str, Any], name: str) -> int:
    entry = doc.get("codes", {}).get(name) or doc.get("retired", {}).get(name) or {}
    return int(entry.get("code", -1))


def _impact_under_vocabulary(document: dict[str, Any], tasks: Any) -> list[dict[str, Any]]:
    """`hardware/service.impact_of`, for a hypothetical vocabulary.

    Which saved tasks generate today and would not under `document` — NEWLY,
    so a task already failing for its own reasons is not blamed on this edit.
    """
    import copy

    if tasks is None:
        return []
    entries = list(tasks.list_entries())
    if not entries:
        return []
    before = {e["id"]: tasks.failures(e["id"]) for e in entries}
    saved = rig_registry.current_vocabulary_source()
    try:
        rig_registry.set_vocabulary_source(lambda: copy.deepcopy(document))
        after = {e["id"]: tasks.failures(e["id"]) for e in entries}
    finally:
        rig_registry.set_vocabulary_source(saved)
    out: list[dict[str, Any]] = []
    for entry in entries:
        gained = sorted(after[entry["id"]] - before[entry["id"]])
        if gained:
            out.append({"specId": entry["id"], "label": entry.get("label"), "codes": gained})
    return out


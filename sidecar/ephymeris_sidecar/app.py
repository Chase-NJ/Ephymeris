"""Application state and command handlers.

Keeps `__main__` thin and owns the hardware layer. Each handler takes its
command's schema-checked arguments and returns its result; the exceptions it
lets through are answered by `wire_errors.py` (`ARCHITECTURE.md#dispatch`), so
`ports/` and every other domain package stay protocol-free.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analytics import AnalyticsService, CohortArchive
from .analytics.archive import ArchiveChange
from .analytics.repository import AnalyticsRepository
from .backup import BackupManager
from .boards import create_board_tool
from .boards.tool import BoardTool
from .cohorts import folders, grouping, move_apply, relocate
from .cohorts.move import MoveRequest
from .cohorts.db import DB_FILENAME, Database, has_mark
from .cohorts.repository import CohortRepository
from .sessions.paths import resolve_session_folder
from .hardware import service as hardware_service
from .hardware import store as hardware_store
from .intan import probemap as intan_probemap
from .intan.service import IntanService
from .logbook.service import LogbookService
from .rig import definition as rig_definition
from .rig import registry as rig_registry
from .sessions.repository import SessionRepository
from .sessions.lifecycle import MappingEntry, SessionLifecycle
from .sessions.runner import SessionRunner
from .strobes import store as strobe_store
from .strobes.editor import VocabularyEditor
from .strobes.usage import ArchiveScanner
from .taskdef import bundled as bundled_sketches
from .taskdef import store as taskdef_store
from .taskdef import transfer as task_transfer
from .taskdef.model import TaskDefinition
from .taskdef.validate import validate as validate_task
from .tasks import profile as task_profile
from .tasks.start_command import build_start_command
from .debug_run import DebugRuns
from .ports.flashing import FlashJob, FlashQueue, Origin
from .ports.handler import DEFAULT_LINE_ENDING, OutputLine
from .ports.manager import PortManager
from .ports.states import PortState
from .protocol import Cmd, ErrCode, Evt, event
from .server import Args, CommandError, SidecarServer
from .settings import BOX_COUNT, SidecarSettings
from .sketch_library import SketchLibrary
from .utility import UtilityBaseline
from .wire_errors import ERRORS

log = logging.getLogger(__name__)


class _LifecycleRig:
    """The session lifecycle's answers for the archive, which is built before
    the lifecycle is: no lifecycle yet means nothing holds the rig."""

    def __init__(self, app: Application) -> None:
        self._app = app

    @property
    def held(self) -> str | None:
        lifecycle = self._app.lifecycle
        return lifecycle.held if lifecycle is not None else None

    @property
    def in_use(self) -> bool:
        lifecycle = self._app.lifecycle
        return lifecycle is not None and lifecycle.in_use

    @property
    def writing(self) -> bool:
        lifecycle = self._app.lifecycle
        return lifecycle is not None and lifecycle.writing


class Application:
    def __init__(
        self, server: SidecarServer, data_dir: Path, *, tool: BoardTool | None = None
    ) -> None:
        self.server = server
        self.settings = SidecarSettings()
        #: This rig's task profiles, and the sketches generated from them.
        #: Built before the first scan, because `discover()` reads its root.
        self.task_store = taskdef_store.TaskStore(data_dir)
        #: Where the bundled sketches are rebuilt against this rig's wiring
        #: (`taskdef/bundled.py`). A separate root from the profiles: one holds
        #: what the operator authored, the other a build output the app can
        #: throw away and remake.
        self.pinned_root = data_dir / "rig" / "sketches"
        #: Every flashable sketch, as of the last scan (`sketch_library.py`).
        self.sketches = SketchLibrary(
            self.task_store.root,
            self.pinned_root,
            on_rescan=lambda: self.server.publish(Evt.SKETCHES_UPDATED),
        )
        # data_dir is where the bundled arduino data seed gets its writable
        # copy in a packaged install (`boards/cli_tool.py`). The factory picks
        # the gRPC daemon backend when grpcio is importable, the subprocess
        # backend otherwise (`boards/__init__.py`). Tests pass their own.
        self.tool = tool if tool is not None else create_board_tool(app_data_dir=data_dir)
        self.ports: PortManager | None = None
        #: Every flash: one compile at a time, restores side by side (`ports/flashing.py`).
        self.flashes: FlashQueue | None = None
        self.utility: UtilityBaseline | None = None
        #: Tasks started by hand from Debug Mode, scored live (`debug_run.py`).
        self.debug_runs = DebugRuns()

        self.db = Database(data_dir / DB_FILENAME)
        self.cohorts = CohortRepository(self.db)
        self.sessions = SessionRepository(self.db)
        self.runner: SessionRunner | None = None
        self.backup: BackupManager | None = None
        self.archive: CohortArchive | None = None
        self.analytics: AnalyticsService | None = None
        #: The session log (`DATA.md#the-session-log`). Off the session path:
        #: the runner never calls it, and its `notes.md` writes never block a reply.
        self.logbook: LogbookService | None = None
        #: The Intan RHX recording subsystem (`RECORDING.md`). Never on the
        #: session path except at `start_recording`.
        self.intan: IntanService | None = None
        self.profiles = AnalyticsRepository(self.db)
        #: The held session and its whole lifecycle (`sessions/lifecycle.py`).
        #: Built with the runner it sequences, in `start`.
        self.lifecycle: SessionLifecycle | None = None
        #: One preview at a time, for load alone: `hardware.preview` and
        #: `tasks.preview` fire on every keystroke and re-validate every stored
        #: task profile. Correctness needs no lock -- a hypothetical is
        #: context-local (`TASKS.md#the-rig-definition`).
        self._preview_gate = asyncio.Semaphore(1)
        #: The rig's own wiring, if it has one. Pointed at the registries by
        #: the rig definition rather than read by them, so `rig` never learns
        #: about data_dir.
        self.hardware_store = hardware_store.HardwareStore(data_dir)
        #: The machine's first start, as the database records it -- never the
        #: wiring record's own absence, which a lost record would fake
        #: (`HardwareStore.settle_record`). Marked once `start` connects.
        self._first_start = not has_mark(data_dir / DB_FILENAME, hardware_store.FIRST_START_MARK)
        #: This machine's strobe vocabulary — the one source of every code
        #: (`TASKS.md#strobe-vocabulary`). Seeded from the shipped default on
        #: first start, then pointed at the registry exactly as the wiring is.
        self.vocab_store = strobe_store.VocabularyStore(data_dir)
        try:
            self.vocab_store.ensure_seeded()
        except OSError as exc:
            log.error("could not seed the strobe vocabulary (%s); decoding with the default", exc)
        #: The rig wiring plus the vocabulary: installs both, and owns every
        #: write to either and the lock generated-folder readers take
        #: (`TASKS.md#the-rig-definition`).
        self.rig_definition = rig_definition.RigDefinition(
            hardware=self.hardware_store,
            vocabulary=self.vocab_store,
            tasks=self.task_store,
            repin=lambda: bundled_sketches.repin_all(self.pinned_root),
            in_use=lambda: self.lifecycle is not None and self.lifecycle.in_use,
            rescan=self.sketches.rescan,
            after_rebuild=self._after_rebuild,
            broadcast=lambda message: self.server.broadcast(message),
            first_start=self._first_start,
        )
        #: The Strobes page's edits and the evidence they're judged on.
        self.vocabulary = VocabularyEditor(
            rig=self.rig_definition,
            tasks=self.task_store,
            # Which recorded files contain which codes, for `strobes.remove`.
            scanner=ArchiveScanner(self.db),
            archive_roots=self._cohort_roots,
            broadcast=lambda message: self.server.broadcast(message),
        )
        #: hardware_id → detected interpreter baud. Detection costs a boot
        #: cycle per candidate rate, so the answer is kept for the app's
        #: lifetime — and invalidated on any flash to that box, since flashing
        #: is precisely what changes it.
        self._board_bauds: dict[str, int] = {}

    # --- lifecycle --------------------------------------------------------

    def register(self) -> None:
        """Every command's handler, the error table and the snapshots a
        client is sent on connect (`ARCHITECTURE.md#dispatch`)."""
        self.server.map_errors(ERRORS)
        self.server.register(Cmd.SETTINGS_PUSH, self._settings_push)
        self.server.register(Cmd.SKETCHES_REFRESH, self._sketches_refresh)
        self.server.register(Cmd.PORT_PASSTHROUGH_OPEN, self._passthrough_open)
        self.server.register(Cmd.PORT_PASSTHROUGH_CLOSE, self._passthrough_close)
        self.server.register(Cmd.PORT_SEND, self._port_send)
        self.server.register(Cmd.PORT_SEND_START, self._port_send_start)
        self.server.register(Cmd.FLASH_ENQUEUE, self._flash_enqueue)
        self.server.register(Cmd.FLASH_CANCEL, self._flash_cancel)
        self.server.register(Cmd.FLASH_STATUS, self._flash_status)
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
        self.server.register(Cmd.TASKS_EXPORT, self._tasks_export)
        self.server.register(Cmd.TASKS_IMPORT, self._tasks_import)
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
        self.server.register(Cmd.SESSIONS_FLASH, self._sessions_flash)
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
        self.server.register(Cmd.HARDWARE_EXPORT_CHANNEL_SET, self._hardware_export_channel_set)
        self.server.register(Cmd.HARDWARE_IMPORT_CHANNEL_SET, self._hardware_import_channel_set)

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

        missing = self.server.unhandled()
        if missing:
            raise RuntimeError(f"protocol/schema.py declares commands with no handler: {sorted(missing)}")

        # Replayed to a client on connect in this order, and broadcast by
        # `publish`. Port states first: everything after reads against them.
        self.server.register_snapshot(Evt.PORT_STATE, self._port_states)
        self.server.register_snapshot(Evt.PORT_TELEMETRY, self.debug_runs.snapshot)
        self.server.register_snapshot(Evt.BOARDS_PRESENCE, self._presence)
        self.server.register_snapshot(Evt.SKETCHES_UPDATED, lambda: self.sketches.current.to_json())
        self.server.register_snapshot(Evt.TASKS_UPDATED, self._tasks_payload)
        self.server.register_snapshot(Evt.COHORTS_UPDATED, self._cohorts_payload)
        self.server.register_snapshot(Evt.PREFIXES_UPDATED, self._prefixes_payload)
        self.server.register_snapshot(
            Evt.FLASH_QUEUE, lambda: self.flashes.status() if self.flashes else None
        )
        self.server.register_snapshot(
            Evt.UTILITY_UPDATED, lambda: self.utility.status() if self.utility else None
        )
        self.server.register_snapshot(
            Evt.BACKUP_STATUS, lambda: self.backup.status() if self.backup else None
        )
        self.server.register_snapshot(
            Evt.INTAN_STATUS, lambda: self.intan.status_json() if self.intan else None
        )

    def start(self) -> None:
        self.db.connect()
        if self._first_start:
            # After the wiring record was seeded: from here a lost record holds.
            self.db.set_mark(hardware_store.FIRST_START_MARK)
        # scipy is NOT imported here: `__main__._run` preloads it before the
        # parent-watch thread exists, and importing it any later than that
        # deadlocks the frozen build (`DATA.md#the-mat-mirror`).
        self._log_rig_wiring()
        # Every generated folder rebuilt before anything can flash one
        # (`RigDefinition.rebuild_at_startup` says why).
        pinned, regenerated = self.rig_definition.rebuild_at_startup()
        if pinned or regenerated:
            self.sketches.rescan_now()
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
        self.archive = CohortArchive(
            db=self.db,
            cohorts=self.cohorts,
            sessions=self.sessions,
            rig=_LifecycleRig(self),
            on_changed=self._archive_changed,
        )
        self.analytics = AnalyticsService(
            db=self.db,
            cohorts=self.cohorts,
            sessions=self.sessions,
            broadcast=self.server.broadcast,
            archive=self.archive,
            sketch_lookup=self.sketches.path_for_name,
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
            archive=self.archive,
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
        self.flashes = FlashQueue(
            loop=loop,
            ports=self.ports,
            discovery=lambda: self.sketches.current,
            broadcast=self.server.broadcast,
            reading=self.rig_definition.reading,
            on_flashed=self._on_flashed,
        )
        self.utility = UtilityBaseline(
            loop=loop,
            ports=self.ports,
            discovery=lambda: self.sketches.current,
            broadcast=self.server.broadcast,
            flashes=self.flashes,
            wiring_problem=self.rig_definition.wiring_problem,
        )
        self.runner = SessionRunner(
            loop=loop,
            ports=self.ports,
            broadcast=self.server.broadcast,
            on_animal_ended=lambda run, reason: self._require_lifecycle().animal_ended(run, reason),
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
        self.lifecycle = SessionLifecycle(
            db=self.db,
            sessions=self.sessions,
            cohorts=self.cohorts,
            runner=self.runner,
            intan=self.intan,
            utility=self.utility,
            profiles=self.profiles,
            logbook=self.logbook,
            rig_reading=self.rig_definition.reading,
            broadcast=self.server.broadcast,
            carried=self.ports.carried,
            flashes=self.flashes,
            wiring_problem=self.rig_definition.wiring_problem,
        )

    async def stop(self) -> None:
        # First, and it only closes OUR sockets: a recording in progress belongs
        # to RHX and outlives the sidecar (`RECORDING.md#when-rhx-goes-away`).
        if self.intan is not None:
            await self.intan.stop()
        # Before the ports go: a lit box has a console open that must be closed
        # through the state machine rather than yanked out from under it.
        # A flash in progress is abandoned with the process; nothing queued
        # behind it may start once the ports begin closing.
        if self.flashes is not None:
            await self.flashes.stop()
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

    async def _after_rebuild(self, tasks: int, pinned: int) -> None:
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

        problem = self.rig_definition.wiring_problem()
        if problem:
            # Never "the shipped pinout": the registry composes it meanwhile, but
            # the rig's own wiring is what failed to load or is held, and no box
            # may start until it is saved or reset
            # (`TASKS.md#the-channel-set-and-the-pin-map`).
            log.error("wiring: the stored rig wiring is not in force. %s", problem)
            return
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

    # --- snapshots (`server.register_snapshot`) ---------------------------

    def _port_states(self) -> list[dict[str, Any]] | None:
        """One payload per box. Its `prev` is its state: what a client that
        connects now missed is not a transition."""
        if self.ports is None:
            return None
        return [
            {"box": box, "state": state.value, "prev": state.value, "reason": "initial state"}
            for box, state in self.ports.current_states().items()
        ]

    def _presence(self) -> dict[str, Any] | None:
        return {"boards": self.ports.presence_json()} if self.ports is not None else None

    async def _tasks_payload(self) -> dict[str, Any]:
        return {"tasks": await asyncio.to_thread(self.task_store.list_entries)}

    async def _cohorts_payload(self) -> dict[str, Any]:
        cohorts = await asyncio.to_thread(self.cohorts.list_cohorts)
        return {"cohorts": [c.to_summary() for c in cohorts]}

    async def _prefixes_payload(self) -> dict[str, Any]:
        prefixes = await asyncio.to_thread(self.sessions.list_prefixes)
        return {"prefixes": [p.to_json() for p in prefixes]}

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
        # A board lost mid-run is the runner's to finalize, and it hears of it
        # from its own claim on the port (`ARCHITECTURE.md#board-drop`).
        # `ARCHITECTURE.md#when-a-restore-happens`: a box that has just become
        # nobody's is a box that should go back
        # to baseline. Driving this off the transition rather than off each
        # command means every way a port can fall idle — a run ending, a
        # console closing, an error acknowledged — is covered by one hook.
        if current == PortState.IDLE and self.utility is not None:
            self.utility.ensure([box])
        # A queued flash may have been waiting on exactly this port.
        if self.flashes is not None:
            self.flashes.port_changed(box)
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

    async def _settings_push(self, args: Args) -> dict[str, Any]:
        """Accept the shell's settings and answer with the library's state.

        The bundled library no longer depends on anything in the settings, but
        the reply still carries its status so a client learns it on connect
        without a second round trip — the same moment it used to learn the old
        directory validation.
        """
        self.settings = SidecarSettings.from_payload(args["settings"])
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
        # app, and a dev checkout restages between pushes. Not mid-rebuild.
        async with self.rig_definition.reading():
            await self.sketches.rescan()
        # After the rescan, so a newly-chosen utility sketch resolves against
        # the library as it is now rather than as it was one push ago.
        if self.intan is not None:
            self.intan.update_settings(self.settings)
        if self.utility is not None:
            self.utility.update_settings(self.settings)
            self.utility.ensure()
            await self.utility.publish()
        return {"library": self.sketches.current.library.to_json()}

    async def _sketches_refresh(self, _args: Args) -> dict[str, Any]:
        async with self.rig_definition.reading():
            await self.sketches.rescan()
            return self.sketches.current.to_json()

    async def _passthrough_open(self, args: Args) -> dict[str, Any]:
        state = self._require_ports().open_passthrough(_box_arg(args), args.get("baud"))
        return {"state": state.value}

    async def _passthrough_close(self, args: Args) -> dict[str, Any]:
        box = _box_arg(args)
        state = self._require_ports().close_passthrough(box)
        return {"state": state.value}

    async def _port_send(self, args: Args) -> dict[str, Any]:
        written = self._require_ports().send(
            _box_arg(args), args["text"], args.get("lineEnding", DEFAULT_LINE_ENDING)
        )
        return {"bytesWritten": written}

    async def _port_send_start(self, args: Args) -> dict[str, Any]:
        """Start a behaviour sketch by hand from the Debug console.

        The block is built here rather than in the client for the reason a
        session's is: `build_start_command` is the one place that knows the
        profile's wire keys and the firmware's line cap, and a `SET` line the
        board silently truncates is the failure this whole path exists to avoid.
        The board's `PARAMS` reply is held against what was sent, as a session's
        is, before the bare `START` goes out.
        """
        box = _box_arg(args)
        path = args["sketchPath"]
        # The profile is read from a generated folder a rig definition write
        # would rebuild (`TASKS.md#the-rig-definition`).
        async with self.rig_definition.reading():
            sketch = self.sketches.find(path)
            if sketch is None:
                raise CommandError(
                    ErrCode.SKETCH_UNKNOWN,
                    "That sketch isn't in the sketch library — refresh the list and "
                    "flash it again.",
                    {"sketchPath": path},
                )
            try:
                profile = await asyncio.to_thread(task_profile.load_profile, sketch.path)
            except task_profile.TaskProfileError:
                profile = None  # profile-less: bare START, as in a session
            # A `TaskProfileError` here is a parameter that cannot be sent as
            # written: a wrong-type value, or one over the firmware's cap.
            command = build_start_command(profile, args.get("config", {}))
            # Off the loop: each `SET` line waits for the board's `PARAMS`.
            written = await asyncio.to_thread(self._require_ports().send_start, box, command)
        # Armed only once the line is really on the wire, and only here: this is
        # the one moment the sidecar knows which profile the strobes that follow
        # should be scored against (`debug_run.py`).
        await self.server.broadcast(
            event(Evt.PORT_TELEMETRY, self.debug_runs.arm(box, profile))
        )
        return {"command": "START", "bytesWritten": written}

    # --- the flash queue (ARCHITECTURE.md#the-flash-queue) ---

    def _require_flashes(self) -> FlashQueue:
        if self.flashes is None:
            raise CommandError(ErrCode.INTERNAL, "hardware layer isn't running")
        return self.flashes

    def _on_flashed(self, box: int, sketch_path: str, origin: Origin) -> None:
        """Every flash that landed, from the queue, before anything yields.

        A session or Debug flash is news to the baseline: a Debug flash is one
        the operator asked for by hand, and it is pinned (`utility.py`). This
        port is about to fall IDLE, the idle hook is about to ask for a
        restore, and without the pin that restore overwrote the task within
        seconds of it landing. A restore reports its own outcome.
        """
        if origin != "baseline" and self.utility is not None:
            self.utility.note_flashed(box, sketch_path, pin=origin == "debug")
            asyncio.create_task(self.utility.publish())
        # Flashing is precisely what changes a board's interpreter baud, so the
        # cached detection result dies with the old firmware.
        hardware_id = self.settings.hardware_id_for(box)
        if hardware_id is not None:
            self._board_bauds.pop(hardware_id, None)

    async def _flash_enqueue(self, args: Args) -> dict[str, Any]:
        """Queue a Debug Mode flash of one sketch onto these boxes."""
        flashes = self._require_flashes()
        boxes = _boxes_arg(args)
        if not boxes:
            raise CommandError(ErrCode.BAD_MESSAGE, "`boxes` must name at least one box")
        path = args["sketchPath"]
        baud = args.get("baud")
        if (problem := self.rig_definition.wiring_problem()) is not None:
            # Every sketch here is built on the pins in force, the shipped ones
            # meanwhile (`ARCHITECTURE.md#unloaded-wiring-holds-it`).
            raise rig_definition.WiringNotLoaded(problem)
        # Only a discovered sketch is flashable (`TASKS.md#sketch-library`) —
        # enforced here, not just by the picker only listing discovered
        # sketches, and again when the job runs.
        if self.sketches.find(path) is None:
            raise CommandError(
                ErrCode.SKETCH_UNKNOWN,
                "That sketch isn't in the sketch library — "
                "refresh the list and pick again.",
                {"sketchPath": path},
            )
        # With a baud the box ends in a console, whichever state it started
        # in: someone who has just put a sketch on a board wants to talk to it,
        # and a flash from IDLE would otherwise land with nothing on screen.
        flashes.submit(
            FlashJob(box=box, origin="debug", prepare=lambda path=path: path, sketch_path=path, baud=baud)
            for box in boxes
        )
        # Before the reply: a client reading its store on the reply finds its
        # own jobs there, not the last flash's outcome.
        await flashes.publish()
        return flashes.status()

    async def _flash_cancel(self, args: Args) -> dict[str, Any]:
        flashes = self._require_flashes()
        flashes.cancel(origins=("session", "debug"), boxes=_boxes_arg(args))
        await flashes.publish()
        return flashes.status()

    async def _flash_status(self, _args: Args) -> dict[str, Any]:
        return self._require_flashes().status()

    async def _port_reset(self, args: Args) -> dict[str, Any]:
        box = _box_arg(args)
        state, resumed = await self._require_ports().reset(box)
        return {"state": state.value, "resumedPassthrough": resumed}

    async def _port_error_ack(self, args: Args) -> dict[str, Any]:
        box = _box_arg(args)
        state = self._require_ports().acknowledge_error(box)
        return {"state": state.value}

    # --- utility baseline (ARCHITECTURE.md#hardware-utility-baseline) ---

    def _require_utility(self) -> UtilityBaseline:
        if self.utility is None:
            raise CommandError(ErrCode.INTERNAL, "hardware layer isn't running")
        return self.utility

    async def _utility_ensure(self, args: Args) -> dict[str, Any]:
        """Schedule a baseline restore and return the picture as it stands.

        Deliberately doesn't await the flashing: six boxes take minutes, and
        the client watches `utility.updated` instead of holding a reply open.
        """
        utility = self._require_utility()
        targets = args.get("boxes")
        # Arriving over the wire means a person asked: that is what releases a
        # Debug Mode pin. The automatic triggers call `ensure` directly.
        utility.unpin(targets)
        utility.ensure(targets, force=args.get("force") is True)
        return utility.status()

    async def _utility_identify(self, args: Args) -> dict[str, Any]:
        delivered, state = await self._require_utility().identify(_box_arg(args), args["on"])
        return {"delivered": delivered, "state": state}

    # --- cohorts (DATA.md#cohorts-animals-and-groups) --------------------

    async def _cohorts_list(self, _args: Args) -> dict[str, Any]:
        return await self._cohorts_payload()

    async def _cohorts_get(self, args: Args) -> dict[str, Any]:
        cohort_id = _str_arg(args, "id")
        cohort = await asyncio.to_thread(self.cohorts.get, cohort_id)
        return {"cohort": cohort.to_json()}

    async def _cohorts_create(self, args: Args) -> dict[str, Any]:
        name = str(args.get("name") or "").strip()
        override = args.get("dataFolder")

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

    async def _cohorts_update(self, args: Args) -> dict[str, Any]:
        cohort_id = _str_arg(args, "id")
        cohort = await asyncio.to_thread(self.cohorts.update, cohort_id, args["patch"])
        await self._broadcast_cohorts()
        return {"cohort": cohort.to_json()}

    async def _cohorts_archive(self, args: Args) -> dict[str, Any]:
        cohort_id = _str_arg(args, "id")
        cohort = await asyncio.to_thread(self.cohorts.archive, cohort_id)
        await self._broadcast_cohorts()
        return {"cohort": cohort.to_json()}

    async def _cohorts_restore(self, args: Args) -> dict[str, Any]:
        cohort_id = _str_arg(args, "id")
        cohort = await asyncio.to_thread(self.cohorts.restore, cohort_id)
        await self._broadcast_cohorts()
        return {"cohort": cohort.to_json()}

    async def _cohorts_delete(self, args: Args) -> dict[str, Any]:
        """Permanent delete (`DATA.md#archive-and-delete`). Removes bookkeeping
        only, never data files."""
        cohort_id = _str_arg(args, "id")
        if args.get("confirm") is not True:
            raise CommandError(
                ErrCode.BAD_MESSAGE, "Permanent delete requires `confirm: true`."
            )
        await asyncio.to_thread(self.cohorts.delete, cohort_id)
        log.info("cohort deleted: %s (data folder left on disk)", cohort_id)
        await self._broadcast_cohorts()
        return {"deleted": True}

    async def _cohorts_set_data_folder(self, args: Args) -> dict[str, Any]:
        """The explicit relocate (`DATA.md#data-folder`). Moving the contents
        moves the records' paths with them, so it waits for an idle rig: a
        session writing into the folder would be writing into one that moves."""
        cohort_id = _str_arg(args, "id")
        path = _str_arg(args, "path")
        move_existing = args.get("moveExisting") is True
        await self._require_archive().relocate(cohort_id, path, move_existing)
        cohort = await asyncio.to_thread(self.cohorts.get, cohort_id)
        return {"cohort": cohort.to_json()}

    async def _cohorts_move_animals(self, args: Args) -> dict[str, Any]:
        """Move animals, their files and their history to another cohort
        (`DATA.md#moving-animals-between-cohorts`). `apply` false is a preview.

        Refused while the rig is in use anywhere, not just in these cohorts:
        copying an archive competes with the write-ahead log's per-strobe
        fsync, and one session runs at a time app-wide.
        """
        request = MoveRequest(
            source_id=_str_arg(args, "cohortId"),
            animal_ids=args["animalIds"],
            dest_id=_str_arg(args, "destinationCohortId"),
            dest_group_id=args.get("destinationGroupId"),
        )
        return await self._require_archive().move_animals(
            request, apply=args.get("apply") is True
        )

    async def _cohorts_suggest_groups(self, args: Args) -> dict[str, Any]:
        """Auto-Balance preview (`DATA.md#auto-balance`). Computes only — the
        client applies via `cohorts.update`."""
        cohort_id = _str_arg(args, "id")
        cohort = await asyncio.to_thread(self.cohorts.get, cohort_id)

        proposal = grouping.suggest_groups(
            cohort.animals,
            group_count=args.get("groupCount"),
            max_group_size=args.get("maxGroupSize"),
            balance_by_sex=args.get("balanceBySex") is True,
        )
        return proposal.to_json()

    async def _broadcast_cohorts(self) -> None:
        await self.server.publish(Evt.COHORTS_UPDATED)

    async def _archive_changed(self, change: ArchiveChange) -> None:
        """Everyone who hears an archive write (`DATA.md#the-cohort-archive`),
        once it is done: the backup mirror, the cohort list, the Dashboard's
        dock and the session log of each cohort it touched."""
        if self.backup is not None and change.files_to_back_up:
            self.backup.enqueue(*change.files_to_back_up)
        if change.cohort_ids:
            await self._broadcast_cohorts()
            # Stale and set-up rows may have gone from the dock.
            if self.lifecycle is not None:
                await self.lifecycle.announce()
        if self.logbook is not None:
            for cohort_id in sorted(change.cohort_ids):
                await self.logbook.refresh(cohort_id)
            # A move's source session whose every note moved away has none left
            # to be found by, but still a stale notes.md.
            for session_id in sorted(change.session_ids):
                self.logbook.schedule_mirror(session_id)

    # --- prefixes (DATA.md#prefixes) ----------------------------------

    async def _prefixes_list(self, _args: Args) -> dict[str, Any]:
        return await self._prefixes_payload()

    async def _prefixes_create(self, args: Args) -> dict[str, Any]:
        prefix = await asyncio.to_thread(self.sessions.create_prefix, args["name"].strip())
        await self.server.publish(Evt.PREFIXES_UPDATED)
        return {"prefix": prefix.to_json()}

    async def _prefixes_delete(self, args: Args) -> dict[str, Any]:
        prefix_id = _str_arg(args, "id")
        await asyncio.to_thread(self.sessions.delete_prefix, prefix_id)
        await self.server.publish(Evt.PREFIXES_UPDATED)
        return {"deleted": True}

    # --- task profiles (TASKS.md#task-profile) -----------------------

    async def _tasks_get_profile(self, args: Args) -> dict[str, Any]:
        sketch_path = _str_arg(args, "sketchPath")
        async with self.rig_definition.reading():
            # A malformed task.json is surfaced (`TaskProfileError`) so it can
            # be fixed; the sketch is otherwise treated as profile-less (bare
            # START, raw strobe log).
            profile = await asyncio.to_thread(task_profile.load_profile, sketch_path)
            return profile.to_json() if profile is not None else {"profile": None}

    # -- task profiles ------------------------------------------------------ #
    #
    # OFF-LOOP, because saving one writes four files and validating one composes
    # the whole channel map, and the event loop owns six serial ports and a
    # 20 Hz output flush. Saving and deleting rewrite a sketch folder, so they
    # are rig definition writes (`TASKS.md#the-rig-definition`); listing and
    # validating read only the registries and need no lock.

    async def _tasks_list(self, _args: Args) -> dict[str, Any]:
        return {"tasks": await asyncio.to_thread(self.task_store.list_entries)}

    async def _tasks_get(self, args: Args) -> dict[str, Any]:
        task_id = _str_arg(args, "taskId")
        definition = await asyncio.to_thread(self.task_store.get, task_id)
        if definition is None:
            raise CommandError(
                ErrCode.TASK_NOT_FOUND,
                f"No task profile called {task_id!r} on this rig.",
                {"taskId": task_id},
            )
        diagnostics = await asyncio.to_thread(validate_task, definition)
        return {
            "definition": definition.to_json(),
            "diagnostics": [d.to_json() for d in diagnostics],
        }

    async def _tasks_preview(self, args: Args) -> dict[str, Any]:
        definition = self._definition_arg(args)
        async with self._preview_gate:
            return await asyncio.to_thread(self._preview_payload, definition)

    def _preview_payload(self, definition: TaskDefinition) -> dict[str, Any]:
        """Compile without writing."""
        from .taskdef import generate

        diagnostics = validate_task(definition)
        profile = generate.build_profile(definition)
        # The same profile compiled with the overrides stripped. Two compiles
        # rather than one because "what does this profile PIN" is not derivable
        # from the merged result: a value equal to the catalogue's is
        # indistinguishable from one that was never set, and storing it would
        # freeze the field against a later correction.
        from dataclasses import replace as _replace

        bare = generate.build_profile(_replace(definition, params={}))
        return {
            "diagnostics": [d.to_json() for d in diagnostics],
            "profile": profile.to_json(),
            "catalogueDefaults": {f.metadata_key: f.default for f in bare.config},
        }

    async def _tasks_save(self, args: Args) -> dict[str, Any]:
        definition = self._definition_arg(args)
        async with self.rig_definition.writing(rig_definition.TASKS_IN_USE):
            # Checked inside the write, so two saves racing on one name cannot
            # both pass.
            #
            # A generated sketch and a bundled one sharing a name makes the
            # picker ambiguous and the flash a coin flip, so this is refused
            # rather than reported: it is the one problem saving cannot leave
            # for later.
            collision = self.sketches.bundled_named(definition.name)
            if collision is not None:
                raise CommandError(
                    ErrCode.TASK_INVALID,
                    f"A sketch that ships with Ephymeris is already called "
                    f"{definition.name!r}. Give this task another name.",
                    {"sketchPath": collision.path},
                )
            # Two saved tasks sharing a name share a sketch folder: saving one
            # overwrites the other's firmware and deleting either removes both.
            # Duplicating a task makes this the easy mistake, so it is refused
            # too. Case-folded because the lab machines' filesystem is
            # case-insensitive.
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

            diagnostics = await asyncio.to_thread(self.task_store.save, definition)
            # The folder is a sketch from this moment, so the library must be
            # rescanned before anyone can flash it. The rescan publishes
            # `sketches.updated`; the task list rides alongside it.
            await self.sketches.rescan()
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

    async def _tasks_delete(self, args: Args) -> dict[str, Any]:
        task_id = _str_arg(args, "taskId")
        async with self.rig_definition.writing(rig_definition.TASKS_IN_USE):
            deleted = await asyncio.to_thread(self.task_store.delete, task_id)
            if deleted:
                await self.sketches.rescan()
                await self._broadcast_tasks()
        return {"deleted": deleted}

    # -- moving a task between machines (TASKS.md#moving-a-task-between-machines)
    #
    # The rules are `taskdef/transfer.py`'s and pure; what is here is the
    # order of the one write. Both refuse while the stored wiring is not in
    # force: the channel set and the vocabulary a task would be judged against
    # are then the shipped ones, not this rig's.

    async def _tasks_export(self, args: Args) -> dict[str, Any]:
        task_id = _str_arg(args, "taskId")

        def export() -> dict[str, Any]:
            problem = self.rig_definition.wiring_problem()
            if problem:
                raise rig_definition.WiringNotLoaded(problem)
            document = self.task_store.document(task_id)
            if not isinstance(document, dict):
                raise CommandError(
                    ErrCode.TASK_NOT_FOUND,
                    f"No readable task profile called {task_id!r} on this rig.",
                    {"taskId": task_id},
                )
            return task_transfer.export_document(
                document, rig_registry.channels(), rig_registry.vocabulary()
            )

        exported = await asyncio.to_thread(export)
        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        return {"document": exported, "filename": f"task-{task_id}-{stamp}.json"}

    async def _tasks_import(self, args: Args) -> dict[str, Any]:
        document = args["document"]
        if not args["apply"]:
            plan = await asyncio.to_thread(self._plan_task_import, document)
            return {"plan": plan.to_json(), "applied": False}
        async with self.rig_definition.writing(rig_definition.TASKS_IN_USE):
            # Planned again inside the write: a task saved, or a wiring
            # changed, since the dialog's plan is judged here.
            plan = await asyncio.to_thread(self._plan_task_import, document)
            if plan.conflicts:
                raise task_transfer.TaskImportConflict(plan.conflicts)
            if plan.identical:
                return {"plan": plan.to_json(), "applied": False}
            if plan.replaces and not args.get("confirm"):
                raise task_transfer.TaskImportReplaces(
                    f"A task called {plan.name!r} with this id is saved here already. "
                    "Importing replaces it; confirm to go ahead."
                )
            # Verbatim: fields this build does not know are kept.
            await asyncio.to_thread(self.task_store.save_document, plan.definition)
            await self.sketches.rescan()
            await self._broadcast_tasks()
        return {"plan": plan.to_json(), "applied": True}

    def _plan_task_import(self, document: Any) -> task_transfer.ImportPlan:
        problem = self.rig_definition.wiring_problem()
        if problem:
            raise rig_definition.WiringNotLoaded(problem)
        return task_transfer.plan_import(
            document,
            channels=rig_registry.channels(),
            vocabulary=rig_registry.vocabulary(),
            tasks=self.task_store,
            bundled_named=self.sketches.bundled_named,
        )

    def _definition_arg(self, args: Args) -> TaskDefinition:
        """`TASK_INVALID` is for a document that is not a definition.

        A well-formed definition describing an impossible task — a channel this
        rig lacks, a reward line serving the wrong well — is NOT this. It is a
        successful reply carrying located diagnostics, exactly as a wiring
        document is.
        """
        raw = args["definition"]
        if not isinstance(raw, dict):
            raise CommandError(ErrCode.TASK_INVALID, "`definition` must be an object.")
        if len(json.dumps(raw).encode()) > taskdef_store.MAX_DEFINITION_BYTES:
            raise CommandError(
                ErrCode.TASK_INVALID,
                f"The definition is over "
                f"{taskdef_store.MAX_DEFINITION_BYTES // 1024} KB — that is not a task.",
            )
        # A `TaskDefinitionError` for anything else that makes it not one.
        return TaskDefinition.from_json(raw)

    async def _broadcast_tasks(self) -> None:
        await self.server.publish(Evt.TASKS_UPDATED)

    # -- strobe vocabulary (TASKS.md#strobe-vocabulary) ------------------- #
    #
    # Every edit is a rig definition write (`TASKS.md#the-rig-definition`): it
    # rebuilds the same generated folders a wiring change does.

    async def _strobes_get(self, _args: Args) -> dict[str, Any]:
        return await self.vocabulary.vocabulary()

    async def _strobes_usage(self, args: Args) -> dict[str, Any]:
        return await self.vocabulary.usage(args["name"], scan=args.get("scan") is True)

    async def _strobes_add(self, args: Args) -> dict[str, Any]:
        return await self.vocabulary.add(
            args["name"], args["code"],
            rationale=args["rationale"], emitted_on=args.get("emittedOn", ""),
        )

    async def _strobes_edit(self, args: Args) -> dict[str, Any]:
        return await self.vocabulary.edit(
            args["name"], rationale=args["rationale"], emitted_on=args.get("emittedOn", "")
        )

    async def _strobes_retire(self, args: Args) -> dict[str, Any]:
        return await self.vocabulary.retire(args["name"], confirm=args["confirm"])

    async def _strobes_reinstate(self, args: Args) -> dict[str, Any]:
        return await self.vocabulary.reinstate(args["name"])

    async def _strobes_remove(self, args: Args) -> dict[str, Any]:
        return await self.vocabulary.remove(args["name"], confirm=args["confirm"])

    async def _strobes_export(self, _args: Args) -> dict[str, Any]:
        return await self.vocabulary.export()

    async def _strobes_import(self, args: Args) -> dict[str, Any]:
        return await self.vocabulary.import_(args["document"], apply=args["apply"])

    # -- rig wiring -------------------------------------------------------- #
    #
    # OFF-LOOP, all four: preview and save re-validate every stored task profile
    # against the proposed wiring, and the event loop also owns six serial ports
    # and a 20 Hz output flush. Save and reset are rig definition writes
    # (`TASKS.md#the-rig-definition`).

    async def _hardware_get(self, _args: Args) -> dict[str, Any]:
        return await asyncio.to_thread(
            hardware_service.document_payload,
            self.hardware_store,
            in_force=self.rig_definition.in_force(),
        )

    async def _hardware_preview(self, args: Args) -> dict[str, Any]:
        document = self._rig_document_arg(args)

        def preview() -> dict[str, Any]:
            breaks = rig_definition.impact_of(self.task_store, wiring=document)
            return hardware_service.preview_payload(
                self.hardware_store,
                document,
                breaks,
                in_force=self.rig_definition.in_force(),
                confirmed_pins=bool(args.get("confirmedPins")),
            )

        async with self._preview_gate:
            return await asyncio.to_thread(preview)

    async def _hardware_save(self, args: Args) -> dict[str, Any]:
        document = self._rig_document_arg(args)
        # EVERY GENERATED SKETCH IS STALE once this lands -- the rebuild inside
        # the write is what makes "a pin change applies to everything" true
        # rather than a claim.
        return await self.rig_definition.save_wiring(
            document, confirm=args["confirm"], confirmed_pins=bool(args.get("confirmedPins"))
        )

    async def _hardware_reset(self, _args: Args) -> dict[str, Any]:
        # A wiring change like any other -- see `_hardware_save`.
        return await self.rig_definition.reset_wiring()

    async def _hardware_export_channel_set(self, _args: Args) -> dict[str, Any]:
        return await asyncio.to_thread(self.rig_definition.export_channel_set)

    async def _hardware_import_channel_set(self, args: Args) -> dict[str, Any]:
        # A rig definition write when applied (`TASKS.md#moving-the-channel-set-between-machines`).
        return await self.rig_definition.import_channel_set(
            args["document"], apply=args["apply"], confirm=bool(args.get("confirm"))
        )

    def _rig_document_arg(self, args: Args) -> dict[str, Any]:
        """`RIG_INVALID` is for a document that is not a document.

        A well-formed document describing an impossible box is NOT this -- it
        is a successful reply carrying located problems.
        """
        document = args["document"]
        if not isinstance(document, dict):
            raise CommandError(ErrCode.RIG_INVALID, "`document` must be an object.")
        if len(json.dumps(document).encode()) > hardware_store.MAX_RIG_BYTES:
            raise CommandError(
                ErrCode.RIG_INVALID,
                f"The document is over {hardware_store.MAX_RIG_BYTES // 1024} KB — "
                "that is not a pin map.",
            )
        return document

    # --- backup (DATA.md#backup-mirroring) --------------------------

    async def _backup_sync_now(self, _args: Args) -> dict[str, Any]:
        """Copy anything the mirror is missing, on demand.

        Setting a backup directory doesn't backfill by itself — that could mean
        an unannounced multi-gigabyte copy the moment someone picks a folder on
        a network share. This is the deliberate version, and it's also how a
        user proves the target works before trusting it.
        """
        if self.backup is None:
            raise CommandError(ErrCode.INTERNAL, "backup manager isn't running")
        return await self.backup.sync_now()

    # --- analytics (PROTOCOL.md#analytics) ---------------------------------

    def _require_archive(self) -> CohortArchive:
        if self.archive is None:
            raise CommandError(ErrCode.INTERNAL, "analytics isn't running")
        return self.archive

    def _require_analytics(self) -> AnalyticsService:
        if self.analytics is None:
            raise CommandError(ErrCode.INTERNAL, "analytics isn't running")
        return self.analytics

    async def _sessions_list(self, args: Args) -> dict[str, Any]:
        """A cohort's sessions, chronologically. **Never touches the filesystem.**

        Deliberately cheap so the dashboard's selectors populate instantly
        while `analytics.summary` is still reading files.
        """
        cohort_id = _str_arg(args, "cohortId")
        include_aborted = args.get("includeAborted") is True
        # Recovered sessions (DATA.md#orphan-adoption) are listed beside the
        # recorded ones so the Analytics selectors cover the whole archive; the
        # archive reads the database only, so the no-filesystem rule holds.
        view = await asyncio.to_thread(
            self._require_archive().view, cohort_id, include_aborted=include_aborted
        )
        counts = view.run_counts()
        return {
            "sessions": [
                session.to_list_item(index + 1, run_count=counts.get(session.id, 0))
                for index, session in enumerate(view.sessions)
            ]
        }

    async def _analytics_summary(self, args: Args) -> dict[str, Any]:
        cohort_id = _str_arg(args, "cohortId")
        return await self._require_analytics().summary(
            cohort_id,
            session_ids=args.get("sessionIds"),
            animal_ids=args.get("animalIds"),
            min_counted=args.get("minCountedTrials"),
        )

    async def _analytics_set_false_start(self, args: Args) -> dict[str, Any]:
        """A person's ruling on one run (`ANALYTICS.md#false-starts`)."""
        cohort_id = _str_arg(args, "cohortId")
        run_id = _str_arg(args, "runId")
        value = args["falseStart"]
        analytics = self._require_analytics()
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

    async def _analytics_series(self, args: Args) -> dict[str, Any]:
        run_ids = args["runIds"]
        if not run_ids:
            raise CommandError(ErrCode.BAD_MESSAGE, "`runIds` must be a non-empty list")
        try:
            return await self._require_analytics().series(
                run_ids, mode=args.get("mode", "rolling"), metric_ids=args.get("metricIds")
            )
        except ValueError as exc:
            raise CommandError(ErrCode.BAD_MESSAGE, str(exc)) from exc

    async def _analytics_rescan(self, args: Args) -> dict[str, Any]:
        """The explicit archive walk (`DATA.md#database-first`) — never a side
        effect of opening a view."""
        cohort_id = _str_arg(args, "cohortId")
        return await self._require_analytics().rescan(
            cohort_id, adopt_orphans=args.get("adoptOrphans") is not False
        )

    async def _sessions_tidy(self, args: Args) -> dict[str, Any]:
        """Merge a day's split session records and drop empty ones
        (`DATA.md#tidy-records`).

        `apply` false (the default) is a preview. The held session is never
        touched, whatever the plan says; everything else the planner decides.
        """
        cohort_id = _str_arg(args, "cohortId")
        return await self._require_analytics().tidy(
            cohort_id,
            apply=args.get("apply") is True,
            today=datetime.now().date().isoformat(),
        )

    async def _analytics_recent_sessions(self, args: Args) -> dict[str, Any]:
        """Folder-name recency across every active cohort — cheap on purpose,
        so the Dashboard can ask without the rescan's cost or its ceremony."""
        return await self._require_analytics().recent_sessions(args.get("limit"))

    async def _sessions_recover(self, args: Args) -> dict[str, Any]:
        """The crash-recovery backfill (`DATA.md#crash-recovery`), through the
        archive (`CohortArchive.recover`)."""
        return await self._require_archive().recover(_str_arg(args, "cohortId"))

    # --- sessions (PROTOCOL.md#prefixes-and-sessions) ---------------------

    def _require_lifecycle(self) -> SessionLifecycle:
        if self.lifecycle is None:
            raise CommandError(ErrCode.INTERNAL, "session runner isn't running")
        return self.lifecycle

    async def _sessions_suggest_number(self, args: Args) -> dict[str, Any]:
        prefix_id = _str_arg(args, "prefixId")
        suggestion = await asyncio.to_thread(
            self.sessions.suggest_session_number, prefix_id
        )
        same_day = await asyncio.to_thread(
            self.sessions.session_numbers_on, prefix_id, datetime.now().date().isoformat()
        )
        return {"suggestion": suggestion, "sameDayNumbers": same_day}

    async def _sessions_create(self, args: Args) -> dict[str, Any]:
        cohort_id = _str_arg(args, "cohortId")
        prefix_id = _str_arg(args, "prefixId")
        session_number = args["sessionNumber"].strip()
        if not session_number:
            raise CommandError(ErrCode.SESSION_INVALID, "A session number is required.")
        duration = args.get("durationMinutes")
        if duration is not None and duration <= 0:
            raise CommandError(
                ErrCode.SESSION_INVALID,
                "durationMinutes must be a positive whole number of minutes.",
            )

        cohort = await asyncio.to_thread(self.cohorts.get, cohort_id)

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

        # The folder would be made at the old place while the records move to
        # the new one (`DATA.md#data-folder`).
        if await asyncio.to_thread(relocate.moving, self.db, cohort_id):
            raise CommandError(
                ErrCode.SESSION_INVALID,
                "This cohort's data folder is being moved. Set up the session once it finishes.",
            )

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
        await self._require_lifecycle().announce()
        return {"session": session.to_json()}

    async def _sessions_abandon(self, args: Args) -> dict[str, Any]:
        session_id = _str_arg(args, "sessionId")
        session = await self._require_lifecycle().abandon(session_id)
        return {"session": session.to_json()}

    async def _sessions_confirm_mapping(self, args: Args) -> dict[str, Any]:
        session_id = _str_arg(args, "sessionId")
        group_id = _str_arg(args, "groupId")
        entries = [
            MappingEntry(
                box=entry["box"],
                animal_id=entry["animalId"],
                sketch_path=entry["sketchPath"],
                config=entry["config"],
            )
            for entry in args["boxes"]
        ]
        await self._require_lifecycle().confirm_mapping(session_id, group_id, entries)
        return {"ok": True}

    async def _sessions_status(self, args: Args) -> dict[str, Any]:
        session_id = _str_arg(args, "sessionId")
        return await self._require_lifecycle().status(session_id)

    async def _sessions_active(self, _args: Args) -> dict[str, Any]:
        return await self._require_lifecycle().active()

    async def _sessions_flash(self, args: Args) -> dict[str, Any]:
        session_id = _str_arg(args, "sessionId")
        boxes = _boxes_arg(args)
        if not boxes:
            raise CommandError(ErrCode.BAD_MESSAGE, "`boxes` must name at least one box")
        await self._require_lifecycle().flash(session_id, boxes)
        flashes = self._require_flashes()
        await flashes.publish()
        return flashes.status()

    async def _sessions_start_all(self, args: Args) -> dict[str, Any]:
        session_id = _str_arg(args, "sessionId")
        session = await self._require_lifecycle().start_all(session_id)
        return {"session": session.to_json()}

    async def _sessions_end_group(self, args: Args) -> dict[str, Any]:
        """End the group and wait between groups (`ARCHITECTURE.md#group-step`)."""
        session_id = _str_arg(args, "sessionId")
        session = await self._require_lifecycle().end_group(session_id)
        return {"session": session.to_json()}

    async def _sessions_resume(self, args: Args) -> dict[str, Any]:
        """Continue one of today's sessions with another group
        (`DATA.md#continuing-between-groups`)."""
        session_id = _str_arg(args, "sessionId")
        session = await self._require_lifecycle().resume(session_id)
        return {"session": session.to_json()}

    async def _sessions_end(self, args: Args) -> dict[str, Any]:
        session_id = _str_arg(args, "sessionId")
        session = await self._require_lifecycle().end(session_id)
        return {"session": session.to_json()}

    async def _port_start_session(self, args: Args) -> dict[str, Any]:
        box = _box_arg(args)
        await self._require_lifecycle().start_box(box)
        return {"state": self._require_ports().handler(box).state.value}

    async def _port_stop_session(self, args: Args) -> dict[str, Any]:
        box = _box_arg(args)
        self._require_lifecycle().stop_box(box)
        return {"state": self._require_ports().handler(box).state.value}

    # --- the session log (DATA.md#the-session-log) ---------------------------

    def _require_logbook(self) -> LogbookService:
        if self.logbook is None:
            raise CommandError(ErrCode.INTERNAL, "the session log isn't running")
        return self.logbook

    async def _logbook_cohort(self, args: Args) -> dict[str, Any]:
        cohort_id = _str_arg(args, "cohortId")
        return await self._require_logbook().cohort(cohort_id)

    async def _logbook_open_flags(self, args: Args) -> dict[str, Any]:
        cohort_id = _str_arg(args, "cohortId")
        return await self._require_logbook().open_flags(cohort_id)

    async def _logbook_add_note(self, args: Args) -> dict[str, Any]:
        session_id = _str_arg(args, "sessionId")
        return await self._require_logbook().add_note(session_id, args)

    async def _logbook_edit_note(self, args: Args) -> dict[str, Any]:
        note_id = _str_arg(args, "noteId")
        fields = {k: v for k, v in args.items() if k != "noteId"}
        return await self._require_logbook().edit_note(note_id, fields)

    async def _logbook_delete_note(self, args: Args) -> dict[str, Any]:
        note_id = _str_arg(args, "noteId")
        return await self._require_logbook().delete_note(note_id)

    async def _logbook_resolve_flag(self, args: Args) -> dict[str, Any]:
        note_id = _str_arg(args, "noteId")
        return await self._require_logbook().resolve_flag(
            note_id, args["resolved"], args.get("sessionId") or None
        )

    async def _logbook_set_session_log(self, args: Args) -> dict[str, Any]:
        session_id = _str_arg(args, "sessionId")
        fields = {k: args[k] for k in ("operator", "summary") if k in args}
        return await self._require_logbook().set_session_log(session_id, fields)

    # --- Intan recording (RECORDING.md) -----------------------------------

    def _require_intan(self) -> IntanService:
        if self.intan is None:
            raise CommandError(ErrCode.INTERNAL, "the recording layer isn't running")
        return self.intan

    async def _intan_status(self, _args: Args) -> dict[str, Any]:
        return self._require_intan().status_json()

    async def _intan_connect(self, _args: Args) -> dict[str, Any]:
        intan = self._require_intan()
        await intan.connect()
        return intan.status_json()

    async def _intan_disconnect(self, _args: Args) -> dict[str, Any]:
        intan = self._require_intan()
        await intan.disconnect()
        return intan.status_json()

    async def _intan_configure(self, args: Args) -> dict[str, Any]:
        intan = self._require_intan()
        session_id = _str_arg(args, "sessionId")
        group_id = _str_arg(args, "groupId")
        config = args["config"]
        session = await asyncio.to_thread(self.sessions.get_session, session_id)
        cohort = await asyncio.to_thread(self.cohorts.get, session.cohort_id)
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
        rows = config.get("boxes") or []
        # A box the held mapping lacks would reach RHX with no animal
        # (`RECORDING.md#record-step`).
        lifecycle = self._require_lifecycle()
        mapped = lifecycle.mapped_boxes(session_id, group_id, (b["box"] for b in rows))
        # Read with the mapping, before RHX is awaited: a confirmation landing
        # during the setup leaves it for the earlier one, which Start refuses.
        confirmation = lifecycle.confirmations
        mapping = ", ".join(
            f"box {b['box']}={mapped[b['box']].animal_name} port {b.get('port')}" for b in rows
        )
        notes = (
            f"Ephymeris {session.prefix_name} {session.session_number} {session.date}",
            f"cohort {cohort.name} group {group_name}",
            mapping,
        )
        await intan.configure(session_id, group_id, config, base, notes, confirmation=confirmation)
        return intan.status_json()

    async def _intan_parse_probe_map(self, args: Args) -> dict[str, Any]:
        path = _str_arg(args, "path")
        return {"probeMap": await asyncio.to_thread(intan_probemap.parse_file, path)}

    async def _intan_probe_map(self, args: Args) -> dict[str, Any]:
        return {"probeMap": self._require_intan().probe_map_for(_box_arg(args))}

    async def _intan_set_threshold(self, args: Args) -> dict[str, Any]:
        channel = _str_arg(args, "channel")
        value = await self._require_intan().set_threshold(channel, args["microvolts"])
        return {"channel": channel.upper(), "microvolts": value}

    async def _intan_scope_open(self, args: Args) -> dict[str, Any]:
        scope_id = await self._require_intan().open_scope(
            args["kind"], _box_arg(args), args.get("channel"), args.get("params", {})
        )
        return {"scopeId": scope_id}

    async def _intan_scope_update(self, args: Args) -> dict[str, Any]:
        ok = await self._require_intan().update_scope(
            _str_arg(args, "scopeId"), args.get("channel"), args.get("params")
        )
        return {"ok": ok}

    async def _intan_scope_close(self, args: Args) -> dict[str, Any]:
        await self._require_intan().close_scope(_str_arg(args, "scopeId"))
        return {"ok": True}

    async def _intan_force_stop(self, _args: Args) -> dict[str, Any]:
        self._require_intan().force_stop.set()
        return {"ok": True}


def _is_ready_to_run(cohort: Any) -> bool:
    """`ARCHITECTURE.md#configuration` — ready if any group holds a
    box-assigned animal."""
    return any(a.box_number is not None for a in cohort.animals)


def _filename_token(text: str) -> str:
    """One piece of an RHX base filename: no spaces (the name is a single
    token of a `set` command) and nothing a filesystem objects to."""
    cleaned = "".join(c if c.isalnum() or c in "-." else "-" for c in str(text).strip())
    return cleaned.strip("-") or "x"


def _str_arg(args: Args, key: str) -> str:
    """A string the schema has checked, which must not also be blank."""
    value = args[key]
    if not value.strip():
        raise CommandError(ErrCode.BAD_MESSAGE, f"`{key}` must be a non-empty string")
    return value


def _box_arg(args: Args) -> int:
    """`box`, which the schema has made an int, as a box number."""
    box = args["box"]
    if not 1 <= box <= BOX_COUNT:
        raise CommandError(ErrCode.BAD_MESSAGE, f"`box` must be a box number 1–{BOX_COUNT}")
    return box


def _boxes_arg(args: Args) -> list[int] | None:
    """An optional `boxes` list, in the order sent, without repeats."""
    boxes = args.get("boxes")
    if boxes is None:
        return None
    if any(not 1 <= b <= BOX_COUNT for b in boxes):
        raise CommandError(ErrCode.BAD_MESSAGE, f"`boxes` must be a list of box numbers 1–{BOX_COUNT}")
    return list(dict.fromkeys(boxes))

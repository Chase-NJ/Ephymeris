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

from . import __version__, discovery
from .analytics import AnalyticsBusy, AnalyticsService
from .analytics.repository import AnalyticsRepository
from .backup import BackupManager, BackupNotConfigured
from .boards import create_board_tool
from .boards.tool import FlashFailed
from .cohorts import folders, grouping
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
from .specs import compiler as spec_compiler
from .specs import service as spec_service
from .specs import store as spec_store
from .sessions.repository import SessionRepository
from .sessions.runner import ActiveRun, BoxConfig, SessionRunner
from .tasks import profile as task_profile
from .tasks.start_command import build_start_command
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
        self.discovery = discovery.discover()
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

        self.db = Database(data_dir / DB_FILENAME)
        self.cohorts = CohortRepository(self.db)
        self.sessions = SessionRepository(self.db)
        self.runner: SessionRunner | None = None
        self.backup: BackupManager | None = None
        self.analytics: AnalyticsService | None = None
        self.profiles = AnalyticsRepository(self.db)
        self._running_session_id: str | None = None
        #: One compile at a time — see _specs_compile for why this is not
        #: an optimisation.
        self._spec_compile_gate = asyncio.Semaphore(1)
        self.spec_store = spec_store.SpecStore(data_dir)
        #: hardware_id → detected interpreter baud. Detection costs a boot
        #: cycle per candidate rate, so the answer is kept for the app's
        #: lifetime — and invalidated on any flash to that box, since flashing
        #: is precisely what changes it.
        self._board_bauds: dict[str, int] = {}

    # --- lifecycle --------------------------------------------------------

    def register(self) -> None:
        self.server.register(Cmd.PING, self._ping)
        self.server.register(Cmd.SETTINGS_PUSH, self._settings_push)
        self.server.register(Cmd.SKETCHES_REFRESH, self._sketches_refresh)
        self.server.register(Cmd.PORT_PASSTHROUGH_OPEN, self._passthrough_open)
        self.server.register(Cmd.PORT_PASSTHROUGH_CLOSE, self._passthrough_close)
        self.server.register(Cmd.PORT_SEND, self._port_send)
        self.server.register(Cmd.PORT_FLASH, self._port_flash)
        self.server.register(Cmd.PORT_RESET, self._port_reset)
        self.server.register(Cmd.PORT_ERROR_ACK, self._port_error_ack)
        self.server.register(Cmd.UTILITY_STATUS, self._utility_status)
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
        self.server.register(Cmd.PREFIXES_LIST, self._prefixes_list)
        self.server.register(Cmd.PREFIXES_CREATE, self._prefixes_create)
        self.server.register(Cmd.PREFIXES_DELETE, self._prefixes_delete)
        self.server.register(Cmd.TASKS_GET_PROFILE, self._tasks_get_profile)
        self.server.register(Cmd.COHORTS_SUGGEST_GROUPS, self._cohorts_suggest_groups)

        self.server.register(Cmd.SESSIONS_SUGGEST_NUMBER, self._sessions_suggest_number)
        self.server.register(Cmd.SESSIONS_CREATE, self._sessions_create)
        self.server.register(Cmd.SESSIONS_ABANDON, self._sessions_abandon)
        self.server.register(Cmd.SESSIONS_CONFIRM_MAPPING, self._sessions_confirm_mapping)
        self.server.register(Cmd.SESSIONS_STATUS, self._sessions_status)
        self.server.register(Cmd.SESSIONS_START_ALL, self._sessions_start_all)
        self.server.register(Cmd.SESSIONS_SWITCH_GROUP, self._sessions_switch_group)
        self.server.register(Cmd.SESSIONS_END, self._sessions_end)
        self.server.register(Cmd.SESSIONS_ACTIVE, self._sessions_active)
        self.server.register(Cmd.PORT_START_SESSION, self._port_start_session)
        self.server.register(Cmd.PORT_STOP_SESSION, self._port_stop_session)
        self.server.register(Cmd.BACKUP_SYNC_NOW, self._backup_sync_now)

        self.server.register(Cmd.SESSIONS_LIST, self._sessions_list)
        self.server.register(Cmd.ANALYTICS_SUMMARY, self._analytics_summary)
        self.server.register(Cmd.ANALYTICS_SERIES, self._analytics_series)
        self.server.register(Cmd.ANALYTICS_RESCAN, self._analytics_rescan)
        self.server.register(Cmd.ANALYTICS_RECENT_SESSIONS, self._analytics_recent_sessions)
        self.server.register(Cmd.SESSIONS_RECOVER, self._sessions_recover)

        self.server.register(Cmd.SPECS_LIST, self._specs_list)
        self.server.register(Cmd.SPECS_GET, self._specs_get)
        self.server.register(Cmd.SPECS_SCHEMA, self._specs_schema)
        self.server.register(Cmd.SPECS_COMPILE, self._specs_compile)
        self.server.register(Cmd.SPECS_CAPABILITIES, self._specs_capabilities)
        self.server.register(Cmd.SPECS_PARADIGMS, self._specs_paradigms)
        self.server.register(Cmd.SPECS_SKELETON, self._specs_skeleton)
        self.server.register(Cmd.SPECS_SAVE, self._specs_save)
        self.server.register(Cmd.SPECS_DELETE, self._specs_delete)
        self.server.register(Cmd.SPECS_DIFF, self._specs_diff)
        self.server.register(Cmd.SPECS_EXPORT, self._specs_export)
        self.server.register(Cmd.BOARD_CAPABILITIES, self._board_capabilities)
        self.server.register(Cmd.BOARD_UPLOAD_TABLE, self._board_upload_table)
        self.server.register(Cmd.UTILITY_BENCH_HOLD, self._utility_bench_hold)

        self.server.on_client_ready(self._replay_state)

    def start(self) -> None:
        self.db.connect()
        self._log_spec_compiler()
        loop = asyncio.get_running_loop()
        self.backup = BackupManager(
            loop=loop,
            db=self.db,
            cohort_roots=self._cohort_roots,
            broadcast=self.server.broadcast,
        )
        # Every commit marks the database for backup — no write path can forget
        # to, and `session_animal_runs` written overnight counts just as much as
        # a cohort edit (`data.md` §7).
        self.db.on_commit(self.backup.mark_db_dirty)
        self.backup.start()
        self.analytics = AnalyticsService(
            db=self.db,
            cohorts=self.cohorts,
            sessions=self.sessions,
            broadcast=self.server.broadcast,
            sketch_lookup=self._sketch_path_for_name,
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

    async def stop(self) -> None:
        # Before the ports go: a lit box has a console open that must be closed
        # through the state machine rather than yanked out from under it.
        if self.utility is not None:
            await self.utility.stop()
        if self.ports is not None:
            await self.ports.stop()
        # After ports: nothing may be mid-flash once the manager has stopped,
        # so the daemon child (if the gRPC backend is active) can go too.
        await self.tool.close()
        if self.backup is not None:
            await self.backup.stop()
        self.db.close()

    def _log_spec_compiler(self) -> None:
        """Say once, at startup, whether the task-spec compiler came up.

        Its two dependencies are the only ones in this sidecar with no fallback
        behind them, so "is it there" has to be answerable from the log alone --
        particularly in a packaged build, where the failure mode is a PyInstaller
        data entry silently going missing and the only symptom is a banner on one
        screen nobody has opened yet.
        """
        from ephymeris_sidecar.specs import compiler

        ok, why = compiler.self_check()
        if not ok:
            log.warning(
                "task spec compiler unavailable (%s) — the Task screen's spec "
                "editor will be disabled; sessions and flashing are unaffected",
                why,
            )
            return
        log.info(
            "task spec compiler ready (%d specs, %d template versions, from %s)",
            len(list(compiler.bundled_specs_dir().glob("*.yaml"))),
            len(compiler.templates_available()),
            compiler.compiler_root(),
        )

    def _cohort_roots(self) -> list[str]:
        """Every cohort's data folder — the anchors for mirror paths (§8).

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
        await send(event(Evt.COHORTS_UPDATED, {"cohorts": await self._cohort_summaries()}))
        await send(event(Evt.PREFIXES_UPDATED, {"prefixes": await self._prefix_list()}))
        if spec_compiler.available()[0]:
            await send(event(Evt.SPECS_UPDATED, {"specs": self.spec_store.list_entries()}))
        if self.utility is not None:
            await send(event(Evt.UTILITY_UPDATED, self.utility.status()))
        if self.backup is not None:
            await send(event(Evt.BACKUP_STATUS, self.backup.status()))

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
        # §7/§10 hard stop: a box dropping out of IN_SESSION into ERROR means the
        # board vanished mid-run. Finalize whatever the write-ahead log durably
        # captured, with stop_reason "board disconnected". The ERROR itself
        # clears the normal way, via port.error.ack.
        if (
            previous == PortState.IN_SESSION
            and current == PortState.ERROR
            and self.runner is not None
        ):
            self.runner.board_dropped(box)
        # §8: a box that has just become nobody's is a box that should go back
        # to baseline. Driving this off the transition rather than off each
        # command means every way a port can fall idle — a run ending, a
        # console closing, an error acknowledged — is covered by one hook.
        if current == PortState.IDLE and self.utility is not None:
            self.utility.ensure([box])

    async def _handle_output(self, box: int, lines: list[OutputLine]) -> None:
        await self.server.broadcast(
            event(Evt.PORT_OUTPUT, {"box": box, "lines": [line.to_json() for line in lines]})
        )

    async def _handle_presence(self, boards: list[dict[str, object]]) -> None:
        await self.server.broadcast(event(Evt.BOARDS_PRESENCE, {"boards": boards}))
        if self.utility is not None:
            # This is also the startup path: the first poll that finds the rig
            # is what triggers the first baseline restore (§8.1).
            self.utility.note_presence(
                str(b.get("hardwareId")) for b in boards if b.get("hardwareId")
            )
            self.utility.ensure()
            await self.utility.publish()

    # --- handlers ---------------------------------------------------------

    async def _ping(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        return {"pong": True, "sidecarVersion": __version__}

    async def _settings_push(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """Accept the shell's settings and answer with the library's state.

        The bundled library no longer depends on anything in the settings, but
        the reply still carries its status so a client learns it on connect
        without a second round trip — the same moment it used to learn the old
        directory validation.
        """
        self.settings = SidecarSettings.from_payload(args.get("settings", args))
        log.info(
            "settings received (utilitySketch=%r, defaultBaud=%d, backupDirectory=%r)",
            self.settings.utility_sketch_name,
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

    async def _port_flash(self, _server, _conn, args, corr) -> dict[str, Any]:  # noqa: ANN001
        box = _box_arg(args)
        path = args.get("sketchPath")

        # The configured Arduino Directory is the only source of flashable
        # sketches (`tasks.md` §2.3) — enforced here, not just by the
        # picker only listing discovered sketches.
        sketch = next((s for s in self.discovery.sketches if s.path == path), None)
        if sketch is None:
            raise CommandError(
                ErrCode.SKETCH_UNKNOWN,
                "That sketch isn't in the configured Arduino Directory — "
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

        # §4: the session flash sequence needs every box to land in IDLE so the
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
        if self.utility is not None:
            self.utility.note_flashed(box, sketch.path)
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

    # --- utility baseline (settings.md §8) --------------------

    def _require_utility(self) -> UtilityBaseline:
        if self.utility is None:
            raise CommandError(ErrCode.INTERNAL, "hardware layer isn't running")
        return self.utility

    async def _utility_status(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        return self._require_utility().status()

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

    # --- cohorts (cohorts.md) ---------------------------------------------

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
            # §8: an explicit folder wins; otherwise derive one from the
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
        """Permanent delete — §9. Removes bookkeeping only, never data files."""
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
        cohort_id = _str_arg(args, "id")
        path = _str_arg(args, "path")
        move_existing = args.get("moveExisting") is True

        with _cohort_errors():
            cohort = await asyncio.to_thread(self.cohorts.get, cohort_id)
            target = await asyncio.to_thread(
                folders.relocate, cohort.data_folder, path, move_existing
            )
            cohort = await asyncio.to_thread(
                self.cohorts.set_data_folder, cohort_id, str(target)
            )
        await self._broadcast_cohorts()
        return {"cohort": cohort.to_json()}

    async def _cohorts_suggest_groups(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """§7 preview. Computes only — the client applies via `cohorts.update`."""
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

    # --- prefixes (data.md §3.1) -------------------------------------

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

    # --- task profiles (tasks.md §3) --------------------------------

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

    # --- task specs (specs.md) ---------------------------------------------

    def _require_spec_compiler(self) -> None:
        ok, why = spec_compiler.self_check()
        if not ok:
            raise CommandError(
                ErrCode.SPEC_COMPILER_UNAVAILABLE,
                "The task-spec compiler isn't available on this install — the "
                "spec editor is disabled. Sessions and flashing are unaffected.",
                {"reason": why},
            )

    async def _specs_list(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        return {"specs": await asyncio.to_thread(self.spec_store.list_entries)}

    async def _specs_get(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        spec_id = _str_arg(args, "specId")
        record = await asyncio.to_thread(self.spec_store.get, spec_id)
        if record is None:
            raise CommandError(
                ErrCode.SPEC_NOT_FOUND, f"No spec named {spec_id!r}.", {"specId": spec_id}
            )
        text = await asyncio.to_thread(record.read_text)
        return {
            "specId": record.spec_id,
            "origin": record.origin,
            "text": text,
            # None when the text will not parse — not an error here: the editor
            # opens what exists, and the compile that runs on mount is what
            # reports WHY it won't parse.
            "raw": await asyncio.to_thread(spec_store.parse_document, text),
        }

    async def _specs_schema(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        return await asyncio.to_thread(spec_compiler.registries)

    async def _specs_compile(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        text = args.get("text")
        if not isinstance(text, str):
            raise CommandError(ErrCode.SPEC_INVALID, "`text` must be a string.")
        if len(text.encode("utf-8", errors="ignore")) > spec_store.MAX_SPEC_BYTES:
            raise CommandError(
                ErrCode.SPEC_INVALID,
                f"The document is over {spec_store.MAX_SPEC_BYTES // 1024} KB — "
                "that is not a task spec.",
            )
        spec_id = args.get("specId") if isinstance(args.get("specId"), str) else None
        # Off the loop, and one at a time. This runs per keystroke (debounced
        # client-side); a synchronous compile here would stall the 20 Hz output
        # flush for all six ports, and mid-session the fsync-per-strobe write
        # path. The semaphore keeps a typing burst from stacking worker threads
        # that each hold the GIL through jsonschema's hot loop.
        async with self._spec_compile_gate:
            return await asyncio.to_thread(spec_service.compile_payload, text, spec_id)

    async def _specs_paradigms(self, _server, _conn, _args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        # Reads seven small files behind an lru_cache; no thread hop earns its
        # keep, and self_check() has already paid for the first load.
        return spec_service.paradigms_payload()

    async def _specs_skeleton(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        paradigm_id = args.get("paradigmId")
        spec_id = args.get("specId")
        if not isinstance(paradigm_id, str) or not isinstance(spec_id, str):
            raise CommandError(
                ErrCode.SPEC_INVALID, "`paradigmId` and `specId` must be strings."
            )
        if not spec_store.SPEC_ID_RE.match(spec_id):
            raise CommandError(
                ErrCode.SPEC_INVALID,
                f"{spec_id!r} is not a legal spec id — the id is also a filename.",
            )
        answers = args.get("answers")
        if answers is not None and not isinstance(answers, dict):
            raise CommandError(ErrCode.SPEC_INVALID, "`answers` must be an object.")
        try:
            # Behind the same gate as compile, because it ends in one.
            async with self._spec_compile_gate:
                return await asyncio.to_thread(
                    spec_service.skeleton_payload,
                    paradigm_id,
                    spec_id,
                    answers,
                    label=args.get("label"),
                    description=args.get("description"),
                )
        except CommandError:
            raise
        except Exception as exc:
            # A paradigm that cannot generate is an install-integrity problem --
            # the registry shipped broken -- not a document the user can fix, so
            # it reports as unavailable rather than as a diagnostic.
            raise CommandError(
                ErrCode.SPEC_COMPILER_UNAVAILABLE,
                f"the {paradigm_id!r} paradigm could not produce a draft: {exc}",
            ) from exc

    async def _specs_capabilities(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        topology = args.get("topology")
        if not isinstance(topology, dict):
            raise CommandError(ErrCode.SPEC_INVALID, "`topology` must be an object.")
        try:
            # Synchronous on purpose: a pure function of six scalars, cheaper
            # than the thread hop.
            return spec_service.capabilities_payload(topology)
        except Exception as exc:
            # An unknown template name or a malformed knob is a caller mistake,
            # not a compile diagnostic -- there is no document to diagnose.
            raise CommandError(ErrCode.SPEC_INVALID, str(exc)) from exc

    async def _broadcast_specs(self) -> None:
        await self.server.broadcast(
            event(
                Evt.SPECS_UPDATED,
                {"specs": await asyncio.to_thread(self.spec_store.list_entries)},
            )
        )

    async def _specs_save(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        spec_id = _str_arg(args, "specId")
        text = args.get("text")
        if not isinstance(text, str):
            raise CommandError(ErrCode.SPEC_INVALID, "`text` must be a string.")
        if len(text.encode("utf-8", errors="ignore")) > spec_store.MAX_SPEC_BYTES:
            raise CommandError(
                ErrCode.SPEC_INVALID,
                f"The document is over {spec_store.MAX_SPEC_BYTES // 1024} KB — "
                "that is not a task spec.",
            )
        # A document whose own spec_id disagrees with the file it lands in
        # would poison provenance: the id names the file, the table, and what a
        # board reports back after an upload. A HALF-BUILT document (no parse,
        # or no spec_id yet) is fine — the filename stem is its identity, which
        # is exactly the loader's own default.
        raw = await asyncio.to_thread(spec_store.parse_document, text)
        declared = raw.get("spec_id") if isinstance(raw, dict) else None
        if isinstance(declared, str) and declared != spec_id:
            raise CommandError(
                ErrCode.SPEC_INVALID,
                f"The document says `spec_id: {declared}` but is being saved as "
                f"{spec_id!r}. Change one to match the other — the frontend "
                "saves under the document's own id, so this usually means a "
                "stale client.",
            )
        try:
            record = await asyncio.to_thread(self.spec_store.save, spec_id, text)
        except spec_store.SpecIdInvalid as exc:
            raise CommandError(ErrCode.SPEC_INVALID, str(exc)) from exc
        entry = await asyncio.to_thread(self.spec_store.entry_for, record)
        # Saving always compiles — not as a gate (a half-finished spec must be
        # savable; the gate is upload), but because the caller is about to
        # render the result anyway and this keeps save and display in one
        # round trip.
        async with self._spec_compile_gate:
            result = await asyncio.to_thread(spec_service.compile_payload, text, spec_id)
        await self._broadcast_specs()
        return {"entry": entry, "result": result}

    async def _specs_delete(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        spec_id = _str_arg(args, "specId")
        if self.spec_store.get(spec_id) is None:
            raise CommandError(
                ErrCode.SPEC_NOT_FOUND, f"No spec named {spec_id!r}.", {"specId": spec_id}
            )
        await asyncio.to_thread(self.spec_store.delete, spec_id)
        await self._broadcast_specs()
        return {"entry": None}

    async def _specs_diff(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        spec_id = _str_arg(args, "specId")
        record = await asyncio.to_thread(self.spec_store.get, spec_id)
        if record is None:
            raise CommandError(
                ErrCode.SPEC_NOT_FOUND, f"No spec named {spec_id!r}.", {"specId": spec_id}
            )

        text = args.get("text")
        after_text = text if isinstance(text, str) else await asyncio.to_thread(record.read_text)

        against = args.get("againstSpecId")
        if isinstance(against, str) and against:
            other = await asyncio.to_thread(self.spec_store.get, against)
            if other is None:
                raise CommandError(
                    ErrCode.SPEC_NOT_FOUND, f"No spec named {against!r}.", {"specId": against}
                )
            before_text = await asyncio.to_thread(other.read_text)
            baseline = "spec"
        else:
            # Two baselines, not three. There is no shipped version to review
            # against any more, so a diff is either "my unsaved edits against my
            # own file" or "this task against that one".
            before_text, baseline = await asyncio.to_thread(record.read_text), "saved"

        async with self._spec_compile_gate:
            return await asyncio.to_thread(
                spec_service.diff_payload, spec_id, after_text, before_text, baseline
            )

    async def _specs_export(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        spec_id = _str_arg(args, "specId")
        kinds = args.get("artifacts")
        if not isinstance(kinds, list) or not all(isinstance(k, str) for k in kinds):
            raise CommandError(ErrCode.SPEC_INVALID, "`artifacts` must be a list of kinds.")
        text = args.get("text")
        if not isinstance(text, str):
            record = await asyncio.to_thread(self.spec_store.get, spec_id)
            if record is None:
                raise CommandError(
                    ErrCode.SPEC_NOT_FOUND, f"No spec named {spec_id!r}.", {"specId": spec_id}
                )
            text = await asyncio.to_thread(record.read_text)
        async with self._spec_compile_gate:
            return await asyncio.to_thread(spec_service.export_payload, spec_id, text, kinds)

    # --- bench boxes (specs.md) --------------------------------------------
    #
    # The structural invariant, stated where the handlers live: NOTHING here
    # ties a spec to a session. sessions.confirmMapping does not learn a
    # specId, and port.startSession is untouched. The interpreter is proved
    # off-target and has never driven a pin — a box carrying it accepts a
    # table and reports whether it fits. Revisit at Phase 5's exit criteria.

    def _detect_board_baud(self, box: int, address: str, requested: int | None) -> int:
        """The interpreter baud for this box — cached per hardware_id.

        NOT settings.defaultBaud: that is the console default (9600 for every
        legacy sketch), and using it here would make every interpreter board
        look mute. The interpreter fleet is mid-rollout at 115200/9600, which
        is exactly what transport detect exists for.
        """
        from ephymeris_sidecar.taskgraph.transport import client as tg_client

        from .ports.upload import PortLink

        if requested is not None:
            return requested
        hardware_id = self.settings.hardware_id_for(box)
        cached = self._board_bauds.get(hardware_id) if hardware_id else None
        if cached is not None:
            return cached
        baud = tg_client.detect(lambda b: PortLink(address, b, reset=True))
        if hardware_id is not None:
            self._board_bauds[hardware_id] = baud
        return int(baud)

    async def _board_capabilities(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        box = _box_arg(args)
        requested = args.get("baud") if isinstance(args.get("baud"), int) else None

        def work(address: str, handler) -> dict[str, Any]:  # noqa: ANN001
            from ephymeris_sidecar.taskgraph.transport import UploadError
            from ephymeris_sidecar.taskgraph.transport import client as tg_client

            from .ports.upload import PortLink

            try:
                baud = self._detect_board_baud(box, address, requested)
                with PortLink(address, baud, reset=True, mirror=handler.echo) as link:
                    banner, caps = tg_client.probe(link)
            except UploadError as exc:
                raise CommandError(ErrCode.UPLOAD_FAILED, str(exc), {"box": box}) from exc
            return {
                "box": box,
                "present": caps.present,
                "baud": baud,
                "values": dict(caps.values),
                "text": dict(caps.text),
                "banner": banner,
            }

        with _mapped_errors(box):
            _state, _resumed, payload = await self._require_ports().with_port_for_upload(
                box, work
            )
        return payload  # type: ignore[return-value]

    async def _board_upload_table(self, _server, _conn, args, corr) -> dict[str, Any]:  # noqa: ANN001
        self._require_spec_compiler()
        box = _box_arg(args)
        spec_id = _str_arg(args, "specId")
        text = args.get("text")
        if not isinstance(text, str):
            record = await asyncio.to_thread(self.spec_store.get, spec_id)
            if record is None:
                raise CommandError(
                    ErrCode.SPEC_NOT_FOUND, f"No spec named {spec_id!r}.", {"specId": spec_id}
                )
            text = await asyncio.to_thread(record.read_text)

        # Compiled server-side, always — a client-supplied table is never
        # trusted, so the compiler's structural gate (no table from a failing
        # spec) holds on the hardware path too.
        async with self._spec_compile_gate:
            compiled = await asyncio.to_thread(spec_compiler.compile, text, spec_id=spec_id)
        if not compiled.ok or compiled.table is None:
            errors = [d.message for d in compiled.bag if d.severity.name == "ERROR"]
            raise CommandError(
                ErrCode.UPLOAD_REFUSED,
                f"{spec_id} does not compile, so there is no table to upload.",
                {"box": box, "errors": errors[:8]},
            )
        table = compiled.table
        blob, crc = spec_compiler.table_bytes(compiled)

        loop = asyncio.get_running_loop()

        def emit_progress(phase: str, chunk: int | None, chunks: int | None, note: str | None):
            data = {"box": box, "phase": phase, "chunk": chunk, "chunks": chunks, "text": note}
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    self.server.broadcast(event(Evt.UPLOAD_PROGRESS, data, corr=corr))
                )
            )

        requested = args.get("baud") if isinstance(args.get("baud"), int) else None

        def work(address: str, handler) -> dict[str, Any]:  # noqa: ANN001
            from ephymeris_sidecar.taskgraph.transport import UploadError
            from ephymeris_sidecar.taskgraph.transport import client as tg_client
            from ephymeris_sidecar.taskgraph.transport.caps import CapabilityError

            from .ports.upload import PortLink

            emit_progress("detect", None, None, None)
            try:
                baud = self._detect_board_baud(box, address, requested)
                emit_progress("probe", None, None, f"board answered at {baud}")
                with PortLink(
                    address,
                    baud,
                    reset=True,
                    on_progress=emit_progress,
                    mirror=handler.echo,
                ) as link:
                    result = tg_client.upload(link, table, packed=blob)
            except CapabilityError as exc:
                # The board said no BEFORE any byte moved — un-migrated
                # firmware, a wire mismatch, or a capacity the table exceeds.
                # A healthy board answering honestly is not a port fault, so
                # this returns a marker (the port lands cleanly, passthrough
                # resumes) and becomes UPLOAD_REFUSED after landing. A broken
                # TRANSFER raises instead, which parks the port in ERROR — the
                # board's table is invalid and its state genuinely unknown.
                return {"refused": str(exc)}
            except UploadError as exc:
                raise CommandError(ErrCode.UPLOAD_FAILED, str(exc), {"box": box}) from exc
            emit_progress("verify", result.chunks, result.chunks, None)
            return {
                "box": box,
                "specId": table.spec_id,
                "specHash": table.spec_hash,
                "nBytes": result.n_bytes,
                "chunks": result.chunks,
                "crc32": f"{crc:#010x}",
                "digest": f"{result.digest:#010x}",
                "seconds": result.seconds,
                "notes": list(result.notes),
                "caps": {
                    "box": box,
                    "present": result.caps.present,
                    "baud": baud,
                    "values": dict(result.caps.values),
                    "text": dict(result.caps.text),
                    "banner": list(result.banner),
                },
            }

        with _mapped_errors(box):
            _state, _resumed, payload = await self._require_ports().with_port_for_upload(
                box, work
            )
        assert isinstance(payload, dict)
        if "refused" in payload:
            raise CommandError(ErrCode.UPLOAD_REFUSED, payload["refused"], {"box": box})
        log.info(
            "box %d: table %s (%s) uploaded, %d bytes",
            box,
            table.spec_id,
            table.spec_hash,
            len(blob),
        )
        return payload

    async def _utility_bench_hold(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        if self.utility is None:
            raise CommandError(ErrCode.INTERNAL, "hardware layer isn't running")
        self.utility.set_bench_hold(args.get("held") is True)
        await self.utility.publish()
        return self.utility.status()

    # --- backup (data.md §7) ---------------------------------------

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

    # --- analytics (websocket-protocol.md §3.4) --------------------------------------

    def _require_analytics(self) -> AnalyticsService:
        if self.analytics is None:
            raise CommandError(ErrCode.INTERNAL, "analytics isn't running")
        return self.analytics

    def _sketch_path_for_name(self, name: str) -> str | None:
        """A document's `sketch` field resolved against the current Arduino
        Directory — how an adopted orphan finds a `task.json` to decode with
        (`data.md` §8.1). Name collisions across categories are possible
        in principle; first discovery-order match wins, same as the picker.

        Falls back to profiles that *declare* the name in `legacyNames`
        (`tasks.md` §3.7), which is how a run recorded by older software
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
        # Adopted orphans (data.md §8.1) appear as payload-only synthetic
        # sessions so the Analytics selectors cover the whole archive. Both
        # sources are database reads — the no-filesystem rule holds.
        synthetic, synthetic_counts = await asyncio.to_thread(
            self._require_analytics().adopted_session_entries, cohort_id
        )
        merged = sorted(
            [*sessions, *synthetic], key=lambda s: (s.date, s.started_at, s.id)
        )
        return {
            "sessions": [
                session.to_list_item(
                    index + 1,
                    run_count=counts.get(
                        session.id, synthetic_counts.get(session.id, 0)
                    ),
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
        """The explicit archive walk (§8.1) — never a side effect of opening a view."""
        cohort_id = _str_arg(args, "cohortId")
        with _cohort_errors():
            try:
                return await self._require_analytics().rescan(
                    cohort_id, adopt_orphans=args.get("adoptOrphans") is not False
                )
            except AnalyticsBusy as exc:
                raise CommandError(ErrCode.INTERNAL, str(exc)) from exc

    async def _analytics_recent_sessions(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """Folder-name recency across every active cohort — cheap on purpose,
        so the Dashboard can ask without the rescan's cost or its ceremony."""
        return await self._require_analytics().recent_sessions(_opt_int(args.get("limit")))

    async def _sessions_recover(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        """The crash-recovery backfill (`data.md` §12, §11).

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

    # --- sessions (websocket-protocol.md §3) ------------------------------

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

        # §1 readiness: at least one group with a box-assigned animal.
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
        # this mapping just chose (§8.2). Also extinguishes the placement walk's
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
        for box in runner.configured_boxes():
            # `start_box` is a no-op for a box already running (§5.2).
            with _session_errors(box):
                runner.start_box(box)
        await asyncio.to_thread(self._open_group_run, session_id, runner.group_id)
        session = await asyncio.to_thread(self.sessions.set_status, session_id, "running")
        await self._broadcast_lifecycle()
        return {"session": session.to_json()}

    async def _sessions_switch_group(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        session_id = _str_arg(args, "sessionId")
        runner = self._require_runner()
        await runner.end_all("operator stop")
        session = await asyncio.to_thread(self._close_group_run, session_id)
        cohort = await asyncio.to_thread(self.cohorts.get, session.cohort_id)
        # Next populated group after those already run, by order (§5.2).
        run_group_ids = {g.group_id for g in session.group_runs}
        next_group = _next_populated_group(cohort, run_group_ids)
        # The boxes are idle and the operator is about to walk the rig again for
        # the next group, so the baseline comes back now rather than after the
        # whole session — that walk is the one that needs the lights.
        await self._release_baseline()
        if next_group is None:
            # Every populated group has run — finalize exactly as sessions.end
            # would, so no client has to follow up with a second command and
            # the session can't linger as 'running' forever.
            await asyncio.to_thread(self.sessions.set_status, session_id, "completed")
            self._running_session_id = None
        await self._broadcast_lifecycle()
        return {"nextGroupId": next_group}

    async def _sessions_end(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        session_id = _str_arg(args, "sessionId")
        await self._require_runner().end_all("operator stop")
        await asyncio.to_thread(self._close_group_run, session_id)
        session = await asyncio.to_thread(self.sessions.set_status, session_id, "completed")
        self._running_session_id = None
        await self._release_baseline()
        await self._broadcast_lifecycle()
        return {"session": session.to_json()}

    async def _release_baseline(self) -> None:
        """Hand the rig back to the utility baseline once a session lets go."""
        if self.utility is None:
            return
        self.utility.release()
        self.utility.ensure()
        await self.utility.publish()

    def _open_group_run(self, session_id: str, group_id: str) -> None:
        """Record that a group started running.

        This is what stops Switch Group from cycling back to a group that has
        already run — `_next_populated_group` skips whatever is recorded here.
        """
        session = self.sessions.get_session(session_id)
        if any(run.group_id == group_id for run in session.group_runs):
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
        with _session_errors(box):
            self._require_runner().start_box(box)
        return {"state": self._require_ports().handler(box).state.value}

    async def _port_stop_session(self, _server, _conn, args, _corr) -> dict[str, Any]:  # noqa: ANN001
        box = _box_arg(args)
        with _session_errors(box):
            self._require_runner().stop_box(box)
        return {"state": self._require_ports().handler(box).state.value}

    async def _on_animal_ended(self, run: ActiveRun, reason: str) -> None:
        """Record the run and tell the frontend (`session.animalEnded`)."""
        if self._running_session_id is not None:
            # Snapshot the profile that actually decoded this run (§8.2). A
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
            # The parameters this run actually ran on (§6.9). They already reach
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

    # --- internals --------------------------------------------------------

    async def _rescan(self) -> None:
        self.discovery = discovery.discover()
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
    """`dashboard.md` §7.1 — ready if any group holds a box-assigned animal."""
    return any(a.box_number is not None for a in cohort.animals)


def _next_populated_group(cohort: Any, already_run: set[str]) -> str | None:
    """The next group by `order` that has a box-assigned animal (§2.3, §5.2).

    Groups with no box-assigned animal are skipped rather than blocking, per §1.
    """
    populated = {
        a.group_id for a in cohort.animals if a.box_number is not None
    }
    for group in sorted(cohort.groups, key=lambda g: g.order):
        if group.id in populated and group.id not in already_run:
            return group.id
    return None


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


def _box_arg(args: dict[str, Any]) -> int:
    box = args.get("box")
    if not isinstance(box, int) or isinstance(box, bool):
        raise CommandError(ErrCode.BAD_MESSAGE, "`box` must be an integer 1–6")
    return box


class _mapped_errors:
    """Translate hardware-layer exceptions into typed protocol errors.

    The frontend renders whatever comes back here; it never decides for itself
    whether an operation was legal (`dashboard.md` §5.3).
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

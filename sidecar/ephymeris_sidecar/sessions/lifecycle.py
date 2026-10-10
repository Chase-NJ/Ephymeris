"""The held session and everything that happens to it, in order
(`ARCHITECTURE.md#session-lifecycle`).

One owner for the ordering rules: confirm a mapping, then hold the rig;
start the recording before any box; stop the boxes, then RHX; end, then clear,
then release. A handler parses its arguments, calls one method here, and maps
the exceptions below onto wire codes. Nothing else sequences the runner, the recording or the utility
baseline for a session.

Transitions are serialized: each takes one lock for its whole length, so a
second lifecycle command waits instead of landing inside a recording start or a
graceful end. The questions (`held`, `in_use`, `writing`) and the reads take no
lock, and neither does `animal_ended`, which the runner awaits from inside
`end_all` while an end holds it.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncContextManager, Awaitable, Callable

from ..intan.service import IntanNotReady
from ..protocol import Evt, event
from ..tasks import profile as task_profile
from ..tasks.start_command import build_start_command
from .models import GroupRun, Session, SessionAnimalRun, SessionNotFound
from .runner import ActiveRun, BoxConfig

if TYPE_CHECKING:
    from ..analytics.repository import AnalyticsRepository
    from ..cohorts.repository import CohortRepository
    from ..intan.service import IntanService
    from ..logbook.service import LogbookService
    from ..utility import UtilityBaseline
    from .repository import SessionRepository
    from .runner import SessionRunner

log = logging.getLogger(__name__)

#: How long a recording waits for each box to finish the trial it is in
#: after STOP. Longer than any trial the lab runs -- a 20 s error delay plus
#: a 4 s ITI plus the holds -- and the operator can cut it short.
RECORDING_GRACE_S = 45.0


class SessionRefused(Exception):
    """The session can't make this transition now. The message says why."""


class MappingRefused(Exception):
    """One box's mapping can't be run as declared."""

    def __init__(self, box: int, message: str) -> None:
        super().__init__(message)
        self.box = box


class BoxRefused(Exception):
    """Starting one box failed; the runner's or port's error is `__cause__`."""

    def __init__(self, box: int) -> None:
        super().__init__(f"box {box} could not start")
        self.box = box


@dataclass(frozen=True)
class MappingEntry:
    """One row of a confirmed mapping, as the client sent it. `box` is None
    when the client sent no whole number."""

    box: int | None
    animal_id: str
    sketch_path: str
    config: dict[str, Any]


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


class SessionLifecycle:
    def __init__(
        self,
        *,
        sessions: SessionRepository,
        cohorts: CohortRepository,
        runner: SessionRunner,
        intan: IntanService | None,
        utility: UtilityBaseline | None,
        profiles: AnalyticsRepository,
        logbook: LogbookService | None,
        rig_reading: Callable[[], AsyncContextManager[None]],
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._sessions = sessions
        self._cohorts = cohorts
        self._runner = runner
        self._intan = intan
        self._utility = utility
        self._profiles = profiles
        self._logbook = logbook
        self._rig_reading = rig_reading
        self._broadcast = broadcast
        self._held: str | None = None
        self._lock = asyncio.Lock()

    # --- questions --------------------------------------------------------

    @property
    def held(self) -> str | None:
        """The session holding the rig: from its mapping's confirmation (or a
        resume) until it ends or is abandoned. Between groups it is still held."""
        return self._held

    @property
    def in_use(self) -> bool:
        """A session held, or any box running: when nothing may regenerate the
        folders the boxes were or will be flashed from, or move the archive
        they write into."""
        return self._held is not None or bool(self._runner.running_boxes())

    @property
    def writing(self) -> bool:
        """Any box running, so a live `.tsv` with no `.json` yet exists."""
        return bool(self._runner.running_boxes())

    # --- reads --------------------------------------------------------------

    async def status(self, session_id: str) -> dict[str, Any]:
        session = await asyncio.to_thread(self._sessions.get_session, session_id)
        return {
            "session": session.to_json(),
            "groupId": self._runner.group_id,
            "boxes": self._runner.snapshot(),
        }

    async def active(self) -> dict[str, Any]:
        unfinished = await asyncio.to_thread(self._sessions.list_unfinished)
        return build_active_payload(self._held, self._runner, unfinished)

    async def announce(self) -> None:
        """Push the fresh `ActiveSessions` snapshot to every client.

        Every transition here calls it; a handler that changes session records
        some other way (a create, a tidy) calls it too. Never for per-box
        transitions, which stay on `port.state`.
        """
        await self._broadcast(event(Evt.SESSION_LIFECYCLE, await self.active()))

    # --- transitions --------------------------------------------------------

    async def confirm_mapping(
        self, session_id: str, group_id: str, entries: list[MappingEntry]
    ) -> None:
        async with self._lock:
            session = await asyncio.to_thread(self._sessions.get_session, session_id)
            cohort = await asyncio.to_thread(self._cohorts.get, session.cohort_id)

            # Held from the first profile read until the rig is held: a rig
            # definition write waiting meanwhile then sees the session and
            # refuses, instead of rebuilding the folders these profiles were
            # just read from (`TASKS.md#the-rig-definition`).
            async with self._rig_reading():
                names = {a.id: a.name for a in cohort.animals}
                box_configs: list[BoxConfig] = []
                for entry in entries:
                    if entry.box is None or entry.animal_id not in names or not entry.sketch_path:
                        raise SessionRefused(
                            "A box mapping is missing its box, animal, or sketch."
                        )
                    profile = None
                    try:
                        profile = await asyncio.to_thread(
                            task_profile.load_profile, entry.sketch_path
                        )
                    except task_profile.TaskProfileError:
                        profile = None  # profile-less: bare START, raw log
                    try:
                        start_command = build_start_command(profile, entry.config)
                    except task_profile.TaskProfileError as exc:
                        # The profile declares more than the firmware's line
                        # buffer can hold. Refusing the mapping is the point:
                        # the board cannot report a truncated START, so letting
                        # this through would run the session on whichever
                        # parameters happened to fit.
                        raise MappingRefused(entry.box, str(exc)) from exc
                    box_configs.append(
                        BoxConfig(
                            box=entry.box,
                            animal_id=entry.animal_id,
                            animal_name=names[entry.animal_id],
                            sketch_path=entry.sketch_path,
                            sketch_name=Path(entry.sketch_path).name,
                            start_command=start_command,
                            config_metadata=dict(entry.config),
                            profile=profile,
                        )
                    )

                self._runner.configure(
                    Path(session.folder_path),
                    f"{session.prefix_name}_{session.session_number}",
                    group_id,
                    box_configs,
                    duration_s=(
                        session.duration_minutes * 60.0
                        if session.duration_minutes is not None
                        else None
                    ),
                    session_id=session_id,
                )
                self._held = session_id
                # From here until the session ends the boxes belong to the
                # runner: they will carry task sketches and fall idle between
                # flashes, and a baseline restore landing in that window would
                # erase the very sketch this mapping just chose
                # (`ARCHITECTURE.md#three-rules-it-never-breaks`). Also
                # extinguishes the placement walk's lights, in case the client
                # didn't.
                if self._utility is not None:
                    self._utility.hold()
            await self.announce()

    async def start_all(self, session_id: str) -> Session:
        async with self._lock:
            await self._begin_recording_if_any(session_id)
            for box in self._runner.configured_boxes():
                # `start_box` is a no-op for a box already running
                # (`ARCHITECTURE.md#running-boxes`).
                self._start_box(box)
            await asyncio.to_thread(self._open_group_run, session_id, self._runner.group_id)
            session = await asyncio.to_thread(self._sessions.set_status, session_id, "running")
            await self.announce()
            return session

    async def start_box(self, box: int) -> None:
        """Start one box of the held session's mapping (`port.startSession`)."""
        async with self._lock:
            session_id = self._held
            if session_id is not None:
                await self._begin_recording_if_any(session_id)
            self._start_box(box)
            if session_id is not None and self._runner.group_id:
                # A group started one box at a time has run exactly as much as
                # one started with Start All. Without this it was never
                # recorded: the group step could not say it had run, and the
                # session sat in `configuring`, where Back on the next mapping
                # discarded it.
                await asyncio.to_thread(self._open_group_run, session_id, self._runner.group_id)
                session = await asyncio.to_thread(self._sessions.get_session, session_id)
                if session.status != "running":
                    await asyncio.to_thread(self._sessions.set_status, session_id, "running")
                    await self.announce()

    def stop_box(self, box: int) -> None:
        """Ask one box to stop at its next trial boundary (`port.stopSession`).
        Not a transition: the run ends when the board says so."""
        try:
            self._runner.stop_box(box)
        except Exception as exc:
            raise BoxRefused(box) from exc

    async def end_group(self, session_id: str) -> Session:
        """End the group on the rig and wait BETWEEN GROUPS
        (`ARCHITECTURE.md#group-step`).

        The session stays `running` and held, with an empty runner: which group
        runs next is the operator's choice, made on the group step, and a
        session is only ever finished by an explicit `end`.
        """
        async with self._lock:
            await self._end_all_boxes(session_id)
            session = await asyncio.to_thread(self._close_group_run, session_id)
            self._clear_runner()
            # The boxes are idle and the operator is about to walk the rig
            # again for the next group, so the baseline comes back now rather
            # than after the whole session — that walk is the one that needs
            # the lights.
            await self._release_baseline()
            await self.announce()
            return session

    async def end(self, session_id: str) -> Session:
        async with self._lock:
            held = self._held == session_id
            # Close Out on a crash-orphaned session reaches here too, and must
            # not stop whichever OTHER session the runner is holding.
            if held or self._held is None:
                await self._end_all_boxes(session_id)
            await asyncio.to_thread(self._close_group_run, session_id)
            session = await asyncio.to_thread(self._sessions.set_status, session_id, "completed")
            if held:
                self._clear_runner()
                self._held = None
            if held or self._held is None:
                await self._release_baseline()
            await self.announce()
        # The session's clock just closed; its log's end time and elapsed did too.
        if self._logbook is not None:
            await self._logbook.refresh(session.cohort_id, [session.id])
        return session

    async def resume(self, session_id: str) -> Session:
        """Continue one of today's sessions with another group.

        Deliberately NOT session resumption
        (`DATA.md#continuing-between-groups`): nothing is picked up mid-group.
        A group that was running when the app died is closed as it stands --
        its animals' `.tsv` files are the record, and `sessions.recover`
        backfills them -- and the session re-enters the between-groups state
        `end_group` leaves, as if the operator had pressed Switch Group.

        Same day only: the session folder carries its date in its name, and a
        run appended to it tomorrow would be filed under the wrong day.
        """
        async with self._lock:
            session = await asyncio.to_thread(self._sessions.get_session, session_id)
            if session.status not in ("running", "completed"):
                raise SessionRefused(
                    f"session is {session.status}; only one that ran a group can be continued"
                )
            if not session.group_runs:
                raise SessionRefused(
                    "this session never ran a group — start a new session instead"
                )
            if session.date != datetime.now().date().isoformat():
                raise SessionRefused(
                    "only today's sessions can be continued — its folder is named for "
                    f"{session.date}"
                )
            # Holding the rig again waits out a rig definition write in
            # progress, which checked for a held session before this one existed.
            async with self._rig_reading():
                if self._held is not None and self._held != session_id:
                    raise SessionRefused(
                        "another session is open — end it before continuing this one"
                    )
                if self._held == session_id and self._runner.configured_boxes():
                    # Already held with a mapping loaded: nothing to resume.
                    return session
                await asyncio.to_thread(self._close_group_run, session_id)
                session = await asyncio.to_thread(self._sessions.set_status, session_id, "running")
                self._clear_runner()
                self._held = session_id
                await self.announce()
                return session

    async def abandon(self, session_id: str) -> Session:
        async with self._lock:
            session = await asyncio.to_thread(self._sessions.get_session, session_id)
            # Once a group has run the record holds real history; only a
            # session still in Step 2 limbo may be discarded.
            if session.status != "configuring":
                raise SessionRefused(
                    f"session is {session.status}; only a configuring session can be abandoned"
                )
            # A confirmed-but-unstarted mapping may already sit in the runner —
            # drop it so the next session can't inherit this one's boxes.
            if self._held == session_id:
                self._runner.clear()
                self._held = None
            if self._intan is not None:
                # A recording that was set up and never started. One that IS
                # running is left alone -- `release` refuses nothing and stops
                # nothing.
                self._intan.release()
            session = await asyncio.to_thread(self._sessions.set_status, session_id, "aborted")
            await self._release_baseline()
            await self.announce()
            return session

    # --- the runner's hook ------------------------------------------------

    async def animal_ended(self, run: ActiveRun, reason: str) -> None:
        """Record the run and tell the frontend (`session.animalEnded`).

        Keyed by the session the run was started under, never by `held`: a
        finalization may land after the session that started it let go.
        """
        if run.session_id:
            # Snapshot the profile that actually decoded this run
            # (`DATA.md#which-profile-decodes-a-run`). A `task.json` lives
            # beside its sketch and can be edited or deleted long after a
            # session, so without this the run would silently be
            # re-interpreted years later with whatever codes are current.
            profile_hash = None
            if run.config.profile is not None:
                try:
                    profile_hash = await asyncio.to_thread(
                        self._profiles.remember_profile, run.config.profile
                    )
                except Exception:  # noqa: BLE001 - never fail a finalization over this
                    log.exception("couldn't snapshot the task profile for box %d", run.box)
            # The parameters this run actually ran on
            # (`TASKS.md#three-layer-merge`). They already reach the session
            # file; recording them here is what makes them queryable, and what
            # lets Analytics tell two differently-tuned runs of the same sketch
            # apart — `profile_hash` cannot, it covers only the declaration.
            run_config = dict(run.config.config_metadata) or None
            await asyncio.to_thread(
                self._sessions.record_animal_run,
                SessionAnimalRun(
                    id=run.run_id,
                    session_id=run.session_id,
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
        if self._intan is not None:
            self._intan.box_ended(run.box, run.config.animal_name, reason)
        await self._broadcast(
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
        if self._logbook is not None and run.session_id:
            try:
                session = await asyncio.to_thread(self._sessions.get_session, run.session_id)
                await self._logbook.refresh(session.cohort_id, [session.id])
            except Exception:  # noqa: BLE001
                log.exception("logbook: couldn't announce box %d's run", run.box)

    # --- internals ----------------------------------------------------------

    def _start_box(self, box: int) -> None:
        try:
            self._runner.start_box(box)
        except Exception as exc:
            raise BoxRefused(box) from exc

    async def _is_recording_session(self, session_id: str) -> bool:
        try:
            session = await asyncio.to_thread(self._sessions.get_session, session_id)
        except SessionNotFound:
            return False
        return session.recording is not None

    async def _begin_recording_if_any(self, session_id: str) -> None:
        """Start RHX recording BEFORE any box starts, or refuse
        (`RECORDING.md#start`).

        The one place the recording may fail the session path, and on purpose:
        a behavior session quietly missing its electrophysiology cannot be
        re-run, so this raises while no animal has seen a trial yet.
        """
        if self._intan is None or not await self._is_recording_session(session_id):
            return
        if not self._intan.configured_for(session_id, self._runner.group_id):
            raise IntanNotReady(
                "This is a recording session, but no recording is set up for this "
                "group. Finish the Recording step first."
            )
        await self._intan.start_recording()

    async def _end_all_boxes(self, session_id: str) -> None:
        """End every box, and the recording around them if there is one
        (`RECORDING.md#graceful-end`).

        Order is the whole point: STOP the boxes, WAIT for each to close its
        trial, and only then stop RHX -- so the last event of every animal is
        inside the recording, with a post-roll after it.
        """
        intan = self._intan
        if intan is None or not intan.is_recording:
            await self._runner.end_all("operator stop")
            if intan is not None:
                intan.release()
            return
        await self._runner.end_all(
            "operator stop",
            graceful_timeout_s=RECORDING_GRACE_S,
            force=intan.force_stop,
            on_waiting=intan.note_waiting,
        )
        run = await intan.stop_recording()
        if run is not None:
            await asyncio.to_thread(self._record_recording_run, session_id, run)

    def _record_recording_run(self, session_id: str, run: dict[str, Any]) -> None:
        session = self._sessions.get_session(session_id)
        recording = dict(session.recording or {"runs": []})
        recording["runs"] = [*recording.get("runs", []), run]
        self._sessions.set_recording(session_id, recording)

    async def _release_baseline(self) -> None:
        """Hand the rig back to the utility baseline once a session lets go."""
        if self._utility is None:
            return
        self._utility.release()
        self._utility.ensure()
        await self._utility.publish()

    def _clear_runner(self) -> None:
        """Drop the finished group's mapping so the runner holds no boxes.

        Between groups the runner must not still describe the previous group:
        a reload would otherwise offer Start All on animals already carried
        home. `clear` refuses while a run is active, which after `end_all`
        cannot be the case -- but a refusal is logged rather than raised,
        because the group HAS ended and the session must not be stranded.
        """
        try:
            self._runner.clear()
        except RuntimeError:
            log.warning("runner still holds active runs after the group ended")

    def _open_group_run(self, session_id: str, group_id: str) -> None:
        """Record that a group started running.

        What the group step reads to badge a group "ran 10:42", and what
        `resume` requires before a session can be continued. Deduped only
        against an OPEN run of the same group: running a group a second time is
        allowed and appends a second entry, while Start All after a per-box
        start (both in one group run) does not.
        """
        session = self._sessions.get_session(session_id)
        if any(
            run.group_id == group_id and run.ended_at is None
            for run in session.group_runs
        ):
            return
        runs = [*session.group_runs, GroupRun(group_id=group_id, order=len(session.group_runs), started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))]
        self._sessions.set_group_runs(session_id, runs)

    def _close_group_run(self, session_id: str) -> Session:
        """Close the open group run, if there is one."""
        session = self._sessions.get_session(session_id)
        runs = list(session.group_runs)
        for index, run in enumerate(runs):
            if run.ended_at is None:
                runs[index] = replace(run, ended_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                return self._sessions.set_group_runs(session_id, runs)
        return session

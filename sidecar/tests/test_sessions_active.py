"""`sessions.active` reconciliation — `build_active_payload`.

The running slot is keyed off the runner-held id, never bare DB status: a
runner-held session can still read `configuring` (post-confirmMapping,
pre-startAll) and belongs in `running`, while a `running` DB row nobody holds
is a crash orphan and lands in `stale` (`PROTOCOL.md#cmd-sessions.active`).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ephymeris_sidecar.sessions.lifecycle import build_active_payload
from ephymeris_sidecar.protocol import Evt, event, validate_command_result
from ephymeris_sidecar.sessions.models import GroupRun, Session
from ephymeris_sidecar.sessions.runner import BoxConfig, SessionRunner


def _session(sid: str = "s1", status: str = "running") -> Session:
    return Session(
        id=sid,
        cohort_id="c1",
        prefix_id="p1",
        prefix_name="2O-Bdisc",
        session_number="25",
        date="2026-07-27",
        started_at="2026-07-27T09:00:00+00:00",
        status=status,
        folder_path="/data/Batch A/2O-Bdisc/2O-Bdisc_25_2026-07-27",
        group_runs=[GroupRun("g1", 0, "2026-07-27T09:00:00+00:00")],
    )


@pytest.fixture
def runner(tmp_path: Path):
    loop = asyncio.new_event_loop()

    async def broadcast(_message):  # pragma: no cover — never awaited here
        pass

    async def on_animal_ended(_run, _reason):  # pragma: no cover
        pass

    r = SessionRunner(
        loop=loop, ports=None, broadcast=broadcast, on_animal_ended=on_animal_ended
    )
    r.configure(
        tmp_path,
        "2O-Bdisc_25",
        "g1",
        [
            BoxConfig(
                box=1,
                animal_id="a1",
                animal_name="remy1",
                sketch_path="/sk/GRGL_2-Odor",
                sketch_name="GRGL_2-Odor",
                start_command="START",
                config_metadata={},
                profile=None,
            )
        ],
        session_id="s1",
    )
    try:
        yield r
    finally:
        loop.close()


def test_runner_held_running_session_fills_the_running_slot(runner) -> None:
    payload = build_active_payload("s1", runner, [_session("s1", "running")])
    assert payload["running"]["session"]["id"] == "s1"
    assert payload["running"]["groupId"] == "g1"
    assert [b["box"] for b in payload["running"]["boxes"]] == [1]
    assert payload["configuring"] == []
    assert payload["stale"] == []


def test_runner_held_configuring_session_counts_as_running(runner) -> None:
    """Post-confirmMapping, pre-startAll: DB still says configuring, but the
    runner holds it — it belongs in `running`, not in the resumable-setup list."""
    payload = build_active_payload("s1", runner, [_session("s1", "configuring")])
    assert payload["running"]["session"]["status"] == "configuring"
    assert payload["configuring"] == []


def test_crash_orphaned_running_row_lands_in_stale(runner) -> None:
    """A `running` row with no live runner holding it is a crash orphan —
    surfaced, never offered for resume."""
    payload = build_active_payload(None, runner, [_session("s1", "running")])
    assert payload["running"] is None
    assert [s["id"] for s in payload["stale"]] == ["s1"]
    assert payload["configuring"] == []


def test_plain_configuring_rows_are_resumable_setups(runner) -> None:
    payload = build_active_payload(
        "s1",
        runner,
        [
            _session("s1", "running"),
            _session("s2", "configuring"),
            _session("s3", "configuring"),
        ],
    )
    assert payload["running"]["session"]["id"] == "s1"
    assert [s["id"] for s in payload["configuring"]] == ["s2", "s3"]


def test_running_id_with_no_matching_row_yields_null(runner) -> None:
    """A deleted or already-finished row behind the held id must not crash —
    the running slot simply reads empty."""
    payload = build_active_payload("gone", runner, [_session("s2", "configuring")])
    assert payload["running"] is None
    assert [s["id"] for s in payload["configuring"]] == ["s2"]


def test_no_runner_yields_null_running_slot() -> None:
    payload = build_active_payload("s1", None, [_session("s1", "running")])
    assert payload["running"] is None
    assert [s["id"] for s in payload["stale"]] == ["s1"]


def test_unconfigured_group_id_is_emitted_as_null(tmp_path: Path) -> None:
    """`runner.group_id` is `""` before configure — the wire field is null."""
    loop = asyncio.new_event_loop()
    try:

        async def noop(*_args):  # pragma: no cover
            pass

        bare = SessionRunner(loop=loop, ports=None, broadcast=noop, on_animal_ended=noop)
        payload = build_active_payload("s1", bare, [_session("s1", "configuring")])
        assert payload["running"]["groupId"] is None
    finally:
        loop.close()


# --- wire conformance ------------------------------------------------------


def test_active_payload_matches_schema_as_command_and_event(runner) -> None:
    """One shape serves both `sessions.active` and `session.lifecycle` — pin
    the same payload against each. conftest's EPHYMERIS_WIRE_VALIDATE=1 makes
    the `event()` call itself the assertion."""
    payload = build_active_payload(
        "s1",
        runner,
        [
            _session("s1", "running"),
            _session("s2", "configuring"),
            _session("s3", "running"),
        ],
    )
    assert validate_command_result("sessions.active", payload) == []
    assert event(Evt.SESSION_LIFECYCLE, payload)["data"] == payload

    empty = build_active_payload(None, None, [])
    assert validate_command_result("sessions.active", empty) == []
    assert event(Evt.SESSION_LIFECYCLE, empty)["data"] == empty

"""The dispatch seam (`server.py`, `app.py`): every command's refusal reaches
the wire under the code its cause names, and a client that connects late is
told everything a client that was there all along was told.

Driven through `tests/wire.py`'s `dispatch`, which hands a JSON frame to the
server's own message handler, so the error table and the reply check under
test are the ones production runs.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from websockets.asyncio.client import connect

from ephymeris_sidecar.protocol import PROTOCOL_VERSION
from tests.live_sidecar import TOKEN, LiveSidecar, Refused
from tests.wire import dispatch, running_app


@pytest.fixture
async def app(tmp_path: Path):
    async with running_app(tmp_path / "app") as app:
        yield app


async def _cohort(app, folder: Path) -> dict:  # noqa: ANN001
    created = await dispatch(
        app, "cohorts.create", name=folder.name, dataFolder=str(folder),
        groups=[{"id": "g1", "name": "Morning", "order": 0}],
        animals=[{"name": "rat1", "groupId": "g1", "boxNumber": 1}],
    )
    return created["cohort"]


# --- B10: a busy archive is not an internal error -------------------------------


@pytest.mark.parametrize(
    ("cmd", "args"),
    [
        ("cohorts.setDataFolder", lambda c, tmp: {"id": c["id"], "path": str(tmp / "elsewhere"), "moveExisting": False}),
        ("cohorts.moveAnimals", lambda c, tmp: {
            "cohortId": c["id"], "animalIds": [c["animals"][0]["id"]],
            "destinationCohortId": c["id"], "apply": True,
        }),
        ("analytics.rescan", lambda c, tmp: {"cohortId": c["id"]}),
        ("sessions.tidy", lambda c, tmp: {"cohortId": c["id"], "apply": True}),
    ],
)
async def test_a_busy_archive_is_refused_as_busy(app, tmp_path: Path, cmd: str, args) -> None:  # noqa: ANN001
    """A double-click on a walk, a move or a tidy is the operator's to wait out,
    not a sidecar fault: it must not arrive as INTERNAL."""
    cohort = await _cohort(app, tmp_path / "Batch A")
    async with app.archive.exclusive():
        with pytest.raises(Refused) as refused:
            await dispatch(app, cmd, **args(cohort, tmp_path))
    assert refused.value.code == "ARCHIVE_BUSY"
    assert "try again" in refused.value.message


# --- B10: a box whose port refuses to open --------------------------------------


async def test_a_box_start_the_port_refuses_is_a_port_open_failure(app, monkeypatch) -> None:  # noqa: ANN001
    """The code a port command gives for the same failure, with the box named.
    Windows says Access is denied for a COM port another program holds."""

    def refused(box: int) -> None:
        raise PermissionError(13, "Access is denied", f"COM{box + 3}")

    monkeypatch.setattr(app.runner, "start_box", refused)
    with pytest.raises(Refused) as failed:
        await dispatch(app, "port.startSession", box=2)
    assert failed.value.code == "PORT_OPEN_FAILED"
    assert failed.value.detail == {"box": 2}


# --- B12: a client that connects late is told about a Debug run ------------------


async def test_a_client_connecting_after_a_debug_run_started_sees_it_running(sidecar: LiveSidecar) -> None:
    """A webview reload mid bench-test: the new page must still offer End. A
    profile-less sketch is the case that never got a second payload."""
    sidecar.app.debug_runs.arm(3, None)

    late = await _reconnect(sidecar)

    assert {"box": 3, "running": True, "metrics": []} in late


async def _reconnect(sidecar: LiveSidecar) -> list[dict]:
    """Open a second client, authenticate, and return the `port.telemetry`
    payloads replayed to it before its first reply."""
    port = sidecar.app.server.port
    async with connect(f"ws://127.0.0.1:{port}") as ws:
        await ws.recv()  # server.hello
        await ws.send(json.dumps({"v": PROTOCOL_VERSION, "id": "a", "cmd": "auth", "args": {"token": TOKEN}}))
        await ws.recv()  # the auth reply; replay follows it
        await ws.send(json.dumps({"v": PROTOCOL_VERSION, "id": "b", "cmd": "flash.status", "args": {}}))
        telemetry: list[dict] = []
        while True:
            message = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if message.get("corr") == "b":
                return telemetry
            if message.get("evt") == "port.telemetry":
                telemetry.append(message["data"])


async def test_a_cohort_command_still_works_through_dispatch(app, tmp_path: Path) -> None:
    """The harness itself: a plain command round-trips."""
    cohort = await _cohort(app, tmp_path / "Batch B")
    listed = await dispatch(app, "cohorts.list")
    assert [c["id"] for c in listed["cohorts"]] == [cohort["id"]]


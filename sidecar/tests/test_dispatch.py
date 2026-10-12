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
from tests.live_sidecar import TOKEN, LiveSidecar, Refused, animal
from tests.wire import dispatch, running_app


@pytest.fixture
async def app(tmp_path: Path):
    async with running_app(tmp_path / "app") as app:
        yield app


async def _cohort(app, folder: Path) -> dict:  # noqa: ANN001
    created = await dispatch(
        app, "cohorts.create", name=folder.name, dataFolder=str(folder),
        groups=[{"id": "g1", "name": "Morning", "order": 0}],
        animals=[animal("rat1", "g1", box=1)],
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
        # B11: a recover writes files into the folder a relocate may be moving.
        ("sessions.recover", lambda c, tmp: {"cohortId": c["id"]}),
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


# --- B7 and candidate 4: an archive write while a box writes ----------------------


@pytest.mark.parametrize(
    ("cmd", "args"),
    [
        # B7: a walk while a box writes can adopt a file its record is about to claim.
        ("analytics.rescan", lambda c, tmp: {"cohortId": c["id"]}),
        ("sessions.recover", lambda c, tmp: {"cohortId": c["id"]}),
        ("cohorts.setDataFolder", lambda c, tmp: {"id": c["id"], "path": str(tmp / "elsewhere"), "moveExisting": True}),
    ],
)
async def test_an_archive_write_while_a_box_writes_is_refused_as_rig_in_use(
    app, tmp_path: Path, monkeypatch, cmd: str, args  # noqa: ANN001
) -> None:
    """"The rig is in use" is one code, whichever archive write asked."""
    cohort = await _cohort(app, tmp_path / "Batch A")
    monkeypatch.setattr(app.runner, "running_boxes", lambda: [2])
    with pytest.raises(Refused) as refused:
        await dispatch(app, cmd, **args(cohort, tmp_path))
    assert refused.value.code == "RIG_IN_USE"


async def test_a_move_while_the_rig_is_in_use_carries_the_refusal_in_its_plan(
    app, tmp_path: Path, monkeypatch  # noqa: ANN001
) -> None:
    """The move dialog shows a refused plan's reasons (`refusedPlan`), so a
    rig in use stays one of them rather than a code of its own."""
    source = await _cohort(app, tmp_path / "Batch A")
    dest = (await dispatch(
        app, "cohorts.create", name="Batch B", dataFolder=str(tmp_path / "Batch B"),
        groups=[{"id": "g2", "name": "Evening", "order": 0}], animals=[],
    ))["cohort"]
    monkeypatch.setattr(app.runner, "running_boxes", lambda: [2])
    args = {
        "cohortId": source["id"], "animalIds": [source["animals"][0]["id"]],
        "destinationCohortId": dest["id"],
    }
    preview = await dispatch(app, "cohorts.moveAnimals", **args, apply=False)
    assert "busy" in [r["code"] for r in preview["refused"]]
    with pytest.raises(Refused) as refused:
        await dispatch(app, "cohorts.moveAnimals", **args, apply=True)
    assert refused.value.code == "ANIMAL_MOVE_REFUSED"
    assert "busy" in [r["code"] for r in refused.value.detail["refused"]]


async def test_an_archive_write_is_followed_up_in_one_place(app, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """What a recover wrote is mirrored, and a relocate is announced to every
    client, without either handler wiring its own follow-up."""
    from tests.test_recovery import crash_a_run

    cohort = await _cohort(app, tmp_path / "Batch A")
    tsv = crash_a_run(tmp_path / "Batch A" / "2O-Bdisc" / "2O-Bdisc_25_2026-07-22")
    queued: list = []
    monkeypatch.setattr(app.backup, "enqueue", lambda *paths: queued.extend(map(str, paths)))
    published: list[str] = []

    async def publish(evt: str) -> None:
        published.append(evt)

    monkeypatch.setattr(app.server, "publish", publish)

    await dispatch(app, "sessions.recover", cohortId=cohort["id"])
    assert str(tsv.parent.parent / "behavior.json" / f"{tsv.stem}.json") in queued
    assert published == []

    await dispatch(app, "cohorts.setDataFolder", id=cohort["id"], path=str(tmp_path / "C"), moveExisting=True)
    assert published == ["cohorts.updated"]


# --- B10: a box whose port refuses to open --------------------------------------


async def test_a_box_start_the_port_refuses_is_a_port_open_failure(app, monkeypatch) -> None:  # noqa: ANN001
    """The code a port command gives for the same failure, with the box named.

    Pins the error table's `OSError` row for a box's command, reached through
    `BoxRefused`. The runner is patched because a real held COM port no longer
    refuses here: the serial open runs on the session thread
    (`PortHandler.claim_session`), so the start replies and the port then goes
    to ERROR. What still raises synchronously is the runner's own work, or a
    command like `utility.identify` that writes to the port itself."""

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


# --- arguments are the schema's before a handler sees them -----------------------


@pytest.mark.parametrize(
    ("cmd", "args", "problem"),
    [
        ("port.reset", {"box": "1"}, "port.reset.args.box: expected int, got str"),
        ("port.reset", {}, "missing required field `box`"),
        ("port.send", {"box": 1, "text": "x", "lineEnding": "lfcr"}, "not one of"),
        ("cohorts.get", {"id": "c1", "extra": True}, "unknown field `extra`"),
        ("sessions.create", {"cohortId": "c", "prefixId": "p", "sessionNumber": "1", "durationMinutes": 2.5},
         "expected int, got float"),
    ],
)
async def test_arguments_that_are_not_the_schemas_are_a_bad_message(app, monkeypatch, cmd, args, problem) -> None:  # noqa: ANN001
    """Refused before the handler runs, under one code, naming the problem."""
    ran: list[str] = []
    monkeypatch.setitem(app.server._handlers, cmd, lambda _args: ran.append(cmd))  # noqa: SLF001
    with pytest.raises(Refused) as refused:
        await dispatch(app, cmd, **args)
    assert refused.value.code == "BAD_MESSAGE"
    assert any(problem in p for p in refused.value.detail["problems"])
    assert ran == []


async def test_a_box_outside_the_rig_is_a_bad_message(app) -> None:  # noqa: ANN001
    with pytest.raises(Refused) as refused:
        await dispatch(app, "port.reset", box=7)
    assert refused.value.code == "BAD_MESSAGE"


async def test_every_declared_command_has_a_handler(app) -> None:  # noqa: ANN001
    assert app.server.unhandled() == set()


# --- one table ------------------------------------------------------------------


def test_no_domain_module_knows_the_wire_error_type() -> None:
    """Domain modules raise their own exceptions; `wire_errors.py` maps them.
    Only the wire layer may name `CommandError`."""
    package = Path(__file__).resolve().parents[1] / "ephymeris_sidecar"
    wire_layer = {"server.py", "app.py", "wire_errors.py"}
    offenders = [
        str(path.relative_to(package))
        for path in package.rglob("*.py")
        if path.name not in wire_layer and "CommandError" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


# --- one snapshot for replay and publish --------------------------------------------


async def test_publish_sends_what_replay_sends(app, tmp_path: Path) -> None:  # noqa: ANN001
    """A client that reconnects is told what one that stayed was told."""
    await _cohort(app, tmp_path / "Batch C")
    published: list[dict] = []

    async def broadcast(message: dict) -> None:
        published.append(message)

    app.server.broadcast = broadcast
    await app.server.publish("cohorts.updated")
    [replayed] = await app.server.snapshot("cohorts.updated")
    assert [m["data"] for m in published] == [replayed["data"]]


async def test_replay_sends_one_port_state_per_box_first(sidecar: LiveSidecar) -> None:
    port = sidecar.app.server.port
    async with connect(f"ws://127.0.0.1:{port}") as ws:
        await ws.recv()
        await ws.send(json.dumps({"v": PROTOCOL_VERSION, "id": "a", "cmd": "auth", "args": {"token": TOKEN}}))
        await ws.recv()
        replayed = [json.loads(await asyncio.wait_for(ws.recv(), timeout=5)) for _ in range(7)]
    assert [m["evt"] for m in replayed[:6]] == ["port.state"] * 6
    assert [m["data"]["box"] for m in replayed[:6]] == [1, 2, 3, 4, 5, 6]
    assert replayed[6]["evt"] == "boards.presence"  # no Debug run, so no port.telemetry


"""A Debug Mode flash must survive, and must be startable.

The regression this file exists for: flashing a task from an `IDLE` port lands
the port back in `IDLE`, and the app's idle hook answers every `IDLE` transition
by asking the utility baseline for a restore. So the baseline re-flashed its
own sketch over the operator's within seconds, silently, and the box could not
be started or talked to.

`test_utility.py` could not see it, because its harness wires the port manager
with a no-op `on_state_change` — the hook that did the damage was never in the
loop. The harness here hands the port manager the app's REAL
`_handle_state_change`, and drives the real `_port_flash` handler over it, so
the order of "note what was flashed" and "the idle hook fires" is the order
production has.

The second half covers what makes a flashed task usable from the console:
`port.sendStart`, and the live scoring it arms (`debug_run.py`).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from ephymeris_sidecar import app as app_module
from ephymeris_sidecar.app import Application
from ephymeris_sidecar.rig.definition import _ReadWriteLock
from ephymeris_sidecar.boards.tool import DetectedBoard
from ephymeris_sidecar.debug_run import DebugRuns
from ephymeris_sidecar.ports.handler import OutputLine
from ephymeris_sidecar.ports.manager import FQBN, PortManager
from ephymeris_sidecar.protocol import ErrCode, Evt
from ephymeris_sidecar.server import CommandError
from ephymeris_sidecar.settings import SidecarSettings
from ephymeris_sidecar.tasks.metrics import MetricSet
from ephymeris_sidecar.tasks.profile import load_profile, parse_profile
from ephymeris_sidecar.tasks.start_command import build_start_command
from ephymeris_sidecar.utility import UtilityBaseline

from .test_utility import (  # noqa: F401 - fake_serial is an autouse fixture
    ADDRESS,
    HWID,
    TASK_PATH,
    UTILITY_PATH,
    UTILITY_PROFILE,
    FakeDiscovery,
    FakeTool,
    _noop_output,
    _noop_presence,
    box_state,
    fake_serial,
    settle,
)

TASK_PROFILE = parse_profile(
    {
        "taskName": "GRGL",
        "kind": "behavior",
        "config": [
            {
                "metadataKey": "iti",
                "wireKey": "ITI",
                "label": "Inter-trial interval",
                "type": "int",
                "default": 4000,
            },
            {
                "metadataKey": "reward",
                "wireKey": "RW",
                "label": "Reward",
                "type": "int",
                "default": 40,
            },
        ],
    }
)


def make_app() -> SimpleNamespace:
    """The slice of `Application` the port handlers touch, over real parts.

    A stand-in rather than the real class because constructing `Application`
    spawns a board tool and opens a database; the handlers under test read six
    attributes, and every one of them that carries a rule is the real object.
    """
    loop = asyncio.get_event_loop()
    tool = FakeTool()
    events: list[dict] = []

    async def broadcast(message: dict) -> None:
        events.append(message)

    app = SimpleNamespace(
        server=SimpleNamespace(broadcast=broadcast),
        discovery=FakeDiscovery,
        runner=None,
        utility=None,
        debug_runs=DebugRuns(),
        tool=tool,
        events=events,
        _board_bauds={},
        rig_definition=SimpleNamespace(reading=_ReadWriteLock().reading),
    )

    def on_state_change(*args) -> None:  # noqa: ANN002
        # The app's own hook, not an imitation of it: the idle → restore rule
        # and the console-closed → run-dropped rule are both in there.
        Application._handle_state_change(app, *args)

    manager = PortManager(
        loop=loop,
        tool=tool,
        on_state_change=on_state_change,
        on_output=_noop_output,
        on_presence=_noop_presence,
    )
    settings = SidecarSettings.from_payload(
        {
            "defaultBaud": 9600,
            "boxes": [{"box": 1, "hardwareId": HWID}],
        }
    )
    manager.update_settings(settings)
    manager._presence = {HWID: DetectedBoard(hardware_id=HWID, address=ADDRESS, fqbn=FQBN)}

    utility = UtilityBaseline(
        loop=loop,
        ports=manager,
        discovery=FakeDiscovery,
        broadcast=broadcast,
        load_profile=lambda _path: UTILITY_PROFILE,
        is_utility=lambda sketch: sketch.name == "BOX_Utility",
        reading=app.rig_definition.reading,
    )
    utility.update_settings(settings)

    app.settings = settings
    app.utility = utility
    app.ports = manager
    app._require_ports = lambda: manager
    app._require_utility = lambda: utility
    return app


async def flash(app: SimpleNamespace, path: str, **extra) -> dict:  # noqa: ANN003
    return await Application._port_flash(
        app, None, None, {"box": 1, "sketchPath": path, **extra}, "c1"
    )


async def at_baseline(app: SimpleNamespace) -> None:
    app.utility.ensure()
    await settle(app.utility)
    assert app.tool.uploads == [UTILITY_PATH]


# --- the pin ----------------------------------------------------------------


async def test_a_debug_flash_from_idle_is_not_overwritten() -> None:
    """The reported bug, end to end through the real handler and idle hook."""
    app = make_app()
    await at_baseline(app)

    reply = await flash(app, TASK_PATH)
    assert reply == {"state": "IDLE", "resumedPassthrough": False}
    # Let the queued idle hook fire and the worker it starts run dry.
    await asyncio.sleep(0)
    await settle(app.utility)

    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH]
    state = box_state(app.utility)
    assert state["state"] == "pinned"
    assert "GRGL" in state["detail"]


async def test_the_pin_outlasts_every_automatic_trigger() -> None:
    app = make_app()
    await at_baseline(app)
    await flash(app, TASK_PATH)

    # Presence polls and settings pushes call a bare `ensure()`; a console
    # closing fires the idle hook. None of them is the operator asking.
    app.utility.note_presence([HWID])
    app.utility.ensure()
    app.utility.update_settings(app.settings)
    app.utility.ensure()
    app.ports.open_passthrough(1)
    app.ports.close_passthrough(1)
    await asyncio.sleep(0)
    await settle(app.utility)

    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH]
    assert box_state(app.utility)["state"] == "pinned"


async def test_a_session_flash_is_not_pinned() -> None:
    """The session sequence marks itself with `suppressPassthroughResume`; its
    sketches are exactly what the baseline is meant to reclaim afterwards."""
    app = make_app()
    await at_baseline(app)
    app.utility.hold()

    await flash(app, TASK_PATH, suppressPassthroughResume=True)
    await asyncio.sleep(0)
    await settle(app.utility)
    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH]

    app.utility.release()
    app.utility.ensure()
    await settle(app.utility)
    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH, UTILITY_PATH]
    assert box_state(app.utility)["state"] == "ready"


async def test_asking_over_the_wire_releases_the_pin() -> None:
    app = make_app()
    await at_baseline(app)
    await flash(app, TASK_PATH)
    await settle(app.utility)

    await Application._utility_ensure(app, None, None, {"boxes": [1]}, None)
    await settle(app.utility)

    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH, UTILITY_PATH]
    assert box_state(app.utility)["state"] == "ready"


async def test_a_wire_ensure_for_other_boxes_leaves_the_pin() -> None:
    app = make_app()
    await at_baseline(app)
    await flash(app, TASK_PATH)

    await Application._utility_ensure(app, None, None, {"boxes": [2, 3]}, None)
    await settle(app.utility)

    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH]
    assert box_state(app.utility)["state"] == "pinned"


async def test_a_released_pin_waits_for_the_console_to_close() -> None:
    """Return to baseline with the console still open: never take the port,
    but do not forget the request either — the idle hook finishes the job."""
    app = make_app()
    await at_baseline(app)
    await flash(app, TASK_PATH)
    app.ports.open_passthrough(1)

    await Application._utility_ensure(app, None, None, {"boxes": [1]}, None)
    await settle(app.utility)
    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH]
    assert box_state(app.utility)["state"] == "busy"

    app.ports.close_passthrough(1)
    await asyncio.sleep(0)
    await settle(app.utility)
    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH, UTILITY_PATH]


async def test_a_session_releasing_the_rig_clears_the_pin() -> None:
    app = make_app()
    await at_baseline(app)
    await flash(app, TASK_PATH)

    app.utility.hold()
    app.utility.release()
    app.utility.ensure()
    await settle(app.utility)

    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH, UTILITY_PATH]


async def test_a_vanished_board_takes_its_pin_with_it() -> None:
    app = make_app()
    await at_baseline(app)
    await flash(app, TASK_PATH)

    app.utility.note_presence([])  # unplugged
    assert box_state(app.utility)["state"] == "unavailable"
    app.utility.note_presence([HWID])  # a board answers to box 1 again
    app.utility.ensure()
    await settle(app.utility)

    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH, UTILITY_PATH]


async def test_flashing_the_utility_sketch_by_hand_is_a_return_to_baseline() -> None:
    app = make_app()
    await at_baseline(app)
    await flash(app, TASK_PATH)

    await flash(app, UTILITY_PATH)
    await asyncio.sleep(0)
    await settle(app.utility)

    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH, UTILITY_PATH]
    assert box_state(app.utility)["state"] == "ready"


# --- port.sendStart ---------------------------------------------------------


@pytest.fixture
def task_profile_on_disk(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        app_module.task_profile,
        "load_profile",
        lambda path: TASK_PROFILE if path == TASK_PATH else None,
    )


async def send_start(app: SimpleNamespace, **args) -> dict:  # noqa: ANN003
    return await Application._port_send_start(app, None, None, {"box": 1, **args}, None)


async def test_send_start_writes_the_line_a_session_would_build(
    task_profile_on_disk, fake_serial  # noqa: ANN001
) -> None:
    app = make_app()
    app.ports.open_passthrough(1)

    reply = await send_start(app, sketchPath=TASK_PATH, config={"iti": 2500})

    expected = build_start_command(TASK_PROFILE, {"iti": 2500})
    assert expected == "START ITI=2500 RW=40"
    assert reply["command"] == expected
    assert fake_serial.instances[-1].written[-1] == expected
    assert "SEED" not in reply["command"]


async def test_send_start_without_config_uses_the_profile_defaults(
    task_profile_on_disk,  # noqa: ANN001
) -> None:
    app = make_app()
    app.ports.open_passthrough(1)
    reply = await send_start(app, sketchPath=TASK_PATH)
    assert reply["command"] == "START ITI=4000 RW=40"


async def test_send_start_needs_an_open_console(task_profile_on_disk) -> None:  # noqa: ANN001
    app = make_app()
    with pytest.raises(CommandError) as err:
        await send_start(app, sketchPath=TASK_PATH)
    assert err.value.code == ErrCode.SEND_NOT_PASSTHROUGH


async def test_send_start_refuses_an_undiscovered_sketch(task_profile_on_disk) -> None:  # noqa: ANN001
    app = make_app()
    app.ports.open_passthrough(1)
    with pytest.raises(CommandError) as err:
        await send_start(app, sketchPath="/somewhere/else")
    assert err.value.code == ErrCode.SKETCH_UNKNOWN


# --- live metrics for a hand-started task (debug_run.py) --------------------

GRGL_DIR = Path(__file__).resolve().parents[2] / "firmware" / "Olfactory Behavior" / "GRGL"

# Odor 1 rewards the right well (249), odor 3 the left (248) — GRGL's shipped
# profile. Two hits, one miss, one abstention, then the board's own end strobe.
STREAM = [221, 101, 249, 103, 248, 101, 248, 103, 101, 249, 246]


def rx(*codes: int) -> list[OutputLine]:
    return [OutputLine(dir="rx", text=f"{code}\t{1000 + i}", ts=0.0) for i, code in enumerate(codes)]


def telemetry(app: SimpleNamespace) -> list[dict]:
    return [m["data"] for m in app.events if m.get("evt") == Evt.PORT_TELEMETRY]


@pytest.fixture
def grgl_on_disk(monkeypatch: pytest.MonkeyPatch):
    profile = load_profile(str(GRGL_DIR))
    assert profile is not None and profile.live_metrics, "GRGL ships live metrics"
    monkeypatch.setattr(app_module.task_profile, "load_profile", lambda _path: profile)
    return profile


async def started(app: SimpleNamespace) -> None:
    app.ports.open_passthrough(1)
    await send_start(app, sketchPath=TASK_PATH)


async def test_send_start_arms_a_run_and_says_so(grgl_on_disk) -> None:  # noqa: ANN001
    app = make_app()
    await started(app)

    opening = telemetry(app)[-1]
    assert opening["box"] == 1 and opening["running"] is True
    assert [m["value"] for m in opening["metrics"]] == [None] * len(grgl_on_disk.live_metrics)


async def test_a_debug_run_scores_exactly_as_a_session_would(grgl_on_disk) -> None:  # noqa: ANN001
    """The pin that matters: one definition of P(hit), not a bench copy of it."""
    app = make_app()
    await started(app)

    for code in STREAM[:-1]:
        await Application._handle_output(app, 1, rx(code))

    reference = MetricSet(grgl_on_disk)
    for code in STREAM[:-1]:
        reference.offer(code)
    assert telemetry(app)[-1]["metrics"] == [v.to_json() for v in reference.values()]
    assert telemetry(app)[-1]["running"] is True


async def test_one_payload_per_batch_carrying_the_latest_values(grgl_on_disk) -> None:  # noqa: ANN001
    app = make_app()
    await started(app)
    before = len(telemetry(app))

    await Application._handle_output(app, 1, rx(*STREAM[:-1]))

    assert len(telemetry(app)) == before + 1
    by_id = {m["id"]: m for m in telemetry(app)[-1]["metrics"]}
    assert by_id["p_r_odor1"] == {"id": "p_r_odor1", "value": 2 / 3, "n": 3}


async def test_the_boards_end_strobe_ends_the_run(grgl_on_disk) -> None:  # noqa: ANN001
    """End sends STOP; what ENDS the run is the board answering with 246."""
    app = make_app()
    await started(app)
    await Application._handle_output(app, 1, rx(*STREAM))

    assert telemetry(app)[-1]["running"] is False
    assert app.debug_runs.running(1) is False
    # Strobes after the end are not scored into a run that is over.
    count = len(telemetry(app))
    await Application._handle_output(app, 1, rx(101, 249))
    assert len(telemetry(app)) == count


async def test_console_chatter_and_echoes_are_not_strobes(grgl_on_disk) -> None:  # noqa: ANN001
    app = make_app()
    await started(app)
    before = len(telemetry(app))

    await Application._handle_output(
        app,
        1,
        [
            OutputLine(dir="rx", text="READY", ts=0.0),
            OutputLine(dir="tx", text="101\t5", ts=0.0),  # our own echo, not the board
            OutputLine(dir="rx", text="STATUS mode=idle", ts=0.0),
        ],
    )
    assert len(telemetry(app)) == before


async def test_closing_the_console_ends_the_run(grgl_on_disk) -> None:  # noqa: ANN001
    app = make_app()
    await started(app)

    app.ports.close_passthrough(1)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert app.debug_runs.running(1) is False
    assert telemetry(app)[-1]["running"] is False


async def test_nothing_is_scored_until_a_run_is_armed(grgl_on_disk) -> None:  # noqa: ANN001
    """A START typed by hand runs the task; there is no profile to score it by."""
    app = make_app()
    app.ports.open_passthrough(1)
    await Application._handle_output(app, 1, rx(*STREAM))
    assert telemetry(app) == []


async def test_a_profile_less_sketch_still_reports_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module.task_profile, "load_profile", lambda _path: None)
    app = make_app()
    await started(app)
    assert telemetry(app)[-1] == {"box": 1, "running": True, "metrics": []}

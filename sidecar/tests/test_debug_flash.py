"""A Debug Mode flash must survive, and must be startable.

The regression this file exists for: flashing a task from an `IDLE` port lands
the port back in `IDLE`, and the app's idle hook answers every `IDLE` transition
by asking the utility baseline for a restore. So the baseline re-flashed its
own sketch over the operator's within seconds, silently, and the box could not
be started or talked to.

`test_utility.py` could not see it, because its harness wires the port manager
with a no-op `on_state_change` — the hook that did the damage was never in the
loop. The harness here hands the port manager the app's REAL
`_handle_state_change`, and drives a Debug flash through the real
`flash.enqueue` handler and flash queue over it, so the order of "note what was
flashed" and "the idle hook fires" is the order production has.

The second half covers what makes a flashed task usable from the console:
`port.sendStart`, and the live scoring it arms (`debug_run.py`).
"""

from __future__ import annotations

import asyncio
import functools
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ephymeris_sidecar import app as app_module
from ephymeris_sidecar.app import Application
from ephymeris_sidecar.rig.definition import RigDefinition
from ephymeris_sidecar.debug_run import DebugRuns
from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.ports import manager as manager_module
from ephymeris_sidecar.ports.flashing import FlashJob, FlashQueue
from ephymeris_sidecar.ports.handler import OutputLine
from ephymeris_sidecar.ports.manager import FQBN, PortManager
from ephymeris_sidecar.protocol import Cmd, ErrCode, Evt
from ephymeris_sidecar.server import SidecarServer
from ephymeris_sidecar.settings import SidecarSettings
from ephymeris_sidecar.analytics.stream.legacy import MetricSet
from ephymeris_sidecar.tasks.profile import load_profile, parse_profile
from ephymeris_sidecar.tasks.start_command import build_start_command
from ephymeris_sidecar.utility import UtilityBaseline
from ephymeris_sidecar.wire_errors import ERRORS
from tests.live_sidecar import Refused, live_sidecar, settings
from tests.wire import dispatch

from .test_utility import (  # noqa: F401 - fake_serial is an autouse fixture
    ADDRESS,
    HWID,
    TASK_PATH,
    UTILITY_PATH,
    UTILITY_PROFILE,
    FakeDiscovery,
    FakeSerial,
    FakeTool,
    _noop_output,
    _noop_presence,
    box_state,
    fake_serial,
    rig_definition,
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


class ParamsSerial(FakeSerial):
    """`FakeSerial`, and a firmware that speaks `SET`: every key is one it parses,
    unless a test says otherwise, and the answer is the running `PARAMS`."""

    known: set[str] | None = None  # None: every key is one it parses
    clamps: set[str] = set()
    cap = 127
    silent = False

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self._tokens: list[str] = []

    def write(self, data: bytes) -> int:
        line = data.decode().strip()
        written = super().write(data)
        if line == "BEGIN":
            self._tokens = []
        if ParamsSerial.silent or not (line == "SET" or line.startswith("SET ")):
            return written
        for token in line[: ParamsSerial.cap].split()[1:]:
            key, eq, _ = token.partition("=")
            if eq and (ParamsSerial.known is None or key in ParamsSerial.known):
                self._tokens.append(token)
        moved = [t.partition("=")[0] for t in self._tokens if t.partition("=")[0] in ParamsSerial.clamps]
        crc = zlib.crc32(" ".join(self._tokens).encode())
        answer = "".join(f"CLAMPED {key}\n" for key in moved) + f"PARAMS {len(self._tokens)} {crc}\n"
        self._pending.extend(answer.encode())
        return written


@pytest.fixture(autouse=True)
def params_serial(monkeypatch: pytest.MonkeyPatch, fake_serial):  # noqa: ANN001, F811
    monkeypatch.setattr(ParamsSerial, "known", None)
    monkeypatch.setattr(ParamsSerial, "clamps", set())
    monkeypatch.setattr(ParamsSerial, "cap", 127)
    monkeypatch.setattr(ParamsSerial, "silent", False)
    monkeypatch.setattr(handler_module.serial, "Serial", ParamsSerial)
    monkeypatch.setattr(manager_module.serial, "Serial", ParamsSerial)
    monkeypatch.setattr(handler_module, "SESSION_PARAMS_TIMEOUT_S", 0.5)
    return ParamsSerial


async def make_app(rig_definition: RigDefinition) -> SimpleNamespace:
    """The slice of `Application` the port handlers touch, over real parts.

    A stand-in rather than the real class because constructing `Application`
    spawns a board tool and opens a database; the handlers under test read six
    attributes, and every one of them that carries a rule is the real object.
    The commands go through a real `SidecarServer` -- argument checks, the
    error table -- by `tests/wire.py`'s `dispatch`.
    """
    loop = asyncio.get_event_loop()
    tool = FakeTool()
    events: list[dict] = []

    async def broadcast(message: dict) -> None:
        events.append(message)

    server = SidecarServer("127.0.0.1", 0, "unused")
    server.broadcast = broadcast  # type: ignore[method-assign]
    server.map_errors(ERRORS)
    app = SimpleNamespace(
        server=server,
        sketches=SimpleNamespace(
            current=FakeDiscovery,
            find=lambda path: next((s for s in FakeDiscovery.sketches if s.path == path), None),
        ),
        runner=None,
        utility=None,
        flashes=None,
        debug_runs=DebugRuns(),
        tool=tool,
        events=events,
        _board_bauds={},
        rig_definition=rig_definition,
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
    await manager.poll_once()

    flashes = FlashQueue(
        loop=loop,
        ports=manager,
        discovery=FakeDiscovery,
        broadcast=broadcast,
        reading=app.rig_definition.reading,
        on_flashed=lambda *args: Application._on_flashed(app, *args),
    )
    utility = UtilityBaseline(
        loop=loop,
        ports=manager,
        discovery=FakeDiscovery,
        broadcast=broadcast,
        load_profile=lambda _path: UTILITY_PROFILE,
        is_utility=lambda sketch: sketch.name == "BOX_Utility",
        flashes=flashes,
    )
    utility.update_settings(settings)
    utility.flash_queue = flashes  # what `settle` waits on

    app.settings = settings
    app.flashes = flashes
    app.utility = utility
    app.ports = manager
    app._require_ports = lambda: manager
    app._require_utility = lambda: utility
    app._require_flashes = lambda: flashes
    for cmd, handler in {
        Cmd.FLASH_ENQUEUE: Application._flash_enqueue,
        Cmd.UTILITY_ENSURE: Application._utility_ensure,
        Cmd.PORT_SEND_START: Application._port_send_start,
        Cmd.PORT_PASSTHROUGH_CLOSE: Application._passthrough_close,
        Cmd.PORT_ERROR_ACK: Application._port_error_ack,
    }.items():
        server.register(cmd, functools.partial(handler, app))
    return app


async def flash(app: SimpleNamespace, path: str, **extra) -> None:  # noqa: ANN003
    """A Debug Mode flash of box 1, as the dialog asks for it, run to the end."""
    await dispatch(app, "flash.enqueue", boxes=[1], sketchPath=path, **extra)
    await settle(app.utility)


async def at_baseline(app: SimpleNamespace) -> None:
    app.utility.ensure()
    await settle(app.utility)
    assert app.tool.uploads == [UTILITY_PATH]


# --- the pin ----------------------------------------------------------------


async def test_the_pin_outlasts_every_automatic_trigger(rig_definition) -> None:
    app = await make_app(rig_definition)
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


async def test_a_session_flash_is_not_pinned(rig_definition) -> None:
    """A session flash is its own origin; its sketches are exactly what the
    baseline is meant to reclaim afterwards."""
    app = await make_app(rig_definition)
    await at_baseline(app)
    app.utility.hold()

    app.flashes.submit(
        [FlashJob(box=1, origin="session", prepare=lambda: TASK_PATH, sketch_path=TASK_PATH)]
    )
    await settle(app.utility)
    await asyncio.sleep(0)
    await settle(app.utility)
    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH]

    app.utility.release()
    app.utility.ensure()
    await settle(app.utility)
    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH, UTILITY_PATH]
    assert box_state(app.utility)["state"] == "ready"


async def test_asking_over_the_wire_releases_the_pin(rig_definition) -> None:
    app = await make_app(rig_definition)
    await at_baseline(app)
    await flash(app, TASK_PATH)
    await settle(app.utility)

    await dispatch(app, "utility.ensure", boxes=[1])
    await settle(app.utility)

    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH, UTILITY_PATH]
    assert box_state(app.utility)["state"] == "ready"


async def test_a_wire_ensure_for_other_boxes_leaves_the_pin(rig_definition) -> None:
    app = await make_app(rig_definition)
    await at_baseline(app)
    await flash(app, TASK_PATH)

    await dispatch(app, "utility.ensure", boxes=[2, 3])
    await settle(app.utility)

    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH]
    assert box_state(app.utility)["state"] == "pinned"


async def test_a_released_pin_waits_for_the_console_to_close(rig_definition) -> None:
    """Return to baseline with the console still open: never take the port,
    but do not forget the request either — the idle hook finishes the job."""
    app = await make_app(rig_definition)
    await at_baseline(app)
    await flash(app, TASK_PATH)
    app.ports.open_passthrough(1)

    await dispatch(app, "utility.ensure", boxes=[1])
    await settle(app.utility)
    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH]
    assert box_state(app.utility)["state"] == "busy"

    app.ports.close_passthrough(1)
    await asyncio.sleep(0)
    await settle(app.utility)
    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH, UTILITY_PATH]


async def test_a_session_releasing_the_rig_clears_the_pin(rig_definition) -> None:
    app = await make_app(rig_definition)
    await at_baseline(app)
    await flash(app, TASK_PATH)

    app.utility.hold()
    app.utility.release()
    app.utility.ensure()
    await settle(app.utility)

    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH, UTILITY_PATH]


async def test_a_vanished_board_takes_its_pin_with_it(rig_definition) -> None:
    app = await make_app(rig_definition)
    await at_baseline(app)
    await flash(app, TASK_PATH)

    app.utility.note_presence([])  # unplugged
    assert box_state(app.utility)["state"] == "unavailable"
    app.utility.note_presence([HWID])  # a board answers to box 1 again
    app.utility.ensure()
    await settle(app.utility)

    assert app.tool.uploads == [UTILITY_PATH, TASK_PATH, UTILITY_PATH]


async def test_flashing_the_utility_sketch_by_hand_is_a_return_to_baseline(rig_definition) -> None:
    app = await make_app(rig_definition)
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
    return await dispatch(app, "port.sendStart", box=1, **args)


async def test_send_start_sends_the_set_lines_a_session_would_build_then_a_bare_start(
    rig_definition, task_profile_on_disk, params_serial,  # noqa: ANN001
) -> None:
    app = await make_app(rig_definition)
    app.ports.open_passthrough(1)

    reply = await send_start(app, sketchPath=TASK_PATH, config={"iti": 2500})

    expected = build_start_command(TASK_PROFILE, {"iti": 2500})
    assert expected.set_lines == ("SET ITI=2500 RW=40",)
    assert params_serial.instances[-1].written[-3:] == ["BEGIN", *expected.set_lines, "START"]
    assert reply["command"] == "START"
    assert "SEED" not in reply["command"]


async def test_a_refused_send_start_can_be_corrected_and_sent_again_on_the_same_console(
    rig_definition, task_profile_on_disk, params_serial,  # noqa: ANN001
) -> None:
    """The board is still in its start loop after a refusal. Its second PARAMS
    must count the second block alone, or every retry is refused as a count
    mismatch and told to reflash a board that needs nothing."""
    app = await make_app(rig_definition)
    app.ports.open_passthrough(1)

    params_serial.clamps = {"RW"}
    with pytest.raises(Refused) as err:
        await send_start(app, sketchPath=TASK_PATH)
    assert err.value.code == ErrCode.PARAMS_CLAMPED

    params_serial.clamps = set()
    reply = await send_start(app, sketchPath=TASK_PATH)

    assert reply["command"] == "START"
    written = params_serial.instances[-1].written
    assert written.count("BEGIN") == 2
    assert written[-3:] == ["BEGIN", "SET ITI=4000 RW=40", "START"]


async def test_send_start_refuses_a_block_the_board_does_not_confirm(
    rig_definition, task_profile_on_disk, params_serial,  # noqa: ANN001
) -> None:
    """The same checks as a session's start, with nothing started: a key the
    board does not parse, a value it clamps, a line cut short, a silent sketch."""
    cases = [
        ({"known": {"ITI"}}, ErrCode.PARAMS_MISMATCH, "count"),
        ({"clamps": {"RW"}}, ErrCode.PARAMS_CLAMPED, "clamped"),
        ({"cap": 14}, ErrCode.PARAMS_MISMATCH, "count"),
        ({"cap": 17}, ErrCode.PARAMS_MISMATCH, "crc"),
        ({"silent": True}, ErrCode.FIRMWARE_OUTDATED, "no_reply"),
    ]
    for board, code, reason in cases:
        for name, value in board.items():
            setattr(params_serial, name, value)
        app = await make_app(rig_definition)
        app.ports.open_passthrough(1)
        with pytest.raises(Refused) as err:
            await send_start(app, sketchPath=TASK_PATH)
        assert err.value.code == code, board
        assert err.value.detail["reason"] == reason, board
        assert err.value.detail["box"] == 1
        assert "START" not in params_serial.instances[-1].written, board
        assert app.debug_runs.running(1) is False
        app.ports.close_passthrough(1)
        for name in board:
            setattr(params_serial, name, {"known": None, "clamps": set(), "cap": 127, "silent": False}[name])


async def test_send_start_without_config_uses_the_profile_defaults(
    rig_definition, task_profile_on_disk, params_serial,  # noqa: ANN001
) -> None:
    app = await make_app(rig_definition)
    app.ports.open_passthrough(1)
    await send_start(app, sketchPath=TASK_PATH)
    assert params_serial.instances[-1].written[-3:] == ["BEGIN", "SET ITI=4000 RW=40", "START"]


async def test_send_start_needs_an_open_console(rig_definition, task_profile_on_disk) -> None:  # noqa: ANN001
    app = await make_app(rig_definition)
    with pytest.raises(Refused) as err:
        await send_start(app, sketchPath=TASK_PATH)
    assert err.value.code == ErrCode.SEND_NOT_PASSTHROUGH


async def test_a_debug_flash_is_refused_while_the_wiring_is_unloaded(rig_definition, monkeypatch) -> None:  # noqa: ANN001
    """A Debug flash of BOX_Utility built on the shipped pins drives every
    listed output (`ARCHITECTURE.md#unloaded-wiring-holds-it`)."""
    app = await make_app(rig_definition)
    monkeypatch.setattr(
        app.rig_definition, "wiring_problem", lambda: "wiring.json did not load: it will not parse."
    )
    with pytest.raises(Refused) as err:
        await flash(app, UTILITY_PATH)
    assert err.value.code == ErrCode.RIG_WIRING_UNLOADED
    assert app.tool.uploads == []


async def test_send_start_refuses_an_undiscovered_sketch(rig_definition, task_profile_on_disk) -> None:  # noqa: ANN001
    app = await make_app(rig_definition)
    app.ports.open_passthrough(1)
    with pytest.raises(Refused) as err:
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


async def test_send_start_arms_a_run_and_says_so(rig_definition, grgl_on_disk) -> None:  # noqa: ANN001
    app = await make_app(rig_definition)
    await started(app)

    opening = telemetry(app)[-1]
    assert opening["box"] == 1 and opening["running"] is True
    assert [m["value"] for m in opening["metrics"]] == [None] * len(grgl_on_disk.live_metrics)


async def test_a_debug_run_scores_exactly_as_a_session_would(rig_definition, grgl_on_disk) -> None:  # noqa: ANN001
    """The pin that matters: one definition of P(hit), not a bench copy of it."""
    app = await make_app(rig_definition)
    await started(app)

    for code in STREAM[:-1]:
        await Application._handle_output(app, 1, rx(code))

    reference = MetricSet(grgl_on_disk)
    for code in STREAM[:-1]:
        reference.offer(code)
    assert telemetry(app)[-1]["metrics"] == [v.to_json() for v in reference.values()]
    assert telemetry(app)[-1]["running"] is True


async def test_one_payload_per_batch_carrying_the_latest_values(rig_definition, grgl_on_disk) -> None:  # noqa: ANN001
    app = await make_app(rig_definition)
    await started(app)
    before = len(telemetry(app))

    await Application._handle_output(app, 1, rx(*STREAM[:-1]))

    assert len(telemetry(app)) == before + 1
    by_id = {m["id"]: m for m in telemetry(app)[-1]["metrics"]}
    assert by_id["p_r_odor1"] == {"id": "p_r_odor1", "value": 2 / 3, "n": 3}


async def test_the_boards_end_strobe_ends_the_run(rig_definition, grgl_on_disk) -> None:  # noqa: ANN001
    """End sends STOP; what ENDS the run is the board answering with 246."""
    app = await make_app(rig_definition)
    await started(app)
    await Application._handle_output(app, 1, rx(*STREAM))

    assert telemetry(app)[-1]["running"] is False
    assert app.debug_runs.running(1) is False
    # Strobes after the end are not scored into a run that is over.
    count = len(telemetry(app))
    await Application._handle_output(app, 1, rx(101, 249))
    assert len(telemetry(app)) == count


async def test_console_chatter_and_echoes_are_not_strobes(rig_definition, grgl_on_disk) -> None:  # noqa: ANN001
    app = await make_app(rig_definition)
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


async def test_closing_the_console_ends_the_run(rig_definition, grgl_on_disk) -> None:  # noqa: ANN001
    app = await make_app(rig_definition)
    await started(app)

    app.ports.close_passthrough(1)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert app.debug_runs.running(1) is False
    assert telemetry(app)[-1]["running"] is False


async def test_nothing_is_scored_until_a_run_is_armed(rig_definition, grgl_on_disk) -> None:  # noqa: ANN001
    """A START typed by hand runs the task; there is no profile to score it by."""
    app = await make_app(rig_definition)
    app.ports.open_passthrough(1)
    await Application._handle_output(app, 1, rx(*STREAM))
    assert telemetry(app) == []


async def test_a_profile_less_sketch_still_reports_running(rig_definition, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module.task_profile, "load_profile", lambda _path: None)
    app = await make_app(rig_definition)
    await started(app)
    assert telemetry(app)[-1] == {"box": 1, "running": True, "metrics": []}


# --- over the wire ------------------------------------------------------------


async def test_a_debug_flash_from_idle_is_not_overwritten(tmp_path: Path) -> None:
    """The reported bug through the whole sidecar: the real discovery, profiles,
    idle hook and baseline, with only the board and its serial port faked. The
    stand-in harness above wires the hooks itself, so it cannot see
    `Application.start` wiring one wrong; this test can."""
    tool = FakeTool()
    async with live_sidecar(tmp_path / "app", tool=tool) as sidecar:
        await sidecar.call("settings.push", settings=settings(bound={1: HWID}))
        sketches = (await sidecar.call("sketches.refresh"))["sketches"]
        utility = next(s["path"] for s in sketches if s["name"] == "BOX_Utility")
        grgl = next(s["path"] for s in sketches if s["name"] == "GRGL")

        def box_1() -> dict:
            status = sidecar.latest("utility.updated") or {"boxes": []}
            return next((b for b in status["boxes"] if b["box"] == 1), {})

        await sidecar.until(lambda: box_1().get("state") == "ready")
        assert tool.uploads == [utility]

        await sidecar.call("flash.enqueue", boxes=[1], sketchPath=grgl)
        await sidecar.until(lambda: box_1().get("state") == "pinned")

        assert tool.uploads == [utility, grgl]
        assert "GRGL" in box_1()["detail"]

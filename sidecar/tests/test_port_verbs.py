"""A port verb leaves only the states it names (`ARCHITECTURE.md#port-verbs`).

`TRANSITIONS` is the superset of every legal move, and cannot say who is
asking. These drive the app's real handlers, its real idle hook and the real
flash queue over a real `PortManager`, because each failure here was a legal
transition asked for by the wrong caller:

* a console close that arrives mid-flash, from a UI that last saw the console
  open, freed the port during the upload;
* the same close from `ERROR` cleared the fault without the acknowledgement,
  and the idle hook then queued a baseline restore onto the faulted box;
* a baseline restore that met a console took it, which only the restore's
  own `prepare` running with no `await` before the take had prevented.
"""

from __future__ import annotations

import asyncio

import pytest

from ephymeris_sidecar.app import Application
from ephymeris_sidecar.boards.tool import FlashFailed
from ephymeris_sidecar.ports.states import PortState
from ephymeris_sidecar.protocol import ErrCode
from ephymeris_sidecar.server import CommandError

from .test_debug_flash import flash, make_app
from .test_flash_queue import Rig, rig  # noqa: F401 - rig is a fixture
from .test_utility import (  # noqa: F401 - fake_serial is an autouse fixture
    TASK_PATH,
    UTILITY_PATH,
    FakeSerial,
    box_state,
    fake_serial,
    make_baseline,
    rig_definition,
    settle,
)


async def close_console(app) -> None:  # noqa: ANN001
    """`port.passthrough.close` for box 1, as the frontend sends it."""
    await Application._passthrough_close(app, None, None, {"box": 1}, None)


async def until(condition, what: str) -> None:  # noqa: ANN001
    for _ in range(300):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"never saw {what}")


# --- B6: a console close mid-flash or from ERROR -----------------------------


async def test_a_console_close_is_refused_mid_flash(rig_definition) -> None:
    app = await make_app(rig_definition)
    gate = asyncio.Event()
    upload = app.tool.upload

    async def held_upload(*args) -> None:  # noqa: ANN002
        await gate.wait()
        await upload(*args)

    app.tool.upload = held_upload
    app.ports.open_passthrough(1)
    await Application._flash_enqueue(
        app, None, None, {"boxes": [1], "sketchPath": TASK_PATH}, None
    )
    await until(lambda: app.ports.handler(1).state is PortState.FLASHING, "the flash take the port")

    # The console the UI last saw open, closed while the upload holds the port.
    with pytest.raises(CommandError) as refused:
        await close_console(app)

    assert refused.value.code == ErrCode.ILLEGAL_TRANSITION
    assert app.ports.handler(1).state is PortState.FLASHING
    gate.set()
    await settle(app.utility)
    # The flash finished and gave the console back, as a Debug flash does.
    assert app.tool.uploads == [TASK_PATH]
    assert app.ports.handler(1).state is PortState.PASSTHROUGH


async def test_a_console_close_cannot_clear_an_error(rig_definition) -> None:
    app = await make_app(rig_definition)
    app.tool.fail = FlashFailed("compile", "compile failed")
    await flash(app, TASK_PATH)
    assert app.ports.handler(1).state is PortState.ERROR
    app.tool.fail = None

    with pytest.raises(CommandError) as refused:
        await close_console(app)
    await asyncio.sleep(0)  # the idle hook, had the port fallen idle
    await settle(app.utility)

    assert refused.value.code == ErrCode.ILLEGAL_TRANSITION
    assert app.ports.handler(1).state is PortState.ERROR
    # No restore was queued onto a box nobody has acknowledged.
    assert app.tool.uploads == []

    # The acknowledgement is the way out, and it is what frees the box for one.
    await Application._port_error_ack(app, None, None, {"box": 1}, None)
    await asyncio.sleep(0)
    await settle(app.utility)
    assert app.tool.uploads == [UTILITY_PATH]


# --- candidate 2: a restore takes only an idle port, by the verb ------------


async def test_a_baseline_flash_never_takes_a_console(rig: Rig) -> None:
    """Whatever the job's `prepare` decided: a baseline job's flash asks the
    port for `IDLE` only, so a console open at the take is refused there."""
    rig.ports.open_passthrough(1)
    console = FakeSerial.instances[-1]

    rig.queue.submit([rig.job(1, "baseline", UTILITY_PATH)])
    await rig.settle()

    assert rig.ports.handler(1).state is PortState.PASSTHROUGH
    assert not console.closed
    assert rig.uploaded() == []
    assert rig.flashed == []
    # A refused take is not a failed flash: the row goes, as a restore that
    # decided not to flash does.
    assert rig.row(1) is None


async def test_a_restore_that_meets_a_console_at_the_take_leaves_the_box_busy() -> None:
    """The baseline's "only an IDLE port" no longer rests on nothing yielding
    between its decision and the take: here a console opens in between."""
    baseline, manager, tool, _ = await make_baseline()
    queue = baseline.flash_queue
    submit = queue.submit

    def console_opens_after_the_decision(jobs) -> None:  # noqa: ANN001
        jobs = list(jobs)
        for job in jobs:
            decide = job.prepare

            def prepare(decide=decide):  # noqa: ANN001, ANN202
                path = decide()
                manager.open_passthrough(1)
                return path

            job.prepare = prepare
        submit(jobs)

    queue.submit = console_opens_after_the_decision
    baseline.ensure([1])
    await settle(baseline)

    assert manager.handler(1).state is PortState.PASSTHROUGH
    assert tool.uploads == []
    assert box_state(baseline)["state"] == "busy"

    # Busy, not failed: once the console closes, the next restore runs.
    queue.submit = submit
    manager.close_passthrough(1)
    baseline.ensure([1])
    await settle(baseline)
    assert tool.uploads == [UTILITY_PATH]
    assert box_state(baseline)["state"] == "ready"

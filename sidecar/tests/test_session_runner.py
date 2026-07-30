"""Session runner integration — strobes → `.tsv` + metrics + telemetry.

Ties `dashboard.md` §10 step 7 to `data.md` §5: each parsed
strobe must land durably in the write-ahead log *and* update the rolling live
metric pushed to the frontend.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ephymeris_sidecar.sessions.runner import CLEAN_STOP_REASON, BoxConfig, SessionRunner
from ephymeris_sidecar.tasks.profile import parse_profile

GRGL = {
    "taskName": "GRGL 2-Odor Discrimination",
    "config": [
        {"metadataKey": "correction_left", "wireKey": "CL", "label": "L", "type": "int", "default": 0},
        {"metadataKey": "lazy_escalation", "wireKey": "LAZY", "label": "Lazy", "type": "bool", "default": True},
    ],
    "strobes": {"101": "ODOR_1_ON", "248": "WATER_POKE_L", "249": "WATER_POKE_R", "246": "END_SESSION"},
    "liveMetrics": [
        {"id": "p_r_odor1", "label": "P(R | Odor 1)", "triggerCode": 101,
         "successCode": 249, "alternateCode": 248, "windowSize": 20}
    ],
}


class FakePorts:
    """Stands in for PortManager: records calls, exposes the callbacks."""

    def __init__(self) -> None:
        self.started: list[tuple] = []
        self.stopped: list[int] = []
        self.ended: list[tuple] = []
        self.on_ready = None
        self.on_strobe = None

    def resolve_address(self, box: int) -> str:
        return f"/dev/fake{box}"

    def start_session(self, box, start_command, on_ready, on_strobe):
        self.started.append((box, start_command))
        self.on_ready = on_ready
        self.on_strobe = on_strobe

    def stop_session(self, box: int) -> None:
        self.stopped.append(box)

    def end_session(self, box: int, reason: str) -> None:
        self.ended.append((box, reason))


async def wait_until(predicate, *, timeout: float = 5.0) -> None:
    """Yield to the loop until `predicate()` holds.

    Finalization is scheduled on the loop and does its file I/O in a worker
    thread, so how long it takes depends on machine load rather than on
    anything the test controls. A fixed number of short sleeps therefore
    passes alone and fails under a full suite — wait on the condition, with a
    generous ceiling that only trips on a genuine hang.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("timed out waiting for the runner to settle")
        await asyncio.sleep(0.005)


def make_runner(tmp_path: Path, profile_json=GRGL, duration_s=None):
    events: list[dict] = []
    ended: list[tuple] = []

    async def broadcast(message):
        events.append(message)

    async def on_animal_ended(run, reason):
        ended.append((run, reason))

    ports = FakePorts()
    runner = SessionRunner(
        loop=asyncio.get_event_loop(),
        ports=ports,
        broadcast=broadcast,
        on_animal_ended=on_animal_ended,
    )
    profile = parse_profile(profile_json) if profile_json else None
    runner.configure(
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
                start_command="START CL=0 LAZY=1",
                config_metadata={"correction_left": 0, "lazy_escalation": True},
                profile=profile,
            )
        ],
        duration_s=duration_s,
    )
    return runner, ports, events, ended


async def test_a_run_writes_its_tsv_with_the_seed_captured(tmp_path: Path) -> None:
    runner, ports, _events, _ended = make_runner(tmp_path)
    runner.start_box(1)
    box, command = ports.started[0]
    assert box == 1
    assert command.startswith("START CL=0 LAZY=1 SEED=")

    ports.on_ready(288577176)  # SEED arrived
    ports.on_strobe(101, 0)
    ports.on_strobe(249, 500)

    tsv = next((tmp_path / "behavior.tsv").glob("*.tsv"))
    text = tsv.read_text()
    # §5 core fields + flat config + the recognized trial_seed convention (§6.4)
    assert "# rat: remy1" in text
    assert "# serial_port: /dev/fake1" in text
    assert "# session_id: 2O-Bdisc_25" in text
    assert "# sketch: GRGL_2-Odor" in text
    assert "# trial_seed: 288577176" in text
    # Strobes in the board's exact format
    assert "101\t0" in text
    assert "249\t500" in text


async def test_each_start_draws_its_own_seed(tmp_path: Path) -> None:
    """Stop → Start on the same box must not replay the same trial sequence.

    The seed is drawn on the click and not with the mapping, precisely so that
    a box restarted after a false start gets a fresh stream rather than the one
    the animal already ran through.
    """
    runner, ports, _events, _ended = make_runner(tmp_path)
    runner.start_box(1)
    ports.on_ready(None)
    ports.on_strobe(246, 10)
    await wait_until(lambda: not runner.running_boxes())

    runner.start_box(1)
    first, second = (command for _box, command in ports.started)
    assert first != second


async def test_both_seeds_are_recorded_when_the_board_disagrees(tmp_path: Path) -> None:
    """Firmware predating the `SEED=` convention seeds itself and echoes its own
    number. Recording only one of the two would leave the file claiming a seed
    that never reached the RNG — or hiding that the host asked for a better one."""
    runner, ports, _events, _ended = make_runner(tmp_path)
    runner.start_box(1)
    sent = int(ports.started[0][1].rsplit("SEED=", 1)[1])

    ports.on_ready(4242)  # an old sketch's own micros()-derived value
    ports.on_strobe(101, 0)

    text = next((tmp_path / "behavior.tsv").glob("*.tsv")).read_text()
    assert "# trial_seed: 4242" in text, "what the board actually ran on"
    assert f"# host_seed: {sent}" in text, "what this app asked for"


async def test_strobes_push_rolling_telemetry(tmp_path: Path) -> None:
    runner, ports, events, _ended = make_runner(tmp_path)
    runner.start_box(1)
    ports.on_ready(None)

    ports.on_strobe(101, 0)  # trigger — no counted trial yet
    ports.on_strobe(249, 100)  # went right → hit
    await asyncio.sleep(0)  # let the scheduled telemetry coroutines run
    await asyncio.sleep(0)

    telemetry = [e for e in events if e.get("evt") == "session.telemetry"]
    assert telemetry, "expected a session.telemetry push"
    last = telemetry[-1]["data"]
    assert last["box"] == 1
    assert last["animalId"] == "a1"
    metric = last["metrics"][0]
    assert metric["id"] == "p_r_odor1"
    assert metric["value"] == 1.0
    assert metric["n"] == 1


async def test_the_end_code_finalizes_the_run_cleanly(tmp_path: Path) -> None:
    runner, ports, _events, ended = make_runner(tmp_path)
    runner.start_box(1)
    ports.on_ready(None)
    ports.on_strobe(101, 0)
    ports.on_strobe(249, 100)
    ports.on_strobe(246, 3523555)  # END_SESSION per the profile's strobes map

    # The finalize is scheduled on the loop; let it run.
    await wait_until(lambda: bool(ended))

    assert ended, "expected the run to finalize"
    _run, reason = ended[-1]
    assert reason == CLEAN_STOP_REASON
    assert ports.ended == [(1, CLEAN_STOP_REASON)]

    # §7.2 — .json and .mat built once at the end, from the same in-memory list.
    doc = json.loads(next((tmp_path / "behavior.json").glob("*.json")).read_text())
    assert doc["rat"] == "remy1"
    assert doc["stop_reason"] == CLEAN_STOP_REASON
    assert doc["n_events"] == 3
    assert doc["ts_data"] == [[101, 0], [249, 100], [246, 3523555]]
    assert next((tmp_path / "behavior.mat").glob("*.mat")).is_file()


async def test_the_time_limit_sends_stop_and_the_board_ends_the_run(tmp_path: Path) -> None:
    """§2.3 — at the deadline the runner sends the same STOP an operator
    would; the board's own end strobe still does the ending."""
    runner, ports, _events, ended = make_runner(tmp_path, duration_s=0.05)
    runner.start_box(1)
    ports.on_ready(None)
    ports.on_strobe(101, 0)

    # The deadline fires on the loop and only sends STOP — nothing finalizes yet.
    await wait_until(lambda: ports.stopped == [1])
    assert not ended, "STOP alone must not finalize; the trial boundary does"

    # The board honours STOP at its trial boundary and emits its end strobe.
    ports.on_strobe(246, 3000)
    await wait_until(lambda: bool(ended))
    _run, reason = ended[-1]
    assert reason == CLEAN_STOP_REASON


async def test_an_early_end_cancels_the_deadline(tmp_path: Path) -> None:
    """A box that finished before its time limit must never get a ghost STOP —
    by then the port is free and could belong to something else."""
    # The limit is far enough out that no scheduling delay can let it fire
    # during the test: what's asserted below is the timer's *cancelled* state,
    # not that we outran it. Racing a 0.08 s deadline against a 0.15 s wall
    # sleep failed whenever the loop stalled — a stalled loop is exactly when
    # `call_later` fires late, so the old form tested machine load, not this.
    runner, ports, _events, ended = make_runner(tmp_path, duration_s=3600.0)
    runner.start_box(1)
    deadline = runner._active[1].deadline
    assert deadline is not None and not deadline.cancelled(), "box 1 armed no deadline"

    ports.on_ready(None)
    ports.on_strobe(246, 100)  # clean end well before the deadline

    await wait_until(lambda: bool(ended))
    # The handle finalization cancelled is the one this box was armed with, and
    # asyncio never runs a cancelled handle's callback — so `_on_deadline` can
    # no longer reach a port that by now could belong to something else.
    assert deadline.cancelled(), "the early end left the deadline armed"
    assert ports.stopped == [], "the cancelled deadline still sent STOP"


async def test_snapshot_carries_started_at_only_while_running(tmp_path: Path) -> None:
    runner, ports, _events, ended = make_runner(tmp_path)
    assert runner.snapshot()[0]["startedAt"] is None

    runner.start_box(1)
    ports.on_ready(None)
    assert runner.snapshot()[0]["startedAt"] is not None

    ports.on_strobe(246, 100)
    await wait_until(lambda: bool(ended))
    assert runner.snapshot()[0]["startedAt"] is None


async def test_a_board_drop_finalizes_with_whatever_was_captured(tmp_path: Path) -> None:
    """§10 — the hard stop costs no data; the WAL already has it."""
    runner, ports, _events, ended = make_runner(tmp_path)
    runner.start_box(1)
    ports.on_ready(None)
    ports.on_strobe(101, 0)
    ports.on_strobe(249, 100)

    runner.board_dropped(1)
    await wait_until(lambda: bool(ended))

    assert ended
    _run, reason = ended[-1]
    assert reason == "board disconnected"
    # Not a clean end, so the port isn't transitioned here — it's already ERROR.
    assert ports.ended == []

    doc = json.loads(next((tmp_path / "behavior.json").glob("*.json")).read_text())
    assert doc["stop_reason"] == "board disconnected"
    assert doc["ts_data"] == [[101, 0], [249, 100]]


async def test_stop_sends_stop_without_ending_the_run(tmp_path: Path) -> None:
    runner, ports, _events, ended = make_runner(tmp_path)
    runner.start_box(1)
    ports.on_ready(None)

    runner.stop_box(1)
    assert ports.stopped == [1]
    # The board's own end strobe ends it, not the STOP itself (§5.3).
    assert ended == []


async def test_a_profile_less_sketch_still_writes_but_pushes_no_metrics(
    tmp_path: Path,
) -> None:
    runner, ports, events, _ended = make_runner(tmp_path, profile_json=None)
    runner.start_box(1)
    ports.on_ready(None)
    ports.on_strobe(101, 0)
    await asyncio.sleep(0)

    tsv = next((tmp_path / "behavior.tsv").glob("*.tsv"))
    assert "101\t0" in tsv.read_text()
    assert not [e for e in events if e.get("evt") == "session.telemetry"]


async def test_starting_an_unconfigured_box_raises(tmp_path: Path) -> None:
    runner, _ports, _events, _ended = make_runner(tmp_path)
    with pytest.raises(KeyError):
        runner.start_box(4)


async def test_the_snapshot_reports_the_mapping_and_what_is_live(tmp_path: Path) -> None:
    """`sessions.status` is built from this — §5's per-box cards."""
    runner, ports, _events, _ended = make_runner(tmp_path)
    assert runner.group_id == "g1"
    assert runner.snapshot() == [
        {
            "box": 1,
            "animalId": "a1",
            "animalName": "remy1",
            "sketchName": "GRGL_2-Odor",
            "sketchPath": "/sk/GRGL_2-Odor",
            "running": False,
            "startedAt": None,
        }
    ]

    runner.start_box(1)
    assert runner.snapshot()[0]["running"] is True

    ports.on_ready(None)
    ports.on_strobe(246, 10)
    await wait_until(lambda: runner.snapshot()[0]["running"] is False)
    assert runner.snapshot()[0]["running"] is False

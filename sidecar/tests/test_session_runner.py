"""Session runner integration — strobes → `.tsv` + metrics + telemetry.

Ties step 7 of `ARCHITECTURE.md#entering-in_session` to `DATA.md#crash-safety`: each parsed
strobe must land durably in the write-ahead log *and* update the rolling live
metric pushed to the frontend.

Runs on the real `PortManager`, with scripted boards behind its `open_serial`
(`tests/scripted_board.py`): the port's state machine and session thread are
the ones a session runs on, so a port that refuses, or a board that drops, is
met the way the runner meets it on the rig.
"""

from __future__ import annotations

import asyncio
import json
import threading
import zlib
from pathlib import Path

import pytest

from ephymeris_sidecar.tasks.start_command import build_start_command
from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.ports.states import IllegalTransition, PortState
from ephymeris_sidecar.sessions.runner import CLEAN_STOP_REASON, BoxConfig, SessionRunner
from ephymeris_sidecar.tasks.profile import parse_profile
from tests.scripted_board import Bench, ScriptedBoard, until

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


@pytest.fixture(autouse=True)
def _short_seed_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """A board that sends no SEED resolves its handshake when the window
    closes; keep that from idling every test."""
    monkeypatch.setattr(handler_module, "SESSION_SEED_WINDOW_S", 0.05)


@pytest.fixture
async def bench():  # noqa: ANN201
    """Boxes 1 and 2 on a real `PortManager`, boards plugged in."""
    made = await Bench(asyncio.get_running_loop(), (1, 2)).plug_in()
    yield made
    made.shutdown()


async def wait_until(predicate, *, timeout: float = 5.0) -> None:  # noqa: ANN001
    """Yield to the loop until `predicate()` holds.

    Finalization is scheduled on the loop and does its file I/O in a worker
    thread, so how long it takes depends on machine load rather than on
    anything the test controls. A fixed number of short sleeps therefore
    passes alone and fails under a full suite — wait on the condition, with a
    generous ceiling that only trips on a genuine hang.
    """
    try:
        await until(predicate, timeout=timeout)
    except AssertionError:
        raise AssertionError("timed out waiting for the runner to settle") from None


def make_runner(  # noqa: ANN201
    tmp_path: Path,
    bench: Bench,
    profile_json=GRGL,  # noqa: ANN001
    duration_s=None,  # noqa: ANN001
    boxes=(1,),  # noqa: ANN001
    channel_set_hash: str | None = None,
    channel_set_hash_version: int | None = None,
):
    events: list[dict] = []
    ended: list[tuple] = []

    async def broadcast(message):  # noqa: ANN001
        events.append(message)

    async def on_animal_ended(run, reason):  # noqa: ANN001
        ended.append((run, reason))

    runner = SessionRunner(
        loop=asyncio.get_running_loop(),
        ports=bench.ports,
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
                box=box,
                animal_id=f"a{box}",
                animal_name=f"remy{box}",
                sketch_path="/sk/GRGL_2-Odor",
                sketch_name="GRGL_2-Odor",
                start_command=build_start_command(profile, {}),
                config_metadata={"correction_left": 0, "lazy_escalation": True},
                profile=profile,
                channel_set_hash=channel_set_hash,
                channel_set_hash_version=channel_set_hash_version,
            )
            for box in boxes
        ],
        duration_s=duration_s,
        session_id="s1",
    )
    return runner, events, ended


def tsv_text(tmp_path: Path) -> str:
    return next((tmp_path / "behavior.tsv").glob("*.tsv")).read_text(encoding="utf-8")


def released(bench: Bench, box: int) -> list[str]:
    """The reasons `box`'s port was moved out of a session into IDLE."""
    return [
        reason for old, new, reason in bench.transitions(box)
        if (old, new) == (PortState.IN_SESSION, PortState.IDLE)
    ]


async def test_a_run_writes_its_tsv_with_the_seed_captured(tmp_path: Path, bench: Bench) -> None:
    runner, _events, _ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1, seed=288577176)
    # The parameters on a SET line, confirmed; the seed alone on START.
    assert board.sent()[:-1] == ["BEGIN", "SET CL=0 LAZY=1"]
    assert board.sent()[-1].startswith("START SEED=")

    await board.said("101\t0", "249\t500")

    text = tsv_text(tmp_path)
    # Core fields (`DATA.md#the-tsv-log`) + flat config + the recognized
    # trial_seed convention (`TASKS.md#seed`)
    assert "# rat: remy1" in text
    assert "# serial_port: /dev/box1" in text
    assert "# session_id: 2O-Bdisc_25" in text
    assert "# sketch: GRGL_2-Odor" in text
    assert "# trial_seed: 288577176" in text
    # Strobes in the board's exact format
    assert "101\t0" in text
    assert "249\t500" in text


async def test_each_start_draws_its_own_seed(tmp_path: Path, bench: Bench) -> None:
    """Stop → Start on the same box must not replay the same trial sequence.

    The seed is drawn on the click and not with the mapping, precisely so that
    a box restarted after a false start gets a fresh stream rather than the one
    the animal already ran through.
    """
    runner, _events, _ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("246\t10")
    await wait_until(lambda: not runner.running_boxes())
    await wait_until(lambda: bench.state(1) is PortState.IDLE)

    runner.start_box(1)
    again = await bench.run_handshake(1)
    assert again is not board
    assert board.sent()[-1] != again.sent()[-1]


async def test_both_seeds_are_recorded_when_the_board_disagrees(tmp_path: Path, bench: Bench) -> None:
    """Firmware predating the `SEED=` convention seeds itself and echoes its own
    number. Recording only one of the two would leave the file claiming a seed
    that never reached the RNG — or hiding that the host asked for a better one."""
    runner, _events, _ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1, seed=4242)  # an old sketch's own micros()-derived value
    sent = int(board.sent()[-1].rsplit("SEED=", 1)[1])
    await board.said("101\t0")

    text = tsv_text(tmp_path)
    assert "# trial_seed: 4242" in text, "what the board actually ran on"
    assert f"# host_seed: {sent}" in text, "what this app asked for"


async def test_the_interpreter_the_board_announced_is_recorded_in_the_header(
    tmp_path: Path, bench: Bench
) -> None:
    runner, _events, _ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1, seed=5, interp=1)
    await board.said("101\t0")

    text = tsv_text(tmp_path)
    assert "# interp: 1\n" in text
    # Before the first strobe, like the rest of the header.
    assert text.index("# interp: 1") < text.index("101\t0")


async def test_the_channel_set_hash_the_sketch_was_generated_against_is_in_the_header(
    tmp_path: Path, bench: Bench
) -> None:
    runner, _events, _ended = make_runner(
        tmp_path, bench, channel_set_hash="c0ffee0123456789", channel_set_hash_version=2
    )
    runner.start_box(1)
    board = await bench.run_handshake(1, seed=5)
    await board.said("101\t0", "246\t10")

    text = tsv_text(tmp_path)
    assert "# channel_set_hash: c0ffee0123456789\n" in text
    # Which rule made it, so a hash that ignored order is never read as one
    # that covers it (`DATA.md#the-json-document`).
    assert "# channel_set_hash_version: 2\n" in text
    assert text.index("# channel_set_hash:") < text.index("101\t0")
    await wait_until(lambda: any((tmp_path / "behavior.json").glob("*.json")))
    document = json.loads(next((tmp_path / "behavior.json").glob("*.json")).read_text())
    assert document["channel_set_hash"] == "c0ffee0123456789"
    assert document["channel_set_hash_version"] == 2


async def test_a_board_that_announced_no_interpreter_records_none(tmp_path: Path, bench: Bench) -> None:
    runner, _events, _ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1, seed=5)
    await board.said("101\t0")

    assert "# interp" not in tsv_text(tmp_path)


@pytest.mark.parametrize(
    ("answer", "code", "reason"),
    [
        # A value cut short: the right count, the wrong CRC.
        (lambda tokens: [f"PARAMS {len(tokens)} 1"], "PARAMS_MISMATCH", "crc"),
        # A key it does not parse: one fewer than was sent.
        (lambda tokens: [f"PARAMS {len(tokens) - 1} 1"], "PARAMS_MISMATCH", "count"),
        # A value its clamp moved.
        (
            lambda tokens: ["CLAMPED CL", f"PARAMS {len(tokens)} {zlib.crc32(' '.join(tokens).encode())}"],
            "PARAMS_CLAMPED",
            "clamped",
        ),
        # An older sketch: no reply at all.
        (lambda tokens: [], "FIRMWARE_OUTDATED", "no_reply"),
    ],
    ids=["cut-short", "unparsed-key", "clamped", "older-sketch"],
)
async def test_a_refused_start_names_its_box_and_reason_and_writes_no_file(
    tmp_path: Path, bench: Bench, monkeypatch: pytest.MonkeyPatch, answer, code: str, reason: str  # noqa: ANN001
) -> None:
    monkeypatch.setattr(ScriptedBoard, "answer", staticmethod(answer))
    monkeypatch.setattr(handler_module, "SESSION_PARAMS_TIMEOUT_S", 0.3)
    runner, events, ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.wait_for_board(1)
    board.say("READY\n")  # said() would wait for a read the refused session never makes

    await wait_until(lambda: bool(ended))
    refusals = [e["data"] for e in events if e.get("evt") == "sidecar.error"]
    assert len(refusals) == 1
    assert refusals[0]["code"] == code
    assert refusals[0]["detail"]["box"] == 1 and refusals[0]["detail"]["reason"] == reason
    assert refusals[0]["message"].startswith("Box 1: ")
    _run, stop_reason = ended[-1]
    assert stop_reason == f"start refused: {reason}"
    assert not any(line.startswith("START") for line in board.sent()), "START went out anyway"
    assert not (tmp_path / "behavior.tsv").exists(), "a refused start must leave no file"
    assert bench.state(1) is PortState.ERROR


async def test_strobes_push_rolling_telemetry(tmp_path: Path, bench: Bench) -> None:
    runner, events, _ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1)

    await board.said("101\t0", "249\t100")  # trigger, then went right → hit
    # Pushes are scheduled onto the loop one per strobe: wait for the hit's, not the first.
    await wait_until(
        lambda: any(
            e.get("evt") == "session.telemetry" and e["data"]["metrics"][0]["value"] is not None
            for e in events
        )
    )

    telemetry = [e for e in events if e.get("evt") == "session.telemetry"]
    last = telemetry[-1]["data"]
    assert last["box"] == 1
    assert last["animalId"] == "a1"
    metric = last["metrics"][0]
    assert metric["id"] == "p_r_odor1"
    assert metric["value"] == 1.0
    assert metric["n"] == 1


async def test_the_end_code_finalizes_the_run_cleanly(tmp_path: Path, bench: Bench) -> None:
    runner, _events, ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("101\t0", "249\t100", "246\t3523555")  # END_SESSION per the profile's strobes map

    await wait_until(lambda: bool(ended))
    run, reason = ended[-1]
    assert reason == CLEAN_STOP_REASON
    await wait_until(lambda: released(bench, 1) == [CLEAN_STOP_REASON])
    assert board.closed
    # The run names its own session record, whatever is held by the time it lands.
    assert run.session_id == "s1"

    # `DATA.md#built-once-at-the-end` — .json and .mat built once at the end, from the same in-memory list.
    doc = json.loads(next((tmp_path / "behavior.json").glob("*.json")).read_text(encoding="utf-8"))
    assert doc["rat"] == "remy1"
    assert doc["stop_reason"] == CLEAN_STOP_REASON
    assert doc["n_events"] == 3
    assert doc["ts_data"] == [[101, 0], [249, 100], [246, 3523555]]
    assert next((tmp_path / "behavior.mat").glob("*.mat")).is_file()


async def test_the_time_limit_sends_stop_and_the_board_ends_the_run(tmp_path: Path, bench: Bench) -> None:
    """`ARCHITECTURE.md#configuration` — at the deadline the runner sends the same STOP an operator
    would; the board's own end strobe still does the ending."""
    runner, _events, ended = make_runner(tmp_path, bench, duration_s=0.3)
    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("101\t0")

    # The deadline fires on the loop and only sends STOP — nothing finalizes yet.
    await wait_until(lambda: "STOP" in board.sent())
    assert not ended, "STOP alone must not finalize; the trial boundary does"

    # The board honours STOP at its trial boundary and emits its end strobe.
    await board.said("246\t3000")
    await wait_until(lambda: bool(ended))
    _run, reason = ended[-1]
    assert reason == CLEAN_STOP_REASON


async def test_an_early_end_cancels_the_deadline(tmp_path: Path, bench: Bench) -> None:
    """A box that finished before its time limit must never get a ghost STOP —
    by then the port is free and could belong to something else."""
    # The limit is far enough out that no scheduling delay can let it fire
    # during the test: what's asserted below is the timer's *cancelled* state,
    # not that we outran it.
    runner, _events, ended = make_runner(tmp_path, bench, duration_s=3600.0)
    runner.start_box(1)
    deadline = runner._active[1].deadline
    assert deadline is not None and not deadline.cancelled(), "box 1 armed no deadline"

    board = await bench.run_handshake(1)
    await board.said("246\t100")  # clean end well before the deadline

    await wait_until(lambda: bool(ended))
    # The handle finalization cancelled is the one this box was armed with, and
    # asyncio never runs a cancelled handle's callback — so `_on_deadline` can
    # no longer reach a port that by now could belong to something else.
    assert deadline.cancelled(), "the early end left the deadline armed"
    assert "STOP" not in board.sent(), "the cancelled deadline still sent STOP"


async def test_snapshot_carries_started_at_only_while_running(tmp_path: Path, bench: Bench) -> None:
    runner, _events, ended = make_runner(tmp_path, bench)
    assert runner.snapshot()[0]["startedAt"] is None

    runner.start_box(1)
    board = await bench.run_handshake(1)
    assert runner.snapshot()[0]["startedAt"] is not None

    await board.said("246\t100")
    await wait_until(lambda: bool(ended))
    assert runner.snapshot()[0]["startedAt"] is None


async def test_snapshot_reports_a_finished_box_until_it_starts_again(tmp_path: Path, bench: Bench) -> None:
    """`session.animalEnded` is never replayed (`ARCHITECTURE.md#replay-on-connect`), so a
    reloaded Mission Control learns a group is done only from `ended`."""
    runner, _events, ended = make_runner(tmp_path, bench)
    assert runner.snapshot()[0]["ended"] is False

    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("246\t100")
    await wait_until(lambda: bool(ended))
    assert runner.snapshot()[0]["ended"] is True

    await wait_until(lambda: bench.state(1) is PortState.IDLE)
    runner.start_box(1)
    assert runner.snapshot()[0]["ended"] is False


async def test_a_box_is_ended_by_the_time_its_end_is_announced(tmp_path: Path, bench: Bench) -> None:
    """A client re-asks `sessions.status` on `session.animalEnded`; the answer must
    already say the box ended."""
    seen: list[bool] = []
    runner, _events, _ended = make_runner(tmp_path, bench)

    async def on_animal_ended(run, reason):  # noqa: ANN001
        seen.append(runner.snapshot()[0]["ended"])

    runner._on_animal_ended = on_animal_ended
    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("246\t100")
    await wait_until(lambda: bool(seen))
    assert seen == [True]


async def test_a_new_mapping_forgets_finished_boxes(tmp_path: Path, bench: Bench) -> None:
    runner, _events, ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("246\t100")
    await wait_until(lambda: bool(ended))

    runner.configure(tmp_path, "2O-Bdisc_25", "g2", runner.box_configs(), session_id="s1")
    assert runner.snapshot()[0]["ended"] is False


async def test_a_board_drop_finalizes_with_whatever_was_captured(tmp_path: Path, bench: Bench) -> None:
    """`ARCHITECTURE.md#board-drop` — the hard stop costs no data; the WAL already has it.
    The runner hears of the drop from its claim on the port, with nothing in
    between to reconcile the two."""
    runner, _events, ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("101\t0", "249\t100")

    board.unplug()
    await wait_until(lambda: bool(ended))

    _run, reason = ended[-1]
    assert reason == "board disconnected"
    assert runner.running_boxes() == []
    # The ERROR stands until the operator acknowledges it.
    assert bench.state(1) is PortState.ERROR and released(bench, 1) == []

    doc = json.loads(next((tmp_path / "behavior.json").glob("*.json")).read_text(encoding="utf-8"))
    assert doc["stop_reason"] == "board disconnected"
    assert doc["ts_data"] == [[101, 0], [249, 100]]


async def test_a_board_that_never_reports_ready_ends_its_run(
    tmp_path: Path, bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handshake times out into ERROR: the run is finalized, with no file
    since nothing was ever opened, and the box is free to be started again
    once the operator acknowledges the error."""
    monkeypatch.setattr(handler_module, "SESSION_READY_TIMEOUT_S", 0.2)
    runner, _events, ended = make_runner(tmp_path, bench)
    runner.start_box(1)

    await wait_until(lambda: bool(ended))
    _run, reason = ended[-1]
    assert reason == "board disconnected"
    assert runner.running_boxes() == []
    assert bench.state(1) is PortState.ERROR


async def test_stop_sends_stop_without_ending_the_run(tmp_path: Path, bench: Bench) -> None:
    runner, _events, ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1)

    assert runner.stop_box(1) is True
    assert board.sent()[-1] == "STOP"
    # The board's own end strobe ends it, not the STOP itself (`ARCHITECTURE.md#clean-exit`).
    assert ended == []
    assert bench.state(1) is PortState.IN_SESSION


async def test_stopping_a_box_that_is_not_running_is_not_an_error(tmp_path: Path, bench: Bench) -> None:
    runner, _events, _ended = make_runner(tmp_path, bench)
    assert runner.stop_box(1) is False
    assert runner.stop_box(4) is False


async def test_a_profile_less_sketch_still_writes_but_pushes_no_metrics(
    tmp_path: Path, bench: Bench
) -> None:
    runner, events, _ended = make_runner(tmp_path, bench, profile_json=None)
    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("101\t0")
    await asyncio.sleep(0.01)

    assert "101\t0" in tsv_text(tmp_path)
    assert not [e for e in events if e.get("evt") == "session.telemetry"]


async def test_starting_an_unconfigured_box_raises(tmp_path: Path, bench: Bench) -> None:
    runner, _events, _ended = make_runner(tmp_path, bench)
    with pytest.raises(KeyError):
        runner.start_box(4)


async def test_the_snapshot_reports_the_mapping_and_what_is_live(tmp_path: Path, bench: Bench) -> None:
    """`sessions.status` is built from this — Mission Control's per-box tiles
    (`USER-GUIDE.md#reading-a-box-tile`)."""
    runner, _events, _ended = make_runner(tmp_path, bench)
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
            "ended": False,
        }
    ]

    runner.start_box(1)
    assert runner.snapshot()[0]["running"] is True

    board = await bench.run_handshake(1)
    await board.said("246\t10")
    await wait_until(lambda: runner.snapshot()[0]["running"] is False)


# --- a start the port refuses, and a loss during the end (B1, B17) ---------------


async def test_a_box_whose_port_refuses_is_never_a_run(tmp_path: Path, bench: Bench) -> None:
    """B1: a box left in ERROR (here, by a board that never reported READY)
    still carries its sketch, so Start reaches the port, and the port refuses.
    Nothing may be left behind: no run, no time limit, nothing for End to STOP."""
    bench.ports.handler(1).force_error("board never reported READY")
    runner, _events, ended = make_runner(tmp_path, bench, duration_s=3600.0)

    with pytest.raises(IllegalTransition):
        runner.start_box(1)

    assert runner.running_boxes() == []
    assert runner.snapshot()[0]["running"] is False
    await runner.end_all("operator stop")  # nothing to STOP, so nothing raises
    runner.clear()
    assert ended == [] and bench.state(1) is PortState.ERROR


async def test_a_board_lost_while_its_run_finalizes_stays_in_error(
    tmp_path: Path, bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B17: the clean end awaits the writer's finalize; a board pulled in that
    window lands the port in ERROR, and the end that follows must not quietly
    move it to IDLE. ERROR clears only by acknowledgement."""
    from ephymeris_sidecar.sessions import writer as writer_module

    finalizing, may_finish = threading.Event(), threading.Event()
    real_finalize = writer_module.AnimalWriter.finalize

    def slow_finalize(self, reason):  # noqa: ANN001, ANN202
        finalizing.set()
        may_finish.wait(timeout=5)
        return real_finalize(self, reason)

    monkeypatch.setattr(writer_module.AnimalWriter, "finalize", slow_finalize)
    runner, _events, ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1, seed=7)
    board.say("101\t0\n246\t100\n")  # a trial, then END_SESSION
    await until(finalizing.is_set)

    board.unplug()
    await until(lambda: bench.state(1) is PortState.ERROR)
    may_finish.set()
    await until(lambda: bool(ended))
    await asyncio.sleep(0.05)  # let any late transition land

    assert bench.state(1) is PortState.ERROR


async def test_end_reaches_every_box_when_one_port_has_already_failed(tmp_path: Path, bench: Bench) -> None:
    """A port that left the session before End's STOP reached it (its loss
    not yet finalized) must not stop End from reaching the other box."""
    runner, _events, ended = make_runner(tmp_path, bench, boxes=(1, 2))
    runner.start_box(1)
    runner.start_box(2)
    one = await bench.run_handshake(1)
    two = await bench.run_handshake(2)
    bench.ports.handler(1).force_error("board went away")  # its on_lost is queued on the loop

    await runner.end_all("operator stop")

    assert "STOP" not in one.sent() and "STOP" in two.sent()
    assert sorted(run.box for run, _ in ended) == [1, 2]
    assert bench.state(1) is PortState.ERROR and bench.state(2) is PortState.IDLE


# --- graceful end, and the recording's taps (`RECORDING.md#start-and-end`) ---


async def test_a_graceful_end_waits_for_the_board_to_close_its_own_trial(tmp_path: Path, bench: Bench) -> None:
    """The default 100 ms cuts the trial in flight, which is the behavior-only
    contract. A RECORDING cannot afford that: electrophysiology with no
    behavioral outcome to align to. With a real timeout the run ends on the
    board's own end strobe, and says so."""
    runner, _events, ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("101\t0")
    waiting: list[list[int]] = []

    async def board_finishes_its_trial() -> None:
        await asyncio.sleep(0.3)  # three times the default grace
        board.say("249\t1000\n246\t1200\n")  # END_SESSION

    finishing = asyncio.ensure_future(board_finishes_its_trial())
    await runner.end_all("operator stop", graceful_timeout_s=5.0, on_waiting=waiting.append)
    await finishing

    assert board.sent().count("STOP") == 1  # STOP was a request...
    assert [reason for _, reason in ended] == [CLEAN_STOP_REASON]  # ...the board did the ending
    assert waiting == [[1], []]
    document = json.loads(next((tmp_path / "behavior.json").glob("*.json")).read_text())
    assert document["n_events"] == 3  # the trial's outcome made it in


async def test_the_operator_can_stop_waiting(tmp_path: Path, bench: Bench) -> None:
    runner, _events, ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    await bench.run_handshake(1)
    force = asyncio.Event()
    asyncio.get_running_loop().call_later(0.1, force.set)

    started = asyncio.get_running_loop().time()
    await runner.end_all("operator stop", graceful_timeout_s=30.0, force=force)

    assert asyncio.get_running_loop().time() - started < 5.0
    assert [reason for _, reason in ended] == ["operator stop"]


def test_the_end_does_not_spin_on_a_finalization_that_just_finished(tmp_path: Path) -> None:
    """A board's own end strobe finalizes its run in a tracked task. When that
    task finished in the same loop turn `end_all` reached its drain, it was
    still in the set, waiting for its `discard` callback, and a gather over
    finished tasks never yields: `end_all` spun forever and starved the loop.
    It hung CI one run in a few dozen; here the state is set up directly.

    On a thread of its own, so a regression fails instead of hanging the suite."""

    async def scenario() -> None:
        bench = await Bench(asyncio.get_running_loop(), (1,)).plug_in()
        runner, _events, _ended = make_runner(tmp_path, bench)
        loop = asyncio.get_running_loop()
        finished = loop.create_future()
        finished.set_result(None)
        runner._finalizations.add(finished)  # type: ignore[arg-type]
        loop.call_soon(runner._finalizations.discard, finished)  # its callback, queued
        await runner.end_all("operator stop")

    thread = threading.Thread(target=asyncio.run, args=(scenario(),), daemon=True)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive(), "end_all spun on a finished finalization"


async def test_the_default_end_is_unchanged(tmp_path: Path, bench: Bench) -> None:
    runner, _events, ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    await bench.run_handshake(1)
    started = asyncio.get_running_loop().time()
    await runner.end_all("operator stop")
    assert asyncio.get_running_loop().time() - started < 2.0
    assert [reason for _, reason in ended] == ["operator stop"]
    assert released(bench, 1) == ["operator stop"]


async def test_recording_fields_ride_the_document_and_stay_out_of_the_parameters(
    tmp_path: Path, bench: Bench
) -> None:
    """Core, not config: they describe the rig, not the task. Two runs of one
    tuning are comparable whether or not one of them was recorded, so nothing
    the recording adds may reach `config_metadata` -- which is what
    `params_hash` is taken over."""
    runner, _events, ended = make_runner(tmp_path, bench)
    runner.recording_fields = lambda box: {"intan_recording": "base_260920_101500", "intan_digital_in": 5}
    started, tapped = [], []
    runner.on_box_started = lambda box, animal: started.append((box, animal))
    runner.on_strobe_tap = lambda box, code, ms: tapped.append((box, code, ms))

    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("101\t40", "246\t90")
    await wait_until(lambda: len(ended) == 1)

    document = json.loads(next((tmp_path / "behavior.json").glob("*.json")).read_text())
    assert document["intan_recording"] == "base_260920_101500"
    assert document["intan_digital_in"] == 5
    run, _reason = ended[0]
    assert not any(key.startswith("intan_") for key in run.config.config_metadata)
    assert started == [(1, "remy1")]
    assert tapped == [(1, 101, 40), (1, 246, 90)]
    # It survives a crash: the header is the durable copy.
    assert "# intan_recording: base_260920_101500" in tsv_text(tmp_path)


async def test_a_recording_tap_that_throws_costs_the_run_nothing(tmp_path: Path, bench: Bench) -> None:
    """The taps sit between a strobe arriving and the next one. A behavior
    session never pays for the recording's problems."""
    runner, _events, ended = make_runner(tmp_path, bench)

    def broken(*_args):  # noqa: ANN002, ANN202
        raise RuntimeError("the recording layer fell over")

    runner.recording_fields = broken
    runner.on_box_started = broken
    runner.on_strobe_tap = broken

    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("101\t40", "246\t90")
    await wait_until(lambda: len(ended) == 1)

    document = json.loads(next((tmp_path / "behavior.json").glob("*.json")).read_text())
    assert document["n_events"] == 2 and document["stop_reason"] == CLEAN_STOP_REASON

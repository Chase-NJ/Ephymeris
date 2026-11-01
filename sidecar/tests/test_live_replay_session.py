"""A running spine task's live replay, through the real session path (issue #100).

The runner feeds every strobe of a spine run to its box's live replay after the
strobe is fsync'd (`sessions/live_replay.py`), and `session.replay` reports where
the board is and the numbers so far (`ARCHITECTURE.md#live-session-views`).
Here a recorded stream is played by a scripted board into the real
`PortManager` and `SessionRunner`, and what reached the wire is held to what
Analytics makes of the same stream.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics.stream import spine as spine_stream
from ephymeris_sidecar.analytics.stream.summary import summarize
from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.protocol import Evt, validate_event_data
from ephymeris_sidecar.sessions import live_replay
from ephymeris_sidecar.sessions.scorer import LiveScorer
from ephymeris_sidecar.sessions.runner import BoxConfig, SessionRunner
from ephymeris_sidecar.tasks import profile as task_profile
from ephymeris_sidecar.tasks.start_command import build_start_command
from tests.fixtures import spine as fixture
from tests.scripted_board import Bench, until
from tests.test_live_replay import header_of
from tests.test_spine_analytics import go_no_go_animal, simulated_document


#: Runners `make_runner` made, whose scorers each test's end kills.
_RUNNERS: list[SessionRunner] = []


@pytest.fixture(autouse=True)
def _issued_rig(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(handler_module, "SESSION_SEED_WINDOW_S", 0.05)
    fixture.install()
    yield
    fixture.uninstall()
    while _RUNNERS:
        _RUNNERS.pop().close()


@pytest.fixture
async def bench():  # noqa: ANN201
    made = await Bench(asyncio.get_running_loop(), (1,)).plug_in()
    yield made
    made.shutdown()


@pytest.fixture
def scorer():  # noqa: ANN201
    made = LiveScorer()
    yield made
    made.stop()


def document(trials: int = 6) -> dict:
    return simulated_document(fixture.go_no_go(), go_no_go_animal, trials=trials)


def make_runner(tmp_path: Path, bench: Bench, recorded: dict,
                scorer: LiveScorer | None = None) -> tuple[SessionRunner, list[dict]]:
    events: list[dict] = []

    async def broadcast(message: dict) -> None:
        events.append(message)

    async def nothing(*_args) -> None:  # noqa: ANN002
        return None

    profile = task_profile.parse_profile(recorded[task_profile.SNAPSHOT_KEY])
    config = {f.metadata_key: recorded[f.metadata_key] for f in profile.config}
    runner = SessionRunner(loop=asyncio.get_running_loop(), ports=bench.ports,
                           broadcast=broadcast, on_animal_ended=nothing, scorer=scorer)
    runner.configure(
        tmp_path, "SPN-gng_1", "g1",
        [BoxConfig(box=1, animal_id="a1", animal_name="remy1", sketch_path="/sk/spine",
                   sketch_name="Spine Go No-Go", start_command=build_start_command(profile, config),
                   config_metadata=config, profile=profile)],
        duration_s=None, session_id="s1",
    )
    _RUNNERS.append(runner)
    return runner, events


def replays(events: list[dict]) -> list[dict]:
    """Every `session.replay` payload sent, each one the schema's shape."""
    out = [e["data"] for e in events if e["evt"] == Evt.SESSION_REPLAY]
    for payload in out:
        assert validate_event_data(Evt.SESSION_REPLAY, payload) == [], payload
    return out


def lines(strobes) -> list[str]:  # noqa: ANN001
    return [f"{code}\t{ts}" for code, ts in strobes]


async def start(runner: SessionRunner, bench: Bench, recorded: dict):  # noqa: ANN201
    runner.start_box(1)
    return await bench.run_handshake(1, seed=recorded["trial_seed"], interp=recorded["interp"])


async def test_the_live_metrics_at_the_end_are_analytics(tmp_path: Path, bench: Bench) -> None:
    recorded = document()
    runner, events = make_runner(tmp_path, bench, recorded)
    board = await start(runner, bench, recorded)
    await board.said(*lines(recorded["ts_data"]))
    await until(lambda: any(r["status"] == "ended" and r["metrics"] for r in replays(events)), timeout=10)

    final = replays(events)[-1]
    offline = summarize(recorded, None)
    assert final["status"] == "ended" and final["box"] == 1 and final["animalId"] == "a1"
    assert final["metrics"] == [m.to_json() for m in offline.metrics]
    assert final["overall"] == offline.overall.to_json()
    assert final["replay"] == offline.replay.to_json()
    assert final["trials"] == offline.replay.trials
    assert final["state"] is None and final["phase"] is None, "an ended run has no token"
    table = spine_stream.trial_table(recorded)["trials"]
    assert final["last"] == table[-1] and final["current"] is None


async def test_the_token_follows_the_replayed_phase(tmp_path: Path, bench: Bench) -> None:
    recorded = document()
    runner, events = make_runner(tmp_path, bench, recorded)
    board = await start(runner, bench, recorded)
    phases = recorded[task_profile.SNAPSHOT_KEY]["spine"]["table"]["phases"]
    for code, ts in recorded["ts_data"][:12]:
        await board.said(f"{code}\t{ts}")
    await until(lambda: bool(replays(events)))
    seen = [r for r in replays(events) if r["status"] == "replaying"]
    assert seen and all(r["phase"] == phases[r["state"]] for r in seen)
    assert {r["phase"] for r in seen} >= {0, 1, 2}, "wait, present and the window, as the board ran them"
    # A client that connects now is told the same thing.
    assert runner.replay_snapshot() == [replays(events)[-1]]


async def test_a_diverging_board_is_reported_before_the_session_ends(tmp_path: Path, bench: Bench) -> None:
    recorded = document()
    code_of = {name: int(c) for c, name in recorded[task_profile.SNAPSHOT_KEY]["strobes"].items()}
    strobes = [list(s) for s in recorded["ts_data"]]
    k = next(i for i, (c, _) in enumerate(strobes) if c == code_of["FLUID_2_ON"])
    strobes[k][1] += 1  # the reward opened a tick late: not what this table does
    nxt = next(i for i in range(k, len(strobes)) if strobes[i][0] == code_of["TRIAL_START"])
    runner, events = make_runner(tmp_path, bench, recorded)
    board = await start(runner, bench, recorded)
    await board.said(*lines(strobes[: nxt + 1]))
    await until(lambda: any(r["status"] == "diverged" for r in replays(events)), timeout=10)

    diverged = replays(events)[-1]
    assert diverged["status"] == "diverged"
    assert diverged["divergence"]["index"] == k and "FLUID_2_ON" in diverged["detail"]
    assert diverged["state"] is None and diverged["metrics"] == [] and diverged["overall"] is None, \
        "the token and the numbers are withdrawn, never left standing"
    assert runner.running_boxes() == [1], "reported live, while the box still runs"


async def test_a_run_replay_cannot_run_is_reported_as_such(tmp_path: Path, bench: Bench) -> None:
    """A board that announces the trial runner's INTERP under a spine snapshot:
    never replayed under a guess, and said so at once."""
    recorded = document()
    runner, events = make_runner(tmp_path, bench, recorded)
    runner.start_box(1)
    board = await bench.run_handshake(1, seed=recorded["trial_seed"], interp=1)
    await board.said(*lines(recorded["ts_data"][:5]))
    await until(lambda: bool(replays(events)))
    [only] = replays(events)
    assert only["status"] == "unreplayable" and "INTERP 1" in only["detail"]
    assert only["phase"] is None and only["metrics"] == []


async def test_a_legacy_run_has_no_live_replay(tmp_path: Path, bench: Bench) -> None:
    from tests import test_session_runner as legacy

    runner, events, _ended = legacy.make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1, seed=7)
    await board.said("101\t10", "249\t20")
    await until(lambda: any(e["evt"] == Evt.SESSION_TELEMETRY for e in events))
    assert replays(events) == [] and runner.replay_snapshot() == []


# --- between strobes ------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


async def test_a_silent_transition_is_reported_on_the_boards_time(scorer) -> None:  # noqa: ANN001
    """The outcome's timeout runs out into the ITI with nothing strobed: the
    token moves there when the board's clock says so, never by polling it."""
    recorded = document()
    clock = Clock()
    published: list[dict] = []

    async def publish(payload: dict) -> None:
        published.append(payload)

    box = live_replay.BoxReplay(1, "a1", header_of(recorded), loop=asyncio.get_running_loop(),
                                publish=publish, scorer=scorer, clock=clock)
    code_of = {name: int(c) for c, name in recorded[task_profile.SNAPSHOT_KEY]["strobes"].items()}
    strobes = recorded["ts_data"]
    # Through the first reward's end: the board is in the outcome's timeout.
    k = next(i for i, (c, _) in enumerate(strobes) if c == code_of["FLUID_2_OFF"])
    for code, ts in strobes[: k + 1]:
        box.feed(code, ts)
    await until(lambda: bool(published) and published[-1]["phase"] == 3)
    assert published[-1]["provisional"] is False
    clock.now += 0.5  # half a second of silence on the board
    await until(lambda: published[-1]["phase"] == 4, timeout=2)
    assert published[-1]["status"] == "replaying"
    assert published[-1]["provisional"] is True, "marked: no strobe has confirmed it yet"
    box.feed(*strobes[k + 1])  # the next trial's first strobe confirms the board moved on
    await until(lambda: published[-1]["provisional"] is False, timeout=2)
    box.close()


# --- a client that connects mid-session ------------------------------------------


async def test_a_client_that_connects_is_told_each_boxs_replay(tmp_path: Path, monkeypatch, scorer) -> None:  # noqa: ANN001
    from tests.wire import running_app

    recorded = document()

    async def publish(_payload: dict) -> None:
        return None

    box = live_replay.BoxReplay(3, "a3", header_of(recorded), loop=asyncio.get_running_loop(),
                                publish=publish, scorer=scorer)
    for code, ts in recorded["ts_data"][:10]:
        box.feed(code, ts)
    await asyncio.sleep(0.05)
    async with running_app(tmp_path / "app") as app:
        assert await app.server.snapshot(Evt.SESSION_REPLAY) == [], "no spine run, nothing to tell"
        payload = box.payload()
        assert payload["status"] == "replaying" and payload["phase"] is not None
        monkeypatch.setattr(app.runner, "replay_snapshot", lambda: [payload])
        [told] = await app.server.snapshot(Evt.SESSION_REPLAY)
        assert told["evt"] == Evt.SESSION_REPLAY and told["data"] == payload


# --- the scorer fenced off ---------------------------------------------------------


async def test_a_scorer_killed_mid_session_costs_only_the_live_numbers(
        tmp_path: Path, bench: Bench, scorer: LiveScorer) -> None:
    recorded = document(trials=8)
    strobes = recorded["ts_data"]
    runner, events = make_runner(tmp_path, bench, recorded, scorer=scorer)
    board = await start(runner, bench, recorded)
    half = len(strobes) // 2
    await board.said(*lines(strobes[:half]))
    await until(lambda: any(r["metrics"] for r in replays(events)), timeout=20)
    scorer.kill_for_test()
    await until(lambda: replays(events)[-1]["unavailable"] is not None, timeout=10)

    down = replays(events)[-1]
    assert down["status"] == "replaying" and down["metrics"] == [] and down["overall"] is None
    assert "unavailable" in down["unavailable"]
    await board.said(*lines(strobes[half:]))
    await until(lambda: not runner.running_boxes(), timeout=10)
    moving = [r for r in replays(events) if r["unavailable"] and r["phase"] is not None]
    assert len({r["phase"] for r in moving}) > 1, "the token carried on"
    final = replays(events)[-1]
    assert final["status"] == "ended" and final["metrics"] == [] and final["unavailable"]
    await until(lambda: any(p.is_file() for p in tmp_path.rglob("*.json")), timeout=10)
    tsv = next(p for p in tmp_path.rglob("*.tsv") if p.is_file())
    body = [line for line in tsv.read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
    assert body == lines(strobes), "every strobe is in the .tsv, in order"


async def test_a_feed_that_fails_is_unavailable_never_a_clean_end(
        tmp_path: Path, bench: Bench, monkeypatch) -> None:  # noqa: ANN001
    from ephymeris_sidecar.analytics.stream import live

    recorded = document()
    strobes = recorded["ts_data"]
    real = live.LiveReplay.feed
    calls = {"n": 0}

    def flaky(self, code, ts):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] == 20:
            raise RuntimeError("a bug in the live replay")
        return real(self, code, ts)

    monkeypatch.setattr(live.LiveReplay, "feed", flaky)
    runner, events = make_runner(tmp_path, bench, recorded)
    board = await start(runner, bench, recorded)
    await board.said(*lines(strobes))
    await until(lambda: not runner.running_boxes(), timeout=10)
    await asyncio.sleep(0.2)
    final = replays(events)[-1]
    assert final["status"] == "unavailable" and "a bug in the live replay" in final["detail"]
    assert final["metrics"] == [] and final["overall"] is None and final["phase"] is None
    assert not any(r["status"] == "ended" for r in replays(events))
    runner.close()

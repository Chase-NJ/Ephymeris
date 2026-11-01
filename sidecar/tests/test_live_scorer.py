"""The live scoring process (`sessions/scorer.py`, ARCHITECTURE.md#the-live-scorer).

A spine run's live numbers are a whole replay of its stream so far, tens of ms
at a thousand trials. Run on a thread of the sidecar, that holds the GIL the
session threads need to write and fsync each strobe, so it runs in one child
process for every box: fed deltas, coalesced, and fenced, so its death costs
the live numbers and nothing else.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from ephymeris_sidecar.analytics.stream import live
from ephymeris_sidecar.sessions import scorer as scorer_module
from tests.fixtures import spine as fixture
from tests.test_live_replay import header_of
from tests.test_spine_analytics import go_no_go_animal, simulated_document


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


class Results:
    def __init__(self) -> None:
        self.scored: list[tuple[int, dict]] = []
        self.down: list[str] = []
        self.event = threading.Event()

    def on_result(self, n: int, fields: dict) -> None:
        self.scored.append((n, fields))
        self.event.set()

    def on_down(self, reason: str) -> None:
        self.down.append(reason)
        self.event.set()

    def wait(self, predicate, timeout: float = 20.0) -> None:  # noqa: ANN001
        deadline = time.monotonic() + timeout
        while not predicate():
            assert time.monotonic() < deadline, "timed out"
            self.event.wait(0.05)
            self.event.clear()


@pytest.fixture
def scorer():  # noqa: ANN201
    made = scorer_module.LiveScorer()
    yield made
    made.stop()


def test_a_document_is_scored_in_another_process_as_live_scores_it(scorer) -> None:  # noqa: ANN001
    document = simulated_document(fixture.go_no_go(), go_no_go_animal, trials=6)
    got = Results()
    scorer.submit("k1", header_of(document), document["ts_data"], len(document["ts_data"]),
                  on_result=got.on_result, on_down=got.on_down)
    got.wait(lambda: got.scored)
    n, fields = got.scored[-1]
    assert n == len(document["ts_data"])
    assert fields == live.fields(live.scored(document))
    assert scorer.pid is not None and scorer.pid != os.getpid()


def test_deltas_build_the_stream_and_stale_requests_are_dropped(scorer) -> None:  # noqa: ANN001
    document = simulated_document(fixture.go_no_go(), go_no_go_animal, trials=8)
    strobes = document["ts_data"]
    got = Results()
    sent = 0
    for n in range(10, len(strobes) + 1, 10):
        scorer.submit("k1", header_of(document) if sent == 0 else None, strobes[sent:n], n,
                      on_result=got.on_result, on_down=got.on_down)
        sent = n
    scorer.submit("k1", None, strobes[sent:], len(strobes), on_result=got.on_result, on_down=got.on_down)
    got.wait(lambda: got.scored and got.scored[-1][0] == len(strobes))
    assert got.scored[-1][1] == live.fields(live.scored(document)), "the deltas rebuilt the whole stream"
    assert len(got.scored) < len(strobes) // 10, "a slow score drops the requests that queued behind it"


def test_a_dead_scorer_is_reported_down_and_never_raises(scorer) -> None:  # noqa: ANN001
    document = simulated_document(fixture.go_no_go(), go_no_go_animal, trials=2)
    got = Results()
    scorer.submit("k1", header_of(document), document["ts_data"], len(document["ts_data"]),
                  on_result=got.on_result, on_down=got.on_down)
    got.wait(lambda: got.scored)
    scorer.kill_for_test()
    got.wait(lambda: got.down)
    later = Results()
    scorer.submit("k2", header_of(document), document["ts_data"], 1,
                  on_result=later.on_result, on_down=later.on_down)
    later.wait(lambda: later.down)
    assert later.scored == [] and later.down[0] == "the live scorer stopped"
    assert "unavailable" not in later.down[0], "the reason is the cause: the UI says what it costs"


def test_a_killed_scorer_is_reaped_without_waiting_on_it(scorer) -> None:  # noqa: ANN001
    """Seen dead, it is reaped, not left a zombie until the sidecar exits."""
    document = simulated_document(fixture.go_no_go(), go_no_go_animal, trials=2)
    got = Results()
    scorer.submit("k1", header_of(document), document["ts_data"], len(document["ts_data"]),
                  on_result=got.on_result, on_down=got.on_down)
    got.wait(lambda: got.scored)
    scorer.kill_for_test()
    got.wait(lambda: got.down)
    deadline = time.monotonic() + 10
    while scorer.exitcode_for_test() is None:
        assert time.monotonic() < deadline, "never reaped"
        time.sleep(0.02)
    if hasattr(os, "waitpid"):
        with pytest.raises(ChildProcessError):
            os.waitpid(scorer.pid, os.WNOHANG)  # already reaped: no zombie left to wait for


@pytest.mark.skipif(not hasattr(os, "getpriority"), reason="POSIX niceness")
def test_the_scorer_runs_below_the_sidecar(scorer) -> None:  # noqa: ANN001
    """It yields the CPU to the session threads: a lower priority, set in the
    child at start-up (`ARCHITECTURE.md#the-live-scorer`)."""
    document = simulated_document(fixture.go_no_go(), go_no_go_animal, trials=2)
    got = Results()
    scorer.submit("k1", header_of(document), document["ts_data"], len(document["ts_data"]),
                  on_result=got.on_result, on_down=got.on_down)
    got.wait(lambda: got.scored)
    scorer.wait_ready_for_test()
    ours = os.getpriority(os.PRIO_PROCESS, 0)
    assert os.getpriority(os.PRIO_PROCESS, scorer.pid) >= min(ours + scorer_module.NICENESS, 19)


def test_one_run_is_scored_at_most_once_per_interval(monkeypatch, scorer) -> None:  # noqa: ANN001
    """However fast a box asks, a run's whole replay runs at most once per
    `SCORE_INTERVAL_S`; the latest request still lands."""
    document = simulated_document(fixture.go_no_go(), go_no_go_animal, trials=8)
    strobes = document["ts_data"]
    got = Results()
    times: list[float] = []

    def on_result(n: int, fields: dict) -> None:
        times.append(time.monotonic())
        got.on_result(n, fields)

    sent = 0
    for n in range(5, len(strobes) + 1, 5):
        scorer.submit("k1", header_of(document) if sent == 0 else None, strobes[sent:n], n,
                      on_result=on_result, on_down=got.on_down)
        sent = n
        time.sleep(0.02)
    scorer.submit("k1", None, strobes[sent:], len(strobes), on_result=on_result, on_down=got.on_down)
    got.wait(lambda: got.scored and got.scored[-1][0] == len(strobes))
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(gap >= scorer_module.SCORE_INTERVAL_S * 0.9 for gap in gaps), gaps


def test_warming_starts_the_scorer_before_any_request(scorer) -> None:  # noqa: ANN001
    """A mapping with a spine run starts it in set-up, so a box's first strobes
    never meet an interpreter starting up."""
    scorer.warm()
    scorer.wait_ready_for_test()
    assert scorer.pid is not None


def test_a_scorer_that_cannot_start_is_down_at_once(monkeypatch) -> None:  # noqa: ANN001
    def refuse(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise OSError("no processes left")

    monkeypatch.setattr(scorer_module, "_start_process", refuse)
    made = scorer_module.LiveScorer()
    got = Results()
    made.submit("k1", {"x": 1}, [], 0, on_result=got.on_result, on_down=got.on_down)
    got.wait(lambda: got.down)
    assert "no processes left" in got.down[0]
    made.stop()


def test_stopping_never_waits_on_a_busy_scorer() -> None:
    document = simulated_document(fixture.go_no_go(), go_no_go_animal, trials=40, ticks=2_000_000)
    made = scorer_module.LiveScorer()
    got = Results()
    made.submit("k1", header_of(document), document["ts_data"], len(document["ts_data"]),
                on_result=got.on_result, on_down=got.on_down)
    made.wait_started_for_test()
    began = time.monotonic()
    made.stop()
    assert time.monotonic() - began < 0.5
    assert made.process_exited_for_test(timeout=5)


def test_the_scorer_exits_when_the_sidecar_goes_away() -> None:
    """Its request pipe closing is the sidecar gone: the child exits on its own,
    as the sidecar exits on stdin EOF (`ARCHITECTURE.md#process-lifecycle`)."""
    made = scorer_module.LiveScorer()
    got = Results()
    made.submit("k1", {"x": 1}, [], 0, on_result=got.on_result, on_down=got.on_down)
    made.wait_started_for_test()
    made.close_pipe_for_test()
    assert made.process_exited_for_test(timeout=5)

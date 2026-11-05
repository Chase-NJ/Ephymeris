"""Six boxes scored live write their strobes as fast as six boxes not scored
(issue #100, `DATA.md#written-live`, `ARCHITECTURE.md#the-live-scorer`).

Every strobe is fsync'd the moment it arrives. A live score is a whole replay
of the stream so far; on a thread of the sidecar it held the GIL long enough to
put the next strobe's write a second behind. So here six boxes each stream a
long fixed-ratio session, paced, through the real writer and the real live
replay, and each strobe's write-and-fsync is timed from when it was due. With
live scoring on it must stay within twice the figure with it off, plus a floor
of the scheduler's own spread.

On Linux the boxes write to RAM (`/dev/shm`), elsewhere to `tmp_path`. Live
scoring can slow a write only through the GIL and the CPU: the scorer is a child
that touches no file (`ARCHITECTURE.md#the-live-scorer`). A cloud runner's disk
stalls fsyncs by up to a second, scoring or not, and stays that way for minutes
(issue #201), so on it the comparison measured the disk. On RAM the writer, each
write, flush and fsync, and the GIL dropped and retaken around them are as ever;
only the device holds still. Scoring on a thread of the sidecar, or 300 µs of
held GIL per strobe, still puts p99 at least seven times over the bound there.

On a small runner the machine's own noise moves either figure by several times
from one run to the next, which no change here causes. So the two are measured
in alternating rounds, `ROUNDS` of each, and each is read at its median round:
one round the machine disturbed is outvoted on either side, but live scoring
passes only when most of its rounds stay within the budget, so one lucky round
cannot hide a real slowdown. The scorer is checked to run below the sidecar in
every live round.

It runs **alone** (`-m load`, after CI's parallel suite). Beside other tests, their
CPU and, off Linux, their file traffic stall a write by tens to hundreds of ms,
scoring or not, which no statistic over a few rounds sees past.

`EPHYMERIS_LOAD_TRIALS` sets the session length (the review measured 1000);
the default keeps the suite quick. Every board here is a fake: nothing opens
a port.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import statistics
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterator

import pytest

from ephymeris_sidecar.sessions import live_replay
from ephymeris_sidecar.sessions.scorer import LiveScorer
from ephymeris_sidecar.sessions.writer import AnimalWriter
from tests.fixtures import spine as fixture
from tests.test_live_replay import header_of, pressing_animal
from tests.test_spine_analytics import simulated_document

pytestmark = pytest.mark.load

TRIALS = int(os.environ.get("EPHYMERIS_LOAD_TRIALS", "150"))
#: Alternating rounds of each, off then on.
ROUNDS = int(os.environ.get("EPHYMERIS_LOAD_ROUNDS", "3"))
BOXES = 6
#: How often each box strobes: a fast board, faster than any lab task.
EVERY_S = 0.002
#: Linux's RAM file system, where the boxes write when it is there.
RAM = Path("/dev/shm")


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


@pytest.fixture
def root(tmp_path: Path) -> Iterator[Path]:
    """Where the boxes write: RAM on Linux, so the disk is out of the figure."""
    if not (RAM.is_dir() and os.access(RAM, os.W_OK)):
        yield tmp_path
        return
    folder = Path(tempfile.mkdtemp(prefix="ephymeris-load-", dir=RAM))
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def fast_ratio() -> dict:
    return simulated_document(fixture.fixed_ratio(3), pressing_animal, trials=TRIALS,
                              ticks=TRIALS * 2000)


def stream(tmp: Path, box: int, document: dict, feed, lags: list[float]) -> None:  # noqa: ANN001
    writer = AnimalWriter(tmp / f"b{box}.tsv", tmp / f"b{box}.json", tmp / f"b{box}.mat",
                          {"rat": f"r{box}"}, {})
    writer.open_files()
    start = time.monotonic()
    for i, (code, ts) in enumerate(document["ts_data"]):
        due = start + i * EVERY_S
        wait = due - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        writer.record(code, ts)
        lags.append(time.monotonic() - due)
        if feed is not None:
            feed(code, ts)  # after the fsync, as the runner does


async def run(tmp: Path, document: dict, live: bool) -> list[float]:
    loop = asyncio.get_running_loop()
    scorer = LiveScorer() if live else None
    if scorer is not None:
        # As the runner does when a mapping holds a spine run: started in
        # set-up, before the first box strobes (`SessionRunner.configure`).
        scorer.warm()
        scorer.wait_ready_for_test()
    published: list[dict] = []

    async def publish(payload: dict) -> None:
        published.append(payload)

    lags: list[list[float]] = [[] for _ in range(BOXES)]
    threads = []
    for box in range(BOXES):
        feed = None
        if live:
            replay = live_replay.BoxReplay(box + 1, f"a{box}", header_of(document), loop=loop,
                                           publish=publish, scorer=scorer)
            feed = replay.feed
        threads.append(threading.Thread(target=stream, args=(tmp, box, document, feed, lags[box])))
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        await asyncio.sleep(0.01)
    if scorer is not None:
        assert any(p["metrics"] for p in published), "live scoring ran during the load"
        if hasattr(os, "getpriority"):
            # The child yields: below the sidecar, so on a runner with fewer free
            # cores than busy threads the session threads run first.
            assert os.getpriority(os.PRIO_PROCESS, scorer.pid) > os.getpriority(os.PRIO_PROCESS, 0)
        scorer.stop()
    return [lag for box in lags for lag in box]


def summary(lags: list[float]) -> dict[str, float]:
    ordered = sorted(lags)
    return {"p50": statistics.median(ordered), "p99": ordered[int(len(ordered) * 0.99)], "max": ordered[-1]}


async def test_six_boxes_scored_live_write_as_fast_as_six_not(root: Path) -> None:
    document = fast_ratio()
    rounds: dict[str, list[dict[str, float]]] = {"off": [], "on": []}
    for r in range(ROUNDS):
        for mode in ("off", "on"):
            folder = root / f"{mode}{r}"
            folder.mkdir()
            rounds[mode].append(summary(await run(folder, document, live=mode == "on")))
    median = {mode: {k: statistics.median(s[k] for s in runs) for k in ("p50", "p99", "max")}
              for mode, runs in rounds.items()}
    print(f"\n{BOXES} boxes x {len(document['ts_data'])} strobes ({TRIALS} trials), median of {ROUNDS}: "
          f"live off {median['off']}, live on {median['on']}; every round: {rounds}")
    off, on = median["off"], median["on"]
    # The floor: the scheduler's own spread, which on an idle machine is most of either figure.
    assert on["p99"] <= 2 * off["p99"] + 0.005, (off, on)
    assert on["max"] <= 2 * off["max"] + 0.020, (off, on)

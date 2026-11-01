"""Six boxes scored live write their strobes as fast as six boxes not scored
(issue #100, `DATA.md#written-live`, `ARCHITECTURE.md#the-live-scorer`).

Every strobe is fsync'd the moment it arrives. A live score is a whole replay
of the stream so far; on a thread of the sidecar it held the GIL long enough to
put the next strobe's write a second behind. So here six boxes each stream a
long fixed-ratio session, paced, through the real writer and the real live
replay, and each strobe's write-and-fsync is timed from when it was due. With
live scoring on it must stay within twice the figure with it off.

`EPHYMERIS_LOAD_TRIALS` sets the session length (the review measured 1000);
the default keeps the suite quick.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import threading
import time
from pathlib import Path

import pytest

from ephymeris_sidecar.sessions import live_replay
from ephymeris_sidecar.sessions.scorer import LiveScorer
from ephymeris_sidecar.sessions.writer import AnimalWriter
from tests.fixtures import spine as fixture
from tests.test_live_replay import header_of, pressing_animal
from tests.test_spine_analytics import simulated_document

TRIALS = int(os.environ.get("EPHYMERIS_LOAD_TRIALS", "150"))
BOXES = 6
#: How often each box strobes: a fast board, faster than any lab task.
EVERY_S = 0.002


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


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
        scorer.stop()
    return [lag for box in lags for lag in box]


def summary(lags: list[float]) -> dict[str, float]:
    ordered = sorted(lags)
    return {"p50": statistics.median(ordered), "p99": ordered[int(len(ordered) * 0.99)], "max": ordered[-1]}


async def test_six_boxes_scored_live_write_as_fast_as_six_not(tmp_path: Path) -> None:
    document = fast_ratio()
    (tmp_path / "off").mkdir()
    (tmp_path / "on").mkdir()
    off = summary(await run(tmp_path / "off", document, live=False))
    on = summary(await run(tmp_path / "on", document, live=True))
    print(f"\n{BOXES} boxes x {len(document['ts_data'])} strobes ({TRIALS} trials): "
          f"live off {off}, live on {on}")
    # A floor of a few ms: on an idle machine both are well under one.
    assert on["p99"] <= 2 * off["p99"] + 0.005, (off, on)
    assert on["max"] <= 2 * off["max"] + 0.020, (off, on)

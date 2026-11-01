"""A spine run replayed live, strobe by strobe, as Mission Control shows it (issue #100).

`analytics/stream/live.py` feeds each strobe to the same interpreter port
Analytics replays a finished run with (`ANALYTICS.md#live-scoring`). These tests
hold the two to each other on recorded streams: the state the live replay puts
the board in at every tick is offline replay's, and the metrics it reads off
the finished stream are `summarize`'s, exactly. Nothing in it may read a code's
name, so a snapshot whose every code is renamed must replay the same.
"""

from __future__ import annotations

import copy

import pytest

from ephymeris_sidecar.analytics.stream import live
from ephymeris_sidecar.analytics.stream import replay as rp
from ephymeris_sidecar.analytics.stream import spine as spine_stream
from ephymeris_sidecar.analytics.stream.summary import summarize
from ephymeris_sidecar.tasks import profile as task_profile
from tests.fixtures import spine as fixture
from tests.test_spine_analytics import go_no_go_animal, simulated_document, two_afc_animal


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


def header_of(document: dict) -> dict:
    """The run's document as the runner knows it before the first strobe."""
    return {k: v for k, v in document.items() if k not in ("ts_data", "n_events", "stop_reason")}


def offline_states(document: dict) -> list[tuple[int, int]]:
    """(tick, the state the board rests in after it) for every tick offline replay moved."""
    record = spine_stream.decode(document)
    actions, _end = spine_stream._session(record)  # the one replay Analytics runs
    out = []
    for now, a in actions:
        entered = [s for s in a.entered if s != rp.NONE]
        if entered:
            out.append((now, entered[-1]))
    return out


def state_at(states: list[tuple[int, int]], tick: int) -> int:
    return [s for t, s in states if t <= tick][-1]


def pressing_animal(phase, row, ms):  # noqa: ANN001, ARG001
    """Presses the lever every 40 ms, whatever the phase."""
    return 1 if ms % 40 < 20 else 0


DOCUMENTS = {
    "2afc": lambda: simulated_document(fixture.two_afc(), two_afc_animal, trials=8),
    "go/no-go": lambda: simulated_document(fixture.go_no_go(), go_no_go_animal, trials=8),
    "vr": lambda: simulated_document(fixture.variable_ratio(1, 6), pressing_animal, trials=6),
}


@pytest.mark.parametrize("name", DOCUMENTS)
def test_the_live_state_at_every_tick_is_offline_replays(name: str) -> None:
    document = DOCUMENTS[name]()
    offline = offline_states(document)
    strobes = [tuple(s) for s in document["ts_data"]]
    end = strobes[-1][1]
    replay = live.LiveReplay(header_of(document))
    for k, (code, ts) in enumerate(strobes):
        replay.feed(code, ts)
        later = strobes[k + 1][1] if k + 1 < len(strobes) else None
        if later == ts or ts == end:
            continue  # the tick is not closed yet, or the session is over
        # Every tick until the next strobe: the core's own timers, no edge, so
        # what the board did there is what replay says it did.
        upto = later - 1 if later is not None else ts
        for tick in sorted({ts, (ts + upto) // 2, upto}):
            assert replay.at(tick).state == state_at(offline, tick), f"tick {tick}, after strobe {k}"


@pytest.mark.parametrize("name", DOCUMENTS)
def test_the_final_live_metrics_are_analytics_exactly(name: str) -> None:
    document = DOCUMENTS[name]()
    replay = live.LiveReplay(header_of(document))
    for code, ts in document["ts_data"]:
        replay.feed(code, ts)
    assert replay.ended
    scored = live.scored(replay.document())
    offline = summarize(document, None)
    assert scored.status == "ok" and offline.status == "ok"
    assert [m.to_json() for m in scored.metrics] == [m.to_json() for m in offline.metrics]
    assert scored.overall.to_json() == offline.overall.to_json()
    assert scored.score.to_json() == offline.replay.to_json()
    assert [t.to_json() for t in scored.trials] == spine_stream.trial_table(document)["trials"]


def test_a_stream_cut_mid_trial_scores_only_its_complete_trials() -> None:
    document = simulated_document(fixture.go_no_go(), go_no_go_animal, trials=8)
    replay = live.LiveReplay(header_of(document))
    for code, ts in document["ts_data"][: len(document["ts_data"]) // 2]:
        replay.feed(code, ts)
    scored = live.scored(replay.document())
    assert scored.status == "ok"
    assert scored.trials and not scored.trials[-1].complete, "the open trial is in the table, incomplete"
    assert scored.score.trials == len(scored.trials) - 1, "and out of the metrics"


def renamed(document: dict) -> dict:
    """`document` with every code's name changed, consistently, wherever the snapshot says it."""
    out = copy.deepcopy(document)
    snapshot = out[task_profile.SNAPSHOT_KEY]
    names = {name: f"Z{n:03d}" for n, name in enumerate(snapshot["strobes"].values())}

    def walk(value):  # noqa: ANN001, ANN202
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return names.get(value, value) if isinstance(value, str) else value

    out[task_profile.SNAPSHOT_KEY] = walk(snapshot)
    return out


def test_nothing_in_the_live_replay_reads_a_codes_name() -> None:
    document = simulated_document(fixture.two_afc(), two_afc_animal, trials=6)
    other = renamed(document)
    assert "TRIAL_START" not in str(other[task_profile.SNAPSHOT_KEY]), "every name is gone"
    a, b = live.LiveReplay(header_of(document)), live.LiveReplay(header_of(other))
    for code, ts in document["ts_data"]:
        a.feed(code, ts)
        b.feed(code, ts)
        assert a.at(ts) == b.at(ts)
    assert a.ended and b.ended
    one, two = live.scored(a.document()), live.scored(b.document())
    assert [m.to_json() for m in one.metrics] == [m.to_json() for m in two.metrics]
    assert one.score.to_json() == two.score.to_json()


def test_a_diverging_stream_is_scored_as_diverged() -> None:
    document = simulated_document(fixture.go_no_go(), go_no_go_animal, trials=8)
    code_of = {name: int(c) for c, name in document[task_profile.SNAPSHOT_KEY]["strobes"].items()}
    strobes = [list(s) for s in document["ts_data"]]
    # The board opened the reward a tick late: an output replay does not predict.
    k = next(i for i, (c, _) in enumerate(strobes) if c == code_of["FLUID_2_ON"])
    strobes[k][1] += 1
    replay = live.LiveReplay(header_of(document))
    for code, ts in strobes[: k + 1]:
        replay.feed(code, ts)
    scored = live.scored(replay.document())
    assert scored.status == "diverged"
    assert scored.divergence is not None and scored.divergence.index == k
    assert not scored.metrics and scored.score is None, "a diverged run is never scored"


def test_strobes_out_of_order_break_the_live_replay() -> None:
    document = simulated_document(fixture.go_no_go(), go_no_go_animal, trials=4)
    code_of = {name: int(c) for c, name in document[task_profile.SNAPSHOT_KEY]["strobes"].items()}
    replay = live.LiveReplay(header_of(document))
    for code, ts in document["ts_data"][:6]:
        replay.feed(code, ts)
    fed = replay.feed(code_of["ODOR_PORT_ENTER"], 1)
    assert replay.broken and fed.check, "a stream replay cannot be fed is checked at once"
    assert live.scored(replay.document()).status == "diverged"


def test_a_run_replay_cannot_start_is_refused_up_front() -> None:
    document = simulated_document(fixture.go_no_go(), go_no_go_animal, trials=2)
    header = header_of(document)
    header["interp"] = 99
    with pytest.raises(spine_stream.SpineDecodeError):
        live.LiveReplay(header)


def test_the_view_names_the_phase_and_row_from_the_snapshot() -> None:
    document = simulated_document(fixture.two_afc(), two_afc_animal, trials=4)
    table = document[task_profile.SNAPSHOT_KEY]["spine"]["table"]
    rows = [r["id"] for r in document[task_profile.SNAPSHOT_KEY]["spine"]["rows"]]
    replay = live.LiveReplay(header_of(document))
    seen = set()
    for code, ts in document["ts_data"]:
        replay.feed(code, ts)
        # The ITI is entered a tick after the outcome, silently: its timer, no strobe.
        for view in (replay.at(ts), replay.at(ts + 1)):
            assert view.phase == table["phases"][view.state]
            index = table["rows"][view.state]
            assert view.row == (rows[index] if index is not None else None)
            seen.add(view.phase)
    assert seen == {0, 1, 2, 3, 4}, "the token visits every phase"

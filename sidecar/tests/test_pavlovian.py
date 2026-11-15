"""Pavlovian trace and delay conditioning as spine tasks — issue #116, `taskdef/pavlovian.py`.

ADR 0003's first graded paradigm: ITI → Delay(baseline, watching the lick
sensor) → Present(CS, watching licks) → Delay(trace, watching licks) →
Outcome, with no response gate; CS+ and CS− rows. Delay conditioning is the
same spine without the trace. The definition is one place, which the editor's
"trace" seed (#108) can match.
"""

from __future__ import annotations

import json
import os
import shutil

import pytest

from ephymeris_sidecar.analytics.stream import spine as spine_stream
from ephymeris_sidecar.analytics.stream.summary import summarize
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.taskdef import pavlovian
from ephymeris_sidecar.taskdef.model import TaskDefinition
from ephymeris_sidecar.taskdef.validate import validate
from tests.fixtures import spine as fixture


@pytest.fixture(autouse=True)
def _lick_rig():
    fixture.install(*fixture.issued_rig(driven=True, lick=True))
    yield
    fixture.uninstall()


def kinds(spine: list[dict]) -> list[str]:
    return [p["phase"] for p in spine]


def test_the_trace_spine_is_baseline_cs_trace_us_iti_watching_licks():
    seed = pavlovian.phases()
    assert kinds(seed["spine"]) == ["delay", "present", "delay", "outcome", "iti"]
    assert [p.get("watch") for p in seed["spine"]] == [["lick"], ["lick"], ["lick"], ["lick"], None]
    assert seed["spine"][1]["outputs"] == ["cs"] and seed["spine"][3]["line"] == "us"
    assert {s["id"]: s["type"] for s in seed["slots"]} == {"lick": "digital_in", "cs": "tone_out",
                                                          "us": "digital_out"}
    assert not any("response" in p["phase"] for p in seed["spine"]), "no response gate"


def test_delay_conditioning_is_the_same_spine_without_the_trace():
    trace, delay = pavlovian.phases(), pavlovian.phases(trace=False)
    assert kinds(delay["spine"]) == ["delay", "present", "outcome", "iti"]
    assert delay["spine"] == trace["spine"][:2] + trace["spine"][3:]
    assert delay["slots"] == trace["slots"]


def test_a_seed_carries_phases_and_no_names():
    """#108's seed starts a task without bringing back named presets
    (`TASKS.md#what-a-definition-holds`)."""
    assert set(pavlovian.phases()) == {"slots", "spine"}


@pytest.mark.parametrize("trace", [True, False])
def test_the_task_is_clean_on_a_rig_with_a_lick_sensor_and_a_tone(trace):
    raw = pavlovian.definition(trace=trace)
    definition = TaskDefinition.from_json(raw)
    assert validate(definition) == []
    rows = {r.id: r for r in definition.spine.rows}
    assert set(rows) == {"cs_plus", "cs_minus"}
    assert (rows["cs_plus"].name, rows["cs_minus"].name) == ("CS+", "CS−")
    # The US on every CS+ trial, never on a CS− one.
    assert (rows["cs_plus"].reward_permille, rows["cs_minus"].reward_permille) == (1000, 0)
    # One tone, two pitches: each row drives it at its own.
    assert rows["cs_plus"].bind["cs"] == rows["cs_minus"].bind["cs"] == "tone"
    assert rows["cs_plus"].drive["cs"]["hz"] != rows["cs_minus"].drive["cs"]["hz"]
    [block] = definition.spine.blocks
    assert block.select == "bag" and set(block.rows) == set(rows)


def test_a_level_cue_cs_binds_a_channel_per_row():
    raw = pavlovian.definition(cs_plus=pavlovian.Cue("odor_line_1"), cs_minus=pavlovian.Cue("odor_line_2"))
    definition = TaskDefinition.from_json(raw)
    assert validate(definition) == []
    assert {s.id: s.type for s in definition.spine.slots}["cs"] == "digital_out"
    assert [r.bind["cs"] for r in definition.spine.rows] == ["odor_line_1", "odor_line_2"]
    assert all(not r.drive for r in definition.spine.rows)


def test_a_rig_without_a_lick_sensor_is_told_so():
    fixture.install()
    found = {(d.code, d.location) for d in validate(TaskDefinition.from_json(pavlovian.definition()))}
    assert ("SPN101", "rows[0].bind.lick") in found, found


# --- a session, end to end ---------------------------------------------------------


def conditioned_animal() -> str:
    """C++ for a conditioned animal on an active-HIGH lick sensor: a 20 ms lick
    every 500 ms whatever happens (2/s), and from the moment it hears the CS+'s
    pitch until the US line opens, another every 100 ms (10/s more). It reads
    the tone's pitch and the reward line off the board's own pins."""
    pin = {name: registry.channels().get(name).index for name in ("lick_spout", "tone", "fluid_2")}
    return f"""
static bool expecting = false;
static void animal(unsigned long t) {{
  if (bb_tone[{pin['tone']}] == {CS_PLUS_HZ}) expecting = true;
  if (bb_pinValue[{pin['fluid_2']}] == HIGH) expecting = false;
  bool lick = t % 500 < 20 || (expecting && t % 100 >= 50 && t % 100 < 70);
  bb_pinValue[{pin['lick_spout']}] = lick ? HIGH : LOW;
}}
"""


CS_PLUS_HZ = 8000
#: Short phases, so six trials take 22 s of ticks: baseline and CS 1 s each,
#: the trace 500 ms, the US window 300 ms, the ITI 700 ms.
DURATIONS = {"delay_0_ms": 1000, "present_1_ms": 1000, "delay_2_ms": 500, "iti_4_ms": 700}


def overrides(trace: bool) -> dict[str, int]:
    """The run's per-box values, keyed by metadata key (`TASKS.md#lowering`)."""
    if trace:
        return {**DURATIONS, "outcome_3_ms": 300, "block_b1_trials": 6}
    return {"delay_0_ms": 1000, "present_1_ms": 1000, "outcome_2_ms": 300, "iti_3_ms": 700,
            "block_b1_trials": 6}


compiler = shutil.which("clang++") or shutil.which("g++")


@pytest.mark.skipif(compiler is None, reason="no host C++ compiler")
@pytest.mark.skipif(os.name == "nt", reason="as test_spine_run.py's board build: Linux and macOS")
@pytest.mark.parametrize("trace", [True, False], ids=["trace", "delay"])
async def test_a_session_runs_and_replays_with_licks_counted_per_phase(tmp_path, monkeypatch, trace):
    """The saved task's generated folder, compiled for the host, runs a
    conditioned animal; the real session path writes its `.tsv`; replay reads
    the trial table from it. Each trial's lick counts per phase are the lick
    strobes in that phase's span, and the readout says CS+ licks are
    anticipatory and CS− ones are not."""
    from tests import test_spine_run as run

    folder = run.save(tmp_path, pavlovian.definition(trace=trace))
    values = overrides(trace)
    transcript = run.run_board(folder, run.host_lines(folder, values), [], 30000, tmp_path,
                               animal=conditioned_animal())
    assert not any(line.startswith("CLAMPED") for line in transcript)
    tsv = await run.run_session(tmp_path, folder, transcript, monkeypatch, overrides=values)
    document = json.loads(run.json_of(tsv).read_text(encoding="utf-8"))
    assert spine_stream.expected_stream(spine_stream.decode(document)) == [tuple(s) for s in document["ts_data"]]

    table = spine_stream.trial_table(document)["trials"]
    assert len(table) == 6 and {t["row"] for t in table} == {"cs_plus", "cs_minus"}
    assert all(t["rewarded"] == (t["row"] == "cs_plus") for t in table), "the US on CS+ only"

    # Each phase's count is the lick strobes in its span, (entry, next entry].
    lick = registry.vocabulary().code_of("LICK_SPOUT_ENTER")
    licks = [ts for code, ts in document["ts_data"] if code == lick]
    end_of_session = document["ts_data"][-1][1]
    windows = len(pavlovian.phases(trace)["spine"]) - 1
    for k, t in enumerate(table):
        edges = [*t["phaseEntries"], table[k + 1]["atMs"] if k + 1 < len(table) else end_of_session]
        counts = {c["phase"]: c["count"] for c in t["inputCounts"]}
        for p in range(windows):
            assert counts.get(p, 0) == sum(edges[p] < ts <= edges[p + 1] for ts in licks), (k, p)
        assert not any(edges[windows] < ts <= edges[windows + 1] for ts in licks), "the ITI watches nothing"

    summary = summarize(document, None)
    assert summary.status == "ok"
    rate = {(w.row_id, w.phase): w for w in summary.replay.rates}
    cs, last = 1, (2 if trace else 1)
    assert rate[("cs_plus", 0)].rate.mean == pytest.approx(2.0, abs=0.5), "baseline: spontaneous licks only"
    assert rate[("cs_plus", cs)].rate.mean == pytest.approx(12.0, abs=1.0)
    assert rate[("cs_plus", last)].versus.mean == pytest.approx(10.0, abs=1.0)
    assert rate[("cs_minus", cs)].versus.mean == pytest.approx(0.0, abs=1.0)
    assert summary.to_json()["replay"]["rates"][0]["channel"] == "lick_spout"

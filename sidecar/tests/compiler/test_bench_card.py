"""The bench card must be right, because nobody will check it against the table.

That is the whole hazard of a generated reference sheet: an operator holds it next
to a scope and trusts it. A card that printed a plausible-but-wrong pulse width
would send someone chasing a rig fault that does not exist — or worse, would let a
real one pass as expected.

So every figure is checked back against the compiled table, and the card is
checked for the things it must NOT do: print a width for a state that has none,
or omit the reward pulse, which is the one measurement the bench exists for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph.emit.bench import render
from ephymeris_sidecar.taskgraph.graph import NodeType
from ephymeris_sidecar.taskgraph.pipeline import compile_spec
from ephymeris_sidecar.taskgraph.registries import channels, limits
from ephymeris_sidecar.taskgraph.table import DUR_FROM_TRIAL

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, SPEC_DIR, all_specs, spec,
)
SPECS = all_specs()


@pytest.fixture(scope="module", params=[s.stem for s in SPECS])
def card(request):
    t = compile_spec(spec(request.param)).table
    return t, render(t)


def test_every_reward_pulse_appears_with_its_width(card):
    """THE MEASUREMENT THE BENCH EXISTS FOR.

    Pulse width is delivered volume. A card that omitted a port, or printed the
    wrong number, would be worse than no card.
    """
    t, text = card
    section = text[text.index("2 · REWARD PULSE"):text.index("3 · FIXED DURATIONS")]
    for p in t.ports:
        assert p.name in section, f"port {p.name!r} missing from the card"
        if p.reward_line == 0xFF:
            continue
        row = next(ln for ln in section.splitlines() if ln.strip().startswith(p.name))
        assert str(p.reward_line) in row, f"{p.name}: wrong or missing line pin"
        assert f"{t.timing[p.reward_dur_idx]} ms" in row, f"{p.name}: wrong width"
        assert t.timing_ids[p.reward_dur_idx] in row, f"{p.name}: no provenance"


def test_no_width_is_printed_for_a_state_that_has_none(card):
    """A HOLD does not last its duration, it requires it; a WAIT_EXIT has no
    duration at all. Printing either as an expected trace width would send
    someone chasing a discrepancy that is the animal."""
    t, text = card
    fixed = text[text.index("3 · FIXED DURATIONS"):text.index("4 · THRESHOLDS")]
    for i, n in enumerate(t.nodes):
        if n.type is NodeType.DELAY:
            continue
        assert f"S{i:02d} " not in fixed, (
            f"S{i:02d} is a {n.type} and must not appear as a fixed duration"
        )

    paced = text[text.index("5 · SUBJECT-PACED"):text.index("6 · WHAT A DISAGREEMENT")]
    #: STATE ROWS only. The watchdog ceiling legitimately appears in this section
    #: in prose -- it is the one checkable thing about an unbounded state -- and an
    #: assertion that banned "ms" outright flagged it. What must not happen is a
    #: state being given a width to compare against.
    for row in re.findall(r"^  S\d\d.*$", paced, re.M):
        assert " ms" not in row, f"a subject-paced state was given a width: {row!r}"
    for i in t.unbounded_nodes():
        assert f"S{i:02d}" in paced


def test_every_fixed_duration_matches_the_table(card):
    t, text = card
    fixed = text[text.index("3 · FIXED DURATIONS"):text.index("4 · THRESHOLDS")]
    for m in re.finditer(r"^  S(\d\d)\s+.*?(\d+) ms\s+(\S+)$", fixed, re.M):
        i, ms, tid = int(m.group(1)), int(m.group(2)), m.group(3)
        n = t.nodes[i]
        assert n.type is NodeType.DELAY
        assert n.dur_idx != DUR_FROM_TRIAL
        assert t.timing[n.dur_idx] == ms, f"S{i:02d}: card says {ms}, table says {t.timing[n.dur_idx]}"
        assert t.timing_ids[n.dur_idx] == tid


def test_every_probe_point_is_a_real_output_channel(card):
    """A card naming a pin the box does not drive would have someone probing an
    unconnected header for an afternoon."""
    t, text = card
    chans = channels()
    probe = text[text.index("1 · WHERE TO PROBE"):text.index("2 · REWARD PULSE")]
    by_index = {c.index: c for c in chans}

    rows = re.findall(r"^  (\w+)\s+(\d+)\s+(\w+)", probe, re.M)
    assert rows, "the card lists no probe points at all"
    for name, pin, kind in rows:
        c = by_index.get(int(pin))
        assert c is not None and c.name == name, f"{name}/{pin} is not a declared channel"
        assert c.kind == kind
        assert c.direction == "out"

    #: Every line the table can drive must be on the card. A missing one is a
    #: channel nobody thinks to probe.
    driven = {a.channel for a in t.actions if a.channel < 0xF0}
    driven |= {p.reward_line for p in t.ports if p.reward_line != 0xFF}
    driven |= {s.emitter for s in t.stimuli}
    listed = {int(pin) for _, pin, _ in rows}
    assert driven <= listed, f"channels driven but not on the card: {sorted(driven - listed)}"


def test_the_watchdog_ceiling_is_the_real_one(card):
    _, text = card
    paced = text[text.index("5 · SUBJECT-PACED"):]
    if "None —" in paced:
        return
    assert str(limits().TG_WATCHDOG_CEILING_MS) in paced


def test_the_card_says_what_it_is_not_for(card):
    """The card is a reference sheet for a bench, and the sketch it describes has
    never been on one. If that warning ever goes missing, it goes missing from the
    one document an operator reads while holding a probe."""
    _, text = card
    assert "NOT FOR ANIMAL USE" in text
    assert text.count("spec ") >= 1, "the card must name the spec hash it describes"


def test_the_cli_renders_it():
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "ephymeris_sidecar.taskgraph.cli", "bench", str(spec("grgl_2odor"))],
        cwd=REPO_ROOT / "sidecar", capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "BENCH CARD" in r.stdout
    assert "REWARD PULSE" in r.stdout

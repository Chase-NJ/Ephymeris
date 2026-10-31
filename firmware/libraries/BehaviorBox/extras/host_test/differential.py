"""Hold BoxInterp.h and replay.py equal: the differential test (run_diff.sh).

Generates state tables (lowered spines of the first phases, and raw tables
that stress the format), randomized input logs with simultaneous edges, seeds
and start times near the millis() wrap. Runs every case through the C core
(`interp_driver`, stepping every tick as a board does) and through the Python
replay (jumping between edges and timers), and fails on the first tick where
their actions differ.

Then it checks itself: with the Python tie rule deliberately changed, the same
cases must differ. A differential test that cannot see a changed tie rule is
generating too few ties to be trusted.

Usage:  python3 differential.py --driver ./interp_driver [--cases N] [--seed S]
"""

from __future__ import annotations

import argparse
import importlib.util
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPLAY = HERE.parents[4] / "sidecar" / "ephymeris_sidecar" / "analytics" / "stream" / "replay.py"


def load_replay():
    """replay.py by path: it imports only the standard library, so no sidecar install is needed."""
    spec = importlib.util.spec_from_file_location("replay", REPLAY)
    module = importlib.util.module_from_spec(spec)
    sys.modules["replay"] = module
    spec.loader.exec_module(module)
    return module


rp = load_replay()
NONE, RISE, FALL = rp.NONE, rp.RISE, rp.FALL


# --- tables -------------------------------------------------------------------


def raw_table(rng: random.Random, n_params: int) -> rp.Table:
    """Any valid table: every field, ties between up to four exits, chance states."""
    n = rng.randint(2, 8)
    chance = [i > 0 and rng.random() < 0.2 for i in range(n)]
    plain = [i for i in range(n) if not chance[i]]
    inputs = [0, 1, 2, 3] + ([31] if rng.random() < 0.2 else [])
    states, edges = [], []
    for i in range(n):
        if chance[i]:
            states.append(rp.StateRow(chance=rng.randrange(n_params), on_hit=rng.choice(plain),
                                      on_miss=rng.choice(plain), flags=rng.choice((0, rp.STARTS_TRIAL)),
                                      outcome=rng.randrange(8)))
            continue
        watch_list = [c for c in inputs if rng.random() < 0.6]
        exits = [(c, e) for c in watch_list for e in (RISE, FALL) if rng.random() < 0.5]
        rng.shuffle(exits)
        first = len(edges)
        edges.extend(rp.EdgeRow(c, e, rng.randrange(n)) for c, e in exits)
        timed = rng.random() < 0.8 or not exits
        lo, hi = rng.randrange(n_params), rng.randrange(n_params)
        states.append(rp.StateRow(
            outputs=rng.getrandbits(32) if rng.random() < 0.3 else rng.getrandbits(6),
            watch=sum(1 << c for c in watch_list),
            timer_min=lo if timed else NONE,
            timer_max=hi if timed else NONE,
            on_timeout=rng.randrange(n) if timed else NONE,
            edge_first=first if exits else 0,
            edge_count=len(exits),
            flags=rng.choice((0, rp.STARTS_TRIAL)),
            outcome=rng.randrange(8),
        ))
    return rp.Table(states=tuple(states), edges=tuple(edges))


PORT, LEFT, RIGHT = 0, 1, 2       # inputs
LIGHT, FLUID_L, FLUID_R = 0, 5, 6  # outputs; odors are 1-4


def spine_table(rng: random.Random, n_params: int) -> rp.Table:
    """A random spine of Wait, Present, Delay and Outcome phases ending in an ITI,
    lowered as BoxInterp.h's "Lowering the first phases" describes. Every abort
    and timeout goes to the ITI, the last state."""
    phases = [rng.choice(("wait", "present", "delay", "outcome")) for _ in range(rng.randint(1, 5))]
    phases.insert(0, "wait")
    slot = lambda: rng.randrange(n_params)  # noqa: E731
    states: list[dict] = []
    edges: list[tuple[int, int, int, str]] = []  # (state, input, edge, "next" | "iti")
    light = 1 << LIGHT
    for p in phases:
        i = len(states)
        if p == "wait":
            c = rng.choice((PORT, LEFT, RIGHT))
            row = dict(outputs=light if rng.random() < 0.7 else 0, watch=1 << c)
            edges.append((i, c, RISE, "next"))
            if rng.random() < 0.6:
                t = slot()
                row.update(timer_min=t, timer_max=t, on_timeout="iti")
            states.append(row)
        elif p == "present":
            t = slot()
            row = dict(outputs=light | 1 << rng.randint(1, 4), watch=0, timer_min=t, timer_max=t, on_timeout="next")
            if rng.random() < 0.5:   # or on an edge
                c = rng.choice((LEFT, RIGHT))
                row["watch"] |= 1 << c
                edges.append((i, c, RISE, "next"))
            if rng.random() < 0.5:   # abort if the hold is lost
                row["watch"] |= 1 << PORT
                edges.append((i, PORT, FALL, "iti"))
            states.append(row)
        elif p == "delay":
            lo, hi = slot(), slot()
            row = dict(timer_min=lo, timer_max=hi, on_timeout="next", watch=0)
            if rng.random() < 0.5:   # abort on an edge
                c = rng.choice((PORT, LEFT, RIGHT))
                row["watch"] = 1 << c
                edges.append((i, c, rng.choice((RISE, FALL)), "iti"))
            if rng.random() < 0.3:   # watched only: licks counted, no exit
                row["watch"] |= 1 << rng.choice((LEFT, RIGHT))
            states.append(row)
        else:  # outcome: chance -> reward -> class timeout
            ms, timeout = slot(), slot()
            states.append(dict(chance=slot(), on_hit=i + 1, on_miss=i + 2, outcome=rng.randint(1, 8)))
            states.append(dict(outputs=1 << rng.choice((FLUID_L, FLUID_R)), timer_min=ms, timer_max=ms, on_timeout=i + 2))
            states.append(dict(timer_min=timeout, timer_max=timeout, on_timeout="next"))
    iti = len(states)
    t = slot()
    states.append(dict(timer_min=t, timer_max=t, on_timeout=0))
    states[0]["flags"] = rp.STARTS_TRIAL

    def resolve(i: int, v):
        return i + 1 if v == "next" else iti if v == "iti" else v

    rows, edge_rows = [], []
    for i, row in enumerate(states):
        mine = [(c, e, resolve(i, nxt)) for s, c, e, nxt in edges if s == i]
        row = {k: resolve(i, v) if k == "on_timeout" else v for k, v in row.items()}
        if mine:
            row.update(edge_first=len(edge_rows), edge_count=len(mine))
            edge_rows.extend(rp.EdgeRow(c, e, n) for c, e, n in mine)
        rows.append(rp.StateRow(**row))
    return rp.Table(states=tuple(rows), edges=tuple(edge_rows))


# --- cases --------------------------------------------------------------------


def params_for(rng: random.Random, n: int) -> list[int]:
    """Durations of a few ms to a few hundred, and probabilities around 0-1000 permille."""
    out = []
    for _ in range(n):
        r = rng.random()
        out.append(rng.randint(0, 3) if r < 0.15 else
                   rng.randint(0, 60) if r < 0.6 else
                   rng.randint(0, 1100) if r < 0.97 else
                   0xFFFFFFFF)   # a span that wraps to a draw over 0
    return out


def input_log(rng: random.Random, ticks: int, inputs: list[int]) -> list[tuple[int, int, int]]:
    """(offset, rose, fell) per tick with an edge; levels stay consistent, and
    two or more inputs often change in the same tick."""
    level = {c: rng.random() < 0.5 for c in inputs}
    out, offset = [], 0
    while True:
        offset += rng.choice((1, 1, 2, 3, 5, 8, 13, 30, 80))
        if offset > ticks:
            return out
        k = rng.choice((1, 1, 2, 2, 3, 4))
        rose = fell = 0
        for c in rng.sample(inputs, min(k, len(inputs))):
            level[c] = not level[c]
            if level[c]:
                rose |= 1 << c
            else:
                fell |= 1 << c
        out.append((offset, rose, fell))


def make_cases(seed: int, count: int) -> list[dict]:
    rng = random.Random(seed)
    cases = []
    for i in range(count):
        n_params = rng.randint(2, 6)
        table = (spine_table if i % 2 else raw_table)(rng, n_params)
        params = params_for(rng, n_params)
        r = rng.random()
        start = 0 if r < 0.4 else 0xFFFFFFFF - rng.randint(0, 3000) if r < 0.7 else rng.getrandbits(32)
        session_seed = rng.choice((1, 0, 0x80000000, 0xFFFFFFFF)) if rng.random() < 0.1 else rng.randint(1, 2**31 - 2)
        ticks = rng.randint(200, 5000)
        log = input_log(rng, ticks, [0, 1, 2, 3, 31])
        cases.append(dict(table=table, params=params, seed=session_seed, start=start, ticks=ticks, log=log))
    return cases


def encode(cases: list[dict]) -> str:
    lines = []
    for c in cases:
        t: rp.Table = c["table"]
        lines.append(f"CASE {len(t.states)} {len(t.edges)} {len(c['params'])} {c['seed']} {c['start']} {c['ticks']} {len(c['log'])}")
        for s in t.states:
            lines.append(" ".join(str(v) for v in (s.outputs, s.watch, s.timer_min, s.timer_max, s.on_timeout, s.chance,
                                                   s.on_hit, s.on_miss, s.edge_first, s.edge_count, s.flags, s.outcome)))
        lines.extend(f"{e.input} {e.edge} {e.next}" for e in t.edges)
        lines.append(" ".join(map(str, c["params"])))
        lines.extend(f"{o} {r} {f}" for o, r, f in c["log"])
    return "\n".join(lines) + "\n"


def run_c(driver: str, cases: list[dict]) -> tuple[int, list[list[tuple[int, ...]]]]:
    out = subprocess.run([driver], input=encode(cases), capture_output=True, text=True, check=True).stdout.split("\n")
    version = int(out[0].split()[1])
    runs, current = [], None
    for line in out[1:]:
        if line == "CASE":
            current = []
        elif line == "END":
            runs.append(current)
        elif line:
            current.append(tuple(int(v) for v in line.split()))
    return version, runs


def run_python(case: dict) -> list[tuple[int, ...]]:
    start = case["start"]
    events = [((start + o) & 0xFFFFFFFF, rp.Edges(r, f)) for o, r, f in case["log"]]
    run = rp.replay(case["table"], case["params"], case["seed"], events, case["ticks"], start=start)
    return [(now, a.rose, a.fell, a.on, a.off, a.entered[0], a.entered[1], a.flags) for now, a in run]


FIELDS = ("now", "rose", "fell", "on", "off", "entered0", "entered1", "flags")


def first_difference(c_runs, cases) -> str | None:
    for i, (c_run, case) in enumerate(zip(c_runs, cases)):
        py_run = run_python(case)
        for j in range(max(len(c_run), len(py_run))):
            c = c_run[j] if j < len(c_run) else None
            p = py_run[j] if j < len(py_run) else None
            if c != p:
                show = lambda r: "nothing" if r is None else dict(zip(FIELDS, r))  # noqa: E731
                return (f"case {i}, action {j}:\n  C:      {show(c)}\n  Python: {show(p)}\n"
                        f"  table:  {case['table']}\n  params: {case['params']} seed {case['seed']} start {case['start']}")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", required=True)
    ap.add_argument("--cases", type=int, default=600)
    ap.add_argument("--seed", type=int, default=97)
    args = ap.parse_args()

    cases = make_cases(args.seed, args.cases)
    version, c_runs = run_c(args.driver, cases)
    if version != rp.INTERP_VERSION:
        print(f"differential: the C core is INTERP {version}, the replay runs {sorted(rp.INTERP_VERSIONS)}")
        return 1
    if len(c_runs) != len(cases):
        print(f"differential: the driver ran {len(c_runs)} of {len(cases)} cases")
        return 1

    diff = first_difference(c_runs, cases)
    if diff:
        print("differential: the C core and the Python replay differ at", diff)
        return 1
    actions = sum(len(r) for r in c_runs)

    # The test must be able to fail: pick the matching exits in reverse order,
    # drawing exactly as before, and the same cases must now differ somewhere.
    honest = rp._break_tie

    def reversed_tie(rng, matching):
        taken, rng = honest(rng, matching)
        return matching[len(matching) - 1 - matching.index(taken)], rng

    rp._break_tie = reversed_tie
    try:
        caught = first_difference(c_runs, cases)
    finally:
        rp._break_tie = honest
    if not caught:
        print("differential: a reversed tie rule went unnoticed; the cases hold too few ties")
        return 1

    print(f"differential: {len(cases)} cases, {actions} actions equal; a changed tie rule is caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())

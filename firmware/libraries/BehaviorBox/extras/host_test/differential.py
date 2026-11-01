"""Hold BoxInterp.h and replay.py equal: the differential test (run_diff.sh).

Generates state tables (spines lowered by the generator itself,
`taskdef/lowering.py`, with every phase of the palette: Holds, Waits on either
edge, aborts on either edge, Counters over a fixed, drawn or progressive N,
Response windows, contingency maps and several rows; spines of the first
phases lowered here; and raw tables that stress the format, pick, counter and
last-trial states included), randomized input logs with simultaneous edges,
seeds and start times near the millis() wrap. Runs every case through the C core
(`interp_driver`, stepping every tick as a board does) and through the Python
replay (jumping between edges and timers), and fails on the first tick where
their actions differ.

Then it checks itself: with the Python tie rule deliberately changed, the same
cases must differ. A differential test that cannot see a changed tie rule is
generating too few ties to be trusted. So too a changed pick draw, which the
raw tables and the generator's tables must each see. And with every RNG draw
reflected, the generator's tables alone must differ, through their chance and
pick states. And a counter that exits one rise late, or a progressive step that
never advances, must each be seen by both the raw and the generator's tables.

Last, PULSE TRAINS: the C side steps `interp_train_high()` on every tick of a
train, as a board drives one, and replay works each pulse out by arithmetic
(`replay.train_pulses`); every edge's tick must agree, over every rate from 1
to 100 Hz. With replay's rises rounded up instead of down, they must differ.

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
SIDECAR = HERE.parents[4] / "sidecar" / "ephymeris_sidecar"
REPLAY = SIDECAR / "analytics" / "stream" / "replay.py"
LOWERING = SIDECAR / "taskdef" / "lowering.py"


def load(name: str, path: Path):
    """A module by path: replay.py and lowering.py import only the standard
    library, so no sidecar install is needed."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rp = load("replay", REPLAY)
lowering = load("lowering", LOWERING)
NONE, RISE, FALL = rp.NONE, rp.RISE, rp.FALL


# --- tables -------------------------------------------------------------------


def raw_table(rng: random.Random, n_params: int) -> rp.Table:
    """Any valid table: every field, ties between up to four exits, chance states,
    pick states of one to four branches (state 0 often one, as a block of
    several rows lowers), counter states over a fixed, drawn or progressive N,
    and last-trial states."""
    n = rng.randint(3, 8)
    kind = ["pick" if rng.random() < (0.5 if i == 0 else 0.15) else
            "chance" if i > 0 and rng.random() < 0.2 else
            "count" if rng.random() < 0.25 else "plain" for i in range(n)]
    if kind.count("plain") < 2:
        kind[-2:] = ["plain", "plain"]
    plain = [i for i in range(n) if kind[i] in ("plain", "count")]
    inputs = [0, 1, 2, 3] + ([31] if rng.random() < 0.2 else [])
    states, edges = [], []
    for i in range(n):
        if kind[i] == "pick":
            branches = [rng.choice(plain) for _ in range(rng.choice((1, 2, 2, 3, 4)))]
            first = len(edges)
            edges.extend(rp.EdgeRow(0, 0, b) for b in branches)
            states.append(rp.StateRow(edge_first=first, edge_count=len(branches),
                                      flags=rp.PICK | rng.choice((0, rp.STARTS_TRIAL)), outcome=rng.randrange(8)))
            continue
        if kind[i] == "chance":
            states.append(rp.StateRow(chance=rng.randrange(n_params), on_hit=rng.choice(plain),
                                      on_miss=rng.choice(plain), flags=rng.choice((0, rp.STARTS_TRIAL)),
                                      outcome=rng.randrange(8)))
            continue
        if kind[i] == "count":
            # One counted rise; often more inputs watched, whose edges move nothing.
            c = rng.choice(inputs)
            first = len(edges)
            edges.append(rp.EdgeRow(c, RISE, rng.randrange(n)))
            timed = rng.random() < 0.7
            t = rng.randrange(n_params)
            states.append(rp.StateRow(
                outputs=rng.getrandbits(6),
                watch=1 << c | (1 << rng.choice(inputs) if rng.random() < 0.4 else 0),
                timer_min=t if timed else NONE,
                timer_max=t if timed else NONE,
                on_timeout=rng.randrange(n) if timed else NONE,
                edge_first=first,
                edge_count=1,
                flags=rp.COUNT | rng.choice((0, rp.STARTS_TRIAL, rp.LAST_TRIAL)),
                outcome=rng.randrange(8),
            ))
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
            flags=rng.choice((0, 0, rp.STARTS_TRIAL, rp.LAST_TRIAL)),
            outcome=rng.randrange(8),
        ))
    counter = None
    if "count" in kind:
        source = rng.choice(("fixed", "drawn", "ratios"))
        if source == "ratios":
            counter = rp.Counter(ratios=tuple(rng.randint(1, 6) for _ in range(rng.randint(1, 5))))
        else:
            lo = rng.randrange(n_params)
            counter = rp.Counter(count_min=lo, count_max=lo if source == "fixed" else rng.randrange(n_params))
    return rp.Table(states=tuple(states), edges=tuple(edges), counter=counter)


PORT, LEFT, RIGHT = 0, 1, 2       # inputs
LIGHT, FLUID_L, FLUID_R = 0, 5, 6  # outputs; odors are 1-4


def spine_table(rng: random.Random, n_params: int) -> rp.Table:
    """A random spine of Wait, Present, Delay and Outcome phases ending in an ITI,
    written here by hand as raw states, not by the generator: every abort and
    timeout goes to the one ITI, the last state, with no end. The generator's
    own tables, ends included, are `generated_table`'s."""
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


def generated_table(rng: random.Random, n_params: int) -> tuple[rp.Table, int, int]:
    """A random spine DEFINITION, lowered by the generator's own `lowering.lower()`:
    the tables a saved spine task compiles into its `TaskSpine.h`. One to three
    rows, each binding some slots to a channel of its own and some to a shared
    one; often a Response window with a contingency map per row, holds and a
    line on some entries; some outputs driven, a bit per row. Returns the table, how many parameter slots it reads
    (which the generator decides) and how many input bits it has."""
    del n_params  # lowering assigns the slots
    inputs = [f"in{i}" for i in range(rng.randint(1, 4))]
    outputs = [f"out{j}" for j in range(rng.randint(1, 6))]
    n_rows = rng.choice((1, 1, 2, 2, 3))
    classes = lowering.OUTCOME_CLASSES

    def some_outputs():
        return rng.sample(outputs, rng.randint(0, min(3, len(outputs))))

    counted = [False]  # a spine has at most one Counter

    def plain_phase(kinds):
        kind = rng.choice(kinds)
        if kind == "counter" and counted[0]:
            kind = "hold"
        p = {"phase": kind, "outputs": some_outputs()}
        if kind == "wait":
            p["on"] = rng.choice(inputs)
            if rng.random() < 0.4:
                p["edge"] = "exit"
            if rng.random() < 0.5:
                p["timeoutMs"] = 1
        elif kind == "hold":
            p["on"] = rng.choice(inputs)
        elif kind in ("present", "delay"):
            if rng.random() < 0.5:
                p["abortOnRelease"] = rng.choice(inputs)
            if rng.random() < 0.3:
                p["abortOnEnter"] = rng.choice(inputs)
        elif kind == "counter":
            counted[0] = True
            p["on"] = rng.choice(inputs)
            source = rng.choice(("fixed", "drawn", "ratios"))
            if source == "ratios":
                p["ratios"] = [rng.randint(1, 6) for _ in range(rng.randint(1, 5))]
            else:
                p["count"] = 1
                if source == "drawn":
                    p["countMax"] = 1
            if rng.random() < 0.6:
                p["timeoutMs"] = 1
                p["endsSession"] = rng.random() < 0.5
        elif kind == "outcome":
            p["line"] = rng.choice(outputs)
        return p

    phases = []
    palette = ("wait", "hold", "present", "delay", "counter", "counter")
    for n in range(rng.randint(0 if rng.random() < 0.6 else 1, 4)):
        # With several rows a pick branch never lands on an Outcome's chance state.
        first = n == 0 and n_rows > 1
        phases.append(plain_phase(palette if first else (*palette, "outcome")))
    window = None
    if rng.random() < 0.6 or not phases:
        window = {"phase": "response", "responses": rng.sample(inputs, rng.randint(1, len(inputs))),
                  "ms": 1, "outputs": some_outputs()}
        if rng.random() < 0.6:
            window["holdMs"] = 1
        phases.append(window)
        post = [plain_phase(("present", "delay")) for _ in range(rng.choice((0, 0, 1, 2)))]
        post.insert(rng.randint(0, len(post)), {"phase": "outcome", "ms": 1, "outputs": some_outputs()})
        phases.extend(post)
    phases.append({"phase": "iti", "outputs": some_outputs() if rng.random() < 0.2 else []})

    rows = []
    for r in range(n_rows):
        bind = {slot: slot if rng.random() < 0.5 else f"{slot}@{r}" for slot in (*inputs, *outputs)}
        row = {"id": f"r{r}", "bind": bind}
        if window is not None:
            entries = {}
            for key in (*window["responses"], lowering.TIMEOUT):
                entry = {"outcome": rng.choice(classes)}
                if rng.random() < 0.5:
                    entry["line"] = rng.choice(outputs)
                if key != lowering.TIMEOUT and "holdMs" in window and rng.random() < 0.5:
                    entry["hold"] = True
                entries[key] = entry
            row["map"] = entries
        rows.append(row)
    # Some outputs driven (PWM, tone, a train): a bit per row rather than per channel.
    drives = {o: rng.choice(tuple(lowering.DRIVE_PARAMS)) for o in outputs if rng.random() < 0.3}
    low = lowering.lower(phases, inputs=inputs, outputs=outputs, rows=rows, drives=drives)
    table = rp.Table(states=[rp.StateRow(*s) for s in low.states], edges=[rp.EdgeRow(*e) for e in low.edges],
                     counter=rp.Counter(*low.counter) if low.counter is not None else None)
    return table, len(low.params), len(low.inputs)


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
        bits = [0, 1, 2, 3, 31]
        if i % 3 == 2:
            table, n_params, n_inputs = generated_table(rng, n_params)
            bits = list(range(n_inputs))
        else:
            table = (spine_table if i % 3 else raw_table)(rng, n_params)
        params = params_for(rng, n_params)
        if table.counter is not None:
            # N small enough to be reached, now and then 0 or past a uint16_t.
            for slot in table.counter.slots:
                params[slot] = rng.choice((0, 1, 2, 3, 4, 5, 6, 0x10002)) if rng.random() < 0.9 else rng.randint(0, 60)
        r = rng.random()
        start = 0 if r < 0.4 else 0xFFFFFFFF - rng.randint(0, 3000) if r < 0.7 else rng.getrandbits(32)
        session_seed = rng.choice((1, 0, 0x80000000, 0xFFFFFFFF)) if rng.random() < 0.1 else rng.randint(1, 2**31 - 2)
        ticks = rng.randint(200, 5000)
        log = input_log(rng, ticks, bits)
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
        k = t.counter
        lines.append("0 255 255 0" if k is None else
                     " ".join(map(str, (1, k.count_min, k.count_max, len(k.ratios), *k.ratios))))
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


# --- pulse trains -------------------------------------------------------------


def train_cases(seed: int, count: int) -> list[tuple[int, int, int]]:
    """(hz, width, length) trains: every rate from 1 to 100 Hz, rates that do not
    divide 1000 often, widths up to and past the gap to the next rise, lengths
    that end mid-pulse and across several seconds. The first is the ADR's opto
    row, 20 Hz, 5 ms, 1 s."""
    rng = random.Random(seed)
    out = [(20, 5, 1000)]
    for i in range(count):
        hz = i % 100 + 1 if i < 100 else rng.choice((3, 7, 9, 11, 13, 17, 30, 33, 47, 99, rng.randint(1, 100)))
        period = 1000 // hz
        r = rng.random()
        width = (rng.randint(1, max(1, period - 1)) if r < 0.8 else
                 rng.randint(period, period + 20) if r < 0.95 else rng.choice((0, 999)))
        length = rng.choice((rng.randint(1, 3000), rng.randint(1, 60) * 50, 1000 * rng.randint(1, 4)))
        out.append((hz if rng.random() > 0.01 else 0, width, length))
    return out


def run_c_trains(driver: str, trains: list[tuple[int, int, int]]) -> list[list[tuple[int, int]]]:
    text = "".join(f"TRAIN {hz} {w} {n}\n" for hz, w, n in trains)
    out = subprocess.run([driver], input=text, capture_output=True, text=True, check=True).stdout.split("\n")
    runs, current = [], None
    for line in out[1:]:
        if line == "TRAIN":
            current = []
        elif line == "END":
            runs.append(current)
        elif line:
            current.append(tuple(int(v) for v in line.split()))
    return runs


def python_train_edges(hz: int, width: int, length: int) -> list[tuple[int, int]]:
    """`replay.train_pulses` as the driver prints it: each pulse's rise and fall."""
    return [edge for rise, fall in rp.train_pulses(hz, width, length) for edge in ((rise, 1), (fall, 0))]


def first_train_difference(c_runs, trains) -> str | None:
    for (hz, width, length), c in zip(trains, c_runs):
        p = python_train_edges(hz, width, length)
        if c != p:
            at = next((i for i, (a, b) in enumerate(zip(c, p)) if a != b), min(len(c), len(p)))
            return (f"train {hz} Hz, {width} ms wide, {length} ticks: edge {at}\n"
                    f"  C:      {c[at:at + 4]}\n  Python: {p[at:at + 4]}")
    return None


def check_trains(driver: str, seed: int) -> int:
    """The C pulse train and replay's reconstruction agree on every edge's tick,
    and a rise rounded up instead of down is caught."""
    trains = train_cases(seed, 400)
    c_runs = run_c_trains(driver, trains)
    if len(c_runs) != len(trains):
        print(f"differential: the driver ran {len(c_runs)} of {len(trains)} trains")
        return 1
    diff = first_train_difference(c_runs, trains)
    if diff:
        print("differential: the C pulse train and replay's train_pulses differ at", diff)
        return 1
    opto = c_runs[0]
    if opto[:4] != [(0, 1), (5, 0), (50, 1), (55, 0)] or len(opto) != 40 or opto[-1] != (955, 0):
        print(f"differential: a 20 Hz, 5 ms, 1 s train is not 20 pulses 50 ms apart: {opto[:6]} ...")
        return 1

    honest = rp._rise
    rp._rise = lambda j, hz: -(-j * 1000 // hz)  # noqa: E731 - rounds up
    try:
        caught = first_train_difference(c_runs, trains)
    finally:
        rp._rise = honest
    if not caught:
        print("differential: a train whose rises round up went unnoticed; the trains hold too few rates "
              "that do not divide 1000")
        return 1
    edges = sum(len(r) for r in c_runs)
    print(f"differential: {len(trains)} pulse trains, {edges} edges equal; a changed rise is caught")
    return 0


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

    # A pick state's draw, the same way: take the branch mirrored from the one
    # drawn (k -> n-1-k), drawing exactly as before. Raw tables and the
    # generator's tables of several rows must each see it.
    honest_pick = rp._pick

    def mirrored_pick(rng, branches):
        k, rng = honest_pick(rng, branches)
        return branches - 1 - k, rng

    rp._pick = mirrored_pick
    try:
        for name, family in (("raw", [i for i in range(len(cases)) if i % 3 == 0]),
                             ("generated", [i for i in range(len(cases)) if i % 3 == 2])):
            if not first_difference([c_runs[i] for i in family], [cases[i] for i in family]):
                print(f"differential: a changed pick draw went unnoticed on the {name} tables; they "
                      "reach too few pick states")
                return 1
    finally:
        rp._pick = honest_pick

    # The generator's tables have ties only in a window of several responses,
    # so the tie check above leans on the raw tables. Their own check: with
    # every RNG draw reflected (k -> n-1-k), the generated cases alone must now
    # differ, through their chance and pick states.
    family = [i for i in range(len(cases)) if i % 3 == 2]
    honest_draw = rp.draw

    def reflected(ctx, n):
        value, ctx = honest_draw(ctx, n)
        return ((n & 0xFFFFFFFF) - 1 - value if n & 0xFFFFFFFF else value), ctx

    rp.draw = reflected
    try:
        caught = first_difference([c_runs[i] for i in family], [cases[i] for i in family])
    finally:
        rp.draw = honest_draw
    if not caught:
        print("differential: a changed draw went unnoticed on the generator's tables; they reach "
              "too few chance states")
        return 1

    # A counter, two ways: one that exits a rise late, and a progressive one
    # whose step never advances. The raw tables and the generator's must each
    # see both.
    honest_counted = rp._counted

    def late(core):
        count = core.count + 1
        if count <= core.target:
            return rp.replace(core, count=count), False
        return rp.replace(core, count=count, step=min(core.step + 1, 0xFF)), True

    def stuck(core):
        core, exits = honest_counted(core)
        return (rp.replace(core, step=0) if exits else core), exits

    for mutant, what in ((late, "a counter that exits a rise late"), (stuck, "a progressive step that never advances")):
        rp._counted = mutant
        try:
            for name, family in (("raw", [i for i in range(len(cases)) if i % 3 == 0]),
                                 ("generated", [i for i in range(len(cases)) if i % 3 == 2])):
                if not first_difference([c_runs[i] for i in family], [cases[i] for i in family]):
                    print(f"differential: {what} went unnoticed on the {name} tables; they reach too few "
                          "counter states")
                    return 1
        finally:
            rp._counted = honest_counted

    generated = len(family)
    print(f"differential: {len(cases)} cases ({generated} lowered by the generator), "
          f"{actions} actions equal; a changed tie rule, pick draw, draw and counter are caught")
    return check_trains(args.driver, args.seed)


if __name__ == "__main__":
    sys.exit(main())

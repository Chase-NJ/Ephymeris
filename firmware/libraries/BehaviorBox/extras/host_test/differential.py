"""Hold BoxInterp.h and replay.py equal: the differential test (run_diff.sh).

Generates state tables (spines lowered by the generator itself,
`taskdef/lowering.py`, with every phase of the palette: Holds, Waits on either
edge, aborts on either edge, Counters over a fixed, drawn or progressive N,
Response windows, contingency maps, several rows and blocks; four named tasks
lowered the same way, a reversal on 8 of 10, a bandit looping between blocks of
40-60, a shuffle bag and anti-bias, each run with an animal that answers; spines
of the first phases lowered here; and raw tables that stress the format, pick,
counter, last-trial and response states and blocks of every kind included),
randomized input logs with simultaneous edges, seeds and start times near the
millis() wrap. Runs every case through the C core (`interp_driver`, stepping
every tick as a board does) and through the Python replay (jumping between
edges and timers), and fails on the first tick where their actions differ.

Then it checks itself: with the Python tie rule deliberately changed, the same
cases must differ. A differential test that cannot see a changed tie rule is
generating too few ties to be trusted. So too a changed pick draw, which the
raw tables must see. And with every RNG draw reflected, the generator's tables
alone must differ, through their chance and pick states. And a counter that
exits one rise late, or a progressive step that never advances, must each be
seen by both the raw and the generator's tables. So must each block rule
changed alone: the uniform, weighted, bag and anti-bias draws, the N rule, a
drawn N, the criterion, `next`, correction and overrides. And the named
reversal, bandit and bag must each switch blocks in some case.

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
    blocked = rng.random() < 0.6  # blocks, drawn by state 0, a trial-starting pick
    if blocked:
        kind[0] = "pick"
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
                                      flags=rp.PICK | (rp.STARTS_TRIAL if blocked and i == 0 else rng.choice((0, rp.STARTS_TRIAL))),
                                      outcome=rng.randrange(8)))
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
            flags=rng.choice((0, 0, rp.STARTS_TRIAL, rp.LAST_TRIAL)) | (rp.RESPONSE if rng.random() < 0.5 else 0),
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
    blocks = raw_blocks(rng, n_params, states) if blocked else None
    return rp.Table(states=tuple(states), edges=tuple(edges), counter=counter, blocks=blocks)


def raw_blocks(rng: random.Random, n_params: int, states: list[rp.StateRow]) -> rp.Blocks:
    """One to three blocks over the trial-starting picks' branches: every selection,
    an N fixed or drawn, a criterion, both or neither, a next that goes on, loops
    back or ends, a correction limit, entries on input sides, overrides."""
    room = min(s.edge_count for s in states if s.is_pick and s.flags & rp.STARTS_TRIAL)
    n_blocks = rng.randint(1, 3)

    def pair() -> tuple[int, int]:
        if rng.random() < 0.4:
            return NONE, NONE
        lo = rng.randrange(n_params)
        return lo, (lo if rng.random() < 0.5 else rng.randrange(n_params))

    rows = []
    for _ in range(n_blocks):
        count = rng.randint(1, room)
        n_min, n_max = pair()
        k, n = pair()
        rows.append(rp.Block(
            first=rng.randint(0, room - count), count=count,
            select=rng.choice((rp.UNIFORM, rp.WEIGHTED, rp.BAG, rp.ANTIBIAS)),
            n_min=n_min, n_max=n_max, k=k, n=n,
            window=rng.randrange(n_params) if rng.random() < 0.8 else NONE,
            correct=rng.randrange(n_params) if rng.random() < 0.5 else NONE,
            next=rng.choice((NONE, *range(n_blocks)))))
    entries = [rp.Entry(side=rng.choice((0, 1, 2, 3, NONE)),
                        weight=rng.randrange(n_params) if rng.random() < 0.8 else NONE)
               for _ in range(room)] if rng.random() < 0.85 else []
    overrides = [rp.Override(rng.randrange(n_blocks), rng.randrange(n_params), rng.randrange(n_params))
                 for _ in range(rng.choice((0, 0, 1, 2)))]
    return rp.Blocks(rows=tuple(rows), entries=tuple(entries), overrides=tuple(overrides))


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


def generated_table(rng: random.Random, n_params: int):  # noqa: ANN201
    """A random spine DEFINITION, lowered by the generator's own `lowering.lower()`:
    the tables a saved spine task compiles into its `TaskSpine.h`. One to three
    rows, each binding some slots to a channel of its own and some to a shared
    one; often a Response window with a contingency map per row, holds and a
    line on some entries, drawn by one to three blocks; now and then one of the
    `NAMED` tasks. Returns (the table, its lowering) and the values its named
    block settings hold, by slot."""
    del n_params  # lowering assigns the slots
    if rng.random() < 0.3:
        return named_table(rng, rng.choice(NAMED))
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
    # One to three blocks, each drawing some of the rows by any selection, with
    # any end rule, a next that goes on, loops back or ends, a correction limit
    # and an override of a timed phase.
    timed = [i for i, p in enumerate(phases)
             if p["phase"] in lowering._TIMED or (p["phase"] in ("wait", "counter") and "timeoutMs" in p)]
    ids = [r["id"] for r in rows]
    n_blocks = rng.choice((1, 1, 2, 3))
    blocks = []
    for b in range(n_blocks):
        block = {"id": f"b{b}", "rows": rng.sample(ids, rng.randint(1, len(ids))),
                 "select": rng.choice(tuple(lowering.SELECTIONS))}
        end = rng.choice(("none", "n", "drawn", "criterion", "both"))
        if end in ("n", "drawn", "both"):
            block["trials"] = 1
            if end == "drawn":
                block["trialsMax"] = 2
        if end in ("criterion", "both"):
            block["criterion"] = {"correct": 1, "of": 2}
        if rng.random() < 0.5:
            block["next"] = f"b{rng.randrange(n_blocks)}"
        if rng.random() < 0.4:
            block["correction"] = 1
        if timed and rng.random() < 0.3:
            block["phaseMs"] = {str(rng.choice(timed)): 1}
        blocks.append(block)
    return _lowered(phases, inputs, outputs, rows, blocks, rng.random() < 0.5), {}, None


def _lowered(phases, inputs, outputs, rows, blocks, cap):  # noqa: ANN001, ANN202
    low = lowering.lower(phases, inputs=inputs, outputs=outputs, rows=rows, blocks=blocks, session_cap=cap)
    table = rp.Table(states=[rp.StateRow(*s) for s in low.states], edges=[rp.EdgeRow(*e) for e in low.edges],
                     counter=rp.Counter(*low.counter) if low.counter is not None else None,
                     blocks=rp.Blocks(rows=[rp.Block(*b) for b in low.blocks],
                                      entries=[rp.Entry(*e) for e in low.entries],
                                      overrides=[rp.Override(*o) for o in low.overrides]))
    return table, low


#: Four tasks the ADR names, lowered by the generator and run at their own
#: settings: a reversal on 8 correct of 10, a bandit looping between blocks of
#: 40-60 trials, a shuffle bag, and anti-bias.
NAMED = ("reversal", "bandit", "bag", "antibias")


def named_table(rng: random.Random, name: str):  # noqa: ANN201
    """A named task: a 2AFC window (left and right) whose rows map one side to
    correct, its blocks as the ADR's worked example has them. Returns the table,
    and the values its block settings hold, by slot."""
    phases = [{"phase": "response", "responses": ["left", "right"], "ms": 1},
              {"phase": "outcome", "ms": 1}, {"phase": "iti", "ms": 1}]

    def row(row_id: str, correct: str, permille: int = 1000) -> dict:
        wrong = "left" if correct == "right" else "right"
        return {"id": row_id, "bind": {"left": "L", "right": "R", "reward": "F"},
                "map": {correct: {"outcome": "correct", "line": "reward", "rewardPermille": permille},
                        wrong: {"outcome": "wrong_response"}, "timeout": {"outcome": "omission"}}}

    rows = [row("go_right", "right"), row("go_left", "left")]
    settings: dict[str, int] = {}
    if name == "reversal":
        rows += [row("go_right_rev", "left"), row("go_left_rev", "right")]
        blocks = [{"id": "a", "rows": ["go_right", "go_left"], "criterion": {"correct": 8, "of": 10},
                   "correction": 2},
                  {"id": "b", "rows": ["go_right_rev", "go_left_rev"], "criterion": {"correct": 8, "of": 10}}]
        settings = {"BK1": 8, "BKN1": 10, "BC1": 2, "BK2": 8, "BKN2": 10}
    elif name == "bandit":
        rows = [row("left_good", "left", 800), row("right_good", "right", 800)]
        blocks = [{"id": "a", "rows": ["left_good"], "trials": 40, "trialsMax": 60},
                  {"id": "b", "rows": ["right_good"], "trials": 40, "trialsMax": 60, "next": "a"}]
        settings = {"BN1": 40, "BNX1": 60, "BN2": 40, "BNX2": 60}
    elif name == "bag":
        blocks = [{"id": "a", "rows": ["go_right", "go_left"], "select": "bag", "weights": [3, 1], "trials": 20},
                  {"id": "b", "rows": ["go_right", "go_left"], "select": "bag", "weights": [1, 1], "next": "a",
                   "trials": 7}]
        settings = {"W1_1": 3, "W1_2": 1, "BN1": 20, "W2_1": 1, "W2_2": 1, "BN2": 7}
    else:
        blocks = [{"id": "a", "rows": ["go_right", "go_left"], "select": "antibias", "biasWindow": 10,
                   "correction": 1}]
        settings = {"BA1": 10, "W1_1": 1, "W1_2": 1, "BC1": 1}
    table, low = _lowered(phases, ["left", "right"], ["reward"], rows, blocks, False)
    # Short trials, so a run holds enough of them for its blocks to switch.
    fixed = {n: rng.randint(1, 30) for n, s in enumerate(low.slots) if s.role in ("timer", "reward_ms")}
    return (table, low), fixed | {low.params.index(k): v for k, v in settings.items()}, name


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


def answering_log(rng: random.Random, table: rp.Table, params: list[int], seed: int, start: int,
                  ticks: int) -> list[tuple[int, int, int]]:
    """An animal for a named task: at the first tick of each response window it
    pokes the side the row pays, nine times in ten, and lets go a tick later.
    Played through the Python replay to know the row; the C core only sees the log."""
    core, _ = rp.begin(table, params, seed, start)
    out, release = [], 0
    for offset in range(1, ticks + 1):
        rose, fell, release = 0, release, 0
        s = table.states[core.state]
        if s.flags & rp.RESPONSE and not fell:
            exits = table.edges[s.edge_first : s.edge_first + s.edge_count]
            right = [e.input for e in exits if table.states[e.next].outcome == rp.CORRECT]
            wrong = [e.input for e in exits if table.states[e.next].outcome != rp.CORRECT]
            pool = right if right and (rng.random() < 0.9 or not wrong) else wrong
            if pool:
                rose = release = 1 << rng.choice(pool)
        if rose or fell:
            out.append((offset, rose, fell))
        core, _ = rp.step(core, rp.Edges(rose, fell), (start + offset) & 0xFFFFFFFF)
    return out


def make_cases(seed: int, count: int) -> list[dict]:
    rng = random.Random(seed)
    cases = []
    for i in range(count):
        n_params = rng.randint(2, 6)
        bits = [0, 1, 2, 3, 31]
        if i % 3 == 2:
            (table, low), fixed, named = generated_table(rng, n_params)
            n_params, n_inputs = len(low.params), len(low.inputs)
            bits = list(range(n_inputs))
        else:
            table, fixed = (spine_table if i % 3 else raw_table)(rng, n_params), {}
        params = params_for(rng, n_params)
        if table.counter is not None:
            # N small enough to be reached, now and then 0 or past a uint16_t.
            for slot in table.counter.slots:
                params[slot] = rng.choice((0, 1, 2, 3, 4, 5, 6, 0x10002)) if rng.random() < 0.9 else rng.randint(0, 60)
        if table.blocks is not None:
            # Blocks short enough to end, criteria and limits within reach, weights
            # of a few tokens, and now and then one past what the board would hold.
            for slot in table.blocks.slots:
                params[slot] = rng.choice((0, 1, 1, 2, 2, 3, 4, 5, 6, 40, 0x10002))
        for slot, value in fixed.items():  # a named task's own settings
            params[slot] = value
        r = rng.random()
        start = 0 if r < 0.4 else 0xFFFFFFFF - rng.randint(0, 3000) if r < 0.7 else rng.getrandbits(32)
        session_seed = rng.choice((1, 0, 0x80000000, 0xFFFFFFFF)) if rng.random() < 0.1 else rng.randint(1, 2**31 - 2)
        ticks = rng.randint(200, 5000)
        log = (answering_log(rng, table, params, session_seed, start, ticks) if i % 3 == 2 and named
               else input_log(rng, ticks, bits))
        cases.append(dict(table=table, params=params, seed=session_seed, start=start, ticks=ticks, log=log,
                          named=named if i % 3 == 2 else None))
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
        b = t.blocks
        lines.append("0 0 0" if b is None else f"{len(b.rows)} {len(b.entries)} {len(b.overrides)}")
        if b is not None:
            lines.extend(" ".join(map(str, (k.first, k.count, k.select, k.n_min, k.n_max, k.k, k.n, k.window,
                                            k.correct, k.next))) for k in b.rows)
            lines.extend(f"{e.side} {e.weight}" for e in b.entries)
            lines.extend(f"{o.block} {o.slot} {o.with_}" for o in b.overrides)
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
    return [(now, a.rose, a.fell, a.on, a.off, a.entered[0], a.entered[1], a.flags, a.block) for now, a in run]


FIELDS = ("now", "rose", "fell", "on", "off", "entered0", "entered1", "flags", "block")


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


def _mutants() -> list[tuple[str, str, object]]:
    """(what, the replay function, a changed one) per block rule. Each draws
    exactly as the honest one does, so only the rule's own choice differs."""
    honest = {name: getattr(rp, name) for name in (
        "_uniform", "_by_weight", "_from_bag", "_side_weight", "_block_ends", "_start_block", "_next_block",
        "_repeats", "_param")}

    def uniform(c, k):
        return k.first + k.count - 1 - (honest["_uniform"](c, k) - k.first)

    def weighted(c, k, side=None):
        e = honest["_by_weight"](c, k, side)
        if side is not None:
            return e
        return k.first + k.count - 1 - (e - k.first)

    def bag(c, k):
        e = honest["_from_bag"](c, k)
        return k.first + k.count - 1 - (e - k.first)

    def side_weight(c, side, length):
        return 1 + length - (honest["_side_weight"](c, side, length) - 1) if length else 1

    def n_late(c, k):
        if k.n_min != NONE and k.k == NONE:
            return c.block_trials >= c.block_n + 1
        return honest["_block_ends"](c, k)

    def criterion_low(c, k):
        if k.k != NONE and k.n_min == NONE:
            n = c.params[k.n]
            mask = 0xFFFFFFFF if n >= rp.HISTORY else (1 << n) - 1
            return rp._ones(c.corrects & mask) + 1 >= c.params[k.k]
        return honest["_block_ends"](c, k)

    def drawn_n(c, b, a):
        honest["_start_block"](c, b, a)
        k = c.table.blocks.rows[b]
        if k.n_min != NONE and c.params[k.n_max] > c.params[k.n_min]:
            c.block_n = (c.params[k.n_max] + c.params[k.n_min] - c.block_n) & 0xFFFF

    def next_block(k):
        return NONE

    def repeats(c, k, last_outcome):
        return (k.correct != NONE and last_outcome not in (0, rp.CORRECT)
                and c.repeats <= c.params[k.correct])

    def no_override(c, slot):
        return c.params[slot]

    return [("a changed uniform draw", "_uniform", uniform),
            ("a changed weighted draw", "_by_weight", weighted),
            ("a changed shuffle bag", "_from_bag", bag),
            ("anti-bias pushing with the bias", "_side_weight", side_weight),
            ("a block that ends a trial late", "_block_ends", n_late),
            ("a criterion one short", "_block_ends", criterion_low),
            ("a changed drawn N", "_start_block", drawn_n),
            ("a next block that ends the blocks", "_next_block", next_block),
            ("a correction one repeat over", "_repeats", repeats),
            ("an override ignored", "_param", no_override)]


def blocks_caught(c_runs, cases) -> str | None:
    """The first block rule whose change a family of tables misses, or None."""
    families = (("raw", [i for i in range(len(cases)) if i % 3 == 0]),
                ("generated", [i for i in range(len(cases)) if i % 3 == 2]))
    for what, name, mutant in _mutants():
        honest = getattr(rp, name)
        setattr(rp, name, mutant)
        try:
            for family, members in families:
                if not any(cases[i]["table"].blocks is not None for i in members):
                    continue
                if not first_difference([c_runs[i] for i in members], [cases[i] for i in members]):
                    return f"{what} on the {family} tables"
        finally:
            setattr(rp, name, honest)
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

    # A pick state's draw, the same way: take the branch mirrored from the one
    # drawn (k -> n-1-k), drawing exactly as before. The raw tables must see it.
    # Every pick of the generator's tables starts a trial in a table with
    # blocks, so it draws by its block's selection: blocks_caught() changes those.
    honest_pick = rp._pick

    def mirrored_pick(rng, branches):
        k, rng = honest_pick(rng, branches)
        return branches - 1 - k, rng

    rp._pick = mirrored_pick
    try:
        family = [i for i in range(len(cases)) if i % 3 == 0]
        if not first_difference([c_runs[i] for i in family], [cases[i] for i in family]):
            print("differential: a changed pick draw went unnoticed on the raw tables; they reach too few "
                  "pick states")
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

    # The named tasks with more than one block must each switch blocks in some
    # case: a reversal reaching 8 of 10, a bandit's 40-60 trials running out.
    switched = {c["named"] for c, run in zip(cases, c_runs)
                if c["named"] and any(dict(zip(FIELDS, line))["flags"] & rp.ACT_BLOCK_START for line in run[1:])}
    for name in ("reversal", "bandit", "bag"):
        if name not in switched:
            print(f"differential: no {name} case switched blocks; the cases run too few trials")
            return 1

    # Blocks: each selection, each end rule, next, correction and overrides,
    # changed one at a time, must be seen by the raw tables and the generator's.
    missed = blocks_caught(c_runs, cases)
    if missed:
        print(f"differential: {missed} went unnoticed; the cases reach too few blocks of that kind")
        return 1

    generated = len(family)
    print(f"differential: {len(cases)} cases ({generated} lowered by the generator), "
          f"{actions} actions equal; a changed tie rule, pick draw, draw, counter and every block rule are caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())

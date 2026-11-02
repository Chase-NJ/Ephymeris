"""A spine task run against a simulated animal (`TASKS.md#simulating-a-spine-task`).

Simulate checks a task before anything is compiled or flashed
(`0003-phase-spine-task-model.md#ui`). It steps replay's own core with an
animal in the loop, then writes the run document a board running that table
with that animal would have produced:

    result = simulate(snapshot, Animal("correct"), seed)
    summarize(result.document, profile)   # scored as Analytics scores a run

So Simulate's numbers are Analytics' by construction, and the replay check
runs on every simulation: a simulated run that diverged would be a bug here.

**The animal reads the table, never a phase's name.** In the state the core
rests in, it can wait for the timer or make one of the state's watched edges.
It ranks each by the outcome classes the trial can still end in from there
(`_rank`): a hit class first, then no class, then a miss. An engaged animal
takes the best everywhere: it pokes at a Wait, sits through a Hold and leaves
at a Wait for exit. At a trial's first response (`replay.RESPONSE`, while the
core has none), its kind decides:

    correct   the best, as everywhere: on a no-go row that is withholding
    random    uniformly, among the state's edges and its timeout
    biased    its `response` slot with `permille`/1000, else as random
    silent    nothing, anywhere: no edge at all

Its levels stay physical: it never raises a line that is up, and it lets a
line go as soon as the state in force stops watching it, which the board
never strobes. It acts `REACTION_MS` after a state is entered, always before
the state's timer, and presses a Counter's line N times at that pace. An input
counted but never acted on (a Pavlovian task's licks) is never touched.

**Where it ends** is BoxSpine.h's rule, as `spine._session` reads it: the trial
cap NT, the blocks running out, a last-trial state, or the first trial start
after `limit_ms`, the runner's auto-STOP. A session no trial start ends within
`GRACE_MS` after the limit is cut off there, like a crashed file.

**Pure**, like the rest of `stream/`: the animal's randomness is its own
seeded `random.Random`, never the session RNG, so it cannot move the board's
draws.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, replace
from typing import Any

from ...taskdef.lowering import HIT_CLASSES, OUTCOME_CLASSES
from ...tasks.profile import SNAPSHOT_KEY
from . import replay as rp
from . import spine

#: What an animal can be (`0003-phase-spine-task-model.md#ui`).
ANIMALS = ("correct", "random", "biased", "silent")
#: The session time limit when none is given: the runner's auto-STOP.
DEFAULT_LIMIT_MS = 60 * 60_000
#: How long past the limit a session may run on to its next trial start.
GRACE_MS = 10 * 60_000
#: When the animal acts after a state is entered, drawn uniformly, in ms.
REACTION_MS = (200, 600)
#: How long a Counter press holds the line.
PRESS_MS = 100

_HITS = frozenset(OUTCOME_CLASSES.index(name) + 1 for name in HIT_CLASSES)
_WAIT = None  # the option of taking the state's timer


@dataclass(frozen=True)
class Animal:
    """A simulated animal: its `kind`, and for a biased one the response slot it favours."""

    kind: str
    response: str | None = None
    permille: int = 800


@dataclass(frozen=True)
class Simulated:
    """A simulated run: the document its board would have written, and what ended it."""

    document: dict[str, Any]
    #: "trials" (NT), "blocks" (they ran out), "lastTrial" or "timeLimit".
    ended_by: str


def simulate(snapshot: dict[str, Any], animal: Animal, seed: int, *,
             limit_ms: int = DEFAULT_LIMIT_MS) -> Simulated:
    """Run a spine profile (`task.json` with its `spine` snapshot) against `animal`.

    `seed` is the run's `trial_seed`, and seeds the animal too, so one number
    repeats a simulation. Raises ValueError for an animal it cannot be.
    """
    shot = copy.deepcopy(snapshot)
    document = _header(shot, seed)
    record = spine.decode(document)
    walk = _Animal(record.table, animal, _favoured(shot, animal), random.Random(f"animal-{seed}"))
    edges, end, ended_by = _session(record, walk, limit_ms)
    if end is None:
        document["ts_data"] = _cut(record, edges, limit_ms + GRACE_MS)
        document["stop_reason"] = "simulated session cut off past its time limit"
    else:
        document["ts_data"] = _strobes(record, edges) + [[record.session_end, end]]
        document["ts_data"] = [list(s) for s in spine.expected_stream(spine.decode(document))]
    document["n_events"] = len(document["ts_data"])
    return Simulated(document, ended_by)


def _header(shot: dict[str, Any], seed: int) -> dict[str, Any]:
    """The run document before its first strobe, as the runner writes it."""
    return {
        "sketch": shot.get("taskName"),
        "stop_reason": "BF_END_SESSION received",
        "interp": shot["spine"]["interp"],
        "trial_seed": seed,
        SNAPSHOT_KEY: shot,
        **{f["metadataKey"]: f["default"] for f in shot.get("config", [])},
        "ts_data": [],
    }


def _favoured(shot: dict[str, Any], animal: Animal) -> int:
    """The input bits a biased animal favours: every input its response slot binds."""
    if animal.kind not in ANIMALS:
        raise ValueError(f"{animal.kind!r} is not an animal Simulate offers {ANIMALS}")
    if animal.kind != "biased":
        return 0
    responses = {r for p in shot["spine"]["spine"] if p.get("phase") == "response" for r in p.get("responses", [])}
    if animal.response not in responses:
        raise ValueError(f"a biased animal favours one of the spine's responses {sorted(responses)}, "
                         f"not {animal.response!r}")
    if not 0 <= animal.permille <= rp.PERMILLE:
        raise ValueError(f"a biased animal favours its response 0 to {rp.PERMILLE} permille")
    return sum(1 << i for i, entry in enumerate(shot["spine"]["inputs"]) if entry.get("slot") == animal.response)


# --- the session ----------------------------------------------------------------


def _session(record: spine.SpineRecord, walk: _Animal,
             limit_ms: int) -> tuple[list[tuple[int, rp.Edges]], int | None, str]:
    """Step the core with the animal in the loop: every tick's watched input
    edges, the tick the session ended at (None: cut off), and what ended it."""
    table = record.table
    max_trials = record.params[record.trials_slot] if record.trials_slot is not None else None
    started, last = 0, False

    def ends(now: int, a: rp.Actions) -> str | None:
        # spine._session's rule, with the auto-STOP at the limit for END_SESSION.
        nonlocal started, last
        last = last or bool(a.flags & rp.ACT_LAST_TRIAL)
        if not a.flags & rp.ACT_TRIAL_START:
            return None
        if now > 0:
            if max_trials is not None and started >= max_trials:
                return "trials"
            if last:
                return "lastTrial"
            if a.flags & rp.ACT_DONE:
                return "blocks"
            if now >= limit_ms:
                return "timeLimit"
        started += 1
        return None

    core, first = rp.begin(table, record.params, record.seed, 0, record.interp)
    if (reason := ends(0, first)) is not None:
        return [], 0, reason
    levels = 0
    queue = walk.plan(core, levels, 0)
    out: list[tuple[int, rp.Edges]] = []
    now = 0
    while True:
        timer = _due(core, now)
        acts = queue[0][0] if queue else None
        nxt = min(t for t in (timer, acts) if t is not None) if timer is not None or acts is not None else None
        if nxt is None or nxt > limit_ms + GRACE_MS:
            return out, None, "timeLimit"
        rose = fell = 0
        while queue and queue[0][0] == nxt:
            _, r, f = queue.pop(0)
            rose, fell = rose | r, fell | f
        levels = (levels | rose) & ~fell
        watch = table.states[core.state].watch
        if (rose | fell) & watch:
            out.append((nxt, rp.Edges(rose & watch, fell & watch)))
        core, a = rp.step(core, rp.Edges(rose, fell), nxt)
        now = nxt
        if (reason := ends(now, a)) is not None:
            return out, now, reason
        if a.entered[0] != rp.NONE:
            queue = walk.plan(core, levels, now)


def _due(core: rp.Core, now: int) -> int | None:
    """The tick the resting state's timer runs out, as `replay.replay` steps to it."""
    if core.table.states[core.state].timer_min == rp.NONE:
        return None
    return now + max(1, core.duration - (now - core.entered_at))


def _strobes(record: spine.SpineRecord, edges: list[tuple[int, rp.Edges]]) -> list[list[int]]:
    """The input strobes the board sent: each watched edge, rises before falls."""
    out = []
    for now, e in edges:
        out += [[record.rise[b], now] for b in range(len(record.rise)) if e.rose >> b & 1]
        out += [[record.fall[b], now] for b in range(len(record.fall)) if e.fell >> b & 1]
    return out


def _cut(record: spine.SpineRecord, edges: list[tuple[int, rp.Edges]], ticks: int) -> list[list[int]]:
    """A run with no END_SESSION: every strobe through the last tick the core
    acted on before `ticks`, as a crashed file holds them."""
    actions = rp.replay(record.table, record.params, record.seed, edges, ticks, interp=record.interp)
    last = max(now for now, _ in actions)
    held = replace(record, events=tuple(edges), end_tick=None, last_tick=last)
    return [list(s) for s in spine.predicted_through(held, actions)]


# --- the animal -----------------------------------------------------------------


class _Animal:
    """What the animal does in each state the core rests in."""

    def __init__(self, table: rp.Table, animal: Animal, favoured: int, rng: random.Random) -> None:
        self.table, self.animal, self.favoured, self.rng = table, animal, favoured, rng
        self._ranks: dict[tuple[int, int], int] = {}

    def plan(self, core: rp.Core, levels: int, now: int) -> list[tuple[int, int, int]]:
        """Its edges from `now` while the core rests here: (tick, rose, fell), by tick."""
        if self.animal.kind == "silent":
            return []
        s = self.table.states[core.state]
        events: list[tuple[int, int, int]] = []
        free = levels & ~s.watch
        if free:
            events.append((now + 1, 0, free))
            levels &= ~free
        choice = self._choose(core, s, levels)
        if choice is _WAIT:
            return events
        bit = 1 << choice.input
        if s.is_count:
            if levels & bit:
                events.append((now + 1, 0, bit))
            t = now
            for _ in range(max(1, core.target - core.count)):
                t += self._reaction()
                events += [(t, bit, 0), (t + PRESS_MS, 0, bit)]
        else:
            delay = self._reaction()
            if s.timer_min != rp.NONE:
                delay = max(1, min(delay, core.duration))
            rise = choice.edge == rp.RISE
            events.append((now + delay, bit if rise else 0, 0 if rise else bit))
        return sorted(events, key=lambda e: e[0])

    def _reaction(self) -> int:
        return self.rng.randint(*REACTION_MS)

    def _options(self, s: rp.StateRow, levels: int) -> list[rp.EdgeRow | None]:
        """Its timer, and each watched edge the animal can make from these levels."""
        rows = self.table.edges[s.edge_first : s.edge_first + s.edge_count]
        options: list[rp.EdgeRow | None] = [_WAIT] if s.timer_min != rp.NONE else []
        for e in rows:
            up = bool(levels >> e.input & 1)
            if s.is_count or (e.edge == rp.RISE and not up) or (e.edge == rp.FALL and up):
                options.append(e)
        return options

    def _choose(self, core: rp.Core, s: rp.StateRow, levels: int) -> rp.EdgeRow | None:
        options = self._options(s, levels)
        if not options:
            return _WAIT
        responding = bool(s.flags & rp.RESPONSE) and core.response == rp.NONE
        if responding and self.animal.kind in ("random", "biased"):
            favoured = [o for o in options if o is not _WAIT and self.favoured >> o.input & 1]
            if favoured and self.rng.randrange(rp.PERMILLE) < self.animal.permille \
                    and self.animal.kind == "biased":
                return self.rng.choice(favoured)
            return self.rng.choice(options)
        ranked = [(self._rank(s.on_timeout if o is _WAIT else o.next, core.outcome), o) for o in options]
        best = max(r for r, _ in ranked)
        tied = [o for r, o in ranked if r == best]
        return _WAIT if _WAIT in tied else self.rng.choice(tied)

    def _rank(self, target: int, outcome: int) -> int:
        """2: the trial can still end in a hit class from `target`; 1: in no
        class; 0: only in a miss. The trial's class is the last one entered
        before the next trial starts, as `trial_table` reads it."""
        key = (target, outcome)
        if key not in self._ranks:
            finals = self._finals(target, outcome, frozenset())
            self._ranks[key] = 2 if finals & _HITS else 1 if 0 in finals else 0
        return self._ranks[key]

    def _finals(self, u: int, outcome: int, seen: frozenset[tuple[int, int]]) -> set[int]:
        row = self.table.states[u]
        if row.flags & rp.STARTS_TRIAL or (u, outcome) in seen:
            return {outcome} if row.flags & rp.STARTS_TRIAL else set()
        outcome = row.outcome or outcome
        seen = seen | {(u, outcome)}
        if row.is_chance:
            nexts = [row.on_hit, row.on_miss]
        else:
            nexts = [e.next for e in self.table.edges[row.edge_first : row.edge_first + row.edge_count]]
            if row.timer_min != rp.NONE:
                nexts.append(row.on_timeout)
        if not nexts:
            return {outcome}
        return set().union(*(self._finals(v, outcome, seen) for v in nexts if v != rp.NONE))

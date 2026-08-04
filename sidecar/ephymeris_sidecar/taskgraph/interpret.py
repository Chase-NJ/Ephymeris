"""The forward reference interpreter — the oracle.

Walks a compiled table against scripted subject behaviour and emits a strobe
stream. This is the *expected* side of Phase 3's equivalence tests: the firmware
interpreter has to produce exactly what this produces, for the same table, the same
trial, and the same scripted animal.

TWO DESIGN CHOICES WORTH THE WORDS.

**The subject answers per NODE, not per millisecond.** A continuous simulation
would need a sensor model and a time step, and would make every test depend on
both. Instead the interpreter asks "you are in a WAIT_ENTRY watching these
channels — what do you do?" and the subject answers with an action and a dwell.
That keeps scripts readable (`pokes odor_port after 300 ms, holds`) and makes the
whole thing deterministic without a seed.

**It emits, it does not decide.** Trial selection and correction budgets are
policy, and policy is the caller's business — the interpreter takes the bound trial
and walks. Building selection in here would mean reproducing the firmware RNG to
test anything, which is the coupling Phase 3 exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ephymeris_sidecar.taskgraph.graph import NodeType, Trigger
from ephymeris_sidecar.taskgraph.registries import channels
from ephymeris_sidecar.taskgraph.spec import TaskSpec, TrialType
from ephymeris_sidecar.taskgraph.table import (
    BIND_PORT_BREAK,
    BIND_PORT_ENTER,
    BIND_PORT_ERROR,
    BIND_PORT_EXIT,
    BIND_STIM_ON_3,
    BIND_TARGET_EXIT,
    BIND_TARGET_REWARD,
    BIND_TARGET_REWARD_STOP,
    DUR_FROM_TRIAL,
    NO_STROBE,
    NO_TARGET,
    StateTable,
    is_bound,
    selector_of,
)


@dataclass(frozen=True)
class Emission:
    """One strobe, as it would appear on the wire."""

    code: int
    t: int
    node: int
    name: str = ""

    def __repr__(self) -> str:
        return f"{self.name or self.code}@{self.t}"


@dataclass(frozen=True)
class Act:
    """What the subject does in the state it has been asked about.

    `channel` names the port entered (WAIT_ENTRY only). `sustained` says whether a
    HOLD was met. `dwell` is how long it took — clamped by the interpreter to the
    state's own duration, so a script cannot accidentally out-wait a window.
    """

    dwell: int = 0
    channel: str | None = None
    sustained: bool = True


class Subject(Protocol):
    def act(self, node_type: NodeType, watching: tuple[str, ...], limit: int | None) -> Act: ...


@dataclass
class ScriptedSubject:
    """A subject that replays a fixed list of actions.

    Running out of script is an ERROR, not an implicit timeout: a test that
    silently fell off the end of its script would pass for the wrong reason.
    """

    script: list[Act]
    _i: int = 0

    def act(self, node_type: NodeType, watching: tuple[str, ...], limit: int | None) -> Act:
        if self._i >= len(self.script):
            raise RuntimeError(
                f"script exhausted at a {node_type} state — add an Act, or the test "
                f"is asserting less than it appears to"
            )
        a = self.script[self._i]
        self._i += 1
        return a


@dataclass
class Trace:
    emissions: list[Emission] = field(default_factory=list)
    path: list[int] = field(default_factory=list)
    ended: str = ""          # the terminal reached
    t: int = 0

    @property
    def codes(self) -> list[int]:
        return [e.code for e in self.emissions]

    @property
    def names(self) -> list[str]:
        return [e.name for e in self.emissions]


class Interpreter:
    """Walks one trial."""

    def __init__(self, spec: TaskSpec, table: StateTable) -> None:
        self.spec = spec
        self.table = table
        self.channels = channels()

    # -- binding resolution ------------------------------------------------ #

    def _strobe(self, node, trial: TrialType, entered: str | None, stage: int) -> int | None:
        """The code this entry emits for THIS trial.

        RESOLVED FROM THE TABLE, not from the spec. The board has only the table,
        so resolving from the richer spec would let the two implementations agree
        by accident while disagreeing about what the board can actually do. Gate A
        caught exactly that: this returned the raw selector as if it were a code.
        """
        if not is_bound(node.strobe):
            return None if node.strobe == NO_STROBE else node.strobe

        sel = selector_of(node.strobe)
        t = self.table

        if sel <= BIND_STIM_ON_3:  # selectors 0..3 are sampling stages 0..3
            row = t.trial_types[self._trial_index(trial)]
            si = row.stimulus[sel] if sel < len(row.stimulus) else NO_TARGET
            code = t.stimuli[si].on_code if si < len(t.stimuli) else NO_STROBE
            return None if code == NO_STROBE else code

        port_i = self._bind_port(trial, entered, sel)
        if port_i is None or port_i >= len(t.ports):
            return None
        port = t.ports[port_i]
        code = {
            BIND_PORT_ENTER: port.enter_code,
            BIND_PORT_ERROR: port.error_code,
            BIND_PORT_BREAK: port.break_code,
            BIND_PORT_EXIT: port.exit_code,
            BIND_TARGET_EXIT: port.exit_code,
            BIND_TARGET_REWARD: port.reward_code,
            BIND_TARGET_REWARD_STOP: port.reward_stop_code,
        }.get(sel, NO_STROBE)
        return None if code == NO_STROBE else code

    def _trial_index(self, trial: TrialType) -> int:
        for i, t in enumerate(self.spec.contingency.trial_types):
            if t.id == trial.id:
                return i
        return 0

    def _bind_port(self, trial: TrialType, entered: str | None, sel: int) -> int | None:
        """`@ports[$ch]` is the port just entered; `@target` is the trial's correct
        port. They coincide on the correct path and DIFFER on the wrong-port path,
        which is the case that makes the distinction matter."""
        names = list(self.spec.contingency.ports)
        want = trial.target if sel >= BIND_TARGET_REWARD else entered
        return names.index(want) if want in names else None

    def _duration(self, node, trial: TrialType) -> int:
        if node.type in (NodeType.WAIT_EXIT, NodeType.TERMINAL):
            return 0
        if node.dur_idx == DUR_FROM_TRIAL:
            row = self.table.trial_types[self._trial_index(trial)]
            di = row.reward_dur_idx
            return self.table.timing[di] if di < len(self.table.timing) else 0
        return self.table.timing[node.dur_idx] if node.dur_idx < len(self.table.timing) else 0

    def _edges(self, i: int):
        t = self.table
        end = t.nodes[i + 1].edge_idx if i + 1 < len(t.nodes) else len(t.edges)
        return t.edges[t.nodes[i].edge_idx : end]

    def _watching(self, node, trial: TrialType) -> tuple[str, ...]:
        out = []
        for w in node.watch_text:
            out.append(trial.target if w.startswith("@") and trial.target else w)
        return tuple(x for x in out if x)

    # -- the walk ---------------------------------------------------------- #

    def run_trial(self, trial: TrialType, subject: Subject, *, start_t: int = 0,
                  max_steps: int = 200) -> Trace:
        from ephymeris_sidecar.taskgraph.registries import vocabulary

        vocab = vocabulary()
        tr = Trace(t=start_t)
        node_i = 0
        entered: str | None = None
        stage = 0

        for _ in range(max_steps):
            node = self.table.nodes[node_i]
            tr.path.append(node_i)

            code = self._strobe(node, trial, entered, stage)
            if code is not None:
                tr.emissions.append(
                    Emission(code=code, t=tr.t, node=node_i, name=vocab.name_of(code) or str(code))
                )

            if node.type is NodeType.TERMINAL:
                tr.ended = node.label
                return tr

            if node.symbol.startswith("sample_"):
                stage = int(node.symbol.rsplit("_", 1)[1])

            limit = self._duration(node, trial)
            trigger, entered = self._step(node, trial, subject, limit, tr, entered)
            node_i = self._resolve(node_i, trigger, trial, entered)
            if node_i is None:
                raise RuntimeError(
                    f"no edge for {trigger} out of S{tr.path[-1]:02d} — the linter "
                    f"should have made this impossible (TG401)"
                )

        raise RuntimeError(f"trial did not terminate in {max_steps} steps")

    def _step(self, node, trial, subject, limit, tr, entered):
        """Advance the clock and decide which trigger fired."""
        if node.type is NodeType.DELAY or node.type is NodeType.PULSE:
            tr.t += limit
            return (Trigger.TIMEOUT if node.type is NodeType.DELAY else Trigger.DONE), entered

        watching = self._watching(node, trial)
        a = subject.act(node.type, watching, limit)

        if node.type is NodeType.WAIT_ENTRY:
            if a.channel is None:
                tr.t += limit
                return Trigger.TIMEOUT, entered
            tr.t += min(a.dwell, limit)
            return Trigger.ENTER, a.channel

        if node.type is NodeType.HOLD:
            if a.sustained:
                tr.t += limit
                return Trigger.HELD, entered
            tr.t += min(a.dwell, limit)
            return Trigger.BROKEN, entered

        # WAIT_EXIT — unbounded, so the subject's dwell is the only clock there is.
        tr.t += a.dwell
        return Trigger.EXIT, entered

    def _resolve(self, node_i: int, trigger: Trigger, trial, entered) -> int | None:
        """First match wins, and the unguarded default is last — which is exactly
        what TG405 enforces, so this loop can be this simple."""
        for e in self._edges(node_i):
            if e.trigger is not trigger:
                continue
            if e.channel and e.channel != entered:
                continue
            if e.guard_text == "ch == @target" and entered != trial.target:
                continue
            if e.guard_text == "correction budget":
                continue  # policy decides; the caller drives repeats explicitly
            return e.target
        return None

"""Everything wrong with a task definition, located.

The rule this shares with the rig document: a definition that is WELL-FORMED and
describes an impossible task is not an error, it is a successful reply carrying
problems. `TASK_INVALID` is reserved for a document that is not a document.

Every rule here fails QUIETLY without a check, which is why each is an error
rather than a warning:

  TSK101  a channel this rig does not have     -> the pin never fires
  TSK102  a channel of the wrong kind          -> a valve driven as a sensor
  TSK103  a reward line serving the other well -> water to the wrong side
  TSK104  a strobe code that is not declared   -> an unlabelled event in the data
  TSK105  two types sharing an onset code      -> two conditions, one label
  TSK106  a stage schedule that is not ordered -> a row that never engages
  TSK107  a START line over the cap            -> the firmware truncates in silence
  TSK108  a table with no presentable trial    -> a session that runs nothing
  TSK109  a pool whose weights are all zero    -> a uniform pool, silently
  TSK110  a condition with no name             -> a chart titled after a channel
  TSK111  two conditions sharing a name        -> two curves, one title
  TSK113  a go condition paying 0 ms           -> a dry well scored as rewarded
  TSK114  an onset code not its line's own      -> a condition labelled as another odor

(TSK112 is the Task tab's own, derived client-side: an onset code no live
metric scores.)

TSK103, TSK105, TSK109, TSK113 and TSK114 are the five that produce
plausible-looking wrong DATA rather than an obvious failure, and are the reason
this file exists at all.

TSK110 and TSK111 are the naming pair, and they are errors for the same reason
TSK105 is: a condition is only ever read back by its NAME. It titles the live
sparkline, the learning curve and a strategy axis, and it is recorded into the
profile — so an unnamed one is read back as whichever channel happened to carry
it, and two identically named ones are two curves the operator cannot tell
apart. Naming every condition is the one thing the trial table cannot derive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..rig import registry
from ..tasks.profile import TaskProfileError
from ..tasks.start_command import build_start_command
from .model import TaskDefinition


@dataclass(frozen=True)
class Diagnostic:
    location: str
    message: str
    code: str

    def to_json(self) -> dict[str, Any]:
        return {"location": self.location, "message": self.message, "code": self.code}


def validate(definition: TaskDefinition) -> list[Diagnostic]:
    """Every problem, not the first.

    Fixing a new task should be one pass rather than a game of whack-a-mole —
    the same argument `ChannelMap.disagreements()` makes.
    """
    out: list[Diagnostic] = []
    channels = registry.channels()
    vocab = registry.vocabulary()

    out.extend(_trial_problems(definition, channels, vocab))
    out.extend(_reward_problems(definition))
    out.extend(_pool_problems(definition))
    out.extend(_stage_problems(definition))
    out.extend(_line_problems(definition))
    return out


def _trial_problems(definition, channels, vocab) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    seen_onsets: dict[str, int] = {}
    #: Compared case- and space-insensitively: "Go left" and "go  left" are the
    #: same name to everyone reading a chart, and only the picker would disagree.
    seen_names: dict[str, int] = {}
    presentable = 0

    for i, trial in enumerate(definition.trials):
        at = f"trials[{i}]"

        name = trial.label.strip()
        if not name:
            out.append(Diagnostic(
                f"{at}.label",
                "this condition has no name. Its name is what titles the live "
                "sparkline, the learning curve and the strategy axis, and it is "
                "recorded into the profile — unnamed, it is read back as "
                "whichever channel happened to carry it.",
                "TSK110",
            ))
        else:
            first = seen_names.setdefault(_name_key(name), i)
            if first != i:
                out.append(Diagnostic(
                    f"{at}.label",
                    f"trial type {first + 1} is already called {name!r}. Two "
                    "conditions under one name are two curves with one title, "
                    "and nothing downstream can tell which is which.",
                    "TSK111",
                ))

        emitter = channels.get(trial.odor_channel)
        if emitter is None:
            out.append(Diagnostic(
                f"{at}.odorChannel",
                # An unfinished row and a renamed channel are both TSK101 — the
                # code means "this row names no channel this rig has" — but they
                # need different sentences: one is a thing to finish, the other
                # is a thing that broke underneath you.
                "this trial type has no stimulus channel yet — pick the line "
                "that carries its odor."
                if not trial.odor_channel
                else f"this rig has no channel called {trial.odor_channel!r}. It "
                "was either renamed or removed in the Rig tab's wiring editor.",
                "TSK101",
            ))
        elif emitter.kind != "emitter":
            out.append(Diagnostic(
                f"{at}.odorChannel",
                f"{trial.odor_channel!r} is a {emitter.kind} channel, not a "
                "stimulus emitter. Driving it as one would fire the wrong "
                "hardware for the whole trial.",
                "TSK102",
            ))

        declared = emitter.onset_strobe if emitter is not None and emitter.kind == "emitter" else None
        if trial.onset_strobe not in vocab:
            out.append(Diagnostic(
                f"{at}.onsetStrobe",
                "this trial type has no onset code yet — pick the code it "
                "announces itself with, so the recording can name it."
                if not trial.onset_strobe
                else f"{trial.onset_strobe!r} is not a declared strobe code, so "
                "this stimulus would announce itself with a number nothing can "
                "decode. Add it to the vocabulary first.",
                "TSK104",
            ))
        else:
            first = seen_onsets.setdefault(trial.onset_strobe, i)
            if first != i:
                # An odor line declares ONE onset code (`TASKS.md#onset-codes`),
                # so sharing a code is sharing a line — say so in the terms the
                # editor shows.
                out.append(Diagnostic(
                    f"{at}.onsetStrobe",
                    f"trial type {first + 1} already presents this odor line "
                    f"({trial.onset_strobe}). Two conditions reporting one code "
                    "are indistinguishable in the data — every analysis would "
                    "pool them without saying so.",
                    "TSK105",
                ))
            if declared and declared != trial.onset_strobe:
                # THE PAIRING IS THE RIG'S. A trial carrying another line's code
                # records its odor under the wrong name for every session it
                # runs. Two fixes, and the message names both: which is right
                # depends on what the archive already says this bottle is.
                out.append(Diagnostic(
                    f"{at}.onsetStrobe",
                    f"{trial.odor_channel!r} announces its onset as {declared}, but "
                    f"this trial type records it as {trial.onset_strobe}. Use "
                    f"{declared} — or, if this bottle has always been recorded as "
                    f"{trial.onset_strobe}, change the line's onset code on the Rig "
                    "tab instead, so past and future sessions agree.",
                    "TSK114",
                ))

        if not trial.is_go:
            # A withhold type answers at no port and pays nothing; both being
            # absent is the definition of it, not an omission. Only the pool
            # PRESENTS one: both anti-bias selectors draw a side first, and a
            # no-go type has no side (`BehaviorBox.h`, `TASKS.md#selection-modes`).
            if definition.selection_mode == "pool":
                presentable += 1
            continue

        port = channels.get(trial.response_channel) if trial.response_channel else None
        if trial.response_channel is None:
            out.append(Diagnostic(
                f"{at}.responseChannel",
                "a go trial needs a correct response port. Leave it unset only "
                "on a no-go type, where withholding is the correct answer.",
                "TSK101",
            ))
        elif port is None:
            out.append(Diagnostic(
                f"{at}.responseChannel",
                f"this rig has no channel called {trial.response_channel!r}.",
                "TSK101",
            ))
        elif port.kind != "response":
            out.append(Diagnostic(
                f"{at}.responseChannel",
                f"{trial.response_channel!r} is a {port.kind} channel; only a "
                "response port can answer a trial.",
                "TSK102",
            ))
        elif port.port_slot is None:
            out.append(Diagnostic(
                f"{at}.responseChannel",
                f"{trial.response_channel!r} declares no strobe slot, so a poke "
                "there reports nothing at all. Set one in the Rig tab.",
                "TSK102",
            ))

        reward = channels.get(trial.reward_channel) if trial.reward_channel else None
        if trial.reward_channel is None:
            out.append(Diagnostic(
                f"{at}.rewardChannel",
                "a go trial needs a reward line to pay from.",
                "TSK101",
            ))
        elif reward is None:
            out.append(Diagnostic(
                f"{at}.rewardChannel",
                f"this rig has no channel called {trial.reward_channel!r}.",
                "TSK101",
            ))
        elif reward.kind != "reward":
            out.append(Diagnostic(
                f"{at}.rewardChannel",
                f"{trial.reward_channel!r} is a {reward.kind} channel, not a "
                "reward line.",
                "TSK102",
            ))
        elif port is not None and reward.well and reward.well != port.name:
            # THE ONE THAT LOOKS CORRECT ON SCREEN. The trial reads as
            # "odor 3 -> left well", the animal answers left, and the water
            # arrives on the right.
            out.append(Diagnostic(
                f"{at}.rewardChannel",
                f"{trial.reward_channel!r} is plumbed to {reward.well!r}, but "
                f"this trial is answered at {port.name!r}. The animal would be "
                "rewarded at the well it did not choose.",
                "TSK103",
            ))
        else:
            presentable += 1

    if definition.trials and presentable == 0:
        only_nogo = all(not trial.is_go for trial in definition.trials)
        out.append(Diagnostic(
            "trials",
            "every trial type here is no-go, and only Pool selection presents a "
            "no-go type — anti-bias draws a side first, and a withhold has none. "
            "Switch to Pool, or add a go type."
            if only_nogo and definition.selection_mode != "pool"
            else "no trial type in this table can actually be presented, so a "
            "session would run nothing.",
            "TSK108",
        ))
    if not definition.trials:
        out.append(Diagnostic(
            "trials", "a task needs at least one trial type.", "TSK108"
        ))
    return out


def _name_key(name: str) -> str:
    """What counts as the same name on a chart, rather than to a picker."""
    return " ".join(name.lower().split())


def _pool_problems(definition: TaskDefinition) -> list[Diagnostic]:
    """A weighted pool that adds up to nothing.

    THE FIRMWARE ALREADY SURVIVES THIS, which is exactly why it needs saying.
    `generateTrials()` sums the weights and would divide by that total, so an
    all-zero pool falls back to weighting every row equally — on AVR a division
    by zero is a silent wrong answer rather than a trap, and a hung box
    mid-shaping would be worse than a defined session. The consequence is that
    the box runs a UNIFORM pool and reports nothing unusual: the table on screen
    says one thing and the session presents another, for as long as nobody
    checks the trial counts.

    The likeliest way to arrive here is zeroing rows to disable them and then
    zeroing the last one too. A zero on SOME rows is deliberate and supported —
    that row is inert, which is how a type is parked without deleting it — so
    this fires only on the total, and only in the modes that read weights at
    all: the pool, and weighted anti-bias, whose within-side draw makes the
    same uniform fallback. Plain anti-bias draws a side and weights nothing.
    """
    if definition.selection_mode == "antibias" or not definition.trials:
        return []
    if definition.selection_mode == "weighted":
        return _side_weight_problems(definition)
    # `<= 0` rather than `== 0`: this mirrors `generateTrials()`'s own condition,
    # so the two agree about the edge even if a negative weight ever reaches it.
    if sum(trial.weight for trial in definition.trials) > 0:
        return []
    return [Diagnostic(
        "trials",
        "every trial type in this pool has a weight of zero, so there is "
        "nothing to draw from. The firmware falls back to equal weights rather "
        "than dividing by zero, so the session would quietly run a uniform "
        "pool instead of the proportions in this table.",
        "TSK109",
    )]


def _side_weight_problems(definition: TaskDefinition) -> list[Diagnostic]:
    """Weighted anti-bias: a SIDE whose go types all weigh zero.

    The total is the wrong test here. `pickWeighted` draws a side against the
    animal's bias first and only then weighs the types on that side, falling
    back to a uniform draw when the side's weights sum to nothing — so one side
    zeroed out runs uniformly while the other runs the table, and the totals
    look fine.
    """
    sides: dict[str, list[float]] = {}
    for trial in definition.trials:
        if trial.is_go and trial.response_channel:
            sides.setdefault(trial.response_channel, []).append(trial.weight)
    return [
        Diagnostic(
            "trials",
            f"every trial type answered at {side!r} has a weight of zero. Weighted "
            "selection draws a side first, then a type on it by weight — so this "
            "side would quietly be drawn uniformly instead of by this table.",
            "TSK109",
        )
        for side, weights in sorted(sides.items())
        if sum(weights) <= 0
    ]


def _stage_problems(definition: TaskDefinition) -> list[Diagnostic]:
    """The ramp must be strictly ascending after row 0.

    `liveStage()` scans DOWN and returns the first row whose count is reached,
    so an out-of-order row is not an error the firmware can see — it is simply
    a row that never engages, and the ramp appears to skip a step.
    """
    out: list[Diagnostic] = []
    previous = 0
    for i, stage in enumerate(definition.stages):
        if i == 0:
            # Row 0 is live from trial 0 by construction; its count is not read.
            continue
        if stage.trials <= previous:
            out.append(Diagnostic(
                f"stages[{i}].trials",
                f"stage {i} engages at trial {stage.trials}, which is not after "
                f"stage {i - 1}'s {previous}. The ramp is scanned downward, so "
                "this row would never take over — the schedule would look like "
                "it skipped a step.",
                "TSK106",
            ))
        previous = max(previous, stage.trials)
    return out


def _reward_problems(definition: TaskDefinition) -> list[Diagnostic]:
    """A go condition that pays nothing.

    The firmware opens the line for `rewardTime` ms and strobes FLUID/STOP_FLUID
    either side of it regardless, so a 0 ms reward is a dry well that every
    readout scores as a rewarded, correct trial. The value used to be per fluid
    line with the same floor; per condition there are more places to type it,
    and a 0 is the one value that is never what an operator meant.
    """
    return [
        Diagnostic(
            f"trials[{i}].rewardTime",
            "this condition pays 0 ms — the well stays dry while the recording "
            "scores the trial as rewarded",
            "TSK113",
        )
        for i, trial in enumerate(definition.trials)
        if trial.is_go and trial.reward_time <= 0
    ]


def _line_problems(definition: TaskDefinition) -> list[Diagnostic]:
    """The built `START` line must fit, checked rather than trusted.

    `readLineInto()` truncates an overlong line and drops the rest, and the
    board cannot report that — the session runs on whichever values happened to
    fit. So the generator refuses instead, which is the same discipline
    `build_start_command` already applies (`TASKS.md#the-length-cap`).
    """
    from .generate import build_profile  # local: generate imports this module

    try:
        profile = build_profile(definition)
        config = {f.metadata_key: f.default for f in profile.config}
        build_start_command(profile, config)
    except TaskProfileError as exc:
        return [Diagnostic("params", str(exc), "TSK107")]
    except Exception:  # pragma: no cover - a generator crash is not a task fault
        return []
    return []

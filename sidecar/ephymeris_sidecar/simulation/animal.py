"""The simulated animal (`TASKS.md#the-simulated-animal`).

It is told only what an animal in the box could sense, and answers only by
breaking beams: the trial light, the odor reaching the port (the vacuum closing
with an odor line open), the odor ending, and water. It never reads a strobe or
a task parameter, so a task that asks for more than this animal gives fails the
way it would with a real one.

Its randomness is its own `random.Random`, never the session's: the board's
draws depend on the seed alone, whatever the animal does.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, fields
from typing import Any, Mapping

from .errors import SimulationError

FALLBACKS = ("side", "winStay", "alternate", "repeat")

_DRINKING_MS = 60_000
_WITHDRAW_MS = (50, 250)
_LICK_MS = (300, 900)
_BAIL_SHARE = (0.05, 0.4)
_WELL_BAIL_MS = (20, 120)
_SPREAD = (0.5, 1.5)
_HOLD_SPREAD = (0.6, 1.4)


class AnimalError(SimulationError):
    """An animal the simulation cannot be asked for."""


@dataclass(frozen=True)
class Animal:
    """What the animal is like. Shares are 0 to 1, times are ms.

    - `follows_odor`, `follows_odor_end`: how often it answers by the odor, at
      the session's start and once learned; `learning_trials` is the sampled
      trials it takes to move from one to the other (0: at the end from the start).
    - `fallback`: what it does when it is not answering by the odor.
    - `side_bias`: -1 is always left, 1 always right; its first pick under any fallback.
    - `initiates`: how often it starts a trial when the light comes on.
    - `satiates_after`: rewards after which it starts to stop initiating; 0 is never.
    - `answers`: how often it answers at a well once it has sampled.
    - `leaves_early`: how often it pulls out of the odor port on impulse.
    - `drops_hold`: how often it leaves a well before water could come.
    - `hold_ms`, `reaction_ms`: about how long it can hold a poke, and takes to act.
    """

    follows_odor: float = 0.9
    follows_odor_end: float = 0.9
    learning_trials: int = 0
    fallback: str = "side"
    side_bias: float = 0.0
    initiates: float = 0.97
    satiates_after: int = 0
    answers: float = 0.98
    leaves_early: float = 0.03
    drops_hold: float = 0.03
    hold_ms: int = 2500
    reaction_ms: int = 600

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> "Animal":
        wire = {_camel(f.name): f for f in fields(cls)}
        unknown = sorted(set(raw) - set(wire))
        if unknown:
            raise AnimalError(f"An animal has no {', '.join(unknown)}.")
        values: dict[str, Any] = {}
        for key, value in raw.items():
            field = wire[key]
            if field.name == "fallback":
                if value not in FALLBACKS:
                    raise AnimalError(f"An animal falls back on one of {', '.join(FALLBACKS)}.")
                values[field.name] = value
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AnimalError(f"An animal's {key} is a number.")
            values[field.name] = int(value) if field.type == "int" else float(value)
        animal = cls(**values)
        animal._check()
        return animal

    def to_json(self) -> dict[str, Any]:
        return {_camel(f.name): getattr(self, f.name) for f in fields(self)}

    def _check(self) -> None:
        for name in ("follows_odor", "follows_odor_end", "initiates", "answers",
                     "leaves_early", "drops_hold"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise AnimalError(f"An animal's {_camel(name)} is a share from 0 to 1.")
        if not -1.0 <= self.side_bias <= 1.0:
            raise AnimalError("An animal's sideBias runs from -1 (left) to 1 (right).")
        if not 0 <= self.learning_trials <= 100_000:
            raise AnimalError("An animal learns over 0 to 100000 trials.")
        if not 0 <= self.satiates_after <= 100_000:
            raise AnimalError("An animal sates after 0 to 100000 rewards.")
        if not 50 <= self.hold_ms <= 60_000:
            raise AnimalError("An animal holds a poke for 50 ms to 60 s.")
        if not 50 <= self.reaction_ms <= 60_000:
            raise AnimalError("An animal reacts in 50 ms to 60 s.")


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


@dataclass(frozen=True)
class Condition:
    """What one odor line asks for: a side, or `None` to withhold."""

    side: str | None


class Rat:
    """One animal through one session: `sense` an output changing, get back the
    beam lines to say (`tasksim.cpp`'s `L` and `X`)."""

    def __init__(self, animal: Animal, conditions: Mapping[int, Condition], seed: int) -> None:
        self._animal = animal
        self._conditions = dict(conditions)
        self._random = random.Random(f"animal-{seed}")
        self._open_odors: set[int] = set()
        self._odor: int | None = None
        self._in_port: tuple[int, int] | None = None
        self._sampled = False
        self._at_well: tuple[str, int, int] | None = None
        self._last_choice: str | None = None
        self._last_rewarded = False
        self._rewards = 0
        self._sampled_trials = 0

    def sense(self, at: int, output: str, level: int) -> list[str]:
        if output.startswith("odor"):
            line = int(output[4:])
            (self._open_odors.add if level else self._open_odors.discard)(line)
            return []
        if output == "light":
            return self._light_on(at) if level else self._light_off(at)
        if output == "vac":
            return self._odor_arrives(at) if level else self._odor_ends(at)
        if output.startswith("fluid"):
            return self._water_on(at) if level else self._water_off(at)
        return []

    def _between(self, low: float, high: float) -> int:
        return int(self._random.uniform(low, high))

    def _about(self, ms: int, spread: tuple[float, float] = _SPREAD) -> int:
        return max(1, self._between(ms * spread[0], ms * spread[1]))

    def _engagement(self) -> float:
        sated = self._animal.satiates_after
        if sated <= 0 or self._rewards <= sated:
            return self._animal.initiates
        return self._animal.initiates * max(0.0, 1.0 - (self._rewards - sated) / (0.5 * sated))

    def _light_on(self, at: int) -> list[str]:
        self._odor = None
        self._sampled = False
        self._in_port = None
        if self._random.random() >= self._engagement():
            return []
        poke = at + self._about(self._animal.reaction_ms)
        if self._random.random() < self._animal.leaves_early:
            stay = max(1, self._between(*(self._animal.hold_ms * share for share in _BAIL_SHARE)))
        else:
            stay = self._about(self._animal.hold_ms, _HOLD_SPREAD)
        self._in_port = (poke, poke + stay)
        return ["X odor", f"L odor {poke} {poke + stay}"]

    def _odor_arrives(self, at: int) -> list[str]:
        if self._in_port is None or not self._open_odors:
            return []
        if self._in_port[1] > at:
            self._odor = min(self._open_odors)
        return []

    def _odor_ends(self, at: int) -> list[str]:
        if self._in_port is None or self._odor is None:
            return []
        poke, leave = self._in_port
        if leave <= at:
            return []
        self._sampled = True
        self._sampled_trials += 1
        leave = min(leave, at + self._between(*_WITHDRAW_MS))
        self._in_port = (poke, leave)
        return ["X odor", f"L odor {poke} {leave}"]

    def _light_off(self, at: int) -> list[str]:
        if not self._sampled or self._odor is None:
            return []
        self._sampled = False
        choice = self._choice(self._conditions.get(self._odor, Condition(None)))
        if choice is None or self._random.random() >= self._animal.answers:
            return []
        self._last_choice = choice
        self._last_rewarded = False
        arrive = at + self._about(self._animal.reaction_ms)
        if self._random.random() < self._animal.drops_hold:
            stay = self._between(*_WELL_BAIL_MS)
        else:
            stay = self._about(self._animal.hold_ms, _HOLD_SPREAD)
        self._at_well = (choice, arrive, arrive + stay)
        return ["X left", "X right", f"L {choice} {arrive} {arrive + stay}"]

    def _water_on(self, at: int) -> list[str]:
        self._rewards += 1
        self._last_rewarded = True
        if self._at_well is None:
            return []
        well, arrive, _ = self._at_well
        self._at_well = (well, arrive, at + _DRINKING_MS)
        return [f"X {well}", f"L {well} {arrive} {at + _DRINKING_MS}"]

    def _water_off(self, at: int) -> list[str]:
        if self._at_well is None:
            return []
        well, arrive, _ = self._at_well
        leave = at + self._between(*_LICK_MS)
        self._at_well = None
        return [f"X {well}", f"L {well} {arrive} {leave}"]

    def _follows_odor(self) -> float:
        animal = self._animal
        if animal.learning_trials <= 0:
            return animal.follows_odor_end
        done = min(1.0, (self._sampled_trials - 1) / animal.learning_trials)
        eased = done * done * (3.0 - 2.0 * done)
        return animal.follows_odor + (animal.follows_odor_end - animal.follows_odor) * eased

    def _choice(self, condition: Condition) -> str | None:
        """The well it goes to, or None when it holds back."""
        if self._random.random() < self._follows_odor():
            return condition.side
        other = {"left": "right", "right": "left"}
        fallback = self._animal.fallback
        if self._last_choice is not None and fallback != "side":
            if fallback == "repeat":
                return self._last_choice
            if fallback == "alternate":
                return other[self._last_choice]
            return self._last_choice if self._last_rewarded else other[self._last_choice]
        return "right" if self._random.random() < 0.5 + 0.5 * self._animal.side_bias else "left"

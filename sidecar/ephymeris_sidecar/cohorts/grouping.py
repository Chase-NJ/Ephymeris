"""Auto-Balance grouping — `DATA.md#auto-balance`.

A balanced round-robin, deliberately *not* an optimisation search: simple,
deterministic, and easy to explain when a user asks why an animal landed where
it did. Pure functions with no database access, so the behaviour the spec
describes can be tested directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

from .models import MAX_GROUP_SIZE, Animal

#: Buckets are walked in this order so the result is stable.
SEX_BUCKETS = ("M", "F", None)


@dataclass(frozen=True)
class ProposedAnimal:
    animal_id: str
    box_number: int

    def to_json(self) -> dict[str, Any]:
        return {"animalId": self.animal_id, "boxNumber": self.box_number}


@dataclass(frozen=True)
class ProposedGroup:
    name: str
    order: int
    animals: list[ProposedAnimal]

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "order": self.order,
            "animals": [a.to_json() for a in self.animals],
        }


@dataclass(frozen=True)
class GroupProposal:
    groups: list[ProposedGroup]
    rejected: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "groups": [g.to_json() for g in self.groups],
            "rejected": self.rejected,
        }


def minimum_group_count(animal_count: int) -> int:
    """The hard constraint — the fewest groups that can hold this roster."""
    return max(1, math.ceil(animal_count / MAX_GROUP_SIZE))


def resolve_group_count(
    animal_count: int,
    group_count: int | None,
    max_group_size: int | None,
) -> int:
    """The inputs — the user gives one of the two; the other is derived."""
    if group_count is not None and group_count > 0:
        return group_count
    if max_group_size is not None and max_group_size > 0:
        return max(1, math.ceil(animal_count / max_group_size))
    # Neither supplied: fall back to the smallest workable split.
    return minimum_group_count(animal_count)


def _bucket(animal: Animal) -> str | None:
    """Only M/F carry balancing information; `unknown` and null are the same."""
    return animal.sex if animal.sex in ("M", "F") else None


def suggest_groups(
    animals: Iterable[Animal],
    group_count: int | None = None,
    max_group_size: int | None = None,
    balance_by_sex: bool = False,
) -> GroupProposal:
    """Propose a complete grouping (`DATA.md#auto-balance`).

    Always a **full re-proposal** — it considers the entire roster and ignores
    whatever grouping already exists. Nothing is written; the caller
    previews this and commits via `cohorts.update`.
    """
    roster = list(animals)
    target = resolve_group_count(len(roster), group_count, max_group_size)

    # The hard constraint — reject rather than silently producing an
    # unassignable group.
    minimum = minimum_group_count(len(roster))
    if roster and target < minimum:
        return GroupProposal(
            groups=[],
            rejected={
                "reason": (
                    f"{len(roster)} animals can't fit in {target} "
                    f"group{'s' if target != 1 else ''} — no group may exceed "
                    f"{MAX_GROUP_SIZE}, since box numbers only span 1–{MAX_GROUP_SIZE}."
                ),
                "minimumGroups": minimum,
            },
        )

    buckets: dict[str | None, list[Animal]] = {key: [] for key in SEX_BUCKETS}
    for animal in roster:
        # With balancing off everything shares one bucket, which reduces the
        # walk below to a plain round-robin over the roster.
        buckets[_bucket(animal) if balance_by_sex else None].append(animal)

    assigned: list[list[Animal]] = [[] for _ in range(target)]

    # Walk each bucket in turn, cycling group index. Continuing the
    # cursor *across* buckets rather than restarting at 0 is what keeps overall
    # group sizes within one of each other — restarting would pile every
    # bucket's first few animals onto the low-numbered groups.
    cursor = 0
    for key in SEX_BUCKETS:
        for animal in buckets[key]:
            assigned[cursor % target].append(animal)
            cursor += 1

    groups: list[ProposedGroup] = []
    for index, members in enumerate(assigned):
        groups.append(
            ProposedGroup(
                name=f"Group {index + 1}",
                order=index,
                animals=[
                    # Boxes number sequentially in landing order,
                    # making the tedious part a byproduct of grouping.
                    ProposedAnimal(animal_id=a.id, box_number=slot + 1)
                    for slot, a in enumerate(members)
                ],
            )
        )
    return GroupProposal(groups=groups)

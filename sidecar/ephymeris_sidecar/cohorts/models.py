"""Cohort/Animal/Group data model — `cohorts.md` §1.

`to_json` produces exactly the payload shapes documented in
`websocket-protocol.md` §4, so the wire format is defined in one place rather
than assembled ad hoc at each call site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Sex = Literal["M", "F", "unknown"]

#: The surfaces the planet shader can draw (`cohorts.md` §5). Validated here so
#: a value the renderer cannot draw never reaches the store; anything else is
#: refused rather than silently coerced, because a cohort saved with a typo
#: would come back looking like a different world.
PLANET_TYPES = ("rocky", "gas", "ice", "ocean", "lava")

#: `boxNumber` spans an abstract slot range, validated against nothing else.
MIN_BOX = 1
MAX_BOX = 6

#: §7.2 — no group may exceed this, since a larger one could never be uniquely
#: box-assigned within itself.
MAX_GROUP_SIZE = MAX_BOX


@dataclass
class Appearance:
    """How a cohort's world looks — the operator's four choices (§5).

    **Absent is the normal state and is not a gap.** A cohort with no
    appearance derives all four from a hash of its `id`, exactly as the icon it
    replaced always did, so every cohort that has ever existed already has a
    stable, distinct planet. Storing a derived record would freeze that cohort
    against any later correction to the palette or the default type.

    `seed` shifts the noise field and nothing else: a re-roll changes the
    world's weather, never its type, hue or size. That split is what lets an
    operator hunt for a pattern they like without losing the identity they
    already recognise.
    """

    type: str
    hue: float
    ring: bool
    seed: float

    def to_json(self) -> dict[str, Any]:
        return {"type": self.type, "hue": self.hue, "ring": self.ring, "seed": self.seed}

    @staticmethod
    def from_json(raw: Any) -> "Appearance | None":
        """`None` in, `None` out — absent and malformed both mean "derive it".

        Malformed is treated as absent rather than raised on for the same reason
        `TaskStore.get` logs a broken definition and returns None: a cohort is a
        roster of real animals and a folder of real recordings, and refusing to
        load it over a decorative field would be the wrong trade every time.
        """
        if not isinstance(raw, dict):
            return None
        kind = raw.get("type")
        if kind not in PLANET_TYPES:
            return None
        try:
            hue = float(raw["hue"]) % 360
            seed = float(raw["seed"])
        except (KeyError, TypeError, ValueError):
            return None
        return Appearance(type=kind, hue=hue, ring=bool(raw.get("ring", False)), seed=seed)


@dataclass
class Group:
    id: str
    name: str
    order: int

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "order": self.order}


@dataclass
class Animal:
    id: str
    name: str
    group_id: str
    box_number: int | None = None
    #: Home-cage number — cagemates share one. A grouping label (≥ 1), not a
    #: slot: any number of animals may share a cage, across groups included,
    #: because housing and run order are independent facts.
    cage: int | None = None
    sex: Sex | None = None
    id_number: str | None = None
    notes: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "groupId": self.group_id,
            "boxNumber": self.box_number,
            "cage": self.cage,
            "sex": self.sex,
            "idNumber": self.id_number,
            "notes": self.notes,
        }


@dataclass
class Cohort:
    id: str
    name: str
    data_folder: str
    created_at: str
    updated_at: str
    archived_at: str | None = None
    animals: list[Animal] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    #: None means "derive from `id`" — see `Appearance`.
    appearance: Appearance | None = None

    @property
    def cage_count(self) -> int:
        """Distinct home cages. Cageless animals contribute nothing.

        The browser draws one orbiting ship per cage, and an animal with no
        cage rides alone in the rig views — but that is a rig fact about who is
        running, not a housing fact, so it earns no craft here.
        """
        return len({a.cage for a in self.animals if a.cage is not None})

    @property
    def archived(self) -> bool:
        return self.archived_at is not None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "dataFolder": self.data_folder,
            "animals": [a.to_json() for a in self.animals],
            "groups": [g.to_json() for g in sorted(self.groups, key=lambda g: g.order)],
            "archivedAt": self.archived_at,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            # Null on almost every cohort, and that is the answer rather than a
            # missing one: the client derives the world from `id` (§5).
            "appearance": self.appearance.to_json() if self.appearance else None,
        }

    def to_summary(self) -> dict[str, Any]:
        """The grid/dashboard shape — no animal or group detail (§10).

        `assignedBoxes` and `cageCount` are the two exceptions to "no animal
        detail", and both earn it the same way — the browser needs the answer
        for every cohort at once, and without them each answer costs a full
        `cohorts.get` per planet on every route mount. The browser has to say
        whether a cohort's boxes still exist on this machine, and it draws one
        orbiting ship per home cage. Distinct boxes and a cage *count* only:
        which animal holds a box, or shares a cage, is the editor's business.
        """
        return {
            "id": self.id,
            "name": self.name,
            "animalCount": len(self.animals),
            "groupCount": len(self.groups),
            "assignedBoxes": sorted(
                {a.box_number for a in self.animals if a.box_number is not None}
            ),
            "cageCount": self.cage_count,
            "archived": self.archived,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "appearance": self.appearance.to_json() if self.appearance else None,
        }


class ValidationError(Exception):
    """One or more §2 rules were broken.

    Carries per-field detail so the editor can render errors inline against the
    offending row rather than as a detached toast (§6).
    """

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


class CohortNotFound(Exception):
    pass


class NameTaken(Exception):
    """Name already belongs to an *active* cohort (§2)."""


class NotArchived(Exception):
    """Permanent delete attempted before archiving (§9's two-step guard)."""

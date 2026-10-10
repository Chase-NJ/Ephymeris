"""Cohort/Animal/Group data model — `DATA.md#data-model`.

`to_json` produces exactly the payload shapes documented in
`PROTOCOL.md#payload-shapes`, so the wire format is defined in one place rather
than assembled ad hoc at each call site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Sex = Literal["M", "F", "unknown"]

#: The surfaces the planet shader can draw (`ARCHITECTURE.md#cohort-browser`). Validated here so
#: a value the renderer cannot draw never reaches the store; anything else is
#: refused rather than silently coerced, because a cohort saved with a typo
#: would come back looking like a different world.
PLANET_TYPES = ("rocky", "gas", "ice", "ocean", "lava")

#: `boxNumber` spans an abstract slot range, validated against nothing else.
MIN_BOX = 1
MAX_BOX = 6

#: No group may exceed this (`DATA.md#auto-balance`), since a larger one could never be uniquely
#: box-assigned within itself.
MAX_GROUP_SIZE = MAX_BOX


@dataclass
class Appearance:
    """How a cohort's world looks — the operator's four choices (`ARCHITECTURE.md#cohort-browser`).

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
class FormerAnimal:
    """An animal that has history in a cohort but is no longer on its roster
    (`DATA.md#former-members`).

    Two sources, one shape. `removed` is a roster removal the cohort kept a row
    for; `files` is an id the cohort's runs, adoptions or notes still name with
    no row anywhere — a removal from before former members existed — named from
    its files' stems and never stored. Either way the history behind it is
    real, and a name is what lets every view show it as an animal rather than an
    id.
    """

    id: str
    #: Null only for a `files` id whose paths name no animal — a note-only id.
    name: str | None
    source: Literal["removed", "files"]
    removed_at: str | None = None
    #: Recorded plus adopted runs this cohort holds for the animal.
    run_count: int = 0
    sex: Sex | None = None
    id_number: str | None = None
    cage: int | None = None
    notes: str | None = None
    #: The group it was in, by name: groups are rewritten on every roster edit,
    #: so an id would dangle by the next save.
    group_name: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "removedAt": self.removed_at,
            "runCount": self.run_count,
            "sex": self.sex,
            "idNumber": self.id_number,
            "cage": self.cage,
            "notes": self.notes,
            "groupName": self.group_name,
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
    #: Animals with history here that are no longer on the roster. Filled only
    #: when one cohort is loaded on its own (`CohortRepository.get`); a listing
    #: never needs it and leaves it empty.
    former_animals: list[FormerAnimal] = field(default_factory=list)

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
            # missing one: the client derives the world from `id` (`ARCHITECTURE.md#cohort-browser`).
            "appearance": self.appearance.to_json() if self.appearance else None,
            "formerAnimals": [a.to_json() for a in self.former_animals],
        }

    def to_summary(self) -> dict[str, Any]:
        """The grid/dashboard shape — no animal or group detail (`PROTOCOL.md#shape-cohortsummary`).

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
    """One or more validation rules (`DATA.md#validation`) were broken.

    Carries per-field detail so the editor can render errors inline against the
    offending row rather than as a detached toast.
    """

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


class CohortNotFound(Exception):
    pass


class NameTaken(Exception):
    """Name already belongs to an *active* cohort (`DATA.md#validation`)."""


class NotArchived(Exception):
    """Permanent delete attempted before archiving (the two-step guard, `DATA.md#archive-and-delete`)."""

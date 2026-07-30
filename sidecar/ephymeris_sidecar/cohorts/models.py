"""Cohort/Animal/Group data model — `cohorts.md` §1.

`to_json` produces exactly the payload shapes documented in
`websocket-protocol.md` §4, so the wire format is defined in one place rather
than assembled ad hoc at each call site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Sex = Literal["M", "F", "unknown"]

#: `boxNumber` spans an abstract slot range, validated against nothing else.
MIN_BOX = 1
MAX_BOX = 6

#: §7.2 — no group may exceed this, since a larger one could never be uniquely
#: box-assigned within itself.
MAX_GROUP_SIZE = MAX_BOX


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

    @property
    def archived(self) -> bool:
        return self.archived_at is not None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "dataFolder": self.data_folder,
            # The icon is derived client-side from `id` (§5) — nothing to send.
            "animals": [a.to_json() for a in self.animals],
            "groups": [g.to_json() for g in sorted(self.groups, key=lambda g: g.order)],
            "archivedAt": self.archived_at,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    def to_summary(self) -> dict[str, Any]:
        """The grid/dashboard shape — no animal or group detail (§10).

        `assignedBoxes` is the one exception to "no animal detail", and it
        earns it: the browser grid has to say whether a cohort's boxes still
        exist on this machine, and without it that answer needs a full
        `cohorts.get` per card. Distinct numbers only — *which* animal holds a
        box is the editor's business, not the grid's.
        """
        return {
            "id": self.id,
            "name": self.name,
            "animalCount": len(self.animals),
            "groupCount": len(self.groups),
            "assignedBoxes": sorted(
                {a.box_number for a in self.animals if a.box_number is not None}
            ),
            "archived": self.archived,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
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

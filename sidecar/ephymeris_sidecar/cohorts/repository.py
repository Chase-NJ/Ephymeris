"""Cohort persistence and validation — `DATA.md#data-model`, `DATA.md#validation`,
`DATA.md#archive-and-delete`.

Synchronous by design; callers wrap these in `asyncio.to_thread`. Every method
takes the database lock, so a single mutation is atomic with respect to any
other.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from .db import Database
from .members import former_members, referenced_animal_ids
from .models import (
    MAX_BOX,
    MIN_BOX,
    Animal,
    Appearance,
    Cohort,
    CohortNotFound,
    Group,
    NameTaken,
    NotArchived,
    ValidationError,
)

log = logging.getLogger(__name__)

DEFAULT_GROUP_NAME = "Group 1"
VALID_SEX = {"M", "F", "unknown"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return str(uuid.uuid4())


class CohortRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- reads ------------------------------------------------------------

    def list_cohorts(self) -> list[Cohort]:
        with self._db.lock:
            return self._load_all(self._db.conn)

    def get(self, cohort_id: str) -> Cohort:
        with self._db.lock:
            cohort = self._load_one(self._db.conn, cohort_id)
        if cohort is None:
            raise CohortNotFound(cohort_id)
        return cohort

    # --- writes -----------------------------------------------------------

    def create(
        self,
        name: str,
        data_folder: str,
        animals: Any = None,
        groups: Any = None,
    ) -> Cohort:
        """Create a cohort, optionally with its whole roster in one go.

        The editor builds animals and groups client-side, with their own ids,
        before the cohort exists — so it used to create and then immediately
        patch. Two round trips meant two ways to fail, and the second one
        failing left a named, empty cohort nobody asked for. Accepting the
        roster here makes creation atomic: it is validated *before* any row is
        written, so a rejected roster leaves no cohort and no folder behind.
        """
        clean = (name or "").strip()
        if not clean:
            raise ValidationError({"name": "Give the cohort a name."})

        # Parse and validate before touching the database, so a bad roster and
        # a taken name fail the same way regardless of write order. Both
        # parsers already turn `None` into the empty/default case, which is
        # exactly the no-roster create.
        parsed_groups = _parse_groups(groups)
        parsed_animals = _parse_animals(animals)
        _validate(parsed_animals, parsed_groups)

        now = _now()
        cohort_id = _new_id()
        with self._db.lock:
            conn = self._db.conn
            self._assert_name_free(conn, clean, exclude_id=None)
            _assert_ids_free(conn, parsed_animals, cohort_id)
            try:
                conn.execute(
                    "INSERT INTO cohorts (id, name, data_folder, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (cohort_id, clean, data_folder, now, now),
                )
                # Groups always exist (`DATA.md#data-model`), even implicitly, so "grouped" and
                # "ungrouped" cohorts stay one code path.
                for group in parsed_groups:
                    conn.execute(
                        'INSERT INTO groups (id, cohort_id, name, "order")'
                        " VALUES (?, ?, ?, ?)",
                        (group.id, cohort_id, group.name, group.order),
                    )
                for animal in parsed_animals:
                    conn.execute(
                        "INSERT INTO animals"
                        " (id, cohort_id, group_id, name, box_number, cage, sex, id_number, notes)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            animal.id,
                            cohort_id,
                            animal.group_id,
                            animal.name,
                            animal.box_number,
                            animal.cage,
                            animal.sex,
                            animal.id_number,
                            animal.notes,
                        ),
                    )
                conn.commit()
            except sqlite3.IntegrityError as exc:  # pragma: no cover - raced insert
                conn.rollback()
                raise NameTaken(clean) from exc
            cohort = self._load_one(conn, cohort_id)
        assert cohort is not None
        return cohort

    def update(self, cohort_id: str, patch: dict[str, Any]) -> Cohort:
        """Apply a name/animals/groups patch.

        Animals and groups are replaced wholesale when present, which is what
        the editor sends and what Auto-Balance's apply step needs (`DATA.md#auto-balance`).

        **An animal left out of the posted roster is not simply deleted**
        (`DATA.md#former-members`). One with history here — a run, an adoption,
        a note — becomes a former member, keeping its id and name so that
        history still reads as an animal. One with none was a typo or a
        placeholder and goes, as before. Posting a former member's id again
        restores it, history and all.
        """
        with self._db.lock:
            conn = self._db.conn
            existing = self._load_one(conn, cohort_id)
            if existing is None:
                raise CohortNotFound(cohort_id)

            name = existing.name
            if "name" in patch:
                name = (patch["name"] or "").strip()
                if not name:
                    raise ValidationError({"name": "Give the cohort a name."})
                self._assert_name_free(conn, name, exclude_id=cohort_id)

            groups = (
                _parse_groups(patch["groups"]) if "groups" in patch else existing.groups
            )
            animals = (
                _parse_animals(patch["animals"]) if "animals" in patch else existing.animals
            )
            _validate(animals, groups)
            if "animals" in patch:
                _assert_ids_free(conn, animals, cohort_id)

            # Absent leaves it alone; an explicit null RESETS the world to the
            # one derived from the cohort's id. The two are different requests
            # and `"appearance" in patch` is the only thing that tells them
            # apart, which is why this reads the key rather than the value.
            appearance = existing.appearance
            if "appearance" in patch:
                appearance = Appearance.from_json(patch["appearance"])

            try:
                conn.execute(
                    "UPDATE cohorts SET name = ?, appearance_json = ?, updated_at = ?"
                    " WHERE id = ?",
                    (
                        name,
                        json.dumps(appearance.to_json()) if appearance else None,
                        _now(),
                        cohort_id,
                    ),
                )
                if "animals" in patch:
                    _keep_former(conn, cohort_id, existing, animals)
                if "groups" in patch or "animals" in patch:
                    # Animals reference groups, so clear animals first to avoid
                    # tripping the foreign key while groups are being rewritten.
                    conn.execute("DELETE FROM animals WHERE cohort_id = ?", (cohort_id,))
                    conn.execute("DELETE FROM groups WHERE cohort_id = ?", (cohort_id,))
                    for group in groups:
                        conn.execute(
                            'INSERT INTO groups (id, cohort_id, name, "order")'
                            " VALUES (?, ?, ?, ?)",
                            (group.id, cohort_id, group.name, group.order),
                        )
                    for animal in animals:
                        conn.execute(
                            "INSERT INTO animals"
                            " (id, cohort_id, group_id, name, box_number, cage, sex, id_number, notes)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                animal.id,
                                cohort_id,
                                animal.group_id,
                                animal.name,
                                animal.box_number,
                                animal.cage,
                                animal.sex,
                                animal.id_number,
                                animal.notes,
                            ),
                        )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise ValidationError({"_": f"Couldn't save the cohort: {exc}"}) from exc

            cohort = self._load_one(conn, cohort_id)
        assert cohort is not None
        return cohort

    def set_data_folder(self, cohort_id: str, path: str) -> Cohort:
        with self._db.lock:
            conn = self._db.conn
            if self._load_one(conn, cohort_id) is None:
                raise CohortNotFound(cohort_id)
            conn.execute(
                "UPDATE cohorts SET data_folder = ?, updated_at = ? WHERE id = ?",
                (path, _now(), cohort_id),
            )
            conn.commit()
            cohort = self._load_one(conn, cohort_id)
        assert cohort is not None
        return cohort

    def archive(self, cohort_id: str) -> Cohort:
        return self._set_archived(cohort_id, _now())

    def restore(self, cohort_id: str) -> Cohort:
        with self._db.lock:
            conn = self._db.conn
            existing = self._load_one(conn, cohort_id)
            if existing is None:
                raise CohortNotFound(cohort_id)
            # An archived name is free for reuse (`DATA.md#validation`), so the original may have
            # been claimed while this one was away.
            self._assert_name_free(conn, existing.name, exclude_id=cohort_id)
        return self._set_archived(cohort_id, None)

    def purge(self, cohort_id: str) -> None:
        """Remove a record without the archive-first guard (`DATA.md#archive-and-delete`).

        Rollback only: used when the cohort row was written but a subsequent
        step of the same operation failed. Never reachable from the wire.
        """
        with self._db.lock:
            self._db.conn.execute("DELETE FROM cohorts WHERE id = ?", (cohort_id,))
            self._db.conn.commit()

    def delete(self, cohort_id: str) -> None:
        """Permanent delete — the two-step guard (`DATA.md#archive-and-delete`).

        Removes only the app's own bookkeeping. The cohort's `dataFolder` on
        disk is never touched.
        """
        with self._db.lock:
            conn = self._db.conn
            existing = self._load_one(conn, cohort_id)
            if existing is None:
                raise CohortNotFound(cohort_id)
            if not existing.archived:
                raise NotArchived(cohort_id)
            conn.execute("DELETE FROM cohorts WHERE id = ?", (cohort_id,))
            conn.commit()

    # --- internals --------------------------------------------------------

    def _set_archived(self, cohort_id: str, value: str | None) -> Cohort:
        with self._db.lock:
            conn = self._db.conn
            if self._load_one(conn, cohort_id) is None:
                raise CohortNotFound(cohort_id)
            conn.execute(
                "UPDATE cohorts SET archived_at = ?, updated_at = ? WHERE id = ?",
                (value, _now(), cohort_id),
            )
            conn.commit()
            cohort = self._load_one(conn, cohort_id)
        assert cohort is not None
        return cohort

    @staticmethod
    def _assert_name_free(
        conn: sqlite3.Connection, name: str, exclude_id: str | None
    ) -> None:
        row = conn.execute(
            "SELECT id FROM cohorts"
            " WHERE name = ? COLLATE NOCASE AND archived_at IS NULL"
            " AND (? IS NULL OR id != ?)",
            (name, exclude_id, exclude_id),
        ).fetchone()
        if row is not None:
            raise NameTaken(name)

    @staticmethod
    def _load_all(conn: sqlite3.Connection) -> list[Cohort]:
        rows = conn.execute("SELECT * FROM cohorts ORDER BY created_at DESC").fetchall()
        return [CohortRepository._hydrate(conn, row) for row in rows]

    @staticmethod
    def _load_one(conn: sqlite3.Connection, cohort_id: str) -> Cohort | None:
        """One cohort, with its former members — which a listing never needs,
        and which cost a pass over the cohort's history to find."""
        row = conn.execute("SELECT * FROM cohorts WHERE id = ?", (cohort_id,)).fetchone()
        if row is None:
            return None
        cohort = CohortRepository._hydrate(conn, row)
        cohort.former_animals = former_members(conn, cohort.id, {a.id for a in cohort.animals})
        return cohort

    @staticmethod
    def _hydrate(conn: sqlite3.Connection, row: sqlite3.Row) -> Cohort:
        groups = [
            Group(id=g["id"], name=g["name"], order=g["order"])
            for g in conn.execute(
                'SELECT * FROM groups WHERE cohort_id = ? ORDER BY "order"', (row["id"],)
            )
        ]
        animals = [
            Animal(
                id=a["id"],
                name=a["name"],
                group_id=a["group_id"],
                box_number=a["box_number"],
                cage=a["cage"],
                sex=a["sex"],
                id_number=a["id_number"],
                notes=a["notes"],
            )
            for a in conn.execute(
                "SELECT * FROM animals WHERE cohort_id = ? ORDER BY name", (row["id"],)
            )
        ]
        return Cohort(
            id=row["id"],
            name=row["name"],
            data_folder=row["data_folder"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            archived_at=row["archived_at"],
            animals=animals,
            groups=groups,
            appearance=_parse_appearance_column(row["appearance_json"]),
        )


def _assert_ids_free(conn: sqlite3.Connection, animals: list[Animal], cohort_id: str) -> None:
    """Refuse a posted animal id that is another cohort's, active or former.

    Ids are global primary keys, so this used to surface as an integrity
    error — "couldn't save" with no reason. An animal belongs to one cohort;
    moving one is its own operation (`DATA.md#moving-animals-between-cohorts`)
    because its files and history move with it.
    """
    errors: dict[str, str] = {}
    for animal in animals:
        row = conn.execute(
            "SELECT c.name FROM animals a JOIN cohorts c ON c.id = a.cohort_id"
            " WHERE a.id = ? AND a.cohort_id != ?"
            " UNION ALL"
            " SELECT c.name FROM former_animals f JOIN cohorts c ON c.id = f.cohort_id"
            " WHERE f.id = ? AND f.cohort_id != ?",
            (animal.id, cohort_id, animal.id, cohort_id),
        ).fetchone()
        if row is not None:
            errors[f"animal:{animal.id}"] = (
                f"This animal belongs to “{row[0]}”. Move it from there instead."
            )
    if errors:
        raise ValidationError(errors)


def _keep_former(
    conn: sqlite3.Connection, cohort_id: str, existing: Cohort, posted: list[Animal]
) -> None:
    """Turn roster removals with history into former members, and posted
    former members back into roster animals (`DATA.md#former-members`).

    Runs inside `update`'s transaction, before the roster is rewritten.
    """
    posted_ids = {a.id for a in posted}
    history = referenced_animal_ids(conn, cohort_id)
    groups = {g.id: g.name for g in existing.groups}
    now = _now()
    for animal in existing.animals:
        if animal.id in posted_ids or animal.id not in history:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO former_animals"
            " (id, cohort_id, name, cage, sex, id_number, notes, group_name, removed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                animal.id,
                cohort_id,
                animal.name,
                animal.cage,
                animal.sex,
                animal.id_number,
                animal.notes,
                groups.get(animal.group_id),
                now,
            ),
        )
    for animal_id in posted_ids:
        conn.execute(
            "DELETE FROM former_animals WHERE id = ? AND cohort_id = ?", (animal_id, cohort_id)
        )


def _parse_appearance_column(raw: Any) -> Appearance | None:
    """The stored JSON, or None when there is none or it will not parse.

    A damaged appearance is treated as absent rather than raised on: the cohort
    is a roster of real animals and a folder of real recordings, and refusing to
    load it over a decorative field would be the wrong trade every time. The
    cohort simply comes back looking like the world its id derives.
    """
    if not raw:
        return None
    try:
        return Appearance.from_json(json.loads(raw))
    except (TypeError, ValueError):
        log.warning("a cohort's stored appearance will not parse; deriving instead")
        return None


def _parse_groups(raw: Any) -> list[Group]:
    if not isinstance(raw, list) or not raw:
        # A cohort always has at least one group (`DATA.md#data-model`).
        return [Group(id=_new_id(), name=DEFAULT_GROUP_NAME, order=0)]
    groups: list[Group] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip() or f"Group {index + 1}"
        order = item.get("order")
        groups.append(
            Group(
                id=str(item.get("id") or _new_id()),
                name=name,
                order=order if isinstance(order, int) else index,
            )
        )
    return groups or [Group(id=_new_id(), name=DEFAULT_GROUP_NAME, order=0)]


def _parse_animals(raw: Any) -> list[Animal]:
    if not isinstance(raw, list):
        return []
    animals: list[Animal] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        box = item.get("boxNumber")
        cage = item.get("cage")
        sex = item.get("sex")
        animals.append(
            Animal(
                id=str(item.get("id") or _new_id()),
                name=str(item.get("name") or "").strip(),
                group_id=str(item.get("groupId") or ""),
                box_number=box if isinstance(box, int) and not isinstance(box, bool) else None,
                cage=cage if isinstance(cage, int) and not isinstance(cage, bool) else None,
                sex=sex if sex in VALID_SEX else None,
                id_number=_opt_text(item.get("idNumber")),
                notes=_opt_text(item.get("notes")),
            )
        )
    return animals


def _opt_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _validate(animals: list[Animal], groups: list[Group]) -> None:
    """The validation rules (`DATA.md#validation`), reported per-field so the editor can show them inline."""
    errors: dict[str, str] = {}
    group_ids = {g.id for g in groups}

    seen_names: dict[str, str] = {}
    # box uniqueness is scoped to the *group*, not the cohort: groups run
    # consecutively, so the same physical slot is legitimately reused (`DATA.md#validation`).
    seen_boxes: dict[tuple[str, int], str] = {}

    for animal in animals:
        field = f"animal:{animal.id}"

        if not animal.name:
            errors[field] = "Every animal needs a name."
            continue

        key = animal.name.casefold()
        if key in seen_names:
            errors[field] = f"Another animal is already called “{animal.name}”."
        seen_names[key] = animal.id

        if animal.group_id not in group_ids:
            errors[field] = "This animal isn't in one of the cohort's groups."
            continue

        if animal.cage is not None and animal.cage < 1:
            errors[field] = "Cage numbers start at 1."
            continue

        if animal.box_number is not None:
            if not MIN_BOX <= animal.box_number <= MAX_BOX:
                errors[field] = f"Box must be between {MIN_BOX} and {MAX_BOX}."
                continue
            box_key = (animal.group_id, animal.box_number)
            if box_key in seen_boxes:
                errors[field] = (
                    f"Box {animal.box_number} is already taken in this group."
                )
            seen_boxes[box_key] = animal.id

    if errors:
        raise ValidationError(errors)

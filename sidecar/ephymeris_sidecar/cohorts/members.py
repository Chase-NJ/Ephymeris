"""Former members — animals with history in a cohort but no place on its roster
(`DATA.md#former-members`).

The roster is replaced wholesale on every edit, and the run, adoption and note
tables deliberately keep an `animal_id` with no foreign key, so history outlives
an animal's row. Every view names an animal through the roster, though, so an
animal taken off it used to come back as a bare id. This module answers "who
else has history here?" from the database alone.

Synchronous helpers on a connection the caller already holds the lock for.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

from .models import FormerAnimal


def referenced_animal_ids(conn: sqlite3.Connection, cohort_id: str) -> Counter[str]:
    """Every animal id this cohort's history names, with its run count.

    Runs are recorded plus adopted ones; an id named only by a note counts with
    zero runs, so it is still a key.
    """
    counts: Counter[str] = Counter()
    for (animal_id,) in conn.execute(
        "SELECT r.animal_id FROM session_animal_runs r"
        " JOIN sessions s ON s.id = r.session_id WHERE s.cohort_id = ?",
        (cohort_id,),
    ):
        counts[animal_id] += 1
    for (animal_id,) in conn.execute(
        "SELECT animal_id FROM adopted_runs WHERE cohort_id = ?", (cohort_id,)
    ):
        counts[animal_id] += 1
    for (animal_id,) in conn.execute(
        "SELECT DISTINCT animal_id FROM session_notes"
        " WHERE cohort_id = ? AND animal_id IS NOT NULL",
        (cohort_id,),
    ):
        counts.setdefault(animal_id, 0)
    return counts


def _paths_by_animal(conn: sqlite3.Connection, cohort_id: str) -> dict[str, list[str]]:
    paths: dict[str, list[str]] = {}
    for animal_id, file_path in conn.execute(
        "SELECT r.animal_id, r.file_path FROM session_animal_runs r"
        " JOIN sessions s ON s.id = r.session_id"
        " WHERE s.cohort_id = ? AND r.file_path IS NOT NULL",
        (cohort_id,),
    ):
        paths.setdefault(animal_id, []).append(file_path)
    for animal_id, file_path in conn.execute(
        "SELECT animal_id, file_path FROM adopted_runs WHERE cohort_id = ?", (cohort_id,)
    ):
        paths.setdefault(animal_id, []).append(file_path)
    return paths


def name_from_paths(paths: list[str]) -> str | None:
    """The animal a run's files name, by majority across its stored paths.

    No file is opened — the stem is the name, as written at recording
    (`DATA.md#names`) — so this works with the archive unplugged. A majority
    rather than the first hit, because one hand-renamed file should not
    rename the animal. Ties go to the earliest-sorted spelling, so the answer
    is the same on every read.
    """
    from ..analytics.reader import animal_token  # analytics imports cohorts

    votes: Counter[str] = Counter()
    for raw in paths:
        token = animal_token(Path(raw))
        if token:
            votes[token] += 1
    if not votes:
        return None
    best = max(votes.values())
    return min(name for name, count in votes.items() if count == best)


def former_members(
    conn: sqlite3.Connection, cohort_id: str, active_ids: set[str]
) -> list[FormerAnimal]:
    """Stored former members, then ids history names that nothing else does.

    The second kind is a removal from before former members were kept: its
    row is gone, so its name comes from its files and is never written back —
    a derivation, so it heals the moment the animal is restored or moved, and
    it costs nothing to the backup.
    """
    counts = referenced_animal_ids(conn, cohort_id)
    stored = [
        FormerAnimal(
            id=row["id"],
            name=row["name"],
            source="removed",
            removed_at=row["removed_at"],
            run_count=counts.get(row["id"], 0),
            sex=row["sex"],
            id_number=row["id_number"],
            cage=row["cage"],
            notes=row["notes"],
            group_name=row["group_name"],
        )
        for row in conn.execute(
            "SELECT * FROM former_animals WHERE cohort_id = ? ORDER BY name", (cohort_id,)
        )
    ]
    known = active_ids | {f.id for f in stored}
    unlisted_ids = [animal_id for animal_id in counts if animal_id not in known]
    if not unlisted_ids:
        return stored
    paths = _paths_by_animal(conn, cohort_id)
    unlisted = [
        FormerAnimal(
            id=animal_id,
            name=name_from_paths(paths.get(animal_id, [])),
            source="files",
            run_count=counts[animal_id],
        )
        for animal_id in unlisted_ids
    ]
    unlisted.sort(key=lambda f: ((f.name or "").casefold(), f.id))
    return stored + unlisted

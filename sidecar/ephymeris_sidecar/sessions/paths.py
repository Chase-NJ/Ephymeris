"""Session directory and file naming — `data-saving.md` §1–§2.

Pure string/path construction, no I/O, so the naming scheme is testable on its
own. The scheme itself does the collision-avoidance work: the per-animal
filename's `HHMMSS` suffix means same-day reruns never collide (§1), so there is
no "already exists" special case anywhere below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..cohorts.folders import sanitize_name

#: The three sibling format folders inside a session folder (§1).
TSV_DIR = "behavior.tsv"
JSON_DIR = "behavior.json"
MAT_DIR = "behavior.mat"


def date_stamp(when: datetime) -> str:
    """`MM_DD_YY` — matches the lab's existing convention exactly (§2)."""
    return when.strftime("%m_%d_%y")


def time_stamp(when: datetime) -> str:
    """`HHMMSS`, 24-hour (§2)."""
    return when.strftime("%H%M%S")


def session_folder_name(prefix: str, session_number: str, when: datetime) -> str:
    """`<prefix>_<sessionNumber>_<MM>_<DD>_<YY>` (§2)."""
    return f"{sanitize_name(prefix)}_{sanitize_name(session_number)}_{date_stamp(when)}"


def resolve_session_folder(
    cohort_data_folder: str, prefix: str, session_number: str, when: datetime
) -> Path:
    """`<cohort.dataFolder>/<prefix>/<prefix>_<num>_<date>/` (§1).

    The cohort's own `dataFolder` already resolves to
    `<Settings.dataDirectory>/<cohort name>` (`cohorts.md` §8), so this only
    appends the prefix and session-folder segments.
    """
    return (
        Path(cohort_data_folder)
        / sanitize_name(prefix)
        / session_folder_name(prefix, session_number, when)
    )


@dataclass(frozen=True)
class AnimalFilePaths:
    """The three format paths for one animal's run, sharing a basename."""

    tsv: Path
    json: Path
    mat: Path

    @property
    def basename(self) -> str:
        return self.tsv.stem


def resolve_animal_files(
    session_folder: Path,
    animal_name: str,
    prefix: str,
    session_number: str,
    when: datetime,
) -> AnimalFilePaths:
    """`<animal>_<prefix>_<num>_<MM>_<DD>_<YY>_<HHMMSS>.<ext>` (§2).

    Timestamped at the moment the animal's run actually starts, not at
    session-config time, so animals starting minutes apart get honest,
    distinct timestamps.
    """
    stem = (
        f"{sanitize_name(animal_name)}_{sanitize_name(prefix)}_"
        f"{sanitize_name(session_number)}_{date_stamp(when)}_{time_stamp(when)}"
    )
    return AnimalFilePaths(
        tsv=session_folder / TSV_DIR / f"{stem}.tsv",
        json=session_folder / JSON_DIR / f"{stem}.json",
        mat=session_folder / MAT_DIR / f"{stem}.mat",
    )

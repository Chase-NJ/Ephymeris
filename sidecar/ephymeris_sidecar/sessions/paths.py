"""Session directory and file naming — `data-saving.md` §1–§2.

Pure string/path construction, no I/O, so the naming scheme is testable on its
own. The scheme itself does the collision-avoidance work: the per-animal
filename's `HHMMSS` suffix means same-day reruns never collide (§1) — though
the writer no longer *relies* on that, opening its `.tsv` exclusively so an
unreachable collision fails loudly instead of overwriting (§7.1).

**Dates are ISO `YYYY-MM-DD`.** This replaced the lab's original `MM_DD_YY`,
which sorted wrongly across a year boundary (`12_31_26` before `01_01_27`).
Hyphenated rather than underscored on purpose: `MM_DD_YY` and `YYYY_MM_DD`
split into the same number of `_`-separated tokens, so an analysis script
parsing positionally would have kept working and silently read the date wrong.
One hyphenated token changes the token count, so such a script breaks loudly.

Folders and files already written under the old format are left exactly where
they are — nothing in this project renames a user's data. `parse_name_date`
below therefore reads **both** spellings, so anything that later walks the
archive (Analytics, the crash-recovery backfill) sees the whole history rather
than only what was written after this change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ..cohorts.folders import sanitize_name

#: The three sibling format folders inside a session folder (§1).
TSV_DIR = "behavior.tsv"
JSON_DIR = "behavior.json"
MAT_DIR = "behavior.mat"

#: Current naming (§2). Sorts chronologically as a plain string, which is what
#: `MM_DD_YY` could not do.
DATE_FORMAT = "%Y-%m-%d"
#: The pre-ISO format. Read-only — never written, only parsed out of folders
#: and files that already exist on disk.
LEGACY_DATE_FORMAT = "%m_%d_%y"

# Anchored at the end of the name, with an optional `_HHMMSS` for per-animal
# files. Anchoring is what disambiguates the legacy form: in
# `2O-Bdisc_25_07_22_26`, an unanchored search for `NN_NN_NN` would happily
# match `25_07_22` — the session number followed by two thirds of the date.
_ISO_TAIL = re.compile(r"_(\d{4}-\d{2}-\d{2})(?:_(\d{6}))?$")
_LEGACY_TAIL = re.compile(r"_(\d{2}_\d{2}_\d{2})(?:_(\d{6}))?$")


def date_stamp(when: datetime) -> str:
    """`YYYY-MM-DD` (§2)."""
    return when.strftime(DATE_FORMAT)


def time_stamp(when: datetime) -> str:
    """`HHMMSS`, 24-hour (§2)."""
    return when.strftime("%H%M%S")


def parse_date_stamp(stamp: str) -> date | None:
    """Read a bare date stamp in either the current or the legacy spelling."""
    for fmt in (DATE_FORMAT, LEGACY_DATE_FORMAT):
        try:
            return datetime.strptime(stamp, fmt).date()
        except ValueError:
            continue
    return None


def parse_name_date(name: str) -> date | None:
    """Pull the date out of a session folder name or a per-animal file stem.

    Accepts both the current `YYYY-MM-DD` and the legacy `MM_DD_YY`, so a
    caller walking a prefix folder that spans the change sees one history
    rather than two. Returns `None` for a name that carries no date.

    **Use this instead of sorting names as strings.** The legacy format doesn't
    order correctly across a year boundary, and both formats coexist on disk
    indefinitely — so lexical ordering over a real archive is wrong twice over.
    """
    stem = Path(name).stem if Path(name).suffix else name
    for pattern in (_ISO_TAIL, _LEGACY_TAIL):
        match = pattern.search(stem)
        if match is not None:
            parsed = parse_date_stamp(match.group(1))
            if parsed is not None:
                return parsed
    return None


@dataclass(frozen=True)
class ParsedSessionFolder:
    """What a session folder's *name* alone can tell you (§2).

    The archive walk is the only consumer — everything the app recorded itself
    is answered by the database, which also knows things a name cannot carry
    (animal ids, boxes, stop reasons).
    """

    prefix: str
    session_number: str
    date: date | None


def parse_session_folder(name: str) -> ParsedSessionFolder:
    """Split `<prefix>_<number>_<date>` back into its parts, either date spelling.

    Degrades honestly rather than guessing: a name with no recognizable date
    tail comes back whole as the prefix with an empty session number, because
    inventing a split would attribute data to a session that never existed.
    """
    for pattern in (_ISO_TAIL, _LEGACY_TAIL):
        match = pattern.search(name)
        if match is None:
            continue
        parsed = parse_date_stamp(match.group(1))
        if parsed is None:
            continue
        head = name[: match.start()]
        if "_" in head:
            prefix, number = head.rsplit("_", 1)
        else:
            prefix, number = head, ""
        return ParsedSessionFolder(prefix=prefix, session_number=number, date=parsed)
    return ParsedSessionFolder(prefix=name, session_number="", date=None)


def parse_name_time(name: str) -> str | None:
    """The `HHMMSS` tail of a per-animal file stem, as `HH:MM:SS` — or None.

    Session folders don't carry one; per-animal files do (§2). Same
    anchored-tail discipline as `parse_name_date`.
    """
    stem = Path(name).stem if Path(name).suffix else name
    for pattern in (_ISO_TAIL, _LEGACY_TAIL):
        match = pattern.search(stem)
        if match is not None and match.group(2) is not None:
            raw = match.group(2)
            try:
                datetime.strptime(raw, "%H%M%S")
            except ValueError:
                return None
            return f"{raw[0:2]}:{raw[2:4]}:{raw[4:6]}"
    return None


def session_folder_name(prefix: str, session_number: str, when: datetime) -> str:
    """`<prefix>_<sessionNumber>_<YYYY-MM-DD>` (§2)."""
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
    """`<animal>_<prefix>_<num>_<YYYY-MM-DD>_<HHMMSS>.<ext>` (§2).

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

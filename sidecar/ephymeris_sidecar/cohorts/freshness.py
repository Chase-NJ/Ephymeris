"""Carrying a file's freshness key across a transfer — `DATA.md#caching`.

Three tables remember the (mtime, size) of the file each row was read from,
so the next read can tell from a `stat` alone whether the file changed:
`run_metrics_cache`, `adopted_runs` and `strobe_scan_cache`. A relocate or a
move of animals puts a verified copy of the same content at a new path, and
the copy's stat need not be the original's: a volume that keeps mtimes
coarser than NTFS rounds them on the way in (exFAT to 10 ms, FAT32 to 1 s).
A row left with the original's key then misses — and for an adopted run a
miss is not only a re-read: the rescan matches it to an animal by name again,
which a rename since adoption breaks (`DATA.md#orphan-adoption`).

So each row moves to the copy's stat — but only a row that was fresh for the
original. One already stale stays stale, or the copy would vouch for a
summary of content the file no longer has.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable

#: (mtime_ns, size), as the keyed tables store it.
Stat = tuple[int, int]

#: Every table keyed on a file's (path, mtime, size).
KEYED_TABLES = ("run_metrics_cache", "adopted_runs", "strobe_scan_cache")


def stat_of(path: str | Path | None) -> Stat | None:
    if path is None:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def carry(conn: sqlite3.Connection, moved: Iterable[tuple[str, Stat | None]]) -> None:
    """Re-key the rows for each transferred file.

    `moved` pairs each file's path, spelled as the records now store it, with
    the original's stat from before the transfer — None when there was no
    original to compare with, which leaves the rows for the next read to
    decide. Never commits.
    """
    for path, before in moved:
        if before is None:
            continue
        after = stat_of(path)
        if after is None or after == before:
            continue
        for table in KEYED_TABLES:
            conn.execute(
                f"UPDATE {table} SET file_mtime_ns = ?, file_size = ?"
                " WHERE file_path = ? AND file_mtime_ns = ? AND file_size = ?",
                (*after, path, *before),
            )

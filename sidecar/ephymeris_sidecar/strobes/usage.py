"""Where a code is used: firmware that names it, sessions that contain it.

The evidence `store.py`'s rules are judged against, gathered here so those
rules stay pure. Two very different costs:

* **Firmware references** are a regex over a few dozen source files, cheap
  enough to answer on every row the Strobes page selects.
* **The archive scan** reads every recorded session this machine can reach.
  It is the check that decides whether a code may ever be deleted, so it is
  complete rather than sampled — every `.json`, plus every `.tsv` with no
  `.json` beside it (a crashed or still-running session is a recorded session
  too). A per-file cache keyed on (path, mtime, size) makes every scan after
  the first a few thousand `stat`s.

THE SCAN CAN ONLY SEE THIS MACHINE. Another rig's archive, a drive that is not
mounted, a cohort folder deleted from the app but not from disk: none of those
is checked, and the reply says what WAS, so the operator's confirm is made
against the scan's real coverage rather than an implied "nowhere".
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..analytics import reader
from ..analytics.derive import codes_of
from ..cohorts.db import Database
from ..sessions.recovery import STROBE, LEGACY_HEADER, LEGACY_STROBE

log = logging.getLogger(__name__)

#: Source files a sketch or library is written in.
_SOURCE_SUFFIXES = frozenset({".ino", ".h", ".hpp", ".c", ".cpp"})

#: Generated from the vocabulary itself, so naming every code is what it is
#: FOR — counting it would make every code "used" by every sketch.
_GENERATED_DEFINITIONS = frozenset({"TaskPins.h"})

_BF_TOKEN = re.compile(r"\bBF_([A-Z][A-Z0-9_]*)\b")

#: How many containing files a refusal lists. Enough to go and look; the count
#: is what carries the weight.
SAMPLE_SIZE = 5

#: Files between progress reports.
PROGRESS_EVERY = 64

#: Bumped whenever how a file is READ changes, so a row cached by an older
#: reader is re-read rather than trusted. Stored inside `codes_json` — a row
#: without it (a bare list) is from before versioning and is always re-read.
#: 2: legacy three-column `.tsv` lines (`code\tms\tname`) are read; v1 saw none.
READER_VERSION = 2



# --------------------------------------------------------------------------- #
# Firmware
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FirmwareRef:
    """One source file that names `BF_<code>`."""

    path: str
    #: `library` (a shared library every sketch includes — retiring a code it
    #: names stops EVERY sketch compiling), `sketch` (a bundled sketch), or
    #: `task` (a folder generated from a saved task).
    kind: str

    def to_json(self) -> dict[str, str]:
        return {"path": self.path, "kind": self.kind}


def firmware_refs(roots: Iterable[tuple[Path | None, str]]) -> dict[str, list[FirmwareRef]]:
    """`name -> files naming BF_<name>`, over every source file under `roots`.

    `roots` pairs a directory with the kind its sketches are; anything under a
    `libraries/` folder is a `library` reference whatever root it was found
    under. Dotted folders (`.retired/`) and `extras/` are skipped: neither is
    compiled into a sketch — `extras/` is where a library keeps its host tests,
    whose fixture names every code on purpose.
    """
    out: dict[str, list[FirmwareRef]] = {}
    for root, kind in roots:
        if root is None or not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                d for d in dirnames if not d.startswith(".") and d.lower() != "extras"
            )
            here = Path(dirpath)
            rel_parts = here.relative_to(root).parts
            here_kind = "library" if any(p.lower() == "libraries" for p in rel_parts) else kind
            for name in sorted(filenames):
                path = here / name
                if path.suffix.lower() not in _SOURCE_SUFFIXES or name in _GENERATED_DEFINITIONS:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:  # pragma: no cover - unreadable install
                    log.warning("couldn't read %s for strobe references: %s", path, exc)
                    continue
                rel = str(path.relative_to(root))
                for code_name in sorted(set(_BF_TOKEN.findall(_strip_comments(text)))):
                    out.setdefault(code_name, []).append(FirmwareRef(rel, here_kind))
    return out


def _strip_comments(source: str) -> str:
    """C source without its comments, so a `BF_X` in prose is not a use.

    BehaviorBox.h explains its non-emitters in comments that name the codes;
    counting those would make the explanation a reference.
    """
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", " ", source)


def _key(path: Path) -> str:
    """One spelling per file, so a run the walk found and the database lists
    is counted once. Lexical only: resolving symlinks would touch a share."""
    return os.path.normcase(os.path.abspath(path))


# --------------------------------------------------------------------------- #
# The archive
# --------------------------------------------------------------------------- #


@dataclass
class ArchiveIndex:
    """Which recorded files contain which codes, as of one scan."""

    #: code -> files containing it, in scan order.
    containing: dict[int, list[str]] = field(default_factory=dict)
    files: int = 0
    unreadable: int = 0
    roots: list[str] = field(default_factory=list)
    unreachable_roots: list[str] = field(default_factory=list)

    def count(self, code: int) -> int:
        return len(self.containing.get(code, ()))

    def usage_of(self, code: int) -> dict[str, Any]:
        paths = self.containing.get(code, [])
        return {
            "count": len(paths),
            "sample": paths[:SAMPLE_SIZE],
            "scanned": self.coverage(),
        }

    def coverage(self) -> dict[str, Any]:
        return {
            "files": self.files,
            "unreadable": self.unreadable,
            "roots": list(self.roots),
            "unreachableRoots": list(self.unreachable_roots),
        }


class ArchiveScanner:
    """Every recorded session this machine can reach, reduced to code sets.

    One scan at a time: a second caller waits for the first rather than
    reading the same archive twice in parallel, which on a network share is
    the difference between slow and unusable (`DATA.md#reading-the-archive`).
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._lock = threading.Lock()

    def scan(
        self,
        roots: Iterable[str],
        progress: Callable[[int, int], None] | None = None,
    ) -> ArchiveIndex:
        with self._lock:
            return self._scan(list(roots), progress)

    def _scan(self, roots: list[str], progress: Callable[[int, int], None] | None) -> ArchiveIndex:
        index = ArchiveIndex()
        files: dict[str, Path] = {}
        for root in dict.fromkeys(roots):
            if not root:
                continue
            base = Path(root).expanduser()
            index.roots.append(str(base))
            try:
                reachable = base.is_dir()
            except OSError:
                reachable = False
            if not reachable:
                index.unreachable_roots.append(str(base))
                continue
            for path in reader.walk_session_files(base):
                files.setdefault(_key(path), path)
            for path in reader.walk_orphaned_tsvs(base):
                files.setdefault(_key(path), path)
        # Runs the database knows about, wherever they live — an adopted file
        # outside every cohort folder is still a recorded session.
        for path in self._recorded_paths():
            files.setdefault(_key(path), path)

        cached = self._cached()
        fresh: list[tuple[str, int, int, str]] = []
        ordered = sorted(files.values())
        total = len(ordered)
        for done, path in enumerate(ordered, start=1):
            codes = self._codes_of(path, cached, fresh, index)
            if codes is not None:
                index.files += 1
                for code in codes:
                    index.containing.setdefault(code, []).append(str(path))
            if progress is not None and (done % PROGRESS_EVERY == 0 or done == total):
                progress(done, total)
        self._store(fresh)
        return index

    def _codes_of(
        self,
        path: Path,
        cached: dict[str, tuple[int, int, str]],
        fresh: list[tuple[str, int, int, str]],
        index: ArchiveIndex,
    ) -> list[int] | None:
        try:
            stat = path.stat()
        except OSError:
            # Listed by the database, gone from disk: not a file that exists,
            # so not one that can hold a code.
            return None
        key = str(path)
        hit = cached.get(key)
        if hit is not None and hit[0] == stat.st_mtime_ns and hit[1] == stat.st_size:
            stored = json.loads(hit[2])
            if isinstance(stored, dict) and stored.get("v") == READER_VERSION:
                return stored["codes"]
        try:
            if path.suffix == ".tsv":
                codes = _tsv_codes(path)
            else:
                result = reader.read_run(path)
                if not result.ok or result.document is None:
                    raise OSError(result.detail or result.status)
                codes = sorted(set(codes_of(result.document)))
        except (OSError, ValueError) as exc:
            # Counted, never guessed at: the reply says how many files could
            # not be read, so "no session contains it" is never claimed over
            # a file nobody looked inside.
            log.warning("strobe scan couldn't read %s: %s", path, exc)
            index.unreadable += 1
            return None
        fresh.append((
            key, stat.st_mtime_ns, stat.st_size,
            json.dumps({"v": READER_VERSION, "codes": codes}),
        ))
        return codes

    def _recorded_paths(self) -> list[Path]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT file_path FROM session_animal_runs WHERE file_path IS NOT NULL"
                " UNION SELECT file_path FROM adopted_runs"
            ).fetchall()
        out: list[Path] = []
        for row in rows:
            path = Path(row["file_path"])
            out.append(path)
            # A run whose `.json` was never written still has its write-ahead
            # log, and the log is the record.
            if path.suffix == ".json":
                out.append(reader.sibling_tsv(path))
        return [p for p in out if p.suffix == ".json" or not reader.sibling_json(p).is_file()]

    def _cached(self) -> dict[str, tuple[int, int, str]]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT file_path, file_mtime_ns, file_size, codes_json FROM strobe_scan_cache"
            ).fetchall()
        return {
            r["file_path"]: (r["file_mtime_ns"], r["file_size"], r["codes_json"]) for r in rows
        }

    def _store(self, fresh: list[tuple[str, int, int, str]]) -> None:
        if not fresh:
            return
        with self._db.lock:
            self._db.conn.executemany(
                "INSERT OR REPLACE INTO strobe_scan_cache"
                " (file_path, file_mtime_ns, file_size, codes_json) VALUES (?, ?, ?, ?)",
                fresh,
            )
            self._db.conn.commit()


def _tsv_codes(path: Path) -> list[int]:
    """The distinct codes in a `.tsv`, in either dialect.

    The same line rules as `sessions/recovery.parse_tsv` — its regexes, both
    dialects — but the opposite tolerance. Recovery skips a line it does not
    recognise; here that would report a file full of strobes as containing
    none, the one answer this scan must never give wrongly. So a line that is
    neither a strobe, a `#` comment, the legacy header nor blank makes the
    whole file UNREADABLE (counted, never guessed at), except a torn final
    line, which is the one a power cut leaves behind (`DATA.md#crash-safety`).
    """
    codes: set[int] = set()
    unknown: list[int] = []
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        lines = fh.read().replace("\r\n", "\n").replace("\r", "\n").split("\n")
    legacy = bool(lines) and LEGACY_HEADER.match(lines[0].strip()) is not None
    strobe = LEGACY_STROBE if legacy else STROBE
    for number, line in enumerate(lines):
        line = line.strip()
        if not line or line.startswith("#") or (legacy and number == 0):
            continue
        match = strobe.match(line)
        if match:
            codes.add(int(match.group(1)))
        else:
            unknown.append(number)
    last = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
    if any(i != last for i in unknown):
        raise ValueError(f"{len(unknown)} line(s) are neither strobes nor comments")
    return sorted(codes)


"""Reading finalized session files back off disk — `DATA.md#reading-the-archive`.

The sidecar has never done this before: `writer.finalize` returns its document
in memory precisely so callers *don't* re-read it. Analytics is the first
reader, so error classification lives here rather than being invented per
caller.

**A bad file is data, not an error.** Every failure below becomes a status and
a message on the run, never a raised exception — one unreadable `.json` must
not blank a year of history (`DATA.md#caching`).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Sibling format folders, so a missing `.json` can be checked against the
#: write-ahead log that may still hold the data (`DATA.md#layout`).
TSV_DIR = "behavior.tsv"
JSON_DIR = "behavior.json"

#: The lab's pre-Ephymeris software named the format folders with underscores
#: (`behavior_json`, `recovery_tsv`). Real archives carry years of data under
#: those names and nothing in this project renames a user's files, so the walk
#: and the sibling checks read both spellings — write paths never do.
LEGACY_JSON_DIR = "behavior_json"
LEGACY_TSV_DIR = "recovery_tsv"

#: The `.mat` folder names, current and legacy, for the same reason.
MAT_DIR = "behavior.mat"
LEGACY_MAT_DIR = "behavior_mat"

#: Every folder name that marks "this directory holds one format of a session's
#: per-animal files" — the walk treats their *parent* as the session folder.
FORMAT_DIRS = frozenset(
    {TSV_DIR, JSON_DIR, MAT_DIR, LEGACY_JSON_DIR, LEGACY_TSV_DIR, LEGACY_MAT_DIR}
)

#: How far below the cohort folder the walk will look for a format folder.
#: A cohort's `dataFolder` is user-settable and could be pointed at a drive
#: root, so the descent needs a floor; real layouts use two or three levels.
MAX_FORMAT_DEPTH = 6

#: Directories the walk never descends into, on top of every dotted name.
#: `__MACOSX` is where macOS unpacks the AppleDouble sidecars `is_sidecar_file`
#: filters per-file — same junk, one level up.
PRUNED_DIRS = frozenset({"__MACOSX"})


@dataclass(frozen=True)
class ReadResult:
    """A parsed document, or why there isn't one."""

    status: str  # 'ok' | 'missing' | 'unreadable'
    document: dict[str, Any] | None = None
    detail: str | None = None
    mtime_ns: int | None = None
    size: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class StatResult:
    """What one `stat` says about a run file — everything the cache key needs.

    Split out from `ReadResult` because the cache key is answerable without
    opening the file, and the indexing path asks that question about every run
    on every dashboard open (`DATA.md#caching`).
    """

    status: str  # 'ok' | 'missing' | 'unreadable'
    mtime_ns: int | None = None
    size: int | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def sibling_tsv(json_path: Path) -> Path:
    """The `.tsv` beside a `.json` — same stem, sibling format folder.

    A legacy-layout `.json` (inside `behavior_json/`) gets the legacy sibling
    (`recovery_tsv/`); everything else gets the current name.
    """
    if json_path.parent.name == LEGACY_JSON_DIR:
        return json_path.parent.parent / LEGACY_TSV_DIR / f"{json_path.stem}.tsv"
    return json_path.parent.parent / TSV_DIR / f"{json_path.stem}.tsv"


def sibling_json(tsv_path: Path) -> Path:
    """`sibling_tsv` in reverse — where a `.tsv`'s structured copy belongs.

    Layout-preserving on purpose: a legacy-layout `.tsv` (inside
    `recovery_tsv/`) gets `behavior_json/`, so the crash-recovery backfill
    writes into the folder the archive's other files already live in rather
    than minting a current-spelling folder beside it.
    """
    if tsv_path.parent.name == LEGACY_TSV_DIR:
        return tsv_path.parent.parent / LEGACY_JSON_DIR / f"{tsv_path.stem}.json"
    return tsv_path.parent.parent / JSON_DIR / f"{tsv_path.stem}.json"


def sibling_mat(tsv_path: Path) -> Path:
    """The `.mat` slot beside a `.tsv`, same layout-preserving rule."""
    if tsv_path.parent.name == LEGACY_TSV_DIR:
        return tsv_path.parent.parent / LEGACY_MAT_DIR / f"{tsv_path.stem}.mat"
    return tsv_path.parent.parent / MAT_DIR / f"{tsv_path.stem}.mat"


def is_sidecar_file(path: Path) -> bool:
    """AppleDouble junk (`._name.json`), not data.

    macOS writes one of these beside every real file when copying to a
    filesystem that can't hold its metadata — a USB stick, a network share.
    They carry a resource fork, not JSON, so reading one yields a
    `UnicodeDecodeError` and an "unreadable" run that never existed. The real
    Remy archive carries 454 of them against 586 real files: left in, they
    would be the *majority* of what the walk reported.
    """
    return path.name.startswith("._")


def run_identity(path: Path) -> str:
    """What makes two files the same run, regardless of where they sit.

    The per-animal filename (`DATA.md#names`) is
    `<animal>_<prefix>_<number>_<date>_<HHMMSS>` — animal plus session plus
    start time. That is precisely a run's identity, which is what makes the
    stem usable as one. Two copies of a run in different folders are one run;
    two genuinely different runs cannot share a stem, because the `HHMMSS` is
    what stops same-day reruns from colliding in the first place.
    """
    return path.stem.casefold()


def session_folder_of(file_path: Path) -> Path:
    """The session folder a per-animal file belongs to.

    Defined relative to the *format folder*, never to the cohort root — which
    is precisely why `walk_session_files` can find format folders at any depth
    without this needing to know how deep it went.

    The second branch is defensive, not a supported layout: `walk_session_files`
    only ever yields files from inside a format folder, so it cannot produce a
    path that takes it. It exists for a `file_path` read back out of the
    database, where returning the parent beats raising. **Don't "fix" the walk
    to match it** — scoping discovery to format folders is the only thing
    keeping every stray `.json` on a shared drive out of the archive.
    """
    parent = file_path.parent
    return parent.parent if parent.name in FORMAT_DIRS else parent


def stat_run(path: str | Path) -> StatResult:
    """Is the file there, and has it changed? — without opening it.

    Two of `read_run`'s three outcomes are decided here:

    * **missing** — nothing at that path. When the sibling `.tsv` *is* there,
      say so: that is the disk-full-at-finalization case
      (`DATA.md#built-once-at-the-end`: the writer writes `.json` best-effort
      and only logs an `OSError`), the data is
      not lost, and the crash-recovery utility is what fixes it.
    * **unreadable** — the path itself can't be interrogated.
    * **ok** — with the stat the cache key is built from.
    """
    target = Path(path)
    try:
        stat = target.stat()
    except FileNotFoundError:
        detail = "the file is not on disk"
        try:
            if sibling_tsv(target).is_file():
                detail = (
                    "the .tsv is on disk but the .json was never written — "
                    "the data is recoverable"
                )
        except OSError:  # pragma: no cover - unreadable mount
            pass
        return StatResult(status="missing", detail=detail)
    except OSError as exc:
        return StatResult(status="unreadable", detail=str(exc))

    return StatResult(status="ok", mtime_ns=stat.st_mtime_ns, size=stat.st_size)


def parse_run(path: str | Path, stat: StatResult) -> ReadResult:
    """Open and parse a file `stat_run` has already said is there.

    **unreadable** covers present-but-not-parseable, and is cached as a
    negative result so a corrupt file isn't re-parsed on every dashboard open.
    """
    target = Path(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return ReadResult(
            status="unreadable", detail=f"couldn't read {target.name}: {exc}"
        )

    if not isinstance(raw, dict):
        return ReadResult(
            status="unreadable", detail=f"{target.name} is not a JSON object"
        )

    return ReadResult(
        status="ok",
        document=raw,
        mtime_ns=stat.mtime_ns,
        size=stat.size,
    )


def read_run(path: str | Path) -> ReadResult:
    """Load one per-animal session document — stat and parse in one call.

    Three outcomes, deliberately distinguished because they mean different
    things to the operator: **missing**, **unreadable**, and **ok** with the
    stat used for cache invalidation.

    Callers that need the document unconditionally (the rescan, `series`) want
    this. The indexing path deliberately does *not*: it calls `stat_run`,
    settles the cache key, and only reaches `parse_run` on a miss.
    """
    stat = stat_run(path)
    if stat.status != "ok":
        return ReadResult(status=stat.status, detail=stat.detail)
    return parse_run(path, stat)


def walk_session_files(cohort_folder: str | Path) -> list[Path]:
    """Every per-animal `.json` under one cohort's data folder
    (`DATA.md#database-first`).

    Only used by the explicit rescan — the normal path reads what run records
    point at. Two rules do all the work here, and both are stated positively so
    that neither needs a list of exceptions to grow over time:

    **A format folder is recognized by its name, at any depth.** This app files
    sessions under a prefix folder (`<cohort>/<prefix>/<session>/`), but other
    software in this lab put them straight under the cohort root, and nothing
    stops someone adding a per-year level next. Matching on the name instead of
    on a fixed depth reads every one of those from a single pass, which is why
    the depth never has to be known in advance.

    **A format folder's data is exactly its direct children.** The walk stops
    at one, so a plots or notes folder *inside* it (real archives carry
    `behavior_json/analytics/`) contributes nothing, and neither do the
    per-session report folders sitting beside it. Scoping to format folders at
    all is what keeps an unrelated file someone dropped in the cohort folder
    from being mistaken for a session.

    A directory that can't be read costs a warning and its own contents, never
    the cohort: **a bad directory is data too**, the same call
    `DATA.md#caching` makes for a
    bad file. That is why this returns a list and not an error.
    """
    found: list[Path] = []
    for here, filenames in _walk_format_dirs(cohort_folder):
        if here.name in (JSON_DIR, LEGACY_JSON_DIR):
            found.extend(
                here / name
                for name in filenames
                if name.endswith(".json") and not is_sidecar_file(here / name)
            )
    return sorted(found)


def walk_orphaned_tsvs(cohort_folder: str | Path) -> list[Path]:
    """Every `.tsv` under one cohort's data folder with no `.json` sibling.

    The crash-recovery backfill's discovery pass (`DATA.md#crash-recovery`)
    — the same traversal as `walk_session_files`, looking at the *other*
    format folders. A `.tsv` whose structured copy never got written is
    precisely a run that ended in a crash (no finalization at all) or in a
    failed best-effort `.json` write (`DATA.md#built-once-at-the-end`) — either
    way, the write-ahead log
    is the surviving authority and the file is worth offering for recovery.

    A sibling that can't even be `stat`ed is treated as present: recovery
    writes files, and "I couldn't check" must fail toward writing nothing.
    """
    orphans: list[Path] = []
    for here, filenames in _walk_format_dirs(cohort_folder):
        if here.name not in (TSV_DIR, LEGACY_TSV_DIR):
            continue
        for name in filenames:
            path = here / name
            if not name.endswith(".tsv") or is_sidecar_file(path):
                continue
            try:
                if not sibling_json(path).is_file():
                    orphans.append(path)
            except OSError as exc:  # pragma: no cover - unreadable mount
                log.warning("couldn't check %s's sibling: %s", path, exc)
    return sorted(orphans)


def walk_session_dirs(cohort_folder: str | Path) -> list[Path]:
    """Every distinct session folder under one cohort's data folder.

    A session folder is defined the same way `session_folder_of` defines it —
    the *parent* of a format folder — so this is the archive walk's traversal reporting
    directories instead of files. Names only, nothing opened: what
    `analytics.recentSessions` needs, and all it is allowed to cost, since it
    runs from the Dashboard where the rescan deliberately does not.
    """
    seen: set[str] = set()
    dirs: list[Path] = []
    for here, _filenames in _walk_format_dirs(cohort_folder):
        parent = here.parent
        key = str(parent)
        if key not in seen:
            seen.add(key)
            dirs.append(parent)
    return sorted(dirs)


def _walk_format_dirs(cohort_folder: str | Path):
    """Yield every format folder under a cohort folder as `(path, filenames)`.

    The one traversal both walks share — orphan adoption
    (`DATA.md#orphan-adoption`) and the crash-recovery backfill
    (`DATA.md#crash-recovery`). Format folders are matched **by
    name at any depth**, pruned at the format folder, dotted/`__MACOSX` folders
    skipped, depth floored at `MAX_FORMAT_DEPTH`. A directory that can't be read
    costs a warning and its own contents, never the cohort.
    """
    base = Path(cohort_folder).expanduser()
    try:
        if not base.is_dir():
            return
    except OSError as exc:  # pragma: no cover - unreadable mount
        log.warning("couldn't reach %s: %s", base, exc)
        return

    def note(exc: OSError) -> None:
        log.warning("skipping %s: %s", getattr(exc, "filename", base), exc)

    for dirpath, dirnames, filenames in os.walk(base, onerror=note, followlinks=False):
        here = Path(dirpath)

        if here.name in FORMAT_DIRS:
            dirnames[:] = []
            yield here, filenames
            continue

        if len(here.relative_to(base).parts) >= MAX_FORMAT_DEPTH:
            dirnames[:] = []
            continue

        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d not in PRUNED_DIRS
        )

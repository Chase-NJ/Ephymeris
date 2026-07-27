"""Reading finalized session files back off disk — `analytics.md` §8.

The sidecar has never done this before: `writer.finalize` returns its document
in memory precisely so callers *don't* re-read it. Analytics is the first
reader, so error classification lives here rather than being invented per
caller.

**A bad file is data, not an error.** Every failure below becomes a status and
a message on the run, never a raised exception — one unreadable `.json` must
not blank a year of history (§9).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Sibling format folders, so a missing `.json` can be checked against the
#: write-ahead log that may still hold the data (`data-saving.md` §1).
TSV_DIR = "behavior.tsv"
JSON_DIR = "behavior.json"

#: The lab's pre-Ephymeris software named the format folders with underscores
#: (`behavior_json`, `recovery_tsv`). Real archives carry years of data under
#: those names and nothing in this project renames a user's files, so the walk
#: and the sibling checks read both spellings — write paths never do.
LEGACY_JSON_DIR = "behavior_json"
LEGACY_TSV_DIR = "recovery_tsv"

#: Every folder name that marks "this directory holds one format of a session's
#: per-animal files" — the walk treats their *parent* as the session folder.
FORMAT_DIRS = frozenset(
    {TSV_DIR, JSON_DIR, "behavior.mat", LEGACY_JSON_DIR, LEGACY_TSV_DIR, "behavior_mat"}
)


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


def sibling_tsv(json_path: Path) -> Path:
    """The `.tsv` beside a `.json` — same stem, sibling format folder.

    A legacy-layout `.json` (inside `behavior_json/`) gets the legacy sibling
    (`recovery_tsv/`); everything else gets the current name.
    """
    if json_path.parent.name == LEGACY_JSON_DIR:
        return json_path.parent.parent / LEGACY_TSV_DIR / f"{json_path.stem}.tsv"
    return json_path.parent.parent / TSV_DIR / f"{json_path.stem}.tsv"


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

    The per-animal filename (`data-saving.md` §2) is
    `<animal>_<prefix>_<number>_<date>_<HHMMSS>` — animal plus session plus
    start time. That is precisely a run's identity, which is what makes the
    stem usable as one. Two copies of a run in different folders are one run;
    two genuinely different runs cannot share a stem, because the `HHMMSS` is
    what stops same-day reruns from colliding in the first place.
    """
    return path.stem.casefold()


def session_folder_of(file_path: Path) -> Path:
    """The session folder a per-animal file belongs to.

    Files normally sit inside a format folder (`behavior.json/`,
    `behavior_json/`, …) whose parent is the session folder; a file sitting
    directly in a session folder (the oldest hand-managed layouts) is its
    parent's child already.
    """
    parent = file_path.parent
    return parent.parent if parent.name in FORMAT_DIRS else parent


def read_run(path: str | Path) -> ReadResult:
    """Load one per-animal session document.

    Three outcomes, deliberately distinguished because they mean different
    things to the operator:

    * **missing** — nothing at that path. When the sibling `.tsv` *is* there,
      say so: that is the disk-full-at-finalization case (`data-saving.md`
      §7.2 writes `.json` best-effort and only logs an `OSError`), the data is
      not lost, and the crash-recovery utility is what fixes it.
    * **unreadable** — present but not parseable. Cached as a negative result
      so it isn't re-parsed on every dashboard open.
    * **ok** — with the stat used for cache invalidation.
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
        return ReadResult(status="missing", detail=detail)
    except OSError as exc:
        return ReadResult(status="unreadable", detail=str(exc))

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
        mtime_ns=stat.st_mtime_ns,
        size=stat.st_size,
    )


def walk_session_files(cohort_folder: str | Path) -> list[Path]:
    """Every per-animal `.json` under one cohort's data folder (§8.1).

    Only used by the explicit rescan — the normal path reads what run records
    point at. Scoped to `behavior.json/` folders rather than every `.json` in
    the tree, so an unrelated file someone dropped in the cohort folder is
    never mistaken for a session.
    """
    base = Path(cohort_folder).expanduser()
    if not base.is_dir():
        return []
    try:
        found: list[Path] = []
        for json_dir in (JSON_DIR, LEGACY_JSON_DIR):
            found.extend(
                p for p in base.glob(f"*/*/{json_dir}/*.json") if not is_sidecar_file(p)
            )
        return sorted(found)
    except OSError as exc:  # pragma: no cover - unreadable mount
        log.warning("couldn't walk %s: %s", base, exc)
        return []

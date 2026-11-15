"""The archive walk's parts — `DATA.md#orphan-adoption`, `DATA.md#pruning`,
`DATA.md#tidy-records`.

What a rescan and a tidy (`CohortArchive.rescan`, `CohortArchive.tidy`) ask
the disk, and how a rescan matches a stray file to an animal and names the
row it adopts it under.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from . import reader
from .repository import AdoptedRun

log = logging.getLogger(__name__)


def _is_gone(path: str | None, *, kind: str = "run-file") -> bool:
    """Is this path **reachable and absent** — as opposed to just unreachable?

    This is the whole safety of the prune, and the distinction is not
    cosmetic. `exists() is False` answers two completely different questions
    with one word: *the operator deleted this* and *this volume isn't mounted
    right now*. Acting on the second would let one rescan with a drive
    unplugged erase a cohort's history, which is the exact failure the
    keep-the-last-good-summary rule (`DATA.md#caching`) exists to prevent — so
    it must not be
    reintroduced by the mechanism that finally clears genuinely dead records.

    So absence only counts when the storage is demonstrably there: some
    ancestor of the path must be readable. A deleted tree always leaves one
    (the drive root at worst); an unmounted volume leaves none, not even
    `E:\\` or `//server/share`.

    Three further refusals, each an honest "can't tell" rather than a guess:

    * **No recorded path** — nothing to observe. Reported as `missing` by the
      summary already, with its own distinct reason.
    * **A path that can't be `stat`ed for any reason other than not being
      there** — a permission error is not a deletion.
    * **A `.json` whose write-ahead `.tsv` is still on disk** — that run's data
      is intact and `sessions.recover` will rebuild the document from it
      (`DATA.md#crash-recovery`). Pruning it would throw away the `animal_id`,
      `profile_hash` and `config_json` that make the recovered file worth more
      than the orphan adoption could ever reconstruct from a filename.
    """
    if not path:
        return False
    target = Path(path).expanduser()
    try:
        target.stat()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    else:
        # Something is there. Whether it is the *kind* of thing expected is a
        # different question and not this one's business: a session folder
        # replaced by a file is a broken archive, not a deletion.
        return False

    if kind == "run-file":
        try:
            if reader.sibling_tsv(target).is_file():
                return False
        except OSError:  # pragma: no cover - unreadable mount
            return False

    return _storage_is_reachable(target)


def _storage_is_reachable(target: Path) -> bool:
    """Can we see *any* of the path's ancestry? Bottom-up, so a deleted leaf
    costs one stat and an unmounted volume costs the depth of the path."""
    for ancestor in target.parents:
        try:
            if ancestor.is_dir():
                return True
        except OSError:  # pragma: no cover - unreadable mount
            return False
    return False


def _same_path(recorded: str, found: Path) -> bool:
    return _normalize(recorded) == _normalize(str(found))


def _folder_state(path: str) -> bool | None:
    """True if the folder holds any file, False if it demonstrably holds none
    (or is gone), None if it cannot be seen — never read as empty
    (`DATA.md#tidy-records`)."""
    if not path:
        return None
    target = Path(path).expanduser()
    try:
        if target.is_dir():
            return any(child.is_file() for child in target.rglob("*"))
    except OSError:
        return None
    return False if _is_gone(path, kind="folder") else None


def _remove_empty_tree(path: str) -> None:
    """Remove a session folder that contains no file — directories only.

    Bottom-up `rmdir`, which the OS refuses for anything non-empty, so a file
    that appeared since the plan (or a check that was wrong) stops it cold
    rather than being deleted. Never `rmtree`: the app deletes its own
    records, never the user's data (`DATA.md#archive-and-delete`).
    """
    import os

    root = Path(path).expanduser()
    if not root.is_dir():
        return
    try:
        for current, _dirs, files in os.walk(root, topdown=False):
            if files:
                return
            os.rmdir(current)
    except OSError as exc:
        log.info("tidy: left folder %s in place (%s)", path, exc)


def _normalize(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve()).casefold()
    except OSError:  # pragma: no cover
        return path.casefold()


def _iso_or_none(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


# --- adopted orphans (DATA.md#orphan-adoption) -----------------------------


def _prefer(candidate: AdoptedRun, incumbent: AdoptedRun) -> bool:
    """Which copy of the same run to keep.

    Richer wins: a copy whose document names its sketch can be decoded, and one
    that doesn't cannot. The real Remy archive has exactly this asymmetry — 30
    runs where only the consolidated copy carries `sketch` — so "first one
    found" would have thrown away the only usable version. Ties break on path
    so a rescan is deterministic rather than dependent on walk order.

    Judged only on what the *document* says, never on whether that sketch
    currently resolves to a directory entry: resolution depends on settings
    that change between scans, so letting it decide would make the winner —
    and with it the run's recorded file path — flip back and forth for reasons
    that have nothing to do with the data.
    """
    if bool(candidate.sketch_name) != bool(incumbent.sketch_name):
        return bool(candidate.sketch_name)
    return candidate.file_path < incumbent.file_path


def _adoptable_animals(cohort: Any) -> list[Any]:
    """Who a stray file may be matched to: the roster, then the cohort's
    stored former members (`DATA.md#former-members`).

    A file written while an animal was on the roster is still that animal's
    after it comes off. But never a former member whose name an active animal
    now holds — the file is a name, and that name means the animal on the
    roster. Ids derived from files alone (`source == "files"`) are never
    candidates: their name is itself a reading of the files.
    """
    active = {a.name.casefold() for a in cohort.animals}
    former = [
        f
        for f in getattr(cohort, "former_animals", [])
        if f.source == "removed" and f.name and f.name.casefold() not in active
    ]
    return [*cohort.animals, *former]


def _animal_from_filename(
    path: Path, session_folder: Path, animals: list[Any]
) -> str | None:
    """The animal a file *names*, when the document it holds got it wrong.

    Real archives carry typos. One file in this lab's Squeekstreet archive
    records `rat: "HmM103"` while its filename says `HM103_…` — and without a
    second opinion that run vanishes from HM103's history, which reads like the
    animal didn't run that day rather than like a mistyped field. A hole that
    looks like data is the worst of the available failures.

    This is not the guessing `DATA.md#orphan-adoption` rules out. The
    filename and the `rat` field
    are two independent recordings of the same fact by the same program at the
    same moment, and the stem has to be *exactly* what `DATA.md#names`
    prescribes — `<animal>_<the session folder this file is actually sitting
    in>_<HHMMSS>` — checked against the folder on disk rather than assumed. A
    file that doesn't follow the convention contributes nothing. The token that
    survives all that must still match a roster name exactly, case-folded, the
    same test the document's field had to pass.
    """
    token = reader.animal_token(path, session_folder)
    if token is None:
        return None
    folded = token.casefold()
    return next((a.id for a in animals if a.name.casefold() == folded), None)


def _orphan_run_id(cohort_id: str, path: Path) -> str:
    """The id a new adoption is stored under (`DATA.md#orphan-adoption`).

    Keyed on the **cohort and the run identity** (the file stem), never the
    path. A duplicated run has two paths, and which copy `_prefer` picks can
    legitimately change between scans — when a sketch reappears in the
    library, say, and one copy suddenly resolves a profile. A path-keyed id
    would then mint a *second* row for a run that already had one, leaving
    both in place: precisely the double-counting the deduplication exists to
    prevent. And two cohorts whose folders overlap find the *same* path, so
    only the cohort in the key keeps their rows apart.

    Only for a run the cohort does not hold yet. A held row keeps the id it
    was stored under, whatever this returns for it now: a person's ruling
    (`run_flags`) and the cached scores are keyed by that id.
    """
    key = f"{cohort_id}\0{reader.run_identity(path)}"
    return f"adopted:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}"


def _stem_only_run_id(path: Path) -> str:
    """The stem-only id: the run identity alone, with no cohort.

    A row held under its stem-only id keeps it (`_orphan_run_id`), so it is
    the key of any ruling a person made on that run. When such a row is pruned
    and its run adopted afresh, the ruling moves to the new id (`_earlier_ids`,
    `ANALYTICS.md#false-starts`).
    """
    digest = hashlib.sha1(reader.run_identity(path).encode("utf-8")).hexdigest()
    return f"adopted:{digest[:16]}"


def _earlier_ids(
    adoptable: list[AdoptedRun],
    held: dict[str, str],
    dropped: dict[str, str],
    move_sources: dict[str, str | None],
) -> dict[str, list[str]]:
    """The ids a ruling on each freshly adopted run may still sit on
    (`ANALYTICS.md#false-starts`), for `store_adopted` to move it from.

    Only for a run the cohort did not hold: a row read again keeps its own id
    and its own ruling, and never takes one another cohort's pruned row left.
    First the id of a row this rescan's prune just dropped for the same run,
    which a move kept from the cohort that first adopted it. Then the id each
    cohort a move brought this one's animals from would mint for the run
    (`move_sources`: id → data folder, None once the cohort is deleted), for
    a moved row an earlier rescan pruned while its file was away; but never
    the id of a cohort whose folder holds the file, since that cohort may read
    the run again under that very id and its ruling waits for it. Then the
    stem-only id.
    """
    out: dict[str, list[str]] = {}
    for entry in adoptable:
        path = Path(entry.file_path)
        identity = reader.run_identity(path)
        if held.get(identity) is not None:
            continue
        candidates = [dropped[identity]] if identity in dropped else []
        candidates += [
            _orphan_run_id(source, path)
            for source, folder in sorted(move_sources.items())
            if folder is None or not _holds(folder, path)
        ]
        out[entry.id] = [*candidates, _stem_only_run_id(path)]
    return out


def _holds(folder: str, path: Path) -> bool:
    """Is `path` inside `folder`, so a rescan of that folder walks it?"""
    return Path(_normalize(str(path))).is_relative_to(_normalize(folder))

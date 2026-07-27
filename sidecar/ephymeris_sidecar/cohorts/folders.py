"""Cohort data folder resolution — `cohorts.md` §8.

Two rules here are deliberate design calls, not conveniences:

* **Renaming never moves the folder.** The path is resolved once at creation and
  persisted verbatim. An automatic move-on-rename is exactly the kind of
  implicit file operation this project avoids elsewhere.
* **Relocating refuses rather than overwrites.** A non-empty destination is an
  error, not something to merge into.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

#: Characters that are illegal or troublesome in a path segment on either
#: target platform. Windows is the stricter of the two, so it sets the rule.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_SEGMENT = 64


class DataFolderError(Exception):
    """The folder couldn't be created, or a destination was unusable."""


def sanitize_name(name: str) -> str:
    """Turn a cohort name into a safe single path segment."""
    cleaned = _UNSAFE.sub("-", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned[:_MAX_SEGMENT].strip()
    return cleaned or "cohort"


def resolve_default_folder(data_directory: str | None, cohort_name: str) -> Path:
    """`<Settings.dataDirectory>/<sanitized name>`, suffixed until unique.

    Raises when `dataDirectory` isn't configured: there is no basis for a
    default, and inventing one would put session data somewhere the user
    wouldn't think to look. The editor requires an explicit folder in that case.
    """
    if not data_directory or not str(data_directory).strip():
        raise DataFolderError(
            "No data directory is configured. Set one in Settings, or choose a "
            "folder for this cohort explicitly."
        )

    root = Path(data_directory).expanduser()
    base = sanitize_name(cohort_name)

    candidate = root / base
    suffix = 2
    while candidate.exists():
        candidate = root / f"{base}-{suffix}"
        suffix += 1
    return candidate


def ensure_folder(path: str | Path) -> Path:
    """Create the folder if needed and confirm it's usable."""
    target = Path(path).expanduser()
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DataFolderError(f"Couldn't create {target}: {exc.strerror or exc}") from exc
    if not target.is_dir():
        raise DataFolderError(f"{target} exists but isn't a folder.")
    return target


def _is_empty(path: Path) -> bool:
    try:
        return not any(path.iterdir())
    except OSError:
        return False


def relocate(current: str | Path, destination: str | Path, move_existing: bool) -> Path:
    """The explicit "Change data folder…" action (§8).

    Two different intents share this one command, and they have opposite
    requirements for the destination:

    * **Move my data there** (`move_existing=True`) — the destination must be
      empty, because merging two archives into one folder can silently collide
      filenames and there is no safe way to reconcile that automatically.
    * **Point this cohort at data that is already there** (`move_existing=False`)
      — the destination is *expected* to be full. This is how a cohort attaches
      to an archive written before this app existed, which is the entire reason
      orphan adoption exists (`analytics.md` §8.1).

    Refusing a non-empty destination in both cases made the second intent
    impossible to express: the only control for it rejected exactly the folders
    it was meant to accept. Nothing is written to the destination when not
    moving, so there is nothing there to protect.
    """
    source = Path(current).expanduser()
    target = Path(destination).expanduser()

    if source == target:
        return target

    if target.exists() and not target.is_dir():
        raise DataFolderError(f"{target} exists but isn't a folder.")
    if move_existing and target.exists() and not _is_empty(target):
        raise DataFolderError(
            f"{target} isn't empty. Choose an empty folder to move this "
            f"cohort's data into — Ephymeris won't merge into or overwrite "
            f"existing data. To use the data already in {target.name}, "
            f"change the folder without moving."
        )

    if move_existing and source.exists():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                # mkdir'd or pre-existing but empty: move contents into it,
                # since shutil.move would otherwise nest source *inside* target.
                for entry in source.iterdir():
                    shutil.move(str(entry), str(target / entry.name))
                source.rmdir()
            else:
                shutil.move(str(source), str(target))
        except OSError as exc:
            raise DataFolderError(f"Couldn't move data to {target}: {exc}") from exc
        return target

    return ensure_folder(target)

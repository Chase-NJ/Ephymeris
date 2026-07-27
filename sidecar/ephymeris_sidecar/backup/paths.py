"""Mirror path resolution — `data-saving.md` §8.

A cohort's data folder can be relocated anywhere via `cohorts.setDataFolder`
(`cohorts.md` §8), so a mirror path **cannot** be derived by subtracting
`Settings.dataDirectory` from a source path — the source may not live under it.
Every mirrored file is anchored on the cohort folder that contains it instead:

    <backupDirectory>/<cohort folder basename>/<path relative to that folder>

In the normal case — cohort folders sitting directly under `dataDirectory` —
that reproduces the familiar layout exactly, so the backup stays browsable by a
human who has never read this file. That property is the point: a last-resort
archive nobody can navigate is worth much less than one they can.

Two cohorts can only collide here if *both* had their folders relocated by hand
to different parents that share a basename. When that happens every member of
the colliding set gets a short path-derived suffix, so the layout is stable
regardless of which order the cohorts are enumerated in.

Pure path arithmetic, no I/O, so the layout is testable on its own.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

#: Length of the disambiguating suffix used when two cohort folders share a
#: basename. Eight hex characters of SHA-1 over the full path.
_SUFFIX_LEN = 8


def _resolve(path: str | Path) -> Path:
    """Best-effort absolute path. Never raises — a missing path still resolves."""
    candidate = Path(path).expanduser()
    try:
        return candidate.resolve()
    except OSError:  # pragma: no cover - only on an unreadable mount
        return candidate.absolute()


def _fold(name: str) -> str:
    """Collision key. Case-insensitive, because Windows paths are."""
    return name.casefold()


def mirror_segments(roots: Iterable[str | Path]) -> dict[Path, str]:
    """Map each cohort folder to its single path segment under the backup root.

    Duplicates are collapsed first, so the same folder listed twice doesn't
    look like a collision with itself.
    """
    resolved: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        path = _resolve(root)
        if path not in seen:
            seen.add(path)
            resolved.append(path)

    counts = Counter(_fold(path.name) for path in resolved)

    segments: dict[Path, str] = {}
    for path in resolved:
        name = path.name or "cohort"
        if counts[_fold(path.name)] > 1:
            digest = hashlib.sha1(str(path).casefold().encode("utf-8")).hexdigest()
            name = f"{name}-{digest[:_SUFFIX_LEN]}"
            log.warning(
                "two cohort folders share the basename %r; mirroring %s as %r",
                path.name,
                path,
                name,
            )
        segments[path] = name
    return segments


class MirrorLayout:
    """Resolves many source paths against one fixed set of cohort roots.

    Segment computation touches the filesystem (`Path.resolve`) once per root,
    so it's hoisted here rather than repeated per file. That's immaterial for a
    ten-second pass over six live files and very much not immaterial for
    `backup.syncNow` walking an archive of thousands.
    """

    def __init__(self, roots: Iterable[str | Path], backup_root: str | Path) -> None:
        # Longest root first, so the first match is the most specific one: a
        # cohort folder nested inside another mirrors under its own name.
        self._roots = sorted(
            mirror_segments(roots).items(),
            key=lambda pair: len(pair[0].parts),
            reverse=True,
        )
        self._backup_root = Path(backup_root).expanduser()

    def resolve(self, source: str | Path) -> Path | None:
        """Where `source` belongs inside the backup directory.

        Returns `None` when the file isn't under any known cohort folder —
        nothing outside a cohort's own data folder is ours to mirror, and
        guessing a location for it would scatter unrelated files through the
        archive.
        """
        src = _resolve(source)
        for root, segment in self._roots:
            try:
                relative = src.relative_to(root)
            except ValueError:
                continue
            return self._backup_root / segment / relative
        return None


def resolve_mirror_path(
    source: str | Path,
    roots: Iterable[str | Path],
    backup_root: str | Path,
) -> Path | None:
    """One-shot convenience wrapper over `MirrorLayout`."""
    return MirrorLayout(roots, backup_root).resolve(source)

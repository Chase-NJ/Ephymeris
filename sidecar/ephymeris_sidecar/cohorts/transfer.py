"""Copying a cohort's files to another place, verified — `DATA.md#verified-transfer`.

The file half of both transfers that move data between folders: a relocate
onto another volume (`relocate`) and a move of animals between cohorts
(`move_apply`). Each runs the same three steps around its own journal and its
own commit of the records:

1. `copy` — every file through `<name>.part`: copied, fsync'd, renamed into
   place, then re-read and hash-checked. A crash leaves at most a `.part`,
   never a partial file under the real name.
2. `undo`, before the records commit — a copy goes only while its original is
   still there with the same content, and so does any `.part`.
3. `delete_originals`, after they commit — an original goes only while its
   content is still the copy's.

What is never done: delete a file that is the only copy of its content, or
overwrite a destination that differs. Synchronous; callers run it in a worker
thread.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

log = logging.getLogger(__name__)

PART_SUFFIX = ".part"


@dataclass(frozen=True)
class FileCopy:
    src: Path
    dst: Path
    #: The content the copy must have. None when the caller has not read it
    #: (a relocate's files, or anything a restart is cleaning up): `copy` reads
    #: it from the original, and the other steps compare the two files.
    sha256: str | None = None


def digest(path: Path) -> tuple[int, str] | None:
    """Size and SHA-256, or None when there is nothing readable there."""
    try:
        if not path.is_file():
            return None
        h = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                h.update(chunk)
                size += len(chunk)
        return size, h.hexdigest()
    except OSError:
        return None


def part_of(dst: Path) -> Path:
    return dst.with_name(dst.name + PART_SUFFIX)


def copy(
    files: Iterable[FileCopy], on_copied: Callable[[int, int], None] | None = None
) -> list[FileCopy]:
    """Copy each file, verified. Returns them with `sha256` filled in.

    A destination already holding the same content is left as it is; one
    holding anything else raises `OSError`, as does a copy that does not
    re-read as its original. `on_copied(done, total)` follows each file.
    """
    todo = list(files)
    done: list[FileCopy] = []
    for index, f in enumerate(todo):
        expected = f.sha256
        if expected is None:
            read = digest(f.src)
            if read is None:
                raise OSError(f"{f.src} can't be read")
            expected = read[1]
        existing = digest(f.dst)
        if existing is not None:
            if existing[1] != expected:
                raise OSError(f"{f.dst} already exists and differs from the file being copied")
        else:
            f.dst.parent.mkdir(parents=True, exist_ok=True)
            part = part_of(f.dst)
            shutil.copy2(f.src, part)
            with part.open("rb+") as handle:
                os.fsync(handle.fileno())
            os.replace(part, f.dst)
            copied = digest(f.dst)
            if copied is None or copied[1] != expected:
                raise OSError(f"{f.dst} did not verify after copying")
        done.append(replace(f, sha256=expected))
        if on_copied is not None:
            on_copied(index + 1, len(todo))
    return done


def undo(files: Iterable[FileCopy]) -> None:
    """Remove copies the records never followed, and any `.part` left half
    written. Only the caller's own copies: never pass a destination file that
    was there before the transfer."""
    for f in files:
        try:
            part_of(f.dst).unlink(missing_ok=True)
        except OSError:
            pass
        # The original must still be there, the same: the one rule that
        # makes undoing safe. Read it even with a known hash, or a copy of
        # content the original no longer has would go.
        original = digest(f.src)
        copied = digest(f.dst)
        if (
            original is not None
            and copied is not None
            and copied[1] == original[1]
            and f.sha256 in (None, original[1])
        ):
            try:
                f.dst.unlink()
            except OSError as exc:
                log.warning("transfer: couldn't remove copy %s: %s", f.dst, exc)


def delete_originals(files: Iterable[FileCopy]) -> set[Path]:
    """After the records commit, delete each original whose content is still
    the copy's. A file changed since it was copied is left where it is: it is
    not the file that was copied. Returns the folders it removed files from."""
    touched: set[Path] = set()
    for f in files:
        original = digest(f.src)
        if original is None:
            continue
        # Read the copy too, even with a known hash: an original goes only
        # while a copy of it is actually there.
        copied = digest(f.dst)
        if copied is None or copied[1] != original[1] or f.sha256 not in (None, original[1]):
            log.warning("transfer: %s differs from its copy; left in place", f.src)
            continue
        try:
            f.src.unlink()
            touched.add(f.src.parent)
        except OSError as exc:
            log.warning("transfer: couldn't remove %s: %s", f.src, exc)
    return touched

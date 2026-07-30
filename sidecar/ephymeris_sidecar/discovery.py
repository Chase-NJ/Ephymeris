"""Arduino Directory validation and sketch discovery.

Implements `tasks.md` §2.2–§6. Owned by the sidecar because
filesystem work and `arduino-cli` interaction already live here.

The two rules most worth preserving:

* A folder is a valid sketch only if it contains a `.ino` whose base name
  matches the folder's own name (§3). This is arduino-cli's own requirement and
  the single most common reason a sketch silently fails to appear.
* Folders that fail that rule are **skipped but reported** (§4 step 4), never
  silently dropped — otherwise a misnamed sketch is invisible rather than
  merely broken.

Category folders may nest (§3): real lab directories group sketches by
paradigm *and* stage, so the scan descends until it finds sketches rather than
assuming a fixed two-level shape. A sketch's category is the folder that
directly contains it.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

#: Reserved folder name, matched case-insensitively because both target
#: filesystems are case-insensitive by default (§3). Reserved at *every* depth
#: so a nested `libraries/` is never mistaken for a category — only the root
#: one is passed to `arduino-cli --libraries`.
LIBRARIES_DIRNAME = "libraries"

#: How far below the root to look for sketches. Deep enough for the
#: category/sub-category/sketch layouts real labs use, shallow enough that
#: pointing the app at a huge tree by mistake can't crawl for minutes.
MAX_SCAN_DEPTH = 5

DirectoryState = Literal["not_configured", "invalid", "empty", "ok"]


@dataclass(frozen=True)
class Sketch:
    category: str
    name: str
    path: str


@dataclass(frozen=True)
class SkippedEntry:
    path: str
    reason: str


@dataclass(frozen=True)
class DirectoryStatus:
    state: DirectoryState
    path: str | None = None
    message: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SketchDiscovery:
    directory: DirectoryStatus
    sketches: list[Sketch] = field(default_factory=list)
    skipped: list[SkippedEntry] = field(default_factory=list)
    libraries: list[str] = field(default_factory=list)
    libraries_path: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "directory": self.directory.to_json(),
            "sketches": [asdict(s) for s in self.sketches],
            "skipped": [asdict(s) for s in self.skipped],
            "skippedCount": len(self.skipped),
            "libraries": self.libraries,
            "librariesPath": self.libraries_path,
        }


def validate_directory(path: str | None) -> DirectoryStatus:
    """Check the configured root, per §6.

    Distinguishes "you haven't set this yet" from "what you set is broken" —
    the first is expected on first run and is not an error.
    """
    if not path or not str(path).strip():
        return DirectoryStatus("not_configured")

    root = Path(path).expanduser()
    if not root.exists():
        return DirectoryStatus(
            "invalid", str(root), "Can't find your configured Arduino Directory."
        )
    if not root.is_dir():
        return DirectoryStatus(
            "invalid", str(root), "The configured Arduino Directory isn't a folder."
        )
    if not os.access(root, os.R_OK | os.X_OK):
        return DirectoryStatus(
            "invalid", str(root), "The configured Arduino Directory isn't readable."
        )
    return DirectoryStatus("ok", str(root))


def _is_valid_sketch(folder: Path) -> bool:
    """The folder-name-matches-`.ino` rule from §3."""
    return (folder / f"{folder.name}.ino").is_file()


def _contains_ino(folder: Path) -> bool:
    """Does this folder hold any `.ino` at all?

    Distinguishes a *broken sketch* (has an `.ino`, wrongly named — worth
    reporting) from a plain organisational folder (no `.ino`, just grouping —
    not an error).
    """
    try:
        return any(child.suffix.lower() == ".ino" and child.is_file() for child in folder.iterdir())
    except OSError:
        return False


def _skippable(child: Path) -> bool:
    """Folders the scan should pass over without comment.

    Hidden folders cover `.git`, `.claude`, `.vscode` and friends — reporting
    `.git/objects` as an unreadable sketch would bury real problems in noise.
    """
    return child.name.startswith(".") or child.name.lower() == LIBRARIES_DIRNAME


def _scan(
    folder: Path,
    depth: int,
    sketches: list[Sketch],
    skipped: list[SkippedEntry],
    visited: set[Path],
) -> None:
    """Walk one category folder, recursing through sub-categories.

    A sketch's category is the folder directly containing it, so
    `Olfactory Behavior/01_Shaping/shaping_GL` is filed under `01_Shaping`.
    """
    try:
        children = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        skipped.append(SkippedEntry(str(folder), f"couldn't be read: {exc.strerror}"))
        return

    for child in children:
        if not child.is_dir() or _skippable(child):
            continue

        # Symlinks are legitimate here (shared sketches, vendored libraries),
        # so guard against cycles by real path rather than refusing to follow.
        try:
            real = child.resolve()
        except OSError:
            continue
        if real in visited:
            continue
        visited.add(real)

        if _is_valid_sketch(child):
            sketches.append(Sketch(category=folder.name, name=child.name, path=str(child)))
            # Don't descend into a sketch: `src/`, `extras/` and the like are
            # its own business, not more categories.
            continue

        if _contains_ino(child):
            skipped.append(
                SkippedEntry(str(child), f"no {child.name}.ino matching the folder name")
            )
            continue

        if depth < MAX_SCAN_DEPTH:
            _scan(child, depth + 1, sketches, skipped, visited)


def discover(path: str | None) -> SketchDiscovery:
    """Scan the Arduino Directory, per the §4 algorithm."""
    status = validate_directory(path)
    if status.state != "ok" or status.path is None:
        return SketchDiscovery(directory=status)

    root = Path(status.path)
    sketches: list[Sketch] = []
    skipped: list[SkippedEntry] = []
    libraries: list[str] = []
    libraries_path: str | None = None

    try:
        top_level = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        return SketchDiscovery(
            directory=DirectoryStatus(
                "invalid", str(root), f"Couldn't read the Arduino Directory: {exc.strerror}"
            )
        )

    visited: set[Path] = set()

    for entry in top_level:
        if not entry.is_dir():
            continue

        # Only the *root* `libraries/` is handed to arduino-cli; nested ones are
        # reserved by name (never scanned) but not passed to compile.
        if entry.name.lower() == LIBRARIES_DIRNAME:
            libraries_path = str(entry)
            try:
                libraries = sorted(
                    (child.name for child in entry.iterdir() if child.is_dir()),
                    key=str.lower,
                )
            except OSError:
                libraries = []
            continue

        if entry.name.startswith("."):
            continue

        # A sketch sitting at the root has no category to belong to; §3 puts
        # sketches inside a category folder. Report rather than ignore.
        if _is_valid_sketch(entry):
            skipped.append(
                SkippedEntry(str(entry), "sketch folders belong inside a category folder")
            )
            continue

        _scan(entry, 1, sketches, skipped, visited)

    # "Valid but empty" is a distinct state from an error (§6): the path is
    # fine, there's just nothing validly named in it yet.
    if not sketches:
        return SketchDiscovery(
            directory=DirectoryStatus(
                "empty",
                str(root),
                "No valid sketches found. A sketch folder must contain a .ino file "
                "with the same name as the folder.",
            ),
            skipped=skipped,
            libraries=libraries,
            libraries_path=libraries_path,
        )

    return SketchDiscovery(
        directory=status,
        sketches=sketches,
        skipped=skipped,
        libraries=libraries,
        libraries_path=libraries_path,
    )

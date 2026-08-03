"""The bundled sketch library, and discovery within it.

Implements `tasks.md` §2. Owned by the sidecar because filesystem work and
`arduino-cli` interaction already live here.

SKETCHES SHIP WITH THE APP. There is no configured Arduino Directory: the
library is staged into the installer by `scripts/stage-sketches.mjs` and located
here by `library_root()`. That makes the failure modes structural rather than
user-authored — a library can be missing or partial, but it can no longer be
*misconfigured*, and "you haven't set this up yet" stopped being a state anyone
can be in.

The consequence worth stating plainly: adding a sketch now needs a new build.
That is the deliberate trade, and `library_status()` carries the word "damaged"
rather than "invalid" because the remedy changed with it — the old copy sent the
user to a directory picker, and the new one has to send them to whoever
maintains the app.

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

LibraryState = Literal["ok", "empty", "damaged"]
LibrarySource = Literal["bundled", "override"]

#: Points the sidecar at a sketch library other than the bundled one. A developer
#: facility, documented in README.md §2 — deliberately an environment variable and
#: NOT a setting, so it cannot come back as a configurable directory by the back
#: door, and so `not_configured` cannot come back as a state.
LIBRARY_ENV = "EPHYMERIS_SKETCH_LIBRARY"

#: Set by the Tauri shell from its resource dir, exactly as
#: EPHYMERIS_BUNDLED_ARDUINO_CLI already is (`src-tauri/src/sidecar.rs`).
BUNDLED_ENV = "EPHYMERIS_BUNDLED_SKETCHES"


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
class SketchLibraryStatus:
    state: LibraryState
    path: str | None = None
    message: str | None = None
    source: LibrarySource = "bundled"

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SketchDiscovery:
    library: SketchLibraryStatus
    sketches: list[Sketch] = field(default_factory=list)
    skipped: list[SkippedEntry] = field(default_factory=list)
    libraries: list[str] = field(default_factory=list)
    libraries_path: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "library": self.library.to_json(),
            "sketches": [asdict(s) for s in self.sketches],
            "skipped": [asdict(s) for s in self.skipped],
            "skippedCount": len(self.skipped),
            "libraries": self.libraries,
            "librariesPath": self.libraries_path,
        }


def library_root() -> tuple[Path | None, LibrarySource]:
    """Where the sketch library lives, and whether it is the shipped one.

    Three candidates, in order, mirroring how `sidecar.rs::resolve_launch`
    already picks an interpreter:

        $EPHYMERIS_SKETCH_LIBRARY   a developer pointing somewhere else
        $EPHYMERIS_BUNDLED_SKETCHES the installed app, set by the Tauri shell
        <repo>/sketches             a checkout, staged by npm run predev

    The last one is not a fallback for a broken install — it is the only way
    `npm run tauri:dev` works at all, since a dev run has no staged installer
    resources.
    """
    override = os.environ.get(LIBRARY_ENV)
    if override and override.strip():
        return Path(override).expanduser(), "override"

    bundled = os.environ.get(BUNDLED_ENV)
    if bundled and bundled.strip():
        return Path(bundled).expanduser(), "bundled"

    # sidecar/ephymeris_sidecar/discovery.py -> <repo>/sketches
    repo = Path(__file__).resolve().parent.parent.parent / "sketches"
    if repo.is_dir():
        return repo, "bundled"
    return None, "bundled"


def library_status() -> SketchLibraryStatus:
    """Check the library the app shipped with.

    Every failure here means a broken or partial INSTALL, never a wrong setting,
    so every message points at reinstalling rather than at a picker.
    """
    root, source = library_root()
    if root is None:
        return SketchLibraryStatus(
            "damaged",
            None,
            "Ephymeris couldn't find the sketches it ships with. The install looks "
            "incomplete — reinstalling should fix it.",
            source,
        )
    if not root.exists() or not root.is_dir():
        return SketchLibraryStatus(
            "damaged",
            str(root),
            "The sketches Ephymeris ships with are missing. The install looks "
            "incomplete — reinstalling should fix it.",
            source,
        )
    if not os.access(root, os.R_OK | os.X_OK):
        return SketchLibraryStatus(
            "damaged",
            str(root),
            "Ephymeris can't read the sketches it ships with — check the "
            "permissions on the install folder.",
            source,
        )
    return SketchLibraryStatus("ok", str(root), None, source)


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


def discover() -> SketchDiscovery:
    """Scan the bundled sketch library, per the §2.3 algorithm."""
    status = library_status()
    if status.state != "ok" or status.path is None:
        return SketchDiscovery(library=status)

    root = Path(status.path)
    sketches: list[Sketch] = []
    skipped: list[SkippedEntry] = []
    libraries: list[str] = []
    libraries_path: str | None = None

    try:
        top_level = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        return SketchDiscovery(
            library=SketchLibraryStatus(
                "damaged",
                str(root),
                f"Couldn't read the bundled sketches: {exc.strerror}",
                status.source,
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

    # A readable library holding nothing valid is its own state. It used to mean
    # "you pointed at the wrong folder"; now it can only mean a partial install,
    # so it reads as one.
    if not sketches:
        return SketchDiscovery(
            library=SketchLibraryStatus(
                "empty",
                str(root),
                "Ephymeris shipped without any usable sketches, which shouldn't "
                "happen — reinstalling should fix it.",
                status.source,
            ),
            skipped=skipped,
            libraries=libraries,
            libraries_path=libraries_path,
        )

    return SketchDiscovery(
        library=status,
        sketches=sketches,
        skipped=skipped,
        libraries=libraries,
        libraries_path=libraries_path,
    )

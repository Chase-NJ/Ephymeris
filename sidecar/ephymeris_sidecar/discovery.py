"""The bundled sketch library, and discovery within it.

Implements `TASKS.md#sketch-library`. Owned by the sidecar because filesystem work and
`arduino-cli` interaction already live here.

SKETCHES SHIP WITH THE APP. There is no configured sketch directory: the
library is staged into the installer by `scripts/stage-sketches.mjs` and located
here by `library_root()`. That makes the failure modes structural rather than
user-authored — a library can be missing or partial, but it can no longer be
*misconfigured*, and "you haven't set this up yet" stopped being a state anyone
can be in.

`library_status()` therefore carries the word "damaged" rather than "invalid":
the remedy is reinstalling, not a directory picker.

TWO MORE ROOTS, AND THEY DO DIFFERENT THINGS.

`<data_dir>/tasks/` holds the sketch folders the app GENERATES from this rig's
task profiles. They are scanned exactly like bundled ones and marked
`source: "rig"`, and they APPEND — a name that collides with a bundled sketch is
reported and dropped. This is the walk-back `TASKS.md#library-roots` allows: a
hidden additional library that appends to the bundle, never a return of the
configured root. It is what makes a saved profile an ordinary discovered sketch, so
`port.flash`, the session flow and Analytics need no special case for one.

`<data_dir>/rig/sketches/` holds rebuilds of the BUNDLED sketches against this
rig's wiring (`taskdef/bundled.py`). Those REPLACE the entry they were built
from rather than appending: a rebuild is the same sketch with the right pins,
not a second one, and offering both would make flashing a coin flip. They keep
`source: "bundled"` for the same reason — what they are has not changed, only
which pins they compile against.

Neither is user-configurable and neither can be pointed anywhere: the app writes
them, the app scans them.

The two rules most worth preserving:

* A folder is a valid sketch only if it contains a `.ino` whose base name
  matches the folder's own name (`TASKS.md#folder-rules`). This is arduino-cli's own requirement and
  the single most common reason a sketch silently fails to appear.
* Folders that fail that rule are **skipped but reported** (`TASKS.md#discovery`), never
  silently dropped — otherwise a misnamed sketch is invisible rather than
  merely broken.

Category folders may nest (`TASKS.md#folder-rules`): real lab directories group sketches by
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
#: filesystems are case-insensitive by default (`TASKS.md#folder-rules`). Reserved at *every* depth
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
#: facility, documented in `TASKS.md#library-roots` — deliberately an environment variable and
#: NOT a setting, so it cannot come back as a configurable directory by the back
#: door, and so `not_configured` cannot come back as a state.
LIBRARY_ENV = "EPHYMERIS_SKETCH_LIBRARY"

#: Set by the Tauri shell from its resource dir, exactly as
#: EPHYMERIS_BUNDLED_ARDUINO_CLI already is (`src-tauri/src/sidecar.rs`).
BUNDLED_ENV = "EPHYMERIS_BUNDLED_SKETCHES"


SketchSource = Literal["bundled", "rig"]


@dataclass(frozen=True)
class Sketch:
    category: str
    name: str
    path: str
    #: Where it came from. `rig` means the app generated it from a task profile
    #: on this machine, so it is regenerated on every save and every wiring
    #: change — and editing the folder by hand is pointless.
    source: SketchSource = "bundled"


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


def _plain(value: str) -> Path:
    r"""Read a path from the environment without Windows' verbatim prefix.

    The shell simplifies these before exporting them, so this is the second
    line — but it is worth having, because the value ends up as
    `arduino-cli --libraries` and the failure mode is silent. `arduino-cli` is
    Go: handed `\\?\C:\...\libraries` it finds no libraries there and says
    nothing, and the compile fails much later on `#include <BehaviorBox.h>`,
    reading exactly like a library missing from the install. That shipped once
    (v1.1.0-rc.2), and a sidecar running under an older shell would hit it
    again.

    Only the `\\?\C:\` form is stripped. `\\?\UNC\...` is left alone, and so is
    anything past `MAX_PATH`, where the prefix is what makes the path work.
    """
    path = Path(value).expanduser()
    text = str(path)
    if text.startswith("\\\\?\\") and not text.startswith("\\\\?\\UNC"):
        rest = text[4:]
        if len(rest) < 260:
            return Path(rest)
    return path


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
        return _plain(override), "override"

    bundled = os.environ.get(BUNDLED_ENV)
    if bundled and bundled.strip():
        return _plain(bundled), "bundled"

    # sidecar/ephymeris_sidecar/discovery.py -> <repo>/sketches
    repo = Path(__file__).resolve().parent.parent.parent / "sketches"
    if repo.is_dir():
        return repo, "bundled"
    return None, "bundled"


def _apply_pinned(
    root: Path | None,
    sketches: list[Sketch],
    skipped: list[SkippedEntry],
) -> None:
    """Serve this rig's rebuild of a bundled sketch instead of the bundled one.

    Matched on (category, name), which is what a rebuild preserves. A folder
    here that matches nothing in the bundle is REPORTED rather than offered: it
    is a leftover from a sketch an app update removed, and flashing it would run
    firmware this build does not contain.

    Keeps `source: "bundled"` — see this module's header. A rebuild is the same
    sketch, so nothing downstream should have to know which copy it got.
    """
    if root is None or not Path(root).is_dir():
        return
    by_key = {(s.category, s.name): i for i, s in enumerate(sketches)}
    for folder in sorted(Path(root).glob("*/*")):
        if not folder.is_dir() or not _is_valid_sketch(folder):
            continue
        index = by_key.get((folder.parent.name, folder.name))
        if index is None:
            skipped.append(
                SkippedEntry(
                    str(folder),
                    "a rebuilt copy of a sketch this version no longer ships",
                )
            )
            continue
        sketches[index] = Sketch(
            folder.parent.name, folder.name, str(folder), "bundled"
        )


def _scan_generated(
    root: Path | None,
    bundled_names: set[str],
    sketches: list[Sketch],
    skipped: list[SkippedEntry],
    visited: set[Path],
) -> None:
    """Add this rig's generated task sketches, without letting one shadow a bundled one.

    A generated folder that collides with a bundled name is REPORTED rather than
    dropped or preferred. Dropping it silently would leave an operator flashing a
    sketch they did not author while the picker showed the name they did; and
    preferring it would let a saved profile override something that ships.
    """
    if root is None or not Path(root).is_dir():
        return
    for entry in sorted(Path(root).iterdir(), key=lambda p: p.name.lower()):
        # `<data_dir>/tasks/` holds one `<id>.json` per definition alongside the
        # category folders. Only directories are categories.
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        before = len(sketches)
        _scan(entry, 1, sketches, skipped, visited, "rig")
        for sketch in sketches[before:]:
            if sketch.name in bundled_names:
                skipped.append(
                    SkippedEntry(
                        sketch.path,
                        f"a bundled sketch is already called {sketch.name!r}; "
                        "rename the task profile",
                    )
                )
        sketches[before:] = [s for s in sketches[before:] if s.name not in bundled_names]


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
    """The folder-name-matches-`.ino` rule (`TASKS.md#folder-rules`)."""
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
    source: SketchSource = "bundled",
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
            sketches.append(
                Sketch(folder.name, child.name, str(child), source)
            )
            # Don't descend into a sketch: `src/`, `extras/` and the like are
            # its own business, not more categories.
            continue

        if _contains_ino(child):
            skipped.append(
                SkippedEntry(str(child), f"no {child.name}.ino matching the folder name")
            )
            continue

        if depth < MAX_SCAN_DEPTH:
            _scan(child, depth + 1, sketches, skipped, visited, source)


def discover(
    generated_root: Path | None = None,
    pinned_root: Path | None = None,
) -> SketchDiscovery:
    """Scan the bundle, apply this rig's rebuilds, then add its task profiles.

    Both roots are passed in rather than resolved here, so this module never
    learns about the data dir — the same discipline the rig wiring keeps. Absent,
    or missing on disk, simply means a fresh install: no rebuilds yet and no
    profiles yet, and the bundle alone is a working library.

    ORDER IS THE WHOLE ALGORITHM. The bundle is scanned first; `pinned_root`
    REPLACES entries it was built from, because a rebuild is the same sketch
    with this rig's pins; `generated_root` APPENDS, and a name colliding with a
    bundled one is reported and dropped rather than silently winning. Saving a
    profile refuses that collision up front, so this is the second line.
    """
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

        # A sketch sitting at the root has no category to belong to; sketches
        # belong inside a category folder (`TASKS.md#folder-rules`). Report rather than ignore.
        if _is_valid_sketch(entry):
            skipped.append(
                SkippedEntry(str(entry), "sketch folders belong inside a category folder")
            )
            continue

        _scan(entry, 1, sketches, skipped, visited)

    _apply_pinned(pinned_root, sketches, skipped)
    bundled_names = {s.name for s in sketches}
    _scan_generated(generated_root, bundled_names, sketches, skipped, visited)

    # A readable library holding nothing valid is its own state. It used to mean
    # "you pointed at the wrong folder"; now it can only mean a partial install,
    # so it reads as one. A rig profile does not rescue it: a build with no
    # bundled sketches has no root sketch to generate FROM.
    if not any(s.source == "bundled" for s in sketches):
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

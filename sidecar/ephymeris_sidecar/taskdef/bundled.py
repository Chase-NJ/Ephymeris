"""Rig-pinned copies of the bundled sketches.

A task profile is generated against this rig's wiring, so it drives the right
pins by construction. The sketches that SHIP were not: they compiled against
`BoxPins.h`'s defaults, which are the box as built. On a rig that has edited its
wiring that is silently wrong — `utility.identify` lights whatever is on the old
trial-light pin, and the simulator opens whatever is on the old odor line. The
sketch still compiles and the strobe stream still reads perfectly.

So the app rebuilds them. For every bundled sketch that asks for one, a copy
lands under

    <data_dir>/rig/sketches/<category>/<name>/

with a generated `TaskPins.h` — this rig's pins and this machine's strobe
vocabulary — and `discovery` serves that copy IN PLACE OF the bundled original.
It is the same sketch — same source, same name, same category — compiled against
the pins and codes this rig actually has, so nothing downstream learns a new
state.

**A sketch opts in by including the header.** `#include "TaskPins.h"` in its
`.ino` is the whole signal: a sketch that includes it is saying "override my
pins from the rig", and one that does not keeps the shipped numbers. Deriving
the opt-in from the source rather than from a manifest means there is no second
declaration to fall out of sync — and it is greppable.

**It degrades rather than disappearing.** If a copy cannot be written — a full
disk, a locked directory — the bundled entry stands and is offered as it ships.
That original FAILS TO COMPILE, loudly: `BoxStrobes.h` defines no codes and
`#error`s without this header's vocabulary block
(`TASKS.md#strobe-vocabulary`). That is the intended trade — a flash refused with
a reason beats firmware strobing numbers the machine decodes differently.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from ..rig import registry
from . import utility
from .generate import bundled_pins_h

log = logging.getLogger(__name__)

#: The file a sketch includes to declare that it wants this rig's pins.
PINS_HEADER = "TaskPins.h"


def wants_pinning(sketch_dir: Path) -> bool:
    """Whether this sketch asks to be built against the rig's wiring.

    Read from the `.ino` itself. A manifest key would be a second place to
    declare the same thing, and the failure mode of the two disagreeing is a
    sketch that includes the header, gets the shipped copy that declares
    nothing, and quietly runs the wrong pins.
    """
    ino = Path(sketch_dir) / f"{Path(sketch_dir).name}.ino"
    try:
        return f'#include "{PINS_HEADER}"' in ino.read_text(encoding="utf-8")
    except OSError:
        return False


def repin(sketch_dir: Path, category: str, root: Path) -> Path | None:
    """Copy one bundled sketch and give it this rig's pins.

    THE FOLDER IS REPLACED, NOT PATCHED. It is a build output: whatever was
    there described the wiring at some earlier moment, and merging the two would
    leave a header that is half of each.

    THE SOURCE MUST BE THE BUNDLE. Rebuilding from a previous rebuild is refused
    rather than allowed to proceed: `target` is cleared before the copy, so a
    source inside `root` is deleted and then copied from nothing. It cost every
    rebuilt sketch on the first rewiring, and it was invisible — discovery just
    fell back to the bundle and the rig ran the shipped pins.
    """
    source = Path(sketch_dir).resolve()
    root = Path(root).resolve()
    target = root / category / source.name
    if root == source or root in source.parents:
        log.error(
            "refusing to rebuild %s from %s: that is already a rebuild, and the "
            "source must be the bundled sketch",
            source.name,
            source,
        )
        return None
    try:
        shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        # `dirs_exist_ok` is not enough on its own -- `extras/` and friends
        # belong to the sketch and must come along, or a host-test folder simply
        # vanishes from the rebuilt copy.
        shutil.copytree(source, target, dirs_exist_ok=True)
        (target / PINS_HEADER).write_text(
            bundled_pins_h(source.name), encoding="utf-8"
        )
        if utility.wants_utility(target):
            # The box utility gets the rest of the box too: its channel table
            # and the Debug Mode half of its profile (`taskdef/utility.py`).
            (target / utility.UTILITY_HEADER).write_text(
                utility.utility_channels_h(source.name), encoding="utf-8"
            )
            profile_path = target / "task.json"
            template = json.loads(profile_path.read_text(encoding="utf-8"))
            profile_path.write_text(
                json.dumps(utility.utility_profile(template), indent=2) + "\n",
                encoding="utf-8",
            )
        return target
    except (OSError, ValueError) as exc:
        log.warning("could not rebuild %s against this rig's wiring (%s)", source.name, exc)
        shutil.rmtree(target, ignore_errors=True)
        return None


def repin_all(root: Path) -> int:
    """Rebuild every opted-in bundled sketch. Returns how many landed.

    IT SCANS THE BUNDLE ITSELF rather than taking a sketch list, and that is not
    a convenience. The caller's nearest list is `Application.discovery`, whose
    entries point at the PREVIOUS rebuild once one exists — feeding those back
    in makes every source its own target, and `repin` clears the target first.
    Taking no list is what makes that unrepresentable.
    """
    from .. import discovery as _discovery

    root = Path(root).resolve()
    # A bundle-only scan: no pinned root, no generated root. This is the one
    # place the un-replaced entries are available.
    sketches = _discovery.discover().sketches
    kept: set[Path] = set()
    count = 0
    for sketch in sketches:
        if sketch.source != "bundled" or not wants_pinning(Path(sketch.path)):
            continue
        landed = repin(Path(sketch.path), sketch.category, root)
        if landed is not None:
            kept.add(landed)
            count += 1

    # Sweep folders no bundled sketch claims any more -- a sketch renamed or
    # dropped by an app update would otherwise stay discoverable forever, and it
    # would be served IN PLACE OF nothing at all.
    if root.is_dir():
        for existing in root.glob("*/*"):
            # `kept` holds resolved paths (repin resolves); compare like with
            # like or the sweep deletes everything it just wrote.
            if existing.is_dir() and existing.resolve() not in kept:
                shutil.rmtree(existing, ignore_errors=True)
        for category in root.iterdir():
            try:
                if category.is_dir() and not any(category.iterdir()):
                    category.rmdir()
            except OSError:
                pass
    return count


def stamp() -> str:
    """The wiring and strobe vocabulary the copies were last built against."""
    return f"{registry.channels().content_hash()}+{registry.vocabulary().content_hash()}"

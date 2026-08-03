"""Generated artifacts: one definition, several consumers.

`--check` produces nothing and exits 1 if what is on disk differs -- the same
discipline Ephymeris' protocol/generate.py uses, adopted for the same reason: its
hand-maintained mirrors had already drifted before it moved to codegen.

Never writes into ../Arduino or ../Ephymeris. Those repos are read-only references
through Phase 6; anything they will eventually need goes to build/ and is picked up
by a contract test when the time comes.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TG_LIB = ROOT / "Arduino" / "libraries" / "TaskInterpreter"


def outputs() -> dict[Path, str]:
    """Every generated file, keyed by destination.

    Imported here rather than at module scope to keep this package a façade.
    `emit.pack` reads the record layout from `codegen.layout`, so a top-level
    import of `codegen.wire` -- which reads the wire constants back out of
    `emit.pack` -- makes `import taskgraph.codegen.layout` cycle through a
    half-initialised `emit.pack`. It failed by import ORDER, which meant the test
    suite passed and the CLI did not.
    """
    from taskgraph.codegen.indices import outputs as indices_outputs
    from taskgraph.codegen.layout import emit_header as emit_layout
    from taskgraph.codegen.limits import emit_header as emit_limits
    from taskgraph.codegen.strobes import emit_header as emit_strobes
    from taskgraph.codegen.wire import emit_header as emit_wire

    return {
        TG_LIB / "TaskLimits.h": emit_limits(),
        TG_LIB / "TgLayoutAssert.h": emit_layout(),
        TG_LIB / "TgStrobes.h": emit_strobes(),
        TG_LIB / "TgWire.h": emit_wire(),
        **indices_outputs(ROOT / "Arduino"),
    }


def generate_all(check: bool = False) -> int:
    stale: list[Path] = []
    for path, wanted in outputs().items():
        current = path.read_text() if path.exists() else None
        if current == wanted:
            continue
        if check:
            stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(wanted)
            print(f"wrote {path.relative_to(ROOT)}")

    if check:
        if stale:
            names = ", ".join(str(p.relative_to(ROOT)) for p in stale)
            print(f"stale generated file(s): {names}", file=sys.stderr)
            print("run `taskgraph codegen` and commit the result", file=sys.stderr)
            return 1
        print("generated files are current")
    return 0

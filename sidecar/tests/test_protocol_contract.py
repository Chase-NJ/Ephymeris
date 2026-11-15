"""Guards the generated protocol files against going stale.

`protocol/schema.py` is the single source of truth for the wire;
`ephymeris_sidecar/protocol.py`, `src/lib/ws/protocol.ts` and
`docs/PROTOCOL.md` are generated from it and committed. The check here
regenerates all three in a subprocess and fails if any committed file differs —
which catches a hand-edited output and a schema change committed without
regeneration alike.

Because the reference is generated, a name cannot be missing from it; what can
be missing is a description. Every command, event and error code must carry
one, so nothing exists on the wire that the reference cannot explain.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "protocol" / "generate.py"

sys.path.insert(0, str(REPO_ROOT / "protocol"))
from schema import PROTOCOL  # noqa: E402


def test_generated_files_are_current() -> None:
    """Every committed generated file must match what the schema generates today."""
    proc = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"{proc.stderr.strip() or proc.stdout.strip()}"
    )


@pytest.mark.parametrize(
    "kind,name,doc",
    [pytest.param("command", c.name, c.doc, id=c.name) for c in PROTOCOL.commands]
    + [pytest.param("event", e.name, e.doc, id=e.name) for e in PROTOCOL.events]
    + [pytest.param("error", e.name, e.doc, id=e.name) for e in PROTOCOL.errors],
)
def test_every_name_is_described(kind: str, name: str, doc: str | None) -> None:
    assert doc and doc.strip(), f"{kind} `{name}` has no `doc=` in protocol/schema.py"

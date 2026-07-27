"""Guards the generated protocol mirrors against going stale.

`protocol/schema.py` is the machine-readable source of truth;
`ephymeris_sidecar/protocol.py` and `src/lib/ws/protocol.ts` are generated
from it and committed. The check here regenerates both in a subprocess and
fails if either committed file differs — which catches a hand-edited mirror
and a schema change committed without regeneration alike.

`docs/websocket-protocol.md` remains the prose authority, so every wire name
must still appear in it: nothing may exist only in code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ephymeris_sidecar.protocol import (
    ALL_COMMANDS,
    ALL_ERROR_CODES,
    ALL_EVENTS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "protocol" / "generate.py"
PROTOCOL_DOC = REPO_ROOT / "docs" / "websocket-protocol.md"


def test_generated_mirrors_are_current() -> None:
    """Both committed mirrors must match what the schema generates today."""
    proc = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"{proc.stderr.strip() or proc.stdout.strip()}"
    )


@pytest.mark.parametrize("name", sorted(ALL_COMMANDS | ALL_EVENTS | ALL_ERROR_CODES))
def test_every_name_appears_in_the_spec(name: str) -> None:
    """The doc is the prose authority, so nothing may exist only in code."""
    assert PROTOCOL_DOC.exists(), f"protocol spec is missing: {PROTOCOL_DOC}"
    assert name in PROTOCOL_DOC.read_text(encoding="utf-8"), (
        f"`{name}` is implemented but undocumented in {PROTOCOL_DOC.name}"
    )

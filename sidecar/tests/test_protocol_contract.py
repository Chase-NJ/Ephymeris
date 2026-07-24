"""Guards the hand-maintained protocol mirrors against drift.

`docs/websocket-protocol.md` is the source of truth, but nothing mechanically
enforces it. What *can* be enforced is that the Python and TypeScript mirrors
agree, which is where drift would actually bite: a command renamed on one side
and not the other fails at runtime, in the app, on a lab machine.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ephymeris_sidecar.protocol import (
    ALL_COMMANDS,
    ALL_ERROR_CODES,
    ALL_EVENTS,
    PROTOCOL_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_TS = REPO_ROOT / "src" / "lib" / "ws" / "protocol.ts"
PROTOCOL_DOC = REPO_ROOT / "docs" / "websocket-protocol.md"


def _ts_source() -> str:
    if not PROTOCOL_TS.exists():
        pytest.fail(f"TypeScript protocol mirror is missing: {PROTOCOL_TS}")
    return PROTOCOL_TS.read_text(encoding="utf-8")


def _ts_const_block(source: str, name: str) -> str:
    """Extract the body of `export const <name> = { ... } as const;`."""
    match = re.search(
        rf"export const {name}\s*=\s*\{{(.*?)\}}\s*as const;",
        source,
        re.DOTALL,
    )
    if match is None:
        pytest.fail(f"could not find `export const {name}` in {PROTOCOL_TS.name}")
    return match.group(1)


def _ts_string_values(source: str, name: str) -> set[str]:
    return set(re.findall(r'"([^"]+)"', _ts_const_block(source, name)))


def test_command_names_match() -> None:
    assert _ts_string_values(_ts_source(), "CMD") == set(ALL_COMMANDS)


def test_event_names_match() -> None:
    assert _ts_string_values(_ts_source(), "EVT") == set(ALL_EVENTS)


def test_error_codes_match() -> None:
    assert _ts_string_values(_ts_source(), "ERR") == set(ALL_ERROR_CODES)


def test_protocol_version_matches() -> None:
    match = re.search(r"export const PROTOCOL_VERSION\s*=\s*(\d+)", _ts_source())
    assert match is not None, "PROTOCOL_VERSION missing from the TypeScript mirror"
    assert int(match.group(1)) == PROTOCOL_VERSION


@pytest.mark.parametrize("name", sorted(ALL_COMMANDS | ALL_EVENTS | ALL_ERROR_CODES))
def test_every_name_appears_in_the_spec(name: str) -> None:
    """The doc is the source of truth, so nothing may exist only in code."""
    assert PROTOCOL_DOC.exists(), f"protocol spec is missing: {PROTOCOL_DOC}"
    assert name in PROTOCOL_DOC.read_text(encoding="utf-8"), (
        f"`{name}` is implemented but undocumented in {PROTOCOL_DOC.name}"
    )

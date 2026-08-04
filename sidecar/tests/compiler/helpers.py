"""Shared test scaffolding.

`base_document()` returns a fresh, valid spec dict -- the same one the broken-spec
battery patches. Tests that need a spec with one thing wrong mutate the copy;
returning a fresh parse each call means a test cannot leak state into the next one.
"""

from __future__ import annotations

from pathlib import Path

import yaml

TESTS = Path(__file__).resolve().parent
BASE = TESTS / "broken" / "_base.yaml"


def base_document() -> dict:
    """A fresh, valid spec document. Mutate freely."""
    return yaml.safe_load(BASE.read_text())

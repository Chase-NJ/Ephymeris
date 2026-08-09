"""Every path this package resolves, in one place.

All of it is RUNTIME DATA -- `schema/` and `hardware/` live inside the package,
resolve relative to this file, and are present in every install: editable,
wheel, or PyInstaller freeze. Nothing that reads a channel or a strobe code can
work without them.

The repo-only half of the module this was extracted from (`firmware/`, test
fixtures, reached by walking up for a marker file) went with the code generators
that needed it. If something here ever needs a repo path again, walk up for
`sidecar/pyproject.toml` and raise a named error rather than returning a
plausible wrong answer -- counting `..` segments is what broke the last one.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

SCHEMA_DIR = PACKAGE_DIR / "schema"
HARDWARE_DIR = PACKAGE_DIR / "hardware"

RIG_SCHEMA = SCHEMA_DIR / "rig_hardware.v1.json"
CHANNELS_REGISTRY = SCHEMA_DIR / "channels.v1.json"
STROBE_VOCAB = SCHEMA_DIR / "strobe_vocab.v1.json"

"""Where specs live, and the cheap enumeration `specs.list` is built from.

This increment the library is the bundled specs alone — read-only, shipped
inside the vendor tree, one copy shared with the compiler's own goldens. User
specs land in a later increment under the app data dir; `origin` is already on
the wire so the list's shape doesn't move when they do.

Enumeration PARSES but never COMPILES. A list row needs `meta.label` and the
template name, which `yaml.safe_load` yields in microseconds; compiling all of
them would cost tens of milliseconds per spec and rise with every spec added,
on a call that runs at route mount. A document that will not even parse still
gets a row — with nulls — because a spec that has broken is exactly the one
someone needs to find in the list.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import compiler

log = logging.getLogger(__name__)

# NOTE: `yaml` is imported inside functions, never at module scope. This module
# is imported by app.py unconditionally, and pyyaml is one of the two
# dependencies the README §6.4 fence allows to be MISSING — a failed wheel must
# disable the spec editor, not take the sidecar down with it. Every function
# here runs behind compiler.available()/self_check(), which is the guard.

#: Refuse documents past this size before parsing anything. The largest shipped
#: spec is ~9 KB; a megabyte of YAML is not a task spec, and both safe_load and
#: the schema validator are recursive enough to make one expensive.
MAX_SPEC_BYTES = 256 * 1024


@dataclass(frozen=True)
class SpecRecord:
    spec_id: str
    origin: str  # "shipped" | "shipped_edited" | "user"
    path: Path

    def read_text(self) -> str:
        return self.path.read_text(encoding="utf-8")


def records() -> list[SpecRecord]:
    """Every spec in the library, sorted by id. Bundled-only for now."""
    out = [
        SpecRecord(spec_id=path.stem, origin="shipped", path=path)
        for path in sorted(compiler.bundled_specs_dir().glob("*.yaml"))
    ]
    return out


def get(spec_id: str) -> SpecRecord | None:
    return next((r for r in records() if r.spec_id == spec_id), None)


def parse_document(text: str) -> dict[str, Any] | None:
    """`yaml.safe_load`, returning None for anything that isn't a mapping."""
    import yaml

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return raw if isinstance(raw, dict) else None


def entry_for(record: SpecRecord) -> dict[str, Any]:
    """One `SpecEntry` row, from a parse and nothing more."""
    label: str | None = None
    description: str | None = None
    template: str | None = None
    template_version: int | None = None
    try:
        raw = parse_document(record.read_text())
    except OSError:
        raw = None
    if isinstance(raw, dict):
        meta = raw.get("meta")
        if isinstance(meta, dict):
            label = meta.get("label") if isinstance(meta.get("label"), str) else None
            description = (
                meta.get("description") if isinstance(meta.get("description"), str) else None
            )
        topology = raw.get("topology")
        if isinstance(topology, dict):
            template = (
                topology.get("template") if isinstance(topology.get("template"), str) else None
            )
            version = topology.get("template_version")
            template_version = version if isinstance(version, int) else None

    return {
        "specId": record.spec_id,
        "label": label,
        "description": description,
        "origin": record.origin,
        "template": template,
        "templateVersion": template_version,
    }


def list_entries() -> list[dict[str, Any]]:
    return [entry_for(record) for record in records()]

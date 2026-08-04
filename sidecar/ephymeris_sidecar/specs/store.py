"""Where specs live: one directory, all of it the operator's.

Layout, under the sidecar's own data dir (the same place `ephymeris.db` lives —
these are sidecar-side writes, and no Tauri fs capability is involved):

    <data_dir>/specs/
      user/<spec_id>.yaml   every task on this rig
      index.json            {spec_id: {editedAt}}

NOTHING SHIPS AS A SPEC. A task is generated from a paradigm and then belongs to
the rig that made it, so there is no bundled library underneath, no shadowing,
no baseline to restore and nothing an app update can move under an edit. That
retires a real amount of machinery — shipped/shipped_edited origins, the
baseline directory, upstreamChanged, Keep-mine-versus-Reset — which existed to
answer a question that no longer has a subject.

What replaces it is not weaker. A spec's provenance used to be "which bundled
file did this start as"; it is now `paradigmId`, computed from the document's
own shape, so a task that was reshaped in the Designer stops claiming to be what
it started as. That was never true of the old origins.

Enumeration PARSES but never COMPILES. A list row needs `meta.label` and the
template name, which `yaml.safe_load` yields in microseconds; compiling would
cost tens of milliseconds per spec and rise with every spec added, on a call
that runs at route mount. A document that will not even parse still gets a row
— with nulls — because a spec that has broken is exactly the one someone needs
to find in the list.

NOTE: `yaml` is imported inside functions, never at module scope. This module
is imported by app.py unconditionally, and pyyaml is one of the two
dependencies the README §6.4 fence allows to be MISSING — a failed wheel must
disable the spec editor, not take the sidecar down with it. Every method here
runs behind compiler.available()/self_check(), which is the guard.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from . import compiler

log = logging.getLogger(__name__)

#: Refuse documents past this size before parsing anything. The largest shipped
#: spec is ~9 KB; a megabyte of YAML is not a task spec, and both safe_load and
#: the schema validator are recursive enough to make one expensive.
MAX_SPEC_BYTES = 256 * 1024

#: The schema's own spec_id rule, enforced here as well because the id is used
#: as a FILENAME — `../../evil` must die at the door, not in a path join.
SPEC_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

Origin = Literal["shipped", "shipped_edited", "user"]


class SpecIdInvalid(ValueError):
    pass


@dataclass(frozen=True)
class SpecRecord:
    spec_id: str
    origin: Origin
    path: Path

    def read_text(self) -> str:
        return self.path.read_text(encoding="utf-8")


def parse_document(text: str) -> dict[str, Any] | None:
    """`yaml.safe_load`, returning None for anything that isn't a mapping."""
    import yaml

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return raw if isinstance(raw, dict) else None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class SpecStore:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "specs"
        self.user_dir = self.root / "user"
        self.index_path = self.root / "index.json"

    # --- index --------------------------------------------------------------

    def _index(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write_index(self, index: dict[str, dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # --- enumeration --------------------------------------------------------

    def _user(self) -> dict[str, Path]:
        if not self.user_dir.is_dir():
            return {}
        return {p.stem: p for p in sorted(self.user_dir.glob("*.yaml"))}

    def records(self) -> list[SpecRecord]:
        """Every spec on this rig, sorted by id."""
        return [SpecRecord(sid, "user", path) for sid, path in self._user().items()]

    def get(self, spec_id: str) -> SpecRecord | None:
        return next((r for r in self.records() if r.spec_id == spec_id), None)

    def entry_for(self, record: SpecRecord) -> dict[str, Any]:
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
                    topology.get("template")
                    if isinstance(topology.get("template"), str)
                    else None
                )
                version = topology.get("template_version")
                template_version = version if isinstance(version, int) else None

        # Which paradigm's SHAPE this document has, computed from the document
        # rather than recorded in it -- so a task reshaped in the Designer stops
        # claiming to be what it started as. Null reads honestly as "Custom".
        paradigm_id: str | None = None
        if isinstance(raw, dict):
            try:
                from ephymeris_sidecar.taskgraph import paradigms

                paradigm_id = paradigms.fingerprint(raw)
            except Exception:
                paradigm_id = None

        index_entry = self._index().get(record.spec_id, {})
        return {
            "specId": record.spec_id,
            "label": label,
            "description": description,
            "origin": record.origin,
            "template": template,
            "templateVersion": template_version,
            "paradigmId": paradigm_id,
            "editedAt": index_entry.get("editedAt"),
        }

    def list_entries(self) -> list[dict[str, Any]]:
        return [self.entry_for(record) for record in self.records()]

    # --- writes -------------------------------------------------------------

    def save(self, spec_id: str, text: str) -> SpecRecord:
        """Write the spec. There is nothing underneath it to preserve."""
        if not SPEC_ID_RE.match(spec_id):
            raise SpecIdInvalid(
                f"{spec_id!r} is not a valid spec id — lowercase letters, digits "
                "and underscores, starting with a letter, at most 40 characters."
            )
        self.user_dir.mkdir(parents=True, exist_ok=True)
        (self.user_dir / f"{spec_id}.yaml").write_text(text, encoding="utf-8")
        index = self._index()
        index.setdefault(spec_id, {})["editedAt"] = _now()
        self._write_index(index)

        record = self.get(spec_id)
        assert record is not None
        return record

    def delete(self, spec_id: str) -> None:
        """Delete the spec.

        One meaning now, where there used to be three. Every spec belongs to the
        rig that made it, so there is no bundled version underneath to fall back
        to and nothing that can be read-only.
        """
        if self.get(spec_id) is None:
            return
        (self.user_dir / f"{spec_id}.yaml").unlink(missing_ok=True)
        index = self._index()
        index.pop(spec_id, None)
        self._write_index(index)

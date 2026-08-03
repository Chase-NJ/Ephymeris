"""Where specs live: the bundled library, and the user's copies over it.

Layout, under the sidecar's own data dir (the same place `ephymeris.db` lives —
these are sidecar-side writes, and no Tauri fs capability is involved):

    <data_dir>/specs/
      user/<spec_id>.yaml              user-created and user-edited
      shipped-baseline/<spec_id>.yaml  the shipped bytes as of the user's first
                                       edit — what Reset to shipped restores,
                                       and what upstreamChanged compares against
      index.json                       {spec_id: {baselineSha, editedAt}}

THERE IS NO SEEDING. Unlike the arduino-cli data dir, nothing is copied on
first use: the compiler only reads, so a read-only bundled spec is served
as-is, and a bundled spec that ships changed simply IS changed for anyone who
hasn't edited it. A user file with a bundled spec's id SHADOWS it.

AND THERE IS NO MERGING. When an app update changes a bundled spec underneath
a user's edit, the entry gets `upstreamChanged: true` and the user chooses:
Keep mine (re-baseline) or Reset to shipped (delete the copy). A wrong
automatic merge of two YAML task definitions is an experiment nobody designed;
a badge is annoying, which is the correct price.

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

import hashlib
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


class SpecReadOnly(RuntimeError):
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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class SpecStore:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "specs"
        self.user_dir = self.root / "user"
        self.baseline_dir = self.root / "shipped-baseline"
        self.index_path = self.root / "index.json"

    # --- index --------------------------------------------------------------

    def _index(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.index_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write_index(self, index: dict[str, dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")

    # --- enumeration --------------------------------------------------------

    def _bundled(self) -> dict[str, Path]:
        return {p.stem: p for p in sorted(compiler.bundled_specs_dir().glob("*.yaml"))}

    def _user(self) -> dict[str, Path]:
        if not self.user_dir.is_dir():
            return {}
        return {p.stem: p for p in sorted(self.user_dir.glob("*.yaml"))}

    def records(self) -> list[SpecRecord]:
        """Every spec, sorted by id. A user file shadows a bundled id."""
        bundled = self._bundled()
        user = self._user()
        out: list[SpecRecord] = []
        for spec_id in sorted(bundled.keys() | user.keys()):
            if spec_id in user:
                origin: Origin = "shipped_edited" if spec_id in bundled else "user"
                out.append(SpecRecord(spec_id, origin, user[spec_id]))
            else:
                out.append(SpecRecord(spec_id, "shipped", bundled[spec_id]))
        return out

    def get(self, spec_id: str) -> SpecRecord | None:
        return next((r for r in self.records() if r.spec_id == spec_id), None)

    def bundled_text(self, spec_id: str) -> str | None:
        """The CURRENT shipped bytes, whether or not a user copy shadows them."""
        path = self._bundled().get(spec_id)
        if path is None:
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def upstream_changed(self, spec_id: str) -> bool:
        """The bundled bytes moved since this shadow's baseline was taken.

        False for anything that isn't a shadow — a pure user spec has no
        upstream, and an unedited shipped spec that changed simply IS the new
        version, which is the whole argument for not seeding.
        """
        entry = self._index().get(spec_id)
        if entry is None or "baselineSha" not in entry:
            return False
        bundled = self._bundled().get(spec_id)
        if bundled is None:
            return False
        try:
            return _sha256(bundled.read_bytes()) != entry["baselineSha"]
        except OSError:
            return False

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

        index_entry = self._index().get(record.spec_id, {})
        return {
            "specId": record.spec_id,
            "label": label,
            "description": description,
            "origin": record.origin,
            "template": template,
            "templateVersion": template_version,
            "upstreamChanged": self.upstream_changed(record.spec_id),
            "editedAt": index_entry.get("editedAt"),
        }

    def list_entries(self) -> list[dict[str, Any]]:
        return [self.entry_for(record) for record in self.records()]

    # --- writes -------------------------------------------------------------

    def save(self, spec_id: str, text: str) -> SpecRecord:
        """Write a user copy, baselining the shipped bytes on a first shadow.

        The baseline is copied BEFORE the user file exists, so there is no
        ordering in which an edit exists without the means to undo it — and
        because the shipped file itself is never modified, Reset restores it
        byte-for-byte, comments and all.
        """
        if not SPEC_ID_RE.match(spec_id):
            raise SpecIdInvalid(
                f"{spec_id!r} is not a valid spec id — lowercase letters, digits "
                "and underscores, starting with a letter, at most 40 characters."
            )

        bundled = self._bundled().get(spec_id)
        first_shadow = bundled is not None and spec_id not in self._user()

        index = self._index()
        if first_shadow:
            assert bundled is not None
            shipped_bytes = bundled.read_bytes()
            self.baseline_dir.mkdir(parents=True, exist_ok=True)
            (self.baseline_dir / f"{spec_id}.yaml").write_bytes(shipped_bytes)
            index.setdefault(spec_id, {})["baselineSha"] = _sha256(shipped_bytes)

        self.user_dir.mkdir(parents=True, exist_ok=True)
        (self.user_dir / f"{spec_id}.yaml").write_text(text, encoding="utf-8")
        index.setdefault(spec_id, {})["editedAt"] = _now()
        self._write_index(index)

        record = self.get(spec_id)
        assert record is not None
        return record

    def delete(self, spec_id: str) -> SpecRecord | None:
        """User spec: gone. Shadow: reset to shipped. Shipped: refused."""
        record = self.get(spec_id)
        if record is None:
            return None
        if record.origin == "shipped":
            raise SpecReadOnly(
                f"{spec_id} is a shipped spec — the bundled file is part of the "
                "install. Editing it creates your own copy; there is nothing to "
                "delete until then."
            )
        (self.user_dir / f"{spec_id}.yaml").unlink(missing_ok=True)
        (self.baseline_dir / f"{spec_id}.yaml").unlink(missing_ok=True)
        index = self._index()
        index.pop(spec_id, None)
        self._write_index(index)
        return self.get(spec_id)  # the shipped record, or None for a user spec

    def acknowledge_upstream(self, spec_id: str) -> SpecRecord | None:
        """Keep mine: re-baseline against the CURRENT bundled bytes."""
        record = self.get(spec_id)
        bundled = self._bundled().get(spec_id)
        if record is None or bundled is None:
            return record
        shipped_bytes = bundled.read_bytes()
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        (self.baseline_dir / f"{spec_id}.yaml").write_bytes(shipped_bytes)
        index = self._index()
        index.setdefault(spec_id, {})["baselineSha"] = _sha256(shipped_bytes)
        self._write_index(index)
        return self.get(spec_id)

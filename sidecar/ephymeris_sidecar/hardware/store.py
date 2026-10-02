"""The rig wiring document: one file, the operator's, validated on the way in.

Layout, under the sidecar's own data dir (beside `ephymeris.db` — these are
sidecar-side writes, no Tauri fs capability involved):

    <data_dir>/hardware/rig.json

ONE FILE, TWO SECTIONS, mirroring the shipped pair it overrides:

    {"rig_version": 1,
     "channels": {"<name>": {"kind", "label", "well?", "port_slot?", ...}},
     "pins":     {"<name>": {"index", "watch_bit?", "note?"}}}

Keeping the halves apart inside one document is deliberate. The split is what
lets a box generation be swapped without touching what a channel MEANS, and it
is what `ChannelMap.disagreements()` checks; collapsing them into one map would
make that rule unwritable. Writing them together is what makes it easy to satisfy.

A RIG DOCUMENT REPLACES THE SHIPPED PAIR, it does not merge with it. A merge
would mean an operator who deleted a channel got it back, and there would be no
way to express "this box does not have a vacuum line". `default_document()`
seeds a copy of the shipped pair so the first edit starts from something real
rather than from nothing.

THE SHIPPED FILES ARE NEVER WRITTEN. They live inside the package (`paths.py`
resolves them package-relative) and are read-only in a PyInstaller build, which
is exactly why the user document lives here instead.

NOTE `jsonschema` is imported inside the function that needs it, never at module
scope: it is the one sidecar dependency the `ARCHITECTURE.md#dependency-policy` fence allows to be
missing, and a failed wheel must disable the rig editor rather than take down the
process that owns six serial ports.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Refuse before parsing. The shipped pair is ~10 KB together; a megabyte of
#: JSON is not a pin map, and the schema validator is recursive enough to make
#: one expensive.
MAX_RIG_BYTES = 256 * 1024

RIG_FILENAME = "rig.json"


class RigInvalid(ValueError):
    """The document is not a rig document. Carries located diagnostics."""

    def __init__(self, problems: list[tuple[str, str]]) -> None:
        self.problems = problems
        super().__init__("; ".join(f"{loc}: {msg}" for loc, msg in problems[:3]))


@dataclass(frozen=True)
class RigStatus:
    """What the editor needs to know about where the wiring came from."""

    #: True when this rig has its own document; False when it is running the
    #: shipped pinout untouched.
    custom: bool
    #: The shipped pinout this rig derives from, named even when custom — a
    #: rig document is a copy of one, and saying which answers "a Mega, wired
    #: how?" without the operator having to remember.
    derived_from: str
    edited_at: str | None


class HardwareStore:
    """Reads and writes `<data_dir>/hardware/rig.json`.

    Owns the file and nothing else. Composing it into a `ChannelMap`, and
    invalidating the cached registries when it changes, is `rig/registry.py`'s
    job — this class must not reach for a composed map at import time, so that a
    broken rig document is a diagnostic rather than an import error.
    """

    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir) / "hardware"
        self.path = self.root / RIG_FILENAME

    # -- reading ----------------------------------------------------------- #

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> dict | None:
        """The rig document, or None when this rig has never been edited.

        A file that will not parse is reported as None with a logged warning
        rather than raised: the compiler falls back to the shipped pinout, which
        is a working rig, and the editor's own `hardware.get` reports the
        problem with a location. Refusing to start would be worse than running
        the wiring the box shipped with.
        """
        if not self.path.is_file():
            return None
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            log.warning("rig document unreadable (%s); using the shipped pinout", exc)
            return None
        if len(raw) > MAX_RIG_BYTES:
            log.warning(
                "rig document is %d bytes, over the %d limit; using the shipped pinout",
                len(raw),
                MAX_RIG_BYTES,
            )
            return None
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("rig document will not parse (%s); using the shipped pinout", exc)
            return None
        return doc if isinstance(doc, dict) else None

    def status(self) -> RigStatus:
        doc = self.load()
        return RigStatus(
            custom=doc is not None,
            derived_from=str((doc or {}).get("derived_from", "")),
            edited_at=(doc or {}).get("edited_at"),
        )

    # -- writing ----------------------------------------------------------- #

    def save(self, doc: dict) -> dict:
        """Validate, stamp and write. Returns the document as stored.

        Validation is the whole point of this method and it happens BEFORE the
        write, not after: a rig document that fails is not written at all, so
        there is no state in which the file on disk is one the compiler refuses.
        Every problem is reported, not just the first — fixing new wiring should
        be one pass rather than a game of whack-a-mole, which is the same
        argument `ChannelMap.disagreements()` makes.
        """
        problems = validate(doc)
        if problems:
            raise RigInvalid(problems)

        stored = dict(doc)
        stored["edited_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
        return stored

    def reset(self) -> None:
        """Back to the shipped pinout. The file goes; nothing else does."""
        self.path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def validate(doc: Any) -> list[tuple[str, str]]:
    """(location, message) for every way this is not a rig document.

    SCHEMA ONLY. Whether the wiring makes sense — pins in range, no duplicates,
    every response port on a distinct slot — belongs to the rules in
    `rig/registry.py`, and they run against the COMPOSED `ChannelMap` rather
    than against this file, so a problem is reported once no matter which half
    caused it. This function answers the narrower question the schema can: is
    this the right shape.
    """
    if not isinstance(doc, dict):
        return [("rig.json", "the rig document must be a JSON object")]

    try:
        import jsonschema
    except ImportError:  # pragma: no cover - the dependency fence
        return [(
            "rig.json",
            "jsonschema is not installed, so a rig document cannot be validated. "
            "The shipped pinout is still available.",
        )]

    from ephymeris_sidecar.rig.paths import RIG_SCHEMA

    schema = json.loads(RIG_SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    out: list[tuple[str, str]] = []
    for error in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
        out.append((_json_path(error.path), error.message))
    return out


def _json_path(path) -> str:
    """`channels.left_well.kind`, not `channels/left_well/kind`.

    A violation should land on the field the operator is looking at rather than
    becoming a document-level banner.
    """
    parts = list(path)
    if not parts:
        return "rig.json"
    out = str(parts[0])
    for part in parts[1:]:
        out += f"[{part}]" if isinstance(part, int) else f".{part}"
    return out


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #


def default_document() -> dict:
    """A rig document equal to the shipped pinout, as a starting point.

    Read from the shipped files rather than written out here, so this cannot
    become a third description of the same box. The first thing the editor does
    with an unedited rig is show this; the first save writes it back with
    whatever the operator changed.

    READS THE SHIPPED PAIR DIRECTLY, never `registry.channels()`. That call
    returns the wiring currently IN FORCE, which is the rig's own once one
    exists — so "default" would have meant "whatever you last saved", and Reset
    would have reset to itself. It is also a recursion: `channels()` consults
    the rig source, and the rig source is what asks for a default.
    """
    from ephymeris_sidecar.rig import registry

    chans = registry.shipped_channels()
    # DECLARATION ORDER, not sorted. The order of `channels` is load-bearing:
    # `declared_of_kind()` reads it, and the firmware's `Odors[i]` is odor line
    # i+1. Sorting by pin here — which this did — quietly re-ordered the odor
    # table the moment a rig saved its first document, because the pins are not
    # monotonic past line 6 (22,24,26,28,30,32 then 23,25,27,29,31,33). The
    # generated sketch then drove the wrong valve and announced it with the
    # wrong onset code, and every trial still looked correct in the record.
    return {
        "rig_version": 1,
        "derived_from": chans.pinout_id,
        "board": chans.board,
        "pin_range": {"min": chans.pin_min, "max": chans.pin_max},
        "channels": {
            c.name: {
                "kind": c.kind,
                "label": c.name.replace("_", " "),
                **({"well": c.well} if c.well else {}),
                **({"port_slot": c.port_slot} if c.port_slot else {}),
                **({"rationale": c.rationale} if c.rationale else {}),
            }
            for c in chans
        },
        "pins": {
            c.name: {
                "index": c.index,
                **({"watch_bit": c.watch_bit} if c.watchable else {}),
                **({"note": c.pin_note} if c.pin_note else {}),
            }
            for c in chans
        },
    }

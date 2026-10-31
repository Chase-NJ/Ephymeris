"""The rig wiring document: the operator's, validated on the way in.

Layout, under the sidecar's own data dir (beside `ephymeris.db` — these are
sidecar-side writes, no Tauri fs capability involved):

    <data_dir>/hardware/channel_set.json   what each channel IS (lab-wide)
    <data_dir>/hardware/pin_map.json       where each one is on THIS box (local)

TWO FILES, mirroring the shipped pair they override
(TASKS.md#the-channel-set-and-the-pin-map):

    channel_set.json  {"channel_set_version": 1,
                       "channels": {"<name>": {"kind", "type", "role", "edges?", ...}}}
    pin_map.json      {"pin_map_version": 1, "derived_from", "board", "pin_range",
                       "pins": {"<name>": {"index", "watch_bit?", "note?"}}}

The channel set is the document both lab machines will share; the pin map
never leaves the machine. They are still EDITED as one document -- the wire's
`{rig_version, channels, pins}`, which `load` joins and `save` splits -- because
an operator adding a channel gives it a meaning and a pin in one gesture. Keeping
the halves apart is what lets a box generation be swapped without touching what
a channel MEANS, and it is what `ChannelMap.disagreements()` checks.

THE PAIR COMMITS OR FAILS AS ONE. Two files cannot be replaced atomically, and
a new channel set loaded against the old pins records every poke on a swapped
port under the wrong family with no error anywhere. So the pin map names the
channel set it was written beside (`channel_set_digest`), and a save:

  1. stages both files (`*.json.tmp`), complete;
  2. replaces the channel set;
  3. replaces the pin map -- and if that fails, puts the old channel set back.

A save stopped between 2 and 3 (a power cut, or a rollback that failed too)
leaves the staged pin map behind, and it is the commit record: `load` pairs
the new channel set with it. Any other pair whose digests disagree does not
load at all; `load_problems` says why and `hardware.get` shows it.

A RIG SAVED AS ONE FILE (`rig.json`, before the split) is read as both, and the
next save writes the pair and removes it.

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

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Refuse before parsing. The shipped pair is ~10 KB together; a megabyte of
#: JSON is not a pin map, and the schema validator is recursive enough to make
#: one expensive.
MAX_RIG_BYTES = 256 * 1024

#: The single document a rig was saved as before the channel set and the pin
#: map were split. Read when the pair is absent; removed by the next save.
RIG_FILENAME = "rig.json"
CHANNEL_SET_FILENAME = "channel_set.json"
PIN_MAP_FILENAME = "pin_map.json"

#: The keys of the joined document that belong to the pin map, beside `pins`.
_PIN_MAP_KEYS = ("derived_from", "board", "pin_range", "edited_at")


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
    """Reads and writes `<data_dir>/hardware/channel_set.json` and `pin_map.json`.

    Owns the files and nothing else. Composing it into a `ChannelMap`, and
    invalidating the cached registries when it changes, is `rig/registry.py`'s
    job — this class must not reach for a composed map at import time, so that a
    broken rig document is a diagnostic rather than an import error.
    """

    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir) / "hardware"
        #: The one-file document a rig saved before the split; see RIG_FILENAME.
        self.path = self.root / RIG_FILENAME
        self.channel_set_path = self.root / CHANNEL_SET_FILENAME
        self.pin_map_path = self.root / PIN_MAP_FILENAME

    # -- reading ----------------------------------------------------------- #

    def exists(self) -> bool:
        return any(p.is_file() for p in (self.channel_set_path, self.pin_map_path, self.path))

    def load(self) -> dict | None:
        """The rig document, or None when this rig has never been edited.

        A file that will not parse, or a pair that does not belong together, is
        reported as None with a logged warning rather than raised: the compiler
        falls back to the shipped pinout, which is a working rig, and the
        editor's own `hardware.get` reports the problem (`load_problems`).
        Refusing to start would be worse than running the wiring the box
        shipped with.
        """
        return self._load()[0]

    def load_problems(self) -> list[tuple[str, str]]:
        """(location, message) for why stored wiring exists and did not load."""
        return self._load()[1]

    def _load(self) -> tuple[dict | None, list[tuple[str, str]]]:
        if self.channel_set_path.is_file():
            channel_set = _read(self.channel_set_path)
            if channel_set is None:
                return None, [(CHANNEL_SET_FILENAME, "the channel set will not read; see the log")]
            digest = channel_set_digest(channel_set)
            pin_map = _read(self.pin_map_path) if self.pin_map_path.is_file() else None
            if pin_map is None or pin_map.get("channel_set_digest") != digest:
                # The save that wrote this channel set stopped before its pin
                # map landed. The staged one is that save's commit record.
                staged = _read(self._staged(self.pin_map_path), quiet=True)
                if staged is not None and staged.get("channel_set_digest") == digest:
                    pin_map = staged
            if pin_map is not None and pin_map.get("channel_set_digest") == digest:
                return upgrade(join(channel_set, pin_map)), []
            message = (
                f"{PIN_MAP_FILENAME} does not belong to {CHANNEL_SET_FILENAME}: they were "
                "not written by one save, so its pins could put a port under another "
                "port's codes. Running the shipped pinout until this rig's wiring is "
                "saved again."
            )
            log.error(message)
            return None, [(PIN_MAP_FILENAME, message)]
        if self.path.is_file():
            # Saved as one file before the split -- or the first save after it
            # stopped and rolled back, since the old file goes last.
            doc = _read(self.path)
            if doc is None:
                return None, [(RIG_FILENAME, "the rig document will not read; see the log")]
            return upgrade(doc), []
        if self.pin_map_path.is_file():
            message = f"{PIN_MAP_FILENAME} has no {CHANNEL_SET_FILENAME} beside it."
            log.warning("%s Using the shipped pinout.", message)
            return None, [(PIN_MAP_FILENAME, message)]
        return None, []

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
        channel_set, pin_map = split(stored)
        pin_map["channel_set_digest"] = channel_set_digest(channel_set)
        self.root.mkdir(parents=True, exist_ok=True)
        previous = self.channel_set_path.read_bytes() if self.channel_set_path.is_file() else None
        staged_set = _stage(self.channel_set_path, channel_set)
        staged_pins = _stage(self.pin_map_path, pin_map)
        os.replace(staged_set, self.channel_set_path)
        try:
            os.replace(staged_pins, self.pin_map_path)
        except OSError:
            try:
                self._restore(previous)
            except OSError as exc:
                # The staged pin map stays, and `load` completes this save
                # from it: the pair is the new one, whole, rather than torn.
                log.error("could not put the old channel set back (%s)", exc)
            raise
        # The old one-file document goes last, so a save that rolled back still
        # has a whole document to read.
        self.path.unlink(missing_ok=True)
        return stored

    def _restore(self, previous: bytes | None) -> None:
        """Undo step 2 of a save whose pin map did not land (module docstring)."""
        if previous is None:
            self.channel_set_path.unlink(missing_ok=True)
        else:
            staged = self._staged(self.channel_set_path)
            staged.write_bytes(previous)
            os.replace(staged, self.channel_set_path)
        self._staged(self.pin_map_path).unlink(missing_ok=True)

    @staticmethod
    def _staged(path: Path) -> Path:
        return path.with_suffix(".json.tmp")

    def reset(self) -> None:
        """Back to the shipped pinout. The files go; nothing else does."""
        for path in (
            self.channel_set_path,
            self.pin_map_path,
            self.path,
            self._staged(self.channel_set_path),
            self._staged(self.pin_map_path),
        ):
            path.unlink(missing_ok=True)


def channel_set_digest(channel_set: dict) -> str:
    """The channel set's exact content, as the pin map written beside it
    records it. Not `ChannelSet.content_hash()`: that leaves labels out on
    purpose, and pairing two files needs every byte."""
    canonical = json.dumps(channel_set, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def split(doc: dict) -> tuple[dict, dict]:
    """The joined wire document -> (channel set, pin map), as stored on disk."""
    channel_set = {
        "channel_set_version": 1,
        **({"edited_at": doc["edited_at"]} if "edited_at" in doc else {}),
        "channels": doc["channels"],
    }
    pin_map = {
        "pin_map_version": 1,
        **{k: doc[k] for k in _PIN_MAP_KEYS if k in doc},
        "pins": doc["pins"],
    }
    # `save` adds `channel_set_digest`; a split for export carries none.
    return channel_set, pin_map


def join(channel_set: dict, pin_map: dict) -> dict:
    """(channel set, pin map) -> the one document the editor and the wire see."""
    return {
        "rig_version": 1,
        **{k: pin_map[k] for k in _PIN_MAP_KEYS if k in pin_map},
        "channels": channel_set.get("channels"),
        "pins": pin_map.get("pins"),
    }


def _read(path: Path, *, quiet: bool = False) -> dict | None:
    """One stored file, or None with a logged warning: the compiler falls back
    to the shipped pinout and `hardware.get` reports why. `quiet` for a staged
    file, which is usually absent."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        if not quiet:
            log.warning("%s unreadable (%s); using the shipped pinout", path.name, exc)
        return None
    if len(raw) > MAX_RIG_BYTES:
        log.warning(
            "%s is %d bytes, over the %d limit; using the shipped pinout",
            path.name,
            len(raw),
            MAX_RIG_BYTES,
        )
        return None
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("%s will not parse (%s); using the shipped pinout", path.name, exc)
        return None
    return doc if isinstance(doc, dict) else None


def _stage(path: Path, doc: dict) -> Path:
    """Write `doc` complete beside `path`, for a rename to put in place: a
    reader composing the wiring mid-save (a worker thread's cache miss) never
    reads half a file."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return tmp


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


def upgrade(doc: dict) -> dict:
    """Fill what a rig saved before a field existed.

    The channel-set fields (`type`, `role`, an input's `active_level` and
    `debounce_ms`, a reward line's `serves`) come from the channel's own kind
    (`registry.channel_set_defaults`) -- never `edges`, which only a save
    allocates. And an odor line's `onset_strobe` (`TASKS.md#onset-codes`)
    comes from the shipped wiring. A rig saved before emitters declared their onset
    would otherwise report RIG106 on every line the moment it loaded. The fill
    is by CHANNEL NAME AND KIND against the shipped registry -- the same source
    `default_document()` copies -- so a line this rig added or renamed stays
    undeclared and RIG106 asks the operator, rather than anything guessing.

    In memory only; the operator's next save writes it.
    """
    channels = doc.get("channels")
    if not isinstance(channels, dict):
        return doc
    from ephymeris_sidecar.rig import registry

    shipped = registry.shipped_channels()
    filled: dict[str, Any] = {}
    for name, channel in channels.items():
        if not isinstance(channel, dict):
            continue
        defaults = registry.channel_set_defaults(channel)
        if defaults:
            channel = filled[name] = {**channel, **defaults}
        if channel.get("kind") != "emitter" or channel.get("onset_strobe"):
            continue
        source = shipped.get(name)
        if source is not None and source.kind == "emitter" and source.onset_strobe:
            filled[name] = {**channel, "onset_strobe": source.onset_strobe}
    if not filled:
        return doc
    return {**doc, "channels": {name: filled.get(name, c) for name, c in channels.items()}}


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
                **({"onset_strobe": c.onset_strobe} if c.onset_strobe else {}),
                **registry.channel_set_json(c),
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

"""The rig wiring: the operator's, validated on the way in.

Layout, under the sidecar's own data dir (beside `ephymeris.db` — these are
sidecar-side writes, no Tauri fs capability involved):

    <data_dir>/hardware/wiring.json

TWO DOCUMENTS, ONE FILE (TASKS.md#the-channel-set-and-the-pin-map). The channel
set (what each channel IS, lab-wide) and the pin map (where each one is on THIS
box) are separate documents in code -- `split` and `join` -- and the file holds
both, as the wire's `{rig_version, channels, pins, …}`:

    {"rig_version": 1, "derived_from", "board", "pin_range", "edited_at",
     "channels": {"<name>": {"kind", "type", "role", "edges?", ...}},   the channel set
     "pins":     {"<name>": {"index", "watch_bit?", "note?"}}}          the pin map

ONE FILE BECAUSE A SAVE MUST BE WHOLE OR ABSENT. A channel set and a pin map
written as two files can be torn by a failure between them, and a new channel
set read against old pins records every poke on a swapped port under the wrong
family with no error anywhere. One file written to `wiring.json.part`, fsync'd
and renamed over the old one (`_write_atomic`) cannot tear: a reader sees the
old wiring or the new, never a mix. Once the rename lands the save is
committed; the folder fsync after it is best effort, logged if it fails.

STORED WIRING THAT WILL NOT LOAD IS NEVER REPLACED BY THE SHIPPED ONE SILENTLY.
The registry composes the shipped pinout meanwhile, because the process owns six
serial ports and must start; but `load_problems` says why, `hardware.get` shows
it, and no box is started, flashed or identified until the wiring is saved
again, reset, or the app restarts onto a file that loads
(`RigDefinition.wiring_problem`, which follows the wiring IN FORCE).

TWO OLDER LAYOUTS ARE READ IN PLACE until the next save writes `wiring.json`
and removes them:

  * `rig.json` -- the same document under another name;
  * `channel_set.json` + `pin_map.json` -- the two documents in two files, the
    pin map naming its channel set by `channel_set_digest`. A pair whose digests
    disagree is a load problem, never a guess.

`wiring.json` wins over both, so a save stopped before its cleanup still has
its wiring in force. A stray temporary file (`*.part`, `*.json.tmp`) on its own
is no wiring at all.

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

WIRING_FILENAME = "wiring.json"
#: Older layouts, read until the next save (module docstring).
RIG_FILENAME = "rig.json"
CHANNEL_SET_FILENAME = "channel_set.json"
PIN_MAP_FILENAME = "pin_map.json"

#: The keys of the joined document that belong to the pin map, beside `pins`.
#: `edited_at` belongs to neither: it says when a FILE was written, and two
#: machines holding identical wiring must compare equal.
_PIN_MAP_KEYS = ("derived_from", "board", "pin_range")


class RigInvalid(ValueError):
    """The document is not a rig document. Carries located diagnostics."""

    def __init__(self, problems: list[tuple[str, str]]) -> None:
        self.problems = problems
        super().__init__("; ".join(f"{loc}: {msg}" for loc, msg in problems[:3]))


@dataclass(frozen=True)
class RigStatus:
    """What the editor needs to know about where the wiring came from."""

    #: True when this rig has its own stored wiring, loaded or not; False when
    #: it is running the shipped pinout untouched. A stored wiring that did not
    #: load is still the rig's own -- and Reset must stay reachable for it.
    custom: bool
    #: The shipped pinout this rig derives from, named even when custom — a
    #: rig document is a copy of one, and saying which answers "a Mega, wired
    #: how?" without the operator having to remember.
    derived_from: str
    edited_at: str | None


@dataclass(frozen=True)
class _Stored:
    #: The document as parsed, even if it will not load; None if unparseable.
    document: dict | None
    #: (location, message) for why it will not load; empty when it loads.
    problems: list[tuple[str, str]]


class HardwareStore:
    """Reads and writes `<data_dir>/hardware/wiring.json`.

    Owns the file and nothing else. Composing it into a `ChannelMap`, and
    invalidating the cached registries when it changes, is `rig/registry.py`'s
    job — this class must not reach for a composed map at import time, so that a
    broken rig document is a diagnostic rather than an import error.
    """

    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir) / "hardware"
        self.path = self.root / WIRING_FILENAME
        self.legacy_rig_path = self.root / RIG_FILENAME
        self.channel_set_path = self.root / CHANNEL_SET_FILENAME
        self.pin_map_path = self.root / PIN_MAP_FILENAME

    # -- reading ----------------------------------------------------------- #

    def exists(self) -> bool:
        """Whether this rig has stored wiring of its own, loaded or not."""
        return any(p.is_file() for p in self._documents())

    def load(self) -> dict | None:
        """The wiring in force: the rig's own, or None for the shipped pinout.

        None ALSO when stored wiring will not load, so the registry still
        composes a working rig for a process that owns six serial ports -- but
        that case is never silent: `load_problems` names it, and the session
        lifecycle refuses to start or flash a box while it lasts.
        """
        stored = self._stored()
        return stored.document if not stored.problems else None

    def snapshot(self) -> tuple[dict | None, list[tuple[str, str]]]:
        """`(load(), load_problems())` from ONE read, for installing the wiring
        in force: two reads could straddle a change to the file."""
        stored = self._stored()
        return (stored.document if not stored.problems else None), stored.problems

    def load_problems(self) -> list[tuple[str, str]]:
        """(location, message) for why stored wiring exists and did not load."""
        return self._stored().problems

    def stored_document(self) -> dict | None:
        """The stored document as parsed, whether or not it loads, so the
        editor can show the operator the wiring that needs fixing."""
        return self._stored().document

    def status(self) -> RigStatus:
        doc = self.stored_document()
        return RigStatus(
            custom=self.exists(),
            derived_from=str((doc or {}).get("derived_from", "")),
            edited_at=(doc or {}).get("edited_at"),
        )

    def _stored(self) -> _Stored:
        if self.path.is_file():
            return _checked(WIRING_FILENAME, *_read(self.path))
        if self.channel_set_path.is_file():
            return self._two_file_pair()
        if self.legacy_rig_path.is_file():
            return _checked(RIG_FILENAME, *_read(self.legacy_rig_path))
        if self.pin_map_path.is_file():
            return _Stored(None, [_unloaded(PIN_MAP_FILENAME, f"it has no {CHANNEL_SET_FILENAME} beside it")])
        return _Stored(None, [])

    def _two_file_pair(self) -> _Stored:
        """The two-file layout: `channel_set.json` and `pin_map.json`.

        The pin map names its channel set by digest. A pin map staged as
        `pin_map.json.tmp` with the channel set's digest is the second half of
        a save that stopped between its two renames, and completes the pair.
        Anything else that disagrees is a load problem.
        """
        channel_set, why = _read(self.channel_set_path)
        if channel_set is None:
            return _Stored(None, [_unloaded(CHANNEL_SET_FILENAME, why)])
        digest = legacy_pair_digest(channel_set)
        candidates = (self.pin_map_path, self.pin_map_path.with_suffix(".json.tmp"))
        for candidate in candidates:
            pin_map, _ = _read(candidate, quiet=True)
            if pin_map is not None and pin_map.get("channel_set_digest") == digest:
                joined = join(channel_set, pin_map)
                return _checked(PIN_MAP_FILENAME, joined, None)
        return _Stored(
            join(channel_set, _read(self.pin_map_path, quiet=True)[0] or {"pins": {}}),
            [_unloaded(
                PIN_MAP_FILENAME,
                f"it does not belong to {CHANNEL_SET_FILENAME} (they were not written by "
                "one save), so its pins could put a port under another port's codes",
            )],
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
        problems = validate(doc) or _unpinned(doc)
        if problems:
            raise RigInvalid(problems)

        stored = dict(doc)
        stored["edited_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.root.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.path, json.dumps(stored, indent=2) + "\n")
        # Only once the new file is whole: an older layout left behind by a
        # failure here is harmless, because `wiring.json` wins over it.
        self._remove(self._older_layouts())
        return stored

    def reset(self) -> None:
        """Back to the shipped pinout. The files go; nothing else does."""
        self._remove(self._every_layout())

    def _older_layouts(self) -> tuple[Path, ...]:
        return (
            self.legacy_rig_path,
            self.channel_set_path,
            self.pin_map_path,
            self.channel_set_path.with_suffix(".json.tmp"),
            self.pin_map_path.with_suffix(".json.tmp"),
            self.legacy_rig_path.with_suffix(".json.tmp"),
        )

    def _every_layout(self) -> tuple[Path, ...]:
        return (self.path, self.path.with_name(self.path.name + ".part"), *self._older_layouts())

    def _documents(self) -> tuple[Path, ...]:
        """The files that hold wiring; temporary files never do on their own."""
        return (self.path, self.legacy_rig_path, self.channel_set_path, self.pin_map_path)

    @staticmethod
    def _remove(paths) -> None:  # noqa: ANN001 - an iterable of Path
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("could not remove %s (%s); %s still wins", path.name, exc, WIRING_FILENAME)


def split(doc: dict) -> tuple[dict, dict]:
    """The joined document -> (channel set, pin map): the two documents the
    file holds. Neither carries `edited_at` (see `_PIN_MAP_KEYS`)."""
    channel_set = {"channel_set_version": 1, "channels": doc["channels"]}
    pin_map = {
        "pin_map_version": 1,
        **{k: doc[k] for k in _PIN_MAP_KEYS if k in doc},
        "pins": doc["pins"],
    }
    return channel_set, pin_map


def join(channel_set: dict, pin_map: dict) -> dict:
    """(channel set, pin map) -> the one document the file, the editor and the
    wire hold. A two-file pair's `edited_at` is kept, for the status line."""
    edited_at = pin_map.get("edited_at") or channel_set.get("edited_at")
    return {
        "rig_version": 1,
        **{k: pin_map[k] for k in _PIN_MAP_KEYS if k in pin_map},
        **({"edited_at": edited_at} if edited_at else {}),
        "channels": channel_set.get("channels"),
        "pins": pin_map.get("pins"),
    }


def legacy_pair_digest(channel_set: dict) -> str:
    """How the two-file layout's pin map names its channel set. Read only;
    a save writes the one-file layout."""
    canonical = json.dumps(channel_set, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _unloaded(location: str, why: str | None) -> tuple[str, str]:
    message = (
        f"{location} did not load: {why or 'it could not be read'}. This rig is not "
        "using it, so no box can start or be flashed until its wiring is saved "
        "again or reset."
    )
    return location, message


def _checked(location: str, doc: dict | None, why: str | None) -> _Stored:
    """A stored document that read, checked against the schema before it may
    be composed -- a hand edit can break its shape as easily as its JSON."""
    if doc is None:
        return _Stored(None, [_unloaded(location, why)])
    doc = upgrade(doc)
    try:
        import jsonschema  # noqa: F401
    except ImportError:  # pragma: no cover - the dependency fence: compose as before
        return _Stored(doc, [])
    shape = validate(doc) or _unpinned(doc)
    if shape:
        where, what = shape[0]
        return _Stored(doc, [_unloaded(location, f"{where}: {what}")])
    return _Stored(doc, [])


def _unpinned(doc: dict) -> list[tuple[str, str]]:
    """A channel with no pin, or a pin with no channel.

    Not a wiring rule to report and compose past (RIG101 in the editor): the
    composed map drops a channel that has no pin, so a stored document like
    this would load with the channel silently gone.
    """
    channels, pins = set(doc.get("channels") or {}), set(doc.get("pins") or {})
    out = [(f"pins.{name}", f"channel {name!r} has no pin") for name in sorted(channels - pins)]
    out += [(f"channels.{name}", f"pin {name!r} belongs to no channel") for name in sorted(pins - channels)]
    return out


def _read(path: Path, *, quiet: bool = False) -> tuple[dict | None, str | None]:
    """(document, None), or (None, why it would not read) -- logged as an
    error unless `quiet`: a stored wiring that will not read stops the rig."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        why = f"it is unreadable ({exc})"
    else:
        if len(raw) > MAX_RIG_BYTES:
            why = f"it is {len(raw)} bytes, over the {MAX_RIG_BYTES} limit"
        else:
            try:
                doc = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                why = f"it will not parse ({exc})"
            else:
                if isinstance(doc, dict):
                    return doc, None
                why = "it is not a JSON object"
    if not quiet:
        log.error("stored rig wiring %s did not load: %s", path.name, why)
    return None, why


def _write_atomic(path: Path, text: str) -> None:
    """Write, fsync, rename over, fsync the folder -- `strobes/store.py`'s order
    plus the folder. Without the file fsync the rename can reach the disk
    before the bytes, and a power cut leaves an empty file under the real
    name. A failure up to the rename removes the part file and leaves the
    previous `wiring.json` as it was. After the rename the new file IS the
    wiring, so a folder fsync that fails is logged, not raised: reporting the
    save as failed would leave the app describing wiring that is in force as
    if it were not."""
    part = path.with_name(path.name + ".part")
    try:
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o644)
        try:
            data = memoryview(text.encode("utf-8"))
            while data:
                data = data[os.write(fd, data):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    try:
        _fsync_directory(path.parent)
    except OSError as exc:
        log.warning(
            "%s was saved, but fsyncing its folder failed (%s); a power cut now "
            "could still bring back the previous file",
            path.name,
            exc,
        )


def _fsync_directory(folder: Path) -> None:
    if os.name == "nt":  # Windows cannot open a directory to fsync it
        return
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


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
        return [("wiring.json", "the rig document must be a JSON object")]

    try:
        import jsonschema
    except ImportError:  # pragma: no cover - the dependency fence
        return [(
            "wiring.json",
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
        return "wiring.json"
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

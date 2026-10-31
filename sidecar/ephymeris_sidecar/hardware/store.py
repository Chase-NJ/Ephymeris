"""The rig wiring: the operator's, validated on the way in.

Layout, under the sidecar's own data dir (beside `ephymeris.db` — these are
sidecar-side writes, no Tauri fs capability involved):

    <data_dir>/hardware/wiring.json
    <data_dir>/wiring-confirmed.json      the digests of wiring saved here

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

STORED WIRING NOBODY SAVED OR CONFIRMED HERE IS HELD (#131). The store keeps
the content digest of the wiring last saved on this machine, which is also how
a confirmed "I've checked every pin" lands: as a save. Stored wiring that
passes every check but whose digest is not recorded is `held`: copied in,
edited by hand, or fixed by hand after a failed load. It is never put in
force, however many restarts pass, until it is saved. The digests live OUTSIDE
`hardware/`, so copying that folder from the other lab machine never brings
its confirmation along. A machine with no digest file yet (an upgrade from
main, or a fresh install) records, on its first read, the stored wiring it
would have run anyway, so a normal upgrade asks nothing (`_recorded`).

STORED WIRING THAT IS NOT IN FORCE IS NEVER REPLACED BY THE SHIPPED ONE SILENTLY.
The registry composes the shipped pinout meanwhile, because the process owns six
serial ports and must start; but `inspect` says why, and no box is started,
flashed or identified until the wiring is saved again or reset
(`RigDefinition.wiring_problem`, which follows the wiring IN FORCE).
Meanwhile `hardware.get` serves the stored document itself as the editor's
draft, broken or held, so the operator repairs or checks their own wiring and
saves it, rather than retyping it over the shipped pins.

TWO OLDER LAYOUTS ARE READ IN PLACE until the next save writes `wiring.json`
and removes them:

  * `rig.json` -- the same document under another name;
  * `channel_set.json` + `pin_map.json` -- the two documents in two files, the
    pin map naming its channel set by `channel_set_digest`. A pair whose digests
    disagree is a load problem, never a guess.

`wiring.json` wins over both, and the pair over `rig.json`. A layout beside
the one read is a SHADOW: if its digest is recorded it is this app's own
leftover of a save stopped before its cleanup, and the next save removes it;
otherwise it was copied in, `inspect` names it, and no save deletes it. A stray
temporary file (`*.part`, `*.json.tmp`) on its own is no wiring at all.

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
from collections.abc import Callable
import dataclasses
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
#: The digests of the wiring saved on this machine, in the data dir itself.
CONFIRMED_FILENAME = "wiring-confirmed.json"

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
class Stored:
    """The stored wiring now, from one read (`HardwareStore.inspect`)."""

    #: The document as parsed and upgraded, even if it will not load; None if
    #: unparseable.
    document: dict | None
    #: (location, message) for why it will not load; empty when it loads, and
    #: when it is held (it would load, but nobody saved it here).
    problems: list[tuple[str, str]]
    #: Which of `DISK_STATES` the stored wiring is in.
    state: str = "none"
    #: The files it was read from, by name, temporary files left out.
    sources: tuple[str, ...] = ()
    #: Older layouts beside it, not read and not recorded as saved here: copied
    #: in. Named so the operator sees them; no save removes them.
    shadows: tuple[str, ...] = ()
    #: `content_digest` of the document as it is on disk, before `upgrade`.
    digest: str | None = None


#: What the stored wiring on disk is, as `hardware/service.py` acts on it:
#:   none          no stored wiring
#:   loads         it passes every check and was saved here: it may be in force
#:   held          it passes every check but was not saved or confirmed here:
#:                 copied in, or changed by hand. Its pins must be confirmed
#:   invalid       it parses but is out of shape, a channel lacks a pin, or it
#:                 breaks a wiring rule (RIG101-RIG107): a document to repair
#:   mismatched    a two-file pair whose pin map was not written with its
#:                 channel set: a document whose PINS must be confirmed
#:   unrepairable  nothing to repair: unreadable, too large, unparseable, not
#:                 a JSON object, or one half of a pair alone
DISK_STATES = ("none", "loads", "held", "invalid", "mismatched", "unrepairable")


@dataclass(frozen=True)
class _Layout:
    """One way wiring can be stored: the files it owns, and how to read it."""

    files: tuple[Path, ...]
    present: bool
    read: Callable[[], Stored]
    #: The digest of what it holds, read quietly, or None if it holds nothing
    #: whole -- for a shadow, which is never composed.
    digest: Callable[[], str | None]


class HardwareStore:
    """Reads and writes `<data_dir>/hardware/wiring.json`, and the record of
    which wiring was saved here (`<data_dir>/wiring-confirmed.json`).

    Owns those files and nothing else. Composing the wiring into a
    `ChannelMap`, and invalidating the cached registries when it changes, is
    `rig/registry.py`'s job — this class must not reach for a composed map at
    import time, so that a broken rig document is a diagnostic rather than an
    import error.
    """

    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir) / "hardware"
        self.path = self.root / WIRING_FILENAME
        self.legacy_rig_path = self.root / RIG_FILENAME
        self.channel_set_path = self.root / CHANNEL_SET_FILENAME
        self.pin_map_path = self.root / PIN_MAP_FILENAME
        #: Beside `hardware/`, never in it (module docstring).
        self.confirmed_path = Path(data_dir) / CONFIRMED_FILENAME

    # -- reading ----------------------------------------------------------- #

    def exists(self) -> bool:
        """Whether this rig has stored wiring of its own, loaded or not."""
        return any(p.is_file() for p in self._documents())

    def inspect(self) -> Stored:
        """The stored wiring now, from ONE read: its document (even broken or
        held), why it does not load, which of `DISK_STATES` it is in, and the
        copies beside it that are not read."""
        return self._survey()[0]

    def load(self) -> dict | None:
        """The stored wiring if it may be put in force now (`loads`), else None
        for the shipped pinout. None ALSO when stored wiring is held or will not
        load -- never silent: `inspect` says so, and the session lifecycle
        refuses to start or flash a box while it lasts."""
        stored = self.inspect()
        return stored.document if stored.state == "loads" else None

    def load_problems(self) -> list[tuple[str, str]]:
        """(location, message) for why stored wiring exists and did not load."""
        return self.inspect().problems

    def stored_paths(self) -> list[Path]:
        """Every file Reset would remove now, in the order it removes them --
        built from `removal_order`, the list Reset itself walks, so what the
        confirm dialog names and what Reset deletes cannot drift apart."""
        return [p for p in self.removal_order() if p.is_file()]

    def stored_document(self) -> dict | None:
        """The stored document as parsed, whether or not it loads: the draft
        `hardware.get` serves while it is not in force, so the operator can
        repair or check it and save. None when there is none, or it will not
        even parse."""
        return self.inspect().document

    def status(self) -> RigStatus:
        doc = self.stored_document()
        return RigStatus(
            custom=self.exists(),
            derived_from=str((doc or {}).get("derived_from", "")),
            edited_at=(doc or {}).get("edited_at"),
        )

    def _layouts(self) -> tuple[_Layout, ...]:
        """Every layout, highest precedence first: the first present is read."""
        pair = (
            self.channel_set_path,
            self.pin_map_path,
            self.channel_set_path.with_suffix(".json.tmp"),
            self.pin_map_path.with_suffix(".json.tmp"),
        )
        return (
            _Layout(
                (self.path,),
                self.path.is_file(),
                lambda: _checked(WIRING_FILENAME, *_read(self.path), sources=(WIRING_FILENAME,)),
                lambda: _digest_of(_read(self.path, quiet=True)[0]),
            ),
            _Layout(
                pair,
                self.channel_set_path.is_file() or self.pin_map_path.is_file(),
                self._two_file_pair,
                lambda: self._two_file_pair(quiet=True).digest,
            ),
            _Layout(
                (self.legacy_rig_path, self.legacy_rig_path.with_suffix(".json.tmp")),
                self.legacy_rig_path.is_file(),
                lambda: _checked(RIG_FILENAME, *_read(self.legacy_rig_path), sources=(RIG_FILENAME,)),
                lambda: _digest_of(_read(self.legacy_rig_path, quiet=True)[0]),
            ),
        )

    def _survey(self) -> tuple[Stored, frozenset[str], list[_Layout]]:
        """(the stored wiring, the digests recorded as saved here, the older
        layouts a save replaces) -- everything one read of the disk says."""
        present = [layout for layout in self._layouts() if layout.present]
        stored = present[0].read() if present else Stored(None, [], "none")
        recorded = self._recorded(stored)
        if stored.state == "loads" and stored.digest not in recorded:
            stored = dataclasses.replace(stored, state="held")
        shadows = [s for s in present[1:] if s.digest() not in recorded]
        stored = dataclasses.replace(stored, shadows=tuple(
            p.name for s in shadows for p in s.files if p.is_file() and not p.name.endswith(".tmp")
        ))
        replaced = [s for s in present if s.files[0] != self.path and s not in shadows]
        return stored, recorded, replaced

    def _recorded(self, stored: Stored) -> frozenset[str]:
        """The digests of the wiring saved (or confirmed) on this machine.

        NO FILE YET is the upgrade from main, or a fresh install: what is
        stored is recorded if it passes every check -- it is what main would
        have put in force at this start -- and the file is written now, even
        empty, so wiring copied in after today is held. A file that exists but
        will not read is never "no file": it records nothing, so everything is
        held until saved, and the log says why.
        """
        try:
            raw = self.confirmed_path.read_bytes()
        except FileNotFoundError:
            seed = [stored.digest] if stored.state == "loads" and stored.digest else []
            try:
                self._write_recorded(seed)
            except OSError as exc:
                log.warning("could not record the wiring in force (%s); it is trusted this run only", exc)
            return frozenset(seed)
        except OSError as exc:
            log.error("%s is unreadable (%s): every stored wiring is held", CONFIRMED_FILENAME, exc)
            return frozenset()
        try:
            digests = json.loads(raw)["digests"]
            if not isinstance(digests, list) or not all(isinstance(d, str) for d in digests):
                raise TypeError("digests is not a list of strings")
        except (ValueError, KeyError, TypeError) as exc:
            log.error("%s will not read (%s): every stored wiring is held", CONFIRMED_FILENAME, exc)
            return frozenset()
        return frozenset(digests)

    def _write_recorded(self, digests: list[str]) -> None:
        self.confirmed_path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.confirmed_path, json.dumps({"version": 1, "digests": sorted(set(digests))}) + "\n")

    def _two_file_pair(self, *, quiet: bool = False) -> Stored:
        """The two-file layout: `channel_set.json` and `pin_map.json`.

        The pin map names its channel set by digest. A pin map staged as
        `pin_map.json.tmp` with the channel set's digest is the second half of
        a save that stopped between its two renames, and completes the pair.
        Either half alone is nothing to repair; a pair that disagrees is a
        load problem.
        """
        names = tuple(p.name for p in (self.channel_set_path, self.pin_map_path) if p.is_file())
        staged = self.pin_map_path.with_suffix(".json.tmp")
        if not self.channel_set_path.is_file():
            return Stored(
                None,
                [_unloaded(PIN_MAP_FILENAME, f"it has no {CHANNEL_SET_FILENAME} beside it")],
                "unrepairable",
                names,
            )
        channel_set, why = _read(self.channel_set_path, quiet=quiet)
        if channel_set is None:
            return Stored(None, [_unloaded(CHANNEL_SET_FILENAME, why)], "unrepairable", names)
        if not (self.pin_map_path.is_file() or staged.is_file()):
            return Stored(
                None,
                [_unloaded(CHANNEL_SET_FILENAME, f"it has no {PIN_MAP_FILENAME} beside it")],
                "unrepairable",
                names,
            )
        digest = legacy_pair_digest(channel_set)
        for candidate in (self.pin_map_path, staged):
            pin_map, _ = _read(candidate, quiet=True)
            if pin_map is not None and pin_map.get("channel_set_digest") == digest:
                return _checked(PIN_MAP_FILENAME, join(channel_set, pin_map), None, sources=names)
        joined = join(channel_set, _read(self.pin_map_path, quiet=True)[0] or {"pins": {}})
        return Stored(
            joined,
            [_unloaded(
                PIN_MAP_FILENAME,
                f"it does not belong to {CHANNEL_SET_FILENAME} (they were not written by "
                "one save), so its pins could put a port under another port's codes",
            )],
            "mismatched",
            names,
        )

    # -- writing ----------------------------------------------------------- #

    def save(self, doc: dict) -> dict:
        """Validate, stamp, record and write. Returns the document as stored.

        Validation is the whole point of this method and it happens BEFORE the
        write, not after: a rig document that fails is not written at all, so
        there is no state in which the file on disk is one the compiler refuses.
        Every problem is reported, not just the first — fixing new wiring should
        be one pass rather than a game of whack-a-mole, which is the same
        argument `ChannelMap.disagreements()` makes.

        A save records the wiring as saved here, in an order no crash can turn
        into trusting wiring nobody saved, or holding wiring that was:

          1. record the new digest BESIDE the ones already recorded;
          2. write `wiring.json` (the commit);
          3. remove the older layouts it replaces -- never a shadow copied in;
          4. record the new digest alone, unless a removal failed: then the
             digests recorded before stay, so a leftover this app recorded is
             removed silently by the next save (one never recorded is shown).

        A failure at 1 writes nothing; at 2, the previous wiring is still
        recorded; after 2 the save has landed, and step 4 is logged if it fails.
        """
        problems = save_problems(doc)
        if problems:
            raise RigInvalid(problems)

        stored = dict(doc)
        stored["edited_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        new = content_digest(stored)
        _, recorded, replaced = self._survey()
        self._write_recorded([*recorded, new])
        self.root.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.path, json.dumps(stored, indent=2) + "\n")
        # Only once the new file is whole: an older layout left behind by a
        # failure here is harmless, because `wiring.json` wins over it.
        if self._remove(p for layout in replaced for p in layout.files):
            try:
                self._write_recorded([new])
            except OSError as exc:
                log.warning("%s was saved, but recording it alone failed (%s)", WIRING_FILENAME, exc)
        return stored

    def reset(self) -> None:
        """Back to the shipped pinout. The files go; nothing else does.

        NOTHING RECORDED FIRST, so a Reset that stops part-way holds whatever
        it left behind rather than trusting it at the next start. Then LOWEST
        PRECEDENCE FIRST, and the first file that will not go stops it
        (raised): removing `wiring.json` first would let a failure part-way put
        an older wiring back. In this order a failure leaves either the wiring
        that was in force or a load problem, and either is held at a restart.
        """
        self._write_recorded([])
        for path in self.removal_order():
            path.unlink(missing_ok=True)

    def removal_order(self) -> tuple[Path, ...]:
        """Every file Reset removes, lowest precedence first (see `reset`)."""
        return (
            self.channel_set_path.with_suffix(".json.tmp"),
            self.pin_map_path.with_suffix(".json.tmp"),
            self.legacy_rig_path.with_suffix(".json.tmp"),
            self.legacy_rig_path,
            self.pin_map_path,
            self.channel_set_path,
            self.path.with_name(self.path.name + ".part"),
            self.path,
        )

    def _documents(self) -> tuple[Path, ...]:
        """The files that hold wiring; temporary files never do on their own."""
        return (self.path, self.legacy_rig_path, self.channel_set_path, self.pin_map_path)

    @staticmethod
    def _remove(paths) -> bool:  # noqa: ANN001 - an iterable of Path
        """Remove each; True when every one is gone."""
        whole = True
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                whole = False
                log.warning("could not remove %s (%s); %s still wins", path.name, exc, WIRING_FILENAME)
        return whole


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


def content_digest(doc: dict) -> str:
    """What `wiring-confirmed.json` records: the wiring's content, without
    `edited_at`, so identical wiring written at another moment is the same
    wiring. Taken over the document AS STORED, never after `upgrade`: a later
    release that fills one more default must not hold every untouched file."""
    content = {k: v for k, v in doc.items() if k != "edited_at"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _digest_of(doc: dict | None) -> str | None:
    return None if doc is None else content_digest(doc)


def _unloaded(location: str, why: str | None) -> tuple[str, str]:
    """What is wrong with the FILE, and nothing about its consequence: that
    depends on what is in force, which `hardware/service.py` says."""
    return location, f"{location} did not load: {why or 'it could not be read'}."


def _checked(location: str, doc: dict | None, why: str | None, *, sources: tuple[str, ...]) -> Stored:
    """A stored document that read, checked as a save checks it before it may
    be composed: its shape, a pin for every channel, and every wiring rule.
    A hand edit can break any of them as easily as its JSON."""
    if doc is None:
        return Stored(None, [_unloaded(location, why)], "unrepairable", sources)
    digest = content_digest(doc)
    doc = upgrade(doc)
    try:
        import jsonschema  # noqa: F401
    except ImportError:  # pragma: no cover - the dependency fence: compose as before
        return Stored(doc, [], "loads", sources, digest=digest)
    shape = validate(doc) or _unpinned(doc)
    if shape:
        where, what = shape[0]
        return Stored(doc, [_unloaded(location, f"{where}: {what}")], "invalid", sources, digest=digest)
    rules = rule_problems(doc)
    if rules:
        code, where, what = rules[0]
        return Stored(doc, [_unloaded(location, f"{code} {where}: {what}")], "invalid", sources, digest=digest)
    return Stored(doc, [], "loads", sources, digest=digest)


def save_problems(doc: Any) -> list[tuple[str, str]]:
    """Why `save` would refuse this document: its shape, then a channel with
    no pin. Checked by the rig definition before it issues any edge code."""
    return validate(doc) or (_unpinned(doc) if isinstance(doc, dict) else [])


def rule_problems(document: Any) -> list[tuple[str, str, str]]:
    """(code, location, message) for every wiring rule (RIG101-RIG107) a
    document that passed the schema breaks, against the vocabulary in force.

    Here rather than in `hardware/service.py` because a load runs them too:
    a stored file that breaks one is never put in force."""
    from ephymeris_sidecar.rig import registry

    try:
        chans = registry.ChannelMap(*registry.split_rig(document))
    except (KeyError, TypeError) as exc:  # pragma: no cover - schema catches these
        return [("RIG101", WIRING_FILENAME, str(exc))]

    vocab = registry.vocabulary()
    return [
        (code, loc, msg)
        for code, pairs in (
            ("RIG101", chans.disagreements()),
            ("RIG102", chans.pin_problems()),
            ("RIG103", chans.duplicate_pins()),
            ("RIG104", chans.slot_problems(vocab)),
            ("RIG105", chans.sync_problems()),
            ("RIG106", chans.onset_problems(vocab)),
            ("RIG107", chans.edge_problems(vocab)),
        )
        for loc, msg in pairs
    ]


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

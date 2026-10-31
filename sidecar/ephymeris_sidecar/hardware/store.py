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

STORED WIRING NOBODY SAVED OR CONFIRMED HERE IS HELD. `wiring-confirmed.json`
(`_Record`) holds the content digest of the last wiring saved on this machine;
stored wiring that passes every check but is not that wiring is `held`, at
every start, until it is saved. How the record is kept -- outside `hardware/`,
written around each save, seeded only at the machine's first start
(`settle_record`) -- is TASKS.md#the-channel-set-and-the-pin-map.

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
the one read is a SHADOW: the record lists it as the app's own leftover, which
the next save removes, or `inspect` names it and no save deletes it. A stray
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
#: The database's mark (`cohorts/db.py`'s `machine_marks`) that this machine's
#: first start, the one that may seed the record, has happened.
FIRST_START_MARK = "wiring_record"
#: The same fact in the data dir, beside the record: written at every start,
#: so a database restored from before the mark is still no first start.
STARTED_FILENAME = "wiring-record-started"

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
    #: `order_blind_digest` of the same: only to carry an older record over.
    order_blind: str | None = None
    #: Held because a save after it did not finish: this IS the wiring last
    #: saved here, but the record cannot tell it from what that save replaced.
    interrupted: bool = False
    #: Why there is no usable record of the wiring saved here (missing, or
    #: will not read), so nothing stored is trusted; None when there is one.
    record_problem: str | None = None


@dataclass(frozen=True)
class _Record:
    """`wiring-confirmed.json`: which wiring this machine has saved."""

    #: The content digest of the LAST wiring saved or confirmed here, and no
    #: other: a wiring a save replaced is never trusted again.
    digest: str | None = None
    #: A save in flight, recorded before its `wiring.json` is written. While it
    #: stands, ONLY `wiring.json` holding exactly this digest is trusted: that
    #: is what proves the save landed, and `settle_record` finishes it at the
    #: next start. Anything else on disk, the wiring it replaced included, is
    #: held -- a save that failed before its commit puts the record back.
    pending: str | None = None
    #: `_file_digest`s of older layouts that are the app's own leftovers: one a
    #: save replaced but could not remove, or one the first start found beside
    #: `wiring.json`. They mark a file for the next save to remove, and never
    #: put any wiring in force.
    leftovers: frozenset[str] = frozenset()
    #: Why the record is not usable; None when it is.
    problem: str | None = None
    #: The record is not there at all (a first start may seed it).
    missing: bool = False
    #: The digests an earlier build's record named (its `digests` list), read
    #: from a record in that shape: the only wiring a first start may seed.
    #: None for any other record.
    earlier: frozenset[str] | None = None

    def trusts(self, digest: str | None, *, is_wiring_json: bool) -> bool:
        """Whether stored wiring with `digest` may be put in force."""
        if digest is None or self.problem:
            return False
        if self.pending is not None:
            return is_wiring_json and digest == self.pending
        return digest == self.digest

    def to_json(self) -> str:
        return json.dumps({
            "version": 1,
            "digest": self.digest,
            **({"pending": self.pending} if self.pending else {}),
            "leftovers": sorted(self.leftovers),
        }) + "\n"


#: What the stored wiring on disk is, as `hardware/service.py` acts on it:
#:   none          no stored wiring
#:   loads         it passes every check and was saved here: it may be in force
#:   held          it passes every check but was not saved or confirmed here
#:                 (copied in, or changed by hand), or it was saved here but a
#:                 save after it did not finish. Its pins must be confirmed
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
    #: The same, blind to declaration order: only to carry an older record over.
    blind: Callable[[], str | None]


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
        #: `STARTED_FILENAME`: this data dir has started a build that keeps
        #: the record. With the database's mark, what makes a first start.
        self.started_path = Path(data_dir) / STARTED_FILENAME
        #: What the first start recorded but could not write: trusted for this
        #: run only. The next start is not a first start, so it holds.
        self._unwritten: _Record | None = None

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
                lambda: _blind_of(_read(self.path, quiet=True)[0]),
            ),
            _Layout(
                pair,
                self.channel_set_path.is_file() or self.pin_map_path.is_file(),
                self._two_file_pair,
                lambda: self._two_file_pair(quiet=True).digest,
                lambda: self._two_file_pair(quiet=True).order_blind,
            ),
            _Layout(
                (self.legacy_rig_path, self.legacy_rig_path.with_suffix(".json.tmp")),
                self.legacy_rig_path.is_file(),
                lambda: _checked(RIG_FILENAME, *_read(self.legacy_rig_path), sources=(RIG_FILENAME,)),
                lambda: _digest_of(_read(self.legacy_rig_path, quiet=True)[0]),
                lambda: _blind_of(_read(self.legacy_rig_path, quiet=True)[0]),
            ),
        )

    def settle_record(self, *, first_start: bool) -> None:
        """Once per start, before the first install (`RigDefinition`).

        THE MACHINE'S FIRST START is the database's word (`first_start`: its
        mark is absent) AND the data dir's (`STARTED_FILENAME` is absent), so
        neither a lost record nor a database restored from before the upgrade
        fakes one. Only then, and only over no record at all or one in an
        earlier build's shape, is the stored wiring recorded without a save:
        if it passes every check, and, under an earlier record, only if that
        record named it. Older layouts beside `wiring.json`, which the build
        before left mid-migration and would have removed, become leftovers.
        The record is written even when empty, so wiring copied in later is
        held. A record that will not parse holds, first start or not.

        A SAVE CUT OFF BEFORE ITS LAST STEP is finished here only if
        `wiring.json` holds exactly the wiring it was saving: that becomes the
        one recorded, and what it replaced a leftover. Anything else stays held.

        AN ORDER-BLIND RECORD is read here, at the first start, and nowhere
        else (`_carried_over`); at any other start `_record` drops it unread.
        """
        first = first_start and not self.started_path.exists()
        record = self._record(keep_order_blind=True)
        if first:
            record = self._carried_over(record)
        elif _order_blind_in(record):
            log.warning(
                "%s holds a digest blind to channel order at a start that is not this "
                "machine's first: it confirms nothing", CONFIRMED_FILENAME,
            )
            record = self._record()
        self._mark_started()
        if record.problem:
            if first and (record.missing or record.earlier is not None):
                self._seed(record)
            return
        if record.pending is None:
            return
        on_disk = _digest_of(_read(self.path, quiet=True)[0]) if self.path.is_file() else None
        if on_disk != record.pending:
            return  # not the save that was in flight: hold it all
        present, _ = self._present()
        replaced = {
            _file_digest(p)
            for layout in present[1:]
            if layout.digest() == record.digest
            for p in layout.files
            if p.is_file()
        }
        settled = _Record(record.pending, None, record.leftovers | replaced)
        try:
            self._write_record(settled)
        except OSError as exc:
            log.warning("could not finish recording the last wiring save (%s)", exc)

    def _carried_over(self, record: "_Record") -> "_Record":
        """A record whose digests are blind to declaration order (written by a
        build before they covered it) is carried over ONCE, and only at the
        machine's first start (`settle_record`); every other start drops
        them unread (`_record`), so a machine that ran #134 (its database
        marked, no `STARTED_FILENAME`) is held once. Each digest becomes today's form of exactly
        the file it still matches, and is otherwise dropped -- a digest left
        order-blind would confirm that wiring with its odor lines swapped. A
        carry that cannot be written is trusted this run only (`_unwritten`):
        the next start is not a first start, so the order-blind record still
        on disk confirms nothing.

          * `digest` carries to the stored wiring it matches; or, while a save
            it was replaced by carries, to the older layout that save replaced,
            so `settle_record` makes it a leftover; else None.
          * `pending` carries to the stored wiring it matches; else to
            `_UNFINISHED`: that save did not finish, so nothing is trusted.
        """
        if record.problem or not _order_blind_in(record):
            return record
        present, stored = self._present()
        pending = record.pending
        if _order_blind(pending):
            pending = stored.digest if pending == stored.order_blind else _UNFINISHED
        digest = record.digest
        if _order_blind(digest):
            if digest == stored.order_blind:
                digest = stored.digest
            elif pending not in (None, _UNFINISHED):
                digest = next((s.digest() for s in present[1:] if s.blind() == digest), None)
            else:
                digest = None
        carried = dataclasses.replace(record, digest=digest, pending=pending)
        if carried != record:
            try:
                self._write_record(carried)
            except OSError as exc:
                log.warning("could not carry the wiring record over (%s); trusted this run only", exc)
                self._unwritten = carried
        return carried

    def _mark_started(self) -> None:
        if self.started_path.exists():
            return
        try:
            self.started_path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(self.started_path, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
        except OSError as exc:
            log.warning("could not write %s (%s)", STARTED_FILENAME, exc)

    def _seed(self, earlier: "_Record") -> None:
        present, stored = self._present()
        trusted = stored.state == "loads" and (
            earlier.earlier is None or stored.order_blind in earlier.earlier
        )
        beside_wiring = bool(present) and present[0].files[0] == self.path
        leftovers = frozenset(
            _file_digest(p) for layout in present[1:] for p in layout.files if p.is_file()
        ) if beside_wiring else frozenset()
        # An earlier record's own leftovers (`file:` entries) stay the app's.
        leftovers |= frozenset(d for d in earlier.earlier or () if d.startswith("file:"))
        record = _Record(stored.digest if trusted else None, None, leftovers)
        try:
            self._write_record(record)
        except OSError as exc:
            log.warning("could not record the wiring in force (%s); it is trusted this run only", exc)
            self._unwritten = record

    def _present(self) -> tuple[list[_Layout], Stored]:
        """(the layouts on disk, highest precedence first; the first one, read
        and checked, before anything about the record)."""
        present = [layout for layout in self._layouts() if layout.present]
        return present, present[0].read() if present else Stored(None, [], "none")

    def _survey(self) -> tuple[Stored, _Record, list[_Layout]]:
        """(the stored wiring, the record, the older layouts a save replaces)
        -- everything one read of the disk says."""
        present, stored = self._present()
        record = self._record()
        if stored.state == "loads" and not record.trusts(
            stored.digest, is_wiring_json=present[0].files[0] == self.path
        ):
            stored = dataclasses.replace(
                stored,
                state="held",
                interrupted=record.pending is not None and stored.digest == record.digest,
            )
        shadows = [s for s in present[1:] if not _is_leftover(s, record)]
        stored = dataclasses.replace(
            stored,
            shadows=tuple(
                p.name for s in shadows for p in s.files if p.is_file() and not p.name.endswith(".tmp")
            ),
            record_problem=record.problem,
        )
        replaced = [s for s in present if s.files[0] != self.path and s not in shadows]
        return stored, record, replaced

    def _record(self, *, keep_order_blind: bool = False) -> _Record:
        """The record of the wiring saved here. Missing, or a file that will
        not read, is a record with a problem: it trusts nothing.

        What `settle_record` recorded but could not write stands in for the
        file for the rest of this run. A digest blind to declaration order is
        dropped, with the pending save beside it, before anything compares
        it: only the first start keeps one (`keep_order_blind`, `_carried_over`)."""
        if self._unwritten is not None:
            return self._unwritten
        record = self._record_on_disk()
        if keep_order_blind or not _order_blind_in(record):
            return record
        return dataclasses.replace(record, digest=None, pending=None)

    def _record_on_disk(self) -> _Record:
        try:
            raw = self.confirmed_path.read_bytes()
        except FileNotFoundError:
            return _Record(
                problem=f"{CONFIRMED_FILENAME}, the record of the wiring saved on this machine, is missing",
                missing=True,
            )
        except OSError as exc:
            log.error("%s will not read (%s): every stored wiring is held", CONFIRMED_FILENAME, exc)
            return _Record(problem=f"{CONFIRMED_FILENAME}, the record of the wiring saved on this machine, will not read ({exc})")
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "digest" not in data and isinstance(data.get("digests"), list):
                earlier = data["digests"]
                if not all(isinstance(d, str) for d in earlier):
                    raise TypeError("digests are not strings")
                return _Record(
                    problem=f"{CONFIRMED_FILENAME}, the record of the wiring saved on this "
                    "machine, is in an earlier build's shape",
                    earlier=frozenset(earlier),
                )
            digest, pending = data["digest"], data.get("pending")
            leftovers = data.get("leftovers", [])
            if not all(isinstance(d, str) for d in (*[x for x in (digest, pending) if x is not None], *leftovers)):
                raise TypeError("digests are not strings")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            log.error("%s will not read (%s): every stored wiring is held", CONFIRMED_FILENAME, exc)
            return _Record(problem=f"{CONFIRMED_FILENAME}, the record of the wiring saved on this machine, will not read ({exc})")
        return _Record(digest, pending, frozenset(leftovers))

    def _write_record(self, record: _Record) -> None:
        self.confirmed_path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.confirmed_path, record.to_json())
        self._unwritten = None

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

        A save records the wiring as the last saved here, in an order no crash
        can turn into trusting wiring nobody saved, or a wiring it replaced:

          1. record the new digest as PENDING beside the last one;
          2. write `wiring.json` (the commit);
          3. remove the older layouts it replaces -- never a shadow;
          4. record the new digest alone, and as leftovers any file of step 3
             that would not go, so the next save removes it. A leftover is
             never trusted: with `wiring.json` gone it is held.

        A failure at 1 writes nothing; at 2, the previous wiring is still the
        one recorded; after 2 the save has landed, step 4 is logged if it fails,
        and `settle_record` finishes it at the next start.
        """
        problems = save_problems(doc)
        if problems:
            raise RigInvalid(problems)

        stored = dict(doc)
        stored["edited_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        new = content_digest(stored)
        _, record, replaced = self._survey()
        self._write_record(_Record(record.digest, new, record.leftovers))
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            _write_atomic(self.path, json.dumps(stored, indent=2) + "\n")
        except Exception:
            # Not committed: the wiring recorded before is still the last saved.
            try:
                self._write_record(_Record(record.digest, None, record.leftovers))
            except OSError as exc:
                log.warning("could not put back the record after a failed save (%s)", exc)
            raise
        # Only once the new file is whole: an older layout left behind by a
        # failure here is harmless, because `wiring.json` wins over it.
        self._remove(p for layout in replaced for p in layout.files)
        # A file that would not go is this save's own leftover: recorded by
        # its bytes (half a pair has no content digest of its own), so it is
        # never shown as a copy and the next save removes it.
        left = frozenset(_file_digest(p) for layout in replaced for p in layout.files if p.is_file())
        try:
            self._write_record(_Record(new, None, left))
        except OSError as exc:
            log.warning("%s was saved, but recording it failed (%s)", WIRING_FILENAME, exc)
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
        self._write_record(_Record())
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


#: The prefix of a digest that covers channel declaration order.
_ORDERED = "o1:"
#: A pending save carried over from an order-blind record that matched
#: nothing: a save that did not finish, matching no file ever.
_UNFINISHED = _ORDERED + "unfinished"


def content_digest(doc: dict) -> str:
    """What `wiring-confirmed.json` records: the wiring's content, without
    `edited_at`, so identical wiring written at another moment is the same
    wiring. Taken over the document AS STORED, never after `upgrade`: a later
    release that fills one more default must not hold every untouched file.

    DECLARATION ORDER IS CONTENT. `channels` is a JSON object, and a sorted
    dump would make two orders one digest -- but the order is the odor index
    (TASKS.md#order-is-meaning), so channels swapped by hand would load as
    confirmed and drive the wrong valve under the right code. The order is
    hashed beside the sorted content."""
    content = {k: v for k, v in doc.items() if k != "edited_at"}
    channels = doc.get("channels")
    order = list(channels) if isinstance(channels, dict) else None
    canonical = json.dumps({"order": order, "content": content}, sort_keys=True, separators=(",", ":"))
    return _ORDERED + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def order_blind_digest(doc: dict) -> str:
    """The digest the record held before it covered declaration order. Read
    only, to carry a record over (`HardwareStore.settle_record`)."""
    content = {k: v for k, v in doc.items() if k != "edited_at"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _order_blind(digest: str | None) -> bool:
    return digest is not None and not digest.startswith((_ORDERED, "file:"))


def _order_blind_in(record: _Record) -> bool:
    """Whether `record` holds a digest in the order-blind form."""
    return _order_blind(record.digest) or _order_blind(record.pending)


def _digest_of(doc: dict | None) -> str | None:
    return None if doc is None else content_digest(doc)


def _blind_of(doc: dict | None) -> str | None:
    return None if doc is None else order_blind_digest(doc)


def _file_digest(path: Path) -> str:
    """A leftover file's own record entry: its bytes, not its content."""
    return "file:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _is_leftover(layout: _Layout, record: _Record) -> bool:
    """A layout beside the one read is the app's own leftover: every file of
    it is one the record lists (`_Record.leftovers`)."""
    files = [p for p in layout.files if p.is_file()]
    try:
        return bool(files) and all(_file_digest(p) in record.leftovers for p in files)
    except OSError:
        return False


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
    digest, blind = content_digest(doc), order_blind_digest(doc)
    doc = upgrade(doc)
    try:
        import jsonschema  # noqa: F401
    except ImportError:  # pragma: no cover - the dependency fence: compose as before
        return Stored(doc, [], "loads", sources, digest=digest, order_blind=blind)
    shape = validate(doc) or _unpinned(doc)
    if shape:
        where, what = shape[0]
        return Stored(doc, [_unloaded(location, f"{where}: {what}")], "invalid", sources, digest=digest, order_blind=blind)
    from ephymeris_sidecar.rig.rules import rule_problems

    rules = rule_problems(doc)
    if rules:
        code, where, what = rules[0]
        return Stored(doc, [_unloaded(location, f"{code} {where}: {what}")], "invalid", sources, digest=digest, order_blind=blind)
    return Stored(doc, [], "loads", sources, digest=digest, order_blind=blind)


def save_problems(doc: Any) -> list[tuple[str, str]]:
    """Why `save` would refuse this document: its shape, then a channel with
    no pin. Checked by the rig definition before it issues any edge code."""
    return validate(doc) or (_unpinned(doc) if isinstance(doc, dict) else [])


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

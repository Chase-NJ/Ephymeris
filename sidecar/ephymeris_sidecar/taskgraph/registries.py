"""The three frozen registries: strobes, channels, limits.

Loaded once, immutable, and shared by the compiler, the linter and the code
generators. Each mirrors a JSON file under schema/ and nothing here invents a
value -- if a number is not in schema/, it does not exist.

That discipline is the whole point. START_LINE_MAX is mirrored across two repos
with nothing keeping it in sync, and baudRate across nine files; both are
documented hazards. The moment this module hard-codes a limit "just for the
compiler", it becomes the next instance.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

# Re-exported: `specs/compiler.py` and several rules import SCHEMA_DIR from here.
from .paths import HARDWARE_DIR, SCHEMA_DIR  # noqa: F401

#: The first byte value `lower.py` reserves for a runtime-bound channel
#: (`CH_BIND_BASE`). A pin at or above this is encoded identically to
#: "@stim[0].emitter" and is read as one by the board.
#:
#: DUPLICATED HERE ON PURPOSE, and it is the lesser of two evils: `table.py`
#: imports `graph.py`, and importing it back would make a cycle. TG227's message
#: names the number so a mismatch is visible, and `test_registries` pins the two
#: together so it cannot drift silently.
CH_BIND_RESERVED_FROM = 0xF0


def _load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text())


def active_pinout_id() -> str:
    """Which SHIPPED pinout this build falls back to.

    This used to be the whole answer, and its docstring said so: "a BUILD-TIME
    choice, not a runtime setting". A rig can now carry its own wiring
    (`set_rig_source`), so the shipped pinout is the default rather than the
    decision -- what survives from that reasoning is the constraint that made it
    true. Pin numbers end up inside the packed table, so ONE wiring is in force
    at a time and changing it clears the cache; a rig running two box
    generations at once would still need per-box compilation rather than a
    switch. `$EPHYMERIS_PINOUT` still selects among the shipped ones for tests.
    """
    override = os.environ.get("EPHYMERIS_PINOUT")
    if override:
        return override
    return json.loads((HARDWARE_DIR / "_default.json").read_text())["pinout"]


def _pinout() -> dict:
    return json.loads((HARDWARE_DIR / f"{active_pinout_id()}.json").read_text())


# --------------------------------------------------------------------------- #
# Strobes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StrobeEntry:
    name: str
    code: int
    origin: str
    rationale: str
    emitted_by: tuple[str, ...] = ()


class Vocabulary:
    """The append-only strobe registry.

    Resolution is by NAME, always. Codes are non-contiguous and non-patterned
    (101-106, then 221-226, 233-234, 242-258, 357, 369), so anything that computes
    a code rather than looking it up is wrong by construction.
    """

    def __init__(self, raw: dict) -> None:
        self.version: int = raw["vocab_version"]
        self.code_max: int = raw["code_max"]
        self.free_ranges: list[tuple[int, int]] = [tuple(r) for r in raw["free_ranges"]]
        self._by_name: dict[str, StrobeEntry] = {
            name: StrobeEntry(
                name=name,
                code=e["code"],
                origin=e.get("origin", "firmware"),
                rationale=e.get("rationale", ""),
                emitted_by=tuple(e.get("emitted_by", ())),
            )
            for name, e in raw["codes"].items()
        }
        self._by_code = {e.code: e for e in self._by_name.values()}
        #: Codes emitted by firmware this repo no longer contains. NOT in `codes`
        #: -- nothing can produce them any more, and the vocabulary's rule is that
        #: a declared code has a mechanism that emits it -- and NOT free, because
        #: reissuing one would silently merge two unrelated event types in any
        #: analysis spanning the boundary.
        self._retired = {
            e["code"]: name
            for name, e in raw.get("retired", {}).items()
            if isinstance(e, dict) and "code" in e
        }
        #: Slot number -> its six per-port code names. Keys arrive as JSON
        #: strings; they are the one thing here that is genuinely numeric, since
        #: a channel declares `port_slot: 3` as an integer.
        self._slots: dict[int, dict[str, str]] = {
            int(slot): dict(fields)
            for slot, fields in raw.get("port_slots", {}).items()
            if not slot.startswith("_") and isinstance(fields, dict)
        }

    def retired_name(self, code: int) -> str | None:
        return self._retired.get(code)

    @property
    def retired(self) -> dict[int, str]:
        return dict(self._retired)

    def __contains__(self, name: object) -> bool:
        return name in self._by_name

    def __iter__(self):
        return iter(self._by_name.values())

    def get(self, name: str) -> StrobeEntry | None:
        return self._by_name.get(name)

    def code_of(self, name: str) -> int:
        return self._by_name[name].code

    def name_of(self, code: int) -> str | None:
        e = self._by_code.get(code)
        return e.name if e else None

    def names(self) -> set[str]:
        return set(self._by_name)

    def port_slot(self, slot: int) -> dict[str, str] | None:
        """The six per-port code names a response port on `slot` reports with.

        THE REASON THIS TABLE EXISTS. The mapping used to be derived from the
        channel's NAME, in two hand-mirrored places: `_SIDE = {"left_well": "_L",
        "right_well": "_R"}` in paradigms.py and a matching `sideSuffix()` in
        operations.ts. Both returned nothing for a channel called anything else,
        so a box whose wells were named differently got a port with no codes at
        all -- silently, because every field is individually optional.

        Slots 1 and 2 are the historical `_L`/`_R` families, so a recorded
        session decodes exactly as it always did.
        """
        return self._slots.get(int(slot))

    @property
    def port_slots(self) -> dict[int, dict[str, str]]:
        return {n: dict(fields) for n, fields in self._slots.items()}


# --------------------------------------------------------------------------- #
# Channels
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Channel:
    name: str
    index: int          # the Arduino pin number -- from the PINOUT
    direction: str      # "in" | "out" -- from the kind, not the channel
    kind: str           # engagement | response | emitter | reward | cue | vacuum
    watch_bit: int | None = None   # position in TgNode.watchMask, watchable channels only
    well: str | None = None        # reward lines declare which port they serve
    port_slot: int | None = None   # response ports: which strobe family they report with
    rationale: str = ""            # what the channel means
    pin_note: str = ""             # why THIS pin, when there is anything to say
    pin_source: str = ""           # the BehaviorBox.h line the number came from

    @property
    def watchable(self) -> bool:
        return self.watch_bit is not None


class ChannelMap:
    """Name -> pin index, direction and kind, composed from two files.

    WHAT a channel is (`kind`, `well`, the prose) comes from schema/channels.v1.json;
    WHERE it is (`index`, `watch_bit`, provenance) comes from the active pinout under
    hardware/. Composing them here rather than downstream is what lets the split cost
    nothing: `Channel` gained three optional fields and every consumer -- the lowerer,
    the bench card, the listing, TG223/224/225, the templates -- is unchanged.

    The engagement channel and the trial light are resolved BY KIND, not by name.
    No spec names either one -- they are structural facts of the epoch model, not
    per-task choices -- so the template asks for "the engagement channel" and this
    is what answers.

    A channel present in one file and not the other is NOT resolved here. It is
    reported by TG226, because the two files describing different boxes is a
    configuration error the operator has to see, not a KeyError from a lowerer.
    """

    def __init__(self, raw: dict, pinout: dict) -> None:
        self.version: int = raw["channels_version"]
        self.kinds: dict[str, str] = {k: v["doc"] for k, v in raw["kinds"].items()}
        self.pinout_id: str = pinout["pinout_id"]
        self.pinout_version: int = pinout["pinout_version"]
        self.board: str = pinout["board"]
        self.pinout_source: str = pinout.get("transcribed_from", "")
        #: The board's own pin range, so TG227 can say "a Mega has 0-53" rather
        #: than quoting an encoding constant at an operator. Declared by the
        #: pinout because it is a fact about the board, not about the compiler.
        pin_range = pinout.get("pin_range") or {}
        self.pin_min: int = int(pin_range.get("min", 0))
        self.pin_max: int = int(pin_range.get("max", CH_BIND_RESERVED_FROM - 1))

        pins = pinout["pins"]
        self._logical = raw
        self._pins = pins
        self._by_name: dict[str, Channel] = {
            name: Channel(
                name=name,
                index=pins[name]["index"],
                direction=raw["kinds"][c["kind"]]["direction"],
                kind=c["kind"],
                watch_bit=pins[name].get("watch_bit"),
                well=c.get("well"),
                port_slot=c.get("port_slot"),
                rationale=c.get("rationale", ""),
                pin_note=pins[name].get("note", ""),
                pin_source=pins[name].get("source", ""),
            )
            for name, c in raw["channels"].items()
            if name in pins
        }

    def disagreements(self) -> list[tuple[str, str]]:
        """(location, message) for every way the two files fail to describe one box.

        Returned rather than raised so TG226 can report all of them at once with
        real locations; a compiler that stopped at the first would make fixing a
        new pinout a game of whack-a-mole.
        """
        out: list[tuple[str, str]] = []
        logical = set(self._logical["channels"])
        physical = set(self._pins)
        for name in sorted(logical - physical):
            out.append((
                f"hardware/{self.pinout_id}.json",
                f"channel {name!r} is declared in the channel registry but the "
                f"active pinout {self.pinout_id!r} gives it no pin",
            ))
        for name in sorted(physical - logical):
            out.append((
                "schema/channels.v1.json",
                f"the pinout {self.pinout_id!r} assigns a pin to {name!r}, which "
                "the channel registry does not declare",
            ))
        # watch_bit must be dense and 0-based over exactly the watchable channels,
        # because it indexes a uint8 mask. A gap silently misaddresses the mask.
        bits = sorted(c.watch_bit for c in self._by_name.values() if c.watchable)
        if bits != list(range(len(bits))):
            out.append((
                f"hardware/{self.pinout_id}.json",
                f"watch_bit must be dense and 0-based over the watchable channels; "
                f"got {bits}. TgNode.watchMask is a bit position, so a gap "
                "addresses the wrong channel rather than none.",
            ))
        return out

    def pin_problems(self) -> list[tuple[str, str]]:
        """TG227: a pin index that is not a pin on this board.

        UNGUARDED UNTIL NOW, because nobody could type one -- the pinout was a
        transcription of BehaviorBox.h that shipped inside the package. It stops
        being safe the moment an operator edits it, and the two bounds fail
        differently:

        `CH_BIND_BASE` (0xF0) is the hard one. `lower.py::channel_index` encodes
        runtime-bound channels in the same byte as a pin, relying on pins staying
        low enough that the high range is free. A pin at or above it is not
        rejected downstream -- it is read as "@stim[0].emitter" by the board.

        The board's own maximum is the useful one: pin 54 on a Mega is a typo,
        not a subtle encoding bug, and saying so beats letting it reach a table.
        """
        out: list[tuple[str, str]] = []
        where = f"hardware/{self.pinout_id}.json"
        for c in sorted(self._by_name.values(), key=lambda c: c.name):
            if not isinstance(c.index, int) or isinstance(c.index, bool):
                out.append((where, f"{c.name!r} has a non-integer pin {c.index!r}"))
            elif c.index >= CH_BIND_RESERVED_FROM:
                out.append((
                    where,
                    f"{c.name!r} is on pin {c.index}, which collides with the "
                    f"runtime-binding range (>= {CH_BIND_RESERVED_FROM}). A pin there is "
                    "not refused by the board, it is read as a per-trial binding.",
                ))
            elif not (self.pin_min <= c.index <= self.pin_max):
                out.append((
                    where,
                    f"{c.name!r} is on pin {c.index}; {self.board} has pins "
                    f"{self.pin_min}-{self.pin_max}.",
                ))
        return out

    def duplicate_pins(self) -> list[tuple[str, str]]:
        """TG228: two channels on one pin.

        Also unguarded until now, and it is not always wrong on real hardware --
        but it is always wrong HERE, because `watch_port` inverts pin to port and
        the listing's bench card reverse-maps pin to name. Two names on one pin
        makes both lookups pick one arbitrarily.
        """
        seen: dict[int, list[str]] = {}
        for c in self._by_name.values():
            if isinstance(c.index, int) and not isinstance(c.index, bool):
                seen.setdefault(c.index, []).append(c.name)
        return [
            (
                f"hardware/{self.pinout_id}.json",
                f"pin {pin} is assigned to {', '.join(sorted(names))}. The bench card "
                "and the watch table both map a pin back to one channel, so a shared "
                "pin makes that answer arbitrary.",
            )
            for pin, names in sorted(seen.items())
            if len(names) > 1
        ]

    def slot_problems(self, vocab: "Vocabulary") -> list[tuple[str, str]]:
        """TG229: a response channel whose strobe slot does not resolve.

        A port with no slot is the failure the slot table was built to end: it
        used to happen by NAME, silently, to any well not called `left_well` or
        `right_well`, and produced a port with no per-port codes that compiled
        fine until a shape change made TG506 reach for them.
        """
        out: list[tuple[str, str]] = []
        where = "schema/channels.v1.json"
        by_slot: dict[int, list[str]] = {}
        for c in sorted(self.of_kind("response"), key=lambda c: c.name):
            if c.port_slot is None:
                out.append((
                    where,
                    f"response channel {c.name!r} declares no `port_slot`, so it has no "
                    "strobes to report a poke, an error, a broken hold or an exit with.",
                ))
                continue
            if vocab.port_slot(c.port_slot) is None:
                out.append((
                    where,
                    f"response channel {c.name!r} is on port slot {c.port_slot}, which the "
                    f"strobe vocabulary does not define. It declares slots "
                    f"{sorted(vocab.port_slots)}.",
                ))
            by_slot.setdefault(c.port_slot, []).append(c.name)
        for slot, names in sorted(by_slot.items()):
            if len(names) > 1:
                out.append((
                    where,
                    f"port slot {slot} is claimed by {', '.join(sorted(names))}. Two ports "
                    "reporting with one set of codes are indistinguishable in the data.",
                ))
        return out

    def content_hash(self) -> str:
        """SHA-256 over the wiring that can change a compiled byte, truncated.

        THE POINT: `spec_hash` covers the spec document, which names channels and
        never numbers (D15). So re-wiring a box changes what every task compiles
        to and moves no spec_hash -- correct, and a provenance hole the moment a
        rig can be re-wired, because two sessions recorded as the same task ran
        different valves with nothing in the record to tell them apart.

        BEHAVIOURAL FIELDS ONLY. Prose, pin notes and provenance strings are
        excluded, and that is a decision rather than an oversight: this hash
        answers "could these two produce different bytes?", so a rationale
        someone reworded must not move it. A hash that changed on a typo fix
        would train people to ignore it.

        `direction` rides along because it comes from the kind, and a kind
        change moves it -- a reward line that became an input is a real
        difference even though no pin moved.
        """
        import hashlib

        payload = [
            [c.name, c.kind, c.direction, c.index, c.watch_bit, c.well, c.port_slot]
            for c in sorted(self._by_name.values(), key=lambda c: c.name)
        ]
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def to_json(self) -> dict:
        """The composed view, in the shape the raw file used to have.

        Served to the frontend so its pickers keep reading one object with `kind`,
        `well` and `index` on it. Serving the resolved object rather than one of
        its two inputs also strengthens the guarantee the raw file was serving:
        a picker cannot offer a channel the compiler would then fail to place.
        """
        return {
            "channels_version": self.version,
            "pinout": {
                "id": self.pinout_id,
                "version": self.pinout_version,
                "board": self.board,
                "source": self.pinout_source,
            },
            "kinds": self._logical["kinds"],
            "channels": {
                c.name: {
                    "kind": c.kind,
                    "index": c.index,
                    "direction": c.direction,
                    **({"watch_bit": c.watch_bit} if c.watchable else {}),
                    **({"well": c.well} if c.well else {}),
                    **({"port_slot": c.port_slot} if c.port_slot else {}),
                    **({"rationale": c.rationale} if c.rationale else {}),
                    **({"note": c.pin_note} if c.pin_note else {}),
                    **({"source": c.pin_source} if c.pin_source else {}),
                }
                for c in self._by_name.values()
            },
        }

    def __contains__(self, name: object) -> bool:
        return name in self._by_name

    def __iter__(self):
        return iter(self._by_name.values())

    def get(self, name: str) -> Channel | None:
        return self._by_name.get(name)

    def names(self) -> set[str]:
        return set(self._by_name)

    def of_kind(self, kind: str) -> list[Channel]:
        return sorted(
            (c for c in self._by_name.values() if c.kind == kind), key=lambda c: c.index
        )

    def unique_of_kind(self, kind: str) -> Channel | None:
        """The single channel of a kind, or None if there is not exactly one.

        Returning None on ambiguity rather than picking the first is deliberate:
        two engagement ports is a registry bug, and silently choosing one would
        route every trial through whichever happened to sort first.
        """
        found = self.of_kind(kind)
        return found[0] if len(found) == 1 else None

    @property
    def watchable(self) -> list[Channel]:
        return sorted(
            (c for c in self._by_name.values() if c.watchable), key=lambda c: c.watch_bit
        )

    def watch_mask(self, names: list[str]) -> int:
        mask = 0
        for n in names:
            c = self._by_name[n]
            if c.watch_bit is None:
                raise KeyError(f"channel {n!r} is not watchable")
            mask |= 1 << c.watch_bit
        return mask


# --------------------------------------------------------------------------- #
# Limits
# --------------------------------------------------------------------------- #


class Limits:
    """Capacity, protocol and wire constants.

    Flattened from schema/limits.v1.json's groups, because callers want
    `limits.TG_MAX_STATES` and do not care which section it was filed under. The
    grouping exists for the generated header's readability.
    """

    def __init__(self, raw: dict) -> None:
        self.version: int = raw["limits_version"]
        self._raw = raw
        self._values: dict[str, int] = {}
        self._rationale: dict[str, str] = {}
        for group, entries in raw.items():
            if not isinstance(entries, dict) or group.startswith("_") or group == "limits_version":
                continue
            for key, entry in entries.items():
                if key.startswith("_") or not isinstance(entry, dict):
                    continue
                self._values[key] = entry["value"]
                r = entry.get("rationale", "")
                self._rationale[key] = "\n".join(r) if isinstance(r, list) else r

    def __getattr__(self, name: str) -> int:
        try:
            return self.__dict__["_values"][name]
        except KeyError as exc:
            raise AttributeError(
                f"{name} is not defined in schema/limits.v1.json. Add it there "
                f"rather than hard-coding it -- see that file's readme."
            ) from exc

    def __contains__(self, name: object) -> bool:
        return name in self._values

    def rationale(self, name: str) -> str:
        return self._rationale.get(name, "")

    def groups(self) -> dict:
        return self._raw


# --------------------------------------------------------------------------- #
# Accessors
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def vocabulary() -> Vocabulary:
    return Vocabulary(_load("strobe_vocab.v1.json"))


#: The rig's own wiring document, when it has one. Set once at startup and again
#: after every write by `hardware.store`, via `set_rig_source`.
#:
#: A MODULE-LEVEL INJECTION POINT rather than a parameter, because `channels()`
#: is called from the compile hot path with no argument and threading one through
#: would touch every caller for a value that changes about twice a year. It is the
#: same shape `$EPHYMERIS_PINOUT` already had, better typed.
_rig_source: Callable[[], dict | None] | None = None


def current_rig_source() -> Callable[[], dict | None] | None:
    """Whatever is installed, so a caller can put it back.

    `impact_of` installs a HYPOTHETICAL wiring to answer "what would this
    break?", and leaving it installed would mean a preview silently changed
    what the app compiles.
    """
    return _rig_source


def set_rig_source(source: Callable[[], dict | None] | None) -> None:
    """Point the registries at the rig's wiring, and drop what they cached.

    CLEARING HERE, AND ONLY HERE, IS THE POINT. `channels()` is `lru_cache`d and
    is called on every keystroke compile, so it cannot become uncached; and the
    obvious place to hang invalidation — `settings.push` — fires on every
    reconnect, which would throw the compiler's registries away several times a
    session for no reason. A rig document changes when someone saves one.
    """
    global _rig_source
    _rig_source = source
    channels.cache_clear()


@lru_cache(maxsize=1)
def channels() -> ChannelMap:
    """The composed channel map: what each channel means, and where it is.

    A rig document REPLACES the shipped pair rather than merging with it. A
    merge would mean a channel the operator deleted came back, and there would
    be no way to describe a box that lacks one.
    """
    rig = _rig_source() if _rig_source is not None else None
    if rig is not None:
        try:
            return ChannelMap(*_split_rig(rig))
        except (KeyError, TypeError) as exc:
            # A rig document that got past the schema and still cannot compose
            # is a bug, not an operator error -- but falling back to a working
            # rig beats refusing to start with six serial ports open.
            import logging

            logging.getLogger(__name__).warning(
                "rig document could not be composed (%s); using the shipped pinout", exc
            )
    return ChannelMap(_load("channels.v1.json"), _pinout())


def _split_rig(rig: dict) -> tuple[dict, dict]:
    """One rig document -> the (logical, pinout) pair `ChannelMap` composes.

    The two halves are stored together because an operator edits them together,
    and split here because keeping them apart is what makes TG226 writable at
    all. Nothing is invented: `kinds` comes from the shipped registry, since a
    kind's direction is a property of the model rather than of a rig.
    """
    shipped = _load("channels.v1.json")
    logical = {
        "channels_version": shipped["channels_version"],
        "kinds": shipped["kinds"],
        "channels": rig["channels"],
    }
    pinout = {
        "pinout_id": rig.get("derived_from") or "rig",
        "pinout_version": int(rig.get("rig_version", 1)),
        "board": rig.get("board", ""),
        "transcribed_from": "<data_dir>/hardware/rig.json",
        "pins": rig["pins"],
        **({"pin_range": rig["pin_range"]} if rig.get("pin_range") else {}),
    }
    return logical, pinout


@lru_cache(maxsize=1)
def limits() -> Limits:
    return Limits(_load("limits.v1.json"))

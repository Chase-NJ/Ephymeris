"""The two frozen registries: strobes and channels.

Loaded once, cached, and shared by the rig wiring editor and the task-profile
code generator. Each mirrors a JSON file under `schema/`, and nothing here
invents a value -- if a number is not in `schema/` or in the active pinout, it
does not exist.

That discipline is the whole point. `START_LINE_MAX` is mirrored across two
repositories with nothing keeping it in sync and `baudRate` across nine files;
both are documented hazards. The moment this module hard-codes a pin or a code
"just for now", it becomes the next instance.

Resolution is BY NAME, always -- for both registries. Strobe codes are
non-contiguous and non-patterned (101-109 and 114-116, then 221-226, 233-234,
242-258, 262, 357, 369), and pins are whatever the box was wired to, so anything
that COMPUTES either rather than looking it up is wrong by construction. The odor
onsets are the sharpest case: odor 9 is 109 and odor 10 is 114, because 110-113
are retired codes 29 recorded sessions contain.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from .paths import HARDWARE_DIR, SCHEMA_DIR  # noqa: F401  (re-exported)

log = logging.getLogger(__name__)


def _load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def active_pinout_id() -> str:
    """Which SHIPPED pinout this build falls back to.

    A rig can carry its own wiring (`set_rig_source`), so the shipped pinout is
    the default rather than the decision. What survives from the era when it was
    the whole answer is the constraint that made it true: pin numbers are baked
    into the firmware a task profile compiles to, so ONE wiring is in force at a
    time and changing it invalidates every generated sketch.
    `$EPHYMERIS_PINOUT` still selects among the shipped ones for tests.
    """
    override = os.environ.get("EPHYMERIS_PINOUT")
    if override:
        return override
    return json.loads((HARDWARE_DIR / "_default.json").read_text(encoding="utf-8"))["pinout"]


def _pinout() -> dict:
    return json.loads((HARDWARE_DIR / f"{active_pinout_id()}.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Strobes
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StrobeEntry:
    name: str
    code: int
    origin: str
    rationale: str
    emitted_on: str = ""
    emitted_by: tuple[str, ...] = ()


class Vocabulary:
    """The append-only strobe registry.

    APPEND-ONLY IS A DATA GUARANTEE, not a style. Tens of thousands of recorded
    events carry these numbers, so a code is never renumbered and never
    repurposed -- reissuing one would silently merge two unrelated event types in
    any analysis spanning the change. New codes come from `free_ranges`; codes
    whose emitter is gone move to `retired` and stay reserved forever.
    """

    def __init__(self, raw: dict) -> None:
        self.version: int = raw["vocab_version"]
        self.code_min: int = raw.get("code_min", 0)
        self.code_max: int = raw["code_max"]
        self.free_ranges: list[tuple[int, int]] = [tuple(r) for r in raw["free_ranges"]]
        self._by_name: dict[str, StrobeEntry] = {
            name: StrobeEntry(
                name=name,
                code=e["code"],
                origin=e.get("origin", "firmware"),
                rationale=e.get("rationale", ""),
                emitted_on=e.get("emitted_on", ""),
                emitted_by=tuple(e.get("emitted_by", ())),
            )
            for name, e in raw["codes"].items()
        }
        self._by_code = {e.code: e for e in self._by_name.values()}
        #: Codes emitted by firmware this repository no longer contains. NOT in
        #: `codes` -- nothing can produce them any more -- and NOT free, because
        #: reissuing one would merge two event types in any analysis spanning the
        #: boundary. This is the third state, and it is why `is_free()` below
        #: consults both.
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

    def is_free(self, code: int) -> bool:
        """Whether `code` may be issued to a new name.

        Three conditions, and dropping any one of them reissues a number that is
        already in the archive: it must fall inside a declared free range, it
        must not already be taken, and it must not be retired.
        """
        if code in self._by_code or code in self._retired:
            return False
        return any(lo <= code <= hi for lo, hi in self.free_ranges)

    def next_free(self) -> int | None:
        """The lowest issuable code, for an editor that offers one."""
        for lo, hi in self.free_ranges:
            for code in range(lo, hi + 1):
                if self.is_free(code):
                    return code
        return None

    def port_slot(self, slot: int) -> dict[str, str] | None:
        """The six per-port code names a response port on `slot` reports with.

        THE REASON THIS TABLE EXISTS. The mapping used to be derived from the
        channel's NAME, in two hand-mirrored places, and both returned nothing
        for a channel called anything else -- so a box whose wells were named
        differently got a port with no codes at all, silently, because every
        field is individually optional.

        Slots 1 and 2 are the historical `_L`/`_R` families, so a recorded
        session decodes exactly as it always did.
        """
        return self._slots.get(int(slot))

    @property
    def port_slots(self) -> dict[int, dict[str, str]]:
        return {n: dict(fields) for n, fields in self._slots.items()}

    def to_json(self) -> dict:
        """The whole vocabulary, for the Rig tab's viewer.

        Retired codes ride along as their own section rather than being folded
        into `codes`: a reader looking at a legacy session needs to be told
        "retired", which is an explanation, rather than "unknown", which is a
        question.
        """
        return {
            "version": self.version,
            "codeMin": self.code_min,
            "codeMax": self.code_max,
            "freeRanges": [list(r) for r in self.free_ranges],
            "codes": [
                {
                    "name": e.name,
                    "code": e.code,
                    "origin": e.origin,
                    **({"emittedOn": e.emitted_on} if e.emitted_on else {}),
                    **({"rationale": e.rationale} if e.rationale else {}),
                }
                for e in sorted(self._by_name.values(), key=lambda e: e.code)
            ],
            "retired": [
                {"name": name, "code": code}
                for code, name in sorted(self._retired.items())
            ],
            "portSlots": {str(n): dict(f) for n, f in sorted(self._slots.items())},
        }


# --------------------------------------------------------------------------- #
# Channels
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Channel:
    name: str
    index: int          # the Arduino pin number -- from the PINOUT
    direction: str      # "in" | "out" -- from the kind, not the channel
    kind: str           # engagement | response | emitter | reward | cue | vacuum
    watch_bit: int | None = None   # dense 0-based index over the watchable channels
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

    WHAT a channel is (`kind`, `well`, the prose) comes from
    `schema/channels.v1.json`; WHERE it is (`index`, `watch_bit`, provenance)
    comes from the active pinout under `hardware/`. Composing them here rather
    than downstream is what lets the split cost nothing -- a box generation is a
    one-file swap, and every consumer is unchanged, provided the channel NAMES
    are the same. That is exactly what resolving by name buys.

    The engagement port, the trial cue and the vacuum are resolved BY KIND, not
    by name: they are structural facts of the box rather than per-task choices,
    so a caller asks for "the engagement channel" and this is what answers.

    A channel present in one file and not the other is NOT resolved here. It is
    reported by `disagreements()`, because two files describing different boxes
    is a configuration error the operator has to see, not a KeyError from
    whatever asked next.
    """

    def __init__(self, raw: dict, pinout: dict) -> None:
        self.version: int = raw["channels_version"]
        self.kinds: dict[str, str] = {k: v["doc"] for k, v in raw["kinds"].items()}
        self.pinout_id: str = pinout["pinout_id"]
        self.pinout_version: int = pinout["pinout_version"]
        self.board: str = pinout["board"]
        self.pinout_source: str = pinout.get("transcribed_from", "")
        #: The FILE a pin problem should point at. A rig document composes into
        #: the same pair as the shipped files, so without this every diagnostic
        #: on a rig's own wiring named `hardware/<shipped>.json` -- a file the
        #: operator cannot edit and did not touch.
        self.pins_source: str = pinout.get("source_label") or f"hardware/{self.pinout_id}.json"
        self.channels_source: str = raw.get("source_label") or "schema/channels.v1.json"
        #: The board's own pin range, declared by the pinout because it is a fact
        #: about the board. It is what lets a diagnostic say "a Mega has pins
        #: 0-53" rather than quoting a constant at an operator.
        pin_range = pinout.get("pin_range") or {}
        self.pin_min: int = int(pin_range.get("min", 0))
        self.pin_max: int = int(pin_range.get("max", 53))

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
        """(location, message) for every way the two halves fail to describe one box.

        Returned rather than raised so all of them can be reported at once with
        real locations; stopping at the first would make fixing new wiring a game
        of whack-a-mole.
        """
        out: list[tuple[str, str]] = []
        logical = set(self._logical["channels"])
        physical = set(self._pins)
        for name in sorted(logical - physical):
            out.append((
                self.pins_source,
                f"channel {name!r} is declared in the channel registry but the "
                f"active pinout {self.pinout_id!r} gives it no pin",
            ))
        for name in sorted(physical - logical):
            out.append((
                self.channels_source,
                f"the pinout {self.pinout_id!r} assigns a pin to {name!r}, which "
                "the channel registry does not declare",
            ))
        # watch_bit must be dense and 0-based over exactly the watchable
        # channels. It is declared rather than derived so that reordering the
        # pinout cannot silently change what a bit position means.
        bits = sorted(c.watch_bit for c in self._by_name.values() if c.watchable)
        if bits != list(range(len(bits))):
            out.append((
                self.pins_source,
                f"watch_bit must be dense and 0-based over the watchable channels; "
                f"got {bits}. A gap addresses the wrong channel rather than none.",
            ))
        return out

    @staticmethod
    def _at(source: str, channel: str) -> str:
        """`pins.odor_line_1` for a rig document, the file name for a shipped one.

        A rig's problems point at a section an operator can edit; the shipped
        pair's point at a file they cannot, which is the right distinction to
        draw and the reason the label is not just the file either way.
        """
        return f"{source}.{channel}" if "/" not in source else source

    def pin_problems(self) -> list[tuple[str, str]]:
        """A pin index that is not a pin on this board.

        UNGUARDED UNTIL THE WIRING BECAME EDITABLE, because nobody could type
        one -- the pinout was a transcription of `BehaviorBox.h` that shipped
        inside the package. Pin 54 on a Mega is a typo, and saying so beats
        letting it reach a generated sketch, where it compiles fine and simply
        never fires.
        """
        out: list[tuple[str, str]] = []
        # Located on the CHANNEL, not just the file, so it lands on the field the
        # operator is looking at rather than becoming a document-level banner.
        where = lambda name: self._at(self.pins_source, name)  # noqa: E731
        for c in sorted(self._by_name.values(), key=lambda c: c.name):
            if not isinstance(c.index, int) or isinstance(c.index, bool):
                out.append((where(c.name), f"{c.name!r} has a non-integer pin {c.index!r}"))
            elif not (self.pin_min <= c.index <= self.pin_max):
                out.append((
                    where(c.name),
                    f"{c.name!r} is on pin {c.index}; {self.board} has pins "
                    f"{self.pin_min}-{self.pin_max}.",
                ))
        return out

    def duplicate_pins(self) -> list[tuple[str, str]]:
        """Two channels on one pin.

        Not always wrong on real hardware -- but always wrong HERE, because a
        generated sketch drives a channel by pin and the pin table reverse-maps a
        pin back to one name. Two names on one pin makes that answer arbitrary.
        """
        seen: dict[int, list[str]] = {}
        for c in self._by_name.values():
            if isinstance(c.index, int) and not isinstance(c.index, bool):
                seen.setdefault(c.index, []).append(c.name)
        return [
            (
                self.pins_source,
                f"pin {pin} is assigned to {', '.join(sorted(names))}. The pin table "
                "maps a pin back to one channel, so a shared pin makes that answer "
                "arbitrary.",
            )
            for pin, names in sorted(seen.items())
            if len(names) > 1
        ]

    def slot_problems(self, vocab: "Vocabulary") -> list[tuple[str, str]]:
        """A response channel whose strobe slot does not resolve.

        A port with no slot is the failure the slot table was built to end: it
        used to happen by NAME, silently, to any well not called `left_well` or
        `right_well`, and produced a port with no per-port codes -- so a trial
        answered there reported nothing at all.
        """
        out: list[tuple[str, str]] = []
        where = self.channels_source
        by_slot: dict[int, list[str]] = {}
        for c in sorted(self.of_kind("response"), key=lambda c: c.name):
            if c.port_slot is None:
                out.append((
                    self._at(where, c.name),
                    f"response channel {c.name!r} declares no `port_slot`, so it has no "
                    "strobes to report a poke, an error, a broken hold or an exit with.",
                ))
                continue
            if vocab.port_slot(c.port_slot) is None:
                out.append((
                    self._at(where, c.name),
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

        THE POINT: a task profile names channels and never numbers, so re-wiring
        a box changes what every task compiles to and moves no `profile_hash`.
        Correct, and a provenance hole the moment a rig can be re-wired -- two
        sessions recorded as the same task would have driven different valves
        with nothing in the record to tell them apart.

        BEHAVIOURAL FIELDS ONLY. Prose, pin notes and provenance strings are
        excluded, and that is a decision rather than an oversight: this hash
        answers "could these two produce different bytes?", so a rationale
        someone reworded must not move it. A hash that changed on a typo fix
        would train people to ignore it.

        `direction` rides along because it comes from the kind, and a kind change
        moves it -- a reward line that became an input is a real difference even
        though no pin moved.
        """
        payload = [
            [c.name, c.kind, c.direction, c.index, c.watch_bit, c.well, c.port_slot]
            for c in sorted(self._by_name.values(), key=lambda c: c.name)
        ]
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def to_json(self) -> dict:
        """The composed view, in the shape the raw file used to have.

        Served to the frontend so its pickers read one object with `kind`, `well`
        and `index` on it. Serving the resolved object rather than one of its two
        inputs also strengthens the guarantee: a picker cannot offer a channel
        the generator would then fail to place.
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
        """Every channel of a kind, **sorted by pin**.

        For drawing a board and for anything that wants physical order. NOT for
        indexing a firmware table -- see `declared_of_kind`.
        """
        return sorted(
            (c for c in self._by_name.values() if c.kind == kind), key=lambda c: c.index
        )

    def declared_of_kind(self, kind: str) -> list[Channel]:
        """Every channel of a kind, in the order the registry DECLARES them.

        THE ONE TO USE WHEN A POSITION MEANS SOMETHING. `Odors[i]` in the
        firmware is odor line i+1, and the pins behind those lines are not
        monotonic -- 22,24,26,28,30,32 then 23,25,27,29,31,33. So `of_kind`,
        which sorts by pin, returns `odor_line_7` second, and using its position
        as an odor index silently swaps ten of the twelve lines: the sketch
        drives the wrong valve and announces it with the wrong onset code, and
        every trial still looks correct in the record.

        Declaration order is stable because the registry file is a list an
        operator edits, and because a rig document's `channels` map is written
        in that same order by `default_document()`.
        """
        return [c for c in self._by_name.values() if c.kind == kind]

    def unique_of_kind(self, kind: str) -> Channel | None:
        """The single channel of a kind, or None if there is not exactly one.

        Returning None on ambiguity rather than picking the first is deliberate:
        two engagement ports is a wiring bug, and silently choosing one would
        route every trial through whichever happened to sort first.
        """
        found = self.of_kind(kind)
        return found[0] if len(found) == 1 else None

    @property
    def watchable(self) -> list[Channel]:
        return sorted(
            (c for c in self._by_name.values() if c.watchable), key=lambda c: c.watch_bit
        )


# --------------------------------------------------------------------------- #
# Accessors
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def vocabulary() -> Vocabulary:
    return Vocabulary(_load("strobe_vocab.v1.json"))


#: The rig's own wiring document, when it has one. Set once at startup and again
#: after every write by `hardware/store.py`, via `set_rig_source`.
#:
#: A MODULE-LEVEL INJECTION POINT rather than a parameter, because `channels()`
#: is called from paths that have no argument to thread one through, for a value
#: that changes about twice a year. It is the same shape `$EPHYMERIS_PINOUT`
#: already had, better typed.
_rig_source: Callable[[], dict | None] | None = None


def current_rig_source() -> Callable[[], dict | None] | None:
    """Whatever is installed, so a caller can put it back.

    A preview installs a HYPOTHETICAL wiring to answer "what would this break?",
    and leaving it installed would mean a preview silently changed what the app
    generates.
    """
    return _rig_source


def set_rig_source(source: Callable[[], dict | None] | None) -> None:
    """Point the registries at the rig's wiring, and drop what they cached.

    CLEARING HERE, AND ONLY HERE, IS THE POINT. The obvious place to hang
    invalidation -- `settings.push` -- fires on every reconnect, which would
    throw the registries away several times a session for no reason. A rig
    document changes when someone saves one.
    """
    global _rig_source
    _rig_source = source
    channels.cache_clear()


@lru_cache(maxsize=1)
def channels() -> ChannelMap:
    """The composed channel map: what each channel means, and where it is.

    A rig document REPLACES the shipped pair rather than merging with it. A merge
    would mean a channel the operator deleted came back, and there would be no
    way to describe a box that lacks one.
    """
    rig = _rig_source() if _rig_source is not None else None
    if rig is not None:
        try:
            return ChannelMap(*split_rig(rig))
        except (KeyError, TypeError) as exc:
            # A rig document that got past the schema and still cannot compose is
            # a bug, not an operator error -- but falling back to a working rig
            # beats refusing to start with six serial ports open.
            log.warning(
                "rig document could not be composed (%s); using the shipped pinout", exc
            )
    return ChannelMap(_load("channels.v1.json"), _pinout())


def shipped_channels() -> ChannelMap:
    """The shipped pair, ignoring whatever the rig has saved.

    Its own function because `channels()` returns the wiring currently IN FORCE,
    which is the rig's own once one exists -- so seeding a "default" document
    from it would mean "whatever you last saved", and Reset would reset to
    itself. It is also a recursion: `channels()` consults the rig source, and the
    rig source is what asks for a default.
    """
    return ChannelMap(_load("channels.v1.json"), _pinout())


def split_rig(rig: dict) -> tuple[dict, dict]:
    """One rig document -> the (logical, pinout) pair `ChannelMap` composes.

    The two halves are stored together because an operator edits them together,
    and split here because keeping them apart is what makes `disagreements()`
    writable at all. Nothing is invented: `kinds` comes from the shipped
    registry, since a kind's direction is a property of the model rather than of
    a rig.
    """
    shipped = _load("channels.v1.json")
    logical = {
        "channels_version": shipped["channels_version"],
        "kinds": shipped["kinds"],
        "channels": rig["channels"],
        "source_label": "channels",
    }
    pinout = {
        "pinout_id": rig.get("derived_from") or "rig",
        "pinout_version": int(rig.get("rig_version", 1)),
        "board": rig.get("board", ""),
        "transcribed_from": "<data_dir>/hardware/rig.json",
        "source_label": "pins",
        "pins": rig["pins"],
        **({"pin_range": rig["pin_range"]} if rig.get("pin_range") else {}),
    }
    return logical, pinout

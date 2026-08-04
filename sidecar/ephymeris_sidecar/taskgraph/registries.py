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
from functools import lru_cache
from pathlib import Path

# Re-exported: `specs/compiler.py` and several rules import SCHEMA_DIR from here.
from .paths import HARDWARE_DIR, SCHEMA_DIR  # noqa: F401


def _load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text())


def active_pinout_id() -> str:
    """Which box this build compiles for.

    A BUILD-TIME choice, not a runtime setting, and the registries' `lru_cache`
    depends on that staying true: the pin numbers end up inside the packed table,
    so a rig running two box generations at once would need per-box compilation
    rather than a switch. `$EPHYMERIS_PINOUT` exists for testing a second pinout
    without editing the default.
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
        #: -- nothing emits them, and the linter requires a declared code to be
        #: emitted -- and NOT free, because reissuing one would silently merge two
        #: unrelated event types in any analysis spanning the boundary.
        self._retired = {
            e["code"]: name
            for name, e in raw.get("retired", {}).items()
            if isinstance(e, dict) and "code" in e
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


@lru_cache(maxsize=1)
def channels() -> ChannelMap:
    return ChannelMap(_load("channels.v1.json"), _pinout())


@lru_cache(maxsize=1)
def limits() -> Limits:
    return Limits(_load("limits.v1.json"))

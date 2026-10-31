"""Build the start command from a Task Profile — `TASKS.md#building-the-line`.

A run starts in three steps (`TASKS.md#the-start-line`):

1. the parameters go to the board as `SET <wireKey>=<value> …` lines, each
   capped at `SET_LINE_MAX`;
2. the board answers `PARAMS <n> <crc32>` over the tokens it accepted, and
   `CLAMPED <key>` for any value it had to move; `StartCommand.verify` holds
   that against what was sent and refuses on any disagreement;
3. only then `START SEED=<n>`, drawn at the click.

The line grammar matches the firmware's `parseParamTokens()` (unknown keys
ignored, missing keys keep the sketch's own defaults). A sketch with no profile
sends a bare `SET`, so even an empty block is confirmed.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Any

from .profile import ConfigField, TaskProfile, TaskProfileError

#: The wire key carrying the host-drawn trial seed (`TASKS.md#seed`).
#: Reserved across every profile rather than declared by any one of them: a
#: profile that named `SEED` in its own `config` would collide with this and
#: silently lose one of the two values.
SEED_WIRE_KEY = "SEED"

#: The firmware's `SET` line buffer, mirroring `SET_LINE_MAX` in
#: `libraries/BehaviorBox/BehaviorBox.h`. Two files, one value:
#: `tests/test_start_command.py` reads the header and fails when they disagree.
#:
#: It is a buffer size, terminator included, so a line must be shorter than it
#: (`TASKS.md#the-length-cap`).
#:
#: A line is checked rather than trusted because `readLineInto()` truncates an
#: overlong line in silence. Even so, the board's `PARAMS` reply would disagree
#: with the host's, so a cut line cannot start a run — but refusing to build
#: one says why before anything is sent.
SET_LINE_MAX = 128

_SET_VERB = "SET"

#: `ErrCode` names a refused start carries (`protocol/schema.py`).
PARAMS_MISMATCH = "PARAMS_MISMATCH"
PARAMS_CLAMPED = "PARAMS_CLAMPED"
FIRMWARE_OUTDATED = "FIRMWARE_OUTDATED"


class StartRefused(Exception):
    """The board's answer to the parameter block does not clear the start.

    `code` is the wire error code, `reason` the machine-readable cause beneath
    it (`count`, `crc`, `clamped`, `no_reply`) and `detail` what to show beside
    the message. The message names the reason in words an operator can act on.
    """

    def __init__(
        self, code: str, reason: str, message: str, detail: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason
        self.detail = detail or {}


@dataclass(frozen=True)
class ParamsReply:
    """What the board said about the block: the last `PARAMS <n> <crc32>` and
    every `CLAMPED <key>` that came with it."""

    count: int
    crc32: int
    clamped: tuple[str, ...] = ()


@dataclass(frozen=True)
class StartCommand:
    """The parameter block of one run, ready to send and to be checked.

    `tokens` are the `<wireKey>=<value>` strings in the profile's order;
    `set_lines` is the same tokens packed into capped `SET` lines (always at
    least one). The seed is not here: it is drawn at the start click, minutes
    after the block is settled at mapping (`start_line`).
    """

    tokens: tuple[str, ...]
    set_lines: tuple[str, ...] = field(default=("SET",))

    @property
    def count(self) -> int:
        """How many keys the board should report accepting."""
        return len(self.tokens)

    @property
    def crc32(self) -> int:
        """The standard CRC-32 over the tokens joined by single spaces — what
        the board computes over the tokens it received, in the order received."""
        return zlib.crc32(" ".join(self.tokens).encode("utf-8"))

    def start_line(self, seed: int) -> str:
        """The line that starts the run, sent only once the block is confirmed.

        Drawn per box at the instant the operator starts it (`seed.py`), which is
        why it is not part of the block. A board that predates the convention
        ignores the unknown key and seeds itself, and the seed echoed back says so.
        """
        return f"START {SEED_WIRE_KEY}={seed}"

    def verify(self, reply: ParamsReply | None) -> None:
        """Raise `StartRefused` unless the board's reply clears the start.

        `None` is a board that never answered: it does not speak `SET`.
        """
        if reply is None:
            raise StartRefused(
                FIRMWARE_OUTDATED,
                "no_reply",
                "The board never confirmed its parameters, so this box carries an "
                "older sketch. Reflash it, then start again.",
            )
        if reply.clamped:
            keys = list(reply.clamped)
            raise StartRefused(
                PARAMS_CLAMPED,
                "clamped",
                f"The board moved {', '.join(keys)} to bring it inside the range it "
                f"can run, so it would not run the value that was chosen. Change "
                f"the value and start again.",
                {"keys": keys},
            )
        if reply.count != self.count:
            raise StartRefused(
                PARAMS_MISMATCH,
                "count",
                f"The board accepted {reply.count} of {self.count} parameters: a key "
                f"was not recognised by this sketch. Reflash the box with a current "
                f"build of the task.",
                {"sent": self.count, "accepted": reply.count},
            )
        if reply.crc32 != self.crc32:
            raise StartRefused(
                PARAMS_MISMATCH,
                "crc",
                "The parameters the board received differ from the ones sent: a line "
                "was cut or garbled on the way. Start again; if it repeats, check "
                "the cable.",
                {"sent": self.crc32, "received": reply.crc32},
            )


def _format_value(field: ConfigField, value: Any) -> str:
    """Render one config value for the wire.

    Bools go to the firmware as `1`/`0`, matching the Mega's integer-flag
    convention rather than the JSON literals `true`/`false`.
    """
    if field.type == "bool":
        return "1" if _as_bool(value) else "0"
    if field.type == "int":
        return str(int(value))
    if field.type == "float":
        return _trim_float(float(value))
    rendered = str(value)
    if rendered != rendered.strip() or any(c.isspace() for c in rendered):
        # The grammar is space-separated, so an embedded space would split one
        # value into two tokens -- the firmware would then parse the tail as a
        # bare word and drop it, silently.
        raise ValueError(f"string value for {field.wire_key} contains whitespace")
    return rendered


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _trim_float(value: float) -> str:
    # Avoid a trailing ".0" on whole numbers, but keep genuine decimals.
    return str(int(value)) if value.is_integer() else repr(value)


def _tokens(profile: TaskProfile | None, config: dict[str, Any]) -> list[str]:
    if profile is None:
        return []
    tokens: list[str] = []
    for field in profile.config:
        value = config.get(field.metadata_key, field.default)
        if value is None:
            continue
        try:
            rendered = _format_value(field, value)
        except (ValueError, TypeError):
            # A malformed value falls back to the sketch's own default rather
            # than emitting garbage the firmware would misparse.
            if field.default is None:
                continue
            rendered = _format_value(field, field.default)
        tokens.append(f"{field.wire_key}={rendered}")
    return tokens


def _pack(profile_name: str, tokens: list[str]) -> tuple[str, ...]:
    """Greedily pack tokens into `SET` lines shorter than `SET_LINE_MAX`.

    Order is kept — the CRC is over the tokens in the order received — and a
    token is never split across lines.
    """
    lines: list[str] = []
    current = _SET_VERB
    for token in tokens:
        if len(_SET_VERB) + 1 + len(token) >= SET_LINE_MAX:
            raise TaskProfileError(
                f"{profile_name}: the parameter {token[:24]}… makes a SET line "
                f"{len(_SET_VERB) + 1 + len(token)} characters long, over the firmware's "
                f"{SET_LINE_MAX - 1}-character limit. Shorten the value or its wire "
                f"key -- the board would truncate the line without reporting it."
            )
        if len(current) + 1 + len(token) >= SET_LINE_MAX:
            lines.append(current)
            current = _SET_VERB
        current = f"{current} {token}"
    lines.append(current)
    return tuple(lines)


def build_start_command(profile: TaskProfile | None, config: dict[str, Any]) -> StartCommand:
    """Assemble the parameter block as capped `SET` lines.

    `config` is keyed by `metadataKey` (what the pre-flight form collects and
    what lands in the session file, `DATA.md#the-json-document`); the profile maps each to its `wireKey`.
    A field absent from `config` falls back to the profile's declared default;
    a field the profile doesn't declare is ignored, so stale UI state can't leak
    unknown tokens onto the wire.

    Raises `TaskProfileError` when one parameter cannot fit a `SET` line — see
    `SET_LINE_MAX`. A profile that merely declares many fields is spread over
    more lines.
    """
    tokens = _tokens(profile, config)
    name = profile.task_name if profile is not None else "profile-less sketch"
    return StartCommand(tuple(tokens), _pack(name, tokens))

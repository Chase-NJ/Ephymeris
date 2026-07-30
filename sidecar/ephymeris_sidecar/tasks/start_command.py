"""Build the `START` command from a Task Profile — `data-saving.md` §6.3.

Generic across any profile: `START <wireKey>=<value> <wireKey>=<value> …`,
space-separated and order-independent, matching the firmware's
`parseStartCommand()` grammar (unknown keys ignored, missing keys keep the
sketch's own defaults). A sketch with no profile gets a bare `START`.
"""

from __future__ import annotations

from typing import Any

from .profile import ConfigField, TaskProfile

#: The wire key carrying the host-drawn trial seed (`data-saving.md` §6.4).
#: Reserved across every profile rather than declared by any one of them: a
#: profile that named `SEED` in its own `config` would collide with this and
#: silently lose one of the two values.
SEED_WIRE_KEY = "SEED"


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
    return str(value)


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


def build_start_command(profile: TaskProfile | None, config: dict[str, Any]) -> str:
    """Assemble the `START …` line.

    `config` is keyed by `metadataKey` (what the pre-flight form collects and
    what lands in the session file, §5); the profile maps each to its `wireKey`.
    A field absent from `config` falls back to the profile's declared default;
    a field the profile doesn't declare is ignored, so stale UI state can't leak
    unknown tokens onto the wire.
    """
    if profile is None or not profile.config:
        return "START"

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

    return "START " + " ".join(tokens) if tokens else "START"


def with_trial_seed(command: str, seed: int) -> str:
    """Append the run's `SEED=<int>` token to an already-built `START` line.

    Separate from `build_start_command` on purpose, and the separation is the
    whole point: the config half of the line is settled at
    `sessions.confirmMapping`, minutes before the operator starts anything,
    while the seed has to be drawn at the **start click** or it isn't per-run
    entropy at all (`seed.py`). One command, two moments.

    A sketch whose firmware predates the convention ignores the token — that is
    what `parseStartCommand`'s unknown-key rule is for — and falls back to
    seeding itself, so an un-reflashed box degrades rather than failing.
    """
    return f"{command} {SEED_WIRE_KEY}={seed}"

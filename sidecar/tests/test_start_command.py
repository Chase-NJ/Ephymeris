"""The start command: capped `SET` lines, confirmed by CRC, then `START SEED=<n>`
(`TASKS.md#the-length-cap`, `TASKS.md#the-start-line`).

The seam is `build_start_command` and what a `StartCommand` says about the
board's reply. The CRC literals come from zlib, and the firmware host test
(`test_behaviorbox.cpp`) pins the same ones, so the two languages are held to one
number rather than to each other's arithmetic.
"""

from __future__ import annotations

import re
import zlib
from pathlib import Path

import pytest

from ephymeris_sidecar.protocol import ErrCode
from ephymeris_sidecar.tasks.profile import TaskProfileError, load_profile, parse_profile
from ephymeris_sidecar.tasks.start_command import (
    SET_LINE_MAX,
    ParamsReply,
    StartRefused,
    build_start_command,
)

FIRMWARE = Path(__file__).resolve().parents[2] / "firmware"
HEADER = FIRMWARE / "libraries" / "BehaviorBox" / "BehaviorBox.h"
HOST_TEST = FIRMWARE / "libraries" / "BehaviorBox" / "extras" / "host_test" / "test_behaviorbox.cpp"


def _profile(*fields: tuple[str, str, object]):
    """A profile of (wireKey, type, default) fields."""
    return parse_profile(
        {
            "taskName": "T",
            "config": [
                {"metadataKey": key.lower(), "wireKey": key, "label": key, "type": typ, "default": default}
                for key, typ, default in fields
            ],
        }
    )


ITI_PRM = _profile(("ITI", "int", 4000), ("PRM", "int", 1000))


# --- the line ----------------------------------------------------------------


def test_the_parameters_go_out_as_set_lines_not_start() -> None:
    command = build_start_command(ITI_PRM, {})
    assert command.set_lines == ("SET ITI=4000 PRM=1000",)
    assert command.tokens == ("ITI=4000", "PRM=1000")


def test_overrides_are_applied_by_metadata_key_and_stale_keys_are_ignored() -> None:
    command = build_start_command(ITI_PRM, {"iti": 2500, "not_a_field": 99})
    assert command.tokens == ("ITI=2500", "PRM=1000")


def test_the_start_line_carries_only_the_seed() -> None:
    assert build_start_command(ITI_PRM, {}).start_line(123456789) == "START SEED=123456789"


def test_a_command_with_no_parameters_still_sends_one_set_line() -> None:
    """A board that never hears a `SET` cannot be told apart from an older sketch,
    so even an empty block is asked about: a bare `SET` is answered `PARAMS 0 0`."""
    for command in (
        build_start_command(None, {}),
        build_start_command(parse_profile({"taskName": "Utility"}), {}),
    ):
        assert command.set_lines == ("SET",)
        assert (command.count, command.crc32) == (0, 0)


def test_count_and_crc_are_the_standard_crc32_of_the_tokens_joined_by_spaces() -> None:
    command = build_start_command(ITI_PRM, {})
    assert command.count == 2
    assert command.crc32 == 3324716134  # zlib.crc32(b"ITI=4000 PRM=1000"), pinned in test_behaviorbox.cpp
    assert command.crc32 == zlib.crc32(b"ITI=4000 PRM=1000")


def test_a_block_too_long_for_one_line_spreads_over_several() -> None:
    profile = _profile(*((f"W{i:03d}", "int", 20000) for i in range(48)))
    command = build_start_command(profile, {})
    assert len(command.set_lines) > 1
    assert all(line.startswith("SET ") for line in command.set_lines)
    # The lines together carry every token once, in order, and the CRC is over
    # the tokens however they were split.
    assert " ".join(line[len("SET "):] for line in command.set_lines).split(" ") == list(command.tokens)
    assert command.crc32 == zlib.crc32(" ".join(command.tokens).encode())


# --- the cap -----------------------------------------------------------------


def _one_token_line(length: int):
    """A profile whose single `SET` line is exactly `length` characters."""
    value = "a" * (length - len("SET X="))
    return _profile(("X", "string", value))


def test_the_longest_line_the_firmware_holds_whole_is_built() -> None:
    """`char cmd[SET_LINE_MAX]` keeps one byte for the terminator, so
    SET_LINE_MAX - 1 characters is the longest line read intact (the firmware
    host test pins that side)."""
    command = build_start_command(_one_token_line(SET_LINE_MAX - 1), {})
    assert [len(line) for line in command.set_lines] == [SET_LINE_MAX - 1]


@pytest.mark.parametrize("length", [SET_LINE_MAX, SET_LINE_MAX + 1])
def test_a_token_the_firmware_buffer_cannot_hold_whole_is_refused(length: int) -> None:
    """The board cannot report a truncated line, so the host refuses to build one."""
    with pytest.raises(TaskProfileError, match="over the firmware"):
        build_start_command(_one_token_line(length), {})


def test_no_line_of_any_profile_reaches_the_cap() -> None:
    for width in (1, 7, 31, 48, 120):
        profile = _profile(*((f"W{i:03d}", "int", 20000 + i) for i in range(width)))
        for line in build_start_command(profile, {}).set_lines:
            assert len(line) < SET_LINE_MAX


def test_the_set_line_cap_matches_the_firmware() -> None:
    """Two files, one value (`TASKS.md#the-length-cap`). Were they to disagree
    upward the firmware would truncate a line the host had accepted."""
    match = re.search(r"^#define SET_LINE_MAX (\d+)", HEADER.read_text(encoding="utf-8"), re.M)
    assert match is not None, "BehaviorBox.h no longer defines SET_LINE_MAX"
    assert int(match.group(1)) == SET_LINE_MAX


# --- the board's answer ------------------------------------------------------


def _reply(command, **overrides) -> ParamsReply:
    values = {"count": command.count, "crc32": command.crc32, "clamped": ()}
    values.update(overrides)
    return ParamsReply(**values)


def test_a_matching_reply_is_accepted() -> None:
    command = build_start_command(ITI_PRM, {})
    command.verify(_reply(command))  # does not raise


def test_a_truncated_line_is_refused_with_a_reason() -> None:
    """The board read `PRM=10` where `PRM=1000` was sent: the same number of keys,
    a different CRC."""
    command = build_start_command(ITI_PRM, {})
    cut = zlib.crc32(b"ITI=4000 PRM=10")
    with pytest.raises(StartRefused) as refused:
        command.verify(_reply(command, crc32=cut))
    assert refused.value.code == ErrCode.PARAMS_MISMATCH
    assert refused.value.reason == "crc"
    assert "differ" in str(refused.value)


def test_a_key_the_firmware_does_not_parse_is_refused_with_a_reason() -> None:
    """An unknown key is neither counted nor hashed by the board, so its count is
    short of what was sent."""
    command = build_start_command(ITI_PRM, {})
    with pytest.raises(StartRefused) as refused:
        command.verify(_reply(command, count=1, crc32=zlib.crc32(b"ITI=4000")))
    assert refused.value.code == ErrCode.PARAMS_MISMATCH
    assert refused.value.reason == "count"
    assert "1 of 2" in str(refused.value)


def test_a_value_the_board_clamped_is_refused_naming_the_key() -> None:
    command = build_start_command(ITI_PRM, {})
    with pytest.raises(StartRefused) as refused:
        command.verify(_reply(command, clamped=("POL", "BS")))
    assert refused.value.code == ErrCode.PARAMS_CLAMPED
    assert refused.value.reason == "clamped"
    assert refused.value.detail == {"keys": ["POL", "BS"]}
    assert "POL" in str(refused.value) and "BS" in str(refused.value)


def test_a_board_that_never_answers_is_an_older_sketch_and_must_be_reflashed() -> None:
    command = build_start_command(ITI_PRM, {})
    with pytest.raises(StartRefused) as refused:
        command.verify(None)
    assert refused.value.code == ErrCode.FIRMWARE_OUTDATED
    assert refused.value.reason == "no_reply"
    assert "reflash" in str(refused.value).lower()


# --- the firmware agrees -----------------------------------------------------


def _pasted_strings(block: str) -> list[str]:
    return re.findall(r'"([^"]*)"', block)


def test_the_firmware_confirms_the_set_lines_the_app_builds_for_grgl() -> None:
    """`TASKS.md#the-start-line`: the firmware host test feeds a pasted copy of
    GRGL's `SET` lines to the real parser and checks the `PARAMS` it prints. The
    copy proves nothing once it is stale, because a key the app sends and the
    firmware does not know is simply not counted. Rebuild it here, so a stale
    copy fails -- and so does a CRC the app would not have computed."""
    text = HOST_TEST.read_text(encoding="utf-8")
    block = text.split("THE CROSS-REPO CHECK", 1)[1]
    lines_block = block[block.index("kGrglSetLines[]") : block.index("};")]
    pasted_lines = _pasted_strings(lines_block)
    reply = re.search(r'kGrglParams\[\] = "([^"]*)"', block)
    assert reply is not None

    command = build_start_command(load_profile(FIRMWARE / "Olfactory Behavior" / "GRGL"), {})
    assert tuple(pasted_lines) == command.set_lines
    assert reply.group(1) == f"PARAMS {command.count} {command.crc32}\\r\\n"

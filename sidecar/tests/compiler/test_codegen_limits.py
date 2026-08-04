"""TaskLimits.h is generated, and it still says why.

Two failure modes, and the second is the one a naive generator walks into.

**Drift** — the header disagrees with the schema. `taskgraph codegen --check`
covers that, and CI runs it. What is added here is the direction that check does
not cover: a constant present in the schema and *missing* from the header still
passes `--check`, because the check compares the generated text against the file
and both would lack it.

**Amnesia** — the header keeps the numbers and loses the reasoning. That is not a
cosmetic regression. The hand-written original was the best-explained file in the
firmware library; "why 64 and not the ~192 that measurably fits" cost a hardware
spike to answer, and a header that dropped it would send the next person to re-run
the spike. So the rationale is asserted to be present, per constant.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph.codegen.limits import GROUP_ORDER, emit_header
from ephymeris_sidecar.taskgraph.registries import limits

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, all_specs, spec,
)
LIB = FIRMWARE_LIB
HEADER = LIB / "TaskLimits.h"
SCHEMA = SCHEMA_DIR / "limits.v1.json"


@pytest.fixture(scope="module")
def header() -> str:
    return emit_header()


@pytest.fixture(scope="module")
def defines(header) -> dict[str, int]:
    out = {}
    for name, literal in re.findall(r"^#define\s+(TG_\w+)\s+(\S+)", header, re.M):
        out[name] = int(literal, 0)
    return out


def test_the_file_on_disk_is_what_the_generator_produces(header):
    """The same statement `codegen --check` makes, asserted where a developer
    sees it before CI does."""
    assert HEADER.read_text() == header, "run `taskgraph codegen` and commit the result"


def test_every_schema_constant_reaches_the_header(defines):
    """The direction `--check` cannot see.

    A constant added to the schema and dropped by the generator leaves both the
    generated text and the file missing it, so they agree and `--check` is happy.
    The firmware is then missing a number nobody noticed was gone.
    """
    lim = limits()
    raw = lim.groups()
    expected = {
        name: entry["value"]
        for group, entries in raw.items()
        if isinstance(entries, dict) and not group.startswith("_")
        for name, entry in entries.items()
        if not name.startswith("_") and isinstance(entry, dict)
    }
    missing = sorted(set(expected) - set(defines))
    assert not missing, f"schema constants absent from TaskLimits.h: {missing}"
    for name, value in expected.items():
        assert defines[name] == value, name


def test_the_header_invents_nothing(defines):
    """The other direction: every `#define` traces back to the schema.

    A hand-added constant would survive one regeneration -- it would simply
    vanish -- but the window between someone adding it and someone regenerating
    is exactly long enough to build something on top of it.
    """
    lim = limits()
    known = {
        name
        for group, entries in lim.groups().items()
        if isinstance(entries, dict) and not group.startswith("_")
        for name in entries
        if not name.startswith("_")
    } | {"TG_LIMITS_VERSION"}
    assert not sorted(set(defines) - known)


def test_every_constant_still_explains_itself(header):
    """THE ONE THAT MATTERS.

    A generator that emits a wall of naked #defines is correct and passes
    everything else in this file. Each constant must be preceded by a comment
    block, and the block must be substantial enough to be an explanation rather
    than a restatement of the name.
    """
    thin = []
    for m in re.finditer(r"^#define\s+(TG_\w+)\s+\S", header, re.M):
        name = m.group(1)
        if name == "TG_LIMITS_VERSION":
            continue  # the schema's own version; its meaning is its name
        comment = header[: m.start()].rsplit("/*", 1)[-1]
        words = len(re.findall(r"[a-zA-Z]{3,}", comment))
        #: Six, not twelve. Some rationales are legitimately one line -- "2.4x the
        #: largest target task. 8 bytes each." earns its keep and does not need
        #: padding. The bar is "an explanation exists", and a naked #define or a
        #: restatement of the macro name scores far below this.
        if "*/" not in comment or words < 6:
            thin.append(f"{name} ({words} words)")
    assert not thin, (
        "these constants reached the header without their reasoning: "
        + ", ".join(thin)
        + "\nThe rationale lives in schema/limits.v1.json and is the point of it."
    )


def test_the_prose_survives_verbatim():
    """Spot-check the sentences that cost the most to learn.

    Reflowing is fine; losing them is not. Each of these answers a question
    someone will actually ask, and each was expensive: a hardware sweep, a serial
    tooling survey, a firmware archaeology session.
    """
    #: Strip the comment furniture before matching. A phrase that the generator
    #: wrapped across two lines picks up a ` * ` in the middle, and asserting on
    #: the raw text would make this a test of the wrap width.
    text = " ".join(
        re.sub(r"^\s*\*+\s?", "", line) for line in HEADER.read_text().splitlines()
    )
    text = " ".join(text.split())
    for phrase in (
        "not to extract the last byte",            # why 64 and not 192
        "openable by generic POSIX",               # why 115200 and not 250000
        "NOT an independent source of truth",      # why START_LINE_MAX is mirrored
        "one step from a magic one",               # why uint16 durations (D6)
        "silently unwatched",                      # why the watch mask caps ports
    ):
        assert phrase in text, f"lost from TaskLimits.h: {phrase!r}"


def test_a_new_schema_group_fails_loudly():
    """Adding a group to the schema must not silently drop it.

    The generator walks GROUP_ORDER, so an unlisted group would be skipped and
    every other test here would still pass -- the constants would simply not
    exist. It raises instead.
    """
    raw = json.loads(SCHEMA.read_text())
    groups = [
        g for g in raw
        if isinstance(raw[g], dict) and not g.startswith("_") and g != "limits_version"
    ]
    assert sorted(groups) == sorted(GROUP_ORDER), (
        "schema groups and GROUP_ORDER disagree; the generator raises on this, but "
        "the message is clearer here"
    )


@pytest.mark.skipif(shutil.which("clang++") is None, reason="needs clang++")
def test_it_compiles_and_defines_no_constant_twice(tmp_path):
    """`-Wall` promotes a macro redefinition to a warning, and `-Werror` to a
    failure.

    This is not hypothetical: TG_NO_STROBE was defined in TaskTable.h *and* in
    the schema, so generating the header created two definitions of it. Identical
    token sequences make that legal and silent. The schema owns it now -- next to
    TG_STROBE_MAX, since a sentinel defined apart from the range it sits outside
    of is one that can drift into it.
    """
    src = tmp_path / "t.cpp"
    src.write_text(
        '#include "TaskLimits.h"\n#include "TaskTable.h"\n#include "TgWire.h"\n'
        "int main() { return TG_MAX_STATES + TG_NO_STROBE + TG_WIRE_FORMAT ? 0 : 1; }\n"
    )
    r = subprocess.run(
        ["clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(LIB),
         str(src), "-o", str(tmp_path / "t")],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_the_cap_announce_hard_codes_no_number():
    """What announcing the limits is FOR.

    `CAP` exists so a host stops compiling its own copy of MAXSTATES -- the
    pattern that put START_LINE_MAX in two repos and baudRate in nine files. A
    literal in the announce would be a fourth instance, in the very function whose
    job is to end them, and it would be invisible: the board would confidently
    announce a number the table it accepts does not obey.

    So every value in `tgAnnounceCapabilities()` must be a TG_* macro. The one
    allowed literal is TASKGRAPH=1, which is a presence flag rather than a
    quantity.
    """
    src = (LIB / "TaskInterpreter.h").read_text()
    body = src[src.index("inline void tgAnnounceCapabilities()"):]
    body = body[: body.index("\n}")]
    #: Strings only -- the announce is Serial.print(F("...")) and Serial.print(MACRO),
    #: so a bare number can only appear inside a quoted token.
    literals = [
        m for m in re.findall(r'F\("([^"]*)"\)', body) if re.search(r"=\d", m)
    ]
    assert literals == [" TASKGRAPH=1 SPEC="], (
        f"hard-coded values in the CAP announce: {literals}"
    )

    #: And every macro it prints must be one the schema defines.
    printed = set(re.findall(r"Serial\.print(?:ln)?\((TG_\w+)\)", body))
    known = set(defines_on_disk()) | {"TG_WIRE_FORMAT"}
    assert printed <= known, f"CAP announces unknown macro(s): {sorted(printed - known)}"
    assert printed, "the announce prints no macros at all, which cannot be right"


def defines_on_disk() -> dict[str, int]:
    out = {}
    for name, literal in re.findall(r"^#define\s+(TG_\w+)\s+(\S+)", HEADER.read_text(), re.M):
        out[name] = int(literal, 0)
    return out

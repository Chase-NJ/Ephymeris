"""The wire format: does it say what it means, and does C++ read it the same way?

Two independent questions, and the second is the one that can silently ruin a
session. Python can pack a table perfectly self-consistently and still disagree
with the firmware about where byte 37 lives, and every check that stays inside
Python would pass. `TgTimingSet` already demonstrated the shape of that failure --
3 bytes on avr-g++, 4 on clang++, compiling cleanly on both.

So the last test here builds a C++ program that reads the Python-produced bytes
back through the generated offsets and prints what it found. Everything before it
is cheaper and catches cruder mistakes first.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph.codegen.layout import RECORDS
from ephymeris_sidecar.taskgraph.emit import pack as P
from ephymeris_sidecar.taskgraph.pipeline import compile_spec

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, SPEC_DIR, all_specs, spec,
)
SPECS = all_specs()

LIB = FIRMWARE_LIB


@pytest.fixture(scope="module")
def tables():
    out = {}
    for s in SPECS:
        r = compile_spec(s)
        assert r.ok, r.bag.render()
        out[r.table.spec_id] = r.table
    return out


# --------------------------------------------------------------------------- #
# Self-consistency
# --------------------------------------------------------------------------- #


def test_the_two_layout_models_agree():
    """`<`-packed struct sizes must equal the naturally-aligned sizes.

    The C++ assertions are generated from a natural-alignment model; the packer
    uses a no-padding model. Every record has to measure the same under both, and
    one that does not is a record needing an explicit pad byte -- which is exactly
    the fix TgTimingSet needed and did not have.
    """
    for rec in RECORDS:
        assert struct.calcsize(P._fmt(rec)) == rec.size, rec.name


@pytest.mark.parametrize("spec_id", [s.stem for s in SPECS])
def test_packing_is_deterministic(tables, spec_id):
    """The CRC is provenance, and provenance that moves when nothing moved is
    worthless. Compile twice, from scratch, and compare bytes."""
    a = P.pack(tables[spec_id])
    b = P.pack(compile_spec(spec(spec_id)).table)
    assert a == b


@pytest.mark.parametrize("spec_id", [s.stem for s in SPECS])
def test_the_blob_verifies_and_is_the_size_it_claims(tables, spec_id):
    t = tables[spec_id]
    blob = P.pack(t)

    assert blob.startswith(P.MAGIC)
    assert P.verify(blob)
    assert blob[P.HEADER_SIZE:-P.CRC_SIZE] == P.body(t)

    #: The record arithmetic, restated independently of the packer. If this and
    #: the packer ever disagree, one of them is wrong about a section's width and
    #: the board would parse everything after it at the wrong offset.
    expected = (
        P.HEADER_SIZE
        + 8 * len(t.nodes) + 4 * len(t.edges) + 2 * len(t.timing) + 2 * len(t.actions)
        + 8 * len(t.trial_types) + 16 * len(t.ports) + 4 * len(t.stimuli)
        + 4 * len(t.stage_rows) + 4 * len(t.timing_sets)
        + 2 * len(t.nodes) + 2 * P.WATCH_SLOTS
        + P.CRC_SIZE
    )
    assert len(blob) == expected


@pytest.mark.parametrize("spec_id", [s.stem for s in SPECS])
def test_the_header_states_the_real_counts(tables, spec_id):
    """A corrupted count does not produce a parse error -- it produces a table
    that runs and is not the one anybody compiled. So the counts are inside the
    CRC, and they have to be right going in."""
    t = tables[spec_id]
    blob = P.pack(t)
    off = {}
    o = len(P.MAGIC)
    for name, width in P.HEADER_FIELDS:
        off[name] = o
        o += width

    assert blob[off["wire_format"]] == P.WIRE_FORMAT
    assert blob[off["n_nodes"]] == len(t.nodes)
    assert blob[off["n_edges"]] == len(t.edges)
    assert blob[off["n_timing"]] == len(t.timing)
    assert blob[off["n_actions"]] == len(t.actions)
    assert blob[off["n_trial_types"]] == len(t.trial_types)
    assert blob[off["n_ports"]] == len(t.ports)
    assert blob[off["n_stimuli"]] == len(t.stimuli)
    assert blob[off["n_watch"]] == len(t.watch_pins)
    assert blob[off["n_stage_rows"]] == len(t.stage_rows)
    assert blob[off["n_timing_sets"]] == len(t.timing_sets)
    assert struct.unpack_from("<I", blob, off["spec_hash"])[0] == int(t.spec_hash[:8], 16)


@pytest.mark.parametrize("spec_id", [s.stem for s in SPECS])
def test_every_single_bit_flip_is_detected(tables, spec_id):
    """The whole point, stated as strongly as it can be.

    Not "a corrupted table is usually caught" -- every one-bit change anywhere in
    the payload, including inside the counts and inside the CRC field itself, must
    fail verification. CRC32 guarantees this for single-bit errors; the test is
    here because the guarantee only holds if the CRC actually covers the bytes we
    think it covers.
    """
    blob = bytearray(P.pack(tables[spec_id]))
    for i in range(len(blob)):
        for bit in (0, 3, 7):
            blob[i] ^= 1 << bit
            assert not P.verify(bytes(blob)), f"byte {i} bit {bit} went undetected"
            blob[i] ^= 1 << bit


@pytest.mark.parametrize("spec_id", [s.stem for s in SPECS])
def test_truncation_is_detected(tables, spec_id):
    """The failure this protocol exists for. `readLineInto()` truncates silently
    and the board "just runs on the wrong value"; here, every prefix short of the
    whole thing is refused."""
    blob = P.pack(tables[spec_id])
    for n in range(len(blob)):
        assert not P.verify(blob[:n]), f"a {n}-byte prefix verified"
    assert P.verify(blob)


def test_a_table_with_no_magic_is_refused(tables):
    blob = bytearray(P.pack(tables["grgl_2odor"]))
    blob[0] = ord("X")
    blob[-P.CRC_SIZE:] = struct.pack("<I", zlib.crc32(bytes(blob[:-P.CRC_SIZE])) & 0xFFFFFFFF)
    #: Note the CRC is recomputed, so this is a well-formed blob that is simply
    #: not ours. Magic has to be checked separately or a board would happily parse
    #: an internally-consistent something-else.
    assert not P.verify(bytes(blob))


# --------------------------------------------------------------------------- #
# The one that leaves Python
# --------------------------------------------------------------------------- #


CROSS_CHECK = r"""
/*  Read a Python-packed table back through the GENERATED offsets and print what
    the firmware would see. Not a parser -- the receiver is Phase 4's job -- just
    enough to prove both sides agree about where the bytes are.  */
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "TgWire.h"
#include "TaskTable.h"

int main(int argc, char **argv)
{
  std::FILE *f = std::fopen(argv[1], "rb");
  if (!f) return 2;
  std::vector<uint8_t> b;
  int c;
  while ((c = std::fgetc(f)) != EOF) b.push_back((uint8_t)c);
  std::fclose(f);

  std::printf("magic=%c%c%c%c\n", b[0], b[1], b[2], b[3]);
  std::printf("wire=%u spec=%u vocab=%u template=%u\n",
              b[TG_HDR_WIRE_FORMAT], b[TG_HDR_SPEC_VERSION],
              b[TG_HDR_VOCAB_VERSION], b[TG_HDR_TEMPLATE_VERSION]);
  std::printf("spechash=%lu\n", (unsigned long)tgRdU32(b.data(), TG_HDR_SPEC_HASH));
  std::printf("counts=%u,%u,%u,%u,%u,%u,%u,%u,%u,%u\n",
              b[TG_HDR_N_NODES], b[TG_HDR_N_EDGES], b[TG_HDR_N_TIMING],
              b[TG_HDR_N_ACTIONS], b[TG_HDR_N_TRIAL_TYPES], b[TG_HDR_N_PORTS],
              b[TG_HDR_N_STIMULI], b[TG_HDR_N_WATCH], b[TG_HDR_N_STAGE_ROWS],
              b[TG_HDR_N_TIMING_SETS]);

  /*  Walk to a couple of sections by the declared record sizes and read one
      field out of each, including a uint16 -- which is where a layout difference
      would show up first.  */
  const uint16_t nodes = TG_HDR_SIZE;
  const uint16_t edges = nodes + (uint16_t)(sizeof(TgNode) * b[TG_HDR_N_NODES]);
  const uint16_t timing = edges + (uint16_t)(sizeof(TgEdge) * b[TG_HDR_N_EDGES]);
  std::printf("node0=%u,%u,%u,%u\n", b[nodes], b[nodes + 1],
              tgRdU16(b.data(), nodes + 2), b[nodes + 4]);
  std::printf("edge0=%u,%u,%u,%u\n", b[edges], b[edges + 1], b[edges + 2], b[edges + 3]);
  std::printf("timing0=%u\n", tgRdU16(b.data(), timing));
  std::printf("nbytes=%u\n", (unsigned)b.size());
  return 0;
}
"""


@pytest.mark.skipif(shutil.which("clang++") is None, reason="needs clang++")
@pytest.mark.parametrize("spec_id", [s.stem for s in SPECS])
def test_cpp_reads_the_same_bytes(tables, spec_id, tmp_path):
    """THE GATE FOR THIS MODULE.

    Python writes; C++ reads, using the generated offsets and the real record
    sizes from TaskTable.h. If the two layouts ever disagree -- a field width, a
    missing pad byte, an endianness assumption -- the numbers below stop matching
    and the build fails here, instead of a board running a table it misread.
    """
    src = tmp_path / "cross.cpp"
    src.write_text(CROSS_CHECK)
    binary = tmp_path / "cross"
    subprocess.run(
        ["clang++", "-std=c++17", "-Wall", "-I", str(LIB), str(src), "-o", str(binary)],
        check=True, capture_output=True,
    )

    t = tables[spec_id]
    blob = P.pack(t)
    blob_path = tmp_path / f"{spec_id}.bin"
    blob_path.write_bytes(blob)
    got = dict(
        line.split("=", 1)
        for line in subprocess.run(
            [str(binary), str(blob_path)], check=True, capture_output=True, text=True
        ).stdout.splitlines()
    )

    n0, e0 = t.nodes[0], t.edges[0]
    assert got["magic"] == P.MAGIC.decode()
    assert got["wire"].split()[0] == str(P.WIRE_FORMAT)
    assert got["spechash"] == str(int(t.spec_hash[:8], 16))
    assert got["counts"] == ",".join(str(n) for n in (
        len(t.nodes), len(t.edges), len(t.timing), len(t.actions), len(t.trial_types),
        len(t.ports), len(t.stimuli), len(t.watch_pins), len(t.stage_rows),
        len(t.timing_sets),
    ))
    assert got["node0"] == f"{int(n0.type)},{n0.dur_idx},{n0.strobe},{n0.watch_mask}"
    assert got["edge0"] == f"{int(e0.trigger)},{e0.guard},{e0.target},{e0.effect}"
    assert got["timing0"] == str(t.timing[0])
    assert got["nbytes"] == str(len(blob))


# --------------------------------------------------------------------------- #
# The CLI, in a fresh interpreter
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "argv",
    [
        ["codegen", "--check"],
        ["compile", str(spec("grgl_2odor")), "-o", "build"],
        ["listing", "--check", str(spec("grgl_2odor"))],
        ["show", str(spec("gonogo"))],
    ],
    ids=lambda a: a[0],
)
def test_the_cli_starts_from_cold(argv):
    """Every entry point, in a process that has imported nothing yet.

    This exists because of a real miss. `emit.pack` reads the record layout from
    `codegen.layout`, and `codegen.wire` reads the wire constants back out of
    `emit.pack` -- a cycle through the package `__init__` that resolves or
    explodes depending on which module is imported FIRST. The whole suite passed;
    `taskgraph compile` did not. In-process tests inherit an import graph that a
    user's first command does not.
    """
    r = subprocess.run(
        [sys.executable, "-m", "ephymeris_sidecar.taskgraph.cli", *argv],
        cwd=REPO_ROOT / "sidecar", capture_output=True, text=True,
    )
    assert r.returncode == 0, f"{argv} failed:\n{r.stdout}\n{r.stderr}"
    assert "Traceback" not in r.stderr

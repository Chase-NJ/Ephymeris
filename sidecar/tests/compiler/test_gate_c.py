"""GATE C — the table that goes over the wire must be the table that was compiled.

Gates A and B are both statements about a `static const TgTable` the C++ compiler
laid out. A real box never holds that. It holds bytes: packed, framed into lines,
hex encoded, checksummed, and decoded field by field by the receiver. Without this
gate, "the interpreter is correct" describes an artifact no board will ever see.

TWO CLAIMS, AND THE SECOND DOES NOT FOLLOW FROM THE FIRST.

  structural  — every field of the received table equals the compiled-in one.
                Exhaustive, and it localises a failure to a field name.
  behavioural — the two tables, driven by the same randomised animals, emit
                byte-identical streams. A field can compare equal and still be
                read through a different path, and a decode that transposed two
                unused fields would pass structurally while meaning nothing.

The upload is produced by `taskgraph.transport.frame()` — the same function a real
host calls. A gate that framed its own input would be testing a framer nobody
ships.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph.emit.c_table import emit
from ephymeris_sidecar.taskgraph.emit.pack import pack
from ephymeris_sidecar.taskgraph.pipeline import compile_spec
from ephymeris_sidecar.taskgraph.transport import frame

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, SPEC_DIR, all_specs, spec,
)

LIB = FIRMWARE_LIB

MODEL = spec("grgl_2odor")

SEEDS = (20260803, 1, 424242)
TRIALS = 2000

pytestmark = pytest.mark.skipif(
    shutil.which("clang++") is None or not (BEHAVIORBOX / "BehaviorBox.h").is_file(),
    reason="needs clang++ and the reference BehaviorBox.h",
)


@pytest.fixture(scope="module")
def compiled():
    r = compile_spec(MODEL)
    assert r.ok, r.bag.render()
    assert r.table.template_version == 2
    return r.table


@pytest.fixture(scope="module")
def gate_c(compiled, tmp_path_factory):
    (HOST_TEST / "grgl_table.h").write_text(emit(compiled))
    binary = tmp_path_factory.mktemp("gate_c") / "gate_c"
    subprocess.run(
        ["clang++", "-std=c++17", "-Wall", "-I", str(HOST_TEST), "-I", str(LIB),
         "-I", str(BEHAVIORBOX), str(HOST_TEST / "gate_c.cpp"), "-o", str(binary)],
        check=True, capture_output=True,
    )
    return binary


def run(binary, table, blob: bytes, seed: int = SEEDS[0], trials: int = TRIALS) -> dict:
    upload = "\n".join(frame(table, blob)) + "\n"
    out = subprocess.run(
        [str(binary), str(seed), str(trials)], input=upload,
        capture_output=True, text=True,
    ).stdout
    got: dict[str, int | str] = {"_raw": out}
    for key in ("structural", "behavioural", "hangs", "checked", "trials", "correct",
                "wrong", "omission", "abstain", "holdbreak", "holdfail"):
        m = re.search(rf"\b{key}=(\d+)", out)
        if m:
            got[key] = int(m.group(1))
    m = re.search(r"^upload=(\w+)", out, re.M)
    got["upload"] = m.group(1) if m else "MISSING"
    return got


@pytest.fixture(scope="module")
def result(gate_c, compiled):
    return run(gate_c, compiled, pack(compiled))


def test_the_upload_is_accepted(result):
    assert result["upload"] == "OK", result["_raw"]


def test_every_field_survives_the_wire(result):
    """THE STRUCTURAL HALF.

    Node by node, edge by edge, port by port. A CRC says the right bytes arrived;
    this says they arrived in the right fields — the difference between a transfer
    that worked and a decode that did.
    """
    assert result["structural"] == 0, (
        f"{result['structural']} field(s) differ after the round trip\n\n{result['_raw']}"
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_the_uploaded_table_behaves_identically(gate_c, compiled, seed):
    """THE GATE.

    Same animals, two tables: one the C++ compiler laid out, one that arrived as
    hex over a serial line. Same codes, same order, same timestamps, every trial.
    """
    r = run(gate_c, compiled, pack(compiled), seed=seed)
    assert r["behavioural"] == 0, (
        f"seed {seed}: {r['behavioural']} of {r['checked']} trials differ\n\n{r['_raw']}"
    )
    assert r["hangs"] == 0, f"seed {seed}: the interpreter hung\n\n{r['_raw']}"
    assert r["checked"] == r["trials"]


def test_the_battery_covers_every_outcome(result):
    """Zero divergence means nothing if the battery never left the correct path."""
    for cls in ("correct", "wrong", "omission", "abstain", "holdbreak", "holdfail"):
        assert result[cls] >= 50, f"only {result[cls]} {cls} trials\n\n{result['_raw']}"


def test_a_refused_upload_fails_the_gate(gate_c, compiled):
    """The negative control, and it is not a formality.

    Every assertion above would also pass if the gate quietly compared the
    compiled-in table against itself — which is exactly what would happen if the
    upload failed and nobody checked. A corrupted table must reach the end as a
    FAILURE, not as a comparison of one table with itself.
    """
    blob = bytearray(pack(compiled))
    blob[200] ^= 0x10
    r = run(gate_c, compiled, bytes(blob), trials=10)
    assert r["upload"] == "FAILED", r["_raw"]
    assert r["structural"] != 0 or r["behavioural"] != 0, (
        "a refused upload was reported as a clean gate — the gate would pass on a "
        "board that never received anything"
    )


def test_the_gate_would_notice_a_corrupted_field(gate_c, compiled):
    """Proof the structural comparison is load-bearing.

    A table whose bytes are intact but whose CONTENT differs by one field must be
    reported. Built by compiling a spec, mutating the packed record, and resealing
    the CRC — so the receiver accepts it and the comparison is the only thing that
    can object.
    """
    import zlib

    from ephymeris_sidecar.taskgraph.emit.pack import CRC_SIZE, HEADER_SIZE

    blob = bytearray(pack(compiled))
    blob[HEADER_SIZE + 1] = (blob[HEADER_SIZE + 1] + 1) % 8  # node 0's durIdx
    blob[-CRC_SIZE:] = zlib.crc32(bytes(blob[:-CRC_SIZE])).to_bytes(4, "little")

    r = run(gate_c, compiled, bytes(blob), trials=200)
    assert r["upload"] == "OK", "the reseal failed; this test is not testing what it claims"
    assert r["structural"] > 0, (
        "a changed field survived the structural comparison\n\n" + r["_raw"]
    )

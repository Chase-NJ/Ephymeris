"""The receiver: does a bad table get refused, and does a good one land intact?

Driven against `tg_board`, which runs the SAME `TgReceive.h` an ATmega2560 runs.
Only the clock and Serial are mocked; the parser, the state machine, the CRC and
the record decode are the real ones.

WHY THE SCENARIOS LIVE IN PYTHON. Flipping a byte, reordering a chunk or claiming
200 nodes is one line here and a C++ special case there. The board stays dumb --
it reads lines and reports -- and every way an upload can go wrong is constructed
on this side, which is also the side that will construct them for real.

THE BAR. It is not enough that a corrupted table is *usually* rejected. `valid`
must be false after every single failure mode below, because `valid` is the only
thing standing between a half-written table and a session with an animal in it.
"""

from __future__ import annotations

import shutil
import subprocess
import zlib
from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph.emit.pack import CRC_SIZE, HEADER_SIZE, crc32, pack
from ephymeris_sidecar.taskgraph.pipeline import compile_spec
from ephymeris_sidecar.taskgraph.transport import (
    UploadError,
    body_digest,
    chunk_count,
    frame,
    interpret,
)

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, all_specs, spec,
)

LIB = FIRMWARE_LIB

SPECS = all_specs()

pytestmark = pytest.mark.skipif(
    shutil.which("clang++") is None or not (BEHAVIORBOX / "BehaviorBox.h").is_file(),
    reason="needs clang++ and the reference BehaviorBox.h",
)


@pytest.fixture(scope="module")
def board(tmp_path_factory) -> Path:
    binary = tmp_path_factory.mktemp("tg_board") / "tg_board"
    subprocess.run(
        ["clang++", "-std=c++17", "-Wall", "-Wextra", "-I", str(HOST_TEST), "-I", str(LIB),
         "-I", str(BEHAVIORBOX), str(HOST_TEST / "tg_board.cpp"), "-o", str(binary)],
        check=True, capture_output=True,
    )
    return binary


@pytest.fixture(scope="module")
def grgl():
    r = compile_spec(spec("two_afc"))
    assert r.ok, r.bag.render()
    return r.table


class Session:
    """One conversation with the board, and what it said back."""

    def __init__(self, out: str) -> None:
        self.lines = [ln for ln in out.splitlines() if ln]
        self.replies = [ln for ln in self.lines if ln.startswith("TABLE ")]
        self.status = dict(
            kv.split("=", 1)
            for ln in self.lines if ln.startswith("STATUS ")
            for kv in ln.split()[1:]
        )
        self.counts = next(
            ([int(x) for x in ln.split()[1:]] for ln in self.lines if ln.startswith("COUNTS ")),
            [],
        )

    @property
    def valid(self) -> bool:
        return self.status.get("valid") == "1"

    @property
    def fail(self) -> str:
        return self.status.get("fail", "")

    def row(self, tag: str) -> list[int]:
        for ln in self.lines:
            if ln.startswith(tag + " "):
                return [int(x) for x in ln.split()[1:]]
        return []


def talk(board: Path, lines: list[str]) -> Session:
    r = subprocess.run(
        [str(board)], input="\n".join(lines) + "\n", capture_output=True, text=True
    )
    return Session(r.stdout)


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec_id", [s.stem for s in SPECS])
def test_a_good_table_is_accepted_and_lands_intact(board, spec_id):
    """Every spec, uploaded and decoded.

    The CRC only says the right bytes arrived. These assertions say they arrived
    in the right FIELDS -- a transposed record decode would pass a CRC check and
    fail here.
    """
    r = compile_spec(spec(spec_id))
    t, blob = r.table, pack(r.table)
    s = talk(board, list(frame(t, blob)))

    assert s.valid, f"{spec_id} refused: {s.fail}\n" + "\n".join(s.lines)
    assert int(s.status["crc"], 16) == crc32(blob)
    assert int(s.status["spechash"], 16) == int(t.spec_hash[:8], 16)
    assert s.counts == [
        len(t.nodes), len(t.edges), len(t.timing), len(t.actions), len(t.trial_types),
        len(t.ports), len(t.stimuli), len(t.watch_pins), len(t.stage_rows),
        len(t.timing_sets),
    ]

    n0, nn = t.nodes[0], t.nodes[-1]
    assert s.row("NODE0") == [int(n0.type), n0.dur_idx, n0.strobe, n0.watch_mask,
                              n0.action_idx, n0.action_count, n0.edge_idx]
    assert s.row("NODEN") == [int(nn.type), nn.dur_idx, nn.strobe, nn.watch_mask,
                              nn.action_idx, nn.action_count, nn.edge_idx]
    assert s.row("TIMING") == list(t.timing)
    assert s.row("DWELL") == [d or 0 for d in t.max_dwell]

    p = t.ports[0]
    assert s.row("PORT0") == [p.channel, p.reward_line, p.enter_code, p.error_code,
                              p.break_code, p.exit_code, p.reward_code,
                              p.reward_stop_code, p.reward_dur_idx]


def test_the_watch_mapping_survives(board, grgl):
    """The array that turns a set mask bit back into a pin and a port. Without
    it the board knows a poke happened and not which one."""
    s = talk(board, list(frame(grgl, pack(grgl))))
    line = next(ln for ln in s.lines if ln.startswith("WATCH "))
    pairs = [tuple(int(x) for x in tok.split("/")) for tok in line.split()[1:]]
    for i, (pin, port) in enumerate(zip(grgl.watch_pins, grgl.watch_ports, strict=True)):
        assert pairs[i] == (pin, port)
    for pin, port in pairs[len(grgl.watch_pins):]:
        assert (pin, port) == (0xFF, 0xFF), "unused watch slots must be TG_NO_TARGET"


def test_the_board_acks_every_chunk(board, grgl):
    """The acks are how a host knows where it is. One per chunk, in order,
    plus the ack for BEGIN itself."""
    blob = pack(grgl)
    s = talk(board, list(frame(grgl, blob)))
    acks = [ln for ln in s.replies if ln.startswith("TABLE ACK")]
    assert [int(ln.split()[-1]) for ln in acks] == list(range(chunk_count(blob) + 1))
    assert s.replies[-1].startswith(f"TABLE OK {crc32(blob):08x} ")


def test_the_host_side_reader_agrees(board, grgl):
    """Including the DIGEST, which is the check the CRC cannot make.

    `crc` says the right bytes arrived; `DIGEST` says the board put them in the
    right fields. A decode reading a record at the wrong stride produces a
    perfect CRC and a wrong table, and only this catches it.
    """
    blob = pack(grgl)
    s = talk(board, list(frame(grgl, blob)))
    assert interpret(s.replies, crc32(blob), body_digest(blob)) == crc32(blob)


def test_a_board_that_decodes_into_the_wrong_fields_is_caught(board, grgl):
    """The digest, shown to be load-bearing.

    A board reporting the digest of a DIFFERENT table must be rejected even
    though its CRC is right — which is exactly the shape of a decode fault.
    """
    blob = pack(grgl)
    s = talk(board, list(frame(grgl, blob)))
    with pytest.raises(UploadError, match="different fields"):
        interpret(s.replies, crc32(blob), body_digest(blob) ^ 0xFFFF)


def test_firmware_without_a_digest_is_not_silently_trusted(grgl):
    """An older board answers `TABLE OK <crc>` and nothing more. Treating the
    missing field as "fine" would quietly disable the check on exactly the boards
    most likely to need it."""
    blob = pack(grgl)
    with pytest.raises(UploadError, match="no DIGEST"):
        interpret([f"TABLE OK {crc32(blob):08x}"], crc32(blob), body_digest(blob))


# --------------------------------------------------------------------------- #
# Refusals — one per way an upload can go wrong
# --------------------------------------------------------------------------- #


def upload(board: Path, table, blob: bytes, **kw) -> Session:
    return talk(board, list(frame(table, blob, **kw)))


def _hdr_offset(field: str) -> int:
    """Where a header field lives, from the packer's own table rather than a
    literal — so a header change moves these mutations with it instead of
    quietly corrupting the wrong byte and still passing."""
    from ephymeris_sidecar.taskgraph.emit.pack import HEADER_FIELDS, MAGIC

    off = len(MAGIC)
    for name, width in HEADER_FIELDS:
        if name == field:
            return off
        off += width
    raise KeyError(field)


def _reseal(blob: bytearray) -> bytes:
    """Repair the trailing CRC after a deliberate mutation.

    Needed wherever the point is that a table is INTACT and still unacceptable —
    over-capacity, unknown wire format, wrong magic. Without resealing, the CRC
    would catch it first and the check under test would never run.
    """
    blob[-CRC_SIZE:] = zlib.crc32(bytes(blob[:-CRC_SIZE])).to_bytes(4, "little")
    return bytes(blob)


@pytest.mark.parametrize("offset", [0, 4, HEADER_SIZE, HEADER_SIZE + 1, -8, -5])
def test_a_flipped_bit_anywhere_is_refused(board, grgl, offset):
    """Magic, header, first record, last record, deep in the body.

    Each lands on a different check -- magic, wire format, size, or the CRC --
    and every one of them must end with valid=0. Which check catches it is an
    implementation detail; that something does is the contract.
    """
    blob = bytearray(pack(grgl))
    blob[offset] ^= 0x01
    s = upload(board, grgl, bytes(blob))
    assert not s.valid, f"a flipped bit at {offset} was accepted"
    assert s.fail != "NONE"


def test_a_truncated_upload_is_refused(board, grgl):
    """THE FAILURE THIS PROTOCOL EXISTS FOR.

    `readLineInto()` truncates silently and "a lost token is not an error the
    board can see, it just runs on the wrong value". Here the board has the byte
    count the host declared, so a short transfer is a fact it can state.
    """
    blob = pack(grgl)
    lines = list(frame(grgl, blob))
    s = talk(board, lines[:-2] + ["TABLE END"])  # drop the final chunk
    assert not s.valid
    assert s.fail == "TRUNCATED"


def test_a_dropped_middle_chunk_is_refused(board, grgl):
    """Not the same as truncation: the byte count is short AND the sequence
    jumps, so this must be caught at the chunk rather than at END."""
    lines = list(frame(grgl, pack(grgl)))
    s = talk(board, lines[:2] + lines[3:])
    assert not s.valid
    assert s.fail == "SEQ"


def test_a_reordered_chunk_is_refused(board, grgl):
    lines = list(frame(grgl, pack(grgl)))
    s = talk(board, [lines[0], lines[2], lines[1], *lines[3:]])
    assert not s.valid
    assert s.fail == "SEQ"


def test_a_corrupt_chunk_is_caught_before_it_is_stored(board, grgl):
    """A chunk whose own checksum fails must not reach the table.

    Storing first and checking after would leave the table holding bytes the host
    is about to resend, and a resend that then failed would leave a mix of two
    attempts -- which no CRC over the final state can distinguish from a clean
    failure.
    """
    lines = list(frame(grgl, pack(grgl)))
    body = lines[2].split()  # TABLE CHUNK <idx> <hex> <crc>
    body[3] = ("0" if body[3][0] != "0" else "1") + body[3][1:]  # one hex digit
    s = talk(board, [lines[0], lines[1], " ".join(body), *lines[3:]])
    assert not s.valid
    assert s.fail == "CHUNK_CRC"


def test_a_lie_about_the_length_is_refused(board, grgl):
    """The BEGIN line is not checksummed, so its numbers are exactly what a
    corrupted BEGIN would carry. A byte count that disagrees with the header's own
    record counts is caught before a single body byte is stored."""
    blob = pack(grgl)
    lines = list(frame(grgl, blob))
    a = lines[0].split()
    a[4] = str(int(a[4]) + 8)
    s = talk(board, [" ".join(a), *lines[1:]])
    assert not s.valid
    assert s.fail == "SIZE"


def test_a_lie_about_the_crc_is_refused(board, grgl):
    """The other half of an unchecksummed BEGIN. The payload's trailing CRC and
    the one in BEGIN must agree with the bytes AND with each other -- the trailing
    copy alone cannot see a table that arrived intact and is not the one the host
    meant to send."""
    blob = pack(grgl)
    lines = list(frame(grgl, blob))
    a = lines[0].split()
    a[5] = f"{(int(a[5], 16) ^ 0xFF):08x}"
    s = talk(board, [" ".join(a), *lines[1:]])
    assert not s.valid
    assert s.fail == "CRC"


def test_a_table_too_big_for_this_board_is_refused(board, grgl):
    """A count past capacity is not a slow table -- the arrays are statically
    sized, so it is a write past the end of a global. Checked before any of the
    header is adopted."""
    blob = bytearray(pack(grgl))
    blob[_hdr_offset("n_nodes")] = 200  # TG_MAX_STATES is 64
    #: Resealed, so this is a perfectly intact table that this board cannot hold.
    #: Capacity has to be its own check; the CRC cannot see it.
    s = upload(board, grgl, _reseal(blob))
    assert not s.valid
    assert s.fail == "TOO_LARGE"


def test_an_unknown_wire_format_is_refused(board, grgl):
    """A board must refuse a layout it does not know rather than guessing at
    offsets. This is what makes the format versionable at all."""
    blob = bytearray(pack(grgl))
    blob[_hdr_offset("wire_format")] = 99
    s = upload(board, grgl, _reseal(blob))
    assert not s.valid
    assert s.fail == "WIRE"


def test_something_that_is_not_a_table_is_refused(board, grgl):
    blob = bytearray(pack(grgl))
    blob[0:4] = b"XXXX"
    s = upload(board, grgl, _reseal(blob))
    assert not s.valid
    assert s.fail == "MAGIC"


def test_chunks_without_a_begin_are_refused(board, grgl):
    lines = list(frame(grgl, pack(grgl)))
    s = talk(board, lines[1:])
    assert not s.valid
    assert s.fail == "STATE"


def test_an_overlong_line_is_refused(board, grgl):
    """The truncation bug, in the form it actually takes on the wire."""
    lines = list(frame(grgl, pack(grgl)))
    s = talk(board, [lines[0], "TABLE CHUNK 0 " + "ab" * 200 + " 00000000", *lines[2:]])
    assert not s.valid
    assert s.fail == "LINE"


def test_garbage_is_refused(board):
    for line, reason in (
        ("TABLE BEGIN", "SYNTAX"),
        ("TABLE WHAT", "SYNTAX"),
        ("TABLE BEGIN x zz 10 ff", "SYNTAX"),
    ):
        s = talk(board, [line])
        assert not s.valid, line
        assert s.fail == reason, line


def test_lines_that_are_not_ours_are_ignored(board, grgl):
    """A migrated box still has to answer everything else it used to. An
    unrecognised line must pass through, not abort an upload in progress."""
    lines = list(frame(grgl, pack(grgl)))
    s = talk(board, [lines[0], "SEED\t1234", *lines[1:-1], "PING", lines[-1]])
    assert s.valid, s.fail


# --------------------------------------------------------------------------- #
# What a refusal leaves behind
# --------------------------------------------------------------------------- #


def test_a_failed_upload_never_leaves_a_usable_table(board, grgl):
    """THE POINT OF ALL OF IT.

    A refused upload has already partially overwritten the table -- the receiver
    decodes as it goes, deliberately, to avoid a second 2 KB buffer. So `valid`
    is cleared the instant BEGIN arrives and set only after the CRC verifies.
    There must be no failure mode that leaves it true.
    """
    good = list(frame(grgl, pack(grgl)))
    assert talk(board, good).valid

    blob = bytearray(pack(grgl))
    blob[HEADER_SIZE + 3] ^= 0x80
    bad = list(frame(grgl, bytes(blob)))

    #: A good upload, then a bad one. The table is left holding wreckage, and the
    #: flag must say so -- this is the sequence a retry actually produces.
    s = talk(board, good + bad)
    assert not s.valid, "a failed retry left the previous table looking current"
    assert s.fail == "CRC"


def test_the_host_reader_raises_on_every_refusal(board, grgl):
    blob = bytearray(pack(grgl))
    blob[HEADER_SIZE] ^= 0x01
    s = upload(board, grgl, bytes(blob))
    with pytest.raises(UploadError, match="refused"):
        interpret(s.replies, crc32(bytes(blob)))


def test_silence_is_a_failure(board):
    """A board that neither accepts nor refuses has not finished the
    conversation, and the host must not treat that as success."""
    with pytest.raises(UploadError, match="never said"):
        interpret(["TABLE ACK 0"], 0)

"""The upload protocol, host side.

Framing only — turning packed bytes into the lines a board reads, and reading the
lines it sends back. Nothing here opens a serial port; that is `taskgraph
transport upload`, and keeping the two apart is what lets the whole protocol be
tested against a simulated board with no hardware and no timing.

## The sequence

    host  → TABLE BEGIN <spec_id> <spec_hash> <n_bytes> <crc32>
    board → TABLE ACK 0
    host  → TABLE CHUNK 0 <hex> <chunk_crc>
    board → TABLE ACK 1
            ... repeat ...
    host  → TABLE END
    board → TABLE OK <crc32>        (or TABLE FAIL <reason>)

Hex rather than raw binary, because the session reader is line-oriented and a raw
`0x0A` inside a table is indistinguishable from a terminator
(`docs/spikes/transport.md`). It doubles the bytes on the wire and costs 0.1 s for
a real table at 115200, which buys away an entire class of framing ambiguity in
the one path whose failure mode is a silently truncated table.

## Why a per-chunk checksum on top of a whole-table CRC

The whole-table CRC is what decides whether a table may run. The per-chunk
checksum decides *where* a failed upload went wrong, and lets a single bad chunk
be identified rather than a 700-byte transfer being declared bad as a unit. The
board checks a chunk before storing any of its bytes, so a rejected chunk leaves
the table untouched by it.
"""

from __future__ import annotations

import zlib
from collections.abc import Iterator

from ephymeris_sidecar.taskgraph.emit.pack import CHUNK_BYTES, CRC_SIZE, HEADER_SIZE, crc32
from ephymeris_sidecar.taskgraph.table import StateTable


def _crc(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def frame(table: StateTable, packed: bytes, chunk: int = CHUNK_BYTES) -> Iterator[str]:
    """The complete conversation the host sends, in order.

    `packed` is passed in rather than recomputed so the caller can send bytes it
    has already written to disk — and so a test can send bytes it has
    deliberately corrupted, which is most of what the negative cases do.

    The CRC in BEGIN is READ OUT OF the payload rather than recomputed over it.
    If the packer ever produced a payload whose trailing CRC did not match its
    own contents, recomputing here would paper over it and hand the board two
    numbers that agree with each other and not with the bytes. Reading it means
    the board catches the packer.
    """
    yield (
        f"TABLE BEGIN {table.spec_id} {int(table.spec_hash[:8], 16):08x} "
        f"{len(packed)} {crc32(packed):08x}"
    )
    for i in range(0, len(packed), chunk):
        piece = packed[i : i + chunk]
        yield f"TABLE CHUNK {i // chunk} {piece.hex()} {_crc(piece):08x}"
    yield "TABLE END"


def chunk_count(packed: bytes, chunk: int = CHUNK_BYTES) -> int:
    return (len(packed) + chunk - 1) // chunk


class UploadError(RuntimeError):
    """The board refused the table, and said why."""


def body_digest(packed: bytes) -> int:
    """What the board's `DIGEST=` must equal.

    The board re-serialises the table it DECODED and checksums that. A correct
    decode reproduces the body verbatim, so the expected value is simply CRC32 of
    the body the host sent — no second implementation, and nothing here that could
    agree with a wrong board by making the same mistake.
    """
    return _crc(packed[HEADER_SIZE:-CRC_SIZE])


def interpret(replies: list[str], expected_crc: int, expected_digest: int | None = None) -> int:
    """Read the board's side of the conversation. Returns the accepted CRC.

    Raises rather than returning a status, because there is exactly one correct
    thing to do with a refused upload and it is not to continue.
    """
    for line in replies:
        if line.startswith("TABLE FAIL"):
            raise UploadError(f"board refused the table: {line.split(maxsplit=2)[-1]}")
    ok = [ln for ln in replies if ln.startswith("TABLE OK")]
    if not ok:
        raise UploadError(
            "board never said TABLE OK. It neither accepted nor refused, which "
            "means the conversation did not finish — treat it as a failure."
        )
    fields = ok[-1].split()
    got = int(fields[2], 16)
    if got != expected_crc:
        #: Belt and braces: the board reports the CRC it computed, and the host
        #: checks it against the one it sent. Two implementations of CRC32
        #: agreeing on 700 bytes is a stronger statement than either one alone.
        raise UploadError(
            f"board accepted a table with crc {got:#010x}, host sent {expected_crc:#010x}"
        )

    if expected_digest is not None:
        #: THE CHECK THE CRC CANNOT MAKE. `crc` says the right bytes arrived.
        #: `DIGEST` says they were put in the right fields — a decode that read a
        #: record at the wrong stride produces a perfect CRC and a wrong table.
        digest = next(
            (int(f.split("=", 1)[1], 16) for f in fields if f.startswith("DIGEST=")), None
        )
        if digest is None:
            raise UploadError(
                "board reported no DIGEST. Its firmware predates the decode check, "
                "so an intact transfer into the wrong fields would go unnoticed."
            )
        if digest != expected_digest:
            raise UploadError(
                f"board decoded the table into different fields: digest {digest:#010x}, "
                f"expected {expected_digest:#010x}. The bytes arrived intact, so this "
                f"is a decode fault, not a transfer fault."
            )
    return got

"""The conversation: read the banner, check the fit, upload, verify.

Four steps, and the order is the design. The capability check happens BEFORE a
single byte of table is sent, so a board that cannot hold this task says so in
milliseconds rather than after a 700-byte transfer — and says it by naming both
numbers, which is the entire reason `CAP` exists.

WHAT COUNTS AS SUCCESS. Not "the board said OK". The board must report the CRC the
host sent *and* a digest matching the body the host packed. The first says the
bytes arrived; the second says they were decoded into the right fields. A transfer
can be perfect and a decode wrong, and only the second catches it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ephymeris_sidecar.taskgraph.emit.pack import WIRE_FORMAT, crc32, pack
from ephymeris_sidecar.taskgraph.table import StateTable
from ephymeris_sidecar.taskgraph.transport import UploadError, body_digest, chunk_count, frame, interpret
from ephymeris_sidecar.taskgraph.transport.caps import Capabilities, check, parse
from ephymeris_sidecar.taskgraph.transport.link import Link

READY = "READY"


@dataclass
class Result:
    caps: Capabilities
    banner: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    crc: int = 0
    digest: int = 0
    n_bytes: int = 0
    chunks: int = 0
    seconds: float = 0.0


def read_banner(link: Link, timeout: float = 10.0) -> tuple[list[str], Capabilities]:
    """Everything up to and including a bare `READY`.

    `READY` is matched as an EXACT WHOLE LINE, the same way the deployed host
    matches it. Anything before it is free — which is what lets a migrated box
    talk to an un-migrated host — so everything is collected and handed back
    rather than filtered here.

    `timeout` is a TOTAL budget, not per line. Per-line was an unbounded loop
    in disguise: a board streaming at the WRONG baud produces garbage "lines"
    whenever a 0x0A lands in the noise, each one resetting the clock — so
    `detect()` against a chatty legacy sketch (BOX_Utility emits STATUS
    continuously) hung forever at the 115200 attempt instead of failing in
    four seconds. Silence and chatter must exhaust the same budget. Found on
    real hardware; every off-target link is either silent or well-framed,
    which is why no gate ever saw it.
    """
    import time

    deadline = time.monotonic() + timeout
    lines: list[str] = []
    while True:
        remaining = deadline - time.monotonic()
        line = link.read_line(remaining) if remaining > 0 else None
        if line is None:
            raise UploadError(
                "board never reported READY.\n"
                "The usual cause is a baud mismatch: the board answers at a rate "
                "nobody is listening at — silence if it is quiet, undecodable "
                "noise if it is chatty, and neither contains READY. Check the "
                "flashed TG_BAUD_RATE against --baud."
            )
        lines.append(line)
        if line == READY:
            return lines, parse(lines)


def upload(link: Link, table: StateTable, *, packed: bytes | None = None,
           timeout: float = 10.0) -> Result:
    """Put a compiled table on a board, or raise saying why not."""
    import time

    blob = packed if packed is not None else pack(table)
    banner, caps = read_banner(link, timeout)

    #: Before any bytes. A board that cannot hold this table should cost a
    #: millisecond to find out, not a full transfer plus a CRC failure that says
    #: nothing about which dimension was the problem.
    notes = check(caps, table, WIRE_FORMAT)

    started = time.monotonic()
    replies: list[str] = []
    for line in frame(table, blob):
        link.write_line(line)
    while True:
        reply = link.read_line(timeout)
        if reply is None:
            raise UploadError(
                f"board went quiet after {len(replies)} of {chunk_count(blob) + 1} "
                f"acknowledgements. A partial upload leaves table.valid false, so "
                f"the board will refuse to run — but nothing has confirmed that."
            )
        if not reply.startswith("TABLE "):
            continue  # informational lines are the board's business, not ours
        replies.append(reply)
        if reply.startswith(("TABLE OK", "TABLE FAIL")):
            break
    elapsed = time.monotonic() - started

    digest = body_digest(blob)
    crc = interpret(replies, crc32(blob), digest)
    return Result(
        caps=caps, banner=banner, replies=replies, notes=notes,
        crc=crc, digest=digest, n_bytes=len(blob),
        chunks=chunk_count(blob), seconds=elapsed,
    )


def probe(link: Link, timeout: float = 10.0) -> tuple[list[str], Capabilities]:
    """Read the banner and stop. What a box says about itself, without changing
    anything on it."""
    return read_banner(link, timeout)


#: Rates to try, most likely first. Deliberately short: these are the two the
#: fleet actually contains during the 9600 -> 115200 rollout, and a longer list
#: turns a fast answer into a slow one for no gain.
CANDIDATE_BAUDS = (115200, 9600)


def detect(open_link, bauds=CANDIDATE_BAUDS, timeout: float = 4.0):
    """Find the rate a box is actually running at.

    WHY THIS EXISTS RATHER THAN A SYNCHRONISED FLIP. A baud mismatch is not a
    clean error — it is a board that never answers, which reads as a dead board.
    That is what made the 9600/115200 split a flag day: every sketch and every
    host had to move in the same change, and a box flashed but not switched
    host-side was mute until someone noticed.

    Trying two rates and keeping the one that answers removes the flag day. A
    fleet can then contain boxes at both rates — which it does for as long as the
    rollout takes. Every sketch in source opens at 115200 now, but a box runs the
    firmware it was last flashed with, so a box nobody has reflashed is still at
    9600 and stays there until someone gets to it. The tooling reports which.

    `open_link` is a callable taking a baud and returning a Link, so this works
    against a real port and against anything else that speaks lines.

    THE LINK IS CLOSED BEFORE RETURNING, and only the rate comes back. Reading
    the banner consumes it, and a caller handed a live link would then wait for a
    READY that has already gone past — which is exactly what the first version
    did, reporting a successful detection and a timeout in the same breath. The
    caller reopens, which costs one board reset and removes the question.
    """
    tried: list[tuple[int, str]] = []
    for baud in bauds:
        link = open_link(baud)
        try:
            _banner, caps = read_banner(link, timeout)
        except UploadError as exc:
            tried.append((baud, str(exc).splitlines()[0]))
            continue
        finally:
            link.close()

        #: A box that answers at one rate and DECLARES another is worth shouting
        #: about: the CAP line and the port it arrived on disagree, which no
        #: amount of retrying will fix.
        declared = caps.get("BAUD")
        if declared is not None and declared != baud:
            raise UploadError(
                f"the board answered at {baud} but announces BAUD={declared}. "
                f"Its TG_BAUD_RATE and the rate it opened at have diverged, which "
                f"is a firmware bug rather than a configuration one."
            )
        return baud

    detail = "\n".join(f"    {b}: {why}" for b, why in tried)
    raise UploadError("no rate answered:\n" + detail)

"""The uploader: does it refuse the right things, and refuse them early?

Driven against `tg_board`, which announces the same CAP banner a flashed board
does and runs the same receiver. Only the clock and Serial are mocked, so the
conversation under test is the real one.

THE CHECK THAT MATTERS IS THE ONE BEFORE THE BYTES. `CAP` exists so the host stops
compiling its own copy of MAXSTATES — the pattern that put START_LINE_MAX in two
repos and baudRate in nine files, whose failure mode is not a build error but a
board silently truncating a table. So the capability check has to happen before a
single byte is sent, and it has to name both numbers.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph.emit.pack import WIRE_FORMAT, crc32, pack
from ephymeris_sidecar.taskgraph.pipeline import compile_spec
from ephymeris_sidecar.taskgraph.transport import UploadError, body_digest
from ephymeris_sidecar.taskgraph.transport.caps import CapabilityError, check, parse
from ephymeris_sidecar.taskgraph.transport.client import read_banner, upload
from ephymeris_sidecar.taskgraph.transport.link import Link, ProcessLink

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, all_specs, spec,
)

LIB = FIRMWARE_LIB


pytestmark = pytest.mark.skipif(
    shutil.which("clang++") is None or not (BEHAVIORBOX / "BehaviorBox.h").is_file(),
    reason="needs clang++ and the reference BehaviorBox.h",
)


@pytest.fixture(scope="module")
def board(tmp_path_factory) -> Path:
    binary = tmp_path_factory.mktemp("tg_board") / "tg_board"
    subprocess.run(
        ["clang++", "-std=c++17", "-Wall", "-I", str(HOST_TEST), "-I", str(LIB),
         "-I", str(BEHAVIORBOX), str(HOST_TEST / "tg_board.cpp"), "-o", str(binary)],
        check=True, capture_output=True,
    )
    return binary


@pytest.fixture(scope="module")
def grgl():
    r = compile_spec(spec("two_afc"))
    assert r.ok, r.bag.render()
    return r.table


class ScriptedLink(Link):
    """A board that says exactly what a test tells it to, and reads nothing.

    For the cases hardware cannot easily produce: a box that never says READY, one
    that goes quiet mid-transfer, one running firmware from a different era.
    """

    def __init__(self, lines: list[str]) -> None:
        self.said = list(lines)
        self.heard: list[str] = []

    def write_line(self, text: str) -> None:
        self.heard.append(text)

    def read_line(self, timeout: float) -> str | None:
        return self.said.pop(0) if self.said else None


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec_id", [p.stem for p in all_specs()])
def test_every_spec_uploads(board, spec_id):
    r = compile_spec(spec(spec_id))
    blob = pack(r.table)
    with ProcessLink([board]) as link:
        result = upload(link, r.table, packed=blob)
    assert result.crc == crc32(blob)
    assert result.digest == body_digest(blob)
    assert result.caps.get("MAXSTATES") == 64
    assert not result.notes, result.notes


def test_the_banner_is_read_up_to_an_exact_ready(board):
    with ProcessLink([board]) as link:
        banner, caps = read_banner(link)
    assert banner[-1] == "READY", "READY is matched as an exact whole line"
    assert all(ln.startswith("CAP\t") for ln in banner[:-1])
    assert caps.get("PROTO") == 2
    assert caps.get("WIRE") == WIRE_FORMAT


# --------------------------------------------------------------------------- #
# Refusals, before the bytes
# --------------------------------------------------------------------------- #


def test_a_table_too_big_is_refused_by_name(grgl):
    """THE POINT OF CAP.

    Not "the upload failed" — which dimension, this table's number, and the
    board's number. Anything less sends someone to read the firmware.
    """
    caps = parse(["CAP\tPROTO=2 TASKGRAPH=1 WIRE=1", "CAP\tMAXSTATES=8 MAXEDGES=128"])
    with pytest.raises(CapabilityError) as exc:
        check(caps, grgl, WIRE_FORMAT)
    assert "nodes: 26 > 8" in str(exc.value)


def test_a_wire_format_mismatch_is_refused(grgl):
    """A board reading a different byte layout would fail the CRC anyway. Saying
    so up front is the difference between a diagnosis and a symptom."""
    caps = parse(["CAP\tPROTO=2 TASKGRAPH=1 WIRE=99"])
    with pytest.raises(CapabilityError, match="wire-format mismatch"):
        check(caps, grgl, WIRE_FORMAT)


def test_a_board_with_no_wire_version_is_refused(grgl):
    caps = parse(["CAP\tPROTO=2 TASKGRAPH=1"])
    with pytest.raises(CapabilityError, match="no WIRE version"):
        check(caps, grgl, WIRE_FORMAT)


def test_an_unmigrated_box_is_recognised_not_blamed(grgl):
    """No CAP line is PROTO=1, the legacy path — a normal state of the fleet, and
    the reason the rollout can be per-box. It must not read as a malfunction."""
    caps = parse(["READY"])
    assert not caps.present
    with pytest.raises(CapabilityError, match="un-migrated firmware"):
        check(caps, grgl, WIRE_FORMAT)


def test_an_old_protocol_is_refused(grgl):
    caps = parse(["CAP\tPROTO=1 TASKGRAPH=1 WIRE=1"])
    with pytest.raises(CapabilityError, match="predates table upload"):
        check(caps, grgl, WIRE_FORMAT)


def test_an_unannounced_limit_is_a_note_not_a_failure(grgl):
    """Unknown keys are ignored by both sides — that is what makes the vocabulary
    extensible. But a limit this host DOES check and the board did not announce
    means that dimension went unverified, and silence about it would be a lie."""
    caps = parse(["CAP\tPROTO=2 TASKGRAPH=1 WIRE=1 MAXSTATES=64"])
    notes = check(caps, grgl, WIRE_FORMAT)
    assert any("MAXEDGES" in n for n in notes)
    assert all("MAXSTATES" not in n for n in notes)


def test_nothing_is_sent_when_the_table_does_not_fit(grgl):
    """Early, not eventually. A refusal after a 700-byte transfer is a worse
    diagnosis and a wasted second."""
    link = ScriptedLink(["CAP\tPROTO=2 TASKGRAPH=1 WIRE=1 MAXSTATES=8", "READY"])
    with pytest.raises(CapabilityError):
        upload(link, grgl)
    assert link.heard == [], "the uploader sent bytes to a board that cannot hold them"


# --------------------------------------------------------------------------- #
# Boards that misbehave
# --------------------------------------------------------------------------- #


def test_a_silent_board_names_the_likely_cause(grgl):
    """The documented failure of a baud mismatch is not an error — it is silence.
    A message that only says "timeout" leaves the actual cause unnamed."""
    with pytest.raises(UploadError, match="baud mismatch"):
        upload(ScriptedLink([]), grgl)


def test_a_board_that_stops_mid_transfer_is_a_failure(grgl):
    """Neither accepted nor refused. The message has to say the table is NOT
    known to be good, because `valid` staying false is invisible from here."""
    link = ScriptedLink(
        ["CAP\tPROTO=2 TASKGRAPH=1 WIRE=1", "READY", "TABLE ACK 0", "TABLE ACK 1"]
    )
    with pytest.raises(UploadError, match="went quiet"):
        upload(link, grgl)


def test_a_refusal_is_reported_with_the_board_s_reason(board, grgl):
    blob = bytearray(pack(grgl))
    blob[120] ^= 0x40
    with ProcessLink([board]) as link, pytest.raises(UploadError, match="CRC"):
        upload(link, grgl, packed=bytes(blob))


def test_a_board_reporting_the_wrong_digest_is_refused(grgl):
    """A DECODE fault, which the CRC by construction cannot see.

    Scripted rather than driven through tg_board, because producing it needs a
    board that decodes wrongly — and the whole point of the digest is that no
    board we have does. The CRC is correct here and only the digest is not, so
    this fails on exactly the path under test.
    """
    blob = pack(grgl)
    link = ScriptedLink([
        "CAP\tPROTO=2 TASKGRAPH=1 WIRE=1",
        "READY",
        f"TABLE OK {crc32(blob):08x} DIGEST={body_digest(blob) ^ 0xBEEF:08x}",
    ])
    with pytest.raises(UploadError, match="different fields"):
        upload(link, grgl, packed=blob)


def test_firmware_predating_the_digest_is_not_silently_trusted(grgl):
    """An older board answers `TABLE OK <crc>` and stops. Treating the absent
    field as "fine" would disable the check on exactly the firmware most likely
    to need it."""
    blob = pack(grgl)
    link = ScriptedLink([
        "CAP\tPROTO=2 TASKGRAPH=1 WIRE=1",
        "READY",
        f"TABLE OK {crc32(blob):08x}",
    ])
    with pytest.raises(UploadError, match="no DIGEST"):
        upload(link, grgl, packed=blob)


# --------------------------------------------------------------------------- #
# The command line
# --------------------------------------------------------------------------- #


def run_cli(*argv: str) -> subprocess.CompletedProcess:
    import sys

    return subprocess.run(
        [sys.executable, "-m", "ephymeris_sidecar.taskgraph.cli", *argv],
        cwd=REPO_ROOT / "sidecar", capture_output=True, text=True,
    )


def test_the_cli_uploads(board):
    r = run_cli("upload", str(spec("go_nogo")), "--board", str(board))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "accepted:" in r.stdout
    assert "digest=" in r.stdout


def test_the_cli_dry_run_opens_nothing():
    """Compile and pack, stop before the wire — so a spec can be checked for fit
    without walking to the rig."""
    r = run_cli("upload", str(spec("go_nogo")), "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "bytes, crc32=" in r.stdout
    assert "accepted" not in r.stdout


def test_the_cli_probes(board):
    r = run_cli("probe", "--board", str(board))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "READY" in r.stdout
    assert "capabilities announced" in r.stdout


def test_the_cli_needs_a_target():
    r = run_cli("probe")
    assert r.returncode != 0
    assert "--port" in r.stderr


# --------------------------------------------------------------------------- #
# Baud detection — the rollout's actual fix
# --------------------------------------------------------------------------- #


def test_detection_finds_the_rate_that_answers():
    """A mixed-rate fleet is the normal state, not an outage.

    The interpreter firmware opens at 115200 while the eight behaviour sketches
    open at 9600, so "which rate is this box at" is a real question. Trying two
    and keeping the one that answers costs one board reset.
    """
    from ephymeris_sidecar.taskgraph.transport.client import detect

    opened: list[int] = []

    def open_link(baud: int):
        opened.append(baud)
        if baud != 9600:
            return ScriptedLink([])  # silence, which is what a mismatch looks like
        return ScriptedLink(["CAP\tPROTO=2 TASKGRAPH=1 WIRE=1 BAUD=9600", "READY"])

    assert detect(open_link) == 9600
    assert opened == [115200, 9600], "candidates must be tried most-likely first"


def test_detection_reports_every_rate_it_tried():
    """A box that answers nowhere is a different problem from a baud mismatch, and
    the message has to let someone tell them apart."""
    from ephymeris_sidecar.taskgraph.transport.client import detect

    with pytest.raises(UploadError, match="no rate answered") as exc:
        detect(lambda b: ScriptedLink([]))
    assert "115200" in str(exc.value) and "9600" in str(exc.value)


def test_a_chatty_board_at_the_wrong_baud_exhausts_the_budget():
    """The timeout is a TOTAL budget, not per line.

    Found on real hardware: BOX_Utility streams STATUS continuously, and at the
    wrong baud that stream yields garbage "lines" whenever a 0x0A lands in the
    noise — each one reset a per-line clock, so detect() hung forever at the
    115200 attempt instead of failing in four seconds. Silence and chatter must
    look the same to the budget, because neither contains READY.
    """
    import itertools
    import time

    from ephymeris_sidecar.taskgraph.transport.client import read_banner

    class ChattyLink(Link):
        """Garbage lines forever, arriving fast — never a READY."""

        def __init__(self) -> None:
            self.counter = itertools.count()

        def write_line(self, text: str) -> None:  # pragma: no cover - never written
            pass

        def read_line(self, timeout: float) -> str | None:
            return f"\x9c\xf3 noise {next(self.counter)}"

    started = time.monotonic()
    with pytest.raises(UploadError, match="never reported READY"):
        read_banner(ChattyLink(), timeout=0.3)
    assert time.monotonic() - started < 2.0, "the budget did not bound a chatty board"


def test_a_board_answering_at_one_rate_and_declaring_another_is_a_firmware_bug():
    """CAP says BAUD=9600 on a port opened at 115200. No retry fixes that, so it
    is raised rather than papered over."""
    from ephymeris_sidecar.taskgraph.transport.client import detect

    def open_link(baud: int):
        return ScriptedLink(["CAP\tPROTO=2 TASKGRAPH=1 WIRE=1 BAUD=9600", "READY"])

    with pytest.raises(UploadError, match="firmware bug"):
        detect(open_link)


def test_detection_does_not_hand_back_a_consumed_link():
    """The bug the first version had: it returned the live link it had read the
    banner from, so the caller waited for a READY that had already gone past —
    and reported a successful detection and a timeout in the same breath."""
    from ephymeris_sidecar.taskgraph.transport.client import detect

    closed: list[bool] = []

    class Tracking(ScriptedLink):
        def close(self) -> None:
            closed.append(True)

    result = detect(lambda b: Tracking(["CAP\tPROTO=2 TASKGRAPH=1 WIRE=1", "READY"]))
    assert isinstance(result, int), "detect must return only the rate"
    assert closed, "the link it probed with must be closed"

"""Per-animal session writer — `data-saving.md` §5, §7.

Includes the crash-durability kill test §7.3 asks for: SIGKILL a live writer
mid-session and prove the `.tsv` is intact up to the last flushed line.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ephymeris_sidecar.sessions.writer import AnimalWriter, WriteError

CORE = {
    "rat": "remy1",
    "serial_port": "COM6",
    "session_id": "2O-Bdisc_25",
    "sketch": "GRGL_2-Odor",
}
CONFIG = {"correction_left": 0, "correction_right": 0, "lazy_escalation": True}


def make_writer(tmp_path: Path) -> AnimalWriter:
    return AnimalWriter(
        tmp_path / "behavior.tsv" / "remy1.tsv",
        tmp_path / "behavior.json" / "remy1.json",
        tmp_path / "behavior.mat" / "remy1.mat",
        core_metadata=CORE,
        config_metadata=CONFIG,
    )


# --- §7.1 the .tsv header and live lines ----------------------------------


def test_the_header_is_written_before_any_strobe(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    writer.open_files()
    lines = (tmp_path / "behavior.tsv" / "remy1.tsv").read_text().splitlines()
    # All comment lines, no data yet, and the two footer-only fields absent.
    assert all(line.startswith("#") for line in lines)
    assert any(line == "# rat: remy1" for line in lines)
    assert any(line == "# lazy_escalation: true" for line in lines)
    assert not any("stop_reason" in line for line in lines)
    assert not any("n_events" in line for line in lines)


def test_strobes_append_in_the_boards_exact_format(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    writer.open_files()
    writer.record(221, 0)
    writer.record(222, 1000)
    data_lines = [
        line
        for line in (tmp_path / "behavior.tsv" / "remy1.tsv").read_text().splitlines()
        if not line.startswith("#")
    ]
    assert data_lines == ["221\t0", "222\t1000"]


# --- §7.1/§7.2 finalization -----------------------------------------------


def test_finalize_writes_the_footer_and_builds_json_and_mat(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    writer.open_files()
    writer.record(221, 0)
    writer.record(246, 3523555)
    document = writer.finalize("BF_END_SESSION received")

    tsv = (tmp_path / "behavior.tsv" / "remy1.tsv").read_text()
    assert "# stop_reason: BF_END_SESSION received" in tsv
    assert "# n_events: 2" in tsv

    # §5 — core + flat config + data, in one document, matching the sample shape.
    assert document["rat"] == "remy1"
    assert document["correction_left"] == 0
    assert document["lazy_escalation"] is True
    assert document["stop_reason"] == "BF_END_SESSION received"
    assert document["n_events"] == 2
    assert document["ts_data"] == [[221, 0], [246, 3523555]]

    assert (tmp_path / "behavior.json" / "remy1.json").is_file()
    assert (tmp_path / "behavior.mat" / "remy1.mat").is_file()

    import json

    on_disk = json.loads((tmp_path / "behavior.json" / "remy1.json").read_text())
    assert on_disk == document


def test_config_fields_are_flat_at_the_top_level_not_nested(tmp_path: Path) -> None:
    """§5 — matches the sample exactly: no `config` wrapper key."""
    writer = make_writer(tmp_path)
    writer.open_files()
    document = writer.finalize("operator stop")
    assert "config" not in document
    assert document["correction_right"] == 0


def test_finalize_is_idempotent(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    writer.open_files()
    writer.record(221, 0)
    first = writer.finalize("operator stop")
    second = writer.finalize("something else")
    # A second finalize neither re-runs nor changes the recorded reason.
    assert first["stop_reason"] == "operator stop"
    assert second["stop_reason"] == "operator stop"


def test_records_after_finalize_are_ignored(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    writer.open_files()
    writer.finalize("operator stop")
    writer.record(999, 1)  # no-op, no crash
    assert writer.event_count == 0


def test_a_write_to_a_bad_path_raises_writeerror(tmp_path: Path) -> None:
    # Point the .tsv at a path whose parent is a file, so mkdir/open fails.
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    writer = AnimalWriter(
        blocker / "nested" / "remy1.tsv",
        tmp_path / "j.json",
        tmp_path / "m.mat",
        core_metadata=CORE,
        config_metadata=CONFIG,
    )
    with pytest.raises((WriteError, OSError)):
        writer.open_files()


# --- §7.3 crash durability: the kill test ---------------------------------


def test_tsv_survives_a_mid_session_sigkill(tmp_path: Path) -> None:
    """SIGKILL a live writer; the .tsv must hold every flushed line, no footer.

    This is the guarantee `data-saving.md` §7 exists to make real: if the lab PC
    loses power mid-session, everything up through the last completed line is
    already on disk.
    """
    tsv = tmp_path / "behavior.tsv" / "remy1.tsv"
    json_path = tmp_path / "behavior.json" / "remy1.json"
    mat = tmp_path / "behavior.mat" / "remy1.mat"
    ready = tmp_path / "ready"
    n_lines = 8

    child = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).parent / "_kill_writer_child.py"),
            str(tsv),
            str(json_path),
            str(mat),
            str(n_lines),
            str(ready),
        ]
    )
    try:
        # Wait for the child to confirm all lines are written and fsync'd.
        deadline = time.time() + 15
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "child never signalled ready"

        # Kill it hard — no cleanup, no finalize, simulating power loss.
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=5)
    finally:
        if child.poll() is None:
            child.kill()

    # The .tsv is intact: header + exactly the flushed data lines.
    contents = tsv.read_text().splitlines()
    header = [line for line in contents if line.startswith("#")]
    data = [line for line in contents if not line.startswith("#")]

    assert any(line == "# rat: remy1" for line in header)
    assert len(data) == n_lines
    assert data[0] == "100\t0"
    assert data[-1] == f"{100 + n_lines - 1}\t{(n_lines - 1) * 1000}"

    # Footer never written (no finalize), and the structured formats never built.
    assert not any("stop_reason" in line for line in header)
    assert not json_path.exists()
    assert not mat.exists()

"""Per-animal session writer — `data.md` §4, §7.

Includes the crash-durability kill test §7.3 asks for: hard-kill a live writer
mid-session and prove the `.tsv` is intact up to the last flushed line.
"""

from __future__ import annotations

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

#: A minimal but real Task Profile — enough of one that `parse_profile` accepts
#: it, since the point of the snapshot is that the other end parses it.
PROFILE = {
    "taskName": "GRGL 2-Odor",
    "kind": "behavior",
    "config": [
        {"metadataKey": "correction_left", "wireKey": "CL", "label": "Correction L",
         "type": "int", "default": 0},
    ],
    "strobes": {"101": "ODOR_1_ON", "249": "WATER_POKE_R"},
    "liveMetrics": [
        {"id": "p_correct_1", "label": "P(right well | Go right)", "triggerCode": 101,
         "successCode": 249, "alternateCode": 248, "windowSize": 20},
    ],
}


def make_writer(tmp_path: Path, *, profile: dict | None = PROFILE) -> AnimalWriter:
    return AnimalWriter(
        tmp_path / "behavior.tsv" / "remy1.tsv",
        tmp_path / "behavior.json" / "remy1.json",
        tmp_path / "behavior.mat" / "remy1.mat",
        core_metadata=CORE,
        config_metadata=CONFIG,
        profile_snapshot=profile,
    )


# --- §7.1 the .tsv header and live lines ----------------------------------


def test_the_header_is_written_before_any_strobe(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    writer.open_files()
    lines = (tmp_path / "behavior.tsv" / "remy1.tsv").read_text(encoding="utf-8").splitlines()
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
        for line in (tmp_path / "behavior.tsv" / "remy1.tsv").read_text(encoding="utf-8").splitlines()
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

    tsv = (tmp_path / "behavior.tsv" / "remy1.tsv").read_text(encoding="utf-8")
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

    on_disk = json.loads((tmp_path / "behavior.json" / "remy1.json").read_text(encoding="utf-8"))
    assert on_disk == document


def test_config_fields_are_flat_at_the_top_level_not_nested(tmp_path: Path) -> None:
    """§5 — matches the sample exactly: no `config` wrapper key."""
    writer = make_writer(tmp_path)
    writer.open_files()
    document = writer.finalize("operator stop")
    assert "config" not in document
    assert document["correction_right"] == 0


def test_the_document_carries_its_task_profile(tmp_path: Path) -> None:
    """§4.4 — the file is self-describing, which is what lets a copy of it
    decode on a machine that has never seen the sketch."""
    import json

    from ephymeris_sidecar.tasks.profile import SNAPSHOT_KEY, embedded_profile

    writer = make_writer(tmp_path)
    writer.open_files()
    writer.record(101, 5)
    document = writer.finalize("BF_END_SESSION received")

    assert document[SNAPSHOT_KEY] == PROFILE
    on_disk = json.loads(
        (tmp_path / "behavior.json" / "remy1.json").read_text(encoding="utf-8")
    )
    assert embedded_profile(on_disk) is not None
    assert embedded_profile(on_disk).live_metrics[0].id == "p_correct_1"


def test_the_tsv_header_carries_the_snapshot_on_one_line(tmp_path: Path) -> None:
    """The write-ahead log is the file a crash leaves behind, and recovery
    rebuilds a `.json` from it — so the snapshot has to be in the header, and
    compact enough not to turn the log into a document."""
    from ephymeris_sidecar.tasks.profile import SNAPSHOT_KEY

    writer = make_writer(tmp_path)
    writer.open_files()
    lines = (
        (tmp_path / "behavior.tsv" / "remy1.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    snapshot = [line for line in lines if line.startswith(f"# {SNAPSHOT_KEY}: ")]
    assert len(snapshot) == 1
    # Last of the header, after the fields a person actually reads.
    assert lines[-1] == snapshot[0]


def test_a_profile_less_sketch_writes_no_snapshot(tmp_path: Path) -> None:
    """Running a bare `START` is supported (`tasks.md` §3), and a document that
    carried an empty snapshot would claim a declaration that never existed."""
    from ephymeris_sidecar.tasks.profile import SNAPSHOT_KEY

    writer = make_writer(tmp_path, profile=None)
    writer.open_files()
    document = writer.finalize("BF_END_SESSION received")

    assert SNAPSHOT_KEY not in document
    assert SNAPSHOT_KEY not in (
        tmp_path / "behavior.tsv" / "remy1.tsv"
    ).read_text(encoding="utf-8")


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


def test_an_existing_tsv_is_refused_not_overwritten(tmp_path: Path) -> None:
    """§7.1 — the durable file is opened exclusively.

    The `HHMMSS` in the filename makes this practically unreachable, but this
    is the one file carrying the durability guarantee: refusing to start beats
    silently truncating a previous animal's data.
    """
    writer = make_writer(tmp_path)
    writer.open_files()
    writer.record(221, 0)
    writer.finalize("operator stop")
    existing = (tmp_path / "behavior.tsv" / "remy1.tsv").read_text(encoding="utf-8")

    with pytest.raises(WriteError) as caught:
        make_writer(tmp_path).open_files()

    # The message names the file standing in the way, so the operator can act.
    assert "already exists" in str(caught.value)
    assert "remy1.tsv" in str(caught.value)
    # And the first run's data is untouched.
    assert (tmp_path / "behavior.tsv" / "remy1.tsv").read_text(encoding="utf-8") == existing


def test_a_write_to_a_bad_path_raises_writeerror(tmp_path: Path) -> None:
    # Point the .tsv at a path whose parent is a file, so mkdir/open fails.
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")
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


def test_tsv_survives_a_mid_session_hard_kill(tmp_path: Path) -> None:
    """Hard-kill a live writer; the .tsv must hold every flushed line, no footer.

    This is the guarantee `data.md` §5 exists to make real: if the lab PC
    loses power mid-session, everything up through the last completed line is
    already on disk.

    The kill must stay uncatchable so nothing gets a chance to flush on the way
    out — `Popen.kill()` is SIGKILL on POSIX and `TerminateProcess` on Windows.
    Both matter here: the lab machines are Windows, so a POSIX-only signal would
    leave this guarantee untested on the platform that actually ships.
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
        child.kill()
        child.wait(timeout=5)
    finally:
        if child.poll() is None:
            child.kill()

    # The .tsv is intact: header + exactly the flushed data lines.
    contents = tsv.read_text(encoding="utf-8").splitlines()
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

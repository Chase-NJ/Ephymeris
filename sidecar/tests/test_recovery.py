"""Crash-recovery backfill — `DATA.md#crash-recovery`.

The invariant these protect: recovery is the inverse of `writer.AnimalWriter`.
A `.json` backfilled from an orphaned `.tsv` must match what `finalize` would
have written from the same strobes — same fields, same *types* — differing
only where honesty requires it (`stop_reason`, when the crash means the real
one was never recorded).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ephymeris_sidecar.analytics import reader
from ephymeris_sidecar.protocol import validate_command_result
from ephymeris_sidecar.sessions import recovery
from ephymeris_sidecar.sessions.paths import resolve_animal_files
from ephymeris_sidecar.sessions.writer import AnimalWriter

CORE = {
    "rat": "remy1",
    "serial_port": "COM3",
    "session_id": "2O-Bdisc_25",
    "sketch": "GRGL_2-Odor",
}
CONFIG = {"correction_left": 0, "lazy_escalation": True, "trial_seed": 288577176}
STROBES = [(101, 0), (249, 500), (103, 900), (248, 1400)]

#: The snapshot a live run carries (`DATA.md#the-embedded-task-profile`) — real enough to parse,
#: since the point of recovering it is that the other end can.
PROFILE = {
    "taskName": "GRGL 2-Odor",
    "kind": "behavior",
    "config": [],
    "strobes": {"101": "ODOR_1_ON"},
    "liveMetrics": [
        {"id": "p_correct_1", "label": "P(right well | Go right)", "triggerCode": 101,
         "successCode": 249, "alternateCode": 248, "windowSize": 20},
    ],
}


def crash_a_run(session_folder: Path, animal: str = "remy1") -> Path:
    """Write a real header + strobes through the real writer, then 'lose power'
    — close the handle without `finalize`, so no footer and no `.json`."""
    files = resolve_animal_files(
        session_folder, animal, "2O-Bdisc", "25", datetime(2026, 7, 22, 11, 31, 23)
    )
    writer = AnimalWriter(
        files.tsv, files.json, files.mat, dict(CORE), dict(CONFIG),
        profile_snapshot=PROFILE,
    )
    writer.open_files()
    for code, ts in STROBES:
        writer.record(code, ts)
    writer._tsv.close()  # the crash: no footer, no .json, no .mat
    return files.tsv


def finalized_document() -> dict:
    """What `finalize` would have produced from the same strobes — the target."""
    doc = {**CORE, **CONFIG}
    doc["task_profile"] = PROFILE
    doc["stop_reason"] = recovery.RECOVERED_STOP_REASON
    doc["n_events"] = len(STROBES)
    doc["ts_data"] = [[code, ts] for code, ts in STROBES]
    return doc


def test_recovery_rebuilds_exactly_what_finalize_would_have(tmp_path: Path) -> None:
    tsv = crash_a_run(tmp_path)
    entry = recovery.recover_file(tsv)

    assert entry["status"] == "recovered"
    assert entry["nEvents"] == len(STROBES)
    assert entry["stopReason"] == recovery.RECOVERED_STOP_REASON

    document = json.loads(Path(entry["jsonPath"]).read_text(encoding="utf-8"))
    # Field-for-field, *type*-for-type: ints back as ints, bools as bools,
    # and an animal name that happens to look numeric would stay a string.
    assert document == finalized_document()
    # The .mat lands beside it, in the sibling format folder.
    assert reader.sibling_mat(tsv).is_file()


def test_a_footer_carrying_tsv_keeps_its_recorded_stop_reason(tmp_path: Path) -> None:
    """The disk-full case (`DATA.md#crash-recovery`): `finalize` ran (footer written) but the
    best-effort `.json` write failed. The recorded reason is the truth —
    stamping it 'recovered after crash' would erase why the run ended."""
    tsv = crash_a_run(tmp_path)
    with open(tsv, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("# stop_reason: BF_END_SESSION received\n")
        fh.write("# n_events: 4\n")

    entry = recovery.recover_file(tsv)
    assert entry["status"] == "recovered"
    assert entry["stopReason"] == "BF_END_SESSION received"
    document = json.loads(Path(entry["jsonPath"]).read_text(encoding="utf-8"))
    assert document["stop_reason"] == "BF_END_SESSION received"


def test_a_torn_final_line_costs_only_itself(tmp_path: Path) -> None:
    """`DATA.md#crash-recovery` — power died mid-write. The partial line matches neither rule and
    contributes nothing; every complete line before it survives."""
    tsv = crash_a_run(tmp_path)
    with open(tsv, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("24")  # a strobe line torn mid-write, no tab, no newline

    entry = recovery.recover_file(tsv)
    assert entry["status"] == "recovered"
    assert entry["nEvents"] == len(STROBES)
    document = json.loads(Path(entry["jsonPath"]).read_text(encoding="utf-8"))
    assert document["ts_data"] == [[code, ts] for code, ts in STROBES]


def test_n_events_is_recomputed_never_copied(tmp_path: Path) -> None:
    """A footer's count describes the run `finalize` saw, which a torn file no
    longer is — the recovered document must not claim events it doesn't hold."""
    tsv = crash_a_run(tmp_path)
    with open(tsv, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("# stop_reason: operator stop\n")
        fh.write("# n_events: 999\n")

    entry = recovery.recover_file(tsv)
    document = json.loads(Path(entry["jsonPath"]).read_text(encoding="utf-8"))
    assert document["n_events"] == len(STROBES)


def test_a_stray_tsv_is_refused_not_invented(tmp_path: Path) -> None:
    stray = tmp_path / "behavior.tsv" / "notes.tsv"
    stray.parent.mkdir(parents=True)
    stray.write_text("just some notes\nnot a session\n", encoding="utf-8")

    entry = recovery.recover_file(stray)
    assert entry["status"] == "failed"
    assert entry["jsonPath"] is None
    assert not reader.sibling_json(stray).exists()


def test_the_walk_finds_only_tsvs_with_no_json_sibling(tmp_path: Path) -> None:
    """`walk_orphaned_tsvs` shares `walk_session_files`' traversal — format
    folders by name at any depth — and yields only the genuinely orphaned."""
    # A finalized run: .tsv with its .json sibling — not an orphan.
    session_a = tmp_path / "2O-Bdisc" / "2O-Bdisc_25_2026-07-22"
    files = resolve_animal_files(
        session_a, "remy1", "2O-Bdisc", "25", datetime(2026, 7, 22, 11, 0, 0)
    )
    writer = AnimalWriter(files.tsv, files.json, files.mat, dict(CORE), dict(CONFIG))
    writer.open_files()
    writer.record(101, 0)
    writer.finalize("BF_END_SESSION received")

    # A crashed run in the same folder — orphaned.
    orphan = crash_a_run(session_a, animal="remy2")

    # A legacy-layout orphan, sitting straight under the cohort root with the
    # underscored folder names — the depth and spelling the archive walk (`DATA.md#orphan-adoption`) must read.
    legacy_dir = tmp_path / "gr_01_07_22_26" / "recovery_tsv"
    legacy_dir.mkdir(parents=True)
    legacy = legacy_dir / "remy3_gr_01_07_22_26_090000.tsv"
    legacy.write_text("# rat: remy3\n101\t0\n", encoding="utf-8")

    # AppleDouble junk beside it — filtered, same as the .json walk.
    (legacy_dir / "._remy3_gr_01_07_22_26_090000.tsv").write_text(
        "\x00junk", encoding="utf-8"
    )

    found = reader.walk_orphaned_tsvs(tmp_path)
    assert found == sorted([orphan, legacy])


def test_legacy_layout_recovers_into_the_legacy_folders(tmp_path: Path) -> None:
    """Layout-preserving on purpose: a `recovery_tsv/` orphan backfills into
    `behavior_json/`/`behavior_mat/`, not a current-spelling folder minted
    beside the archive's real ones."""
    legacy_dir = tmp_path / "gr_01_07_22_26" / "recovery_tsv"
    legacy_dir.mkdir(parents=True)
    legacy = legacy_dir / "remy3_gr_01_07_22_26_090000.tsv"
    legacy.write_text("# rat: remy3\n# sketch: Shape - L\n101\t0\n249\t500\n", encoding="utf-8")

    entry = recovery.recover_file(legacy)
    assert entry["status"] == "recovered"
    assert Path(entry["jsonPath"]).parent.name == "behavior_json"
    assert (legacy.parent.parent / "behavior_mat").is_dir()
    document = json.loads(Path(entry["jsonPath"]).read_text(encoding="utf-8"))
    assert document["rat"] == "remy3"
    assert document["sketch"] == "Shape - L"  # core field: string, uncoerced


def test_recover_cohort_returns_the_wire_shape(tmp_path: Path) -> None:
    session = tmp_path / "2O-Bdisc" / "2O-Bdisc_25_2026-07-22"
    crash_a_run(session)
    stray = session / "behavior.tsv" / "notes.tsv"
    stray.write_text("not a session\n", encoding="utf-8")

    result = recovery.recover_cohort(str(tmp_path))
    assert result["scanned"] == 2
    assert result["recovered"] == 1
    assert result["failed"] == 1
    assert result["folderMissing"] is False
    assert validate_command_result("sessions.recover", {**result, "cohortId": "c1"}) == []

    # Idempotent by construction: the recovered .tsv now has a .json sibling,
    # so a second pass sees only the stray.
    again = recovery.recover_cohort(str(tmp_path))
    assert again["scanned"] == 1
    assert again["recovered"] == 0


def test_recover_cohort_says_nowhere_to_look(tmp_path: Path) -> None:
    result = recovery.recover_cohort(str(tmp_path / "unplugged-drive"))
    assert result["folderMissing"] is True
    assert result["scanned"] == 0
    assert validate_command_result("sessions.recover", {**result, "cohortId": "c1"}) == []


def test_a_recovered_orphan_is_adoptable_by_the_rescan_walk(tmp_path: Path) -> None:
    """The end-to-end handoff (`DATA.md#crash-recovery` ↔ `DATA.md#orphan-adoption`): recovery writes the
    `.json`, and the adoption walk — the same traversal — then finds it."""
    session = tmp_path / "2O-Bdisc" / "2O-Bdisc_25_2026-07-22"
    tsv = crash_a_run(session)
    assert reader.walk_session_files(tmp_path) == []

    entry = recovery.recover_file(tsv)
    assert reader.walk_session_files(tmp_path) == [Path(entry["jsonPath"])]


def test_a_recovered_file_is_still_self_describing(tmp_path: Path) -> None:
    """`DATA.md#the-embedded-task-profile` — the recovered `.json` is exactly the file somebody carries to
    another machine to find out what happened, so it has to keep the
    declaration that decodes it."""
    from ephymeris_sidecar.tasks.profile import embedded_profile

    tsv = crash_a_run(tmp_path)
    recovery.recover_file(tsv)

    document = json.loads(reader.sibling_json(tsv).read_text(encoding="utf-8"))
    profile = embedded_profile(document)
    assert profile is not None
    assert profile.live_metrics[0].id == "p_correct_1"


def test_a_snapshot_torn_by_the_crash_is_dropped_not_kept_as_text(
    tmp_path: Path,
) -> None:
    """Half a snapshot is worse than none: every reader downstream would have
    to defend against a `task_profile` that is a string. The ladder below it
    (`DATA.md#which-profile-decodes-a-run`) still scores the run, so dropping loses nothing but the shortcut."""
    tsv = crash_a_run(tmp_path)
    lines = tsv.read_text(encoding="utf-8").splitlines()
    torn = [
        line[: len(line) // 2] if line.startswith("# task_profile: ") else line
        for line in lines
    ]
    tsv.write_text("\n".join(torn) + "\n", encoding="utf-8")

    entry = recovery.recover_file(tsv)
    assert entry["status"] == "recovered"
    document = json.loads(reader.sibling_json(tsv).read_text(encoding="utf-8"))
    assert "task_profile" not in document
    # The data itself is untouched by any of this.
    assert document["n_events"] == len(STROBES)

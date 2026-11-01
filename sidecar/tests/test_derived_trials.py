"""A spine run's trial table, written into its `.json` and `.mat` as *derived*
(`DATA.md#the-derived-trial-table`, ADR 0003's *Hashes and data*).

Finalization and recovery write the replay's trial table into both structured
files, stamped with the `INTERP` it was replayed under and `REPLAY_VERSION`.
The app never reads that copy: Analytics always replays. **Re-derive**
rewrites it, and only it, after the replay changes.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import scoring
from ephymeris_sidecar.analytics.stream import spine as spine_stream
from ephymeris_sidecar.sessions import recovery
from ephymeris_sidecar.sessions.writer import AnimalWriter
from ephymeris_sidecar.tasks import profile as task_profile
from tests.fixtures import spine as fixture
from tests.test_spine_analytics import recorded_document, rig, write_document  # noqa: F401 - rig is a fixture

DERIVED = task_profile.DERIVED_KEY
#: The footer-less stop reason a recovered crash records.
CRASHED = recovery.RECOVERED_STOP_REASON


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    scoring.forget_canary()
    yield
    scoring.forget_canary()
    fixture.uninstall()


def files(tmp_path: Path, stem: str = "remy1") -> tuple[Path, Path, Path]:
    session = tmp_path / "cohort" / "P" / "P_1_2026-10-30"
    return (session / "behavior.tsv" / f"{stem}.tsv", session / "behavior.json" / f"{stem}.json",
            session / "behavior.mat" / f"{stem}.mat")


def run_through_writer(tmp_path: Path, document: dict, *, finalize: bool = True) -> tuple[Path, Path, Path]:
    """Record `document`'s strobes through a real `AnimalWriter`, as a session would."""
    tsv, json_path, mat = files(tmp_path)
    snapshot = document[task_profile.SNAPSHOT_KEY]
    declared = {f["metadataKey"] for f in snapshot["config"]}
    skip = {task_profile.SNAPSHOT_KEY, "stop_reason", "n_events", "ts_data"}
    writer = AnimalWriter(
        tsv, json_path, mat,
        core_metadata={k: v for k, v in document.items() if k not in declared | skip},
        config_metadata={k: v for k, v in document.items() if k in declared},
        profile_snapshot=snapshot,
    )
    writer.open_files()
    for code, ts in document["ts_data"]:
        writer.record(code, ts)
    if finalize:
        writer.finalize("BF_END_SESSION received")
    return tsv, json_path, mat


def table_of(document: dict) -> list[dict]:
    """What replay says the trial table is, in the file's own field names."""
    return [_snake(t.to_json()) for t in spine_stream.replayed(document).trials]


def _snake(value):  # noqa: ANN001, ANN202
    """The wire's camelCase row, spelled as the file spells it: an independent
    check that the file's columns are the trial table's, field for field."""
    if isinstance(value, dict):
        return {"".join("_" + c.lower() if c.isupper() else c for c in k): _snake(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_snake(v) for v in value]
    return value


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- finalization -------------------------------------------------------------


def test_a_finalized_spine_run_carries_its_trial_table_in_the_json(tmp_path: Path) -> None:
    document = recorded_document()
    _, json_path, _ = run_through_writer(tmp_path, document)
    written = read_json(json_path)

    block = written[DERIVED]
    assert list(written)[-1] == DERIVED, "the derived block comes after the data it is derived from"
    assert block["status"] == "ok" and block["detail"] is None
    assert block["interp"] == document["interp"]
    assert block["replay_version"] == spine_stream.REPLAY_VERSION
    assert block["phases"] == ["wait", "present", "delay", "outcome", "iti"]
    assert block["trials"] == table_of(document)
    assert len(block["trials"]) == 3
    first = block["trials"][0]
    assert (first["outcome"], first["rewarded"], first["reward_line"], first["reward_ms"]) == \
        ("correct", True, "fluid_2", 100)
    assert first["input_counts"] == [{"phase": 0, "channel": "odor_port", "count": 1}]


def load_mat(path: Path) -> dict:
    import scipy.io

    return scipy.io.loadmat(str(path))


def mat_trials(path: Path):  # noqa: ANN201
    """`S.derived.trials` as loadmat gives it: an N×1 struct array."""
    return load_mat(path)[DERIVED][0, 0]["trials"]


def mat_value(cell):  # noqa: ANN001, ANN201
    """One struct field's value as MATLAB holds it, unwrapped to Python."""
    import numpy as np

    if cell.dtype.kind in "US":
        return str(cell[0]) if cell.size else ""
    if cell.dtype == np.uint8:
        # How loadmat hands back a logical at any depth: every number here is a
        # double, so a uint8 can only be a bool written as a logical.
        return bool(cell.ravel()[0])
    if cell.dtype.names is None and cell.size == 1:
        value = float(cell.ravel()[0])
        return None if np.isnan(value) else value
    return cell


def test_a_finalized_spine_run_carries_its_trial_table_in_the_mat(tmp_path: Path) -> None:
    import numpy as np

    document = recorded_document()
    _, _, mat = run_through_writer(tmp_path, document)
    expected = table_of(document)

    block = load_mat(mat)[DERIVED][0, 0]
    assert str(block["status"][0]) == "ok"
    assert float(block["replay_version"][0, 0]) == spine_stream.REPLAY_VERSION
    assert [str(c[0]) for c in block["phases"][0]] == ["wait", "present", "delay", "outcome", "iti"]
    trials = block["trials"]
    assert trials.shape == (len(expected), 1), "one struct per trial, N×1, for struct2table"
    for i, row in enumerate(expected):
        got = trials[i, 0]
        assert mat_value(got["index"]) == row["index"]
        assert mat_value(got["at_ms"]) == row["at_ms"]
        assert mat_value(got["row"]) == row["row"]
        assert mat_value(got["outcome"]) == (row["outcome"] or ""), "a null string is ''"
        assert mat_value(got["rewarded"]) is row["rewarded"], "a bool is a logical"
        assert mat_value(got["reward_ms"]) == row["reward_ms"], "a null number is NaN, never []"
        assert mat_value(got["latency_ms"]) is None and got["latency_ms"].shape == (1, 1)
        entries = got["phase_entries"]
        assert entries.shape == (1, len(row["phase_entries"]))
        assert [None if np.isnan(v) else v for v in entries[0]] == row["phase_entries"]
        counts = got["input_counts"]
        assert counts.shape == (len(row["input_counts"]), 1)
        assert [(mat_value(c["phase"]), mat_value(c["channel"]), mat_value(c["count"]))
                for c in counts[:, 0]] == [(c["phase"], c["channel"], c["count"]) for c in row["input_counts"]]


def test_a_crashed_spine_run_recovers_with_its_trial_table_through_its_last_strobe(tmp_path: Path) -> None:
    document = recorded_document()
    cut = {**document, "ts_data": document["ts_data"][:-6]}
    tsv, json_path, mat = run_through_writer(tmp_path, cut, finalize=False)

    entry = recovery.recover_file(tsv)
    assert entry["status"] == "recovered" and entry["stopReason"] == CRASHED
    block = read_json(json_path)[DERIVED]
    assert block["status"] == "ok"
    assert block["trials"] == table_of(recovery.recovered_document(recovery.parse_tsv(tsv)))
    assert block["trials"][-1]["complete"] is False, "the trial the crash cut off"
    trials = mat_trials(mat)
    assert trials.shape == (len(block["trials"]), 1)
    assert [(mat_value(t["index"]), mat_value(t["outcome"]), mat_value(t["complete"])) for t in trials[:, 0]] \
        == [(r["index"], r["outcome"] or "", r["complete"]) for r in block["trials"]]


def test_a_legacy_run_gets_no_derived_table(tmp_path: Path) -> None:
    from tests.test_writer import make_writer

    writer = make_writer(tmp_path)
    writer.open_files()
    writer.record(101, 0)
    document = writer.finalize("BF_END_SESSION received")
    assert DERIVED not in document
    assert DERIVED not in read_json(tmp_path / "behavior.json" / "remy1.json")
    assert DERIVED not in load_mat(tmp_path / "behavior.mat" / "remy1.mat")

    (tmp_path / "behavior.json" / "remy1.json").unlink()
    recovery.recover_file(tmp_path / "behavior.tsv" / "remy1.tsv")
    assert DERIVED not in read_json(tmp_path / "behavior.json" / "remy1.json")


def diverged_document() -> dict:
    document = recorded_document()
    fluid_on = next(int(c) for c, n in document[task_profile.SNAPSHOT_KEY]["strobes"].items()
                    if n == "FLUID_2_ON")
    k = next(i for i, (c, _) in enumerate(document["ts_data"]) if c == fluid_on)
    document["ts_data"][k][1] += 1
    return document


def test_a_diverged_run_is_marked_and_carries_no_trials(tmp_path: Path) -> None:
    _, json_path, mat = run_through_writer(tmp_path, diverged_document())

    block = read_json(json_path)[DERIVED]
    assert block["status"] == "diverged" and "diverged at strobe" in block["detail"]
    assert block["trials"] == []
    trials = mat_trials(mat)
    assert trials.shape == (0, 1) and "outcome" in trials.dtype.names, \
        "an empty struct array that keeps its fields, so struct2table gives 0 rows"


def test_an_unreplayable_run_is_marked(tmp_path: Path) -> None:
    from ephymeris_sidecar.analytics.stream import replay

    document = recorded_document()
    document["interp"] = max(replay.INTERP_VERSIONS) + 1
    _, json_path, _ = run_through_writer(tmp_path, document)
    block = read_json(json_path)[DERIVED]
    assert block["status"] == "unreplayable" and "INTERP" in block["detail"]
    assert block["interp"] == document["interp"] and block["trials"] == []


def test_a_derivation_that_fails_never_costs_the_json(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    def broken(_document):  # noqa: ANN001, ANN202
        raise RuntimeError("a bug in replay")

    monkeypatch.setattr(spine_stream, "replayed", broken)
    _, json_path, mat = run_through_writer(tmp_path, recorded_document())
    written = read_json(json_path)
    assert DERIVED not in written and written["ts_data"], "the run's file, without a table"
    assert mat.is_file()


def test_the_footer_is_durable_before_the_replay_starts(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """A kill while the trial table is derived must not cost the run its stop
    reason: the `.tsv` footer is written and fsync'd first."""

    class Killed(BaseException):
        """The process dying mid-derive: nothing below `finalize` catches it."""

    def killed(_document):  # noqa: ANN001, ANN202
        raise Killed

    monkeypatch.setattr(spine_stream, "replayed", killed)
    with pytest.raises(Killed):
        run_through_writer(tmp_path, recorded_document())
    tsv, json_path, _ = files(tmp_path)
    assert not json_path.exists()

    monkeypatch.undo()
    fixture.install()
    entry = recovery.recover_file(tsv)
    assert entry["stopReason"] == "BF_END_SESSION received", "the footer's reason, not a crash"
    assert read_json(json_path)[DERIVED]["status"] == "ok"


# --- Analytics never reads it -------------------------------------------------


def wrong_block(block: dict) -> dict:
    """A derived block that disagrees with the run on every count."""
    trials = [{**t, "outcome": "false_alarm", "rewarded": not t["rewarded"], "row": "nonsense"}
              for t in block["trials"]]
    return {**block, "trials": trials + trials, "phases": ["x"]}


async def test_analytics_replays_and_never_reads_the_stored_table(rig) -> None:  # noqa: ANN001, F811
    document = recorded_document()
    honest = write_document(rig, document)
    before = (await rig.service.summary(rig.cohort.id))["runs"][0]
    [series_before] = (await rig.service.series([honest]))["series"]

    path = Path(rig.sessions.runs_for(before["sessionId"])[0].file_path)
    tampered = {**document, DERIVED: wrong_block(spine_stream_block(document))}
    path.write_text(json.dumps(tampered), encoding="utf-8")
    after = (await rig.service.summary(rig.cohort.id))["runs"][0]
    [series_after] = (await rig.service.series([honest]))["series"]

    for key in ("status", "metrics", "overall", "replay", "divergence"):
        assert after[key] == before[key], key
    assert series_after["trialTable"] == series_before["trialTable"]


def spine_stream_block(document: dict) -> dict:
    from ephymeris_sidecar.sessions import derived

    return derived.derive(document)


def test_no_analytics_module_but_the_reader_names_the_derived_key() -> None:
    """The reader drops it; nothing else in Analytics may look for it."""
    import ephymeris_sidecar.analytics as analytics

    root = Path(analytics.__file__).parent
    for source in root.rglob("*.py"):
        if source.name == "reader.py":
            continue
        text = source.read_text(encoding="utf-8")
        assert "DERIVED_KEY" not in text and not re.search(r"""["']derived["']""", text), source


# --- Re-derive ----------------------------------------------------------------


async def test_rederive_rewrites_only_the_derived_table(rig) -> None:  # noqa: ANN001, F811
    tsv, json_path, mat = run_through_writer(rig.root, recorded_document())
    finalized = json_path.read_text(encoding="utf-8")
    tsv_bytes = tsv.read_bytes()
    mat_before = load_mat(mat)

    stale = read_json(json_path)
    stale[DERIVED] = {**wrong_block(stale[DERIVED]), "replay_version": 0}
    json_path.write_text(json.dumps(stale, indent=2), encoding="utf-8")

    result = await rig.archive.rederive(rig.cohort.id)
    assert (result["scanned"], result["rewritten"], result["current"], result["failed"]) == (1, 1, 0, 0)
    assert result["entries"] == [{"jsonPath": str(json_path), "status": "rewritten", "reason": None,
                                  "matError": None}]
    assert result["skipped"] == 0 and "written" not in result, "the backup list stays off the wire"
    assert result["cohortId"] == rig.cohort.id

    assert json_path.read_text(encoding="utf-8") == finalized, \
        "every other key byte for byte, and the table as finalization derived it"
    assert tsv.read_bytes() == tsv_bytes, "the write-ahead log is never touched"
    mat_after = load_mat(mat)
    for name in set(mat_before) - {DERIVED, "__header__"}:
        assert repr(mat_after[name]) == repr(mat_before[name]), name
    assert rig.changes[-1].files_to_back_up == (str(json_path), str(mat)), "queued for backup"


async def test_rederive_leaves_a_current_run_untouched(rig) -> None:  # noqa: ANN001, F811
    _, json_path, mat = run_through_writer(rig.root, recorded_document())
    stamps = (json_path.stat().st_mtime_ns, mat.stat().st_mtime_ns)
    result = await rig.archive.rederive(rig.cohort.id)
    assert (result["scanned"], result["rewritten"], result["current"]) == (1, 0, 1)
    assert result["entries"] == []
    assert (json_path.stat().st_mtime_ns, mat.stat().st_mtime_ns) == stamps
    assert not rig.changes, "nothing written, nothing queued"


async def test_rederive_fills_in_a_spine_run_with_no_table_and_skips_a_legacy_run(rig) -> None:  # noqa: ANN001, F811
    from tests.test_spine_analytics import tracer_stream

    _, json_path, _ = run_through_writer(rig.root, recorded_document())
    bare = read_json(json_path)
    del bare[DERIVED]
    json_path.write_text(json.dumps(bare, indent=2), encoding="utf-8")
    session = rig.add_session("1", "2026-10-30")
    rig.add_run(session, "a2", tracer_stream(), snapshot=False)
    legacy = Path(rig.sessions.runs_for(session)[0].file_path)
    legacy_bytes = legacy.read_bytes()

    result = await rig.archive.rederive(rig.cohort.id)
    assert (result["scanned"], result["rewritten"]) == (1, 1), "the legacy run is not a spine run"
    assert read_json(json_path)[DERIVED]["trials"] == table_of(bare)
    assert legacy.read_bytes() == legacy_bytes


def stale_on_disk(json_path: Path, **block_edits) -> dict:  # noqa: ANN003
    """Rewrite a run's `.json` with its derived block edited, as an older (or
    newer) build would have left it."""
    stale = read_json(json_path)
    stale[DERIVED] = {**stale[DERIVED], **block_edits}
    json_path.write_text(json.dumps(stale, indent=2), encoding="utf-8")
    return stale


async def test_rederive_refreshes_the_json_when_the_mat_cannot_be_written(rig, monkeypatch) -> None:  # noqa: ANN001, F811
    """A `.mat` that cannot be written never holds the `.json` back, is
    reported on its own, and is written by the next Re-derive that can."""
    from ephymeris_sidecar.sessions import matwriter

    _, json_path, mat = run_through_writer(rig.root, recorded_document())
    matwriter.savemat(str(mat), stale_on_disk(json_path, replay_version=0))
    real = matwriter.savemat

    def full_disk(*_args):  # noqa: ANN002, ANN202
        raise OSError("disk full")

    monkeypatch.setattr(matwriter, "savemat", full_disk)
    result = await rig.archive.rederive(rig.cohort.id)
    [entry] = result["entries"]
    assert (result["rewritten"], result["failed"], entry["status"]) == (1, 0, "rewritten")
    assert "disk full" in entry["matError"]
    assert read_json(json_path)[DERIVED]["replay_version"] == spine_stream.REPLAY_VERSION
    assert rig.changes[-1].files_to_back_up == (str(json_path),), "only what changed is queued"

    monkeypatch.setattr(matwriter, "savemat", real)
    again = await rig.archive.rederive(rig.cohort.id)
    assert again["rewritten"] == 1 and again["entries"][0]["matError"] is None, \
        "the .json is current, but its .mat still holds the old table, so the .mat is written"
    assert rig.changes[-1].files_to_back_up == (str(mat),)
    assert float(load_mat(mat)[DERIVED][0, 0]["replay_version"][0, 0]) == spine_stream.REPLAY_VERSION
    assert (await rig.archive.rederive(rig.cohort.id))["current"] == 1


async def test_a_json_rederive_could_not_write_changes_nothing(rig, monkeypatch) -> None:  # noqa: ANN001, F811
    from ephymeris_sidecar.sessions import matwriter, writer

    _, json_path, mat = run_through_writer(rig.root, recorded_document())
    stale = stale_on_disk(json_path, replay_version=0)
    matwriter.savemat(str(mat), stale)  # the .mat as stale as the .json
    mat_bytes = mat.read_bytes()
    real = writer.write_atomic

    def refuse_json(path, data):  # noqa: ANN001, ANN202
        if Path(path).suffix == ".json":
            raise OSError("permission denied")
        real(path, data)

    monkeypatch.setattr(writer, "write_atomic", refuse_json)
    result = await rig.archive.rederive(rig.cohort.id)
    assert result["failed"] == 1 and "permission denied" in result["entries"][0]["reason"]
    assert read_json(json_path) == stale and mat.read_bytes() == mat_bytes, "both as they were"
    assert not rig.changes


async def test_rederive_never_overwrites_a_table_from_a_newer_replay(rig) -> None:  # noqa: ANN001, F811
    """Two machines on different builds can share one archive."""
    _, json_path, _ = run_through_writer(rig.root, recorded_document())
    newer = stale_on_disk(json_path, replay_version=spine_stream.REPLAY_VERSION + 1, trials=[])
    result = await rig.archive.rederive(rig.cohort.id)
    assert (result["skipped"], result["rewritten"]) == (1, 0)
    [entry] = result["entries"]
    assert entry["status"] == "skipped" and "newer" in entry["reason"]
    assert read_json(json_path) == newer and not rig.changes


async def test_rederive_never_replaces_a_replayed_table_with_unreplayable(rig, monkeypatch) -> None:  # noqa: ANN001, F811
    """A build that does not know a run's INTERP has nothing to say about its table."""
    from ephymeris_sidecar.analytics.stream import replay

    _, json_path, _ = run_through_writer(rig.root, recorded_document())
    before = json_path.read_bytes()
    monkeypatch.setattr(replay, "INTERP_VERSIONS", frozenset({99}))
    result = await rig.archive.rederive(rig.cohort.id)
    assert (result["skipped"], result["rewritten"]) == (1, 0)
    assert "INTERP" in result["entries"][0]["reason"]
    assert json_path.read_bytes() == before and not rig.changes


EMOJI = "\U0001F42D"


def test_a_name_outside_the_bmp_is_escaped_never_costing_the_mat(tmp_path: Path) -> None:
    """A row, channel or phase name with an emoji: escaped as JSON escapes it,
    as the embedded profile always was, so the `.mat` is still written."""
    import scipy.io

    from ephymeris_sidecar.sessions import derived, matwriter

    block = derived.derive(recorded_document())
    block["phases"][1] = f"present {EMOJI}"
    block["trials"][0]["row_name"] = f"Odor 1 {EMOJI}"
    block["trials"][0]["input_counts"][0]["channel"] = f"port {EMOJI}"
    path = tmp_path / "run.mat"
    matwriter.savemat(str(path), {"rat": "remy1", DERIVED: block})

    got = scipy.io.loadmat(str(path))[DERIVED][0, 0]
    escaped = json.dumps(EMOJI)[1:-1]  # 🐭
    assert str(got["phases"][0][1][0]) == f"present {escaped}"
    first = got["trials"][0, 0]
    assert mat_value(first["row_name"]) == f"Odor 1 {escaped}"
    assert mat_value(first["input_counts"][0, 0]["channel"]) == f"port {escaped}"
    assert json.loads(f'"{mat_value(first["row_name"])}"') == f"Odor 1 {EMOJI}", "jsondecode gives it back"


async def test_an_animal_name_outside_the_bmp_never_holds_the_json_back(rig) -> None:  # noqa: ANN001, F811
    """A top-level string the `.mat` still refuses (`DATA.md#the-mat-mirror`):
    Re-derive refreshes the `.json` and reports the `.mat` apart."""
    _, json_path, mat = run_through_writer(rig.root, {**recorded_document(), "rat": f"remy{EMOJI}"})
    assert DERIVED in read_json(json_path) and not mat.exists()
    stale_on_disk(json_path, replay_version=0)
    [entry] = (await rig.archive.rederive(rig.cohort.id))["entries"]
    assert entry["status"] == "rewritten" and "can't be written to a .mat" in entry["matError"]
    assert read_json(json_path)[DERIVED]["replay_version"] == spine_stream.REPLAY_VERSION
    assert rig.changes[-1].files_to_back_up == (str(json_path),)

    # From then on the .json is current and its .mat can never be written, as
    # on any build: not this run's failure, so not `failed`, every time.
    again = await rig.archive.rederive(rig.cohort.id)
    assert (again["failed"], again["skipped"]) == (0, 1)
    assert again["entries"][0]["reason"] == "the animal name can't be written to a .mat"


async def test_a_stale_mat_with_a_newer_mtime_is_rewritten(rig) -> None:  # noqa: ANN001, F811
    """The `.mat` is judged by its content, as the `.json` is: a copy made
    without keeping mtimes can leave an old table with a new mtime."""
    import os

    from ephymeris_sidecar.sessions import matwriter

    _, json_path, mat = run_through_writer(rig.root, recorded_document())
    old = {**read_json(json_path)}
    old[DERIVED] = {**old[DERIVED], "replay_version": 0}
    matwriter.savemat(str(mat), old)
    later = json_path.stat().st_mtime_ns + 10**9
    os.utime(mat, ns=(later, later))

    result = await rig.archive.rederive(rig.cohort.id)
    [entry] = result["entries"]
    assert (result["rewritten"], entry["matError"]) == (1, None)
    assert rig.changes[-1].files_to_back_up == (str(mat),), "the .json was current"
    assert float(load_mat(mat)[DERIVED][0, 0]["replay_version"][0, 0]) == spine_stream.REPLAY_VERSION
    assert (await rig.archive.rederive(rig.cohort.id))["current"] == 1


async def test_a_mat_from_a_newer_replay_is_left_alone(rig) -> None:  # noqa: ANN001, F811
    from ephymeris_sidecar.sessions import matwriter

    _, json_path, mat = run_through_writer(rig.root, recorded_document())
    newer = {**read_json(json_path)}
    newer[DERIVED] = {**newer[DERIVED], "replay_version": spine_stream.REPLAY_VERSION + 1}
    matwriter.savemat(str(mat), newer)
    before = mat.read_bytes()

    result = await rig.archive.rederive(rig.cohort.id)
    assert result["skipped"] == 1 and "newer" in result["entries"][0]["reason"]
    assert mat.read_bytes() == before and not rig.changes


async def test_rederive_is_refused_while_a_box_is_writing(rig) -> None:  # noqa: ANN001, F811
    from ephymeris_sidecar.analytics.archive import RigInUse

    rig.lifecycle.writing = True
    with pytest.raises(RigInUse):
        await rig.archive.rederive(rig.cohort.id)


# --- one generic serializer ---------------------------------------------------

MATLAB_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def test_every_trial_column_has_a_mat_class_and_a_matlab_name() -> None:
    """A column whose type the serializer has no class for would be written as
    JSON text: legal, but not what a MATLAB user can compute with."""
    from ephymeris_sidecar.analytics.stream import trial_table
    from ephymeris_sidecar.sessions import derived

    def walk(fields, path=""):  # noqa: ANN001, ANN202
        for name, kind in fields:
            assert MATLAB_NAME.match(name), f"{path}{name} is not a MATLAB identifier"
            assert kind.name != "json", f"{path}{name} has no .mat class: give `derived._kind` one"
            walk(kind.fields, f"{path}{name}.")

    walk(derived.fields_of(trial_table.ReplayTrial))
    block = derived.derive(recorded_document())
    assert all(MATLAB_NAME.match(k) for k in block)


def test_a_column_added_to_the_trial_row_is_written_with_no_change_here(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """#107 may add columns to `ReplayTrial`; each is written as it is, by name."""
    from ephymeris_sidecar.analytics.stream import trial_table

    @dataclasses.dataclass(frozen=True)
    class Wider(trial_table.ReplayTrial):
        lick_rate: float | None = None
        tags: tuple[int | None, ...] = ()

    real = spine_stream.replayed

    def widened(document):  # noqa: ANN001, ANN202
        result = real(document)
        # `trial_table.name` builds the patched class, so each row is a Wider.
        trials = tuple(dataclasses.replace(t, lick_rate=2.5 if t.index == 0 else None, tags=(t.index, None))
                       for t in result.trials)
        return dataclasses.replace(result, trials=trials)

    monkeypatch.setattr(trial_table, "ReplayTrial", Wider)
    monkeypatch.setattr(spine_stream, "replayed", widened)
    _, json_path, mat = run_through_writer(tmp_path, recorded_document())

    rows = read_json(json_path)[DERIVED]["trials"]
    assert [(r["lick_rate"], r["tags"]) for r in rows[:2]] == [(2.5, [0, None]), (None, [1, None])]
    trials = mat_trials(mat)
    assert mat_value(trials[0, 0]["lick_rate"]) == 2.5 and mat_value(trials[1, 0]["lick_rate"]) is None
    assert trials[1, 0]["tags"].shape == (1, 2)


# --- the replay version -------------------------------------------------------

#: A fingerprint of the derived blocks of fixed runs. **When this fails, a run's
#: trial table has changed: bump `spine.REPLAY_VERSION`, then update this pin**,
#: so a file's stamp says which replay wrote its table (`DATA.md#the-derived-trial-table`).
REPLAY_PIN = "7b3a05fea3f50923"


def test_the_replay_version_pins_the_trial_table() -> None:
    from ephymeris_sidecar.analytics.stream import trial_table
    from ephymeris_sidecar.sessions import derived

    document = recorded_document()
    crashed = {**document, "ts_data": document["ts_data"][:-6]}
    blocks = [derived.derive(d) for d in (document, crashed, diverged_document())]
    columns = [(name, kind.name) for name, kind in derived.fields_of(trial_table.ReplayTrial)]
    canon = json.dumps({"blocks": blocks, "columns": columns}, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16] == REPLAY_PIN


def test_the_legacy_adapters_columns_are_written_to_both_files(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """#107's columns: `scores` as a struct array of {condition, correct}, and a
    nullable `correct` as 1, 0 or NaN, never a null read back as false."""
    from ephymeris_sidecar.analytics.stream import trial_table

    real = spine_stream.replayed

    def scored(document):  # noqa: ANN001, ANN202
        result = real(document)
        trials = tuple(dataclasses.replace(
            t, correct=None if t.index == 1 else t.correct,
            scores=(trial_table.ConditionScore("r1", True), trial_table.ConditionScore("l1", None))
            if t.index == 0 else ()) for t in result.trials)
        return dataclasses.replace(result, trials=trials)

    monkeypatch.setattr(spine_stream, "replayed", scored)
    _, json_path, mat = run_through_writer(tmp_path, recorded_document())

    rows = read_json(json_path)[DERIVED]["trials"]
    assert rows[0]["scores"] == [{"condition": "r1", "correct": True}, {"condition": "l1", "correct": None}]
    assert rows[1]["correct"] is None and rows[1]["scores"] == []
    assert {"outcome_ms", "presented"} <= set(rows[0])
    trials = mat_trials(mat)
    first = trials[0, 0]["scores"]
    assert first.shape == (2, 1)
    assert mat_value(first[0, 0]["condition"]) == "r1" and mat_value(first[0, 0]["correct"]) == 1.0
    assert mat_value(first[1, 0]["correct"]) is None, "an exclusion stays NaN, not false"
    assert mat_value(trials[1, 0]["correct"]) is None
    assert trials[1, 0]["scores"].shape == (0, 1)

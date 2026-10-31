"""A saved spine task runs a session end to end, with no box — issue #98.

No hardware is needed to prove the path, only to measure it. The saved task's
GENERATED folder is compiled for the host against the instrumented shim
(`extras/host_test/box_shim/`), so the board here is the real `BoxSpine.h`
running the real generated table on a simulated animal. Its serial transcript
is then played into the real session path (`PortManager`, the handshake,
`SessionRunner`, `AnimalWriter`), and the `.tsv` that path wrote is replayed
from nothing but itself: every strobe the board sent must be predicted.

What still needs a real box: an AVR build flashed and run, and the free RAM a
Mega reports with the table loaded (the host shim reports a fixed number).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics.stream import spine as spine_stream
from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.sessions import recovery
from ephymeris_sidecar.sessions import runner as runner_module
from ephymeris_sidecar.sessions.runner import BoxConfig, SessionRunner
from ephymeris_sidecar.taskdef.model import TaskDefinition
from ephymeris_sidecar.taskdef.store import TaskStore
from ephymeris_sidecar.tasks import profile as task_profile
from ephymeris_sidecar.tasks.start_command import build_start_command
from tests.fixtures import spine as fixture
from tests.scripted_board import Bench, ScriptedBoard, until

REPO = Path(__file__).resolve().parents[2]
FIRMWARE = REPO / "firmware"
HOST_TEST = FIRMWARE / "libraries" / "BehaviorBox" / "extras" / "host_test"
SEED = 1234567
FREE_RAM = 4321
#: The run's per-box overrides: three trials, and a reward drawn 60% of the
#: time so the session RNG is exercised and must replay.
OVERRIDES = {"block_trials": 3, "reward_permille": 600}

compiler = shutil.which("clang++") or shutil.which("g++")
pytestmark = [
    pytest.mark.skipif(compiler is None, reason="no host C++ compiler"),
    pytest.mark.skipif(os.name == "nt", reason="the AVR build is C++11 and clang on Windows needs "
                       "MSVC's C++14 library, as test_box_utility.py's compile; runs on Linux and macOS"),
]


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


def save_tracer(tmp_path: Path) -> Path:
    store = TaskStore(tmp_path / "data", library_root=FIRMWARE)
    definition = TaskDefinition.from_json(fixture.tracer())
    assert store.save(definition) == []
    return store.sketch_dir(definition)


def animal(pin: int) -> list[tuple[int, int, int]]:
    """(ms, pin, level) for a rat on the port beam (active LOW: LOW is a poke)."""
    poke, clear = 0, 1
    return [
        (200, pin, poke), (1500, pin, clear),    # trial 1: holds through the present
        (2000, pin, poke), (2100, pin, clear),   # a poke in the ITI: unwatched, never strobed
        (5000, pin, poke), (5300, pin, clear),   # trial 2: lets go during the present, an abort
        (8500, pin, poke), (9800, pin, clear),   # trial 3: holds through
        (14500, pin, poke),                      # after the session: nothing
    ]


def run_board(folder: Path, host_lines: list[str], events, ticks: int, tmp_path: Path) -> list[str]:
    """Compile the generated folder for the host and run it: its serial transcript."""
    ino = folder / f"{folder.name}.ino"
    port = registry.channels().get("odor_port").index
    feed = "\n".join(f"  bb_feed({json.dumps(line)});" for line in host_lines)
    moves = ", ".join(f"{{{t}UL, {p}, {v}}}" for t, p, v in events)
    source = tmp_path / "board.cpp"
    source.write_text(
        "#include <Arduino.h>\n"
        f'#include "{ino}"\n'
        "struct Move { unsigned long t; int pin; int level; };\n"
        f"static const Move kMoves[] = {{ {moves} }};\n"
        "int main() {\n"
        f"  bb_pinValue[{port}] = HIGH;\n"
        f"{feed}\n"
        "  setup();\n"
        "  unsigned long t0 = millis();\n"
        "  size_t k = 0, n = sizeof(kMoves) / sizeof(kMoves[0]);\n"
        f"  for (unsigned long t = 1; t <= {ticks}UL; ++t) {{\n"
        "    while (k < n && kMoves[k].t == t) { bb_pinValue[kMoves[k].pin] = kMoves[k].level; k++; }\n"
        "    bb_ms = t0 + t;\n"
        "    loop();\n"
        "  }\n"
        "  fputs(bb_output().c_str(), stdout);\n"
        "}\n",
        encoding="utf-8",
    )
    binary = tmp_path / "board"
    built = subprocess.run(
        [compiler, "-std=c++11", "-Wall", "-Werror", "-Wno-unused-function",
         f"-DBOX_HOST_FREE_RAM={FREE_RAM}",
         f"-I{HOST_TEST / 'box_shim'}", f"-I{FIRMWARE / 'libraries' / 'BehaviorBox'}",
         "-x", "c++", str(source), "-o", str(binary)],
        capture_output=True, text=True,
    )
    assert built.returncode == 0, f"{compiler} failed:\n{built.stdout}{built.stderr}"
    ran = subprocess.run([str(binary)], capture_output=True, text=True, check=True)
    return ran.stdout.splitlines()


async def run_session(tmp_path: Path, folder: Path, transcript: list[str], monkeypatch) -> Path:
    """Play the board's transcript into the real session path; the `.tsv` it wrote."""
    profile = task_profile.load_profile(folder)
    config = {f.metadata_key: OVERRIDES.get(f.metadata_key, f.default) for f in profile.config}
    command = build_start_command(profile, config)
    ready = transcript.index("READY")
    replies = [line for line in transcript if line.startswith(("PARAMS", "CLAMPED"))]
    strobes = [line for line in transcript if handler_module.STROBE_RE.match(line)]

    # The board answers each SET line as the compiled board did, in order.
    groups, current = [], []
    for line in replies:
        current.append(line)
        if line.startswith("PARAMS"):
            groups.append(current)
            current = []
    answers = iter(groups)
    monkeypatch.setattr(ScriptedBoard, "answer", staticmethod(lambda _tokens: next(answers)))
    monkeypatch.setattr(runner_module, "new_trial_seed", lambda: SEED)
    monkeypatch.setattr(handler_module, "SESSION_SEED_WINDOW_S", 0.05)

    bench = await Bench(asyncio.get_running_loop(), (1,)).plug_in()
    try:
        async def nothing(*_args):  # noqa: ANN002
            return None

        runner = SessionRunner(loop=asyncio.get_running_loop(), ports=bench.ports,
                               broadcast=nothing, on_animal_ended=nothing)
        runner.configure(
            tmp_path / "session", "SPN-tracer_1", "g1",
            [BoxConfig(box=1, animal_id="a1", animal_name="remy1", sketch_path=str(folder),
                       sketch_name=folder.name, start_command=command, config_metadata=config,
                       profile=profile)],
            duration_s=None, session_id="s1",
        )
        runner.start_box(1)
        board = await bench.wait_for_board(1)
        board.seed_on_start = SEED
        await board.said(*transcript[: ready + 1])
        await until(lambda: any(line.startswith("START") for line in board.sent()))
        await board.said()
        # What the host sent is exactly what the compiled board was fed.
        assert board.sent() == [command.begin_line, *command.set_lines, command.start_line(SEED)]
        await board.said(*strobes)
        await until(lambda: not runner.running_boxes(), timeout=10)
        await until(lambda: any(p.is_file() for p in (tmp_path / "session").rglob("*.json")), timeout=10)
    finally:
        bench.shutdown()
    return tsv_of(tmp_path)


def tsv_of(tmp_path: Path) -> Path:
    return next(p for p in (tmp_path / "session").rglob("*.tsv") if p.is_file())


def json_of(tsv: Path) -> Path:
    """The run's `.json`: the same name, in the session's `behavior.json/` folder."""
    return tsv.parent.parent / "behavior.json" / f"{tsv.stem}.json"


def host_lines(folder: Path) -> list[str]:
    profile = task_profile.load_profile(folder)
    config = {f.metadata_key: OVERRIDES.get(f.metadata_key, f.default) for f in profile.config}
    command = build_start_command(profile, config)
    return [command.begin_line, *command.set_lines, command.start_line(SEED)]


async def test_a_saved_spine_task_runs_a_session_and_its_tsv_alone_replays(tmp_path, monkeypatch):
    folder = save_tracer(tmp_path)
    port = registry.channels().get("odor_port").index
    transcript = run_board(folder, host_lines(folder), animal(port), 16000, tmp_path)
    assert transcript[:3] == ["INTERP=2", f"FREE_RAM={FREE_RAM}", "READY"]
    assert not any(line.startswith("CLAMPED") for line in transcript)

    tsv = await run_session(tmp_path, folder, transcript, monkeypatch)
    text = tsv.read_text(encoding="utf-8")
    header = text[: text.index("\n", text.index("# task_profile:"))]
    # Everything replay needs is in the header, before the first strobe.
    assert "# interp: 2\n" in header and f"# free_ram: {FREE_RAM}\n" in header
    assert f"# trial_seed: {SEED}\n" in header and "# block_trials: 3\n" in header
    assert '"spine":' in header

    document = json.loads(json_of(tsv).read_text(encoding="utf-8"))
    vocab = registry.vocabulary()
    names = {document["task_profile"]["strobes"][str(c)] for c, _ in document["ts_data"]}
    edge_names = set(registry.channel_set().edge_codes())
    assert names <= edge_names | {"START_SESSION", "TRIAL_START", "END_SESSION"}, \
        "the stream holds only channel edge codes and structural codes"
    assert names >= {"ODOR_PORT_ENTER", "TRIAL_LIGHT_ON", "ODOR_LINE_1_ON", "END_SESSION"}
    assert [n for c, _ in document["ts_data"] for n in [vocab.name_of(c)]].count("TRIAL_START") == 3
    assert document["stop_reason"] == runner_module.CLEAN_STOP_REASON

    record = spine_stream.decode(document)
    assert spine_stream.expected_stream(record) == [tuple(s) for s in document["ts_data"]], \
        "replay predicts every strobe the board sent, at its tick"


async def test_a_crashed_runs_tsv_alone_replays_as_far_as_it_goes(tmp_path, monkeypatch):
    folder = save_tracer(tmp_path)
    port = registry.channels().get("odor_port").index
    transcript = run_board(folder, host_lines(folder), animal(port), 16000, tmp_path)
    tsv = await run_session(tmp_path, folder, transcript, monkeypatch)

    # The power fails mid-session: the footer and the last strobes never land,
    # and there is no .json.
    lines = tsv.read_text(encoding="utf-8").splitlines(keepends=True)
    body = [i for i, line in enumerate(lines) if not line.startswith("#")]
    cut = lines[: body[len(body) // 2]]
    json_of(tsv).unlink()
    tsv.write_text("".join(cut), encoding="utf-8")

    assert recovery.recover_file(tsv)["status"] == "recovered"
    document = json.loads(json_of(tsv).read_text(encoding="utf-8"))
    record = spine_stream.decode(document)
    assert record.end_tick is None
    assert spine_stream.expected_stream(record) == [tuple(s) for s in document["ts_data"]]


async def test_a_run_cut_inside_one_ticks_burst_replays_what_it_holds(tmp_path, monkeypatch):
    """The power can fail between two strobes of the same tick: the port's enter
    code written, the odor's on code not. What the file holds still replays;
    what it never got to hold is not demanded of it."""
    folder = save_tracer(tmp_path)
    port = registry.channels().get("odor_port").index
    transcript = run_board(folder, host_lines(folder), animal(port), 16000, tmp_path)
    tsv = await run_session(tmp_path, folder, transcript, monkeypatch)

    lines = tsv.read_text(encoding="utf-8").splitlines(keepends=True)
    body = [i for i, line in enumerate(lines) if not line.startswith("#")]
    ticks = [lines[i].split("\t")[1] for i in body]
    # The first strobe that shares its tick with the one after it, past trial 1.
    cut = next(body[k] for k in range(3, len(body) - 1) if ticks[k] == ticks[k + 1])
    json_of(tsv).unlink()
    tsv.write_text("".join(lines[: cut + 1]), encoding="utf-8")

    assert recovery.recover_file(tsv)["status"] == "recovered"
    document = json.loads(json_of(tsv).read_text(encoding="utf-8"))
    assert spine_stream.expected_stream(spine_stream.decode(document)) == [
        tuple(s) for s in document["ts_data"]
    ]


async def test_a_cut_at_any_byte_replays_what_it_holds_or_is_refused_by_name(tmp_path, monkeypatch):
    """A power cut can land on any byte. Whatever it tears, the torn line costs
    only itself: every cut recovers to exactly what its complete lines say, and
    then replays to exactly its strobes, or is refused as `SpineDecodeError`
    (a cut before the snapshot, the seed or a parameter is complete), never
    with a bare error and never with a prediction the file contradicts."""
    folder = save_tracer(tmp_path)
    port = registry.channels().get("odor_port").index
    transcript = run_board(folder, host_lines(folder), animal(port), 16000, tmp_path)
    data = (await run_session(tmp_path, folder, transcript, monkeypatch)).read_bytes()

    cut, whole = tmp_path / "cut.tsv", tmp_path / "whole.tsv"
    replayed = refused = 0
    for k in range(1, len(data) + 1):
        cut.write_bytes(data[:k])
        whole.write_bytes(data[: data.rfind(b"\n", 0, k) + 1])
        document = recovery.recovered_document(recovery.parse_tsv(cut))
        assert document == recovery.recovered_document(recovery.parse_tsv(whole)), k
        try:
            record = spine_stream.decode(document)
            predicted = spine_stream.expected_stream(record)
        except spine_stream.SpineDecodeError:
            refused += 1
            continue
        assert predicted == [tuple(s) for s in document["ts_data"]], k
        replayed += 1
    assert replayed > 100, "every cut after the header replays"
    assert refused > 0


async def test_an_edited_output_strobe_is_not_what_replay_predicts(tmp_path, monkeypatch):
    folder = save_tracer(tmp_path)
    port = registry.channels().get("odor_port").index
    transcript = run_board(folder, host_lines(folder), animal(port), 16000, tmp_path)
    tsv = await run_session(tmp_path, folder, transcript, monkeypatch)
    document = json.loads(json_of(tsv).read_text(encoding="utf-8"))
    fluid_on = registry.vocabulary().code_of("FLUID_2_ON")
    edited = [[c, t + 1 if c == fluid_on else t] for c, t in document["ts_data"]]
    assert any(c == fluid_on for c, _ in edited), "the run paid at least once"
    record = spine_stream.decode(dict(document, ts_data=edited))
    assert spine_stream.expected_stream(record) != [tuple(s) for s in edited]


def test_an_unknown_table_format_is_refused_rather_than_replayed():
    document = {"interp": 99, "task_profile": {"spine": {"interp": 99}}, "ts_data": []}
    with pytest.raises(spine_stream.SpineDecodeError, match="INTERP 99"):
        spine_stream.decode(document)


@pytest.mark.parametrize(
    "damage",
    [
        lambda d: d.update(ts_data=[["x", 1]]),
        lambda d: d.update(trial_seed="seven"),
        lambda d: d["task_profile"]["spine"].update(inputs=[{"slot": "port"}]),
        lambda d: d["task_profile"]["spine"]["table"].update(states=[[1, 2]]),
        lambda d: d.update(ts_data=[[1, 5], [1, 3]]),
    ],
)
def test_a_malformed_document_is_refused_by_name(damage):
    """Replay refuses as `SpineDecodeError`, never with whatever a malformed
    field happens to raise, so a caller can always tell a refusal apart."""
    document = {
        "interp": 2, "trial_seed": 7, "ts_data": [],
        "task_profile": {"strobes": {}, "config": [], "spine": {
            "interp": 2, "params": [], "inputs": [], "outputs": [],
            "table": {"states": [[0, 0, 255, 255, 255, 255, 255, 255, 0, 0, 1, 0]], "edges": []},
            "structural": {},
        }},
    }
    damage(document)
    with pytest.raises(spine_stream.SpineDecodeError):
        spine_stream.expected_stream(spine_stream.decode(document))


@pytest.mark.parametrize("header", [1, None])
def test_the_header_must_name_the_interpreter_the_snapshot_was_lowered_for(header):
    """The header alone says which interpreter ran a run (`INTERP=<n>`). A run
    whose header names the trial runner, or nothing, is not replayed as a table
    whatever its snapshot claims: the board that wrote it never said it ran one."""
    document = {"task_profile": {"spine": {"interp": 2}}, "ts_data": []}
    if header is not None:
        document["interp"] = header
    with pytest.raises(spine_stream.SpineDecodeError, match="header"):
        spine_stream.decode(document)

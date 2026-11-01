"""A saved spine task runs a session end to end, with no box — issues #98, #101 and #102.

No hardware is needed to prove the path, only to measure it. The saved task's
GENERATED folder is compiled for the host against the instrumented shim
(`extras/host_test/box_shim/`), so the board here is the real `BoxSpine.h`
running the real generated table on a simulated animal. Its serial transcript
is then played into the real session path (`PortManager`, the handshake,
`SessionRunner`, `AnimalWriter`), and the `.tsv` that path wrote is replayed
from nothing but itself: every strobe the board sent must be predicted.

A 2AFC task and a go/no-go pair run the same way, with an animal that reacts
to the board's own outputs, and the outcome class of each trial is read off
the states its replay entered. So do FR, VR and PR sessions on a pressing
animal, with each trial's counted presses and the PR breakpoint, and a held
trial whose broken hold and aborts each replay to their class.

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

from ephymeris_sidecar.analytics.stream import replay as rp
from ephymeris_sidecar.analytics.stream import spine as spine_stream
from ephymeris_sidecar.analytics.stream.summary import summarize
from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.sessions import recovery
from ephymeris_sidecar.sessions import runner as runner_module
from ephymeris_sidecar.sessions.runner import BoxConfig, SessionRunner
from ephymeris_sidecar.taskdef import lowering
from ephymeris_sidecar.taskdef.model import TaskDefinition
from ephymeris_sidecar.taskdef.store import TaskStore
from ephymeris_sidecar.taskdef.validate import validate
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
OVERRIDES = {"block_b1_trials": 3, "reward_permille_r1": 600}

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
    return save(tmp_path, fixture.tracer())


def save(tmp_path: Path, raw: dict) -> Path:
    store = TaskStore(tmp_path / "data", library_root=FIRMWARE)
    definition = TaskDefinition.from_json(raw)
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


def run_board(folder: Path, host_lines: list[str], events, ticks: int, tmp_path: Path,
              animal: str = "") -> list[str]:
    """Compile the generated folder for the host and run it: its serial transcript.

    `events` are scripted (ms, pin, level) moves; `animal` is C++ defining
    `static void animal(unsigned long t)`, called every tick before `loop()`,
    for an animal that reacts to what the board drives."""
    ino = folder / f"{folder.name}.ino"
    channels = registry.channels()
    profile = task_profile.load_profile(folder)
    # Every input starts inactive: the rig's beams are active LOW.
    idle = "".join(f"  bb_pinValue[{channels.get(i['channel']).index}] = HIGH;\n"
                   for i in profile.spine["inputs"])
    feed = "\n".join(f"  bb_feed({json.dumps(line)});" for line in host_lines)
    moves = ", ".join(f"{{{t}UL, {p}, {v}}}" for t, p, v in events) or "{0UL, 0, 0}"
    source = tmp_path / "board.cpp"
    source.write_text(
        "#include <Arduino.h>\n"
        f'#include "{ino}"\n'
        "struct Move { unsigned long t; int pin; int level; };\n"
        f"static const Move kMoves[] = {{ {moves} }};\n"
        f"{animal or 'static void animal(unsigned long) {}'}\n"
        "int main() {\n"
        f"{idle}"
        f"{feed}\n"
        "  setup();\n"
        "  unsigned long t0 = millis();\n"
        "  size_t k = 0, n = sizeof(kMoves) / sizeof(kMoves[0]);\n"
        f"  for (unsigned long t = 1; t <= {ticks}UL; ++t) {{\n"
        "    while (k < n && kMoves[k].t == t) { bb_pinValue[kMoves[k].pin] = kMoves[k].level; k++; }\n"
        "    animal(t);\n"
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


async def run_session(tmp_path: Path, folder: Path, transcript: list[str], monkeypatch,
                      overrides: dict | None = None) -> Path:
    """Play the board's transcript into the real session path; the `.tsv` it wrote."""
    profile = task_profile.load_profile(folder)
    overrides = OVERRIDES if overrides is None else overrides
    config = {f.metadata_key: overrides.get(f.metadata_key, f.default) for f in profile.config}
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


def host_lines(folder: Path, overrides: dict | None = None) -> list[str]:
    profile = task_profile.load_profile(folder)
    overrides = OVERRIDES if overrides is None else overrides
    config = {f.metadata_key: overrides.get(f.metadata_key, f.default) for f in profile.config}
    command = build_start_command(profile, config)
    return [command.begin_line, *command.set_lines, command.start_line(SEED)]


async def test_a_saved_spine_task_runs_a_session_and_its_tsv_alone_replays(tmp_path, monkeypatch):
    folder = save_tracer(tmp_path)
    port = registry.channels().get("odor_port").index
    transcript = run_board(folder, host_lines(folder), animal(port), 16000, tmp_path)
    assert transcript[:3] == ["INTERP=5", f"FREE_RAM={FREE_RAM}", "READY"]
    assert not any(line.startswith("CLAMPED") for line in transcript)

    tsv = await run_session(tmp_path, folder, transcript, monkeypatch)
    text = tsv.read_text(encoding="utf-8")
    header = text[: text.index("\n", text.index("# task_profile:"))]
    # Everything replay needs is in the header, before the first strobe.
    assert "# interp: 5\n" in header and f"# free_ram: {FREE_RAM}\n" in header
    assert f"# trial_seed: {SEED}\n" in header and "# block_b1_trials: 3\n" in header
    assert '"spine":' in header

    document = json.loads(json_of(tsv).read_text(encoding="utf-8"))
    vocab = registry.vocabulary()
    names = {document["task_profile"]["strobes"][str(c)] for c, _ in document["ts_data"]}
    edge_names = set(registry.channel_set().edge_codes())
    assert names <= edge_names | {"START_SESSION", "BLOCK_START", "TRIAL_START", "END_SESSION"}, \
        "the stream holds only channel edge codes and structural codes"
    assert names >= {"ODOR_PORT_ENTER", "TRIAL_LIGHT_ON", "ODOR_LINE_1_ON", "END_SESSION"}
    assert [n for c, _ in document["ts_data"] for n in [vocab.name_of(c)]].count("TRIAL_START") == 3
    assert [vocab.name_of(c) for c, _ in document["ts_data"]][1] == "BLOCK_START", "the one block starts at once"
    assert document["stop_reason"] == runner_module.CLEAN_STOP_REASON

    record = spine_stream.decode(document)
    assert spine_stream.expected_stream(record) == [tuple(s) for s in document["ts_data"]], \
        "replay predicts every strobe the board sent, at its tick"

    # And Analytics scores it from that replay (`ANALYTICS.md#how-a-spine-run-is-scored`):
    # trials 1 and 3 held through the odor, trial 2 let go during it.
    summary = summarize(document, None)
    assert summary.status == "ok" and summary.divergence is None
    [metric] = summary.metrics
    assert (metric.hits, metric.counted, metric.triggered) == (2, 2, 3), "the abort is excluded"
    table = spine_stream.trial_table(document)
    assert [t["outcome"] for t in table["trials"]] == ["correct", "abort_during_sampling", "correct"]
    assert [t["phaseEntries"][1] for t in table["trials"]] == [200, 5000, 8500], \
        "the present begins at each poke, on the board's own clock"
    assert summary.replay.rewarded.n == sum(t["rewarded"] for t in table["trials"])


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


# --- the Response window and the contingency map (#101) -------------------------


def answering_animal(plan: list[tuple[int, int, int]]) -> str:
    """C++ for an animal that pokes the port when the trial light comes on, holds
    it until the odor goes off, and 100 ms later answers trial k as plan[k] says:
    (the input pin it pokes after odor 1, after odor 2, how long it holds), a
    pin of -1 to withhold. It reads the odor off the board's own output pins,
    so it answers whichever row the board drew."""
    pin = {name: registry.channels().get(name).index
           for name in ("odor_port", "trial_light", "odor_line_1", "odor_line_2")}
    rows = ", ".join(f"{{{a}, {b}, {hold}}}" for a, b, hold in plan)
    return f"""
static const int kPlan[][3] = {{ {rows} }};
static const int kPlanLen = {len(plan)};
static int stage = 0, odor = 0, trial = -1, held = -1;
static unsigned long answerAt = 0, releaseAt = 0;
static void animal(unsigned long t) {{
  if (held >= 0 && t == releaseAt) {{ bb_pinValue[held] = HIGH; held = -1; }}
  if (stage == 0 && bb_pinValue[{pin['trial_light']}] == HIGH) {{
    trial++; odor = 0; bb_pinValue[{pin['odor_port']}] = LOW; stage = 1;
  }} else if (stage == 1) {{
    if (bb_pinValue[{pin['odor_line_1']}] == HIGH) odor = 1;
    if (bb_pinValue[{pin['odor_line_2']}] == HIGH) odor = 2;
    if (odor && bb_pinValue[{pin['odor_line_1']}] == LOW && bb_pinValue[{pin['odor_line_2']}] == LOW) {{
      bb_pinValue[{pin['odor_port']}] = HIGH; answerAt = t + 100; stage = 2;
    }}
  }} else if (stage == 2 && t == answerAt) {{
    int at = trial < kPlanLen ? kPlan[trial][odor - 1] : -1;
    if (at >= 0) {{ bb_pinValue[at] = LOW; held = at; releaseAt = t + (unsigned long)kPlan[trial][2]; }}
    stage = 3;
  }} else if (stage == 3 && bb_pinValue[{pin['trial_light']}] == LOW) {{
    stage = 0;
  }}
}}
"""


def trials_of(document: dict) -> list[dict]:
    """Each trial's row id, outcome class, whether it paid and how many presses
    a Counter counted, read off the states its replay entered: the row from the
    snapshot's `table.rows`, the class from the one state with an outcome, the
    pay from a chance state's hit, and the presses from the watched rises while
    a counter state rested (the completing one included), as #99's trial table
    counts them."""
    record = spine_stream.decode(document)
    snapshot = document["task_profile"]["spine"]
    states, row_of = record.table.states, snapshot["table"]["rows"]
    trials: list[dict] = []
    held = None
    for now, a in rp.replay(record.table, record.params, record.seed, record.events, record.end_tick,
                            interp=record.interp):
        if trials and held is not None and states[held].is_count:
            trials[-1]["presses"] += bin(a.rose).count("1")
        if a.entered[0] != rp.NONE:
            held = a.entered[1] if a.entered[1] != rp.NONE else a.entered[0]  # where the core now rests
        if a.flags & rp.ACT_TRIAL_START:
            if now == record.end_tick:
                break  # the start that ends the session is no trial
            trials.append({"row": None, "outcome": None, "rewarded": False, "presses": 0})
        trial = trials[-1]
        for s in (e for e in a.entered if e != rp.NONE):
            if row_of[s] is not None:
                trial["row"] = snapshot["rows"][row_of[s]]["id"]
            if states[s].outcome:
                assert trial["outcome"] is None, "a trial marks its class once"
                trial["outcome"] = lowering.OUTCOME_CLASSES[states[s].outcome - 1]
        first = states[a.entered[0]] if a.entered[0] != rp.NONE else None
        if first is not None and first.is_chance and a.entered[1] == first.on_hit:
            trial["rewarded"] = True
    return trials


async def run_generated(tmp_path, monkeypatch, raw: dict, overrides: dict, plan, ticks: int) -> dict:
    """Save `raw`, run its generated board on the answering animal, play it
    through the session path, and check the `.tsv`'s replay predicts every
    strobe. The run's document."""
    return await run_task(tmp_path, monkeypatch, raw, overrides, ticks, animal=answering_animal(plan))


async def run_task(tmp_path, monkeypatch, raw: dict, overrides: dict, ticks: int, events=(),
                   animal: str = "") -> dict:
    """`run_generated`, for scripted (ms, pin, level) `events` or any animal."""
    folder = save(tmp_path, raw)
    transcript = run_board(folder, host_lines(folder, overrides), list(events), ticks, tmp_path, animal)
    assert transcript[:3] == ["INTERP=5", f"FREE_RAM={FREE_RAM}", "READY"]
    assert not any(line.startswith("CLAMPED") for line in transcript)
    tsv = await run_session(tmp_path, folder, transcript, monkeypatch, overrides)
    document = json.loads(json_of(tsv).read_text(encoding="utf-8"))
    assert document["stop_reason"] == runner_module.CLEAN_STOP_REASON
    record = spine_stream.decode(document)
    assert spine_stream.expected_stream(record) == [tuple(s) for s in document["ts_data"]], \
        "replay predicts every strobe the board sent, at its tick"
    return document


async def test_a_2afc_task_runs_and_replays_to_its_outcome_classes(tmp_path, monkeypatch):
    port = registry.channels()
    left, right = port.get("left_well").index, port.get("right_well").index
    answers = {  # odor 1 pays at the right well, odor 2 at the left; each must be held 200 ms
        "correct": (right, left, 300),
        "wrong_response": (left, right, 50),
        "omission": (-1, -1, 0),
        "hold_broken": (right, left, 50),
    }
    plan = ["correct", "wrong_response", "omission", "hold_broken", "correct", "correct", "correct", "correct"]
    overrides = {"block_b1_trials": len(plan), "reward_permille_odor_1_right": 600,
                 "reward_permille_odor_2_left": 600}
    document = await run_generated(tmp_path, monkeypatch, fixture.two_afc(), overrides,
                                   [answers[a] for a in plan], 70000)

    trials = trials_of(document)
    assert [t["outcome"] for t in trials] == plan
    assert {t["row"] for t in trials} == {"odor_1", "odor_2"}, "the pick state drew both rows"
    # A reward drawn at 600 permille: some correct trials paid and some did not,
    # and nothing else ever pays.
    paid = [t["rewarded"] for t in trials if t["outcome"] == "correct"]
    assert True in paid and False in paid
    assert not any(t["rewarded"] for t in trials if t["outcome"] != "correct")
    vocab = registry.vocabulary()
    fluid = [vocab.name_of(c) for c, _ in document["ts_data"] if vocab.name_of(c).startswith("FLUID_")]
    expected = [f"FLUID_{2 if t['row'] == 'odor_1' else 1}_{edge}" for t in trials if t["rewarded"]
                for edge in ("ON", "OFF")]
    assert fluid == expected, "each paid trial opened its own row's line"


async def test_a_go_no_go_pair_runs_and_replays_to_its_outcome_classes(tmp_path, monkeypatch):
    resp = registry.channels().get("right_well").index
    respond, withhold = (resp, resp, 50), (-1, -1, 0)
    plan = [respond, withhold] * 5
    overrides = {"block_b1_trials": len(plan), "reward_permille_go_resp": 600}
    document = await run_generated(tmp_path, monkeypatch, fixture.go_no_go(), overrides, plan, 80000)

    trials = trials_of(document)
    assert {t["row"] for t in trials} == {"go", "no_go"}, "the pick state drew both rows"
    classes = {("go", True): "correct", ("go", False): "omission",
               ("no_go", True): "false_alarm", ("no_go", False): "withheld"}
    assert [t["outcome"] for t in trials] == [classes[t["row"], answer == respond]
                                              for t, answer in zip(trials, plan)]
    assert not any(t["rewarded"] for t in trials if t["outcome"] != "correct")


# --- Hold, aborts and the Counter (#102) ----------------------------------------


def presses(pin: int, start: int, stop: int, every: int = 40) -> list[tuple[int, int, int]]:
    """A rat working a lever (the right well's beam, active LOW): a 10 ms press
    every `every` ms from `start` until `stop`."""
    out = []
    for t in range(start, stop, every):
        out += [(t, pin, 0), (t + 10, pin, 1)]
    return out


def lever() -> int:
    return registry.channels().get("right_well").index


def scored(document: dict) -> list[tuple[str | None, int, bool]]:
    """The run's trial table, as #99's `replayed()` reads it from the table's own
    annotations: each trial's class, the presses it counts in the Counter
    phase (phase 0) on the lever's channel, and whether it paid."""
    result = spine_stream.replayed(document)
    assert result.divergence is None and all(t.complete for t in result.trials)
    return [(t.outcome, sum(c.count for c in t.input_counts if c.phase == 0 and c.channel == "right_well"),
             t.rewarded) for t in result.trials]


async def test_a_fixed_ratio_session_pays_every_fifth_press(tmp_path, monkeypatch):
    document = await run_task(tmp_path, monkeypatch, fixture.fixed_ratio(5), {"block_b1_trials": 6}, 8000,
                              events=presses(lever(), 100, 7000))
    trials = trials_of(document)
    assert [(t["outcome"], t["presses"], t["rewarded"]) for t in trials] == [("correct", 5, True)] * 6
    assert scored(document) == [("correct", 5, True)] * 6, "the trial table counts each ratio's presses"


async def test_a_variable_ratio_session_draws_n_for_each_reward(tmp_path, monkeypatch):
    document = await run_task(tmp_path, monkeypatch, fixture.variable_ratio(1, 9), {"block_b1_trials": 12}, 12000,
                              events=presses(lever(), 100, 11000))
    trials = trials_of(document)
    assert [t["outcome"] for t in trials] == ["correct"] * 12
    counts = [t["presses"] for t in trials]
    assert all(1 <= n <= 9 for n in counts) and len(set(counts)) >= 3, counts
    assert scored(document) == [("correct", n, True) for n in counts]


async def test_a_progressive_ratio_session_ends_at_its_breakpoint(tmp_path, monkeypatch):
    """The rat presses for 6 s and stops. Each reward needed the next ratio; the
    unfinished one runs out its 2 s limit, an omission, and the session ends
    after that trial's ITI by itself, long before its 50 trials."""
    document = await run_task(tmp_path, monkeypatch, fixture.progressive_ratio(2000), {"block_b1_trials": 50}, 14000,
                              events=presses(lever(), 100, 6000))
    trials = trials_of(document)
    *done, last = trials
    assert done and [t["outcome"] for t in done] == ["correct"] * len(done)
    assert [t["presses"] for t in done] == fixture.RICHARDSON_ROBERTS[: len(done)]
    assert last["outcome"] == "omission" and last["presses"] < fixture.RICHARDSON_ROBERTS[len(done)]
    breakpoint_ = max(t["presses"] for t in trials if t["outcome"] == "correct")
    assert breakpoint_ == fixture.RICHARDSON_ROBERTS[len(done) - 1] >= 9, "the last ratio completed"
    vocab = registry.vocabulary()
    assert vocab.name_of(document["ts_data"][-1][0]) == "END_SESSION"
    assert len(trials) < 50
    # The trial table holds the breakpoint's data: each trial's counted presses,
    # the omission that ended the session complete and last.
    table = scored(document)
    assert table == [(t["outcome"], t["presses"], t["rewarded"]) for t in trials]
    assert max(n for outcome, n, _ in table if outcome == "correct") == breakpoint_


@pytest.mark.parametrize(("override", "clamped"), [
    ({"counter_0_count": 8, "counter_0_count_max": 3}, True),   # inverted: N would be fixed at 8
    ({"counter_0_count": 12, "counter_0_count_max": 15}, False),  # both past the defaults, in order
    ({}, False),
])
def test_the_board_refuses_a_drawn_count_whose_range_is_inverted(tmp_path, override, clamped):
    """A per-box override can set countMax below count, which would silently make
    VR an FR. The board answers CLAMPED for the high end, so the host never
    sends START (`TASKS.md#confirming-the-parameters`)."""
    folder = save(tmp_path, fixture.variable_ratio(1, 9))
    transcript = run_board(folder, host_lines(folder, {"block_b1_trials": 3, **override}), [], 10, tmp_path)
    assert ("CLAMPED NX0" in transcript) == clamped, transcript
    assert not any(line.startswith("CLAMPED") and line != "CLAMPED NX0" for line in transcript)


async def test_an_abort_after_the_outcome_leaves_a_paid_trial_correct(tmp_path, monkeypatch):
    """FR-2, then a Delay a press aborts. The pressing rat aborts every Delay,
    after its reward: the trial was decided at its Outcome, so it stays correct."""
    raw = fixture.fixed_ratio(2)
    raw["spine"].insert(2, {"phase": "delay", "ms": 300, "abortOnEnter": "lever"})
    assert validate(TaskDefinition.from_json(raw)) == []
    document = await run_task(tmp_path, monkeypatch, raw, {"block_b1_trials": 5}, 6000,
                              events=presses(lever(), 100, 5500))
    record = spine_stream.decode(document)
    phase_of = document["task_profile"]["spine"]["table"]["phases"]
    aborted = [now for now, a in rp.replay(record.table, record.params, record.seed, record.events,
                                           record.end_tick, interp=record.interp)
               if a.rose and a.entered[0] != rp.NONE and phase_of[a.entered[0]] == 3]
    assert len(aborted) == 5, "a press aborted each delay, straight to the ITI"
    assert scored(document) == [("correct", 2, True)] * 5


async def test_a_broken_hold_and_each_abort_replay_to_their_class(tmp_path, monkeypatch):
    """The held trial (wait 5 s, hold 300, present 500 holding, delay 400 that a
    right-well poke aborts, reward, ITI 1000), five times."""
    channels = registry.channels()
    port, early = channels.get("odor_port").index, channels.get("right_well").index
    poke, clear = 0, 1
    events = [
        # 1: no poke for 5 s: the wait runs out before any stimulus.
        (6200, port, poke), (6350, port, clear),        # 2: let go 150 ms into the hold
        (7500, port, poke), (8000, port, clear),        # 3: let go during the odor
        (9200, port, poke), (9950, port, clear),        # 4: through the odor, then
        (10200, early, poke), (10250, early, clear),    #    a poke at the right well in the delay
        (11200, port, poke), (12100, port, clear),      # 5: through the odor; the delay runs out
    ]
    document = await run_task(tmp_path, monkeypatch, fixture.held_trial(), {"block_b1_trials": 5}, 16000,
                              events=events)
    classes = ["abort_before_stimulus", "hold_broken", "abort_during_sampling", "abort_during_sampling", "correct"]
    assert [t["outcome"] for t in trials_of(document)] == classes
    result = spine_stream.replayed(document)
    assert result.divergence is None and [t.outcome for t in result.trials] == classes
    assert [t.rewarded for t in result.trials] == [False] * 4 + [True]
    assert all(t.row == "r1" for t in result.trials), "an end the rows share still names the trial's row"


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


def test_a_version_2_run_whose_table_holds_a_pick_state_is_refused():
    """INTERP 2 had no pick state, so a run claiming it with one in its table
    was not run by the table it carries."""
    n = rp.NONE
    pick = [0, 0, n, n, n, n, n, n, 0, 1, rp.STARTS_TRIAL | rp.PICK, 0]
    rest = [0, 0, 0, 0, 0, n, n, n, 0, 0, 0, 0]
    document = {
        "interp": 2, "trial_seed": 7, "ts_data": [], "block_b1_trials": 1,
        "task_profile": {"strobes": {"1": "START_SESSION", "2": "TRIAL_START", "3": "END_SESSION"},
                         "config": [{"wireKey": "NT", "metadataKey": "block_b1_trials"}], "spine": {
            "interp": 2, "params": ["NT"], "inputs": [], "outputs": [],
            "table": {"states": [pick, rest], "edges": [[0, 0, 1]]},
            "structural": {"sessionStart": "START_SESSION", "trialStart": "TRIAL_START",
                           "sessionEnd": "END_SESSION"},
        }},
    }
    with pytest.raises(spine_stream.SpineDecodeError, match="pick"):
        spine_stream.decode(document)
    for version in (document, document["task_profile"]["spine"]):
        version["interp"] = 3
    assert spine_stream.decode(document).interp == 3


def test_a_version_3_run_whose_table_holds_a_counter_is_refused():
    n = rp.NONE
    counter = [1, 1, n, n, n, n, n, n, 0, 1, rp.STARTS_TRIAL | rp.COUNT, 0]
    document = {
        "interp": 3, "trial_seed": 7, "ts_data": [], "block_b1_trials": 1, "count": 5,
        "task_profile": {"strobes": {}, "config": [], "spine": {
            "interp": 3, "params": [], "inputs": [], "outputs": [],
            "table": {"states": [counter], "edges": [[0, rp.RISE, 0]],
                      "counter": {"min": 0, "max": 0, "ratios": []}},
            "structural": {},
        }},
    }
    with pytest.raises(spine_stream.SpineDecodeError, match="counter"):
        spine_stream.decode(document)


# --- blocks (#103) ----------------------------------------------------------------


#: Short trials: odor for 50 ms, an ITI of 50 ms. The animal answers 100 ms
#: after the odor goes off and holds 300 ms, past the window's 200 ms hold.
FAST = {"present_1_ms": 50, "iti_4_ms": 50}


def board_names(document: dict) -> list[str]:
    vocab = registry.vocabulary()
    return [vocab.name_of(c) for c, _ in document["ts_data"]]


async def test_a_reversal_switches_blocks_on_the_trial_after_8_of_10_correct(tmp_path, monkeypatch):
    """Block a ends once 8 of its last 10 trials were correct; block b reverses
    the maps for 4 trials, and its end ends the session. An error in block a
    repeats its row once. The block column comes from the core, through replay."""
    left, right = (registry.channels().get(n).index for n in ("left_well", "right_well"))
    as_a, as_b, wrong = (right, left, 300), (left, right, 300), (left, right, 50)
    # A wrong answer (repeated once, wrong again), then eight right: block a's
    # 10 trials hold 8 correct when trial 11 starts. Then block b, answered reversed.
    plan = [wrong, wrong] + [as_a] * 8 + [as_b] * 4
    document = await run_generated(tmp_path, monkeypatch, fixture.reversal(), FAST, plan, 40000)

    result = spine_stream.replayed(document)
    assert result.divergence is None
    trials = result.trials
    assert [t.block for t in trials] == ["a"] * 10 + ["b"] * 4
    assert [t.outcome for t in trials] == ["wrong_response"] * 2 + ["correct"] * 12
    assert [t.correction for t in trials] == [False, True] + [False] * 12, "one repeat, k = 1"
    assert trials[1].row == trials[0].row, "a correction repeats the row"
    assert {t.row for t in trials[10:]} <= {"odor_1_rev", "odor_2_rev"}
    names = board_names(document)
    assert names.count("BLOCK_START") == 2 and names[-1] == "END_SESSION"
    assert names.count("TRIAL_START") == 14, "the blocks' end ended the session, at no trial cap"


async def test_a_looping_bandit_runs_blocks_of_40_to_60_until_its_trial_cap(tmp_path, monkeypatch):
    """Two blocks, each lasting N drawn from 40-60 at its start, loop until the
    session's 130 trials. The animal always picks the left well, which pays 80%
    of the time in block a and 20% in block b."""
    left = registry.channels().get("left_well").index
    document = await run_generated(tmp_path, monkeypatch, fixture.bandit(), FAST, [(left, left, 300)] * 130,
                                   130 * 700)

    result = spine_stream.replayed(document)
    assert result.divergence is None
    blocks = [t.block for t in result.trials]
    assert len(blocks) == 130
    runs: list[list] = []
    for block in blocks:
        if runs and runs[-1][0] == block:
            runs[-1][1] += 1
        else:
            runs.append([block, 1])
    assert [b for b, _ in runs] == ["a", "b", "a"][: len(runs)] and len(runs) == 3
    assert all(40 <= n <= 60 for _, n in runs[:-1]) and runs[-1][1] <= 60, runs
    assert board_names(document).count("BLOCK_START") == 3
    paid = {b: sum(t.rewarded for t in result.trials if t.block == b) / blocks.count(b) for b in "ab"}
    assert paid["a"] > 0.6 > 0.4 > paid["b"], paid


async def test_a_shuffle_bag_draws_each_row_its_weight_in_every_refill(tmp_path, monkeypatch):
    """Pool selection is a shuffle bag per block, drawn from the seeded stream
    as the session runs: of every four trials, three draw odor 1 and one odor 2."""
    left, right = (registry.channels().get(n).index for n in ("left_well", "right_well"))
    raw = fixture.two_afc(blocks=[{"id": "pool", "rows": ["odor_1", "odor_2"], "select": "bag",
                                   "weights": [3, 1], "trials": 12}])
    document = await run_generated(tmp_path, monkeypatch, raw, FAST, [(right, left, 300)] * 12, 20000)
    rows = [t.row for t in spine_stream.replayed(document).trials]
    assert len(rows) == 12
    for refill in range(0, 12, 4):
        assert sorted(rows[refill : refill + 4]) == ["odor_1"] * 3 + ["odor_2"], rows


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

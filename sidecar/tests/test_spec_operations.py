"""The structural edit blocks' invariants, mirrored.

The Task Designer's structural blocks (`src/lib/specs/operations.ts`) are
compound edits that move a topology knob together with everything that must
move with it, so the machine is never invalid in between. Each op maintains
the lint rules an operator actually trips: TG201 (a timing rename rewrites
every reference), TG220/TG221 (referential integrity and stage counts),
TG224 (a reward line's well matches its port), TG302/TG303/TG304 (agreement
with `capabilities()`), TG506 (every bound strobe resolves for every port it
could select).

> [!CAUTION]
> **THIS IS A SECOND IMPLEMENTATION, AND IT IS ONE ON PURPOSE.** The frontend
> is TypeScript and this repo has no frontend test runner (`npm run typecheck`
> is the only automated frontend gate, and `SpecDocument` is
> `Record<string, unknown>` so it cannot check a document path either). What
> follows applies the same path edits to the same bundled specs in Python and
> asserts the compiler accepts the result.
>
> So it proves the DESIGN is sound — that this sequence of edits to this spec
> produces a task that compiles — and it does NOT prove `operations.ts`
> implements that design. When an op changes, this file must be changed with
> it by hand; nothing detects the two drifting apart. It earns its place
> because the invariants are the expensive part and the op table is small:
> every case here is one that was, or could plausibly become, a real bug. The
> go/no-go → n-alternative case below is the one that already was — the
> operation shipped without the per-port codes and produced six TG506s.

Run: `pytest tests/test_spec_operations.py`
"""

from __future__ import annotations

import copy

import pytest
import yaml

from ephymeris_sidecar.specs import compiler

pytestmark = pytest.mark.skipif(
    not compiler.available(), reason="vendored task-spec compiler unavailable"
)


def load(spec_id: str) -> dict:
    return yaml.safe_load((compiler.bundled_specs_dir() / f"{spec_id}.yaml").read_text())


def compile_ok(doc: dict, spec_id: str) -> None:
    """Compile and fail with every ERROR, not just the first."""
    result = compiler.compile(yaml.safe_dump(doc, sort_keys=False), spec_id=spec_id)
    errors = [d for d in list(result.bag) if d.severity.name == "ERROR"]
    assert not errors, "\n".join(f"{d.code} {d.location}: {d.message}" for d in errors)
    assert result.table is not None


# --------------------------------------------------------------------------- #
# The shared primitive: a timing rename rewrites every reference (TG201).
# --------------------------------------------------------------------------- #


def rename_timing(doc: dict, old: str, new: str, *, keep: bool) -> None:
    for row in doc["timing"]:
        if row["id"] == old:
            row["id"] = new
            if not keep:
                row.pop("note", None)
                row.pop("wire_key", None)
    for outcome in doc["contingency"]["outcome_map"].values():
        if outcome.get("delay") == old:
            outcome["delay"] = new
    for port in doc["contingency"]["ports"].values():
        if port.get("reward_duration") == old:
            port["reward_duration"] = new
    for row in doc.get("policy", {}).get("stage_schedule", []) or []:
        if old in row.get("set", {}):
            row["set"][new] = row["set"].pop(old)


def test_rename_timing_id_rewrites_every_reference():
    """The rename primitive, on the spec that exercises all four reference
    sites at once: shaping_gr has a stage schedule keyed by timing id."""
    doc = load("shaping_gr")
    assert any("t_resp_win" in row["set"] for row in doc["policy"]["stage_schedule"])

    rename_timing(doc, "t_resp_win", "t_response_window", keep=True)

    assert not any(row["id"] == "t_resp_win" for row in doc["timing"])
    assert not any("t_resp_win" in row["set"] for row in doc["policy"]["stage_schedule"])
    assert all("t_response_window" in row["set"] for row in doc["policy"]["stage_schedule"])
    # It no longer matches capabilities(), which is TG303's job to say — the
    # point here is only that nothing still points at the old id (TG201).
    result = compiler.compile(yaml.safe_dump(doc, sort_keys=False), spec_id="shaping_gr")
    assert not [d for d in list(result.bag) if d.code == "TG201"]


# --------------------------------------------------------------------------- #
# addSamplingStage / removeSamplingStage
# --------------------------------------------------------------------------- #


def add_sampling_stage(doc: dict) -> None:
    n = doc["topology"]["n_sampling_stages"]
    doc["topology"]["n_sampling_stages"] = n + 1
    if n == 1:
        # Same firmware field at a new index — the note and wire key stay true.
        rename_timing(doc, "t_sample_hold", "t_sample_hold_0", keep=True)
    hold_0 = next(r["ms"] for r in doc["timing"] if r["id"] == "t_sample_hold_0")
    doc["timing"].append({"id": f"t_interstim_gap_{n - 1}", "ms": 0})
    # Seeded from its peer in this document, never from a defaults table.
    doc["timing"].append({"id": f"t_sample_hold_{n}", "ms": hold_0})
    for tt in doc["contingency"]["trial_types"]:
        tt["stages"] = [*tt["stages"], tt["stages"][-1]]


def test_add_sampling_stage_keeps_grgl_compiling():
    doc = load("grgl_2odor")
    add_sampling_stage(doc)
    compile_ok(doc, "grgl_2odor")

    # TG221: every trial type has exactly n stages.
    n = doc["topology"]["n_sampling_stages"]
    assert n == 2
    assert all(len(tt["stages"]) == n for tt in doc["contingency"]["trial_types"])


def test_add_sampling_stage_twice():
    """Past the 1→2 crossing the rename must NOT happen again."""
    doc = load("grgl_2odor")
    add_sampling_stage(doc)
    add_sampling_stage(doc)
    compile_ok(doc, "grgl_2odor")
    assert doc["topology"]["n_sampling_stages"] == 3
    ids = [r["id"] for r in doc["timing"]]
    assert "t_sample_hold" not in ids
    assert {"t_sample_hold_0", "t_sample_hold_1", "t_sample_hold_2"} <= set(ids)


def test_remove_sampling_stage_to_zero():
    """n=0 skips the sampling epoch entirely — the 'pure shaping' recipe."""
    doc = load("shaping_gr")
    doc["topology"]["n_sampling_stages"] = 0
    for tt in doc["contingency"]["trial_types"]:
        tt["stages"] = []
    compile_ok(doc, "shaping_gr")


def test_remove_sampling_stage_renames_back():
    """2→1 restores the unsuffixed id, and every reference follows."""
    doc = load("seq2_retention")
    doc["topology"]["n_sampling_stages"] = 1
    rename_timing(doc, "t_sample_hold_0", "t_sample_hold", keep=True)
    for tt in doc["contingency"]["trial_types"]:
        tt["stages"] = tt["stages"][:1]
    compile_ok(doc, "seq2_retention")


# --------------------------------------------------------------------------- #
# setResponseMode — the op that already shipped a bug.
# --------------------------------------------------------------------------- #

PORT_CODES = {
    "left_well": {
        "enter_code": "WATER_POKE_L",
        "error_code": "WATER_POKE_ERROR_L",
        "break_code": "WATER_UNPOKE_EARLY_L",
        "exit_code": "WATER_UNPOKE_L",
        "reward_line": "fluid_0",
        "reward_code": "FLUID_L",
        "reward_stop_code": "STOP_FLUID_G_L",
    },
    "right_well": {
        "enter_code": "WATER_POKE_R",
        "error_code": "WATER_POKE_ERROR_R",
        "break_code": "WATER_UNPOKE_EARLY_R",
        "exit_code": "WATER_UNPOKE_R",
        "reward_line": "fluid_2",
        "reward_code": "FLUID_R",
        "reward_stop_code": "STOP_FLUID_G_R",
    },
}


def to_n_alternative(doc: dict) -> None:
    doc["topology"]["response_mode"] = "n_alternative"
    # A DIFFERENT firmware field (nogoWellPoll → fluidWellPoll), so the note
    # and wire key are dropped rather than left to lie.
    rename_timing(doc, "t_withhold_win", "t_resp_win", keep=False)
    doc["timing"].append({"id": "t_resp_hold", "ms": 200})

    om = doc["contingency"]["outcome_map"]
    om["correct"]["trigger"] = "HELD"
    om["correct"].pop("note", None)
    om["correct"]["reward"] = "@target"
    om["correct"]["strobe"] = "@target.exit_code"

    ports = doc["contingency"]["ports"]
    for name, codes in PORT_CODES.items():
        if name not in ports:
            continue
        duration = f"t_reward_{name.replace('_well', '')}"
        doc["timing"].append({"id": duration, "ms": 100})
        ports[name].update(**codes, reward_duration=duration)

    for tt in doc["contingency"]["trial_types"]:
        if tt.get("target") is None:
            tt["target"] = "left_well"

    # TG302 is checked in BOTH directions: the stale class has to go.
    del om["false_alarm"]
    om["wrong"] = {
        "trigger": "ENTER", "reward": None, "terminal": "TRIAL_INCORRECT",
        "delay": "t_pen_error", "strobe": "@ports[$ch].error_code",
    }
    om["omission"] = {
        "trigger": "TIMEOUT", "reward": None, "terminal": "TRIAL_INCORRECT",
        "delay": "t_pen_error", "strobe": "RESP_OMIT",
    }
    om["hold_fail"] = {
        "trigger": "BROKEN", "reward": None, "terminal": "TRIAL_INCORRECT",
        "delay": "t_pen_break", "strobe": "@ports[$ch].break_code",
    }


def test_gonogo_to_n_alternative():
    """The regression this file exists for.

    A withhold task's ports declare `enter_code` and nothing else — it never
    reports a wrong port, a broken response hold, or leaving a reward port.
    Switching to n-alternative makes all three reachable at once, and TG506
    wants a code for each on EVERY port. The op shipped without them and
    produced six errors.
    """
    doc = load("gonogo")
    assert "error_code" not in doc["contingency"]["ports"]["left_well"]

    to_n_alternative(doc)
    compile_ok(doc, "gonogo_2")


def test_gonogo_to_n_alternative_without_port_codes_is_rejected():
    """The negative case, pinned: dropping the port codes must NOT compile.

    Without this, a future 'simplification' of the op could quietly remove the
    codes again and the positive test above would still pass for the wrong
    reason — it would be asserting that some other change did the work.
    """
    doc = load("gonogo")
    to_n_alternative(doc)
    for port in doc["contingency"]["ports"].values():
        for field in ("error_code", "break_code", "exit_code"):
            port.pop(field, None)

    result = compiler.compile(yaml.safe_dump(doc, sort_keys=False), spec_id="gonogo_2")
    codes = {d.code for d in list(result.bag) if d.severity.name == "ERROR"}
    assert "TG506" in codes
    assert result.table is None


def test_n_alternative_to_gonogo():
    """The mirror: every target becomes null, which IS the withhold
    declaration, and the classes n-alternative produces have to go."""
    doc = load("grgl_2odor")
    doc["topology"]["response_mode"] = "go_nogo"
    rename_timing(doc, "t_resp_win", "t_withhold_win", keep=False)

    om = doc["contingency"]["outcome_map"]
    om["correct"].update(trigger="TIMEOUT", reward=None, strobe="WATER_POKE_NONE")
    om["correct"].pop("note", None)
    for cls in ("wrong", "omission", "hold_fail"):
        del om[cls]
    om["false_alarm"] = {
        "trigger": "ENTER", "reward": None, "terminal": "TRIAL_INCORRECT",
        "delay": "t_pen_error", "strobe": "@ports[$ch].enter_code",
    }
    for tt in doc["contingency"]["trial_types"]:
        tt["target"] = None

    compile_ok(doc, "grgl_2odor")


# --------------------------------------------------------------------------- #
# The knob toggles
# --------------------------------------------------------------------------- #


def test_drop_commit_hold():
    doc = load("grgl_2odor")
    doc["topology"]["commit_hold"] = False
    # t_commit_hold is no longer required — but an unused timing row is legal,
    # which is what lets the form grey it instead of deleting a typed value.
    compile_ok(doc, "grgl_2odor")


def test_add_retention_delay():
    doc = load("grgl_2odor")
    doc["topology"]["retention_delay"] = True
    doc["timing"].append({"id": "t_retention", "ms": 1500})
    compile_ok(doc, "grgl_2odor")


def test_remove_retention_delay():
    doc = load("seq2_retention")
    doc["topology"]["retention_delay"] = False
    compile_ok(doc, "seq2_retention")


# --------------------------------------------------------------------------- #
# setCorrectRewarded — a contingency field that changes the graph's SHAPE.
# --------------------------------------------------------------------------- #


def test_unrewarded_2afc_drops_the_reward_states():
    """The 'unrewarded 2AFC' recipe. `correct.reward: null` omits the delivery
    PULSE and the consumption WAIT_EXIT from the outcome epoch entirely —
    which is why docs/specs.md §1 cannot say topology is the ONLY layer that
    changes shape."""
    doc = load("grgl_2odor")
    before = compiler.compile(
        yaml.safe_dump(doc, sort_keys=False), spec_id="grgl_2odor"
    )
    doc["contingency"]["outcome_map"]["correct"]["reward"] = None
    doc["contingency"]["outcome_map"]["correct"].pop("note", None)
    compile_ok(doc, "grgl_2odor")

    after = compiler.compile(yaml.safe_dump(doc, sort_keys=False), spec_id="grgl_2odor")
    assert len(after.table.nodes) < len(before.table.nodes)


def test_rewarding_needs_a_line_on_the_matching_well():
    """TG224, pinned: the op filters reward-line options to lines whose `well`
    IS the port's channel, so this mistake is unreachable from the UI. It is
    still worth pinning that the compiler catches it — the filter is a
    convenience, the rule is the guarantee."""
    doc = load("grgl_2odor")
    # fluid_0 is plumbed to the LEFT well; give it to the right one.
    doc["contingency"]["ports"]["right_well"]["reward_line"] = "fluid_0"
    result = compiler.compile(yaml.safe_dump(doc, sort_keys=False), spec_id="grgl_2odor")
    codes = {d.code for d in list(result.bag) if d.severity.name == "ERROR"}
    assert "TG224" in codes


# --------------------------------------------------------------------------- #
# addStimulus / addTrialType
# --------------------------------------------------------------------------- #


def test_add_stimulus_and_trial_type():
    doc = load("grgl_2odor")
    doc["contingency"]["stimuli"].append(
        {"id": "odor2", "emitter": "odor_line_2", "on_code": "ODOR_2_ON"}
    )
    doc["contingency"]["trial_types"].append(
        {"id": "tt3", "stages": ["odor2"], "target": "right_well", "weight": 1}
    )
    compile_ok(doc, "grgl_2odor")


def test_trial_type_stage_count_must_match():
    """TG221 is exact, not a minimum — which is why adding a stage has to
    touch every trial type rather than only the ones being edited."""
    doc = load("seq2_retention")
    # A DECLARED stimulus, just one of them — so the only thing wrong is the
    # count. An undeclared id would be caught by the schema's identifier
    # pattern in the LOAD pass and never reach TG221.
    doc["contingency"]["trial_types"][0]["stages"] = ["odor_a"]
    result = compiler.compile(
        yaml.safe_dump(doc, sort_keys=False), spec_id="seq2_retention"
    )
    codes = {d.code for d in list(result.bag) if d.severity.name == "ERROR"}
    assert "TG221" in codes


# --------------------------------------------------------------------------- #
# Every bundled spec still compiles untouched — the baseline these all move from.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "spec_id", ["grgl_2odor", "gonogo", "seq2_retention", "shaping_gr", "shaping_gr_ez"]
)
def test_bundled_spec_compiles(spec_id: str):
    compile_ok(copy.deepcopy(load(spec_id)), spec_id)

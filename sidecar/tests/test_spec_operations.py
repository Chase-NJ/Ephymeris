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


def load(paradigm_id: str) -> dict:
    """A freshly generated task, which is what an operator actually edits.

    These used to be the five bundled specs. Nothing ships as a spec, so the
    bases are the paradigms' own skeletons -- a stronger subject for op tests,
    since it is the document the ops will really be run against.
    """
    from ephymeris_sidecar.taskgraph import paradigms

    p = paradigms.get(paradigm_id)
    return paradigms.skeleton(p, spec_id=paradigm_id)


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
    doc = load("shaping")
    doc["policy"]["stage_schedule"] = [{"at_trial": 0, "set": {"t_resp_win": 5000}}]

    rename_timing(doc, "t_resp_win", "t_response_window", keep=True)

    assert not any(row["id"] == "t_resp_win" for row in doc["timing"])
    assert not any("t_resp_win" in row["set"] for row in doc["policy"]["stage_schedule"])
    assert all("t_response_window" in row["set"] for row in doc["policy"]["stage_schedule"])
    # It no longer matches capabilities(), which is TG303's job to say — the
    # point here is only that nothing still points at the old id (TG201).
    result = compiler.compile(yaml.safe_dump(doc, sort_keys=False), spec_id="shaping")
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
    doc = load("two_afc")
    add_sampling_stage(doc)
    compile_ok(doc, "grgl_2odor")

    # TG221: every trial type has exactly n stages.
    n = doc["topology"]["n_sampling_stages"]
    assert n == 2
    assert all(len(tt["stages"]) == n for tt in doc["contingency"]["trial_types"])


def test_add_sampling_stage_twice():
    """Past the 1→2 crossing the rename must NOT happen again."""
    doc = load("two_afc")
    add_sampling_stage(doc)
    add_sampling_stage(doc)
    compile_ok(doc, "grgl_2odor")
    assert doc["topology"]["n_sampling_stages"] == 3
    ids = [r["id"] for r in doc["timing"]]
    assert "t_sample_hold" not in ids
    assert {"t_sample_hold_0", "t_sample_hold_1", "t_sample_hold_2"} <= set(ids)


def test_remove_sampling_stage_to_zero():
    """n=0 skips the sampling epoch entirely — the 'pure shaping' recipe."""
    doc = load("shaping")
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

    THE GENERATOR NOW PREVENTS THIS BY CONSTRUCTION: a skeleton emits all five
    codes on every port whatever its shape, precisely so that a later shape
    change cannot strand one. The condition therefore has to be recreated here
    -- which is still worth testing, because a hand-written spec or a deleted
    field produces it and the op is what has to cope.
    """
    doc = load("go_nogo")
    for port in doc["contingency"]["ports"].values():
        for field in ("error_code", "break_code", "exit_code"):
            port.pop(field, None)
    assert "error_code" not in doc["contingency"]["ports"]["left_well"]

    to_n_alternative(doc)
    compile_ok(doc, "go_nogo_2")


def test_gonogo_to_n_alternative_without_port_codes_is_rejected():
    """The negative case, pinned: dropping the port codes must NOT compile.

    Without this, a future 'simplification' of the op could quietly remove the
    codes again and the positive test above would still pass for the wrong
    reason — it would be asserting that some other change did the work.
    """
    doc = load("go_nogo")
    to_n_alternative(doc)
    for port in doc["contingency"]["ports"].values():
        for field in ("error_code", "break_code", "exit_code"):
            port.pop(field, None)

    result = compiler.compile(yaml.safe_dump(doc, sort_keys=False), spec_id="go_nogo_2")
    codes = {d.code for d in list(result.bag) if d.severity.name == "ERROR"}
    assert "TG506" in codes
    assert result.table is None


def test_n_alternative_to_gonogo():
    """The mirror: every target becomes null, which IS the withhold
    declaration, and the classes n-alternative produces have to go."""
    doc = load("two_afc")
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
    doc = load("two_afc")
    doc["topology"]["commit_hold"] = False
    # t_commit_hold is no longer required — but an unused timing row is legal,
    # which is what lets the form grey it instead of deleting a typed value.
    compile_ok(doc, "grgl_2odor")


def test_add_retention_delay():
    doc = load("two_afc")
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
    doc = load("two_afc")
    before = compiler.compile(
        yaml.safe_dump(doc, sort_keys=False), spec_id="two_afc"
    )
    doc["contingency"]["outcome_map"]["correct"]["reward"] = None
    doc["contingency"]["outcome_map"]["correct"].pop("note", None)
    compile_ok(doc, "grgl_2odor")

    after = compiler.compile(yaml.safe_dump(doc, sort_keys=False), spec_id="two_afc")
    assert len(after.table.nodes) < len(before.table.nodes)


def test_rewarding_needs_a_line_on_the_matching_well():
    """TG224, pinned: the op filters reward-line options to lines whose `well`
    IS the port's channel, so this mistake is unreachable from the UI. It is
    still worth pinning that the compiler catches it — the filter is a
    convenience, the rule is the guarantee."""
    doc = load("two_afc")
    # fluid_0 is plumbed to the LEFT well; give it to the right one.
    doc["contingency"]["ports"]["right_well"]["reward_line"] = "fluid_0"
    result = compiler.compile(yaml.safe_dump(doc, sort_keys=False), spec_id="two_afc")
    codes = {d.code for d in list(result.bag) if d.severity.name == "ERROR"}
    assert "TG224" in codes


# --------------------------------------------------------------------------- #
# addStimulus / addTrialType
# --------------------------------------------------------------------------- #


def test_add_stimulus_and_trial_type():
    doc = load("two_afc")
    doc["contingency"]["stimuli"].append(
        {"id": "odor2", "emitter": "odor_line_2", "on_code": "ODOR_2_ON"}
    )
    doc["contingency"]["trial_types"].append(
        {"id": "tt3", "stages": ["odor2"], "target": "right_well", "weight": 1}
    )
    compile_ok(doc, "grgl_2odor")


# --------------------------------------------------------------------------- #
# Removing a trial type: the CONTEXT SCHEDULE is the half that is easy to
# forget. `contingency.context_schedule[].targets` is keyed by trial type id,
# so deleting the row alone leaves a reversal pointing at nothing.
# --------------------------------------------------------------------------- #


def remove_trial_type(doc: dict, tt_id: str) -> None:
    """`removeTrialType`, mirrored."""
    types = doc["contingency"]["trial_types"]
    assert len(types) > 1, "the pool must not empty -- the op refuses the last one"
    doc["contingency"]["trial_types"] = [t for t in types if t["id"] != tt_id]
    for row in doc["contingency"].get("context_schedule") or []:
        row.get("targets", {}).pop(tt_id, None)


def test_removing_a_trial_type_cleans_every_context_row():
    """The cleanup, asserted on the DOCUMENT rather than through a compile.

    A context schedule cannot be compiled at all today: TG230 refuses any block
    boundary because the v1 table has no way to represent one, and says so
    rather than dropping it silently (v2 will). So there is no compiling spec
    that exercises this, and pinning it here is the only place the rule is
    written down outside `operations.ts` itself.

    It is still worth pinning, because the failure it prevents outlives the
    limitation: `targets` is keyed BY TRIAL TYPE ID, so a delete that touches
    only `trial_types` leaves a reversal naming something that no longer
    exists — and it will start compiling, and start being wrong, the day v2
    lands.
    """
    doc = load("two_afc")
    ids = [t["id"] for t in doc["contingency"]["trial_types"]]
    assert len(ids) >= 2

    doc["contingency"]["context_schedule"] = [
        {
            "at_trial": 0,
            "context": "acquisition",
            "targets": {ids[0]: "left_well", ids[1]: "right_well"},
        },
        {
            "at_trial": 50,
            "context": "reversal",
            "targets": {ids[0]: "right_well", ids[1]: "left_well"},
        },
    ]

    remove_trial_type(doc, ids[0])

    for row in doc["contingency"]["context_schedule"]:
        assert ids[0] not in row["targets"], "a reversal still names the deleted type"
        assert ids[1] in row["targets"], "the surviving type lost its override"
    assert len(doc["contingency"]["context_schedule"]) == 2, "rows were dropped, not cleaned"

    # And with the (currently uncompilable) schedule removed, what is left is a
    # task that really does compile.
    del doc["contingency"]["context_schedule"]
    compile_ok(doc, "two_afc")


def test_removing_a_trial_type_that_no_schedule_names_is_still_fine():
    """The common case: no context schedule at all, so there is nothing to clean."""
    doc = load("two_afc")
    ids = [t["id"] for t in doc["contingency"]["trial_types"]]
    remove_trial_type(doc, ids[0])
    assert doc["contingency"].get("context_schedule") in (None, [])
    compile_ok(doc, "two_afc")


# --------------------------------------------------------------------------- #
# Removing a stimulus: blocked while a stage still names it, because the repair
# is a CHOICE (drop the trial type, or re-point the stage) the op cannot make.
# --------------------------------------------------------------------------- #


def test_a_stimulus_a_trial_type_still_presents_cannot_be_dropped():
    """The negative case, and the reason the op refuses rather than cascading.

    Deleting the stimulus and leaving the stage is exactly TG220 — a reference
    to something that no longer exists. This asserts the compiler really does
    reject it, so the block in `removeStimulus` is protecting against a real
    failure rather than being defensive.
    """
    doc = load("two_afc")
    stim = doc["contingency"]["stimuli"][0]["id"]
    users = [
        t["id"] for t in doc["contingency"]["trial_types"] if stim in t.get("stages", [])
    ]
    assert users, "the fixture must have a trial type presenting this stimulus"

    doc["contingency"]["stimuli"] = [
        s for s in doc["contingency"]["stimuli"] if s["id"] != stim
    ]
    result = compiler.compile(yaml.safe_dump(doc, sort_keys=False), spec_id="two_afc")
    errors = [d for d in list(result.bag) if d.severity.name == "ERROR"]
    assert errors, "dropping a presented stimulus must not compile"


def test_a_stimulus_nothing_presents_can_be_dropped():
    doc = load("two_afc")
    doc["contingency"]["stimuli"].append(
        {"id": "odor_spare", "emitter": "odor_line_3", "on_code": "ODOR_3_ON"}
    )
    compile_ok(doc, "two_afc")
    doc["contingency"]["stimuli"] = [
        s for s in doc["contingency"]["stimuli"] if s["id"] != "odor_spare"
    ]
    compile_ok(doc, "two_afc")


# --------------------------------------------------------------------------- #
# Adding a response option: a correction budget is EXTENDED, never invented.
# --------------------------------------------------------------------------- #


def add_response_option(doc: dict, name: str, channel: str) -> None:
    """`addResponseOption`, in the one respect this file is about.

    The strobe codes and reward binding the real op fills in are set literally
    here — TG506's per-port coverage has its own case above. What is mirrored
    is the correction-budget rule, because it is the one that decides whether a
    field appears in the document at all.
    """
    doc["contingency"]["ports"][name] = {
        "channel": channel,
        "enter_code": "WATER_POKE_L",
        "error_code": "WATER_POKE_ERROR_L",
        "break_code": "WATER_UNPOKE_EARLY_L",
        "exit_code": "WATER_UNPOKE_L",
        "reward_line": "fluid_0",
        "reward_duration": "t_reward_left",
        "reward_code": "FLUID_L",
        "reward_stop_code": "STOP_FLUID_G_L",
    }
    doc["topology"]["response_ports"].append(name)
    doc["timing"].append({"id": "t_reward_left", "ms": 100})

    # THE RULE: extend a budgets map that exists; do not create one.
    budgets = (doc.get("policy", {}).get("correction") or {}).get("budgets")
    if budgets is not None:
        budgets[name] = 0


def test_adding_a_port_does_not_invent_a_correction_policy():
    """`blank` declares no correction budgets, so a task grown from it has none.

    Writing `policy.correction.budgets.<new port>` unconditionally produced a
    block holding exactly one entry — the port just added — which reads as a
    deliberate zero for that well and an unstated default for the well that was
    already there. A task that does not run correction trials should come out
    of the wizard with no correction block at all.
    """
    doc = load("blank")
    assert "correction" not in (doc.get("policy") or {})

    add_response_option(doc, "left_well", "left_well")
    doc["contingency"]["stimuli"].append(
        {"id": "odor2", "emitter": "odor_line_2", "on_code": "ODOR_2_ON"}
    )
    doc["contingency"]["trial_types"].append(
        {"id": "tt_odor2_left", "stages": ["odor2"], "target": "left_well", "weight": 1}
    )

    assert "correction" not in (doc.get("policy") or {})
    compile_ok(doc, "grown_from_blank")


def test_adding_a_port_extends_an_existing_correction_policy():
    """Where the block DOES exist, a port missing from it is the asymmetry."""
    doc = load("two_afc")
    budgets = doc["policy"]["correction"]["budgets"]
    assert set(budgets) == set(doc["topology"]["response_ports"])

    # Free the channel the third port will take, so the mirror stays honest
    # about there being one — `channels.v1.json` declares two response kinds
    # today, which is the wall `capabilities()` computes rather than declares.
    doc["contingency"]["ports"]["third_well"] = dict(
        doc["contingency"]["ports"]["left_well"]
    )
    doc["topology"]["response_ports"].append("third_well")
    budgets["third_well"] = 0

    assert set(budgets) == set(doc["topology"]["response_ports"])


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
    "spec_id", ["two_afc", "two_afc_unrewarded", "shaping", "go_nogo", "seq2_retention",
     "seq3_retention", "shaping_no_stimulus"]
)
def test_paradigm_skeleton_compiles(spec_id: str):
    compile_ok(copy.deepcopy(load(spec_id)), spec_id)


# --------------------------------------------------------------------------- #
# setStageTrial — moving a ramp boundary
# --------------------------------------------------------------------------- #
#
# The op re-sorts because TG205 wants rows ascending by `at_trial`, and an
# out-of-order schedule is the dangerous kind of wrong: the board applies the
# LATEST row whose count has been reached, so the wrong values arrive and
# nothing reports it. The mirror below is the same sort the TS op does.


def set_stage_trial(doc: dict, index: int, at_trial: int) -> None:
    rows = sorted(
        doc["policy"]["stage_schedule"], key=lambda r: int(r.get("at_trial", 0))
    )
    if any(int(r.get("at_trial", 0)) == at_trial for i, r in enumerate(rows) if i != index):
        raise AssertionError(f"collision at trial {at_trial}")
    rows[index] = {**rows[index], "at_trial": at_trial}
    doc["policy"]["stage_schedule"] = sorted(
        rows, key=lambda r: int(r.get("at_trial", 0))
    )


def _ramp(doc: dict, ids: list[str], boundaries: list[int]) -> None:
    """What the wizard's ramp step builds: every row carries every id."""
    base = {i["id"]: i["ms"] for i in doc["timing"]}
    doc["policy"]["stage_schedule"] = [
        {"at_trial": at, "set": {i: base[i] for i in ids}} for at in boundaries
    ]


def test_moving_a_boundary_keeps_the_schedule_ascending():
    doc = load("shaping")
    _ramp(doc, ["t_commit_hold", "t_sample_hold"], [0, 25, 50])

    # Push the FIRST row past the last one. Typed in isolation this is exactly
    # how a schedule ends up descending.
    set_stage_trial(doc, 0, 90)

    ats = [int(r["at_trial"]) for r in doc["policy"]["stage_schedule"]]
    assert ats == sorted(ats) == [25, 50, 90]
    compile_ok(doc, "shaping")


def test_a_descending_schedule_is_rejected_by_the_compiler():
    """The rule the sort exists to satisfy — proving it is real, not folklore."""
    doc = load("shaping")
    _ramp(doc, ["t_commit_hold"], [0, 25, 50])
    doc["policy"]["stage_schedule"][0]["at_trial"] = 90  # no re-sort

    result = compiler.compile(yaml.safe_dump(doc, sort_keys=False), spec_id="shaping")
    codes = {d.code for d in list(result.bag) if d.severity.name == "ERROR"}
    assert "TG205" in codes


def test_moving_a_boundary_onto_another_is_refused():
    doc = load("shaping")
    _ramp(doc, ["t_commit_hold"], [0, 25, 50])
    with pytest.raises(AssertionError):
        set_stage_trial(doc, 0, 25)


def test_the_ramp_the_wizard_builds_compiles_and_every_row_is_total():
    """TG507: a row that omits a ramped id does not leave it alone.

    The five-duration, five-boundary shape is the lab's real shaping ramp, and
    it is the case the wizard's `setRampedIds` fills in for every row at once.
    """
    doc = load("shaping")
    ids = ["t_engage_win", "t_commit_hold", "t_sample_hold", "t_resp_win", "t_resp_hold"]
    _ramp(doc, ids, [0, 20, 25, 50, 100])
    compile_ok(doc, "shaping")

    assert all(set(r["set"]) == set(ids) for r in doc["policy"]["stage_schedule"])

    # And the negative: drop one id from one row and the compiler says so.
    doc["policy"]["stage_schedule"][2]["set"].pop("t_resp_win")
    result = compiler.compile(yaml.safe_dump(doc, sort_keys=False), spec_id="shaping")
    codes = {d.code for d in list(result.bag) if d.severity.name == "ERROR"}
    assert "TG507" in codes

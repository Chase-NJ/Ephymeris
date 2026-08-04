"""Phase 0 gate: every hand-authored spec validates, and every cross-reference resolves.

These are NOT the Phase 1 graph linter -- there is no compiler yet, so nothing here
walks a graph. They check the properties the schema alone can guarantee, plus the
referential integrity that makes the schema worth freezing:

  * every spec validates against schema/task_spec.v1.json
  * every strobe NAME resolves against the append-only vocabulary
  * every timing reference resolves against that spec's own timing vector
  * every port / stimulus / trial-type reference resolves
  * stages[] length == topology.n_sampling_stages
  * the shaping _EZ variant differs from its parent in LAYER 3 ONLY

The last one is the roadmap's layer-3 claim, asserted as a test rather than a comment.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, all_specs, spec as spec_path,
)

SCHEMA = json.loads((SCHEMA_DIR / "task_spec.v1.json").read_text())
VOCAB = json.loads((SCHEMA_DIR / "strobe_vocab.v1.json").read_text())

SPEC_FILES = all_specs()
BINDING_RE = re.compile(r"^@")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


@pytest.fixture(params=SPEC_FILES, ids=lambda p: p.stem)
def spec(request) -> dict:
    return load(request.param)


def test_every_paradigm_generates_a_file():
    """Nothing ships as a spec, so what this suite validates is what the wizard
    produces. A paradigm that stopped generating would empty this whole module
    rather than failing one case -- hence the explicit floor."""
    from ephymeris_sidecar.taskgraph import paradigms

    assert {p.stem for p in SPEC_FILES} == {p.id for p in paradigms.load_all()}
    assert len(SPEC_FILES) >= 7


def test_validates_against_schema(spec):
    errors = sorted(Draft202012Validator(SCHEMA).iter_errors(spec), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def _walk_strobes(spec):
    """Yield every strobe-shaped value in the spec."""
    for stim in spec["contingency"].get("stimuli", []):
        yield stim["on_code"]
    for port in spec["contingency"]["ports"].values():
        for key in ("enter_code", "error_code", "break_code", "exit_code",
                    "reward_code", "reward_stop_code"):
            if key in port:
                yield port[key]
    for outcome in spec["contingency"]["outcome_map"].values():
        if "strobe" in outcome:
            yield outcome["strobe"]


def test_strobe_names_resolve(spec):
    """A literal strobe name must exist in the append-only vocabulary.

    Catches the failure mode Ephymeris docs/tasks.md:207-213 records: a code that is
    emitted but never declared degrades silently at every layer.
    """
    for value in _walk_strobes(spec):
        if value is None or BINDING_RE.match(value or ""):
            continue
        assert value in VOCAB["codes"], f"undeclared strobe {value!r}"


def test_strobe_codes_are_wire_representable():
    """emitStrobe formats %03d and the host regex is ^\\d{1,3}\\t\\d+$ -- so >999 is
    unparseable and silently dropped. Five codes already exceed 255, which is why the
    compiled table uses uint16 (docs/decisions.md D5)."""
    for name, entry in VOCAB["codes"].items():
        assert 0 <= entry["code"] <= 999, f"{name} = {entry['code']} is not wire-representable"


def test_strobe_codes_are_unique():
    """Append-only means a code is never reused. A duplicate is a repurposing bug."""
    seen: dict[int, str] = {}
    for name, entry in VOCAB["codes"].items():
        code = entry["code"]
        assert code not in seen, f"{name} reuses code {code} (already {seen[code]})"
        seen[code] = name


def test_every_declared_code_has_a_rationale():
    for name, entry in VOCAB["codes"].items():
        assert entry.get("rationale"), f"{name} has no rationale"


def test_timing_ids_unique_and_referenced(spec):
    ids = [t["id"] for t in spec["timing"]]
    assert len(ids) == len(set(ids)), "duplicate timing id"
    assert "t_zero" in ids, "t_zero is required: zero-duration nodes carry paired strobes"

    known = set(ids)
    for outcome in spec["contingency"]["outcome_map"].values():
        assert outcome["delay"] in known, f"unresolved timing ref {outcome['delay']!r}"
    for port in spec["contingency"]["ports"].values():
        if "reward_duration" in port:
            assert port["reward_duration"] in known
    for row in spec.get("policy", {}).get("stage_schedule", []):
        for ref in row["set"]:
            assert ref in known, f"stage_schedule rewrites unknown timing id {ref!r}"


def test_stage_count_matches_bindings(spec):
    """stages[] length must equal n_sampling_stages -- the constraint that makes
    @stim[$stage] resolvable for every trial type."""
    n = spec["topology"]["n_sampling_stages"]
    for tt in spec["contingency"]["trial_types"]:
        assert len(tt["stages"]) == n, f"{tt['id']}: {len(tt['stages'])} stages, expected {n}"


def test_references_resolve(spec):
    stimuli = {s["id"] for s in spec["contingency"].get("stimuli", [])}
    ports = set(spec["contingency"]["ports"])

    for p in spec["topology"]["response_ports"]:
        assert p in ports, f"response_ports names undeclared port {p!r}"

    for tt in spec["contingency"]["trial_types"]:
        for stage in tt["stages"]:
            assert stage in stimuli, f"{tt['id']} references undeclared stimulus {stage!r}"
        if tt.get("target") is not None:
            assert tt["target"] in ports, f"{tt['id']} targets undeclared port {tt['target']!r}"

    for row in spec["contingency"].get("context_schedule", []):
        known_tt = {t["id"] for t in spec["contingency"]["trial_types"]}
        for tt_id, target in row["targets"].items():
            assert tt_id in known_tt
            assert target is None or target in ports


def test_stage_schedule_is_ordered(spec):
    """Rows are scanned descending with >=, so a spec that lists them out of order is
    readable-but-wrong. Require ascending at_trial (BehaviorBox.h:551-562)."""
    rows = spec.get("policy", {}).get("stage_schedule", [])
    counts = [r["at_trial"] for r in rows]
    assert counts == sorted(counts), "stage_schedule must be in ascending at_trial order"
    assert len(counts) == len(set(counts)), "duplicate at_trial in stage_schedule"


def test_gonogo_inverts_timeout_without_a_special_case():
    """The load-bearing property of the go/no-go design: TIMEOUT scores CORRECT, and
    that is expressed purely as an edge effect in the outcome map."""
    spec = load(spec_path("go_nogo"))
    outcomes = spec["contingency"]["outcome_map"]

    assert outcomes["correct"]["trigger"] == "TIMEOUT"
    assert outcomes["correct"]["terminal"] == "TRIAL_CORRECT"
    assert outcomes["false_alarm"]["trigger"] == "ENTER"

    # The states that must NOT be in the spine.
    assert "omission" not in outcomes, "window expiry is the correct outcome, not an omission"
    assert "hold_fail" not in outcomes, "there is no response hold to fail"
    assert all(o.get("reward") is None for o in outcomes.values()), "a withhold task rewards nothing"

    # Reward states are removed by ABSENCE of a binding, never by a flag.
    for port in spec["contingency"]["ports"].values():
        assert "reward_line" not in port

    # And the contrast: an n-alternative task scores the same trigger as an omission.
    grgl = load(spec_path("two_afc"))
    assert grgl["contingency"]["outcome_map"]["omission"]["trigger"] == "TIMEOUT"
    assert grgl["contingency"]["outcome_map"]["omission"]["terminal"] == "TRIAL_INCORRECT"


def test_omission_announces_itself():
    """Every target spec emits RESP_OMIT rather than nothing.

    Silence was a firmware accommodation. Firmware conforms to the model now, so
    the accommodation is gone -- see docs/decisions.md D21 and D4's amendment.
    """
    for name in ("two_afc", "two_afc_unrewarded", "shaping", "seq2_retention",
                 "seq3_retention", "shaping_no_stimulus"):
        spec = load(spec_path(name))
        assert spec["contingency"]["outcome_map"]["omission"]["strobe"] == "RESP_OMIT"


def test_target_specs_pin_the_current_template():
    """A spec left on v1 would silently keep the accommodations v2 removed."""
    for path in SPEC_FILES:
        spec = load(path)
        assert spec["topology"]["template_version"] == 2, f"{path.stem} is still on v1"


def test_two_tasks_from_one_paradigm_are_the_same_machine():
    """THE LAYER-3 CLAIM, restated for a world with no shipped variants.

    It used to be checked between shaping_gr and shaping_gr_ez: "eased and
    standard variants differ only in the timing vector". Those files are gone,
    but the claim is the paradigm's own property now and matters more, because
    it is what makes Shaping-R and Shaping-L one task with one history rather
    than two: answering a paradigm differently must move values, never the
    graph.
    """
    from ephymeris_sidecar.taskgraph import paradigms

    p = paradigms.get("shaping")
    right = paradigms.skeleton(p, spec_id="shaping_r", answers={"rewarded_arm": "right_well"})
    left = paradigms.skeleton(p, spec_id="shaping_l", answers={"rewarded_arm": "left_well"})

    assert right["topology"] == left["topology"], "an answer must not change the graph"
    assert right["timing"] == left["timing"]
    assert right["contingency"] != left["contingency"], (
        "the two must differ somewhere, or they are not different tasks"
    )
    targets = [
        [t["target"] for t in d["contingency"]["trial_types"] if t.get("weight") == 1]
        for d in (right, left)
    ]
    assert targets == [["right_well"], ["left_well"]]

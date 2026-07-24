"""Task Profiles — `data-saving.md` §6."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ephymeris_sidecar.tasks.metrics import MetricSet, compute_series
from ephymeris_sidecar.tasks.profile import (
    TaskProfileError,
    load_profile,
    parse_profile,
)
from ephymeris_sidecar.tasks.start_command import build_start_command

# The exact task.json the user supplied for GRGL_2-Odor.
GRGL = {
    "taskName": "GRGL 2-Odor Discrimination",
    "config": [
        {"metadataKey": "correction_left", "wireKey": "CL", "label": "Left correction budget", "type": "int", "default": 0},
        {"metadataKey": "correction_right", "wireKey": "CR", "label": "Right correction budget", "type": "int", "default": 0},
        {"metadataKey": "lazy_escalation", "wireKey": "LAZY", "label": "Escalating lazy penalty", "type": "bool", "default": True},
    ],
    "strobes": {"101": "ODOR_1_ON", "103": "ODOR_3_ON", "248": "WATER_POKE_L", "249": "WATER_POKE_R", "246": "END_SESSION"},
    "liveMetrics": [
        {"id": "p_r_odor1", "label": "P(R | Odor 1)", "triggerCode": 101, "successCode": 249, "alternateCode": 248, "windowSize": 20},
        {"id": "p_l_odor3", "label": "P(L | Odor 3)", "triggerCode": 103, "successCode": 248, "alternateCode": 249, "windowSize": 20},
    ],
}


# --- §6.1 discovery -------------------------------------------------------


def test_a_sketch_without_a_task_json_is_profile_less(tmp_path: Path) -> None:
    """§6.1 — fully supported, not an error."""
    (tmp_path / "clean_flush.ino").write_text("void setup(){}")
    assert load_profile(tmp_path) is None


def test_a_sketch_with_a_task_json_loads_it(tmp_path: Path) -> None:
    (tmp_path / "GRGL_2-Odor.ino").write_text("void setup(){}")
    (tmp_path / "task.json").write_text(json.dumps(GRGL))
    profile = load_profile(tmp_path)
    assert profile is not None
    assert profile.task_name == "GRGL 2-Odor Discrimination"
    assert len(profile.config) == 3
    assert len(profile.live_metrics) == 2


def test_a_malformed_task_json_raises_rather_than_silently_dropping(tmp_path: Path) -> None:
    (tmp_path / "task.json").write_text("{ not valid json")
    with pytest.raises(TaskProfileError):
        load_profile(tmp_path)


# --- §6.2 parsing ---------------------------------------------------------


def test_the_supplied_grgl_profile_round_trips_to_json() -> None:
    profile = parse_profile(GRGL)
    out = profile.to_json()
    assert out["taskName"] == GRGL["taskName"]
    assert out["config"] == GRGL["config"]
    # Strobe keys stay strings on the wire, matching the authored file.
    assert out["strobes"]["101"] == "ODOR_1_ON"


def test_missing_task_name_is_rejected() -> None:
    with pytest.raises(TaskProfileError):
        parse_profile({"config": []})


def test_unknown_config_type_is_rejected() -> None:
    with pytest.raises(TaskProfileError):
        parse_profile({"taskName": "X", "config": [{"metadataKey": "k", "wireKey": "W", "type": "colour"}]})


def test_empty_sections_default_cleanly() -> None:
    profile = parse_profile({"taskName": "Utility"})
    assert profile.config == []
    assert profile.live_metrics == []
    assert profile.strobes == {}


# --- §6.6 utility profiles (kind + controls + telemetry) -----------------

# The exact task.json the user supplied for PRIME_Lines.
PRIME_LINES = {
    "taskName": "Prime Lines (latch)",
    "kind": "utility",
    "controls": [
        {"id": "gear", "label": "Fluid set", "type": "select", "options": [
            {"label": "Set 1", "command": "SET GEAR=1"},
            {"label": "Set 2", "command": "SET GEAR=2"},
        ]},
        {"id": "toggle_l", "label": "Toggle L", "type": "button", "command": "TOGGLE L"},
        {"id": "alloff", "label": "All off", "type": "button", "command": "ALLOFF"},
    ],
    "telemetry": {
        "match": "STATUS",
        "fields": [
            {"key": "gear", "label": "Fluid set"},
            {"key": "left", "label": "Left line"},
            {"key": "right", "label": "Right line"},
        ],
    },
}


def test_kind_defaults_to_behavior_when_absent() -> None:
    assert parse_profile({"taskName": "X"}).kind == "behavior"


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(TaskProfileError):
        parse_profile({"taskName": "X", "kind": "gadget"})


def test_a_behavior_profile_has_no_controls_or_telemetry() -> None:
    profile = parse_profile(GRGL)
    assert profile.kind == "behavior"
    assert profile.controls == []
    assert profile.telemetry is None
    # to_json still carries an (empty) controls list and omits telemetry.
    out = profile.to_json()
    assert out["kind"] == "behavior"
    assert out["controls"] == []
    assert "telemetry" not in out


def test_a_utility_profile_round_trips_to_json() -> None:
    profile = parse_profile(PRIME_LINES)
    assert profile.kind == "utility"
    out = profile.to_json()
    assert out["kind"] == "utility"
    # A select control keeps its options; a button keeps its command.
    gear, toggle_l, alloff = out["controls"]
    assert gear["type"] == "select"
    assert gear["options"][0] == {"label": "Set 1", "command": "SET GEAR=1"}
    assert toggle_l == {"id": "toggle_l", "label": "Toggle L", "type": "button", "command": "TOGGLE L"}
    assert alloff["command"] == "ALLOFF"
    assert out["telemetry"]["match"] == "STATUS"
    assert {f["key"] for f in out["telemetry"]["fields"]} == {"gear", "left", "right"}


def test_button_control_requires_a_command() -> None:
    with pytest.raises(TaskProfileError):
        parse_profile({"taskName": "X", "kind": "utility",
                       "controls": [{"id": "go", "type": "button"}]})


def test_select_control_requires_non_empty_options() -> None:
    with pytest.raises(TaskProfileError):
        parse_profile({"taskName": "X", "kind": "utility",
                       "controls": [{"id": "g", "type": "select", "options": []}]})


def test_unknown_control_type_is_rejected() -> None:
    with pytest.raises(TaskProfileError):
        parse_profile({"taskName": "X", "kind": "utility",
                       "controls": [{"id": "g", "type": "slider", "command": "X"}]})


def test_telemetry_match_defaults_to_STATUS() -> None:
    profile = parse_profile({"taskName": "X", "kind": "utility", "telemetry": {"fields": []}})
    assert profile.telemetry is not None
    assert profile.telemetry.match == "STATUS"


def test_a_utility_profile_gets_a_bare_start_command() -> None:
    # Utility sketches aren't scored tasks; the builder still yields bare START
    # if one is ever sent (they're driven via passthrough, not startSession).
    assert build_start_command(parse_profile(PRIME_LINES), {}) == "START"


# --- §6.3 START command builder ------------------------------------------


def test_start_command_uses_wire_keys_and_defaults() -> None:
    profile = parse_profile(GRGL)
    # No overrides → every field falls back to its declared default.
    cmd = build_start_command(profile, {})
    assert cmd == "START CL=0 CR=0 LAZY=1"


def test_start_command_applies_overrides_by_metadata_key() -> None:
    profile = parse_profile(GRGL)
    cmd = build_start_command(profile, {"correction_left": 5, "lazy_escalation": False})
    assert cmd == "START CL=5 CR=0 LAZY=0"


def test_bools_render_as_one_and_zero_not_true_false() -> None:
    profile = parse_profile(GRGL)
    assert "LAZY=1" in build_start_command(profile, {"lazy_escalation": True})
    assert "LAZY=0" in build_start_command(profile, {"lazy_escalation": False})


def test_unknown_config_keys_are_ignored() -> None:
    """§6.3 — stale UI state can't leak unknown tokens onto the wire."""
    profile = parse_profile(GRGL)
    cmd = build_start_command(profile, {"correction_left": 3, "not_a_field": 99})
    assert "not_a_field" not in cmd
    assert "99" not in cmd


def test_a_profile_less_sketch_gets_bare_start() -> None:
    assert build_start_command(None, {}) == "START"
    assert build_start_command(parse_profile({"taskName": "Utility"}), {}) == "START"


# --- §6.5 live metric computation (the scientific output) ----------------

# GRGL codes: 101 = Odor 1 on, 103 = Odor 3 on, 249 = water poke R, 248 = water poke L.
# Metric p_r_odor1: trigger 101, success 249 (went right), alternate 248 (went left).


def metric(profile_json=GRGL, index=0):
    return parse_profile(profile_json).live_metrics[index]


def test_a_hit_is_a_response_at_the_success_well() -> None:
    m = metric()
    # 101 → 249: went right after odor 1 → hit → P = 1.0
    assert compute_series(m, [101, 249]) == [1.0]


def test_a_miss_is_a_response_at_the_other_well() -> None:
    m = metric()
    # 101 → 248: went left after odor 1 → miss → P = 0.0, still counted
    assert compute_series(m, [101, 248]) == [0.0]


def test_a_no_response_trial_is_excluded_entirely() -> None:
    m = metric()
    # 101 → odor off, stream ends with no water poke → excluded, no data point.
    # (The odor-3-boundary variant is covered separately below, since a single
    # metric in isolation only knows its own trigger as a boundary — the union
    # of triggers is what MetricSet supplies live.)
    assert compute_series(m, [101, 247]) == []


def test_intervening_non_response_codes_do_not_end_the_trial() -> None:
    m = metric()
    # 101 … 247 (odor off) … 224 (odor poke) … 249: still a hit, unrelated codes ignored
    assert compute_series(m, [101, 247, 224, 249]) == [1.0]


def test_rolling_probability_tracks_the_window() -> None:
    m = metric()
    # hit, hit, miss, hit → 1.0, 1.0, 0.667, 0.75
    series = compute_series(m, [101, 249, 101, 249, 101, 248, 101, 249])
    assert series[0] == 1.0
    assert series[1] == 1.0
    assert round(series[2], 3) == 0.667
    assert series[3] == 0.75


def test_the_window_only_covers_the_last_n_counted_trials() -> None:
    profile = {**GRGL, "liveMetrics": [{**GRGL["liveMetrics"][0], "windowSize": 2}]}
    m = metric(profile)
    # window=2: after miss,hit,hit the window holds the last two (hit,hit) → 1.0
    series = compute_series(m, [101, 248, 101, 249, 101, 249])
    assert series[-1] == 1.0


def test_two_metrics_score_independently_from_one_stream() -> None:
    """Interleaved odor-1 and odor-3 trials update their own metrics only."""
    metric_set = MetricSet(parse_profile(GRGL))
    # Odor 1 → right (hit for p_r_odor1); Odor 3 → left (hit for p_l_odor3)
    for code in [101, 249, 103, 248]:
        values = metric_set.offer(code)
    by_id = {v.id: v for v in values}
    assert by_id["p_r_odor1"].value == 1.0
    assert by_id["p_r_odor1"].n == 1
    assert by_id["p_l_odor3"].value == 1.0
    assert by_id["p_l_odor3"].n == 1


def test_an_odor3_onset_ends_an_unresolved_odor1_trial() -> None:
    """The union of trigger codes forms the trial boundary set (§6.5)."""
    m = metric()  # p_r_odor1, boundaries = {101, 103}
    boundaries = frozenset({101, 103})
    # 101 (odor1) then 103 (odor3) with no water poke → odor1 trial excluded
    assert compute_series(m, [101, 103, 248], boundaries) == []


def test_a_profile_less_metric_set_is_empty() -> None:
    metric_set = MetricSet(None)
    assert metric_set.empty
    assert metric_set.offer(101) == []

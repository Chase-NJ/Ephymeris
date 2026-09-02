"""Task Profiles — `tasks.md` §3."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ephymeris_sidecar.tasks.metrics import MetricSet, compute_series
from ephymeris_sidecar.tasks.profile import (
    TaskProfileError,
    build_legacy_name_index,
    load_profile,
    parse_profile,
)
from ephymeris_sidecar.tasks.start_command import START_LINE_MAX, build_start_command

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
    (tmp_path / "clean_flush.ino").write_text("void setup(){}", encoding="utf-8")
    assert load_profile(tmp_path) is None


def test_a_sketch_with_a_task_json_loads_it(tmp_path: Path) -> None:
    (tmp_path / "GRGL_2-Odor.ino").write_text("void setup(){}", encoding="utf-8")
    (tmp_path / "task.json").write_text(json.dumps(GRGL), encoding="utf-8")
    profile = load_profile(tmp_path)
    assert profile is not None
    assert profile.task_name == "GRGL 2-Odor Discrimination"
    assert len(profile.config) == 3
    assert len(profile.live_metrics) == 2


def test_a_malformed_task_json_raises_rather_than_silently_dropping(tmp_path: Path) -> None:
    (tmp_path / "task.json").write_text("{ not valid json", encoding="utf-8")
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


def test_every_shipped_profile_keeps_its_hash_through_a_round_trip() -> None:
    """THE IDENTITY A COPIED SESSION FILE DEPENDS ON (`data.md` §4.4).

    A run's file carries its profile as JSON; the machine that reads it parses
    that back and re-serializes to hash it. If the pair is not exactly
    reversible, a copied run lands under a different `profile_hash` than the
    run it came from — a separate profile group, a separate comparability set,
    and no error anywhere. Anything added to `TaskProfile` has to keep this
    true.
    """
    from ephymeris_sidecar.taskdef import generate
    from ephymeris_sidecar.tasks.profile import profile_hash
    from tests.fixtures import task_definitions as presets

    for preset in presets.PRESETS:
        definition = presets.instantiate(preset["id"], preset["id"])
        original = generate.build_profile(definition)
        # Through the wire form and back, exactly as a session file does it.
        copied = parse_profile(json.loads(json.dumps(original.to_json())))
        assert profile_hash(copied) == profile_hash(original), preset["id"]
        assert copied.to_json() == original.to_json(), preset["id"]


def test_a_document_that_carries_no_snapshot_yields_none() -> None:
    """`embedded_profile` is a reader of untrusted files: a profile-less
    sketch, an archive predating the field, and a damaged snapshot all mean
    "no declaration here" rather than an exception — the strobes below it are
    still real data."""
    from ephymeris_sidecar.tasks.profile import SNAPSHOT_KEY, embedded_profile

    assert embedded_profile({}) is None
    assert embedded_profile({SNAPSHOT_KEY: "GRGL"}) is None
    assert embedded_profile({SNAPSHOT_KEY: {"config": []}}) is None  # no taskName
    assert embedded_profile({SNAPSHOT_KEY: GRGL}) is not None


def test_recorded_config_is_the_declared_fields_and_nothing_else() -> None:
    """Which of a document's flat fields are PARAMETERS is a question only the
    profile answers. `trial_seed` and `host_seed` sit right beside them and are
    deliberately not declared fields — they describe the run, not its tuning,
    and the recording side never hashed them either."""
    from ephymeris_sidecar.tasks.profile import recorded_config

    profile = parse_profile(GRGL)
    keys = {field.metadata_key for field in profile.config}
    assert keys, "the fixture needs at least one declared field to test with"
    document = {
        "rat": "remy1",
        "trial_seed": 288577176,
        "host_seed": 288577176,
        **{key: 7 for key in keys},
    }
    assert recorded_config(document, profile) == {key: 7 for key in keys}
    # No profile means no way to tell a parameter from a core field.
    assert recorded_config(document, None) is None


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


# --- grid controls (§6.6) --------------------------------------------------

GRID_PROFILE = {
    "taskName": "Box Utility",
    "kind": "utility",
    "controls": [
        {
            "id": "fluids",
            "label": "Fluid lines",
            "type": "grid",
            "channels": [
                {"label": "Left 1", "state": "f1", "toggle": "TOGGLE F1", "pulse": "PULSE F1"},
                {"label": "Right 1", "state": "f3", "toggle": "TOGGLE F3"},
            ],
        }
    ],
}


def test_grid_control_round_trips_to_json() -> None:
    profile = parse_profile(GRID_PROFILE)
    control = profile.controls[0]
    assert control.type == "grid"
    assert [c.label for c in control.channels] == ["Left 1", "Right 1"]
    assert control.channels[0].pulse == "PULSE F1"
    # A channel that declares no pulse omits the key rather than sending null.
    out = profile.to_json()["controls"][0]
    assert out["channels"][0] == {
        "label": "Left 1",
        "state": "f1",
        "toggle": "TOGGLE F1",
        "pulse": "PULSE F1",
    }
    assert "pulse" not in out["channels"][1]
    # Re-parsing the emitted JSON reproduces it exactly — the shape the sidecar
    # snapshots for a run is the shape it can decode again years later.
    assert parse_profile(profile.to_json()).to_json() == profile.to_json()


def test_grid_control_requires_channels() -> None:
    with pytest.raises(TaskProfileError):
        parse_profile({"taskName": "X", "kind": "utility",
                       "controls": [{"id": "g", "type": "grid", "channels": []}]})


def test_a_grid_channel_needs_something_to_do() -> None:
    """A row with neither command is inert decoration — a profile bug worth
    naming rather than silently rendering."""
    with pytest.raises(TaskProfileError) as exc:
        parse_profile({"taskName": "X", "kind": "utility",
                       "controls": [{"id": "g", "type": "grid",
                                     "channels": [{"label": "Left 1", "state": "f1"}]}]})
    assert "Left 1" in str(exc.value)


def test_a_grid_channel_needs_a_label() -> None:
    with pytest.raises(TaskProfileError):
        parse_profile({"taskName": "X", "kind": "utility",
                       "controls": [{"id": "g", "type": "grid",
                                     "channels": [{"toggle": "TOGGLE F1"}]}]})


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


# --- §6.7 the legacyNames index -------------------------------------------


class _Sketch:
    """Just the attribute `build_legacy_name_index` reads off a discovered
    sketch, so the index is testable without a whole Application."""

    def __init__(self, path: str) -> None:
        self.path = path


def test_the_legacy_name_index_reads_each_task_json_once() -> None:
    """One read per sketch, not one per question. An adopted archive asks the
    same question for every file it holds."""
    reads: list[str] = []

    def load(path: str):
        reads.append(path)
        return parse_profile({**GRGL, "legacyNames": [f"Shape - {path[-1]}"]})

    index = build_legacy_name_index([_Sketch("a/L"), _Sketch("b/R")], load=load)
    assert index == {"Shape - L": "a/L", "Shape - R": "b/R"}
    assert reads == ["a/L", "b/R"]


def test_the_first_declaration_wins() -> None:
    """Same rule as the picker — discovery order decides a collision."""

    def load(path: str):
        return parse_profile({**GRGL, "legacyNames": ["Shape - L"]})

    index = build_legacy_name_index([_Sketch("first"), _Sketch("second")], load=load)
    assert index == {"Shape - L": "first"}


def test_one_broken_task_json_does_not_hide_the_others() -> None:
    """A single malformed profile must not cost every other sketch its legacy
    names — the index is a lookup table, not a validation pass."""

    def load(path: str):
        if path == "broken":
            raise TaskProfileError("nope")
        if path == "profileless":
            return None
        return parse_profile({**GRGL, "legacyNames": ["Shape - R"]})

    index = build_legacy_name_index(
        [_Sketch("broken"), _Sketch("profileless"), _Sketch("good")], load=load
    )
    assert index == {"Shape - R": "good"}


# --- §6.2 presentation metadata ------------------------------------------


def _field(**overrides: object) -> dict:
    base = {"metadataKey": "odor_poke_hold", "wireKey": "S0P", "label": "Poke hold", "type": "int", "default": 500}
    base.update(overrides)
    return base


def test_presentation_metadata_round_trips() -> None:
    """§6.2 — group/unit/min/max/step/help/advanced ride through to the wire."""
    profile = parse_profile({"taskName": "T", "config": [_field(
        group="Stage 0", unit="ms", min=0, max=5000, step=10,
        help="Hold required before odor delivery.", advanced=True)]})
    field = profile.config[0]
    assert (field.group, field.unit, field.min, field.max, field.step) == ("Stage 0", "ms", 0, 5000, 10)
    assert field.help == "Hold required before odor delivery."
    assert field.advanced is True
    assert profile.to_json()["config"][0]["group"] == "Stage 0"


def test_a_profile_declaring_no_metadata_is_unchanged() -> None:
    """The whole point of making these optional: every profile written before
    they existed must serialize exactly as it did, with no null-valued keys.
    The wire declares them *absent*, not nullable, and the validator enforces
    the difference."""
    emitted = parse_profile(GRGL).to_json()["config"][0]
    assert set(emitted) == {"metadataKey", "wireKey", "label", "type", "default"}


def test_metadata_is_type_checked() -> None:
    for bad in ({"group": 7}, {"unit": ""}, {"min": "0"}, {"step": True}, {"help": 3}):
        with pytest.raises(TaskProfileError):
            parse_profile({"taskName": "T", "config": [_field(**bad)]})


def test_min_above_max_is_rejected() -> None:
    """A range no value can satisfy would make every entry unclampable."""
    with pytest.raises(TaskProfileError, match="min is above max"):
        parse_profile({"taskName": "T", "config": [_field(min=500, max=10)]})


# --- §6.2 the four silent-failure guards ----------------------------------


def test_a_profile_cannot_claim_the_reserved_seed_key() -> None:
    """§6.4 — the app appends SEED itself, so a profile claiming it would put
    two SEED tokens on one line and the firmware would keep whichever parsed
    last. Nothing downstream would report the lost value."""
    with pytest.raises(TaskProfileError, match="reserved wire key"):
        parse_profile({"taskName": "T", "config": [_field(wireKey="SEED")]})


@pytest.mark.parametrize("core", ["rat", "sketch", "session_id", "trial_seed", "n_events"])
def test_a_metadata_key_cannot_collide_with_a_core_field(core: str) -> None:
    """§5 — config is merged into the session file FLAT at the top level, so a
    collision overwrites the core field instead of sitting beside it. A run
    whose `rat` field held a poke-hold duration would be unrecoverable."""
    with pytest.raises(TaskProfileError, match="collides with a core"):
        parse_profile({"taskName": "T", "config": [_field(metadataKey=core)]})


def test_duplicate_keys_are_rejected() -> None:
    """Two entries sharing a key means one silently wins -- on the wire for a
    duplicate wireKey, in the file for a duplicate metadataKey."""
    with pytest.raises(TaskProfileError, match="metadataKey"):
        parse_profile({"taskName": "T", "config": [_field(), _field(wireKey="S1P")]})
    with pytest.raises(TaskProfileError, match="wireKey"):
        parse_profile({"taskName": "T", "config": [_field(), _field(metadataKey="other")]})


@pytest.mark.parametrize(
    "typ,default",
    [("int", "500"), ("int", True), ("bool", 1), ("float", "x"), ("string", 5)],
)
def test_a_default_must_match_its_declared_type(typ: str, default: object) -> None:
    """`true` for an int used to be accepted -- bool is an int subclass in
    Python, so an unguarded isinstance let it through and the START builder
    then rendered it as `1`."""
    with pytest.raises(TaskProfileError, match="is not a"):
        parse_profile({"taskName": "T", "config": [_field(type=typ, default=default)]})


def test_a_whole_number_is_a_valid_float_default() -> None:
    """0 is a legal float default and must not be caught by the check above."""
    profile = parse_profile({"taskName": "T", "config": [_field(type="float", default=0)]})
    assert profile.config[0].default == 0


def test_a_string_default_cannot_contain_whitespace() -> None:
    """The START grammar is space-separated, so this would split into two
    tokens and the firmware would drop the tail as a bare word."""
    with pytest.raises(TaskProfileError, match="whitespace"):
        parse_profile({"taskName": "T", "config": [_field(type="string", default="two words")]})


# --- §6.3 the START line length cap ---------------------------------------


def _wide_profile(n: int) -> dict:
    """A profile with `n` int fields, each rendering a ~10-character token."""
    return {"taskName": "Wide", "config": [
        {"metadataKey": f"field_{i}", "wireKey": f"W{i:03d}", "label": "x", "type": "int", "default": 20000}
        for i in range(n)
    ]}


def test_a_realistically_wide_profile_fits() -> None:
    """The lab's widest real profile is ~48 fields. That has to fit with the
    seed token still to come, or the feature doesn't ship."""
    cmd = build_start_command(parse_profile(_wide_profile(48)), {})
    assert len(cmd) < START_LINE_MAX


def test_an_over_declared_profile_is_refused_rather_than_truncated() -> None:
    """The firmware CANNOT report this: readLineInto() truncates an overlong
    line and drops the rest, so the session would run on whichever parameters
    happened to fit. Refusing to build the line is the only place it is visible."""
    with pytest.raises(TaskProfileError, match="over the firmware"):
        build_start_command(parse_profile(_wide_profile(200)), {})


def test_the_cap_reserves_room_for_the_seed_appended_later() -> None:
    """The seed is drawn at the start click, minutes after the config half of
    the line is settled, so the budget has to account for a token that does not
    exist yet -- a line that fits alone but not with SEED is still too long."""
    from ephymeris_sidecar.tasks.start_command import with_trial_seed

    for n in range(56, 64):
        profile = parse_profile(_wide_profile(n))
        try:
            cmd = build_start_command(profile, {})
        except TaskProfileError:
            continue
        assert len(with_trial_seed(cmd, 2**31 - 2)) <= START_LINE_MAX


def test_a_value_with_whitespace_falls_back_to_the_default() -> None:
    """A string value the operator typed a space into can't ride the wire; the
    builder already degrades to the sketch's own default rather than emitting
    a token the firmware would misparse."""
    profile = parse_profile({"taskName": "T", "config": [
        {"metadataKey": "mode", "wireKey": "MD", "label": "Mode", "type": "string", "default": "fast"}]})
    assert build_start_command(profile, {"mode": "not fast"}) == "START MD=fast"

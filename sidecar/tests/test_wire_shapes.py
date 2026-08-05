"""Pins the sidecar's actual payload emitters to `protocol/schema.py`.

The generated mirrors cannot drift from each other (they share one source),
but a Python emitter can still drift from the schema — a field added in a
`to_json` and forgotten in `schema.py`, or vice versa. The conformance tests
here run the real emitters and validate their output; the validator tests pin
the semantics that make the check trustworthy (optional vs nullable, unknown
keys, bool-is-not-int).

Events are covered more broadly than this file: `conftest.py` turns validation
on inside `protocol.event()` itself, so every event any test emits is checked.
"""

from __future__ import annotations

import pytest

from ephymeris_sidecar.boards.tool import DetectedBoard
from ephymeris_sidecar.cohorts.grouping import suggest_groups
from ephymeris_sidecar.cohorts.models import Animal, Cohort, Group
from ephymeris_sidecar.discovery import SketchDiscovery, SketchLibraryStatus, library_status
from ephymeris_sidecar.ports.handler import OutputLine
from ephymeris_sidecar.protocol import (
    Evt,
    WireShapeError,
    event,
    validate,
    validate_command_result,
    validate_event_data,
)
from ephymeris_sidecar.sessions.models import GroupRun, Prefix, Session
from ephymeris_sidecar.tasks import profile as task_profile


# --- Validator semantics ---------------------------------------------------


def test_optional_is_not_nullable() -> None:
    spec = ("obj", (("present", "str", False), ("maybe", "int", True)))
    assert validate(spec, {"present": "x"}) == []
    assert validate(spec, {"present": "x", "maybe": 3}) == []
    # Optional means the key may be absent — not that null is acceptable.
    assert validate(spec, {"present": "x", "maybe": None}) != []
    assert validate(spec, {"maybe": 3}) != []


def test_unknown_fields_are_drift_not_noise() -> None:
    spec = ("obj", (("a", "str", False),))
    problems = validate(spec, {"a": "x", "b": 1})
    assert problems and "unknown field `b`" in problems[0]


def test_bool_does_not_pass_as_number() -> None:
    assert validate("int", True) != []
    assert validate("float", True) != []
    assert validate("float", 3) == []  # an int is a fine float on the wire


def test_union_accepts_either_arm() -> None:
    profile = task_profile.parse_profile({"taskName": "T"})
    assert validate_command_result("tasks.getProfile", profile.to_json()) == []
    assert validate_command_result("tasks.getProfile", {"profile": None}) == []
    assert validate_command_result("tasks.getProfile", {"profile": "GRGL"}) != []


def test_event_builder_rejects_drift_when_enabled() -> None:
    good = {"box": 1, "state": "IDLE", "prev": "ERROR", "reason": "acknowledged"}
    assert event(Evt.PORT_STATE, good)["data"] == good
    with pytest.raises(WireShapeError):
        event(Evt.PORT_STATE, {**good, "port": "COM3"})


# --- Emitter conformance ---------------------------------------------------


def _session() -> Session:
    return Session(
        id="s1",
        cohort_id="c1",
        prefix_id="p1",
        prefix_name="2O-Bdisc",
        session_number="25",
        date="2026-07-27",
        started_at="2026-07-27T09:00:00+00:00",
        status="running",
        folder_path="/data/Batch A/2O-Bdisc/2O-Bdisc_25_2026-07-27",
        group_runs=[GroupRun("g1", 0, "2026-07-27T09:00:00+00:00")],
    )


def test_session_to_json_matches_schema() -> None:
    assert validate(("ref", "Session"), _session().to_json()) == []


def test_session_list_item_matches_schema() -> None:
    assert validate(("ref", "SessionListItem"), _session().to_list_item(3)) == []
    assert (
        validate(("ref", "SessionListItem"), _session().to_list_item(3, run_count=2)) == []
    )


def test_prefix_matches_schema() -> None:
    assert validate(("ref", "Prefix"), Prefix("p1", "2O-Bdisc").to_json()) == []


def _cohort() -> Cohort:
    return Cohort(
        id="c1",
        name="Batch A",
        data_folder="/data/Batch A",
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-01T00:00:00+00:00",
        animals=[
            Animal("a1", "R-14", "g1", box_number=3, cage=2, sex="M"),
            Animal("a2", "R-15", "g1"),  # every nullable field null
        ],
        groups=[Group("g1", "Group 1", 0)],
    )


def test_cohort_payloads_match_schema() -> None:
    cohort = _cohort()
    assert validate(("ref", "Cohort"), cohort.to_json()) == []
    assert validate(("ref", "CohortSummary"), cohort.to_summary()) == []


def test_group_proposal_matches_schema() -> None:
    animals = [Animal(f"a{i}", f"R-{i}", "g1") for i in range(8)]
    accepted = suggest_groups(animals, group_count=2)
    assert validate(("ref", "GroupProposal"), accepted.to_json()) == []
    # One group can't hold eight animals — the rejection arm is a payload too.
    rejected = suggest_groups(animals, group_count=1)
    assert rejected.to_json()["rejected"] is not None
    assert validate(("ref", "GroupProposal"), rejected.to_json()) == []


def test_task_profile_payloads_match_schema() -> None:
    behavior = task_profile.parse_profile(
        {
            "taskName": "GRGL 2-Odor Discrimination",
            "config": [
                {
                    "metadataKey": "correction_left",
                    "wireKey": "CL",
                    "label": "Correction left",
                    "type": "int",
                    "default": 0,
                }
            ],
            "strobes": {"101": "ODOR_1_ON", "246": "END_SESSION"},
            "liveMetrics": [
                {
                    "id": "p_r_odor1",
                    "label": "P(R | Odor 1)",
                    "triggerCode": 101,
                    "successCode": 249,
                    "alternateCode": 248,
                    "windowSize": 20,
                }
            ],
        }
    )
    assert validate(("ref", "TaskProfile"), behavior.to_json()) == []

    utility = task_profile.parse_profile(
        {
            "taskName": "Clean & Flush",
            "kind": "utility",
            "controls": [
                {"id": "alloff", "label": "All off", "type": "button", "command": "ALLOFF"},
                {
                    "id": "gear",
                    "label": "Fluid set",
                    "type": "select",
                    "options": [{"label": "Set 1", "command": "SET GEAR=1"}],
                },
            ],
            "telemetry": {"match": "STATUS", "fields": [{"key": "gear", "label": "Fluid set"}]},
            "identify": {"on": "ON LIGHT", "off": "OFF LIGHT"},
        }
    )
    assert validate(("ref", "TaskProfile"), utility.to_json()) == []


def test_utility_baseline_payloads_match_schema() -> None:
    """The baseline snapshot is one shape shared by two commands and an event."""
    from ephymeris_sidecar.utility import BoxBaseline

    box = BoxBaseline(box=2, state="restoring", detail="flashing BOX_Utility")
    assert validate(("ref", "UtilityBoxState"), box.to_json()) == []
    assert validate_command_result("utility.identify", {"delivered": False, "state": box.to_json()}) == []

    status = {
        "configured": True,
        "sketchPath": "/sk/Utility/BOX_Utility",
        "sketchName": "BOX_Utility",
        "canIdentify": True,
        "held": False,
        "message": None,
        "boxes": [box.to_json()],
    }
    assert validate_command_result("utility.status", status) == []
    assert validate_command_result("utility.ensure", status) == []
    assert validate_event_data("utility.updated", status) == []


def test_analytics_derive_payloads_match_schema() -> None:
    """Every `to_json` in `analytics/derive.py`, run for real and validated.

    These are the emitters most likely to drift: a field is added to the maths
    and shows up in the payload, and `schema.py` is a separate file that has to
    be remembered. `RunSummary.to_json` is spread across `RunSummary` on the
    wire rather than nested, so it is checked field-by-field against that shape
    instead of by reference.
    """
    from ephymeris_sidecar.analytics import derive

    profile = task_profile.parse_profile(
        {
            "taskName": "GRGL",
            "strobes": {
                "101": "ODOR_1_ON", "103": "ODOR_3_ON",
                "222": "LIGHTS_ON", "224": "ODOR_POKE",
                "226": "ODOR_UNPOKE", "225": "ODOR_UNPOKE_EARLY",
                "248": "WATER_POKE_L", "249": "WATER_POKE_R",
                "250": "WATER_UNPOKE_EARLY_L", "252": "FLUID_L", "253": "FLUID_R",
                "257": "WATER_POKE_ERROR_L", "246": "END_SESSION",
            },
            "liveMetrics": [
                {"id": "p_r_odor1", "label": "P(R | Odor 1)", "triggerCode": 101,
                 "successCode": 249, "alternateCode": 248, "windowSize": 20},
                {"id": "p_l_odor3", "label": "P(L | Odor 3)", "triggerCode": 103,
                 "successCode": 248, "alternateCode": 249, "windowSize": 20},
            ],
        }
    )
    # One of everything: rewarded, hold-failed, wrong-well, unanswered, a
    # pre-odor bail and a lazy trial — so no branch of any emitter is unreached.
    # Repeated past `DEFAULT_MIN_COUNTED` in the *slower* condition (odor 3
    # scores once per block), or the strategy trail never starts and its
    # emitter goes unchecked.
    codes = (
        [222, 224, 101, 226, 249, 253] + [222, 224, 103, 226, 248, 250]
        + [222, 224, 101, 226, 248, 257] + [222, 224, 103, 226]
        + [222, 224, 225] + [222, 223]
    ) * 12
    document = {
        "rat": "remy1",
        "stop_reason": derive.CLEAN_STOP_REASON,
        "trial_seed": 288577176,
        "ts_data": [[code, index * 1000] for index, code in enumerate(codes)],
    }

    summary = derive.summarize(document, profile)
    payload = summary.to_json()
    assert summary.overall is not None
    assert summary.outcomes is not None
    assert summary.engagement is not None
    assert summary.conditions

    for name, value in (
        ("MetricSummary", payload["metrics"][0]),
        ("MetricSummary", payload["overall"]),
        ("TrialOutcomes", payload["outcomes"]),
        ("ConditionOutcomes", payload["conditions"][0]),
        ("TrialEngagement", payload["engagement"]),
    ):
        assert validate(("ref", name), value) == [], name

    for name, value in (
        ("MetricSeries", derive.series(document, profile)[0].to_json()),
        ("StrategyPoint", derive.strategy_trail(document, profile)[0].to_json()),
        ("TrialRecord", derive.trials_of(document, profile)[0].to_json()),
    ):
        assert validate(("ref", name), value) == [], name

    # And the nullable arms: a profile with no reward vocabulary and no trial
    # light emits null for all three rather than an empty object.
    bare = task_profile.parse_profile(
        {
            "taskName": "Bare",
            "strobes": {"101": "ODOR_1_ON", "248": "WATER_POKE_L", "249": "WATER_POKE_R"},
            "liveMetrics": [
                {"id": "p_r_odor1", "label": "P", "triggerCode": 101,
                 "successCode": 249, "alternateCode": 248, "windowSize": 20}
            ],
        }
    )
    thin = derive.summarize(document, bare).to_json()
    assert thin["outcomes"] is None
    assert thin["engagement"] is None
    assert thin["conditions"] == []


def test_hardware_payloads_match_schema() -> None:
    line = OutputLine(dir="rx", text="READY", ts=1721600000.1)
    assert validate(("ref", "OutputLine"), line.to_json()) == []
    board = DetectedBoard(hardware_id="85735313", address="COM7", fqbn="arduino:avr:mega")
    assert validate(("ref", "DetectedBoard"), board.to_json(box_id=2)) == []
    assert validate(("ref", "DetectedBoard"), board.to_json()) == []


def test_discovery_payloads_match_schema() -> None:
    # The real resolver's answer on this machine, whatever state it is in —
    # ok, empty and damaged all serialise to the same shape.
    status = library_status()
    assert validate(("ref", "SketchLibraryStatus"), status.to_json()) == []
    assert validate(("ref", "SketchDiscovery"), SketchDiscovery(library=status).to_json()) == []
    # The damaged arm explicitly, since a dev machine will rarely produce it.
    damaged = SketchLibraryStatus("damaged", None, "missing", "bundled")
    assert validate(("ref", "SketchLibraryStatus"), damaged.to_json()) == []


def test_capabilities_payload_matches_schema() -> None:
    """The real emitter, over every topology the templates can be asked about.

    `timingHelp`/`outcomeHelp` are the reason this is worth pinning: they are
    projections of the template's own `timing_defaults`/`outcome_defaults`, so a
    template that adds an outcome class or a duration adds a wire key here
    without anyone touching `service.py`. The go/no-go arm is not decoration —
    it is the only topology whose `correct` comes from `_GONOGO_CORRECT`, and
    the only one whose class set omits `wrong`/`omission`/`hold_fail`.
    """
    from ephymeris_sidecar.specs import compiler, service

    if not compiler.available():
        pytest.skip("spec compiler unavailable (jsonschema/pyyaml not installed)")

    for topology in (
        {},
        {"response_mode": "go_nogo"},
        {"response_mode": "n_alternative", "n_sampling_stages": 3, "retention_delay": True},
        {"commit_hold": False, "n_sampling_stages": 0},
    ):
        payload = service.capabilities_payload(topology)
        assert validate(("ref", "SpecCapabilities"), payload) == [], topology
        # Every class the topology produces can be explained, and every
        # required duration too — a help map covering some of them would be
        # worse than one covering none, since the gaps read as "no comment".
        assert set(payload["outcomeHelp"]) == set(payload["outcomeClasses"]), topology
        assert set(payload["requiredTiming"]) <= set(payload["timingHelp"]), topology


def test_event_data_specs_cover_every_event() -> None:
    from ephymeris_sidecar.protocol import ALL_EVENTS, EVENT_DATA

    assert set(EVENT_DATA) == set(ALL_EVENTS)
    assert validate_event_data("no.such.event", {}) != []

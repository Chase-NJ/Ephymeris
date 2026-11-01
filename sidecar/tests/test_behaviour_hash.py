"""A spine task's `profile_hash` covers behaviour only — `TASKS.md#a-spine-tasks-hash-covers-behaviour-only`.

What the board runs and how replay scores it moves the hash; every string
meant for a person does not. The list of what is left out is explicit and
pinned, so a field added later is hashed unless someone deliberately lists it.
"""

from __future__ import annotations

import copy
import json

import pytest

from ephymeris_sidecar.analytics import scoring
from ephymeris_sidecar.taskdef import generate
from ephymeris_sidecar.taskdef.model import TaskDefinition
from ephymeris_sidecar.tasks import behaviour
from ephymeris_sidecar.tasks import profile as task_profile
from tests.fixtures import spine as fixture


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


def generated(**edits) -> dict:
    """The tracer's `task.json`, as the generator writes it."""
    return generate.build_profile(TaskDefinition.from_json(fixture.tracer(**edits))).to_json()


def digest(raw: dict) -> str:
    return task_profile.profile_hash(task_profile.parse_profile(raw))


def renamed_row(name: str) -> list[dict]:
    rows = fixture.tracer()["rows"]
    return [rows[0] | {"name": name}]


def test_renaming_a_row_leaves_the_hash_unchanged():
    assert digest(generated(rows=renamed_row("Orange"))) == digest(generated())


def test_editing_help_text_and_other_words_for_a_person_leaves_the_hash_unchanged():
    raw = generated()
    reworded = generated()
    for field in reworded["config"]:
        field |= {"label": field["label"] + " (ms)", "help": "Reworded.", "group": "Timing", "unit": "msec"}
    reworded["legacyNames"] = ["Spine Tracer (old)"]
    assert digest(reworded) == digest(raw)


def raw_spine(**rows) -> dict:
    """A spine profile written by hand, so it can carry fields the generator
    does not write yet: a row's `contingency` map, a second row."""
    row = {"id": "go", "name": "Go", "bind": {"port": "odor_port", "reward": "fluid_2"},
           "rewardMs": 100, "rewardPermille": 1000,
           "contingency": {"port": {"outcome": "correct", "line": "reward", "permille": 1000},
                           "timeout": {"outcome": "omission"}}}
    return {
        "taskName": "Hand written",
        "config": [{"metadataKey": "reward_ms", "wireKey": "RW1", "label": "Reward — Go",
                    "type": "int", "default": 100, "min": 0, "max": 5000}],
        "spine": {
            "interp": 2,
            "slots": [{"id": "port", "type": "digital_in"}, {"id": "reward", "type": "digital_out"}],
            "spine": [{"phase": "wait", "on": "port"}, {"phase": "outcome", "line": "reward", "ms": 0},
                      {"phase": "iti", "ms": 3000}],
            "rows": rows.get("rows", [row]),
            "blocks": [{"id": "b1", "rows": ["go"], "trials": 20}],
        },
    }


def test_changing_a_contingency_moves_the_hash():
    raw = raw_spine()
    row = raw["spine"]["rows"][0]
    edited = raw_spine(rows=[row | {"contingency": row["contingency"] | {"timeout": {"outcome": "withheld"}}}])
    assert digest(edited) != digest(raw)


def test_changing_a_phase_moves_the_hash():
    phases = fixture.tracer()["spine"]
    longer = generated(spine=phases[:2] + [{"phase": "delay", "ms": 750}] + phases[3:])
    assert digest(longer) != digest(generated())
    edited = raw_spine()
    edited["spine"]["spine"][0] = {"phase": "wait", "on": "port", "timeoutMs": 4000}
    assert digest(edited) != digest(raw_spine())


def test_changing_a_block_moves_the_hash():
    assert digest(generated(blocks=[{"id": "b1", "rows": ["r1"], "trials": 40}])) != digest(generated())
    edited = raw_spine()
    edited["spine"]["blocks"][0]["trials"] = 21
    assert digest(edited) != digest(raw_spine())


def test_rows_are_keyed_by_their_stable_id():
    first = raw_spine()["spine"]["rows"][0]
    second = first | {"id": "nogo", "name": "No go", "rewardPermille": 0}
    assert digest(raw_spine(rows=[first, second])) == digest(raw_spine(rows=[second, first])), (
        "reordering rows is not a change of behaviour: a block draws them by id"
    )
    assert digest(raw_spine(rows=[first | {"id": "go2"}])) != digest(raw_spine()), (
        "a row's id is what blocks draw it by"
    )


def test_the_unhashed_list_is_pinned():
    """Adding a path here is a decision that a field is a person's words, not
    behaviour: every run of a task hashes the same whatever it says."""
    assert behaviour.UNHASHED == {
        ("legacyNames",),
        ("config", "*", "label"),
        ("config", "*", "help"),
        ("config", "*", "group"),
        ("config", "*", "unit"),
        ("liveMetrics", "*", "label"),
        ("spine", "rows", "*", "name"),
    }


def leaves(value, path=()):
    """Every scalar in a JSON value, by path; a list index is an int step."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from leaves(child, (*path, key))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from leaves(child, (*path, i))
    else:
        yield path, value


def unhashed(path) -> bool:
    if path[:1] == ("strobes",):
        return True  # left out of every profile's hash
    # A listed path leaves out everything beneath it.
    # `*` is any list element (an int step); a dict step is always its key.
    return any(len(p) <= len(path) and all(s == step or (s == behaviour.ANY and isinstance(step, int))
                                           for s, step in zip(p, path))
               for p in behaviour.UNHASHED)


#: Strings the parser checks against a set: each is swapped for another legal one.
_LEGAL_SWAPS = {"behavior": "utility", "utility": "behavior", "int": "float", "float": "int",
                "bool": "int", "string": "int"}


def changed(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, str):
        return _LEGAL_SWAPS.get(value, value + "x")
    return 0


def replaced(raw, path, value):
    """`raw` with the leaf at `path` set to `value`."""
    edited = copy.deepcopy(raw)
    target = edited
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return edited


def test_every_field_not_on_the_list_moves_the_hash_and_every_field_on_it_does_not():
    """The walk covers whatever the generator writes, including fields added
    after this test: a new one is hashed unless its path is on the list."""
    raw = task_profile.parse_profile(generated(legacyNames=["Old tracer"])).to_json()
    raw["strobes"] = {"7": "TRIAL_START"}
    base = digest(raw)
    on_the_list = set()
    for path, value in leaves(raw):
        moved = digest(replaced(raw, path, changed(value))) != base
        assert moved != unhashed(path), (
            f"{path} {'moved' if moved else 'did not move'} the hash"
        )
        if unhashed(path):
            on_the_list.add(path[0])
    assert on_the_list == {"strobes", "legacyNames", "config", "spine"}, "the walk reached the listed fields"


def test_the_snapshot_round_trips_byte_for_byte_through_the_parser():
    """Names stay in the snapshot: only the hash leaves them out."""
    raw = generated(rows=renamed_row("Orange"))
    again = task_profile.parse_profile(raw).to_json()
    assert json.dumps(again) == json.dumps(raw)
    assert again["spine"]["rows"][0]["name"] == "Orange"
    hand = task_profile.parse_profile(raw_spine()).to_json()
    assert json.dumps(task_profile.parse_profile(hand).to_json()) == json.dumps(hand)
    assert json.dumps(hand["spine"]) == json.dumps(raw_spine()["spine"]), "fields it does not know survive"


def test_a_metric_label_is_left_out():
    def with_metric(label: str) -> dict:
        return raw_spine() | {"liveMetrics": [{"id": "p_go", "label": label, "triggerCode": 7,
                                                "successCode": 8, "alternateCode": 9, "windowSize": 5}]}
    assert digest(with_metric("P(go)")) == digest(with_metric("Hit rate"))
    moved = with_metric("P(go)")
    moved["liveMetrics"][0]["windowSize"] = 10
    assert digest(moved) != digest(with_metric("P(go)"))


@pytest.mark.parametrize("edit", [*sorted(behaviour.UNHASHED), "hash rows as a list"], ids=str)
def test_the_score_canary_sees_every_part_of_the_projection(monkeypatch, edit):
    """A cached score is served verbatim (`DATA.md#caching`): a change to this
    projection moves every spine run's scored digest, so it must move the canary.
    Each listed path is put back into the hash in turn, and rows are unkeyed."""
    before = scoring.canary_fingerprint()
    if isinstance(edit, tuple):
        monkeypatch.setattr(behaviour, "UNHASHED", behaviour.UNHASHED - {edit})
    else:
        monkeypatch.setattr(behaviour, "_keyed_by_id", lambda rows: rows)
    assert scoring.canary_fingerprint() != before


def test_a_profile_without_a_spine_still_hashes_its_words():
    """Legacy hashes cannot be recomputed: their projection is unchanged."""
    plain = {"taskName": "Plain", "config": [{"metadataKey": "hold", "wireKey": "H", "label": "Hold",
                                              "type": "int", "default": 1}]}
    relabelled = copy.deepcopy(plain)
    relabelled["config"][0]["label"] = "Poke hold"
    assert digest(relabelled) != digest(plain)


def test_rows_sharing_an_id_are_both_hashed():
    first = raw_spine()["spine"]["rows"][0]
    twin = first | {"rewardMs": 250}
    both = digest(raw_spine(rows=[first, twin]))
    assert both != digest(raw_spine(rows=[twin])) and both != digest(raw_spine(rows=[first])), (
        "keyed by a repeated id, one row would replace the other"
    )


def test_rows_without_an_id_are_both_hashed():
    first = {k: v for k, v in raw_spine()["spine"]["rows"][0].items() if k != "id"}
    second = first | {"rewardMs": 250}
    assert digest(raw_spine(rows=[first, second])) != digest(raw_spine(rows=[second]))

"""A spine task's `profile_hash` covers behaviour only — `TASKS.md#profile-and-params-hashes`.

What the board runs and how replay scores it moves the hash; every string
meant for a person does not. The list of what is left out is explicit and
pinned, so a field added later is hashed unless someone deliberately lists it.
"""

from __future__ import annotations

import copy
import json

import pytest

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
    return any(len(p) <= len(path) and all(s == "*" or s == step for s, step in zip(p, path))
               for p in behaviour.UNHASHED)


def changed(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, str):
        return value + "x"
    return 0


def at(raw, path, value):
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
        try:
            moved = digest(at(raw, path, changed(value))) != base
        except task_profile.TaskProfileError:
            assert not unhashed(path), f"{path} is on the list but its value is checked"
            continue
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
    assert json.dumps(again, sort_keys=True) == json.dumps(raw, sort_keys=True)
    assert again["spine"]["rows"][0]["name"] == "Orange"
    assert json.dumps(task_profile.parse_profile(raw_spine()).to_json()["spine"], sort_keys=True) == \
        json.dumps(raw_spine()["spine"], sort_keys=True)


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
    assert digest(raw_spine(rows=[first, twin])) != digest(raw_spine(rows=[first, first]))

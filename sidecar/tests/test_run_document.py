"""One way to read a run's document — `DATA.md#the-json-document`.

`sessions/run_document.py` is the only module that knows where a core field
sits in a run's document, so a change of shape is a change in one file. That
holds only while nothing else indexes a document by a core key, to read it or
to write it, so this walks
every module's syntax tree and fails on any that does, as
`test_analytics_stream_is_pure.py` does for purity.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ephymeris_sidecar.sessions import run_document as rd
from ephymeris_sidecar.tasks.profile import DERIVED_KEY, SNAPSHOT_KEY

PACKAGE = Path(__file__).resolve().parents[1] / "ephymeris_sidecar"
ACCESSOR = PACKAGE / "sessions" / "run_document.py"

DOCUMENT = {
    "rat": "remy1", "serial_port": "COM5", "session_id": "8O-Bdisc_09", "sketch": "GRGL 8-Odor EZ",
    "interp": 1, "free_ram": 5120, "stream": 2, "sync": "tick",
    "channel_set_hash": "abc", "channel_set_hash_version": 2,
    "intan_recording": "rec_1", "intan_path": "D:/rhx", "intan_digital_in": 1, "intan_port": "A",
    "intan_channels": "A-016:A-031", "intan_sample_rate": 30000,
    "num_trials": 1000, "error_delay": 20000,
    "trial_seed": 7, "host_seed": 8,
    "task_profile": {"taskName": "GRGL 8-Odor EZ"},
    "stop_reason": "BF_END_SESSION received", "n_events": 2, "ts_data": [[221, 0], [222, 1001]],
    "derived": {"status": "ok", "trials": []},
}


@pytest.mark.parametrize(("accessor", "key"), [
    (rd.animal_of, "rat"), (rd.serial_port_of, "serial_port"), (rd.session_id_of, "session_id"),
    (rd.sketch_of, "sketch"), (rd.interp_of, "interp"), (rd.free_ram_of, "free_ram"),
    (rd.stream_of, "stream"), (rd.sync_of, "sync"),
    (rd.channel_set_hash_of, "channel_set_hash"),
    (rd.channel_set_hash_version_of, "channel_set_hash_version"),
    (rd.recording_name_of, "intan_recording"), (rd.recording_path_of, "intan_path"),
    (rd.recording_digital_in_of, "intan_digital_in"), (rd.recording_port_of, "intan_port"),
    (rd.recording_channels_of, "intan_channels"), (rd.recording_sample_rate_of, "intan_sample_rate"),
    (rd.trial_seed_of, "trial_seed"), (rd.host_seed_of, "host_seed"),
    (rd.snapshot_of, "task_profile"), (rd.stop_reason_of, "stop_reason"),
    (rd.n_events_of, "n_events"), (rd.strobes_of, "ts_data"), (rd.trial_table_of, "derived"),
])
def test_an_accessor_returns_the_field_as_stored_and_none_when_absent(accessor, key) -> None:
    assert accessor(DOCUMENT) is DOCUMENT[key]
    assert accessor({}) is None


def test_the_snapshot_and_the_trial_table_are_core_fields() -> None:
    assert {SNAPSHOT_KEY, DERIVED_KEY} <= rd.FIELDS


def test_strobes_take_a_default_for_a_document_without_them() -> None:
    assert rd.strobes_of({}, []) == []
    assert rd.strobes_of({"ts_data": None}, []) is None


def test_a_parameter_is_read_by_its_metadata_key() -> None:
    assert rd.has_param(DOCUMENT, "num_trials")
    assert rd.param_of(DOCUMENT, "num_trials") == 1000
    assert not rd.has_param(DOCUMENT, "reward_time_5")
    assert not rd.has_param(DOCUMENT, None)
    with pytest.raises(KeyError):
        rd.param_of(DOCUMENT, "reward_time_5")


def test_the_trial_table_is_dropped_and_set_without_touching_the_original() -> None:
    bare = rd.without_trial_table(DOCUMENT)
    assert "derived" not in bare and "derived" in DOCUMENT
    assert list(bare) == [key for key in DOCUMENT if key != "derived"]
    block = {"status": "ok"}
    again = rd.with_trial_table(bare, block)
    assert again["derived"] is block and list(again)[-1] == "derived"
    assert "derived" not in bare


def test_the_accessor_is_pure() -> None:
    """Standard library typing only, so `analytics/stream/` may import it."""
    for node in ast.walk(ast.parse(ACCESSOR.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            assert {alias.name for alias in node.names} <= {"typing"}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in {"__future__", "typing"}


# --------------------------------------------------------------------------- #
# Nothing else reads a core field by key
# --------------------------------------------------------------------------- #

#: Names that stand for a core key wherever they are used as one.
KEY_CONSTANTS = {"SNAPSHOT_KEY", "DERIVED_KEY"}

#: Keyed reads that are not of a run's document: `{file: {receiver: why}}`.
#: The walk sees `x["session_id"]` and cannot see what `x` is, so each dict
#: that shares a key name with the document is named here once.
NOT_A_DOCUMENT: dict[str, dict[str, str]] = {
    "cohorts/move.py": {"run": "a database row"},
    "intan/impedance_store.py": {"first": "a database row"},
    "intan/yield_store.py": {"row": "a database row"},
    "logbook/repository.py": {"row": "a database row"},
    "rig/transfer.py": {"other": "a rig export file"},
    "sessions/derived.py": {"block": "the derived block itself"},
    "sessions/repository.py": {"row": "a database row"},
    "sessions/runner.py": {
        "core": "a run's fields by name, handed to run_document.build",
        "recording": "the recording's fields by name, as intan/service.py gives them",
    },
    "taskdef/transfer.py": {"file": "a task export file"},
    "tasks/start_command.py": {"config": "the merged parameters, before any document exists"},
}


def _key(node: ast.AST) -> str | None:
    """The core key `node` names, as a literal, a constant, or a profile field's `metadata_key`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in rd.FIELDS:
        return node.value
    if isinstance(node, ast.Name) and node.id in KEY_CONSTANTS:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in KEY_CONSTANTS | {"metadata_key"}:
        return node.attr
    return None


def keyed_reads(source: str) -> list[tuple[int, str, str]]:
    """`(line, receiver, key)` for every `x[key]` (read, written or deleted),
    `x.get(key)`, `x.pop(key)` and `key in x`."""
    out = []
    for node in ast.walk(ast.parse(source)):
        key = receiver = None
        if isinstance(node, ast.Subscript):
            key, receiver = _key(node.slice), node.value
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in {"get", "pop"} and node.args):
            key, receiver = _key(node.args[0]), node.func.value
        elif (isinstance(node, ast.Compare) and len(node.ops) == 1
              and isinstance(node.ops[0], (ast.In, ast.NotIn))):
            key, receiver = _key(node.left), node.comparators[0]
        if key is not None and receiver is not None:
            out.append((node.lineno, ast.unparse(receiver), key))
    return out


def test_the_walk_sees_each_way_of_reading_a_key() -> None:
    source = (
        "a = document['rat']\n"
        "b = document.get('sketch')\n"
        "c = 'stream' in document\n"
        "d = document.pop(DERIVED_KEY, None)\n"
        "e = document[field.metadata_key]\n"
        "document['ts_data'] = []\n"
        "del document['trial_seed']\n"
        "f = document['num_trials']\n"    # not a core key
    )
    assert [(line, key) for line, _, key in keyed_reads(source)] == [
        (1, "rat"), (2, "sketch"), (3, "stream"), (4, "DERIVED_KEY"), (5, "metadata_key"),
        (6, "ts_data"), (7, "trial_seed"),
    ]


#: `protocol.py` is generated, and its keys are the wire's, not a document's.
MODULES = sorted(p for p in PACKAGE.rglob("*.py") if p != ACCESSOR and p.name != "protocol.py")


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.relative_to(PACKAGE).as_posix())
def test_no_module_reads_or_writes_a_core_field_by_key(path: Path) -> None:
    allowed = NOT_A_DOCUMENT.get(path.relative_to(PACKAGE).as_posix(), {})
    found = [
        f"line {line}: {receiver} read by {key!r}"
        for line, receiver, key in keyed_reads(path.read_text(encoding="utf-8"))
        if receiver not in allowed
    ]
    assert not found, (
        f"{path.name} reads or writes a run document's core field by key; go through "
        f"sessions/run_document.py instead, or name the dict in NOT_A_DOCUMENT if it is not a run's document: {found}"
    )


def test_the_exceptions_are_all_still_needed() -> None:
    """An exception whose read is gone is removed, so the list never hides a new one."""
    stale = []
    for file, receivers in NOT_A_DOCUMENT.items():
        seen = {receiver for _, receiver, _ in keyed_reads((PACKAGE / file).read_text(encoding="utf-8"))}
        stale.extend(f"{file}: {receiver}" for receiver in receivers if receiver not in seen)
    assert not stale, stale

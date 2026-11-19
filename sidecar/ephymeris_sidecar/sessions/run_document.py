"""The one place that knows where a field sits in a run's document — `DATA.md#the-json-document`.

Every reader asks here instead of indexing the document, so a change to the
document's shape is a change to this file alone;
`tests/test_run_document.py` fails on a keyed read anywhere else.

**Pure**: standard-library typing only, no file, database or clock, so
`analytics/stream/` and `tasks/profile.py` may both import it.

A document has one of two shapes. **Version 2** is nested: `schema_version`,
then its facts under `run`, `task`, `params`, `recording` and `trials`, with
`ts_data` and `task_profile` beside them. **Version 1** is flat and has no
`schema_version`. Every function here takes either; `lifted` turns the first
into the second, and `analytics/reader.py` does that to every file it opens.

Each `*_of` returns the value exactly as stored, or None when the document has
none. Nothing is coerced or checked: a hand-edited file can hold anything, and
what a wrong type means is the caller's call.
"""

from __future__ import annotations

from typing import Any

Document = dict[str, Any]

#: The key a document carries its profile snapshot under
#: (`DATA.md#the-embedded-task-profile`): written by `sessions/writer.py`.
SNAPSHOT_KEY = "task_profile"

#: The key a version-1 document carries its derived trial table under
#: (`DATA.md#the-derived-trial-table`): written by `sessions/derived.py`.
DERIVED_KEY = "derived"

#: The same block's key in version 2, and the key its rows sit under there
#: (version 1 has them under `trials`, inside `derived`).
TRIALS_KEY = "trials"
_ROWS = {1: "trials", 2: "rows"}

#: The newest document version this build reads, and the key that carries it.
SCHEMA_VERSION = 2
VERSION_KEY = "schema_version"

_STROBES = "ts_data"

#: Every core field of a version-1 document: all of it that is not one of the
#: run's parameters.
FIELDS = frozenset({
    "rat", "serial_port", "session_id", "sketch",
    "interp", "free_ram", "stream", "sync", "channel_set_hash", "channel_set_hash_version",
    "intan_recording", "intan_path", "intan_digital_in", "intan_port", "intan_channels",
    "intan_sample_rate",
    "trial_seed", "host_seed", SNAPSHOT_KEY,
    "stop_reason", "n_events", _STROBES, DERIVED_KEY,
})


#: Where each version-1 core field sits in version 2: `flat key -> (block, key)`.
_WHERE = {
    "rat": ("run", "animal"),
    "serial_port": ("run", "serial_port"),
    "session_id": ("run", "session_id"),
    "stop_reason": ("run", "stop_reason"),
    "n_events": ("run", "n_events"),
    "sketch": ("task", "sketch"),
    "stream": ("task", "stream"),
    "interp": ("task", "interp"),
    "free_ram": ("task", "free_ram"),
    "sync": ("task", "sync"),
    "trial_seed": ("task", "trial_seed"),
    "host_seed": ("task", "host_seed"),
    "channel_set_hash": ("task", "channel_set_hash"),
    "channel_set_hash_version": ("task", "channel_set_hash_version"),
    "intan_recording": ("recording", "name"),
    "intan_path": ("recording", "path"),
    "intan_digital_in": ("recording", "digital_in"),
    "intan_port": ("recording", "port"),
    "intan_channels": ("recording", "channels"),
    "intan_sample_rate": ("recording", "sample_rate"),
}

#: The version-2 blocks that hold plain values, in the order they are written.
VALUE_BLOCKS = ("run", "task", "params", "recording")


# --- which shape ------------------------------------------------------------ #

def is_version_2(document: Document) -> bool:
    version = document.get(VERSION_KEY)
    return version == SCHEMA_VERSION and not isinstance(version, bool)


def unreadable_reason(document: Document) -> str | None:
    """Why this build must not read `document`, or None when it may.

    A version above this build's is a newer build's file: its blocks may mean
    something else, so it is refused whole rather than half-read.
    """
    if VERSION_KEY not in document or is_version_2(document):
        return None
    version = document[VERSION_KEY]
    if isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA_VERSION:
        return (f"is a version {version} run document, written by a newer build of Ephymeris "
                f"(this build reads up to version {SCHEMA_VERSION})")
    return f"has a schema_version of {version!r}, which is not a version of the run document"


def lifted(document: Document) -> Document:
    """`document` in the version-2 shape: a version-1 one regrouped into a new
    dict, a version-2 one returned as it is.

    Every flat key that is not a core field is one of the run's parameters, so
    it goes under `params`. Nothing is dropped, renamed beyond `_WHERE`, or
    given a value the file did not hold.
    """
    if is_version_2(document):
        return document
    blocks: dict[str, Document] = {name: {} for name in VALUE_BLOCKS}
    for key, value in document.items():
        if key in _WHERE:
            block, name = _WHERE[key]
            blocks[block][name] = value
        elif key not in FIELDS:
            blocks["params"][key] = value
    out: Document = {VERSION_KEY: SCHEMA_VERSION}
    out.update({name: blocks[name] for name in VALUE_BLOCKS if blocks[name] or name != "recording"})
    if DERIVED_KEY in document:
        out[TRIALS_KEY] = _renamed(document[DERIVED_KEY], _ROWS[1], _ROWS[2])
    for key in (_STROBES, SNAPSHOT_KEY):
        if key in document:
            out[key] = document[key]
    return out


def _block(document: Document, name: str) -> Document:
    """A version-2 block, or an empty one where the document's is missing or torn."""
    block = document.get(name)
    return block if isinstance(block, dict) else {}


def _field(document: Document, flat_key: str) -> Any:
    if is_version_2(document):
        block, name = _WHERE[flat_key]
        return _block(document, block).get(name)
    return document.get(flat_key)


def _renamed(block: Any, old: str, new: str) -> Any:
    """`block` with one key renamed in place; anything but a dict as it is."""
    if not isinstance(block, dict):
        return block
    return {(new if key == old else key): value for key, value in block.items()}


# --- the run ---------------------------------------------------------------- #

def animal_of(document: Document) -> Any:
    return _field(document, "rat")


def serial_port_of(document: Document) -> Any:
    return _field(document, "serial_port")


def session_id_of(document: Document) -> Any:
    return _field(document, "session_id")


def sketch_of(document: Document) -> Any:
    return _field(document, "sketch")


def stop_reason_of(document: Document) -> Any:
    return _field(document, "stop_reason")


def n_events_of(document: Document) -> Any:
    return _field(document, "n_events")


def trial_seed_of(document: Document) -> Any:
    """The seed the board drew its trials from, off its `SEED` line."""
    return _field(document, "trial_seed")


def host_seed_of(document: Document) -> Any:
    """The seed the app sent on the `START` line."""
    return _field(document, "host_seed")


# --- what the board announced before READY (`TASKS.md#confirming-the-parameters`) --- #

def interp_of(document: Document) -> Any:
    return _field(document, "interp")


def free_ram_of(document: Document) -> Any:
    return _field(document, "free_ram")


def stream_of(document: Document) -> Any:
    """The stream grammar the board announced as `STREAM=<n>` (`TASKS.md#stream-grammar`)."""
    return _field(document, "stream")


def sync_of(document: Document) -> Any:
    """`"tick"` for one sync pulse per strobing tick (`RECORDING.md#firmware-pulse`)."""
    return _field(document, "sync")


def channel_set_hash_of(document: Document) -> Any:
    return _field(document, "channel_set_hash")


def channel_set_hash_version_of(document: Document) -> Any:
    return _field(document, "channel_set_hash_version")


# --- the Intan recording the run was inside (`RECORDING.md#what-is-written`) --- #

def recording_name_of(document: Document) -> Any:
    return _field(document, "intan_recording")


def recording_path_of(document: Document) -> Any:
    return _field(document, "intan_path")


def recording_digital_in_of(document: Document) -> Any:
    return _field(document, "intan_digital_in")


def recording_port_of(document: Document) -> Any:
    return _field(document, "intan_port")


def recording_channels_of(document: Document) -> Any:
    return _field(document, "intan_channels")


def recording_sample_rate_of(document: Document) -> Any:
    return _field(document, "intan_sample_rate")


# --- the parameters the run ran on ------------------------------------------ #

def _params(document: Document) -> Document:
    return _block(document, "params") if is_version_2(document) else document


def has_param(document: Document, metadata_key: Any) -> bool:
    """Whether the run records a value for the parameter of this `metadataKey`."""
    return metadata_key in _params(document)


def param_of(document: Document, metadata_key: str) -> Any:
    """The recorded value of one parameter. Raises KeyError when the run has none."""
    return _params(document)[metadata_key]


# --- the profile snapshot, the strobes and the trial table ------------------- #

def snapshot_of(document: Document) -> Any:
    """The run's own profile snapshot (`DATA.md#the-embedded-task-profile`)."""
    return document.get(SNAPSHOT_KEY)


def strobes_of(document: Document, default: Any = None) -> Any:
    """`ts_data` as stored: `[[code, timestamp_ms], …]`. `default` only when the
    document has no such field at all."""
    return document.get(_STROBES, default)


def trial_table_key(document: Document) -> str:
    """The key this document's shape keeps its trial table under, in both files."""
    return TRIALS_KEY if is_version_2(document) else DERIVED_KEY


def stored_trial_table(document: Document, block: Any) -> Any:
    """`block`, as `sessions/derived.py` derives it, in the shape this document
    stores it in: version 2 keeps the rows under `rows`."""
    return _renamed(block, _ROWS[1], _ROWS[2]) if is_version_2(document) else block


def trial_table_of(document: Document) -> Any:
    """The stored trial-table block (`DATA.md#the-derived-trial-table`), in the
    shape `sessions/derived.py` derives it in: its rows under `trials`."""
    if is_version_2(document):
        return _renamed(document.get(TRIALS_KEY), _ROWS[2], _ROWS[1])
    return document.get(DERIVED_KEY)


def without_trial_table(document: Document) -> Document:
    """A copy of `document` with no trial-table block, its other fields in order."""
    drop = trial_table_key(document)
    return {key: value for key, value in document.items() if key != drop}


def with_trial_table(document: Document, block: Any) -> Document:
    """A copy of `document` with `block` as its trial table: last in version 1,
    before the strobes in version 2."""
    bare = without_trial_table(document)
    if not is_version_2(document):
        return {**bare, DERIVED_KEY: block}
    out: Document = {}
    for key, value in bare.items():
        if key == _STROBES:
            out[TRIALS_KEY] = stored_trial_table(document, block)
        out[key] = value
    out.setdefault(TRIALS_KEY, stored_trial_table(document, block))
    return out

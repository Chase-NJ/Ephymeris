"""The one place that knows where a field sits in a run's document — `DATA.md#the-json-document`.

Every reader asks here instead of indexing the document, so a change to the
document's shape is a change to this file alone;
`tests/test_run_document.py` fails on a keyed read anywhere else.

**Pure**: standard-library typing only, no file, database or clock, so
`analytics/stream/` and `tasks/profile.py` may both import it.

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

#: The key a document carries its derived trial table under
#: (`DATA.md#the-derived-trial-table`): written by `sessions/derived.py`.
DERIVED_KEY = "derived"

_STROBES = "ts_data"

#: Every core field: all of a document that is not one of the run's parameters.
FIELDS = frozenset({
    "rat", "serial_port", "session_id", "sketch",
    "interp", "free_ram", "stream", "sync", "channel_set_hash", "channel_set_hash_version",
    "intan_recording", "intan_path", "intan_digital_in", "intan_port", "intan_channels",
    "intan_sample_rate",
    "trial_seed", "host_seed", SNAPSHOT_KEY,
    "stop_reason", "n_events", _STROBES, DERIVED_KEY,
})


# --- the run ---------------------------------------------------------------- #

def animal_of(document: Document) -> Any:
    return document.get("rat")


def serial_port_of(document: Document) -> Any:
    return document.get("serial_port")


def session_id_of(document: Document) -> Any:
    return document.get("session_id")


def sketch_of(document: Document) -> Any:
    return document.get("sketch")


def stop_reason_of(document: Document) -> Any:
    return document.get("stop_reason")


def n_events_of(document: Document) -> Any:
    return document.get("n_events")


def trial_seed_of(document: Document) -> Any:
    """The seed the board drew its trials from, off its `SEED` line."""
    return document.get("trial_seed")


def host_seed_of(document: Document) -> Any:
    """The seed the app sent on the `START` line."""
    return document.get("host_seed")


# --- what the board announced before READY (`TASKS.md#confirming-the-parameters`) --- #

def interp_of(document: Document) -> Any:
    return document.get("interp")


def free_ram_of(document: Document) -> Any:
    return document.get("free_ram")


def stream_of(document: Document) -> Any:
    """The stream grammar the board announced as `STREAM=<n>` (`TASKS.md#stream-grammar`)."""
    return document.get("stream")


def sync_of(document: Document) -> Any:
    """`"tick"` for one sync pulse per strobing tick (`RECORDING.md#firmware-pulse`)."""
    return document.get("sync")


def channel_set_hash_of(document: Document) -> Any:
    return document.get("channel_set_hash")


def channel_set_hash_version_of(document: Document) -> Any:
    return document.get("channel_set_hash_version")


# --- the Intan recording the run was inside (`RECORDING.md#what-is-written`) --- #

def recording_name_of(document: Document) -> Any:
    return document.get("intan_recording")


def recording_path_of(document: Document) -> Any:
    return document.get("intan_path")


def recording_digital_in_of(document: Document) -> Any:
    return document.get("intan_digital_in")


def recording_port_of(document: Document) -> Any:
    return document.get("intan_port")


def recording_channels_of(document: Document) -> Any:
    return document.get("intan_channels")


def recording_sample_rate_of(document: Document) -> Any:
    return document.get("intan_sample_rate")


# --- the parameters the run ran on ------------------------------------------ #

def has_param(document: Document, metadata_key: Any) -> bool:
    """Whether the run records a value for the parameter of this `metadataKey`."""
    return metadata_key in document


def param_of(document: Document, metadata_key: str) -> Any:
    """The recorded value of one parameter. Raises KeyError when the run has none."""
    return document[metadata_key]


# --- the profile snapshot, the strobes and the trial table ------------------- #

def snapshot_of(document: Document) -> Any:
    """The run's own profile snapshot (`DATA.md#the-embedded-task-profile`)."""
    return document.get(SNAPSHOT_KEY)


def strobes_of(document: Document, default: Any = None) -> Any:
    """`ts_data` as stored: `[[code, timestamp_ms], …]`. `default` only when the
    document has no such field at all."""
    return document.get(_STROBES, default)


def trial_table_of(document: Document) -> Any:
    """The stored trial-table block (`DATA.md#the-derived-trial-table`)."""
    return document.get(DERIVED_KEY)


def without_trial_table(document: Document) -> Document:
    """A copy of `document` with no trial-table block, its other fields in order."""
    return {key: value for key, value in document.items() if key != DERIVED_KEY}


def with_trial_table(document: Document, block: Any) -> Document:
    """A copy of `document` with `block` as its trial table, last."""
    return {**without_trial_table(document), DERIVED_KEY: block}

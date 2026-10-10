"""Parse and validate a sketch's `task.json` — `TASKS.md#task-profile`.

Kept lenient in one specific way: a **missing** `task.json` is not an error —
it's the fully-supported profile-less case (`TASKS.md#overview`). A **malformed** one is an
error, surfaced so the operator can fix it, with the sketch otherwise treated as
profile-less.

Two sketch *kinds* share this file (`TASKS.md#top-level-keys`):

* ``behavior`` (the default) — a scored ``IN_SESSION`` task, described by
  ``config`` / ``liveMetrics``, decoded through the strobe vocabulary.
* ``utility`` — a ``PASSTHROUGH`` tool (priming, box self-test) the app drives
  with ``controls`` (each maps to a serial command sent over ``port.send``) and
  reads back through ``telemetry`` (how to parse the sketch's non-persisted
  ``STATUS`` lines out of ``port.output``). No new wire commands: utility control
  and status ride the existing passthrough primitives.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable

if TYPE_CHECKING:
    from ..rig.registry import Vocabulary

log = logging.getLogger(__name__)

TASK_FILENAME = "task.json"

#: Config field types the pre-flight form and START builder understand (`TASKS.md#config-fields`).
CONFIG_TYPES = {"int", "float", "bool", "string"}

#: Sketch kinds (`TASKS.md#top-level-keys`). Anything else is a malformed profile.
PROFILE_KINDS = {"behavior", "utility"}

#: Control widget types a utility profile can declare (`TASKS.md#utility-controls-and-telemetry`).
CONTROL_TYPES = {"button", "select", "grid"}

#: Reserved across every profile (`TASKS.md#seed`). The host appends the run's seed itself,
#: so a profile claiming this key would collide and silently lose one of the two.
RESERVED_WIRE_KEYS = {"SEED"}

#: The core session-file fields (`DATA.md#the-json-document`). Config is merged into the session file FLAT at the top
#: level, so a `metadataKey` matching one of these would overwrite it rather than
#: sit beside it — and nothing downstream would report the loss.
CORE_METADATA_KEYS = frozenset(
    {
        "rat",
        "serial_port",
        "session_id",
        "sketch",
        "stop_reason",
        "n_events",
        "ts_data",
        "trial_seed",
        "host_seed",
        # The run's own profile snapshot, written after the task fields — a
        # field of this name would be silently replaced by it.
        "task_profile",
        # `RECORDING.md#what-is-written` -- written beside the core fields when a run is
        # inside an Intan recording.
        "intan_recording",
        "intan_path",
        "intan_digital_in",
        "intan_port",
        "intan_channels",
        "intan_sample_rate",
    }
)

#: Python types a declared `default` may have, per the field's `type` (`TASKS.md#config-fields`).
#: `bool` is checked before `int` everywhere below: in Python `bool` IS an `int`,
#: so an unguarded isinstance would accept `true` as a valid int default.
_DEFAULT_TYPES: dict[str, tuple[type, ...]] = {
    "int": (int,),
    "float": (int, float),  # 0 is a legal float default
    "bool": (bool,),
    "string": (str,),
}


class TaskProfileError(Exception):
    """`task.json` exists but couldn't be parsed or is structurally invalid."""


@dataclass(frozen=True)
class ConfigField:
    metadata_key: str  # the .json/.mat field name (`DATA.md#the-json-document`)
    wire_key: str  # the START command token (`TASKS.md#building-the-line`)
    label: str
    type: str
    default: Any
    # Presentation metadata (`TASKS.md#config-fields`) — all optional, all inert on the wire. A
    # profile that declares none renders exactly as it did before these existed.
    group: str | None = None
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    help: str | None = None
    advanced: bool = False

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "metadataKey": self.metadata_key,
            "wireKey": self.wire_key,
            "label": self.label,
            "type": self.type,
            "default": self.default,
        }
        # Omitted rather than emitted as null: the wire shape declares these
        # optional (absent), not nullable, and the validator enforces that.
        for key, value in (
            ("group", self.group),
            ("unit", self.unit),
            ("min", self.min),
            ("max", self.max),
            ("step", self.step),
            ("help", self.help),
        ):
            if value is not None:
                payload[key] = value
        if self.advanced:
            payload["advanced"] = True
        return payload


@dataclass(frozen=True)
class LiveMetric:
    id: str
    label: str
    trigger_code: int
    success_code: int
    alternate_code: int
    window_size: int

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "triggerCode": self.trigger_code,
            "successCode": self.success_code,
            "alternateCode": self.alternate_code,
            "windowSize": self.window_size,
        }


@dataclass(frozen=True)
class ControlOption:
    """One choice in a ``select`` control — a label + the command it sends."""

    label: str
    command: str

    def to_json(self) -> dict[str, Any]:
        return {"label": self.label, "command": self.command}


@dataclass(frozen=True)
class ControlChannel:
    """One row of a ``grid`` control (`TASKS.md#utility-controls-and-telemetry`) — a named output with its own
    commands and its own live state key."""

    label: str
    state: str | None = None
    toggle: str | None = None
    pulse: str | None = None
    #: The rig channel kind behind the row (`emitter`, `reward`, …), when the
    #: profile says — a generated one always does. Lets Debug Mode colour and
    #: find rows by what they ARE rather than by guessing from their names.
    kind: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"label": self.label}
        if self.state is not None:
            out["state"] = self.state
        if self.kind is not None:
            out["kind"] = self.kind
        if self.toggle is not None:
            out["toggle"] = self.toggle
        if self.pulse is not None:
            out["pulse"] = self.pulse
        return out


@dataclass(frozen=True)
class Control:
    """A utility control the app renders in Debug Mode (`TASKS.md#utility-controls-and-telemetry`).

    ``button`` carries a single ``command``; ``select`` carries ``options`` (each
    with its own command); ``grid`` carries ``channels`` — a row per piece of
    hardware, each with a toggle, a pulse, and a state key. All three send over
    the existing ``port.send`` primitive while the port is in ``PASSTHROUGH``.
    """

    id: str
    label: str
    type: str  # "button" | "select" | "grid"
    command: str | None = None
    options: list[ControlOption] = field(default_factory=list)
    channels: list[ControlChannel] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "label": self.label, "type": self.type}
        if self.type == "button":
            out["command"] = self.command
        elif self.type == "grid":
            out["channels"] = [c.to_json() for c in self.channels]
        else:
            out["options"] = [o.to_json() for o in self.options]
        return out


@dataclass(frozen=True)
class TelemetryField:
    key: str
    label: str

    def to_json(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label}


@dataclass(frozen=True)
class Telemetry:
    """How to parse a utility sketch's non-persisted ``STATUS`` lines (`TASKS.md#utility-controls-and-telemetry`).

    A line from ``port.output`` beginning with ``match`` (default ``"STATUS"``)
    carries space-separated ``key=value`` pairs; ``fields`` names the ones worth
    labelling in the live status strip. Parsing happens client-side off
    ``port.output`` — nothing here is stored (`ARCHITECTURE.md#invariants`).
    """

    match: str
    fields: list[TelemetryField] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"match": self.match, "fields": [f.to_json() for f in self.fields]}


@dataclass(frozen=True)
class Identify:
    """The two commands that make a box announce itself (`TASKS.md#identify`).

    Declared by the sketch, never assumed by the app: "point at box 3" is a
    universal thing to want and ``ON trial_light`` is a Hart-lab detail. A utility
    profile that omits it simply can't be asked, which the guided placement
    walk degrades around rather than refusing.
    """

    on: str
    off: str

    def to_json(self) -> dict[str, Any]:
        return {"on": self.on, "off": self.off}


@dataclass(frozen=True)
class TaskProfile:
    task_name: str
    kind: str = "behavior"
    config: list[ConfigField] = field(default_factory=list)
    strobes: dict[int, str] = field(default_factory=dict)
    live_metrics: list[LiveMetric] = field(default_factory=list)
    controls: list[Control] = field(default_factory=list)
    telemetry: Telemetry | None = None
    identify: Identify | None = None
    #: Names older software wrote into a run document's `sketch` field for this
    #: same task (`TASKS.md#legacy-names`). Only the archive walk reads these, to
    #: decode historical runs whose recorded name isn't a folder name. Declared
    #: rather than inferred on purpose: matching "Shape - L" to `shaping_GL`
    #: by resemblance would be a guess, and a wrong guess decodes real data
    #: with the wrong strobe map.
    legacy_names: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "taskName": self.task_name,
            "kind": self.kind,
            "config": [c.to_json() for c in self.config],
            # Codes are ints internally; the wire/JSON form uses string keys to
            # match the authored task.json exactly.
            "strobes": {str(code): name for code, name in self.strobes.items()},
            "liveMetrics": [m.to_json() for m in self.live_metrics],
            "controls": [c.to_json() for c in self.controls],
            "legacyNames": list(self.legacy_names),
        }
        if self.telemetry is not None:
            out["telemetry"] = self.telemetry.to_json()
        if self.identify is not None:
            out["identify"] = self.identify.to_json()
        return out

    @property
    def end_code(self) -> int | None:
        """The strobe that marks a clean session end (`ARCHITECTURE.md#clean-exit`).

        Identified by name in the strobes map — the code whose name contains
        `END_SESSION` (GRGL's `246 → END_SESSION`). A sketch that declares no
        such code only ends via operator stop or board drop.
        """
        for code, name in self.strobes.items():
            if "END_SESSION" in name.upper():
                return code
        return None


def profile_hash(profile: TaskProfile) -> str:
    """A stable content address for a profile (`TASKS.md#profile-and-params-hashes`).

    Hashes the canonical JSON with sorted keys, so two profiles that mean the
    same thing hash the same regardless of authoring order. Used to snapshot
    which profile decoded a run, and to test whether two runs are comparable
    at all — an equality check on this string rather than a blob comparison.

    Hashing the *serialized* form is deliberate: `TaskProfile` is `frozen` but
    holds a `dict` and lists, so the object itself is unhashable.

    **`strobes` is left out.** A loaded profile's map is the machine's whole
    vocabulary (`TASKS.md#strobe-vocabulary`), so hashing it would split every
    task's history the first time anyone added a code. Codes are never
    renumbered or repurposed, so the map says nothing about whether two runs
    are comparable. Stored hashes were re-keyed once when this changed
    (`cohorts/db.py` `_to_v13`).
    """
    declaration = profile.to_json()
    declaration.pop("strobes", None)
    canonical = json.dumps(declaration, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def params_hash(config: dict[str, Any] | None) -> str | None:
    """A stable content address for one run's task parameters (`TASKS.md#profile-and-params-hashes`).

    The companion to `profile_hash`, and needed for the same reason it was:
    that hash covers the profile *declaration*, which is identical across every
    run of a sketch. Once the values became operator-set, two runs on a 10 ms
    and a 500 ms poke hold started hashing the same — so Analytics would pool
    them onto one axis and call them comparable. Comparability is the pair.

    `None` in, `None` out: a run with no recorded parameters is not the same
    thing as a run recorded with none, and flattening the two would claim a
    pre-v6 run was comparable to a modern default-valued one.
    """
    if config is None:
        return None
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# The snapshot a session file carries (`DATA.md#the-embedded-task-profile`)
# --------------------------------------------------------------------------- #

#: The key a per-animal session document carries its profile snapshot under.
#:
#: Written by `sessions/writer.py`, read here — one constant so the two halves
#: of the contract cannot drift. It is the ONLY nested value in an otherwise
#: flat document, which is deliberate and is why `matwriter` has a rule for it.
SNAPSHOT_KEY = "task_profile"


def embedded_profile(document: dict[str, Any]) -> TaskProfile | None:
    """The profile a session file carries with it, or None.

    **This is what makes a session file self-describing.** A `task.json` lives
    beside its sketch on one machine; the database snapshot that used to be the
    only record of what decoded a run lives on that machine too. Neither
    travels with the data, so a session copied to another rig — the normal case
    in this lab — could previously only be scored against whatever sketch of
    the same name happened to exist there, or inferred from its own strobes.
    Carrying the declaration inside the file makes the copy decode exactly as
    the original does.

    Returns None rather than raising for anything malformed: a file with a
    damaged snapshot is still a file full of real strobes, and the ladder below
    it (`DATA.md#which-profile-decodes-a-run`) still scores it.
    """
    raw = document.get(SNAPSHOT_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        return parse_profile(raw)
    except (TaskProfileError, ValueError) as exc:
        log.warning("a session file's embedded task profile is unusable: %s", exc)
        return None


def recorded_config(
    document: dict[str, Any], profile: TaskProfile | None
) -> dict[str, Any] | None:
    """The parameter values this run actually ran on, out of its own file.

    The document already carries every one of them — `finalize` writes the
    config flat at the top level (`DATA.md#the-json-document`) — but *which* of its keys are parameters
    is a question only the profile answers. With the snapshot beside them, a
    copied run can be given the same `params_hash` its own rig computed, which
    is what completes the comparability pair (`TASKS.md#profile-and-params-hashes`) for data this machine never
    recorded. Without it those runs carry a profile hash and no parameters, and
    two differently-tuned runs of one task pool silently.

    Keyed exactly as `config_metadata` was, so the hash matches: the declared
    fields and nothing else. `trial_seed` and `host_seed` sit beside them in
    the document and are deliberately not declared fields — they describe the
    run, not its tuning, and the recording side never hashed them either.
    """
    if profile is None:
        return None
    values = {
        field.metadata_key: document[field.metadata_key]
        for field in profile.config
        if field.metadata_key in document
    }
    return values or None


def profile_path(sketch_dir: str | Path) -> Path:
    return Path(sketch_dir) / TASK_FILENAME


def load_profile(sketch_dir: str | Path) -> TaskProfile | None:
    """Return the parsed profile, or `None` when the sketch has no `task.json`.

    Raises `TaskProfileError` only when the file exists but is broken.

    **The strobe map comes from the vocabulary, never from the file**
    (`TASKS.md#strobes`). A sketch's `task.json` used to carry its own copy,
    and a copy is a thing that drifts: GRGL_Sim's once declared 23 of the 31
    codes it emitted. A `strobes` key still found in one is ignored, and said
    so once per file.
    """
    from ..rig.registry import vocabulary

    path = profile_path(sketch_dir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise TaskProfileError(f"couldn't read {path.name}: {exc}") from exc
    if isinstance(raw, dict) and "strobes" in raw and str(path) not in _WARNED_STROBES:
        _WARNED_STROBES.add(str(path))
        log.warning(
            "%s declares a strobes map; it is ignored — codes come from the strobe "
            "vocabulary (TASKS.md#strobes)",
            path,
        )
    return parse_profile(raw, vocabulary=vocabulary())


#: Files already warned about a stale `strobes` key. `load_profile` runs on
#: every mapping, every Send START and every analytics index, and once is
#: enough to tell a firmware author.
_WARNED_STROBES: set[str] = set()


def build_legacy_name_index(
    sketches: Iterable[Any],
    load: Callable[[str], TaskProfile | None] = load_profile,
) -> dict[str, str]:
    """Every declared `legacyNames` entry → the sketch path that declares it.

    Reading the whole sketch library to answer one name is fine once and
    ruinous per run: an adopted archive asks the same question for every file
    it holds. Built as a whole index so the answer costs one `task.json` read
    per sketch, not per question.

    First declaration in discovery order wins, matching the picker. A sketch
    whose `task.json` is broken contributes nothing rather than failing the
    build — one bad profile must not hide every other sketch's legacy names.
    """
    index: dict[str, str] = {}
    for sketch in sketches:
        try:
            profile = load(sketch.path)
        except TaskProfileError:
            continue
        if profile is None:
            continue
        for name in profile.legacy_names:
            index.setdefault(name, sketch.path)
    return index


def parse_profile(raw: Any, vocabulary: Vocabulary | None = None) -> TaskProfile:
    """A profile from its JSON form.

    Two callers, and `vocabulary` is what tells them apart:

    * **A sketch's own `task.json`** (`load_profile`, a generated profile) passes
      the vocabulary in force. The `strobes` map is filled from it and any in
      the file is ignored, and `liveMetrics` may name its codes
      (`"trigger": "ODOR_1_ON"`) rather than number them.
    * **A snapshot** — a session file's embedded profile, a stored row — passes
      none, and its own `strobes` map is kept verbatim. That map is the record
      of what decoded the run, not a copy of anything, and it must survive the
      vocabulary changing after the run was recorded.
    """
    if not isinstance(raw, dict):
        raise TaskProfileError("task.json must be a JSON object")

    task_name = raw.get("taskName")
    if not isinstance(task_name, str) or not task_name.strip():
        raise TaskProfileError("task.json needs a non-empty taskName")

    return TaskProfile(
        task_name=task_name,
        kind=_parse_kind(raw.get("kind")),
        config=_parse_config(raw.get("config")),
        strobes=(
            vocabulary.code_map() if vocabulary is not None
            else _parse_strobes(raw.get("strobes"))
        ),
        live_metrics=_parse_metrics(raw.get("liveMetrics"), vocabulary),
        controls=_parse_controls(raw.get("controls")),
        telemetry=_parse_telemetry(raw.get("telemetry")),
        identify=_parse_identify(raw.get("identify")),
        legacy_names=_parse_legacy_names(raw.get("legacyNames")),
    )


def _parse_identify(raw: Any) -> Identify | None:
    """The `identify` pair (`TASKS.md#identify`) — absent is the norm, not an error.

    Both halves are required together: a sketch that can be lit but not
    unlit would leave a box announcing itself forever.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TaskProfileError("identify must be an object")
    on = raw.get("on")
    off = raw.get("off")
    if not isinstance(on, str) or not on.strip():
        raise TaskProfileError("identify.on must be a non-empty command")
    if not isinstance(off, str) or not off.strip():
        raise TaskProfileError("identify.off must be a non-empty command")
    return Identify(on=on.strip(), off=off.strip())


def _parse_legacy_names(raw: Any) -> list[str]:
    """The `legacyNames` list (`TASKS.md#legacy-names`) — absent is the norm, not an error."""
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(n, str) for n in raw):
        raise TaskProfileError("legacyNames must be a list of strings")
    return [n for n in (n.strip() for n in raw) if n]


def _parse_kind(raw: Any) -> str:
    if raw is None:
        return "behavior"  # missing kind = the default scored task
    if raw not in PROFILE_KINDS:
        raise TaskProfileError(f"kind must be one of {sorted(PROFILE_KINDS)}, got {raw!r}")
    return raw


def _opt_str(entry: dict[str, Any], key: str, where: str) -> str | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise TaskProfileError(f"config entry {where}: {key} must be a non-empty string")
    return value


def _opt_num(entry: dict[str, Any], key: str, where: str) -> float | None:
    value = entry.get(key)
    if value is None:
        return None
    # bool first: it is an int subclass, so `"min": true` would otherwise pass.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TaskProfileError(f"config entry {where}: {key} must be a number")
    return value


def _parse_config(raw: Any) -> list[ConfigField]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TaskProfileError("config must be an array")
    fields: list[ConfigField] = []
    seen_metadata: set[str] = set()
    seen_wire: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise TaskProfileError("each config entry must be an object")
        metadata_key = entry.get("metadataKey")
        wire_key = entry.get("wireKey")
        field_type = entry.get("type")
        if not isinstance(metadata_key, str) or not metadata_key:
            raise TaskProfileError("config entry missing metadataKey")
        if not isinstance(wire_key, str) or not wire_key:
            raise TaskProfileError(f"config entry {metadata_key} missing wireKey")
        if field_type not in CONFIG_TYPES:
            raise TaskProfileError(
                f"config entry {metadata_key} has unknown type {field_type!r}"
            )

        # Four ways a profile can be wrong that all fail SILENTLY downstream —
        # a lost value or an overwritten one, with nothing raised at the point
        # the data goes bad. Cheaper to reject the profile here.
        if wire_key in RESERVED_WIRE_KEYS:
            raise TaskProfileError(
                f"config entry {metadata_key} claims the reserved wire key "
                f"{wire_key!r} (TASKS.md#seed) — the app supplies it"
            )
        if metadata_key in CORE_METADATA_KEYS:
            raise TaskProfileError(
                f"config entry {metadata_key} collides with a core session-file "
                f"field (DATA.md#the-json-document); config is merged in flat and would overwrite it"
            )
        if metadata_key in seen_metadata:
            raise TaskProfileError(f"config declares metadataKey {metadata_key!r} twice")
        if wire_key in seen_wire:
            raise TaskProfileError(f"config declares wireKey {wire_key!r} twice")
        seen_metadata.add(metadata_key)
        seen_wire.add(wire_key)

        default = entry.get("default")
        if default is not None and not isinstance(default, _DEFAULT_TYPES[field_type]):
            raise TaskProfileError(
                f"config entry {metadata_key}: default {default!r} is not a {field_type}"
            )
        if field_type != "bool" and isinstance(default, bool):
            raise TaskProfileError(
                f"config entry {metadata_key}: default {default!r} is not a {field_type}"
            )
        if isinstance(default, str) and any(c.isspace() for c in default):
            # The START grammar is space-separated, so this would split into two
            # tokens on the wire and the firmware would drop the tail as a bare
            # word. Rejected here so the *fallback* path in the START builder --
            # which reaches for the default when a user value is unusable --
            # always has something safe to reach for.
            raise TaskProfileError(
                f"config entry {metadata_key}: default {default!r} contains "
                f"whitespace, which the space-separated START grammar cannot carry"
            )

        low = _opt_num(entry, "min", metadata_key)
        high = _opt_num(entry, "max", metadata_key)
        if low is not None and high is not None and low > high:
            raise TaskProfileError(f"config entry {metadata_key}: min is above max")

        fields.append(
            ConfigField(
                metadata_key=metadata_key,
                wire_key=wire_key,
                label=str(entry.get("label") or metadata_key),
                type=field_type,
                default=default,
                group=_opt_str(entry, "group", metadata_key),
                unit=_opt_str(entry, "unit", metadata_key),
                min=low,
                max=high,
                step=_opt_num(entry, "step", metadata_key),
                help=_opt_str(entry, "help", metadata_key),
                advanced=entry.get("advanced") is True,
            )
        )
    return fields


def _parse_strobes(raw: Any) -> dict[int, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TaskProfileError("strobes must be an object")
    out: dict[int, str] = {}
    for code, name in raw.items():
        try:
            out[int(code)] = str(name)
        except (ValueError, TypeError) as exc:
            raise TaskProfileError(f"strobe key {code!r} isn't an integer") from exc
    return out


def _parse_metrics(raw: Any, vocabulary: Vocabulary | None = None) -> list[LiveMetric]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TaskProfileError("liveMetrics must be an array")
    metrics: list[LiveMetric] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise TaskProfileError("each liveMetrics entry must be an object")
        try:
            metrics.append(
                LiveMetric(
                    id=str(entry["id"]),
                    label=str(entry.get("label") or entry["id"]),
                    trigger_code=_metric_code(entry, "trigger", vocabulary),
                    success_code=_metric_code(entry, "success", vocabulary),
                    alternate_code=_metric_code(entry, "alternate", vocabulary),
                    window_size=int(entry.get("windowSize", 20)),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise TaskProfileError(f"liveMetrics entry is malformed: {exc}") from exc
    return metrics


def _metric_code(entry: dict[str, Any], role: str, vocabulary: Vocabulary | None) -> int:
    """One of a metric's three codes, by name (`"trigger"`) or number (`"triggerCode"`).

    BY NAME is how a profile should say it: a number written into `task.json`
    is one more copy of the vocabulary. The numeric key stays readable because
    every snapshot already recorded carries it, and `to_json` writes numbers so
    a name-form and a number-form profile that mean the same thing hash the same.
    """
    name = entry.get(role)
    if name is not None:
        if vocabulary is None:
            raise TaskProfileError(
                f"liveMetrics names its {role} code ({name!r}) but nothing resolved it"
            )
        entry_ = vocabulary.get(str(name))
        if entry_ is None:
            raise TaskProfileError(
                f"liveMetrics {role} {name!r} is not a live code in the strobe vocabulary"
            )
        return entry_.code
    return int(entry[f"{role}Code"])


def _parse_controls(raw: Any) -> list[Control]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TaskProfileError("controls must be an array")
    controls: list[Control] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise TaskProfileError("each controls entry must be an object")
        control_id = entry.get("id")
        if not isinstance(control_id, str) or not control_id:
            raise TaskProfileError("control entry missing id")
        control_type = entry.get("type")
        if control_type not in CONTROL_TYPES:
            raise TaskProfileError(
                f"control {control_id} has unknown type {control_type!r}"
            )
        label = str(entry.get("label") or control_id)
        if control_type == "button":
            command = entry.get("command")
            if not isinstance(command, str) or not command:
                raise TaskProfileError(f"button control {control_id} missing command")
            controls.append(Control(id=control_id, label=label, type="button", command=command))
        elif control_type == "grid":
            channels = _parse_control_channels(control_id, entry.get("channels"))
            controls.append(
                Control(id=control_id, label=label, type="grid", channels=channels)
            )
        else:  # select
            options = _parse_control_options(control_id, entry.get("options"))
            controls.append(
                Control(id=control_id, label=label, type="select", options=options)
            )
    return controls


def _parse_control_channels(control_id: str, raw: Any) -> list[ControlChannel]:
    """Rows of a `grid` control. A row needs a label and at least one thing it
    can do — a row with neither command is inert decoration, which is a
    profile bug worth naming rather than silently rendering."""
    if not isinstance(raw, list) or not raw:
        raise TaskProfileError(f"grid control {control_id} needs a non-empty channels array")
    channels: list[ControlChannel] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise TaskProfileError(f"each {control_id} channel must be an object")
        label = entry.get("label")
        if not isinstance(label, str) or not label:
            raise TaskProfileError(f"a {control_id} channel is missing its label")
        toggle = entry.get("toggle")
        pulse = entry.get("pulse")
        if not isinstance(toggle, str) and not isinstance(pulse, str):
            raise TaskProfileError(
                f"{control_id} channel {label!r} needs a toggle or a pulse command"
            )
        state = entry.get("state")
        kind = entry.get("kind")
        channels.append(
            ControlChannel(
                label=label,
                state=state if isinstance(state, str) and state else None,
                toggle=toggle if isinstance(toggle, str) and toggle else None,
                pulse=pulse if isinstance(pulse, str) and pulse else None,
                kind=kind if isinstance(kind, str) and kind else None,
            )
        )
    return channels


def _parse_control_options(control_id: str, raw: Any) -> list[ControlOption]:
    if not isinstance(raw, list) or not raw:
        raise TaskProfileError(f"select control {control_id} needs a non-empty options array")
    options: list[ControlOption] = []
    for opt in raw:
        if not isinstance(opt, dict):
            raise TaskProfileError(f"select control {control_id} has a non-object option")
        command = opt.get("command")
        if not isinstance(command, str) or not command:
            raise TaskProfileError(f"select control {control_id} option missing command")
        options.append(ControlOption(label=str(opt.get("label") or command), command=command))
    return options


def _parse_telemetry(raw: Any) -> Telemetry | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TaskProfileError("telemetry must be an object")
    match = raw.get("match", "STATUS")
    if not isinstance(match, str) or not match:
        raise TaskProfileError("telemetry.match must be a non-empty string")
    raw_fields = raw.get("fields")
    fields: list[TelemetryField] = []
    if raw_fields is not None:
        if not isinstance(raw_fields, list):
            raise TaskProfileError("telemetry.fields must be an array")
        for entry in raw_fields:
            if not isinstance(entry, dict):
                raise TaskProfileError("each telemetry field must be an object")
            key = entry.get("key")
            if not isinstance(key, str) or not key:
                raise TaskProfileError("telemetry field missing key")
            fields.append(TelemetryField(key=key, label=str(entry.get("label") or key)))
    return Telemetry(match=match, fields=fields)

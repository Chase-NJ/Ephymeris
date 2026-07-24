"""Parse and validate a sketch's `task.json` — `data-saving.md` §6.2.

Kept lenient in one specific way: a **missing** `task.json` is not an error —
it's the fully-supported profile-less case (§6.1). A **malformed** one is an
error, surfaced so the operator can fix it, with the sketch otherwise treated as
profile-less.

Two sketch *kinds* share this file (§6.2):

* ``behavior`` (the default) — a scored ``IN_SESSION`` task, described by
  ``config`` / ``strobes`` / ``liveMetrics``.
* ``utility`` — a ``PASSTHROUGH`` tool (priming, box self-test) the app drives
  with ``controls`` (each maps to a serial command sent over ``port.send``) and
  reads back through ``telemetry`` (how to parse the sketch's non-persisted
  ``STATUS`` lines out of ``port.output``). No new wire commands: utility control
  and status ride the existing passthrough primitives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TASK_FILENAME = "task.json"

#: Config field types the pre-flight form and START builder understand (§6.2).
CONFIG_TYPES = {"int", "float", "bool", "string"}

#: Sketch kinds (§6.2). Anything else is a malformed profile.
PROFILE_KINDS = {"behavior", "utility"}

#: Control widget types a utility profile can declare (§6.6).
CONTROL_TYPES = {"button", "select"}


class TaskProfileError(Exception):
    """`task.json` exists but couldn't be parsed or is structurally invalid."""


@dataclass(frozen=True)
class ConfigField:
    metadata_key: str  # the .json/.mat field name (§5)
    wire_key: str  # the START command token (§6.3)
    label: str
    type: str
    default: Any

    def to_json(self) -> dict[str, Any]:
        return {
            "metadataKey": self.metadata_key,
            "wireKey": self.wire_key,
            "label": self.label,
            "type": self.type,
            "default": self.default,
        }


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
class Control:
    """A utility control the app renders in Debug Mode (§6.6).

    ``button`` carries a single ``command``; ``select`` carries ``options`` (each
    with its own command). Both send over the existing ``port.send`` primitive
    while the port is in ``PASSTHROUGH``.
    """

    id: str
    label: str
    type: str  # "button" | "select"
    command: str | None = None
    options: list[ControlOption] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "label": self.label, "type": self.type}
        if self.type == "button":
            out["command"] = self.command
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
    """How to parse a utility sketch's non-persisted ``STATUS`` lines (§6.6).

    A line from ``port.output`` beginning with ``match`` (default ``"STATUS"``)
    carries space-separated ``key=value`` pairs; ``fields`` names the ones worth
    labelling in the live status strip. Parsing happens client-side off
    ``port.output`` — nothing here is stored (`websocket-protocol.md` §5.4).
    """

    match: str
    fields: list[TelemetryField] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"match": self.match, "fields": [f.to_json() for f in self.fields]}


@dataclass(frozen=True)
class TaskProfile:
    task_name: str
    kind: str = "behavior"
    config: list[ConfigField] = field(default_factory=list)
    strobes: dict[int, str] = field(default_factory=dict)
    live_metrics: list[LiveMetric] = field(default_factory=list)
    controls: list[Control] = field(default_factory=list)
    telemetry: Telemetry | None = None

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
        }
        if self.telemetry is not None:
            out["telemetry"] = self.telemetry.to_json()
        return out

    @property
    def end_code(self) -> int | None:
        """The strobe that marks a clean session end (`starting-a-session.md` §7).

        Identified by name in the strobes map — the code whose name contains
        `END_SESSION` (GRGL's `246 → END_SESSION`). A sketch that declares no
        such code only ends via operator stop or board drop.
        """
        for code, name in self.strobes.items():
            if "END_SESSION" in name.upper():
                return code
        return None


def profile_path(sketch_dir: str | Path) -> Path:
    return Path(sketch_dir) / TASK_FILENAME


def load_profile(sketch_dir: str | Path) -> TaskProfile | None:
    """Return the parsed profile, or `None` when the sketch has no `task.json`.

    Raises `TaskProfileError` only when the file exists but is broken.
    """
    path = profile_path(sketch_dir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise TaskProfileError(f"couldn't read {path.name}: {exc}") from exc
    return parse_profile(raw)


def parse_profile(raw: Any) -> TaskProfile:
    if not isinstance(raw, dict):
        raise TaskProfileError("task.json must be a JSON object")

    task_name = raw.get("taskName")
    if not isinstance(task_name, str) or not task_name.strip():
        raise TaskProfileError("task.json needs a non-empty taskName")

    return TaskProfile(
        task_name=task_name,
        kind=_parse_kind(raw.get("kind")),
        config=_parse_config(raw.get("config")),
        strobes=_parse_strobes(raw.get("strobes")),
        live_metrics=_parse_metrics(raw.get("liveMetrics")),
        controls=_parse_controls(raw.get("controls")),
        telemetry=_parse_telemetry(raw.get("telemetry")),
    )


def _parse_kind(raw: Any) -> str:
    if raw is None:
        return "behavior"  # missing kind = the default scored task
    if raw not in PROFILE_KINDS:
        raise TaskProfileError(f"kind must be one of {sorted(PROFILE_KINDS)}, got {raw!r}")
    return raw


def _parse_config(raw: Any) -> list[ConfigField]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TaskProfileError("config must be an array")
    fields: list[ConfigField] = []
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
        fields.append(
            ConfigField(
                metadata_key=metadata_key,
                wire_key=wire_key,
                label=str(entry.get("label") or metadata_key),
                type=field_type,
                default=entry.get("default"),
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


def _parse_metrics(raw: Any) -> list[LiveMetric]:
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
                    trigger_code=int(entry["triggerCode"]),
                    success_code=int(entry["successCode"]),
                    alternate_code=int(entry["alternateCode"]),
                    window_size=int(entry.get("windowSize", 20)),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise TaskProfileError(f"liveMetrics entry is malformed: {exc}") from exc
    return metrics


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
        else:  # select
            options = _parse_control_options(control_id, entry.get("options"))
            controls.append(
                Control(id=control_id, label=label, type="select", options=options)
            )
    return controls


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

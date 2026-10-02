"""Settings received from the Tauri shell.

The shell owns settings (`ARCHITECTURE.md#who-owns-settings`) and pushes the full payload
here on every connect and every change. This module is the receiving end: it
holds the last payload and reads the handful of keys the sidecar actually
needs.

Parsing is deliberately lenient. Adding a setting the sidecar doesn't consume
is meant to be a non-event, and a malformed value should degrade to the default
rather than take down the process that owns the serial ports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BOX_COUNT = 6
#: Matches the `baudRate` every bundled sketch declares, and the interpreter
#: firmware's `TG_BAUD_RATE`. Only a fallback here — the shell owns the real
#: value and pushes it, and `src/lib/settings/schema.ts` declares the same
#: number in TypeScript. The two must move together.
DEFAULT_BAUD = 115200


@dataclass(frozen=True)
class BoxBinding:
    """Maps a box number to a specific physical board.

    Bound by `hardware_id` (the board's USB serial number) rather than port
    address, because Windows renumbers COM ports across reboots and
    re-enumeration — see `ARCHITECTURE.md#box-bindings`.
    """

    box: int
    hardware_id: str | None = None
    label: str = ""
    #: The recording controller's digital input this box's sync line reaches,
    #: 1-16, or None when the box is not wired for recording.
    intan_digital_in: int | None = None


#: Intan RHX's own defaults (Network -> Remote TCP Control).
INTAN_COMMAND_PORT = 5000
INTAN_WAVEFORM_PORT = 5001
INTAN_SPIKE_PORT = 5002
INTAN_DIGITAL_INPUTS = 16


@dataclass(frozen=True)
class IntanEndpoints:
    """Where RHX's three TCP servers listen. Always on this machine."""

    command_port: int = INTAN_COMMAND_PORT
    waveform_port: int = INTAN_WAVEFORM_PORT
    spike_port: int = INTAN_SPIKE_PORT


@dataclass
class SidecarSettings:
    arduino_cli_path: str | None = None
    #: The sketch every idle box is returned to (`ARCHITECTURE.md#hardware-utility-baseline`), by FOLDER
    #: NAME — the same key `taskDefaults` uses, because the bundled library's
    #: path differs per install while the name is what a session file records.
    #: `None` turns the baseline off entirely — the app is fully usable without
    #: one, it just can't ask a box to point at itself.
    utility_sketch_name: str | None = None
    #: Where session output lives. Used as the base for new cohorts' data
    #: folders (`DATA.md#data-folder`) — distinct from the app data directory that
    #: holds the cohort database (`DATA.md#sqlite-database`).
    data_directory: str | None = None
    #: Where session data and `ephymeris.db` are mirrored
    #: (`DATA.md#backup-mirroring`). Protects against losing `data_directory` entirely — a different
    #: failure from the one the `.tsv` write-ahead log covers. `None` turns
    #: mirroring off; the app is fully usable without it.
    backup_directory: str | None = None
    default_baud: int = DEFAULT_BAUD
    boxes: list[BoxBinding] = field(default_factory=list)
    intan: IntanEndpoints = field(default_factory=IntanEndpoints)

    @classmethod
    def from_payload(cls, payload: Any) -> "SidecarSettings":
        if not isinstance(payload, dict):
            log.warning("settings payload was not an object; using defaults")
            return cls(boxes=_default_boxes())

        return cls(
            arduino_cli_path=_opt_str(payload.get("arduinoCliPath")),
            utility_sketch_name=_utility_sketch_name(payload),
            data_directory=_opt_str(payload.get("dataDirectory")),
            backup_directory=_opt_str(payload.get("backupDirectory")),
            default_baud=_baud(payload.get("defaultBaud")),
            boxes=_boxes(payload.get("boxes")),
            intan=_intan(payload.get("intan")),
        )

    def binding_for(self, box: int) -> BoxBinding | None:
        return next((b for b in self.boxes if b.box == box), None)

    def hardware_id_for(self, box: int) -> str | None:
        binding = self.binding_for(box)
        return binding.hardware_id if binding else None


def _opt_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _utility_sketch_name(payload: dict) -> str | None:
    """Read the baseline sketch, healing the retired path-valued key.

    Until sketches shipped with the app this was `utilitySketchPath`, an absolute
    path into the user's Arduino Directory. The shell migrates its own store the
    same way, so this branch should never fire on a paired build — it exists for
    the unpaired case (an old store pushed verbatim by a dev shell), where
    silently losing the baseline would mean six boxes quietly stop returning to
    it. The basename of the old path IS the sketch's folder name, because
    arduino-cli requires `<folder>/<folder>.ino`.
    """
    name = _opt_str(payload.get("utilitySketchName"))
    if name is not None:
        return name
    legacy = _opt_str(payload.get("utilitySketchPath"))
    if legacy is not None:
        return Path(legacy).name or None
    return None


def _baud(value: Any) -> int:
    if isinstance(value, bool):  # bool is an int subclass; not a baud rate
        return DEFAULT_BAUD
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return DEFAULT_BAUD
        return parsed if parsed > 0 else DEFAULT_BAUD
    return DEFAULT_BAUD


def _port(value: Any, fallback: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value if 1 <= value <= 65535 else fallback


def _intan(value: Any) -> IntanEndpoints:
    if not isinstance(value, dict):
        return IntanEndpoints()
    return IntanEndpoints(
        command_port=_port(value.get("commandPort"), INTAN_COMMAND_PORT),
        waveform_port=_port(value.get("waveformPort"), INTAN_WAVEFORM_PORT),
        spike_port=_port(value.get("spikePort"), INTAN_SPIKE_PORT),
    )


def _digital_in(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value <= INTAN_DIGITAL_INPUTS else None


def _default_boxes() -> list[BoxBinding]:
    return [BoxBinding(box=n, label=f"Box {n}") for n in range(1, BOX_COUNT + 1)]


def _boxes(value: Any) -> list[BoxBinding]:
    if not isinstance(value, list):
        return _default_boxes()

    by_number: dict[int, BoxBinding] = {}
    # Two boxes on one digital input are indistinguishable in the recording --
    # every edge would be matched against both strobe streams. The first claim
    # stands and the second is dropped, so the later box reads as "not wired"
    # and the recording walkthrough refuses it, rather than both recording
    # plausibly and wrongly.
    claimed: set[int] = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        number = raw.get("box")
        if not isinstance(number, int) or not 1 <= number <= BOX_COUNT:
            continue
        digital_in = _digital_in(raw.get("intanDigitalIn"))
        if digital_in is not None and digital_in in claimed:
            log.warning("box %d repeats DIGITAL-IN-%d; ignoring it", number, digital_in)
            digital_in = None
        if digital_in is not None:
            claimed.add(digital_in)
        by_number[number] = BoxBinding(
            box=number,
            hardware_id=_opt_str(raw.get("hardwareId")),
            label=_opt_str(raw.get("label")) or f"Box {number}",
            intan_digital_in=digital_in,
        )

    # Always return all six, so callers never have to handle a missing box.
    return [by_number.get(n, BoxBinding(box=n, label=f"Box {n}")) for n in range(1, BOX_COUNT + 1)]

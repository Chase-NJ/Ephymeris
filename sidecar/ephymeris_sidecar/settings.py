"""Settings received from the Tauri shell.

The shell owns settings (`ephymeris_v1.0.md` §4.5) and pushes the full payload
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
from typing import Any

log = logging.getLogger(__name__)

BOX_COUNT = 6
DEFAULT_BAUD = 115200


@dataclass(frozen=True)
class BoxBinding:
    """Maps a box number to a specific physical board.

    Bound by `hardware_id` (the board's USB serial number) rather than port
    address, because Windows renumbers COM ports across reboots and
    re-enumeration — see `ephymeris_v1.0.md` §5.
    """

    box: int
    hardware_id: str | None = None
    label: str = ""


@dataclass
class SidecarSettings:
    arduino_directory: str | None = None
    arduino_cli_path: str | None = None
    #: Where session output lives. Used as the base for new cohorts' data
    #: folders (`cohorts.md` §8) — distinct from the app data directory that
    #: holds the cohort database (§3).
    data_directory: str | None = None
    default_baud: int = DEFAULT_BAUD
    boxes: list[BoxBinding] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: Any) -> "SidecarSettings":
        if not isinstance(payload, dict):
            log.warning("settings payload was not an object; using defaults")
            return cls(boxes=_default_boxes())

        return cls(
            arduino_directory=_opt_str(payload.get("arduinoDirectory")),
            arduino_cli_path=_opt_str(payload.get("arduinoCliPath")),
            data_directory=_opt_str(payload.get("dataDirectory")),
            default_baud=_baud(payload.get("defaultBaud")),
            boxes=_boxes(payload.get("boxes")),
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


def _default_boxes() -> list[BoxBinding]:
    return [BoxBinding(box=n, label=f"Box {n}") for n in range(1, BOX_COUNT + 1)]


def _boxes(value: Any) -> list[BoxBinding]:
    if not isinstance(value, list):
        return _default_boxes()

    by_number: dict[int, BoxBinding] = {}
    for raw in value:
        if not isinstance(raw, dict):
            continue
        number = raw.get("box")
        if not isinstance(number, int) or not 1 <= number <= BOX_COUNT:
            continue
        by_number[number] = BoxBinding(
            box=number,
            hardware_id=_opt_str(raw.get("hardwareId")),
            label=_opt_str(raw.get("label")) or f"Box {number}",
        )

    # Always return all six, so callers never have to handle a missing box.
    return [by_number.get(n, BoxBinding(box=n, label=f"Box {n}")) for n in range(1, BOX_COUNT + 1)]

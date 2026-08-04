"""Settings received from the Tauri shell.

The shell owns settings (`settings.md` §4) and pushes the full payload
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
    re-enumeration — see `README.md` §1.
    """

    box: int
    hardware_id: str | None = None
    label: str = ""


@dataclass
class SidecarSettings:
    arduino_cli_path: str | None = None
    #: The sketch every idle box is returned to (`settings.md` §8), by FOLDER
    #: NAME — the same key `taskDefaults` uses, because the bundled library's
    #: path differs per install while the name is what a session file records.
    #: `None` turns the baseline off entirely — the app is fully usable without
    #: one, it just can't ask a box to point at itself.
    utility_sketch_name: str | None = None
    #: Where session output lives. Used as the base for new cohorts' data
    #: folders (`cohorts.md` §8) — distinct from the app data directory that
    #: holds the cohort database (§3).
    data_directory: str | None = None
    #: Where session data and `ephymeris.db` are mirrored (`data.md`
    #: §8). Protects against losing `data_directory` entirely — a different
    #: failure from the one the `.tsv` write-ahead log covers. `None` turns
    #: mirroring off; the app is fully usable without it.
    backup_directory: str | None = None
    default_baud: int = DEFAULT_BAUD
    boxes: list[BoxBinding] = field(default_factory=list)

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

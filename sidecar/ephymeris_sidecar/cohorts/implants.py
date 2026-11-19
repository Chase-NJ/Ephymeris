"""An animal's implant — `DATA.md#implants`.

Entered once, on the animal: the device, when it went in, an optional probe
map, its **targets** (`GLOSSARY.md#target`: a group of the device's channels
at one place in the brain) and the dated lowerings of its drive. Kept in the
wire's own shape (`protocol/schema.py`'s `Implant`), as JSON, in a table
keyed by the animal's id.

**Its own table, with no foreign key.** `cohorts.update` deletes and
re-inserts every `animals` row on each roster save (`DATA.md#indexes`), so an
implant stored on that row, or cascading from it, would be wiped by a rename.
Keyed by id alone, it follows the animal through a rename, a removal to a
former member and a move between cohorts.

**Channels are numbered on the device**, never by RHX's native name, which
depends on the port and range the box was given that day
(`RECORDING.md#record-step`).
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import UTC, date, datetime
from typing import Any, Iterable

TABLE = "implants"

HEMISPHERES = ("left", "right", "midline")

#: The highest channel number a device can have: RHX's largest controller.
MAX_CHANNEL = 1023

_COORDINATES = (("apMm", "AP"), ("mlMm", "ML"), ("dvMm", "DV"))


class ImplantError(ValueError):
    """An implant that cannot be meant, said in words for the editor."""


def parse_channels(spec: Any) -> list[int]:
    """A target's channels on the device: a range (`0-15`), a list (`0,2,4`)
    or both (`0-3,8,10-11`), in the order written. Raises `ImplantError` for
    anything else, and for a channel named twice."""
    if not isinstance(spec, str) or not spec.strip():
        raise ImplantError("channels are a range such as 0-15 or a list such as 0,2,4")
    out: list[int] = []
    for part in spec.split(","):
        first, dash, last = part.strip().partition("-")
        first, last = first.strip(), last.strip()
        if not first.isdigit() or (dash and not last.isdigit()):
            raise ImplantError(f"channels {spec.strip()!r} are not a range such as 0-15 or a list such as 0,2,4")
        low, high = int(first), int(last) if dash else int(first)
        if high < low or high > MAX_CHANNEL:
            raise ImplantError(f"channels {part.strip()!r} do not name a range of the device's channels")
        out.extend(range(low, high + 1))
    if len(set(out)) != len(out):
        raise ImplantError(f"channels {spec.strip()!r} name a channel twice")
    return out


def parse_implant(raw: Any) -> dict[str, Any]:
    """The implant as stored and sent (`Implant` on the wire): text trimmed,
    lowerings in date order. Raises `ImplantError` saying what is wrong."""
    if not isinstance(raw, dict):
        raise ImplantError("an implant is an object")
    device = _text(raw.get("device"))
    if not device:
        raise ImplantError("give the device a name")
    surgery = _date(raw.get("surgeryDate"), "the surgery date")

    targets_raw = raw.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        raise ImplantError("an implant needs at least one target")
    targets: list[dict[str, Any]] = []
    claimed: dict[int, str] = {}
    names: set[str] = set()
    for item in targets_raw:
        entry = _target(item)
        key = entry["name"].casefold()
        if key in names:
            raise ImplantError(f"two targets called {entry['name']!r}")
        names.add(key)
        for channel in parse_channels(entry["channels"]):
            if channel in claimed:
                raise ImplantError(
                    f"{claimed[channel]} and {entry['name']} both claim channel {channel}"
                )
            claimed[channel] = entry["name"]
        targets.append(entry)

    lowerings_raw = raw.get("lowerings") or []
    if not isinstance(lowerings_raw, list):
        raise ImplantError("lowerings are a list")
    lowerings = sorted((_lowering(item, surgery) for item in lowerings_raw), key=lambda entry: entry["date"])

    probe_map = _text(raw.get("probeMapPath"))
    return {
        "device": device,
        "surgeryDate": surgery,
        "probeMapPath": probe_map or None,
        "targets": targets,
        "lowerings": lowerings,
    }


def _target(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ImplantError("each target is an object")
    name = _text(raw.get("name"))
    if not name:
        raise ImplantError("every target needs a name")
    hemisphere = raw.get("hemisphere")
    if hemisphere not in HEMISPHERES:
        raise ImplantError(f"{name}: hemisphere is {', '.join(HEMISPHERES[:-1])} or {HEMISPHERES[-1]}")
    out: dict[str, Any] = {"name": name, "region": _text(raw.get("region")), "hemisphere": hemisphere}
    for key, label in _COORDINATES:
        out[key] = _number(raw.get(key), f"{name}: {label} is a number of millimetres")
    try:
        parse_channels(raw.get("channels"))
    except ImplantError as exc:
        raise ImplantError(f"{name}: {exc}") from exc
    out["channels"] = raw["channels"].strip()
    return out


def _lowering(raw: Any, surgery: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ImplantError("each lowering is an object")
    when = _date(raw.get("date"), "a lowering's date")
    if when < surgery:
        raise ImplantError(f"a lowering on {when} is before the surgery ({surgery})")
    mm = _number(raw.get("mm"), "a lowering's distance is a number of millimetres")
    if mm == 0:
        raise ImplantError("a lowering's distance cannot be 0")
    return {"date": when, "mm": mm}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _date(value: Any, what: str) -> str:
    try:
        return date.fromisoformat(value).isoformat() if isinstance(value, str) else _refuse_date(what)
    except ValueError:
        return _refuse_date(what)


def _refuse_date(what: str) -> str:
    raise ImplantError(f"{what} is a date such as 2026-11-30")


def _number(value: Any, problem: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ImplantError(problem)
    return value


def depth_on(implant: dict[str, Any], target: dict[str, Any], on: str) -> tuple[float, str]:
    """A target's depth on a date, and the date that depth was set: its DV at
    surgery plus every lowering on or before `on`; the surgery date when none
    had happened yet.

    One drive carries the whole electrode, so a lowering moves every target by
    its distance. A lowering moves the contacts to other neurons, which is why
    the date travels with the depth: runs that share it were recorded in one
    place.
    """
    past = [entry for entry in implant.get("lowerings", []) if entry["date"] <= on]
    depth = target["dvMm"] + sum(entry["mm"] for entry in past)
    return round(depth, 6), max((entry["date"] for entry in past), default=implant["surgeryDate"])


# --- storage (`DATA.md#implants`) ------------------------------------------------ #

def load(conn: sqlite3.Connection, animal_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Each of these animals' implants, by id; an animal with none is absent."""
    ids = list(animal_ids)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out: dict[str, dict[str, Any]] = {}
    for row in conn.execute(f"SELECT animal_id, implant_json FROM {TABLE} WHERE animal_id IN ({marks})", ids):
        try:
            out[row["animal_id"]] = json.loads(row["implant_json"])
        except ValueError:  # pragma: no cover - only a hand-edited database
            continue
    return out


def save(conn: sqlite3.Connection, animal_id: str, implant: dict[str, Any] | None) -> None:
    """Store this animal's implant, or with None remove it."""
    if implant is None:
        conn.execute(f"DELETE FROM {TABLE} WHERE animal_id = ?", (animal_id,))
        return
    conn.execute(
        f"INSERT OR REPLACE INTO {TABLE} (animal_id, implant_json, updated_at) VALUES (?, ?, ?)",
        (animal_id, json.dumps(implant), datetime.now(UTC).isoformat(timespec="seconds")),
    )


def follow(conn: sqlite3.Connection, old_id: str, new_id: str) -> None:
    """A move joined `old_id` into `new_id` (`DATA.md#moving-animals-between-cohorts`):
    the implant goes with it, unless the animal it joins has its own, which stands."""
    conn.execute(f"UPDATE OR IGNORE {TABLE} SET animal_id = ? WHERE animal_id = ?", (new_id, old_id))
    conn.execute(f"DELETE FROM {TABLE} WHERE animal_id = ?", (old_id,))

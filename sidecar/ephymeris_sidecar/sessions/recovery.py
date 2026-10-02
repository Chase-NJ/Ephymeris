"""Crash-recovery backfill — `DATA.md#crash-recovery`.

If the machine loses power mid-session, every strobe up to that moment is
durably on disk in the write-ahead `.tsv` — but `.json`/`.mat` are built only
at clean finalization (`DATA.md#built-once-at-the-end`), so they were never produced. This module reads
an orphaned `.tsv` back and rebuilds both structured formats from it.

This is **not** session resumption (out of scope by decision, `DATA.md#what-is-guaranteed`): nothing
here talks to a board or reopens a run. It is a pure file transformation, the
inverse of `writer.AnimalWriter` — parse the `# key: value` header, the
`<code>\t<timestamp>` lines, and the optional footer; emit the same
document `finalize` would have (`DATA.md#the-json-document`).

Two honesty rules:

* **A footer wins.** A `.tsv` that carries `# stop_reason` finalized cleanly
  and only the best-effort `.json` write failed (disk full — finalization logs and
  moves on). Its recorded reason is the truth; stamping it "recovered after
  crash" would erase why the run actually ended. Only a footer-less log —
  a genuine crash — gets the marker.
* **Recovered counts are parsed counts.** `n_events` is recomputed from the
  lines actually read, never copied from a footer, so the document can't
  claim more events than it holds.

Discovery reuses the same archive walker as orphan adoption
(`DATA.md#orphan-adoption`, `reader.walk_orphaned_tsvs`) — both must see every legacy layout a
real archive has, so they are one traversal by decision (`DATA.md#crash-recovery`).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..analytics import reader
from ..tasks.profile import SNAPSHOT_KEY
from . import matwriter

log = logging.getLogger(__name__)

#: The stop reason a footer-less (crashed) recovery records (`DATA.md#crash-recovery`).
RECOVERED_STOP_REASON = "recovered after crash"

#: The board's exact line format — the same strict rule the live session
#: parser applies (`ARCHITECTURE.md#entering-in_session`), so recovery can't admit a
#: line the session wouldn't have.
_STROBE = re.compile(r"^(\d{1,3})\t(\d+)$")

#: Core fields (`DATA.md#the-json-document`) that are always strings, exempt from value coercion — an
#: animal named "123" must not come back as an integer.
_STRING_FIELDS = frozenset(
    {
        "rat", "serial_port", "session_id", "sketch",
        # An RHX base filename like "0423_7" must not come back as a number.
        "intan_recording", "intan_path", "intan_port", "intan_channels",
    }
)

#: Footer keys `finalize` appends after the data (`DATA.md#the-tsv-log`) — never header fields.
_FOOTER_KEYS = frozenset({"stop_reason", "n_events"})

#: Header fields whose value is a JSON document rather than a rendered scalar
#: (`DATA.md#the-embedded-task-profile`). Read back as the object they are, so a recovered `.json` is as
#: self-describing as a finalized one — which is the whole point of the
#: snapshot: the recovered file is exactly the one likely to be carried to
#: another machine to find out what happened.
_JSON_FIELDS = frozenset({SNAPSHOT_KEY})


@dataclass(frozen=True)
class ParsedTsv:
    """What one write-ahead log holds, however far it got before stopping."""

    metadata: dict[str, Any]
    events: list[list[int]]
    #: The footer's recorded reason, when the file has one — its presence is
    #: what distinguishes "finalized but the .json write failed" from "crashed".
    stop_reason: str | None


def parse_tsv(path: Path) -> ParsedTsv:
    """Read a `.tsv` back into header, events, and optional footer.

    Tolerant exactly where a crash makes tolerance necessary: a torn final
    line (power died mid-write, `DATA.md#what-is-guaranteed`) matches neither rule and contributes
    nothing, costing at most the one strobe the guarantee already declares at risk.
    Everything else is strict — a line is a `# key: value` comment or a
    board-format strobe, and anything unrecognized is skipped, not guessed at.
    """
    metadata: dict[str, Any] = {}
    events: list[list[int]] = []
    stop_reason: str | None = None

    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if line.startswith("# "):
                key, sep, value = line[2:].partition(": ")
                if not sep:
                    continue
                if key == "stop_reason":
                    stop_reason = value
                elif key in _JSON_FIELDS:
                    # Dropped rather than kept as text when it doesn't parse.
                    # A header line torn by the crash that stopped the session
                    # is the realistic way to get here, and half a snapshot
                    # that every reader has to defend against is worse than
                    # none: the ladder below it (`DATA.md#which-profile-decodes-a-run`) still scores the run.
                    decoded = _decode_json(value)
                    if decoded is not None:
                        metadata[key] = decoded
                elif key not in _FOOTER_KEYS:
                    metadata[key] = _coerce(key, value)
                continue
            match = _STROBE.match(line)
            if match is not None:
                events.append([int(match.group(1)), int(match.group(2))])

    return ParsedTsv(metadata=metadata, events=events, stop_reason=stop_reason)


def recover_file(tsv_path: Path) -> dict[str, Any]:
    """Backfill one orphaned `.tsv`'s `.json` and `.mat` (`DATA.md#crash-recovery`).

    Returns one wire-shaped `RecoveredTsv` entry. The `.json` is the recovery
    — a failure writing it fails the entry. The `.mat` stays best-effort,
    mirroring `finalize` (`DATA.md#built-once-at-the-end`): by then the recovered document is durably on
    disk twice over.
    """
    entry: dict[str, Any] = {
        "tsvPath": str(tsv_path),
        "jsonPath": None,
        "status": "failed",
        "nEvents": 0,
        "stopReason": None,
        "reason": None,
    }
    try:
        parsed = parse_tsv(tsv_path)
    except OSError as exc:
        entry["reason"] = f"couldn't read the .tsv: {exc}"
        return entry

    if not parsed.metadata and not parsed.events:
        # Nothing recognizable — a stray .tsv someone dropped in the folder,
        # not a session log. Refuse rather than minting an empty document.
        entry["reason"] = "no header or strobe lines — not a session .tsv"
        return entry

    stop_reason = parsed.stop_reason or RECOVERED_STOP_REASON
    document = dict(parsed.metadata)
    document["stop_reason"] = stop_reason
    document["n_events"] = len(parsed.events)
    document["ts_data"] = parsed.events

    json_path = reader.sibling_json(tsv_path)
    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    except OSError as exc:
        entry["reason"] = f"couldn't write {json_path.name}: {exc}"
        return entry

    mat_path = reader.sibling_mat(tsv_path)
    try:
        mat_path.parent.mkdir(parents=True, exist_ok=True)
        matwriter.savemat(str(mat_path), document)
    except OSError as exc:
        log.error("couldn't write %s: %s", mat_path, exc)

    entry.update(
        {
            "jsonPath": str(json_path),
            "status": "recovered",
            "nEvents": len(parsed.events),
            "stopReason": stop_reason,
        }
    )
    return entry


def recover_cohort(data_folder: str) -> dict[str, Any]:
    """Find and recover every orphaned `.tsv` under one cohort's data folder.

    The result is the `RecoverResult` wire shape minus `cohortId`, which the
    command handler adds — this function only knows folders. `folderMissing`
    mirrors `analytics.rescan`'s: "nothing there" and "nowhere to look" are
    different answers.
    """
    folder_exists = Path(data_folder).expanduser().is_dir()
    orphans = reader.walk_orphaned_tsvs(data_folder) if folder_exists else []
    entries = [recover_file(path) for path in orphans]
    recovered = sum(1 for e in entries if e["status"] == "recovered")
    return {
        "scanned": len(orphans),
        "recovered": recovered,
        "failed": len(entries) - recovered,
        "entries": entries,
        "dataFolder": data_folder,
        "folderMissing": not folder_exists,
    }


def _decode_json(value: str) -> Any | None:
    try:
        decoded = json.loads(value)
    except ValueError:
        log.warning("a .tsv header carries an unparseable JSON field; dropping it")
        return None
    return decoded if isinstance(decoded, dict) else None


def _coerce(key: str, value: str) -> Any:
    """Undo the header's string rendering (`writer._render`) — best effort.

    The header renders every value as text, so types must be read back out:
    lowercase booleans exactly as `_render` spells them, then numbers, then
    the string itself. Core fields (`_STRING_FIELDS`) skip all of it — they are defined as
    strings whatever they look like.
    """
    if key in _STRING_FIELDS:
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value

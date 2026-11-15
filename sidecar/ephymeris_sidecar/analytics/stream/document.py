"""The strobe stream out of a finalized run's document — `ANALYTICS.md#run-level-scalars`.

A run's `.json` holds its stream as `ts_data`, `[[code, timestamp], …]`
(`DATA.md#the-json-document`). Everything else in `stream/` reads it through
here, so a malformed row is skipped the same way everywhere.
"""

from __future__ import annotations

from typing import Any


def codes_of(document: dict[str, Any]) -> list[int]:
    """The strobe codes out of `ts_data`, skipping malformed rows.

    `ts_data` is `[[code, timestamp], …]` (`DATA.md#the-json-document`), but a
    hand-edited or recovery-produced file can hold anything, and an
    `IndexError` escaping from a worker thread would take out an indexing pass
    over an entire cohort.
    """
    raw = document.get("ts_data")
    if not isinstance(raw, list):
        return []
    codes: list[int] = []
    for pair in raw:
        if isinstance(pair, (list, tuple)) and len(pair) >= 1:
            code = pair[0]
            if isinstance(code, int) and not isinstance(code, bool):
                codes.append(code)
    return codes


def _pairs_of(document: dict[str, Any]) -> list[tuple[int, int | None]]:
    """`(code, timestamp | None)` pairs, aligned with `codes_of`'s output.

    One pass rather than a zip of `codes_of` and `_timestamps`: those two skip
    malformed rows *independently*, so on a file where one row has a bad code
    and another a bad timestamp, zipping their outputs silently offsets every
    later timestamp by a row. Filtering on the code here — the same rule
    `codes_of` applies — keeps index *i* of this list the same event as index
    *i* of that one, with the timestamp merely `None` where it is unusable.
    """
    raw = document.get("ts_data")
    if not isinstance(raw, list):
        return []
    out: list[tuple[int, int | None]] = []
    for pair in raw:
        if isinstance(pair, (list, tuple)) and len(pair) >= 1:
            code = pair[0]
            if isinstance(code, int) and not isinstance(code, bool):
                ts = pair[1] if len(pair) >= 2 else None
                if not isinstance(ts, int) or isinstance(ts, bool):
                    ts = None
                out.append((code, ts))
    return out


def _duration_ms(document: dict[str, Any]) -> int | None:
    """Wall span of the recorded stream, or `None` under two events.

    `max - min` rather than `last - first`. The board's clock is monotonic and a
    finalized file is written in arrival order, so on real data the two agree
    exactly — but a hand-edited or concatenated file need not be ordered, and
    `last - first` on one of those yields a *negative* duration, which then
    flows into a session tile as a nonsense figure rather than being caught.
    A span can't be negative, which is the whole reason to compute it that way.
    """
    stamps = _timestamps(document)
    if len(stamps) < 2:
        return None
    return max(stamps) - min(stamps)


def _timestamps(document: dict[str, Any]) -> list[int]:
    raw = document.get("ts_data")
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for pair in raw:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            ts = pair[1]
            if isinstance(ts, int) and not isinstance(ts, bool):
                out.append(ts)
    return out

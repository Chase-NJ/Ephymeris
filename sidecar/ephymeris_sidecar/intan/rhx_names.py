"""RHX's native channel names — `RECORDING.md#record-step`.

A headstage channel is named by its port and its number on that port
(`A-016`), and a box's range is written first to last (`A-016:A-031`).
Standard library only, so the session runner and the offline reader share it.
"""

from __future__ import annotations

from typing import Any


def channel_names(spec: Any) -> list[str]:
    """`"A-016:A-031"` → A-016 … A-031; nothing for anything else."""
    if not isinstance(spec, str) or ":" not in spec:
        return []
    first, last = (part.strip().upper() for part in spec.split(":", 1))
    port, _, a = first.partition("-")
    port2, _, b = last.partition("-")
    if port != port2 or not a.isdigit() or not b.isdigit():
        return []
    return [f"{port}-{n:03d}" for n in range(int(a), int(b) + 1)]


def recording_folder_name(base_filename: str, file_timestamp: str | None) -> str:
    """The folder RHX saves one recording into: the base filename, then the
    timestamp RHX stamped it with once it started (`RECORDING.md#what-is-written`)."""
    return f"{base_filename}_{file_timestamp}" if file_timestamp else base_filename

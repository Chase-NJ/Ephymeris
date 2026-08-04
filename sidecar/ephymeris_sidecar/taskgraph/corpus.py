"""Loading recorded sessions.

The corpus lives outside this repo — it is real behavioural data — so nothing here
writes to it and no path is hard-coded into a test. `TASKGRAPH_CORPUS` or an
explicit argument points at it; absent that, the corpus tests skip rather than
fail, because a checkout on a machine with no data is not a broken checkout.

A recorded session is a JSON document whose `ts_data` is a list of
`[code, milliseconds]` pairs, plus the merged parameter values the run used
(docs/tasks.md §5).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

#: Codes that reveal which firmware generation produced a session.
#:
#: Ephymeris records that LIGHTS_OFF, WATER_UNPOKE_L and WATER_UNPOKE_R "were dead
#: for a while — declared, wired to real hardware events, and never strobed." A
#: session containing any of them post-dates that fix; one containing none of them
#: pre-dates it. That single bit splits the corpus cleanly, and it is the
#: difference between a session the current graph can explain and one it cannot.
MODERN_MARKERS = frozenset({233, 254, 255})


@dataclass(frozen=True)
class Session:
    path: Path
    sketch: str | None
    rat: str | None
    session_id: str | None
    seed: int | None
    stop_reason: str | None
    events: tuple[tuple[int, int], ...]
    params: dict

    @property
    def codes(self) -> set[int]:
        return {c for c, _ in self.events}

    @property
    def modern(self) -> bool:
        """True when the session was produced by firmware that emits the three
        once-dead codes."""
        return bool(self.codes & MODERN_MARKERS)

    @property
    def generation(self) -> str:
        return "modern" if self.modern else "legacy"

    def __len__(self) -> int:
        return len(self.events)


def corpus_root(explicit: str | Path | None = None) -> Path | None:
    """Where the recordings live, or None if this machine has none."""
    for candidate in (
        explicit,
        os.environ.get("TASKGRAPH_CORPUS"),
        Path.home() / "Documents" / "Hart Lab" / "04_Data" / "00_Behavior",
    ):
        if candidate:
            p = Path(candidate).expanduser()
            if p.is_dir():
                return p
    return None


def load_session(path: Path) -> Session | None:
    """Parse one session file. Returns None for anything that is not one.

    Tolerant on purpose: the data directory holds sidecar files and notes as well
    as sessions, and a loader that raised on the first of those would make the
    corpus unusable for the sake of being strict about files it does not own.
    """
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("ts_data"), list):
        return None

    events: list[tuple[int, int]] = []
    for row in d["ts_data"]:
        if isinstance(row, list | tuple) and len(row) == 2:
            try:
                events.append((int(row[0]), int(row[1])))
            except (TypeError, ValueError):
                return None
    if not events:
        return None

    core = {"rat", "serial_port", "session_id", "sketch", "stop_reason",
            "n_events", "ts_data", "trial_seed", "host_seed"}
    return Session(
        path=path,
        sketch=d.get("sketch"),
        rat=d.get("rat"),
        session_id=d.get("session_id"),
        seed=d.get("trial_seed"),
        stop_reason=d.get("stop_reason"),
        events=tuple(events),
        params={k: v for k, v in d.items() if k not in core},
    )


def load_corpus(root: str | Path | None = None, sketch: str | None = None) -> list[Session]:
    """Every session under `root`, optionally filtered to one sketch."""
    base = corpus_root(root)
    if base is None:
        return []
    out = []
    for f in sorted(base.rglob("*.json")):
        s = load_session(f)
        if s is None:
            continue
        if sketch is None or s.sketch == sketch:
            out.append(s)
    return out

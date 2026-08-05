"""Loading recorded sessions.

The corpus lives outside this repo — it is real behavioural data — so nothing here
writes to it and no path is hard-coded into a test. `TASKGRAPH_CORPUS` or an
explicit argument points at it; absent that, the corpus tests skip rather than
fail, because a checkout on a machine with no data is not a broken checkout.

A recorded session is a JSON document whose `ts_data` is a list of
`[code, milliseconds]` pairs, plus the merged parameter values the run used
(docs/tasks.md §5).

It also carries no firmware version, which is why `Session.generation` derives one
from the stream: the corpus spans the 2026-08-03 conformance cutover, and a session
is only explainable by the graph of the firmware that produced it
(docs/TaskGraph.md §7.1).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .registries import vocabulary

#: The behavioural strobes that share an instant with `LIGHTS_OFF` on an abort.
#:
#: All three abort paths in `runTrial()` drop the house light and announce what the
#: animal did in the same firmware instant, so the two strobes carry identical
#: timestamps and only their ORDER separates the generations. Template v1 put
#: `LIGHTS_OFF` first; v2 always puts the behavioural strobe first, which is what
#: let the `cue_off_placement` knob be deleted rather than kept for a quirk (D21).
ABORT_PARTNERS = ("LAZY_RAT", "ODOR_UNPOKE_EARLY")

#: Emitted only by v2 firmware, and the reason `generation` does not rest on the
#: ordering alone: a v2 session in which no animal ever ran the response window
#: out has no abort ordering to read, but an omission is unambiguous.
V2_ONLY = ("RESP_OMIT",)


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
    def generation(self) -> str:
        """Which template generation explains this recording: `"v1"` or `"v2"`.

        NOT A TEST FOR WHICH CODES APPEAR, and the difference matters. `LIGHTS_OFF`,
        `WATER_UNPOKE_L` and `WATER_UNPOKE_R` were dead for a while and started
        being emitted on 2026-07-31, three days before the ordering changed. That
        looks like the same cutover and is not: those sessions still carry v1
        ordering and are still explained by the as-built graph. Splitting on code
        presence files eleven of them against the model, which rejects them.

        A recording with no abort and no omission is genuinely undated by its own
        contents — nothing in it distinguishes the two generations, so either graph
        explains it. Those answer `"v1"`, because the as-built graph accepts every
        one of them and is the graph that produced them.
        """
        vocab = vocabulary()
        off = vocab.code_of("LIGHTS_OFF")
        partners = {vocab.code_of(n) for n in ABORT_PARTNERS}
        if self.codes & {vocab.code_of(n) for n in V2_ONLY}:
            return "v2"
        codes = [c for c, _ in self.events]
        if any(a in partners and b == off for a, b in zip(codes, codes[1:])):
            return "v2"
        return "v1"

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

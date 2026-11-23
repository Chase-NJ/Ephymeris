"""A simulated session as the wire carries it, scored as a recorded run is.

The strobes go into the document the runner would have written and through
`analytics.stream.summarize`, and the live metrics are the `MetricSet` a running
box is scored by, so nothing here computes a number of its own
(`TASKS.md#simulating-a-task`).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..analytics import stream
from ..analytics.stream.legacy.trials import MetricSet
from ..sessions import run_document
from ..taskdef.model import TaskDefinition
from .animal import Animal
from .errors import SimulationError
from .session import ENDED_BY_CUT, DEFAULT_LIMIT_MS, SEED_RANGE, Simulated, simulate

CUT_OFF_REASON = "simulated session cut off past its time limit"

DEFAULT_SESSIONS = 10
MAX_SESSIONS = 50
MAX_ANIMALS = 12
_SEED_STEP = 7919


def stress_seeds(first: int, sessions: int) -> list[int]:
    """The seeds of a stress test's sessions: `first`, then a fixed walk from it."""
    low, high = SEED_RANGE
    span = high - low + 1
    return [low + (first - low + index * _SEED_STEP) % span for index in range(max(0, sessions))]


def check_stress(animals: int, sessions: int) -> None:
    if not 1 <= animals <= MAX_ANIMALS:
        raise SimulationError(f"A stress test runs 1 to {MAX_ANIMALS} animals.")
    if not 1 <= sessions <= MAX_SESSIONS:
        raise SimulationError(f"A stress test runs 1 to {MAX_SESSIONS} sessions per animal.")


def document_of(run: Simulated) -> dict[str, Any]:
    """The run document a board that sent `run.strobes` would have left."""
    fields = {
        "sketch": run.profile.task_name,
        "stop_reason": CUT_OFF_REASON if run.ended_by == ENDED_BY_CUT else stream.CLEAN_STOP_REASON,
        "interp": run.interp,
        "stream": run.stream,
        "trial_seed": run.seed,
        "host_seed": run.seed,
    }
    return run_document.build(fields, run.params, None, run.strobes)


def telemetry_of(run: Simulated) -> list[dict[str, Any]]:
    """Every moment the live metrics moved: the strobe's index, and the values
    a box's `session.telemetry` would have carried."""
    metrics = MetricSet(run.profile)
    moved: list[dict[str, Any]] = []
    for index, (code, _) in enumerate(run.strobes):
        values = [value.to_json() for value in metrics.offer(code)]
        if values and (not moved or values != moved[-1]["metrics"]):
            moved.append({"strobe": index, "metrics": values})
    return moved


def _water(table: Mapping[str, Any] | None) -> dict[str, int]:
    paid = [trial for trial in (table or {}).get("trials", []) if trial.get("rewarded")]
    return {"rewards": len(paid), "ms": sum(trial.get("rewardMs") or 0 for trial in paid)}


def payload(definition: TaskDefinition, animal: Animal, seed: int, *,
            limit_ms: int = DEFAULT_LIMIT_MS) -> dict[str, Any]:
    """`tasks.simulate`'s result."""
    run = simulate(definition, animal, seed, limit_ms=limit_ms)
    document = document_of(run)
    table = stream.trial_table_of(document, run.profile)
    return {
        "seed": run.seed,
        "limitMs": run.limit_ms,
        "endedBy": run.ended_by,
        "durationMs": run.strobes[-1][1] if run.strobes else 0,
        "animal": animal.to_json(),
        "strobes": run.strobes,
        "telemetry": telemetry_of(run),
        "summary": stream.summarize(document, run.profile).to_json(),
        "trialTable": table,
        "water": _water(table),
    }


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _session_row(definition: TaskDefinition, animal: Animal, seed: int, limit_ms: int) -> dict[str, Any]:
    run = simulate(definition, animal, seed, limit_ms=limit_ms)
    document = document_of(run)
    summary = stream.summarize(document, run.profile)
    table = stream.trial_table_of(document, run.profile)
    trials = (table or {}).get("trials", [])
    water = _water(table)
    duration = run.strobes[-1][1] if run.strobes else 0
    scored = [trial for trial in trials if trial.get("correct") is not None]
    return {
        "seed": seed,
        "endedBy": run.ended_by,
        "durationMs": duration,
        "presented": len(trials),
        "scored": len(scored),
        "correct": sum(1 for trial in scored if trial["correct"]),
        "rewards": water["rewards"],
        "waterMs": water["ms"],
        "accuracy": (summary.to_json()["overall"] or {}).get("pSession"),
    }


def stress_payload(definition: TaskDefinition, animals: Sequence[tuple[str, Animal]],
                   seeds: Sequence[int], *, limit_ms: int = DEFAULT_LIMIT_MS) -> dict[str, Any]:
    """`tasks.stressTest`'s result: every animal over the same seeds, so two
    rows differ by the animal alone."""
    rows = []
    for label, animal in animals:
        sessions = [_session_row(definition, animal, seed, limit_ms) for seed in seeds]
        hours = [s["durationMs"] / 3_600_000 for s in sessions]
        rows.append({
            "label": label,
            "animal": animal.to_json(),
            "sessions": sessions,
            "meanAccuracy": _mean([s["accuracy"] for s in sessions if s["accuracy"] is not None]),
            "meanRewards": _mean([s["rewards"] for s in sessions]),
            "meanWaterMs": _mean([s["waterMs"] for s in sessions]),
            "meanPresented": _mean([s["presented"] for s in sessions]),
            "meanDurationMs": _mean([s["durationMs"] for s in sessions]),
            "rewardsPerHour": _mean([s["rewards"] / h for s, h in zip(sessions, hours) if h > 0]),
        })
    return {"seeds": list(seeds), "limitMs": limit_ms, "animals": rows}

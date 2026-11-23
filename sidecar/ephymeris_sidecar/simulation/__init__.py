"""Running a task definition off the rig (`TASKS.md#simulating-a-task`).

The firmware itself runs the task: `build` compiles the real sketch and trial
runner for this computer, `session` drives one through the board's own start
handshake and plays an `animal` against it, and `result` scores what it strobed
with the scorer a recorded run goes through. Nothing here touches a port, a
file of the session data or the database.
"""

from .animal import Animal, AnimalError
from .build import SimulatorUnavailable
from .errors import SimulationError
from .result import DEFAULT_SESSIONS, check_stress, payload, stress_payload, stress_seeds
from .session import DEFAULT_LIMIT_MS, simulate

__all__ = [
    "DEFAULT_LIMIT_MS",
    "DEFAULT_SESSIONS",
    "check_stress",
    "stress_seeds",
    "Animal",
    "AnimalError",
    "SimulationError",
    "SimulatorUnavailable",
    "payload",
    "simulate",
    "stress_payload",
]

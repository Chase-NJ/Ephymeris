"""What a simulation refuses with."""

from __future__ import annotations


class SimulationError(Exception):
    """A simulation that cannot be run as asked (`SIMULATION_REFUSED`)."""

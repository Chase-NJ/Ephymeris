"""RHX's impedance CSV -> per-site readings (`RECORDING.md#impedance-tracking`). Pure.

RHX has no TCP command that returns impedances: `execute MeasureImpedance`
measures every amplifier channel on every connected headstage, and `execute
SaveImpedance` writes them to `ImpedanceFilename` as CSV. That file is what
this reads. Its shape, from RHX's `ImpedanceReader::saveImpedances`:

    Channel Number,Channel Name,Port,Enabled,Impedance Magnitude at 1000 Hz (ohms),
        Impedance Phase at 1000 Hz (degrees),Series RC equivalent R (Ohms),...
    A-000,A-000,Port A,1,1.00e+05,-70,3.42e+04,...

"Channel Number" holds the NATIVE name and "Channel Name" the custom one, so
the native name is read from the first column. The frequency is the one RHX
actually measured at (`ActualImpedanceFreqHertz`), which can differ from the
one asked for.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

_FREQUENCY = re.compile(r"Impedance Magnitude at\s+([0-9.eE+-]+)\s*Hz", re.IGNORECASE)


class ImpedanceFileError(ValueError):
    """The file is not an RHX impedance CSV."""


@dataclass(frozen=True)
class SiteImpedance:
    channel: str
    ohms: float
    phase_deg: float


@dataclass(frozen=True)
class ImpedanceFile:
    frequency_hz: float
    sites: tuple[SiteImpedance, ...]


def parse_csv(text: str) -> ImpedanceFile:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ImpedanceFileError("The impedance file is empty.")
    header = [cell.strip() for cell in rows[0]]
    match = next((m for cell in header if (m := _FREQUENCY.search(cell))), None)
    if match is None or len(header) < 6:
        raise ImpedanceFileError("Not an RHX impedance file: no magnitude column.")
    magnitude = next(i for i, cell in enumerate(header) if _FREQUENCY.search(cell))
    phase = magnitude + 1
    sites: list[SiteImpedance] = []
    for row in rows[1:]:
        if len(row) <= phase or not row[0].strip():
            continue
        try:
            ohms = float(row[magnitude])
            phase_deg = float(row[phase])
        except ValueError as exc:
            raise ImpedanceFileError(f"Unreadable impedance for {row[0].strip()}: {exc}") from exc
        sites.append(SiteImpedance(row[0].strip().upper(), ohms, phase_deg))
    return ImpedanceFile(float(match.group(1)), tuple(sites))

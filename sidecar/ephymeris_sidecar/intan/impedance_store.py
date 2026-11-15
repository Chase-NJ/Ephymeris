"""Each animal's electrode impedance history (`RECORDING.md#impedance-tracking`).

The `electrode_impedances` table, reached only through `Database.write` and
`Database.read` (`DATA.md#transactions`). A measurement is the rows that share
an animal and a `measured_at`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..cohorts.db import Database, Tx
from .impedance import SiteImpedance


@dataclass(frozen=True)
class Measurement:
    animal_id: str
    measured_at: str
    box: int
    session_id: str | None
    frequency_hz: float
    csv_file: str | None
    sites: tuple[SiteImpedance, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "animalId": self.animal_id,
            "measuredAt": self.measured_at,
            "box": self.box,
            "sessionId": self.session_id,
            "frequencyHz": self.frequency_hz,
            "file": self.csv_file,
            "sites": {s.channel: {"ohms": s.ohms, "phaseDeg": s.phase_deg} for s in self.sites},
        }


class ImpedanceStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, measurements: list[Measurement], *, tx: Tx | None = None) -> None:
        """One measurement per animal, written together."""
        with self._db.write(tx) as unit:
            for m in measurements:
                for site in m.sites:
                    unit.execute(
                        "INSERT OR REPLACE INTO electrode_impedances (animal_id, measured_at,"
                        " channel, session_id, box_number, frequency_hz, ohms, phase_deg, csv_file)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            m.animal_id,
                            m.measured_at,
                            site.channel,
                            m.session_id,
                            m.box,
                            m.frequency_hz,
                            site.ohms,
                            site.phase_deg,
                            m.csv_file,
                        ),
                    )

    def latest(self, animal_id: str, *, before: str | None = None) -> Measurement | None:
        """The animal's most recent measurement, or its most recent strictly
        before `before` (a `measured_at`): the one a new one is compared with."""
        with self._db.read() as q:
            row = q.execute(
                "SELECT measured_at FROM electrode_impedances WHERE animal_id = ?"
                + (" AND measured_at < ?" if before is not None else "")
                + " ORDER BY measured_at DESC LIMIT 1",
                (animal_id, before) if before is not None else (animal_id,),
            ).fetchone()
            if row is None:
                return None
            rows = q.execute(
                "SELECT * FROM electrode_impedances WHERE animal_id = ? AND measured_at = ?"
                " ORDER BY channel",
                (animal_id, row["measured_at"]),
            ).fetchall()
        first = rows[0]
        return Measurement(
            animal_id=animal_id,
            measured_at=first["measured_at"],
            box=first["box_number"],
            session_id=first["session_id"],
            frequency_hz=first["frequency_hz"],
            csv_file=first["csv_file"],
            sites=tuple(SiteImpedance(r["channel"], r["ohms"], r["phase_deg"]) for r in rows),
        )

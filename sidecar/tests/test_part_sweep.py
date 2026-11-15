"""The first `settings.push` sweeps the `.part`s earlier runs' interrupted writes
left (`DATA.md#built-once-at-the-end`): under the data directory and every
cohort's data folder, never under the backup directory, once per process. The
rule itself is `sessions/writer.py`'s `sweep_parts`, tested in `test_writer.py`.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from ephymeris_sidecar import app as app_module
from ephymeris_sidecar.sessions.writer import PART_GRACE_S, PART_SUFFIX
from tests.live_sidecar import animal, settings
from tests.scripted_board import until
from tests.wire import dispatch, running_app


def _part(folder: Path, name: str) -> Path:
    """A part another process's `write_atomic` left."""
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / f"{name}.{os.getpid() + 1}-123456{PART_SUFFIX}"
    part.write_bytes(b"half a document")
    return part


def _swept() -> bool:
    return not any(thread.name == "part-sweep" for thread in threading.enumerate())


async def test_the_first_settings_push_sweeps_earlier_runs_parts(tmp_path: Path) -> None:
    data = tmp_path / "data"
    elsewhere = tmp_path / "elsewhere" / "Cohort"
    backup = data / "backup"
    in_data = _part(data / "Old" / "2O-Bdisc_25_2026-07-22", "remy1.json")
    in_cohort = _part(elsewhere / "2O-Bdisc_26_2026-07-23", "remy1.mat")
    mirrored = _part(backup / "Cohort", "remy1.json")

    async with running_app(tmp_path / "app") as app:
        # Parts written now are stale only to a process that started later
        # (`test_writer.py` says why).
        app._started = time.time() + 2 * PART_GRACE_S
        await dispatch(
            app, "cohorts.create", name="Cohort", dataFolder=str(elsewhere),
            groups=[{"id": "g1", "name": "Morning", "order": 0}],
            animals=[animal("rat1", "g1")],
        )
        await dispatch(app, "settings.push", settings=settings(
            dataDirectory=str(data), backupDirectory=str(backup),
        ))
        await until(_swept)

        assert not in_data.exists() and not in_cohort.exists()
        assert mirrored.exists()


async def test_later_pushes_do_not_sweep_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(app_module, "sweep_parts", lambda *a, **k: calls.append(a))

    async with running_app(tmp_path / "app") as app:
        for _ in range(3):
            await dispatch(app, "settings.push", settings=settings(dataDirectory=str(tmp_path)))
        await until(_swept)

    assert len(calls) == 1

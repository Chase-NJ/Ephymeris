"""`intan.configure` sets up a recording only for the boxes the held mapping
has, and a recording set up for one mapping never starts for another
(`RECORDING.md#record-step`).

The Record step builds its rows from the mapping, but nothing on the client
stops a stale form naming a box the mapping no longer has: RHX would be
configured for it and its notes would say `box N=?`. Driven through
`tests/wire.py`'s `dispatch` against the app's own `IntanService` talking to a
fake RHX, so the notes asserted on are the ones RHX was sent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.fake_rhx import FakeRhx
from tests.live_sidecar import Refused, animal, settings
from tests.scripted_board import until
from tests.test_intan_service import config
from tests.test_utility import HWID, FakeTool, fake_serial  # noqa: F401 - fake_serial is an autouse fixture
from tests.wire import dispatch, running_app


@pytest.fixture
async def rhx():
    fake = await FakeRhx().start()
    try:
        yield fake
    finally:
        await fake.stop()


@pytest.fixture
async def app(tmp_path: Path, rhx: FakeRhx):
    """The sidecar with RHX on `rhx` and a board bound to box 1 (wired to DIN 2)."""
    async with running_app(tmp_path / "app", tool=FakeTool()) as app:
        await dispatch(app, "settings.push", settings=settings(
            boxes=[
                {"box": 1, "hardwareId": HWID, "label": "Box 1", "intanDigitalIn": 2},
                {"box": 3, "hardwareId": None, "label": "Box 3", "intanDigitalIn": 5},
            ],
            intan={
                "commandPort": rhx.command_port,
                "waveformPort": rhx.waveform_port,
                "spikePort": rhx.spike_port,
            },
        ))
        yield app


async def _recording_session(app, folder: Path) -> tuple[str, dict[str, Any]]:  # noqa: ANN001
    """A recording session of a cohort with rat1 on box 1 and rat2 unplaced.
    Its mapping is not confirmed yet."""
    cohort = (await dispatch(
        app, "cohorts.create", name=folder.name, dataFolder=str(folder),
        groups=[{"id": "g1", "name": "Morning", "order": 0}],
        animals=[animal("rat1", "g1", box=1), animal("rat2", "g1")],
    ))["cohort"]
    prefix = (await dispatch(app, "prefixes.create", name="2O-Bdisc"))["prefix"]["id"]
    session = (await dispatch(
        app, "sessions.create", cohortId=cohort["id"], prefixId=prefix,
        sessionNumber="1", recording=True,
    ))["session"]
    return session["id"], cohort


async def _grgl(app) -> str:  # noqa: ANN001
    sketches = (await dispatch(app, "sketches.refresh"))["sketches"]
    return next(s["path"] for s in sketches if s["name"] == "GRGL")


async def _confirm_box_1(app, session_id: str, cohort: dict[str, Any], rat: str = "rat1") -> None:  # noqa: ANN001
    animal_id = next(a["id"] for a in cohort["animals"] if a["name"] == rat)
    await dispatch(
        app, "sessions.confirmMapping", sessionId=session_id, groupId="g1",
        boxes=[{"box": 1, "animalId": animal_id, "sketchPath": await _grgl(app), "config": {}}],
    )


async def test_a_box_the_held_mapping_does_not_have_is_refused(app, rhx: FakeRhx, tmp_path: Path) -> None:  # noqa: ANN001
    """B5: the mapping moved on (box 3's animal went to box 5) and the form
    still names box 3. Nothing reaches RHX, and the refusal names the box."""
    session_id, cohort = await _recording_session(app, tmp_path / "Batch A")
    await _confirm_box_1(app, session_id, cohort)

    with pytest.raises(Refused) as refused:
        await dispatch(app, "intan.configure", sessionId=session_id, groupId="g1", config=config(tmp_path))

    assert refused.value.code == "SESSION_INVALID"
    assert refused.value.detail == {"boxes": [3]}
    assert "box 3" in refused.value.message.lower()
    assert "note3" not in rhx.params


async def test_a_session_whose_mapping_is_not_confirmed_is_refused(app, rhx: FakeRhx, tmp_path: Path) -> None:  # noqa: ANN001
    """Without a held mapping no box is mapped, so RHX would be told `box 1=?`."""
    session_id, _cohort = await _recording_session(app, tmp_path / "Batch B")
    only_box_1 = config(tmp_path, boxes=[{"box": 1, "port": "A", "firstChannel": 0, "lastChannel": 15}])

    with pytest.raises(Refused) as refused:
        await dispatch(app, "intan.configure", sessionId=session_id, groupId="g1", config=only_box_1)

    assert refused.value.code == "SESSION_INVALID"
    assert refused.value.detail == {"boxes": [1]}
    assert "note3" not in rhx.params


async def test_another_groups_mapping_is_not_this_groups(app, rhx: FakeRhx, tmp_path: Path) -> None:  # noqa: ANN001
    """The held mapping is one group's: its box 1 is not another group's box 1."""
    session_id, cohort = await _recording_session(app, tmp_path / "Batch C")
    await _confirm_box_1(app, session_id, cohort)
    only_box_1 = config(tmp_path, boxes=[{"box": 1, "port": "A", "firstChannel": 0, "lastChannel": 15}])

    with pytest.raises(Refused) as refused:
        await dispatch(app, "intan.configure", sessionId=session_id, groupId="g2", config=only_box_1)

    assert refused.value.code == "SESSION_INVALID"
    assert refused.value.detail == {"boxes": [1]}


async def test_a_mapped_box_reaches_rhx_with_its_animal(app, rhx: FakeRhx, tmp_path: Path) -> None:  # noqa: ANN001
    session_id, cohort = await _recording_session(app, tmp_path / "Batch D")
    await _confirm_box_1(app, session_id, cohort)
    only_box_1 = config(tmp_path, boxes=[{"box": 1, "port": "A", "firstChannel": 0, "lastChannel": 15}])

    status = await dispatch(app, "intan.configure", sessionId=session_id, groupId="g1", config=only_box_1)

    assert status["state"] == "configured"
    assert "box 1=rat1 port A" in rhx.params["note3"]


async def test_a_recording_set_up_for_an_earlier_mapping_does_not_start(app, rhx: FakeRhx, tmp_path: Path) -> None:  # noqa: ANN001
    """The Record step set RHX up for rat1 on box 1; the operator went back to
    Boxes, put rat2 there, confirmed the group again and went straight to
    Mission Control. RHX still holds rat1's notes and channels, so Start All is
    refused before RHX records anything."""
    session_id, cohort = await _recording_session(app, tmp_path / "Batch E")
    await _confirm_box_1(app, session_id, cohort)
    await dispatch(app, "sessions.flash", sessionId=session_id, boxes=[1])
    grgl = await _grgl(app)
    await until(lambda: (c := app.ports.carried(1)) is not None and c.is_of(grgl), timeout=10)
    only_box_1 = config(tmp_path, boxes=[{"box": 1, "port": "A", "firstChannel": 0, "lastChannel": 15}])
    await dispatch(app, "intan.configure", sessionId=session_id, groupId="g1", config=only_box_1)
    assert "box 1=rat1" in rhx.params["note3"]

    await _confirm_box_1(app, session_id, cohort, rat="rat2")

    with pytest.raises(Refused) as refused:
        await dispatch(app, "sessions.startAll", sessionId=session_id)

    assert refused.value.code == "INTAN_NOT_READY"
    assert "Record step" in refused.value.message
    assert rhx.params["runmode"] == "Stop"
    assert app.runner.running_boxes() == []

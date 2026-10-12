"""`intan.configure` sets up a recording only for the boxes the held mapping
has (`RECORDING.md#recording-walkthrough`).

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
from tests.test_intan_service import config
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
    async with running_app(tmp_path / "app") as app:
        await dispatch(app, "settings.push", settings=settings(
            boxes=[
                {"box": box, "hardwareId": None, "label": f"Box {box}", "intanDigitalIn": din}
                for box, din in ((1, 2), (3, 5))
            ],
            intan={
                "commandPort": rhx.command_port,
                "waveformPort": rhx.waveform_port,
                "spikePort": rhx.spike_port,
            },
        ))
        yield app


async def _recording_session(app, folder: Path) -> tuple[str, dict[str, Any]]:  # noqa: ANN001
    """A recording session of a cohort with rat1 on box 1. Its mapping is not
    confirmed yet."""
    cohort = (await dispatch(
        app, "cohorts.create", name=folder.name, dataFolder=str(folder),
        groups=[{"id": "g1", "name": "Morning", "order": 0}],
        animals=[animal("rat1", "g1", box=1)],
    ))["cohort"]
    prefix = (await dispatch(app, "prefixes.create", name="2O-Bdisc"))["prefix"]["id"]
    session = (await dispatch(
        app, "sessions.create", cohortId=cohort["id"], prefixId=prefix,
        sessionNumber="1", recording=True,
    ))["session"]
    return session["id"], cohort


async def _confirm_box_1(app, session_id: str, cohort: dict[str, Any]) -> None:  # noqa: ANN001
    sketches = (await dispatch(app, "sketches.refresh"))["sketches"]
    grgl = next(s["path"] for s in sketches if s["name"] == "GRGL")
    [rat] = cohort["animals"]
    await dispatch(
        app, "sessions.confirmMapping", sessionId=session_id, groupId="g1",
        boxes=[{"box": 1, "animalId": rat["id"], "sketchPath": grgl, "config": {}}],
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

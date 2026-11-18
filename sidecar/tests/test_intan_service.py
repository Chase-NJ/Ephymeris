"""`IntanService` against a fake RHX on real sockets.

The rule under test is the Backup mirror's, restated: RHX may be slow, absent
or dead and none of that may stall or fail a behavior session -- with the one
deliberate exception that a recording which cannot START says so before any box
does.
"""

from __future__ import annotations

import asyncio

import pytest

from ephymeris_sidecar.intan.client import RhxCommandFailed
from ephymeris_sidecar.intan.service import SILENT_POLLS, IntanNotReady, IntanService
from ephymeris_sidecar.intan.streams import (
    FRAMES_PER_BLOCK,
    FrameLayout,
    Spike,
    WaveformBlock,
    pack_spike,
    pack_waveform_block,
)
from ephymeris_sidecar.protocol import Evt, validate
from ephymeris_sidecar.settings import SidecarSettings
from tests.fake_rhx import FakeRhx

FS = 30000


def settings_for(fake: FakeRhx, dins: dict[int, int]) -> SidecarSettings:
    return SidecarSettings.from_payload(
        {
            "boxes": [{"box": b, "intanDigitalIn": d} for b, d in dins.items()],
            "intan": {
                "commandPort": fake.command_port,
                "waveformPort": fake.waveform_port,
                "spikePort": fake.spike_port,
            },
        }
    )


def config(tmp_path, **edits) -> dict:
    base = {
        "saveDirectory": str(tmp_path / "ephys"),
        "fileFormat": "OneFilePerSignalType",
        "saveWideband": False,
        "saveSpikes": True,
        "saveSpikeSnapshots": False,
        "snapshotPreMs": 1,
        "snapshotPostMs": 2,
        "saveLowpass": False,
        "lowpassDownsample": 1,
        "saveHighpass": False,
        "threshold": {"mode": "absolute", "microvolts": -60, "rmsMultiple": 4.0, "negative": True},
        "boxes": [
            {"box": 1, "port": "A", "firstChannel": 0, "lastChannel": 15},
            {"box": 3, "port": "A", "firstChannel": 16, "lastChannel": 31},
        ],
    }
    base.update(edits)
    return base


class Harness:
    def __init__(self, fake: FakeRhx, service: IntanService, events: list[dict]) -> None:
        self.fake, self.service, self.events = fake, service, events

    def last(self, name: str) -> dict:
        return next(e["data"] for e in reversed(self.events) if e["evt"] == name)

    async def until(self, predicate, timeout: float = 3.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            assert asyncio.get_running_loop().time() < deadline, "condition never held"
            await asyncio.sleep(0.01)


@pytest.fixture
async def rig():
    """A service wired to a fake RHX, with boxes 1 and 3 bound to DIN 2 and 5."""
    made: list[Harness] = []

    async def make(
        *, sync: bool = True, dins=None, poll_s: float = 0.05, stop_timeout_s: float = 1.0, **fake_kwargs
    ) -> Harness:
        fake = await FakeRhx(**fake_kwargs).start()
        events: list[dict] = []

        async def broadcast(message: dict) -> None:
            events.append(message)

        service = IntanService(
            loop=asyncio.get_running_loop(),
            broadcast=broadcast,
            settings=settings_for(fake, dins if dins is not None else {1: 2, 3: 5}),
            rig_has_sync=lambda: sync,
            pre_roll_s=0.0,
            post_roll_s=0.0,
            poll_s=poll_s,
            stop_timeout_s=stop_timeout_s,
        )
        service.start()
        harness = Harness(fake, service, events)
        made.append(harness)
        return harness

    yield make
    for harness in made:
        await harness.service.stop()
        await harness.fake.stop()


# --- configure --------------------------------------------------------------


async def test_configure_tells_rhx_exactly_what_was_asked(rig, tmp_path):
    h = await rig()
    await h.service.configure("s1", config(tmp_path), "GRGL_7_2026-09-20_A", ("a", "b", "c"))
    p = h.fake.params

    assert p["fileformat"] == "OneFilePerSignalType"
    assert p["filename.basefilename"] == "GRGL_7_2026-09-20_A"
    assert p["filename.path"].endswith("/ephys") and "\\" not in p["filename.path"]
    assert (tmp_path / "ephys").is_dir()  # RHX is not trusted to create it
    assert p["savewidebandamplifierwaveforms"] == "false" and p["savespikedata"] == "true"

    # Exactly the claimed ranges are saved and spike-streamed...
    assert h.fake.enabled("tcpdataoutputenabledspike") == [f"A-{n:03d}" for n in range(32)]
    # ...and each box's OWN digital input is saved, named and streamed.
    assert p["digital-in-02.enabled"] == "true" and p["digital-in-05.enabled"] == "true"
    assert p["digital-in-02.customchannelname"] == "BOX1_EVENTS"
    assert p["digital-in-05.tcpdataoutputenabled"] == "true"

    # Stale outputs are cleared FIRST, and thresholds applied AFTER the enables
    # -- `SetSpikeDetectionThresholds` only touches enabled channels.
    log = h.fake.log
    assert log.index("execute clearalldataoutputs") < log.index("set a-000.enabled true")
    assert log.index("set a-031.enabled true") < log.index("execute setspikedetectionthresholds")
    assert p["absolutethresholdmicrovolts"] == "-60"

    assert h.service.status_json()["state"] == "configured"
    assert h.service.status_json()["liveStreams"] is True


async def test_channels_nobody_claimed_are_switched_off(rig, tmp_path):
    h = await rig()
    boxes = [{"box": 1, "port": "A", "firstChannel": 0, "lastChannel": 7}]
    await h.service.configure("s1", config(tmp_path, boxes=boxes), "x")
    assert h.fake.params["a-007.enabled"] == "true"
    assert h.fake.params["a-008.enabled"] == "false"


async def test_a_save_location_rhx_would_truncate_is_refused_not_recorded_elsewhere(rig, tmp_path):
    """THE PACKAGED-ONLY CLASS OF BUG. If RHX splits a `set` value on spaces it
    ACCEPTS `C:/Hart Lab/x` and records into `C:/Hart`. Only the read-back sees
    it, and the message says what to do."""
    h = await rig(truncate_at_space=True)
    spaced = tmp_path / "Hart Lab" / "ephys"
    with pytest.raises(RhxCommandFailed, match="space"):
        await h.service.configure("s1", config(tmp_path, saveDirectory=str(spaced)), "x")
    assert h.service.status_json()["state"] != "configured"


@pytest.mark.parametrize(
    ("kwargs", "edits", "says"),
    [
        ({"dins": {1: 2}}, {}, "Box 3 has no Intan digital input"),
        ({"sync": False}, {}, "no sync channel"),
        ({}, {"boxes": [{"box": 1, "port": "B", "firstChannel": 0, "lastChannel": 3}]}, "no headstage"),
        ({}, {"boxes": [{"box": 1, "port": "A", "firstChannel": 0, "lastChannel": 40}]}, "last channel"),
        (
            {},
            {"boxes": [
                {"box": 1, "port": "A", "firstChannel": 0, "lastChannel": 20},
                {"box": 3, "port": "A", "firstChannel": 16, "lastChannel": 31},
            ]},
            "claimed by box 1 and box 3",
        ),
        ({}, {"saveSpikes": False}, "Nothing would be saved"),
    ],
)
async def test_a_setup_that_cannot_record_says_why(rig, tmp_path, kwargs, edits, says):
    h = await rig(**kwargs)
    with pytest.raises(IntanNotReady, match=says):
        await h.service.configure("s1", config(tmp_path, **edits), "x")


async def test_an_rhx_left_running_is_stopped_but_one_recording_is_not_touched(rig, tmp_path):
    h = await rig()
    h.fake.params["runmode"] = "Run"
    await h.service.configure("s1", config(tmp_path), "x")
    assert h.fake.params["runmode"] == "Stop"

    await h.service.disconnect()
    h.fake.params["runmode"] = "Record"
    with pytest.raises(IntanNotReady, match="already recording"):
        await h.service.configure("s1", config(tmp_path), "x")
    assert h.fake.params["runmode"] == "Record"


# --- record -----------------------------------------------------------------


async def test_start_means_samples_are_arriving_not_that_record_was_requested(rig, tmp_path):
    h = await rig(runmode_delay_s=0.12)
    await h.service.configure("s1", config(tmp_path), "base")
    await h.service.start_recording()

    assert h.fake.params["runmode"] == "Record"
    status = h.service.status_json()
    assert status["state"] == "recording"
    assert status["recording"]["fileTimestamp"] == "260920_101500"
    # What one animal's session document says about the recording it is inside.
    assert h.service.recording_fields(3) == {
        "intan_recording": "base_260920_101500",
        "intan_path": str(tmp_path / "ephys"),
        "intan_digital_in": 5,
        "intan_port": "A",
        "intan_channels": "A-016:A-031",
        "intan_sample_rate": FS,
    }
    assert h.service.recording_fields(2) == {}  # a box that is not recorded


async def test_a_recording_that_cannot_start_refuses(rig, tmp_path):
    """The one place RHX may fail the session path: before any box has started."""
    h = await rig()
    await h.service.configure("s1", config(tmp_path), "x")
    h.fake.refuse.add("runmode")
    with pytest.raises(RhxCommandFailed):
        await h.service.start_recording()
    assert h.service.status_json()["state"] != "recording"

    with pytest.raises(IntanNotReady):
        await (await rig()).service.start_recording()  # nothing configured at all


async def test_stop_returns_the_run_and_never_raises_even_with_rhx_dead(rig, tmp_path):
    """By the time this runs the animals are done. A raise here could only
    strand the session as `running`."""
    h = await rig()
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    await h.fake.die()

    run = await h.service.stop_recording()

    assert run is not None and run["endedAt"]
    status = h.service.status_json()
    assert status["state"] == "error" and "Stop it from RHX" in status["message"]


async def test_a_stop_rhx_never_answers_is_bounded_and_sent_once_it_does(rig, tmp_path):
    """THE RULE at End: a wedged RHX costs the stop `stop_timeout_s`, not the
    session. The stop is owed, and the first poll RHX answers sends it."""
    h = await rig(poll_s=30.0, stop_timeout_s=0.5)
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    h.fake.silent = True

    started = asyncio.get_running_loop().time()
    run = await h.service.stop_recording()

    assert asyncio.get_running_loop().time() - started < 2.0
    assert run is not None and run["endedAt"]
    assert h.fake.params["runmode"] == "Record"
    assert "did not answer in time" in h.service.status_json()["message"]

    h.fake.silent = False
    await h.service._poll_once()
    await h.until(lambda: h.fake.params["runmode"] == "Stop")
    status = h.service.status_json()
    assert status["state"] == "idle"
    assert "Stopped the RHX recording" in status["message"]  # said, not silent


async def _owe_a_stop(h, tmp_path) -> None:  # noqa: ANN001
    """A recording whose stop RHX never answered: the stop is owed."""
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    h.fake.silent = True
    await h.service.stop_recording()
    assert h.fake.params["runmode"] == "Record"


async def test_an_owed_stop_leaves_a_recording_started_by_hand_alone(rig, tmp_path):
    """RHX was stopped and started again by hand while unreachable: the file it
    writes now is not the run the session ended, so it is not stopped. Said
    plainly instead."""
    h = await rig(poll_s=30.0, stop_timeout_s=0.5)
    await _owe_a_stop(h, tmp_path)
    h.fake.params["filename.activefiletimestamp"] = "260920_111111"

    h.fake.silent = False
    await h.service._poll_once()
    await asyncio.sleep(0.2)

    assert h.fake.params["runmode"] == "Record"
    assert "left it alone" in h.service.status_json()["message"]
    await h.service._poll_once()  # and never on a later poll either
    await asyncio.sleep(0.2)
    assert h.fake.params["runmode"] == "Record"


async def test_an_owed_stop_waits_while_rhx_cannot_say_what_it_records(rig, tmp_path):
    """A stamp that can't be read is no verdict: RHX is left alone meanwhile,
    and the stop is still owed when a later poll can read it."""
    h = await rig(poll_s=30.0, stop_timeout_s=0.5)
    await _owe_a_stop(h, tmp_path)
    del h.fake.params["filename.activefiletimestamp"]

    h.fake.silent = False
    await h.service._poll_once()
    await asyncio.sleep(0.2)

    assert h.fake.params["runmode"] == "Record"
    assert "left it alone" in h.service.status_json()["message"]

    h.fake.params["filename.activefiletimestamp"] = "260920_101500"
    await h.service._poll_once()
    await h.until(lambda: h.fake.params["runmode"] == "Stop")


async def test_a_lost_link_keeps_saying_a_stop_is_owed(rig, tmp_path):
    """The link given up on after the failed stop: the debt, and the message
    saying so, outlive it."""
    h = await rig(poll_s=30.0, stop_timeout_s=0.5)
    await _owe_a_stop(h, tmp_path)
    for _ in range(SILENT_POLLS):  # unanswered polls: the link is given up on
        await h.service._poll_once()

    status = h.service.status_json()
    assert status["connected"] is False
    assert "could not stop the RHX recording" in status["message"]


async def test_a_reconnect_does_not_adopt_a_recording_started_by_hand(rig, tmp_path):
    """The link drops, and RHX is stopped and started again by hand. On
    reconnect RHX is in Record, but not writing this run: it is not picked
    back up as ours, and the End that follows does not stop it."""
    h = await rig(poll_s=0.05, stop_timeout_s=0.5)
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    await h.fake.stop_listening()
    await h.until(lambda: h.service.status_json()["state"] == "error")
    h.fake.params["filename.activefiletimestamp"] = "260920_111111"

    await h.fake.listen_again()
    # Reconnected and decided: the lost-link message is gone either way.
    await h.until(lambda: "Lost contact" not in (h.service.status_json()["message"] or ""))
    status = h.service.status_json()
    assert status["state"] == "error" and "not this run" in status["message"]

    run = await h.service.stop_recording()
    await asyncio.sleep(0.2)
    assert run is not None
    assert h.fake.params["runmode"] == "Record"


async def test_an_end_waiting_on_boxes_offers_end_now_with_rhx_lost(rig, tmp_path):
    """Mission Control offers End now only while `stopping`. With the link
    lost, an End still waits on the boxes, so it must still be offered --
    and the reason RHX is in trouble must not vanish."""
    h = await rig(poll_s=0.05)
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    await h.fake.stop_listening()
    await h.until(lambda: h.service.status_json()["state"] == "error")

    h.service.note_waiting([1, 3])
    await asyncio.sleep(0.3)  # several polls, each failing to reconnect

    status = h.service.status_json()
    assert (status["state"], status["waitingOn"]) == ("stopping", [1, 3])
    assert "Lost contact with RHX" in status["message"]

    # The link back mid-wait: the run is picked up, and End now stays.
    await h.fake.listen_again()
    await h.until(lambda: "Lost contact" not in (h.service.status_json()["message"] or ""))
    assert h.service.status_json()["state"] == "stopping"


async def test_a_reconnect_adopts_the_run_once_its_stamp_can_be_read(rig, tmp_path):
    """One stamp read that fails on reconnect is not a verdict: a later poll
    reads it, finds RHX on this run's file, and picks the run back up."""
    h = await rig(poll_s=0.05)
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    await h.fake.stop_listening()
    await h.until(lambda: h.service.status_json()["state"] == "error")
    del h.fake.params["filename.activefiletimestamp"]

    await h.fake.listen_again()
    await h.until(lambda: "Lost contact" not in (h.service.status_json()["message"] or ""))
    assert h.service.status_json()["state"] == "error"  # not adopted on an unread stamp
    h.fake.params["filename.activefiletimestamp"] = "260920_101500"

    await h.until(lambda: h.service.status_json()["state"] == "recording")


async def _end_inside_a_polls_stamp_read(h) -> dict | None:  # noqa: ANN001
    """End's stop, run to completion while a poll's file-stamp read is held
    open; End's own reads go through. Returns End's run."""
    client = h.service._client
    real_get = client.get
    inside, release = asyncio.Event(), asyncio.Event()

    async def get(parameter: str) -> str:
        if parameter == "filename.activefiletimestamp" and not inside.is_set():
            inside.set()
            await release.wait()
        return await real_get(parameter)

    client.get = get
    poll = asyncio.create_task(h.service._poll_once())
    await inside.wait()
    run = await h.service.stop_recording()
    release.set()
    await poll
    return run


@pytest.mark.parametrize("via", ["poll", "reconnect"])
async def test_an_end_during_an_adoption_is_not_undone_by_it(rig, tmp_path, via):
    """A poll -- or the reconnect itself -- is reading the file stamp to pick an
    unconfirmed run back up when End stops it. The read's answer is about a
    run that is no longer open: it must not adopt it, leaving `recording` with
    no run and live streams, for the next poll to call "stopped from RHX"."""
    h = await rig(poll_s=30.0)
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    await h.fake.stop_listening()
    await h.service._poll_once()  # the link is lost
    await h.fake.listen_again()
    if via == "poll":
        del h.fake.params["filename.activefiletimestamp"]
        await h.service._poll_once()  # back, but the stamp unread: not adopted
        assert h.service.status_json()["state"] == "error"
        h.fake.params["filename.activefiletimestamp"] = "260920_101500"

    run = await _end_inside_a_polls_stamp_read(h)

    assert run is not None and h.fake.params["runmode"] == "Stop"
    assert h.service.recording is None and not h.service._run_confirmed
    assert h.service._stream_tasks == []
    assert h.service.status_json()["state"] == "idle"
    await h.service._poll_once()
    status = h.service.status_json()
    assert status["state"] == "idle"
    assert "RHX itself" not in (status["message"] or "")


async def test_an_end_during_a_reconnects_stamp_read_keeps_its_message(rig, tmp_path):
    """On reconnect RHX is on another file, and End closes the run while that
    is being read. End's verdict on the recording it left alone stands; the
    reconnect's stale "not this run" must not overwrite it."""
    h = await rig(poll_s=30.0)
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    await h.fake.stop_listening()
    await h.service._poll_once()  # the link is lost
    await h.fake.listen_again()
    h.fake.params["filename.activefiletimestamp"] = "260920_111111"

    run = await _end_inside_a_polls_stamp_read(h)

    assert run is not None and h.fake.params["runmode"] == "Record"
    status = h.service.status_json()
    assert status["state"] == "error"
    assert "not the run whose session ended" in status["message"]


async def test_a_stop_and_record_by_hand_during_the_grace_is_not_stopped(rig, tmp_path):
    """While End waits on the boxes, Stop then Record is pressed in RHX: a new
    file. The post-roll stop must not end that recording as if it were ours."""
    h = await rig(poll_s=30.0, stop_timeout_s=0.5)
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    h.service.note_waiting([1])
    h.fake.params["runmode"] = "Stop"
    await h.service._poll_once()
    assert h.service.status_json()["state"] == "stopping"  # End now stays offered
    h.fake.params["runmode"] = "Record"
    h.fake.params["filename.activefiletimestamp"] = "260920_111111"
    h.service.note_waiting([])

    run = await h.service.stop_recording()
    await asyncio.sleep(0.2)

    assert run is not None
    assert h.fake.params["runmode"] == "Record"


async def test_an_owed_stop_is_dropped_when_rhx_was_stopped_by_hand(rig, tmp_path):
    """Stopped from RHX before the link came back: nothing is left to stop, and
    the next recording RHX is put in is not touched."""
    h = await rig(poll_s=30.0, stop_timeout_s=0.5)
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    h.fake.silent = True
    await h.service.stop_recording()

    h.fake.params["runmode"] = "Stop"
    h.fake.silent = False
    await h.service._poll_once()
    h.fake.params["runmode"] = "Record"
    await h.service._poll_once()
    await asyncio.sleep(0.2)
    assert h.fake.params["runmode"] == "Record"


async def test_losing_rhx_mid_recording_is_loud_and_the_run_is_kept(rig, tmp_path):
    h = await rig()
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    await h.fake.die()

    await h.until(lambda: h.service.status_json()["state"] == "error")
    status = h.service.status_json()
    assert "behavior session is unaffected" in status["message"]
    assert status["recording"] is not None  # still the run we will close out


async def test_every_status_is_the_declared_wire_shape(rig, tmp_path):
    h = await rig()
    assert validate(("ref", "IntanStatus"), h.service.status_json()) == []
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    h.service.box_started(1, "R12")
    await asyncio.sleep(0)
    assert validate(("ref", "IntanStatus"), h.service.status_json()) == []
    assert h.last(Evt.INTAN_STATUS)["state"] == "recording"


# --- noticing the link go, and come back ------------------------------------


async def test_rhx_hanging_up_is_seen_at_once_not_at_the_next_poll(rig):
    """REPORTED FROM THE BENCH: Disconnect was pressed in RHX and both the Rig
    tab and the Dashboard went on saying "connected". A closed socket is known
    without sending anything, so it must not wait for a poll -- the poll here is
    thirty seconds away, and the status still flips in well under one."""
    h = await rig(poll_s=30.0)
    await h.service.connect()
    assert h.service.status_json()["connected"] is True

    await h.fake.hang_up()
    # Waits on the BROADCAST, not on `status_json()`: what matters is that the
    # UI was told, and the screens only ever learn anything from the event.
    await h.until(lambda: h.last(Evt.INTAN_STATUS)["connected"] is False, timeout=1.5)

    status = h.last(Evt.INTAN_STATUS)
    assert (status["connected"], status["state"], status["runMode"]) == (False, "disconnected", None)


async def test_a_silent_rhx_stops_reading_as_connected(rig):
    """The other way to lose the link, and the one that was actually broken:
    the socket stays open and nothing answers. The service used to mark the
    link lost while `connected` -- which is the socket's -- stayed True, so
    the state said one thing and the flag every screen reads said another."""
    h = await rig(poll_s=0.05)
    await h.service.connect()
    h.fake.silent = True

    await h.until(lambda: h.service.status_json()["state"] == "disconnected", timeout=8.0)
    status = h.service.status_json()
    assert status["connected"] is False  # the flag and the state agree


async def test_one_missed_poll_is_not_a_lost_link(rig):
    """RHX goes quiet for a moment when it is busy. Dropping the socket on the
    first silence would cost the operator a walk to RHX to press Connect."""
    h = await rig(poll_s=30.0)
    await h.service.connect()
    h.fake.silent = True
    await h.service._poll_once()
    assert h.service.status_json()["connected"] is True
    h.fake.silent = False
    await h.service._poll_once()
    await h.service._poll_once()
    assert h.service.status_json()["connected"] is True


async def test_the_link_comes_back_by_itself(rig):
    """Once RHX is listening again the operator should have nothing to do here."""
    h = await rig(poll_s=0.05)
    await h.service.connect()
    await h.fake.hang_up()
    await h.until(lambda: h.last(Evt.INTAN_STATUS)["connected"] is False, timeout=1.5)
    await h.until(lambda: h.last(Evt.INTAN_STATUS)["connected"] is True, timeout=3.0)
    assert h.last(Evt.INTAN_STATUS)["state"] == "idle"


# --- live views -------------------------------------------------------------


def din_block(first: int, high_at: dict[int, int]) -> bytes:
    """One block of the DIN-only stream; `high_at` maps sample -> word."""
    layout = FrameLayout(digital_in=True)
    stamps = tuple(range(first, first + FRAMES_PER_BLOCK))
    return pack_waveform_block(
        layout,
        WaveformBlock(stamps, {}, tuple(high_at.get(t, 0) for t in stamps)),
    )


async def test_strobes_and_sync_edges_meet(rig, tmp_path):
    """The whole chain: a box's serial strobes (its own ms clock) and the edges
    its sync pin put on ITS digital input, paired into the sync check."""
    h = await rig(params={"synthetic": "False"})  # a controller, with real DINs
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    h.service.box_started(3, "R12")
    await asyncio.sleep(0)

    bit = 1 << (5 - 1)  # box 3 is on DIN 5
    # Four odor onsets (code 101) at 1 s intervals, each followed by a poke.
    events = [(101, 0), (222, 250), (101, 1000), (222, 1250), (101, 2000), (222, 2250), (101, 3000)]
    origin = 12_800
    sample_of = lambda ms: origin + ms * FS // 1000  # noqa: E731
    high = {}
    for _, ms in events:
        for t in range(sample_of(ms), sample_of(ms) + 15):  # a 500 us pulse
            high[t] = bit
    # A glitch on ANOTHER box's input must not count.
    high[sample_of(500)] = high.get(sample_of(500), 0) | (1 << (2 - 1))

    blocks = b"".join(din_block(first, high) for first in range(0, 140_000, FRAMES_PER_BLOCK))
    await h.fake.push_waveform(blocks)
    for code, ms in events:
        h.service.on_strobe(3, code, ms)

    await h.until(lambda: h.service.status_json()["sync"][0]["matched"] == len(events))
    stat = h.service.status_json()["sync"][0]
    assert (stat["box"], stat["spuriousEdges"], stat["unmatchedStrobes"]) == (3, 0, 0)


async def test_spikes_reach_the_firing_map_batched_by_box(rig, tmp_path):
    """`intan.spikes`: each box hears only its own channels, counted since the
    last send; a channel no box records is not reported; and once RHX's clock
    has been read the batch says how late its slowest spike was."""
    h = await rig()
    await h.service.configure("s1", config(tmp_path), "x")
    assert h.fake.params["tcpnumberdatablocksperwrite"] == "2"
    await h.service.start_recording()
    await h.until(lambda: h.service._clock is not None and h.service._clock.lag_ms(0, 0.0) is not None)

    spikes = [Spike("A-003", 9_000, 1), Spike("A-003", 9_100, 1), Spike("A-020", 9_000, 1)]
    await h.fake.push_spikes(b"".join(pack_spike(s) for s in spikes))
    sent = lambda: [e["data"] for e in h.events if e["evt"] == Evt.INTAN_SPIKES]  # noqa: E731
    await h.until(lambda: {d["box"] for d in sent()} == {1, 3})

    by_box = {d["box"]: d for d in sent()}
    assert by_box[1]["counts"] == {"A-003": 2}
    assert by_box[3]["counts"] == {"A-020": 1}
    assert all(isinstance(d["lagMs"], float) for d in sent())
    assert all(validate(("ref", "IntanSpikes"), d) == [] for d in sent())

    # Nothing new: nothing sent.
    before = len(sent())
    await asyncio.sleep(0.2)
    assert len(sent()) == before


async def test_a_tick_pulsed_box_matches_every_strobe_of_a_tick_to_its_one_edge(rig, tmp_path):
    """A spine board announces `SYNC=TICK` and pulses once per tick that
    strobes; the runner says so at START and the box's matcher pairs by tick.
    Matched per strobe, every one, with no edge left over and none missing."""
    h = await rig(params={"synthetic": "False"})
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    h.service.box_started(3, "R12", tick_pulsed=True)
    await asyncio.sleep(0)

    bit = 1 << (5 - 1)  # box 3 is on DIN 5
    ticks = [(0, [17, 48, 29, 42]), (250, [40, 44]), (1350, [43, 45, 46]), (2400, [47])]
    origin = 12_800
    sample_of = lambda ms: origin + ms * FS // 1000  # noqa: E731
    high = {t: bit for ms, _ in ticks for t in range(sample_of(ms), sample_of(ms) + 15)}
    blocks = b"".join(din_block(first, high) for first in range(0, 100_000, FRAMES_PER_BLOCK))
    await h.fake.push_waveform(blocks)
    for ms, codes in ticks:
        for code in codes:
            h.service.on_strobe(3, code, ms)

    strobes = sum(len(codes) for _, codes in ticks)
    await h.until(lambda: h.service.status_json()["sync"][0]["matched"] == strobes)
    stat = h.service.status_json()["sync"][0]
    assert (stat["spuriousEdges"], stat["unmatchedStrobes"]) == (0, 0)


async def test_synthetic_data_has_no_sync_line_so_the_check_is_off(rig, tmp_path):
    """RHX's demo mode generates its own digital inputs, which no box drives.
    The counters would diagnose wiring that does not exist, so they are not
    published."""
    h = await rig()  # the fake is synthetic by default, as RHX's demo is
    assert h.service.status_json()["synthetic"] is False  # not yet asked
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    assert h.service.status_json()["synthetic"] is True
    h.service.box_started(3, "R12")
    await asyncio.sleep(0)

    # Whatever the generated inputs do -- here, DIN 5 toggling every block --
    # is not an edge that means anything.
    bit = 1 << (5 - 1)
    blocks = b"".join(
        din_block(first, {t: bit for t in range(first, first + 64)})
        for first in range(0, 64_000, FRAMES_PER_BLOCK)
    )
    await h.fake.push_waveform(blocks)
    h.service.on_strobe(3, 101, 5000)
    await asyncio.sleep(0.05)
    assert h.service.status_json()["sync"] == []

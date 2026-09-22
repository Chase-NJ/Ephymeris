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
from ephymeris_sidecar.intan.service import IntanNotReady, IntanService
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

    async def make(*, sync: bool = True, dins=None, poll_s: float = 0.05, **fake_kwargs) -> Harness:
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
    await h.service.configure("s1", "g1", config(tmp_path), "GRGL_7_2026-09-20_A", ("a", "b", "c"))
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
    await h.service.configure("s1", "g1", config(tmp_path, boxes=boxes), "x")
    assert h.fake.params["a-007.enabled"] == "true"
    assert h.fake.params["a-008.enabled"] == "false"


async def test_a_save_location_rhx_would_truncate_is_refused_not_recorded_elsewhere(rig, tmp_path):
    """THE PACKAGED-ONLY CLASS OF BUG. If RHX splits a `set` value on spaces it
    ACCEPTS `C:/Hart Lab/x` and records into `C:/Hart`. Only the read-back sees
    it, and the message says what to do."""
    h = await rig(truncate_at_space=True)
    spaced = tmp_path / "Hart Lab" / "ephys"
    with pytest.raises(RhxCommandFailed, match="space"):
        await h.service.configure("s1", "g1", config(tmp_path, saveDirectory=str(spaced)), "x")
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
        await h.service.configure("s1", "g1", config(tmp_path, **edits), "x")


async def test_an_rhx_left_running_is_stopped_but_one_recording_is_not_touched(rig, tmp_path):
    h = await rig()
    h.fake.params["runmode"] = "Run"
    await h.service.configure("s1", "g1", config(tmp_path), "x")
    assert h.fake.params["runmode"] == "Stop"

    await h.service.disconnect()
    h.fake.params["runmode"] = "Record"
    with pytest.raises(IntanNotReady, match="already recording"):
        await h.service.configure("s1", "g1", config(tmp_path), "x")
    assert h.fake.params["runmode"] == "Record"


# --- record -----------------------------------------------------------------


async def test_start_means_samples_are_arriving_not_that_record_was_requested(rig, tmp_path):
    h = await rig(runmode_delay_s=0.12)
    await h.service.configure("s1", "g1", config(tmp_path), "base")
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
    await h.service.configure("s1", "g1", config(tmp_path), "x")
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
    await h.service.configure("s1", "g1", config(tmp_path), "x")
    await h.service.start_recording()
    await h.fake.die()

    run = await h.service.stop_recording()

    assert run is not None and run["groupId"] == "g1" and run["endedAt"]
    status = h.service.status_json()
    assert status["state"] == "error" and "Stop it from RHX" in status["message"]


async def test_losing_rhx_mid_recording_is_loud_and_the_run_is_kept(rig, tmp_path):
    h = await rig()
    await h.service.configure("s1", "g1", config(tmp_path), "x")
    await h.service.start_recording()
    await h.fake.die()

    await h.until(lambda: h.service.status_json()["state"] == "error")
    status = h.service.status_json()
    assert "behavior session is unaffected" in status["message"]
    assert status["recording"] is not None  # still the run we will close out
    assert h.service.is_recording is False or status["state"] == "error"


async def test_every_status_is_the_declared_wire_shape(rig, tmp_path):
    h = await rig()
    assert validate(("ref", "IntanStatus"), h.service.status_json()) == []
    await h.service.configure("s1", "g1", config(tmp_path), "x")
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


async def test_strobes_and_sync_edges_meet_and_drive_a_psth(rig, tmp_path):
    """The whole chain: a box's serial strobes (its own ms clock), the edges its
    sync pin put on ITS digital input, the spikes on ITS channel -- ending in a
    PSTH aligned to a named event."""
    h = await rig(params={"synthetic": "False"})  # a controller, with real DINs
    await h.service.configure("s1", "g1", config(tmp_path), "x")
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

    # A spike 20 ms after every odor onset, on one of box 3's channels.
    spikes = b"".join(pack_spike(Spike("A-020", sample_of(ms) + 600, 1)) for c, ms in events if c == 101)
    await h.fake.push_spikes(spikes)

    await h.until(lambda: h.service.status_json()["sync"][0]["matched"] == len(events))
    stat = h.service.status_json()["sync"][0]
    assert (stat["box"], stat["spuriousEdges"], stat["unmatchedStrobes"]) == (3, 0, 0)

    scope = await h.service.open_scope(
        "psth", 3, "a-020", {"triggerCodes": [101], "preMs": 100, "postMs": 200, "binMs": 10}
    )
    await h.until(lambda: any(e["evt"] == Evt.INTAN_SCOPE_DATA for e in h.events))
    data = h.last(Evt.INTAN_SCOPE_DATA)
    assert data["scopeId"] == scope and data["channel"] == "A-020"
    assert data["data"]["trials"] == 4
    assert data["data"]["alignment"] == "sync"
    assert all(row == [20.0] for row in data["data"]["rasters"])
    assert data["data"]["counts"][12] == 4  # the bin holding +20 ms

    # Nothing has changed, so the same PSTH is not sent again and again.
    sent = sum(1 for e in h.events if e["evt"] == Evt.INTAN_SCOPE_DATA and e["data"]["scopeId"] == scope)
    await asyncio.sleep(1.0)
    assert sum(1 for e in h.events if e["evt"] == Evt.INTAN_SCOPE_DATA and e["data"]["scopeId"] == scope) == sent

    # A channel that belongs to another box is refused, not silently empty.
    with pytest.raises(IntanNotReady, match="not one of box 3"):
        await h.service.open_scope("isi", 3, "A-002", {})


async def test_a_spikescope_streams_its_channel_and_cuts_waveforms(rig, tmp_path):
    h = await rig()
    await h.service.configure("s1", "g1", config(tmp_path), "x")
    await h.service.start_recording()

    await h.service.open_scope("spikescope", 1, "A-004", {})
    assert h.fake.params["a-004.tcpdataoutputenabledhigh"] == "true"

    layout = FrameLayout(amplifier=(("A-004", "high"),), digital_in=True)
    data = b""
    for first in range(0, 6400, FRAMES_PER_BLOCK):
        stamps = tuple(range(first, first + FRAMES_PER_BLOCK))
        data += pack_waveform_block(
            layout,
            WaveformBlock(stamps, {("A-004", "high"): tuple(32768 + (t % 7) for t in stamps)}, tuple(0 for _ in stamps)),
        )
    await h.fake.push_spikes(pack_spike(Spike("A-004", 3000, 1)))
    await asyncio.sleep(0.05)
    await h.fake.push_waveform(data)

    await h.until(
        lambda: any(
            e["evt"] == Evt.INTAN_SCOPE_DATA and e["data"]["data"].get("added") for e in h.events
        )
    )
    payload = next(
        e["data"]["data"] for e in h.events
        if e["evt"] == Evt.INTAN_SCOPE_DATA and e["data"]["data"].get("added")
    )
    snippet = payload["added"][0]
    assert snippet["sample"] == 3000
    assert len(snippet["microvolts"]) == 60 + 120 + 1  # 2 ms before, 4 ms after
    assert payload["streaming"] is True

    # Five channels would outrun TCP; the fifth is refused and nothing changes.
    for n in (5, 6, 7):
        await h.service.open_scope("spikescope", 1, f"A-{n:03d}", {})
    with pytest.raises(IntanNotReady, match="At most 4"):
        await h.service.open_scope("spikescope", 1, "A-008", {})
    assert "a-008.tcpdataoutputenabledhigh" not in h.fake.params


async def test_closing_the_last_scope_stops_the_stream_it_asked_for(rig, tmp_path):
    h = await rig()
    await h.service.configure("s1", "g1", config(tmp_path), "x")
    scope = await h.service.open_scope("spikescope", 1, "A-001", {})
    await h.service.close_scope(scope)
    assert h.fake.params["a-001.tcpdataoutputenabledhigh"] == "false"
    await h.service.close_scope(scope)  # idempotent


async def test_synthetic_data_has_no_sync_line_so_the_check_is_off_and_strobes_align_by_arrival(rig, tmp_path):
    """RHX's demo mode generates its own digital inputs, which no box drives.
    The counters would diagnose wiring that does not exist, so they are not
    published; the PSTH still draws, placing each strobe by when it arrived."""
    h = await rig()  # the fake is synthetic by default, as RHX's demo is
    assert h.service.status_json()["synthetic"] is False  # not yet asked
    await h.service.configure("s1", "g1", config(tmp_path), "x")
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
    await h.until(lambda: h.service._newest_sample >= 63_000)
    newest = h.service._newest_sample
    h.service.on_strobe(3, 101, 5000)
    await asyncio.sleep(0.02)
    assert h.service.status_json()["sync"] == []

    # The strobe landed at the newest sample seen when it arrived; a spike
    # 20 ms after that shows up at +20 ms.
    placed = h.service._triggers[3][101][0]
    assert placed == newest
    await h.fake.push_spikes(pack_spike(Spike("A-020", placed + 600, 1)))
    await h.fake.push_waveform(b"".join(din_block(f, {}) for f in range(64_000, 80_000, FRAMES_PER_BLOCK)))

    scope = await h.service.open_scope(
        "psth", 3, "A-020", {"triggerCodes": [101], "preMs": 100, "postMs": 200, "binMs": 10}
    )
    await h.until(
        lambda: any(
            e["evt"] == Evt.INTAN_SCOPE_DATA and e["data"]["scopeId"] == scope and e["data"]["data"]["trials"]
            for e in h.events
        )
    )
    data = h.last(Evt.INTAN_SCOPE_DATA)["data"]
    assert data["alignment"] == "arrival"
    assert data["rasters"] == [[20.0]]


async def test_a_spikescope_can_move_to_another_channel(rig, tmp_path):
    """Swapping one streamed channel for another keeps the frame the same
    size; the parser is told where RHX's clock stood when the swap was
    acknowledged and switches there. Before this, the old layout went on
    confirming forever and the new channel never read as streaming."""
    h = await rig()
    await h.service.configure("s1", "g1", config(tmp_path), "x")
    await h.service.start_recording()
    scope = await h.service.open_scope("spikescope", 1, "A-004", {})

    def push(name: str, first: int, blocks: int, level: int) -> bytes:
        layout = FrameLayout(amplifier=((name, "high"),), digital_in=True)
        out = b""
        for start in range(first, first + blocks * FRAMES_PER_BLOCK, FRAMES_PER_BLOCK):
            stamps = tuple(range(start, start + FRAMES_PER_BLOCK))
            out += pack_waveform_block(
                layout,
                WaveformBlock(stamps, {(name, "high"): tuple(level for _ in stamps)}, tuple(0 for _ in stamps)),
            )
        return out

    await h.fake.push_waveform(push("A-004", 0, 4, 33000))
    await h.until(lambda: h.service._snippets["A-004"].ring.newest is not None)

    await h.service.update_scope(scope, "A-009", None)
    assert h.fake.params["a-004.tcpdataoutputenabledhigh"] == "false"
    assert h.fake.params["a-009.tcpdataoutputenabledhigh"] == "true"
    assert set(h.service._snippets) == {"A-009"}
    marker = int(h.fake.params["currenttimestamp"])
    assert marker > 4 * FRAMES_PER_BLOCK

    # A block from before the marker is ambiguous and dropped (so is the one
    # the parser was still holding for confirmation); blocks from the marker
    # on are the new channel's and fill its ring.
    await h.fake.push_waveform(push("A-004", 4 * FRAMES_PER_BLOCK, 1, 33000) + push("A-009", marker, 8, 34000))
    await h.until(lambda: h.service._snippets["A-009"].ring.newest is not None)
    assert h.service._waveform is not None and h.service._waveform.dropped_blocks == 2
    assert h.service._snippets["A-009"].ring.cut(marker + 300, 2, 2) == [34000] * 5

    await h.fake.push_spikes(pack_spike(Spike("A-009", marker + 400, 1)))
    await h.until(
        lambda: any(
            e["evt"] == Evt.INTAN_SCOPE_DATA and e["data"]["channel"] == "A-009" and e["data"]["data"]["streaming"]
            for e in h.events
        )
    )

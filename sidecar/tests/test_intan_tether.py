"""The tether alarm's detector (`RECORDING.md#tether-alarm`) against synthetic
RHX streams: what a cut tether, a lost ground and a chewing artifact look like
in a box's crossings, and what must NOT raise an alarm -- one dead site, a
short glitch, a stalled stream, every box going quiet at once."""

from __future__ import annotations

import random

from ephymeris_sidecar.intan.analysis import (
    TETHER_BASELINE_S,
    TETHER_SUSTAIN_S,
    TetherBoard,
    TetherChange,
)
from tests.test_intan_service import rig as rig_service  # noqa: F401

RATE = 1000  # samples a second: small numbers, same arithmetic
SITES = [f"A-{n:03d}" for n in range(16)]


class Rig:
    """A fake RHX: spikes per site at given rates, the waveform delivered a
    second at a time, every change the board reports collected."""

    def __init__(self, boxes: dict[int, list[str]] | None = None, seed: int = 7) -> None:
        self.board = TetherBoard(float(RATE))
        self.random = random.Random(seed)
        self.now = 0
        self.changes: list[TetherChange] = []
        for box, channels in (boxes or {1: SITES}).items():
            self.board.watch(box, channels, 0)

    def run(self, seconds: int, rates: dict[str, float], *, together: int = 0, deliver: bool = True) -> None:
        """`rates`: Hz per site (others silent). `together`: crossings per second
        that land on every listed site at the same sample (an artifact)."""
        for _ in range(seconds):
            start = self.now
            for channel, hz in rates.items():
                for _ in range(self._poisson(hz)):
                    self.board.add_spike(channel, start + self.random.randrange(RATE))
            for _ in range(together):
                at = start + self.random.randrange(RATE)
                for channel in rates:
                    self.board.add_spike(channel, at)
            self.now += RATE
            if deliver:
                self.changes += self.board.delivered(start, self.now - 1)

    def _poisson(self, hz: float) -> int:
        count, t = 0, self.random.expovariate(hz) if hz > 0 else 2.0
        while t < 1.0:
            count += 1
            t += self.random.expovariate(hz)
        return count

    def states(self, box: int = 1) -> list[str]:
        return [c.state for c in self.changes if c.box == box]


HEALTHY = {site: 8.0 for site in SITES}
BASELINE = int(TETHER_BASELINE_S) + 2
SUSTAIN = int(TETHER_SUSTAIN_S)


def test_a_healthy_box_learns_its_baseline_and_never_alarms():
    rig = Rig()
    rig.run(BASELINE + 600, HEALTHY)
    assert rig.states() == ["ok"]
    assert rig.board.watches_silence(1)


def test_a_cut_tether_alarms_after_the_sustain_and_dates_the_fault_from_its_start():
    rig = Rig()
    rig.run(BASELINE, HEALTHY)
    cut_at = rig.now
    rig.run(SUSTAIN + 5, {})
    assert rig.states() == ["ok", "silent"]
    alarm = rig.changes[-1]
    # Dated from the first silent WINDOW: within a window and the lag of the cut.
    assert cut_at <= alarm.at_sample <= cut_at + 2 * RATE

    rig.run(SUSTAIN + 5, HEALTHY)  # reconnected
    assert rig.states() == ["ok", "silent", "ok"]


def test_a_lost_ground_is_noisy():
    rig = Rig()
    rig.run(BASELINE, HEALTHY)
    rig.run(SUSTAIN + 2, {site: 80.0 for site in SITES})
    assert rig.states() == ["ok", "noisy"]


def test_a_chewing_artifact_is_noisy_at_an_ordinary_rate():
    """Crossings at a believable rate, but landing on every site at once."""
    rig = Rig()
    rig.run(BASELINE, HEALTHY)
    rig.run(SUSTAIN + 2, {site: 1.0 for site in SITES}, together=6)
    assert rig.states() == ["ok", "noisy"]


def test_one_dead_site_is_not_an_alarm():
    rig = Rig()
    rig.run(BASELINE, HEALTHY)
    rig.run(300, {site: 8.0 for site in SITES[1:]})
    assert rig.states() == ["ok"]


def test_a_glitch_shorter_than_the_sustain_is_not_an_alarm():
    rig = Rig()
    rig.run(BASELINE, HEALTHY)
    for _ in range(5):
        rig.run(SUSTAIN // 2, {})
        rig.run(5, HEALTHY)
    assert rig.states() == ["ok"]


def test_a_stalled_stream_is_not_a_silent_tether():
    """No samples delivered: nothing is judged, however long."""
    rig = Rig()
    rig.run(BASELINE, HEALTHY)
    rig.run(SUSTAIN * 3, {}, deliver=False)
    rig.run(10, HEALTHY)  # the stream resumes, later samples
    assert rig.states() == ["ok"]


def test_every_box_silent_at_once_is_upstream_not_a_tether():
    rig = Rig({1: SITES[:8], 2: SITES[8:]})
    rig.run(BASELINE, HEALTHY)
    rig.run(SUSTAIN * 2, {})
    assert rig.states(1) == ["ok"] and rig.states(2) == ["ok"]
    assert rig.board.all_silent


def test_one_box_silent_while_another_runs_is_that_box_s_tether():
    rig = Rig({1: SITES[:8], 2: SITES[8:]})
    rig.run(BASELINE, HEALTHY)
    rig.run(SUSTAIN + 2, {site: 8.0 for site in SITES[8:]})
    assert rig.states(1) == ["ok", "silent"] and rig.states(2) == ["ok"]


def test_a_baseline_too_quiet_to_tell_quiet_from_gone_never_alarms_silent():
    rig = Rig()
    rig.run(BASELINE, {SITES[0]: 1.0})  # 1 Hz for the whole box
    rig.run(SUSTAIN * 2, {})
    assert rig.states() == ["ok"]
    assert not rig.board.watches_silence(1)


def test_a_box_started_later_is_judged_from_its_own_start():
    rig = Rig({1: SITES[:8]})
    rig.run(60, HEALTHY)
    rig.board.watch(2, SITES[8:], rig.now)
    rig.run(BASELINE, HEALTHY)
    assert rig.states(1) == ["ok"]
    assert rig.states(2) == ["ok"]  # learned from its own START, not before it


# --- through the service, against the fake RHX ---------------------------------


async def test_a_cut_tether_reaches_the_status_rhx_s_notes_and_the_session_log(rig_service, tmp_path, monkeypatch):
    """End to end on real sockets, with the windows shortened: three seconds
    of baseline, two of sustain."""
    import asyncio

    from ephymeris_sidecar.intan import analysis
    from ephymeris_sidecar.intan.streams import FRAMES_PER_BLOCK, Spike, pack_spike
    from tests.test_intan_service import FS, config, din_block

    monkeypatch.setattr(analysis, "TETHER_BASELINE_S", 3.0)
    monkeypatch.setattr(analysis, "TETHER_SUSTAIN_S", 2.0)
    h = await rig_service()
    told: list[tuple[str, int, str, str]] = []

    async def tell(*args) -> None:  # noqa: ANN002
        told.append(args)

    h.service.on_tether = tell
    await h.service.configure("s1", "g1", config(tmp_path), "x")
    await h.service.start_recording()
    h.service.box_started(1, "R7")
    await asyncio.sleep(0)

    # Four healthy seconds on box 1's sixteen sites, then nothing: the waveform
    # runs on to eight seconds, so the stream is fine and the tether is not.
    rnd = random.Random(3)
    spikes = [
        Spike(f"A-{n:03d}", rnd.randrange(4 * FS), 1) for n in range(16) for _ in range(40)
    ]
    await h.fake.push_spikes(b"".join(pack_spike(s) for s in sorted(spikes, key=lambda s: s.timestamp)))
    await h.until(lambda: h.service._runs[1].counts.get("A-000") == 40)
    await h.fake.push_waveform(b"".join(din_block(f, {}) for f in range(0, 8 * FS + FRAMES_PER_BLOCK, FRAMES_PER_BLOCK)))

    await h.until(lambda: any(t["box"] == 1 and t["state"] == "silent" for t in h.service.status_json()["tether"]))
    [stat] = [t for t in h.service.status_json()["tether"] if t["box"] == 1]
    assert stat["since"] is not None and stat["acknowledged"] is False and stat["watchesSilence"]
    await h.until(lambda: any("BOX1 TETHER SILENT" in n for n in h.fake.notes))
    await h.until(lambda: len(told) == 1)
    assert told[0][:3] == ("s1", 1, "silent")

    assert await h.service.acknowledge_tether(1) is True
    assert h.service.status_json()["tether"][0]["acknowledged"] is True
    assert await h.service.acknowledge_tether(3) is False  # no alarm there

    # The box ends: its watch and alarm go with it.
    h.service.box_ended(1, "R7", "end")
    assert h.service.status_json()["tether"] == []

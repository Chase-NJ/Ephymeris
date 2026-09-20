"""The pure layer behind the live recording views.

The `EdgeMatcher` tests are the ones that matter. Everything it can get wrong
yields a PSTH that looks like data -- events attributed to their neighbours --
rather than an error.
"""

from __future__ import annotations

from ephymeris_sidecar.intan.analysis import (
    EdgeDetector,
    EdgeMatcher,
    SpikeRing,
    WaveformRing,
    isi_histogram,
    psth,
)

FS = 30000.0


def samples(ms: float, *, offset: int = 900_000, drift: float = 1.0) -> int:
    """Where an Arduino-ms instant lands on the recording clock."""
    return offset + int(round(ms * drift * FS / 1000.0))


# --- edges ------------------------------------------------------------------


def test_an_edge_is_seen_once_even_across_a_block_boundary():
    detector = EdgeDetector(digital_in=3)
    bit = 0b100
    first = detector.feed((0, 1, 2, 3), (0, 0, bit, bit))
    second = detector.feed((4, 5, 6, 7), (bit, bit, 0, bit))
    assert first == [2]
    assert second == [7]  # still high at 4 is not a second edge


def test_a_line_that_is_high_when_the_stream_opens_is_not_an_event():
    detector = EdgeDetector(digital_in=1)
    assert detector.feed((0, 1, 2), (1, 1, 1)) == []
    assert detector.feed((3, 4, 5), (1, 0, 1)) == [5]


def test_other_boxes_inputs_are_not_this_box_s_edges():
    detector = EdgeDetector(digital_in=2)
    detector.feed((0,), (0,))
    assert detector.feed((1, 2, 3), (0b0001, 0b0101, 0b1000)) == []
    assert detector.feed((4, 5), (0b0000, 0b0010)) == [5]


# --- matching ---------------------------------------------------------------


def run(matcher: EdgeMatcher, strobes, edges):
    out = []
    for code, ms in strobes:
        out += matcher.add_strobe(code, ms)
    out += matcher.add_edges(edges)
    return out


def test_every_strobe_gets_its_own_edge():
    strobes = [(101, 0), (222, 640), (233, 1900), (246, 2400)]
    got = run(EdgeMatcher(FS), strobes, [samples(ms) for _, ms in strobes])
    assert [(e.code, e.sample) for e in got] == [(c, samples(ms)) for c, ms in strobes]


def test_a_spurious_leading_edge_does_not_shift_every_event_by_one():
    """THE TRAP. The Mega's pins twitch as it resets, before START. Matched by
    count, that one edge attributes every event in the session to the strobe
    before it -- and the PSTH still looks like a PSTH."""
    strobes = [(101, 0), (222, 640), (233, 1900), (246, 2400), (101, 9000)]
    edges = [samples(-350)] + [samples(ms) for _, ms in strobes]
    matcher = EdgeMatcher(FS)
    got = run(matcher, strobes, edges)
    assert [(e.code, e.sample) for e in got] == [(c, samples(ms)) for c, ms in strobes]
    assert matcher.spurious_edges == 1 and matcher.unmatched_strobes == 0


def test_a_glitch_in_the_middle_is_dropped_and_the_next_event_still_lands():
    strobes = [(101, 0), (222, 500), (233, 4000), (246, 4600)]
    edges = [samples(0), samples(500), samples(2100), samples(4000), samples(4600)]
    matcher = EdgeMatcher(FS)
    got = run(matcher, strobes, edges)
    assert [e.sample for e in got] == [samples(ms) for _, ms in strobes]
    assert matcher.spurious_edges == 1


def test_a_missing_pulse_costs_one_event_not_the_rest_of_the_session():
    strobes = [(101, 0), (222, 500), (233, 1500), (246, 2600)]
    edges = [samples(0), samples(500), samples(2600)]  # 233's pulse never came
    matcher = EdgeMatcher(FS)
    got = run(matcher, strobes, edges)
    assert [(e.code, e.sample is not None) for e in got] == [
        (101, True), (222, True), (233, False), (246, True)
    ]
    assert got[-1].sample == samples(2600)


def test_half_a_percent_of_clock_drift_is_not_a_mismatch():
    """The Mega runs on a ceramic resonator. Over a twenty-second gap the two
    clocks honestly disagree by ~100 ms; a fixed tolerance would call that a
    missing pulse, every long inter-trial interval."""
    strobes = [(101, 0), (222, 700), (233, 20_700), (246, 21_300), (101, 61_300)]
    edges = [samples(ms, drift=1.005) for _, ms in strobes]
    matcher = EdgeMatcher(FS)
    got = run(matcher, strobes, edges)
    assert all(e.sample is not None for e in got) and len(got) == 5
    assert matcher.spurious_edges == 0


def test_it_does_not_matter_which_stream_arrives_first():
    strobes = [(101, 0), (222, 640), (233, 1900)]
    edges = [samples(ms) for _, ms in strobes]
    matcher = EdgeMatcher(FS)
    got = matcher.add_edges(edges)  # TCP beat the serial line
    for code, ms in strobes:
        got += matcher.add_strobe(code, ms)
    assert [e.sample for e in got] == edges


def test_an_unconnected_sync_line_does_not_queue_strobes_forever():
    matcher = EdgeMatcher(FS)
    got = []
    for n in range(200):
        got += matcher.add_strobe(101, n * 1000)
    assert len(got) == 200 - EdgeMatcher.MAX_PENDING
    assert all(e.sample is None for e in got)


# --- histograms -------------------------------------------------------------


def test_isi_bins_intervals_and_owns_up_to_the_ones_it_cannot_show():
    spikes = [0, 300, 600, 1500, 30_000]  # 10, 10, 30, 950 ms
    result = isi_histogram(spikes, FS, span_ms=50, bin_ms=5)
    assert result["counts"][2] == 2 and result["counts"][6] == 1
    assert result["beyond"] == 1 and result["intervals"] == 4
    assert sum(result["counts"]) + result["beyond"] == result["intervals"]


def test_psth_counts_only_trials_whose_window_has_closed():
    """A trial still filling would add its early bins and not its late ones, and
    the right of the histogram would sag by however recent the last trigger is."""
    triggers = [30_000, 90_000, 150_000]
    spikes = sorted(t + d for t in triggers for d in (-1500, 300, 3000))
    kwargs = dict(sample_rate=FS, pre_ms=100, post_ms=200, bin_ms=50, max_trials=50)

    early = psth(spikes, triggers, newest_sample=152_000, **kwargs)  # third still open
    assert early["trials"] == 2 and len(early["rasters"]) == 2

    late = psth(spikes, triggers, newest_sample=160_000, **kwargs)
    assert late["trials"] == 3
    assert late["rasters"][0] == [-50.0, 10.0, 100.0]
    assert late["counts"] == [0, 3, 3, 0, 3, 0]
    # 3 spikes in a 50 ms bin over 3 trials = 20 Hz.
    assert late["rateHz"][1] == 20.0


def test_psth_keeps_the_newest_trials_when_there_are_too_many():
    triggers = [n * 30_000 for n in range(1, 8)]
    result = psth([], triggers, FS, 100, 100, 50, max_trials=3, newest_sample=10**7)
    assert result["trials"] == 3


# --- rings ------------------------------------------------------------------


def test_a_snippet_is_cut_by_sample_number_or_not_at_all():
    ring = WaveformRing(capacity=1000)
    ring.extend(5000, tuple(range(128)))
    ring.extend(5128, tuple(range(128, 256)))
    assert ring.cut(5130, before=2, after=3) == [128, 129, 130, 131, 132, 133]
    assert ring.cut(5250, before=2, after=30) is None  # the tail has not arrived
    assert ring.cut(5001, before=5, after=5) is None   # before the ring begins


def test_a_gap_in_the_timestamps_empties_the_ring():
    """A snippet cut across a gap is two unrelated pieces of signal drawn as
    one spike."""
    ring = WaveformRing(capacity=1000)
    ring.extend(0, tuple(range(128)))
    ring.extend(1024, tuple(range(128)))  # blocks were lost in between
    assert ring.cut(100, before=5, after=5) is None
    assert ring.cut(1030, before=5, after=5) is not None


def test_the_spike_ring_counts_a_recent_window():
    ring = SpikeRing(capacity=4)
    for t in (10, 20, 30, 40, 50):
        ring.add(t)
    assert ring.snapshot() == [20, 30, 40, 50]
    assert ring.count_since(35) == 2

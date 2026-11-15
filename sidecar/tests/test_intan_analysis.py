"""The pure layer behind the sync check and the live firing map.

The `EdgeMatcher` tests are the ones that matter. Everything it can get wrong
yields events attributed to their neighbours, which looks like data -- and
offline alignment reruns the same matcher -- rather than an error.
"""

from __future__ import annotations

from ephymeris_sidecar.intan.analysis import (
    EdgeDetector,
    EdgeMatcher,
    SampleClock,
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


# A spine run's stream, as BoxSpine.h strobes it: every strobe of a tick carries
# that tick's ms, and a tick-pulsed board pulses once per tick that strobes.
TICKS = [
    (0, [17, 48, 29, 42]), (10, [40, 44]), (110, [43, 45, 46]), (140, [47]), (191, [48, 29, 42]),
]


def tick_strobes(ticks):
    return [(code, ms) for ms, codes in ticks for code in codes]


def test_a_tick_pulsed_run_gives_every_strobe_of_a_tick_its_tick_s_one_edge():
    matcher = EdgeMatcher(FS, tick_pulsed=True)
    got = run(matcher, tick_strobes(TICKS), [samples(ms) for ms, _ in TICKS])
    assert [(e.code, e.ms, e.sample) for e in got] == [(c, ms, samples(ms)) for c, ms in tick_strobes(TICKS)]
    assert matcher.spurious_edges == 0 and matcher.unmatched_strobes == 0


def test_a_per_strobe_run_still_takes_one_edge_per_strobe_sharing_a_ms_or_not():
    """GRGL pulses once per strobe, 0.7 ms apart: two strobes of one ms are two
    edges, and the second is the second strobe's."""
    strobes = [(101, 0), (230, 640), (243, 640), (222, 1900)]
    edges = [samples(0), samples(640), samples(640.7), samples(1900)]
    matcher = EdgeMatcher(FS)
    got = run(matcher, strobes, edges)
    assert [(e.code, e.sample) for e in got] == list(zip([c for c, _ in strobes], edges))
    assert matcher.spurious_edges == 0 and matcher.unmatched_strobes == 0


def test_a_strobe_of_a_tick_whose_edge_is_already_paired_takes_that_edge():
    """The edges can beat the serial line, so a tick's edge may be paired on its
    first strobes, before the rest of that tick's strobes have arrived."""
    matcher = EdgeMatcher(FS, tick_pulsed=True)
    got = matcher.add_edges([samples(ms) for ms, _ in TICKS])
    for code, ms in tick_strobes(TICKS):
        got += matcher.add_strobe(code, ms)
    assert [(e.code, e.sample) for e in got] == [(c, samples(ms)) for c, ms in tick_strobes(TICKS)]
    assert matcher.unmatched_strobes == 0 and matcher.spurious_edges == 0


def test_an_owed_rise_still_pairs_with_its_own_tick():
    """Two ticks that strobe, stepped in one pass where millis() skipped 110:
    110's edge rises when the pass runs, at 111, and 111's is owed a pulse and
    a gap later. Each tick keeps its own edge."""
    ticks = [(0, [17]), (10, [40]), (110, [46]), (111, [47]), (140, [42])]
    edges = [samples(0), samples(10), samples(111), samples(111.7), samples(140)]
    matcher = EdgeMatcher(FS, tick_pulsed=True)
    got = run(matcher, tick_strobes(ticks), edges)
    assert [e.sample for e in got] == edges
    assert matcher.spurious_edges == 0 and matcher.unmatched_strobes == 0


def test_a_tick_pulsed_run_drops_the_reset_twitch_too():
    matcher = EdgeMatcher(FS, tick_pulsed=True)
    got = run(matcher, tick_strobes(TICKS), [samples(-350)] + [samples(ms) for ms, _ in TICKS])
    assert [e.sample for e in got] == [samples(ms) for _, ms in tick_strobes(TICKS)]
    assert matcher.spurious_edges == 1 and matcher.unmatched_strobes == 0


def test_a_tick_whose_pulse_never_came_releases_each_of_its_strobes():
    edges = [samples(ms) for ms, _ in TICKS if ms != 110]
    matcher = EdgeMatcher(FS, tick_pulsed=True)
    got = run(matcher, tick_strobes(TICKS), edges)
    assert [(e.code, e.sample is not None) for e in got] == [
        (c, ms != 110) for c, ms in tick_strobes(TICKS)]
    assert matcher.unmatched_strobes == 3 and matcher.spurious_edges == 0


def test_a_tick_pulsed_anchor_gives_up_on_leading_ticks_not_strobes():
    """MAX_LEAD counts strobing times: two leading ticks of six strobes whose
    pulses never came are two to skip, not six."""
    edges = [samples(ms) for ms, _ in TICKS[2:]]
    matcher = EdgeMatcher(FS, tick_pulsed=True)
    got = run(matcher, tick_strobes(TICKS), edges)
    assert [e.sample is not None for e in got] == [ms >= 110 for _, ms in tick_strobes(TICKS)]
    assert matcher.unmatched_strobes == 6


def test_an_unconnected_tick_pulsed_line_does_not_queue_strobes_forever():
    matcher = EdgeMatcher(FS, tick_pulsed=True)
    got = []
    for n in range(200):
        for code in (40, 44, 46):
            got += matcher.add_strobe(code, n * 1000)
    assert len(got) == 3 * (200 - EdgeMatcher.MAX_PENDING)
    assert all(e.sample is None for e in got) and matcher.unmatched_strobes == len(got)


# --- latency ----------------------------------------------------------------


def test_a_spike_s_lag_is_measured_from_the_tightest_clock_read():
    clock = SampleClock(FS)
    assert clock.lag_ms(30_000, 10.0) is None  # not read yet
    # Sample n reached RHX at t = 4 + n / FS; two of the replies came back late.
    clock.read(30_000, 5.020)
    clock.read(60_000, 6.000)  # the tight one: offset 4.000
    clock.read(90_000, 7.004)
    # A spike at 2.5 s, which RHX had at t = 6.5, reaching us at 6.512 is 12 ms late.
    assert round(clock.lag_ms(75_000, 6.512), 3) == 12.0


def test_a_restarted_acquisition_forgets_the_old_offset():
    clock = SampleClock(FS)
    clock.read(300_000, 10.0)  # offset 0.0
    clock.read(30_000, 20.0)  # restarted at zero: offset 19.0, not min(0, 19)
    assert round(clock.lag_ms(30_000, 20.010), 3) == 10.0
    clock.read(-1, 30.0)  # RHX stopped: no read, no change
    assert round(clock.lag_ms(30_000, 20.010), 3) == 10.0


def test_old_clock_reads_age_out_so_drift_cannot_pile_up():
    clock = SampleClock(FS, window=2)
    clock.read(0, 1.000)  # offset 1.000, the tightest -- until it ages out
    clock.read(30_000, 2.010)
    clock.read(60_000, 3.010)
    assert round(clock.lag_ms(60_000, 3.010), 3) == 0.0

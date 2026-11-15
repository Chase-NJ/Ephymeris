"""Pure analysis behind the sync check and the live firing map. No I/O, no clocks.

Everything here is in the recording controller's own unit -- SAMPLES since
acquisition began -- and converts to time only at the edge, with the sample
rate RHX reports. The Arduino's milliseconds appear in exactly one place, the
`EdgeMatcher`, because reconciling the two clocks is that class's whole job.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from functools import reduce
from operator import and_, or_


# --------------------------------------------------------------------------- #
# Sync edges
# --------------------------------------------------------------------------- #


class EdgeDetector:
    """Rising edges of one bit of the digital-input word.

    `digital_in` is 1-based, as RHX's Recording Controller names its inputs
    (DIGITAL-IN-1 is bit 0). The state carries across blocks, so an edge that
    straddles a block boundary is seen once and a line that is simply HIGH when
    the stream opens is not an edge at all.
    """

    def __init__(self, digital_in: int) -> None:
        self._mask = 1 << (digital_in - 1)
        self._high: bool | None = None

    def feed(self, timestamps: tuple[int, ...], words: tuple[int, ...]) -> list[int]:
        mask = self._mask
        high = self._high
        # Nearly every block has no edge in it. OR-ing and AND-ing the whole
        # block settles that in two C-level passes instead of a Python loop
        # over 128 words, 234 times a second, per box.
        any_high = bool(reduce(or_, words) & mask)
        all_high = bool(reduce(and_, words) & mask)
        if any_high == all_high and (high is None or high == any_high):
            self._high = any_high
            return []
        edges: list[int] = []
        for timestamp, word in zip(timestamps, words):
            now = bool(word & mask)
            if now and high is False:
                edges.append(timestamp)
            high = now
        self._high = high
        return edges


@dataclass(frozen=True)
class MatchedEvent:
    """One strobe, with the recording sample its sync pulse rose on.

    `sample` is None when the pulse never arrived -- the strobe is still real
    (it is in the `.tsv`), it just has no place on the recording clock.
    """

    code: int
    ms: int
    sample: int | None


class EdgeMatcher:
    """Pair a box's serial strobes with the sync edges its pin produced.

    Each edge is one STROBING TIME: one strobe, from the trial runner, which
    pulses once per strobe; or one tick, from a spine run announced as
    tick-pulsed (`tick_pulsed`), which pulses once per tick that strobes, so
    every strobe of a tick (all sharing its millisecond) takes that tick's
    edge. So the Nth edge is the Nth strobing time -- in principle. Matching
    by count alone is exactly as fragile as that sentence: ONE extra edge (the
    line twitching as the Mega resets, a glitch on a long cable) and every
    later event is attributed to its neighbour, which draws a PSTH that looks
    like data. So order proposes and TIME disposes: an edge is accepted for a
    strobing time only if it lands where that time's own timestamp says it
    should, measured from the last accepted pair. An early edge is spurious
    and dropped; a late one means this time's pulse went missing, and its
    strobes are released unmatched.

    The tolerance is relative because the Mega's clock is a ceramic resonator,
    good to about half a percent: over a ten-second gap the two clocks
    legitimately disagree by tens of milliseconds. Measuring from the LAST pair
    rather than the first keeps that error from accumulating.

    The first pair has nothing to be measured from, so it is chosen as the
    earliest alignment under which two consecutive gaps agree -- which is what
    lets a leading spurious edge be discarded instead of anchoring everything.
    """

    ABS_TOLERANCE_MS = 4.0
    REL_TOLERANCE = 0.015
    #: How many leading strobing times (strobes, or ticks when tick-pulsed) may
    #: be given up on while finding the first pair.
    MAX_LEAD = 3
    #: Unpaired items tolerated before the oldest is given up on. A box whose
    #: sync line is simply not connected must not queue strobes forever.
    MAX_PENDING = 64

    def __init__(self, sample_rate: float, tick_pulsed: bool = False) -> None:
        self._per_ms = sample_rate / 1000.0
        self._tick_pulsed = tick_pulsed
        # Strobing times awaiting an edge: (ms, codes), one code each unless
        # tick-pulsed, where a strobe of the newest time's ms joins it.
        self._strobes: deque[tuple[int, list[int]]] = deque()
        self._edges: deque[int] = deque()
        self._anchor: tuple[int, int] | None = None  # (ms, sample)
        # Tick-pulsed: the last time released, (ms, sample), so a strobe of
        # that tick arriving after its edge was paired takes the same answer.
        self._released: tuple[int, int | None] | None = None
        self.spurious_edges = 0
        self.unmatched_strobes = 0

    def add_strobe(self, code: int, ms: int) -> list[MatchedEvent]:
        if self._tick_pulsed:
            if self._strobes and self._strobes[-1][0] == ms:
                self._strobes[-1][1].append(code)
                return []
            if not self._strobes and self._released is not None and self._released[0] == ms:
                sample = self._released[1]
                if sample is None:
                    self.unmatched_strobes += 1
                return [MatchedEvent(code, ms, sample)]
        self._strobes.append((ms, [code]))
        return self._drain()

    def add_edges(self, samples: list[int]) -> list[MatchedEvent]:
        self._edges.extend(samples)
        return self._drain()

    def _tolerance(self, gap_ms: float) -> float:
        return max(self.ABS_TOLERANCE_MS, abs(gap_ms) * self.REL_TOLERANCE)

    def _release(self, out: list[MatchedEvent], sample: int | None) -> None:
        """The oldest strobing time, every strobe of it at `sample`."""
        ms, codes = self._strobes.popleft()
        if sample is None:
            self.unmatched_strobes += len(codes)
        else:
            self._anchor = (ms, sample)
        self._released = (ms, sample)
        out.extend(MatchedEvent(code, ms, sample) for code in codes)

    def _drain(self) -> list[MatchedEvent]:
        out: list[MatchedEvent] = []
        while self._strobes:
            if self._anchor is None:
                if not self._find_anchor(out):
                    break
                continue
            if not self._edges:
                break
            ms = self._strobes[0][0]
            anchor_ms, anchor_sample = self._anchor
            gap_ms = ms - anchor_ms
            error_ms = (self._edges[0] - anchor_sample) / self._per_ms - gap_ms
            tolerance = self._tolerance(gap_ms)
            if error_ms < -tolerance:
                self._edges.popleft()          # too early to be this time's
                self.spurious_edges += 1
            elif error_ms > tolerance:
                self._release(out, None)       # its pulse never came
            else:
                self._release(out, self._edges.popleft())
        self._shed(out)
        return out

    def _find_anchor(self, out: list[MatchedEvent]) -> bool:
        strobes, edges = self._strobes, self._edges
        # Strobes are trusted far more than edges -- a serial line does not
        # invent events, while a sync line twitches through every reset and
        # flash before START -- so at most MAX_LEAD strobing times may be
        # skipped but any number of leading edges. Smallest total skip wins.
        for lead in range(self.MAX_LEAD + len(edges)):
            for skip_strobes in range(min(lead, self.MAX_LEAD) + 1):
                skip_edges = lead - skip_strobes
                if len(strobes) < skip_strobes + 2 or len(edges) < skip_edges + 2:
                    continue
                gap_ms = strobes[skip_strobes + 1][0] - strobes[skip_strobes][0]
                gap_samples = edges[skip_edges + 1] - edges[skip_edges]
                if abs(gap_samples / self._per_ms - gap_ms) > self._tolerance(gap_ms):
                    continue
                for _ in range(skip_strobes):
                    self._release(out, None)
                for _ in range(skip_edges):
                    edges.popleft()
                    self.spurious_edges += 1
                self._release(out, edges.popleft())
                return True
        return False

    def _shed(self, out: list[MatchedEvent]) -> None:
        while len(self._strobes) > self.MAX_PENDING:
            self._release(out, None)
        while len(self._edges) > self.MAX_PENDING:
            self._edges.popleft()
            self.spurious_edges += 1


# --------------------------------------------------------------------------- #
# Latency
# --------------------------------------------------------------------------- #

#: Clock reads kept. At one a second this is half a minute: long enough for a
#: tight bound, short enough that the two clocks' drift (tens of ppm: about a
#: millisecond over the window at worst) never builds up inside it.
CLOCK_WINDOW = 30


class SampleClock:
    """Where RHX's sample clock stands against ours, to time a spike's trip.

    Each `read` is a `currenttimestamp` reply and the time it came back. RHX
    had that sample no later than the reply, so `at - sample / rate` bounds
    the clocks' offset from above, and the SMALLEST recent bound is the
    tightest. A spike's lag is then measured from RHX's clock reaching its
    sample, and leaves out the USB transfer before that, which no client can
    see or shorten. On RHX 3.5.0 it reads about 10 ms LOW: `currenttimestamp`
    trails what RHX has already written to TCP (`RECORDING.md#live-firing-map`).
    Times are passed in, so this stays clock-free.
    """

    def __init__(self, rate: float, window: int = CLOCK_WINDOW) -> None:
        self._rate = rate
        self._bounds: deque[float] = deque(maxlen=window)
        self._last = -1

    def read(self, sample: int, at: float) -> None:
        if sample < 0:
            return  # not acquiring
        if sample < self._last:
            self._bounds.clear()  # acquisition restarted at zero
        self._last = sample
        self._bounds.append(at - sample / self._rate)

    def lag_ms(self, sample: int, at: float) -> float | None:
        """None until the clock has been read since acquisition (re)started."""
        if not self._bounds or sample < 0:
            return None
        return (at - (sample / self._rate + min(self._bounds))) * 1000.0

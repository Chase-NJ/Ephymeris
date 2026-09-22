"""Pure analysis behind the live recording views. No I/O, no clocks.

Everything here is in the recording controller's own unit -- SAMPLES since
acquisition began -- and converts to time only at the edge, with the sample
rate RHX reports. The Arduino's milliseconds appear in exactly one place, the
`EdgeMatcher`, because reconciling the two clocks is that class's whole job.
"""

from __future__ import annotations

from array import array
from bisect import bisect_left, bisect_right
from collections import deque
from dataclasses import dataclass
from functools import reduce
from math import ceil
from operator import and_, or_
from typing import Sequence


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

    The firmware pulses once per strobe, so the Nth edge is the Nth strobe --
    in principle. Matching by count alone is exactly as fragile as that
    sentence: ONE extra edge (the line twitching as the Mega resets, a glitch
    on a long cable) and every later event is attributed to its neighbour,
    which draws a PSTH that looks like data. So order proposes and TIME
    disposes: an edge is accepted for a strobe only if it lands where the
    strobe's own timestamp says it should, measured from the last accepted
    pair. An early edge is spurious and dropped; a late one means this strobe's
    pulse went missing, and the strobe is released unmatched.

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
    #: How many leading STROBES may be given up on while finding the first pair.
    MAX_LEAD = 3
    #: Unpaired items tolerated before the oldest is given up on. A box whose
    #: sync line is simply not connected must not queue strobes forever.
    MAX_PENDING = 64

    def __init__(self, sample_rate: float) -> None:
        self._per_ms = sample_rate / 1000.0
        self._strobes: deque[tuple[int, int]] = deque()
        self._edges: deque[int] = deque()
        self._anchor: tuple[int, int] | None = None  # (ms, sample)
        self.spurious_edges = 0
        self.unmatched_strobes = 0

    def add_strobe(self, code: int, ms: int) -> list[MatchedEvent]:
        self._strobes.append((code, ms))
        return self._drain()

    def add_edges(self, samples: list[int]) -> list[MatchedEvent]:
        self._edges.extend(samples)
        return self._drain()

    def _tolerance(self, gap_ms: float) -> float:
        return max(self.ABS_TOLERANCE_MS, abs(gap_ms) * self.REL_TOLERANCE)

    def _drain(self) -> list[MatchedEvent]:
        out: list[MatchedEvent] = []
        while self._strobes:
            if self._anchor is None:
                if not self._find_anchor(out):
                    break
                continue
            if not self._edges:
                break
            code, ms = self._strobes[0]
            anchor_ms, anchor_sample = self._anchor
            gap_ms = ms - anchor_ms
            error_ms = (self._edges[0] - anchor_sample) / self._per_ms - gap_ms
            tolerance = self._tolerance(gap_ms)
            if error_ms < -tolerance:
                self._edges.popleft()          # too early to be this strobe's
                self.spurious_edges += 1
            elif error_ms > tolerance:
                self._strobes.popleft()        # its pulse never came
                self.unmatched_strobes += 1
                out.append(MatchedEvent(code, ms, None))
            else:
                self._strobes.popleft()
                sample = self._edges.popleft()
                self._anchor = (ms, sample)
                out.append(MatchedEvent(code, ms, sample))
        self._shed(out)
        return out

    def _find_anchor(self, out: list[MatchedEvent]) -> bool:
        strobes, edges = self._strobes, self._edges
        # Strobes are trusted far more than edges -- a serial line does not
        # invent events, while a sync line twitches through every reset and
        # flash before START -- so at most MAX_LEAD strobes may be skipped but
        # any number of leading edges. Smallest total skip wins.
        for lead in range(self.MAX_LEAD + len(edges)):
            for skip_strobes in range(min(lead, self.MAX_LEAD) + 1):
                skip_edges = lead - skip_strobes
                if len(strobes) < skip_strobes + 2 or len(edges) < skip_edges + 2:
                    continue
                gap_ms = strobes[skip_strobes + 1][1] - strobes[skip_strobes][1]
                gap_samples = edges[skip_edges + 1] - edges[skip_edges]
                if abs(gap_samples / self._per_ms - gap_ms) > self._tolerance(gap_ms):
                    continue
                for _ in range(skip_strobes):
                    code, ms = strobes.popleft()
                    self.unmatched_strobes += 1
                    out.append(MatchedEvent(code, ms, None))
                for _ in range(skip_edges):
                    edges.popleft()
                    self.spurious_edges += 1
                code, ms = strobes.popleft()
                sample = edges.popleft()
                self._anchor = (ms, sample)
                out.append(MatchedEvent(code, ms, sample))
                return True
        return False

    def _shed(self, out: list[MatchedEvent]) -> None:
        while len(self._strobes) > self.MAX_PENDING:
            code, ms = self._strobes.popleft()
            self.unmatched_strobes += 1
            out.append(MatchedEvent(code, ms, None))
        while len(self._edges) > self.MAX_PENDING:
            self._edges.popleft()
            self.spurious_edges += 1


# --------------------------------------------------------------------------- #
# Spikes
# --------------------------------------------------------------------------- #


class SpikeRing:
    """One channel's recent spike times, in samples, oldest first.

    A preallocated int64 array, eight bytes a spike: a deque of Python ints
    costs five times that, and a noisy 128-channel probe would hold a hundred
    megabytes of timestamps by the end of a session.

    `complete_since` is the sample from which the ring holds EVERY spike the
    socket delivered. It moves when the oldest spike is evicted and when the
    stream is reopened after a gap, and it is what lets a PSTH refuse a trial
    that reaches back past it -- instead of drawing that trial with whichever
    of its spikes happen to remain, which under-counts the oldest trials and
    looks like a unit that has since become responsive.
    """

    def __init__(self, capacity: int = 50_000) -> None:
        self._buf = array("q", bytes(8 * capacity))
        self._capacity = capacity
        self._head = 0
        self._n = 0
        self.complete_since = 0

    def add(self, sample: int) -> None:
        if self._n == self._capacity:
            evicted = self._buf[self._head]
            self._head = (self._head + 1) % self._capacity
            if evicted + 1 > self.complete_since:
                self.complete_since = evicted + 1
        else:
            self._n += 1
        self._buf[(self._head + self._n - 1) % self._capacity] = sample

    def reopened(self, sample: int) -> None:
        """The stream came back at `sample`; whatever fired while it was down
        was never delivered, so nothing before this is complete."""
        if sample > self.complete_since:
            self.complete_since = sample

    def __len__(self) -> int:
        return self._n

    def snapshot(self) -> array:
        """Oldest first. An `array`, not a list: `bisect` and slicing work on
        it, and it is one memcpy rather than fifty thousand boxed ints."""
        end = self._head + self._n
        if end <= self._capacity:
            return self._buf[self._head : end]
        return self._buf[self._head :] + self._buf[: end - self._capacity]

    def count_since(self, sample: int) -> int:
        buf, cap = self._buf, self._capacity
        n = 0
        last = self._head + self._n - 1
        while n < self._n and buf[(last - n) % cap] >= sample:
            n += 1
        return n


def _bin_count(span_ms: float, bin_ms: float) -> int:
    """Bins covering [0, span): the last one may be PARTIAL. Rounding instead
    would leave 40-50 ms of a 50 ms span at 20 ms bins uncounted -- shown as
    "beyond the span" while the axis says 50."""
    return max(1, int(ceil(span_ms / bin_ms - 1e-9)))


def isi_histogram(spikes: Sequence[int], sample_rate: float, span_ms: float, bin_ms: float) -> dict:
    """Inter-spike intervals, binned over [0, span). Intervals at or past the
    span are counted in `beyond`, not dropped silently -- a histogram that
    looks complete while discarding most of its intervals is how a slow unit
    gets read as a quiet one."""
    bins = _bin_count(span_ms, bin_ms)
    counts = [0] * bins
    beyond = 0
    per_ms = sample_rate / 1000.0
    total_ms = 0.0
    for earlier, later in zip(spikes, spikes[1:]):
        interval_ms = (later - earlier) / per_ms
        if interval_ms < 0:
            continue
        total_ms += interval_ms
        index = int(interval_ms // bin_ms)
        if index < bins:
            counts[index] += 1
        else:
            beyond += 1
    n = max(0, len(spikes) - 1)
    return {
        "spanMs": span_ms,
        "binMs": bin_ms,
        "counts": counts,
        "beyond": beyond,
        "intervals": n,
        "meanIsiMs": (total_ms / n) if n else None,
    }


def psth(
    spikes: Sequence[int],
    triggers: Sequence[int],
    sample_rate: float,
    pre_ms: float,
    post_ms: float,
    bin_ms: float,
    max_trials: int,
    newest_sample: int,
    complete_since: int = 0,
) -> dict:
    """Spikes around each trigger: a raster per trial and the pooled histogram.

    Only COMPLETE trials are counted -- ones whose post-window has fully
    elapsed by `newest_sample`, AND whose pre-window begins no earlier than
    `complete_since`, the sample from which every spike is still held. A trial
    still filling would contribute its early bins and not its late ones, so
    the histogram's right side would sag in proportion to how recently the
    last trigger fired; a trial older than the spike ring would contribute
    whichever of its spikes survived, which reads as a unit that fired less
    back then.
    """
    per_ms = sample_rate / 1000.0
    pre, post = pre_ms * per_ms, post_ms * per_ms
    complete = [
        t for t in triggers if t + post <= newest_sample and t - pre >= complete_since
    ][-max_trials:]
    span_ms = pre_ms + post_ms
    bins = _bin_count(span_ms, bin_ms)
    counts = [0] * bins
    rasters: list[list[float]] = []
    for trigger in complete:
        lo = bisect_left(spikes, trigger - pre)
        hi = bisect_right(spikes, trigger + post)
        row: list[float] = []
        for spike in spikes[lo:hi]:
            rel_ms = (spike - trigger) / per_ms
            row.append(round(rel_ms, 2))
            index = int((rel_ms + pre_ms) // bin_ms)
            if 0 <= index < bins:
                counts[index] += 1
        rasters.append(row)
    trials = len(complete)
    # A partial last bin is normalised by ITS width, or its rate reads low.
    widths = [bin_ms] * bins
    widths[-1] = span_ms - bin_ms * (bins - 1)
    rate = [round(c * 1000.0 / w / trials, 3) if trials else 0.0 for c, w in zip(counts, widths)]
    return {
        "preMs": pre_ms,
        "postMs": post_ms,
        "binMs": bin_ms,
        "trials": trials,
        "counts": counts,
        "rateHz": rate,
        "rasters": rasters,
    }


# --------------------------------------------------------------------------- #
# Waveform snippets (SpikeScope)
# --------------------------------------------------------------------------- #


class WaveformRing:
    """The last couple of seconds of ONE channel's samples, addressable by
    recording sample number, so a spike's waveform can be cut out after the
    fact. Contiguity is assumed and CHECKED: a gap in the timestamps empties
    the ring, because a snippet cut across a gap is two unrelated pieces of
    signal drawn as one spike."""

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        # A list trimmed in slabs, not a deque: `cut` indexes into the middle,
        # which a deque does in O(n) per sample.
        self._samples: list[int] = []
        self._next: int | None = None  # timestamp the next sample must carry

    def extend(self, first_timestamp: int, raw: tuple[int, ...]) -> None:
        if self._next is not None and first_timestamp != self._next:
            self._samples.clear()
        self._samples.extend(raw)
        if len(self._samples) > 2 * self._capacity:
            del self._samples[: len(self._samples) - self._capacity]
        self._next = first_timestamp + len(raw)

    @property
    def newest(self) -> int | None:
        return None if self._next is None else self._next - 1

    def cut(self, center: int, before: int, after: int) -> list[int] | None:
        """Raw samples over [center-before, center+after], or None if any of
        it is not held (not arrived yet, or already aged out)."""
        if self._next is None:
            return None
        start_ts = self._next - len(self._samples)
        lo, hi = center - before - start_ts, center + after - start_ts
        if lo < 0 or hi >= len(self._samples):
            return None
        return self._samples[lo : hi + 1]

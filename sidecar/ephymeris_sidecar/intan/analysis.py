"""Pure analysis behind the sync check, the live firing map and the tether
alarm. No I/O, no clocks.

Everything here is in the recording controller's own unit -- SAMPLES since
acquisition began -- and converts to time only at the edge, with the sample
rate RHX reports. The Arduino's milliseconds appear in exactly one place, the
`EdgeMatcher`, because reconciling the two clocks is that class's whole job.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from functools import reduce
from math import ceil
from statistics import median
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
    pulses once per strobe; or one tick, from a board that announced itself
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

    @property
    def anchored(self) -> bool:
        """The first pair has been found."""
        return self._anchor is not None

    @property
    def pending_edges(self) -> int:
        """Edges held, unpaired. An offline feed keeps this small, as a live
        stream does, so a whole session's edges never trip `MAX_PENDING`."""
        return len(self._edges)

    def flush(self) -> list[MatchedEvent]:
        """The stream is over: every strobing time still waiting never got its
        pulse. Offline only; live, a stream is never over."""
        out: list[MatchedEvent] = []
        while self._strobes:
            self._release(out, None)
        return out

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


# --------------------------------------------------------------------------- #
# Tether watch
# --------------------------------------------------------------------------- #

#: Each box is judged one window of RHX samples at a time.
TETHER_WINDOW_S = 1.0
#: Spikes trail the waveform socket (two sockets, not in lockstep): a window is
#: closed only once the waveform is this far past its end.
TETHER_LAG_S = 0.25
#: A box's own crossing rate over its first this-many seconds is its baseline.
TETHER_BASELINE_S = 120.0
#: A condition must hold this long to raise an alarm, and its absence this long
#: to clear one: a twitching connector must not flicker the warning.
TETHER_SUSTAIN_S = 20.0
#: SILENT: the box's total rate under this share of its baseline.
TETHER_SILENT_FRACTION = 0.1
#: NOISY: this many times the baseline, on at least this share of its sites...
TETHER_NOISY_FACTOR = 5.0
TETHER_NOISY_SITES = 0.8
#: ...or this share of its crossings landing together on half its sites or more
#: (within `TETHER_COINCIDENT_S`): neurons do not fire in lockstep across a probe.
TETHER_COINCIDENT_FRACTION = 0.5
TETHER_COINCIDENT_S = 0.0005
#: A baseline quieter than this (whole box) cannot show silence: too few
#: crossings to tell quiet from gone.
TETHER_MIN_BASELINE_HZ = 2.0
#: The baseline follows slow drift while the box is healthy.
TETHER_BASELINE_TAU_S = 600.0


@dataclass(frozen=True)
class TetherChange:
    box: int
    state: str
    previous: str
    #: The first sample of the evidence: where the fault began, not when it was believed.
    at_sample: int


@dataclass
class _Watch:
    channels: tuple[str, ...]
    first_window: int
    state: str = "learning"
    baseline_hz: float | None = None
    learned: list[float] = field(default_factory=list)
    streak_kind: str | None = None
    streak: int = 0
    streak_from: int = 0
    #: window -> channel -> crossings, and window -> coincidence bucket -> channels
    counts: dict[int, dict[str, int]] = field(default_factory=dict)
    buckets: dict[int, dict[int, set[str]]] = field(default_factory=dict)

    @property
    def watches_silence(self) -> bool:
        return self.baseline_hz is not None and self.baseline_hz >= TETHER_MIN_BASELINE_HZ


class TetherBoard:
    """Every recording box's tether, judged on RHX's sample clock
    (`RECORDING.md#tether-alarm`).

    A fault hits a whole box at once: every site silent (tether cut,
    headstage unplugged) or every site noisy (ground lost, connector half
    seated, chewing). One quiet site is ordinary and never an alarm. Each box
    is judged against ITS OWN baseline, learned from its first
    `TETHER_BASELINE_S`, because implants differ tenfold in rate.

    Windows are cut from RHX's samples, never from wall time, and
    `delivered` is told which samples the waveform socket actually brought:
    a window a gap touches is skipped. So a stream that stalls is never a
    silent tether -- and when EVERY judged box goes silent in the same window
    (`all_silent`), the problem is upstream of the tethers, and no box alarms.
    """

    def __init__(self, rate: float) -> None:
        self._w = max(1, int(round(rate * TETHER_WINDOW_S)))
        self._lag = int(rate * TETHER_LAG_S)
        self._bucket = max(1, int(rate * TETHER_COINCIDENT_S))
        self._baseline_windows = ceil(TETHER_BASELINE_S / TETHER_WINDOW_S)
        self._sustain = ceil(TETHER_SUSTAIN_S / TETHER_WINDOW_S)
        self._alpha = TETHER_WINDOW_S / TETHER_BASELINE_TAU_S
        self._watches: dict[int, _Watch] = {}
        self._box_of: dict[str, int] = {}
        self._next: int | None = None
        self._last: int | None = None
        self._gaps: list[tuple[int, int]] = []
        #: The last closed window found every judged box silent at once.
        self.all_silent = False

    # --- boxes -------------------------------------------------------------

    def watch(self, box: int, channels: list[str], from_sample: int) -> None:
        """From the first whole window at or after `from_sample` (the box's START)."""
        self.unwatch(box)
        first = -(-max(0, from_sample) // self._w)
        self._watches[box] = _Watch(tuple(c.upper() for c in channels), first)
        for channel in channels:
            self._box_of[channel.upper()] = box

    def unwatch(self, box: int) -> None:
        watch = self._watches.pop(box, None)
        if watch is not None:
            for channel in watch.channels:
                if self._box_of.get(channel) == box:
                    del self._box_of[channel]

    def state(self, box: int) -> str | None:
        watch = self._watches.get(box)
        return watch.state if watch is not None else None

    def watches_silence(self, box: int) -> bool:
        watch = self._watches.get(box)
        return watch is not None and watch.watches_silence

    def boxes(self) -> list[int]:
        return sorted(self._watches)

    # --- input -------------------------------------------------------------

    def add_spike(self, channel: str, sample: int) -> None:
        box = self._box_of.get(channel)
        if box is None:
            return
        window = sample // self._w
        if self._next is not None and window < self._next:
            return  # its window is already judged
        watch = self._watches[box]
        counts = watch.counts.setdefault(window, {})
        counts[channel] = counts.get(channel, 0) + 1
        watch.buckets.setdefault(window, {}).setdefault(sample // self._bucket, set()).add(channel)

    def delivered(self, first: int, last: int) -> list[TetherChange]:
        """The waveform socket brought samples `first`..`last`. Closes every
        window it can and returns the state changes, oldest first."""
        if self._last is not None and first > self._last + 1:
            self._gaps.append((self._last + 1, first - 1))
        self._last = last if self._last is None else max(self._last, last)
        if self._next is None:
            self._next = -(-first // self._w)  # the first WHOLE window
        changes: list[TetherChange] = []
        while (self._next + 1) * self._w + self._lag <= last:
            changes += self._close(self._next)
            self._next += 1
        horizon = self._next * self._w
        self._gaps = [g for g in self._gaps if g[1] >= horizon]
        return changes

    # --- judging -----------------------------------------------------------

    def _close(self, window: int) -> list[TetherChange]:
        start, end = window * self._w, (window + 1) * self._w - 1
        covered = not any(a <= end and b >= start for a, b in self._gaps)
        verdicts: dict[int, tuple[str | None, float]] = {}
        for box, watch in self._watches.items():
            counts = watch.counts.pop(window, {})
            buckets = watch.buckets.pop(window, {})
            if window < watch.first_window or not covered:
                continue
            rate = sum(counts.values()) / TETHER_WINDOW_S
            verdicts[box] = (self._verdict(watch, counts, buckets), rate)

        judged = [box for box, (v, _) in verdicts.items() if v is not None]
        self.all_silent = len(judged) >= 2 and all(verdicts[b][0] == "silent" for b in judged)
        changes = []
        for box, (verdict, rate) in verdicts.items():
            if self.all_silent:
                verdict = None  # upstream of every tether: not any box's alarm
            change = self._step(box, self._watches[box], verdict, rate, start)
            if change is not None:
                changes.append(change)
        return changes

    def _verdict(self, watch: _Watch, counts: dict[str, int], buckets: dict[int, set[str]]) -> str | None:
        if watch.baseline_hz is None:
            return None  # still learning
        n = len(watch.channels)
        total = sum(counts.values())
        rate = total / TETHER_WINDOW_S
        crossing = sum(1 for c in counts.values() if c > 0)
        together = max(3, ceil(n / 2))
        coincident = sum(len(chans) for chans in buckets.values() if len(chans) >= together)
        if (rate > TETHER_NOISY_FACTOR * watch.baseline_hz and crossing >= TETHER_NOISY_SITES * n) or (
            total >= n and coincident >= TETHER_COINCIDENT_FRACTION * total
        ):
            return "noisy"
        if watch.watches_silence and rate < TETHER_SILENT_FRACTION * watch.baseline_hz:
            return "silent"
        return "ok"

    def _step(self, box: int, watch: _Watch, verdict: str | None, rate: float, start: int) -> TetherChange | None:
        if watch.state == "learning":
            if self.all_silent:
                return None
            watch.learned.append(rate)
            if len(watch.learned) < self._baseline_windows:
                return None
            # The median, so a fault during learning cannot set the bar.
            watch.baseline_hz = median(watch.learned)
            watch.learned = []
            watch.state = "ok"
            return TetherChange(box, "ok", "learning", start)
        if verdict is None:
            return None  # a gap, or upstream: no evidence either way
        if verdict == watch.state:
            watch.streak_kind, watch.streak = None, 0
            if verdict == "ok" and watch.baseline_hz is not None:
                watch.baseline_hz += self._alpha * (rate - watch.baseline_hz)
            return None
        if verdict != watch.streak_kind:
            watch.streak_kind, watch.streak, watch.streak_from = verdict, 0, start
        watch.streak += 1
        if watch.streak < self._sustain:
            return None
        previous, watch.state = watch.state, verdict
        watch.streak_kind, watch.streak = None, 0
        return TetherChange(box, verdict, previous, watch.streak_from)

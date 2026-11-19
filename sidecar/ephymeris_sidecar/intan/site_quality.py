"""How much signal each electrode site carried — `RECORDING.md#unit-like-sites`.

Not spike sorting. For every site of one animal, from the snapshots RHX saved
around each threshold crossing:

    noise      a robust standard deviation of the samples each snapshot keeps
               *before* its spike, the only stretch of signal the file holds
               that is not a spike
    amplitude  each spike's extremum near the crossing, in those noise SDs
    artifacts  spikes RHX flagged, spikes landing on half the animal's sites
               at once, and spikes past the amplitude cap: set aside, counted

What is kept per site is a count of its remaining spikes by amplitude over
noise (`SNR_EDGES`). Raw measurements only: what makes a site *unit-like* is
judged in the webview, so a new bar re-judges history with nothing to
re-measure.

**Memory is bounded by the animal's own spikes**, as the export's is
(`sort_export`): the noise is a histogram of ADC levels per site, filled chunk
by chunk, never the lead-in samples themselves; each spike adds 9 bytes.

numpy is imported by the caller and handed in (`DATA.md#the-mat-mirror`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

#: Lower edges of the amplitude-over-noise bins, in noise SDs; the last bin is
#: open-ended and a spike under the first edge is in none. Fixed: a stored
#: row's counts are read against the edges stored beside it.
SNR_EDGES: tuple[float, ...] = (4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 16.0, 24.0)

#: Samples just before the crossing that are left out of the noise: the
#: spike's own rise.
LEAD_GAP = 12
#: A snapshot that keeps fewer lead-in samples than this, after the gap, is
#: not measured from: the run gets no waveform measurements at all.
MIN_LEAD_SAMPLES = 12

#: A spike's amplitude is its extremum from this many samples before the
#: crossing to this many after it (0.13 ms before to 0.3 ms after at 30 kS/s).
AMPLITUDE_BEFORE = 4
AMPLITUDE_AFTER = 10

#: RHX's own artifact mark on a spike.
ARTIFACT_ID = 128
#: No neuron on a microwire is this large: a spike past it is movement or a
#: connector.
ARTIFACT_UV = 1000.0
#: Neurons do not fire in lockstep across a probe; chewing and a tugged tether
#: do. A spike with spikes on at least `COINCIDENT_FRACTION` of the animal's
#: fired sites (and never fewer than `COINCIDENT_MIN_SITES`) within
#: `COINCIDENT_S` either side is set aside.
COINCIDENT_S = 0.0005
COINCIDENT_FRACTION = 0.5
COINCIDENT_MIN_SITES = 4

#: ADC counts to microvolts, and the count that reads 0 µV (as `sort_export`).
UV_PER_COUNT = 0.195
ADC_ZERO = 32768
ADC_LEVELS = 1 << 16
#: MAD to standard deviation, for a normal distribution.
MAD_TO_SD = 1.4826


@dataclass(frozen=True)
class SiteQuality:
    """One site's measurements, as the wire's `SiteSignal` carries them."""

    channel: str
    spikes: int
    artifacts: int
    #: None for a site with no spike to measure from, or a lead-in that never varied.
    noise_uv: float | None
    #: One count per `SNR_EDGES` bin; None when the noise could not be measured.
    snr_counts: tuple[int, ...] | None

    def to_json(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "spikes": self.spikes,
            "artifacts": self.artifacts,
            "noiseUv": self.noise_uv,
            "snrCounts": None if self.snr_counts is None else list(self.snr_counts),
        }


@dataclass(frozen=True)
class RunQuality:
    """One animal's sites over one recording."""

    #: The span of the recording measured: its first spike to its last, any channel.
    recorded_seconds: float
    #: Every channel asked for that the recording holds, in RHX's order, silent ones included.
    sites: tuple[SiteQuality, ...]
    edges: tuple[float, ...] = SNR_EDGES


def lead_samples(samples_before: int) -> int:
    """How many of a snapshot's first samples the noise is measured from; 0
    when it keeps too few before a detection."""
    usable = samples_before - LEAD_GAP
    return usable if usable >= MIN_LEAD_SAMPLES else 0


def robust_sd(np: Any, levels: Any) -> float:
    """A histogram of ADC levels' robust standard deviation, in µV: 1.4826 ×
    the median distance from the median. About the median rather than zero,
    since a lead-in riding a slow artifact is offset; on a clean site the two
    agree."""
    total = int(levels.sum())
    if total == 0:
        return 0.0
    median = int(np.searchsorted(np.cumsum(levels), (total + 1) // 2))
    distance = np.abs(np.arange(levels.shape[0]) - median)
    by_distance = np.bincount(distance, weights=levels, minlength=levels.shape[0])
    mad = int(np.searchsorted(np.cumsum(by_distance), total / 2.0))
    return MAD_TO_SD * mad * UV_PER_COUNT


def coincident(np: Any, stamps: list[Any], sample_rate: float) -> list[Any]:
    """For each site's timestamps, which spikes land with spikes on enough of
    the animal's fired sites to be an artifact. Counts spikes, not distinct
    sites: a site cannot cross twice inside one snapshot."""
    fired = [s for s in stamps if s.shape[0] > 0]
    need = max(COINCIDENT_MIN_SITES, math.ceil(COINCIDENT_FRACTION * len(fired)))
    if len(fired) < need:
        return [np.zeros(s.shape[0], dtype=bool) for s in stamps]
    everything = np.sort(np.concatenate(fired).astype(np.int64))
    reach = int(round(COINCIDENT_S * sample_rate))
    out = []
    for site in stamps:
        at = site.astype(np.int64)
        near = np.searchsorted(everything, at + reach, "right") - np.searchsorted(everything, at - reach, "left")
        out.append(near >= need)
    return out


def snr_counts(np: Any, amplitude_uv: Any, noise_uv: float) -> tuple[int, ...]:
    """Spikes by amplitude over noise, one count per `SNR_EDGES` bin."""
    edges = np.asarray(SNR_EDGES, dtype=np.float64)
    bins = np.searchsorted(edges, amplitude_uv.astype(np.float64) / noise_uv, "right")
    return tuple(int(n) for n in np.bincount(bins, minlength=len(SNR_EDGES) + 1)[1:])


def measure_site(
    np: Any, channel: str, amplitude_uv: Any, artifact: Any, noise_uv: float
) -> SiteQuality:
    """One site, from each spike's amplitude, whether it is an artifact, and
    the site's noise."""
    spikes = int(amplitude_uv.shape[0])
    measured = noise_uv > 0.0 and math.isfinite(noise_uv)
    return SiteQuality(
        channel=channel,
        spikes=spikes,
        artifacts=int(artifact.sum()),
        noise_uv=round(noise_uv, 2) if measured else None,
        snr_counts=snr_counts(np, amplitude_uv[~artifact], noise_uv) if measured else None,
    )


class Gatherer:
    """Collects, chunk by chunk as the export reads `spike.dat`, what the
    measurement needs of each of one animal's channels."""

    def __init__(self, np: Any, keys: list[bytes], counts: dict[bytes, int], samples_before: int) -> None:
        self._np = np
        self._keys = keys
        self._lead = lead_samples(samples_before)
        self._window = slice(samples_before - AMPLITUDE_BEFORE, samples_before + AMPLITUDE_AFTER)
        fired = [key for key in keys if counts.get(key, 0) > 0]
        self._levels = {key: np.zeros(ADC_LEVELS, dtype=np.int64) for key in fired}
        self._stamps = {key: np.empty(counts[key], dtype=np.int32) for key in fired}
        self._amplitude = {key: np.empty(counts[key], dtype=np.float32) for key in fired}
        self._flagged = {key: np.zeros(counts[key], dtype=bool) for key in fired}

    @staticmethod
    def measurable(samples_before: int, samples_after: int) -> bool:
        """Whether a snapshot of this shape can be measured from at all."""
        return lead_samples(samples_before) > 0 and samples_after >= AMPLITUDE_AFTER

    def add(self, key: bytes, rows: Any, at: int) -> None:
        """One chunk's records of one channel, the channel's `at`-th onwards."""
        np = self._np
        snapshot = rows["snapshot"]
        n = rows.shape[0]
        self._levels[key] += np.bincount(
            snapshot[:, : self._lead].ravel().astype(np.intp), minlength=ADC_LEVELS
        )
        swing = np.abs(snapshot[:, self._window].astype(np.int32) - ADC_ZERO).max(axis=1)
        self._amplitude[key][at:at + n] = UV_PER_COUNT * swing
        self._stamps[key][at:at + n] = rows["timestamp"]
        self._flagged[key][at:at + n] = rows["spike_id"] == ARTIFACT_ID

    def measure(self, sample_rate: float, first_stamp: int, last_stamp: int) -> RunQuality | None:
        """Every channel's measurements; None for a recording too short to
        have a rate."""
        np = self._np
        recorded = (last_stamp - first_stamp) / sample_rate
        if not recorded > 0.0:
            return None
        fired = list(self._stamps)
        together = dict(zip(fired, coincident(np, [self._stamps[key] for key in fired], sample_rate)))
        sites = []
        for key in self._keys:
            channel = key.decode("latin-1")
            if key not in self._stamps:
                sites.append(SiteQuality(channel, 0, 0, None, (0,) * len(SNR_EDGES)))
                continue
            amplitude = self._amplitude[key]
            artifact = self._flagged[key] | together[key] | (amplitude > ARTIFACT_UV)
            sites.append(measure_site(np, channel, amplitude, artifact, robust_sd(np, self._levels[key])))
        return RunQuality(round(recorded, 3), tuple(sites))

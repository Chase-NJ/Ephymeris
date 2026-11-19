"""RHX's saved recording, read back (`RECORDING.md#event-psth`).

Only the "One File Per Signal Type" format, Ephymeris' default: the
Traditional `.rhd` saves no spike file at all. RHX's own writer,
`FilePerSignalTypeSaveManager`, is the reference for every layout here:

    time.dat       int32 per sample: the sample's timestamp. No header.
    digitalin.dat  uint16 per sample: all sixteen digital inputs, bit n = input n+1.
    spike.dat      a header, then one record per detected crossing:
                     uint32 magic 0x18f8474b, uint16 version,
                     the folder name, the native names (comma-separated), the
                     custom names, each a NUL-terminated string;
                     float32 sample rate; uint32 samples before and after a
                     detection kept as a snapshot (0 when none are saved);
                   record: 5 chars native name, int32 timestamp, uint8 id,
                     then (before + after) uint16 snapshot samples.

Everything is little-endian. Timestamps in spike.dat are on time.dat's clock,
so a spike and a digital edge compare directly.

**Speed without dependencies.** A one-hour recording's digitalin.dat is about
108 million words. Python never touches them one by one: each chunk's byte
holding the box's bit is sliced out (`bytes[k::2]`), mapped to 0/1 with
`bytes.translate`, and the rising edges found with `bytes.find` -- all in C.
Python loops only over the edges, which number in the thousands.
"""

from __future__ import annotations

import struct
from array import array
from dataclasses import dataclass
from pathlib import Path

SPIKE_FILE_MAGIC = 0x18F8474B
#: Samples read per chunk: 4 MB of time.dat, 2 MB of digitalin.dat.
CHUNK_SAMPLES = 1 << 20
_NAME_BYTES = 5
_RECORD = struct.Struct("<5siB")
#: After the header's three strings: the sample rate as a float32 (not a
#: double), then the snapshot's samples before and after a detection. Checked
#: against a real RHX recording and Intan's own `read_Intan_spike_file.m`.
_HEADER_TAIL = struct.Struct("<fII")
#: Bounds no recording crosses: RHX samples at 30 kS/s at most, and keeps at
#: most a few milliseconds around a detection.
MAX_SAMPLE_RATE = 100_000.0
MAX_SNAPSHOT_SAMPLES = 4096


class RhxFileError(ValueError):
    """The folder is not a readable RHX per-signal-type recording."""


@dataclass(frozen=True)
class SpikeFileHeader:
    sample_rate: float
    native_names: tuple[str, ...]
    snapshot_samples: int
    #: Where the first record starts.
    data_offset: int
    #: How many of a snapshot's samples come before the detection; the rest
    #: come after it.
    samples_before: int = 0

    @property
    def record_bytes(self) -> int:
        return _RECORD.size + 2 * self.snapshot_samples


def _cstring(data: bytes, at: int) -> tuple[str, int]:
    end = data.find(b"\x00", at)
    if end < 0:
        raise RhxFileError("spike.dat's header is cut short")
    return data[at:end].decode("latin-1"), end + 1


def parse_spike_header(data: bytes) -> SpikeFileHeader:
    """The header from the file's first bytes (a few kB is plenty)."""
    if len(data) < 6 or struct.unpack_from("<I", data)[0] != SPIKE_FILE_MAGIC:
        raise RhxFileError("not an RHX spike.dat: wrong magic number")
    at = 6  # magic + version
    _folder, at = _cstring(data, at)
    natives, at = _cstring(data, at)
    _customs, at = _cstring(data, at)
    if len(data) < at + _HEADER_TAIL.size:
        raise RhxFileError("spike.dat's header is cut short")
    rate, before, after = _HEADER_TAIL.unpack_from(data, at)
    # A layout read wrongly gives numbers, not an error: refuse ones no
    # recording has, rather than read every record from the wrong byte.
    if not 1.0 <= rate <= MAX_SAMPLE_RATE or before + after > MAX_SNAPSHOT_SAMPLES:
        raise RhxFileError("spike.dat's header does not read as a sample rate and a snapshot length")
    names = tuple(n.strip().upper() for n in natives.split(",") if n.strip())
    return SpikeFileHeader(rate, names, before + after, at + _HEADER_TAIL.size, before)


def read_spikes(path: Path, channels: set[str] | None = None) -> tuple[SpikeFileHeader, dict[str, array]]:
    """Every crossing's timestamp, by native channel, in file order (time
    order). `channels` keeps only those. A partial last record -- a file RHX
    was still writing -- is ignored."""
    with path.open("rb") as handle:
        head = handle.read(1 << 16)
        header = parse_spike_header(head)
        handle.seek(header.data_offset)
        size = header.record_bytes
        out: dict[str, array] = {}
        per_chunk = max(1, (4 << 20) // size)
        while chunk := handle.read(per_chunk * size):
            whole = len(chunk) - len(chunk) % size
            for offset in range(0, whole, size):
                name, stamp, _unit = _RECORD.unpack_from(chunk, offset)
                channel = name.decode("latin-1").strip().upper()
                if channels is not None and channel not in channels:
                    continue
                out.setdefault(channel, array("q")).append(stamp)
            if whole < len(chunk):
                break
    return header, out


def rising_edges(folder: Path, digital_in: int) -> list[int]:
    """Timestamps of every rising edge of one digital input (1-based, as
    Ephymeris binds them). A line already high when the file starts is not
    an edge, as live (`EdgeDetector`)."""
    bit = digital_in - 1
    if not 0 <= bit < 16:
        raise RhxFileError(f"no digital input {digital_in}")
    which_byte, mask = divmod(bit, 8)
    table = bytes(1 if b & (1 << mask) else 0 for b in range(256))
    times_path, words_path = folder / "time.dat", folder / "digitalin.dat"
    if not words_path.is_file():
        raise RhxFileError("no digitalin.dat: the digital inputs were not saved")
    edges: list[int] = []
    previous = b"\x01"  # as if high before the file: a high start is no edge
    with times_path.open("rb") as times, words_path.open("rb") as words:
        while True:
            raw = words.read(2 * CHUNK_SAMPLES)
            if len(raw) < 2:
                break
            raw = raw[: len(raw) - len(raw) % 2]
            stamps = array("i")
            stamps.frombytes(times.read(2 * len(raw)))
            levels = previous + raw[which_byte::2].translate(table)
            at = levels.find(b"\x00\x01")
            while at >= 0:
                index = at  # the sample whose level is 1, less the carried byte
                if index < len(stamps):
                    edges.append(stamps[index])
                at = levels.find(b"\x00\x01", at + 1)
            previous = levels[-1:]
    return edges

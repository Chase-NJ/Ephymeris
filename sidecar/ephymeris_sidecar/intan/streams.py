"""Pure parsers for RHX's two data sockets. No I/O; bytes in, records out.

WAVEFORM SOCKET. RHX writes *data blocks* of 128 frames. A block is a 4-byte
magic number, then 128 frames; a frame is an int32 timestamp (in samples since
acquisition began) followed by one uint16 per enabled output, in RHX's own
order: every enabled band of every amplifier channel (wide, low, high per
channel), then auxiliary inputs, then board ADCs, and last -- once, however
many digital inputs are enabled -- ONE uint16 word holding all sixteen. So the
frame's shape is a function of what has been enabled over the command socket,
and nothing in the stream says what that is: `FrameLayout` is the reader's copy
of a fact that lives in RHX, and a wrong copy parses garbage without complaint.

That is what the magic number is for, and it is checked at BOTH ends of a
block: a block is only believed when the next block's magic sits exactly one
block-length later. Intan's example reads with a single blocking `recv` and
checks `len % blockSize`; a real stream splits blocks across reads, so the
parser accumulates, and the two-ended check is also what makes a layout change
mid-run safe -- bytes already in flight under the old layout stop confirming,
and the parser moves to the pending layout the moment *it* confirms.

EXCEPT when the two layouts are the same size. A SpikeScope switching from one
channel to another swaps a column for a column: every block confirms under
either layout, the old one is tried first, and it goes on "confirming" forever
while the new channel's samples are filed under the old channel's name. So a
same-size change is switched on a SAMPLE MARKER instead: the caller reads
`currenttimestamp` after RHX has acknowledged the change, and a block whose
first timestamp is at or past it was written after the change. Blocks before
the marker are ambiguous -- they may be either shape -- and are DROPPED rather
than guessed, because a wrong guess draws one channel's waveform as another's.

SPIKE SOCKET. Fixed 14-byte chunks: magic, a 5-character native channel name
("A-010"), a uint32 timestamp, a uint8 spike id.

Everything is little-endian. Amplifier samples are offset binary at
0.195 µV per bit.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

WAVEFORM_MAGIC = 0x2EF07A08
SPIKE_MAGIC = 0x3AE2710F
FRAMES_PER_BLOCK = 128
SPIKE_CHUNK_BYTES = 14
MICROVOLTS_PER_BIT = 0.195
SAMPLE_OFFSET = 32768

_WAVEFORM_MAGIC_BYTES = struct.pack("<I", WAVEFORM_MAGIC)
_SPIKE_MAGIC_BYTES = struct.pack("<I", SPIKE_MAGIC)
_SPIKE = struct.Struct("<I5sIB")

#: Bands in the order RHX writes them within one amplifier channel.
BAND_ORDER = ("wide", "low", "high")


def native_sort_key(name: str) -> tuple[str, int]:
    """RHX's channel order: port letter, then channel number."""
    port, _, number = name.upper().partition("-")
    return (port, int(number) if number.isdigit() else 0)


@dataclass(frozen=True)
class FrameLayout:
    """What one frame holds, in stream order.

    `amplifier` is (native name, band) pairs and is kept SORTED here rather
    than trusted from the caller: RHX orders by channel and then by band, not
    by the order outputs were enabled in, so an unsorted copy would swap two
    channels' samples and still pass every magic check.
    """

    amplifier: tuple[tuple[str, str], ...] = ()
    digital_in: bool = False
    _struct: struct.Struct = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(
                ((name.upper(), band) for name, band in self.amplifier),
                key=lambda pair: (native_sort_key(pair[0]), BAND_ORDER.index(pair[1])),
            )
        )
        object.__setattr__(self, "amplifier", ordered)
        frame = "i" + "H" * self.columns
        object.__setattr__(self, "_struct", struct.Struct("<" + frame * FRAMES_PER_BLOCK))

    @property
    def columns(self) -> int:
        return len(self.amplifier) + (1 if self.digital_in else 0)

    @property
    def block_bytes(self) -> int:
        return 4 + self._struct.size

    @property
    def empty(self) -> bool:
        """RHX writes nothing at all when no output is enabled."""
        return self.columns == 0


@dataclass
class WaveformBlock:
    """128 frames, column-wise. Samples are RAW uint16; see `to_microvolts`."""

    timestamps: tuple[int, ...]
    amplifier: dict[tuple[str, str], tuple[int, ...]]
    digital_in: tuple[int, ...] | None


def to_microvolts(raw: int) -> float:
    return MICROVOLTS_PER_BIT * (raw - SAMPLE_OFFSET)


class WaveformParser:
    """Accumulating block parser with two-ended confirmation and resync."""

    def __init__(self, layout: FrameLayout) -> None:
        self._layout = layout
        self._pending: FrameLayout | None = None
        #: Sample marker for a same-size pending layout; None = switch now.
        self._switch_at: int | None = None
        self._drop_next = False
        self._buffer = bytearray()
        #: Bytes thrown away hunting for a block boundary. A number that climbs
        #: means the layout is wrong, not that the link is noisy -- TCP does not
        #: corrupt -- so it is surfaced rather than logged and forgotten.
        self.discarded = 0
        #: Whole blocks dropped in the ambiguous window of a same-size change.
        self.dropped_blocks = 0

    @property
    def layout(self) -> FrameLayout:
        return self._layout

    def set_layout(self, layout: FrameLayout, *, from_timestamp: int | None = None) -> None:
        """Announce a layout change made over the command socket.

        Not applied at once: blocks written before RHX saw the change are still
        arriving in the old shape. The old layout keeps parsing until it stops
        confirming, and only then does the pending one take over.

        `from_timestamp` is the marker a SAME-SIZE change is switched on (see
        the module doc): RHX's `currenttimestamp`, read after the change was
        acknowledged. Without one a same-size change is applied at once --
        right for a stream that is not running yet, a guess for one that is.
        """
        if layout == self._layout:
            self._pending, self._switch_at = None, None
            return
        self._pending, self._switch_at = layout, from_timestamp

    def feed(self, data: bytes) -> list[WaveformBlock]:
        self._buffer += data
        out: list[WaveformBlock] = []
        while True:
            layout = self._confirmed_layout()
            if layout is None:
                if not self._resync():
                    return out
                continue
            body = bytes(self._buffer[4 : layout.block_bytes])
            del self._buffer[: layout.block_bytes]
            if self._drop_next:
                self._drop_next = False
                self.dropped_blocks += 1
                continue
            out.append(_unpack(layout, body))

    def _confirmed_layout(self) -> FrameLayout | None:
        """The layout whose NEXT block boundary is where it says, if any."""
        if self._buffer[:4] != _WAVEFORM_MAGIC_BYTES:
            return None
        pending = self._pending
        if pending is not None and pending.block_bytes == self._layout.block_bytes:
            # Framing cannot tell these apart; the marker decides.
            end = pending.block_bytes
            if len(self._buffer) < end + 4 or self._buffer[end : end + 4] != _WAVEFORM_MAGIC_BYTES:
                return None
            marker = self._switch_at
            if marker is None or _first_timestamp(self._buffer) >= marker:
                self._layout, self._pending, self._switch_at = pending, None, None
                return pending
            self._drop_next = True
            return pending  # its size, consumed and dropped by `feed`
        for candidate in (self._layout, self._pending):
            if candidate is None or candidate.empty:
                continue
            end = candidate.block_bytes
            if len(self._buffer) < end + 4:
                continue
            if self._buffer[end : end + 4] == _WAVEFORM_MAGIC_BYTES:
                if candidate is self._pending:
                    self._layout, self._pending, self._switch_at = candidate, None, None
                return candidate
        return None

    def _resync(self) -> bool:
        """Drop bytes up to the next plausible boundary. False = need more data."""
        longest = max(
            (c.block_bytes for c in (self._layout, self._pending) if c is not None and not c.empty),
            default=0,
        )
        if longest == 0:
            self.discarded += len(self._buffer)
            self._buffer.clear()
            return False
        if self._buffer[:4] == _WAVEFORM_MAGIC_BYTES and len(self._buffer) < longest + 4:
            return False  # at a boundary, just not enough to confirm it yet
        nxt = self._buffer.find(_WAVEFORM_MAGIC_BYTES, 1)
        if nxt < 0:
            # Keep a tail that could be the front of a magic number.
            keep = 3
            self.discarded += max(0, len(self._buffer) - keep)
            del self._buffer[: max(0, len(self._buffer) - keep)]
            return False
        self.discarded += nxt
        del self._buffer[:nxt]
        return True


def _first_timestamp(buffer: bytearray) -> int:
    """The first frame's timestamp of the block at the front of `buffer`."""
    return struct.unpack_from("<i", buffer, 4)[0]


def _unpack(layout: FrameLayout, body: bytes) -> WaveformBlock:
    flat = layout._struct.unpack(body)
    stride = 1 + layout.columns
    amplifier = {
        key: flat[1 + index :: stride] for index, key in enumerate(layout.amplifier)
    }
    digital = flat[stride - 1 :: stride] if layout.digital_in else None
    return WaveformBlock(timestamps=flat[0::stride], amplifier=amplifier, digital_in=digital)


@dataclass(frozen=True)
class Spike:
    channel: str
    timestamp: int
    unit: int


class SpikeParser:
    """Accumulating parser for the spike socket's 14-byte chunks."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.discarded = 0

    def feed(self, data: bytes) -> list[Spike]:
        self._buffer += data
        out: list[Spike] = []
        while len(self._buffer) >= SPIKE_CHUNK_BYTES:
            if self._buffer[:4] != _SPIKE_MAGIC_BYTES:
                nxt = self._buffer.find(_SPIKE_MAGIC_BYTES, 1)
                drop = nxt if nxt >= 0 else max(0, len(self._buffer) - 3)
                self.discarded += drop
                del self._buffer[:drop]
                if nxt < 0:
                    break
                continue
            _, name, timestamp, unit = _SPIKE.unpack_from(self._buffer)
            del self._buffer[:SPIKE_CHUNK_BYTES]
            out.append(Spike(name.decode("ascii", errors="replace").strip().upper(), timestamp, unit))
        return out


def pack_waveform_block(layout: FrameLayout, block: WaveformBlock) -> bytes:
    """The inverse of the parser -- for the fake RHX the tests drive, so the
    tests exercise the real framing rather than a second description of it."""
    flat: list[int] = []
    for i, timestamp in enumerate(block.timestamps):
        flat.append(timestamp)
        flat.extend(block.amplifier[key][i] for key in layout.amplifier)
        if layout.digital_in:
            assert block.digital_in is not None
            flat.append(block.digital_in[i])
    return _WAVEFORM_MAGIC_BYTES + layout._struct.pack(*flat)


def pack_spike(spike: Spike) -> bytes:
    return _SPIKE.pack(SPIKE_MAGIC, spike.channel.encode("ascii")[:5].ljust(5), spike.timestamp, spike.unit)

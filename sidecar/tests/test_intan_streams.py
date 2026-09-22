"""RHX's data sockets. Every test goes through `pack_*`, the parser's inverse,
so what is exercised is the framing itself and not a second description of it."""

from __future__ import annotations

from ephymeris_sidecar.intan.streams import (
    FRAMES_PER_BLOCK,
    FrameLayout,
    Spike,
    SpikeParser,
    WaveformBlock,
    WaveformParser,
    pack_spike,
    pack_waveform_block,
    to_microvolts,
)


def block(layout: FrameLayout, first: int, *, word: int = 0, level: int = 32768) -> WaveformBlock:
    stamps = tuple(range(first, first + FRAMES_PER_BLOCK))
    return WaveformBlock(
        timestamps=stamps,
        amplifier={key: tuple(level + i for i in range(FRAMES_PER_BLOCK)) for key in layout.amplifier},
        digital_in=tuple(word for _ in stamps) if layout.digital_in else None,
    )


def stream(layout: FrameLayout, blocks: int, start: int = 0, **kwargs) -> bytes:
    return b"".join(
        pack_waveform_block(layout, block(layout, start + n * FRAMES_PER_BLOCK, **kwargs))
        for n in range(blocks)
    )


def test_the_block_size_is_intan_s_own_arithmetic():
    """Their worked example: one wideband channel is 4 + 128 * (4 + 2) bytes."""
    assert FrameLayout(amplifier=(("A-010", "wide"),)).block_bytes == 4 + 128 * 6
    assert FrameLayout(digital_in=True).block_bytes == 4 + 128 * 6
    # ONE word however many digital inputs are enabled.
    assert FrameLayout(amplifier=(("A-000", "high"),), digital_in=True).block_bytes == 4 + 128 * 8


def test_blocks_split_across_reads_come_out_whole():
    """Intan's example does one blocking recv and checks len % blockSize. A
    real stream hands over whatever TCP felt like."""
    layout = FrameLayout(amplifier=(("A-003", "high"),), digital_in=True)
    data = stream(layout, 6, word=0b100)
    parser = WaveformParser(layout)
    got = []
    for i in range(0, len(data), 777):  # nothing about 777 divides a block
        got += parser.feed(data[i : i + 777])
    # The last block is held back: nothing after it confirms where it ends.
    assert [b.timestamps[0] for b in got] == [0, 128, 256, 384, 512]
    assert got[0].digital_in[0] == 0b100
    assert got[0].amplifier[("A-003", "high")][5] == 32773
    assert parser.discarded == 0


def test_the_layout_is_sorted_the_way_rhx_writes_not_the_way_it_was_asked_for():
    """RHX orders by channel then band. A caller-ordered copy would swap two
    channels' samples and pass every magic check."""
    layout = FrameLayout(amplifier=(("B-001", "high"), ("A-010", "high"), ("A-010", "wide")))
    assert layout.amplifier == (("A-010", "wide"), ("A-010", "high"), ("B-001", "high"))


def test_garbage_before_a_boundary_is_skipped_and_counted():
    layout = FrameLayout(digital_in=True)
    parser = WaveformParser(layout)
    got = parser.feed(bytes([1, 2, 3]) * 11 + stream(layout, 3))
    assert [b.timestamps[0] for b in got] == [0, 128]
    assert parser.discarded == 33


def test_a_layout_change_mid_stream_loses_nothing_on_either_side():
    """A SpikeScope opening adds a column while blocks in the old shape are
    still in flight. The old layout parses until it stops confirming; only
    then does the pending one take over."""
    old = FrameLayout(digital_in=True)
    new = FrameLayout(amplifier=(("A-007", "high"),), digital_in=True)
    parser = WaveformParser(old)
    data = stream(old, 3) + stream(new, 4, start=3 * FRAMES_PER_BLOCK, level=40000)

    parser.set_layout(new)  # announced BEFORE the old blocks have all arrived
    got = parser.feed(data)

    assert [b.timestamps[0] for b in got] == [0, 128, 256, 384, 512, 640]
    assert [bool(b.amplifier) for b in got] == [False, False, False, True, True, True]
    assert got[3].amplifier[("A-007", "high")][0] == 40000
    assert parser.layout == new and parser.discarded == 0


def test_swapping_one_channel_for_another_switches_on_the_marker_not_the_framing():
    """Same block size before and after, so every block confirms under either
    layout and the old one would go on winning forever -- the new channel's
    samples filed under the old channel's name. The marker decides instead,
    and the blocks it cannot decide are dropped, not guessed."""
    old = FrameLayout(amplifier=(("A-004", "high"),), digital_in=True)
    new = FrameLayout(amplifier=(("A-009", "high"),), digital_in=True)
    assert old.block_bytes == new.block_bytes
    parser = WaveformParser(old)
    assert parser.feed(stream(old, 2)) and parser.layout == old

    # RHX acknowledged the change when its clock read 3 * 128 + 40: block 2 is
    # still the old shape, block 3 straddles the marker, blocks 4-6 are new
    # (the last is held back until the block after it confirms it, as ever).
    parser.set_layout(new, from_timestamp=3 * FRAMES_PER_BLOCK + 40)
    got = parser.feed(
        stream(old, 2, start=2 * FRAMES_PER_BLOCK)
        + stream(new, 3, start=4 * FRAMES_PER_BLOCK, level=40000)
    )
    assert [b.timestamps[0] for b in got] == [512, 640]
    assert all(("A-009", "high") in b.amplifier for b in got)
    assert got[0].amplifier[("A-009", "high")][0] == 40000
    assert parser.layout == new
    # Block 1 was buffered but unconfirmed when the change was announced, so
    # it is ambiguous too: three dropped, nothing misfiled.
    assert parser.dropped_blocks == 3 and parser.discarded == 0


def test_a_same_size_change_with_no_marker_is_applied_at_once():
    old = FrameLayout(amplifier=(("A-004", "high"),), digital_in=True)
    new = FrameLayout(amplifier=(("A-009", "high"),), digital_in=True)
    parser = WaveformParser(old)
    parser.set_layout(new)
    got = parser.feed(stream(new, 3, level=40000))
    assert [tuple(b.amplifier) for b in got] == [(("A-009", "high"),)] * 2
    assert parser.dropped_blocks == 0


def test_sample_scaling_is_offset_binary_at_0_195_microvolts():
    assert to_microvolts(32768) == 0
    assert round(to_microvolts(32768 + 1000), 3) == 195.0
    assert round(to_microvolts(32768 - 1000), 3) == -195.0


def test_spike_chunks_survive_any_read_boundary_and_a_bad_byte():
    spikes = [Spike("A-010", 1000 + n * 30, n % 3) for n in range(9)]
    data = bytes([255]) + b"".join(pack_spike(s) for s in spikes)
    parser = SpikeParser()
    got = []
    for i in range(0, len(data), 5):
        got += parser.feed(data[i : i + 5])
    assert got == spikes
    assert parser.discarded == 1

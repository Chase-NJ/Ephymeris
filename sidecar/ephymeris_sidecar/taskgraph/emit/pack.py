"""The wire format: a compiled table as the bytes a board receives.

THIS IS THE ARTIFACT THE CRC IS DEFINED OVER, so it is also the artifact the whole
upload protocol is about. `docs/spikes/transport.md` names the class of bug this
closes, quoting the firmware's own `readLineInto()`: *"a lost token is not an
error the board can see, it just runs on the wrong value."* Everything below is
arranged so that sentence stops being true — a table that arrives wrong must be
rejected, never run.

THE LAYOUT IS NOT DEFINED HERE. Record widths and field order come from
`taskgraph/codegen/layout.py`, the same table that generates the C++
`static_assert`s. A packer with its own idea of the layout would be a second
source of truth for the one thing both sides must agree on byte for byte, and the
project has already been bitten by exactly that: `TgTimingSet` measured 3 bytes on
AVR and 4 on the host while compiling cleanly on both. What this module adds is
the *order of sections*, the header, and the checksum.

Little-endian throughout. Both ends are little-endian — AVR and every host this
runs on — so declaring it costs nothing and removes a question that would
otherwise be answered by accident.

## The shape

    +--------------------------------+
    |  header, 24 bytes              |  magic, versions, spec hash, counts
    +--------------------------------+
    |  body                          |  sections, in SECTIONS order
    +--------------------------------+
    |  crc32, 4 bytes                |  over everything above it
    +--------------------------------+

**Why the CRC is at the end rather than only in the framing.** The protocol's
`TABLE BEGIN <spec_id> <spec_hash> <n_bytes> <crc32>` line already carries it, and
that line has no checksum of its own — so a corrupted BEGIN would have the board
verifying against the wrong number and accepting a wrong table. With the value
also inside the payload, the board has two independent statements that must agree:
one from the framing, one from the bytes. A truncated transfer loses the trailing
copy; a mangled BEGIN disagrees with it. Either way the table is refused.

A CRC cannot cover itself, so it covers everything before it. That is the same
arrangement PNG and zip use, for the same reason.

**The header is inside the CRC.** The counts are the most dangerous bytes in the
file: a corrupted `n_nodes` does not produce a parse error, it produces a table
that runs and is not the one anybody compiled.
"""

from __future__ import annotations

import struct
import zlib

from ephymeris_sidecar.taskgraph.codegen.layout import BY_NAME, U8, U16, U32, Record
from ephymeris_sidecar.taskgraph.registries import limits
from ephymeris_sidecar.taskgraph.table import StateTable

#: 'TGTB'. First bytes on the wire, so a board that is handed something else --
#: a truncated previous upload, a stray START line -- says so instead of parsing
#: whatever arrived as a node array.
MAGIC = b"TGTB"

#: The version of THIS byte layout, distinct from spec/vocab/template versions.
#: Bumped when a section moves, is added, or changes width. A board refuses a
#: format it does not know rather than guessing at offsets.
WIRE_FORMAT = 1

HEADER_SIZE = 24
CRC_SIZE = 4

_CODE = {U8: "B", U16: "H", U32: "I"}

#: The header, as (name, width) in order. Not a C struct: the firmware parses it
#: byte by byte out of the receive buffer, at generated offsets, so there is no
#: alignment or padding question to get wrong. `magic` is raw bytes and sits
#: outside this table.
HEADER_FIELDS: tuple[tuple[str, int], ...] = (
    ("wire_format", U8),
    ("spec_version", U8),
    ("vocab_version", U8),
    ("template_version", U8),
    ("spec_hash", U32),
    ("n_nodes", U8),
    ("n_edges", U8),
    ("n_timing", U8),
    ("n_actions", U8),
    ("n_trial_types", U8),
    ("n_ports", U8),
    ("n_stimuli", U8),
    ("n_watch", U8),
    ("n_stage_rows", U8),
    ("n_timing_sets", U8),
    ("_pad0", U8),
    ("_pad1", U8),
)

#: Section order on the wire. THE FIRMWARE PARSES IN THIS ORDER, and the order is
#: emitted into the generated header so neither side can drift. Grouped as
#: graph, then task, then the two parallel arrays that describe nodes and
#: channels from the outside.
SECTIONS: tuple[str, ...] = (
    "nodes", "edges", "timing", "actions",
    "trial_types", "ports", "stimuli",
    "stage_rows", "timing_sets",
    "max_dwell", "watch_pin", "watch_port",
)

#: watchPin/watchPort are packed at full extent rather than at n_watch. They are
#: 16 bytes total, and a fixed extent means "what is in the rest" is not a
#: question the receiver has to answer -- unused slots are TG_NO_TARGET and mean
#: nothing.
#:
#: FROM THE SCHEMA, not a literal 8. This number is the width of TgNode.watchMask
#: and therefore a hard ceiling, and it was previously implicit in three places at
#: once: the struct's array bound, this constant, and TG504's help text.
WATCH_SLOTS = limits().TG_MAX_WATCH
NO_TARGET = 0xFF

#: Payload bytes per `TABLE CHUNK` line. 64 bytes is 128 hex characters, so a
#: chunk line fits inside a 192-byte board-side buffer with room for the keyword,
#: the index and the checksum -- comfortably under the 640-byte START line the
#: firmware already handles.
#:
#: Small enough that a retry is cheap (5.6 ms on the wire at 115200) and large
#: enough that a real table is 8-11 lines rather than a hundred. The board does
#: not require this size -- it processes whatever arrives -- but it does bound the
#: line, and TG_RX_LINE_MAX is derived from it.
CHUNK_BYTES = 64
RX_LINE_MAX = 192


def _fmt(rec: Record) -> str:
    """A little-endian struct format for one record, derived from the layout.

    `<` means no implicit padding, so this describes exactly the bytes the record
    occupies. That it agrees with `rec.size` -- which is computed from the
    natural-alignment model the C++ assertions use -- is itself worth checking:
    the two models must coincide for every record, and a record where they do not
    is one that needs an explicit pad byte.
    """
    fmt = "<" + "".join(_CODE[f.width] for f in rec.fields)
    if struct.calcsize(fmt) != rec.size:
        raise AssertionError(
            f"{rec.name}: packed size {struct.calcsize(fmt)} != declared {rec.size}. "
            f"The packed and naturally-aligned layouts disagree, which means the "
            f"record needs an explicit pad byte."
        )
    return fmt


def _header(t: StateTable) -> bytes:
    fmt = "<" + "".join(_CODE[w] for _, w in HEADER_FIELDS)
    values = {
        "wire_format": WIRE_FORMAT,
        "spec_version": t.spec_version,
        "vocab_version": t.vocab_version,
        "template_version": t.template_version,
        #: The first 4 bytes of the spec hash. Not integrity -- the CRC is that --
        #: but provenance: which spec compiled this table, echoed back by the board
        #: so a recorded session names it (docs/protocol-negotiation.md).
        "spec_hash": int(t.spec_hash[:8], 16),
        "n_nodes": len(t.nodes),
        "n_edges": len(t.edges),
        "n_timing": len(t.timing),
        "n_actions": len(t.actions),
        "n_trial_types": len(t.trial_types),
        "n_ports": len(t.ports),
        "n_stimuli": len(t.stimuli),
        "n_watch": len(t.watch_pins),
        "n_stage_rows": len(t.stage_rows),
        "n_timing_sets": len(t.timing_sets),
        "_pad0": 0,
        "_pad1": 0,
    }
    out = MAGIC + struct.pack(fmt, *(values[name] for name, _ in HEADER_FIELDS))
    if len(out) != HEADER_SIZE:
        raise AssertionError(f"header is {len(out)} bytes, declared {HEADER_SIZE}")
    return out


def _section(t: StateTable, name: str) -> bytes:
    """One section's bytes.

    Every case is explicit rather than reflected from field names. The record
    layout is single-sourced; this mapping is not, and should not be -- a silent
    rename that reflection would follow into the wrong slot is exactly the failure
    that has no symptom until a board runs the wrong task.
    """
    if name == "nodes":
        f = _fmt(BY_NAME["TgNode"])
        return b"".join(
            struct.pack(f, n.type, n.dur_idx, n.strobe, n.watch_mask,
                        n.action_idx, n.action_count, n.edge_idx)
            for n in t.nodes
        )
    if name == "edges":
        f = _fmt(BY_NAME["TgEdge"])
        return b"".join(struct.pack(f, e.trigger, e.guard, e.target, e.effect) for e in t.edges)
    if name == "timing":
        return struct.pack(f"<{len(t.timing)}H", *t.timing)
    if name == "actions":
        f = _fmt(BY_NAME["TgAction"])
        return b"".join(struct.pack(f, a.channel, a.op) for a in t.actions)
    if name == "trial_types":
        f = _fmt(BY_NAME["TgTrialType"])
        out = []
        for r in t.trial_types:
            stim = list(r.stimulus) + [NO_TARGET] * (4 - len(r.stimulus))
            out.append(struct.pack(f, *stim[:4], r.target, r.weight,
                                   r.reward_line, r.reward_dur_idx))
        return b"".join(out)
    if name == "ports":
        f = _fmt(BY_NAME["TgPort"])
        return b"".join(
            struct.pack(f, p.channel, p.reward_line, p.enter_code, p.error_code,
                        p.break_code, p.exit_code, p.reward_code, p.reward_stop_code,
                        p.reward_dur_idx, 0)
            for p in t.ports
        )
    if name == "stimuli":
        f = _fmt(BY_NAME["TgStimulus"])
        return b"".join(struct.pack(f, s.emitter, 0, s.on_code) for s in t.stimuli)
    if name == "stage_rows":
        f = _fmt(BY_NAME["TgStageRow"])
        return b"".join(struct.pack(f, r.at_trial, r.count, r.first_idx) for r in t.stage_rows)
    if name == "timing_sets":
        f = _fmt(BY_NAME["TgTimingSet"])
        return b"".join(struct.pack(f, s.idx, 0, s.ms) for s in t.timing_sets)
    if name == "max_dwell":
        #: Zero means "the compiler could not bound this node" -- sampling release
        #: and consumption, which wait on the subject. Safe as a sentinel because a
        #: node whose real bound is 0 ms cannot overrun anything, so the watchdog
        #: reading zero as "use the session ceiling" can never shorten a real bound.
        dwell = [d or 0 for d in t.max_dwell]
        return struct.pack(f"<{len(dwell)}H", *dwell)
    if name == "watch_pin":
        pins = list(t.watch_pins) + [NO_TARGET] * (WATCH_SLOTS - len(t.watch_pins))
        return bytes(pins[:WATCH_SLOTS])
    if name == "watch_port":
        ports = list(t.watch_ports) + [NO_TARGET] * (WATCH_SLOTS - len(t.watch_ports))
        return bytes(ports[:WATCH_SLOTS])
    raise AssertionError(f"no packer for section {name!r}")


def body(table: StateTable) -> bytes:
    return b"".join(_section(table, name) for name in SECTIONS)


def pack(table: StateTable) -> bytes:
    """Header + body + trailing CRC32 — exactly what goes over the wire.

    Deterministic: the same compiled table always produces the same bytes, which
    is what makes the CRC usable as provenance. Nothing here consults a dict
    ordering, a set, a hash seed or a clock.
    """
    payload = _header(table) + body(table)
    return payload + struct.pack("<I", zlib.crc32(payload) & 0xFFFFFFFF)


def crc32(packed: bytes) -> int:
    """The CRC the board must arrive at, read back out of packed bytes.

    Reading it rather than recomputing is deliberate at call sites that are
    *reporting* the value: the number the host announces in `TABLE BEGIN` should
    be the number inside the payload, so that a packer bug shows up as a board
    refusing the table rather than as two wrong numbers agreeing.
    """
    return struct.unpack("<I", packed[-CRC_SIZE:])[0]


def verify(packed: bytes) -> bool:
    """What the firmware does, in Python — the reference the C++ side is tested
    against."""
    if len(packed) < HEADER_SIZE + CRC_SIZE or not packed.startswith(MAGIC):
        return False
    return zlib.crc32(packed[:-CRC_SIZE]) & 0xFFFFFFFF == crc32(packed)

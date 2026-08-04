"""What a board says it can do, and whether this table fits.

`CAP` exists so the host stops compiling its own copy of `MAXSTATES`. That
pattern put `START_LINE_MAX` in two repos with nothing keeping them in sync and
`baudRate` in nine files, and its failure mode is not a build error — it is a
board silently truncating a table and running a session nobody specified
(`docs/protocol-negotiation.md`).

So the check here is the point of the whole announcement: **compare the compiled
table against the numbers the board stated, and refuse to upload with a message
naming both.** Nothing in this module has an opinion about what the limits are.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ephymeris_sidecar.taskgraph.table import StateTable


@dataclass
class Capabilities:
    """Parsed `CAP` lines. Unknown keys are kept, not dropped.

    Forward compatibility runs both ways: a board may announce a key this host
    does not know, and discarding it would make `taskgraph probe` useless for
    diagnosing exactly the mismatch someone is chasing.
    """

    values: dict[str, int] = field(default_factory=dict)
    text: dict[str, str] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)

    def __contains__(self, key: str) -> bool:
        return key in self.values or key in self.text

    def get(self, key: str, default: int | None = None) -> int | None:
        return self.values.get(key, default)

    @property
    def present(self) -> bool:
        """Did this board announce anything at all?

        An un-migrated box emits no CAP line, and that is not an error — it is
        PROTO=1, the legacy bare-START path, and the host is expected to fall
        back to it rather than complain.
        """
        return bool(self.lines)


def parse(lines: list[str]) -> Capabilities:
    caps = Capabilities()
    for line in lines:
        if not line.startswith("CAP\t") and not line.startswith("CAP "):
            continue
        caps.lines.append(line)
        for token in line[3:].split():
            key, _, value = token.partition("=")
            if not _:
                continue
            try:
                caps.values[key] = int(value)
            except ValueError:
                caps.text[key] = value
    return caps


class CapabilityError(RuntimeError):
    """The board cannot hold this table, or does not speak this protocol."""


#: Table dimension -> the CAP key that bounds it. Every one of these is a static
#: array on the board, so exceeding it is not a slow table -- it is a write past
#: the end of a global.
CAPACITY = (
    ("nodes", "MAXSTATES", lambda t: len(t.nodes)),
    ("edges", "MAXEDGES", lambda t: len(t.edges)),
    ("timing entries", "MAXTIMING", lambda t: len(t.timing)),
    ("actions", "MAXACTIONS", lambda t: len(t.actions)),
    ("trial types", "MAXTRIALTYPES", lambda t: len(t.trial_types)),
    ("ports", "MAXPORTS", lambda t: len(t.ports)),
    ("stimuli", "MAXSTIMULI", lambda t: len(t.stimuli)),
    ("watch channels", "MAXWATCH", lambda t: len(t.watch_pins)),
    ("stage rows", "MAXSTAGEROWS", lambda t: len(t.stage_rows)),
    ("timing rewrites", "MAXTIMINGSETS", lambda t: len(t.timing_sets)),
)


def check(caps: Capabilities, table: StateTable, wire_format: int) -> list[str]:
    """Raise if this board cannot take this table. Returns advisory notes.

    Ordered so the most fundamental mismatch is reported first: a board that does
    not speak the protocol at all should say so before being told its node count
    is fine.
    """
    if not caps.present:
        raise CapabilityError(
            "the board announced no CAP line, so it is running un-migrated firmware "
            "and has no table to upload into. Flash the interpreter sketch first."
        )

    proto = caps.get("PROTO")
    if proto is None or proto < 2:
        raise CapabilityError(
            f"the board speaks PROTO={proto}, which predates table upload. "
            f"PROTO=1 is the legacy bare-START path."
        )

    if not caps.get("TASKGRAPH"):
        raise CapabilityError("the board does not advertise TASKGRAPH=1")

    board_wire = caps.get("WIRE")
    if board_wire is None:
        raise CapabilityError(
            "the board announced no WIRE version, so there is no way to know how it "
            "expects a table to be packed. Refusing rather than guessing at offsets."
        )
    if board_wire != wire_format:
        raise CapabilityError(
            f"wire-format mismatch: this compiler packs v{wire_format}, the board "
            f"reads v{board_wire}. One of the two needs updating; uploading anyway "
            f"would be caught by the CRC, which is a worse way to find out."
        )

    over = [
        f"{name}: {count(table)} > {caps.get(key)}"
        for name, key, count in CAPACITY
        if key in caps and count(table) > caps.get(key, 0)
    ]
    if over:
        raise CapabilityError(
            "the table does not fit this board:\n  "
            + "\n  ".join(over)
            + "\nThe board's arrays are statically sized, so this would be a write "
              "past the end of a global rather than a slow table."
        )

    notes: list[str] = []
    #: Not fatal. A limit this host does not know about is the normal state of a
    #: board running newer firmware, and the design says unknown keys are ignored
    #: by both sides -- but a MISSING one this host does check is worth saying,
    #: because it means that dimension went unverified.
    for name, key, _ in CAPACITY:
        if key not in caps:
            notes.append(f"board did not announce {key}; {name} went unchecked")

    for key, label in (("SPEC", "spec"), ("VOCAB", "vocabulary"), ("CHANNELS", "channels")):
        if key in caps and caps.get(key) != table.spec_version and key == "SPEC":
            notes.append(
                f"board reads {label} v{caps.get(key)}, this table is v{table.spec_version}"
            )
    return notes

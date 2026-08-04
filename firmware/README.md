# Arduino — the table-driven interpreter

Firmware developed **alongside** the Python compiler in this repo, so a change to
the table format can move both sides in one commit and one review.

**Status: the interpreter runs, off-target only.** `TgInterpret.h` walks a compiled
table and emits the same strobe stream as `runTrial()`, proved by two gates that run in
CI (`tests/test_gate_a.py`, `tests/test_gate_b.py`). It has not been near a board: table
upload, CRC and the watchdog are Phase 4.

---

## Why this lives here and not in the firmware repo

The compiler and the interpreter share one artifact: the layout in
[`TaskTable.h`](libraries/TaskInterpreter/TaskTable.h). If a field moves, both sides must
move together or every uploaded table is silently misread. Keeping them in one repo makes
that a single atomic commit instead of a coordination problem across two histories.

The firmware repo stays a **read-only reference** throughout Phase 0–6. Nothing here
modifies it, and the existing behaviour sketches keep running and shipping unchanged.
`runTrial()` is not touched until Phase 7.

### When the firmware does need to change: `patches/`

The model is authoritative and firmware conforms (D21), so some changes have to happen
on the other side of that boundary. They are written here as patches rather than as
commits there — proposed, verified against the battery *before* being applied, and
reviewable in one place afterwards.

`patches/0001-behaviorbox-model-conformance.patch` has landed. It fixed an inverted
sensor test that could hang a box mid-session, made cue-off ordering consistent, and
gave omissions their own strobe. `tests/test_firmware_conformance.py` reads the
firmware repo's files and asserts all three are still there — including the seven
`task.json` strobe mirrors, which no gate would ever catch going stale because nothing
in the trial loop reads one.

See [`docs/firmware-changes.md`](../docs/firmware-changes.md) for what each change was
and why.

### BehaviorBox.h is consumed, not copied

The hardware and pinout layer is sound and orthogonal, and it is meant to survive the
migration intact — pins, `initBoxHardware()`, `emitStrobe()`, `verifySensor()`, and the
`AntiBiasSelector` / `AbstentionPenalty` / `CorrectionPolicy` classes are all reused here
rather than reimplemented.

So the build points at **two library roots** and `BehaviorBox.h` exists in exactly one
place:

```
--libraries <firmware-repo>/libraries    # BehaviorBox.h, single source
--libraries Task-Graph/Arduino/libraries # TaskInterpreter.h, this repo
```

Vendoring a copy would be faster to set up and would drift. Drifting mirrors are the
failure mode this project already documents twice — `START_LINE_MAX` across two repos, and
`baudRate` across nine files — and reproducing it in the one header both sides parse would
be the worst possible place for it.

---

## Layout

```
Arduino/
├── build.sh                                 two-root compile helper
├── patches/                                 changes the model requires of BehaviorBox.h
├── TaskRunner_Dev/                          dev sketch; compiles, runs nothing
└── libraries/TaskInterpreter/
    ├── TaskTable.h                          record layout — the compiler/firmware contract
    ├── TaskLimits.h                         capacity + protocol constants (WILL BE GENERATED)
    ├── TaskInterpreter.h                    declarations, plus the CAP announce
    ├── TgInterpret.h                        the interpreter; tgEnterNode owns every strobe
    ├── TgLayoutAssert.h                     generated; compiled under clang++ AND avr-g++
    └── extras/host_test/
        ├── Arduino.h                        mock clock, scripted sensors, captured Serial
        ├── run.sh / run_equivalence.sh      off-target checks
        ├── test_tasktable.cpp               layout assertions
        ├── gate_a.cpp                       C++ interpreter == Python reference
        └── gate_b.cpp                       interpreter == runTrial(), randomised battery
```

Bare folder libraries with no `library.properties`, and `extras/` for host tests — matching
the reference repo's conventions so the two feel like one codebase.

---

## Building

```bash
sh Arduino/build.sh                    # TaskRunner_Dev for arduino:avr:mega
sh Arduino/build.sh TaskRunner_Dev -v  # extra args pass through to arduino-cli
```

Set `BEHAVIORBOX_REPO` if the firmware repo is not the sibling default; the script fails
loudly rather than compiling against a missing header.

Off-target layout checks, needing no board and no Arduino shim:

```bash
sh Arduino/libraries/TaskInterpreter/extras/host_test/run.sh
```

Current footprint of the dev sketch, for reference: **1860 bytes** of globals (the 1440-byte
table plus BehaviorBox's own), leaving 6332 bytes.

---

## What is deliberately not here yet

| | Phase | Why not now |
|---|---|---|
| Table upload, CRC, watchdog | 4 | The interpreter reads a table compiled into the binary. Getting one over the wire, and bounding a state with the emitted max-dwell budget, is next. |
| Anything on a board | 5 | The gates run off-target. The first hardware run is a rig-validation session, not a subject. |
| Generated `TaskLimits.h` | 1 | The generator is Phase 1. The header is hand-written today and says so. |

`TaskRunner_Dev` idles rather than half-running a trial, because a skeleton that partly
works invites someone to trust it.

**Nothing in this folder is for animal use.** It drives no trial and delivers no reward.

---

## Two invariants to preserve when this grows

**One state, one entry strobe.** Every strobe must be emitted by exactly one call to
`tgEnterNode()`, so which edge fired is always recoverable from which strobe appeared and
every timestamp is a state-entry time. Nothing else may call `emitStrobe()`. A paired
emission is two nodes, the second with duration `t_zero` — measured at 0 ms skew on
hardware, so it costs nothing observable.

**CAP lines come before a bare `READY`, never on it.** The host matches readiness as an
exact whole line and ignores anything preceding it. Reverse that order and every deployed
host fails with *"board never reported READY"*. This ordering is precisely what lets a
migrated box keep working against an un-migrated host with no host-side change at all.

See [`docs/decisions.md`](../docs/decisions.md) for both, with the alternatives rejected.

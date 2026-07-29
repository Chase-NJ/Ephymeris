# Hardware Interaction Layer

> **Status** · Living spec — **Built and verified against real Mega2560 hardware.** The state machine (including `IN_SESSION`, §3.5), passthrough read/send, flashing, DTR reset, and out-of-band presence polling are all live.
>
> **Owns** · Everything that talks to the six boards: the per-port state machine, flashing, reset, passthrough monitoring, and board discovery.
>
> **Read with** · [websocket-protocol.md](websocket-protocol.md) (the messages that drive every operation here) · [arduino-directory.md](arduino-directory.md) (where flashable sketches come from) · [starting-a-session.md](starting-a-session.md) (what `IN_SESSION` actually does)
>
> **Still open** · Debug Mode batch flash · box re-binding UX

**Contents** — [1. Scope](#1-scope) · [2. Architecture](#2-architecture-overview) · [3. Per-Port State Machine](#3-per-port-state-machine) · [4. Flashing](#4-flashing) · [5. Reset](#5-reset) · [6. Passthrough](#6-passthrough-monitoring-read--send) · [7. Board Discovery](#7-board-discovery--status) · [8. Open Items](#8-open-items--tbd)

> **The invariant everything here exists to protect:** a serial port has exactly one owner at a time. Every state, every transition rule, and the entire out-of-band presence design follow from that one sentence.

---

## 0. Tech Stack

Tauri shell (Rust) · React 19 + TypeScript frontend · Python sidecar owning all serial I/O and `arduino-cli` interaction · local WebSocket between frontend and sidecar. Developed on macOS (Apple Silicon), shipped and run on Windows 11. Full detail in [`ephymeris_v1.0.md` §0](ephymeris_v1.0.md#0-tech-stack).

---

## 1. Scope

The hardware interaction layer is responsible for all direct communication with the 6× Arduino Mega2560 R3 boards. It owns:

- Board discovery and connection status
- Sketch flashing (compile + upload) via `arduino-cli`
- Hardware reset
- Live passthrough monitoring (raw serial, bidirectional)
- Serial I/O during an active behavior session (strobe protocol parsing)

It explicitly does **not** own: cohort/session data modeling, storage/serialization, or analytics. Those consume events produced by this layer but are out of scope for this doc.

---

## 2. Architecture Overview

- All hardware interaction lives in the **Python sidecar process** (not the frontend, not the shell/Rust layer if using Tauri).
- **Serial I/O:** `pyserial`, one dedicated thread per port (6 threads max, one per box).
- **Flashing/board tooling:** bundled `arduino-cli` binary, invoked via its **daemon mode (gRPC)** rather than repeated CLI subprocess calls, to support frequent/continuous status polling without process-spawn overhead.
  - **Implementation status: migrated (2026-07-29).** The daemon backend (`boards/grpc_tool.py`) is now primary, exactly where the `BoardTool` seam said it would go: one long-lived `arduino-cli daemon` child, client stubs generated from **vendored protos** (`sidecar/proto/`, taken at the tag named in `scripts/gen_grpc.py`, which must match the bundled CLI) and committed like the wire-protocol mirrors, so codegen never runs at install time. What it bought: no process spawn per presence poll, and **true line-by-line compile/upload streaming** (`out_stream`/`err_stream` chunks live, not `--format json`'s buffered replay). The subprocess backend was kept as the daemon's **per-call fallback** — chosen by `create_board_tool` when `grpcio` won't import (`EPHYMERIS_NO_GRPC_DAEMON=1` forces it for troubleshooting), and used per operation when the daemon can't spawn or dies mid-call. Every fallback logs loudly; flashing degrades to the proven path, never breaks.
  - **The daemon exits on stdin EOF** — its own parent-death watch, the same mechanism this app's sidecar uses against the shell. The spawn must hold a stdin pipe open for the daemon's lifetime; `stdin=DEVNULL` reads as an instant EOF and the daemon exits silently with code 0 before ever listening (found the hard way — it looks exactly like "the daemon is broken"). The pipe doubles as orphan protection: a hard-killed sidecar closes it, taking the daemon down too. Shutdown closes stdin first (the clean path) and only then terminates. Note the `--format json` startup banner is pretty-printed across multiple lines, so the address reader accumulates until the JSON parses.
  - FQBN: `arduino:avr:mega`
  - `arduino:avr` core is pre-installed and bundled with the app installer (not fetched at runtime) to avoid depending on internet access on lab machines.
- **Frontend:** communicates with the sidecar over WebSocket (schema TBD in a future section). The frontend never talks to serial ports or `arduino-cli` directly.

---

## 3. Per-Port State Machine

Each of the 6 ports has its own **independent state machine**. A given port can only be in one state at a time — this is the core invariant of the whole layer, because a serial port can only have one owner.

### 3.1 States

| State | Description |
|---|---|
| `IDLE` | Port not open. No owner. Board may or may not be physically connected. |
| `PASSTHROUGH` | Port open, raw bidirectional serial streaming to/from the GUI. Used for "clean and prime" workflows and general debug console use. No parsing, no storage. |
| `FLASHING` | `arduino-cli` compile + upload in progress. Port exclusively owned by the upload process. |
| `RESETTING` | Brief transitional state — DTR toggle in progress. |
| `IN_SESSION` | Port owned by the active behavior session runner. Strict strobe-protocol parsing; output feeds the storage pipeline. Entry/exit sequence specified in `starting-a-session.md` §7 and summarised in §3.5 below. |
| `ERROR` | Port failed to open, board disconnected unexpectedly, or an operation (flash/reset) failed. Requires user acknowledgment or auto-retry logic to return to `IDLE`. |

### 3.2 Transitions

The complete legal-transition table, as enforced by `assert_transition` in `ports/states.py`:

| From | May go to |
|---|---|
| `IDLE` | `PASSTHROUGH` · `FLASHING` · `RESETTING` · `IN_SESSION` · `ERROR` |
| `PASSTHROUGH` | `IDLE` · `FLASHING` · `RESETTING` · `ERROR` |
| `FLASHING` | `IDLE` · `PASSTHROUGH` · `ERROR` |
| `RESETTING` | `IDLE` · `PASSTHROUGH` · `ERROR` |
| `IN_SESSION` | `IDLE` · `ERROR` |
| `ERROR` | `IDLE` — and nothing else |

Read the **absences**, because they carry most of the meaning:

- **Nothing reaches `IN_SESSION` except `IDLE`.** In particular `PASSTHROUGH → IN_SESSION` is illegal, which is exactly why the session flash sequence passes `suppressPassthroughResume: true` (§3.3) — a box that auto-resumed into passthrough after its flash could not then be claimed by the runner.
- **`IN_SESSION` leads only to `IDLE` or `ERROR`.** A running animal cannot be flashed, reset, or monitored out from under itself.
- **`ERROR` is a dead end until acknowledged.** Only a manual `port.error.ack` clears it. There is no timeout and no retry.

A transition to the state a port is already in is a silent no-op, not an error.

### 3.3 Exclusivity Rules

- Only one state may be active per port at any time.
- Entering `FLASHING` or `RESETTING` **forces a clean release** of `PASSTHROUGH` first — close the port cleanly before handing it to `arduino-cli` or toggling DTR.
- **`FLASHING` and `RESETTING` are terminal-adjacent to `PASSTHROUGH`:** if the port was in `PASSTHROUGH` immediately before a flash or reset was triggered, the sidecar **auto-resumes `PASSTHROUGH`** afterward so the user sees the new sketch's output (or the reset board's boot output) without an extra click.
- **One deliberate exception to that auto-resume:** `port.flash` accepts `suppressPassthroughResume: bool` (default `false`). The session flash sequence sets it `true`, forcing every box to land in `IDLE` regardless of its pre-flash state, because the session runner can only claim an `IDLE` port. Debug Mode leaves it `false` and keeps the convenient behaviour.
- `IN_SESSION` is exclusive with everything — the session runner should refuse to start on a port that isn't `IDLE`, and no other operation (flash/reset/passthrough) should be permitted while `IN_SESSION` is active on that port. (Session-abort/emergency-stop handling is deferred to the session runner spec.)
- All state transitions must be enforced **in the sidecar**, not just the frontend. The GUI reflecting/disabling buttons is a UX nicety, not the source of truth — never trust the frontend to prevent an illegal transition.

### 3.4 GUI Representation

Each box gets a status badge reflecting its state (color/spinner per state above), shown on a per-box card in a 6-box grid. State changes should animate (Framer Motion) rather than snap, to reinforce that a port is mid-transition (e.g. "flashing…" → success pulse → auto-resume passthrough).

### 3.5 `IN_SESSION` entry and exit

No longer a stub — fully specified in `starting-a-session.md` §7 and implemented.
Summarised here because it is a state-machine concern:

**Entry** (per box, from `IDLE` only): open the port — which itself triggers the
Mega's DTR auto-reset (§5's existing mechanism, not a new one) — wait for the
board's `READY` line, send the built `START …` command (`data-saving.md` §6.3),
watch briefly for an optional `SEED\t<value>` line (§6.4), then enter
strobe-parsing mode.

**Parsing** is stricter than `PASSTHROUGH`'s opaque text (§6.2): a data line is
exactly `^\d{1,3}\t\d+$`, read as `[code, timestamp]`. Anything else is logged
to scrollback — which is also what gives a profile-less sketch its raw session
log — but is never treated as data.

**Exit (clean):** the board's own end-of-session strobe (identified by name in
the Task Profile's `strobes` map) → finalize the file → `IN_SESSION → IDLE`.

**Exit (board drop):** always a hard stop — see §8.

---

## 4. Flashing

- Two-step via `arduino-cli`:
  1. `compile --fqbn arduino:avr:mega <sketch_dir>`
  2. `upload -p <port> --fqbn arduino:avr:mega <sketch_dir>`
- Use `--format json` on both calls; parse structured output and stream progress/errors to the frontend incrementally (not just a spinner-until-done).
- User selects a sketch from the categorized list discovered in the configured **Arduino Directory** (see `arduino-directory.md` for location, structure, detection, and error/empty states) — no longer an arbitrary file browse per flash.
- On failure (compile error or upload failure), transition to `ERROR` with the parsed error message surfaced to the user; do not silently fall back to `IDLE`.
- On success, auto-resume `PASSTHROUGH` if that was the pre-flash state (see §3.3).

---

## 5. Reset

- Reset is a **serial-layer operation**, not an `arduino-cli` operation — it does not go through the daemon.
- Mechanism: toggle DTR line, which the Mega2560 R3's auto-reset circuit interprets as a reset signal.
  - Close port if open → `dtr = False` → brief delay (~100ms) → `dtr = True` → reopen.
- Treated as a short-lived `RESETTING` state; returns to prior context afterward (auto-resume `PASSTHROUGH` if applicable, per §3.3).

---

## 6. Passthrough Monitoring (Read + Send)

### 6.1 Purpose

Serves two use cases with a single implementation:
1. **Clean/prime workflow** — user has flashed a cleaning/priming sketch and wants to run it without any data being saved.
2. **General debug console** — raw serial monitor for any sketch, at any time a port isn't `FLASHING` or `IN_SESSION`.

### 6.2 Read Path

- Data is treated as **opaque text**, decoded with error-replacement for bad bytes. Never passed through the strobe-protocol parser used by `IN_SESSION`.
- Per-port **ring buffer**, capped at the last **2000 lines** — this is debug output, not data to retain long-term.
- **Throttled delivery to frontend:** the sidecar reads continuously but batches accumulated lines and flushes on a fixed **50 ms tick (20 Hz)** rather than one WebSocket message per line, to avoid flooding the UI under high-output sketches across six boxes.
- A partial line with no terminator is force-flushed once it exceeds a **4096-byte** cap, so a sketch that never sends a newline cannot grow the buffer without bound.
- **Line splitting** accepts `\n`, `\r`, and `\r\n`, since `Serial.println` emits CRLF but hand-written sketches emit all three. A trailing `\r` is held back briefly in case it is the first half of a CRLF split across two reads; if two flush ticks pass with no further data it is released as a complete line, so a bare-CR sketch that prints once and then waits still reaches the console.

### 6.3 Send Path

- Same per-port handler object that owns the read loop also exposes a `write(bytes)` method — reads and writes are never split across separate objects/threads for the same port, to avoid races with state transitions.
- **Line-ending selector per console panel:** None / Newline (`\n`) / Carriage Return (`\r`) / Both (`\r\n`). Default: Newline. Appended to user input before writing.
- Sent commands are echoed back into the console scrollback (visually distinct prefix) so sent/received history is interleaved and reviewable.
- **Send is only permitted while the port is in `PASSTHROUGH`.** Enforce this in the sidecar (reject + return an error for the frontend to toast), not just by disabling the UI input — guards against a queued send firing during a mid-flight state transition (e.g. a flash kicking off).

### 6.4 Baud Rate

- Per-box, user-configurable baud rate field on the connect/passthrough UI, defaulting to the configured `defaultBaud`. A user-chosen sketch may not match it.
- **`defaultBaud` ships as 9600**, which is what every sketch in the lab's Arduino Directory declares — each carries its own `baudRate` constant and they all agree. It shipped as 115200 for most of v1, which was wrong for every box on both machines and wrong *silently*: a mismatched console prints nothing legible rather than reporting an error, so it reads as a dead board. Config's baud picker and the setup wizard's handshake step both surface it, because that is where a wrong value first shows itself.

### 6.5 Data Handling / Scope Boundary

- Passthrough scrollback (received + sent) is **ephemeral and never enters the storage pipeline** — not written to `.json`/`.mat`/`.tsv`, not associated with any cohort/session record.
- Provide a "copy log" / "save debug log" affordance so users can manually export a passthrough session's output for troubleshooting, explicitly outside the formal data pipeline.

### 6.6 UI Shape

**Amendment (2026-07-27, was: 6-box grid of collapsible console panels).** Debug is now a constellation landing plus a per-box detail view (`ephymeris_v1.0.md` §4.3): the chosen zodiac layout with one clickable node per bound box, and selecting a node opens that box's full toolset. The *capabilities* below are unchanged — only their arrangement moved, from one packed panel per box to intent-grouped sections for the selected box:

- Connection/state badge (per §3.4), baud, open/close, reset, error acknowledge
- Scrollback (throttled/batched output, sent commands interleaved)
- Single-line input + line-ending selector + send button (Enter-to-send)
- **Utility controls + status** when the box's flashed sketch has a `"kind": "utility"` Task Profile (`data-saving.md` §6.6): the profile's `controls` render as buttons/selects that send serial commands over the same `port.send` path (gated to `PASSTHROUGH`), and a status strip parses the sketch's non-persisted `STATUS` lines out of the scrollback per the profile's `telemetry`. This rides the passthrough primitives — no new commands, nothing persisted — so a cleaning/self-test sketch is driven and monitored without leaving Debug.

### 6.7 The Config Handshake Test — Another Passthrough Composition

Config's per-box handshake test (`ephymeris_v1.0.md` §4.6) is a third rider on these same primitives, again deliberately without a new wire command: open passthrough (the open asserts DTR, which resets the Mega — §5 — and its boot output lands in `port.output` because the reader thread is attached by then), listen up to 10 s for a `READY` line or any output at all, close. **`port.reset` is unsuitable for this** and the test must never use it: its DTR pulse opens a throwaway handle that is never read, so the boot output it provokes is unobservable — and from `PASSTHROUGH` it would reset the board twice.

---

## 7. Board Discovery / Status

- **Resolved: status polling is out-of-band.** Board presence and identity are checked without ever opening the port — via the daemon's `BoardList` RPC (backed by the OS's serial port enumeration), on a continuous **1.5 s** interval. Since the gRPC migration this costs no process spawn at all — discovery runs inside the long-lived daemon; on a machine where the daemon can't run, the fallback's `board list` subprocess still covers all six ports in one call. Both backends apply identical filters (serial protocol, non-blank hardware id, truthy vendor id, no vendor allow-list), pinned against each other by `test_grpc_tool.py`.
- Board-list output includes non-Arduino serial ports (Bluetooth, debug consoles), so the poller filters them out: it keeps entries with `protocol == "serial"`, a non-blank `hardware_id` (falling back to `properties.serialNumber`), a truthy vendor id, and a non-empty address. It deliberately does **not** allow-list specific vendor ids — CH340 and FTDI clones are common in the lab and must still appear, even though they report no FQBN.
- Because this never opens the port, it **does not participate in the per-port state machine at all** and never contends with `PASSTHROUGH`, `FLASHING`, `RESETTING`, or `IN_SESSION` for ownership. A port can be polled for presence/identity regardless of its current state.
- The per-box status badge (§3.4) is therefore driven by two independent inputs: (1) this out-of-band presence/identity check, and (2) the port's own state-machine state. E.g. a box can show "connected, idle" vs. "connected, flashing" vs. "not detected."

---

## 8. The Hardware Utility Baseline

**The rig has a resting state, and the app maintains it.** A box that isn't
flashing, isn't in a console, and isn't running a session should be sitting on
the operator's chosen *hardware utility sketch* — the one that speaks
Ephymeris's own vocabulary (`data-saving.md` §6.6). That is what "baseline"
means here: not a mode the user enters, but the firmware a free box is expected
to be carrying.

The reason to want it is concrete. Before this, the state of a board between
sessions was whatever the last thing to touch it happened to leave behind — a
task sketch from three weeks ago, a half-finished prime, an unflashed board
fresh out of a drawer. Nothing could be asked of a box without first asking the
operator to flash something, which meant every small piece of hardware
assistance (light this box, pulse that line, confirm this port is alive) had to
begin with a detour. Maintaining the baseline pays that cost once, in the
background, and turns those into things the app can simply do.

### 8.1 When a restore happens

The trigger is always *a box becoming free*, never a clock:

- **On startup**, when the presence poll (§7) first reports the rig. This is the
  cold case: nothing is known about any board, so every bound box is a
  candidate.
- **When a board appears** — replugged, or a new one bound in Config.
- **When a port falls back to `IDLE`** — a run finishing, a console closing, an
  error acknowledged. Hooking the *transition* rather than each command means
  every path to idleness is covered by one rule, including ones added later.
- **When a session lets go** — `sessions.end`, `sessions.switchGroup`, or
  `sessions.abandon`. Switch Group restores immediately rather than waiting for
  the whole session, because the operator's very next act is walking the rig to
  swap animals, and that walk is what wants the lights.
- **On demand**, from Config's *Reflash boxes* button (`utility.ensure`, §3.5 of
  the protocol doc), which is the only path that passes `force`.

Restores run **one box at a time**, sequentially, for the same reason the
session flash sequence does (`starting-a-session.md` §4).

### 8.2 What it will never do

Two exclusions carry the whole design, and both are about not being clever:

- **Only an `IDLE` port is ever touched.** Entering `FLASHING` would happily
  force-release a `PASSTHROUGH` console (§3.3) — that is correct when a *user*
  asks to flash and unacceptable when a background restore does. So the check
  is on the port already being idle, not on the transition being legal.
- **A confirmed session mapping holds the entire rig.** Between
  `sessions.confirmMapping` and the session ending, boxes carry task sketches
  and fall idle constantly — between the flash sequence and Start All, and
  again after each animal finishes. A restore in that window would erase the
  sketch the runner is about to start, so the hold is not an optimisation; it
  is the difference between this feature working and it destroying sessions.

A restore that fails is reported (`state: "failed"` with the compiler's own
message) and then **acknowledged back out of `ERROR`**. A failed flash normally
leaves the port in `ERROR` awaiting a manual `port.error.ack` (§3.2), which is
right when the operator asked for the flash and wrong when they didn't: a
broken `arduino-cli` would otherwise put all six boxes into a state needing
individual clearing before anything else could run. The fault is surfaced in
Config instead, where it can be read and acted on, and the failure is sticky
per box so the acknowledgement can't bounce straight into another doomed
attempt.

### 8.3 Identify — asking a box to point at itself

With a known sketch on the board, "which box is box 3?" becomes answerable in
hardware. The utility sketch's Task Profile may declare an `identify` pair
(`data-saving.md` §6.8) — two commands, on and off. The sidecar opens
`PASSTHROUGH`, waits for the board's boot line, sends the *on* command, and
waits for the sketch's own telemetry line as confirmation that it was received
and acted on; the matching *off* sends the counterpart and closes the console
again, but only if this layer was the one that opened it. A box the user has
open in Debug Mode keeps its console.

Waiting for the reply rather than assuming it is what makes this trustworthy:
the most likely silent failure is a **baud mismatch**, and the difference
between "the light is on" and "we sent something into the void" is exactly the
difference the operator needs to know about. When no reply comes, the box is
reported failed with that cause named, and the caller is told the signal wasn't
delivered. Building this is what surfaced that `defaultBaud` shipped as 115200
while every sketch in the lab's directory opens at 9600 (§6.4) — the check
found a real misconfiguration on its first read-through, before it ever ran.

Its first consumer is the guided placement walk
(`starting-a-session.md` §3.5): one animal at a time, with that animal's box
lit until the enclosure is closed. That walk deliberately runs **before** the
session flash sequence — the boxes are still at baseline then, which is the
only firmware that can be asked to light one.

### 8.4 What a baseline sketch owes the rig

A sketch nominated as the baseline is held to two rules a merely-useful utility
sketch isn't, both because of what the baseline *is*: the firmware sitting on
every box the rest of the time, including while animals are being placed into
them.

- **Announce `READY` on boot**, exactly as a task sketch does. It is what
  Config's handshake test (§6.7) looks for to report the top tier, and it is
  the app's only evidence that the board on the far end of the port speaks its
  protocol at all. It does *not* then block for a `START` the way a task sketch
  does — there is no session, and the app begins sending commands the moment
  the port opens.
- **Do nothing on its own.** `BOX_Utility` inherited a convenience from
  `TEST_Box`, where an odor poke while idle started the full self-test. That
  was reasonable for a sketch you flashed by hand when you wanted to test a
  box, and it is not reasonable for the resting firmware: an animal placed in a
  chamber nose-pokes, and the self-test fires all twelve odor lines and pulses
  every fluid line. Removed. A baseline sketch reacts to the app and to nothing
  else.

---

## 9. Open Items / TBD

- [x] ~~WebSocket/IPC message schema between frontend and sidecar~~ — resolved in `websocket-protocol.md`
- [x] ~~Migrate the `BoardTool` backend from subprocess to the `arduino-cli` gRPC daemon (§2). **Committed, not conditional**~~ — **done (2026-07-29)**, as committed: protos vendored at the CLI's own tag, `grpcio-tools` codegen with committed stubs (`scripts/gen_grpc.py`), the daemon primary and the subprocess backend demoted to its fallback. Line-by-line compiler streaming is real now — chunks arrive mid-compile over the stream instead of being replayed from the final JSON object. Validated against the known-good baseline exactly as planned: integration tests drive a real daemon through spawn, kill-respawn, a streamed `arduino:avr:mega` compile, and a compile error (`test_grpc_tool.py`). The dependency-policy tension was resolved by fencing, not exception-by-fiat — see `reference.md`'s dependency policy. One discovery worth its own line: **the daemon watches its stdin and exits on EOF** (§2), so it must be spawned with a held-open pipe — and gets sidecar-grade orphan protection free as a result
- [x] ~~Session-runner interaction with this layer (start/stop/abort semantics on `IN_SESSION`)~~ — resolved in `starting-a-session.md` §7 and summarised in §3.5. Entry is `IDLE`-only (open → DTR auto-reset → `READY` → `START` → optional `SEED` → strobe parsing); clean exit is the board's own end-of-session strobe; `STOP` is sent but never forces the transition, since the firmware honours it at its next trial boundary
- [x] ~~Error recovery/retry policy for `ERROR` state — what should happen when a board drops mid-`IN_SESSION`~~ — resolved in `starting-a-session.md` §10: **always a hard stop, no auto-recovery.** A drop is exactly the failure `ERROR` already exists for, so the port goes `IN_SESSION → ERROR` like any other unexpected failure and clears through the existing manual `port.error.ack` — no new recovery logic. The file is finalized immediately with `stop_reason: "board disconnected"`, which costs nothing in data because `data-saving.md` §7's write-ahead log already made every strobe durable. v1 therefore ships manual acknowledgment only, by design rather than by omission
- [ ] **The utility baseline (§8) has never run against real boards.** Two things need watching the first time it does. (1) The cold-start restore is six sequential compiles-and-uploads triggered by the first presence poll, so the first minute or two of a fresh launch has the rig busy — tolerable, but if it proves annoying the answer is probably to defer the cold restore until something actually needs a box rather than to parallelise it. (2) `identify` confirms delivery by waiting for the sketch's telemetry line, which assumes the profile declares `telemetry`; a utility sketch with an `identify` pair and no `telemetry` block gets no confirmation and is trusted on the send alone
- [ ] Multi-port operation batching (e.g. "flash all 6" workflows) — sequential vs. parallel, and how partial failures are surfaced. **Partly answered:** the session flash sequence (`starting-a-session.md` §4) is strictly sequential and halts at the first failure, and that's built. What's still open is whether Debug Mode wants a batch flash at all, and whether it would share this policy
- [ ] Box→board binding UI depth: how a board that is physically swapped (new `hardware_id`, same cage) gets re-bound. **Partially addressed** — bindings now live in Config (`ephymeris_v1.0.md` §4.6) with a re-runnable setup wizard and a handshake test to confirm the swap took; proactive "new board detected, bind it?" surfacing is the part still open
- [x] ~~§6.5's "save debug log" as a file: v1 ships copy-to-clipboard only. **Decide which owns it** — `tauri-plugin-fs` plus a save dialog, or a sidecar-side export command~~ — **decided and built: the shell owns it.** `NodeDetail.tsx` gains a save button beside copy (`save()` from the dialog plugin → `writeTextFile()` from `tauri-plugin-fs`), exporting whichever console tab is visible. Shell-side won on three grounds: the frontend already used the dialog plugin for folder pickers, the dialog grants the chosen path to the fs scope at runtime so the webview can write exactly that file and nothing else, and the export keeps working when the sidecar is down — which is when a debug log matters most. Still ephemeral, still outside the data pipeline (§6.5)

---

**Next:** [websocket-protocol.md](websocket-protocol.md) — the messages that drive every operation in this document.
[Documentation index](README.md) · [Open items register](TODO.md)

# Hardware Interaction Layer

> **Status** · Living spec — **Built and verified against real Mega2560 hardware.** The state machine (including `IN_SESSION`, §3.5), passthrough read/send, flashing, DTR reset, and out-of-band presence polling are all live.
>
> **Owns** · Everything that talks to the six boards: the per-port state machine, flashing, reset, passthrough monitoring, and board discovery.
>
> **Read with** · [websocket-protocol.md](websocket-protocol.md) (the messages that drive every operation here) · [arduino-directory.md](arduino-directory.md) (where flashable sketches come from) · [starting-a-session.md](starting-a-session.md) (what `IN_SESSION` actually does)
>
> **Still open** · The gRPC migration · Debug Mode batch flash · box re-binding UX · saving a debug log to file

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
  - **Implementation status (deferred, not overturned):** v1 ships a subprocess + `--format json` backend behind a `BoardTool` interface, with the gRPC daemon to be swapped in behind that same interface later. Reason: `arduino-cli` publishes no official Python gRPC client, so the daemon path requires vendoring its `.proto` files and adding a `grpcio-tools` codegen step — the highest-uncertainty work in the layer, front-loaded before there is a working app to validate it against. The polling cost that motivated daemon mode is also lower than first assumed: a single `board list` call covers all six ports, so the 1–2s poll is ~1 subprocess/sec, not 6. See §8.
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

- Per-box, user-configurable baud rate field on the connect/passthrough UI (default: standard session baud rate, e.g. 115200). A user-chosen sketch may not match the app's default session baud rate.

### 6.5 Data Handling / Scope Boundary

- Passthrough scrollback (received + sent) is **ephemeral and never enters the storage pipeline** — not written to `.json`/`.mat`/`.tsv`, not associated with any cohort/session record.
- Provide a "copy log" / "save debug log" affordance so users can manually export a passthrough session's output for troubleshooting, explicitly outside the formal data pipeline.

### 6.6 UI Shape

6-box grid of collapsible console panels (independently toggleable), each showing:
- Connection/state badge (per §3.4)
- Scrollback (throttled/batched output, sent commands interleaved)
- Single-line input + line-ending selector + send button (Enter-to-send)
- **Utility controls + status** when the box's flashed sketch has a `"kind": "utility"` Task Profile (`data-saving.md` §6.6): the profile's `controls` render as buttons/selects that send serial commands over the same `port.send` path (gated to `PASSTHROUGH`), and a status strip parses the sketch's non-persisted `STATUS` lines out of the scrollback per the profile's `telemetry`. This rides the passthrough primitives — no new commands, nothing persisted — so a cleaning/self-test sketch is driven and monitored without leaving Debug Mode.

---

## 7. Board Discovery / Status

- **Resolved: status polling is out-of-band.** Board presence and identity are checked without ever opening the port — via `arduino-cli board list` (backed by the OS's serial port enumeration), on a continuous **1.5 s** interval. Until the gRPC migration lands this runs through the subprocess backend described in §2; one `board list` call covers all six ports, so the poll costs roughly one subprocess per second, not six.
- Board-list output includes non-Arduino serial ports (Bluetooth, debug consoles), so the poller filters them out: it keeps entries with `protocol == "serial"`, a non-blank `hardware_id` (falling back to `properties.serialNumber`), a truthy vendor id, and a non-empty address. It deliberately does **not** allow-list specific vendor ids — CH340 and FTDI clones are common in the lab and must still appear, even though they report no FQBN.
- Because this never opens the port, it **does not participate in the per-port state machine at all** and never contends with `PASSTHROUGH`, `FLASHING`, `RESETTING`, or `IN_SESSION` for ownership. A port can be polled for presence/identity regardless of its current state.
- The per-box status badge (§3.4) is therefore driven by two independent inputs: (1) this out-of-band presence/identity check, and (2) the port's own state-machine state. E.g. a box can show "connected, idle" vs. "connected, flashing" vs. "not detected."

---

## 8. Open Items / TBD

- [x] ~~WebSocket/IPC message schema between frontend and sidecar~~ — resolved in `websocket-protocol.md`
- [ ] Migrate the `BoardTool` backend from subprocess to the `arduino-cli` gRPC daemon (§2). **Committed, not conditional** — the subprocess backend is a staging step, not the destination. Requires vendoring the `.proto` files and a `grpcio-tools` codegen step. Was scheduled for after flashing worked end-to-end so it could be validated against a known-good baseline; **that milestone is reached**, making this the next hardware-layer task. It also buys true line-by-line compiler streaming, which the subprocess backend's `--format json` cannot provide (output arrives buffered at phase end)
- [x] ~~Session-runner interaction with this layer (start/stop/abort semantics on `IN_SESSION`)~~ — resolved in `starting-a-session.md` §7 and summarised in §3.5. Entry is `IDLE`-only (open → DTR auto-reset → `READY` → `START` → optional `SEED` → strobe parsing); clean exit is the board's own end-of-session strobe; `STOP` is sent but never forces the transition, since the firmware honours it at its next trial boundary
- [x] ~~Error recovery/retry policy for `ERROR` state — what should happen when a board drops mid-`IN_SESSION`~~ — resolved in `starting-a-session.md` §10: **always a hard stop, no auto-recovery.** A drop is exactly the failure `ERROR` already exists for, so the port goes `IN_SESSION → ERROR` like any other unexpected failure and clears through the existing manual `port.error.ack` — no new recovery logic. The file is finalized immediately with `stop_reason: "board disconnected"`, which costs nothing in data because `data-saving.md` §7's write-ahead log already made every strobe durable. v1 therefore ships manual acknowledgment only, by design rather than by omission
- [ ] Multi-port operation batching (e.g. "flash all 6" workflows) — sequential vs. parallel, and how partial failures are surfaced. **Partly answered:** the session flash sequence (`starting-a-session.md` §4) is strictly sequential and halts at the first failure, and that's built. What's still open is whether Debug Mode wants a batch flash at all, and whether it would share this policy
- [ ] Box→board binding UI depth: how a board that is physically swapped (new `hardware_id`, same cage) gets re-bound without hunting through Settings
- [ ] §6.5's "save debug log" as a file: v1 ships copy-to-clipboard only (`ConsolePanel.tsx`'s `copyLog()` → `navigator.clipboard.writeText`). Saving to disk needs a write path the shell doesn't currently have — either `tauri-plugin-fs` plus a save dialog, or a sidecar-side export command. **Decide which owns it**

---

**Next:** [websocket-protocol.md](websocket-protocol.md) — the messages that drive every operation in this document.
[Documentation index](README.md) · [Open items register](TODO.md)

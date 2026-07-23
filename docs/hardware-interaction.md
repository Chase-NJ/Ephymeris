# Hardware Interaction Layer — Full Spec

**Status:** Living document. Covers the serial/Arduino hardware layer only.
**Companion documents:** `ephymeris_v1.0.md` (tech stack, dashboard, Settings), `arduino-directory.md` (sketch/library discovery consumed by §4, Flashing).
**Not yet covered (future sections):** WebSocket/IPC message schema, behavior session runner, cohort management, storage layer (.json/.mat/.tsv), analytics pipeline.

---

## 0. Tech Stack

- **Shell / desktop runtime:** Tauri
- **Frontend:** React (TypeScript), styled with Tailwind, animated with Framer Motion
- **Backend:** Python sidecar process (owns all serial I/O, `arduino-cli` interaction, storage, and analytics)
- **Frontend ↔ sidecar communication:** local WebSocket (message schema TBD in a future section)
- **Target platforms:** developed on macOS (Apple Silicon); shipped/run on Windows 11 (both lab machines)

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
| `IN_SESSION` | Port owned by the active behavior session runner. Strict strobe-protocol parsing; output feeds the storage pipeline. |
| `ERROR` | Port failed to open, board disconnected unexpectedly, or an operation (flash/reset) failed. Requires user acknowledgment or auto-retry logic to return to `IDLE`. |

### 3.2 Transitions

```
IDLE ──────────► PASSTHROUGH ──────────► IDLE
IDLE ──────────► FLASHING ─────────────► IDLE (or auto-resume PASSTHROUGH, see 3.3)
IDLE ──────────► RESETTING ────────────► IDLE
IDLE ──────────► IN_SESSION ───────────► IDLE
PASSTHROUGH ───► FLASHING              (auto-releases port first)
PASSTHROUGH ───► RESETTING             (auto-releases port first)
any state ─────► ERROR                 (on failure)
ERROR ─────────► IDLE                  (on user ack / recovery)
```

### 3.3 Exclusivity Rules

- Only one state may be active per port at any time.
- Entering `FLASHING` or `RESETTING` **forces a clean release** of `PASSTHROUGH` first — close the port cleanly before handing it to `arduino-cli` or toggling DTR.
- **`FLASHING` and `RESETTING` are terminal-adjacent to `PASSTHROUGH`:** if the port was in `PASSTHROUGH` immediately before a flash or reset was triggered, the sidecar should **auto-resume `PASSTHROUGH`** afterward so the user sees the new sketch's output (or the reset board's boot output) without an extra click.
- `IN_SESSION` is exclusive with everything — the session runner should refuse to start on a port that isn't `IDLE`, and no other operation (flash/reset/passthrough) should be permitted while `IN_SESSION` is active on that port. (Session-abort/emergency-stop handling is deferred to the session runner spec.)
- All state transitions must be enforced **in the sidecar**, not just the frontend. The GUI reflecting/disabling buttons is a UX nicety, not the source of truth — never trust the frontend to prevent an illegal transition.

### 3.4 GUI Representation

Each box gets a status badge reflecting its state (color/spinner per state above), shown on a per-box card in a 6-box grid. State changes should animate (Framer Motion) rather than snap, to reinforce that a port is mid-transition (e.g. "flashing…" → success pulse → auto-resume passthrough).

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
- Per-port **ring buffer**, capped (e.g. last 2000 lines) — this is debug output, not data to retain long-term.
- **Throttled delivery to frontend:** sidecar reads continuously but batches accumulated lines and flushes to the frontend on a fixed tick (e.g. every 50ms / 20Hz) rather than one WebSocket message per line, to avoid flooding the UI under high-output sketches (×6 boxes).

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

---

## 7. Board Discovery / Status

- **Resolved: status polling is out-of-band.** Board presence/identity is checked without ever opening the port — via the `arduino-cli` daemon's board-list query (backed by the OS's serial port enumeration), on a short continuous interval (e.g. every 1–2s).
- Because this never opens the port, it **does not participate in the per-port state machine at all** and never contends with `PASSTHROUGH`, `FLASHING`, `RESETTING`, or `IN_SESSION` for ownership. A port can be polled for presence/identity regardless of its current state.
- The per-box status badge (§3.4) is therefore driven by two independent inputs: (1) this out-of-band presence/identity check, and (2) the port's own state-machine state. E.g. a box can show "connected, idle" vs. "connected, flashing" vs. "not detected."

---

## 8. Open Items / TBD

- [ ] WebSocket/IPC message schema between frontend and sidecar
- [ ] Session-runner interaction with this layer (start/stop/abort semantics on `IN_SESSION`)
- [ ] Error recovery/retry policy for `ERROR` state (auto-retry vs. manual ack)
- [ ] Multi-port operation batching (e.g. "flash all 6" workflows) — sequential vs. parallel, and how partial failures are surfaced

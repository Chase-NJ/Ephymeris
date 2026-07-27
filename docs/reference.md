# Engineering Reference

> **Status** · Derived view, maintained alongside the seven specs. Where a spec and this document disagree on *behaviour*, the spec wins. This document is authoritative on **where things live** and **what is actually built**.
>
> **Purpose** · The specs describe behaviour and rationale but never map to files. This one does. Read it after [ephymeris_v1.0.md](ephymeris_v1.0.md) and before touching code.
>
> **Verified** · On 2026-07-26, after building `data-saving.md` §8's Backup Directory mirroring. `tsc --noEmit` clean · **372** sidecar tests passing · **2** Rust tests passing.

**Contents** — [1. Architecture](#1-system-architecture) · [2. Module Map](#2-module-map) · [3. Wire Surface](#3-wire-surface-at-a-glance) · [4. Core Behaviours](#4-core-domain-behaviours) · [5. Implementation Status](#5-implementation-status) · [6. Development](#6-development) · [7. Known Rough Edges](#7-known-rough-edges-in-the-code) · [8. Glossary](#8-glossary)

---

## 1. System Architecture

Three processes, one WebSocket, one strict ownership rule.

```
┌──────────────────────────────────────────────────────────────────┐
│  Tauri shell — Rust (src-tauri/)                                 │
│  · spawns & supervises the sidecar                               │
│  · owns settings persistence (tauri-plugin-store)                │
│  · native directory pickers                                      │
│  · NO hardware or session logic                                  │
└───────────────┬──────────────────────────────┬───────────────────┘
                │ spawn (piped stdio)          │ serves
                │ handshake on stdout          │
                ▼                              ▼
┌───────────────────────────────┐   ┌──────────────────────────────┐
│ Python sidecar (sidecar/)     │   │ React webview (src/)         │
│ SOURCE OF TRUTH for:          │◄──┤ · renders reported state     │
│  · serial I/O (pyserial)      │ WS│ · never predicts transitions │
│  · arduino-cli invocation     │──►│ · never touches serial       │
│  · SQLite (cohorts/sessions)  │   │ · pushes settings on connect │
│  · session file writing       │   └──────────────────────────────┘
│  · state machine enforcement  │
└───────────────┬───────────────┘
                │ pyserial · arduino-cli
                ▼
      6 × Arduino Mega2560 R3 ("boxes")
```

### The three rules that explain most design decisions

1. **The sidecar owns all state.** The frontend renders what it is told. An illegal operation is rejected server-side with a typed error code; disabled UI buttons are a courtesy, not enforcement.
2. **A serial port has exactly one owner.** This is the core invariant of the hardware layer and the reason the per-port state machine exists at all.
3. **Box number 1–6 is the key, never a port address.** Windows renumbers COM ports across reboots; the sidecar resolves `box → hardware_id → current address` internally.

### Process lifecycle

Rust spawns `python -m ephymeris_sidecar --data-dir <app_data_dir>` with piped stdio. The sidecar binds `127.0.0.1` on an ephemeral port, generates a random token, and prints **exactly one line** to stdout:

```
EPHYMERIS_WS_PORT=<port> EPHYMERIS_WS_TOKEN=<token>
```

Everything else it logs goes to stderr and is forwarded into the Tauri log. Rust parses that line and emits `sidecar://ready`, or `sidecar://down` if stdout closes.

> **Orphan protection is load-bearing, not a nicety.** Tauri holds the sidecar's stdin open for the app's lifetime; the sidecar exits on stdin EOF, and Rust also kills the child on exit. A sidecar that outlived its parent would keep serial ports open and lock out the next launch.

> **There is no auto-respawn.** A crashed sidecar surfaces `sidecar://down` and the user restarts the app. A silent respawn would resurrect the process without the port ownership or session state it had.

Full detail: [`websocket-protocol.md` §1](websocket-protocol.md#1-transport--lifecycle).

---

## 2. Module Map

### 2.1 Python sidecar — `sidecar/ephymeris_sidecar/`

Owns everything stateful. Runtime dependencies are deliberately just `pyserial` and `websockets`; see §6 before adding a third.

| Module | Responsibility | Spec |
|---|---|---|
| `__main__.py` | CLI entry, `--data-dir`/`--token`/`--no-parent-watch`, stdin-EOF orphan watch | protocol §1 |
| `app.py` | Wires everything together; registers **33** command handlers. The largest module (~800 lines) and the place to look first for any command's behaviour | protocol §3 |
| `server.py` | WebSocket server, auth handshake, command dispatch, event fan-out. Handles `auth` itself, before dispatch | protocol §1.1 |
| `settings.py` | Receives the shell's settings push. Deliberately lenient — an unknown key is a non-event, a malformed value degrades to a default rather than killing the process that owns the ports | v1.0 §4.5 |
| `discovery.py` | Arduino Directory validation and sketch/library scanning, including the skipped-but-reported rule | arduino-directory §3–§6 |
| `protocol.py` | Hand-maintained mirror of the wire schema — commands, events, error codes, envelope builders | protocol (all) |
| **`ports/`** | | |
| `ports/states.py` | The state machine transition table and `assert_transition`. Small, and the authority on what is legal | hardware §3 |
| `ports/handler.py` | Per-port owner: read loop, write path, ring buffer, line splitting, the three-phase session handshake, strobe parsing | hardware §6 |
| `ports/manager.py` | Owns the six handlers, the binding map, the 1.5 s presence poll, and the 20 Hz output flush | hardware §7 |
| **`boards/`** | | |
| `boards/tool.py` | The `BoardTool` interface — the seam the gRPC migration will slot into | hardware §2 |
| `boards/cli_tool.py` | Current backend: `arduino-cli` subprocess with `--format json` | hardware §2, §4 |
| **`cohorts/`** | | |
| `cohorts/db.py` | SQLite connection and schema. Its connection subclass reports every commit, which is what triggers a database backup — hooking `commit` rather than each repository method means no write path can forget | cohorts §3, data-saving §8.3 |
| `cohorts/models.py` | Cohort/Animal/Group dataclasses | cohorts §1 |
| `cohorts/repository.py` | CRUD, validation, archive/delete semantics | cohorts §2, §9 |
| `cohorts/folders.py` | Data folder resolution, name sanitization, collision suffixing | cohorts §8 |
| `cohorts/grouping.py` | Auto-Balance balanced round-robin | cohorts §7.3 |
| **`sessions/`** | | |
| `sessions/models.py` | `Session` and `SessionAnimalRun` records | data-saving §4 |
| `sessions/repository.py` | Session/prefix persistence, session-number suggestion | data-saving §3–§4 |
| `sessions/paths.py` | Directory and filename construction. Pure, no I/O. Also `parse_name_date`, which reads both the current ISO and the legacy `MM_DD_YY` spelling — **use it instead of sorting names as strings**, since both formats coexist on disk | data-saving §1–§2 |
| `sessions/writer.py` | Per-animal file writer. `.tsv` write-ahead log with per-line `flush()`+`fsync()`, opened exclusively so a collision fails loudly; `.json`/`.mat` built once at finalization | data-saving §5, §7 |
| `sessions/matwriter.py` | Hand-written MAT v5 serializer — exists specifically to avoid a `scipy` dependency | data-saving §5.1 |
| `sessions/runner.py` | Live session runner: which animal is in which box, its writer, its metrics, its run record. Writer I/O stays on the port's session thread; anything touching the socket or state machine is scheduled back onto the event loop | starting §7 |
| **`backup/`** | | |
| `backup/manager.py` | The mirror: queued finalization copies, the 10 s self-paced `.tsv` pass, the debounced `ephymeris.db` backup with dated snapshots, and the explicit sync walk. Every filesystem operation runs in a worker thread; nothing here is ever on a session's critical path | data-saving §8 |
| `backup/paths.py` | Mirror path resolution, anchored on the cohort folder rather than `dataDirectory` — a relocated cohort isn't under it, so path subtraction doesn't work in general. Pure, no I/O | data-saving §8.1 |
| **`tasks/`** | | |
| `tasks/profile.py` | `task.json` parsing and validation | data-saving §6.1–§6.2 |
| `tasks/start_command.py` | Builds `START <wireKey>=<value> …` from a profile plus config | data-saving §6.3 |
| `tasks/metrics.py` | Rolling live-metric computation. This is scientific output, not a UI detail — the hit/miss/excluded definition is followed to the letter | data-saving §6.5 |

### 2.2 React frontend — `src/`

Talks to the sidecar over the WebSocket only.

| Path | Responsibility |
|---|---|
| `lib/ws/client.ts` | Connection lifecycle, auth, reconnect with backoff (250 ms → 8 s, six steps then held), request/reply correlation, event fan-out |
| `lib/ws/protocol.ts` | The second hand-maintained mirror of the wire schema |
| `lib/ws/SidecarProvider.tsx` | Mounts the client at the app root |
| `lib/{hardware,cohorts,sessions,settings}/` | One Provider + store per domain, each wrapping the shared client |
| `lib/settings/schema.ts` | The settings shape and its normalizer, tolerant of older stored shapes |
| `lib/backup/useBackupStatus.ts` | Live mirroring state plus the `backup.syncNow` call. A hook rather than a Provider — unlike hardware state, nothing needs this on every screen or needs it accumulating while unmounted |
| `lib/sessions/stars.ts` | Deterministic star placement seeded from `(cohortId, animalId)`, plus the nearest-neighbour link pass |
| `lib/prng.ts` | The `mulberry32`-style seeded generator behind every procedural visual |
| `lib/motion.ts`, `lib/useReduceMotion.ts` | Shared spring definitions and the reduced-motion hook |
| `styles/index.css` | **The theme.** Tailwind v4 `@theme` block — every colour, font, and radius token lives here. There is no `tailwind.config.js` |
| `routes/` | One component per top-level view, wired in `App.tsx` under a shared `AppShell` |
| `components/chrome/` | Persistent shell: sidebar, titlebar, starfield, constellation status widget |
| `components/cohorts/` | Cohort grid, editor panels, procedural icon, Auto-Balance |
| `components/debug/` | Console panels, flash dialog, state badges, utility controls |
| `components/sessions/` | Mission Control surfaces — 3D constellation, metric strip, star panel, task config form, journey rail, placement banner |

**`HardwareProvider` is mounted at the app root, not per-view**, because the sidebar's constellation status widget needs box health on every screen — not only in Debug Mode.

#### Routes

| Route | View | Status |
|---|---|---|
| `/` | Dashboard — hero CTA plus three summary tiles | Wired |
| `/cohorts`, `/cohorts/new`, `/cohorts/:id` | Cohort browser and editor | Wired |
| `/debug` | Debug Mode console grid | Wired |
| `/session/new` | Step 1 — configuration | Wired |
| `/session/:id/mapping` | Step 2 — animal→box mapping, config, flash | Wired |
| `/session/:id/control` | Mission Control + 3D constellation | Wired |
| `/settings` | Settings | Wired |
| `/analytics` | Analytics | **Stub** — also serves as the session-end landing |
| `*` | Falls back to the dashboard rather than a blank pane or a 404 | — |

### 2.3 Rust shell — `src-tauri/src/`

| File | Responsibility |
|---|---|
| `main.rs` | Binary entry |
| `lib.rs` | Tauri builder, plugin registration, the `sidecar_endpoint` command |
| `sidecar.rs` | Spawn, handshake parsing, stdout/stderr forwarding, stdin-held-open orphan protection, kill on exit |

The interpreter resolves to `sidecar/.venv` unless `EPHYMERIS_SIDECAR_PYTHON` overrides it. The app data directory is resolved here so shell and sidecar cannot disagree about where `ephymeris.db` lives.

---

## 3. Wire Surface at a Glance

[`websocket-protocol.md`](websocket-protocol.md) is canonical and carries every argument, result, and payload shape. This is the index.

The surface is **34 commands, 12 events, 22 error codes**. 33 commands are registered in `app.py`; `auth` is handled in `server.py` as the connection's mandatory first message and never reaches the dispatch table.

**Envelope.** JSON over loopback. Client→server is always a command carrying a client-generated `id`. Server→client is either a correlated reply (`corr`, exactly one per command) or an unsolicited event. Protocol version mismatches are rejected, not best-effort parsed. `PROTOCOL_VERSION` is `1`.

### Commands (34 including `auth`)

| Group | Commands |
|---|---|
| Connection | `auth`, `ping`, `settings.push` |
| Sketches | `sketches.refresh` |
| Ports | `port.passthrough.open`, `port.passthrough.close`, `port.send`, `port.flash`, `port.reset`, `port.error.ack` |
| Cohorts | `cohorts.list`, `.get`, `.create`, `.update`, `.archive`, `.restore`, `.delete`, `.setDataFolder`, `.suggestGroups` |
| Prefixes | `prefixes.list`, `.create`, `.delete` |
| Task profiles | `tasks.getProfile` |
| Sessions | `sessions.suggestNumber`, `.create`, `.abandon`, `.confirmMapping`, `.status`, `.startAll`, `.switchGroup`, `.end` |
| Session ports | `port.startSession`, `port.stopSession` |
| Backup | `backup.syncNow` |

### Events (12)

`server.hello` · `port.state` · `port.output` · `boards.presence` · `flash.progress` · `sketches.updated` · `cohorts.updated` · `prefixes.updated` · `session.telemetry` · `session.animalEnded` · `backup.status` · `sidecar.error`

All twelve are emitted. `sidecar.error` fires on a mid-session `.tsv` write failure — the failure with no command to attribute it to, and the one a user most needs to hear about immediately.

### Error codes (22)

`BAD_MESSAGE` · `UNKNOWN_COMMAND` · `UNAUTHORIZED` · `PROTOCOL_VERSION_MISMATCH` · `ILLEGAL_TRANSITION` · `SEND_NOT_PASSTHROUGH` · `PORT_NOT_BOUND` · `PORT_OPEN_FAILED` · `FLASH_FAILED` · `SKETCH_UNKNOWN` · `COHORT_NOT_FOUND` · `COHORT_NAME_TAKEN` · `COHORT_INVALID` · `COHORT_NOT_ARCHIVED` · `DATA_FOLDER_INVALID` · `PREFIX_NAME_TAKEN` · `SESSION_INVALID` · `SESSION_NOT_READY` · `TASK_PROFILE_INVALID` · `BACKUP_UNAVAILABLE` · `DIR_INVALID` · `INTERNAL`

`DIR_INVALID` is defined in both mirrors but **never raised** — directory problems surface as a `DirectoryStatus` payload instead. See the note in `websocket-protocol.md` §6.

### Changing the wire — the required order

There is no codegen. The surface is small enough that a build step would cost more than it saves, so drift is prevented by a test instead:

1. Update `docs/websocket-protocol.md` (the source of truth).
2. Update `sidecar/ephymeris_sidecar/protocol.py`.
3. Update `src/lib/ws/protocol.ts`.
4. Run `pytest tests/test_protocol_contract.py` — **69 cases** that fail the build if the mirrors drift.

That test compares **names and the protocol version** across all three files. It does not check payload shapes, and it does not verify that a command has a handler.

### Behaviours worth knowing before you debug

- **State replay on connect.** After a successful `auth` the server unicasts current state to that client alone: one `port.state` per box, then `boards.presence`, `sketches.updated`, `cohorts.updated`, and `prefixes.updated`. **Live session state is not replayed** — a client reconnecting mid-session must call `sessions.status` to learn what is running.
- **Settings re-push on every auth**, including reconnects. This is the wire-level implementation of the one-directional Tauri→sidecar sync.
- **`port.output` is batched at ~20 Hz**, not one message per line. Six chatty boxes would otherwise flood the UI.
- **Client-side timeouts don't cancel sidecar work.** Default 15 s; `port.flash` gets 300 s and `sketches.refresh` 60 s. The sidecar remains the authority on what actually happened.

---

## 4. Core Domain Behaviours

Condensed; each links to the spec that owns it.

### 4.1 Per-port state machine — [`hardware-interaction.md` §3](hardware-interaction.md#3-per-port-state-machine)

Six states: `IDLE`, `PASSTHROUGH`, `FLASHING`, `RESETTING`, `IN_SESSION`, `ERROR`. Each of the six ports runs its own independent machine, enforced in `ports/states.py`.

| From | May go to |
|---|---|
| `IDLE` | `PASSTHROUGH` · `FLASHING` · `RESETTING` · `IN_SESSION` · `ERROR` |
| `PASSTHROUGH` | `IDLE` · `FLASHING` · `RESETTING` · `ERROR` |
| `FLASHING` | `IDLE` · `PASSTHROUGH` · `ERROR` |
| `RESETTING` | `IDLE` · `PASSTHROUGH` · `ERROR` |
| `IN_SESSION` | `IDLE` · `ERROR` |
| `ERROR` | `IDLE` only, by manual ack |

The deliberate absences matter: nothing enters `IN_SESSION` except from `IDLE` — `PASSTHROUGH → IN_SESSION` is illegal — and `IN_SESSION` leads only to `IDLE` or `ERROR`.

**The auto-resume exception.** Flash and reset normally resume `PASSTHROUGH` if that was the pre-operation state. The session flash sequence passes `suppressPassthroughResume: true` so boxes land in `IDLE` for the runner to claim.

**Board presence is out-of-band.** Polled via `arduino-cli board list` every 1.5 s, never opening a port, so it never contends for ownership. A box reports "connected" and "flashing" as two independent facts.

### 4.2 Session data path — [`starting-a-session.md` §7](starting-a-session.md#7-in_session--resolving-the-hardware-layer-tbd), [`data-saving.md` §7](data-saving.md#7-write-strategy--crash-safety)

Per box, on Start:

1. `IDLE → IN_SESSION` (refused from any other state).
2. Open the port — which itself triggers the Mega's DTR auto-reset.
3. Wait for the board's `READY` line, up to 10 s, then `ERROR`.
4. Send the built `START …` command.
5. Watch 1.5 s for an optional `SEED\t<value>` line; proceed either way.
6. Enter strict strobe parsing: a data line is exactly `^\d{1,3}\t\d+$`, read as `[code, timestamp]`. Anything else goes to scrollback but is never treated as data.
7. Every parsed strobe is appended to that animal's `.tsv` and `flush()`+`fsync()`'d **immediately**, and updates any matching rolling live metric.

**Clean exit:** the board's own end-of-session strobe → finalize → `IN_SESSION → IDLE`. That strobe is found by *name* — the first entry in the profile's `strobes` map containing `END_SESSION` — not by a fixed code.

**Board drop:** always a hard stop into `ERROR` with `stop_reason: "board disconnected"`, cleared by manual `port.error.ack`. No auto-recovery, by design — the write-ahead log already made every strobe durable, so the hard-stop policy costs nothing in data.

**Why `.tsv` is not a third export format.** It is the write-ahead log that makes the durability guarantee real. `.json` and `.mat` are built once, at clean finalization, from the same in-memory buffer, and a failure to write them is logged rather than raised. Per-line `fsync` is affordable because real sessions average well under one event per second.

### 4.3 Task Profiles — [`data-saving.md` §6](data-saving.md#6-task-profiles)

A sketch may ship a `task.json` sibling to its `.ino`. This is what lets the app render a config form and live charts without hardcoding any one task.

- `kind: "behavior"` (the default) declares `config`, `strobes`, and `liveMetrics` — a scored `IN_SESSION` task.
- `kind: "utility"` declares `controls` and `telemetry` instead — a `PASSTHROUGH` tool (priming, self-test) driven from Debug Mode. These ride existing passthrough primitives; nothing new on the wire, nothing persisted.

`kind` is a **convention, not a schema gate** — the parser accepts every field from every profile regardless of kind.

A sketch with no `task.json` is fully supported: bare `START`, and a raw scrolling strobe log instead of charts. **Never special-case a particular sketch (e.g. GRGL) in app code** — drive everything off the profile.

### 4.4 Cohorts — [`cohorts.md`](cohorts.md)

Cohort → Animals → Groups, in SQLite in the app data directory (*not* in the user's `dataDirectory`, which is for browsable session output).

- Cohort names are unique among **active** cohorts; archived ones don't reserve names.
- `boxNumber` is an abstract slot 1–6, validated against that range only — never against which boards happen to be bound right now. Cohorts can be fully configured before any hardware is connected.
- `boxNumber` uniqueness is scoped to the **group**, not the cohort, because groups run consecutively.
- Groups always exist, implicitly if the user never makes one, so grouped and ungrouped cohorts share one code path.
- Archive is the everyday reversible delete; permanent delete is available only *from* the archived view and never touches the data folder on disk.

### 4.5 Arduino Directory — [`arduino-directory.md`](arduino-directory.md)

A configured root folder is the only source of flashable sketches; there is no arbitrary-file fallback. Any top-level folder other than the reserved `libraries/` is a category, categories may nest up to five levels, and a sketch's category is the folder directly containing it.

**A folder is a valid sketch only if it holds a `.ino` matching the folder's own name.** This is arduino-cli's requirement, and it is the single most common reason a sketch silently fails to appear. Folders that fail it are skipped **and reported**, never silently dropped.

Only the **root** `libraries/` is passed to `arduino-cli --libraries`, so every sketch compiles against one predictable collection.

---

## 5. Implementation Status

| Area | Status | Notes |
|---|---|---|
| Per-port state machine | **Done** | Verified against real Mega2560 hardware |
| Passthrough read/send | **Done** | Including the CR/LF/CRLF split-line handling |
| Flashing + DTR reset | **Done** | Sequential; session sequence halts at first failure |
| Board presence polling | **Done** | Out-of-band at 1.5 s, never opens a port |
| Arduino Directory discovery | **Done** | All four states; `--libraries` confirmed against arduino-cli 1.5.1 |
| WebSocket protocol | **Done** | All 34 commands and 12 events implemented and emitted |
| Cohorts (model, UI, Auto-Balance) | **Done** | |
| Settings | **Done** | All seven fields collected; the sidecar consumes six and ignores `reducedMotion` by design |
| Session flow (config → mapping → flash) | **Done** | |
| Mission Control + 3D constellation | **Done** | Zoomed star view currently shows a recent-strobe feed; live-metric sparklines live in the per-box cards |
| `IN_SESSION` runner + file writing | **Done** | `.tsv` write-ahead log, `.json`/`.mat` at finalization |
| Task Profiles (behavior + utility) | **Done** | |
| **Analytics** | **Stub** | `<PlaceholderView>`; also the session-end landing |
| Backup Directory mirroring | **Done** | Session files, live `.tsv`, and `ephymeris.db` with dated snapshots. Not yet exercised against a real network share |
| **Windows packaging** | **Not started** | Sidecar freezing, `arduino-cli` bundling, signing, CI |
| **arduino-cli gRPC daemon** | **Deferred** | Committed migration behind the `BoardTool` seam |
| **Crash recovery utility** | **Not built** | Backfill `.json`/`.mat` from an orphaned `.tsv` |
| Session resumption after restart | **Out of scope** | By decision, not omission |

Full detail and priority: [TODO.md](TODO.md).

---

## 6. Development

### Toolchain

Node.js 20+, Python 3.12+, Rust stable, and `arduino-cli` with the `arduino:avr` core.

> **Environment note (this machine):** `npm` and `cargo` are installed but not on the shell `PATH`. They live at `C:\Program Files\nodejs\npm.cmd` and `%USERPROFILE%\.cargo\bin\cargo.exe`. Either prepend those to `PATH` or invoke them by full path.

### Commands

| From | Command | Purpose |
|---|---|---|
| root | `npm run tauri:dev` | The full app |
| root | `npm run dev` | Vite alone, fixed port 1420 (Tauri expects it) |
| root | `npm run typecheck` | `tsc --noEmit` — the only automated frontend check |
| root | `npm run build` | Typecheck then Vite build |
| `sidecar/` | `pytest` | Full sidecar suite |
| `sidecar/` | `pytest tests/test_protocol_contract.py` | The mirror-drift guard |
| `src-tauri/` | `cargo test` | Handshake parser and shell unit tests |

The Tauri shell expects the sidecar interpreter at `sidecar/.venv`; override with `EPHYMERIS_SIDECAR_PYTHON`.

### Test map

**372 sidecar tests · 2 Rust tests · no frontend test runner.**

| Test file | Tests | Covers |
|---|---:|---|
| `test_protocol_contract.py` | 72 | Mirror drift across doc, `protocol.py`, `protocol.ts` |
| `test_port_states.py` | 35 | Transition table legality |
| `test_port_handler.py` | 30 | Read loop, line splitting, ring buffer, send gating |
| `test_task_profiles.py` | 30 | `task.json` parsing, validation, START building |
| `test_cohort_repository.py` | 30 | CRUD, validation, archive/delete |
| `test_session_repository.py` | 30 | Session/prefix persistence, number suggestion, both date spellings |
| `test_discovery.py` | 26 | Sketch scanning, the four directory states |
| `test_backup.py` | 25 | Mirror layout, copy semantics, db backup and snapshots, explicit sync |
| `test_grouping.py` | 19 | Auto-Balance round-robin |
| `test_data_folder.py` | 18 | Resolution, sanitization, collision suffixing |
| `test_in_session.py` | 13 | `IN_SESSION` entry/exit sequence |
| `test_flash_reset.py` | 12 | Flash and DTR reset paths |
| `test_settings.py` | 9 | Lenient settings parsing |
| `test_writer.py` | 9 | Write-ahead log, exclusive open, finalization |
| `test_session_runner.py` | 8 | Runner orchestration |
| `test_matwriter.py` | 6 | Hand-written MAT v5 output |

`test_writer.py` includes a crash-durability test that kills a child mid-write (`_kill_writer_child.py`) to prove the `.tsv` guarantee holds. It runs on Windows.

`test_backup.py` deliberately tests more than "did the file appear." A mirror that works but blocks session finalization, or one that drops a queued file when the target blinks, would pass a naive check and still be wrong — so isolation and failure-recovery have their own cases.

### Dependency policy

Sidecar runtime dependencies are **deliberately just `pyserial` and `websockets`**. Lab machines are maintained by non-technical users, so install failure modes are a real cost. This is why `.mat` writing is a hand-written serializer rather than `scipy` — a large binary wheel and by far the most likely thing to fail at install time.

Frontend dependencies are less constrained (the 3D stack is `three` + `@react-three/fiber` + `@react-three/drei`) because npm install failures don't happen on the lab machines.

Don't add a sidecar runtime dependency without strong justification.

### Theme constraints

Dark mode only for v1 — no light mode, not even a placeholder toggle. Six palette tokens: **Void, Nebula, Halo, Pulsar, Ion, Starlight**, plus `Static` for muted text and three `status-*` values for state. All of them are declared in one place, `src/styles/index.css`, as a Tailwind v4 `@theme` block — **there is no `tailwind.config.js`.**

**Pulsar is deliberately matte** — no gradients, no glow. That is the explicit guard against scope creep.

Three faces with fixed roles: Space Grotesk for headers only, Inter for UI text, JetBrains Mono for all data, timestamps, and IDs. Motion is spring-physics everywhere except the 3D camera's zoom-to-star move, which is the one deliberate cubic-easing exception.

---

## 7. Known rough edges in the code

Small things that are true today and will confuse a reader who assumes otherwise. None are bugs; all are tracked in [TODO.md](TODO.md) where they need a decision.

- **`MetricChart.tsx` is dead code.** It implements exactly the rolling live-metric chart that `starting-a-session.md` §6.4 describes as deferred — correctly, with its chance line — and nothing imports it. Re-landing that feature is a wiring job.
- **`PlaceholderView` claims three callers, has one.** Its doc comment describes "the three unwired sections" and it exposes a `preview` prop nobody passes. Only Analytics uses it now.
- **`RatPlacementBanner.tsx` is ~780 lines**, by a wide margin the largest file in `src/`. That is not complexity to be refactored away: it is a hand-authored isometric SVG animation — six pose tables across nine choreography phases, an articulated hand, a rat drawn as bezier paths. It contains no data logic at all.
- **The "six-token palette" is seven `@theme` colours** once `Static` is counted, plus three status values. Several code comments say six. The six named in `ephymeris_v1.0.md` §2.2 are the ones that carry the theme's identity; `Static` is a text weight.
- **`.tsv` files are opened in truncating write mode.** The `HHMMSS` in the filename makes collision practically unreachable, so this has never bitten — but it is the durable file.

---

## 8. Glossary

| Term | Meaning |
|---|---|
| **Box** | One of up to six Arduino Mega2560 R3 behavior chambers. Identified by box number 1–6 — the stable key everywhere |
| **Binding** | The `box_number → hardware_id` map in Settings. `hardware_id` is the board's USB serial number, stable across COM renumbering |
| **Strobe** | One event line from the board: `<code>\t<timestamp_ms>`, elapsed since that animal's own session start |
| **Passthrough** | Raw bidirectional serial monitoring. Opaque text, ephemeral, never persisted beyond a 2000-line ring buffer |
| **Task Profile** | A sketch's optional `task.json`, declaring its config fields, strobe names, and live metrics |
| **Prefix** | A global task/paradigm name (e.g. `2O-Bdisc`) used in session folder naming. Shared across all cohorts |
| **Group** | A subset of a cohort's animals that run together. Groups run consecutively, which is why a box number may repeat across them |
| **Session** | One invocation of the session flow, possibly spanning several consecutive group runs |
| **Write-ahead log** | The per-animal `.tsv`, fsync'd per line. The mechanism behind the crash-durability guarantee |
| **Constellation** | The astronomy motif, used in three places with three different link rules: the sidebar status widget (fixed adjacency), the procedural cohort icon (seeded nearest-neighbour), and Mission Control's 3D view (seeded nearest-neighbour, per animal) |

---

[Documentation index](README.md) · [Open items register](TODO.md)

# WebSocket / IPC Message Schema — Full Spec

**Status:** Living document. Covers the message schema between the React frontend and the Python sidecar. **Every v1 command and event below is implemented** (the one exception: `sidecar.error` is defined and mirrored but nothing emits it yet — reserved for failures with no command to attribute them to).
**Companion documents:** `hardware-interaction.md` (the hardware layer these messages drive), `arduino-directory.md` (sketch discovery payloads), `ephymeris_v1.0.md` (tech stack, Settings ownership).
**Not yet covered (future sections):** analytics queries.

This document resolves the "WebSocket/IPC message schema" item listed as TBD in `hardware-interaction.md` §8 and `ephymeris_v1.0.md` §6.

**Source of truth:** this file. `sidecar/ephymeris_sidecar/protocol.py` and `src/lib/ws/protocol.ts` are hand-maintained mirrors of it; `sidecar/tests/test_protocol_contract.py` fails the build if the two mirrors drift apart. There is no codegen step — the surface is small enough that a build step would cost more than it saves.

---

## 1. Transport & Lifecycle

The sidecar is spawned by the Tauri shell, not by the frontend. Startup sequence:

1. Rust spawns the sidecar with piped stdin/stdout/stderr.
2. The sidecar binds `127.0.0.1` on an **ephemeral port** (`port=0`) and generates a random token.
3. It prints exactly one line to **stdout**:
   ```
   EPHYMERIS_WS_PORT=<port> EPHYMERIS_WS_TOKEN=<token>
   ```
   Everything else the sidecar logs goes to **stderr**, keeping stdout a single-purpose channel. Rust forwards stderr into the app log.
4. Rust parses that line, stores the endpoint, and emits the Tauri event `sidecar://ready`. If the sidecar's stdout closes, Rust emits `sidecar://down`.
5. The frontend obtains the endpoint via the `sidecar_endpoint` Tauri command (covering the case where the sidecar was ready before the webview loaded) or via `sidecar://ready`, then opens the WebSocket.

**Why an ephemeral port:** lab PCs are shared and a fixed port is a collision waiting to happen. **Why a token:** the socket is loopback-only, but any local process could otherwise connect to it and drive the hardware.

**Orphan protection.** The shell holds the sidecar's stdin open for the life of the app. The sidecar watches stdin for EOF and exits when it closes. A sidecar that outlived its parent would keep serial ports open and lock out the next launch, so this is load-bearing, not a nicety. The shell additionally kills the child on exit.

**Development fallback (dev builds only).** When no Tauri shell is present (plain-browser preview), the frontend accepts a manually supplied endpoint from `localStorage` under `ephymeris:endpoint` — `{"port": N, "token": "…"}` — so the full UI can be driven against a standalone sidecar started with `--token`/`--no-parent-watch`. Deliberately `localStorage` rather than URL parameters: the token-never-in-a-URL rule (§1.1) has no dev exception. Compiled out of production builds.

### 1.1 Authentication

The server sends `server.hello` immediately on connect. The client's **first** message must be the `auth` command; anything else, a bad token, or silence for more than 5 seconds closes the connection with code `1008`.

The token travels in a message body rather than a URL query string, so it never lands anywhere a URL would be logged.

### 1.2 State replay on connect

Immediately after a successful `auth`, the server replays current state to that
client alone: one `port.state` per box (with `prev` equal to `state` and reason
`"initial state"`), one `boards.presence`, one `sketches.updated`, and one
`cohorts.updated`.

Events are otherwise emitted only when something changes, so a client that
connects during a quiet period would have nothing to render and would have to
guess. Guessing is exactly what §5.2 forbids.

### 1.3 Reconnection

The frontend reconnects with backoff (250ms → 8s, capped). **On every successful authentication — including reconnects — the frontend re-sends `settings.push`.** This is the wire-level implementation of the one-directional Tauri→sidecar settings sync required by `ephymeris_v1.0.md` §4.5.

---

## 2. Envelope

JSON, UTF-8. Client→server is always a command. Server→client is either a correlated reply or an unsolicited event.

```jsonc
// client → server
{ "v": 1, "id": "c7", "cmd": "port.flash", "args": { "box": 1, "sketchPath": "/…/clean_flush" } }

// server → client — reply (exactly one per command)
{ "v": 1, "corr": "c7", "ok": true,  "result": { … } }
{ "v": 1, "corr": "c7", "ok": false, "error": { "code": "SEND_NOT_PASSTHROUGH", "message": "…", "detail": null } }

// server → client — event (unsolicited; `corr` present when caused by a command)
{ "v": 1, "evt": "port.output", "ts": 1721600000.123, "data": { … } }
```

| Field | Meaning |
|---|---|
| `v` | Protocol version. A mismatch is rejected with `PROTOCOL_VERSION_MISMATCH` rather than best-effort parsed |
| `id` | Client-generated correlation id, unique per connection |
| `corr` | Echoes the `id` of the command this message relates to |
| `ts` | Server-side Unix timestamp (float seconds) |

Every command receives exactly one reply. Long-running commands (`port.flash`) additionally emit `flash.progress` events carrying `corr`, so progress can be attributed to the specific request that caused it.

### 2.1 Reply timeouts

The client applies a default 15s reply timeout, overridden per command where the work legitimately runs long:

| Command | Timeout |
|---|---|
| `port.flash` | 300s — a compile plus upload routinely outlasts the default |
| `sketches.refresh` | 60s |
| everything else | 15s |

Timing out client-side does **not** cancel the sidecar's work. The sidecar remains the authority on what actually happened; the resulting `port.state` event is what the UI reflects.

---

## 3. Commands (client → server)

`box` is always a **box number, 1–6** — never a port address. See §5.1.

| Command | Args | Result | Notes |
|---|---|---|---|
| `auth` | `{token}` | `{authenticated: true}` | Must be the first message (§1.1) |
| `ping` | — | `{pong, sidecarVersion}` | Liveness probe for the connection indicator |
| `settings.push` | full settings payload (§4) | `{arduinoDirectory: <DirectoryStatus>}` | Sent on connect and on every change. The reply carries the immediate Arduino Directory validation required by `arduino-directory.md` §2 |
| `sketches.refresh` | — | `<SketchDiscovery>` (§4) | Manual Refresh and Debug Mode mount, per `arduino-directory.md` §4 |
| `port.passthrough.open` | `{box, baud}` | `{state}` | `baud` per box, default 115200 (`hardware-interaction.md` §6.4) |
| `port.passthrough.close` | `{box}` | `{state}` | |
| `port.send` | `{box, text, lineEnding}` | `{bytesWritten}` | `lineEnding` ∈ `none` \| `lf` \| `cr` \| `crlf`, default `lf`. Rejected with `SEND_NOT_PASSTHROUGH` unless the port is in `PASSTHROUGH` (`hardware-interaction.md` §6.3) |
| `port.flash` | `{box, sketchPath, suppressPassthroughResume?}` | `{state, resumedPassthrough: bool}` | Streams `flash.progress`. `resumedPassthrough` reports the §3.3 auto-resume. `suppressPassthroughResume` (default `false`) forces the port to land in `IDLE` afterward regardless of pre-flash state — the session flash sequence needs `IDLE` so the runner can claim the port (`starting-a-session.md` §4) |
| `port.reset` | `{box}` | `{state, resumedPassthrough: bool}` | DTR toggle (`hardware-interaction.md` §5) |
| `port.error.ack` | `{box}` | `{state}` | `ERROR` → `IDLE` (`hardware-interaction.md` §3.2) |

### 3.1 Cohorts

Merged from `cohorts.md` §10, which proposed these; this document is canonical.
All cohort state lives in the sidecar's SQLite database (`cohorts.md` §3).

| Command | Args | Result | Notes |
|---|---|---|---|
| `cohorts.list` | — | `{cohorts: [CohortSummary]}` | Includes archived; the client filters (`cohorts.md` §4) |
| `cohorts.get` | `{id}` | `{cohort: <Cohort>}` | Full detail, fetched when a card is opened |
| `cohorts.create` | `{name, dataFolder?}` | `{cohort: <Cohort>}` | `dataFolder` resolved per `cohorts.md` §8 when omitted; an implicit default group is always created (§2) |
| `cohorts.update` | `{id, patch}` | `{cohort: <Cohort>}` | `patch` may carry `name`, `animals`, `groups`. Also the commit path for an Auto-Balance preview (§7.4) — no separate apply command |
| `cohorts.archive` | `{id}` | `{cohort: <Cohort>}` | Soft-delete; record and `dataFolder` stay intact (§9) |
| `cohorts.restore` | `{id}` | `{cohort: <Cohort>}` | Rejected with `COHORT_NAME_TAKEN` if an active cohort has since claimed the name |
| `cohorts.delete` | `{id, confirm: true}` | `{deleted: true}` | Rejected with `COHORT_NOT_ARCHIVED` unless already archived. **Never touches `dataFolder` on disk** (§9) |
| `cohorts.setDataFolder` | `{id, path, moveExisting}` | `{cohort: <Cohort>}` | The explicit relocate of §8 — distinct from renaming. Refuses with `DATA_FOLDER_INVALID` rather than overwriting a non-empty destination |
| `cohorts.suggestGroups` | `{id, groupCount?, maxGroupSize?, balanceBySex?}` | `<GroupProposal>` | **Non-mutating.** Computes §7.3's balanced round-robin for preview; the user applies via `cohorts.update` |

### 3.2 Sessions & Prefixes

Merged from `data-saving.md` §9 and `starting-a-session.md` §9; this document is
canonical. Prefixes and session records live in the same SQLite database as
cohorts. The actual per-strobe file writing happens sidecar-side and is not a
command — see `data-saving.md` §7.

| Command | Args | Result | Notes |
|---|---|---|---|
| `prefixes.list` | — | `{prefixes: [Prefix]}` | Global, shared across all cohorts (`data-saving.md` §3) |
| `prefixes.create` | `{name}` | `{prefix: <Prefix>}` | Name-unique; rejected with `PREFIX_NAME_TAKEN` |
| `prefixes.delete` | `{id}` | `{deleted: true}` | Non-destructive — never touches folders already written under the name (`data-saving.md` §3) |
| `tasks.getProfile` | `{sketchPath}` | `<TaskProfile>` \| `{profile: null}` | Reads the `task.json` sibling to the sketch's `.ino` (`data-saving.md` §6.1). A sketch with none returns `{profile: null}` — fully supported |
| `sessions.suggestNumber` | `{prefixId}` | `{suggestion, sameDayNumbers: [string]}` | Step 1's pre-fill (`starting-a-session.md` §2.2). `suggestion` is the highest numeric session number for the prefix +1, or `null` where there's no numeric history. `sameDayNumbers` are the numbers already used for this prefix *today*, driving the **soft** reuse warning — reuse is legal, never blocked. Aborted sessions count toward neither: they never wrote data, so their numbers stay claimable |
| `sessions.create` | `{cohortId, prefixId, sessionNumber}` | `{session: <Session>}` | Status `configuring`. Rejected with `SESSION_NOT_READY` if the cohort has no group with a box-assigned animal (`starting-a-session.md` §1) |
| `sessions.abandon` | `{sessionId}` | `{session: <Session>}` | Discards a session still in `configuring` — Step 2's Back button (`starting-a-session.md` §3). Marks it `aborted` and clears any confirmed-but-unstarted mapping from the runner. Rejected with `SESSION_INVALID` once a group has started running; abandoned sessions never wrote data, so nothing on disk is touched |
| `sessions.confirmMapping` | `{sessionId, groupId, boxes: [{box, animalId, sketchPath, config}]}` | `{ok: true}` | Session-local mapping + per-box Task Profile config; feeds §4's flash sequence. `config` is a `{metadataKey: value}` map |
| `sessions.status` | `{sessionId}` | `{session: <Session>, groupId, boxes: [{box, animalId, animalName, sketchName, sketchPath, running}]}` | What Mission Control renders (`starting-a-session.md` §5). The runner is the authority on the confirmed mapping and which boxes are live, so reopening the window mid-session shows the truth rather than a stale client copy |
| `sessions.startAll` | `{sessionId}` | `{session: <Session>}` | Enters `IN_SESSION` on every box in the current group not already running (`starting-a-session.md` §5.2) |
| `sessions.switchGroup` | `{sessionId}` | `{nextGroupId}` | Ends current runs, advances to the next populated group by `order`; the client re-enters Step 2 |
| `sessions.end` | `{sessionId}` | `{session: <Session>}` | Gracefully stops all boxes, finalizes files, marks `completed` |
| `port.startSession` | `{box, startCommand}` | `{state}` | Per-box `IN_SESSION` entry: open → DTR reset → await `READY` → send `startCommand` → optional `SEED` (`starting-a-session.md` §7) |
| `port.stopSession` | `{box}` | `{state}` | Sends the literal `STOP` line. Does **not** force the transition — the board's own end-of-session strobe does (`starting-a-session.md` §5.3) |

---

## 4. Events (server → client)

| Event | `data` | Notes |
|---|---|---|
| `server.hello` | `{protocolVersion, sidecarVersion}` | First frame on every connection |
| `port.state` | `{box, state, prev, reason}` | Emitted on **every** transition. `state`/`prev` are the `hardware-interaction.md` §3.1 names |
| `port.output` | `{box, lines: [{dir, text, ts}]}` | `dir` ∈ `rx` \| `tx`. **Batched** — see §5.2 |
| `boards.presence` | `{boards: [{hardwareId, address, fqbn, boxId}]}` | The out-of-band poll (`hardware-interaction.md` §7). `boxId` is `null` for an unassigned board |
| `flash.progress` | `{box, phase, stream, text}` | `phase` ∈ `compile` \| `upload`; `stream` ∈ `stdout` \| `stderr`. Carries `corr` |
| `sketches.updated` | `<SketchDiscovery>` | Pushed whenever discovery re-runs for any reason |
| `cohorts.updated` | `{cohorts: [CohortSummary]}` | Pushed whenever the cohort list changes — same push-on-change pattern as `sketches.updated`, keeping the browser grid and the dashboard tile in sync without polling |
| `prefixes.updated` | `{prefixes: [Prefix]}` | Push-on-change for the prefix list, same pattern as `cohorts.updated` |
| `session.telemetry` | `{box, animalId, metrics: [<TelemetryMetric>]}` | Pushed on every strobe that updates a rolling live metric (`starting-a-session.md` §7 step 7) — **not** batched at `port.output`'s 20Hz, since metric updates are far lower-frequency than raw strobes |
| `session.animalEnded` | `{box, animalId, stopReason, filePath}` | One animal's run finalized (`starting-a-session.md` §8's `stopReason` set) |
| `sidecar.error` | `{code, message, detail}` | Failures with no command to attribute them to — includes a `.tsv` write failure mid-session (`data-saving.md` §7.1) |

### Shared payload shapes

```jsonc
// DirectoryStatus — the four states of arduino-directory.md §6
{
  "state": "not_configured" | "invalid" | "empty" | "ok",
  "path": "/Users/…/ArduinoDirectory" | null,
  "message": "Can't find your configured Arduino Directory"   // present when state != "ok"
}

// SketchDiscovery
{
  "directory": <DirectoryStatus>,
  "sketches": [ { "category": "utility", "name": "clean_flush", "path": "/…/utility/clean_flush" } ],
  "skipped":  [ { "path": "/…/utility/broken", "reason": "no .ino matching folder name" } ],
  "skippedCount": 1,          // drives the "Partial" note in arduino-directory.md §6
  "libraries": [ "EphymerisStrobe" ],
  "librariesPath": "/…/libraries" | null
}
```

`skipped` is carried in full rather than as a bare count so the reason a sketch is missing is inspectable, per `arduino-directory.md` §4 step 4 ("skipped but reported, not silently dropped").

### Cohort payload shapes

Mirrors the `cohorts.md` §1 data model. Timestamps are ISO-8601 strings.

```jsonc
// CohortSummary — enough for the grid and the dashboard tile, no animal detail
{
  "id": "9f2c…", "name": "Batch A",
  "animalCount": 6, "groupCount": 2,
  "archived": false,
  "createdAt": "2026-07-23T…", "updatedAt": "2026-07-23T…"
}

// Cohort — the full record, fetched only when a card is opened
{
  "id": "9f2c…", "name": "Batch A",
  "dataFolder": "/Users/…/Behavior/Batch A",   // resolved once at creation (§8)
  "animals": [ <Animal> ],
  "groups":  [ <Group> ],                       // always ≥ 1 (§2)
  "archivedAt": null,
  "createdAt": "…", "updatedAt": "…"
}

// Animal
{
  "id": "…", "name": "R-14",
  "groupId": "…",                               // exactly one group
  "boxNumber": 3 | null,                        // abstract slot 1–6, NOT a live port
  "sex": "M" | "F" | "unknown" | null,
  "idNumber": "0421" | null,
  "notes": "…" | null
}

// Group
{ "id": "…", "name": "Group 1", "order": 0 }

// GroupProposal — cohorts.suggestGroups; a preview, nothing is written
{
  "groups": [ { "name": "Group 1", "order": 0,
                "animals": [ { "animalId": "…", "boxNumber": 1 } ] } ],
  "rejected": null                              // or { reason, minimumGroups } — see below
}
```

The icon is **not** in any payload: it is derived client-side from `id`
(`cohorts.md` §5), so nothing about it is stored or transmitted.

`cohorts.suggestGroups` returns `rejected` rather than erroring when the request
would violate §7.2's six-animals-per-group hard constraint — the tool is meant to
answer with the minimum viable group count (`ceil(animalCount / 6)`) so the user
can accept it, which is guidance rather than a failure.

### Session & prefix payload shapes

Mirrors `data-saving.md` §3–§6 and `starting-a-session.md` §9. Timestamps are
ISO-8601 strings.

```jsonc
// Prefix — global, names a task/paradigm (data-saving.md §3)
{ "id": "…", "name": "2O-Bdisc" }

// TaskProfile — parsed from the sketch's task.json sibling (data-saving.md §6).
// Passed through verbatim; the sidecar validates shape but doesn't reinterpret.
// `kind` selects which fields apply: "behavior" (default) uses config/strobes/
// liveMetrics; "utility" uses controls/telemetry (§6.6). Utility control + status
// reuse the existing port.send / port.output primitives — no new wire commands.
{
  "taskName": "GRGL 2-Odor Discrimination",
  "kind": "behavior" | "utility",         // default "behavior" when omitted
  "config": [
    { "metadataKey": "correction_left", "wireKey": "CL", "label": "…",
      "type": "int" | "bool" | "float" | "string", "default": 0 }
  ],
  "strobes": { "101": "ODOR_1_ON", "246": "END_SESSION" },   // code → name, display/debug
  "liveMetrics": [
    { "id": "p_r_odor1", "label": "P(R | Odor 1)",
      "triggerCode": 101, "successCode": 249, "alternateCode": 248, "windowSize": 20 }
  ],
  // utility only — Debug-Mode controls + how to parse non-persisted STATUS lines:
  "controls": [
    { "id": "gear", "label": "Fluid set", "type": "select",
      "options": [ { "label": "Set 1", "command": "SET GEAR=1" } ] },
    { "id": "alloff", "label": "All off", "type": "button", "command": "ALLOFF" }
  ],
  "telemetry": { "match": "STATUS", "fields": [ { "key": "gear", "label": "Fluid set" } ] }
}

// Session (data-saving.md §4)
{
  "id": "…", "cohortId": "…", "prefixId": "…",
  "sessionNumber": "25",            // free text, not strictly numeric (§10)
  "date": "2026-07-22",
  "startedAt": "…", "endedAt": null,
  "status": "configuring" | "running" | "completed" | "aborted",
  "folderPath": "/…/2O-Bdisc/2O-Bdisc_25_07_22_26",
  "groupRuns": [ { "groupId": "…", "order": 0, "startedAt": "…", "endedAt": null } ]
}

// SessionAnimalRun (data-saving.md §4) — written at finalization
{
  "id": "…", "sessionId": "…", "animalId": "…",
  "boxNumber": 3, "sketchPath": "/…/GRGL_2-Odor",
  "filePath": "/…/behavior.json/remy1_….json",
  "startedAt": "…", "endedAt": "…",
  "stopReason": "BF_END_SESSION received"   // starting-a-session.md §8
}

// TelemetryMetric — one rolling live-metric value (session.telemetry)
{ "id": "p_r_odor1", "value": 0.85, "n": 20 }   // value = P(hit); n = counted trials in window
```

### `settings.push` payload

The payload mirrors the Tauri-side store, which is the source of truth (`ephymeris_v1.0.md` §4.5). The full settings schema is still an open item there, so this document does **not** restate it as fixed — the sidecar reads the keys it needs (`arduinoDirectory`, `arduinoCliPath`, `defaultBaud`, `boxBindings`, `dataDirectory`) and ignores the rest. Adding a setting the sidecar doesn't consume is deliberately a non-event.

---

## 5. Invariants

### 5.1 `box` is the key, never a port address

Every per-port message is keyed by box number 1–6. The sidecar resolves box → `hardware_id` → current port address through the binding map supplied in settings. Windows renumbers COM ports across reboots and re-enumeration; if the wire protocol were keyed by address, a renumber would silently re-point a box at the wrong physical board. Consequences:

- A box with no bound board still exists in the protocol and reports `IDLE` with no presence.
- Commands against an unbound box are rejected with `PORT_NOT_BOUND`.
- `boards.presence` reports boards the app has *seen*, including unassigned ones (`boxId: null`), so Settings can offer them for assignment.

### 5.2 The sidecar is authoritative on state

The frontend never sets port state optimistically. It renders exactly what `port.state` reports, and an illegal operation is rejected server-side with a typed error code. This is the wire-level expression of `hardware-interaction.md` §3.3: *"never trust the frontend to prevent an illegal transition."* Disabled buttons in the UI are a courtesy, not the enforcement mechanism.

### 5.3 Output is batched, not per-line

`port.output` carries an array of lines accumulated over a fixed ~50ms tick (20Hz), not one message per line, per `hardware-interaction.md` §6.2. Six chatty boxes at one message per line would flood the UI. Sent commands are interleaved into the same stream with `dir: "tx"` so scrollback stays chronological (§6.3).

### 5.4 Passthrough data never enters storage

Nothing in `port.output` is persisted by the sidecar beyond the capped in-memory ring buffer (~2000 lines/port). Export is a manual, user-initiated action outside the formal data pipeline (`hardware-interaction.md` §6.5).

---

## 6. Error Codes

| Code | Meaning |
|---|---|
| `BAD_MESSAGE` | Malformed JSON or non-object frame |
| `UNKNOWN_COMMAND` | Unrecognized `cmd` |
| `UNAUTHORIZED` | Missing/invalid token, or a non-`auth` first message |
| `PROTOCOL_VERSION_MISMATCH` | `v` does not match the sidecar's protocol version |
| `ILLEGAL_TRANSITION` | Operation not permitted from the port's current state |
| `SEND_NOT_PASSTHROUGH` | `port.send` attempted while not in `PASSTHROUGH` |
| `PORT_NOT_BOUND` | No board bound to that box number |
| `PORT_OPEN_FAILED` | Serial open failed (absent, busy, permissions) |
| `FLASH_FAILED` | Compile or upload failed; `detail` carries parsed `arduino-cli` output |
| `SKETCH_UNKNOWN` | `port.flash` named a path that isn't in the current discovery result — the configured Arduino Directory is the only source of flashable sketches (`arduino-directory.md` §5), and that is enforced here, not just in the picker UI |
| `COHORT_NOT_FOUND` | No cohort with that id |
| `COHORT_NAME_TAKEN` | Name already used by an **active** cohort. Archived cohorts don't reserve names (`cohorts.md` §2), so this can also reject a `cohorts.restore` whose name was claimed while it was away |
| `COHORT_INVALID` | A `cohorts.md` §2 validation failure. `detail` carries per-field errors so the editor can surface them inline rather than as a toast (§6) |
| `COHORT_NOT_ARCHIVED` | `cohorts.delete` on a cohort that hasn't been archived first — the deliberate two-step guard of §9 |
| `DATA_FOLDER_INVALID` | A data folder couldn't be created, or a `cohorts.setDataFolder` destination isn't empty. Refuses rather than overwriting (§8) |
| `PREFIX_NAME_TAKEN` | A prefix with that name already exists (`data-saving.md` §3) |
| `SESSION_INVALID` | Malformed session command — unknown cohort/prefix/group, or a mapping referencing a box/animal that doesn't belong to the session |
| `SESSION_NOT_READY` | `sessions.create` against a cohort with no group holding a box-assigned animal (`starting-a-session.md` §1) |
| `TASK_PROFILE_INVALID` | A sketch's `task.json` exists but is malformed. `detail` carries the parse error; the sketch is otherwise treated as profile-less |
| `DIR_INVALID` | Arduino Directory missing, not a directory, or unreadable |
| `INTERNAL` | Unhandled sidecar exception |

---

## 7. Versioning

`PROTOCOL_VERSION` is a single integer bumped on any breaking change. Shell and sidecar ship together, so negotiation is unnecessary — a mismatch means a stale build and is surfaced as an error rather than worked around.

---

## 8. Resolved Decisions

| Decision | Outcome |
|---|---|
| Transport | Local WebSocket, JSON, loopback-only |
| Port selection | **Ephemeral**, handed to the shell over stdout — no fixed port to collide on shared lab PCs |
| Auth | Random per-launch token, sent as the first message body (never in a URL) |
| Message pattern | Correlated request/reply **plus** unsolicited server events — not a pure event stream |
| Per-port key | **Box number 1–6**, resolved to a port address inside the sidecar (§5.1) |
| Schema sharing | Hand-maintained mirrors + a contract test, no codegen |
| Orphan protection | Sidecar exits on stdin EOF; shell also kills the child on exit |
| Crashed sidecar | **No auto-respawn.** `sidecar://down` is surfaced and the app must be restarted. A silent respawn mid-session would resurrect the process without the port ownership or session state it had, which is worse than an honest failure the user can see |

---

## 9. Open Items / TBD

- [x] ~~Session-runner messages: `IN_SESSION` start/stop/abort, and the strobe-parsed data stream shape~~ — merged into §3.2/§4 from `data-saving.md` §9 and `starting-a-session.md` §9
- [x] ~~Whether a crashed sidecar should be auto-respawned by the shell~~ — resolved: **no auto-respawn** (§8)
- [x] ~~Storage/export message shapes (`.json`/`.mat`/`.tsv`)~~ — the write path is sidecar-side, not a wire message (`data-saving.md` §7); telemetry and finalization are `session.telemetry`/`session.animalEnded` (§4)
- [ ] Analytics query messages
- [ ] Multi-port batching (e.g. "flash all 6") — shared with `hardware-interaction.md` §8; whether that is one command with six progress streams or six independent commands
- [ ] Back-pressure policy if the frontend cannot keep up with `port.output` at 20Hz × 6 boxes (currently: unbounded send, relying on the ring buffer cap)

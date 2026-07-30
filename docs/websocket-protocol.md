# WebSocket / IPC Message Schema

> **Status** · Living spec — **Built.** Every command and event below is implemented and emitted. The surface is **38 commands, 13 events, 22 error codes**.
>
> **Owns** · The complete wire schema between the React frontend and the Python sidecar. This document is **canonical** — where any other spec describes a message differently, this one wins.
>
> **Read with** · [hardware-interaction.md](hardware-interaction.md) (the hardware layer these messages drive) · [arduino-directory.md](arduino-directory.md) (sketch discovery payloads) · [ephymeris_v1.0.md](ephymeris_v1.0.md) (Settings ownership)
>
> **Still open** · Debug Mode batch flash · `port.output` back-pressure policy

**Contents** — [1. Transport & Lifecycle](#1-transport--lifecycle) · [2. Envelope](#2-envelope) · [3. Commands](#3-commands-client--server) · [4. Events](#4-events-server--client) · [5. Invariants](#5-invariants) · [6. Error Codes](#6-error-codes) · [7. Versioning](#7-versioning) · [8. Resolved Decisions](#8-resolved-decisions) · [9. Open Items](#9-open-items--tbd)

This document resolves the "WebSocket/IPC message schema" item listed as TBD in `hardware-interaction.md` §9 and `ephymeris_v1.0.md` §6.

> **Changing the wire — the required order.** This document is the **prose** authority (rationale, lifecycle, invariants); `protocol/schema.py` at the repo root is the **shape** authority. `sidecar/ephymeris_sidecar/protocol.py` and `src/lib/ws/protocol.ts` are **generated** from the schema — never edit them by hand:
>
> 1. Update `protocol/schema.py` **and this document** together.
> 2. Run `npm run gen:protocol` (or `python protocol/generate.py`) and commit the regenerated mirrors. `npm run build` and `npm run dev` regenerate automatically.
> 3. Run `pytest tests/test_protocol_contract.py` — it regenerates in a subprocess and fails if a committed mirror is stale or hand-edited, and still requires every wire name to appear in this document.
>
> Because both mirrors come from one schema, they cannot drift from each other — including **payload shapes**, which the old hand-maintained mirrors never guarded. On the TypeScript side the generated `CommandArgsMap`/`CommandResultMap`/`EventDataMap` make `client.call` fully typed, so a frontend use of a stale shape fails `npm run typecheck`. On the Python side the generated specs power a runtime validator: with `EPHYMERIS_WIRE_VALIDATE=1` (the test suite sets it; production leaves it off) every `event()` payload and every dispatched reply is checked against the schema, and `tests/test_wire_shapes.py` pins the real emitters to it. What remains unverified is only that a command *has* a handler.

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

Immediately after a successful `auth`, the server replays current state **to that client alone** (unicast, not a broadcast), in this order:

1. One `port.state` per box — with `prev` deliberately equal to `state`, and reason `"initial state"`.
2. One `boards.presence`.
3. One `sketches.updated`.
4. One `cohorts.updated`.
5. One `prefixes.updated`.

Events are otherwise emitted only when something changes, so a client connecting during a quiet period would have nothing to render and would have to guess. Guessing is exactly what §5.2 forbids.

> **Live session state is *not* replayed.** No runner snapshot, no `groupId`, no in-flight telemetry. A client that reconnects mid-session gets correct port, board, and cohort state, then must **ask**: `sessions.active` for global discovery (which session is running, with no prior knowledge of ids — what the Launch page and a fresh window need), or `sessions.status` for a session it already knows. This is deliberate — the runner is the authority on the confirmed mapping, and asking it beats replaying a snapshot that could already be stale by the time it arrives. After that first ask, `session.lifecycle` broadcasts keep the answer current without polling.

A replay callback that raises is logged and swallowed rather than dropping the connection.

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

Of the 43 commands, 42 are registered in the sidecar's dispatch table. **`auth` is the exception:** it is consumed by the server's authentication step before dispatch begins and never reaches a handler, because it must be the connection's literal first frame (§1.1).

| Command | Args | Result | Notes |
|---|---|---|---|
| `auth` | `{token}` | `{authenticated: true}` | Must be the first message (§1.1) |
| `ping` | — | `{pong, sidecarVersion}` | Liveness probe for the connection indicator |
| `settings.push` | full settings payload (§4) | `{arduinoDirectory: <DirectoryStatus>}` | Sent on connect and on every change. The reply carries the immediate Arduino Directory validation required by `arduino-directory.md` §2 |
| `sketches.refresh` | — | `<SketchDiscovery>` (§4) | Manual Refresh and Debug Mode mount, per `arduino-directory.md` §4 |
| `port.passthrough.open` | `{box, baud}` | `{state}` | `baud` per box; omitted means the configured `defaultBaud`, which ships as 9600 (`hardware-interaction.md` §6.4) |
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
| `cohorts.create` | `{name, dataFolder?, animals?, groups?}` | `{cohort: <Cohort>}` | `dataFolder` resolved per `cohorts.md` §8 when omitted. **The roster may travel with the create**, which is what makes the editor's Create a single call: animals and groups are built client-side with their own ids before the cohort exists, and sending them afterwards meant a second command that could fail on its own and leave a named, empty cohort. Both are validated *before* any row is written, so a rejected roster leaves no cohort and no folder. Omitting `groups` still mints the implicit default group (§2) |
| `cohorts.update` | `{id, patch}` | `{cohort: <Cohort>}` | `patch` may carry `name`, `animals`, `groups`. Also the commit path for an Auto-Balance preview (§7.4) — no separate apply command |
| `cohorts.archive` | `{id}` | `{cohort: <Cohort>}` | Soft-delete; record and `dataFolder` stay intact (§9) |
| `cohorts.restore` | `{id}` | `{cohort: <Cohort>}` | Rejected with `COHORT_NAME_TAKEN` if an active cohort has since claimed the name |
| `cohorts.delete` | `{id, confirm: true}` | `{deleted: true}` | Rejected with `COHORT_NOT_ARCHIVED` unless already archived. **Never touches `dataFolder` on disk** (§9) |
| `cohorts.setDataFolder` | `{id, path, moveExisting}` | `{cohort: <Cohort>}` | The explicit relocate of `cohorts.md` §8 — distinct from renaming. **`moveExisting` selects between two intents:** `true` moves the cohort's data and refuses with `DATA_FOLDER_INVALID` if the destination isn't empty; `false` writes nothing and simply re-points the cohort, so a full destination is expected — that is how a cohort attaches to a pre-existing archive |
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
| `sessions.create` | `{cohortId, prefixId, sessionNumber, durationMinutes?}` | `{session: <Session>}` | Status `configuring`. Rejected with `SESSION_NOT_READY` if the cohort has no group with a box-assigned animal (`starting-a-session.md` §1). `durationMinutes` is the optional per-box time limit (`starting-a-session.md` §2.4): the sidecar sends `STOP` to each box that long after *that box's* start — measured per box, not from Start All, because boxes are started individually. `STOP` remains a request the firmware honours at a trial boundary, so the recorded `stop_reason` is still the board's own clean end |
| `sessions.abandon` | `{sessionId}` | `{session: <Session>}` | Discards a session still in `configuring` — Step 2's Back button (`starting-a-session.md` §3). Marks it `aborted` and clears any confirmed-but-unstarted mapping from the runner. Rejected with `SESSION_INVALID` once a group has started running; abandoned sessions never wrote data, so nothing on disk is touched |
| `sessions.confirmMapping` | `{sessionId, groupId, boxes: [{box, animalId, sketchPath, config}]}` | `{ok: true}` | Session-local mapping + per-box Task Profile config; feeds §4's flash sequence. `config` is a `{metadataKey: value}` map |
| `sessions.status` | `{sessionId}` | `{session: <Session>, groupId, boxes: [{box, animalId, animalName, sketchName, sketchPath, running, startedAt}]}` | What Mission Control renders (`starting-a-session.md` §5). The runner is the authority on the confirmed mapping and which boxes are live, so reopening the window mid-session shows the truth rather than a stale client copy. `startedAt` (null unless running) is what lets a reloaded window resume its per-box elapsed clocks |
| `sessions.startAll` | `{sessionId}` | `{session: <Session>}` | Enters `IN_SESSION` on every box in the current group not already running (`starting-a-session.md` §5.2) |
| `sessions.switchGroup` | `{sessionId}` | `{nextGroupId}` | Ends current runs, advances to the next populated group by `order`; the client re-enters Step 2. A `null` `nextGroupId` means every populated group has run — the sidecar then finalizes exactly as `sessions.end` would (marks `completed`, releases the runner), so the client never has to follow up with a second command |
| `sessions.end` | `{sessionId}` | `{session: <Session>}` | Gracefully stops all boxes, finalizes files, marks `completed` |
| `sessions.active` | — | `<ActiveSessions>` | The global "what is running?" query — deliberately argument-free, so a client with no prior knowledge of ids (the Launch page, a reconnecting window) can discover the running session. The `running` slot is keyed off the **live runner**, never a bare DB status query: a `running` row with no live runner is a crash orphan and lands in `stale` instead, surfaced for honesty but never offered for resume (session resumption after a restart is out of scope by decision). `configuring` rows are setups never finished — legitimately resumable into Step 2 |
| `port.startSession` | `{box, startCommand}` | `{state}` | Per-box `IN_SESSION` entry: open → DTR reset → await `READY` → send `startCommand` → optional `SEED` (`starting-a-session.md` §7) |
| `port.stopSession` | `{box}` | `{state}` | Sends the literal `STOP` line. Does **not** force the transition — the board's own end-of-session strobe does (`starting-a-session.md` §5.3) |

### 3.3 Backup

Mirroring itself takes no commands — it runs off `Settings.backupDirectory`, pushed with everything else via `settings.push` (`data-saving.md` §8). The one command here is the deliberate backfill.

| Command | Args | Result | Notes |
|---|---|---|---|
| `backup.syncNow` | — | `{copied, skipped, failed, errors: [string], directory}` | Walks every cohort data folder and mirrors anything missing or stale, then backs up `ephymeris.db`. Setting a backup directory deliberately does **not** backfill on its own — that could mean an unannounced multi-gigabyte copy to a network share the moment a folder is picked — so this is the explicit version, and doubles as the way to prove a target works before trusting it. Rejected with `BACKUP_UNAVAILABLE` when no directory is set or a sync is already running. Long-running: the client should raise its reply timeout for this command |

### 3.4 Analytics

Designed in [analytics.md](analytics.md) §9, which carries the rationale. Implemented and in both mirrors.

| Command | Args | Result | Notes |
|---|---|---|---|
| `sessions.list` | `{cohortId, includeAborted?}` | `{sessions: [SessionListItem]}` | Belongs to the `sessions.*` family rather than `analytics.*` because session history is independently useful. **Must never touch the filesystem**, so selectors populate instantly. Returns a chronological `ordinal` derived from `(date, startedAt)` — never from `sessionNumber`, which is free text. `SessionListItem` is the trimmed listing form of `Session` (no `prefixId`/`groupRuns`, plus `ordinal` and `runCount`) and is the same shape `analytics.summary` embeds — one emitter serves both |
| `analytics.summary` | `{cohortId, sessionIds?, animalIds?, minCountedTrials?}` | cohort table — sessions, animals, run summaries, profile groups, counts, warnings | One call per cohort; every session and animal selection filters it client-side. The heatmap and the strategy space are the same data, so they share one command. Run summaries are a **flat list, not a matrix** — a matrix has nowhere to put two runs for one animal and session, which really happens |
| `analytics.series` | `{runIds: [], mode?, metricIds?}` | `{series: [RunSeries], warnings}` | Learning-curve data. **Plural** so "all six animals in this session" is one call; the list is capped server-side. The x-axis is the counted-trial index and is implicit. Each `RunSeries` also carries `trail` — the within-session walk through the strategy plane (`analytics.md` §4.4) as `[StrategyPoint]`. It rides here rather than in its own command because the file is already open and decoded, and it is **always rolling** whatever `mode` says. Empty unless the profile declares exactly two conditions, and **not** derivable client-side from `metrics`: those are indexed by each metric's own counted trials, which interleave |
| `analytics.rescan` | `{cohortId, adoptOrphans?}` | `{scanned, adopted, orphans: [RescanOrphan], cohortId}` | The explicit archive walk, for files no run record points at. Same pattern as `sketches.refresh` and `backup.syncNow`: expensive reconciliation is a deliberate user action, never a side effect of opening a view |
| `analytics.recentSessions` | `{limit?}` | `{sessions: [DiskSession]}` | The N most recent session folders across every active cohort's archive, ordered by folder-name date. **Directory names only — no file is ever opened**, which is what keeps this cheap enough for the Dashboard where the rescan deliberately is not. Each `DiskSession` carries the identity a folder name alone can assert (`sessions/paths.py`'s parsers, both date spellings): cohort, prefix, session number, ISO date, path, and `recorded` — whether this machine's database holds a session row for that folder. `recorded: false` is the point of the command: a session another Ephymeris machine wrote into the shared archive is real history and belongs on the landing page, but it has no run record here until a rescan adopts it |
| `sessions.recover` | `{cohortId}` | `{scanned, recovered, failed, entries: [RecoveredTsv], cohortId, dataFolder, folderMissing}` (`RecoverResult`) | The crash-recovery backfill (`data-saving.md` §7.3, §11): rebuilds `.json`/`.mat` from orphaned write-ahead `.tsv` files — same traversal as the rescan's walk, same explicit-action discipline. Each `RecoveredTsv` entry is `{tsvPath, jsonPath, status, nEvents, stopReason, reason}`; a footer-carrying `.tsv` keeps its recorded `stop_reason`, a footer-less (crashed) one gets `"recovered after crash"`. Rejected with `SESSION_INVALID` while any box is running — a live run's `.tsv` has no `.json` yet and is not an orphan |

A corrupt or missing file is **data, not an error** — it yields a run with a non-ok status plus a warning, and the command still succeeds. One unreadable `.json` must never blank a year of history.

Each `RescanOrphan` reports one file the walk found and what could honestly be said about it. `animalName` is always the name the *document* carries, reported as written even when that is what failed to match; `animalSource` says which recording `animalId` was resolved from. `document` is the normal case. `filename` means the document's `rat` matched no animal on the roster and the file stem did — the per-animal naming rule (`data-saving.md` §2) gives a second independent recording of the same fact, and matching it exactly is not the same act as guessing from a resemblance. Null `animalSource` means the run is kept unattributed, which stays the outcome whenever neither recording matches.

### 3.5 Hardware utility baseline

Designed in [hardware-interaction.md](hardware-interaction.md) §8, which carries the rationale. The baseline is the state the app returns every idle box to: the configured utility sketch, flashed and left in `IDLE`, so any box that isn't doing something else is a box Ephymeris can talk to. Restores are automatic — on startup, when a board appears, and whenever a run or session ends — so these commands exist for the two moments the automatic path can't cover: a client that wants the picture, and the placement walk that needs a specific box lit *now*.

| Command | Args | Result | Notes |
|---|---|---|---|
| `utility.status` | — | `<UtilityStatus>` | The same snapshot `utility.updated` pushes, for a client that just mounted |
| `utility.ensure` | `{boxes?, force?}` | `<UtilityStatus>` | Restore the baseline now instead of waiting for the next board or session event. **Returns as soon as the work is scheduled** — flashing six boxes outlasts any sane reply timeout, so progress arrives on `utility.updated`. Never touches a box that isn't `IDLE`, and never one held by a confirmed session mapping. `force` reflashes a box already believed to be at baseline (the Config button; no automatic path sets it) |
| `utility.identify` | `{box, on}` | `{delivered, state: <UtilityBoxState>}` | Make one box point at itself with its profile's `identify` pair (`starting-a-session.md` §3.5). Opens `PASSTHROUGH` if the box is `IDLE` and closes it again on the matching `off`; a box the *user* already has open in Debug Mode keeps its console. `delivered: false` is the ordinary answer for a box not at baseline — the placement walk carries on by number rather than failing |

Rejected with `UTILITY_UNAVAILABLE` when no utility sketch is configured or the configured one can't be used at all. A box-level problem is **not** an error: it is a `state` on that box in the returned snapshot.

```jsonc
// UtilityStatus — the utility.status/utility.ensure result AND the
// utility.updated payload. One shape, one emitter.
{
  "configured": true,
  "sketchPath": "/…/Utility/BOX_Utility",
  "sketchName": "BOX_Utility",
  "canIdentify": true,        // the profile declares an `identify` pair
  "held": false,              // a confirmed session mapping owns the rig
  "message": null,            // why the baseline isn't operating at all
  "boxes": [
    { "box": 1, "state": "ready", "detail": null, "identifying": false },
    { "box": 2, "state": "restoring", "detail": "flashing BOX_Utility", "identifying": false },
    { "box": 3, "state": "busy", "detail": "port is PASSTHROUGH", "identifying": false },
    { "box": 4, "state": "unavailable", "detail": "no board bound to box 4", "identifying": false }
  ]
}
```

`state` ∈ `unknown` | `restoring` | `ready` | `busy` | `held` | `unavailable` | `failed`. Only `failed` is a fault; `busy` and `held` both mean *not now, deliberately* — the sidecar never takes a port away from a console, a flash, or a running session to restore a baseline.

An `identify` pair rides on the utility sketch's own `task.json` (`data-saving.md` §6.8) rather than in settings, for the same reason the rest of the Task Profile does: the app must not know that a Hart-lab box says `ON LIGHT`.

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
| `session.lifecycle` | `<ActiveSessions>` | Broadcast whenever session **identity or status** changes — create, abandon, confirmMapping, startAll, switchGroup, end. A full snapshot, not a delta: a second window learns "ended" by seeing `running: null` with zero merge logic, and snapshots cannot be mis-merged. Per-box liveness is deliberately **not** re-broadcast here — `port.state` remains that channel, and `boxes[].running` inside the snapshot is point-in-time |
| `utility.updated` | `<UtilityStatus>` | The hardware utility baseline (§3.5). Sent on client connect and whenever any box's belief changes — a restore starting or finishing, a hold going on or off, an identify light. This is the only progress channel `utility.ensure` has, since that command returns before the flashing starts |
| `backup.status` | `<BackupStatus>` | The state of Backup Directory mirroring (`data-saving.md` §8). Sent on client connect, on every settings push that changes the directory, and whenever the mirror's state changes or it actually copies something — deliberately **not** every quiet 10s tick, so six idle boxes don't generate an event stream |
| `analytics.progress` | `{cohortId, phase, done, total}` | Earns its place against the client's 15 s default reply timeout: the first summary after upgrading is a cold index of every historical run, and on a network-mounted data directory this is the difference between "working" and "hung". Published on phase change and every N files, following `backup.status`'s discipline — never per file |
| `sidecar.error` | `{code, message, detail}` | Failures with no command to attribute them to. **Emitted** by the session runner when a mid-session `.tsv` write raises (disk full, permissions) — `data-saving.md` §7.1. Carries `code: "INTERNAL"`, a message naming the box, and `detail: {box}` |

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

```jsonc
// BackupStatus — data-saving.md §8
{
  "configured": true,                      // false when no backupDirectory is set
  "directory": "D:/EphymerisBackup" | null,
  "state": "disabled" | "pending" | "ok" | "failed",
  "pending": 2,                            // finalized files queued for their one-shot copy
  "tracking": 6,                           // live .tsv files being mirrored each pass
  "mirroredFiles": 148,                    // copies made this sidecar lifetime
  "lastSuccessAt": "2026-07-26T11:31:23+00:00" | null,
  "lastError": "remy1_….tsv: [Errno 28] No space left on device" | null,
  "syncing": false,                        // a backup.syncNow walk is running
  "intervalSeconds": 10.0
}
```

`state` is `pending` between a directory being set and the first pass completing — distinct from `ok` (a pass succeeded) and from `failed` (the last pass didn't). The distinction matters because a freshly-set network path that turns out to be unreachable should not read as healthy for its first ten seconds.

### Cohort payload shapes

Mirrors the `cohorts.md` §1 data model. Timestamps are ISO-8601 strings.

```jsonc
// CohortSummary — enough for the grid and the dashboard tile, no per-animal detail
{
  "id": "9f2c…", "name": "Batch A",
  "animalCount": 6, "groupCount": 2,
  "assignedBoxes": [1, 2, 3],   // distinct box numbers its animals hold, sorted
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
  "cage": 2 | null,                             // home-cage number — cagemates share one (cohorts.md §2)
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
  "id": "…", "cohortId": "…", "prefixId": "…", "prefixName": "2O-Bdisc",
  "sessionNumber": "25",            // free text, not strictly numeric (§10)
  "date": "2026-07-22",
  "startedAt": "…", "endedAt": null,
  "status": "configuring" | "running" | "completed" | "aborted",
  "folderPath": "/…/2O-Bdisc/2O-Bdisc_25_07_22_26",
  "groupRuns": [ { "groupId": "…", "order": 0, "startedAt": "…", "endedAt": null } ],
  "durationMinutes": 60 | null      // per-box time limit; the sidecar STOPs a box
}                                   // this long after that box's own start

// SessionAnimalRun (data-saving.md §4) — written at finalization
{
  "id": "…", "sessionId": "…", "animalId": "…",
  "boxNumber": 3, "sketchPath": "/…/GRGL_2-Odor",
  "filePath": "/…/behavior.json/remy1_….json",
  "startedAt": "…", "endedAt": "…",
  "stopReason": "BF_END_SESSION received"   // starting-a-session.md §8
}

// ConditionOutcomes — TrialOutcomes restricted to one declared condition
// (analytics.md §3.9). One per liveMetrics entry, in authored order; the
// entries partition `outcomes` field-for-field. Empty (never null) when the
// profile's vocabulary cannot express an outcome at all.
{ "metricId": "p_r_odor1", "label": "P(R | Odor 1)",
  "triggerCode": 101,               // the code opening this condition's trials
  "outcomes": { /* <TrialOutcomes> */ } }

// TrialEngagement — how far each OFFERED trial got (analytics.md §3.10).
// Delimited on the trial light, not on odor onset: the firmware only strobes
// odor-on after the animal has poked and held, so every other count in a run
// summary is conditioned on engagement and none of them can measure it.
// A ladder, not a partition — presented >= poked >= odorDelivered by
// construction, and the two gaps are reported ready-made. Null (never zeroed)
// when the profile declares no trial light.
{ "presented": 312,                 // one per LIGHTS_ON — trials the box offered
  "poked": 264,                     // of those, the animal engaged the odor port
  "odorDelivered": 251,             // of those, reached odor delivery
  "noPoke": 48,                     // presented - poked (LAZY_RAT, in practice)
  "pokeAborted": 13,                // poked - odorDelivered: let go pre-odor.
                                    // NOT TrialOutcomes.aborted, which received
                                    // odor and left during sampling
  "pEngaged": 0.846154,             // poked / presented
  "pDelivered": 0.804487,           // odorDelivered / presented
  "engagedLow": 0.802, "engagedHigh": 0.882 }   // Wilson on pEngaged

// StrategyPoint — one sample of the within-session strategy walk (§4.4)
{ "trial": 84,                      // counted trials across BOTH conditions
  "x": 0.9, "y": 0.55,              // rolling P per condition, authored order
  "n": 20 }                         // the smaller of the two window lengths

// TelemetryMetric — one rolling live-metric value (session.telemetry)
{ "id": "p_r_odor1", "value": 0.85, "n": 20 }   // value = P(hit); n = counted trials in window

// RunnerSession — the runner-held session, identical to a sessions.status reply
{
  "session": { /* <Session> */ },
  "groupId": "…" | null,            // null only before any mapping was confirmed
  "boxes": [ { "box": 1, "animalId": "…", "animalName": "remy1",
               "sketchName": "GRGL_2-Odor", "sketchPath": "/…", "running": true } ]
}

// ActiveSessions — sessions.active result AND session.lifecycle payload.
// One shape, one emitter: the command and the event can never drift apart.
{
  "running": { /* <RunnerSession> */ } | null,  // keyed off the live runner, never bare DB status
  "configuring": [ /* <Session> */ ],           // setup never finished — resumable into Step 2
  "stale": [ /* <Session> */ ]                  // 'running' rows with no live runner — crash orphans,
}                                               // surfaced for honesty, never offered for resume
```

### `settings.push` payload

The payload mirrors the Tauri-side store, which is the source of truth (`ephymeris_v1.0.md` §4.5). The full settings schema is still an open item there, so this document does **not** restate it as fixed — the sidecar reads the keys it needs (`arduinoDirectory`, `arduinoCliPath`, `utilitySketchPath`, `defaultBaud`, `boxes`, `dataDirectory`, `backupDirectory`) and ignores the rest. Adding a setting the sidecar doesn't consume is deliberately a non-event — the Config view's `constellation`, `constellationSlots`, and `boxSetupComplete` (`ephymeris_v1.0.md` §4.6) ride the same payload and are ignored by the sidecar entirely.

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
| `DATA_FOLDER_INVALID` | A data folder couldn't be created, or a `cohorts.setDataFolder` destination isn't empty **while `moveExisting` is true**. Refuses rather than overwriting (`cohorts.md` §8). A non-empty destination with `moveExisting: false` is legal and expected |
| `PREFIX_NAME_TAKEN` | A prefix with that name already exists (`data-saving.md` §3) |
| `SESSION_INVALID` | Malformed session command — unknown cohort/prefix/group, or a mapping referencing a box/animal that doesn't belong to the session |
| `SESSION_NOT_READY` | `sessions.create` against a cohort with no group holding a box-assigned animal (`starting-a-session.md` §1) |
| `TASK_PROFILE_INVALID` | A sketch's `task.json` exists but is malformed. `detail` carries the parse error; the sketch is otherwise treated as profile-less |
| `BACKUP_UNAVAILABLE` | `backup.syncNow` with no `backupDirectory` set, or with a sync already running. Note that an ordinary mirroring **failure** never surfaces as a command error — there is no command to attribute it to; it appears as `state: "failed"` on `backup.status` (`data-saving.md` §8) |
| `UTILITY_UNAVAILABLE` | A `utility.*` command with no `utilitySketchPath` set, or with one that can't be used at all — a path no longer in the Arduino Directory, or a sketch whose profile isn't `kind: "utility"`. A *box-level* problem never raises this: it is reported as that box's `state` in the snapshot (§3.5), because "box 4 has no board" is a fact about the rig, not a failure of the command |
| `DIR_INVALID` | Arduino Directory missing, not a directory, or unreadable |
| `INTERNAL` | Unhandled sidecar exception. Also the code carried by `sidecar.error` on a mid-session write failure |

> **`DIR_INVALID` is defined but never raised.** Directory problems surface as a `DirectoryStatus` payload on the `settings.push` reply (§3) rather than as a command error, because the caller wants to *render* the four states from §6 of `arduino-directory.md`, not catch a failure. The code is kept because that reasoning could reverse — but as of today nothing in the sidecar emits it, and a client should not wait for it.

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
| Schema sharing | **Generated mirrors** from `protocol/schema.py` (build-time codegen, stdlib-only generator) + a contract test that fails on a stale mirror. Reversed 2026-07-27 — the original "no codegen" call was made when the surface was a dozen names; at 38 commands with payload shapes, hand-maintenance was the costlier side, and shapes had already drifted (`analytics.rescan`'s documented result never matched the implementation) |
| Orphan protection | Sidecar exits on stdin EOF; shell also kills the child on exit |
| Crashed sidecar | **No auto-respawn.** `sidecar://down` is surfaced and the app must be restarted. A silent respawn mid-session would resurrect the process without the port ownership or session state it had, which is worse than an honest failure the user can see |

---

## 9. Open Items / TBD

- [x] ~~Session-runner messages: `IN_SESSION` start/stop/abort, and the strobe-parsed data stream shape~~ — merged into §3.2/§4 from `data-saving.md` §9 and `starting-a-session.md` §9
- [x] ~~Whether a crashed sidecar should be auto-respawned by the shell~~ — resolved: **no auto-respawn** (§8)
- [x] ~~Storage/export message shapes (`.json`/`.mat`/`.tsv`)~~ — the write path is sidecar-side, not a wire message (`data-saving.md` §7); telemetry and finalization are `session.telemetry`/`session.animalEnded` (§4)
- [x] ~~`sidecar.error` is defined and mirrored but nothing emits it~~ — **resolved.** The session runner now emits it on a mid-session `.tsv` write failure, which was always its intended first use (§4)
- [x] ~~Analytics query messages~~ — **designed** in `analytics.md` §9 and documented in §3.4/§4 as proposed. Four commands, one event, no new error codes. Not implemented, and deliberately absent from both mirrors until they are
- [x] ~~The contract test guards *names*, not *shapes*~~ — **resolved** by switching to build-time codegen: both mirrors are generated from `protocol/schema.py`, TypeScript callers are typed against the generated payload maps, and the sidecar validates payloads against the schema under `EPHYMERIS_WIRE_VALIDATE=1` (on in the test suite). See the "Changing the wire" callout above
- [ ] Multi-port batching (e.g. "flash all 6") — shared with `hardware-interaction.md` §9; whether that is one command with six progress streams or six independent commands
- [ ] Back-pressure policy if the frontend cannot keep up with `port.output` at 20 Hz × 6 boxes (currently: unbounded send, relying on the ring buffer cap)

---

**Next:** [arduino-directory.md](arduino-directory.md) — short, and flashing depends on it.
[Documentation index](README.md) · [Open items register](TODO.md)

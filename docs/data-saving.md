# Data Saving — Full Spec

**Status:** Living document. **Implemented** as of this revision — §§1–7 and §9 are built and verified against real hardware. Two exceptions, both called out in place: §5.1's `.mat` writer deviates from `scipy` (see below), and **§8's Backup Directory mirroring is not built** — the setting exists, nothing writes to it yet. Written alongside `starting-a-session.md`; the two depend on each other and should be read together — this doc defines what gets written and where, that one defines what triggers the writing.
**Companion documents:** `cohorts.md` (the `dataFolder`/`Settings.dataDirectory` this doc writes beneath), `hardware-interaction.md` (the `IN_SESSION` state this doc's writes are sourced from), `arduino-directory.md` (sketch identity — `sketch` metadata is the exact discovered sketch name), `websocket-protocol.md` (wire schema, extended in §9), `ephymeris_v1.0.md` (Settings' `dataDirectory`/backup directory).
**Not yet covered:** analytics queries over saved session data (a future doc, once Analytics moves past its stub).

Built directly against a real session file (`remy1_2O-Bdisc_25_07_22_26_113123.json`) and the current GRGL firmware (`GRGL_2-Odor.ino`, `GRGLSession.h`), rather than an invented schema — the structure below is what that file actually contains.

---

## 0. Scope

Defines the on-disk directory/file layout, the per-animal session file schema (JSON + `.mat`), the **Task Profile** mechanism that lets a sketch declare its own config/metadata/live-metric shape, write/crash-safety strategy, and backup behavior. `starting-a-session.md` owns the live session-runner and Mission Control UI that produces the data described here.

---

## 1. Directory Structure

```
<Settings.dataDirectory>/
└── <cohort name>/                          ← Cohort.dataFolder, per cohorts.md §8
    └── <prefix>/                           ← Session Prefix, §3
        └── <prefix>_<sessionNumber>_<MM>_<DD>_<YY>/     ← one per (prefix, sessionNumber, date) — see §2
            ├── behavior.tsv/                    ← written live, during the session — see §7
            │   ├── remy1_<prefix>_<sessionNumber>_<MM>_<DD>_<YY>_<HHMMSS>.tsv
            │   └── remy2_<prefix>_<sessionNumber>_<MM>_<DD>_<YY>_<HHMMSS>.tsv
            ├── behavior.json/                    ← built once, at session end, from the same data
            │   ├── remy1_<prefix>_<sessionNumber>_<MM>_<DD>_<YY>_<HHMMSS>.json
            │   └── remy2_<prefix>_<sessionNumber>_<MM>_<DD>_<YY>_<HHMMSS>.json
            └── behavior.mat/
                ├── remy1_<prefix>_<sessionNumber>_<MM>_<DD>_<YY>_<HHMMSS>.mat
                └── remy2_<prefix>_<sessionNumber>_<MM>_<DD>_<YY>_<HHMMSS>.mat
```

Concretely, from the sample file: `Data Directory/<cohort>/2O-Bdisc/2O-Bdisc_25_07_22_26/behavior.json/remy1_2O-Bdisc_25_07_22_26_113123.json`.

**A session folder is keyed by `(prefix, sessionNumber, date)`, not just date.** Starting a second session with the same prefix later the same day but a *different* session number produces a second folder; reusing the same prefix **and** number the same day (unusual, but not blocked — see `starting-a-session.md` §2) lands in the *same* folder, with new per-animal files added alongside the earlier ones. This falls out of the naming scheme on its own — the per-animal filename's `HHMMSS` suffix means same-day reruns never collide, so there's no special-case logic needed for "already exists."

---

## 2. Naming Conventions

- **Date:** `MM_DD_YY` (e.g. `07_22_26`). This matches the real sample exactly, so it's preserved as-is rather than switched to something like ISO `YYYY-MM-DD` for alphabetical sortability — continuity with the lab's existing convention matters more than that property, but it's worth flagging: `MM_DD_YY` does **not** sort correctly across a year boundary (`12_31_26` sorts after `01_01_27` alphabetically). Not proposing a change, just noting it.
- **Time:** `HHMMSS`, 24-hour, matching `remy1_..._113123` = 11:31:23.
- **Session folder:** `<prefix>_<sessionNumber>_<MM>_<DD>_<YY>`.
- **Per-animal file (both formats):** `<animal name>_<prefix>_<sessionNumber>_<MM>_<DD>_<YY>_<HHMMSS>.<ext>` — timestamped at the moment that animal's run actually starts (not session-config time), so two animals starting a few minutes apart get distinct, honest timestamps.
- **Sanitization:** cohort/prefix/animal names run through the same filesystem-safe sanitization already established for cohort data folders (`cohorts.md` §8).

---

## 3. Session Prefix

```
Prefix {
  id: uuid
  name: string     // e.g. "2O-Bdisc" — unique
}
```

Global, shared across all cohorts — a prefix like "2O-Bdisc" names a task/paradigm, not a cohort, and the same task plausibly runs across many cohorts over time.

User-managed list (add/remove), surfaced as a dropdown in `starting-a-session.md`'s configuration step. Persisted in SQLite alongside `cohorts`/`animals`/`groups` (`cohorts.md` §3) — same database, same ownership.

**Removing a prefix** doesn't touch any folder or file already written under its name on disk — same non-destructive instinct as cohort archival (`cohorts.md` §9). It just stops appearing in the dropdown for new sessions.

---

## 4. Session Entity

A record tying together one Starting-a-Session invocation — which may run multiple groups consecutively (`cohorts.md` §2's `Group.order`) — so Mission Control has something to display a header from, and so session history exists for whenever Analytics moves past its stub.

```
Session {
  id: uuid
  cohortId: uuid
  prefixId: uuid
  sessionNumber: string          // free text, not strictly numeric — see §10
  date: date                     // the calendar day this session's folder belongs to
  startedAt: timestamp
  endedAt: timestamp | null
  status: "configuring" | "running" | "completed" | "aborted"
  folderPath: string             // resolved session folder, §1
  groupRuns: [
    { groupId: uuid, order: int, startedAt: timestamp, endedAt: timestamp | null }
  ]
}

SessionAnimalRun {
  id: uuid
  sessionId: uuid
  animalId: uuid
  boxNumber: 1–6
  sketchPath: string
  filePath: string                // the finalized .json path (the .mat sits alongside, same basename)
  startedAt: timestamp
  endedAt: timestamp | null
  stopReason: string | null       // §5
}
```

`SessionAnimalRun` is forward-looking infrastructure for the eventual Analytics doc more than something the live Mission Control needs — Mission Control can run off in-memory state and wire events without querying it mid-session — but it costs little to write now and a lot to reconstruct later from files alone.

---

## 5. Per-Animal Session File Schema

Every field below is taken directly from the sample file, not invented:

```jsonc
{
  "rat": "remy1",
  "serial_port": "COM6",
  "session_id": "2O-Bdisc_25",
  "sketch": "GRGL_2-Odor",
  "correction_left": 0,
  "correction_right": 0,
  "lazy_escalation": true,
  "stop_reason": "BF_END_SESSION received",
  "trial_seed": 288577176,
  "n_events": 2392,
  "ts_data": [[221, 0], [222, 1000], [223, 5001], /* … */ [246, 3523555]]
}
```

| Field | Source | Notes |
|---|---|---|
| `rat` | `Animal.name` | |
| `serial_port` | Live hardware state at run time | The literal OS port string (`COM6`) — captures *which physical port* this run actually used, distinct from the abstract `boxNumber` |
| `session_id` | `"<prefix>_<sessionNumber>"` | Matches the session folder's own naming, §2 |
| `sketch` | The exact sketch name selected in `starting-a-session.md` §3 | Discovered via `arduino-directory.md`, not hand-typed |
| `correction_left`, `correction_right`, `lazy_escalation` | **Task-specific** — from this sketch's Task Profile (§6) | Not present for a sketch with no Task Profile, or one that declares different fields |
| `stop_reason` | Assigned by the sidecar at session end | An open, extensible set of strings — always includes the literal strobe-parser-observed reason (`"BF_END_SESSION received"`) when the board reports it cleanly; also covers operator stop, board disconnect, and sidecar-level errors — see `starting-a-session.md` §7 |
| `trial_seed` | A recognized **optional wire convention**, not a Task Profile field — see §6.4 | Absent for a sketch that never emits a `SEED\t<value>` line |
| `n_events` | `len(ts_data)` | Written once, at finalization |
| `ts_data` | The raw strobe stream | `[code, timestamp_ms]` pairs, `timestamp_ms` elapsed since that animal's own `BF_START_SESSION` (`recordEvent()`'s own convention — untouched, not re-based to wall-clock) |

**Core fields** (`rat`, `serial_port`, `session_id`, `sketch`, `stop_reason`, `n_events`, `ts_data`) are always present regardless of Task Profile. **Task-specific fields** (`correction_left`, `correction_right`, `lazy_escalation` for GRGL-family sketches) are merged in flat at the top level — not nested under a `config` key — matching the sample exactly.

### 5.1 `.mat` Mirror

Same field names, written from the identical in-memory dict used to write the JSON — one source of truth serialized twice, not two independent writers that could drift. `ts_data` becomes an `N×2` double array.

**Implemented deviation: a hand-written MAT v5 serializer, not `scipy.io.savemat`.** The named dependency was dropped on the explicit instruction to keep dependencies and setup failure modes to an absolute minimum, since most lab members aren't technical — `scipy` is a large binary wheel and by far the most likely thing to fail at install time on a lab machine. `sidecar/ephymeris_sidecar/sessions/matwriter.py` writes Level-5 MAT directly (column-major `N×2` doubles, strings as `miUINT16` char arrays, bools as `miUINT8` with the logical flag `0x02`). It was validated by round-tripping a file through `scipy.io.loadmat` in a throwaway virtualenv that was then deleted, so MATLAB/scipy compatibility is proven while the runtime dependency list stays at `pyserial` + `websockets`. This also settles §11's "confirm `savemat`'s type mapping" item by removing the question.

### 5.2 `.tsv` — Not a Third Copy of This Schema

Unlike `.json`/`.mat`, `.tsv` isn't a serialization of this same structured document — it's a live append-only log with a different shape entirely (a small `# key: value` header, then raw `code\ttimestamp` lines). Its format and purpose are specified in §7, where the reasoning for that difference actually belongs.

---

## 6. Task Profiles

The mechanism that lets a sketch declare its own START-command config, and (for `starting-a-session.md`) its own live-metric visualization — so the app isn't hardcoded to GRGL forever.

### 6.1 Location

A `task.json` file **sibling to the `.ino`** inside each sketch's own folder (`arduino-directory.md` §3's discovery already finds this folder; a sibling file is a trivial extension of that scan, not a new discovery mechanism). **Deliberately per-sketch, not shared across a prefix-family** — `GRGL_2-Odor` and `GRGL_2-Odor_EZ` share `GRGLSession.h`'s *logic*, but a task profile is a declaration of *this sketch's* strobe vocabulary and config surface, and the EZ variant's shaping stages plausibly diverge from the full task's (`GRGLSession.h`'s own comments describe real behavioral differences between the two, e.g. when the lazy escalator resets). Sharing one profile file risks it silently drifting out of sync with one of the two sketches; duplicating a small hand-written file is cheap by comparison.

A sketch with **no `task.json`** is fully supported — no config form appears before flashing it (bare `START`, matching a sketch's own documented legacy defaults), and its zoomed-in Mission Control view falls back to a raw scrolling strobe log instead of a metric chart. Not every sketch is a scored task; utility/cleaning sketches shouldn't need one.

### 6.2 Schema

```jsonc
{
  "taskName": "GRGL 2-Odor Discrimination",
  "kind": "behavior",
  "config": [
    { "metadataKey": "correction_left",  "wireKey": "CL",   "label": "Left correction budget",  "type": "int",  "default": 0 },
    { "metadataKey": "correction_right", "wireKey": "CR",   "label": "Right correction budget", "type": "int",  "default": 0 },
    { "metadataKey": "lazy_escalation",  "wireKey": "LAZY", "label": "Escalating lazy penalty",  "type": "bool", "default": true }
  ],
  "strobes": {
    "101": "ODOR_1_ON", "103": "ODOR_3_ON",
    "248": "WATER_POKE_L", "249": "WATER_POKE_R",
    "246": "END_SESSION"
    /* … full map is documentation/debug value, not required for liveMetrics to function */
  },
  "liveMetrics": [
    { "id": "p_r_odor1", "label": "P(R | Odor 1)", "triggerCode": 101, "successCode": 249, "alternateCode": 248, "windowSize": 20 },
    { "id": "p_l_odor3", "label": "P(L | Odor 3)", "triggerCode": 103, "successCode": 248, "alternateCode": 249, "windowSize": 20 }
  ]
}
```

- **`kind`** is `"behavior"` (the default when omitted) or `"utility"`. A **behavior** profile is a scored `IN_SESSION` task, described by the three fields below. A **utility** profile is a `PASSTHROUGH` tool (priming, box self-test) described instead by `controls` + `telemetry` (§6.6); it has no `config`/`strobes`/`liveMetrics` since it isn't a scored run. This keeps every profile-less-but-now-declared utility sketch first-class without special-casing it in app code.
- **`config`** drives three things from one declaration: the pre-flight config form (`starting-a-session.md` §3), the `START` command built from it (§6.3), and the metadata fields written into the session file (§5) — `metadataKey` is the JSON/`.mat` field name, `wireKey` is the `START` command token.
- **`strobes`** is a human-readable code→name map for debugging/display; not required for `liveMetrics` to compute (those reference raw codes directly), but worth having so a raw strobe log or an error message can show a name instead of a bare `249`.
- **`liveMetrics`** are rolling-window response-probability metrics — the general form of "P(R | Odor 1)." `windowSize: 20` deliberately matches the sketch's own anti-bias `biasWindow` default, not picked arbitrarily.

### 6.3 Building the `START` Command

Generic across any Task Profile: `START <wireKey1>=<value1> <wireKey2>=<value2> …` — space-separated, order-independent, matching `parseStartCommand()`'s actual grammar exactly (unknown keys ignored, missing keys keep the sketch's own defaults). The sketch's own header comment references a Python-side `protocol.build_start_command` — this section is that builder's spec, generalized from GRGL-specific to Task-Profile-driven.

### 6.4 `SEED` — a Recognized Line, Not a Task Profile Field

`trial_seed` isn't declared in `config` — it's a recognized **optional wire convention**: any line matching `SEED\t<int>` immediately following `START` is captured as `trial_seed`, the same way `READY` is already a recognized non-strobe line (`hardware-interaction.md` §6 covers passthrough's dumb handling of arbitrary text; `IN_SESSION` parsing is stricter — see `starting-a-session.md` §7). A sketch that never emits a `SEED` line just doesn't get that field. This is a protocol-level convention available to any sketch, not something a Task Profile opts into.

### 6.5 Live Metric Computation (Precise Definition)

Getting this exactly right matters — it's the actual scientific output, not just a UI detail. For each occurrence of `triggerCode` in an animal's strobe stream, scan forward for the *next* occurrence of either `successCode` or `alternateCode`, stopping the scan at the next occurrence of `triggerCode` (or any other recognized trial-boundary code) — whichever comes first:

- `successCode` found first → counts as a **hit**.
- `alternateCode` found first → counts as a **miss** (still counts toward the denominator — this is "did they go to the other side," not "did they fail to respond").
- Neither found before the scan stops (lazy/invalid/no-response trial) → **excluded entirely**, from both numerator and denominator.

This directly implements "the probability the animal responded at [a well] following [an odor] — does not mean only rewarded trials": it's response-conditional (excludes true non-responses) but reward-unconditional (a response that was detected but then failed the hold-verification, or that inherently didn't need a hold, still counts — `hardware-interaction.md`'s Mega firmware fires `WATER_POKE_L`/`R` the instant a poke is *detected*, before any hold check). The rolling window is the last `windowSize` *counted* (hit-or-miss) trials, not the last `windowSize` strobe events.

### 6.6 Utility Profiles — Controls & Telemetry

A `"kind": "utility"` profile makes a cleaning/priming/self-test sketch first-class in **Debug Mode** without hardcoding it in app code. Utility sketches run in `PASSTHROUGH`, never `IN_SESSION` — so their control and status **ride the existing passthrough primitives**: no new wire commands, and nothing they emit is stored (`websocket-protocol.md` §5.4). Two fields:

```jsonc
{
  "taskName": "Prime Lines (latch)",
  "kind": "utility",
  "controls": [
    { "id": "gear", "label": "Fluid set", "type": "select", "options": [
      { "label": "Set 1", "command": "SET GEAR=1" },
      { "label": "Set 2", "command": "SET GEAR=2" }
    ] },
    { "id": "toggle_l", "label": "Toggle L", "type": "button", "command": "TOGGLE L" },
    { "id": "alloff",   "label": "All off",  "type": "button", "command": "ALLOFF" }
  ],
  "telemetry": {
    "match": "STATUS",
    "fields": [
      { "key": "gear",  "label": "Fluid set" },
      { "key": "left",  "label": "Left line" },
      { "key": "right", "label": "Right line" }
    ]
  }
}
```

- **`controls`** — the widgets the console panel renders for the box (once its flashed sketch is known). Each `button` sends its `command`; each `select` sends the chosen option's `command`. The app sends them verbatim over `port.send` (LF-terminated), and they're gated to `PASSTHROUGH` exactly like the manual console input. The sketch parses these whole-line commands non-blockingly (`BehaviorBox.h`'s `CommandReader`) alongside its manual hardware triggers, so both drive the same state.
- **`telemetry`** — how to read the sketch's live state back. The sketch emits `STATUS <key>=<value> …` lines (`BehaviorBox.h`'s `emitStatus`); the app scans `port.output` for the newest line beginning with `match` (default `"STATUS"`), parses the space-separated `key=value` pairs, and shows the declared `fields`. This is **display-only**: parsed client-side off the capped passthrough ring, never persisted. A `STATUS` line is deliberately shaped so it can never be mistaken for a strobe (`^\d{1,3}\t\d+$`), and the strict strobe parser doesn't run in `PASSTHROUGH` anyway.

The sketch↔app contract is thus fully declared in `task.json`: the app needs no per-sketch knowledge to drive `PRIME_Lines` vs `PRIME_Bolus` vs `TEST_Box`.

---

## 7. Write Strategy & Crash Safety

The actual goal — recoverable data up to the moment of a power loss, not just "eventually consistent" — reframes `.tsv`'s role. Rather than a third redundant export format, it's the **write-ahead log that makes the durability guarantee real**, and `.json`/`.mat` are built from it rather than sitting alongside it as equals.

### 7.1 `.tsv` is written live, one line at a time

Every parsed strobe (`starting-a-session.md` §7 step 7) is appended to that animal's `.tsv` file **the instant it's received** — `flush()` + `fsync()` on every single line, not batched. This is safe here in a way it wouldn't be in a high-frequency-DAQ context: the real sample session averages under one event per second, and even during a burst of trial activity the rate stays low enough that a few-millisecond `fsync` per line is nowhere near a bottleneck. A `.tsv` line is written in **exactly the format the board itself sends** (`<code>\t<timestamp>`) — no transformation, so there's no risk of a formatting bug corrupting the one file that has to be bulletproof.

A short header, written once immediately after `START`/`SEED` resolve (before the first strobe arrives, since everything needed is already known by then): `rat`, `serial_port`, `session_id`, `sketch`, and any Task Profile config fields, each as a `# key: value` comment line. Raw strobe lines follow below it. `stop_reason` and `n_events` aren't knowable yet at that point, so they're **appended as a footer** at clean finalization (§7.3) — a `.tsv` recovered mid-session is missing only that footer, nothing else.

**If the write itself fails** (disk full, permissions) mid-session, that's surfaced via `sidecar.error` (`websocket-protocol.md` §4) — there's no user command to attribute it to, same reasoning that error hook already exists for.

### 7.2 `.json`/`.mat` are built once, at the end

Structured formats aren't append-friendly, and — this is the point — they don't need to be, because `.tsv` already carries the real-time durability guarantee. Rewriting `.json`/`.mat` throughout a session would just be extra I/O for no additional safety. The sidecar keeps the same in-memory event list it's simultaneously flushing to `.tsv`, and serializes it into both structured formats once, when the animal's run cleanly ends (`stop_reason`/`n_events` now known) — exactly the process described in §5.1 for `.mat`, unchanged for `.json`.

### 7.3 Recovery scope — data durability, not session resumption

What's now genuinely guaranteed: if the lab PC loses power mid-session, every strobe up through the last completed line is safely on disk in `.tsv`, immediately readable by a human, with at most the very last in-flight line at risk (and even that only if power died mid-write, not mid-buffer — nothing sits unflushed waiting on a timer anymore).

What's **not** in scope for v1, deliberately: the app noticing on restart that a session was interrupted and automatically resuming it. That's a materially bigger feature (reconnecting boards, resuming trial state, deciding whether the animal even kept running during the outage) and stays out of scope here. What this design does make cheap, as a natural follow-on rather than core scope: a small recovery utility that reads an orphaned `.tsv` and backfills the missing `.json`/`.mat` with `stop_reason: "recovered after crash"` — flagged in §11, not built now.

---

## 8. Backup Strategy

> **Not implemented.** `Settings.backupDirectory` exists in the settings schema and is pushed to the sidecar, but nothing copies files into it yet — neither the finalization copy nor the periodic `.tsv` mirror nor the `ephymeris.db` backup. The `.tsv` write-ahead log (§7) *is* built, so the same-disk crash guarantee holds; what's missing is the different-disk guarantee. Tracked in §11.

Two distinct, complementary mechanisms, protecting against two different failures — worth being explicit that they're not the same thing:

- **`.tsv` as write-ahead log (§7):** protects against the app/power dying mid-session, on the *same* disk. This is now load-bearing, not redundant.
- **Backup Directory mirroring** (`ephymeris_v1.0.md` §4.5's separate `backupDirectory` setting): protects against losing the whole `dataDirectory` — drive failure, accidental deletion — a different disk/location entirely. `.json`/`.mat` are copied into the mirror on finalization, same as before. `.tsv` is mirrored too, but on a **periodic cadence** (e.g. every ~5–10s) rather than per-line: `backupDirectory` may be a slower or network location, and stalling the real-time strobe-parsing thread on every single line's remote write would undermine the exact guarantee §7 just established locally. `ephymeris.db` (`cohorts.md` §3) is included in this mirror too — resolving that doc's §12 TBD item — backed up on every app start and after any cohort-affecting write.

---

## 9. Wire Messages (merged)

**Merged into `websocket-protocol.md` §3.1/§3.2/§4** — that file is canonical; the tables below are kept for rationale only. `protocol.py`, `protocol.ts` and the doc are held in sync by the contract test.

**Commands:**

| Command | Args | Result |
|---|---|---|
| `prefixes.list` | — | `{prefixes: [Prefix]}` |
| `prefixes.create` | `{name}` | `{prefix}` |
| `prefixes.delete` | `{id}` | `{deleted: true}` |
| `tasks.getProfile` | `{sketchPath}` | `<TaskProfile>` or `{profile: null}` if the sketch has none |

**Events:**

| Event | `data` | Notes |
|---|---|---|
| `prefixes.updated` | `{prefixes: [Prefix]}` | Push-on-change, same pattern as `cohorts.updated` |

Session lifecycle commands/events (`session.start`, per-animal telemetry, etc.) are specified in `starting-a-session.md` §9 rather than duplicated here, since they're driven by that doc's flow.

---

## 10. Resolved Decisions

| Decision | Outcome |
|---|---|
| Third backup format | **Kept, but redefined.** `.tsv`'s job is real-time crash durability, not redundant export — §7 |
| Session Prefix scope | **Global**, shared across all cohorts (§3) |
| Session number format | Free text, confirmed. Config UI suggests the next numeric value as a default (`starting-a-session.md` §2.2) |
| `.mat` writer (§5.1) | **Hand-written MAT v5 serializer, not `scipy`.** Zero added runtime dependencies, on the explicit instruction to minimise setup failure modes for non-technical users; compatibility proven by a throwaway-venv `loadmat` round-trip |
| `SessionAnimalRun` write timing | **At finalization only**, not incrementally — the lighter of §11's two options. Incremental writes only buy anything for crash resumption, which is out of scope |

---

## 11. Open Items / TBD

- [x] ~~Confirm `scipy.io.savemat`'s exact type mapping (bools, strings) once implementation starts (§5.1)~~ — moot: `scipy` isn't used. The hand-written serializer's mapping is fixed by us and asserted by `test_matwriter.py`, and was checked against `loadmat` once in a throwaway venv
- [x] ~~Merge §9's proposed commands/events into `websocket-protocol.md`~~ — **done**, along with `starting-a-session.md` §9; the contract test covers every name across the doc, `protocol.py`, and `protocol.ts`
- [ ] **§8's Backup Directory mirroring is not built at all** — finalization copy, periodic `.tsv` mirror, and `ephymeris.db` backup are all still to do. This is the largest known gap in this doc, and the one that leaves `cohorts.md` §12's `ephymeris.db` item open
- [ ] Small recovery utility to backfill `.json`/`.mat` from an orphaned `.tsv` after a crash, with `stop_reason: "recovered after crash"` — cheap given §7's design, deliberately out of scope for this pass (§7.3)
- [ ] Exact backup mirroring interval for `.tsv` beyond "every ~5–10s" (§8) — blocked on the above being built at all
- [ ] Exact backup trigger cadence for `ephymeris.db` beyond "app start + every cohort-affecting write" (§8) — may need a periodic timer too if the app runs unattended for long stretches

# Data Saving

> **Status** · Living spec — **Built**, for §§1–9. §§1–7 and §9 are verified against real hardware; §8's mirroring is built and unit-tested but has not yet run a full session against a real network share. One deviation, called out in place: §5.1's `.mat` writer replaces the originally-named `scipy`.
>
> **Owns** · The on-disk layout, the per-animal file schema, the Task Profile mechanism, and the crash-safety and backup strategies.
>
> **Read with** · [starting-a-session.md](starting-a-session.md) (what triggers these writes — the two were written together) · [cohorts.md](cohorts.md) (the `dataFolder` written beneath) · [websocket-protocol.md](websocket-protocol.md) (canonical for the commands §9 proposed)
>
> **Still open** · §8's mirroring against a real network share

**Contents** — [1. Directory Structure](#1-directory-structure) · [2. Naming](#2-naming-conventions) · [3. Session Prefix](#3-session-prefix) · [4. Session Entity](#4-session-entity) · [5. File Schema](#5-per-animal-session-file-schema) · [6. Task Profiles](#6-task-profiles) · [7. Crash Safety](#7-write-strategy--crash-safety) · [8. Backup](#8-backup-strategy) · [9. Wire Messages](#9-wire-messages-merged) · [10. Resolved Decisions](#10-resolved-decisions) · [11. Open Items](#11-open-items--tbd)

> **`.tsv` is not an export format.** It is the **write-ahead log** — the mechanism that makes the crash-durability guarantee real. Every strobe is `flush()`+`fsync()`'d to it the instant it arrives. `.json` and `.mat` are built once, at clean finalization, from the same in-memory buffer. Read §7 before treating `.tsv` as redundant with the other two.

Built directly against a real session file (`remy1_2O-Bdisc_25_07_22_26_113123.json`) and the current GRGL firmware (`GRGL_2-Odor.ino`, `GRGLSession.h`) rather than an invented schema — the structure below is what that file actually contains.

---

## 0. Scope

Defines the on-disk directory/file layout, the per-animal session file schema (JSON + `.mat`), the **Task Profile** mechanism that lets a sketch declare its own config/metadata/live-metric shape, write/crash-safety strategy, and backup behavior. `starting-a-session.md` owns the live session-runner and Mission Control UI that produces the data described here.

---

## 1. Directory Structure

```
<Settings.dataDirectory>/
└── <cohort name>/                          ← Cohort.dataFolder, per cohorts.md §8
    └── <prefix>/                           ← Session Prefix, §3
        └── <prefix>_<sessionNumber>_<YYYY-MM-DD>/     ← one per (prefix, sessionNumber, date) — see §2
            ├── behavior.tsv/                    ← written live, during the session — see §7
            │   ├── remy1_<prefix>_<sessionNumber>_<YYYY-MM-DD>_<HHMMSS>.tsv
            │   └── remy2_<prefix>_<sessionNumber>_<YYYY-MM-DD>_<HHMMSS>.tsv
            ├── behavior.json/                    ← built once, at session end, from the same data
            │   ├── remy1_<prefix>_<sessionNumber>_<YYYY-MM-DD>_<HHMMSS>.json
            │   └── remy2_<prefix>_<sessionNumber>_<YYYY-MM-DD>_<HHMMSS>.json
            └── behavior.mat/
                ├── remy1_<prefix>_<sessionNumber>_<YYYY-MM-DD>_<HHMMSS>.mat
                └── remy2_<prefix>_<sessionNumber>_<YYYY-MM-DD>_<HHMMSS>.mat
```

Concretely: `Data Directory/<cohort>/2O-Bdisc/2O-Bdisc_25_2026-07-22/behavior.json/remy1_2O-Bdisc_25_2026-07-22_113123.json`. The original sample file was named `remy1_2O-Bdisc_25_07_22_26_113123.json`; §2.1 covers why that spelling changed and why old files keep it.

**A session folder is keyed by `(prefix, sessionNumber, date)`, not just date.** Starting a second session with the same prefix later the same day but a *different* session number produces a second folder; reusing the same prefix **and** number the same day (unusual, but not blocked — see `starting-a-session.md` §2) lands in the *same* folder, with new per-animal files added alongside the earlier ones. This falls out of the naming scheme on its own — the per-animal filename's `HHMMSS` suffix means same-day reruns never collide, so there's no special-case logic needed for "already exists."

The writer nonetheless opens its `.tsv` **exclusively** rather than trusting that (§7.1). The naming scheme is what makes a collision unreachable; the exclusive open is what makes an unreachable collision fail loudly instead of quietly truncating an animal's data.

---

## 2. Naming Conventions

- **Date:** ISO `YYYY-MM-DD` (e.g. `2026-07-22`). See §2.1 — this replaced the sample's original `MM_DD_YY`.
- **Time:** `HHMMSS`, 24-hour, matching `remy1_..._113123` = 11:31:23.
- **Session folder:** `<prefix>_<sessionNumber>_<YYYY-MM-DD>`.
- **Per-animal file (both formats):** `<animal name>_<prefix>_<sessionNumber>_<YYYY-MM-DD>_<HHMMSS>.<ext>` — timestamped at the moment that animal's run actually starts (not session-config time), so two animals starting a few minutes apart get distinct, honest timestamps.
- **Sanitization:** cohort/prefix/animal names run through the same filesystem-safe sanitization already established for cohort data folders (`cohorts.md` §8).

### 2.1 Why the date format changed, and why it's hyphenated

The original convention, taken from the real sample file, was `MM_DD_YY`. It does not sort correctly across a year boundary — `12_31_26` sorts *after* `01_01_27` alphabetically — and for a while that was accepted as the cost of continuity with the lab's existing naming. It was changed on an explicit lab-side decision, not silently: session folders now carry ISO dates and sort chronologically as plain strings.

**Hyphenated (`2026-07-22`), not underscored (`2026_07_22`), and the distinction is the interesting part.** Both `MM_DD_YY` and `YYYY_MM_DD` split into the same number of `_`-separated tokens:

```
remy1_2O-Bdisc_25_07_22_26_113123      →  7 tokens   (legacy)
remy1_2O-Bdisc_25_2026_07_22_113123    →  7 tokens   (underscored ISO — rejected)
remy1_2O-Bdisc_25_2026-07-22_113123    →  6 tokens   (chosen)
```

An existing analysis script parsing these names positionally would survive the underscored change and read every date **wrong** — year where it expected month, month where it expected day. The hyphenated form changes the token count instead, so such a script fails immediately and visibly. A loud break beats silent corruption, and hyphens are already normal in these names anyway (the prefix `2O-Bdisc` carries one).

**Nothing already on disk is renamed.** Consistent with how cohort delete and prefix delete refuse to touch files (§3, `cohorts.md` §9), the change applies to newly-written folders only; a prefix folder will contain both spellings for as long as its history spans the change. `sessions/paths.py`'s `parse_name_date` therefore reads **both**, anchored at the end of the name — anchoring is what disambiguates the legacy form, since an unanchored search for `NN_NN_NN` in `2O-Bdisc_25_07_22_26` matches `25_07_22`, the session number plus two thirds of the date.

> **Never sort these names lexically.** Both formats coexist on disk indefinitely, so string ordering over a real archive is wrong regardless of which format you assume. Parse the date. This is a standing invariant for Analytics and for the §11 recovery utility, and `parse_name_date` exists so there's no reason to hand-roll it.

### 2.2 Reading names other software wrote

Everything above governs what this app *writes*. What it **reads** is wider, because the archive walk (`analytics.md` §8.1) meets folders named by programs that never saw this document — and the standing rule that nothing here renames a user's files means those names have to be read as they are, permanently.

Two shapes beyond the legacy date turned up in a real cohort. The session number can lead rather than trail (`00_01_shaping_gr_06_17_26` — number, then task label, then date, the inverse of the convention above), so `parse_session_folder` identifies the number by *being numeric* rather than by its position: trailing first, so every name this app wrote is read exactly as before, then leading. And separators vary within one archive — one folder among thirty was typed `18-19-shaping-gr` while its siblings used underscores.

**A separator variant is reported as written, not normalized.** Folding `-` into `_` would tidy that one folder and also merge `2O-Bdisc` with `2O_bdisc`, which are two distinct prefixes in another real archive. Reporting `shaping-gr` for a folder named `shaping-gr` is the honest read; anything else is the app deciding it knows better than the disk. Renaming the folder is a five-second operation with no data risk, and it belongs to whoever owns the data.

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
  durationMinutes: int | null    // optional per-box time limit (starting-a-session.md §2.4);
}                                // null = no limit. One value for every group in the session.

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
  profileHash: string | null      // the Task Profile this run actually used — see below
}
```

**`profileHash` records which Task Profile decoded this run**, content-addressed so identical profiles store once (`analytics.md` §8.2). A `task.json` lives beside its sketch, outside the data directory, and can be edited, renamed, or deleted long after a session — so without a snapshot, a run recorded a year ago would be silently re-interpreted with today's strobe codes and metric definitions. `null` means the run predates snapshotting, and is exactly the flag Analytics needs to mark it as decoded with a possibly-changed profile.

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

- **`kind`** is `"behavior"` (the default when omitted) or `"utility"`. A **behavior** profile is a scored `IN_SESSION` task, described by the three fields below. A **utility** profile is a `PASSTHROUGH` tool (priming, box self-test) described instead by `controls` + `telemetry` (§6.6), since it isn't a scored run. This keeps a utility sketch first-class without special-casing it in app code.

  > **`kind` is a convention, not a schema gate.** The parser reads `config`, `strobes`, `liveMetrics`, `controls`, and `telemetry` from *every* profile regardless of `kind`, and unknown top-level keys are ignored silently. So a `utility` profile carrying `liveMetrics` is accepted and simply never scored, and a malformed `kind` is the only thing that will actually be rejected. Write profiles to the convention — nothing will enforce it for you.
- **`config`** drives three things from one declaration: the pre-flight config form (`starting-a-session.md` §3), the `START` command built from it (§6.3), and the metadata fields written into the session file (§5) — `metadataKey` is the JSON/`.mat` field name, `wireKey` is the `START` command token.
- **`strobes`** is a human-readable code→name map for debugging/display; not required for `liveMetrics` to compute (those reference raw codes directly), but worth having so a raw strobe log or an error message can show a name instead of a bare `249`.
- **`liveMetrics`** are rolling-window response-probability metrics — the general form of "P(R | Odor 1)." `windowSize: 20` deliberately matches the sketch's own anti-bias `biasWindow` default, not picked arbitrarily.
- **`legacyNames`** (optional, default `[]`) lists names *older software* wrote into a run document's `sketch` field for this same task — see §6.7.

### 6.3 Building the `START` Command

Generic across any Task Profile: `START <wireKey1>=<value1> <wireKey2>=<value2> …` — space-separated, order-independent, matching `parseStartCommand()`'s actual grammar exactly (unknown keys ignored, missing keys keep the sketch's own defaults). The sketch's own header comment references a Python-side `protocol.build_start_command` — this section is that builder's spec, generalized from GRGL-specific to Task-Profile-driven.

### 6.4 `SEED` — a Recognized Line, Not a Task Profile Field

`trial_seed` isn't declared in `config` — it's a recognized **optional wire convention**: any line matching `SEED\t<int>` immediately following `START` is captured as `trial_seed`, the same way `READY` is already a recognized non-strobe line (`hardware-interaction.md` §6 covers passthrough's dumb handling of arbitrary text; `IN_SESSION` parsing is stricter — see `starting-a-session.md` §7). A sketch that never emits a `SEED` line just doesn't get that field. This is a protocol-level convention available to any sketch, not something a Task Profile opts into.

### 6.5 Live Metric Computation (Precise Definition)

Getting this exactly right matters — it's the actual scientific output, not just a UI detail. For each occurrence of `triggerCode` in an animal's strobe stream, scan forward for the *next* occurrence of either `successCode` or `alternateCode`, stopping the scan at the next occurrence of `triggerCode` (or any other recognized trial-boundary code) — whichever comes first:

- `successCode` found first → counts as a **hit**.
- `alternateCode` found first → counts as a **miss** (still counts toward the denominator — this is "did they go to the other side," not "did they fail to respond").
- Neither found before the scan stops (lazy/invalid/no-response trial) → **excluded entirely**, from both numerator and denominator.

This directly implements "the probability the animal responded at [a well] following [an odor] — does not mean only rewarded trials": it's response-conditional (excludes true non-responses) but reward-unconditional (a response that was detected but then failed the hold-verification, or that inherently didn't need a hold, still counts — `hardware-interaction.md`'s Mega firmware fires `WATER_POKE_L`/`R` the instant a poke is *detected*, before any hold check). The rolling window is the last `windowSize` *counted* (hit-or-miss) trials, not the last `windowSize` strobe events. `windowSize` defaults to **20** when a profile omits it.

Two consequences fall out of that definition and are worth stating so nobody reads them as bugs:

- **A `successCode` or `alternateCode` arriving with no trial open is ignored entirely.** It is not counted as anything. Only a strobe following a `triggerCode` can score.
- **`n` legitimately lags the true trial count**, because excluded trials never enter the window. A metric reading `n=14` after 20 triggers means six trials had no response — which is information, not a defect.

Every metric's `triggerCode` acts as a trial boundary for *every other* metric in the profile, so an unanswered trial is closed rather than left open to be scored by a later, unrelated strobe.

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

- **`controls`** — the widgets Debug Mode renders for the box (once its flashed sketch is known). Three types, all sent verbatim over `port.send` (LF-terminated) and gated to `PASSTHROUGH` exactly like the manual console input:

  | Type | Renders as | Sends |
  |---|---|---|
  | `button` | one button | its `command` |
  | `select` | a dropdown | the chosen option's `command` |
  | `grid` | a labelled row per `channels[]` entry, each with a live state lamp | that row's `toggle` or `pulse` |

  The sketch parses these whole-line commands non-blockingly (`BehaviorBox.h`'s `CommandReader`) alongside its manual hardware triggers, so both drive the same state.

  **Why `grid` exists.** A behavior box has 18 controllable outputs (12 odor solenoids, 4 fluid lines, vacuum, trial light). As flat buttons that is 36 controls in a wrapped row with no indication of which are *open* — and for solenoids on a fluid rig, "what is energized right now" is a safety readout, not a convenience. A grid row carries `label`, an optional `state` (a telemetry key whose `1`/`open`/`true` lights the lamp), and at least one of `toggle`/`pulse`. A row with neither command is rejected at parse time rather than rendered inert. An absent `state` key leaves the lamp neutral rather than claiming "closed" — not-reported and closed are different facts.

- **`telemetry`** — how to read the sketch's live state back. The sketch emits `STATUS <key>=<value> …` lines (`BehaviorBox.h`'s `emitStatus`); the app scans `port.output` for the newest line beginning with `match` (default `"STATUS"`), parses the space-separated `key=value` pairs, and shows the declared `fields` — and, for a `grid`, lights each row from its own `state` key. This is **display-only**: parsed client-side off the capped passthrough ring, never persisted. A `STATUS` line is deliberately shaped so it can never be mistaken for a strobe (`^\d{1,3}\t\d+$`), and the strict strobe parser doesn't run in `PASSTHROUGH` anyway.

  > **STATUS values cannot contain spaces** — the parser splits on whitespace. So a sketch's *prose* (a self-test's running commentary, its pass/fail confirmations) belongs in ordinary `Serial.println` lines, which land in the console pane where a human reads them. `STATUS` carries the structured state for the strip. `BOX_Utility` uses exactly this split.

The sketch↔app contract is thus fully declared in `task.json`: the app needs no per-sketch knowledge to drive one. **`Utility/BOX_Utility`** is the worked example — one sketch consolidating what were three (`PRIME_Lines` latch, `PRIME_Bolus` pulse, `TEST_Box` self-test), because priming a line and pulsing it were never different programs, only the same solenoid with a different open time, and re-flashing between them cost more than it saved. It declares three grids (fluids, vacuum+light, odors), a pulse-width select, and self-test/stop/all-off buttons; it addresses every output through channel tokens (`O1`–`O12`, `F1`–`F4`, `VAC`, `LIGHT`) so `TOGGLE`/`PULSE`/`ON`/`OFF` are written once rather than per class of hardware. The three sketches it replaces are named in its `legacyNames` (§6.7) so historical runs still decode.

---

### 6.7 `legacyNames` — decoding an archive older than this app

A finalized run document records `sketch` as a **name**, and the archive walk (`analytics.md` §8.1) resolves that name against the Arduino Directory to find the `task.json` that can score the run. For anything this app wrote, the name is the sketch folder's name and resolution is exact.

Data written by whatever the lab used before is not so lucky. The real Remy archive records `"Shape - L"` and `"Shape - R"` — human labels — where the directory holds `shaping_GL` and `shaping_GR`. Those runs are perfectly decodable; the name is simply not the folder's.

```jsonc
{
  "taskName": "Shaping — Go-Left (Odor 3)",
  "kind": "behavior",
  "legacyNames": ["Shape - L"],   // what older software called this same task
  /* … */
}
```

**Declared, never inferred.** Matching `"Shape - L"` to `shaping_GL` by resemblance is exactly the kind of guess §8.1 forbids for animal names, and for the same reason: a wrong match decodes real data with the wrong strobe map and produces confident, wrong numbers. Resemblance is not evidence. So the mapping is a one-line assertion by the person who knows, sitting in the profile it belongs to — which also means it travels with the sketch and is reviewable in a diff.

Only the archive walk reads this. It is never used to pick a sketch to flash, never shown in the picker, and has no effect on a live session. An unresolvable name is not an error: the run decodes to `no-metrics` and its `detail` **names the sketch it wanted**, so the fix is visible rather than something to go hunting for.

---

### 6.8 `identify` — asking a box to point at itself

A utility profile may declare one more pair, used by the hardware utility baseline (`hardware-interaction.md` §8.3) rather than by any control in Debug Mode:

```jsonc
{
  "kind": "utility",
  "identify": { "on": "ON LIGHT", "off": "OFF LIGHT" },
  /* … */
}
```

"Point at box 3" is a universal thing for the app to want; `ON LIGHT` is a Hart-lab detail. Putting the pair in the profile is the same call §6.2 makes everywhere else — the app drives hardware it knows nothing about, through commands the sketch names — and it is why the guided placement walk (`starting-a-session.md` §3.5) works on a rig whose boxes signal with a buzzer, or an LED on a different pin, or not at all.

**Both halves are required together.** A sketch that can be lit but not unlit would leave a box announcing itself indefinitely, so a profile declaring only one is malformed rather than half-supported. Omitting the block entirely is the normal case for a behaviour sketch and perfectly fine for a utility one; it means the box can't be asked, which every caller is expected to degrade around.

The pair is deliberately **not** the same thing as the `LIGHT` row in `BOX_Utility`'s `aux` grid. That row is a manual control a human toggles while debugging; `identify` is a contract the app drives on its own. They happen to reach the same solenoid, and would not on a rig that signalled some other way.

---

## 7. Write Strategy & Crash Safety

The actual goal — recoverable data up to the moment of a power loss, not just "eventually consistent" — reframes `.tsv`'s role. Rather than a third redundant export format, it's the **write-ahead log that makes the durability guarantee real**, and `.json`/`.mat` are built from it rather than sitting alongside it as equals.

### 7.1 `.tsv` is written live, one line at a time

Every parsed strobe (`starting-a-session.md` §7 step 7) is appended to that animal's `.tsv` file **the instant it's received** — `flush()` + `fsync()` on every single line, not batched. This is safe here in a way it wouldn't be in a high-frequency-DAQ context: the real sample session averages under one event per second, and even during a burst of trial activity the rate stays low enough that a few-millisecond `fsync` per line is nowhere near a bottleneck. A `.tsv` line is written in **exactly the format the board itself sends** (`<code>\t<timestamp>`) — no transformation, so there's no risk of a formatting bug corrupting the one file that has to be bulletproof.

A short header, written once immediately after `START`/`SEED` resolve (before the first strobe arrives, since everything needed is already known by then): `rat`, `serial_port`, `session_id`, `sketch`, and any Task Profile config fields, each as a `# key: value` comment line. Raw strobe lines follow below it. `stop_reason` and `n_events` aren't knowable yet at that point, so they're **appended as a footer** at clean finalization (§7.3) — a `.tsv` recovered mid-session is missing only that footer, nothing else.

**The file is opened exclusively (`"x"`), not truncating.** §1's `HHMMSS` already makes a same-path collision unreachable, so this will effectively never fire — but this is the one file carrying the durability guarantee, and "practically unreachable" is a weaker claim there than anywhere else in the codebase. On the impossible day it does fire, the box refuses to start with an error naming the file in the way, rather than silently overwriting a previous animal's session. Refusing to start is recoverable; a truncated write-ahead log is not.

**If the write itself fails** (disk full, permissions) mid-session, that's surfaced via `sidecar.error` (`websocket-protocol.md` §4) — there's no user command to attribute it to, which is the exact reason that error hook exists. **This is built:** the runner catches the write failure, logs it, and broadcasts `sidecar.error` naming the box. The strobe is dropped rather than retried, and the run continues — the operator is told immediately that data is no longer being saved, and can decide what to do about it. A failure to *open* the file at all takes the same route, and carries the underlying cause into both the error and the recorded `stop_reason`, so a box that refuses to start says why.

### 7.2 `.json`/`.mat` are built once, at the end

Structured formats aren't append-friendly, and — this is the point — they don't need to be, because `.tsv` already carries the real-time durability guarantee. Rewriting `.json`/`.mat` throughout a session would just be extra I/O for no additional safety. The sidecar keeps the same in-memory event list it's simultaneously flushing to `.tsv`, and serializes it into both structured formats once, when the animal's run cleanly ends (`stop_reason`/`n_events` now known) — exactly the process described in §5.1 for `.mat`, unchanged for `.json`.

Finalization is **idempotent** (the first `stop_reason` wins, so a double-stop can't rewrite history) and the two structured writes are **best-effort**: an `OSError` writing `.json` or `.mat` is logged, not raised. That ordering is deliberate — the `.tsv` is already closed and durable by then, so a failure to produce the convenience formats must never be allowed to look like a failure to save the data.

### 7.3 Recovery scope — data durability, not session resumption

What's now genuinely guaranteed: if the lab PC loses power mid-session, every strobe up through the last completed line is safely on disk in `.tsv`, immediately readable by a human, with at most the very last in-flight line at risk (and even that only if power died mid-write, not mid-buffer — nothing sits unflushed waiting on a timer anymore).

What's **not** in scope for v1, deliberately: the app noticing on restart that a session was interrupted and automatically resuming it. That's a materially bigger feature (reconnecting boards, resuming trial state, deciding whether the animal even kept running during the outage) and stays out of scope here.

The cheap follow-on this design promised is now **built**: `sessions/recovery.py` and the `sessions.recover` command (surfaced as **Recover** beside Rescan in Analytics) walk a cohort's archive for orphaned `.tsv` files — write-ahead logs with no `.json` sibling — and rebuild both structured formats from them. Discovery shares `analytics.md` §8.1's depth-tolerant walker (one traversal underlies both, per §11's build-them-to-share-one note), so every legacy layout the adoption walk reads, recovery reads too, and it backfills layout-preservingly (a `recovery_tsv/` orphan gets `behavior_json/`/`behavior_mat/`). Two honesty rules: a footer-carrying `.tsv` — §7.2's disk-full case, where `finalize` ran but the best-effort `.json` write failed — keeps its recorded `stop_reason`, and only a footer-less (crashed) log gets `stop_reason: "recovered after crash"`; and `n_events` is always recomputed from the lines actually parsed, never copied from a footer a torn file may no longer live up to. A torn final line matches neither the header nor the strobe grammar and costs only itself, exactly the at-most-one-line risk stated above. The command is rejected while any box is running — a live run's `.tsv` legitimately has no `.json` yet and is not an orphan.

---

## 8. Backup Strategy

> **Built** (`sidecar/ephymeris_sidecar/backup/`). Previously the largest gap in this document: the setting was collected and pushed but nothing read it, so a user who set it reasonably believed their data was mirrored when it wasn't.

Two distinct, complementary mechanisms, protecting against two different failures — worth being explicit that they're not the same thing:

- **`.tsv` as write-ahead log (§7):** protects against the app/power dying mid-session, on the *same* disk. This is load-bearing, not redundant.
- **Backup Directory mirroring** (`ephymeris_v1.0.md` §4.5's separate `backupDirectory` setting): protects against losing the whole `dataDirectory` — drive failure, accidental deletion — a different disk or location entirely.

Mirroring is **entirely off the critical path**, and every design decision below follows from one rule: *the backup target may be slow, networked, or dead, and none of that may ever slow, stall, or fail a session.* A mirror that works but blocks finalization would be worse than no mirror at all, because it would put a network share in the path of the guarantee §7 exists to make.

### 8.1 Layout — anchored on the cohort folder, not the data directory

```
<backupDirectory>/
├── <cohort folder basename>/       ← mirrors that cohort's folder, contents unchanged
│   └── <prefix>/<session folder>/behavior.{tsv,json,mat}/…
├── ephymeris.db                    ← current mirror of the cohort database
└── db-snapshots/
    └── ephymeris_<YYYY-MM-DD>.db   ← one per day, newest 14 kept
```

The mirror path is **not** derived by subtracting `Settings.dataDirectory` from the source path, because it can't be: `cohorts.setDataFolder` (`cohorts.md` §8) can put a cohort's folder anywhere, including somewhere with no relationship to the data directory at all. Every mirrored file is anchored on the cohort folder containing it instead. In the normal case — cohort folders sitting under `dataDirectory` — this reproduces the familiar layout exactly, which is the point: a last-resort archive nobody can navigate is worth much less than one they can.

Two cohorts can only collide here if *both* had their folders relocated by hand into different parents sharing a basename. When that happens every member of the colliding set gets a short path-derived suffix, so the layout doesn't depend on which order cohorts happen to be enumerated in.

**The mirror is additive. Nothing is ever deleted from it because it disappeared from the source** — a mirror that faithfully reproduces a deletion is no protection against one.

### 8.2 Session files

- **`.json`/`.mat` at finalization** are *queued*, not copied inline. Ending a session, or switching groups with six boxes finalizing at once, never waits on the backup target. `backup.status` reports the queue depth, so "not yet mirrored" is visible rather than assumed.
- **`.tsv` while running** is mirrored on a **periodic ~10s cadence**, never per line. Stalling the real-time strobe-parsing thread on a remote write would undermine the exact guarantee §7 established locally. The interval is measured from the *end* of the previous pass, so a slow target stretches the cadence instead of queuing overlapping passes. At the real session rate of well under one event per second this leaves at most ~10 strobes unmirrored, against a local file that is already `fsync`'d per line.
- **Every copy is whole-file**, not an incremental append. A partial append to a slow target could leave the mirrored write-ahead log torn; copying whole makes that impossible, and a full session `.tsv` is only tens of kilobytes. Copies land via a `.part` file plus an atomic replace, so a crash mid-copy can never leave a half-written file where a good one was.

### 8.3 `ephymeris.db`

Backed up on **every commit**, debounced by 5 s — resolving `cohorts.md` §12's open item. Hooking commit itself rather than calling out from each repository method means no write path can forget to announce itself, and it broadens the trigger correctly: `session_animal_runs` is written at finalization during an unattended overnight run, and is not a "cohort-affecting write" by any reading. The debounce matters because editing a roster commits many times in quick succession, and without it every keystroke's save would copy the file to a network share.

This is also why **no periodic timer is needed** (an earlier open question): the database only changes when something writes to it, so a timer over an idle database would re-copy identical bytes. A settings push carrying a new directory marks it dirty immediately, which is what satisfies "on every app start" — settings arrive right after the sidecar comes up.

The copy is two-step on purpose. SQLite's own online backup API is used rather than a file copy, since a plain copy of a live database can capture a torn page — but that API holds the database lock for its duration, so it writes to a **local** temp file first (milliseconds), and the slow copy out to the mirror happens with nothing locked. Pointing it straight at a network share would let that share's latency block every cohort read in the app.

**Dated snapshots exist because the live mirror alone doesn't protect against half of what backup is for.** A single overwritten copy would faithfully propagate an accidental cohort deletion within seconds. One dated snapshot per day, first-of-day wins (a later one would only overwrite the very state someone is trying to undo), newest 14 retained. Snapshot names are ISO-dated, so pruning the oldest is a plain sort — a small payoff of §2.1's date decision.

### 8.4 No automatic backfill

Setting a backup directory mirrors from that moment on; it does **not** copy what's already on disk. Doing so automatically could mean an unannounced multi-gigabyte copy to a network share the instant someone picks a folder, and it would fire again on every repoint. The explicit version is `backup.syncNow` (`websocket-protocol.md` §3.3), surfaced as a refresh control beside the Settings field, which walks every cohort folder and copies anything missing or stale. It doubles as the way to prove a target actually works before trusting it with anything.

### 8.5 Failure is visible, not silent

A backup that silently stops working is the same class of problem as a setting that silently does nothing — which is what this section was written to fix. Mirroring failures surface as `state: "failed"` on the `backup.status` event, with the underlying error, rendered as a persistent note in Settings and a compact indicator in Mission Control. They are deliberately **not** `sidecar.error` toasts: a dead network share fails every pass, and a transient notification every 10 s would be noise that teaches people to ignore it. Retries continue on the normal cadence, and recovery clears the state on its own.

Nothing about a failed mirror affects the session. Local writing continues untouched, which the Settings note says in as many words.

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
| `backup.syncNow` | — | `{copied, skipped, failed, errors, directory}` — the §8.4 explicit backfill |

**Events:**

| Event | `data` | Notes |
|---|---|---|
| `prefixes.updated` | `{prefixes: [Prefix]}` | Push-on-change, same pattern as `cohorts.updated` |
| `backup.status` | `<BackupStatus>` | Mirroring state (§8.5). Sent on connect, on a directory change, and on any state change or real copy — not on quiet ticks |

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
| Date format (§2.1) | **Changed to ISO `YYYY-MM-DD`**, on an explicit lab-side decision. Hyphenated so a positional parser breaks loudly rather than misreading dates silently. Existing files keep `MM_DD_YY`; `parse_name_date` reads both |
| `.tsv` mirror cadence (§8.2) | **~10 s, self-paced** from the end of the previous pass, plus a copy at finalization. Whole-file, never incremental append |
| `ephymeris.db` backup trigger (§8.3) | **Every commit, debounced 5 s.** No periodic timer — an idle database has nothing new to copy, and hooking commit means no write path can forget |
| `ephymeris.db` retention (§8.3) | **Live mirror plus one dated snapshot per day, newest 14 kept.** A single overwritten copy would propagate an accidental deletion, defeating half the purpose |
| Backfill on setting a directory (§8.4) | **None automatic.** Explicit `backup.syncNow` instead, which also serves as the way to verify a target works |
| Finalization copy timing (§8.2) | **Queued, never blocking.** A slow or dead target must not be able to stall session teardown |
| `.tsv` open mode (§7.1) | **Exclusive create (`"x"`).** A collision fails the box loudly rather than truncating; the naming scheme already makes it unreachable |

---

## 11. Open Items / TBD

- [x] ~~Confirm `scipy.io.savemat`'s exact type mapping (bools, strings) once implementation starts (§5.1)~~ — moot: `scipy` isn't used. The hand-written serializer's mapping is fixed by us and asserted by `test_matwriter.py`, and was checked against `loadmat` once in a throwaway venv
- [x] ~~Merge §9's proposed commands/events into `websocket-protocol.md`~~ — **done**, along with `starting-a-session.md` §9; the contract test covers every name across the doc, `protocol.py`, and `protocol.ts`
- [x] ~~**§8's Backup Directory mirroring is not built at all**~~ — **built.** Finalization queue, periodic `.tsv` mirror, and `ephymeris.db` backup with dated snapshots all live in `sidecar/ephymeris_sidecar/backup/`, covered by `tests/test_backup.py`. This also closes `cohorts.md` §12's `ephymeris.db` item
- [x] ~~Exact backup mirroring interval for `.tsv` beyond "every ~5–10s"~~ — **10 s, self-paced** (§8.2)
- [x] ~~Exact backup trigger cadence for `ephymeris.db` beyond "app start + every cohort-affecting write"~~ — **every commit, debounced 5 s, no timer** (§8.3). The original wording was also too narrow: `session_animal_runs` is written unattended and isn't a cohort edit
- [x] ~~`.tsv` files are opened in truncating write mode~~ — **exclusive create** (§7.1). A collision now fails the box with the offending path named, instead of truncating
- [x] ~~Small recovery utility to backfill `.json`/`.mat` from an orphaned `.tsv` after a crash, with `stop_reason: "recovered after crash"`~~ — **built** (§7.3): `sessions/recovery.py` + `sessions.recover`, covered by `tests/test_recovery.py`. It does share §8.1's walker — `reader._walk_format_dirs` now underlies both walks — and the shared traversal is what makes it date-spelling- and layout-agnostic. One refinement to the original wording: a `.tsv` that carries its footer keeps its recorded `stop_reason`; only a footer-less (genuinely crashed) log gets the `"recovered after crash"` marker
- [x] ~~`profileHash` on `SessionAnimalRun` (§4) is specified but not built~~ — **built.** Every run finalized from now on records the profile that decoded it. Runs recorded before this keep `null` and fall back to the current `task.json`, flagged in the UI (`analytics.md` §8.2)
- [ ] §8's mirroring is unit-tested but has not yet run a full session against a **real network share** — the slow-target behaviour it's designed around is the one thing a local-filesystem test can't exercise

---

**Next:** [analytics.md](analytics.md) — how everything written here is read back, scored, and visualized. Its §3 extends §6.5's metric definitions to recorded sessions.

Or jump to the [documentation index](README.md) · [Open items register](TODO.md) · [Engineering reference](reference.md)

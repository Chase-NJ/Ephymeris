# Tasks

Everything between "a box runs firmware that emits strobes" and "the app draws its trial flow and builds its `SET` lines". For maintainers and firmware authors. What the recorded values become on disk is [DATA.md](DATA.md); how a strobe stream is scored, live and in Analytics, is [ANALYTICS.md](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md); the session flow that sends the line is [ARCHITECTURE.md](ARCHITECTURE.md#session-lifecycle).

## Contents

- [Overview](#overview)
  - [Two places a value can come from](#two-places-a-value-can-come-from)
  - [The three bundled sketches](#the-three-bundled-sketches)
- [Firmware](#firmware)
  - [Guarded defaults](#guarded-defaults)
  - [Counts that move with their key lists](#counts-that-move-with-their-key-lists)
  - [Reward volume on the trial type](#reward-volume-on-the-trial-type)
  - [Selection modes](#selection-modes)
  - [Compiling and the host tests](#compiling-and-the-host-tests)
- [Sketch library](#sketch-library)
  - [Library roots](#library-roots)
  - [Folder rules](#folder-rules)
  - [Discovery](#discovery)
  - [Library states](#library-states)
- [Task profile](#task-profile)
  - [Top level keys](#top-level-keys)
  - [Config fields](#config-fields)
  - [Ramped values](#ramped-values)
  - [Strobes](#strobes)
  - [Live metric entries](#live-metric-entries)
  - [Utility controls and telemetry](#utility-controls-and-telemetry)
  - [Identify](#identify)
  - [Legacy names](#legacy-names)
- [Task definitions](#task-definitions)
  - [What a definition holds](#what-a-definition-holds)
  - [The field catalogue](#the-field-catalogue)
  - [Diagnostics](#diagnostics)
  - [Saving and regeneration](#saving-and-regeneration)
  - [Rebuilt bundled sketches](#rebuilt-bundled-sketches)
  - [The box utility](#the-box-utility)
  - [Order is meaning](#order-is-meaning)
- [Spine tasks](#spine-tasks)
  - [What a spine task holds](#what-a-spine-task-holds)
  - [Lowering](#lowering)
  - [The generated folder](#the-generated-folder)
  - [The runner](#the-runner)
  - [The snapshot](#the-snapshot)
  - [Spine diagnostics](#spine-diagnostics)
- [Rig wiring](#rig-wiring)
  - [The channel set and the pin map](#the-channel-set-and-the-pin-map)
  - [Registry rules](#registry-rules)
  - [The wiring page](#the-wiring-page)
  - [Wiring rules](#wiring-rules)
  - [The sync channel](#the-sync-channel)
  - [Moving the channel set between machines](#moving-the-channel-set-between-machines)
- [Strobe vocabulary](#strobe-vocabulary)
  - [Append only](#append-only)
  - [Editing the vocabulary](#editing-the-vocabulary)
  - [Moving codes between machines](#moving-codes-between-machines)
  - [Every declared code is emitted](#every-declared-code-is-emitted)
  - [Port slots](#port-slots)
  - [Onset codes](#onset-codes)
  - [Edge codes](#edge-codes)
- [The START line](#the-start-line)
  - [Three layer merge](#three-layer-merge)
  - [Building the line](#building-the-line)
  - [Confirming the parameters](#confirming-the-parameters)
  - [The length cap](#the-length-cap)
  - [SEED](#seed)
- [Profile and params hashes](#profile-and-params-hashes)
  - [A spine task's hash covers behaviour only](#a-spine-tasks-hash-covers-behaviour-only)
- [Derived state machine](#derived-state-machine)
  - [Why derived](#why-derived)
  - [The model](#the-model)
  - [Gates](#gates)
  - [Nodes and outcomes](#nodes-and-outcomes)
  - [One condition node](#one-condition-node)
  - [Live token](#live-token)
  - [Layout](#layout)
- [The Task tab](#the-task-tab)
  - [Landing](#landing)
  - [Editor](#editor)
  - [Trial types](#trial-types)
  - [Trial generation](#trial-generation)
  - [Ramp](#ramp)
  - [Parameter dial](#parameter-dial)
- [Writing a new sketch](#writing-a-new-sketch)
  - [Authoring steps](#authoring-steps)
  - [Verify](#verify)
  - [Troubleshooting](#troubleshooting)
  - [What raises](#what-raises)
  - [What degrades silently](#what-degrades-silently)

## Overview

A **task** is a sketch plus an optional `task.json` sibling that describes it (its *profile*). The profile is what lets the app render a config form, draw the trial-flow diagram, build the `START` command and score live metrics for a sketch it has never seen. A sketch with no `task.json` is fully supported: it gets a bare `START`, no form, and a raw scrolling strobe log instead of charts.

> [!IMPORTANT]
> **No sketch is special-cased in app code.** Drive everything off the profile. If you are about to write `if (sketchName === "GRGL")`, the profile is missing a declaration.

Operators do not write `task.json` by hand. They author a **task definition** on the Task tab and the app generates a sketch folder from it plus this rig's wiring ([Task definitions](#task-definitions)). A hand-written profile is for a firmware author adding a sketch of their own ([Writing a new sketch](#writing-a-new-sketch)).

### Two places a value can come from

Everything an experiment varies reaches the firmware one of two ways. Which way follows from what the firmware can accept, not from preference.

| | Arrives at | Carries | Changing it costs |
|---|---|---|---|
| **Generated headers** (`TaskPins.h`, `TaskTrials.h`) | compile time | channel→pin map, the strobe vocabulary, the trial table, how many ramp stages and trial types exist, which selector runs | a rebuild and reflash |
| **`SET` lines** | run time | every timing, hold, window, penalty, per-condition reward volume (`RW<n>`), pool weight (`PW<n>`), anti-bias clamp and stage threshold | a few serial lines, confirmed by the board before `START` |

The two roads to the board. The left one runs once per save or rewiring; the right one runs at every start:

```mermaid
flowchart LR
    subgraph compileTime["Compile time: rebuild and reflash"]
        definition["Task definition"] --> generator["taskdef generator"]
        wiring["Rig wiring"] --> generator
        generator --> headers["TaskPins.h<br/>TaskTrials.h"]
        headers --> binary["Flashed binary"]
    end
    subgraph runTime["Run time: SET lines, confirmed"]
        values["Merged parameter values"] --> line["SET lines"]
    end
    binary --> board["Mega2560"]
    line --> board
```

The dividing line is what a capped `SET` line can carry ([`SET_LINE_MAX`](#the-length-cap)): a trial table and a pin map do not fit, and pins must be compile-time constants anyway. Everything that fits stays on the wire, which is what lets **one flashed binary serve six boxes tuned differently** — the per-box overrides at mapping would otherwise mean six compiles.

### The three bundled sketches

| Sketch | Folder | What it is |
|---|---|---|
| **GRGL** | `Olfactory Behavior/GRGL/` | The one behavioural sketch. Covers discrimination, shaping and eased variants of either; every generated task is a copy of it with new headers. Its shipped `TaskPins.h`/`TaskTrials.h` are defaults, so a bare checkout runs the lab's historical 2-odor task. |
| **BOX_Utility** | `Utility/BOX_Utility/` | The resting baseline every idle box is returned to ([ARCHITECTURE.md](ARCHITECTURE.md#hardware-utility-baseline)). |
| **GRGL_Sim** | `Utility/GRGL_Sim/` | Drives a real box through a full session with no animal in it — valves, light, vacuum and fluid on this rig's pins. **Its fluid lines really open**: run it dry or with a catch vessel unless you mean to dispense. |

## Firmware

The firmware lives in `firmware/` ([its README](../firmware/README.md)); it was a separate repository until it was imported here with its history. A checkout's sidecar reads it in place, and `scripts/package-resources.mjs` copies it into the installer. **Edit firmware in `firmware/`**; there is no other copy to keep in step.

All trial logic lives in `libraries/BehaviorBox/BehaviorBox.h`: the serial helpers (strobe emitter, `START` reader, `STOP` poll), `TaskParams` and the one declarative wire-key list `TASK_PARAM_LIST` the `START` parser is generated from, the trial primitives (`TrialType`, `generateTrials`), the selection policies, and one `runTrial()` loop. That shared loop is why the state machine can be [derived](#derived-state-machine) rather than declared. The pinout is in `BoxPins.h`; the strobe codes are in no file of the firmware repo — the app generates them into `TaskPins.h`, and `BoxStrobes.h` only refuses to build without them.

A [spine task](#spine-tasks) runs none of that. Its runner is `libraries/BehaviorBox/BoxSpine.h`, around the phase interpreter's pure core `BoxInterp.h`, and it shares only the serial helpers and the `SET` handshake's pieces with `BehaviorBox.h`.

`emitStrobe()` also pulses a sync pin for electrophysiology alignment; see [RECORDING.md](RECORDING.md#the-sync-line).

### Guarded defaults

Every pin in `BoxPins.h` is `#ifndef`-guarded. Strobe codes are not defaults at all: `BoxStrobes.h` defines none and stops the build with an `#error` unless the generated `TaskPins.h` has already defined them ([Strobe vocabulary](#strobe-vocabulary)). A sketch includes the generated headers around the library:

```cpp
#include "TaskPins.h"    // pure preprocessor: pins, strobes, counts, selection mode
#include <BehaviorBox.h>
#include "TaskTrials.h"  // constructs TrialType, so it must come after
```

Whatever `TaskPins.h` declares wins; an unmentioned pin falls back to the box as built. A sketch built bare from `firmware/` therefore does not compile — build the folder the app generated. `TaskPins.h` must stay pure preprocessor — it is read before `BehaviorBox.h` has defined any type.

### Counts that move with their key lists

Two counts size arrays that the `START` parser writes into, so each must move with its key list(s) or a token writes past the end of an array:

| Count | Key list(s) |
|---|---|
| `NUM_STAGES` | `BOX_STAGE_KEY_LIST` |
| `BOX_MAX_TRIAL_TYPES` | **both** `BOX_POOL_KEY_LIST` and `BOX_REWARD_KEY_LIST` |

A key list shorter than its count only leaves slots unreachable; a longer one corrupts memory. The generator emits each count together with its list(s), which is the only reason the counts are safe to make variable. The unguarded defaults reproduce the historical line, so a sketch with no generated header parses exactly what it always did.

### Reward volume on the trial type

`TrialType::rewardTime` is the one non-const member. The compiled value is the profile's default, and `applyRewardTimes()` overwrites it from the `SET` lines (`RW<slot+1>`) before the first trial, so `deliverReward()` never consults `TaskParams` for it. The table is therefore `static TrialType kTrials[]`, not `const`.

### Selection modes

`BOX_SELECTION_MODE` picks one of three, all compile-time:

| Mode | Behaviour |
|---|---|
| `BOX_SELECT_ANTIBIAS` | Draw a side against the animal's recent bias, then a type uniformly within the side. Weights are ignored. |
| `BOX_SELECT_WEIGHTED` | The same side draw, then a type within the side by `poolWeights` (`WeightedAntiBiasSelector`; no virtuals, `TrialPolicy` still holds the base pointer). For showing a stimulus still being learned more often without giving up side balancing. A side whose weights sum to zero is drawn uniformly. |
| `BOX_SELECT_POOL` | A block-shuffled sequence built from `poolWeights` at `START`, exact proportions per block of `BS`, `NT` clamped to 1000. |

What each reads — the editor's [trial generation](#trial-generation) panel mirrors this by hand (`src/lib/taskdef/selection.ts`):

| | Anti-bias | Weighted | Pool |
|---|---|---|---|
| Side balancing (`BW`, `MCS`, `DBS`, `PMN`, `PMX`) | yes | yes | no |
| Row weights (`PW<n>`) | no | within a side | across the session |
| Block size (`BS`) | no | no | yes |
| Correction budgets (`CL`, `CR`) | yes | yes | no — `runTrial` gets no policy |
| Abstention escalation (`LAZY`, `LZS`, `LZM`, `LZG`) | yes | yes | no; `LZD` still applies, flat |
| No-go types presented | no — a withhold has no side | no | yes |

The three values are themselves guarded in `BehaviorBox.h`. A header that once omitted them made `#if BOX_SELECTION_MODE == BOX_SELECT_POOL` evaluate as `0 == 0`.

### Compiling and the host tests

> [!CAUTION]
> **`arduino-cli compile` will not tell you about a type error.** The AVR core builds with `-fpermissive -w`, so passing a `const TrialType*` where an `int` is expected is a warning the build then suppresses: you get a size report and exit 0 on wrong code. `GRGL_Sim` once compiled clean against a changed `AntiBiasSelector` signature while reading a truncated pointer as its trial count. After any shared-signature change, compile every sketch with `--warnings all` **and** run the host tests (`libraries/BehaviorBox/extras/host_test/run.sh` and `run_box.sh`), which build without `-fpermissive` and are the strictest check available.

The host tests compile `BehaviorBox.h` off-target against a minimal `Arduino.h` shim. They do not replace a real AVR compile and flash.

`run_interp.sh` tests `BoxInterp.h`, the phase interpreter's pure core ([ADR 0003](adr/0003-phase-spine-task-model.md)), which includes no Arduino header and needs no shim. `run_diff.sh` is the **differential test**: it runs that core and its Python port, `analytics/stream/replay.py`, over generated state tables and randomized input logs, and fails on the first tick where their actions differ. It then changes the Python tie rule and expects a difference, so a run that generates too few ties fails rather than passing on nothing. Change the header and the port together; the header documents the table format and the tick rules for both. A third of the differential test's tables are lowered by the generator itself (`taskdef/lowering.py`), so the tables a saved spine task compiles are held to both interpreters. Those tables hold no ties (a lowered state has at most one exit), so their family has a self-check of its own: with every RNG draw reflected, they must differ.

`run_spine.sh` tests `BoxSpine.h`, the runner around that core, on the instrumented shim with a hand-written table: the handshake, the stream's order and tick times, skipped `millis()` values, and the [session end rule](#the-runner). `sidecar/tests/test_spine_run.py` compiles a **generated** spine task the same way, plays its serial output through the real session path, and replays the `.tsv` that path wrote.

## Sketch library

Sketches **ship with the app**. There is no configured sketch directory: the library is a fact about the build, so adding or changing a bundled sketch needs a new build. Owned by `discovery.py`.

### Library roots

The bundled root is resolved in this order (`discovery.library_root()`):

| Priority | Source | Used by |
|---|---|---|
| 1 | `$EPHYMERIS_SKETCH_LIBRARY` | A developer pointing the sidecar elsewhere. An environment variable and **deliberately not a setting**, so a configurable directory cannot come back by the back door. Reported as `source: "override"`. |
| 2 | `$EPHYMERIS_BUNDLED_SKETCHES` | An installed build; set by the Tauri shell from its resource dir. |
| 3 | `<repo>/firmware` | A checkout, read in place. The only way `tauri dev` has a library. |

Two more roots are written by the app and scanned after the bundle. **Order is the whole algorithm** (`discovery.discover`):

| Root | Holds | Effect |
|---|---|---|
| `<data_dir>/rig/sketches/` | Bundled sketches rebuilt against this rig's wiring ([Rebuilt bundled sketches](#rebuilt-bundled-sketches)) | **Replaces** the bundled entry with the same category and name, keeping `source: "bundled"`. A rebuild is the same sketch with the right pins; offering both would make flashing a coin flip. A folder matching nothing in the bundle is reported, not offered. |
| `<data_dir>/tasks/` | Sketch folders generated from saved task definitions | **Appends**, as `source: "rig"`. A saved task *is* a discovered sketch, so flashing, the session flow, `tasks.getProfile`, `settings.taskDefaults` and Analytics need no special case. A name colliding with a bundled sketch is reported and dropped (saving already refuses it). |

### Folder rules

```
<library root>/
├── Olfactory Behavior/GRGL/     category / sketch (GRGL.ino, TaskPins.h, TaskTrials.h, task.json)
├── Utility/BOX_Utility/  Utility/GRGL_Sim/
└── libraries/BehaviorBox/       reserved; the one path passed to arduino-cli --libraries
```

> [!WARNING]
> **A folder is a sketch only if it holds a `.ino` whose name matches the folder's own** (`clean_flush/clean_flush.ino`, never `clean_flush/main.ino`). This is arduino-cli's rule, and the most common reason a sketch fails to appear. A folder that breaks it is **skipped and reported**, never silently dropped.

- **Categories** are any top-level folder other than `libraries/` (matched case-insensitively). Names are not hardcoded. A sketch's category is the folder **directly** containing it.
- **Sketches need a category.** A valid sketch at the root is reported as skipped.
- **Sketch folders are terminal.** Their contents (`src/`, `extras/`) are not scanned.
- **`libraries/` is reserved at every depth**, and only the root one goes to `arduino-cli`, so every sketch compiles against one collection. Put shared headers directly in it — plain folders of `.h`/`.cpp`, no `library.properties` needed, and no symlinks (fragile on the Windows lab machines).
- **Hidden folders** (leading `.`) are ignored silently, so `.git/objects` does not bury real problems.

### Discovery

The sidecar rescans on every `settings.push` (connect and every change), on `sketches.refresh`, after `tasks.save`/`tasks.delete`, and after a wiring rebuild, then broadcasts `sketches.updated`. There is no filesystem watcher; the library changes when the app does. The scan descends at most `MAX_SCAN_DEPTH` levels, follows symlinks but records every resolved directory so a loop terminates, and treats a folder with no `.ino` at all as plain organisation (not reported).

Skip reasons, each reported with its path:

| Reason | Meaning |
|---|---|
| `no <name>.ino matching the folder name` | Holds some `.ino`, just not the one arduino-cli needs |
| `sketch folders belong inside a category folder` | A valid sketch at the root |
| `couldn't be read: <error>` | Permissions or I/O failure |
| `a rebuilt copy of a sketch this version no longer ships` | A `rig/sketches/` leftover |
| `a bundled sketch is already called …` | A generated task shadowing a bundled name |

### Library states

`SketchLibraryStatus.state`, carried on the `settings.push` reply and on `sketches.updated`. Every non-ok state means a **broken or partial install**, never a wrong setting, so the copy points at reinstalling.

| State | Condition |
|---|---|
| `damaged` | Root missing, not a directory, or unreadable |
| `empty` | Readable, but no valid **bundled** sketch. A saved task does not rescue it: with no bundled `GRGL` there is nothing to generate from |
| `ok` | Sketches found. A non-zero `skippedCount` is a non-blocking "some items couldn't be read" note |

`source` records whether the root was the bundle or the developer override, so a bug report can say which library was scanned. `LibraryStatusNote` shows the state on the Task landing.

## Task profile

`task.json` sits **beside the `.ino`** and is **per sketch, never shared**: one file serving two sketches drifts out of sync with one of them. The parser `tasks/profile.py` (`parse_profile`) is the only enforcement point; `load_profile` returns `None` for a missing file and raises `TaskProfileError` for a broken one.

### Top level keys

| Key | Type | Default | Meaning |
|---|---|---|---|
| `taskName` | non-empty string | **required** | Display name |
| `kind` | `"behavior"` \| `"utility"` | `"behavior"` | Anything else raises |
| `config` | array | `[]` | Fields for the form, the `SET` lines and the session file |
| `strobes` | object, integer-string keys → names | — | **Ignored** in a sketch's `task.json`: filled from the [strobe vocabulary](#strobe-vocabulary) at load. Kept verbatim in a session snapshot |
| `liveMetrics` | array | `[]` | Rolling P metrics, and the gate on the diagram's condition rows |
| `controls` | array | `[]` | Utility profiles: Debug Mode widgets |
| `telemetry` | object | absent | Utility profiles: how to parse `STATUS` lines |
| `identify` | `{on, off}` | absent | Commands that make a box point at itself |
| `legacyNames` | array of strings | `[]` | Names older software wrote into a run's `sketch` field |
| `spine` | object | absent | A [spine task](#the-snapshot)'s snapshot: the definition, its state table and what each bit is. Written by the generator, passed through verbatim |

Unknown top-level keys are ignored. `kind` is a convention, not a schema gate: every key is read from every profile, and a utility profile's `liveMetrics` is simply never scored.

> [!CAUTION]
> **There is no `states` or `graph` key, and none should be added.** It would change `profile_hash` and split the sketch's runs in Analytics; see [Derived state machine](#derived-state-machine). A spine task's `spine` key is not that: it appears only on a profile generated from a spine definition, so no existing profile's hash moves.

### Config fields

Each `config` entry is a `ConfigField`:

| Key | Required | Rules |
|---|:---:|---|
| `metadataKey` | yes | The key the form collects under, and the key written **flat** into the session `.json`/`.mat` |
| `wireKey` | yes | The `START` token; must match what the firmware's `TASK_PARAM_LIST` parses |
| `type` | yes | `int`, `float`, `bool` or `string` |
| `label` | | Falls back to `metadataKey` |
| `default` | | Type-checked (`bool` is guarded separately, being an `int` in Python). A `string` default may not contain whitespace — the grammar is space-separated |
| `group` | | Section the field is filed under, the key the diagram's `governedBy` matches, and what `GROUP_ORDER` sorts |
| `unit`, `help` | | Non-empty strings |
| `min`, `max` | | Numbers, inclusive; the form **clamps, never rejects**. `min > max` raises |
| `step` | | A number; presentation only |
| `advanced` | | Strictly `true` collapses the field behind a disclosure |

> [!CAUTION]
> **Four silent-failure guards, enforced at parse time.** Each would otherwise yield wrong data, not an error:
>
> 1. **`wireKey` may not be `SEED`** — the host appends that token itself ([SEED](#seed)).
> 2. **`metadataKey` may not collide with a core session-file field** (`CORE_METADATA_KEYS` in `tasks/profile.py`, which includes the `intan_*` fields). Config merges in flat, so a collision would overwrite the core field.
> 3. **No duplicate `metadataKey`.**
> 4. **No duplicate `wireKey`.**

`to_json()` omits absent optional keys rather than emitting `null`, and emits `advanced` only when true. That keeps `profile_hash` stable for profiles that declare none of them.

**Every operator-tunable parameter is a config field.** The lab's profiles expose every timing, hold, window, penalty, reward volume, pool weight and stage threshold.

### Ramped values

> [!CAUTION]
> **A ramped value is declared per stage, never once.** The firmware rewrites `odorPokeHold`, `fluidWellHold`, `fluidWellPoll` and `odorPortTimeout` from `stage[]` on every completed trial. A single field for one of them would appear to work and then be **silently overwritten at the first stage boundary** (around trial 15–20 on the lab's schedules).

Each ramp row is a group of ordinary `int` fields with wire keys `S<n>P` (odor-poke hold), `S<n>H` (well hold), `S<n>W` (response window), `S<n>O` (odor-port timeout) and, for rows after 0, `S<n>T` (the completed-trial count at which the row engages). Row 0 is live from trial 0 and has no `T` field. The generator names the groups `Stage 0` … `Stage N`, or `Holds & windows` when there is only one row. A task that does not ramp declares row 0 only.

### Strobes

A profile does not declare strobe codes. `load_profile` fills `TaskProfile.strobes` with the machine's whole [strobe vocabulary](#strobe-vocabulary) — every live code and every retired one, code → name — and a `strobes` key still found in a sketch's `task.json` is ignored with a warning, once per file. The end-of-session code is found by **name**: the first entry whose name contains `END_SESSION`, which is how the runner knows to finalize.

Mission Control's strobe console, `liveTrials.ts`'s `vocabFrom` and the [state machine](#derived-state-machine) all key off this map, so it is always the full set. It used to be a hand-maintained copy in each `task.json`, and a partial copy degraded all three silently. What a sketch *presents* is stated by `liveMetrics`, never by which codes the map holds.

> [!IMPORTANT]
> **A session snapshot keeps its own map.** `parse_profile` without a vocabulary — an embedded profile in a session file, a stored `task_profiles` row — reads `strobes` verbatim, because that map is the record of what decoded the run and must survive the vocabulary being edited afterwards ([DATA.md](DATA.md#the-embedded-task-profile)).

### Live metric entries

```jsonc
{ "id": "p_r_odor1", "label": "P(R | Odor 1)",
  "trigger": "ODOR_1_ON", "success": "WATER_POKE_R", "alternate": "WATER_POKE_L", "windowSize": 20 }
```

Each code is named, and resolved against the vocabulary at load; a name that is not a live code raises. The numeric keys (`triggerCode`, `successCode`, `alternateCode`) still parse, because every recorded snapshot carries them, and `to_json` always writes numbers — so the two spellings of one metric hash the same. A metric with a single alternate writes `alternateCode` alone; one with several also writes `alternateCodes`.

| Key | Required | Notes |
|---|:---:|---|
| `id` | yes | A stable identifier only. A generated profile numbers them (`p_correct_1`), which names no condition |
| `trigger` (or `triggerCode`) | yes | Opens a trial for this metric |
| `success` (or `successCode`) | yes | Scores a hit |
| `alternate` (or `alternateCode`) | yes | Scores a miss (still in the denominator). A name, or a list of names when several codes miss: a no-go type misses at every response port. `alternateCodes` is the numeric list; `alternateCode` repeats its first |
| `label` | | What every readout titles the metric with. Falls back to `id`; a generated profile builds it from the trial type's required name |
| `windowSize` | | Default 20, matching the firmware's anti-bias `biasWindow` default |

> [!IMPORTANT]
> **`liveMetrics` order is load-bearing**, and the array does double duty: besides scoring, it is the gate that decides which declared odor codes become drawn conditions ([Gates](#gates)). One metric per condition actually presented.

Scoring semantics are in [ANALYTICS.md](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#trials-hits-misses-and-exclusions).

### Utility controls and telemetry

A `"kind": "utility"` profile makes a priming, cleaning or self-test sketch first-class in Debug Mode. Utility sketches run in `PASSTHROUGH`, so their controls and status ride the passthrough primitives: **no new wire commands, and nothing they emit is stored.**

| Control `type` | Renders as | Sends | Requires |
|---|---|---|---|
| `button` | a button | its `command` | non-empty `command` |
| `select` | a dropdown | the chosen option's `command` | non-empty `options[]`, each with a `command` |
| `grid` | one row per channel with a state lamp | that row's `toggle` or `pulse` | non-empty `channels[]`; each needs a `label` and at least one of `toggle`/`pulse` |

![Debug Mode for box 3 on BOX_Utility: buttons for Full self-test, Stop test and All off, a pulse-width dropdown, a Prime block, and grid rows with a lamp and switch for each fluid line, the vacuum, the trial light (lit, "1 open") and twelve odor lines](images/debug-mode.webp)

*`BOX_Utility`'s profile rendered in Debug Mode: `button`s, a `select` for the pulse width, and `grid`s whose
section headers count what is open. Prime is the app's own control
([ARCHITECTURE.md](ARCHITECTURE.md#running-a-task-from-debug-mode)), not a profile control.*

`grid` exists because "which solenoid is energized right now" on a fluid rig is a safety readout, not a convenience. A row with neither `toggle` nor `pulse` is rejected rather than rendered as inert decoration. A missing `state` leaves the lamp neutral rather than claiming "closed" — not reported and closed are different facts.

`telemetry` is `{ match?: string (default "STATUS"), fields?: [{key, label?}] }`. The app finds the newest `port.output` line beginning with `match`, parses space-separated `key=value` pairs, and shows the declared fields. **`STATUS` values cannot contain spaces.** Prose belongs in ordinary `Serial.println` lines, which land in the console.

### Identify

```jsonc
{ "identify": { "on": "ON trial_light", "off": "OFF trial_light" } }
```

The two commands that make a box announce itself, used by the utility baseline's `utility.identify` and the guided placement walk ([ARCHITECTURE.md](ARCHITECTURE.md#hardware-utility-baseline)). Keeping them in the profile is what lets the walk work on a rig that signals with a buzzer, another LED, or not at all. **Both halves are required together** — a box that can be lit but not unlit would announce itself indefinitely. Omitting the block is normal: that box simply cannot be asked. For the box utility it is generated, on the rig's first `cue` channel ([The box utility](#the-box-utility)). `identify` is not the same as that channel's row in a `grid`: that is a manual control; this is a contract the app drives on its own.

### Legacy names

A finalized run records `sketch` as a name, and the archive walk resolves it to a profile ([DATA.md](DATA.md#reading-the-archive)). For anything this app wrote, the name is the folder's. Data from earlier software records labels like `"Shape - L"`; `legacyNames` maps them.

> [!IMPORTANT]
> **Declared, never inferred.** Matching `"Shape - L"` to a sketch by resemblance would decode real data with the wrong strobe map and produce confident wrong numbers. The mapping is a one-line assertion by someone who knows, reviewable in a diff.

> [!CAUTION]
> Removing a sketch from the bundle, or deleting a `legacyNames` entry, makes every archived run recorded under that name stop decoding against its profile — **with a warning, not an error**. `tests/test_bundled_library_covers_archives.py` pins the names the lab's real archives contain; keep it current when a new archive appears.

The bundled `GRGL/task.json` declares the lab's historical names (`GRGL_2-Odor`, `GRGL_2-Odor_EZ`, `shaping_GR`, `shaping_GL`, `shaping_GR_EZ`, `shaping_GL_EZ`, `Shape - R`, `Shape - L`). A saved task can re-declare them in its Details card. Only the archive walk reads this key; an unresolvable name is not an error and falls through to inference.

## Task definitions

A **definition** is the operator's document, authored on the Task tab. The app generates the sketch and its `task.json` from it plus this rig's wiring (`sidecar/ephymeris_sidecar/taskdef/`). Wire commands: [PROTOCOL.md](PROTOCOL.md#task-profiles).

```
<data_dir>/tasks/
    <id>.json                  the DEFINITION — the only thing worth preserving
    <category>/<name>/         the GENERATED sketch folder, a build output
        <name>.ino             the bundled GRGL root, copied verbatim
        TaskPins.h             pins, strobes, counts, selection mode
        TaskTrials.h           the trial table
        task.json              an ordinary profile, read by ordinary code
```

The two halves are kept apart so "regenerate everything" can never mean "delete the operator's work". The generated folder is rewritten whole; nothing hand-edited there survives.

### What a definition holds

Four answers, nothing derivable (`taskdef/model.py`):

| Field | Holds |
|---|---|
| `trials[]` | Each row names an **odor channel**, a **response channel**, a **reward channel** and an **onset strobe** (go rows; a no-go row has neither response nor reward), plus its own `rewardTime`, `weight` and required `label`. The onset strobe is still stored on the row — the format, the generator and `profile_hash` are unchanged — but the editor sets it from the line's declared onset ([Onset codes](#onset-codes)) |
| `selectionMode` | `antibias`, `weighted` or `pool` ([Selection modes](#selection-modes)) |
| `stages[]` | The ramp, at least one row |
| `params{}` | Only what **diverges** from the field catalogue's default |

Plus `id`, `name` (becomes the sketch folder and must be a legal folder name), `category`, `legacyNames` and `notes`.

A definition stores **channel names and strobe code names, never pins or numbers.** That indirection makes "odor line 3 means go-left on this rig" an edit to one document rather than to firmware, and lets a rewiring be costed before it is written.

> [!CAUTION]
> **`params` holds only divergences**, for the same reason `settings.taskDefaults` does. Storing the merged set would mean a catalogue change — a corrected range, a better help string — could never reach a saved definition.

**Reward volume and weight live on the row, never in `params`.** The generator reads `reward_time`/`weight` off each `TrialTypeDef` and emits `RW<i+1>`/`PW<i+1>` from the same loop that emits `kTrials[i]`, so a `params["reward_time_1"]` or `params["pool_weight_1"]` is accepted and ignored. The editor offers these only on the row and never writes them into `params` (`isRowOwnedField`, `src/lib/taskdef/lines.ts`). A value on the row is a property of that condition: two conditions paying from one fluid line can pay differently, and deleting the row takes its volume with it.

**There are no presets.** A task is built from scratch. What a preset would seed that matters most is a condition's *name*, which differs on every bench, and a guessed name is wrong for everyone but its author. The lab's real historical definitions survive as test data in `sidecar/tests/fixtures/task_definitions.py`, each transcribed from the sketch it replaced — a generator change that breaks one breaks something the lab actually ran.

### The field catalogue

`taskdef/fields.py` declares every scalar tunable once — wire key, label, unit, range, prose — and every generated profile is built from it, so two profiles differ in values and trial table, never in what a parameter means. Three count-dependent families are not in it, because only the definition knows how many exist: ramp rows, pool weights (one per trial type) and reward volumes (one per go trial type).

> [!CAUTION]
> **`fields.py` is a cross-repo mirror of `TASK_PARAM_LIST` and nothing enforces it at runtime.** A key it declares that the firmware does not parse is sent and **silently ignored**; the session runs on the compiled-in value with nothing reporting a problem.

### Diagnostics

`taskdef/validate.py` reports every problem, not the first. `tasks.preview` returns them as the operator types; `tasks.get` recomputes them, because most depend on the **wiring** and a task saved clean can be broken by a rewiring it never saw.

| Code | Problem | Consequence without it |
|---|---|---|
| `TSK101` | A channel this rig does not have (or an unfinished row) | The pin never fires |
| `TSK102` | A channel of the wrong kind | A valve driven as a sensor |
| **`TSK103`** | **A reward line serving the other well** | The row reads "→ left", the animal answers left, water arrives on the right |
| `TSK104` | A strobe code the vocabulary does not declare | An unlabelled number in the data |
| **`TSK105`** | **Two trial types on one odor line** (one line declares one onset code) | Two conditions, one label, pooled by every analysis |
| `TSK106` | A ramp not strictly ascending after row 0 | `liveStage()` scans down, so the row never engages |
| `TSK108` | No presentable trial — a row is presentable exactly when the generator emits it (`taskdef/rows.py`), so go rows with no usable response port, reward line or slot count for nothing; so does a table of only no-go types outside pool, since both anti-bias selectors draw a side first | A session that runs nothing |
| **`TSK109`** | **All pool weights zero** (pool), or **a side whose go types all weigh zero** (weighted) | The firmware falls back to a uniform draw while the table says otherwise |
| `TSK110` | A condition with no name | Every readout titles it after whichever channel carried it |
| `TSK111` | Two conditions sharing a name (case- and whitespace-insensitive) | Two curves under one title |
| `TSK112` | An onset code no live metric scores — **derived client-side** in `routes/TaskEditor.tsx` | The condition silently drops out of the diagram |
| **`TSK113`** | **A go condition paying 0 ms** | A dry well every readout scores as rewarded |
| **`TSK114`** | **An onset code that is not its line's declared one** ([Onset codes](#onset-codes)) | Every session records one bottle under another's name |

> [!CAUTION]
> **`TSK103`, `TSK105`, `TSK109`, `TSK113` and `TSK114` produce plausible wrong data rather than a failure.** Read them first.

**Every trial type must be named.** The name is the one thing the trial table cannot derive, and the metric label built from it titles Mission Control's live sparkline, the learning curve and a strategy axis. Two kinds of name meet here and must stay apart: the **rig's channel label** ("sandalwood") belongs to the wiring and never enters the profile; the **row's name** ("Go right") is the condition and does.

A definition with diagnostics **still saves, and still generates a flashable sketch**: a half-finished task must be savable. Nothing refuses to flash it either — the editor says "it will still flash" — so the diagnostics are the operator's warning, not a lock. `tasks.save` refuses only a name that collides with a bundled sketch or (case-insensitively) another saved task, because two tasks with one name share a sketch folder and saving one would overwrite the other's firmware.

### Saving and regeneration

A saved task's folder is regenerated on `tasks.save`, at **every sidecar start**, on every `hardware.save`/`hardware.reset`, and on every [vocabulary edit](#editing-the-vocabulary).

- **At start**, because a folder written by an older generator either stops compiling (loud — `TrialType` grew an argument) or sends keys the firmware no longer parses (silent).
- **On a wiring change or a vocabulary edit**, because pins and strobe codes are compiled into `TaskPins.h`.

A wiring change, from the Rig tab's save to the rescan, is all one [rig definition write](#the-rig-definition), including the [edge codes](#edge-codes) it issues (`RigDefinition.save_wiring` / `reset_wiring` in `rig/definition.py`). A vocabulary edit joins at the rebuild after installing its document. Startup runs the same two rebuilds (`rebuild_at_startup`), before anything can flash:

```mermaid
flowchart TD
    save["hardware.save"] --> inuse{"Session set up<br/>or a box running?"}
    inuse -->|yes| busy["RIG_IN_USE<br/>nothing written"]
    inuse -->|no| check{"Pins confirmed if asked,<br/>schema, RIG101–RIG107?"}
    check -->|"pins unconfirmed, or a rule broken"| blocked["RIG_SAVE_BLOCKED<br/>nothing written"]
    check -->|"not a rig document"| invalid["RIG_INVALID<br/>nothing written"]
    check -->|"yes"| impact{"Would it newly break<br/>a saved task?"}
    impact -->|"yes, without confirm"| refuse["RIG_WOULD_BREAK_TASKS<br/>nothing written"]
    impact -->|"no, or confirm: true"| write["Issue edge codes, record the digest,<br/>write wiring.json in one step"]
    reset["hardware.reset"] --> inuse
    write -->|"written"| install["set_rig_source:<br/>ChannelMap cache cleared"]
    install --> rebuild["RigDefinition._rebuild"]
    vocab["strobes.add / retire / remove …"] --> vinstall["set_vocabulary_source:<br/>vocabulary cache cleared"]
    vinstall --> rebuild
    rebuild --> tasks["Regenerate every saved task"]
    rebuild --> bundled["Rebuild every bundled sketch<br/>that includes TaskPins.h"]
    tasks --> rescan["Rescan the library"]
    bundled --> rescan
```

> [!CAUTION]
> **A wiring change or a vocabulary edit must rebuild every stored profile AND every bundled sketch, and the failure is invisible if it does not.** A stale folder still compiles and runs; the only symptom is a valve that never fires or an event decoded under the wrong name. Both rebuilds go through the one call site `RigDefinition._rebuild` (rebuild, then rescan), because splitting it into two calls is how one eventually gets forgotten.

### The rig definition

The [rig definition](../GLOSSARY.md#rig-definition) is the rig wiring plus the strobe vocabulary in force: everything a generated sketch takes from the rig rather than from its task. `rig/definition.py` owns it; `rig/registry.py`'s `channels()` and `vocabulary()` are how everything reads it.

**A preview asks about a hypothetical without installing it.** `hardware.preview`, `hardware.save`'s impact check and `strobes.usage` validate every saved task under a hypothetical wiring or vocabulary (`definition.impact_of`) and report only what it would *newly* break. The hypothetical lives in a `ContextVar` (`registry.hypothetical`): the code that installed it, and the `asyncio.to_thread` worker it runs in, see it; a rebuild, a session's profile load or anything else reading at the same moment sees the definition in force ([ADR 0001](adr/0001-rig-definition-hypotheticals-are-context-local.md)).

> [!CAUTION]
> **Never answer "what if" with `set_rig_source` or `set_vocabulary_source`.** They change the definition every thread reads. A rebuild reading it then writes the previewed pins or codes into `TaskPins.h`, and the sketch compiles. The same holds for starting a plain `threading.Thread` inside `registry.hypothetical`: it begins with an empty context and reads the definition in force, so its answer is silently about the wrong rig.

**The in-force values are cached, and a cache never keeps a value composed before a clear.** `set_rig_source` / `set_vocabulary_source` drop the cache and bump a generation; a reader that began composing from the old document returns its value without storing it.

**A write runs end to end, alone.** Every command that rewrites a generated folder is a rig definition write: `hardware.save` and `hardware.reset`, every vocabulary edit, `tasks.save` and `tasks.delete`. Each takes `RigDefinition.writing()` and holds it through judge → store → install → rebuild → rescan → announce, so no second write, reset or task save interleaves with a rebuild.

**Everything that uses a generated folder holds `RigDefinition.reading()`** for as long as it uses it, including any belief it records about what a board now carries: a flash from the discovery lookup through the record `PortManager.flash` writes and `utility.note_flashed`, a utility restore through that same record, `port.sendStart`, confirm mapping from the first profile read until the rig is held, `tasks.getProfile`, `strobes.usage`, and every rescan outside a write. So a write waits for flashes already in progress (at most one per box, though restores on different boxes run side by side), and a flash, a `START` or a mapping waits for a write. A waiting write goes before readers that arrive after it, so a stream of restores cannot starve a save. Commands that may wait carry long client timeouts (`client.ts`). Reads of the registries alone — `tasks.list`, `tasks.get`, the previews — take nothing. **Analytics is the one reader that takes nothing**: a cold index runs for minutes and would stall every save; it decodes from each run's own profile snapshot first.

**No write while a session is set up or a box is running** (`RIG_IN_USE`; `STROBE_SESSION_RUNNING` for the vocabulary). The session read its profiles from these folders at mapping and will flash from them; a running box was flashed from them. It is checked once before waiting and again once the write holds the lock — the check that counts, since a mapping confirmed while the write waited is exactly the case.

> [!CAUTION]
> **Never use a generated folder outside `reading()`, and never call `RigDefinition` writes or `reading()` from inside a write.** The first lets a rebuild delete a folder mid-compile or undo a box's belief about what it carries; the second waits on itself (the lock refuses re-entry rather than deadlock). `SketchLibrary.rescan` takes no lock for that reason: writes call it.

### Rebuilt bundled sketches

The shipped sketches compile against `BoxPins.h`'s defaults — the box as built. On a rewired rig that is silently wrong: `utility.identify` lights whatever is on the old trial-light pin and `GRGL_Sim` opens whatever is on the old odor line. So `taskdef/bundled.py` rebuilds them into `<data_dir>/rig/sketches/<category>/<name>/` with a generated `TaskPins.h`, served in place of the original.

| Rule | Why |
|---|---|
| **Opt in by `#include "TaskPins.h"`** in the `.ino` | Read from the source, so there is no manifest to drift. A test asserts every bundled sketch that drives a pin opts in. |
| **Pins and the vocabulary** (`bundled_pins_h`) | No counts or trial table — those are what a task adds — but every live code, since `BoxStrobes.h` defines none. |
| **Always rebuilt from the bundle** | `repin` refuses a source inside the rebuild root, since it clears the target before copying. |
| **On failure the bundled entry stands** | And refuses to compile at `BoxStrobes.h`, loudly — a refused flash with a reason beats firmware strobing numbers the machine decodes differently. |

### The box utility

`BOX_Utility` is the resting firmware on every idle box and Debug Mode's control panel: it latches and pulses outputs, primes lines, and runs a hardware self-test. **Nothing in it describes the box.** The logic is written once in the library's `BoxUtility.h` and host-tested (`extras/host_test/run_box.sh`, against a deliberately smaller fixture box). What the box *is* comes from the rig, through `taskdef/utility.py`, whenever the sketch is rebuilt (every start, wiring change and vocabulary edit, the same triggers as any [rebuilt bundled sketch](#rebuilt-bundled-sketches)).

```mermaid
flowchart LR
    rig["Rig page<br/>channels, pins, labels"] --> gen["taskdef/utility.py"]
    tmpl["firmware/Utility/BOX_Utility/task.json<br/>buttons, pulse select, legacyNames"] --> gen
    gen --> h["UtilityChannels.h<br/>one row per output and beam"]
    gen --> tj["task.json<br/>+ grids, beam fields, identify"]
    h --> eng["BoxUtility.h<br/>commands, STATUS, self-test"]
    tj --> dm["Debug Mode panel"]
```

| From the rig | Becomes |
|---|---|
| Every `emitter`, `reward`, `cue` and `vacuum` channel, in declaration order within its kind | An output row: its **channel name** is the command token (`PULSE fluid_2`) and STATUS key (`fluid_2=1`); its **Rig label** names it in the self-test and the Debug Mode grid (a reward line adds its well) |
| Every `engagement` and `response` channel | A beam: a STATUS key, a telemetry field, a prompted step in the self-test |
| The first `cue` | The `identify` pair (`ON trial_light` / `OFF trial_light`) |
| `sync` | Nothing. A pulse on it would be an edge in a recording |

- **Opt-in is the include.** A sketch whose `.ino` includes `UtilityChannels.h` is generated (`wants_utility`), as one including `TaskPins.h` is re-pinned. The shipped `UtilityChannels.h` declares nothing, so a bare build stops at `BoxUtility.h`'s `#error`.
- **The profile is merged, not replaced.** The folder's own `task.json` keeps what does not depend on the box. The generator adds three grids (`fluids`, `aux`, `emitters`) whose rows carry an explicit `kind`, beam telemetry fields and `identify`. `fluids` keeps its id because Prime finds the reward grid by it.
- **The self-test follows the table.** Stimulus lines fire with the vacuum energised, reward lines pulse one by one with their labels printed, each cue blinks, then every beam must read clear at rest and break when prompted. The tally is one check per beam plus the rest check.

### Order is meaning

Two orderings carry meaning and both are emitted from a single pass so they cannot disagree:

- **Odor index.** `Odors[i]` is odor line i+1, and the pins are not monotonic past line 6. Use `ChannelMap.declared_of_kind()`, never `of_kind()` (which sorts by pin) — the wrong one swaps lines, drives the wrong valve and announces it with the wrong onset code while every trial looks correct.
- **Trial-table slot.** Slot i is `kTrials[i]`, is `poolWeights[i]` (wire `PW<i+1>`), and is `rewardTimes[i]` (wire `RW<i+1>`). Reordering the table re-weights a pool task and re-pays every condition, which is why the trial table has no drag handle.

## Spine tasks

A **spine task** is ADR 0003's model, one tracer ahead of the rest: an ordered spine of phases, lowered by the generator to a state table that one interpreter walks ([ADR 0003](adr/0003-phase-spine-task-model.md)). It needs no firmware written for it. The definition is saved with `tasks.save` like any task, and its folder is generated, flashed and run through the ordinary session flow. Nothing in the app names a sketch: what a spine task does differently is read from its definition and its profile. The Task editor does not edit one yet, so today a spine definition is written as JSON.

The tracer has limits, and each is diagnosed rather than guessed around:

- the phases are Wait, Present, Delay, Outcome and ITI;
- a task has one row and one block;
- nothing is scored live yet: Mission Control says so, from the profile (`src/lib/sessions/liveScoring.ts`);
- it is proven on the host, not yet on a Mega: the free RAM a board reports with a table loaded is still to be measured ([README.md](../README.md#not-yet-done)).

### What a spine task holds

A definition with a top-level `spine` key is a spine task (`taskdef/model.py`, `Spine`). Without that key a definition is exactly what [What a definition holds](#what-a-definition-holds) describes, byte for byte.

| Field | Holds |
|---|---|
| `slots[]` | The spine's roles, each `{id, type}` with type `digital_in` or `digital_out` |
| `spine[]` | The phases, in order. Each `{phase, …}`:<br>• `wait` moves on at a rise on input slot `on`, with an optional `timeoutMs` that goes to the ITI;<br>• `present` lasts `ms`, and `abortOnRelease` names an input slot whose release aborts to the ITI;<br>• `delay` lasts `ms`;<br>• `outcome` opens output slot `line`, then waits `ms`;<br>• `iti` lasts `ms`.<br>Any phase may name `outputs`, the output slots HIGH while in it |
| `rows[]` | One row: a stable `id`, a required `name`, `bind` (slot → channel name), `rewardMs`, and `rewardPermille` |
| `blocks[]` | One block: `{id, rows: [the row's id], trials}` |
| `params{}` | Only divergences from the defaults the spine itself states, keyed by metadata key |

Plus `id`, `name`, `category`, `legacyNames` and `notes`, as for any task. A slot binds a channel by **name**, never a pin.

### Lowering

`taskdef/lowering.py` writes each phase as states, as `BoxInterp.h`'s *Lowering the first phases* describes. It is pure and standard-library only, so the differential test loads it by path and holds its tables to both interpreters ([Compiling and the host tests](#compiling-and-the-host-tests)).

- **Channels are bits.** Input bit i is the i-th `digital_in` slot and output bit j is the j-th `digital_out` slot, in slot order. No pin enters the table.
- **Every duration and probability is a parameter slot**, set by a `SET` line. One table therefore serves every tuning and every pin map.

| Slot | Wire key | Metadata key | What |
|---|---|---|---|
| 0 | `NT` | `block_trials` | The block's trial count. The session ends at the start of the next trial |
| 1… | `T<i>` | `<phase>_<i>_ms`, or `wait_<i>_timeout_ms` | Phase i's timer, one per timed phase |
| then | `RW1`, `RP1` | `reward_ms`, `reward_permille` | The row's reward time and probability, when the spine has an Outcome |

- **The ITI comes last.** A spine ends in exactly one ITI, which is where every abort and timeout goes; its timer leads back to state 0, which starts a trial.
- **The Outcome's states.** An Outcome is a chance state on `RP1`, recording the outcome class `correct`, then the reward line's state (`RW1`), then the class timeout. The phase's own `outputs` stay HIGH through all of it, the reward included.
- **Outcome class numbers** come from `lowering.OUTCOME_CLASSES` and are append-only.

### The generated folder

```
<data_dir>/tasks/<category>/<name>/
    <name>.ino      five includes and two calls: box_spine::setup(), box_spine::loop()
    TaskPins.h      this rig's pins and every live strobe code, as for any task
    TaskSpine.h     the state table, the channel rows, the parameter keys (preprocessor only)
    task.json       the profile, carrying the spine snapshot
```

`TaskSpine.h` names each channel's edge codes as `BF_<NAME>` macros, which `TaskPins.h` defines from the vocabulary. So **no code number is written for a spine task**, and a code the vocabulary lacks does not compile. A folder that cannot run (a slot bound to nothing, an edge with no code, a structural code missing) is still written, with an `#error` naming the reason, so it refuses to compile rather than strobing what nobody declared.

### The runner

`libraries/BehaviorBox/BoxSpine.h` is the one runner of every spine task: the hardware layer around `BoxInterp.h`'s pure core.

- **Inputs.** Each input is read and debounced every loop pass, by its channel's `active_level` and `debounce_ms`.
- **Ticks.** The core is stepped once per millisecond of `millis()`, including each value AVR `millis()` skips.
- **Outputs and strobes.** The runner drives each tick's outputs, then strobes the tick's actions, each stamped with the tick.
- **The handshake.** It is the one in [Confirming the parameters](#confirming-the-parameters), over the table's parameter slots. A value is held only when it is a whole number within its slot's declared range; otherwise the board answers `CLAMPED` and the start is refused.
- **The announcement.** The runner announces `INTERP=2`.

**The stream** holds only what the board observed and what it did. Within a tick it runs in this order:

1. `START_SESSION`;
2. watched inputs that rose (the channel's `enter` code), then those that fell (`exit`);
3. `TRIAL_START`;
4. outputs driven LOW (`off`), then outputs driven HIGH (`on`).

An edge on an input no state is watching is never strobed: the interpreter ignores it, so replay needs only what was strobed. The structural codes are the vocabulary's `START_SESSION` and `END_SESSION` (the ADR's SESSION_START and SESSION_END, the same events) and `TRIAL_START`. No outcome or state code is ever strobed.

> [!CAUTION]
> **The session end rule is part of what replay reproduces.** The session ends at the tick that would start trial `NT`+1, or at the first trial start after `STOP`. At that tick the board strobes the tick's watched input edges, then the `off` code of every output still HIGH, then `END_SESSION`. It does not strobe `TRIAL_START` and does not drive the new trial's outputs. Change the rule in `BoxSpine.h` and in `analytics/stream/spine.py` together, or every run's last tick reads as a divergence.

`STOP` is honoured at a trial boundary, as with the trial runner. A spine whose first phase waits forever, with no animal poking, therefore ends only when End Session forces it.

### The snapshot

The profile's `spine` key is everything replay needs that the run's own header does not already hold:

- the definition's slots, phases, rows and blocks;
- the table exactly as lowered, with its `interp`;
- each bit's channel and edge code **names**;
- each parameter slot's wire key;
- the structural code names.

It rides in the `# task_profile:` header line of every run's `.tsv` ([DATA.md](DATA.md#the-tsv-log)), beside the parameter values, the seed and `# interp: 2`, so a crashed run's `.tsv` alone replays. Code numbers come from the snapshot's own `strobes` map, which is the vocabulary when the run started. `analytics/stream/spine.py` reads a run's document back into the table, parameters, seed and input edges, and predicts every strobe the board must have sent ([ANALYTICS.md](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#the-folder-at-a-glance)).

`profile_hash` hashes the snapshot for its behaviour only: row names and the profile's other words for a person are left out of the hash, never out of the snapshot ([A spine task's hash covers behaviour only](#a-spine-tasks-hash-covers-behaviour-only)).

### Spine diagnostics

`taskdef/spine.py` judges a spine task in place of the `TSK1xx` rules ([Diagnostics](#diagnostics)). As there, a task with problems still saves.

| Code | Problem | Consequence without it |
|---|---|---|
| `SPN101` | A slot bound to no channel, or to one this rig lacks | A role with no pin |
| `SPN102` | A channel whose type is not the slot's, or the sync line | A sensor driven as a valve; a pulse in a recording |
| **`SPN103`** | **A channel edge with no live code.** The shipped channel set names none, so the rig's first wiring save issues them ([Edge codes](#edge-codes)) | An edge recorded as a number nothing decodes |
| `SPN104` | The vocabulary lacks `START_SESSION`, `TRIAL_START` or `END_SESSION`. A machine seeded before `TRIAL_START` existed adds it on Task > Strobes, at the number the shipped vocabulary gives it (`rig/schema/strobe_vocab.default.json`) | A stream with no trials in it |
| `SPN105` | A spine of the wrong shape: an unknown phase, no ITI or not last, a slot of the wrong direction, a missing duration | A table the interpreter cannot walk |
| `SPN106` | More than one row or block, a block that does not draw the row, a trial count or probability out of range | What the tracer cannot express yet |
| `SPN107` | Two slots on one channel | One pin, two roles |
| `SPN108` | A row with no name | Every readout titled after nothing |

## Rig wiring

The rig's description of itself lives in `sidecar/ephymeris_sidecar/rig/` and `hardware/`. Wire commands: [PROTOCOL.md](PROTOCOL.md#rig-wiring). Box↔board bindings are a different, runtime wiring ([ARCHITECTURE.md](ARCHITECTURE.md#boxes-and-boards)); this one is compile-time input to every generated sketch.

### The channel set and the pin map

| File | Says | Owner |
|---|---|---|
| `rig/schema/channels.v1.json` | **What a channel means**: `kind`, `well`, `port_slot`, `onset_strobe`, and the channel-set fields | shipped |
| `rig/hardware/<pinout>.json` (selected by `_default.json`; `$EPHYMERIS_PINOUT` for tests) | **Where it is** on this box generation: a literal transcription of the firmware pinout | shipped |
| `<data_dir>/hardware/wiring.json` | This rig's own wiring, as two documents in one file: **the channel set** (`channels`: what each channel is, no pins, the half meant to be the same on both lab machines) and **the pin map** (`pins`, `board`, `pin_range`: where each channel is on this box, never leaving the machine) | operator |
| `<data_dir>/wiring-confirmed.json` | The content digest of the last wiring saved, or confirmed, on this machine: the only wiring that may be put in force (see the caution below) | sidecar |
| `<data_dir>/wiring-record-started` | That this data dir has started a build that keeps the record: with the database's mark, what rules out a first start | sidecar |

A second box generation is a one-file pinout swap, *provided the channel names are the same*. Resolving by name is what makes that work.

The operator's pair **replaces** the shipped pair rather than merging with it. A merge would bring back a channel someone deleted, and it could not describe a box that lacks one.

The editor and the wire see the same **one document**, `{rig_version, channels, pins, …}`. In code, `hardware/store.py`'s `split` and `join` turn it into the two documents and back.

> [!CAUTION]
> **The two documents are saved as one file, in one step, and stored wiring that will not load, or that nobody saved or confirmed on this machine, never runs.**
>
> - **Why one file.** Two files can be torn by a failure between their writes. A new channel set read against old pins can put a swapped port under the other port's codes: every poke is then recorded under the wrong family, with no error anywhere.
> - **How a save writes it.** It writes `wiring.json.part`, fsyncs it and renames it over the old file. A failure up to the rename leaves the previous file whole. Once the rename lands the save is committed and its wiring is installed; the folder fsync that follows is best effort, and a failure there is logged as a warning.
> - **Only the wiring last saved here is put in force.** `<data_dir>/wiring-confirmed.json` records the content digest of the last wiring saved on this machine, and no other; a save with `confirmedPins` is how a confirmation lands, so it is recorded the same way. Stored wiring that passes every check but that the record cannot vouch for is **[held](../GLOSSARY.md#held-wiring)**: copied in (as `wiring.json`, `rig.json` or the two-file pair), edited by hand, fixed by hand after a failed load, a layout a later save replaced, or the wiring saved here when a save after it did not finish. Held wiring is treated like wiring that did not load, below, and RIG108 asks for its pins.
>   - **A restart never confirms anything.** Held wiring stays held at every start until it is confirmed and saved; a restart lifts a refusal only onto the wiring last saved here.
>   - **The record sits outside `hardware/`**, so copying that folder from the other lab machine never brings its confirmation along.
>   - **The digest covers content only**, without `edited_at`, taken over the file as stored and never after `upgrade`: a release that fills one more default must not hold every untouched file.
>   - **Content includes channel declaration order** (`content_digest`), because the order is the [odor index](#order-is-meaning): odor lines swapped by hand in `wiring.json` would otherwise load as confirmed and drive line 2 under line 1's onset code, with every trial looking right. A record whose digests are blind to order (written before they covered it) is carried over once, and only at the machine's first start (below), which rewrites it. Every other start drops each order-blind digest, with the pending save beside it, before anything is compared, so it confirms nothing. That covers a record the first start converted but could not write (trusted that run only), one an older build wrote after this build had run, and a machine that ran #134: that build set the database's mark but never wrote `wiring-record-started`, so its next start is not a first start, and its stored wiring is held once behind RIG108 until one confirm. Each order-blind digest becomes the order-aware digest of exactly the file it still matches: the stored wiring, or, for a save that landed, the older layout it replaced, which then becomes a leftover. An order-blind digest that matches nothing is dropped and never consulted again, because left in place it would confirm that wiring with its odor lines swapped at any later start; a pending save that matches nothing stays unfinished, so nothing is trusted. A reorder after that start is held. An earlier build's `digests` list is read the same way at a first start.
>   - **It is written with the save, in an order no crash can turn into trusting a wiring nobody saved or one the save replaced** (`HardwareStore.save`): record the new digest as *pending* beside the last one, write `wiring.json`, remove the older layouts it replaced, then record the new digest alone. While a save is pending, the only wiring trusted is `wiring.json` holding exactly the digest it was saving, which proves the save landed; the next start finishes recording it (`HardwareStore.settle_record`). Anything else on disk is held, the wiring the save replaced included: a save that fails before its commit puts the record back, and a process that dies at the commit holds the last wiring until it is confirmed once. Its notice says so: the wiring was saved here, but a save after it did not finish (`Stored.interrupted`), never that it was not saved here. Reset records nothing *before* it removes a file, so a Reset that stops part-way holds what it left.
>   - **The machine's first start seeds it**, and nothing else does. With no record yet (an upgrade from a build without one, or a fresh install), that start records the stored wiring if it passes every check, since that is the wiring the build before would have put in force, and writes the file even when it is empty. Over a record in an earlier build's shape (a list of `digests`), it records the stored wiring only if that list names it. Older layouts beside `wiring.json`, which the build before left mid-migration and would have removed, become leftovers; any other older layout is shown. A normal upgrade asks nothing; wiring copied in after it is held. A record that will not parse holds everything, at the first start too.
>   - **"First start" takes two witnesses, neither of them the record**: `ephymeris.db` has no `wiring_record` [machine mark](DATA.md#machine-marks) (set once that start connects), **and** the data dir has no `wiring-record-started` (written at every start). So a record lost or unwritable at a later start, or lost while the app runs, holds every stored wiring behind RIG108 with a notice saying the record is missing, until a save records it again; and so does a database restored from a snapshot taken before the mark, because the data dir still says this build has run. Two witnesses because each covers the other's way of being lost: a restore brings back an old database but leaves the data dir's files, and a tidy-up of the data dir leaves the database.
>   - **What still seeds again**: only a data directory that has lost both its `ephymeris.db` mark and `wiring-record-started`: wiped, or a new machine, a first start by definition. Running an older build in between seeds nothing: it leaves both in place.
> - **When stored wiring will not load** (unreadable, unparseable, out of shape, a channel without a pin, a wiring rule broken (RIG101–RIG107, checked at load as a save checks them), or an older layout that disagrees with itself), **or is held**:
>   - the registry composes the shipped pinout, so the sidecar still starts;
>   - the startup log says the stored wiring failed to load;
>   - `hardware.get` serves the stored document itself as the editor's draft, so it can be repaired and saved. What the draft is depends on what the file is now:
>     - **out of shape** (or a channel without a pin, or a rule broken): the broken document, to repair, then its pins confirmed;
>     - **held**, or **a file that loads now**: that file;
>     - **a two-file pair whose pin map was not written with its channel set**: the joined document;
>     - **unreadable, unparseable, not a JSON object, or one half of the pair alone**: the shipped pins. There is nothing to repair, so Save is off (`RIG_SAVE_BLOCKED`), and Reset is offered with a dialog naming every file it removes (`status.resetReplaces`).
>
>     One notice says the shipped pins are in force, why, and what that blocks; the next describes the file as it is now and what the editor shows;
>   - `sessions.startAll`, `port.startSession`, `sessions.flash`, `flash.enqueue` (Debug Mode) and `utility.identify` refuse with `RIG_WIRING_UNLOADED`, and the utility baseline flashes no box ([ARCHITECTURE.md](ARCHITECTURE.md#unloaded-wiring-holds-it)).
> - **The refusal follows the wiring in force, never a fresh read of the file.** `RigDefinition` reads the stored wiring once, when it installs it (at startup, and after every save and reset), and the registry composes from exactly that read (`_install_wiring`). A file fixed or copied in by hand changes no pin, so it lifts nothing: only a save, a reset, or a restart onto the wiring last saved here puts wiring in force.
> - **The status describes the wiring in force, never the file.** `status.custom` is false while the shipped pins are in force. `status.notices` say where the wiring in force and the files part ways: it did not load, it is held, or it was copied in, edited, corrupted or deleted by hand while the app ran. Each says what is in force, whether boxes run or are refused, **what the editor shows**, and what a restart would do. What the editor shows is one decision (`hardware/service.py`'s `_served`), and every notice's sentence about it comes from that decision, so no notice claims the editor shows the wiring in force when it does not.
> - **A stored file that is not in force is never put in force unseen.** This covers a file copied in from another machine (as `wiring.json`, `rig.json` or the two-file pair, over the shipped pins or over the rig's own), a file changed outside the app, and any stored wiring served after a failed load, including one repaired in the editor.
>   - It is served as the draft, its notice names the actual files, and the draft carries RIG108 until the operator confirms every pin. A file put back exactly as it was last saved here needs no confirming.
>   - The confirmation is an explicit act sent as `confirmedPins`. Without it, `hardware.save` is `RIG_SAVE_BLOCKED`, edited or not; with it, the save puts that wiring in force and records it, so later restarts keep it.
>   - Until then boxes run the wiring in force, and after a restart none runs.
> - **A copy beside the layout read is shown, unless it is the app's own leftover.** An older layout beside `wiring.json` (or `rig.json` beside the pair) is not read. The record lists, by each file's bytes, the app's own leftovers: a layout a save replaced and could not remove (the one the operator just saved over, which the editor served as the draft), and any older layout the first start found beside `wiring.json`, which the build before left mid-migration and would have removed at its next save (never one beside the pair, which is shown instead). The next save removes a leftover without a notice; a leftover never puts any wiring in force. Any other copy is named by a notice as not saved here, no save removes it, and Reset does.
> - **Notices are the rig's, `problems` are the draft's.** Every preview replaces `problems`, while the notices stand through every edit. While stored wiring is in force, healthy and the same as the file, the draft is that wiring.
> - **The sidecar decides Save (`status.canSave`), and the editor renders it.** A draft may be saved when it has no problems, the rig's state allows a save, and it either differs from the served draft or would clear a notice. Every `hardware.get`, `hardware.preview` and `hardware.save` reply carries the answer for the draft it describes.
>   - The editor holds Save while a preview is in flight.
>   - When an edit is undone back to the served draft, the editor shows the served draft's own answer again; no preview describes that draft.
> - **A save validates the whole document before it costs it or issues any edge code**: its shape, a pin for every channel, and every wiring rule (RIG101–RIG107, refused as `RIG_SAVE_BLOCKED`). So a draft that is going to be refused never asks the operator to accept the tasks it would break, a refused save never touches the vocabulary, and the editor's own hold on Save is never the only guard.
> - **Reset forgets the record first, then removes the lowest-precedence file first and `wiring.json` last, and stops at the first file it cannot remove.** A partial reset therefore leaves either the wiring that was in force or a load problem, never an older wiring in force, and a restart holds whatever it left. Its confirm dialog lists `status.resetReplaces`, built from the same list Reset walks (`HardwareStore.removal_order`), so a staged pin map holding the pins in force is named too.
> - **No `edited_at` in any digest or hash.** Identical wiring copied from another machine compares equal.

**Older layouts are read in place, and the next save writes `wiring.json` and removes them:**

- `rig.json`: the same document under its old name.
- `channel_set.json` + `pin_map.json`: the two documents in two files. The pin map names its channel set by a digest, and a pair whose digests disagree is a load problem, never a guess.

`wiring.json` wins over both, and the pair over `rig.json`, so a save stopped before its cleanup still has its wiring in force. A layout beside the one read is a copy the app shows and never deletes silently (see the caution above). A stray temporary file (`*.part`, `*.json.tmp`) on its own is no wiring at all.

Channel kinds are `engagement` (exactly one), `response`, `emitter`, `reward`, `cue`, `vacuum` and `sync` (at most one).

Beside its kind, every channel declares what it is ([ADR 0003](adr/0003-phase-spine-task-model.md)):

| Field | Values | Notes |
|---|---|---|
| `type` | `digital_in`, `digital_out` | Fixes the channel's edges: `enter`/`exit` on an input, `on`/`off` on an output. Must agree with the kind's direction (RIG107) |
| `role` | `port`, `stimulus`, `reward`, `cue`, `routing`, `sync` | What the line is for in a task |
| `active_level`, `debounce_ms` | `low`/`high`, ms | Inputs only |
| `serves` | a channel name | Reward lines only: the port the line pays at, equal to `well` while both exist |
| `edges` | edge → code name | Issued by a save ([Edge codes](#edge-codes)), never typed |

A channel that declares none of these, as every rig saved before they existed does, takes its type and role from its kind (`registry.channel_set_defaults`).

**The trial-runner generator reads none of the new fields.** It still generates from `kind`, `well`, `port_slot` and `onset_strobe`, so every saved task and bundled sketch regenerates byte-identical (`test_channel_set.py`). A [spine task](#spine-tasks) reads `type`, `active_level`, `debounce_ms` and `edges`, and nothing else of a channel but its pin.

### Registry rules

Which documents become the `ChannelMap` (`registry.channels()`), and what is built from it:

```mermaid
flowchart TD
    saved{"A saved channel set<br/>and pin map?"}
    saved -->|no| shipped["channels.v1.json + the<br/>selected hardware pinout"]
    saved -->|"yes: replaces the pair"| rig["data_dir/hardware/wiring.json<br/>(kinds still from channels.v1.json)"]
    shipped --> map["ChannelMap<br/>cached until set_rig_source"]
    rig --> map
    map --> taskPins["Each saved task's generated folder"]
    map --> bundledPins["Bundled sketches rebuilt into<br/>data_dir/rig/sketches/"]
    map --> diagnostics["Task diagnostics<br/>tasks.preview, tasks.get"]
```

`rig/registry.py` composes the pair into a `ChannelMap`. Three rules that are easy to break:

- **`channels()` is cached and cleared only by `set_rig_source`**, which `Application` calls at construction and after a wiring write. Never hang invalidation off `settings.push`: it fires on every reconnect.
- **`hardware/store.py`'s `default_document()` reads the shipped pair via `shipped_channels()`**, never the wiring in force — otherwise Reset resets to itself. It also keeps declaration order (sorting by pin once re-ordered the odor table on a rig's first save).
- **`ChannelMap.content_hash()` covers only fields that can change a compiled byte** (name, kind, direction, pin, watch bit, well, port slot). A reworded rationale must not move it, or people learn to ignore it. **`onset_strobe` is excluded for the same reason**: the generator emits the code a trial row stores, so the declaration changes what the editor writes, never a compiled byte. A profile names channels, not pins, so a rewiring moves no `profile_hash`; this hash is what records which wiring a sketch was built against (it is stamped into each generated header).
- **The channel-set fields stay out of `ChannelMap.content_hash()`.** They have their own hash, `ChannelSet.content_hash()` (`channelSetHash` on the Rig status). It covers what every channel is and **the order the channels are declared in**, and leaves out labels, prose and every pin, so two machines sharing one channel set agree on it whatever their pin maps say. Order is in it because declaration order is the [odor index](#order-is-meaning): the same lines in another order are not the same channel set.
  - **The hash has a version, recorded beside it** (`CHANNEL_SET_HASH_VERSION`, `channel_set_hash_version` in run files and exports). Version 2, the current one, covers declaration order. Version 1 sorted channels by name and ignored order. A recorded hash with no version is version 1, so it is checked by its own rule and never misread as one that covers order.
  - Putting the new fields in the pinout hash would rebuild every sketch for a change no box can observe.

### The wiring page

`/config/wiring` (`routes/RigWiring.tsx`) hosts `RigWiringEditor` and `PinTable` over one document: the page owns the `useRig` session and the selected channel, so clicking a table row and clicking its pin are the same gesture. The board map selects and moves, the inspector rail edits, and the pin table edits nothing.

![The Wiring page: a kind summary (1 engagement, 2 response, 12 emitter, 4 reward, 1 cue, 1 vacuum, 1 sync), the Mega's pin map with each channel labelled on its pin (odor_port, right_well and left_well on 2 to 4, odor lines on 22 to 33, trial_light, vacuum, fluid_0 to fluid_3, sync_out on 49), an Inspector, Reset, Revert and Save, and the Configured pins table below](images/rig-wiring.webp)

*The shipped wiring ("as shipped"; a saved one reads "this rig's own"). The hash beside it is
`ChannelMap.content_hash()`, the one stamped into each generated header. Odor lines 1–6 sit on the even pins 22–32 and
7–12 on the odd pins 23–33, which is why [odor index](#order-is-meaning) must come from declaration order,
not pin order.*

**The inspector edits what a channel is.** Beside its kind, it edits the channel's type and role; for an input, its active level and debounce; for a reward line, the port it serves. A channel's edge codes are shown read-only, and an edge with no code yet reads "issued on save".

**Export channel set** and **Import channel set** move the channel set and the vocabulary to and from the other lab machine ([Moving the channel set between machines](#moving-the-channel-set-between-machines)). The import dialog renders the sidecar's plan, and holds Import on any conflict.

**Saving previews what it would issue.** `hardware.preview` returns `allocations`, the [edge codes](#edge-codes) a save would issue. The page lists them above Save, so a new code is never a surprise in the vocabulary.

**Saving previews what it would break.** `hardware.preview` validates as the operator types and reports `breaks` — the saved tasks this wiring would *newly* break, computed by validating each definition under both wirings ([The rig definition](#the-rig-definition)). `hardware.save` without `confirm` refuses such a change with `RIG_WOULD_BREAK_TASKS`; with `confirm: true` it writes anyway. Rewiring is the operator's call; the app only refuses to let it happen unnoticed. A document that fails validation is never written.

### Wiring rules

A well-formed document describing an impossible box is a successful reply carrying located problems; `RIG_INVALID` is reserved for a document that is not a document. Schema problems and these rules read as one list:

| Code | Problem |
|---|---|
| `RIG101` | The meaning and the pinout halves describe different boxes |
| `RIG102` | A pin the board does not have |
| `RIG103` | Two channels on one pin |
| `RIG104` | A response port with no strobe slot ([Port slots](#port-slots)) |
| `RIG105` | More than one `sync` channel |
| `RIG106` | An odor line with no onset code, one that is not a live onset code, two lines on one code, or an onset on a channel that is not an emitter ([Onset codes](#onset-codes)) |
| `RIG107` | A type that contradicts the kind's direction, an active level or debounce on an output, an edge the type does not have, an edge code that is not live, or one code on two edges ([Edge codes](#edge-codes)) |
| `RIG108` | A draft read from a stored file that is not in force and that the record cannot vouch for (copied in, changed outside the app, not loaded even once repaired, a pin map not written with its channel set, or saved here when a save after it did not finish), its pins not yet confirmed by the operator ([The channel set and the pin map](#the-channel-set-and-the-pin-map)) |

### The sync channel

`sync` is the seventh kind: one output that pulses on every strobe into a recording controller's digital input ([RECORDING.md](RECORDING.md#the-sync-line)). It is resolved by kind, so a rig may name it anything. `BOX_PIN_SYNC_OUT` is **the one pin always emitted** — `-1` when the rig declares no sync channel — because every other undeclared pin keeps `BoxPins.h`'s default, and here that default would pulse a pin the operator never declared while the app reports the box has no sync line. Since a saved rig replaces the shipped pair, a rig document saved without a sync channel has none until one is added.

### Moving the channel set between machines

Both lab machines must hold one channel set and emit identical codes ([ADR 0003](adr/0003-phase-spine-task-model.md)). One machine edits it and exports it from the Wiring page; the other imports it (`hardware.exportChannelSet`, `hardware.importChannelSet`; rules in `rig/transfer.py`, the write in `RigDefinition.import_channel_set`).

**The export** is one file:

```json
{"channel_set_export_version": 1,
 "channel_set_hash": "3f0c…",
 "channel_set_hash_version": 2,
 "channel_set": {"channel_set_version": 1, "channels": {"odor_port": {…}, …}},
 "vocabulary": {"vocab_version": 3, "codes": {…}, "retired": {…}, …}}
```

- **`channel_set`** is the channel set in force: every channel entry whole, in declaration order. It has no pins.
- **`vocabulary`** is the whole vocabulary, as `strobes.export` sends it.
- **`channel_set_hash`** is `ChannelSet.content_hash()` ([Registry rules](#registry-rules)), by the rule `channel_set_hash_version` names. An export with no version was made before the hash covered order: the import checks its hash by version 1's rule, and its order by the `order` conflicts. A higher integer version is `CHANNEL_SET_INVALID`, naming a newer build; anything else that is not an integer version is `CHANNEL_SET_INVALID` as a file that is not an export.
- **Update both machines before moving a channel set.** A newer build can read an older one's export, but not the reverse. A build from before the hash had a version ignores `channel_set_hash_version` and checks a newer export's hash by its own order-blind rule, so it refuses a genuine file as a `hash` conflict: "changed after it was exported". That build cannot be changed after the fact.
- **The plan reports three hashes.** `hereHash` and `importedHash` are this rig's, now and after the import, by the current rule. `fileHash` and `fileHashVersion` are what the file states. Only the file's hash is checked against the file.
- **Export is refused** in two cases:
  - an edge has no code yet, for example on the shipped set before this machine's first save. The importer would issue its own numbers;
  - the stored wiring is not in force: it did not load, or it is held.

**The import replaces this machine's channel set with the file's and keeps every pin.** It adopts the file's entries verbatim, labels included, so the two documents agree beyond the hash. Declaration order must already agree (an `order` conflict otherwise). It merges the vocabulary as [a vocabulary import](#moving-codes-between-machines) does. `apply: false` returns the plan and writes nothing.

**Any conflict refuses the whole import**, and the plan lists every one (`ChannelSetConflict.kind`):

| Kind | When |
|---|---|
| `vocabulary` | One name with two codes, one code with two names, or a code this machine cannot issue |
| `not_here` | A channel the file has and this rig lacks. It has no pin here |
| `only_here` | A channel this rig has and the file lacks. Its pin would belong to no channel |
| `order` | A channel both sides have, declared at another position. Declaration order is the [odor index](#order-is-meaning), so adopting another order would put another line behind each odor position with every trial still looking correct. One conflict per channel that would move |
| `no_code` | An edge the file names no code for |
| `rule` | A [wiring rule](#wiring-rules) the joined document breaks against the merged vocabulary. One case is a code retired here that the file's channel names: a merge never reinstates |
| `hash` | The joined channel set does not hash to the file's `channel_set_hash`: the file changed after export |

Two kinds are judged only when nothing else already names the problem. `rule` and `hash` are judged only once both sides have the same channels, because a channel one side lacks would come back as RIG101. `hash` is also skipped over a `rule` or `no_code` conflict. A code in a `vocabulary` conflict is left out of the merge the rules are judged against, so a rule it breaks is still listed beside it.

Besides conflicts:

- **A plan reports `breaks`**, as `hardware.preview` does. Applying it needs `confirm`.
- **An import is refused** while the stored wiring did not load or is held, while a stored file waits for its pins to be confirmed (RIG108), and while a session is set up or a box is running.

**A clean import is one [rig definition write](#the-rig-definition).** It plans again inside the write, then takes three steps, each skipped when it changes nothing, then runs one rebuild:

1. **The vocabulary's new codes.** Adding a code breaks no wiring.
2. **`wiring.json`.** The new wiring names only codes step 1 made live.
3. **The vocabulary's retirements.** Only now is a code retired that the old wiring may still name.

> [!WARNING]
> **Never retire before the wiring lands.** A retirement written while the wiring write then fails leaves this rig's own wiring naming a retired code. After a restart it fails RIG107, the shipped pins are in force, and a re-import is refused as unloaded wiring: a dead end.

In this order, a failure between any two steps leaves a wiring and a vocabulary that load together. What landed stays, since the vocabulary is append only. The rebuild still runs, the rig restarts on its own wiring, and importing again finishes the rest. An identical import writes nothing.

**Adding a channel lab-wide is not covered yet.** The file's new channel has no pin on the importing machine, so the import refuses it as `not_here`.

## Strobe vocabulary

Each machine owns one vocabulary document, `<data_dir>/strobes/vocabulary.json`, and it is **the only place a strobe code is defined**. Everything else derives from it:

| Consumer | How it gets the codes |
|---|---|
| Firmware | `TaskPins.h` defines `BF_<NAME> <code>` for every live code, in every generated task folder and every rebuilt bundled sketch (`generate._strobe_lines`). `BoxStrobes.h` defines none and `#error`s without them |
| Task profiles | `load_profile` fills `strobes` from it ([Strobes](#strobes)); `liveMetrics` name their codes |
| The app | `registry.vocabulary()`, over the wire as `strobes.get` and `strobes.updated` |

The first start on a machine seeds the document from the shipped default, `rig/schema/strobe_vocab.default.json`; after that the default is never read there. There is deliberately **no reset**: a reset could drop a code this machine added and then reissue its number. A document that will not read is decoded with the default, logged, flagged on the page, and **every edit is refused** until it is repaired, for the same reason.

The page is `/task/strobes`. It lives on the Task tab rather than Rig because a code is what a *condition is named by* — the trial table's onset picker is its main consumer — while a pin is compile-time input that belongs to the box.

![The Strobe vocabulary page: a code band from 0 to 999 showing the reserved range, the live onset run 101–116 with the retired 110–113 gap, and the live codes from 221 to 369; below it the filtered code table with ODOR_3_ON selected, and a detail panel giving its meaning, the two sketches that name it, the archive check, and Retire and Remove](images/task-strobes.webp)

*The band makes the numbering visible: the odor onsets run 101–109 then 114–116, stepping over the
retired 110–113, which is why a code is always looked up by name.*

### Append only

> [!CAUTION]
> **A code is never renumbered and never repurposed, and a name is never reissued with a different number.** Tens of thousands of recorded events carry these numbers; reissuing one silently merges two unrelated event types in any analysis spanning the change.

- A code is **free** when it lies in `code_min`..`code_max` (999 — the host parses three digits), outside `reserved` (0–100), and is neither live nor retired. Free ranges are derived, never stored.
- A code whose emitter is gone but which a **real session** contains moves to `retired` and stays reserved forever. Retired is a third state — neither live nor free — and the generated header does not define it, so firmware that still emits it fails to compile.
- **Removing a code is possible, and the bar is not "unused".** It is "no recorded session has ever contained it", checked against the archive rather than assumed. A code emitted once, to a file that still exists, can never be removed; retire it.

### Editing the vocabulary

Every edit is a `strobes.*` command (`app.py`, rules in `strobes/store.py`, evidence in `strobes/usage.py`). The sidecar computes the blockers (`strobes.usage`) so the page never predicts one, checks them again inside the [rig definition write](#the-rig-definition) when the edit is made, and refuses every edit while a session is set up or a box is running.

| Edit | Refused outright | Needs `confirm` |
|---|---|---|
| **Add** | malformed name (`^[A-Z][A-Z0-9_]*$`, no `BF_`), a name already live **or retired**, a number that is not free, a blank meaning | never |
| **Edit meaning** | a retired code; any change to the name or number (not offered) | never |
| **Retire** | a [port-slot](#port-slots) code; a code the shared firmware library names (every sketch would stop compiling) | a saved task or bundled sketch names it (`STROBE_WOULD_BREAK_TASKS`) |
| **Reinstate** | — | never; the name and number were never reissued |
| **Remove** | **any recorded session contains it** (`STROBE_IN_RECORDED_SESSION`); the retire refusals above | as for retire |

**Where a code is used** has three answers, all computed per request:

- **Firmware:** a regex for `BF_<NAME>` over every source file under the sketch library and the saved-task folders, comments stripped, the generated `TaskPins.h` and any `extras/` folder (a library's host tests) excluded. A hit under `libraries/` is a `library` reference.
- **Tasks:** the [impact check](#the-rig-definition) with a hypothetical vocabulary — every saved task validated with and without the code, only what is *newly* broken reported.
- **Sessions:** `ArchiveScanner` walks every cohort's data folder (archived ones included) plus every file the database lists, reading each `.json` and each `.tsv` with no `.json` beside it — a crashed or running session is a recorded session. Results are cached per file in `strobe_scan_cache` on (path, mtime, size), so only the first scan reads everything; it publishes `strobes.scanProgress`.

> [!WARNING]
> **The scan sees only this machine.** Another rig's archive, an unmounted drive, a folder no cohort points at — none is checked. The reply reports what was (`scanned`: files, roots, unreachable roots, unreadable files) and the Remove dialog says so. If a code may have been recorded elsewhere, retire it instead.

### Moving codes between machines

Vocabularies are per machine, so a lab with two rigs keeps them in step by **Export** and **Import** on the page (`strobes.export`, `strobes.import`). An import is a **union**: it adds codes this machine lacks, and a code retired there and live here is retired here too (some session there contains it). It never removes a code, and never reinstates one. Any **conflict** — one name with two numbers, or one number with two names — refuses the whole import: picking a winner would relabel one machine's recorded data. `strobes.import` with `apply: false` returns the plan and writes nothing; the dialog shows it before applying. A v2 export (stored `free_ranges`) is read as v3. A [channel-set import](#moving-the-channel-set-between-machines) carries the vocabulary too, and merges it by the same rules.

### Every declared code is emitted

A declared code that nothing can emit is a name in every picker that no session will contain; an emitted code the vocabulary lacks would arrive as an unlabelled number. The second is now impossible for named codes — the generated header is the only definition, so firmware naming an undeclared code does not compile. The first is checked two ways:

- **The shipped default** is pinned by `tests/test_taskdef.py` against `firmware/`: every `BF_*` the library and bundled sketches name is a live default code, and every default code is either named there or is a stimulus onset (`_<n>_ON`) the trial table can bind to a line. The two deliberate non-emitters in `BehaviorBox.h` — `shutdownHardware()` (runs before the clock is stamped and in utility sketches) and `flashLight()` (one `LIGHTS_OFF` per blink would bury the real light edges) — carry comments saying why.
- **A code added on a machine** cannot be tested; its detail panel says "nothing on this machine names it — no firmware emits it yet" until a sketch does. Add the code first, then write `BF_<NAME>` into the firmware.

### Port slots

`port_slots` maps a slot number to the six codes a response port on it reports with (enter, error, break, exit, reward, reward-stop). There are **two** slots, pointing at the historical `_L`/`_R` names, because `checkResponse()` polls two ports. The vocabulary is the authority; `RIG104` reads it, so the channel schema deliberately does not cap `port_slot` as well. Nothing derives a code from a channel's *name*.

### Onset codes

**An odor line declares the code that announces its onset** — `onset_strobe: "ODOR_3_ON"` on the emitter in `channels.v1.json` and in a rig's own channel set — the way a response port declares its slot. It is a code **name**; the number lives only in the vocabulary. Nothing derives it from the channel's name or position: the onsets run 101–109 and then 114–116, and the emitter pins are not in line order (`generate._onset_macro` records the derivation that was wrong).

- **The editor fills a row's code from its line**, and shows it read-only, so line and code are one choice. One line declares one code, so **a line can carry only one trial type** — the picker lists a line another row holds as disabled, and two rows on one line are `TSK105`.
- **The row still stores `onsetStrobe`**; the generator emits it, and `profile_hash` is unchanged. A stored row that disagrees with its line's declaration is **`TSK114`**.
- **`RIG106`** checks the declarations: every emitter has one, each is a live onset-shaped code (`ONSET_NAME`, mirrored in `src/lib/taskdef/lines.ts`), no two lines share one.
- **A rig saved before the field existed is filled on load** (`hardware/store.py`'s `upgrade`) from the shipped channel of the same name and kind, in memory until the next save. A line the rig added or renamed stays undeclared and `RIG106` asks the operator — nothing guesses.

> [!CAUTION]
> **When `TSK114` appears on a task the lab has run, fix the wiring, not the task.** Changing the row changes the code every *future* session records for that bottle, splitting it from the archive. If the bottle has always been recorded under the stored code, set the line's onset code on the Rig tab to match.

### Edge codes

**Every edge of every channel names the code that announces it**: `edges: {"on": "FLUID_2_ON", "off": "FLUID_2_OFF"}` in the channel set. The channel's type fixes its edges. A code is a **name**, and the number lives only in the vocabulary.

**A save issues a code for every edge that has none** (`rig/allocation.py`):

- **Order:** channels in declaration order, and each channel's edges in its type's order.
- **The name:** `<CHANNEL>_<EDGE>`, upper-cased (`ODOR_PORT_ENTER`). A name the vocabulary ever gave to anything else, live or retired, gets `_2`, `_3`, … instead.
- **The number:** the lowest free one ([Append only](#append-only)), with origin `channel_set`.
- **Inside the write:** the vocabulary gains the codes inside the same [rig definition write](#the-rig-definition) as the wiring, then one rebuild serves both. `strobes.updated` is broadcast beside `hardware.updated`.
- **In the preview:** `hardware.preview` runs the same plan and writes nothing.
- **When the vocabulary will not read:** a save that needs a code is refused, as every vocabulary edit is. A save that needs none goes ahead.
- **When the wiring will not write:** codes already issued stay issued (append only). The rebuild every vocabulary edit owes still runs, and the next save reclaims them.

**The shipped channel set names no edge codes.** So the shipped vocabulary is untouched, and a machine's first save issues one code per edge.

**Renaming a channel never renames its codes.** The `edges` map travels inside the channel's entry, and a save fills only an edge that has none.

**One case takes a name back.** Each code records the channel, edge, kind and role it was issued for (`issued_for`). A plan reuses a live `channel_set` code when all of these hold:

- the code has exactly the name the plan would issue;
- it was issued for the same channel, edge, kind and role;
- no edge in the document holds it.

That covers a channel set reset to the shipped one, a channel deleted and added back as what it was, and a save that issued codes and then failed to write. Issuing those again under `_2` would only grow the vocabulary with codes that mean the same thing. A deleted reward line `lever` that comes back as a cue is a different event, and gets fresh codes.

**A spine task emits them; GRGL still strobes its own codes.** A [spine task](#the-runner) strobes the `enter`/`exit` or `on`/`off` code of every channel its slots bind. The page says "nothing on this machine names it" ([Every declared code is emitted](#every-declared-code-is-emitted)) for a code no sketch names.

## The START line

### Three layer merge

| Layer | Lives in | Scope |
|---|---|---|
| Profile default | the sketch's `task.json` (for a saved task, its definition) | the task, everywhere |
| Rig default | `settings.taskDefaults[sketchName]` | this machine |
| Per-box override | the session's box mapping | this animal, this run |

For each field the profile declares, the most specific layer that has a value wins. From there the line is
built sidecar-side as `SET` lines, and only the seed, on `START`, is left for the click:

```mermaid
flowchart LR
    profileDefault["Profile default<br/>task.json"] --> merge["defaultConfig<br/>src/lib/sessions/types.ts"]
    rigDefault["Rig default<br/>settings.taskDefaults"] --> merge
    override["Per-box override<br/>mapping step"] --> merge
    merge -->|"sessions.confirmMapping"| build["build_start_command<br/>SET lines, each under SET_LINE_MAX"]
    build -->|"Start: SET lines, PARAMS checked"| line["START SEED=n<br/>to the board"]
```

They merge in that order in exactly one place, `defaultConfig` in `src/lib/sessions/types.ts`. **It iterates the profile's fields, not the stored objects**, so a value for a field the sketch no longer declares cannot reach the wire. `taskDefaults` is keyed by sketch folder name (what the session file records as `sketch`) and stores only divergences; it has no editor, and entries keyed by a sketch that no longer exists are inert. The session file records the merged values flat, plus `config_json`/`params_hash` on the run — a reader never needs to know which layer a number came from.

The mapping step keeps **only the per-box layer**: a row (and its set-up draft) holds the keys the operator edited in `TaskConfigForm` and nothing else. The full config is rebuilt by `defaultConfig` from the current profile and `taskDefaults` whenever the form renders, and again at confirm. The Confirm button waits until every chosen profile has loaded, because the merge needs it. An edit is a key whose value moved between what the form showed and what it reported. A reset drops the key, so the field goes back to following the layers underneath.

> [!CAUTION]
> Never seed a row with the merged config, and never decide what is an override by comparing a value against the baseline. The rig is not held until the first group's walk starts, so Open Task or Open Rig can regenerate the chosen sketch's `task.json` mid-setup. A seeded snapshot would keep the old default. Compared against the new baseline, that old default reads as an override the operator never set, and it goes to the board and into the session file as if it had been chosen.

### Building the line

`build_start_command(profile, config)` in `tasks/start_command.py` returns a `StartCommand`: the run's parameters as tokens, `<wireKey>=<value>`, packed into `SET <token> <token> …` lines. Tokens are order-independent to the firmware parser (unknown keys are not parsed, missing keys keep the compiled default) but the order is kept, because the board's CRC is over the tokens in the order it received them.

- `config` is keyed by `metadataKey`; tokens follow the profile's `config` order.
- A missing key uses the field's default; an undeclared key is ignored, so stale UI state cannot leak.
- A value is rendered only if the board will read exactly what is written: `bool` → `1`/`0` (from a bool, 0/1, or a word such as `true`); `int` → a whole number (4000.0 and `"4000"` pass, 4.9 and `abc` do not); `float` → trimmed, finite and within the board's float; `string` → verbatim (whitespace raises). Anything else raises `TaskProfileError` naming the field, at mapping, and **nothing is swapped for the default**: the board would run a setting nobody chose.
- Tokens are packed greedily into lines shorter than `SET_LINE_MAX`, never split across lines.
- No profile, or no config fields → one bare `SET`. The board is asked even about an empty block, because a board that never hears a `SET` cannot be told apart from an older sketch.

It is built sidecar-side at `sessions.confirmMapping` (and by `port.sendStart` in Debug Mode). Only the `START` line is left for the click.

### Confirming the parameters

Before a run starts, the board proves it holds exactly what the host meant it to. The host sends each `SET` line alone and waits for the board's answer before the next, because the Mega's receive buffer is 64 bytes.

```mermaid
sequenceDiagram
    participant Host as Sidecar
    participant Board as Mega2560
    Board-->>Host: INTERP=1 (a spine task: INTERP=2)
    Board-->>Host: FREE_RAM=n
    Board-->>Host: READY
    Host->>Board: BEGIN
    loop each SET line, one at a time
        Host->>Board: SET KEY=value …
        Board-->>Host: CLAMPED KEY (for each value its clamp would move)
        Board-->>Host: PARAMS n crc32
    end
    Note over Host: n and crc32 of the last answer must equal the host's own, with no CLAMPED
    Host->>Board: START SEED=n
    Board-->>Host: SEED n
```

- **`BEGIN`** opens the block. The board forgets any earlier one: the running total below, and the values, back to what the sketch holds on entry. That is what lets a refused Debug Mode start be corrected and sent again on the same open console. Without it the second block is added to the first and every retry is refused as a count mismatch. A board that has not been sent one (a hand-typed console) starts empty anyway.
- **`PARAMS <n> <crc32>`** is the running total: `n` is how many keys the board has accepted, and `crc32` is the standard CRC-32 (what Python's `zlib.crc32` computes) over the accepted tokens **exactly as received**, joined by single spaces, in the order received. The host computes both over what it sent (`StartCommand.count`, `.crc32`) and acts on the answer to its last line.
- **`CLAMPED <key>`** is printed before that `PARAMS`, once for each value the board could not hold as sent: one `clampTaskParams()` would change in the block so far, or one it read differently from how it was written. The second kind matters because the CRC is over the text. `ITI=40000` hashes the same whether the board holds 40000 or wraps it to −25536 (the range of its 16-bit `int` is `BOX_INT_MIN`..`BOX_INT_MAX`, −32768..32767), `ITI=4.9` the same as 4, `ITI=abc` as 0, `LAZY=true` as 0 and `DBS=1e40` as infinity. Only the board saying it did not parse the text exactly (junk after the digits, a fraction for an int, a word for a number, a non-finite float) stops the run. The host does not render such a value for a bundled profile, but a hand-written `task.json` can declare one. More inexact keys than the audit can name (16) are reported as `CLAMPED *`. The board judges a copy, so the block it holds is untouched until `START`; a clamp on an early line that a later line corrects does not appear in the last answer.

  > [!CAUTION]
  > **A parameter whose declared `max` is above 32767 can be refused by the board.** GRGL's `task.json` allows `ERR`, `ITI`, `NPH`, `LZD` up to 120000, `NWP`, `LZS`, `S<n>W`, `S<n>O` up to 60000 and `LZM` up to 300000, but the board holds them in a 16-bit `int`. Such a value now refuses the start with `PARAMS_CLAMPED` instead of running wrapped; the form does not yet stop it being typed.
- **`START SEED=<n>`** is sent only after the answer clears. It carries the seed and nothing else ([SEED](#seed)); the board clamps and applies ramp row 0 then.
- **`INTERP=<n>`** is printed before `READY` and names the firmware interpreter, in one numbering space: `1` is `BehaviorBox.h`'s trial runner (GRGL), `2` is the state-table interpreter that runs a [spine task](#the-runner) (`BoxInterp.h`'s `INTERP_VERSION`). The run's `.tsv` header records it as `# interp: <n>` ([DATA.md](DATA.md#the-tsv-log)), so the header alone tells a spine run from a legacy one; a board that announced none leaves the line out. Replay runs only the state-table versions and refuses `1`.
- **`FREE_RAM=<n>`** follows it: the bytes of RAM free between the heap and the stack, measured in `setup()` with the sketch's tables already resident (`boxFreeRam()` in `BehaviorBox.h`). The header records it as `# free_ram: <n>`, and the `.json` as `free_ram`. A host build has no RAM to measure and reports a fixed value.

The start is refused, with nothing started and the port in `ERROR` until acknowledged, on any of:

| Error code | `detail.reason` | What it caught |
|---|---|---|
| `PARAMS_MISMATCH` | `count` | The board accepted fewer keys than were sent: a key this sketch does not parse. A line cut inside a key lands here too, since the stub is no key |
| `PARAMS_MISMATCH` | `crc` | The same count but different bytes: a line cut inside a value, or garbled in transit |
| `PARAMS_CLAMPED` | `clamped` | The board would not run a value as chosen; `detail.keys` names them |
| `FIRMWARE_OUTDATED` | `no_reply` | No `PARAMS` within `SESSION_PARAMS_TIMEOUT_S`: the sketch predates `SET`, and the message says to reflash |

At a session start the refusal arrives as `sidecar.error` for that box (the click had already returned) and the run ends with `stop_reason: "start refused: <reason>"`; from Debug Mode it is the reply to `port.sendStart`. In Debug Mode the confirmed block is followed by a bare `START`: a hand-run task takes no seed and records nothing.

> [!CAUTION]
> **A bare `START` still starts a board.** A hand-typed console session keeps working, and runs on the compiled-in defaults without any confirmation. The app never sends one: a run it starts has either been confirmed or refused.

### The length cap

> [!CAUTION]
> **The cap is checked rather than trusted, because the firmware cannot report the failure.** `readLineInto()` truncates an overlong line and drops the rest. The host therefore never builds a `SET` line that long: `build_start_command` raises, naming the parameter and the limit, when a single token cannot fit. And were a line cut anyway, the board's `PARAMS` would disagree with the host's and [the start would be refused](#confirming-the-parameters). `SET_LINE_MAX` lives in **two files** — `tasks/start_command.py` and `firmware/libraries/BehaviorBox/BehaviorBox.h` — and `tests/test_start_command.py` fails when they disagree.

`SET_LINE_MAX` is the firmware's line **buffer**, terminator included: a sketch reads into `char cmd[SET_LINE_MAX]`, so the longest line it keeps whole is `SET_LINE_MAX - 1` characters, and the host refuses a token that would make a line of `SET_LINE_MAX` or more. The firmware host test pins what `readLineInto()` keeps; `tests/test_start_command.py` pins the host at both edges.

The cap is on each line, not on the run: a profile with many fields is spread over more lines. Only one parameter too long for a line is refused, as `TASK_PROFILE_INVALID` with the box, and **the mapping is refused**. A profile that fails to *parse* at mapping is instead treated as profile-less (one bare `SET`).

### SEED

`SEED` is a reserved wire key no profile may claim.

- **Host → board:** `StartCommand.start_line` puts `SEED=<n>` on the `START` line at the instant the operator starts **that box** (`tasks/seed.py`), once the parameters are confirmed. Drawn per box at start, not at mapping, which would give every box in a group the same value and survive Stop → Start.
- **Board → host:** a `SEED\t<n>` line right after `START` is captured as `trial_seed`.

The host draws it because the board cannot: opening the port pulls DTR and resets the Mega, so `micros()` at `START` measures only boot time plus a round-trip — a few hundred reachable seeds. The host uses the OS CSPRNG, held to `[1, 2^31 - 2]` (`randomSeed(0)` is a no-op; avr-libc's `random()` state space ends at `2^31 - 2`). Both values are recorded: `host_seed` is what was sent, `trial_seed` what the board reports running on. They differ only if a board ignored `SEED=` and seeded itself, and the sidecar warns when they do.

## Profile and params hashes

Both are SHA-256 over canonical JSON (`sort_keys`, compact separators), truncated to 16 hex characters, in `tasks/profile.py`.

| | `profile_hash` | `params_hash` |
|---|---|---|
| Input | the serialized profile — `taskName`, `kind`, the full `config` array **including presentation keys** (`group`, `label`, `unit`, `help`, ranges), `liveMetrics` (as codes), `controls`, `legacyNames`, and `telemetry`/`identify` when present — **not** `strobes`. A [spine task](#spine-tasks)'s profile is hashed for its behaviour only ([below](#a-spine-tasks-hash-covers-behaviour-only)) | one run's merged parameter values, keyed by `metadataKey` |
| `None` input | n/a | returns `None` — a run with no recorded parameters is not a run recorded with none |
| Stored on | `task_profiles.hash` (content-addressed) | `session_animal_runs.params_hash`, beside `config_json` |

> [!IMPORTANT]
> **Comparability in Analytics is the pair `(profile_hash, params_hash)`.** A profile hash covers only the declaration and is identical across every run of a sketch however it was tuned, so grouping on it alone would pool a shaping run with a full-task run.

What this rests on:

- **Anything in `to_json` moves `profile_hash`** (on a spine task, anything not on [the unhashed list](#a-spine-tasks-hash-covers-behaviour-only)), and a moved hash permanently splits a task's runs in Analytics (old hashes cannot be recomputed). This is why the diagram is derived rather than declared, why the parameter dial's tab fold is the app's rather than the profile's ([Parameter dial](#parameter-dial)), and why `group` must not be re-filed in `fields.py` casually. Editing a saved trial-table task — renaming a condition, which renames its metric label — is a new declaration and correctly a new hash. So is a generator change that alters what every regenerated `task.json` contains; earlier runs then group separately and still decode by their own snapshot.
- **`strobes` is left out** because a loaded profile's map is the machine's whole vocabulary: hashing it would split every task's history the first time anyone added a code, and codes are never renumbered, so the map says nothing about comparability. Stored hashes were re-keyed once when this changed (`cohorts/db.py` `_to_v13`, [DATA.md](DATA.md#changing-the-schema)).
- **`to_json` must round-trip through `parse_profile` byte-for-byte.** A finalized session file embeds its profile ([DATA.md](DATA.md#per-animal-files)); if the round trip drifts, a copied run lands under a different hash than its origin.
- **`intan_*` fields are core, not config** (`CORE_METADATA_KEYS`), so they stay out of `params_hash`: two runs of one tuning are comparable whether or not one was recorded.

### A spine task's hash covers behaviour only

A profile with a `spine` key is hashed through `tasks/behaviour.py` ([ADR 0003](adr/0003-phase-spine-task-model.md#hashes-and-data)): what the board runs and how replay scores it, and none of the words a person reads. So renaming a row or rewording help text keeps one history, and changing a phase, a block, a binding or a contingency moves the hash. Every other profile hashes exactly as the table above says.

- **The list is of what is left out.** `behaviour.UNHASHED` names each string meant for a person by path (`*` is any list element; a dict step is always a key): `legacyNames`, `config[*].label`, `.help`, `.group` and `.unit`, `liveMetrics[*].label`, and `spine.rows[*].name`. A config label is on it because the generator writes the row's name into the reward fields' labels. Everything else is hashed, `taskName` included, and so is any field added to a row, phase or block later. **A new field meant for a person is hashed until its path is added**, deliberately: `tests/test_behaviour_hash.py` pins the list and changes every leaf of a generated profile in turn.
- **Rows are keyed by their stable `id`**, hashed as `{id: row}`, so reordering `spine.rows` moves nothing; a block's `rows` list keeps its order. Anything the lowering derives from row order (a wire key, a config entry, the table) is hashed where it appears, so a reorder that changes what the board runs still moves the hash. When an id is missing or repeated, the rows are hashed as a list, so none is dropped.
- **The snapshot keeps the names.** Only the hash leaves them out: `to_json` and `parse_profile` still round-trip every byte, so a run's own file says what its rows were called. A spine run decodes by its file's snapshot when the file embeds one ([ANALYTICS.md](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#which-profile-decodes-a-run)).

  > [!CAUTION]
  > **Without a snapshot in its file, a spine run decodes by its `task_profiles` row, and that row may carry another declaration's words.** `task_profiles` is content-addressed, so its row for a hash holds the first declaration seen with it: the same behaviour, but possibly another task's or an earlier edit's row and metric names. Read a row's name from the run's own file, never from that row.
- **No migration re-keys a spine run's stored hash.** A spine run whose file embeds its snapshot is scored by it, so a change to this projection moves the [canary](DATA.md#caching), and the cache version moving recomputes its scored hash. Only `session_animal_runs.profile_hash` keeps the digest it was recorded with, and that digest's `task_profiles` row still resolves.

## Derived state machine

The Task tab and Mission Control draw the trial's state machine. It is **computed from the profile** in `src/lib/tasks/topology.ts` (`taskGraph`) — pure, no React, store or fetch — and laid out by `src/lib/tasks/graphLayout.ts`. Both are pinned by `topology.test.ts` and `graphLayout.test.ts`.

### Why derived

Every behaviour sketch runs one shared `runTrial()`, so the topology is identical across them; what differs is which branches exist, and the declared strobe names say exactly that. Everything gates on **names**, never raw codes.

> [!CAUTION]
> **Never add a `states` or `graph` key to `task.json`.** It changes `profile_hash`, which Analytics groups runs by, and would split every sketch's historical runs from its future ones with nothing to recompute the old hashes.

**Left to right is when the firmware strobes it.** The condition sits at odor delivery, because the odor-on code is strobed after `ODOR_POKE` and the pre-odor hold (the odor is primed earlier, silently). `LIGHTS_OFF` is its own state between withdrawal and answer: it separates presentation from response and is where a real trial rests for seconds.

### The model

`taskGraph(profile)` returns `{nodes, edges, conditions, congruent, usable}`. A node has a `kind` (`state`, `outcome` — coloured to match Analytics' outcome palette — or `abort`), authored `column`/`row` in a 100-wide frame, `governedBy` (config `group` names that tune it), `entryNames` (strobe names that put the live token there), optional `variants` (a collapsed node's conditions) and `settlesToIti`. Edges carry a `kind` and an optional `label`. **The model carries no counts**: the only place a graph and a live run coexist is Mission Control, and a partial mid-session tally reads as a result while its trials are still arriving. Analytics owns recorded figures.

### Gates

- **`usable`** = `LIGHTS_ON` and any of `WATER_POKE_L`/`_R`/`_NONE`. Otherwise no diagram (prose instead), though `conditions` is still returned.
- **`conditionsOf` — the gate.** Odor names are those matching `ODOR_<n>_ON`. If any is the `triggerCode` of a `liveMetrics` entry, **only metric-named odors survive**; if none is, all declared odors survive unlabelled.
- **`scoredNames`** — names any metric's trigger, success or alternate code (every one of `alternateCodes`) resolves to. Gates the `withheld` outcome.

> [!IMPORTANT]
> **A declared code is not a presented condition.** A hand-written profile lists every odor code of the shared vocabulary, and every generated profile declares `WATER_POKE_NONE` because the runner can emit it, while a task presents a few odors and often no no-go trials. So conditions and the withhold arm are gated on a `liveMetrics` entry **scoring** them, not on the code existing. Any change to this derivation must keep handling that.

### Nodes and outcomes

| Node | Gate | Entry names |
|---|---|---|
| `start` "Light" → `await-poke` "Poke" | always | `LIGHTS_ON`, `ODOR_POKE` |
| `lazy` "No poke" (abort) | `LAZY_RAT` | `LAZY_RAT` |
| the odor node | conditions exist | every condition's onset name |
| `abort-pre-odor` "Let go", `abort-sampling` "Left early" | `ODOR_UNPOKE_EARLY` (one code, two edges, told apart by whether an onset preceded) | none |
| `sample` "Unpoke" | always | `ODOR_UNPOKE` |
| `lights-off` "Light off" | `LIGHTS_OFF` (else the answer comes straight off `sample`) | `LIGHTS_OFF` |
| `choice` "Answer" | always | `WATER_POKE_L`, `WATER_POKE_R` |
| `iti` | always | `WATER_UNPOKE_L/R`, `END_CORRECT_ITI`, `END_INCORRECT_ITI` |
| `repeat` (abort) | any abort exists | `INVALID_TRIAL` |

Outcomes, best to worst, each with exactly one inbound edge (never a condition × outcome cross product):

| Outcome | Gate | From | Note |
|---|---|---|---|
| Reward | `FLUID_L` or `FLUID_R` | answer | Settles to ITI on a timer **only** if `WATER_UNPOKE_L/R` are undeclared; otherwise the animal's withdrawal moves the token |
| Withheld | `WATER_POKE_NONE` **and** scored | window | The gate is a metric scoring the withhold (see the note above). The scorer has no no-go bucket: [ANALYTICS.md](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#rewarded-and-response-accuracy) |
| No hold | `WATER_UNPOKE_EARLY_L/R` | answer | |
| Wrong well | `WATER_POKE_ERROR_L/R` | answer | |
| No answer | always | window | |

With more than one condition on a fan, edge labels are dropped: one label drawn N times around a fan is clutter.

What `taskGraph` returns for the bundled `GRGL/task.json`, with the same labels. Its two conditions are congruent, so they collapse into one "Odor" node; it declares `WATER_POKE_NONE` but no metric scores it, so there is no Withheld outcome. Dashed nodes are aborts:

```mermaid
flowchart LR
    light["Light"] -->|"pokes"| poke["Poke"]
    light -->|"window elapses"| noPoke["No poke"]
    poke -->|"holds"| odor["Odor"]
    poke -->|"releases early"| letGo["Let go"]
    odor -->|"samples"| unpoke["Unpoke"]
    odor -->|"leaves early"| leftEarly["Left early"]
    unpoke --> lightOff["Light off"]
    lightOff --> answer["Answer"]
    answer -->|"correct, held"| reward["Reward"]
    answer --> noHold["No hold"]
    answer --> wrongWell["Wrong well"]
    lightOff --> noAnswer["No answer"]
    reward --> iti["ITI"]
    noHold --> iti
    wrongWell --> iti
    noAnswer --> iti
    iti --> light
    noPoke --> repeat["Repeat"]
    letGo --> repeat
    leftEarly --> repeat
    repeat --> light
    classDef abort stroke-dasharray: 5 4
    class noPoke,letGo,leftEarly,repeat abort
```

### One condition node

The conditions are **one node carrying `variants`**, drawn as a tick strip, not N nodes. The arms are congruent — same in-edge, same out-edges, same `governedBy`, same downstream, mutually exclusive — so a fan spent O(N) rows of the drawing's scarcest axis to encode a label, and collided with the abort band at four conditions. Height is now constant in the condition count. The node is labelled after its condition when there is one, and generically ("Odor") when it stands for several.

**`armsCongruent` is the guard.** Differing correct wells are still congruent, but a **go/no-go mix is not**: a withhold arm never reaches the wells, so one node would assert a path that does not exist. That profile falls back to a fan (`lane: "fan"`).

> [!CAUTION]
> **`correctWellOf` reads `successCode` only and returns `null` whenever it cannot prove an answer.** Falling back to `alternateCode` prints a confident lie: a no-go type's alternates are every response port (the generator's `_enter_codes`, `infer.no_go_alternates`), so the fallback renders "Odor 4 → left well" for a condition whose answer is to poke nothing. It is the only figure the diagram *adds* rather than rearranges, so it is the only one that can be false.

**`liveConditionId`** walks the strobe tail newest-first and **stops at a trial boundary** (`LIGHTS_ON`, `INVALID_TRIAL`, the ITI and session codes), so a previous trial's odor never leaks into the current pre-odor phase. It returns a condition, **`unlisted`** (the box announced an odor the profile does not declare — almost always the `liveMetrics` gate having dropped a trial type), or `null` (no odor yet this trial). It **never falls back to `conditions[0]`**: a wrong condition looks exactly like a right one. `unlisted` exists because collapsing turned a missing arm (a visibly missing node) into a nameless absence; the Task tab makes the same finding at edit time as `TSK112`.

### Live token

`liveNodeId` walks the codes newest-first and returns the first node whose `entryNames` contains the code's name; `useLiveNode` scans the last `TAIL` strobes, and the condition lookup a wider `CONDITION_TAIL`, because a correction trial's repeated pokes can push the onset out of the short window. The newest-first walk is what disambiguates `LIGHTS_OFF`, which every path emits: each abort strobes its own code and then `LIGHTS_OFF`, serves its penalty delay in silence (`lazyRatDelay`, the escalating abstention delay, or `noPokeHoldTimeout`), and only then does the sketch loop strobe `INVALID_TRIAL`. So an aborted trial's token rests on `lights-off` for the whole penalty and moves to `repeat` when `INVALID_TRIAL` arrives; `LAZY_RAT` (the `lazy` node's entry) is shadowed by the `LIGHTS_OFF` after it, and is the newest code only when a profile does not declare `LIGHTS_OFF`. On error paths the outcome strobe *is* the start of a long silent delay, so an outcome marked `settlesToIti` hands the token to `iti` after `OUTCOME_SETTLE_MS`.

![A running box's panel in Mission Control: the Trial flow diagram with the live token on ITI, the collapsed condition node labelled Odor 3 with its tick lit, a status line reading "ITI · Odor 3 → left well", and below it a P(right | odor) chart, an outcome mix, live metrics and recent strobes](images/box-panel.webp)

*The same derivation live, on a box's panel. While a condition is in play (`liveConditionId`), the
collapsed node takes that condition's label and lights its tick.*

### Layout

> [!CAUTION]
> **Row placement is measured in the renderer, never multiplied in the model.** `graphLayout.ts` places the abort band at `max(authored depth, deepest measured content + gap)` — a lower bound, never a replacement, or the drawing's proportions would depend on how many groups a profile declares. `measureNode` must stay on the layout side: the chip count comes from the profile's declared groups, which `topology.ts` cannot see, and the live panel draws no chips at all. A model-side measurement would be right for one host and ~48px optimistic for the other, and the symptom is a band sitting inside a chip stack, not an error.

## The Task tab

The Task tab answers *what the animal does*; the Rig tab answers *what this box is*.

### Landing

`/task` (`routes/Task.tsx`) lists this rig's saved tasks (`TaskRow`), with open, **Duplicate**, delete and create; a door to the strobe vocabulary; and `LibraryStatusNote`, since a damaged install is the one thing that stops a task existing at all. Duplicate opens an **unsaved** copy named clear of every saved task (`GRGL copy`, `GRGL copy 2`) and **drops `legacyNames`**: a legacy name resolves to one sketch, so a copy carrying it would silently take over or lose the historical runs it decodes.

![The Task tab: a + New task row, then three saved tasks — 4-Odor Discrimination (weighted, 4 conditions, no ramp), Shaping - Both Sides (pool, 5 stages) and 2-Odor Discrimination (anti-bias, 5 stages) — each marked ready, with the Strobes door below](images/task-landing.webp)

### Editor

`/task/new` and `/task/:taskId` (`routes/TaskEditor.tsx`) is a [telemetry display](ARCHITECTURE.md#telemetry-panels) in one frame: the derived **state machine** front and centre with every **trial type** beneath it, and beside them the **parameter dial** and **trial generation**. The diagram is the fastest check that an edit did what was meant, so it is never off screen. **Every redraw comes from `tasks.preview`**: the diagram is derived from the profile the *current* definition compiles to, and validation needs the wiring, which the frontend does not hold.

- **The header** (`editor/EditorHeader.tsx`): the way back, the task's glyph and name, a **Problems** popover (every diagnostic grouped by where it lives; each one jumps to its row, the dial's Holds stop or the generation panel), the **Details** popover (category, legacy names, notes — `TaskDetailsBody`, opened once on a new task because the category decides the sketch folder), then Revert and Save.
- **One link, read from every end.** A planet, the generation panel or a machine chip lights the states it tunes; hovering a state lights its planet; a trial row or a composition segment lights its condition's tick. A chip or state click opens its home. The machine's own condition list is off here (`conditionRail={false}`): the trial rows are the accessible condition list.
- **The machine draws itself on** left to right on first sight (a `DrawOn` clip wipe, each state fading in as the wipe reaches it), and a small flat dot rides the rewarded trial from start to ITI (`happyPath`, `spinePath`). The dot is not the live token: it has no ring, and it is hidden under reduced motion and whenever anything is lit.
- **The machine has a floor and the page bends around it** (`lib/tasks/editorLayout.ts`). It is never drawn narrower than `EDITOR_MIN_W` and never scaled. **Split**: the machine and trial types in the main column, the dial and generation in an aside. **Stacked** — when the aside would squeeze the machine below its floor, as on the app's minimum window — the aside's panels move under the trial types and the page scrolls. Panels carry `layoutId`s, so they travel between homes on a spring, and the drawing's layout width moves in `WIDTH_STEP`s that glide (`useGlidingWidth`).

![The task editor for 4-Odor Discrimination: Details at the top, the state machine across the left, four trial types below it (Sandalwood, Orange, Cedar and Lemon, each with its odor line, well, fluid line, reward and weight), the Parameters dial on Session at the top right, and Trial generation set to Weighted below it](images/task-editor.webp)

### Trial types

`editor/TrialTypes.tsx`, one row per condition: name, **odor line**, answers at, paid from, reward ms, weight (weighted and pool only), go/no-go.

- **The odor line is the one choice.** Its onset code is the line's own, declared on the Rig tab ([Onset codes](#onset-codes)); choosing a line writes both, and the code is shown read-only with its number from the vocabulary. A line another row presents is listed disabled ("in row 2"). A line with no declaration says so and points at the Rig tab; a stored row that disagrees (`TSK114`) shows its code in error colour with a one-click fix and the note that the wiring may be the right thing to change.
- Every cell is a **channel name or code name**, never a pin or index. Row order is the contract ([Order is meaning](#order-is-meaning)); there is no drag handle. A new row is seeded from the last one, on the first free line.
- **Reward volume and weight live on the row** and only there — the generator reads them off the row, so the editor never offers `pool_weight_N`/`reward_time_N` anywhere else and never writes them into `params` (`isRowOwnedField`).
- Each row is **named** (`TSK110`/`TSK111`) and has a second line — its onset code and the contingency in the rig's own labels ("sandalwood → left well, paid from fluid 0 · plumbed to left well"), the one rendering that catches `TSK103` by eye — or its first problem. When the rows would not all fit two lines in the room the panel has, they go to one line and the hovered row's second line shows in a caption below.
- A no-go row outside Pool says it is never presented ([Selection modes](#selection-modes)).

![The Trial types panel for 4-Odor Discrimination under weighted selection: four rows, each with its odor line, answers at, paid from, reward ms and weight, and a second line giving its onset code (ODOR_1_ON · 101 to ODOR_4_ON · 104) and its contingency](images/task-trial-table.webp)

### Trial generation

`editor/GenerationPanel.tsx` makes how the next trial is chosen a choice of its own: the three modes as one control, a sentence on how each draws and a ✓/✗ row of what it does (`lib/taskdef/selection.ts`, a hand mirror of the [selection modes](#selection-modes)), and a **composition strip** — the session the mode would deal, each condition in its colour; two side halves for the anti-bias modes, one bar for the pool, never-presented types as outlines after it.

Below sit the groups that are selection policy: **Anti-bias selection**, **Trial pool** (the block size) and **Correction trials** (the firmware runs correction budgets as policy, and the pool has none). A group the mode never reads folds to one dimmed "not used in pool" line that still opens, so its values survive switching back; a field the mode skips inside a live group (the escalation fields under pool, the no-go window outside it) is dimmed with a note. Table-level `TSK109` shows here.

<img src="images/task-generation.webp" alt="The Trial generation panel set to Weighted: the mode switch, the hint and its facts, the composition strip split into right and left halves by row weight, Trial pool folded as not used in weighted, and the Correction trials and Anti-bias selection fields" width="360">

### Ramp

The ramp is the dial's **Holds & shaping** stop (`editor/StageList.tsx`): one compact row per stage — the trial it engages at, odor hold, well hold, response window, odor port window — with the timeline strip once there is more than one stage. Row 0 has no "engages at"; a new row is seeded from the row before it, never from a defaults table, so no stage appears carrying numbers nobody chose. Each added stage costs five tokens, which the parameter block spreads over more `SET` lines; there is no total to exhaust.

<img src="images/task-ramp.webp" alt="The Parameters dial turned to Holds &amp; shaping for 2-Odor Discrimination: a timeline of five stages engaging at trials 0, 15, 30, 50 and 80, and one row per stage with its odor hold, well hold, response window and port window, above the note that each stage costs five parameters" width="385">

### Parameter dial

`editor/ParameterOrrery.tsx`: the task's parameter categories as planets on an **orbit** — the upper half of a tilted ellipse with a fixed zenith marker. Selecting one (click, arrow keys, Home/End, or one wheel step per gesture) turns the whole orbit on one spring until it sits at the zenith, and its fields slide in from the direction of travel. Geometry is `lib/tasks/orrery.ts`. A planet with values this task pins carries a small moon; one with problems a red ring. Under reduced motion the orbit jumps.

**Stops are tabs, not groups** (`topology.ts`'s `tabOf`, `dialTabs`):

| Home | Groups |
|---|---|
| Dial: Session, Trial timing, Abstention penalty | their own group |
| Dial: Holds & shaping | `Holds & windows`, `Stage n` |
| Trial generation panel | `Anti-bias selection`, `Trial pool`, `Correction trials` |
| Trial rows | `Reward volume` (and the pool weights, which are row-owned) |

> [!IMPORTANT]
> **The fold is the app's, never the profile's.** `group` rides in `ConfigField.to_json` and therefore inside `profile_hash`, so re-filing a field in `fields.py` would give every regenerated `task.json` a new hash and split each task's runs. `QUICK_TUNE_GROUPS` (the groups the mapping step promotes) and the mode scope in `selection.ts` rest on the same reasoning. Anything comparing a tab against a node's `governedBy` folds through `tabOf` first (`nodesGovernedByTab`); the machine's chips fold the same way (`holds`, `selection`).

`settings.taskDefaults` has no editor here or anywhere; a profile's own values are edited on this tab.

## Writing a new sketch

For a firmware author adding a sketch to the bundle with its own hand-written `task.json`. Operators make tasks on the Task tab instead.

### Authoring steps

1. **Write the sketch in `firmware/`**, inside a category folder, with `<Name>/<Name>.ino`. `#include "TaskPins.h"` before `<BehaviorBox.h>` (and ship a `TaskPins.h` that declares nothing) so the app rebuilds it against each rig's wiring and vocabulary — a `BehaviorBox` sketch without it does not compile. A name must not collide with a saved task.
2. **Minimum profile:** `{ "taskName": "My Task" }`. This alone gives one bare `SET`, no form, a raw log and no diagram.
3. **Emit only codes the vocabulary holds.** Add any new one on the Strobes page first ([Editing the vocabulary](#editing-the-vocabulary)), then emit `BF_<NAME>`. Don't declare `strobes` in `task.json`; the vocabulary fills it. Which names the vocabulary holds unlocks each part of the diagram ([Nodes and outcomes](#nodes-and-outcomes)); `END_SESSION` is what lets the runner finalize cleanly.
4. **Declare every operator-tunable parameter** in `config`, with `wireKey`s that `TASK_PARAM_LIST` parses, a `metadataKey` you want in the data file, a `group` from `GROUP_ORDER` (unknown groups sort last), and ramped values **per stage**. Mind the [length cap](#the-length-cap).
5. **Declare `liveMetrics`**, one per presented condition, naming its codes. A metric whose `trigger` is an `ODOR_<n>_ON` code is what draws that condition; one scoring `WATER_POKE_NONE` draws the withhold arm.
6. **Optional:** `legacyNames`; `identify` (a baseline candidate); `kind: "utility"` with `controls` and `telemetry` for a Debug Mode tool.
7. **Restart the app** to pick the change up (an installed app gets a bundled sketch change only with a new build).

### Verify

1. Pick the sketch on a session's mapping step. A malformed `task.json` surfaces its parse error there, naming the rule (Debug Mode silently treats a broken profile as profile-less).
2. `cd sidecar && pytest tests/test_task_profiles.py tests/test_taskdef.py tests/test_discovery.py`.
3. Compile with `--warnings all` and run the host tests ([Compiling and the host tests](#compiling-and-the-host-tests)).
4. Flash a box (or run `GRGL_Sim` dry) and watch the live token; if it sticks, check that state's entry names are declared.

### Troubleshooting

| Symptom | Cause |
|---|---|
| Sketch missing from the picker | `.ino` doesn't match the folder name, or the sketch sits at the root; check `skipped` |
| No diagram, just prose | `usable` is false: `LIGHTS_ON` or all three water-poke codes undeclared |
| A condition is missing | No `liveMetrics` entry has that odor's code as its `trigger` |
| "Withheld" never appears | `WATER_POKE_NONE` declared but not scored by any metric |
| Token sticks on Reward for the ITI | `WATER_UNPOKE_L`/`_R` undeclared |
| Token jumps straight to Answer | `LIGHTS_OFF` undeclared |
| Console shows `Strobe <n>` | The firmware emitted a raw number the vocabulary never issued |
| `#error "No strobe codes…"` | Built bare — compile the folder the app generated |
| Compile error naming a `BF_` code | The code is retired or was never added; reinstate or add it on the Strobes page |
| Mapping refused, `TASK_PROFILE_INVALID` | A parameter too long for a `SET` line |
| Start refused, `PARAMS_MISMATCH`, `PARAMS_CLAMPED` or `FIRMWARE_OUTDATED` | The board's answer to the `SET` lines ([confirming the parameters](#confirming-the-parameters)) |
| A value ignored by the board | `wireKey` not parsed by `TASK_PARAM_LIST` |
| A value reverts mid-session | A ramped value declared once instead of per stage |
| Analytics splits the sketch's history | Something in `to_json` changed ([hashes](#profile-and-params-hashes)) |
| Valve never fires on a rewired rig | The sketch does not include `TaskPins.h`, so it keeps the shipped pins |

### What raises

All raise `TaskProfileError`, surfaced as `TASK_PROFILE_INVALID` ([PROTOCOL.md](PROTOCOL.md#error-codes)):

- **Parse:** a non-object root; missing `taskName`; unknown `kind`; malformed `config` (missing keys, unknown type, reserved `SEED`, a core-field collision, duplicates, a default of the wrong type, whitespace in a string default, non-string `group`/`unit`/`help`, non-numeric `min`/`max`/`step`, `min > max`); non-object `strobes` or a non-integer key (snapshots only); a `liveMetrics` entry missing a required key, or naming a code that is not live; malformed `controls` or `telemetry`; `identify` missing a half; `legacyNames` not a list of strings.
- **Load:** unreadable or invalid JSON (`couldn't read task.json: …`). A missing file is not an error.
- **Build:** a single parameter that makes a `SET` line at or over `SET_LINE_MAX` ([the length cap](#the-length-cap)).

`tasks.getProfile` returns the error with `sketchPath`. At `sessions.confirmMapping` and `port.sendStart` a profile that fails to parse is downgraded to profile-less (one bare `SET`); only the length case refuses. `build_legacy_name_index` skips a broken profile so it cannot hide every other sketch's legacy names.

### What degrades silently

| Situation | Result |
|---|---|
| A vocabulary without a name the diagram gates on | Lost diagram states, a stranded live token |
| An odor code no metric scores | Dropped from the diagram (`TSK112` on a saved task; `unlisted` live) |
| Unknown top-level keys or `group` names | Ignored; unknown groups sort last |
| Out-of-range number in the form | Clamped, never rejected |
| Half-typed number in the form | Kept as text with a warning that the box would run on the default |
| A utility profile with `liveMetrics` | Accepted, never scored |
| A `fields.py` key the firmware doesn't parse | Sent and ignored; the compiled value runs |

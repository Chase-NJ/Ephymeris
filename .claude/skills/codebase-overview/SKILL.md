---
name: codebase-overview
description: Ephymeris architecture, serial-to-analysis data flow, which doc section answers what, and the rules that are easy to break. Use before changing or debugging any sidecar, webview, Rust shell, firmware or protocol code when you don't yet know where the code lives or which rules apply. Skip for edits confined to one file you already understand.
---

# Codebase overview

## Data flow

1. **Serial in.** `ports/handler.py`: one handler per box (keyed 1–6) owns its port's state machine, a
   reader `threading.Thread`, a ring buffer and the write path. `ports/manager.py` opens ports, flashes and
   resets. Every state change goes through `ports/states.py`'s `assert_transition`.
2. **Session.** `sessions/lifecycle.py` orders everything that happens to a held session (runner, RHX
   recording, utility baseline). `sessions/runner.py` ties `IN_SESSION` serial I/O to file writing and telemetry.
3. **Files.** `sessions/writer.py` fsyncs each strobe to the `.tsv` (the write-ahead log). At clean
   finalization it builds the `.json`, and `sessions/matwriter.py` mirrors it to `.mat`; a spine run also
   gets its derived trial table (`sessions/derived.py`). Paths come from `sessions/paths.py`.
4. **Database.** SQLite, reached only through `db.write()` / `db.read()` (`DATA.md#transactions`): cohorts,
   sessions, runs, logbook, score caches.
5. **Analysis.** `analytics/reader.py` opens a run file, `scoring.py` picks its profile and caches, and
   `analytics/stream/` (pure) turns strobes into trials and numbers. See the `behavior-analysis` skill.
6. **Wire.** `server.py` serves one WebSocket; `app.py` wires services. Commands and events are defined
   in `protocol/schema.py` and generated into `protocol.py` and `src/lib/ws/protocol.ts`. The webview (`src/`)
   renders what the sidecar reports and never predicts a transition.

Other sidecar packages: `rig/` (wiring, strobe vocabulary, rig definition), `taskdef/` (task definitions →
generated sketches, BOX_Utility), `tasks/` (profiles, `START` line, seeds), `boards/`, `intan/` (RHX),
`backup/`, `logbook/`, `cohorts/`. The full table is `ARCHITECTURE.md#module-map`.

## Where to look

| Question | Read |
|---|---|
| Processes, wire, settings, ports, session lifecycle, frontend, theme | `ARCHITECTURE.md#overview`, then the section |
| Firmware, task.json, task definitions, wiring, strobe vocabulary, `START`, hashes | `TASKS.md#firmware` and siblings |
| Files on disk, crash safety, SQLite, backup, the archive walk | `DATA.md#crash-safety` and siblings |
| Scoring, metrics, profile ladder, false starts | `ANALYTICS.md#start-here` |
| Intan RHX | `RECORDING.md#the-rule` |
| Exact command or event shape | `docs/PROTOCOL.md` (generated; grep it) |
| A domain term | `GLOSSARY.md`; a decision that looks odd: `docs/adr/` |
| Setup and known open issues | `README.md` |

`TASKS.md`, `ARCHITECTURE.md`, `PROTOCOL.md` and `protocol/schema.py` are 100–210 KB each. Never read one
whole: `grep -n '^#' <file>` for headings, then Read with `offset`/`limit`. `> [!CAUTION]` callouts mark
places where a mistake yields plausible but wrong data instead of an error.

## Rules that are easy to break

- The wire changes in one place: `protocol/schema.py` (with a `doc=` on every name), then `npm run gen:protocol`, and commit the generated files. `ARCHITECTURE.md#wire-protocol`
- The sidecar owns all state; the frontend renders what it reports. `ARCHITECTURE.md#overview`
- The sidecar dies with the shell and is never respawned: it exits on stdin EOF and the shell kills it on exit; keep both halves. `ARCHITECTURE.md#process-lifecycle`
- One owner per port: every port state change goes through `assert_transition`. `ARCHITECTURE.md#port-state-machine`
- The utility baseline only touches IDLE ports, holds during a confirmed mapping, and respects a deliberate flash. `ARCHITECTURE.md#hardware-utility-baseline`
- Never sequence the runner, RHX or the utility baseline from a handler; ask `held` / `in_use` / `writing`, not the runner. `ARCHITECTURE.md#session-lifecycle`
- A SQLite column needs `SCHEMA_VERSION` + `SCHEMA` + a `MIGRATIONS` entry. `DATA.md#changing-the-schema`
- Writes that must land together share one unit by passing its `tx=`, never by nesting a second unit. `DATA.md#transactions`
- A cached score is served verbatim, so a scoring change must move the cache version: when `test_the_score_version_pins_every_input` fails, update its `CANARY`; when it passes, add a canary case or bump `SCORE_VERSION`. `DATA.md#caching`
- The strobe vocabulary is append-only: never renumber or rename; retire rather than remove anything a recorded session contains. `TASKS.md#strobe-vocabulary`
- Drive every sketch's behaviour off its task profile, never a special case in app code, and keep out of `task.json` any key that would change `profile_hash`. `TASKS.md#profile-and-params-hashes`
- `SET_LINE_MAX` lives in `tasks/start_command.py` and `BehaviorBox.h`, kept equal by `test_start_command.py`. `TASKS.md#the-length-cap`
- Only wiring saved or confirmed on this machine is put in force (digest: `wiring-confirmed.json`). Any other stored wiring is held behind RIG108 until every pin is confirmed; a restart, a hand fix or a copied file confirms nothing. Sessions, flashes, identify and the utility baseline stand down while wiring is held or unloaded. `TASKS.md#the-channel-set-and-the-pin-map`, `GLOSSARY.md#held-wiring`
- Channel declaration order is the odor index, as trial-table order is the slot index: index odor lines with `ChannelMap.declared_of_kind()`, never the pin-sorted `of_kind()`, and never reorder channels. `TASKS.md#order-is-meaning`
- A wiring change, a vocabulary edit and every startup rebuild every stored profile and bundled sketch (`RigDefinition._rebuild`); a stale folder still compiles and flashes the old pins or codes. `TASKS.md#task-definitions`
- Ask "what if" only through `registry.hypothetical`; write the rig definition only through `RigDefinition`; use a generated folder only inside `reading()`. `TASKS.md#the-rig-definition`
- BOX_Utility knows no box: its logic is `BoxUtility.h`; its channels, labels and Debug Mode grids are generated by `taskdef/utility.py`. Never hand-list channels. `TASKS.md#the-box-utility`
- `arduino-cli compile` hides type errors (`-fpermissive -w`): compile with `--warnings all` and run the firmware host tests after a shared-signature change. `TASKS.md#firmware`
- RHX may be slow, absent or dead without stalling a behavior session; only starting a recording may refuse. `RECORDING.md#the-rule`
- Backup mirroring never sits in a session's critical path. `DATA.md#backup-mirroring`
- Dark mode only; six-token palette; no gradients or glow on Pulsar; Space Grotesk for headers only. `ARCHITECTURE.md#theme`

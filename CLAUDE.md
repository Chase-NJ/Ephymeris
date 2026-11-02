# CLAUDE.md

Ephymeris is the lab's desktop app for rodent behavior sessions on six Arduino Mega2560 boxes: it flashes
task sketches, streams each box's serial strobes into per-animal session files, and manages cohorts,
sessions and analysis. A Tauri (Rust) shell starts a Python sidecar that owns all state; a React webview
renders what the sidecar reports over one WebSocket. Built for two Windows 11 lab machines, developed on macOS.

Before changing an area, load the `codebase-overview` skill (architecture, data flow, docs map, the rules
that are easy to break). For scoring, trials or `.mat`/`.json` files, load `behavior-analysis`.

## Map

- `sidecar/ephymeris_sidecar/` — the sidecar (`__main__.py`, `app.py`): ports, sessions, analytics, rig, tasks, cohorts
- `sidecar/tests/` — pytest suite; `fixtures/legacy_*.json` are huge one-line documents, never read them
- `src/` — React/TS webview (`main.tsx`); `src/lib/` holds the logic vitest covers
- `src-tauri/src/` — Rust shell; `sidecar.rs` spawns the sidecar and kills it on exit
- `firmware/` — Arduino sketches and the `BehaviorBox` library ([firmware/README.md](firmware/README.md))
- `protocol/schema.py` — the one source of the wire; generates `protocol.py`, `src/lib/ws/protocol.ts`, `docs/PROTOCOL.md`
- `docs/` — ARCHITECTURE, TASKS, DATA, RECORDING, PROTOCOL (generated), USER-GUIDE, `adr/`, `agents/`
- `scripts/` — npm helpers: check, gen-protocol, packaging, release

## Commands

```bash
npm run tauri:dev                                   # full app
npm run check                                       # protocol freshness + tsc + vitest (src/lib)
npm run gen:protocol                                # after editing protocol/schema.py
cd sidecar && .venv/bin/python -m pytest            # sidecar suite (CI adds -n 4, then runs -m load alone)
cd sidecar && .venv/bin/python -m pytest tests/test_x.py -k name
cd src-tauri && cargo test
sh firmware/libraries/BehaviorBox/extras/host_test/run.sh   # also run_box/run_interp/run_spine/run_diff.sh
```

A worktree under `.claude/worktrees/` has no venv: use the main checkout's `sidecar/.venv/bin/python`.
A hook trims pytest output to failures plus the summary; append `# raw` to a command for full output.
No linter is configured; `tsc` is the TypeScript check.

## Conventions

- Python 3, stdlib first. A runtime dependency must pass [the dependency policy](docs/ARCHITECTURE.md#dependency-policy).
- Small, logically separated functions. `analytics/stream/` stays pure (no files, db or clock); a test enforces it.
- Ad-hoc scripts and analyses save their outputs next to their inputs by default.
- The wire changes only in `protocol/schema.py` + `npm run gen:protocol`; never hand-edit generated files.
- Docs: one home per fact, current behaviour only, cite as `FILE.md#anchor`, update in the same commit
  ([rules](README.md#documentation-rules)). Name concepts with [GLOSSARY.md](GLOSSARY.md) terms.
- Branch + PR for every change ([contributing](README.md#contributing)); never commit to `main`.

## Domain facts that change behavior

- **Strobes** are `[code, timestamp]` pairs. Codes are defined only in the per-machine strobe vocabulary
  (default `sidecar/ephymeris_sidecar/rig/schema/strobe_vocab.default.json`): refer to them by name, never copy
  a number into code, `task.json`, firmware or tests. Append-only ([why](docs/TASKS.md#strobe-vocabulary)).
- **Start handshake:** board prints `INTERP=`, `FREE_RAM=`, `READY`; host sends `BEGIN`, then one `SET` line
  at a time, each answered by `PARAMS <n> <crc32>` (after any `CLAMPED <key>`). `START SEED=<n>` goes only when
  both match the host's and nothing was clamped ([details](docs/TASKS.md#confirming-the-parameters)).
- **End:** a run ends cleanly when the board emits `BF_END_SESSION` (trial cap, `STOP`, or time limit);
  `stop_reason` is then `"BF_END_SESSION received"`.
- **Naming:** folder `<prefix>_<n>_<YYYY-MM-DD>` (e.g. `2O-Bdisc_25_2026-07-22`); per-animal files
  `<animal>_<prefix>_<n>_<date>_<HHMMSS>.{tsv,json,mat}`. Order names with `sessions/paths.py`'s
  `parse_name_date`, never as strings. Legacy names such as `00_01_shaping_gr_06_17_26` are read as written
  ([layout](docs/DATA.md#directory-layout-and-naming)).
- **Crash safety:** every strobe is fsync'd to the `.tsv` live; `.json`/`.mat` are built once at clean finalization.
- Ports are keyed by box number 1–6, never a COM address. Session data lives outside the repo, in the
  configured data directory.

## Agent skills

Issue tracker: GitHub Issues on `Chase-NJ/Ephymeris` via `gh` ([docs/agents/issue-tracker.md](docs/agents/issue-tracker.md)).
Triage labels: [docs/agents/triage-labels.md](docs/agents/triage-labels.md). Domain docs: [docs/agents/domain.md](docs/agents/domain.md).

# Compact instructions

When compacting, keep: every file changed and why; decisions and constraints the user stated (verbatim
where short); failing tests and error messages with their file:line; the current branch/PR; remaining TODOs.
Drop: exploratory file dumps, full test logs, grep output, and doc text that can be re-read on demand.

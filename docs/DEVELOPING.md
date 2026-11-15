# Developing Ephymeris

Building, testing, releasing and contributing. How the system works is in
[ARCHITECTURE.md](ARCHITECTURE.md); installing and using the app is in the [README](../README.md).

Ephymeris is three processes: a desktop shell (`electron/`), a React webview (`src/`) and a Python sidecar
(`sidecar/`) that owns all hardware and data state ([ARCHITECTURE.md](ARCHITECTURE.md#overview)). Until
both lab PCs have moved to the Electron shell, the Tauri shell (`src-tauri/`) is still in the repository
([ADR 0006](adr/DECISIONS.md#0006-the-shell-is-electron-not-tauri)).

## Setup

| Tool | Version | Why |
|---|---|---|
| Node.js | 20.19+ or 22.12+ | Vite's `engines` field |
| Python | 3.12+ (3.13 for packaging) | `requires-python` in `sidecar/pyproject.toml` |
| `arduino-cli` | recent | on `PATH`, or set on the Rig tab |
| Rust | stable | only for the Tauri shell (`npm run tauri:dev`, `cargo test`), until it is removed |

**Windows 11:** install Node.js and Python (tick **Add python.exe to PATH**), then
`winget install ArduinoSA.CLI`. **macOS:** `brew install node python arduino-cli`. On both:

```bash
arduino-cli core update-index && arduino-cli core install arduino:avr
git clone https://github.com/Chase-NJ/Ephymeris.git
cd Ephymeris && npm install
```

The shell runs the sidecar from exactly `sidecar/.venv` (or the interpreter `EPHYMERIS_SIDECAR_PYTHON`
names):

```powershell
python -m venv sidecar\.venv; sidecar\.venv\Scripts\pip.exe install -e "sidecar[dev]"   # Windows
```

```bash
python3 -m venv sidecar/.venv && sidecar/.venv/bin/pip install -e "sidecar[dev]"         # macOS
```

The `dev` extra brings pytest (with pytest-xdist), the gRPC code generator and PyInstaller. Then run the
app with `npm run electron:dev` and do the README's [rig set-up](../README.md#set-up-the-rig-once). A dev
run reads the sketch library from `firmware/` in place ([its README](../firmware/README.md));
`EPHYMERIS_SKETCH_LIBRARY` points it elsewhere.

| Symptom | Cause |
|---|---|
| `predev` fails: the firmware folder is missing | `firmware/` was deleted or the checkout is partial |
| "Sidecar interpreter not found" | No venv at `sidecar/.venv`, or one older than Python 3.12 |
| `.venv/bin/pytest` fails with "No such file" | The repo moved after the venv was made; run `python -m pytest` or recreate the venv |
| The app opens but nothing connects | The sidecar exited (never respawned, by design); its stderr is in the terminal running the app |

## Commands

| Command | What it does |
|---|---|
| `npm start` / `npm run electron:dev` | The full app: regenerates the protocol, compiles `electron/`, starts Vite on 1420, opens the window. Arguments after `--` go to Electron |
| `npm run tauri:dev` | The same under the Tauri shell, while it exists |
| `npm run dev` | Vite alone on port 1420, for a plain-browser preview |
| `npm run build` / `npm run build:electron` | `tsc` and a production Vite build into `dist/`; compile `electron/` into `dist-electron/` |
| `npm run check` | Protocol mirrors current, both typechecks, unit tests; all run even after a failure |
| `npm run test` / `test:watch` | Vitest over `src/lib/**` and `electron/**` |
| `npm run gen:protocol` | Regenerate `protocol.py`, `protocol.ts` and `PROTOCOL.md` from `protocol/schema.py` |
| `npm run package:electron` | Stage resources and build the Electron installer into `release/` ([below](#building-the-installer)) |
| `npm run package` | Stage resources and build the Tauri installer, while it exists |
| `pytest` in `sidecar/` | The sidecar suite; CI adds `-n auto --dist worksteal`, then runs `-m load` alone |
| `cargo test` in `src-tauri/` | The Tauri shell's tests, while it exists |
| `firmware/libraries/BehaviorBox/extras/host_test/run.sh` | Firmware host tests; `run_box.sh`, `run_interp.sh`, `run_spine.sh`, `run_diff.sh` for the utility, the interpreter, the spine runner and core-vs-replay |

## Tests

**Frontend: Vitest over `src/lib/**` and `electron/**`, with no DOM.** It pins the arithmetic and
decoding that produce a drawing or readout that looks deliberate when wrong (the derived state machine,
its layout, the strategy plane, the cohort sky, the probe geometry and firing map), and the Electron shell's pure parts.
Stores are tested through `FakeSidecar` (`lib/ws/fakeSidecar.ts`); `ws/port.contract.test.ts` holds it to
the real client's rules. `lib/shell/boundary.test.ts` keeps each shell inside `lib/shell`. There is no
linter; `tsc` is the type check.

**Sidecar: pytest in `sidecar/tests/`.** `conftest.py` sets `EPHYMERIS_WIRE_VALIDATE=1`, so every reply
and event is checked against `protocol/schema.py`. Tests run in parallel and share nothing: no fixed
port, no path outside `tmp_path`, no unrestored module state. Test a command through the `sidecar`
fixture (`tests/live_sidecar.py`, the real server over a WebSocket with only the board tool and serial
faked), and set up the database through its repositories, not raw SQL. The guards that matter most:

| Test | Guards |
|---|---|
| `test_protocol_contract.py` | The generated mirrors match the schema; every wire name is in PROTOCOL.md |
| `test_wire_shapes.py` | The real emitters conform to the schema; extend it with each new emitter |
| `test_migrations.py` | Old schemas, pinned as literals, upgrade |
| `test_analytics_*.py` | Inference matches the declared profile; metric definitions; `analytics/stream/` stays pure; the score cache version moves with every input |
| `test_legacy_pin.py`, `test_legacy_corpus.py` | The legacy adapter on a pinned corpus and, with `EPHYMERIS_CORPUS`, a real archive. Never regenerate their fixtures from the code under test |
| `test_taskdef.py`, `test_strobes.py` | The strobe vocabulary against the firmware's names; vocabulary edits |
| `test_flash_queue.py`, `test_debug_flash.py` | One compile at a time; restores upload one at a time; Debug flashes survive the baseline |
| `test_writer.py` | Kills a child mid-write to prove the `.tsv` crash guarantee |
| `test_doc_links.py` | Every `FILE.md#anchor` cited anywhere exists |

`test_grpc_tool.py` needs a real `arduino-cli`, and `test_intan_real_rhx.py` runs only with
`EPHYMERIS_REAL_RHX=1`; the rest of the Intan suite runs against `tests/fake_rhx.py`.

**Firmware: host tests** compile the shared library without `-fpermissive`, the strictest type check the
sketches get ([TASKS.md](TASKS.md#compiling-and-the-host-tests)).

> [!CAUTION]
> `arduino-cli compile` hides type errors (`-fpermissive -w`): a wrong argument type compiles and exits 0.
> After a shared-signature change, compile every sketch with `--warnings all` and run the host tests.

## Continuous integration and releases

| Workflow | Runs on | Does |
|---|---|---|
| `check.yml` | every push to `main` and every PR | `npm run check`, the sidecar suite on Windows and Linux, firmware host tests and compiles |
| `release.yml` | a pushed `v*` tag | builds the installers and attaches them to a **draft** pre-release |
| `ship-main.yml` | by hand | builds `main` as `<package.json version>.<commit count>` and publishes it |
| `installer.yml` | called by the two above | the one copy of the build steps, on a clean Windows runner |
| `publish-update.yml` | publishing a release | points the update feed (`updates` branch) at it ([ARCHITECTURE.md](ARCHITECTURE.md#updates)) |

Tests that need hardware, `arduino-cli`, RHX or the lab's probe maps skip themselves in CI.

**A tagged release:** set the version in `package.json` (and `src-tauri/tauri.conf.json` while it exists),
commit, then `git tag v1.2.0-alpha && git push origin main --tags`. The workflow refuses a tag that
disagrees. Write the draft's notes and publish it: **publishing is shipping**; every installed copy finds
it at its next check.

**Shipping main:** `gh workflow run ship-main.yml --ref main`. It needs no bump or tag; the commit count
makes `1.1.3-alpha` ship as `1.1.3-alpha.214`, above the release it follows and below the next. It runs
only from `main` and refuses a version the feed already holds or has passed.

## Building the installer

```bash
npm run package:electron
```

`scripts/package-resources.mjs` stages `build/resources/`: the sidecar frozen with PyInstaller from
`sidecar/.venv`, `arduino-cli` from `PATH`, a clean `arduino:avr` core (needs the network once; delete
`build/resources/` to re-seed), and the sketch library from `firmware/`. `electron-builder`
(`electron-builder.yml`) then writes `release/Ephymeris-<version>-setup.exe`, its `.blockmap` and
`latest.yml`. The frozen sidecar carries the Python that built it; use 3.13, as CI does (3.12's Windows
asyncio clock makes short waits end early). Packaging is proven on Windows only; the installer is
unsigned.

## Dependency policy

Lab machines never run `pip`: the installer ships a frozen sidecar. A sidecar runtime dependency is
welcome when it meets all four:

1. **Stable and widely used**, with Windows x64 wheels for the CPython the freeze uses.
2. **It removes code we maintain**, which is then deleted.
3. **No runtime cost on the session path**: import it inside the function that needs it, or load a heavy
   one on a thread at startup, and measure.
4. **Fenced**: a failed import costs only the feature that uses it.

| Dependency | For | Fence |
|---|---|---|
| `grpcio`, `protobuf` | The `arduino-cli` daemon backend | Falls back, loudly, to the subprocess backend: live streaming is lost, never flashing |
| `jsonschema` | Validating wiring documents and task profiles | Imported only where needed; a failure disables those editors only |
| `scipy` (`numpy`) | The `.mat` mirror ([DATA.md](DATA.md#the-mat-mirror)) | Imported only in `matwriter`; a failure costs the `.mat`, never the `.tsv` or `.json` |

The shell's `electron-updater` is fenced the same way: only the main process's update channels reach it,
and a failed check costs the Updates tile its answer. Small maths stays hand-written when the import
costs more than the code (the Wilson interval, [ANALYTICS.md](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#uncertainty)).
Frontend packages are bundled at build time; `@react-pdf/renderer` still loads only through a dynamic
`import()` in the log's PDF export.

## Open issues

### Not yet done

- **The live scorer in the frozen Windows sidecar** has not started on a lab machine
  ([ARCHITECTURE.md](ARCHITECTURE.md#the-live-scorer)). If it fails, live numbers read unavailable and
  nothing else changes.
- **A full-length recording from a real animal** ([RECORDING.md](RECORDING.md#not-yet-verified)). Rigs
  with a saved wiring document have no sync channel until one is added.
- **A spine task with an animal or catch vessel** on a real box, and its trial table in Analytics
  ([TASKS.md](TASKS.md#spine-tasks)).
- **PWM, tone and pulse trains** and **Pavlovian conditioning** measured on a real box
  ([TASKS.md](TASKS.md#driven-outputs)).

### Known bugs

- `sessions.status` reports `groupId: ""` with no group held; `sessions.active` reports `null`.

### Open decisions

- Analytics with large cohorts: the session rail grows long; the animal colours repeat past six.
- `cohorts.list`, `prefixes.list` and `cohorts.suggestGroups` have no frontend caller.
- Frontend coverage beyond the pure layer and two stores; no linter.
- `settings.taskDefaults` has no editor, so stale entries cannot be cleared.
- No back-pressure policy on `port.output`.
- Nothing prompts to bind a newly appeared board.
- Archiving has no confirmation, on purpose (it is reversible).
- Code-signing the installer, to remove the SmartScreen dialog.
- `kind` in a task profile is a convention, not a schema gate.

### Deferred by decision

| Item | Decision |
|---|---|
| Resuming a group mid-run, auto-respawning the sidecar, recovering from a board drop | No: each would come back without the state it had; the `.tsv` is the record |
| Light mode | Not in v1 |
| Sketches from outside the bundled library, or a watcher on it | No; saved tasks extend it, and it changes only when the app does |
| A `states`/`graph` key in `task.json` | No: it changes `profile_hash` and splits a sketch's runs |
| Uploaded cohort artwork | Deferred; a cohort's world is procedural |

## Contributing

Commit with a short imperative summary and detail in the body when it helps. Three rules cover most of
the risk:

1. **The wire mirrors are generated.** Edit `protocol/schema.py`, run `npm run gen:protocol`, commit the
   regenerated files ([ARCHITECTURE.md](ARCHITECTURE.md#wire-protocol)).
2. **Box number 1–6 is the key everywhere**, never a COM port.
3. **The sidecar enforces state transitions**, not the UI.

### Documentation rules

- **One home per fact**; others link to it.
- **Current behaviour only.** No history. A past mistake stays only as a rule with its reason, in
  [LESSONS.md](LESSONS.md); a decision's reason and rejected options go in the
  [decision record](adr/DECISIONS.md).
- **Cite docs from code as `FILE.md#anchor`**, never by section number. `test_doc_links.py` checks every
  citation.
- **Update the doc in the same commit as the behaviour.**
- **At most 10 pages (5,000 words, visuals excluded) per doc**, and 3 for the README.
- **`PROTOCOL.md` is generated** from `protocol/schema.py`.
- **Keep every `> [!CAUTION]`**: each marks a place where a mistake yields plausible but wrong data.

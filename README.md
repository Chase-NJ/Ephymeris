# Ephymeris

Ephymeris is a desktop app for running rodent behaviour sessions on up to six Arduino Mega2560 R3
boards, one per behaviour box. It flashes the task firmware to the boards, streams their serial output
while animals run, writes every event to that animal's data file as it arrives, and keeps the
bookkeeping around it: cohorts, animals, groups, session prefixes and session records. An Analytics view
reads the recorded archive back and draws learning curves, per-condition accuracy and strategy plots.
A session can also drive an Intan RHX electrophysiology recording alongside the behaviour.

![The Ephymeris Dashboard on a six-box rig: Start a Session and Start a Recording at the top left, the rig's boxes drawn as stars in a 3D sky, and tiles for the Rig, Task, Cohorts, Boxes (6/6 connected) and Analytics with recent sessions](docs/images/dashboard.webp)

*The Dashboard. Each star in the sky is a behaviour box; the figure in the sidebar's corner is the same six boxes as a status readout, on every screen.*

It is built for the Hart Lab's two Windows 11 lab machines and developed on macOS. The people who run
sessions are lab members, not programmers. They should read the [user guide](docs/USER-GUIDE.md).
Maintainers should start with [Architecture](docs/ARCHITECTURE.md).

**Status.** The current version is in `package.json`. Every feature — cohorts, the Rig, Task and
Recording tabs, Debug Mode, Settings, the full session flow, backup mirroring, Analytics and recording
with Intan RHX — has been tested and run on real hardware. The one thing not yet done is a
full-length recording from a real animal ([Not yet verified](docs/RECORDING.md#not-yet-verified)).
Analytics decodes two of the lab's real archives end to end. The Windows installer builds, but it is
unsigned and there is no CI.

## Documentation

| Document | Read it if you… |
|---|---|
| [docs/USER-GUIDE.md](docs/USER-GUIDE.md) | run sessions: setting up a cohort, running and watching a session, results, troubleshooting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | maintain the app: processes, wire rules, settings, the port state machine, the utility baseline, the session lifecycle, frontend rules, theme, module map |
| [docs/TASKS.md](docs/TASKS.md) | write firmware or define tasks: the sketch library, `task.json`, task definitions, rig wiring, strobe vocabulary, the `START` line, the derived state machine |
| [docs/DATA.md](docs/DATA.md) | touch anything written to disk or analysed: file layout, crash safety and recovery, SQLite, backup, the archive walk, metric definitions |
| [docs/RECORDING.md](docs/RECORDING.md) | work on the Intan RHX integration |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | need the exact shape of a command, event or error code. **Generated** from `protocol/schema.py`; never edit it by hand |
| [CLAUDE.md](CLAUDE.md) | are an AI coding agent: the load-bearing invariants in brief |

## Installing on a lab machine

The installer is self-contained. The machine needs no Python, Node, Arduino IDE or internet: the frozen
backend, `arduino-cli` and the `arduino:avr` toolchain all ship inside it.

1. Copy `Ephymeris_<version>_x64-setup.exe` to the machine and run it. It installs per user, so no
   administrator account is needed.
2. The installer is not code-signed, so Windows shows **"Windows protected your PC"**. Click **More info**,
   then **Run anyway**. This is expected.
3. Launch Ephymeris from the Start menu. On first launch it copies its Arduino toolchain into a writable
   folder, so boards can take a few extra seconds to appear that once.
4. Set up the rig on the **Rig** tab:
   - **Boxes**: click **Add box** once per behaviour box, give each a **Label**, and pick its board under
     **Bound board** (boards are listed by USB serial number). **Test** opens the box's console and
     waits for its firmware to announce itself.
   - **Utility baseline**: choose the **Hardware utility sketch** (`BOX_Utility`). Idle boxes are kept on
     it, which is what lets the app light a box during animal placement.
   - **Hardware**: the **Default baud rate** (leave at 115200 unless the firmware changes) and an
     optional **arduino-cli path override**.
   - **Wiring** opens the channel-to-pin editor. A recording rig needs a sync channel added here.
5. In **Settings → Storage**, choose the **Data directory** where session files go, and optionally a
   **Backup directory** on another drive or share.
6. Save at least one task on the **Task** tab and create a cohort on **Cohorts**. Then start from the
   Dashboard's **Start a Session**.

The app installs to `%LOCALAPPDATA%\Ephymeris`. Its own state (the cohort database, settings, the
writable toolchain copy, saved tasks) lives in `%APPDATA%\edu.hartlab.ephymeris`. Session data goes
wherever the Data directory points. Uninstalling removes the app but leaves both data locations alone.
To update, run a newer installer over the old one.

## Developer setup

Ephymeris is three processes: a Rust/Tauri shell, a React webview and a Python sidecar that owns all
hardware and data state ([Architecture](docs/ARCHITECTURE.md#overview)). Both platforms run the same
arrangement; only the system toolchain and the venv path differ.

### Prerequisites

| Tool | Version | Source of the requirement |
|---|---|---|
| Node.js | 20.19+ or 22.12+ | Vite's `engines` field |
| Python | 3.12+ | `requires-python` in `sidecar/pyproject.toml` |
| Rust | stable (at least `rust-version` in `src-tauri/Cargo.toml`) | via [rustup](https://rustup.rs) |
| `arduino-cli` | recent | on `PATH`, or set on the Rig tab |

**Windows 11.** Install Node.js, Python (tick **Add python.exe to PATH**) and rustup. Tauri also needs
the Microsoft C++ Build Tools: in the Visual Studio Build Tools installer, select *Desktop development
with C++*. WebView2 already ships with Windows 11. Then `winget install ArduinoSA.CLI`.

**macOS.** `xcode-select --install`, then `brew install node python rustup arduino-cli` and `rustup-init`.

On both, install the AVR core the Mega compiles against:

```bash
arduino-cli core update-index && arduino-cli core install arduino:avr
```

### Clone and install

```bash
git clone https://github.com/Chase-NJ/Ephymeris.git
git clone https://github.com/Chase-NJ/Arduino.git   # the firmware, as a sibling: ../Arduino
cd Ephymeris && npm install
```

The firmware lives in its own repo. `npm run stage:sketches` copies it into this repo's gitignored
`sketches/` (`predev` runs it for you). Edit firmware in `../Arduino` and commit it there: anything
edited under `sketches/` is overwritten at the next stage. Set `EPHYMERIS_FIRMWARE_REPO` if the
firmware repo lives elsewhere; `EPHYMERIS_SKETCH_LIBRARY` points a dev sidecar at another library.

### Sidecar virtual environment

The shell looks for the interpreter at exactly `sidecar/.venv`. To keep it elsewhere, point
`EPHYMERIS_SIDECAR_PYTHON` at the interpreter.

```powershell
# Windows (PowerShell)
python -m venv sidecar\.venv; sidecar\.venv\Scripts\pip.exe install -e "sidecar[dev]"
```

```bash
# macOS
python3 -m venv sidecar/.venv && sidecar/.venv/bin/pip install -e "sidecar[dev]"
```

The `dev` extra includes pytest, the gRPC code generator and PyInstaller, so the same venv can build
the installer.

### Run it

```bash
npm run tauri:dev
```

This regenerates the protocol mirrors, stages the sketches, starts Vite on port 1420, builds the shell,
spawns the sidecar and opens the window. The first run compiles the Rust dependencies and takes a few
minutes. On first launch, do steps 4 to 6 of [Installing on a lab machine](#installing-on-a-lab-machine).

### Troubleshooting

| Symptom | Cause |
|---|---|
| `predev` fails: firmware repo not found | `../Arduino` is missing. Clone it, or set `EPHYMERIS_FIRMWARE_REPO` |
| No boards detected | Genuine Mega2560 R3 boards need no driver, but CH340 clones do. Ephymeris lists only what `arduino-cli board list` reports |
| "Sidecar interpreter not found" | No venv at `sidecar/.venv`, or one made with Python older than 3.12 |
| `.venv/bin/pytest` fails with "No such file" | The repo moved after the venv was made, and its scripts point at the old path. Run `python -m pytest`, or recreate the venv |
| A box will not flash after a failure | A failed flash leaves the port in `ERROR`, and `ERROR → FLASHING` is refused. Acknowledge the fault first |
| The app opens but nothing connects | The sidecar exited. There is no automatic respawn by design; restart the app. Its stderr is in the Tauri log |

## Commands

Run from the repo root unless noted.

| Command | What it does |
|---|---|
| `npm run tauri:dev` | The full app: shell, sidecar and webview |
| `npm run dev` | Vite alone on the fixed port 1420 (Tauri expects it). `predev` regenerates the protocol and stages sketches first |
| `npm run build` | `tsc --noEmit`, then a production Vite build. `prebuild` regenerates the protocol |
| `npm run preview` | Serve the production build |
| `npm run typecheck` | `tsc --noEmit` only |
| `npm run test` / `npm run test:watch` | Vitest over `src/lib/**`, once or watching |
| `npm run check` | Protocol mirrors up to date, typecheck and unit tests; runs all three even after a failure |
| `npm run gen:protocol` | Regenerate `sidecar/ephymeris_sidecar/protocol.py`, `src/lib/ws/protocol.ts` and `docs/PROTOCOL.md` from `protocol/schema.py` |
| `npm run stage:sketches` | Copy `../Arduino` into `sketches/` |
| `npm run package` | Stage installer resources, then build the Windows installer |
| `pytest` (in `sidecar/`, inside the venv) | The sidecar suite |
| `pytest tests/test_protocol_contract.py` (in `sidecar/`) | The mirror-drift guard; run it after any wire change |
| `cargo test` (in `src-tauri/`) | Shell unit tests, such as the handshake parser |
| `libraries/BehaviorBox/extras/host_test/run.sh` (in `../Arduino`) | Firmware host tests for the shared library; `run_box.sh` tests `BOX_Utility` |

## Tests

**Frontend: Vitest, `src/lib/**` only, and deliberately no DOM.** What is worth pinning there is the
arithmetic and decoding that yield a drawing or readout that looks deliberate when it is wrong: the
derived state machine (`tasks/topology.ts`), its layout (`tasks/graphLayout.ts`), the strategy plane's
axes (`analytics/view.ts`), cohort appearance, the cohort sky layout and the scope maths. A component
test would need a DOM, a settings context and a WebSocket client to assert what a screenshot shows
better. There is no linter.

**Sidecar: pytest, `sidecar/tests/`.** `conftest.py` sets `EPHYMERIS_WIRE_VALIDATE=1` for the whole suite,
so every event and command reply is checked against `protocol/schema.py`; production leaves it off.
The guards that matter most:

- `test_protocol_contract.py`: the generated mirrors match the schema, and every wire name appears in
  the protocol doc.
- `test_wire_shapes.py`: the real `to_json` emitters conform to the schema. Extend it when you add an emitter.
- `test_migrations.py`: pins old schemas as literal fixtures and upgrades them.
- `test_analytics_infer.py`: inference from the strobe stream scores identically to the declared GRGL
  profile. Extend it before touching either side.
- `test_analytics_derive.py`: the metric definitions, and the payload's field names against `CODEC_VERSION`.
- `test_taskdef.py`: the strobe vocabulary against the firmware's `BoxStrobes.h`, in both directions.
- `test_debug_flash.py`: a Debug Mode flash survives the utility baseline, and Debug scoring matches a session's.
- `test_writer.py`: kills a child mid-write to prove the `.tsv` crash guarantee.
- `test_doc_links.py`: every `FILE.md#anchor` cited anywhere in the repo exists.

Some tests need outside things and skip without them: `test_grpc_tool.py` drives a real `arduino-cli`
daemon when one is installed, and `test_intan_real_rhx.py` runs only with `EPHYMERIS_REAL_RHX=1`
against a live RHX. Everything else in the Intan suite runs against `tests/fake_rhx.py`.

**Rust: `cargo test`** in `src-tauri/`, for the sidecar handshake parser and other shell units.

**Firmware: host tests** in `../Arduino/libraries/BehaviorBox/extras/host_test/`. They compile the
shared library without `-fpermissive`, which makes them the strictest type check the sketches get.

> [!CAUTION]
> `arduino-cli compile` hides type errors: the AVR core builds with `-fpermissive -w`, so a wrong
> argument type is a suppressed warning and the compile exits 0. After any shared-signature change,
> compile every sketch with `--warnings all` and run the host tests. See [Firmware](docs/TASKS.md#firmware).

## Building the installer

From a development machine that already runs the app from source:

```bash
npm run package
```

`scripts/package-resources.mjs` stages `src-tauri/resources/`: it freezes the sidecar with PyInstaller
from `sidecar/.venv`, copies `arduino-cli` from this machine's `PATH`, seeds a clean `arduino:avr` core
(this needs the network once), and stages the sketch library from `../Arduino`. Then `tauri build`
merges `src-tauri/tauri.bundle.conf.json` and writes an NSIS installer to
`src-tauri/target/release/bundle/nsis/`. Delete `src-tauri/resources/` to force a fresh stage.

The installer is unsigned and built by hand; there is no CI build. Packaging has only been run on
Windows. The script is written platform-neutrally, but a macOS package has never been built, so treat
macOS as run-from-source. Packaged-only path bugs exist (Windows verbatim `\\?\` paths); see
[Architecture](docs/ARCHITECTURE.md#process-lifecycle).

## Open issues

### Not yet done

- **A full-length recording from a real animal.** Recording has been run through the app against a
  real RHX and real boxes; a complete recording session with an animal has not.
  [Not yet verified](docs/RECORDING.md#not-yet-verified) lists what to watch for on the first one.
  Every rig with a saved wiring document has no sync channel until one is added on the wiring page.

### Known bugs

- `sessions.status` reports `groupId: ""` when no group is held, while `sessions.active` reports `null`
  for the same state (`app.py` applies `or None` in one place only). Pick one.

### Open decisions

- **Analytics with large cohorts.** The session rail grows long over many sessions, and the six-colour
  animal ramp repeats past six animals.
- **Unused sidecar commands.** `cohorts.list`, `prefixes.list` and `cohorts.suggestGroups` have handlers
  but no frontend caller; Auto-Balance runs client-side in `src/lib/cohorts/grouping.ts`. Remove them,
  or route Auto-Balance through the sidecar.
- **Frontend coverage beyond the pure layer.** Stores (`lib/sessions/store.ts`, `lib/hardware/store.ts`),
  the session flow's step transitions and every component are untested, and there is no linter.
- **A "flash all six" in Debug Mode**: whether to have one, whether it halts at the first failure as the
  session sequence does, and whether it is one command or six.
- **Settings schema.** The sidecar reads only the keys it needs and ignores the rest, so adding a key is
  deliberately cheap; the set is not final. `settings.taskDefaults` has no editor, so stale entries
  (inert, but present) cannot be cleared.
- **Back-pressure on `port.output`.** Sends are unbounded, relying on the ring-buffer cap. No policy
  exists for a frontend that cannot keep up; not yet seen as a problem.
- **Board re-binding.** A swap is confirmed with the Rig tab's Test, but nothing yet says "a new board
  appeared, bind it to box 3?".
- **Archive has no confirmation**, on purpose: archiving is reversible and only permanent delete is
  gated. Revisit if it proves too easy to trigger.
- **Installer signing and a CI build.** Signing would remove the SmartScreen dialog; CI would make the
  installer reproducible and untie it from one machine's `arduino-cli`.
- **`kind` in a task profile is a convention**, not a schema gate: a `utility` profile carrying
  `liveMetrics` is accepted and never scored. Enforce it only if it causes confusion.

### Deferred by decision

These were decided, not missed.

| Item | Decision |
|---|---|
| Resuming a group mid-run after a restart | Out of scope. Continuing *between* groups is built; if the sidecar dies mid-group the run is over and the `.tsv` is the record |
| Auto-respawn of a crashed sidecar | No. It would come back without the port ownership or session state it had |
| Auto-recovery from a board drop mid-session | No. Always a hard stop into `ERROR`, cleared by hand; the write-ahead log means no data is lost |
| Light mode | Not in v1, not even a placeholder toggle |
| Sketches from outside the bundled library | No. One source keeps the empty and error states unambiguous; saved tasks extend it |
| `scipy` for `.mat` files | No. A hand-written MAT v5 writer keeps the sidecar's dependencies minimal |
| A `states`/`graph` key in `task.json` | No. It changes `profile_hash` and splits a sketch's runs in Analytics |
| Uploaded cohort artwork | Deferred. A cohort's world is procedural and tunable with four fields |
| A live filesystem watcher on the sketch library | Not needed. The library only changes when the app does |

## Contributing

Work on a branch off `main` and open a pull request. Commit messages are a short imperative summary
("Echo the flash command from the arguments actually sent"), with detail in the body when it helps.
Read [CLAUDE.md](CLAUDE.md) before a non-trivial change: it lists the invariants that bite.

Three rules cover most of the risk:

1. **The wire mirrors are generated.** Edit `protocol/schema.py`, run `npm run gen:protocol`, commit the
   regenerated files, and run the contract test. See [Wire protocol](docs/ARCHITECTURE.md#wire-protocol).
2. **Box number 1–6 is the key everywhere**, never a COM port address.
3. **The sidecar enforces state transitions**, not the UI. A disabled button is a courtesy.

### Documentation rules

- **One home per fact.** Each fact lives in one document; others link to it.
- **Current behaviour only.** No history ("used to", "was replaced by"); git has it. A past mistake stays
  only as a rule with its reason, when someone is likely to repeat it.
- **Cite docs from code as `FILE.md#anchor`**, for example `DATA.md#crash-safety`. Never cite a section
  number: numbers go stale silently. `sidecar/tests/test_doc_links.py` checks that every cited anchor
  exists and that no code cites a section number.
- **Update the doc in the same commit as the behaviour.**
- **`docs/PROTOCOL.md` is generated** from `protocol/schema.py`. Edit the schema, never the doc.
- **Keep every `> [!CAUTION]`.** It marks a place where getting it wrong yields plausible but wrong data
  rather than an error.

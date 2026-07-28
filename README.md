# Ephymeris

A lab desktop app for running rodent behavior sessions on up to six Arduino Mega2560 R3 boards ("boxes").

Ephymeris covers the whole loop of a behavior session. It discovers your sketches and flashes them to the right boards, opens the serial ports and streams live data while animals run, parses the boards' strobe protocol into per-animal data files as trials arrive, and keeps the cohort, animal, group, and session bookkeeping that surrounds all of it. A built-in Analytics dashboard then reads the recorded archive back and derives learning curves, per-condition accuracy, and strategy plots.

Three things shape how it works:

- **The backend owns the truth.** A Python sidecar owns serial I/O, `arduino-cli`, the SQLite database, and file writing. The UI renders what the sidecar reports and never predicts hardware state.
- **Boxes are numbered, not addressed.** A box is 1–6, bound to a physical board by its USB hardware id — so a box keeps pointing at the same board after Windows renumbers COM ports.
- **Data is written as it arrives.** Every parsed trial is flushed and `fsync`'d to that animal's `.tsv` immediately, so a crash mid-session costs nothing already recorded. The `.json`/`.mat` files are built at clean finalization.

Sketches stay data-driven: a sketch can ship a `task.json` describing its start-command fields, strobe codes, and live metrics, and the app builds its config form and live charts from that. No task is special-cased in app code.

Built for two Windows 11 lab machines; developed on macOS and Windows.

**Status: v1.0 in progress.** Cohorts, Config, Debug Mode, Settings, Backup Directory mirroring, and the complete session flow (config → mapping → flash → Mission Control → 3D constellation) are implemented, and everything but the mirroring is verified against real hardware. Analytics is built and decodes the lab's real archive end to end. Windows packaging is unstarted — there is no installer yet, so the app runs from source on both platforms. See [docs/TODO.md](docs/TODO.md) for the full register.

---

## Getting it running

There is no packaged build yet. Both platforms run the same three-process dev setup, and the only real differences are the system toolchain and the path to the Python interpreter.

### 1. Install the prerequisites

Common to both platforms:

| Tool | Version | Notes |
|---|---|---|
| Node.js | 20+ | |
| Python | 3.12+ | |
| Rust | stable | Install via [rustup](https://rustup.rs) |
| `arduino-cli` | recent | Must be on your `PATH`, or set an explicit path in Config |

<details open>
<summary><strong>Windows 11</strong></summary>

Install [Node.js](https://nodejs.org), [Python](https://www.python.org/downloads/windows/) (tick **Add python.exe to PATH** in the installer), and [rustup](https://rustup.rs).

Tauri also needs the **Microsoft C++ Build Tools**. Install them from the [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) installer, selecting the *Desktop development with C++* workload. WebView2 is already part of Windows 11, so there is nothing to do there.

Then `arduino-cli`, most easily via winget:

```powershell
winget install ArduinoSA.CLI
```

</details>

<details open>
<summary><strong>macOS</strong></summary>

Xcode Command Line Tools provide the compiler and linker Tauri needs:

```bash
xcode-select --install
```

The rest via [Homebrew](https://brew.sh):

```bash
brew install node python rustup arduino-cli
rustup-init
```

</details>

Finally, install the AVR core that the Mega2560 compiles against — same on both platforms:

```bash
arduino-cli core update-index
arduino-cli core install arduino:avr
```

### 2. Get the code and install dependencies

```bash
git clone https://github.com/Chase-NJ/Ephymeris.git
cd Ephymeris
npm install
```

### 3. Create the sidecar virtual environment

The Tauri shell looks for a Python interpreter at exactly `sidecar/.venv`. This is the one step whose command differs by platform.

**Windows 11 (PowerShell):**

```powershell
python -m venv sidecar\.venv
sidecar\.venv\Scripts\pip.exe install -e "sidecar[dev]"
```

**macOS:**

```bash
python3 -m venv sidecar/.venv
sidecar/.venv/bin/pip install -e "sidecar[dev]"
```

If you keep the environment somewhere else, point `EPHYMERIS_SIDECAR_PYTHON` at the interpreter instead.

### 4. Run it

```bash
npm run tauri:dev
```

That builds the Rust shell, starts the Vite dev server on port 1420, spawns the Python sidecar, and opens the app window. The first run compiles the Rust dependencies and takes a few minutes; later runs are fast.

### 5. First-launch setup

Nothing is guessed or shipped with defaults — point the app at your own folders and hardware:

1. **Config** opens a five-step box setup wizard on first launch. Add a row per behavior box, bind each to a connected board (boards are listed by USB serial number), give them nicknames, optionally run the handshake test, and pick a constellation for the status display. You can skip it and do the same things from the Config screen directly.
2. **Config → Hardware → Arduino Directory** — the root folder holding your sketch category folders and a shared `libraries/` folder. The screen reports how many sketches and libraries it found.
3. **Settings → Data directory** — where session data is written. Optionally set a **Backup directory** too, on a different drive or share, to mirror session files and the cohort database.

Then create a cohort under **Cohorts**, and start a run from **Launch**.

### If something doesn't work

- **No boards detected.** Genuine Mega2560 R3 boards need no driver on either platform, but many clones use a CH340 USB-serial chip that does. Check the board appears as a serial device to the OS first; Ephymeris only lists what `arduino-cli board list` reports.
- **"Sidecar interpreter not found".** The venv isn't at `sidecar/.venv`, or was created by a Python older than 3.12.
- **Flashing fails on one box.** A failed flash leaves that port in `ERROR`, and `ERROR → FLASHING` is refused by design. Acknowledge the fault on the box's card (or in Debug Mode) before retrying.
- **The app starts but nothing connects.** The sidecar exited. There is no automatic respawn on purpose — restart the app. Its stderr is forwarded into the Tauri log.

## Commands

Run these from the repository root unless noted.

| Command | What it does |
|---|---|
| `npm run tauri:dev` | The real app: shell + sidecar + webview |
| `npm run dev` | Vite dev server alone, on the fixed port 1420 |
| `npm run typecheck` | `tsc --noEmit` — the only automated frontend check |
| `npm run build` | Typecheck, then a production Vite build |
| `npm run gen:protocol` | Regenerate the two wire-protocol mirrors from `protocol/schema.py` |
| `pytest` | Sidecar test suite (run from `sidecar/`, inside its venv) |
| `cargo test` | Rust shell tests (run from `src-tauri/`) |

There is no frontend test runner or linter configured yet; `typecheck` is the whole automated frontend story.

After changing anything on the wire, run the mirror-drift guard specifically:

```bash
pytest tests/test_protocol_contract.py
```

## How it fits together

Three processes and one WebSocket:

```
Tauri shell (Rust, src-tauri/)  ──spawns & supervises──►  Python sidecar (sidecar/)
        │                                                          │
        └── serves the webview (React/TS, src/) ──WebSocket────────┘
```

The **Python sidecar** owns everything stateful: serial I/O, `arduino-cli` invocation, the SQLite database, and session file writing. It is the source of truth for hardware and data state.

The **React frontend** talks to the sidecar over the WebSocket only. It never touches serial ports or `arduino-cli`, and it never sets port state optimistically — it renders what the sidecar reports.

The **Rust shell** is thin. It spawns the sidecar, owns settings persistence, and pushes settings over the wire. It holds no hardware or session logic.

A fuller version of this, including a file-by-file module map, is in [docs/reference.md](docs/reference.md).

## Documentation

Start at the **[documentation index](docs/README.md)**, which says which document answers which question. The two entry points most people want:

- **[docs/reference.md](docs/reference.md)** — the consolidated engineering reference: architecture, module map, the complete wire surface, and per-area implementation status.
- **[docs/TODO.md](docs/TODO.md)** — every known gap and open decision in one prioritized register.

The eight documents under `docs/` are living specifications and are more authoritative than inferring behavior from code. For the wire schema, `docs/websocket-protocol.md` carries the prose and `protocol/schema.py` is the machine-readable shape authority; the two code mirrors are generated from it.

## Contributing

Read [CLAUDE.md](CLAUDE.md) first — it captures the invariants that are load-bearing and shouldn't be relitigated without reading the relevant spec.

The three that bite hardest:

1. **The wire protocol mirrors are generated — never edit them by hand.** Update `protocol/schema.py` and `docs/websocket-protocol.md` together, run `npm run gen:protocol`, commit the regenerated mirrors, and run the contract test.
2. **Box number 1–6 is the key everywhere**, never a COM port address.
3. **The sidecar enforces state transitions**, not the UI. Disabled buttons are a courtesy.

# Getting Started with Ephymeris

A quick-start guide for setting up a **developer build** of Ephymeris — the lab desktop app that runs rodent behavior sessions on 6× Arduino Mega2560 R3 boards. This covers both supported development platforms: **Windows 11** and **macOS**.

> Looking for architecture, module maps, or the full command reference instead? See [`docs/README.md`](docs/README.md) — that's the engineering guide. This document only covers getting a dev build running.

---

## 1. How the app is put together

Before installing anything, it helps to know what you're about to run. Ephymeris is **three processes talking over one WebSocket**:

```
Tauri shell (Rust)  →  spawns  →  Python sidecar
        │                              │
        └── serves the webview (React) ── WebSocket ──┘
```

| Process | Language | Responsibility |
|---|---|---|
| **Tauri shell** | Rust (`src-tauri/`) | Spawns/supervises the sidecar, serves the webview, persists settings |
| **Frontend** | React + TypeScript (`src/`) | Renders state reported by the sidecar; never touches serial ports directly |
| **Sidecar** | Python (`sidecar/`) | Owns everything stateful — serial I/O, `arduino-cli`, SQLite, session files |

You'll be installing a toolchain for all three: **Node.js** for the frontend, **Rust** for the shell, and **Python** for the sidecar — plus **arduino-cli** so the app can talk to real (or simulated) hardware.

---

## 2. Prerequisites

| Tool | Version | Why |
|---|---|---|
| **Node.js** | 20+ | Frontend build (Vite) and the Tauri CLI |
| **Python** | 3.12+ | The sidecar — exactly this venv location is load-bearing, see [§4](#4-set-up-the-python-sidecar) |
| **Rust** | stable | The Tauri shell, via [rustup](https://rustup.rs) |
| **arduino-cli** | recent | Flashing and board discovery — must be on `PATH`, or pointed to explicitly in the app's **Config** screen |

### 🪟 Windows 11

1. Install [Node.js](https://nodejs.org).
2. Install [Python](https://www.python.org/downloads/windows/) — **tick "Add python.exe to PATH"** during setup.
3. Install [rustup](https://rustup.rs) and run it once to install the stable toolchain.
4. Install the **Microsoft C++ Build Tools**: grab the [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) installer and select the **"Desktop development with C++"** workload. (Tauri needs this to compile the Rust shell; WebView2 already ships with Windows 11, so no separate install needed there.)
5. Install `arduino-cli`:

   ```powershell
   winget install ArduinoSA.CLI
   ```

### 🍎 macOS

Everything can go through Homebrew:

```bash
xcode-select --install
brew install node python rustup arduino-cli
rustup-init
```

### Both platforms — install the AVR core

The Mega2560 boards compile against the AVR core, which isn't bundled — install it once:

```bash
arduino-cli core update-index
arduino-cli core install arduino:avr
```

---

## 3. Clone and install frontend dependencies

```bash
git clone https://github.com/Chase-NJ/Ephymeris.git
cd Ephymeris
npm install
```

`npm install` pulls in the React/Tauri/Vite toolchain. Nothing platform-specific happens here — this step is identical on Windows and macOS.

---

## 4. Set up the Python sidecar

> [!WARNING]
> The Tauri shell looks for a Python interpreter at **exactly `sidecar/.venv`**. If you'd rather keep your virtual environment somewhere else, point the `EPHYMERIS_SIDECAR_PYTHON` environment variable at your interpreter instead of moving the venv.

This is the one step where the command itself differs by OS (different venv activation/binary paths) — everything else about the sidecar is identical.

<table>
<tr><th>🪟 Windows 11 (PowerShell)</th><th>🍎 macOS</th></tr>
<tr>
<td>

```powershell
python -m venv sidecar\.venv
sidecar\.venv\Scripts\pip.exe install -e "sidecar[dev]"
```

</td>
<td>

```bash
python3 -m venv sidecar/.venv
sidecar/.venv/bin/pip install -e "sidecar[dev]"
```

</td>
</tr>
</table>

This installs the sidecar in editable mode along with its dev/test dependencies (`pytest`, `pytest-asyncio`, `grpcio-tools`).

---

## 5. Run the app

From the repo root:

```bash
npm run tauri:dev
```

This single command:

1. Starts the Vite dev server on the **fixed port 1420** (Tauri expects this exact port — don't change it).
2. Builds the Rust shell.
3. Spawns the Python sidecar as a subprocess.
4. Opens the app window, wired up end-to-end.

> ⏱️ **First run is slow.** Compiling the Rust dependencies from scratch takes a few minutes. Subsequent runs are much faster thanks to incremental compilation.

### Handy variants

| Command | Run from | What it does |
|---|---|---|
| `npm run tauri:dev` | repo root | **The full app** — shell + sidecar + webview |
| `npm run dev` | repo root | Vite alone (frontend only, no Tauri shell/sidecar) |
| `npm run typecheck` | repo root | `tsc --noEmit` — the only automated frontend check |
| `npm run build` | repo root | Typecheck, then a production Vite build |
| `pytest` | `sidecar/` (inside its venv) | Full sidecar test suite |
| `cargo test` | `src-tauri/` | Rust shell unit tests (handshake parser, etc.) |

---

## 6. First-launch setup

Nothing is pre-seeded — the app expects you to point it at your own folders and hardware on first run:

| Step | Screen | What you're doing |
|---|---|---|
| **1** | **Config** | A box-setup wizard walks you through binding each of the 6 boxes to a connected board, nicknaming them, and (optionally) running a handshake test. Skippable — same options live on the Config screen directly. |
| **2** | **Task → Arduino Directory** | Point at the root folder holding your sketch category folders plus a shared `libraries/` folder. |
| **3** | **Settings → Data directory** | Where session data gets written. You can also set an optional **Backup directory** on another drive or network share. |

Once that's done, create a **Cohort** and start a run from the **Dashboard**.

---

## 7. Troubleshooting

| Symptom | Likely cause |
|---|---|
| **No boards detected** | Genuine Mega2560 R3 boards need no driver on either OS, but many clones use a CH340 USB-serial chip that does. Ephymeris only shows what `arduino-cli board list` reports — confirm the board shows up as a serial device to the OS first. |
| **"Sidecar interpreter not found"** | The venv isn't at `sidecar/.venv`, or it was created with a Python older than 3.12. Re-check [§4](#4-set-up-the-python-sidecar). |
| **Flashing fails on one box** | A failed flash leaves that port in an `ERROR` state, and the state machine deliberately refuses `ERROR → FLASHING`. Acknowledge the fault on the box's card (or in Debug Mode) before retrying. |
| **The app opens but nothing connects** | The sidecar process exited. There's no automatic respawn by design — just restart the app. Its stderr output is forwarded into the Tauri log if you need to see why it died. |

---

## 8. Where to go next

- **[`docs/README.md`](docs/README.md)** — the full engineering guide: architecture, file-by-file module map, test map, and the open-issues register. Read this before making non-trivial changes.
- **[`docs/dashboard.md`](docs/dashboard.md)** — theme/tokens, the shell, every screen, the per-port hardware state machine, Mission Control, the 3D constellation.
- **[`docs/cohorts.md`](docs/cohorts.md)** — the Cohort/Animal/Group data model and UI.
- **[`docs/tasks.md`](docs/tasks.md)** — the Arduino Directory, `task.json` schema, and how to author a new behavior task.
- **[`docs/data.md`](docs/data.md)** — on-disk data layout, the SQLite schema, backup mirroring, and Analytics.
- **[`docs/settings.md`](docs/settings.md)** — every settings key, box bindings, and the hardware utility baseline.
- **[`docs/websocket-protocol.md`](docs/websocket-protocol.md)** — the canonical wire protocol schema.

If you're about to change anything on the wire protocol, remember: edit `protocol/schema.py` and its doc together, then run `npm run gen:protocol` — never hand-edit the generated mirrors in `sidecar/ephymeris_sidecar/protocol.py` or `src/lib/ws/protocol.ts`.

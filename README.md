# Ephymeris

A lab desktop app for running rodent behavior sessions on up to six Arduino Mega2560 R3 boards ("boxes"). It flashes sketches, streams live serial data during a session, parses a strobe protocol into per-animal data files, and manages cohort/animal/session bookkeeping.

Built for two Windows 11 lab machines; developed on macOS and Windows.

**Status: v1.0 in progress.** Cohorts, Debug Mode, Settings, and the complete session flow (config → mapping → flash → Mission Control → 3D constellation) are implemented and verified against real hardware. Analytics is a stub and Windows packaging is unstarted. See [docs/TODO.md](docs/TODO.md) for the full register.

---

## Quick start

You need **Node.js 20+**, **Python 3.12+**, **Rust** (stable), and **`arduino-cli`** with the `arduino:avr` core installed.

```bash
git clone https://github.com/Chase-NJ/Ephymeris.git
cd Ephymeris
npm install
```

Create the sidecar virtual environment — the Tauri shell expects an interpreter at exactly `sidecar/.venv`:

```bash
python3 -m venv sidecar/.venv
```

```bash
sidecar/.venv/bin/pip install -e "sidecar[dev]"
```

On Windows, that last path is `sidecar\.venv\Scripts\pip.exe`. Override the interpreter location with the `EPHYMERIS_SIDECAR_PYTHON` environment variable if you keep it elsewhere.

Then run the full app — Tauri shell, Python sidecar, and webview together:

```bash
npm run tauri:dev
```

On first launch, open **Settings** and set the **Arduino Directory** (the root folder holding your sketches) and the **Data Directory** (where session output is written). No defaults are shipped or guessed. Then add your boxes: each is a box number 1–6 bound to a specific board by its USB `hardware_id`, which is what keeps a box pointing at the same physical board after Windows renumbers COM ports.

## Commands

Run these from the repository root unless noted.

| Command | What it does |
|---|---|
| `npm run tauri:dev` | The real app: shell + sidecar + webview |
| `npm run dev` | Vite dev server alone, on the fixed port 1420 |
| `npm run typecheck` | `tsc --noEmit` — the only automated frontend check |
| `npm run build` | Typecheck, then a production Vite build |
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

The seven documents under `docs/` are living specifications, kept current with the implementation, and are more authoritative than inferring behavior from code. `docs/websocket-protocol.md` in particular is the canonical source for the wire schema; the two code mirrors are hand-maintained against it.

## Contributing

Read [CLAUDE.md](CLAUDE.md) first — it captures the invariants that are load-bearing and shouldn't be relitigated without reading the relevant spec.

The three that bite hardest:

1. **The wire protocol has no codegen.** Update `docs/websocket-protocol.md`, then `sidecar/ephymeris_sidecar/protocol.py`, then `src/lib/ws/protocol.ts`, in that order, and run the contract test.
2. **Box number 1–6 is the key everywhere**, never a COM port address.
3. **The sidecar enforces state transitions**, not the UI. Disabled buttons are a courtesy.

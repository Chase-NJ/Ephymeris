# Ephymeris Documentation

Nine documents. This page tells you which one to open.

The seven specification documents are **living specs** — kept current with the implementation and more authoritative than inferring behavior from code. Each carries a **Resolved Decisions** table (what is settled and why) and an **Open Items / TBD** table (what is still in flux); those two tables are the fastest way to check the status of anything before changing it.

The two consolidated documents (this index aside) are derived views, maintained alongside the specs:

| Document | What it is |
|---|---|
| **[reference.md](reference.md)** | The engineering reference — architecture, file-by-file module map, the complete wire surface, implementation status, and the test map. Start here to orient in the codebase. |
| **[TODO.md](TODO.md)** | Every open item from every spec, plus gaps found in code, in one prioritized register. Start here to pick up work. |

---

## Find the right spec

| If you need to know… | Read |
|---|---|
| What the app is, the tech stack, the dashboard layout, the theme tokens, or how Settings works | [ephymeris_v1.0.md](ephymeris_v1.0.md) |
| How serial ports, flashing, reset, or passthrough behave — and the per-port state machine | [hardware-interaction.md](hardware-interaction.md) |
| How sketches and libraries are discovered, categorized, and validated | [arduino-directory.md](arduino-directory.md) |
| The exact shape of any command, event, payload, or error code on the wire | [websocket-protocol.md](websocket-protocol.md) |
| The Cohort/Animal/Group data model, cohort UI, or Auto-Balance grouping | [cohorts.md](cohorts.md) |
| What happens between the "Start a Session" button and a running box | [starting-a-session.md](starting-a-session.md) |
| What gets written to disk, in what format, and what survives a crash | [data-saving.md](data-saving.md) |

## Reading order for a new engineer

The specs have real dependencies. This order avoids forward references:

1. **[ephymeris_v1.0.md](ephymeris_v1.0.md)** — the app, the stack, the theme. Everything else assumes it.
2. **[reference.md](reference.md)** — the architecture and module map, so the names in the specs map to files.
3. **[hardware-interaction.md](hardware-interaction.md)** — the per-port state machine is the core invariant of the whole system.
4. **[websocket-protocol.md](websocket-protocol.md)** — how the frontend and sidecar actually talk.
5. **[arduino-directory.md](arduino-directory.md)** — short, and flashing depends on it.
6. **[cohorts.md](cohorts.md) → [starting-a-session.md](starting-a-session.md) → [data-saving.md](data-saving.md)** — three interdependent documents in dependency order. The last two were written together and should be read together.

## Which document is canonical when two disagree

Overlap between specs is deliberate — each document restates enough context to stand alone. Where they conflict, precedence is:

- **The wire schema:** `websocket-protocol.md` wins, always. `cohorts.md` §10, `starting-a-session.md` §9, and `data-saving.md` §9 all originally proposed commands that have since been merged into it; those sections are retained for design rationale only and are explicitly not canonical.
- **Port state transitions:** `hardware-interaction.md` §3 wins.
- **On-disk layout and file schema:** `data-saving.md` §1–§2, §5 wins.
- **Theme tokens, type roles, and motion:** `ephymeris_v1.0.md` §2 wins.
- **Implementation status:** [reference.md](reference.md) and [TODO.md](TODO.md) are the current view. A spec's own status header describes that document's subject area and can lag a working-tree change by a commit or two.

## Conventions used throughout

- **Box number, 1–6** is the stable key for anything per-port, in the UI, on the wire, and in the data model. A COM port address is never a key — Windows renumbers them across reboots.
- **Section references** are written as `doc.md §N` and are stable; sections are not renumbered when content is added.
- **Strikethrough items** in an Open Items table are resolved, with the resolution noted inline. They are kept rather than deleted so the decision history stays readable.
- **`.tsv` means write-ahead log**, not an export format. See `data-saving.md` §7 before treating it as redundant with `.json`/`.mat`.

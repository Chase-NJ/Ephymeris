# Task Specs

![status](https://img.shields.io/badge/status-built-7CC98F?style=flat-square) ![owner](https://img.shields.io/badge/owns-specs_·_compiler_·_bench-8B7EC8?style=flat-square) ![animals](https://img.shields.io/badge/animal_use-not_yet-C96C6C?style=flat-square)

> **What this is** · The task-spec editor under the Task tab: a declarative task compiled into a state table that a fixed on-board interpreter walks. **Tasks stop being firmware and become data** — a new task ships without touching C++.
>
> **Owns** · The vendored Task-Graph compiler · where specs live and how edits are stored · the editor (form, palette, graph, diff) · the bench upload path · the boundaries that keep all of it away from live sessions.
>
> **Read with** · [tasks.md](tasks.md) (the *other* kind of task — sketches and `task.json`) · [websocket-protocol.md](websocket-protocol.md) §3.6–3.7 (the wire) · [README.md §6.4](README.md#64-dependency-policy) (the dependency fence) · Task-Graph's own `docs/` for the compiler's internals.

**Contents** — [1. What a spec is](#1-what-a-spec-is) · [2. The vendored compiler](#2-the-vendored-compiler) · [3. Where specs live](#3-where-specs-live) · [4. The editor](#4-the-editor) · [5. The palette and the graph](#5-the-palette-and-the-graph) · [6. The diff as a review](#6-the-diff-as-a-review) · [7. The bench](#7-the-bench) · [8. What is proven, and what is not](#8-what-is-proven-and-what-is-not)

---

## 1. What a spec is

A YAML document with four layers, compiled by the [Task-Graph](../../Task-Graph) compiler into a byte table a fixed interpreter executes:

| Layer | Key | Changes |
|---|---|---|
| **1 · Topology** | `topology` | **The graph.** Six knobs handed to a versioned epoch template — the only layer that changes the shape |
| **2 · Contingency** | `contingency` | Per-trial content: stimuli, ports, trial types, the outcome map. Reversals live entirely here |
| **3 · Timing** | `timing` | One duration per id. Order is load-bearing — the index is what the firmware holds |
| **4 · Policy** | `policy` | Selection, correction, penalty escalation, the shaping schedule, trial count, seed |

There is deliberately **no `nodes:` key**. Task authors never write a node: the set of representable graphs is exactly the image of the templates over the topology knobs, which is what makes compilation, validation and this editor tractable (Task-Graph D1 — a spec declaring `nodes` is rejected with a message saying so, TG103).

> [!CAUTION]
> **A spec is a SIBLING artifact to a sketch's `task.json`, never an extension of it.** The two describe different things and hash differently: `profile_hash` is what Analytics groups a sketch's historical runs by, and adding anything to `task.json` to make a graph authorable would split every sketch's past runs from its future ones permanently ([tasks.md §4.1](tasks.md#41-why-derived-not-declared), Task-Graph D7). Both kinds of task live on the one Task screen — the spec workbench above, the sketch section below — because both answer "what does the animal do".

Provenance mirrors the shapes Ephymeris already records: `spec_hash` is SHA-256 over the **parsed document** (16 hex chars, like `profile_hash`/`params_hash`), so reformatting never moves it; the compiled table additionally carries the template name, version and **source hash**, so editing a pinned template — which the file-per-version rule forbids — shows up as a diff rather than a silent change.

## 2. The vendored compiler

The compiler is copied into `sidecar/vendor/` **byte-identical** to its source repo, mirroring Task-Graph's repo root (`taskgraph/` and `schema/` stay siblings — four modules resolve paths as `__file__/../../…`). It is imported through one `sys.path` entry (`specs/_vendor.py`), never by a dotted package path: the linter's rule registry and the cached registries are module-level state, and a second module object means two vocabularies disagreeing silently.

Two drift guards, and neither can do the other's job:

| Where | Catches |
|---|---|
| `sidecar/tests/test_vendor_drift.py` | someone **edited the copy** — compares against the `VENDORED` manifest, no second repo needed |
| Task-Graph `tests/test_ephymeris_mirror.py` | the copy is **stale** — runs the sync script's own `--check` against this checkout |

To update: run Task-Graph's `scripts/sync_to_ephymeris.py --dest <ephymeris>/sidecar/vendor` and commit the result here.

**The dependency fence** ([README.md §6.4](README.md#64-dependency-policy)): `jsonschema` + `pyyaml` are the sidecar's second exception, and a weaker one than `grpcio`'s — nothing stands in for a compiler. On import failure every `specs.*` command raises `SPEC_COMPILER_UNAVAILABLE`, the Task screen shows one banner, and the legacy `task.json` path, flashing, and the whole session flow are untouched. The startup log line comes from `compiler.self_check()`, which **compiles a real bundled spec** rather than merely importing — a packaged build can bundle the tree, import it, and still fail every compile on missing metaschema data, and an import check reported ready for exactly that build once.

In a packaged build the vendor tree ships as PyInstaller `--add-data` — plain `.py` on disk, never in the archive, because `templates.load()` imports a module whose name it computes and `source_hash()` reads the file's own bytes.

## 3. Where specs live

```
sidecar/vendor/specs/               the bundled specs — read-only, one copy shared
                                    with the compiler's own checked-in listings
<data_dir>/specs/
  user/<spec_id>.yaml               user-created and user-edited
  shipped-baseline/<spec_id>.yaml   the shipped bytes as of the user's first edit
  index.json                        {spec_id: {baselineSha, editedAt}}
```

Sidecar-side writes, under the same roof as `ephymeris.db` — no Tauri fs capability involved.

**No seeding.** Nothing is copied on first use: the compiler only reads, so a bundled spec is served as-is and one that ships changed simply *is* changed for anyone who hasn't edited it. A user file with a bundled id **shadows** it; the shipped bytes are baselined *before* the first edit lands, so no ordering exists in which an edit lacks its undo. The shipped file itself is never modified — which is why **Reset to shipped restores it byte-for-byte, comments included** (the shipped specs' comments cite firmware line numbers; they are documentation, and the editor's YAML rewrite would destroy them, which the workbench says at the moment of first divergence).

**No merging.** When an app update changes a bundled spec underneath a local edit, the entry gets `upstreamChanged` and the user picks: **Keep mine** (re-baseline) or **Take the new shipped version** (reset). A wrong automatic merge of two task definitions is an experiment nobody designed; a badge is annoying, which is the correct price.

Three origins ride every list row: `shipped` · `shipped_edited` · `user`. The save target is the **document's own `spec_id`**, so renaming the id field and saving creates a copy — the whole create/duplicate flow is one text field. The id is also a filename; it dies at a regex (`^[a-z][a-z0-9_]{0,39}$`) before any path join.

## 4. The editor

The form is generated, not written, from three sources with strict jobs:

| Source | Says |
|---|---|
| `schema/task_spec.v1.json` | what is **legal** — types, ranges, enums |
| `schema/task_spec.presentation.v1.json` | what a field is **called** and which **widget** edits it (labels, units, groups, help). Lives in Task-Graph beside the schema it describes, tested there for two-way coverage |
| the document | which **rows exist** |
| `capabilities(topology)` | which rows this topology **needs** |

> [!IMPORTANT]
> **`capabilities()` decides which rows EXIST; the compiler decides which are VALID.** The form re-implements no lint rule. A template's `capabilities(topology)` returns the outcome classes and timing ids this configuration produces — a *function*, not a table, because the answer depends on several knobs at once — and the form re-gates its timing rows and outcome cards the instant a knob moves, before any compile returns. A timing row the topology no longer needs is **greyed with a Remove button, never hidden** — hiding silently orphans a value the operator typed.

**The live compile** runs on every edit (120 ms debounce, stale replies discarded): the frontend serializes the document and `specs.compile` checks **exactly the bytes a save would write** — the LOAD pass (schema validation, TG1xx, the YAML `on:` trap) checks things that only exist before parsing, so the wire carries text, never a dict. Sidecar-side it runs in a worker thread behind a semaphore of 1; a synchronous compile on the loop would stall the 20 Hz output flush and, mid-session, the fsync-per-strobe write path. ~21 ms warm.

**A spec that doesn't compile is a successful reply carrying diagnostics, never an error** — the Analytics corrupt-file discipline. Each diagnostic arrives with its `placement` precomputed by the compiler's own `placement()` (field / row / section / node / document) and an `anchor` that is an overlay key — so putting an error next to the input that caused it is a dictionary lookup, and the frontend never parses a location. The panel below the form lists **every** diagnostic regardless, with `help` and the `D-number` decision pointer, because a diagnostic that reaches nobody is the failure mode the whole design exists to avoid.

Pickers draw from the **vendored registry files** — the same bytes the compiler validates against — served once per mount by `specs.schema`. The frontend never holds its own copy of a registry: a strobe picker offering a code the compiler rejects would be manufacturing an error.

## 5. The palette and the graph

The topology editor is an **epoch-block palette, not a free-form node canvas** — four fixed band cards (engagement · sampling · response · outcome) holding the knobs that shape each band, with live readouts. Stated honestly, as the roadmap demanded: `topology` is six scalars, so "assembling epochs" *is* setting knobs and immediately seeing the generated graph. A node canvas would make invalid machines representable, which is the trap the whole epoch model exists to forbid — the constraint is kept at the UI layer, not thrown away by it. The Outcome card has no knobs at all: its chips *are* `capabilities().outcomeClasses`, because which outcomes exist is a consequence of the other three cards. The palette owns the topology knobs outright; the form has no topology section, because two editing surfaces for one field eventually disagree.

**`SpecGraph` draws the compiled machine graph** — six node primitives (shape-coded), trigger-keyed edges with guards, returns as the faintest unlabelled arcs — and is deliberately not a second mode of `TaskGraph.tsx`, which draws the *behavioural* graph a `task.json` derives and serves the live-session path. Layout (`lib/specs/layout.ts`) is a pure, deterministic function: band = column group; **x within a band = index order, which is the order the listing prints** — the graph and the review artifact must not disagree about ordering; y by branch, spine straight, penalty chains below. Hovering a node shows its listing block verbatim.

## 6. The diff as a review

`specs.diff` diffs the **listing** — the compiler's checked-in review artifact — never the YAML. Headline first (`26 → 29 states · 462 → 508 bytes`); hunks grouped by the listing's own ruled sections so a change reads as *"in STATES"*; `spec_hash`/`template_hash` move on every edit and are confined to a provenance strip, never hunks. Baselines: *vs shipped*, *vs saved*, or *vs another spec* — the last is how a `derived_from` claim gets read: an eased variant against its base shows **no structural hunks** (same nodes, same edges), with values moving in TIMING VECTOR and its derived sections (STAGE SCHEDULE, DWELL BUDGET) alongside.

`specs.export` returns bytes in the reply — spec, listing, lint, canonical JSON, packed `.bin`, bench card — and the frontend writes one artifact at a time through the user's own save dialog. No wire command writes an arbitrary file.

## 7. The bench

Probing and upload own the port through a dedicated **`UPLOADING`** state — `FLASHING`'s twin (force-release passthrough, auto-resume), but the uploader opens its **own** serial handle: the passthrough ring buffer is drained by the 20 Hz flusher, not consumed, and a table transfer is request/response with deadlines. `ports/upload.py::PortLink` implements the vendored transport's `Link`; progress is extracted *inside* the link (chunks counted at the board's ACK, not at hopeful writes) so `taskgraph.transport.client` is used unmodified; the console mirror carries headline lines and never the hex chunks.

The pieces that exist because hardware taught them:

- **Baud** is found by `detect` (115200 then 9600 — the fleet's two rates mid-rollout), cached per `hardware_id`, invalidated by any flash to that box. Never `settings.defaultBaud`, which is the console default. `read_banner`'s timeout is a **total budget** — a chatty board at the wrong baud produces garbage "lines" fast enough that a per-line clock never expires (found on the first real probe; BOX_Utility streams STATUS continuously).
- **`PortLink` settles, flushes, then pulses DTR again** — upstream `SerialLink`'s order, where the order is the point: the flush discards the open's own boot banner, and the deliberate second reset makes the banner read next *this run's*. Flushing without re-resetting made every legacy sketch look mute at its own baud.
- **`UPLOAD_REFUSED` vs `UPLOAD_FAILED` follows where the fault lies.** A healthy board saying no before any byte moved (no CAP → *"flash the interpreter sketch first"*, wire mismatch, capacity exceeded) lands the port cleanly. A broken transfer parks it in `ERROR`, because a partial table leaves the board's state genuinely unknown.
- **`utility.benchHold`** suspends baseline restores while the bench panel is mounted — otherwise an upload ends with the port falling `IDLE` and the baseline quietly reflashing `BOX_Utility` over the interpreter, the table dying with it. A separate flag from the session hold, so neither release can leak into the other.

The UI is **two explicit clicks, never one combined button** — *Flash TaskRunner_Dev* (destructive, labelled as such) then *Upload table* — under a permanent strip:

> **Bench only.** The table interpreter is proved off-target and has never driven a pin — a box carrying TaskRunner accepts a table and reports whether it fits. It runs no trial and delivers no reward. Do not put an animal in a box running this.

> [!CAUTION]
> **The no-session invariant, structurally enforced:** no wire command ties a spec to a session. `sessions.confirmMapping` does not learn a `specId`, `port.startSession` is untouched, and `UPLOADING ↔ IN_SESSION` is illegal in the transition table in both directions. That door opens at Task-Graph Phase 5's exit criteria — actuator timing verified on hardware, parallel run clean — not because the parts happened to be ready.

## 8. What is proven, and what is not

**Proven, on a real Mega2560 through the app's own wire commands** (2026-08-03): the legacy-sketch flash against the merged bundled libraries; the no-CAP probe and refusal with the port landing cleanly; TaskRunner_Dev flashed and announcing `PROTO=2 WIRE=1` with the full capacity set at 115200; `grgl_2odor` uploaded — 558 bytes / 9 chunks / 207 ms — with CRC **and** body digest confirmed (the CRC says the bytes arrived; the digest says they decoded into the right fields); the baud cache invalidated by a flash and skipping detection on the second upload. Off-target, the same sidecar-compiled tables go `TABLE OK` into `tg_board`, the real receiver compiled for the host — and every upload-protocol failure mode stays covered by Task-Graph's own `test_uploader.py`, deliberately not retested here.

**Not proven, and marked accordingly:** anything involving an animal. The interpreter has never driven a solenoid, a light, or a vacuum line under this app — that is Task-Graph Phase 5 (bench jig, scope, parallel run), and until its exit criteria hold, the bench strip and the no-session invariant are the boundary. Also still open: the spec editor on Windows (packaging is staged but the frozen vendor tree is verified on macOS only), and a crashed client leaves `benchHold` set until app restart — deliberate, erring toward not-reflashing, but worth knowing when a box mysteriously stops returning to baseline.

---

**Where to next** — [tasks.md](tasks.md) (sketches and `task.json` — the other kind of task) · [websocket-protocol.md](websocket-protocol.md) §3.6–3.7 (every command above, with shapes) · [dashboard.md](dashboard.md) §5 (the port state machine `UPLOADING` joined) · [README.md](README.md)

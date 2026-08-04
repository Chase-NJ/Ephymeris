# Task Specs

![status](https://img.shields.io/badge/status-built-7CC98F?style=flat-square) ![owner](https://img.shields.io/badge/owns-specs_·_compiler_·_bench-8B7EC8?style=flat-square) ![animals](https://img.shields.io/badge/animal_use-not_yet-C96C6C?style=flat-square)

> **What this is** · The task-spec editor under the Task tab: a declarative task compiled into a state table that a fixed on-board interpreter walks. **Tasks stop being firmware and become data** — a new task ships without touching C++.
>
> **Owns** · The vendored Task-Graph compiler · where specs live and how edits are stored · the editor (form, palette, graph, diff) · the bench upload path · the boundaries that keep all of it away from live sessions.
>
> **Read with** · [tasks.md](tasks.md) (the *other* kind of task — sketches and `task.json`) · [websocket-protocol.md](websocket-protocol.md) §3.6–3.7 (the wire) · [README.md §6.4](README.md#64-dependency-policy) (the dependency fence) · Task-Graph's own `docs/` for the compiler's internals.

**Contents** — [1. What a spec is](#1-what-a-spec-is) · [2. The vendored compiler](#2-the-vendored-compiler) · [3. Where specs live](#3-where-specs-live) · [4. The editor](#4-the-editor) · [5. The graph is the editor](#5-the-graph-is-the-editor) · [6. The diff as a review](#6-the-diff-as-a-review) · [7. The bench](#7-the-bench) · [8. What is proven, and what is not](#8-what-is-proven-and-what-is-not)

---

## 1. What a spec is

A YAML document with four layers, compiled by the [Task-Graph](../../Task-Graph) compiler into a byte table a fixed interpreter executes:

| Layer | Key | Changes |
|---|---|---|
| **1 · Topology** | `topology` | **The graph.** Six knobs handed to a versioned epoch template — very nearly the only layer that changes the shape |
| **2 · Contingency** | `contingency` | Per-trial content: stimuli, ports, trial types, the outcome map. Reversals live entirely here |
| **3 · Timing** | `timing` | One duration per id. Order is load-bearing — the index is what the firmware holds |
| **4 · Policy** | `policy` | Selection, correction, penalty escalation, the shaping schedule, trial count, seed |

There is deliberately **no `nodes:` key**. Task authors never write a node: the set of representable graphs is exactly the image of the templates over the topology knobs, which is what makes compilation, validation and this editor tractable (Task-Graph D1 — a spec declaring `nodes` is rejected with a message saying so, TG103).

**The one shape-bearing exception to layer 1, named because hiding it would be worse:** `contingency.outcome_map.correct.reward` is a layer-2 field, and setting it to `null` omits the reward delivery `PULSE` and the consumption `WAIT_EXIT` from the outcome epoch entirely (`four_epoch/v2.py`'s `if correct.reward:`). An unrewarded 2AFC really is a different machine from a rewarded one. Everything else in layers 2–4 changes content, ordering or duration and leaves the node set alone.

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

Three origins ride every list row: `shipped` · `shipped_edited` · `user`. The save target is the **document's own `spec_id`**, so renaming the id field and saving creates a copy. The id is also a filename; it dies at a regex (`^[a-z][a-z0-9_]{0,39}$`) before any path join.

**Creating a task is that same rename-and-save, given a front door.** *New task* opens a paradigm gallery over the bundled specs (`components/specs/NewSpecGallery.tsx`): pick one, take a new id and label, and it is fetched, re-identified and saved under the new id. The source is untouched because nothing wrote to it. **No new wire command exists for this, and none should** — a blank-skeleton generator would be a second definition of what a minimal legal spec is, competing with the schema; a bundled paradigm is a task the compiler *and* the linter already agree on, and it arrives carrying its author's notes. *Duplicate* on a library card is the same path with the id chosen for you. All three surfaces go through one function, `lib/specs/create.ts::createSpecFrom` — they were on their way to being three near-copies, which is how the rewrite-the-id-in-the-document rule gets forgotten in one of them.

**A paradigm is a SHAPE, not a spec id** (`lib/specs/paradigms.ts`). Five bundled specs are three graphs: `grgl_2odor` *is* two-alternative forced choice, and `shaping_gr`/`shaping_gr_ez` are the same 26-state machine with a timing ramp — `specs.diff` between them shows no structural hunks, which §6 already names as the test of a `derived_from` claim. The gallery groups them as variants under one paradigm and says "same machine, different timings" out loud, because listing them as three paradigms would teach that a timing ramp is a different kind of task. Matching is by **fingerprint computed from the document**, never by spec id, so a rig's own `my_task_3` lands under the right paradigm without being registered anywhere and one that matches nothing reads honestly as Custom.

**The wizard** (`routes/TaskNew.tsx`, `/task/new`) walks the questions with the compiled machine beside them. It is a route rather than a modal for the reasons §7 gives the bench — it needs the canvas at a usable size, `Modal` is capped, the unsaved guard is per-route, and arriving should be deliberate.

> [!IMPORTANT]
> **The wizard always starts from a bundled paradigm, and that is the argument above, not a convenience.** Every step is an *edit* to a document the compiler and the linter already agree on, applied through the same structural blocks the Designer exposes (§4), so "it compiles at every step" is on screen rather than claimed. The moment it grows a *start from nothing* option it becomes the blank-skeleton generator this section rejects.

Paradigms this rig can reach that no bundled file holds are **recipes**: a base plus a fixed sequence of those same blocks (unrewarded 2AFC, three-stimulus sequence, shaping with no stimulus). A recipe is not a skeleton generator either — it is a sequence of edits to a spec that already compiled. New bundled *files* cannot come from here at all: `sidecar/vendor/` is byte-identical to Task-Graph and drift-tested, so a genuinely new bundled paradigm arrives through the sync script (§2) or not at all.

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

**Structural blocks** (`lib/specs/operations.ts`) are how the shape changes. A knob never moves alone: adding a sampling stage renames `t_sample_hold` to `t_sample_hold_0`, appends the new hold and the gap before it, and extends *every* trial type's `stages` — six edits that are only jointly valid, which is exactly why they are one operation with one preflight rather than six fields to remember. The ops are pure and composed from `setAt`/`deleteAt`; they are **handed** `capabilities()` for the topology they PROPOSE (fetched by `useOperation` before anything is applied) rather than computing it, because an op that computed its own class set would be a second implementation of the template's `capabilities()` — the trap the function-not-a-table argument exists to prevent.

Four rules that make a block safe to press:

- **A new timing row is seeded from a sibling in the same document, or asked for inline — never from a defaults table.** A table would be a second definition of what a reasonable task looks like, competing with the bundled specs. `t_sample_hold_1` copies `t_sample_hold_0` (the template's own comment says stage-indexed ids exist so each stage is independently rampable); `t_retention` and `t_resp_hold` have no peer and so are asked for, and Apply waits. A seeded row's preflight line names the row it copied.
- **An op that changes a value a `note:` describes deletes the note, and says so.** Rewriting one means inventing a firmware citation; leaving it makes a pinned line number a lie. `t_resp_win → t_withhold_win` is a *different* firmware field (`fluidWellPoll` → `nogoWellPoll`) so the note and `wire_key` go; `t_sample_hold → t_sample_hold_0` is the same field at a new index, so they stay.
- **Stale outcome classes are deleted; stale timing rows are kept and greyed.** TG302 errors in both directions, so a class the topology cannot produce is a hard error and has to go (the baseline recovers it). An unused timing row is merely unused — hiding or deleting one silently orphans a value the operator typed.
- **An op that cannot be made valid says why, from the registry.** *Add a response option* ships permanently blocked because `channels.v1.json` declares exactly two `kind: response` channels and both are bound; the message is computed from the registry rather than hardcoded, so a Task-Graph registry change plus a re-sync turns the op on with no frontend edit. It exists rather than being absent so the UI can explain.

> [!CAUTION]
> **A block must fill every field its new shape makes reachable, not just the ones its knob names.** Switching go/no-go → n-alternative is the case that already bit: a withhold task's ports declare `enter_code` and nothing else, because it never reports a wrong port, a broken response hold, or leaving a reward port. All three become reachable at once and TG506 wants a code for each on *every* port — the operation shipped without them and produced six errors. `sidecar/tests/test_spec_operations.py` pins both directions, including the negative case.

**The live compile** runs on every edit (120 ms debounce, stale replies discarded): the frontend serializes the document and `specs.compile` checks **exactly the bytes a save would write** — the LOAD pass (schema validation, TG1xx, the YAML `on:` trap) checks things that only exist before parsing, so the wire carries text, never a dict. Sidecar-side it runs in a worker thread behind a semaphore of 1; a synchronous compile on the loop would stall the 20 Hz output flush and, mid-session, the fsync-per-strobe write path. ~21 ms warm.

**A spec that doesn't compile is a successful reply carrying diagnostics, never an error** — the Analytics corrupt-file discipline. Each diagnostic arrives with its `placement` precomputed by the compiler's own `placement()` (field / row / section / node / document) and an `anchor` that is an overlay key — so putting an error next to the input that caused it is a dictionary lookup, and the frontend never parses a location. The panel below the form lists **every** diagnostic regardless, with `help` and the `D-number` decision pointer, because a diagnostic that reaches nobody is the failure mode the whole design exists to avoid.

Pickers draw from the **vendored registry files** — the same bytes the compiler validates against — served once per mount by `specs.schema`. The frontend never holds its own copy of a registry: a strobe picker offering a code the compiler rejects would be manufacturing an error.

## 5. The graph is the editor

The Designer (`routes/TaskDesigner.tsx`) is built around the compiled machine, with identity and the save/review/export actions above it, the fields that produced the current selection to its right, and the compiler's diagnostics in a drawer below. A segmented **Graph | Parameters** switch puts the generated form (§4) behind the canvas for everything with no graph anchor — policy, trial types, stimuli, meta.

**`SpecCanvas` draws the compiled machine graph** — six node primitives (shape-coded), trigger-keyed edges with guards, returns as the faintest unlabelled arcs, and the four epochs as full-width lanes carrying their state count and knob readout. It is deliberately not a second mode of `TaskGraph.tsx`, which draws the *behavioural* graph a `task.json` derives and serves the live-session path.

**The flow is vertical, top to bottom** — a trial reads down the page the way it reads down the listing. Layout (`lib/specs/layout.ts`) is a pure, deterministic function of the `SpecGraph` payload: no randomness, no measured text, no simulation, because two compiles of the same spec must produce an identical picture. Band = row group; branches lateral, spine straight, penalty chains to the right. Ordering is restated as: **within every lane, flow position is strictly increasing in node index; lanes are ordered by the index of their first member; bands by band number** — so reading lane 0 top to bottom reproduces the listing's main line, and the graph and the review artifact still cannot disagree.

Two rules earn their keep against the shapes real tasks make:

- **A branch starts at the position of the spine node it leaves from, not at its own index.** Otherwise every branch node pushes the spine one row further down and leaves the spine's own rows empty — band 1 of `grgl_2odor` was ten rows deep for a three-node spine.
- **Lanes are per BRANCH, not per connected component.** A band's abort chains all end at the same repeat terminal, so plain connectivity fuses them into one blob and stacks it; descent separates them, and a node several branches converge on rides the last of the lanes that feed it rather than claiming one of its own.

Text is budgeted rather than trusted: SVG text neither wraps nor clips, so band headers live in a fixed left gutter where they *cannot* reach a lane, node labels are left-anchored beside their node inside a per-lane budget, and everything passes through `fitMono` — character arithmetic, so the same string always truncates the same way, with the full text in a `<title>`. Edge labels are placed in `layout.ts` too, with parallel edges bowed apart and same-bucket labels pushed down in edge-index order. At rest the graph fits by width and starts at the top; the wheel pans rather than zooming.

**The view goes home for a new PICTURE, not a new compile.** The reset keys on `graphSignature` — node symbols, bands, types and the edge list — and deliberately excludes durations, labels and strobe names. Keying on the payload's identity meant every 120 ms compile snapped the operator back to the top of a graph they were reading halfway down. Hovering a node shows its listing block verbatim.

> [!IMPORTANT]
> **Nothing on the canvas can be dragged, added or rewired, and selection is the whole interaction.** `topology` is six scalars and a versioned template emits the nodes, so a node canvas would make invalid machines representable — the trap the epoch model exists to forbid, and the ordering error the roadmap names as the most costly one available. The constraint is kept at the UI layer rather than thrown away by it. Clicking a node, an edge or a lane instead asks *what produced this*, and the Inspector renders the answer. The lane's block glyph is a **selector and nothing more** — it selects the lane and asks the Inspector to reveal that band's structural blocks (§4), which live there because the Inspector already owns the knobs they compound. It deliberately opens no menu on the canvas: a menu on the canvas is the first step toward editing on the canvas.

**The mapping from graph back to fields is `lib/specs/selection.ts`, and every rule in it joins on data rather than on names.** The compiler's own `Provenance(template, line, band, knobs)` does not survive lowering into the `StateTable`, so the mapping is reconstructed frontend-side — but only from values both sides genuinely share: a node's `durationId` finds the `timing` row declaring it *and* any outcome whose `delay` is that id (which is how a penalty node finds the outcome it serves); an edge's `score:<class>` effect names an outcome class outright, and the compiler wrote it; `watch` finds the port bindings on those channels; `strobeName` finds every field currently holding it, and is allowed to return several because `WATER_POKE_L` genuinely is both a port's `enter_code` and, through `@ports[$ch].enter_code`, an outcome's strobe. `symbol` is deliberately never consulted — it is stable within a template version and meaningless across one. The inverse (`nodesForPath`) lights every state a hovered field governs, which is the one thing the graph can say that a form cannot.

**The Inspector owns the topology knobs outright**, reached by selecting the lane they shape; the form still has no topology section, because two editing surfaces for one field eventually disagree. The Outcome lane has no knobs at all: its chips *are* `capabilities().outcomeClasses`, because which outcomes exist is a consequence of the other three lanes.

> [!CAUTION]
> **A spec with any ERROR produces no table and therefore no graph.** On a page where the graph is the whole frame of reference, rendering nothing would blank the canvas at exactly the moment the operator needs it to understand the error — so the Designer keeps the last graph that compiled, dims it, and lets the diagnostics say why it is stale. Do not "fix" this by clearing the canvas on a failed compile.

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

The bench is **its own route** (`/task/bench`, reached from the landing page or from the Designer's *Bench* action, which passes `?spec=<id>`) rather than a panel inside the editor. It is the one surface in the app that talks to real hardware about a spec, and it must not read as one more section of a form — arriving is a deliberate act, and the page says what it is before it says what it can do. The UI is then **two explicit clicks, never one combined button** — *Flash TaskRunner_Dev* (destructive, labelled as such) then *Upload table* — under a permanent strip:

> **Bench only.** The table interpreter is proved off-target and has never driven a pin — a box carrying TaskRunner accepts a table and reports whether it fits. It runs no trial and delivers no reward. Do not put an animal in a box running this.

> [!CAUTION]
> **The no-session invariant, structurally enforced:** no wire command ties a spec to a session. `sessions.confirmMapping` does not learn a `specId`, `port.startSession` is untouched, and `UPLOADING ↔ IN_SESSION` is illegal in the transition table in both directions. That door opens at Task-Graph Phase 5's exit criteria — actuator timing verified on hardware, parallel run clean — not because the parts happened to be ready.

## 8. What is proven, and what is not

**Proven, on a real Mega2560 through the app's own wire commands** (2026-08-03): the legacy-sketch flash against the merged bundled libraries; the no-CAP probe and refusal with the port landing cleanly; TaskRunner_Dev flashed and announcing `PROTO=2 WIRE=1` with the full capacity set at 115200; `grgl_2odor` uploaded — 558 bytes / 9 chunks / 207 ms — with CRC **and** body digest confirmed (the CRC says the bytes arrived; the digest says they decoded into the right fields); the baud cache invalidated by a flash and skipping detection on the second upload. Off-target, the same sidecar-compiled tables go `TABLE OK` into `tg_board`, the real receiver compiled for the host — and every upload-protocol failure mode stays covered by Task-Graph's own `test_uploader.py`, deliberately not retested here.

**The structural blocks** (§4) are covered two ways, and the gap between them is worth naming. `sidecar/tests/test_spec_operations.py` applies each op's path edits to each bundled spec and asserts the real compiler accepts the result — but it is a **second implementation in Python**, so it proves the design is sound and *not* that `operations.ts` implements it; when an op changes, that file must be changed by hand. The other way is driving the app: every unblocked op on every bundled spec, watching `CompileLine`. **There is no frontend test runner** — `npm run typecheck` is the only automated frontend gate, and since `SpecDocument` is `Record<string, unknown>` it cannot check a document path either. That is a named gap, not an oversight.

**Not proven, and marked accordingly:** anything involving an animal. The interpreter has never driven a solenoid, a light, or a vacuum line under this app — that is Task-Graph Phase 5 (bench jig, scope, parallel run), and until its exit criteria hold, the bench strip and the no-session invariant are the boundary. Also still open: the spec editor on Windows (packaging is staged but the frozen vendor tree is verified on macOS only), and a crashed client leaves `benchHold` set until app restart — deliberate, erring toward not-reflashing, but worth knowing when a box mysteriously stops returning to baseline.

---

**Where to next** — [tasks.md](tasks.md) (sketches and `task.json` — the other kind of task) · [websocket-protocol.md](websocket-protocol.md) §3.6–3.7 (every command above, with shapes) · [dashboard.md](dashboard.md) §5 (the port state machine `UPLOADING` joined) · [README.md](README.md)

# Task Specs

![status](https://img.shields.io/badge/status-built-7CC98F?style=flat-square) ![owner](https://img.shields.io/badge/owns-specs_·_compiler_·_bench-8B7EC8?style=flat-square) ![animals](https://img.shields.io/badge/animal_use-not_yet-C96C6C?style=flat-square)

> **What this is** · The task-spec editor under the Task tab: a declarative task compiled into a state table that a fixed on-board interpreter walks. **Tasks stop being firmware and become data** — a new task ships without touching C++.
>
> **Owns** · Where specs live and how edits are stored · the editor (form, blocks, graph, diff) · the wizard · the bench upload path · the boundaries that keep all of it away from live sessions.
>
> **Read with** · [TaskGraph.md](TaskGraph.md) (the compiler itself — design theory, the byte format, the decision log) · [creating-a-task.md](creating-a-task.md) (authoring, for the person designing an experiment) · [tasks.md](tasks.md) (the *other* kind of task — sketches and `task.json`) · [websocket-protocol.md](websocket-protocol.md) §3.6–3.7 (the wire) · [README.md §6.4](README.md#64-dependency-policy) (the dependency fence).

**Contents** — [1. What a spec is](#1-what-a-spec-is) · [2. The compiler](#2-the-compiler) · [3. Where specs live](#3-where-specs-live) · [4. The editor](#4-the-editor) · [5. The graph is the editor](#5-the-graph-is-the-editor) · [6. The diff as a review](#6-the-diff-as-a-review) · [7. The bench](#7-the-bench) · [8. What is proven, and what is not](#8-what-is-proven-and-what-is-not)

---

## 1. What a spec is

A YAML document with four layers, compiled into a byte table a fixed interpreter executes ([TaskGraph.md](TaskGraph.md)):

| Layer | Key | Changes |
|---|---|---|
| **1 · Topology** | `topology` | **The graph.** Six knobs handed to a versioned epoch template — very nearly the only layer that changes the shape |
| **2 · Contingency** | `contingency` | Per-trial content: stimuli, ports, trial types, the outcome map. Reversals live entirely here |
| **3 · Timing** | `timing` | One duration per id. Order is load-bearing — the index is what the firmware holds |
| **4 · Policy** | `policy` | Selection, correction, penalty escalation, the shaping schedule, trial count, seed |

There is deliberately **no `nodes:` key**. Task authors never write a node: the set of representable graphs is exactly the image of the templates over the topology knobs, which is what makes compilation, validation and this editor tractable ([D1](taskgraph-decisions.md#d1) — a spec declaring `nodes` is rejected with a message saying so, TG103).

**The one shape-bearing exception to layer 1, named because hiding it would be worse:** `contingency.outcome_map.correct.reward` is a layer-2 field, and setting it to `null` omits the reward delivery `PULSE` and the consumption `WAIT_EXIT` from the outcome epoch entirely (`four_epoch/v2.py`'s `if correct.reward:`). An unrewarded 2AFC really is a different machine from a rewarded one. Everything else in layers 2–4 changes content, ordering or duration and leaves the node set alone.

> [!CAUTION]
> **A spec is a SIBLING artifact to a sketch's `task.json`, never an extension of it.** The two describe different things and hash differently: `profile_hash` is what Analytics groups a sketch's historical runs by, and adding anything to `task.json` to make a graph authorable would split every sketch's past runs from its future ones permanently ([tasks.md §4.1](tasks.md#41-why-derived-not-declared), [D7](taskgraph-decisions.md#d7)). Both kinds of task live on the one Task screen — the spec workbench above, the sketch section below — because both answer "what does the animal do".

Provenance mirrors the shapes Ephymeris already records: `spec_hash` is SHA-256 over the **parsed document** (16 hex chars, like `profile_hash`/`params_hash`), so reformatting never moves it; the compiled table additionally carries the template name, version and **source hash**, so editing a pinned template — which the file-per-version rule forbids — shows up as a diff rather than a silent change.

## 2. The compiler

The compiler lives in the sidecar as a first-class subpackage,
`sidecar/ephymeris_sidecar/taskgraph/`, imported by dotted path like anything
else. Its design is [TaskGraph.md](TaskGraph.md); this section covers only the
seam between it and the app.

It used to be vendored byte-identical from a sibling repository and reached
through a `sys.path` insert, with a sync script and two mirror-drift test suites
holding the two copies together. That arrangement bought drift detection between
two repos, and cost a dead `codegen` pass, a build that silently depended on
`../Task-Graph` existing, and a rule that no one could nest the tree one level
deeper. Task-Graph is Ephymeris, so it is in here now. The two-module-objects
hazard the `sys.path` insert had to manage — a second copy of the linter's rule
registry and the `lru_cache`d registries, disagreeing silently — is structurally
impossible once there is only a dotted path.

`taskgraph/paths.py` is the one place `__file__` is walked. Runtime data
(`schema/`, `hardware/`, `templates/`, `paradigms/`) resolves package-relative and
is present in every install; repo-only paths (`firmware/`, test fixtures) walk up
for a marker file and raise a named error when frozen, because a packaged sidecar
has no business writing C headers.

**The dependency fence** ([README.md §6.4](README.md#64-dependency-policy)):
`jsonschema` + `pyyaml` are the sidecar's second exception, and a weaker one than
`grpcio`'s — nothing stands in for a compiler. On import failure every `specs.*`
command raises `SPEC_COMPILER_UNAVAILABLE`, the Task screen shows one banner, and
the legacy `task.json` path, flashing, and the whole session flow are untouched.
That fence survived the fold unchanged, because it was never about where the
source lived: **a rig that cannot compile a spec must still run sessions.**

The startup line comes from `compiler.self_check()`, which **generates a paradigm
skeleton and compiles, lints and packs it** rather than merely importing:

```
task spec compiler ready (7 paradigms, 2 template versions,
pinout behaviorbox_mega2560.v1, from .../ephymeris_sidecar/taskgraph)
```

That probe is deliberately end-to-end. A packaged build can bundle the tree,
import it, and still fail every compile on missing metaschema data — and an
import-only check reported ready for exactly that build once. The generated probe
exercises the paradigm registry, the template, the composed pinout, the strobe
vocabulary, `jsonschema`'s own data, the linter and the packer, so every data file
a freeze could drop is proven at startup rather than at first use in a lab.

In a packaged build the data files ship via `--collect-data`, and
`taskgraph/templates/` additionally as `--add-data` — plain `.py` on disk, never
in the archive, because `templates.load()` resolves a version file by path and
`source_hash()` hashes its bytes. A template family directory therefore carries no
`__init__.py`: that is what stops PyInstaller's `--collect-submodules` baking a
second copy into the archive under the very name `load()` caches.

## 3. Where specs live

```
<data_dir>/specs/
  user/<spec_id>.yaml               every spec on this rig
  index.json                        {spec_id: {editedAt}}
```

Sidecar-side writes, under the same roof as `ephymeris.db` — no Tauri fs
capability involved.

> [!IMPORTANT]
> **Nothing ships as a spec.** A fresh install has an empty library. Every task on
> a rig is that rig's own, which is why there is exactly one origin (`user`) and
> the only thing the editor's chip still says is whether there are unsaved edits.

This replaced a shipped/shadow/baseline arrangement: five specs bundled read-only,
a user file shadowing one by id, the shipped bytes baselined before the first
edit, and an `upstreamChanged` badge offering Keep-mine or Reset when an app
update moved a bundled spec underneath a local edit. All of it existed to answer
"what happens when we ship a new version of a task the user has edited" — a
question that stops being askable once no task ships.

What replaced it is **paradigms** ([§3.1](#31-paradigms-and-the-skeleton)), which
are a genuinely different thing: a bundled spec was a *task*, and shipping one
meant shipping an experiment somebody would run. A paradigm is a *shape*, and
generating from it produces a document the rig owns outright from its first save.

The save target is the **document's own `spec_id`**, so renaming the id field and
saving creates a copy — that is the entire Duplicate flow, riding one text field.
The sidecar refuses a parsed document whose id disagrees with the target, so the
two cannot drift. The id is also a filename; it dies at a regex
(`^[a-z][a-z0-9_]{0,39}$`) before any path join.

### 3.1 Paradigms and the skeleton

Seven paradigm files (`taskgraph/paradigms/*.yaml`) declare **knobs, counts,
questions and prose** — never a node, never a timing value, never a strobe code.
`schema/paradigm.v1.json` rejects the rest, so a paradigm file cannot grow into a
second spec format.

`specs.skeleton` returns **YAML text plus the compile result** in one round trip:
text because the LOAD pass checks things that only exist before parsing, and the
result because it makes "it compiles at step zero" true rather than claimed. It is
pure and writes nothing — creation stays `specs.save`, so `createSpecFrom` keeps
its single definition.

> [!NOTE]
> **This section used to forbid a skeleton generator**, on the grounds that it
> would be "a second definition of what a minimal legal spec is, competing with
> the schema". That objection was comparative — generator *versus* bundled
> paradigm — and with zero bundled specs the second term is gone.
>
> More to the point, **the generator defines nothing.** Every value it emits is
> read from an existing authority: which knobs are fixed from the paradigm file;
> outcome classes, timing ids and per-id defaults from the template, via
> `capabilities()` extended with `outcome_defaults`/`timing_defaults`; channel
> names and reward pairings from the channel registry; per-port strobes from the
> vocabulary; everything else from the user's answer, or the field is not emitted.
> That is `operations.ts`'s existing rule — *seeded from a sibling or asked for
> inline, never from a defaults table* — applied to creation instead of edit.
>
> Putting the defaults in the **template** is the load-bearing part. The template
> already decides which outcome classes exist and already consumes each one's
> trigger, terminal, delay and strobe when it emits nodes. And the firmware's own
> `TaskParams` in-class defaults *are* the GRGL values, so `timing_defaults` is not
> an invention — it is the same provenance the deleted specs carried, moved next
> to the template that emits the node. `wire_key` and `note` ride along with it.

**What was traded, stated honestly:** the deleted specs carried author comments
citing firmware line numbers, and Reset-to-shipped restored them byte for byte.
Those comments are partly recovered through `timing_defaults`, whose notes are
emitted into every generated skeleton — but a spec the operator has edited for
six months no longer has a pristine version to fall back to, because there is no
longer a shipped copy for it to differ from.

**A paradigm is matched by fingerprint, not by id.** `paradigms.fingerprint()`
computes a rig's own `my_task_3` back to the paradigm whose knobs it matches, so
it lands under the right heading without being registered anywhere, and one that
matches nothing reads honestly as Custom.

**The wizard** (`routes/TaskNew.tsx`, `/task/new`) is a route rather than a modal
for the reasons §7 gives the bench — `Modal` is capped, the unsaved guard is
per-route, and arriving should be deliberate. Each step recompiles, so a step that
leaves the task unable to compile says so there rather than at the end.

> [!IMPORTANT]
> **The wizard shows one epoch of the machine, never the whole of it.** It was a
> two-pane screen for a while — `SpecCanvas` on the left, the step's questions in
> a rail on the right — so that "it compiles at every step" was something an
> operator could watch rather than something we claimed. What that actually did
> was make creating a task look like the Designer and read like an editor you had
> to already understand: twenty-six nodes and thirty-six edges restructuring
> themselves on every keystroke, in front of someone who has not yet decided how
> many odours there are.
>
> That objection was right about the WHOLE graph and wrong about a slice of it.
> `EpochGraph` (`components/specs/EpochGraph.tsx`) heads each epoch step with
> four to ten nodes — exactly the ones the step below edits — live on the same
> 120 ms compile. It is read-only in the strong sense: no pan, no zoom, no
> selection, `pointerEvents: none` on the SVG, because editing is the step's job
> and a picture that highlights on hover invites a click that does nothing.
>
> Everything else still mirrors the **guided session flow** — a `TaskJourney`
> rail of constellation stars across the top, one hint line naming the next
> action, `hud` panels over the rig's own sky, all the same shape as
> `/session/new` because it is the same kind of errand. The rail settles to
> `COMPACT_SCALE` on Review, the way the session flow's does on reaching Mission
> Control.

**The epoch slice is a scope on the one layout, not a second one.**
`layoutSpecGraph(graph, {scope})` decides structure globally and scopes only
coordinates, and both halves of that are load-bearing:

- `reachesLaterBand` is *definitionally* global — it asks whether a node can
  reach a **later** band. Handed a single-band subgraph nothing can, so the
  spine comes out empty and every branch collapses into one column: the
  `grgl_2odor` bug the lane rules exist to prevent.
- `graph.nodes[i].index === i` is load-bearing in `layout.ts` and in every
  caller. Scoping therefore **masks**; it never filters the node array.

Edges crossing the boundary are drawn as labelled stubs (`HELD → sampling ·
S10`) rather than dropped, because an epoch's abort chains leaving is most of
what the picture is for. `layoutSpecGraph(graph)` with no scope is byte-identical
to what the Designer got before scopes existed.

> [!CAUTION]
> **Band 4 is not the outcome epoch, and a go/no-go task has no band 4 at all.**
> `outcome_chain`/`_sink`/`_score` memoise per class and stamp whatever band was
> current when the class was **first referenced**, so on a plain 2AFC
> `TRIAL_REPEAT` is band 1 and `TRIAL_ADVANCE` band 3; and `b.band(Band.OUTCOME)`
> sits inside `four_epoch/v2.py`'s `if correct.reward:`, which go/no-go never
> enters. Scoping the Score step by `band === 4` therefore draws a wrong picture
> on every topology and a blank one on go/no-go. `lib/specs/outcome.ts` walks the
> compiler's own `score:<class>` edges instead — and must not use
> `selection.ts`'s `durationId ↔ outcome.delay` join for it, since `wrong` and
> `omission` share `t_pen_error` and that join returns both classes for either
> node.

**`TaskShape` is gone**, and its two jobs went to the two places that already
answered them. Its four epoch readouts are now sublabels under the rail's stars,
absolutely positioned so the rail's fixed-width arithmetic is untouched. Its
trial-type rows became `ResponseMap` (§3.2) — the mapping shown once, on the step
that owns it, rather than in a standing tile competing with the epoch graph above
it.

**From scratch is the default, and it is still a paradigm.** `/task/new` opens on
step 1 with `paradigms/blank.yaml` already loaded — the smallest topology that
compiles, fixing nothing, asking nothing. A quiet *Start from a template* link
reaches the seven shapes this lab runs. That inverts what the screen used to be, a
mandatory gate in front of every new task, and the doctrine survives the inversion
intact **because "from scratch" is a paradigm that fixes nothing rather than the
absence of one**: `specs.skeleton` still reads a paradigm, so the generator still
invents no value and there is still exactly one creation path. `blank.yaml` is
`hidden: true` — listing it in the gallery would offer the default as one of the
alternatives to itself.

**The steps run in trial order, not layer order.**

| # | Step | Shape | Durations it carries |
|---|---|---|---|
| 1 | Identity | — | — |
| 2 | The paradigm's questions — *skipped when it asks none, which `blank` does* | — | — |
| 3 | How does a trial begin? | commitment hold | band 1 |
| 4 | What does the animal sample? | stimuli, stages, retention | band 2 |
| 5 | How does it answer? | ports, go/no-go, the mapping | band 3 |
| 6 | What counts as right? | rewarded | the outcome routes |
| 7 | How does the session run? | selection mode | trials, seed, the ramp |

Two of those orderings are the point:

- **The standalone timing step is gone; every duration is grouped into the epoch
  that owns it.** No document changes — each field is still a path write to
  `timing[i].ms` — only the grouping moves. The wizard's order is the operator's
  mental model and the document's layer order is the compiler's, and nothing
  requires them to match. **The grouping is derived from the compiled graph**
  (`band` + `durationId`), never from a hand-written table, which is also what
  gets the awkward cases right: a penalty lands with the epoch it aborts from, and
  `t_pen_break` appears under *both* engagement and response because a hold break
  can happen in either.
- **Stimuli come before responses**, which inverts what this document argued
  when the mapping was a table. The old order put Answer first because "a trial
  type maps a stimulus onto a target, so the answer space has to exist before
  anything can be mapped onto it" — and that premise moved with the gesture.
  Mapping is now a stimulus chip dropped onto a response tile, so the **stimuli**
  are what must exist first; the ports do not, because they come from the rig's
  channel registry rather than from the document and are there whatever order the
  walk runs in.

Each duration is labelled with the template's own `timing_defaults` note rather
than the overlay's line about the field — `odorPokeHold at BehaviorBox.h:1176`
instead of the same sentence about the uint16 ceiling repeated down six rows.
That is what `capabilities().timingHelp` is for ([websocket-protocol.md
§3.6](websocket-protocol.md)).

### 3.2 The mapping is a gesture

`components/specs/ResponseMap.tsx` is the Answer step. **The tiles are the rig's
own `kind: response` channels**, bound or not, because "which ports could this
box answer at" is a fact about the box and the operator is choosing among them —
which is also what keeps the ceiling honest: no number here says how many
response ports are allowed, and a rig that grows a third one in Rig wiring grows
a third tile with no frontend edit.

Dropping a stimulus on a bound tile **is** how a trial type comes into existence:
the gesture answers the two questions `addTrialType` would ask and the op fills
the rest from its own sibling-seeded suggestions, so there is no modal. Clicking
a mapping expands it in place to the port's strobes, its reward line and the
trial type's weight — one fact from the operator's side, two blocks in the
document. Re-aiming a mapping between two existing ports is the one plain
`setAt`, because it crosses no invariant.

Everything structural still runs the same pure ops the Designer's blocks do, and
`blocksFor(3)`'s three overlapping buttons are hidden **in the wizard only**
(`StructureBlocks`' `covered` prop). The Designer keeps them: it has no tiles,
and they are its only way to reach those ops.

> [!IMPORTANT]
> **Click-to-carry is the supported path; dragging is the nicety.** HTML5 drag
> works in this app only because `dragDropEnabled: false` is set in
> `tauri.conf.json`, and the lab runs Windows where none of it has been tried.
> Same recipe as `CageAssignment`: a plain `<button draggable>` INSIDE a
> `motion.span layout`, because on a motion component `onDragStart` is framer's
> pan-gesture prop and the native event is never heard.

### 3.3 The explanation rail

`components/specs/ExplainTile.tsx` sits left of each epoch step and **follows
focus**, one definition at a time. Every tunable in a spec already had a sentence
written about it somewhere that could not reach the operator: the presentation
overlay for the fields, the template's `timing_defaults`/`outcome_defaults` for
the durations and outcome classes, the channel registry and the strobe vocabulary
for the values. At rest it names the epoch, which is what someone who has focused
nothing is actually asking.

A standing glossary of every tunable on the page was the alternative and is
worse: a step can carry twenty rows and a column of twenty definitions is a wall
nobody reads. The inline `FieldRow` caption **stays** — it is what makes a field
legible without a pointer, and a tile that only speaks on hover would make the
form worse for keyboard use.

Plumbed in exactly one place, `SpecField`, which is the single dispatcher every
generated spec field goes through — so the wizard, the Designer's form and the
Inspector are covered at once and the shared `FieldRow`/`rows.tsx` the session
screens also use are untouched.

### 3.4 The Score step

`components/specs/OutcomeMap.tsx` is built around the **two terminals**, because
a trial advances or it repeats and those are the only two things that can happen
to the counter. Every outcome class is drawn routed into one of them, and each is
a card that expands to its trigger, terminal, delay, strobe and reward — with
`capabilities().outcomeHelp[cls].note`, the template's own sentence about what
the class *means*, which `outcomeClasses` cannot say.

An operator **cannot add a terminal or invent an outcome class** — `capabilities()`
decides which exist and TG302 errors in both directions. What they can do is
retune every class that exists, and see the ones a different shape would produce:
those are listed greyed, each naming the knob and the step that would unlock it,
and the list is computed by asking `specs.capabilities` for the *proposed*
topology exactly as `useOperation` does. Re-implementing `capabilities()`'s
conditionals in TS would be the second answer the function-not-a-table rule
exists to forbid.

The correction budget is offered **only where `policy.correction.budgets` already
exists**, for the reason §4 gives from the other side: a block covering some of
the ports is worse than one covering none.

**The small visualizations are computed, never listed.** *One pass* draws a band's
durations to scale by walking the compiled graph from the band's first node along
each primitive's success edge (a HOLD is held, a WAIT_ENTRY entered, a DELAY
expires) and stopping when the walk leaves the band. Laying every duration in the
band end to end instead would draw a trial that cannot happen, with the abstention
penalty following the engagement window it exists *instead of* — so what the walk
misses is listed under *instead, on failure* rather than drawn. The bar is floored
so a 10 ms hold beside a 60 s window stays visible, which means **the number
printed on each segment is the authority and the picture is only for the ratio**.
`ResponseMap`'s tiles print each channel's pin and reward line from a one-shot
`hardware.get`; a channel the rig has no entry for reads "not wired" rather than
inventing a pin.

**The Task tab is a column of HUD tiles over the sky**, the Dashboard's shape and
now literally its component — `components/common/SummaryCard.tsx`, extracted when
the Task tab's own flatter version (a 14px static icon, no divider, no rows) made
the two pages that are both "tiles over the rig's constellation" stop looking like
one app. One Pulsar hero slab is the page's single primary action; the library,
Rig wiring, Bench and Sketches are tiles. The template gallery appears **only
while the library is empty**: with nothing shipped that is the first-run
experience, and once a rig has tasks the wizard's own quiet link is the way in
rather than a permanent gallery competing with the library above it.
`components/specs/ParadigmCard.tsx` is the one card, used by both, each
paradigm carrying a glyph and an accent — held there and not in the paradigm file,
because an icon is a property of how this app draws a card and not of what an
experiment measures. The card shows the **first sentence** of `affords`, not the
paragraph: every paradigm's opening sentence is already its summary, so this needs
no second field to keep in sync and throws no prose away.

## 4. The editor

The form is generated, not written, from three sources with strict jobs:

| Source | Says |
|---|---|
| `schema/task_spec.v1.json` | what is **legal** — types, ranges, enums |
| `taskgraph/schema/task_spec.presentation.v1.json` | what a field is **called** and which **widget** edits it (labels, units, groups, help). Lives beside the schema it describes, with a test pinning two-way coverage |
| the document | which **rows exist** |
| `capabilities(topology)` | which rows this topology **needs** |

> [!IMPORTANT]
> **`capabilities()` decides which rows EXIST; the compiler decides which are VALID.** The form re-implements no lint rule. A template's `capabilities(topology)` returns the outcome classes and timing ids this configuration produces — a *function*, not a table, because the answer depends on several knobs at once — and the form re-gates its timing rows and outcome cards the instant a knob moves, before any compile returns. A timing row the topology no longer needs is **greyed with a Remove button, never hidden** — hiding silently orphans a value the operator typed.

**Structural blocks** (`lib/specs/operations.ts`) are how the shape changes. A knob never moves alone: adding a sampling stage renames `t_sample_hold` to `t_sample_hold_0`, appends the new hold and the gap before it, and extends *every* trial type's `stages` — six edits that are only jointly valid, which is exactly why they are one operation with one preflight rather than six fields to remember. The ops are pure and composed from `setAt`/`deleteAt`; they are **handed** `capabilities()` for the topology they PROPOSE (fetched by `useOperation` before anything is applied) rather than computing it, because an op that computed its own class set would be a second implementation of the template's `capabilities()` — the trap the function-not-a-table argument exists to prevent.

Four rules that make a block safe to press:

- **A new timing row is seeded from a sibling in the same document, or asked for inline — never from a defaults table.** A table would be a second definition of what a reasonable task looks like, competing with the template's own `timing_defaults` (§3.1). `t_sample_hold_1` copies `t_sample_hold_0` (the template's own comment says stage-indexed ids exist so each stage is independently rampable); `t_retention` and `t_resp_hold` have no peer and so are asked for, and Apply waits. A seeded row's preflight line names the row it copied.
- **An op that changes a value a `note:` describes deletes the note, and says so.** Rewriting one means inventing a firmware citation; leaving it makes a pinned line number a lie. `t_resp_win → t_withhold_win` is a *different* firmware field (`fluidWellPoll` → `nogoWellPoll`) so the note and `wire_key` go; `t_sample_hold → t_sample_hold_0` is the same field at a new index, so they stay.
- **Stale outcome classes are deleted; stale timing rows are kept and greyed.** TG302 errors in both directions, so a class the topology cannot produce is a hard error and has to go (the baseline recovers it). An unused timing row is merely unused — hiding or deleting one silently orphans a value the operator typed.
- **An op that cannot be made valid says why, from the registry.** *Add a response option* blocks when every `kind: response` channel is already bound — two of them on the shipped wiring — and the message is computed by counting the registry rather than hardcoded, so adding a third response channel in Rig wiring turns the op on with no frontend edit. **That is now a thing an operator can actually do** (§9), which is why the message names the screen; before the rig document existed this op was blocked permanently and the registry-derived message was a promise about a build nobody could make. It exists rather than being absent so the UI can explain.
- **An op extends a policy block that exists; it never creates one.** Adding a response option writes `policy.correction.budgets.<port>` **only if that map is already there**. Writing it unconditionally invented a correction policy on a task that had declared none — and worse, produced a block holding exactly one entry, the port just added, so the new well read as a deliberate zero and the well that was already there as an unstated default. A block covering some of the ports is worse than one covering none.

> [!CAUTION]
> **A block must fill every field its new shape makes reachable, not just the ones its knob names.** Switching go/no-go → n-alternative is the case that already bit: a withhold task's ports declare `enter_code` and nothing else, because it never reports a wrong port, a broken response hold, or leaving a reward port. All three become reachable at once and TG506 wants a code for each on *every* port — the operation shipped without them and produced six errors. `sidecar/tests/test_spec_operations.py` pins both directions, including the negative case.

**The live compile** runs on every edit (120 ms debounce, stale replies discarded): the frontend serializes the document and `specs.compile` checks **exactly the bytes a save would write** — the LOAD pass (schema validation, TG1xx, the YAML `on:` trap) checks things that only exist before parsing, so the wire carries text, never a dict. Sidecar-side it runs in a worker thread behind a semaphore of 1; a synchronous compile on the loop would stall the 20 Hz output flush and, mid-session, the fsync-per-strobe write path. ~21 ms warm.

**A spec that doesn't compile is a successful reply carrying diagnostics, never an error** — the Analytics corrupt-file discipline. Each diagnostic arrives with its `placement` precomputed by the compiler's own `placement()` (field / row / section / node / document) and an `anchor` that is an overlay key — so putting an error next to the input that caused it is a dictionary lookup, and the frontend never parses a location. The panel below the form lists **every** diagnostic regardless, with `help` and the `D-number` decision pointer, because a diagnostic that reaches nobody is the failure mode the whole design exists to avoid.

Pickers draw from the **registry files** — the same bytes the compiler validates against, served as the compiler's own composed view (logical channels merged with the active pinout) rather than one of its raw inputs — once per mount, via `specs.schema`. The frontend never holds its own copy of a registry: a strobe picker offering a code the compiler rejects would be manufacturing an error.

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

`specs.diff` diffs the **listing** — the compiler's checked-in review artifact — never the YAML. Headline first (`26 → 29 states · 462 → 508 bytes`); hunks grouped by the listing's own ruled sections so a change reads as *"in STATES"*; `spec_hash`/`template_hash` move on every edit and are confined to a provenance strip, never hunks. Baselines: *vs saved*, or *vs another spec* — the second is how a `derived_from` claim gets read: an eased variant against its base shows **no structural hunks** (same nodes, same edges), with values moving in TIMING VECTOR and its derived sections (STAGE SCHEDULE, DWELL BUDGET) alongside.

`specs.export` returns bytes in the reply — spec, listing, lint, canonical JSON, packed `.bin`, bench card — and the frontend writes one artifact at a time through the user's own save dialog. No wire command writes an arbitrary file.

## 7. The bench

Probing and upload own the port through a dedicated **`UPLOADING`** state — `FLASHING`'s twin (force-release passthrough, auto-resume), but the uploader opens its **own** serial handle: the passthrough ring buffer is drained by the 20 Hz flusher, not consumed, and a table transfer is request/response with deadlines. `ports/upload.py::PortLink` implements the compiler transport's `Link`; progress is extracted *inside* the link (chunks counted at the board's ACK, not at hopeful writes) so `taskgraph.transport.client` is used unmodified; the console mirror carries headline lines and never the hex chunks.

The pieces that exist because hardware taught them:

- **Baud** is found by `detect` (115200 then 9600 — the fleet's two rates mid-rollout), cached per `hardware_id`, invalidated by any flash to that box. Never `settings.defaultBaud`, which is the console default. `read_banner`'s timeout is a **total budget** — a chatty board at the wrong baud produces garbage "lines" fast enough that a per-line clock never expires (found on the first real probe; BOX_Utility streams STATUS continuously).
- **`PortLink` settles, flushes, then pulses DTR again** — upstream `SerialLink`'s order, where the order is the point: the flush discards the open's own boot banner, and the deliberate second reset makes the banner read next *this run's*. Flushing without re-resetting made every legacy sketch look mute at its own baud.
- **`UPLOAD_REFUSED` vs `UPLOAD_FAILED` follows where the fault lies.** A healthy board saying no before any byte moved (no CAP → *"flash the interpreter sketch first"*, wire mismatch, capacity exceeded) lands the port cleanly. A broken transfer parks it in `ERROR`, because a partial table leaves the board's state genuinely unknown.
- **`utility.benchHold`** suspends baseline restores while the bench panel is mounted — otherwise an upload ends with the port falling `IDLE` and the baseline quietly reflashing `BOX_Utility` over the interpreter, the table dying with it. A separate flag from the session hold, so neither release can leak into the other.

The bench is **its own route** (`/task/bench`, reached from the landing page or from the Designer's *Bench* action, which passes `?spec=<id>`) rather than a panel inside the editor. It is the one surface in the app that talks to real hardware about a spec, and it must not read as one more section of a form — arriving is a deliberate act, and the page says what it is before it says what it can do. The UI is then **two explicit clicks, never one combined button** — *Flash TaskRunner_Dev* (destructive, labelled as such) then *Upload table* — under a permanent strip:

> **Bench only.** The table interpreter is proved off-target and has never driven a pin — a box carrying TaskRunner accepts a table and reports whether it fits. It runs no trial and delivers no reward. Do not put an animal in a box running this.

> [!CAUTION]
> **The no-session invariant, structurally enforced:** no wire command ties a spec to a session. `sessions.confirmMapping` does not learn a `specId`, `port.startSession` is untouched, and `UPLOADING ↔ IN_SESSION` is illegal in the transition table in both directions. That door opens at the Phase 5 exit criteria — actuator timing verified on hardware, parallel run clean — not because the parts happened to be ready.

## 8. What is proven, and what is not

**Proven, on a real Mega2560 through the app's own wire commands** (2026-08-03): the legacy-sketch flash against the merged bundled libraries; the no-CAP probe and refusal with the port landing cleanly; TaskRunner_Dev flashed and announcing `PROTO=2 WIRE=1` with the full capacity set at 115200; a compiled 2AFC table uploaded — 558 bytes / 9 chunks / 207 ms — with CRC **and** body digest confirmed (the CRC says the bytes arrived; the digest says they decoded into the right fields); the baud cache invalidated by a flash and skipping detection on the second upload. Off-target, the same sidecar-compiled tables go `TABLE OK` into `tg_board`, the real receiver compiled for the host — and every upload-protocol failure mode stays covered by the compiler's own `tests/compiler/test_uploader.py`, deliberately not retested at the app layer.

**The structural blocks** (§4) are covered two ways, and the gap between them is worth naming. `sidecar/tests/test_spec_operations.py` applies each op's path edits to each paradigm skeleton and asserts the real compiler accepts the result — but it is a **second implementation in Python**, so it proves the design is sound and *not* that `operations.ts` implements it; when an op changes, that file must be changed by hand. The other way is driving the app: every unblocked op on a task generated from each paradigm, watching `CompileLine`. **There is no frontend test runner** — `npm run typecheck` is the only automated frontend gate, and since `SpecDocument` is `Record<string, unknown>` it cannot check a document path either. That is a named gap, not an oversight.

**Not proven, and marked accordingly:** anything involving an animal. The interpreter has never driven a solenoid, a light, or a vacuum line under this app — that is Phase 5 (bench jig, scope, parallel run), and until its exit criteria hold, the bench strip and the no-session invariant are the boundary. Also still open: the spec editor on Windows (a frozen build is verified on macOS only), and a crashed client leaves `benchHold` set until app restart — deliberate, erring toward not-reflashing, but worth knowing when a box mysteriously stops returning to baseline.

---

## 9. Rig wiring

`/task/hardware` (`routes/TaskHardware.tsx`) is where an operator says which pin
each channel is on. Before it existed, `taskgraph/hardware/behaviorbox_mega2560.v1.json`
was a transcription of `BehaviorBox.h` shipped inside the package and read-only in
a frozen build — `active_pinout_id()`'s docstring called it "a BUILD-TIME choice,
not a runtime setting" — so an operator who rewired a box could not tell Ephymeris.
They edited firmware and rebuilt.

**It is on Task, not Config, and the boundary is subject.** Config answers *how is
this rig wired* in the sense of which USB port is box 3 — runtime indirection, per
rig, changing on every board swap. This answers *what is channel `left_well`* —
compile-time input, per box generation, baked into every table the compiler emits.
Two different axes, and the naming reflects it: this screen is **Rig wiring** and
the Config step that was called "Map hardware" is now **Bind boxes**, because two
screens with one name is a support call.

**The document** is `<data_dir>/hardware/rig.json`, owned and validated by
`hardware/store.py` on the `specs/store.py` pattern — not settings (leniently
parsed and silently defaulting, which is catastrophic for a pin) and not SQLite
(no relational content, and it would put registry loading behind the db lock). It
keeps the shipped pair's two-section shape, `channels` and `pins`, so TG226 still
means something. `registries.set_rig_source()` composes it into `channels()`, and
**`channels.cache_clear()` fires on write and only on write** — that cache sits on
the hot compile path, and hanging invalidation off `settings.push` would clear it
on every reconnect.

Three lint rules exist because a pin became typeable: **TG227** an index outside
the board's legal range or at/above the `0xF0` binding-sentinel floor, **TG228**
two channels on one pin, **TG229** a response channel with no slot, two on one
slot, or a slot the vocabulary has no codes for.

> [!CAUTION]
> **`spec_hash` does not absorb the pinout, and must not** (D22). A spec is
> identified by what it says, and it says channel *names* — so a re-pin changes
> every compiled byte and moves no `spec_hash`, and the listing, which prints
> names, shows nothing. `specs.diff` is this project's designated review artifact,
> so that was a provenance hole the moment the pinout became per-rig: two sessions
> recorded as the same task, different valves fired, nothing in the record telling
> them apart. A `pinout_hash` rides **beside** `spec_hash` in the listing header
> and on the run record instead. Folding it in would conflate what a task *is*
> with where it is *wired*, and Analytics groups by `spec_hash`.

**`hardware.save` reports breakage before it lands.** Full authoring means an
operator can delete `left_well` while a stored spec binds it — TG223 catches that
at compile, which is far too late. The save path recompiles every stored spec
under both wirings and returns the ones that **newly** fail, so "shown loudly" is
a list of task ids rather than a warning tone.

The screen follows the existing grain — *the canvas selects, the rail edits* —
with an SVG board diagram ported from `ConstellationBoard.tsx` (one write per
completed drag, never per move) and click-to-carry alongside dragging, which is
mandatory rather than a nicety: HTML5 drag only works here because
`dragDropEnabled: false` is set in `tauri.conf.json`, and the lab runs Windows,
where none of this has been tried.

---

**Where to next** — [tasks.md](tasks.md) (sketches and `task.json` — the other kind of task) · [websocket-protocol.md](websocket-protocol.md) §3.6–3.7 (every command above, with shapes) · [dashboard.md](dashboard.md) §5 (the port state machine `UPLOADING` joined) · [README.md](README.md)

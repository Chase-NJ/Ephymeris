# Starting a Session — Full Spec

**Status:** Living document. **Implemented** as of this revision — the full path from the dashboard CTA through configuration, mapping, flashing, `IN_SESSION`, Mission Control and the 3D constellation is built, and was verified end to end against a real Mega running firmware that speaks §7's protocol. Written alongside `data-saving.md`; read together. This doc also resolves several long-standing TBD items: `hardware-interaction.md`'s stubbed `IN_SESSION` state, `websocket-protocol.md` §9's session-runner messages, and `cohorts.md` §12's "what does 'ready to run' mean."
**Companion documents:** `data-saving.md` (file writing, Task Profiles this doc's config form and live view are driven by), `cohorts.md` (the cohort/animal/group model this doc runs against), `hardware-interaction.md` (per-port state machine — `IN_SESSION` entry/exit is specified here), `arduino-directory.md` (sketch selection), `websocket-protocol.md` (wire schema, extended in §9), `ephymeris_v1.0.md` (the `/session/new` stub this doc replaces, motion conventions).

---

## 0. Scope

Defines the full path from the dashboard's "Start a Session" CTA to a running Mission Control dashboard: the configuration step, the animal→box mapping and flashing sequence, and the live session UI (3D constellation, per-box controls, the zoomed-in per-animal view). Consumes `data-saving.md`'s Task Profiles and file schema; doesn't redefine them.

---

## 1. "Ready to Run" — Resolving `cohorts.md` §12

The dashboard hero CTA currently does an existence check only (`cohort count > 0`). Full readiness, defined here: a cohort is ready to start a session if it has **at least one group with at least one animal that has a `boxNumber` assigned.** A group with zero box-assigned animals is skipped automatically rather than blocking the whole cohort — see §2.3.

---

## 2. Step 1 — Configuration Menu

The first screen after the hero CTA (or a cohort card's "Start Session" action). All three fields are required before continuing:

### 2.1 Cohort

Selected from the same card-grid pattern as the Cohorts tab (`cohorts.md` §4) — visual consistency, not a plain dropdown, since the user is already familiar with picking a cohort that way.

### 2.2 Session Prefix + Number

- Prefix: dropdown over `data-saving.md` §3's `Prefix` list, with inline add/remove.
- Session number: text field, pre-filled with a suggested next value (highest existing numeric session number for that prefix, +1 — `data-saving.md` §10 asks whether this should be strictly numeric; the suggestion degrades gracefully to "no suggestion" for a prefix with no numeric history yet).
- **Soft warning, not a block**, if the chosen `(prefix, sessionNumber)` already has data from earlier the same day: "Session 25 for this prefix already has data from today — continue anyway?" Reusing it is legal (`data-saving.md` §1) but usually accidental.

### 2.3 Which Group Runs First

Not a manual choice in this step — the session begins with the cohort's lowest-`order` group that has at least one box-assigned animal (§1). This is what `Group.order` was reserved for in `cohorts.md` §1; asking the user to also pick a starting group here would be redundant with data they already set up. Switching to the next group later is a live-session action (§5.2), not a config-time one.

---

## 3. Step 2 — Animal → Box Mapping Confirmation

A per-box card grid — visually similar in spirit to Debug Mode's 6-box layout (`hardware-interaction.md` §6.6), but purpose-built: this is a confirm-and-configure step, not a console.

Each card shows the box number, the animal assigned to it (name, sex, icon treatment consistent with `cohorts.md`'s theme), and:

- **Sketch selector** — the categorized picker from `arduino-directory.md` §5, scoped to this one box.
- **Task config sub-form** — appears once a sketch is chosen, *only if that sketch has a Task Profile* (`data-saving.md` §6). Fields, labels, and defaults come straight from the profile's `config` array. A sketch with no profile shows no sub-form — bare `START` at flash/run time.

Configured **per box, independently** — two boxes running the same sketch don't have to share config values, matching the real sample data (`correction_left`/`correction_right` are per-animal, and a lab plausibly tunes these differently per rat).

The user can adjust the standing `boxNumber` mapping here too (it's a confirmation step, not just a readout) — changes here are **session-local only**. They never write back to the cohort's stored mapping; permanent changes go through Cohort management (`cohorts.md` §6) instead. Keeps this step's purpose singular — confirm and configure *this run* — rather than doubling as an editor for stored cohort data.

**Leaving the step:** what "back" means depends on whether the session has run yet. On first entry (session still `configuring`), Back returns to Step 1 and abandons the session record via `sessions.abandon` — the record is marked `aborted` rather than left stranded in `configuring`, and Step 1 creates a fresh session on the next Continue. On re-entry via Switch Group the session already holds recorded group runs, so Back would be a lie — the step instead offers **End session** (`sessions.end`), landing on Analytics like any other session end.

---

## 4. Step 2b — Flashing Sequence

Once the user confirms, each box's sketch is flashed **in sequence**, not in parallel — reuses `port.flash` (`hardware-interaction.md` §4) exactly, one box after another.

**Animated, on-theme progress indicator:** each box's card icon transitions through the same states its Debug Mode badge would (`hardware-interaction.md` §3.4), but rendered here as part of the star motif already established — a box mid-flash shows its star "flaring" (brief animated pulse) rather than a generic spinner, so the visual language stays consistent with the rest of the app rather than switching to a plain loading indicator for this one step.

**Important protocol wrinkle:** `hardware-interaction.md` §3.3 normally auto-resumes `PASSTHROUGH` after a successful flash if that was the pre-flash state. This flow needs the opposite — every box must land in `IDLE` afterward so the session runner can claim it (§5.1's `IN_SESSION` entry requires `IDLE`, same as every other port operation). **Proposed protocol change:** `port.flash` gains a `suppressPassthroughResume: bool` arg (default `false`, preserving existing Debug Mode behavior); this flow sets it `true`. Flagged for `websocket-protocol.md` in §9.

On completion, the user lands in Mission Control.

---

## 5. Mission Control — Overview

### 5.1 Header

Always visible: session name (`<prefix>_<sessionNumber>`), date, current time, and session start time — all in 24-hour format, per your instruction.

### 5.2 Session-Wide Affordances

- **Start All** — sends the built `START` command (§ `data-saving.md` §6.3) to every box in the current group that isn't already running. Per-box `IN_SESSION` entry sequence, detailed in §7.
- **Switch Group** — only shown if the cohort has more than one populated group. Ends the current group's runs (same graceful stop as §5.3's per-box Stop, applied to all), then re-enters **Step 2** (§3) scoped to the next group by `order` — since different animals are physically going into the boxes, the mapping/sketch/config confirmation and flash sequence (§3–§4) genuinely need to happen again, not just a data-model swap.
- **End Session** — gracefully stops every currently-running box (§5.3's Stop, applied to all), waits for each to finalize (`data-saving.md` §7), then marks the `Session` record `completed` and returns to the dashboard.

### 5.3 Per-Box Affordances

- **Start** — the `IN_SESSION` entry sequence (§7) for that one box.
- **Stop** — sends the literal `STOP` line over that box's serial connection. The firmware checks for it once per trial boundary (`GRGL_2-Odor.ino`'s own `checkForStop()`), so a trial in progress always completes before the board honors it — this is firmware behavior this doc relies on, not something the app enforces itself.
- **Reset** — the existing DTR-toggle reset (`hardware-interaction.md` §5), unchanged. Rebooting mid-session returns that box to `IDLE`/waiting-at-`READY`; the operator presses Start again to resume.

---

## 6. The 3D Constellation

The centerpiece view. Per-cohort, orbitable, built with `three.js`/`react-three-fiber` (no constraint here from any sandboxed widget environment — this is the real app, full npm access).

### 6.1 Star Identity and Placement

Extends `cohorts.md` §5's procedural generation rather than replacing it — same deterministic-PRNG instinct, one real change: **each star's position is seeded from `(cohortId, animalId)` together**, not just the cohort id. `cohorts.md`'s 2D icon only needed an aesthetically stable *count*; this needs a specific, permanent position *per animal*, stable regardless of roster edits elsewhere (an animal added later doesn't reshuffle everyone else's star). Connections between nearby stars reuse the same thin-`Pulsar`-line treatment as the 2D icon and the hardware status widget — one consistent visual family across all three places it now appears.

### 6.2 General (Orbit) View

Camera starts pulled back, the full constellation visible, orbit/pan via click-drag (standard `OrbitControls`-equivalent). Stars for animals currently `IN_SESSION` are **illuminated**; everyone else in the constellation is present but dim/unlit — including animals in a group that isn't running right now (§5.2), and animals with no box assigned at all. Only illuminated stars are interactive (hover indicator, clickable) — an unlit star has no live view to show.

### 6.3 Zoom-to-Star ("Arrival")

Clicking an illuminated star flies the camera to it — an eased cinematic move (cubic/exponential easing, a deliberate, acknowledged exception to the app's usual spring-physics motion convention; a camera flythrough reads as cinematic rather than mechanical, and springs would fight that). On arrival, a **sleek but still matte** treatment — proposed, not finalized, worth seeing built before committing further: thin concentric rings (in `Pulsar`/`Halo`) animate outward from the star and settle into a slowly rotating decorative ring around it — an instrument/HUD feel rather than a glow or gradient, keeping the theme's explicit "no glow effects" rule (`ephymeris_v1.0.md` §2.2) intact even at the app's single most visually ambitious moment.

The 3D scene **stays rendering in the background** once arrived — the data panel (§6.4) overlays it (translucent `Nebula`, vibrancy blur, docked to one side) rather than replacing it outright. "Arrival" means the camera is now close to that star; you're looking at it with an instrument panel open, not cutting to a different screen.

### 6.4 Zoomed-In Star View

- Animal name.
- Running sketch (name, and its category from `arduino-directory.md` if useful context).
- Start / Stop / Reset for that box (§5.3, same actions, just reachable from here too).
- **Recent strobes** — a fixed five-row feed of the box's most recent strobes, newest first: code chip, the profile's decoded strobe name (`data-saving.md` §6.4; a profile-less sketch shows `Strobe <code>`), and the board-side timestamp. Rows land with the app's snappy spring and dim as they age down the frame; empty slots hold the frame's shape. *Interim design:* the rolling live-metric charts originally specified here (P(hit) over `windowSize`, per `liveMetrics` entry) are deliberately out of the zoomed view for now — the general view's per-box metric strip still shows them — and are expected to return once the zoomed view's layout settles.
- **Back to overview** — reverses the camera move (same eased eached-move convention, §6.3), returns to the pulled-back constellation view.

### 6.5 Guided-Flow Chrome (spans §2–§6)

Three implemented pieces that guide an operator through the flow. Grouped here because they are all visual scaffolding rather than steps of their own; they appear across Steps 1–2 and Mission Control.

**The journey rail** (`SessionJourney`) — a four-step progress indicator, **Configure → Boxes → Run → Finish**, rendered as constellation stars joined by a thin `Pulsar` path: completed stars are filled, the current one pulses in `Starlight` behind a flat expanding ring, upcoming ones are `Halo` outlines. No blur anywhere, so the palette's no-glow rule (`ephymeris_v1.0.md` §2.2) holds even on the pulsing element.

Beneath it sits a single crossfading hint line — the only text direction in the flow — which always names the next action, plus the running group's position (`group 2/3 · Group B`) when a cohort has more than one populated group. It is deliberately always on and deliberately subtle: the flow is run by lab members who may use it infrequently, so the next action should never have to be inferred, but it also can't compete with live data for attention.

**The placement banner** (`RatPlacementBanner`, Step 2 only) — the box-placement instruction drawn rather than written: a lab member lifts an animal from its home cage and places it through the front door of an operant chamber, looping over the boxes actually mapped on the cards below, with the chamber's number lighting `Ion` once the animal is inside.

**Deliberately off-theme in style, not in palette.** The rest of the app is schematic and flat; this one illustration is filled, rounded, and drawn in 3/4 perspective on purpose — it is the only moment in the flow about *handling an animal* rather than reading data, and it should feel warm. Every fill still comes from the six tokens (white rat = `Starlight`, gloves = `Pulsar`, equipment = `Nebula`/`Halo`, depth = `Void`, success = `Ion`), stays flat and matte, and takes its depth from face shading and a travelling ground shadow — never a gradient or a glow. Under `prefers-reduced-motion` the scene renders as a still of the finished placement.

**The session-end landing** — End Session navigates to `/analytics` carrying the ended session's name, and that view acknowledges the session closed and its data files were written before showing its usual placeholder. This is what makes "Finish" a real destination rather than the flow simply stopping. It stays honest about Analytics being a stub (`ephymeris_v1.0.md` §4.4) while still closing the loop the rail promises.

---

## 7. `IN_SESSION` — Resolving the Hardware-Layer TBD

`hardware-interaction.md` marks `IN_SESSION` as awaiting this spec. Entry sequence, per box, triggered by Start (§5.1 or §5.3):

1. Port transitions `IDLE → IN_SESSION` (refused if not currently `IDLE`, same enforcement rule as every other transition, `hardware-interaction.md` §3.3).
2. Sidecar opens the port — this itself triggers the Mega's DTR auto-reset (`hardware-interaction.md` §5's existing reset mechanism, not a new one), rebooting the board into `setup()`.
3. Sidecar waits for the board's `READY` line.
4. Sidecar sends the built `START ...` command (`data-saving.md` §6.3).
5. Sidecar watches for an optional `SEED\t<value>` line for a brief window (`data-saving.md` §6.4); captures it if present, proceeds either way.
6. Sidecar enters strobe-parsing mode: unlike `PASSTHROUGH`'s opaque-text handling (`hardware-interaction.md` §6.2), `IN_SESSION` parsing expects lines matching `^\d{1,3}\t\d+$` as `[code, timestamp]` strobe pairs; anything else is logged but not treated as data.
7. Each parsed strobe both (a) appends to `data-saving.md` §7's in-memory buffer/checkpoint path, and (b) — if its code matches a `liveMetrics` `triggerCode`/`successCode`/`alternateCode` in that sketch's Task Profile — updates the rolling metric pushed to the frontend (§9's telemetry event).

**Exit** (clean): `STOP` sent → board finishes its current trial boundary → emits `BF_END_SESSION` (or whatever the sketch's own end-of-session code is, per its Task Profile's `strobes` map) → sidecar finalizes the file (`data-saving.md` §7) → port transitions `IN_SESSION → IDLE`.

**Exit** (board drop mid-session): **always a hard stop, no auto-recovery attempt.** Reuses `hardware-interaction.md`'s existing machinery rather than inventing new recovery logic — a dropped board during `IN_SESSION` is exactly the failure case that state machine's `ERROR` state already exists for (§3.1: "Port failed to open, board disconnected unexpectedly"), so the port transitions `IN_SESSION → ERROR` the same as any other unexpected failure, and clears via the existing manual `port.error.ack` (§3.2) — the operator acknowledges, then can press Start again on that box to begin a fresh run if they want to resume that animal. The file is finalized immediately at drop, `stop_reason: "board disconnected"` (§8), using whatever was durably captured in `data-saving.md` §7's `.tsv` write-ahead log up to that exact moment — the hard-stop policy costs nothing in data, since real-time durability was already the point of that design.

---

## 8. `stop_reason` Values

An open, extensible set rather than a fixed enum — but a baseline for v1:

| Value | Trigger |
|---|---|
| `"BF_END_SESSION received"` | Clean firmware-reported end (board hit its own trial cap, or honored a `STOP`) — literal string as observed, per `data-saving.md` §5's table |
| `"operator stop"` | The user pressed Stop/End Session and the board hadn't already self-ended |
| `"board disconnected"` | Port dropped mid-`IN_SESSION` (§7's open exit-handling question) |
| `"sidecar error"` | An unhandled failure on the sidecar side while parsing/writing |

---

## 9. Wire Messages (merged)

**Merged into `websocket-protocol.md` §3.2/§4** — that file is canonical; the tables below are kept for rationale only.

Two commands were added during implementation that this section didn't anticipate, both documented in full there:

- **`sessions.suggestNumber`** `{prefixId}` → `{suggestion, sameDayNumbers}` — §2.2 asks for a pre-filled next number *and* a soft same-day warning, and neither had a message. One round trip serves both.
- **`sessions.status`** `{sessionId}` → `{session, groupId, boxes}` — Mission Control had no way to learn its own mapping. Asking the runner (the authority on what is actually configured and running) beats carrying it in router state, where reopening the window would lose it.

**Commands:**

| Command | Args | Result |
|---|---|---|
| `sessions.create` | `{cohortId, prefixId, sessionNumber}` | `{session}` — status `configuring` |
| `sessions.confirmMapping` | `{sessionId, groupId, boxes: [{box, animalId, sketchPath, config}]}` | `{ok: true}` — feeds §4's flash sequence |
| `sessions.startAll` | `{sessionId}` | `{state}` |
| `sessions.switchGroup` | `{sessionId}` | `{nextGroupId}` — triggers re-entry to Step 2 |
| `sessions.end` | `{sessionId}` | `{session}` — status `completed` |
| `port.startSession` | `{box, startCommand}` | `{state}` | Per-box `IN_SESSION` entry, §7 |
| `port.stopSession` | `{box}` | `{state}` | Sends `STOP`, doesn't force the transition — the board's own end-of-session strobe does that |

**Events:**

| Event | `data` | Notes |
|---|---|---|
| `session.telemetry` | `{box, animalId, metrics: [{id, value, n}]}` | Pushed on every strobe that updates a rolling metric (§7 step 7), not batched at `port.output`'s 20Hz — metric updates are much lower-frequency than raw strobes |
| `session.animalEnded` | `{box, animalId, stopReason, filePath}` | |

**Amendment to an existing command** (§4), also merged: `port.flash` gains `suppressPassthroughResume: bool` (default `false`). This is what leaves a freshly-flashed box in `IDLE` so the runner can claim it, instead of Debug Mode's auto-resume into `PASSTHROUGH`.

All of the above now live in `websocket-protocol.md`, same convention as `cohorts.md` §10 and `data-saving.md` §9.

---

## 10. Resolved Decisions

| Decision | Outcome |
|---|---|
| Session-local mapping edits (§3) | **Session-local only, no save-to-cohort option.** Permanent changes go through Cohort management instead |
| Board drop mid-`IN_SESSION` (§7) | **Always a hard stop.** Reuses `hardware-interaction.md`'s existing `ERROR` state and manual `port.error.ack` rather than new recovery logic — also resolves that doc's own §8 TBD on this question |
| Flash failure mid-sequence (§4) | **Halt.** The sequence stops at the failed box, marks its star failed, and surfaces the error; boxes already flashed keep their firmware. The simplest of the three options, chosen deliberately — skip-and-continue would leave the operator to notice a silently-absent box |
| Per-box controls vs. an inert star (§5.3 / §6.2) | **The card grid stays, below the constellation.** §6.2 makes an unlit star non-interactive by design, so a box that hasn't started yet would have no reachable Start if the constellation were the only surface. §6.4's "reachable from here too" reads the same way |
| Camera motion (§6.3) | Cubic ease-out, 1.5 s, approach along the current view direction, aimed slightly past the star so it lands clear of the docked panel |

**§6.3's arrival visual is now built** and is the version described here: three thin concentric rings expanding outward with staggered cubic easing, settling into a slow rotation, in `Pulsar`/`Halo` with no glow. Deliberately the simplest reading of the proposal, so there's something concrete to react to — still open to revision, which is exactly what this line always meant.

---

## 11. Open Items / TBD

- [x] ~~Merge §9's proposed commands/events into `websocket-protocol.md`, including the `port.flash` amendment~~ — **done**, plus the two commands §9 now lists as added during implementation
- [x] ~~Multi-box flash sequencing failure handling~~ — resolved in §10: **halt at the failed box.** Note this answers only the *session* flash sequence; `hardware-interaction.md` §8's general "flash all 6" batching question is still open for Debug Mode
- [x] ~~Exact camera-motion parameters (easing curve, duration) for §6.3~~ — cubic ease-out over 1.5 s, recorded in §10
- [x] ~~Whether `SessionAnimalRun` should be written incrementally or only at finalization~~ — **finalization only** (`data-saving.md` §10). Incremental writes only pay off for crash resumption, which is deliberately out of scope
- [ ] **Switch Group's second lap is untested end to end.** The group-run bookkeeping that makes it advance rather than cycle is verified (the first group is recorded and skipped), but a full two-group session — switch, re-map, re-flash, run, end — hasn't been driven on hardware
- [ ] Session resumption after an app or sidecar restart remains unsupported and unbuilt, by decision rather than omission. Mission Control recovers a *reload* fine via `sessions.status`, because the sidecar kept running; if the sidecar dies, the run is over and the `.tsv` is the record

# Starting a Session

> **Status** · Living spec — **Built and verified end to end** against a real Mega running firmware that speaks §7's protocol. The full path from the dashboard CTA through configuration, mapping, flashing, `IN_SESSION`, Mission Control, and the 3D constellation is live.
>
> **Owns** · Everything between the "Start a Session" button and a running box: the two setup steps, the flash sequence, `IN_SESSION` entry and exit, and Mission Control.
>
> **Read with** · [data-saving.md](data-saving.md) (what the run writes — these two were written together and should be read together) · [cohorts.md](cohorts.md) (the model this runs against) · [hardware-interaction.md](hardware-interaction.md) (the state machine `IN_SESSION` lives in)
>
> **Still open** · Switch Group's second lap is untested on hardware · session resumption is out of scope by decision

**Contents** — [1. "Ready to Run"](#1-ready-to-run--resolving-cohortsmd-12) · [2. Step 1 — Configuration](#2-step-1--configuration-menu) · [3. Step 2 — Mapping](#3-step-2--animal--box-mapping-confirmation) · [4. Step 2b — Flashing](#4-step-2b--flashing-sequence) · [5. Mission Control](#5-mission-control--overview) · [6. The 3D Constellation](#6-the-3d-constellation) · [7. `IN_SESSION`](#7-in_session--resolving-the-hardware-layer-tbd) · [8. `stop_reason`](#8-stop_reason-values) · [9. Wire Messages](#9-wire-messages-merged) · [10. Resolved Decisions](#10-resolved-decisions) · [11. Open Items](#11-open-items--tbd)

**The flow at a glance:**

```
Dashboard  /                  hero CTA + session dock (the retired /launch's content):
   │                          start fresh, resume the running session, end it,
   │                          or resume/discard a set-up left mid-flow
   ▼
Step 1  /session/new          cohort · prefix · session number
   │
   ▼
Step 2  /session/:id/mapping  animal→box · sketch · per-box task config
   │                          then: sequential flash, halting on first failure
   ▼
        /session/:id/control  Mission Control + 3D constellation
   │                          Start All · Switch Group ⤴ (back to Step 2) · End Session
   ▼
        /analytics            session-end landing
```

This document also resolves three long-standing TBD items: `hardware-interaction.md`'s stubbed `IN_SESSION` state, `websocket-protocol.md` §9's session-runner messages, and `cohorts.md` §12's "what does 'ready to run' mean."

---

## 0. Scope

Defines the full path from the Dashboard (`/` — the hero CTA and the session dock beside it, which absorbed the retired `/launch` page, `ephymeris_v1.0.md` §3.2) to a running Mission Control dashboard: the configuration step, the animal→box mapping and flashing sequence, and the live session UI (3D constellation, per-box controls, the zoomed-in per-animal view). The session dock is also the way *back*: it renders `sessions.active`'s answer — the running session with an Open Mission Control action, set-ups still in `configuring` with Resume-setup/Discard, and crash-orphaned `stale` rows shown read-only (View in Analytics / Close out — never Resume, per §11). Consumes `data-saving.md`'s Task Profiles and file schema; doesn't redefine them.

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

### 2.4 Time Limit

An optional **minutes** field. Empty means no limit — the session runs until the operator or the board ends it, exactly as before the field existed.

When set, it is a **per-box** limit measured from **each box's own start**, not from Start All: boxes are started individually (a box can be restarted mid-group, a straggler started late), and the point of a time limit is that every *animal* runs for the same duration. The value is stored on the `Session` record (`durationMinutes`, `data-saving.md` §4), so every group in a multi-group session runs under the same limit and a reloaded window still knows it.

Enforcement is sidecar-side, never client-side: the runner schedules an auto-`STOP` per box at start (§5.4). A closed or crashed frontend changes nothing about when boxes stop.

---

## 3. Step 2 — Animal → Box Mapping Confirmation

A per-box card grid — visually similar in spirit to Debug Mode's 6-box layout (`hardware-interaction.md` §6.6), but purpose-built: this is a confirm-and-configure step, not a console.

Each card shows the box number, the animal assigned to it (name, sex, icon treatment consistent with `cohorts.md`'s theme), and:

- **Sketch selector** — the categorized picker from `arduino-directory.md` §5, scoped to this one box.
- **Task config sub-form** — appears once a sketch is chosen, *only if that sketch has a Task Profile* (`data-saving.md` §6). Fields, labels, and defaults come straight from the profile's `config` array. A sketch with no profile shows no sub-form — bare `START` at flash/run time.

Configured **per box, independently** — two boxes running the same sketch don't have to share config values, matching the real sample data (`correction_left`/`correction_right` are per-animal, and a lab plausibly tunes these differently per rat).

The user can adjust the standing `boxNumber` mapping here too (it's a confirmation step, not just a readout) — changes here are **session-local only**. They never write back to the cohort's stored mapping; permanent changes go through Cohort management (`cohorts.md` §6) instead. Keeps this step's purpose singular — confirm and configure *this run* — rather than doubling as an editor for stored cohort data.

### 3.5 The guided placement walk

Confirming the mapping doesn't flash anything yet. It starts a **walk of the rig**: one animal at a time, in **box-number order**, with the app pointing at exactly one card and — where the hardware allows — lighting that box until the operator says the enclosure is closed.

Three decisions inside that are worth keeping:

- **Box order, not animal order.** The operator is walking down a bench. Sending them from box 5 to box 2 and back is how an animal ends up in the wrong chamber, which is the single failure this whole step exists to prevent: a mis-placed animal produces a complete, plausible, silently mislabelled data file, and nothing downstream can detect it.
- **The mapping locks while the walk runs.** Every card but the current one dims and stops accepting clicks. Changing a box number after animals are already in chambers would invalidate the placements behind it without saying so.
- **The lights are a confirmation, not the instruction.** The box's own number is on the card and on the chamber; the light is the app corroborating it. So a rig with no utility sketch configured, a box still being restored, or a board that didn't answer all get the same walk with a line explaining to go by the number. Refusing to continue because a bulb didn't light would be worse than the problem.

The lighting itself is `utility.identify` (`hardware-interaction.md` §8.3), which is why this step sits **before** the flash sequence: the boxes are still carrying the utility sketch here, and that is the only firmware that can be asked to light one. After the last animal, the step becomes Confirm-and-flash (§4), and confirming the mapping is what puts the baseline on hold and extinguishes any remaining light.

**Leaving the step:** what "back" means depends on whether the session has run yet. On first entry (session still `configuring`), Back returns to Step 1 and abandons the session record via `sessions.abandon` — the record is marked `aborted` rather than left stranded in `configuring`, and Step 1 creates a fresh session on the next Continue. On re-entry via Switch Group the session already holds recorded group runs, so Back would be a lie — the step instead offers **End session** (`sessions.end`), landing on Analytics like any other session end.

---

## 4. Step 2b — Flashing Sequence

Once the user confirms, each box's sketch is flashed **in sequence**, not in parallel — reuses `port.flash` (`hardware-interaction.md` §4) exactly, one box after another.

**Animated, on-theme progress indicator:** each box's card icon transitions through the same states its Debug Mode badge would (`hardware-interaction.md` §3.4), but rendered here as part of the star motif already established — a box mid-flash shows its star "flaring" (brief animated pulse) rather than a generic spinner, so the visual language stays consistent with the rest of the app rather than switching to a plain loading indicator for this one step.

**Recovering from a failed flash, in place.** A failed flash leaves its box in `ERROR` (`hardware-interaction.md` §3), and `ERROR → FLASHING` is refused — so a retry is rejected until the fault is acknowledged. The acknowledgement therefore lives on the card that is stuck: a box in `ERROR` shows its reason and an **Acknowledge** button (`port.error.ack`, the same command Debug Mode's panel sends), and Confirm-and-flash stays disabled while any mapped box is faulted, since the sequence would only halt on it again. Without this, the step most likely to *produce* a flash failure — a bad sketch is discovered here, not in Debug Mode — was the one place it couldn't be cleared. A fault inherited from before a reload carries only the replay placeholder reason (`websocket-protocol.md` §1.2's `"initial state"`), so the card states plainly that the box is in an error state rather than repeating a word that explains nothing.

> **The protocol wrinkle this flow forced.** `hardware-interaction.md` §3.3 normally auto-resumes `PASSTHROUGH` after a successful flash if that was the pre-flash state. This flow needs the opposite — every box must land in `IDLE` afterward so the session runner can claim it, since `IN_SESSION` can only be entered from `IDLE`. So `port.flash` carries a `suppressPassthroughResume: bool` argument, default `false` to preserve Debug Mode's behaviour; this flow sets it `true`. **Built and merged into `websocket-protocol.md` §3.**

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

### 5.4 Per-Box Run Clocks & the Time-Limit Auto-Stop

Each live box's card shows an elapsed clock — `m:ss` since *that box's* start, shown as `elapsed / limit` when the session carries a time limit (§2.4). The clock is driven by the runner's per-box `startedAt` (carried in `sessions.status`'s `boxes`), never by a client-side stopwatch, so a reloaded window resumes mid-count instead of restarting from zero.

At the deadline the **sidecar** sends the same `STOP` an operator's press would — the auto-stop is exactly §5.3's Stop with a scheduler behind it. Everything downstream is unchanged: the board finishes its trial, emits its end strobe, and the run finalizes through the normal path with the normal `stop_reason` (§8) — the time limit decides *when* the request is sent, not *how* the run ends. Once time is up the card's clock stops counting and reads "time up — stopping at the next trial boundary", because that is the true state: the request is in, and the board owns the timing of the end. A box that ends early (its own end strobe, an operator stop, a board drop) cancels its scheduled auto-stop — a freed port must never receive a ghost `STOP`.

A sketch with no Task Profile declares no end strobe, so `STOP` alone cannot finalize it (§7) — for those, the time limit sends the request but the operator still closes the run out, same as a manual stop today.

### 5.5 The Group-Swap Prompt

When every box in the current group has finalized **and** another populated group is waiting, Mission Control prompts with the placement scene played backwards (§3's `RatPlacementBanner`, `mode="return"`): the handler lifts the animal back out of the chamber and carries it home to its cage — literally the operator's next physical act — with a **Switch Group** button beneath it. Same scenery, same performers, mirrored choreography; the arrival flourish is omitted because leaving celebrates nothing.

The prompt appears whether the group ended by time limit, by operator stop, or by every board's own end strobe — "everyone is done and more animals are waiting" is the trigger, not how it came to be true. On the last group no swap is offered; the journey rail's existing End Session guidance stands.

---

## 6. The 3D Constellation

The centerpiece view. Per-cohort, orbitable, built with `three.js`/`react-three-fiber` (no constraint here from any sandboxed widget environment — this is the real app, full npm access).

### 6.1 Star Identity and Placement

**The scene is the rig's own asterism.** Whichever zodiac constellation Box Setup chose, and whichever star each box was slotted onto (`ephymeris_v1.0.md` §4.6), is what this view draws — lifted out of the 2D widget's 100×54 authoring frame into world space. It reads the *same* `box → star` slot map as the sidebar status widget and the Debug Mode landing, through the same `layoutFor`, so the three cannot disagree about which box owns which star. An animal stands on the star of the box it is running in.

This makes a star **the box, not the animal**, which is a deliberate reversal of this section's original rule. An animal's position therefore moves when it is mapped to a different box, and two animals that run in box 1 on different days share a star. That is the point: the arrangement mirrors the rig rather than the roster, so an operator who has learned their rig's shape reads the session view with the same glance they read the sidebar with.

Three consequences worth stating:

- **Unoccupied stars of the asterism are still drawn**, faint and inert, in `Halo`. Without them a two-box rig would render as two dots and a line, and the constellation the user deliberately picked would be invisible in the one view that is mostly constellation.
- **Links are the catalogue's own edges**, not nearest-neighbour. The traditional stick figure is what makes Scorpius read as the fishhook; nearest-neighbour would draw a different shape from the same stars. (The 2D cohort icon still uses nearest-neighbour — it has no asterism to be faithful to.) Same thin-`Pulsar`-line treatment as the icon and the status widget, so all three stay one visual family.
- **Scaling is uniform**, and the figure is sized to fit inside the overview camera's frame with margin. A per-axis fit would stretch the tail and turn the Teapot into a bowl; a figure you have to orbit before you recognize it is not mirroring anything. Depth is a small seeded jitter per star — enough that orbiting reveals a sky rather than a poster, small enough that near stars don't occlude the shape.

**Animals with no star** — no box mapped in the running group, or a box Box Setup never bound — keep the original seeded placement, pushed onto a wider shell *outside* the asterism. §6.2 requires every animal in the cohort to be present; putting them in the figure they are not part of would misreport the rig.

**The seeded fallback remains** for an install that never ran Box Setup (`settings.constellation` is null). There, each star's position is seeded from `(cohortId, animalId)` together — not just the cohort id, which is all `cohorts.md` §5's 2D icon needed — so an animal added later doesn't reshuffle everyone else's star.

### 6.2 General (Orbit) View

Camera starts pulled back, the full constellation visible. **Orbit** is left-drag, **pan** is right-drag or two-finger drag, **zoom** is the wheel — standard `OrbitControls` bindings, panning in the *screen* plane rather than a ground plane, since a sky has no floor.

> **Shared with Debug Mode.** The camera, the controls, the hover reticle, the nameplates, the arrival flight and the docked-panel offset all live in `components/constellation3d/Scene.tsx`, which `ephymeris_v1.0.md` §4.3's box browser renders too. The two views are deliberately the same instrument pointed at different things — a cohort's animals here, the rig's boxes there. What each supplies for itself is the **body** of a star, because colour means different things in the two: rolling accuracy here, box health there. That is the one thing the shared module refuses to own.

**The deep sky** (`components/constellation3d/Backdrop.tsx`, also shared). Behind the asterism: a field of ~700 twinkling stars — one seeded `Points` draw, per-star phase, rate and a palette-family tint, the only per-frame cost a time uniform — a handful of nebula banks (procedurally painted canvas textures in deep violet/green/dusk cousins of the palette, hung further out than the star shell, drifting slowly against each other), and every half-minute or so a supernova: a fast flash that decays over a few seconds while a thin shell ring expands through it. Three rules keep it scenery rather than spectacle:

- **Deterministic.** Every position, hue, phase and flare site is seeded through the same `mulberry32` the 2D starfield and the cohort icons use — the same sky on every mount and every machine.
- **Behind the data.** The whole field lives outside the camera's zoom range with depth-writing off, so scenery never occludes a star an operator is reading; the banks are kept faint enough that one drifting behind a foreground star never reads as a halo on it.
- **Reduced motion stills it.** The twinkle freezes at its seeded phase, the banks stop drifting, supernovae never happen. The field stays; the theatre goes.

**No tile.** The canvas is transparent and fades out over its last few dozen pixels on every side (two intersected linear-gradient masks — a radial one would hollow the corners of a wide frame), and the routes draw no border or rounding around it. The scene composites straight over the app's `Void` background and the chrome's own drifting 2D starfield, so the browser reads as a window onto the app's sky rather than a framed widget sitting on the page. The nameplates portal into the same masked wrapper, so a plate dissolves at the frame edge along with the scene it annotates.

Panning also has on-screen controls: a four-arrow pad with a recentre button, docked bottom-left, plus a one-line legend naming the three gestures. The bindings alone are not enough — this app is run by lab members who use it infrequently, and right-drag-to-pan is not something an infrequent user discovers. Each arrow moves a fixed fraction of the visible frame (so one press covers the same apparent distance at any zoom) and repeats while held; camera and orbit target move together, so panning slides the view instead of swinging the constellation around a displaced pivot. A press **supersedes an in-progress camera flight** rather than being ignored until it lands: the operator asking to move means now, and a flight only advances while frames are being delivered, so a window left in the background would otherwise wedge the controls until it was focused again. The pad is hidden while a star is focused — the controls are disabled during arrival anyway, and §6.4's panel owns the frame at that point.

Stars for animals currently `IN_SESSION` are **illuminated**; everyone else in the constellation is present but dim/unlit — including animals in a group that isn't running right now (§5.2), and animals with no box assigned at all. Only illuminated stars are interactive (hover reticle, nameplate, clickable) — an unlit star has no live view to show, and gets neither treatment.

**A lit star's colour is its temperature, and its temperature is that animal's pooled rolling accuracy** (`components/constellation3d/starSurface.ts` + `StellarSurface.tsx`, shared with Debug's rig view since 2026-07-29 — `ephymeris_v1.0.md` §4.3). It renders as an actual stellar surface — granulated convection cells from a noise fBm, limb darkening so the disc reads as a sphere, and a rim-only chromosphere — climbing the real stellar sequence as the animal works:

| Pooled rolling accuracy | Reads as | Class |
|---|---|---|
| ≤ chance (0.5) | deep red | M |
| ~0.6 | orange | K |
| ~0.7 | yellow, sun-like | G |
| ~0.85 | white | F/A |
| → 1.0 | blue-white | B |

Three decisions worth not relitigating:

- **Pooled, not per-condition.** A single-condition figure cannot tell learning from a side bias — an animal that always pokes right scores ~1.0 on the go-right odor and ~0.0 on the other, and either alone tells a story the data doesn't support. Pooled, that animal sits at chance, which is the truth (`analytics.md` §3.7).
- **Chance is the floor, not zero.** Below chance an animal isn't "colder", it's doing something other than the task; stretching the ramp to zero would spend half the visible range on a distinction nobody reads. An animal that has scored nothing yet shows at the cool end rather than warm, because it hasn't demonstrated anything.
- **This is a deliberate, bounded exception to §2.2's flat-matte rule** (`ephymeris_v1.0.md`). It buys real information — the overview answers "who is working" without opening a panel — and it is confined to this 3D scene. An *unlit* star stays a flat matte dot: it has no performance to report, and giving it a surface would imply it were running. Nothing in the 2D chrome gains a gradient or a glow.

The colour eases toward its target rather than snapping, so a run of good trials warms a star visibly instead of flickering between classes trial by trial. Reduced motion stills the granulation; the temperature still reads.

**Hover** swells a lit star and draws a billboarded targeting reticle — four short `Pulsar` arcs at the quadrants that sweep inward as they appear, the way an instrument marks the thing it is tracking. Both the swell and the reticle are eased with a frame-rate-independent approach rather than snapped: the pointer crosses a hit sphere four times the star's radius, so an instant jump would fire often and read as a glitch. The reticle is deliberately *not* another concentric ring — §6.3's arrival already owns that idiom, and two ring treatments moments apart read as one confused animation. Billboarding is what keeps it facing the camera from any orbit angle, which a ring fixed in the XY plane does not.

**Every lit star carries a persistent nameplate**: box number and animal name on a small matte plate, hung under the star on a short leader. Persistent rather than hover-only, because "which star is which" is a question the overview should never make you hover to answer — but only for *lit* stars, since a plate on every animal in the cohort would bury the running ones. It is DOM rather than in-scene text, so it stays crisp and uses the app's own type (JetBrains Mono — an animal name is an identifier, `ephymeris_v1.0.md` §2.3), and it carries **no `distanceFactor`**: a plate that scaled with camera distance would be enormous on arrival at a star. Constant screen size is also what makes it read as a HUD annotation rather than an object floating in the scene. The plate never takes the pointer, so the star's hit sphere behind it stays clickable; hovering the star brightens its plate's border and leader to `Pulsar`.

**Every occupied star carries its animal in orbit** (`components/constellation3d/Orbiters.tsx`, shared with Debug). A small matte octahedron — angular on purpose, a made thing next to the round star — circles the box's star for each animal assigned to it, carrying a mini mono name tag and a periodic double-flash strobe, the way you'd know a satellite was up there at all. Inclination, bearing, orbit speed and blink phase are all seeded from the animal's id, so no two satellites move alike and a full rig never blinks in sync. The motion follows the app's grammar: a *running* animal's satellite orbits and strobes; an assigned-but-idle one parks at its seeded bearing with a steady faint light — "assigned here, not running". Zodiac mode only: there a star *is* the box (§6.1), so the satellite says who is assigned to it; in the seeded fallback the star is the animal itself, and a craft orbiting its own namesake would just repeat the nameplate. The tag is deliberately smaller and fainter than the star's plate — it labels an annotation, and must never outrank the thing it annotates. Satellites sit outside the hover swell on purpose: the swell announces the star under the pointer, and craft lurching outward with it would read as part of the star rather than the annotation they are.

### 6.3 Zoom-to-Star ("Arrival")

Clicking an illuminated star flies the camera to it — an eased cinematic move (cubic/exponential easing, a deliberate, acknowledged exception to the app's usual spring-physics motion convention; a camera flythrough reads as cinematic rather than mechanical, and springs would fight that). On arrival, a **sleek but still matte** treatment — proposed, not finalized, worth seeing built before committing further: thin concentric rings (in `Pulsar`/`Halo`) animate outward from the star and settle into a slowly rotating decorative ring around it — an instrument/HUD feel rather than a glow or gradient, keeping the theme's explicit "no glow effects" rule (`ephymeris_v1.0.md` §2.2) intact even at the app's single most visually ambitious moment.

The 3D scene **stays rendering in the background** once arrived — the data panel (§6.4) overlays it (translucent `Nebula`, vibrancy blur, docked to one side) rather than replacing it outright. "Arrival" means the camera is now close to that star; you're looking at it with an instrument panel open, not cutting to a different screen.

### 6.4 Zoomed-In Star View

- Animal name.
- Running sketch (name, and its category from `arduino-directory.md` if useful context).
- Start / Stop / Reset for that box (§5.3, same actions, just reachable from here too).
- **Rolling accuracy** — the pooled figure the star's temperature encodes (§6.2), stated as a number beside the trial count. A colour ramp nobody can read precisely still needs its value written somewhere.
- **Live panels** (`components/sessions/LivePanels.tsx`) — three charts, rebuilding what the lab's previous software showed per animal, in this app's own chart primitives (`components/charts/`) so they inherit its axis idiom and palette rather than becoming a second charting dialect:

  | Panel | Shows | Reads |
  |---|---|---|
  | **P(right \| odor)** | one rolling curve per odor the task presented, over a 20-trial window, against the 0.5 chance line | separation between the curves is discrimination; both near 0.5 is chance; both near the same extreme is a side bias |
  | **Outcome mix** | cumulative stacked proportions — earned / hold-fail / wrong well / abstained | how the session is going overall; the bands settle as trials accumulate |
  | **Well hold** | every well poke as a mark at its hold duration, filled where the hold was met and hollow where released early, coloured by side, against the inferred hold threshold | early releases cluster below the rule; a side that only ever appears hollow is a physical problem, not a learning one |

  All three are views of **one trial record** (`lib/sessions/liveTrials.ts`), so they cannot disagree about what happened. That record is derived by **strobe name, never by raw code** — `BehaviorBox.h` defines one shared `BF_*` vocabulary and every `task.json` mirrors it by name, so resolving `WATER_POKE_L` → whatever code *this* sketch assigned keeps the app free of per-sketch knowledge. A sketch declaring none of those names shows the console alone and says so.

  The hold threshold is **inferred, not declared**: a held trial fires its fluid strobe the instant the hold is satisfied, so the shortest held duration *is* the threshold. Nothing is drawn until at least one trial has been held, because a reference line that later moves is worse than none.

- **Console** — the five-row strobe feed, now **collapsed by default**. It is how you check the box is still talking, which matters exactly when something looks wrong and is noise the rest of the time; the panels above are what a run is actually watched for. Newest first: code chip, the profile's decoded strobe name (`data-saving.md` §6.4; a profile-less sketch shows `Strobe <code>`), and the board-side timestamp.

> **Where the trial record comes from.** The session store keeps its own decoded strobe log per box, separate from `HardwareStore`'s console ring. That ring is capped at ~2000 lines and trimmed oldest-first — correct for scrollback, wrong here: a real session emits several thousand strobes (2,711 in the reference archive run), so deriving from it would silently drop the early trials, which is exactly the part of a learning curve you want. The log holds decoded `{code, at}` pairs, is capped an order of magnitude higher, and is folded incrementally so a long session stays cheap.
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
3. Sidecar waits for the board's `READY` line. **If it never arrives within 10 seconds, the box drops to `ERROR`** with "board never reported READY" — a board that isn't speaking the protocol fails loudly rather than hanging the operator.
4. Sidecar sends the built `START ...` command (`data-saving.md` §6.3).
5. Sidecar watches for an optional `SEED\t<value>` line for a **1.5-second** window (`data-saving.md` §6.4); captures it if present, proceeds either way. A strobe arriving before the window closes also ends it — a board that goes straight to work isn't penalised with a wait.
6. Sidecar enters strobe-parsing mode: unlike `PASSTHROUGH`'s opaque-text handling (`hardware-interaction.md` §6.2), `IN_SESSION` parsing expects lines matching `^\d{1,3}\t\d+$` as `[code, timestamp]` strobe pairs; anything else is logged to scrollback but never treated as data.
7. Each parsed strobe both (a) appends to that animal's `.tsv` write-ahead log (`data-saving.md` §7) and its in-memory buffer, and (b) — if its code matches a `liveMetrics` `triggerCode`/`successCode`/`alternateCode` in that sketch's Task Profile — updates the rolling metric pushed to the frontend as `session.telemetry`.

**Exit** (clean): `STOP` sent → board finishes its current trial boundary → emits its end-of-session strobe → sidecar finalizes the file (`data-saving.md` §7) → port transitions `IN_SESSION → IDLE`, with `stop_reason: "BF_END_SESSION received"`.

> **How the end-of-session strobe is identified.** Not by a fixed code — the sidecar scans the Task Profile's `strobes` map for the **first entry whose name contains `END_SESSION`** and watches for that code. A sketch that names its terminal strobe something else entirely, or ships no profile at all, therefore has no end code, and its run ends only when the operator stops it or the board drops. Worth knowing before writing a new task's `task.json`.

`STOP` is a nudge, not a command with authority: it is written to the port, and nothing else. It does not force a state transition. Only the board's own end strobe does that — or, when the operator ends the whole session, a forced finalization a beat later for any box that didn't answer.

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
| Board drop mid-`IN_SESSION` (§7) | **Always a hard stop.** Reuses `hardware-interaction.md`'s existing `ERROR` state and manual `port.error.ack` rather than new recovery logic — also resolves that doc's own §9 TBD on this question |
| Flash failure mid-sequence (§4) | **Halt.** The sequence stops at the failed box, marks its star failed, and surfaces the error; boxes already flashed keep their firmware. The simplest of the three options, chosen deliberately — skip-and-continue would leave the operator to notice a silently-absent box |
| Per-box controls vs. an inert star (§5.3 / §6.2) | **The card grid stays, below the constellation.** §6.2 makes an unlit star non-interactive by design, so a box that hasn't started yet would have no reachable Start if the constellation were the only surface. §6.4's "reachable from here too" reads the same way |
| Camera motion (§6.3) | Cubic ease-out, 1.5 s, approach along the current view direction, aimed slightly past the star so it lands clear of the docked panel |
| The deep-sky backdrop (§6.2) | **Seeded scenery, never data.** Twinkle field, nebula banks, and supernovae are all deterministic (`mulberry32`), live outside the camera's zoom range with depth-writing off, and hold still under reduced motion. The canvas is transparent with edge-fade masks and the routes drop the tile border — the scene joins the app background rather than sitting in a frame |
| Animal satellites (§6.2) | **One per assigned animal, zodiac mode only.** Mission Control feeds them from the current group's mapping, Debug from the running session; running = orbiting + strobing, assigned-but-idle = parked with a steady light. Debug's anonymous mote stands down while a named satellite is up |

**§6.3's arrival visual is now built** and is the version described here: three thin concentric rings expanding outward with staggered cubic easing, settling into a slow rotation, in `Pulsar`/`Halo` with no glow. Deliberately the simplest reading of the proposal, so there's something concrete to react to — still open to revision, which is exactly what this line always meant.

---

## 11. Open Items / TBD

- [x] ~~Merge §9's proposed commands/events into `websocket-protocol.md`, including the `port.flash` amendment~~ — **done**, plus the two commands §9 now lists as added during implementation
- [x] ~~Multi-box flash sequencing failure handling~~ — resolved in §10: **halt at the failed box.** Note this answers only the *session* flash sequence; `hardware-interaction.md` §9's general "flash all 6" batching question is still open for Debug Mode
- [x] ~~Exact camera-motion parameters (easing curve, duration) for §6.3~~ — cubic ease-out over 1.5 s, recorded in §10
- [x] ~~Whether `SessionAnimalRun` should be written incrementally or only at finalization~~ — **finalization only** (`data-saving.md` §10). Incremental writes only pay off for crash resumption, which is deliberately out of scope
- [ ] **Switch Group's second lap is untested end to end.** The group-run bookkeeping that makes it advance rather than cycle is verified (the first group is recorded and skipped), but a full two-group session — switch, re-map, re-flash, run, end — hasn't been driven on hardware
- [ ] Session resumption after an app or sidecar restart remains unsupported and unbuilt, by decision rather than omission. Mission Control recovers a *reload* fine via `sessions.status`, because the sidecar kept running; if the sidecar dies, the run is over and the `.tsv` is the record. The Dashboard's session dock now *surfaces* such crash-orphaned rows (`sessions.active`'s `stale` list) with View-in-Analytics and Close-out actions — visibility changed, the no-resumption decision did not
- [x] ~~**`MetricChart.tsx` is built but unwired** (§6.4)~~ — **closed.** The zoomed view now has real live panels (§6.4), built on the shared `components/charts/` primitives; `MetricChart.tsx` is deleted rather than wired, since `UnitChart` had already generalised its idiom

---

**Next:** [data-saving.md](data-saving.md) — what this run actually writes to disk.
[Documentation index](README.md) · [Open items register](TODO.md)

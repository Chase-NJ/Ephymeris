# Tech Stack & Dashboard Design

> **Status** · Living spec — **Built.** Dashboard shell, the full theme, Cohorts, Debug Mode, Settings, and the session flow are all wired end to end. Analytics is built to its own spec.
>
> **Owns** · Tech stack, app identity, theme tokens, dashboard information architecture, and Settings ownership.
>
> **Read with** · [hardware-interaction.md](hardware-interaction.md) (the serial layer) · [cohorts.md](cohorts.md) (the Cohorts tab) · [websocket-protocol.md](websocket-protocol.md) (the wire schema) · [arduino-directory.md](arduino-directory.md) (sketch discovery)
>
> **Still open** · the full Settings schema · app icon design · Windows packaging

**Contents** — [0. Tech Stack](#0-tech-stack) · [1. App Identity](#1-app-identity) · [2. Theme](#2-theme-astronomy--linux) · [3. Dashboard IA](#3-dashboard--landing-window--information-architecture) · [4. Section Wiring](#4-section-by-section-breakdown--wiring) · [5. Resolved Decisions](#5-resolved-decisions) · [6. Open Items](#6-open-items--tbd)

---

## 0. Tech Stack

| Layer | Choice |
|---|---|
| **Shell / desktop runtime** | Tauri 2 (Rust) |
| **Frontend** | React 19 + TypeScript, Vite, Tailwind v4, Framer Motion |
| **3D** | `three` + `@react-three/fiber` + `@react-three/drei` |
| **Backend** | Python sidecar process — owns all serial I/O, `arduino-cli` interaction, storage, and analytics |
| **Frontend ↔ sidecar** | Local WebSocket — see [websocket-protocol.md](websocket-protocol.md) |
| **Target platforms** | Developed on macOS (Apple Silicon); shipped and run on Windows 11 (both lab machines) |

Tailwind v4 is wired through `@tailwindcss/vite` with **no `tailwind.config.js`** — the design tokens in §2 are declared as an `@theme` block in `src/styles/index.css`, which is therefore the one file that decides what the palette, type scale, and radius scale actually are.

*(Same stack as `hardware-interaction.md` §0 — restated here since this doc stands alone as the UI/theme reference.)*

---

## 1. App Identity

App name: **Ephymeris** — a deliberate misspelling of "ephemeris" (the astronomical table of a celestial object's positions over time), punning on "ephys" (electrophysiology). Fits both halves of the theme directly: it's a real astronomy term, and it nods at the neuroscience-adjacent research context the app is built for.

---

## 2. Theme: Astronomy & Linux

### 2.1 Design Thesis

The app is, functionally, a mission-control console: six independent instruments (behavior boxes) that need to be monitored, commanded, and trusted at a glance, often during a live, time-sensitive session. That's the observatory/mission-control half of the theme. The Linux half shows up as texture, not costume — monospace data readouts, terminal-inflected debug tooling, unglossy surfaces — appropriate for a tool built by and for people comfortable in a terminal. Apple's influence is procedural: clarity, restraint, and material honesty (flat, matte, no false skeuomorphism) rather than literal macOS chrome, since production machines are Windows.

### 2.2 Color Palette

Dark mode is the default and, for v1, the only mode — light mode is out of scope entirely, including as a placeholder toggle in Settings.

| Token | Hex | Usage |
|---|---|---|
| **Void** | `#0B0B10` | Base app background — near-black, faint cool/purple undertone |
| **Nebula** | `#16151F` | Elevated surfaces: cards, sidebar, panels |
| **Halo** | `#2C2A3A` | Hairline borders, dividers, inactive/idle indicators |
| **Pulsar** | `#8B7EC8` | Primary accent — matte, desaturated purple. Primary buttons, active nav state, focus rings, links |
| **Ion** | `#7CC98F` | Secondary accent — muted terminal green. "Connected / nominal / success" status only, used sparingly |
| **Starlight** | `#EDEBF6` | Primary text |

A seventh value, **`Static` `#948FA8`**, carries secondary and muted text. It began as "not a full token, just a value used consistently enough to name," but it is now declared alongside the six in `src/styles/index.css` as `--color-static`. When this project says *the six-token palette*, it means the six above — the six that carry the theme's identity. `Static` is real, and it is deliberately not one of them: it is a text weight, not a colour decision.

> **The core stylistic bet — protect this one.** No gradients on the primary accent. No glossy highlights, no glow effects on `Pulsar`. Saturation stays low (~30–35%) so the purple reads as a *material*, not a light source. This is the thing to defend against scope-creep-by-gradient later.

**Semantic status colours** — derived, used only for state, never decorative. All three are declared in the same `@theme` block as `--color-status-*`:

| State | Token | Hex | Notes |
|---|---|---|---|
| Connected / Success | `--color-status-ok` | `#7CC98F` | The same value as `Ion`, named separately so status usage reads as status |
| Warning | `--color-status-warning` | `#D9A15C` | Muted amber |
| Error | `--color-status-error` | `#C96C6C` | Muted red — matte, not alarm-red |

**A structural property of the palette, worth knowing before adding to it:** Void, Nebula, Halo, Static and Starlight all sit at **OKLCH hue 285–295** — the entire neutral stack is tinted toward Pulsar's 291. That is why the app reads as one coherent thing rather than a dark theme with a purple accent bolted on, and it is the rule any new neutral should respect.

#### 2.2.1 Data-visualization ramps

Added for Analytics. **Neither ramp changes anything above** — Pulsar remains the primary accent, and the no-gradient, no-glow rule holds in full. `analytics.md` §7 carries the derivation and the measurements; this is the token list.

The six-token palette has no categorical ramp, which is correct for chrome and insufficient for data: six animals cannot be six colours, and Analytics cross-filters three linked panels where a reader must identify a mark without a legend lookup (`analytics.md` §2.1).

**Series ramp** — `--color-series-1` … `--color-series-6`, categorical, anchored on Pulsar:

| Token | Hex | OKLCH |
|---|---|---|
| `--color-series-1` | `#8B7EC8` | `oklch(0.635 0.110 291.0)` — Pulsar |
| `--color-series-2` | `#229582` | `oklch(0.604 0.102 178.6)` |
| `--color-series-3` | `#52B79D` | `oklch(0.713 0.103 173.8)` |
| `--color-series-4` | `#9E9FF6` | `oklch(0.737 0.125 282.0)` |
| `--color-series-5` | `#CBA23E` | `oklch(0.731 0.125 85.8)` |
| `--color-series-6` | `#BE7031` | `oklch(0.619 0.125 56.0)` |

Chroma stays ≤ 0.125 against Pulsar's 0.110, so the ramp reads matte. Hues avoid the error red and warning amber so a series is never mistaken for a state. Worst-case pairwise separation is ΔE ≈ 10 under normal, deuteranopic **and** protanopic vision.

> **Don't flatten the lightness spread.** The obvious improvement — six hues at identical lightness, for perfectly equal visual weight — was built and measured, and two of its pairs collapse to ΔE 0.9 under deuteranopia. Lightness is the only channel that survives dichromacy, so an iso-lightness categorical ramp is inherently colour-blind-hostile. The 5.2–8.2:1 contrast spread is the deliberate price. See `analytics.md` §7.1.

**Diverging ramp** — `--color-diverging-1` … `--color-diverging-7`, for the Analytics heatmap. Seven quantized bins centred on chance, so below-chance reads as a different *kind* of result rather than a smaller one. Quantized rather than continuous because a continuous ramp passes through a mid-lightness band where an in-cell label fails contrast against both Starlight and Void; every bin here clears WCAG AA. The top bin **is** Ion, and the centre bin sits just above Halo's lightness so chance reads as "nothing happening." Values in `analytics.md` §7.2.

### 2.3 Typography

Three roles, per the frontend-design convention of a characterful display face used with restraint, a neutral body face, and a utility/data face:

| Role | Face | Used for |
|---|---|---|
| **Display** | Space Grotesk | Dashboard title, section headers — geometric, slightly technical, and the name itself is a small on-theme wink |
| **Body / UI** | Inter | All interface text, buttons, labels. The closest widely-available cross-platform analog to SF Pro's neutrality and legibility at small sizes — genuine SF Pro is Apple-licensed and unavailable on Windows |
| **Mono / Data** | JetBrains Mono | Timestamps, COM port names, box/cohort IDs, hex values, and all Debug Mode console text — this is where the Linux/terminal identity actually lives |

Space Grotesk and Inter should not otherwise mix within the same block of text — Space Grotesk stays confined to headers so it doesn't dilute into "just another sans."

### 2.4 Layout & Materials

- **Radius scale:** `6 / 10 / 16 / 24px` (sm/md/lg/xl), applied consistently — no ad hoc radii.
- **Elevation:** subtle shadow + 1px `Halo` hairline border, not heavy drop shadows. Flat and matte fits the theme better than skeuomorphic depth.
- **Vibrancy (Apple nod):** sidebar and modal/dialog surfaces use a translucent `Nebula` tint with `backdrop-filter: blur(20px)` — frosted glass, used only on persistent chrome (sidebar) and transient overlays (modals), never on primary content cards. Confirmed compatible cross-platform: Tauri's webview is Chromium-based on both targets (WebView2 on Windows, WKWebView on macOS), both support `backdrop-filter`.
- **Squircle nod, used once:** the app's icon/wordmark mark uses a continuous-corner (squircle) shape via `clip-path`, echoing Apple's app-icon geometry. Not applied to buttons or cards generally — this is the one place it's spent.

### 2.5 Motion

- Framer Motion **spring physics** (not duration/easing curves) for nav selection, panel transitions, and modal open/close — the closest web equivalent to the springy feel of UIKit/SwiftUI transitions.
- Ambient motion is restrained and functional, not decorative filler: a slow (60s+ loop), very low-opacity drifting starfield sits behind dashboard content as groundwork for the signature element below. It must respect `prefers-reduced-motion` and pause when the window loses focus — this app is often watched during live data collection, so ambient effects can't compete for attention.
- **One acknowledged exception to the spring rule:** the 3D constellation's zoom-to-star camera move (`starting-a-session.md` §6.3) uses cubic easing, because a camera flythrough should read as cinematic rather than mechanical and a spring fights that. It is the only eased move in the app; everything else, including the panel that opens on arrival, stays on springs.

### 2.6 Iconography

Lucide (already available in this environment's component library) as the practical SF-Symbols analog: consistent stroke width across every icon, outline-only (no mixing filled and outlined icons).

### 2.7 Signature Element

The hardware status indicator — present in the sidebar per `hardware-interaction.md` §7's out-of-band polling — renders as a small **constellation map** instead of a plain row of status dots: nodes in a fixed abstract layout, thin `Pulsar` lines connecting adjacent nodes when both boxes are connected and nominal. A line dims or breaks on disconnect; a node turns `Error` red on fault. This is the one place the astronomy metaphor is spent deliberately — it's not decoration, it's the actual at-a-glance system-health readout, doing real work.

**Amendment (was: always six nodes).** Boxes are user-configured (§4.5), so the map shows **only boxes bound to a board** — the same rule that decides which boxes get a console panel in Debug Mode (§4.3). A rig running two boxes shows two nodes, not two nodes and four permanently grey ones implying four boards are missing. The caption reads `N/M boxes` against the configured count, or `no boxes configured` when empty. Consequences of the amendment:

- **Node positions stay pinned per box number** — box 4 always sits where box 4 sits. Positions are what make the map glanceable, so they must not reflow as health changes.
- **The frame reflows, not the layout.** The viewBox is fitted to a constant aspect so the sidebar never jumps; a small rig fills the space instead of huddling in a corner. Framing changes only on configuration acts, never mid-session.
- **Marks keep a constant apparent size.** Node radius and line width scale with the frame, so zooming spreads the *spacing* rather than inflating the dots; a one-box rig renders one normal dot, not one enormous one.
- **An edge is drawn only when both its endpoints are configured.** A sparse selection (say boxes 1 and 6) can therefore show unconnected nodes — honest, since there is no adjacency to report.

**Second amendment (zodiac layouts, §4.6).** The layout itself is now the user's choice: box setup lets them pick one of the twelve **zodiac constellations** as the map, with boxes occupying stars (`lib/constellations/zodiac.ts` holds the hand-authored asterisms; `settings.constellation` + `settings.constellationSlots` persist the choice). This refines the rules above rather than replacing them:

- **"Pinned per box number" becomes "pinned per assigned star."** A box sits on its star until the user drags it elsewhere in Config — still never a reflow the app initiates.
- **In zodiac mode the frame fits the whole asterism**, occupied stars and empty alike — the recognizable shape is the point, and it must not warp as boxes come and go. The occupied-only framing above now applies only to the fallback layout.
- **Unoccupied stars render as faint markers** (Halo fill, reduced radius) — visibly different from an `absent` box, which keeps full radius. An edge touching an empty star draws dim, never live.
- **The old fixed layout survives as the fallback** for installs that never chose a constellation (`constellation: null`) — they look exactly as they always did, hand-authored pair list and all.

> **Two constellations, two different linking rules — don't conflate them.** This widget (`components/chrome/ConstellationStatus.tsx`) draws a **declared** adjacency map — the chosen zodiac's stick figure (or the legacy fixed shape) — because a status readout has to be glanceable and must not reflow. Mission Control's 3D constellation (`starting-a-session.md` §6) is a different object entirely — one star per *animal*, seeded positions, links computed by nearest-neighbour in `lib/sessions/stars.ts`. They share a visual family and nothing else.

---

## 3. Dashboard / Landing Window — Information Architecture

### 3.1 Layout Overview

```
┌────────────────────────────────────────────────────────────┐
│  ⋆ Ephymeris                                       [_][□][X] │  ← custom titlebar
├───────────┬────────────────────────────────────────────────┤
│           │  Dashboard                                      │
│  ⋆ Dash   │                                                 │
│  ◐ Cohort │   ┌─────────────────────────────────────────┐  │
│  ▹ Debug  │   │            Start a Session          →    │  │  ← hero CTA
│  ◇ Analyt │   └─────────────────────────────────────────┘  │
│  ⚙ Settng │                                                 │
│           │   ┌────────────┐ ┌────────────┐ ┌───────────┐  │
│           │   │  Cohorts   │ │  Analytics │ │ Debug Mode│  │
│  ─────    │   │  4 active →│ │   view →   │ │ 6 boxes → │  │
│  •—•—•    │   └────────────┘ └────────────┘ └───────────┘  │
│  •—•—•    │                                                 │
│ (status)  │                                                 │
└───────────┴────────────────────────────────────────────────┘
```

Two-region layout: a persistent left sidebar (frosted glass, `Nebula` translucent) and a main content area. No top menu bar beyond the custom titlebar — all navigation lives in the sidebar, consistent with the macOS System Settings/Music-style pattern.

The titlebar is app-drawn on **both** platforms (see §5): native window decorations are disabled, and minimize/maximize/close are rendered by the app. The bar itself is a drag region.

### 3.2 Sidebar

- App mark + wordmark at top. The *bundle* icon exists as of 2026-07-29 — the goggled rat-on-a-rocket, palette-native (source `src-tauri/icons/icon.svg`, all platform sizes generated from it via `npx tauri icon`). The in-titlebar mark deliberately stays the six-point-star squircle: at 17px the rocket-rat artwork would be an unreadable smudge, and the star was purpose-built for that size.
- Nav list, two groups: **Dashboard** (home, default selected) · **Cohorts** · **Debug** · **Analytics** at the top, and the configuration pair **Config** · **Settings** pinned to the bottom just above the constellation widget — setup lives at the edge of the list, not among the daily destinations. Selected item gets a `Pulsar`-tinted rounded-rect highlight at reduced opacity, matching the macOS sidebar selection convention; the highlight is one shared `layoutId`, so it glides between the groups as readily as within one.
- Very bottom of sidebar: the constellation status widget (§2.7) — always visible regardless of which section is active, since box connectivity is something the user should never have to navigate to check.

Note: this row has now been decided three times (each recorded, not erased). Originally **Start a Session** was deliberately *not* a sidebar nav item — the app's single primary action getting the hero CTA position instead of competing in a list of equally-weighted destinations. That was **reversed**: once a session can outlive the screen that started it, a *running* session needs a stable, always-visible way back, and the hero CTA only ever started one — so **Launch** (`/launch`) became a nav item owning the primary action, the way back, and unfinished set-ups. **Reversed again 2026-07-29**: with the Dashboard hero compacted, Launch's entire content fits *beside* the hero as the **session dock** (§3.3), and a nav item whose destination duplicates the home view is a redundant tab. The stable-way-back requirement stands and is now met by the Dashboard itself: its nav row carries the small matte `status-ok` dot while a session runs, its active state covers the whole `/session/*` flow, and the hero reads "Resume Session." `/launch` no longer exists as a route; old paths fall through the wildcard to the Dashboard, which shows the same content. Config and Settings are sidebar-only and not duplicated as dashboard tiles, following the Apple convention that configuration lives in one fixed, always-reachable place rather than as browsable "content."

### 3.3 Main Content — Dashboard/Home View

**The rig's 3D constellation is the page** (revised again 2026-07-29, superseding the same-day grid layout; columns split later the same day): the same browser Debug flies (§4.3) — temperature stars, cage-ships, orbit/pan/zoom, the deep-sky backdrop — fills the content area edge to edge, and everything else docks over it as **two columns of HUD tiles**. The **left is the command column**: the page title, the hero CTA directly under it, and the session dock (running / configuring / stale sessions) directly under that — "what do I do now" in one stack. The **right is the overview column**: the Cohorts / Debug Mode / Analytics summary cards. Tiles are translucent (`.hud` — the docked-panel treatment §2.4; the sky reads through them) and both containers ignore the pointer, so the sky between the columns still orbits. **Debug shares this exact scaffold** — full-bleed sky, header overlaid on the same title grid (32px indent, 28px down), detail panel docked at the same 16px insets — which is what makes Dashboard → Debug seamless: the two views hand the one shared canvas (`SharedCanvas.tsx`) a pixel-identical rectangle, so the handoff needs no resize, aspect change or reflow.

> **The Rig tile is a readout, not a destination** (2026-07-29). It was the "Debug Mode" card, with a clickable header that navigated to `/debug`. That header was a third route to a place the page already was: the sky on the Dashboard **is** the rig, and selecting a box — by clicking its star, or one of the tile's rows — is what opens that box's instrument panel. So the header lost its link and its arrow and now states rig health only (`n/m connected`), while the rows carry the one real gesture: each sets the shared rig selection and lands in Debug with the camera already flying, exactly as its star does. `SummaryCard`'s `onOpen` is optional for this reason, and its absence is the signal — a card with one is a destination, a card without one is a readout. The tile keeps a single link, to Config, and only when no box is bound: that is the one repair a click on the sky cannot perform. Renamed to **Rig** so it names its subject rather than duplicating the sidebar's Debug entry.

> **The sky is never animated, in either view.** Both routes keep the canvas host *outside* their entrance transition and fade only their chrome. This is not a polish detail: the shared canvas physically lives in the active view's subtree, so a view-level opacity animation fades the constellation with it — and because both views show the same sky, navigating between them made it blink out and back on every arrival. Chrome crossfades, sky holds still. Any new view that hosts the constellation must follow the same rule.

**One sky, across views.** The camera pose and the selected box persist in `lib/constellations/viewMemory.ts`, keyed by subject ("rig"; Mission Control keys per cohort) — navigating Dashboard ↔ Debug lands exactly where the other view left off, selection included, which is what makes the two views read as one continuous instrument rather than two screens with similar wallpaper. Selecting a star on the Dashboard hands off to Debug (where the box's instrument panel lives) with the arrival flight continuing across the navigation. Memory is per-sitting by design — a fresh launch starts at the overview; it is the within-session snap-back that would read as a glitch.

- **Hero CTA:** "Start a Session," primary `Pulsar`-filled, the head of the HUD column and its one deliberately opaque tile — the primary action doesn't dissolve into the sky. Navigates straight to its destination (§3.2): Step 1 (`/session/new`) normally, `/cohorts` when no cohort exists yet, Mission Control while a session runs ("Resume Session"). On hover the rocket lifts toward its heading and a looping booster-trail streams behind it — `Void` on the `Pulsar` fill, fire drawn with motion, not colour or glow (§2.2); the loop stands down under reduced motion (§2.5).
- **Session dock** (`components/sessions/SessionDock.tsx`): everything `sessions.active` reports — the running session's card (live per-box liveness from `port.state`, Open Mission Control, End Session), `configuring` set-ups (Resume setup / Discard), crash-orphaned `stale` rows read-only (View in Analytics / Close out — never Resume, `starting-a-session.md` §11). Renders nothing when there is nothing to act on, and nothing before `sessions.active` has answered — the no-spinner rule.
- **Summary cards:** clickable header (icon, label, live status, arrow) over at-a-glance rows; header and rows navigate to the same destination as the sidebar item.
  - **Cohorts** — active cohorts (name, animal/group counts), rows opening the editor, deferring to the grid past five rows.
  - **Debug Mode** — every bound box with the widget's health dot and wording. Status: "connected/bound."
  - **Analytics** (revised 2026-07-29, replacing the single latest-session preview) — two things:
    - **A reward-accuracy sparkline per cohort**: one point per session in date order, rewarded over administered trials pooled across the session's runs — **the earned-drop rate, not choice accuracy** (`analytics.md` §3.8): a correct choice that failed the hold counts against it. Fixed shared domain (floored just below chance, guide line at 0.5) so cohorts compare at a glance; the latest value prints beside the line so the number is never colour-alone. Rides the app-level analytics cache — the same per-cohort summaries the rig's star temperatures load.
    - **The three most recent sessions by date, from the archive itself** (`analytics.recentSessions` — folder names only, never a file open): sessions another Ephymeris machine wrote into the shared data directory are real history and appear here marked "not indexed," where `sessions.list` (this machine's database) could never see them. A session starting or ending refetches.

---

## 4. Section-by-Section Breakdown & Wiring

**Originally:** only Debug Mode and Settings were to get real wiring for v1, with the other three sharing a placeholder pattern rather than dead, inert buttons — clicking should still feel like the app responded, just with an honest "not yet."

**As built:** all sections are wired. The subsections below record each one's journey, since the original reasoning explains why the app is shaped the way it is.

| Section | Route | State |
|---|---|---|
| Start a Session | `/session/new` → `/session/:id/mapping` → `/session/:id/control` | **Built** |
| Cohorts | `/cohorts`, `/cohorts/new`, `/cohorts/:id` | **Built** |
| Debug Mode | `/debug` | **Built** |
| Analytics | `/analytics` | **Wired** |
| Config | `/config` | **Built** |
| Settings | `/settings` | **Built** |

### 4.1 Start a Session — *wired* (was: stub, with real gating logic)

- Starting a session **requires an existing cohort.** This is the one piece of actual conditional logic among the three stub sections.
- Convenient consequence of build order: since Cohorts (§4.2) has no real data in v1, the cohort count is always zero — so the hero CTA can honestly render its **empty-state** every time, with no need to fake or hardcode anything. The gating logic is real; it just always resolves the same way until Cohorts is wired.
- Empty-state behavior: hero card shows "Create a cohort to get started" in place of the normal CTA label, and clicking it routes to `/cohorts` instead of `/session/new`.
- **Now a live check** against the real cohort count (Cohorts is wired — §4.2). Still deliberately an *existence* check: "ready to run" is now defined (`starting-a-session.md` §1) but is a property of one cohort, and the CTA isn't scoped to a cohort — Step 1 is where a cohort gets picked, so that's where the readiness check lives and warns.
- **`/session/new` is no longer a `<PlaceholderView>`.** It opens the two-step setup flow specified in `starting-a-session.md` — configuration, then animal→box mapping and the sequential flash — handing off to Mission Control at `/session/:id/control`, with the 3D constellation as its centerpiece. Sessions write to disk per `data-saving.md`.

### 4.2 Cohorts — *wired* (was: stub)

- Sidebar item + dashboard tile → route `/cohorts`.
- **No longer a `<PlaceholderView>`.** Fully specified and implemented in `cohorts.md`: card grid with the procedural constellation icon, create/edit editor at `/cohorts/new` and `/cohorts/:id`, Auto-Balance grouping, and archive/permanent-delete. Cohort data lives in the sidecar's SQLite database.
- The dashboard's "N active" tile stat is consequently real rather than placeholder text.

### 4.3 Debug — *wired* (overhauled 2026-07-27: constellation landing + node detail; 3D browser 2026-07-28; deep-sky backdrop + animal satellites 2026-07-29)

- Reached by the sidebar item, or by selecting any box on the Dashboard — its Rig tile is a readout, not a link (§3.3) — route `/debug`. **One continuous 3D scene**, not two views; selection lives in the shared rig view-memory (`lib/constellations/viewMemory.ts`, revised 2026-07-29 from route-local state) because the Dashboard now browses the same sky (§3.3) and the two views must agree on what is selected. Still never a URL segment: memory is per-sitting, so a reload landing on the overview remains the right recovery.
- **The landing is the same 3D browser as Mission Control** (`components/constellation3d/Scene.tsx`, shared verbatim with `starting-a-session.md` §6.2–§6.3): the chosen zodiac asterism (§4.6) in world space, orbit on left-drag, pan on right-drag with an on-screen arrow pad and recentre button, wheel zoom, the billboarded hover reticle, persistent nameplates, and the eased arrival flight. Debug browses the *rig* where Mission Control browses a cohort — an operator who has learned one has learned the other. Every bound box is a star at its assigned slot; unclaimed stars of the asterism are drawn faint as scenery, so the constellation still reads on a rig that binds two boxes. With no constellation chosen, `resolveLayout` supplies the pre-zodiac `legacyLayout`, which pins a position per box number.
- **Colour is temperature here too** (revised 2026-07-29 — reversing the original "colour here is status, never performance" call, recorded not erased). A box's star takes Mission Control's stellar ramp (`constellation3d/StellarSurface.tsx`, shared verbatim): its temperature is the **mean recorded accuracy of the animals assigned to that box**, each animal pooled across *all* of its scored sessions (`debug/useBoxStellar.ts` — hits over counted trials of the run-level pooled `overall` metric, `analytics.md` §3.7, meaned per box across every active cohort that assigns it). Deep red at chance through orange, yellow and white to blue-white — hotter is better, and a box with nothing scored sits at the cool end rather than claiming warmth. The data rides the app-level analytics cache, so stars warm as summaries arrive instead of blocking the scene. What the original decision protected — "is this box alive, and what is it doing" — moved fully into motion: a *detected* box's surface churns and carries a mote in orbit; an undetected box's photosphere is **frozen** — stillness is the status, written into the star itself; an *open* box (passthrough / in session) adds the slow dashed instrument ring; a *faulted* box wears a thin steady Error-red ring, status colour's one holdout, because a fault must not be readable as merely a cool star. The stellar surfaces are the same bounded exception to §2.2 that Mission Control's are; the 2D chrome still gains no gradient or glow.
- **Debug is laid out as the Dashboard's twin** (2026-07-29): full-bleed sky, the header overlaid on the shared title grid rather than stacked above a boxed canvas, and "Select a box to inspect it" as a subtitle under the title instead of a footer line. The old flex column (`px-8 pb-3 pt-8`, canvas in the leftover height) gave the shared canvas a *different rectangle* than the Dashboard's, so every handoff resized the renderer mid-navigation — the jitter this replaced. The empty-rig notice is now a HUD tile over the sky, not a bare paragraph on a blank page.
- **Every bound box is selectable, however sick.** This is the deliberate divergence from §6.2, where an unlit star is inert by construction: an absent or faulted box is precisely the one you came to Debug to open.
- **The deep-sky backdrop and the unframed canvas are shared too** (`starting-a-session.md` §6.2): the seeded twinkle field, nebula banks, and occasional supernova sit behind the rig's asterism exactly as they do behind a cohort's, and the transparent, edge-faded canvas joins the app background with no tile border. Scenery, deterministic, still under reduced motion — status animation stays the only motion that *means* anything.
- **Every home cage rides a star as one crewed ship** (`components/constellation3d/Orbiters.tsx`, `lib/constellations/ships.ts`, `starting-a-session.md` §6.2) — revised again 2026-07-29 from per-animal satellites: cagemates (`cohorts.md` §2 `cage`) share a single craft, tagged with the whole crew, and cageless animals fly solo. A ship orbits the box of its currently running crew member, else the box its most recently ran member ran on — the members and run history come from the same per-cohort summaries as the temperatures, so the rig view answers "where is this cage" whether or not anything is running. Parked crews hold their seeded bearings with a steady faint light; a live session upgrades the matching ship to active (orbit + engine burn + double-flash strobe), so "who is in box 3 *right now*" reads as motion against the parked fleet. The anonymous detected-mote stands down while any ship is up — crossing craft would read as noise, and a crewed box's liveness still shows in the churn of its surface.
- **Node detail** (`components/debug/NodeDetail.tsx`). Selecting a star flies the camera to it and **docks the panel over the still-rendering scene**, translucent Nebula with a vibrancy blur, exactly as Mission Control's `StarPanel` does — arrival means the camera is now close to that box's star with an instrument panel open, not a cut to a different screen. It carries identity (hardware id in mono, port, carried sketch) and every debugging utility, grouped by intent rather than compressed into one header row: **Connection** (state badge, baud, open/close, reset, error acknowledge, rejection surface), **Sketch** (flash dialog, utility controls + telemetry strip for `"kind": "utility"` profiles per `data-saving.md` §6.6), **Console** (scrollback, send with line-ending selector, copy log). The carried sketch is the *baseline's* answer first (`hardware-interaction.md` §6.6, revised 2026-07-29): a box the baseline reports `ready` shows the configured utility sketch — labelled "(baseline)" — with its controls and telemetry already live, no manual flash needed; only a user flash of a different sketch displaces it. Escape, Back, or clicking empty space flies back out.

  > The panel sits at `z-20`, above the `zIndexRange` drei gives the nameplates. Those plates are crisp opaque DOM rather than part of the scene the translucent panel is meant to show through, and one drifting over a control would be a plate sitting on a button.

  > `Star3D.tsx` is **retired**. It existed to give the old full-page detail view a star of its own; the docked panel has the real one right behind it, in the box's own health colour, still turning.

  The console is **two tabs, Console and Status**. A utility sketch emits a telemetry line on every state change *plus* a ~1 s heartbeat (`data-saving.md` §6.6), so interleaved they bury the command echoes, boot banner, and self-test confirmations the console exists to show — on `BOX_Utility` they outnumber everything else several to one. The split is by the profile's `telemetry.match` (default `STATUS`) and applies only to **received** lines: a sent `STATUS?` is a command echo and belongs beside what it caused. Each tab carries its own line count, and Copy copies whichever tab is open. The Status tab is the *history*; the utility strip above it is the current parsed values, and they answer different questions.

  > This splits what is *displayed*, not what is *kept*: both tabs read the one capped ring buffer (~2000 lines/box, `websocket-protocol.md` §5.4). A 1 Hz heartbeat therefore still consumes that budget — roughly half an hour of scrollback on a chatty utility sketch — so a long priming session can age out earlier console lines even though the Console tab looks quiet. Worth knowing before trusting it as a long-run log; the copy-log affordance is the escape hatch. The old one-panel-per-box `ConsolePanel` is retired; `Scrollback` was extracted from it and everything else was reorganized into the groups, not re-invented.
- The WebSocket connection is **app-level, not per-view** (a deliberate amendment to this section's original "opens on mount"): the constellation widget must reflect box health from every screen, so the connection, the state replay, and the shared hardware store live at the app root. What Debug Mode *does* trigger on mount is a sketch rescan (`arduino-directory.md` §4).
- This is the first real end-to-end data path in the app: **sidecar → WebSocket → React state**, feeding both the full Debug Mode view *and* the sidebar's constellation status widget from the same out-of-band polling channel. Building this wired up the signature element for free, as predicted.

### 4.4 Analytics — *wired*

- Sidebar item + dashboard tile → route `/analytics`.
- **Built to [analytics.md](analytics.md)**, which is canonical for this section: a single-route dashboard with persistent cohort/session/animal selectors, three linked visualizations (strategy space, learning curves, cohort heatmap), the metric definitions derived from recorded sessions, and the query surface behind them.
- Also the session-end landing, now preselecting the run just finished.

### 4.5 Settings — *wired* (now: storage & interface only)

- Sidebar item → route `/settings`.
- **Editing surface split (2026-07-27):** everything hardware-shaped — box→board bindings, per-box nicknames, default baud, the Arduino Directory, and the `arduino-cli` override — moved to **Config** (§4.6). Settings keeps the data directory, the backup directory, and the reduced-motion toggle. **Ownership did not move**: the settings *store* still holds every field in one place; only where each field is edited changed.
- The persisted schema, all shell-owned:
  - Default data save directory *(edited here)*
  - Backup directory *(edited here)* — see `data-saving.md` §8 for what is mirrored and when
  - Reduced-motion toggle *(edited here)*
  - **Arduino Directory** *(edited in Config)* — see `arduino-directory.md`
  - Default baud rate *(edited in Config)*
  - **Box→board bindings** with per-box nicknames *(edited in Config)* — a `box_number → hardware_id` map so a box keeps its identity across reboots and Windows COM renumbering (see §5)
  - `arduino-cli` / core path override *(edited in Config)*
  - `constellation`, `constellationSlots`, `boxSetupComplete` *(edited in Config; shell-only — the sidecar ignores them)* — the §4.6 zodiac layout and first-run flag
- **Ownership: Tauri-side store** (`tauri-plugin-store`, JSON on disk in the app data dir), not the Python sidecar. Reasoning:
  - Most of these fields (save paths, baud rate, `arduino-cli` path) are exactly the values most likely to be *wrong* when something is misconfigured — and a wrong `arduino-cli` path or bad save directory is a plausible cause of the sidecar failing to start. If the sidecar owned settings, a bad config could lock the user out of the one screen that fixes it. Settings needs to work even when the sidecar doesn't.
  - The Tauri store plugin is simple, well-supported, and gives native OS directory pickers for free from the shell layer — no need for the sidecar to implement its own config persistence/schema/migrations on top of everything else it owns.
  - The sidecar still needs these values at runtime, so the shell **pushes the full settings payload to the sidecar on every WebSocket connect/reconnect, and again on every change** — a one-directional sync (Tauri → sidecar) rather than the sidecar being the source of truth. Simpler failure mode: worst case, the sidecar is briefly running on stale values until the next push, rather than being unreachable entirely.

### 4.6 Config — *built*

- Sidebar item → route `/config` (`routes/Config.tsx`). Everything box-related in one place: the constellation layout, box→board bindings, the handshake test, default baud, the Arduino Directory, and the `arduino-cli` override.
- **First-run setup wizard** (`components/config/SetupWizard.tsx`): opens instead of the normal view until `boxSetupComplete` is set. Five linear steps — map hardware (the same `BoxBindingsTable` as the normal view, write-through), nickname boxes, per-box handshake test, pick a zodiac constellation, done. In-route rather than a modal (a multi-minute guided flow is not "transient", and vibrancy stays reserved for the sidebar and true modals — §2.4). **Never traps:** Back always works, "Skip setup" is always visible and just sets the flag, and a failed handshake never blocks advancing — the hardware may simply be off. The constellation choice is local until Finish, so an abandoned run leaves no half-chosen layout; the gate renders nothing until settings are `loaded`, or the wizard would flash for every configured user on every launch. "Run setup again" re-opens it without clearing the flag.
- **Zodiac layouts** (`lib/constellations/zodiac.ts`): twelve hand-authored, simplified asterisms — data, not generated, because they must be recognizable. Star counts are honest (Aries has four) and the picker **disables any constellation with fewer stars than configured boxes** rather than distorting the shape. Slot semantics (`lib/constellations/slots.ts`): **slots follow boxes** — deleting a box frees its star, a new box takes the lowest free star, switching constellations keeps star indices that still exist; `reconcileSlots` is the single authority and `layoutFor` runs it defensively so a stale persisted map can never render a node off the chart. Keys in `constellationSlots` are strings (JSON on the wire).
- **Drag is snap-to-star** (`components/config/ConstellationBoard.tsx`): raw pointer events with viewBox-space hit-testing, a ghost node while dragging, snap to the nearest star within radius or revert, **swap** when the target is occupied. One settings write per completed drag, never per pointer move.
- **Handshake test** (`lib/hardware/useHandshakeTest.ts`) — composed from existing wire primitives, deliberately **no new command**: `port.passthrough.open` asserts DTR on open, which resets the Mega and captures its boot output into `port.output`; listen ≤ 10 s (the sidecar's own READY budget); always close in a `finally`, including on unmount. `port.reset` is unsuitable — its DTR pulse uses an unread throwaway handle, so its own boot output is unobservable, and it would double-reset. Tiered result:

  | Tier | Meaning | Colour |
  |---|---|---|
  | `ready` | `READY` line seen — speaks the Ephymeris protocol | Ion |
  | `output` | Some output — wiring and port good, not an Ephymeris task sketch | Pulsar |
  | `silent` | Port opened, nothing heard — wrong baud or a mute sketch | status-warning |
  | `failed` | Port never opened — unbound box, missing/busy port | status-error |

  A box already in `PASSTHROUGH` is closed before the test (re-opening is what causes the observable reset) — which also honours the hardware rule that **a stale handler must never survive a rebind**: close before rebinding, or rebind only while `IDLE`.

### Shared: `<PlaceholderView>`

One reusable component — a title, a short explanatory line in the interface's own voice, and optionally a disabled preview of what the real view will eventually contain. It was built to cover §4.1, §4.2, and §4.4 at once, effectively wiring three of the five sections for the price of one.

**It now has exactly one caller: Analytics.** The other two grew into real views. The component's own doc comment still says "the three unwired sections" and its `preview` prop is unused — harmless, but it is the last trace of the original plan, and it will read as confusing to the next person who opens it.

---

## 5. Resolved Decisions

| Decision | Outcome |
|---|---|
| App name | **Ephymeris** (§1) |
| Settings ownership | **Tauri-side store**, pushed to sidecar on connect/change (§4.5) |
| Start-a-Session gating | **Requires an existing cohort** (§4.1) |
| Light mode | **Out of scope for v1**, no placeholder toggle (§2.2) |
| Box→board binding | **By `hardware_id`** (the board's USB serial number), stored in Settings and editable. Port addresses are not stable — Windows renumbers COM ports across reboots and re-enumeration, which would silently re-point a box at the wrong physical board. Box number 1–6 is therefore the stable key throughout the app and on the wire (`websocket-protocol.md` §5.1) |
| `arduino-cli` integration | **Subprocess + `--format json`** behind a `BoardTool` interface for v1; gRPC daemon is a committed migration scheduled after flashing works end-to-end (`hardware-interaction.md` §2, §9) |
| Box list | **User-managed, starts empty** — Settings offers add/remove rather than six fixed rows, since a rig may run two boxes or six. Box *numbers* remain 1–6 and stay the stable protocol key (`websocket-protocol.md` §5.1); only which of them exist is configurable (§4.5) |
| Debug Mode panels | **One per bound box.** "Bound" means *configured with a board*, not *currently detected* — an unplugged box keeps its panel, since that's where its scrollback and any `ERROR` state must stay visible (§4.3) |
| Constellation scope | **Only bound boxes get a node** (§2.7), amending the original always-six layout |
| Window chrome | **Custom controls on both platforms** — native decorations off, app-drawn `[_][□][X]` per the §3.1 sketch. macOS does not keep its traffic lights, so the titlebar is identical on the dev machine and the lab PCs and there is no platform-specific chrome to reason about |
| 3D dependencies | `three` + `@react-three/fiber` + `@react-three/drei` added for `starting-a-session.md` §6. Frontend-only — the **sidecar's** runtime dependencies remain just `pyserial` and `websockets`, which is where install fragility actually costs the lab something |

No open questions remaining as of this revision.

---

## 6. Open Items / TBD

- [x] ~~Session-setup flow spec~~ — resolved in `starting-a-session.md` (configuration → mapping → flash → Mission Control → 3D constellation) and `data-saving.md` (what the run writes to disk); both are built
- [x] ~~Cohort CRUD spec (create/edit/delete/group management)~~ — resolved in `cohorts.md`
- [x] ~~Once Cohorts is wired: replace Start-a-Session's hardcoded always-empty gating (§4.1) with a live cohort-count check~~ — done; existence check only, with readiness deferred to the Starting a Session doc
- [x] ~~Analytics view spec (within-session, across-session, per-cohort)~~ — **written**, as [analytics.md](analytics.md), the eighth living spec. All three views are specified, along with the derived-metric definitions and the query surface — and now built to it (§4.4)
- [ ] Full Settings schema (fields listed in §4.5 are a starting point, not final — grown to ten with §4.6's three shell-only keys)
- [x] ~~WebSocket/IPC message schema (shared with `hardware-interaction.md`), including the settings-push message shape~~ — resolved in `websocket-protocol.md`
- [ ] App icon / wordmark design for Ephymeris. The titlebar currently carries a placeholder mark — a six-point star knocked out of a Pulsar squircle
- [x] ~~**Constellation adjacency (§2.7).**~~ — **superseded by §4.6's zodiac layouts.** The layout is now the user's chosen constellation, so there is no fixed pair list to confirm against the bench; the hand-authored `1–2, 2–3, 4–5, 5–6, 1–4, 3–6` shape survives only as the fallback for installs that never ran box setup
- [x] ~~**Backup Directory does nothing yet.**~~ — **built.** `data-saving.md` §8's mirroring now covers all three: session files at finalization (queued, never blocking teardown), the `.tsv` while running (10 s, self-paced), and `ephymeris.db` (every commit, debounced, with dated daily snapshots). Settings shows live mirroring state and an explicit sync control beside the field, and Mission Control carries a compact indicator — because a backup that silently stops working would be the same broken promise this item was about
- [x] ~~**Windows packaging**~~ — **built** (2026-07-28). `npm run package` produces an NSIS per-user installer carrying a PyInstaller-frozen sidecar, `arduino-cli`, and a seeded `arduino:avr` core — no Python, no Arduino install, no internet needed on the lab machine (`hardware-interaction.md` §2 satisfied). Remaining from the original scope: signing and a CI build (TODO item 27) — the installer is unsigned, so first run shows SmartScreen's "More info → Run anyway"

---

**Next:** [reference.md](reference.md) — the architecture and module map, so the names above map to files.
[Documentation index](README.md) · [Open items register](TODO.md)

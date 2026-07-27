# Tech Stack & Dashboard Design

> **Status** · Living spec — **Built.** Dashboard shell, the full theme, Cohorts, Debug Mode, Settings, and the session flow are all wired end to end. Analytics alone is still a placeholder.
>
> **Owns** · Tech stack, app identity, theme tokens, dashboard information architecture, and Settings ownership.
>
> **Read with** · [hardware-interaction.md](hardware-interaction.md) (the serial layer) · [cohorts.md](cohorts.md) (the Cohorts tab) · [websocket-protocol.md](websocket-protocol.md) (the wire schema) · [arduino-directory.md](arduino-directory.md) (sketch discovery)
>
> **Still open** · Analytics view spec · the full Settings schema · app icon design · Windows packaging

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
- **The frame reflows, not the layout.** The viewBox is fitted to whichever boxes exist (keeping a constant aspect so the sidebar never jumps), so a small rig fills the space instead of huddling in a corner. Framing changes only when boxes are added or removed — a deliberate configuration act, never something that happens mid-session.
- **Marks keep a constant apparent size.** Node radius and line width scale with the frame, so zooming spreads the *spacing* rather than inflating the dots; a one-box rig renders one normal dot, not one enormous one.
- **An edge is drawn only when both its endpoints are configured.** A sparse selection (say boxes 1 and 6) can therefore show unconnected nodes — honest, since there is no adjacency to report.

> **Two constellations, two different linking rules — don't conflate them.** This widget (`components/chrome/ConstellationStatus.tsx`) draws a **fixed** adjacency map: six pinned node positions and a hand-authored edge list, because a status readout has to be glanceable and must not reflow. Mission Control's 3D constellation (`starting-a-session.md` §6) is a different object entirely — one star per *animal*, seeded positions, links computed by nearest-neighbour in `lib/sessions/stars.ts`. They share a visual family and nothing else. The open item in §6 is about *this* widget's fixed pair list only.

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

- App mark + wordmark at top (placeholder glyph shown above; actual icon design is a future item).
- Nav list: **Dashboard** (home, default selected) · **Cohorts** · **Debug Mode** · **Analytics** · **Settings**. Selected item gets a `Pulsar`-tinted rounded-rect highlight at reduced opacity, matching the macOS sidebar selection convention.
- Bottom of sidebar: the constellation status widget (§2.7) — always visible regardless of which section is active, since box connectivity is something the user should never have to navigate to check.

Note: **Start a Session** is deliberately *not* a sidebar nav item. It's the app's single primary action, so it gets the hero CTA position in the main content area instead of competing for space in a list of five equally-weighted destinations. Settings is sidebar-only and not duplicated as a dashboard tile, following the Apple convention that Settings lives in one fixed, always-reachable place rather than as browsable "content."

### 3.3 Main Content — Dashboard/Home View

- **Hero card:** "Start a Session," full-width, primary `Pulsar`-filled. The single most prominent element on the screen, reflecting that running sessions is the core workflow of the app.
- **Secondary tile row:** three compact cards — Cohorts, Analytics, Debug Mode — each with an icon, label, and a one-line placeholder status (e.g. "4 active," "6 boxes"). Clicking a tile navigates to the same destination as its sidebar item; the tiles exist for at-a-glance summary and faster access from the home view, not as a separate IA branch.

---

## 4. Section-by-Section Breakdown & Wiring

**Originally:** only Debug Mode and Settings were to get real wiring for v1, with the other three sharing a placeholder pattern rather than dead, inert buttons — clicking should still feel like the app responded, just with an honest "not yet."

**As built:** four of the five are wired. Start a Session, Cohorts, Debug Mode, and Settings are all real; **Analytics is the only remaining placeholder.** The subsections below record each one's journey, since the original reasoning explains why the app is shaped the way it is.

| Section | Route | State |
|---|---|---|
| Start a Session | `/session/new` → `/session/:id/mapping` → `/session/:id/control` | **Built** |
| Cohorts | `/cohorts`, `/cohorts/new`, `/cohorts/:id` | **Built** |
| Debug Mode | `/debug` | **Built** |
| Analytics | `/analytics` | **Placeholder** |
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

### 4.3 Debug Mode — *wired*

- Sidebar item + dashboard tile → route `/debug`.
- Renders the 6-box console grid exactly as specified in `hardware-interaction.md` §6 (per-box panels, read/send, line-ending selector, state badges), plus the flashing dialog and reset control from §4–§5. A box flashed with a `"kind": "utility"` sketch also gets profile-driven **controls + a live status strip** (`data-saving.md` §6.6), so priming/self-test sketches are driven from the app rather than by hand at the box.
- The WebSocket connection is **app-level, not per-view** (a deliberate amendment to this section's original "opens on mount"): the constellation widget must reflect box health from every screen, so the connection, the state replay, and the shared hardware store live at the app root. What Debug Mode *does* trigger on mount is a sketch rescan (`arduino-directory.md` §4).
- This is the first real end-to-end data path in the app: **sidecar → WebSocket → React state**, feeding both the full Debug Mode view *and* the sidebar's constellation status widget from the same out-of-band polling channel. Building this wired up the signature element for free, as predicted.

### 4.4 Analytics — *stub*

- Sidebar item + dashboard tile → route `/analytics`.
- Same `<PlaceholderView>` pattern.

### 4.5 Settings — *wired*

- Sidebar item → route `/settings`.
- Needs a real, if minimal, persisted config even at this stage. Proposed fields to start:
  - Default data save directory
  - Backup directory — a second copy on a different drive or share; see `data-saving.md` §8 for what is mirrored and when
  - **Arduino Directory** — root folder for sketches/libraries; see `arduino-directory.md` for structure, detection, and error handling
  - Default baud rate
  - Per-box COM port labels/nicknames
  - **Box→board bindings** — a `box_number → hardware_id` map, editable, so a box keeps its identity across reboots and Windows COM renumbering (see §5)
  - `arduino-cli` / core path override
  - Reduced-motion toggle
- **Ownership: Tauri-side store** (`tauri-plugin-store`, JSON on disk in the app data dir), not the Python sidecar. Reasoning:
  - Most of these fields (save paths, baud rate, `arduino-cli` path) are exactly the values most likely to be *wrong* when something is misconfigured — and a wrong `arduino-cli` path or bad save directory is a plausible cause of the sidecar failing to start. If the sidecar owned settings, a bad config could lock the user out of the one screen that fixes it. Settings needs to work even when the sidecar doesn't.
  - The Tauri store plugin is simple, well-supported, and gives native OS directory pickers for free from the shell layer — no need for the sidecar to implement its own config persistence/schema/migrations on top of everything else it owns.
  - The sidecar still needs these values at runtime, so the shell **pushes the full settings payload to the sidecar on every WebSocket connect/reconnect, and again on every change** — a one-directional sync (Tauri → sidecar) rather than the sidecar being the source of truth. Simpler failure mode: worst case, the sidecar is briefly running on stale values until the next push, rather than being unreachable entirely.

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
| `arduino-cli` integration | **Subprocess + `--format json`** behind a `BoardTool` interface for v1; gRPC daemon is a committed migration scheduled after flashing works end-to-end (`hardware-interaction.md` §2, §8) |
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
- [ ] Analytics view spec (within-session, across-session, per-cohort)
- [ ] Full Settings schema (fields listed in §4.5 are a starting point, not final)
- [x] ~~WebSocket/IPC message schema (shared with `hardware-interaction.md`), including the settings-push message shape~~ — resolved in `websocket-protocol.md`
- [ ] App icon / wordmark design for Ephymeris. The titlebar currently carries a placeholder mark — a six-point star knocked out of a Pulsar squircle
- [ ] **Constellation adjacency (§2.7).** The spec says lines connect *adjacent* nodes but never enumerates which pairs. `components/chrome/ConstellationStatus.tsx` uses `1–2, 2–3, 4–5, 5–6, 1–4, 3–6` — one closed shape, so no node is ever orphaned — over node positions pinned in a 100×54 viewBox. **Confirm this matches the physical box arrangement on the bench;** if the rig is laid out differently, the map should mirror it. Now that only bound boxes render, a sparse selection can leave nodes with no edges at all, which makes the pair list more visible than it used to be. Applies to the sidebar widget only — Mission Control's 3D constellation computes its own links and is unaffected
- [x] ~~**Backup Directory does nothing yet.**~~ — **built.** `data-saving.md` §8's mirroring now covers all three: session files at finalization (queued, never blocking teardown), the `.tsv` while running (10 s, self-paced), and `ephymeris.db` (every commit, debounced, with dated daily snapshots). Settings shows live mirroring state and an explicit sync control beside the field, and Mission Control carries a compact indicator — because a backup that silently stops working would be the same broken promise this item was about
- [ ] **Windows packaging** — deliberately deferred while v1 was developed on macOS. Covers: freezing/shipping the Python sidecar (dev builds run it from `sidecar/.venv`), bundling `arduino-cli` + the `arduino:avr` core with the installer per `hardware-interaction.md` §2 (currently uses the machine's own install), Tauri Windows bundling/signing, and a Windows CI build. None of it is started

---

**Next:** [reference.md](reference.md) — the architecture and module map, so the names above map to files.
[Documentation index](README.md) · [Open items register](TODO.md)

# Ephymeris — Tech Stack & Dashboard Design

**Status:** Living document. Covers overall tech stack, dashboard/landing window IA, and app theme.
**Companion document:** `hardware-interaction.md` (serial/Arduino hardware layer full spec), `arduino-directory.md` (sketch/library discovery).
**Not yet covered (future sections):** session-setup flow, cohort CRUD spec, analytics view spec, full settings schema, WebSocket/IPC message schema.

---

## 0. Tech Stack

- **Shell / desktop runtime:** Tauri
- **Frontend:** React (TypeScript), styled with Tailwind, animated with Framer Motion
- **Backend:** Python sidecar process (owns all serial I/O, `arduino-cli` interaction, storage, and analytics)
- **Frontend ↔ sidecar communication:** local WebSocket (message schema TBD in a future section)
- **Target platforms:** developed on macOS (Apple Silicon); shipped/run on Windows 11 (both lab machines)

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

Secondary/muted text: `Static` `#948FA8` (not a full token, but used consistently enough to name).

**Deliberately matte:** no gradients on the primary accent, no glossy highlights or glow effects on `Pulsar`. Saturation stays low (~30–35%) so the purple reads as a material, not a glow — this is the core stylistic bet of the theme and the thing to protect against scope-creep-by-gradient later.

**Semantic status colors** (derived, used only for state — never decorative):
| State | Hex | Notes |
|---|---|---|
| Connected / Success | `Ion` `#7CC98F` | |
| Warning | `#D9A15C` | Muted amber |
| Error | `#C96C6C` | Muted red — matte, not alarm-red |

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

### 2.6 Iconography

Lucide (already available in this environment's component library) as the practical SF-Symbols analog: consistent stroke width across every icon, outline-only (no mixing filled and outlined icons).

### 2.7 Signature Element

The 6-box hardware status indicator — present in the sidebar per `hardware-interaction.md` §7's out-of-band polling — renders as a small **constellation map** instead of a plain row of status dots: six nodes in a fixed abstract layout, thin `Pulsar` lines connecting adjacent nodes when both boxes are connected and nominal. A line dims or breaks on disconnect; a node turns `Error` red on fault. This is the one place the astronomy metaphor is spent deliberately — it's not decoration, it's the actual at-a-glance system-health readout, doing real work.

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

Per your instruction, only **Debug Mode** and **Settings** get real wiring for v1. The other three get a shared placeholder pattern rather than dead, inert buttons — clicking them should still feel like the app responded, just with an honest "not yet" rather than nothing happening.

### 4.1 Start a Session — *stub, with real gating logic*

- Starting a session **requires an existing cohort.** This is the one piece of actual conditional logic among the three stub sections.
- Convenient consequence of build order: since Cohorts (§4.2) has no real data in v1, the cohort count is always zero — so the hero CTA can honestly render its **empty-state** every time, with no need to fake or hardcode anything. The gating logic is real; it just always resolves the same way until Cohorts is wired.
- Empty-state behavior: hero card shows "Create a cohort to get started" in place of the normal CTA label, and clicking it routes to `/cohorts` instead of `/session/new`.
- Once Cohorts is wired (future work), this becomes a live check against real cohort count rather than a hardcoded always-zero — noted in §6.
- No sidecar calls, no state writes for v1.

### 4.2 Cohorts — *stub*

- Sidebar item + dashboard tile → route `/cohorts`.
- Same `<PlaceholderView>` pattern.

### 4.3 Debug Mode — *wired*

- Sidebar item + dashboard tile → route `/debug`.
- Renders the 6-box console grid exactly as specified in `hardware-interaction.md` §6 (per-box panels, read/send, line-ending selector, state badges).
- On mount: opens the WebSocket connection to the Python sidecar.
- This is the first real end-to-end data path in the app: **sidecar → WebSocket → React state**, feeding both the full Debug Mode view *and* the sidebar's constellation status widget from the same out-of-band polling channel. Building this wires up the signature element for free.

### 4.4 Analytics — *stub*

- Sidebar item + dashboard tile → route `/analytics`.
- Same `<PlaceholderView>` pattern.

### 4.5 Settings — *wired*

- Sidebar item → route `/settings`.
- Needs a real, if minimal, persisted config even at this stage. Proposed fields to start:
  - Default data save directory
  - Backup directory
  - **Arduino Directory** — root folder for sketches/libraries; see `arduino-directory.md` for structure, detection, and error handling
  - Default baud rate
  - Per-box COM port labels/nicknames
  - `arduino-cli` / core path override
  - Reduced-motion toggle
- **Ownership: Tauri-side store** (`tauri-plugin-store`, JSON on disk in the app data dir), not the Python sidecar. Reasoning:
  - Most of these fields (save paths, baud rate, `arduino-cli` path) are exactly the values most likely to be *wrong* when something is misconfigured — and a wrong `arduino-cli` path or bad save directory is a plausible cause of the sidecar failing to start. If the sidecar owned settings, a bad config could lock the user out of the one screen that fixes it. Settings needs to work even when the sidecar doesn't.
  - The Tauri store plugin is simple, well-supported, and gives native OS directory pickers for free from the shell layer — no need for the sidecar to implement its own config persistence/schema/migrations on top of everything else it owns.
  - The sidecar still needs these values at runtime, so the shell **pushes the full settings payload to the sidecar on every WebSocket connect/reconnect, and again on every change** — a one-directional sync (Tauri → sidecar) rather than the sidecar being the source of truth. Simpler failure mode: worst case, the sidecar is briefly running on stale values until the next push, rather than being unreachable entirely.

### Shared: `<PlaceholderView>`

One reusable component covers §4.1, §4.2, and §4.4 — a title, a short explanatory line in the interface's own voice, and (optionally) a disabled preview of what the real view will eventually contain. Building this once effectively "wires" three of the five sections.

---

## 5. Resolved Decisions

| Decision | Outcome |
|---|---|
| App name | **Ephymeris** (§1) |
| Settings ownership | **Tauri-side store**, pushed to sidecar on connect/change (§4.5) |
| Start-a-Session gating | **Requires an existing cohort** (§4.1) |
| Light mode | **Out of scope for v1**, no placeholder toggle (§2.2) |

No open questions remaining as of this revision.

---

## 6. Open Items / TBD

- [ ] Session-setup flow spec
- [ ] Cohort CRUD spec (create/edit/delete/group management)
- [ ] Once Cohorts is wired: replace Start-a-Session's hardcoded always-empty gating (§4.1) with a live cohort-count check
- [ ] Analytics view spec (within-session, across-session, per-cohort)
- [ ] Full Settings schema (fields listed in §4.5 are a starting point, not final)
- [ ] WebSocket/IPC message schema (shared with `hardware-interaction.md`), including the settings-push message shape
- [ ] App icon / wordmark design for Ephymeris

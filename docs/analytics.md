# Analytics

> **Status** · Living spec — **Built and running on real data.** The derivation layer, the four commands, the schema, and the Observatory dashboard are implemented. Driven end to end against the lab's real Remy archive — 306 per-animal files across 50 sessions and 6 animals, all decoded — which required the orphan adoption of §8.1. The frontend has not yet been exercised at that volume.
>
> **Owns** · The Analytics view, the **derived-metric definitions** computed from recorded sessions, and the query surface that feeds them.
>
> **Read with** · [data-saving.md](data-saving.md) (what is on disk, and the live metric definitions these extend) · [cohorts.md](cohorts.md) (the roster and groups the views are organised by) · [ephymeris_v1.0.md](ephymeris_v1.0.md) §2 (canonical for the theme tokens §7 adds to) · [websocket-protocol.md](websocket-protocol.md) (canonical for the commands §9 proposes)
>
> **Still open** · the session raster · statistical testing between groups · export · a real-archive run

**Contents** — [0. Scope](#0-scope) · [1. Three Questions](#1-the-three-questions) · [2. Layout](#2-layout--the-observatory) · [3. Derived Metrics](#3-derived-metrics) · [4. Strategy Space](#4-the-strategy-space) · [5. Learning Curves](#5-learning-curves) · [6. Cohort Heatmap](#6-the-cohort-heatmap) · [7. Palette](#7-palette-additions) · [8. Reading & Caching](#8-reading-decoding--caching) · [9. Wire Messages](#9-wire-messages-proposed) · [10. Schema](#10-schema-changes) · [11. Resolved Decisions](#11-resolved-decisions) · [12. Open Items](#12-open-items--tbd)

> **The numbers this document defines are the scientific output, not a UI detail.** `data-saving.md` §6.5 says the same thing about the live metrics, and holds itself to it. This document extends those definitions to recorded data and is held to the same standard: §3 is the part to get right, and the part to review first.

---

## 0. Scope

Defines the Analytics view — its layout, its three visualizations, and the interaction model that ties them together — plus the **derived-metric definitions** computed from finalized session files, the reading and caching strategy behind them, and the query surface they need.

Does **not** own: the on-disk layout or file schema (`data-saving.md` §1–§5), the live in-session metrics (`data-saving.md` §6.5, which this document extends rather than restates), or the canonical wire schema (`websocket-protocol.md`, into which §9 merges).

---

## 1. The Three Questions

`ephymeris_v1.0.md` §4.4 names three analyses — within-session, across-session, and per-cohort. They are three genuinely different questions, and each has one panel that answers it:

| Question | Asked as | Answered by |
|---|---|---|
| **Within-session** | "How did this animal do today, and when did it change?" | Learning curve at trial resolution (§5) |
| **Across-session** | "Is this animal learning, and how fast?" | Learning curve at session resolution (§5), and the strategy trail (§4) |
| **Per-cohort** | "Who is learning, who is stuck, and did the groups differ?" | The heatmap (§6), all animals at once |

A fourth question is worth naming because the answer is the reason §4 exists at all:

| **What strategy is it using?** | "Is it discriminating, or is it biased and lucky?" | The strategy space (§4) |

An animal at 70% correct looks identical whether it is discriminating imperfectly or responding to one side on most trials and getting the easy half right. A learning curve cannot separate those two; §4's plot separates them by construction.

---

## 2. Layout — the Observatory

**One route, `/analytics`. No sub-routes, no tabs.** Cohort, task, session, and animal are persistent selectors, and the panels react to them.

The **task** selector appears only when a cohort's archive holds more than one Task Profile, and defaults to the dominant one (§4.3). It is not a convenience: a real cohort runs shaping before discrimination, and the profiles are not comparable — a shaping profile declares one condition where a discrimination profile declares two. Every panel is scoped by it. Changing task resets the metric selection, because metrics are declared per task and the outgoing choice usually doesn't exist on the incoming one.

```
┌───────────────────────────────────────────────────────────┐
│ Analytics          ◈ Batch A ▾  [ Task ▾ ] [ Metric ▾ ]   │
├───────────────────────────────────────────────────────────┤
│ SESSIONS      spaced by date — a gap is a real gap        │
│    25  26      27 28                                      │
│  ·  ●  ·        ·  ·  ·                         [ all ]   │
│ ─┴──┴──┴────────┴──┴──┴─                                  │
│  Jul 24        Jul 27                                     │
│  2O-Bdisc_26 · 2026-07-25 · 6 runs · mean P 0.71          │
├──────────────┬────────────────────────────────────────────┤
│ ANIMALS      │ ┌─ Strategy space ─┐ ┌─ Learning curves ─┐ │
│ Group 1      │ │                  │ │                   │ │
│ ■ remy1  .82 │ │      ··╱         │ │       ╱‾‾‾‾‾      │ │
│ ■ remy2  .61 │ │    ·╱            │ │     ╱             │ │
│ Group 2      │ └──────────────────┘ └───────────────────┘ │
│ ■ remy3  .49 │ ┌─ Heatmap · animals × sessions ─────────┐ │
│ ■ remy4  .77 │ │  ░ ▒ ▒ █ █ █   ░ ▒ █ █ █ █             │ │
└──────────────┴────────────────────────────────────────────┘
```

### 2.1 Selection is a filter, not a navigation event

This is the design thesis, and everything else follows from it.

Selecting a session **narrows** every panel rather than swapping the view. Hovering an animal highlights its curve, its heatmap row, and its strategy trail *simultaneously*. Clicking a heatmap cell selects both that animal and that session, and every other panel follows.

That is what lets one route serve all three of §1's questions without tabs, and it is the reason per-animal identity colour (§7.1) is load-bearing rather than decorative: linked highlighting across three panels only works if a reader can tell at a glance which mark is which, in every panel, without a legend lookup.

**Session scope drives what the curves show:**

| Session selector | Learning curves show | Heatmap | Strategy space |
|---|---|---|---|
| `all` | P(correct) per session, across sessions | full | every session, trails drawn |
| one session | rolling P(hit) per counted trial, within it | that column emphasised | that session's points enlarged, prior sessions faded to trail |

### 2.2 The session rail

Sessions are placed along a **real date axis**, not evenly by index. A five-day gap in training renders as a five-day gap, because that gap frequently explains the dip that follows it — and an evenly-spaced strip would hide the one piece of context that makes the dip readable.

The rail is also the browse surface: this is where "browsing sessions" happens, so it is a visualization in its own right rather than a dropdown. Each mark carries the cohort's mean P(correct) for that session, making the rail a sparkline of cohort progress that you also click.

Ordering is by `(date, started_at)`. **Never by `session_number`**, which is free text (`data-saving.md` §10), and never by a lexical sort of folder names — `sessions/paths.py:72-90` documents exactly why, with the year-boundary counterexample.

**The rail is laid out in pixels, not in a stretched `viewBox`.** It scrolls, so its width depends on how much archive there is; scaling a fixed-unit `viewBox` to that width with `preserveAspectRatio="none"` drew every mark as an ellipse that widened as the archive grew. Pixel space also lets each mark be a real focusable button with a hit target larger than the dot it draws.

Two collisions a date axis cannot resolve by itself, and how the rail does:

- **Same-day sessions** share a date and therefore a position — a supported workflow, since a reused prefix appends to the same folder (`data-saving.md` §1). They fan out horizontally around their date, and a day is never drawn narrower than the widest such fan, so one date's cluster can never drift across the next and make a real break look shorter than it was.
- **Dense stretches** would overlap their labels. Per-mark session numbers appear only when the tightest pair can hold them, and date labels thin out on the same principle — the axis stays readable instead of becoming a smear.

A session that recorded nothing is drawn **hollow**, not grey: "nothing to score" and "scored badly" must not look alike. The line beneath the rail names the selected session and says plainly when it has no runs — which is the question a session ended before any box started actually raises.

### 2.3 The animal rail

One row per animal, grouped by the cohort's groups (`cohorts.md` §2), since groups are usually the experimental conditions and the comparison is usually between them. Each row carries the animal's identity colour, a sparkline of its across-session trend, and its latest value in JetBrains Mono.

The rail is the highlight selector. Hover previews, click pins.

### 2.4 States

Follow the house patterns rather than inventing new ones: `Cohorts.tsx`'s `Notice` for not-connected and loading, and `MetricStrip.tsx`'s one-sentence empty state for a cohort that has no sessions yet. The rule from `ConstellationStatus.tsx:62-64` applies with full force here — **when data can't be trusted, show nothing rather than something stale.** A heatmap rendered from a half-loaded index is worse than a spinner.

### 2.5 The session-end landing

Ending a session navigates to `/analytics` carrying `endedSession` in router state (`MissionControl.tsx` → `Analytics.tsx`). Today that renders a confirmation line on a placeholder.

It becomes: **the dashboard opens with that cohort and that session already selected**, the save confirmation riding above as a dismissible banner. The guided flow's last step stops being an acknowledgement and becomes the payoff — you finish a run and immediately see how every animal did, at the one moment when the operator's context and the data are perfectly aligned.

**The arrival always refetches, and it is keyed on the navigation rather than on the cohort.** Both halves are corrections of the same bug. The client cache holds a summary per cohort for the life of the app, and the run that just finished is precisely what that cache predates — so a cohort looked at earlier in the session would land showing everything *except* the session the banner is announcing. And keying the arrival on "no cohort selected yet" meant a different cohort already in view simply won, putting one session's confirmation above another cohort's panels. The refetch drops the cached summary before asking, so the interval shows the reading notice rather than the old numbers, per §2.4.

It deliberately does **not** rescan. For a session this app ran, the run record and the file both exist by the time `sessions.end` returns, so the database-first path already has it and a walk would find nothing new — while §8.1's rule that reconciliation is a deliberate user action exists exactly to keep an expensive archive walk off a view-opening path, on the machine whose data directory is a network share. The one case where the record is genuinely absent is a finalization that lands after the session closed, and the cure for that is the Rescan button, reached deliberately after noticing something missing.

Staleness is also handled away from this path: a finished run invalidates the client cache on `session.animalEnded`, so a dashboard left open on another route can't keep serving a summary the disk has moved past. The event names an animal and a box but not a cohort, so that invalidation is deliberately broad — the cache is only ever an optimization, and nothing refetches until a view asks.

### 2.6 Arriving cold: the cohort landing

Arriving from anywhere *other* than a finished session shows a **cohort picker**, not a dashboard — the same procedural-icon card grid the Cohorts view uses (`cohorts.md` §5), because choosing a cohort to study is the same act as choosing one to manage and this lab already recognises a cohort by that icon.

This replaced auto-selecting the most recent cohort. That put an answer on screen before the reader had asked a question, and buried the control that would change it in a corner dropdown. §2.5's landing is the one exception and stays: arriving *from* a session already carries the cohort, and making that reader pick it again would be asking a question already answered.

### 2.7 The reveal

Data appears rather than blinking into place: the heatmap fills **column by column in session order**, per-animal sparklines draw left to right, and the rewarded-accuracy line draws with them. It replays on the two events that mean the data underneath is genuinely different — a cohort swap and a rescan — and never on a hover or a session selection, which would make the panels twitch every time the pointer moved.

This is not decoration. The heatmap's x-axis *is* time, so filling it in time order says what the axis means before a single label is read.

The reveal is also **armed by visibility**: a panel below the fold holds its initial state until it is actually on screen, then plays once. A line that draws itself where nobody is looking plays to an empty room, and the reader scrolls down to an already-finished chart — which is indistinguishable from no reveal at all. Scrolling away and back does not replay it; only the two data events above do, and a replay triggered while the panel is off-screen again waits to be seen.

> **A line draws on by being wiped, never with `pathLength`** — `components/charts/DrawOn.tsx`. Framer Motion implements `pathLength` by normalising the path to length 1 and animating `stroke-dasharray`, which the browser resolves in *user* space, while `vector-effect="non-scaling-stroke"` — which every chart here needs so a stretched viewBox doesn't distort line weight — paints that dash in *screen* space. An upscaled chart therefore **finishes** its animation holding a dash far shorter than the line it should cover, and settles as disconnected chunks whose gaps fall in arbitrary places rather than at the data's own discontinuities. Measured on the shipped panels: the rewarded-accuracy trend renders at 8.2× horizontally and its finished dash covered 18% of the line; the strategy plane was broken at a perfectly *uniform* 3.52×, so upscaling is the trigger, not non-uniformity. Only the animal rail escaped, and only because it is the one chart drawn smaller than its viewBox.
>
> The wipe also reads better on a time axis, which is the reason to prefer it even where it isn't forced: `pathLength` advances along arc length, so a jagged stretch crawls while a flat one races and the draw never tracks x, whereas a wipe advances uniformly — which is what "draws left to right in session order" actually means. It is also what lets a mark delayed by `x × duration` surface exactly as the edge reaches it, and it composes with `stroke-dasharray`, so a dashed gap bridge reveals on the same clock instead of needing its own fade.
>
> The one panel that cannot use it is the **within-session strategy walk**, whose x is a probability rather than time: a left-to-right wipe would assert a chronology a 2D trajectory doesn't have, and a per-segment reveal is the hundred-elements-per-animal cost that component is built to avoid — its nodes are trials, and there are hundreds. It fades instead, and loses nothing: its gradient already carries the direction of travel.

**Highlighting an animal replays its own history, in session order.** The arrival reveal shows the cohort; this shows one animal, and it is a different question asked deliberately — so it runs **slower** (`HIGHLIGHT_DRAW`, `components/charts/reveal.ts`). An arrival reveal has to get out of the way before the reader can start; a highlight reveal *is* the reading, and the eye has to be able to follow it. Only the hovered animal animates. Every other trail holds still at its dimmed weight, because six lines redrawing at once is the thing the highlight exists to cut through.

On a time axis — the learning curves at either resolution, and the rewarded-accuracy overlay — that is the same left-to-right wipe, just longer. The **across-session strategy space** is the exception, and the interesting one: its x is a probability, so the trail has to be *walked node by node* instead, each session's hop and marker arriving in turn. That is affordable here precisely because only one animal is ever walking and its nodes are sessions rather than trials — a few dozen elements, not a few hundred.

> Each hop is delayed by its **session ordinal**, not by its position among the sessions the animal actually ran. So a trail with sessions missing from the middle *pauses* over the gap rather than closing it up — the walk spends real time where the animal has no data, which is the same honesty the dashed bridge buys in space. It also means the last node always lands at `HIGHLIGHT_DRAW` whatever the trail's length, so two animals' walks are comparable histories rather than a race.

---

## 3. Derived Metrics

Everything here is computed from `ts_data` — a flat `[[code, timestamp_ms], …]` list (`data-saving.md` §5). There are no trials, no accuracy, and no computed metrics on disk; all of it is derived at read time from raw strobe codes plus the task profile that decodes them.

**Nothing here reimplements scoring.** `tasks/metrics.py` already replays a stream offline and is numerically identical to the live run. The derivation layer loads a document, picks a profile, and calls the existing machinery. The parts that are hard are *finding* the files (§8), *deciding which profile decodes them* (§8.2), and *not lying* when a file is absent or a trial count is tiny.

### 3.1 Boundary codes — the easiest thing here to get silently wrong

> **Invariant.** The offline scan must be passed the union of **every** trigger code in the profile, exactly as the live runner does.

`MetricSet.__init__` builds that union (`tasks/metrics.py:109`). But `compute_series` defaults to **only the metric's own trigger** when `boundary_codes` is omitted (`tasks/metrics.py:139`). For any profile with more than one metric those differ, and the difference is not academic:

> A trial where Odor 1 fires, the animal does not respond, and Odor 3 fires next is **excluded** by the live path and **mis-scored** by the offline default.

The animal's later response to Odor 3 would be attributed to the abandoned Odor 1 trial. Every unanswered trial in the session scores wrongly, silently, and the recorded numbers quietly stop matching what the operator watched.

Requirements: one shared `boundaries_for(profile)` helper used by both paths, and a test that replays a recorded stream through the live accumulator and the offline one and asserts they agree.

### 3.2 Two probabilities per metric, never one

| | Definition | Window | Used by |
|---|---|---|---|
| `pWindow` | last value of the rolling series | `windowSize` as authored | Continuity with Mission Control — the last number the operator actually saw |
| `pSession` | same computation, window widened to the whole session | all counted trials | **Every summary**: heatmap cells, both strategy-space axes, cross-session curves |

Widening the window is done by `dataclasses.replace` on the frozen `LiveMetric` (`tasks/profile.py:61`), which reuses the same accumulator, the same forward scan, and the same exclusion rules — so the two differ *only* in window length and cannot drift apart in behaviour.

> **Gotcha.** These two diverge sharply over the first `windowSize` trials. Two panels using different ones under the same axis label is an invisible error, and the most likely bug in this whole document. Every panel's choice is stated explicitly in §4–§6.

`pSession` is the summary statistic everywhere it is a summary: it is less noisy and it is the only one of the two with a defensible sample size. `pWindow` exists so that a session's headline number can be reconciled against what Mission Control displayed while it ran.

### 3.3 Trial counts

- **`counted`** — trials that scored as hit or miss. The series has exactly one entry per counted trial (`tasks/metrics.py:143-149`), so `counted = len(series)` needs no separate counter.
- **`triggered`** — total trials presented, the number of occurrences of `trigger_code`.
- **`excluded`** = `triggered − counted` — the lazy, invalid, and no-response trials that `data-saving.md` §6.5 defines out of both numerator and denominator.

`excluded` is scientifically meaningful and free to compute: a session with 200 triggers and 90 counted is a very different session from one with 200 and 195, at identical P(correct). Surface it.

> **Gotcha.** `MetricValue.n` (`tasks/metrics.py:97-101`) is the **window length**, capped at `windowSize` — not a trial count. Using it as the sample size for a confidence interval on `pSession` would be wrong by an order of magnitude. `counted` is the real count.

The final trial of a session is usually unresolved when the board ends; it correctly lands in `excluded`.

### 3.4 Run-level scalars

- **`totalEvents`** = `len(ts_data)`. Cross-check against the document's own `n_events` and warn on mismatch — a disagreement means a hand-edited or recovery-produced file. Trust `ts_data`.
- **`durationMs`** = last timestamp − first. **Stream-relative**, not wall clock.
- **`wallDurationS`** = `ended_at − started_at` from the run record, when both are present.

Report both durations and do not reconcile them. They legitimately differ: `started_at` is stamped when the runner creates the `ActiveRun` (`sessions/runner.py:165`), while stream `t=0` is the board's own `BF_START_SESSION` — after the DTR auto-reset and the `READY` handshake, hundreds of milliseconds later.

- **`stopReason`** from the document, and `clean = stopReason == "BF_END_SESSION received"` (the literal at `sessions/runner.py:34`).

### 3.5 Uncertainty

Every probability is reported with `counted` beside it and a **95% Wilson score interval**.

Wilson rather than the normal approximation because this data lives at small *n* **and** at *p* near 1 — a trained animal sits around 0.95 — which is precisely where the normal approximation produces intervals extending past 1.0. It is a few lines of arithmetic over `math.sqrt`, so it adds **no dependency**, which matters given the two-dependency policy in `reference.md` §6.

**The sidecar never suppresses.** It reports the value, the count, the interval, and a `lowConfidence` flag (`counted < minCountedTrials`, default 10). Suppression is a *presentation* policy, applied client-side and only where there is nowhere to draw a band:

| Panel | Low-*n* treatment |
|---|---|
| Learning curves (§5) | Wilson band, widening where *n* is small |
| Strategy space (§4) | Point drawn hollow and smaller; trail still passes through it |
| Heatmap (§6) | Cell suppressed to a distinct hatch — no band is possible in a cell |

The division matters: a filtered archive silently lies about whether a session happened. Keeping the value server-side and suppressing only at the point of display preserves the distinction between *"this session was cut short after three trials"* and *"this session never happened"* — which is most of the point of a cohort heatmap.

### 3.6 Edge cases — the exact rules

**Zero counted trials.** Emit `null`, **never `0.0`**. Zero percent and "no trials" are opposite claims about an animal. The heatmap renders the no-data treatment; the strategy trail **skips** the session and draws a dashed gap rather than interpolating a line through a session that produced nothing.

**Profile-less sketch.** Fully supported by design (`data-saving.md` §6.1); `MetricSet(None)` is empty by construction (`tasks/metrics.py:107-110`). Emit `no-metrics` and no metrics. **The run is still listed** — it has a real duration, event count, and stop reason. Do not invent a default metric. It contributes no cell and no point.

**Utility-kind profile.** `kind` is a convention, not a schema gate — the parser reads `liveMetrics` from every profile regardless (`data-saving.md` §6.2). Compute and return them, but mark the run excluded from cohort aggregates by default. Honest either way, and it costs nothing.

**Board disconnected mid-run.** A drop **does** finalize: `IN_SESSION → ERROR` routes into `runner.board_dropped` (`app.py:219-224`), which finalizes with `stop_reason: "board disconnected"`. A complete-up-to-the-drop file exists. **Include it**, surface the stop reason, mark it truncated. A drop at trial 180 of 200 is good data.

This is different from a session row with `status: "aborted"`, which never wrote anything at all and has no runs.

**No file path recorded.** Real today: the run record's file path is `None` when the writer never opened (`sessions/runner.py:69-71`) — the handshake never resolved, or the exclusive open collided (`data-saving.md` §7.1). Emit `missing`.

**File path recorded but absent on disk.** Also real: `finalize` writes `.json` best-effort and only *logs* an `OSError` (`sessions/writer.py:139`). A disk-full at finalization leaves a run record with a path, no `.json`, and a complete `.tsv`. Emit `missing`, and — because this one is actionable — check for the sibling `.tsv` and say so. That is exactly the case the crash-recovery utility (`data-saving.md` §11) exists to fix.

**Two runs for one (animal, session).** Happens on a restart after a board drop, and when a prefix and session number are reused the same day — which `data-saving.md` §1 explicitly supports. **Pivot rule: the run with the most `counted` trials wins the cell, and the cell is marked as having siblings.** Stated here so the frontend does not silently take whichever happened to come last.

---

### 3.7 Pooled accuracy — the honest single number

Alongside each declared metric, a run carries **`overall`**: correct trials over scored trials, pooled across every condition. It is offered first in the metric selector and is what the heatmap, the animal rail and the session rail use by default.

> **Why this exists, discovered by looking at real output.** A single metric cannot show a side bias. An animal that pokes right on every trial scores ~1.0 on "P(R | Odor 1)" and ~0.0 on "P(L | Odor 3)". A heatmap keyed on the first declared metric therefore paints a completely bias-locked animal as one of the *best* in the cohort — which is the exact opposite of what §6 exists to show. Pooled, that animal sits at chance, which is the truth.
>
> This was not in the original design. It surfaced when the first populated dashboard showed a deliberately non-learning animal reading 0.72–0.84 and looking healthy.

Pooled by summing hits and trials, **not** by averaging the two proportions, so a session that scored 90 trials of one condition and 10 of the other is weighted the way it actually ran. It carries its own Wilson interval over the pooled count.

The pooled figure is a **summary, not a condition.** It never becomes a strategy-space axis (§4 needs two real conditions), and it has no within-session series: at trial resolution the conditions interleave, and pooling them into one rolling window would need an accumulator the live path does not have.

---

### 3.8 Trial outcomes — rewarded accuracy vs side accuracy

The declared metrics (§3.1) are **reward-unconditional**: `tasks/metrics.py` scores a `WATER_POKE_L/R` the instant the poke is detected, so an animal that reaches the correct well and releases before the fluid hold clears still scores a hit. That is the right definition for a live discrimination readout — it measures the *choice*, not the consummatory hold — but it is not the question "how often did this animal actually earn water", and one number cannot honestly answer both.

So each run also carries a tally of what happened per trial, classified from the profile's own strobe vocabulary:

| Outcome | Recognised by | Meaning |
|---|---|---|
| rewarded | `FLUID_*` | fluid delivered |
| hold failed | `WATER_UNPOKE_EARLY_*` | correct well, released before the hold — no drop |
| wrong well | `WATER_POKE_ERROR_*` | wrong side |
| no response | administered, none of the above | engaged, never answered |
| aborted | no `ODOR_UNPOKE` | odor port left early, or never poked |

From which:

- **Rewarded accuracy** = `rewarded / administered`. Conservative — a hold failure counts against it.
- **Side accuracy** = `(rewarded + holdFailed) / administered`. The discrimination figure: the correct side was chosen whether or not the hold earned the drop. **Always ≥ rewarded accuracy**, and the gap between the two *is* the consummatory hold-failure rate — a real, separately interesting behaviour rather than noise. Carried on the wire as `pSide`, and surfaced to the reader as **response accuracy** (§6.5) — the UI name says what the figure answers ("did it respond correctly"), where `pSide` says how it is computed.

Three things this gets right on purpose:

- **Administered is the denominator, not trials.** A trial the animal never engaged with is not evidence about discrimination. Aborted trials are reported separately, because 200 trials with 90 administered is a very different session from 200 with 195 at identical accuracy.
- **Matched by anchored name, never by code number.** `data-saving.md` §6 makes the `strobes` map the sketch's own declaration; a bare code means nothing without it. The patterns are anchored (`^FLUID(_|$)`) rather than substrings specifically so `STOP_FLUID_G_R` — which marks delivery *ending* — cannot be counted as a second reward, and so `ODOR_UNPOKE_EARLY` can never satisfy the completed-sampling marker `ODOR_UNPOKE`.
- **A task that declares no reward vocabulary reports `outcomes: null`**, not zeros. "This task has no notion of a reward delivery" and "this animal earned nothing" are different claims, and a shaping profile that scores one condition is the former.

Trials are delimited by the same boundary union as the metrics (§3.1), so an abandoned trial closes at the next odor rather than stealing the next trial's outcome.

---

### 3.9 The same tally, per condition

`outcomes` (§3.8) pools every trial in the run. That answers "what did this animal earn", but not "on which *kind* of trial", and the difference is the whole question a two-condition task exists to ask: a rat that earned 60% overall could be at 95% on one odor and 25% on the other, and the pooled figure is the same number in both worlds.

So each run also carries `conditions` — the identical tally restricted to the trials one declared condition opened. A **condition** is a `liveMetrics` entry, and its trials are the ones its `triggerCode` opened. For GRGL that is odor 1 (answer right) and odor 3 (answer left), which is what makes "how many go-right trials were administered, and how many of those paid out" a field lookup rather than a re-read of the file.

- **Driven off the profile, never off a task's vocabulary.** A profile declaring five conditions gets five entries; one declaring none gets an empty list. Nothing here knows what an odor is.
- **Authored `liveMetrics` order**, the same order §4.2 already treats as load-bearing — so a reader comparing this tile against the strategy space sees the same conditions in the same sequence.
- **A partition, not a second count.** Every trial belongs to exactly one condition, and the entries sum to `outcomes` field-for-field. One classification pass produces both, so they cannot drift apart.
- **A declared condition with no trials is zeroed, not omitted.** "Odor 3 never came up" is a fact about the session. Its rates stay `null` rather than collapsing to `0.0`, following §3.6.
- **Empty — not `null` — when `outcomes` is `null`.** There is no separate claim to make about a task whose vocabulary cannot express an outcome at all.

Two metrics sharing a trigger code legitimately produce two entries over the same trials. The trigger is what delimits a condition; a profile declaring the same trials twice is asking for exactly that.

---

## 4. The Strategy Space

The panel that separates *learning* from *being lucky*.

### 4.1 What it plots

For a profile declaring exactly two metrics, each session-animal pair becomes one point:

- **x** = `pSession` of `liveMetrics[0]`
- **y** = `pSession` of `liveMetrics[1]`

Both axes are "fraction correct for this condition", plotted **as authored**. That gives:

| Position | Meaning |
|---|---|
| Top-right `(1,1)` | Perfect discrimination — correct on both conditions |
| Centre `(0.5,0.5)` | Chance |
| Anti-diagonal, `x + y ≈ 1` | **Pure side bias** — same response regardless of stimulus |
| Bottom-left `(0,0)` | Reversed contingency — also learning, just inverted |

Distance from the anti-diagonal is discrimination strength; position along it is which side the animal favours. Up-and-to-the-right is better, which is the reading everyone has instinctively.

**A chronological trail** connects an animal's sessions, opacity ramping from dim (oldest) to full (most recent), latest session drawn as a larger point. The trail is the learning story: it starts near the bias anti-diagonal and migrates toward the corner over weeks. Visually it is the constellation motif doing analytical work — points and trails in a dark field.

### 4.2 Why not a signal-detection ROC

The textbook framing for this data plots hit rate against false-alarm rate, putting chance on the diagonal. It was **rejected**, and the reason is worth recording so it is not "fixed" later.

That transform requires knowing that one metric's `successCode` and the other metric's `alternateCode` are **the same physical response**. `LiveMetric` (`tasks/profile.py:61`) carries `trigger_code`, `success_code`, and `alternate_code` and declares no relationship whatsoever between the response codes of different metrics. Nothing in a task profile says that `WATER_POKE_R` in one metric is the same port as `WATER_POKE_R` in another — that is a fact about the rig, inferred from a shared integer.

Plotting the values as authored requires no such inference, works for any two-metric profile, and is wrong in no case. The ROC form would be more familiar to a reviewer and occasionally wrong, which is the worse trade.

> **Invariant.** Axis assignment comes from the profile's authored metric order. `liveMetrics[0]` is x, `liveMetrics[1]` is y. Reordering a `task.json`'s metrics silently transposes every historical plot, so authored order is load-bearing and must be treated as part of the profile's identity.

### 4.3 Rules

- **Applies only to a two-metric profile.** With any other count the panel names the profile and its metric count rather than rendering an empty frame.
- **All points on one plot must share a profile hash** (§8.2). A GRGL point and an EZ-variant point on shared axes is a category error, even when both profiles happen to declare two metrics.
- Both coordinates are `pSession` (§3.2). A run where either metric has `counted == 0` produces **no point**.
- Trail order is `(session.date, session.started_at, run.started_at)`.
- Axis labels are the metrics' own `label` strings, so the plot reads correctly for any task without app-side knowledge.
- Chance is marked at the centre and along the anti-diagonal, in Halo, dashed — the same reference-line treatment `MetricChart.tsx` already uses for its 0.5 line.

### 4.4 The within-session walk

§4.1 plots **one point per session**, so a session is an endpoint there and its shape is invisible. An animal that answered the same port for the first eighty trials and then started discriminating lands in the same place as one that was steady throughout — and those are not the same session.

So the plane has a second occupant: the same axes, same reference lines, same region meanings, walked at trial resolution. **The across-session trails render only when the scope is all sessions; selecting one session replaces them with that session's walks.** Two trail types in one frame would be four unlabelled meanings of a line, and the reader has no way to tell a week from an hour.

| | Across-session (§4.1) | Within-session (§4.4) |
|---|---|---|
| One point is | one session | one counted trial |
| Coordinates | `pSession` — the whole-session figure | rolling P at the authored `windowSize` |
| Clock | `(session.date, started_at)` | counted trials across **both** conditions |
| Reads as | learning, over weeks | the strategy actually running, minute to minute |

Rules that are decisions rather than description:

- **The coordinates are the rolling figure, never the whole-session one.** The question is "what strategy is this animal running *right now*", and a running whole-session average is dominated by its own history — it would flatten the very transition the panel exists to show.
- **The clock is counted trials across both conditions**, because that is the only one the two metrics share. It is not wall time (§5 gives the reasons) and not either metric's own index.
- **A point needs both conditions to have scored.** A coordinate and a blank is not a position, so the walk never begins at trial 1.
- **And it needs both windows to hold `minCountedTrials` (§3.5).** A rolling proportion over one trial is exactly 0.0 or 1.0, so an unfiltered walk opens pinned to a corner of the plane and thrashes between the edges for its first few trials. That is an artefact of the estimator that reads as a behaviour — the worst kind of wrong in this panel, since a corner is where the whole plot's meaning is concentrated. The existing "too few trials to read firmly" threshold is reused rather than a fresh number invented. A profile whose authored window is *shorter* than that caps the requirement at its own window size, so a small-window task still gets a walk instead of silently getting none.
- **`n` is the smaller of the two window lengths.** A point is only as trustworthy as the condition supporting it least.
- **Start hollow, end filled**, and the path fades from dim to full along its length — the same direction-of-travel grammar as the across-session trail, so one reading serves both.

This cannot be assembled client-side from the §5 series. Those are indexed by each metric's **own** counted trials, and the conditions interleave, so index *k* of one is not the same moment as index *k* of the other. Pairing them requires replaying the stream with both accumulators fed together, which is why the walk is computed sidecar-side and rides along on `analytics.series` as `trail` — the file is already open and already decoded there, and the panel that wants it is on the same screen as the panels that want the series.

---

## 5. Learning Curves

P(correct) over time, at whichever resolution the session selector implies (§2.1).

| Scope | x axis | y | Source |
|---|---|---|---|
| One session | counted trial index | rolling P(hit) at the authored `windowSize` | the rolling series |
| All sessions | session, positioned by date | `pSession` | one point per session |

One line per animal in its identity colour; the highlighted animal gains weight, the rest drop to a dim opacity. Chance at 0.5, dashed. A Wilson band (§3.5) behind each line, drawn at low opacity so six overlapping bands stay readable.

**The x axis is trial index, not time.** `timestamp_ms` is elapsed since that animal's own start (`data-saving.md` §5), animals within a session start minutes apart, and stream `t=0` trails `started_at` by the handshake (§3.4). Any plot aligning several animals on a shared time axis would be quietly wrong. Cross-animal time alignment is out of scope (§12).

One chart per metric, stacked — a profile may declare several, and `MetricStrip.tsx`'s stacked-row layout is the existing idiom for exactly this.

> **Reuse.** `src/components/sessions/MetricChart.tsx` already implements this chart correctly — unit-space `viewBox`, `preserveAspectRatio="none"`, `vectorEffect="non-scaling-stroke"`, chance line, label row above and metadata row below. It is imported by nothing (`TODO.md` item 20). Generalising it into the shared trend chart this section needs is the natural way to close that item, and gives dead code a real home rather than deleting it.

---

## 6. The Cohort Heatmap

Rows are animals grouped by group; columns are sessions in chronological order; each cell is that animal's `pSession` for that session. It answers "who is learning and who is stuck" across a whole cohort in about two seconds, which no line chart does.

**Columns are scoped to the selected task profile (§2), not to every session the cohort ever ran.** Sessions with no run on that task are dropped from the axis, and the count dropped is stated in the panel header — a filter that silently removes columns is indistinguishable from an archive that never had them. Without this the surface put a shaping column beside a discrimination column on one colour scale, and a change of *task* read as a collapse in *performance*. One session can legitimately appear under more than one task, since a cohort can be shaping some animals while others discriminate; scoped that way, an empty cell means "no run on this task" rather than "did not run", and says so.

The heatmap is also a selector: clicking a cell selects that animal and that session, a row header selects the animal across all sessions, a column header selects the whole session.

### 6.1 Four cell states that must never be confused

| State | Treatment |
|---|---|
| **Scored** | Filled from the diverging ramp (§7.2), value in JetBrains Mono |
| **Below chance** | A *different hue*, not merely a lighter fill — see below |
| **Too few trials** | Distinct hatch, no fill, `n` shown |
| **Absent** — the animal did not run | **Outline only, no fill** |

> **Invariant.** Absent must never render as a low fill. "Didn't run" rendered as a pale cell reads as "got everything wrong", which inverts the meaning of the single most scannable panel in the app.

The chance-level fill sits ΔE 15.9 from the empty-cell surface, so a chance cell and an absent cell are unambiguous side by side. Below-chance getting its own hue rather than a fainter one is the reason §7.2's ramp is **diverging** rather than sequential: below chance is a qualitatively different finding, not a smaller quantity, and frequently means the animal learned the reverse contingency.

### 6.2 Legibility

Values are shown **in the cell**, in mono, at every size the grid permits — with the label colour flipping between Starlight and Void at the ramp's lightness threshold (§7.2), so every bin clears WCAG AA. The row's own summary sits in a fixed right-hand column on the panel surface, where contrast is guaranteed regardless of cell fill, matching `MetricStrip.tsx`'s fixed numeric-column idiom.

---

### 6.3 The session summary

Selecting a session opens it up beneath the cohort views: those *compare* sessions, this one is the inside of a single one. **One card per animal**, not one row — the per-condition counts below need a second dimension, and a row that carries them all is a row nobody can read.

Each card answers, in this order:

| | |
|---|---|
| **Trials · administered · aborted** | the effort header. Administered is every accuracy's denominator (§3.8), so it is stated before any rate. |
| **Per condition** (§3.9) — one row each, in authored order | `administered`, `rewarded`, and that condition's within-session trajectory. This is where "how many go-right trials, and how many paid out" is read off. |
| **Rewarded vs side** | the two accuracies, as one bar, not two. |
| **Outcome composition** | how the administered trials resolved. |

Two things this gets right on purpose:

- **The two accuracies share one track.** Side accuracy is `(rewarded + holdFailed) / administered` and rewarded is `rewarded / administered`, so the second is a **subset** of the first — always ≥, never crossing (§3.8). Drawing them as two independent bars invites reading the difference as a comparison of unrelated quantities; drawing rewarded as a filled span *inside* the side span makes the containment structural, and the remaining segment **is** the hold-failure rate rather than a number the reader has to subtract. That segment carries the hold-failure colour it already has in the outcome bar, so the same behaviour is the same colour in both places on the card.
- **The outcome bar is scaled by administered count**, not normalised per animal: a rat that engaged with half as many trials reads as half a bar rather than a full bar of different proportions. Composition and effort are both part of what happened, and normalising would hide one to show the other.

A trajectory can only show the declared metrics, which are reward-unconditional (§3.8) — an animal can hold a respectable P(R | Odor 1) while earning almost nothing if it keeps releasing the well before the fluid hold clears. That is why the card carries counts and the reward bar alongside the trajectories rather than trajectories alone.

### 6.4 Rewarded accuracy across sessions

A separate panel from the learning curves, deliberately: those plot the declared metrics, this plots what was actually earned, and putting a reward-conditional and a reward-unconditional line on one axis invites reading a gap between them as a trend. It is a cohort-pooled figure per session — summed trials, not averaged proportions (§3.7) — with a 95% Wilson band, and it says `fluid delivered` in the frame so the basis is never in doubt. A session whose administered count is thin draws its point hollow, following §3.5.

Across sessions only. Within one session there is a single pooled number rather than a trend, and §6.3 shows that per animal instead of flattening it to a dot.

Pooled is the resting state, not the only one. The shared highlight (§2.1) reaches this panel too: hovering an animal fades the cohort figure and its band back and overlays that animal's own rewarded line, in its identity colour, on the same session slots — the same question asked of one animal, directly comparable to the cohort behind it. Sessions the animal sat out bridge dashed rather than interpolating (§3.6), and its thin points draw hollow on the same rule as the pooled ones. Nothing is highlighted by default, so the panel still opens on the cohort answer.

This panel and the three below it share one x-slot list — one point per session with at least one outcome tally — so a session sits above itself in all four. §6.5 depends on that most: the gap between its curve and this one is only readable if a session is at the same x in both. A session whose administered count is zero keeps its slot: the rewarded line bridges it dashed rather than interpolating (§3.6), because "ran and aborted everything" is data, not absence.

### 6.5 Response accuracy across sessions

The same panel as §6.4, on the same slots, asking the same question of the **choice** instead of the **drop**: a trial where the animal answered the correct well counts here whether or not it held long enough to earn fluid. `derive.py` already computes it as `pSide` (§3.8) — this is the panel that finally shows it.

**It exists to be read against the panel above it, and everything about it is held identical so that it can be.** Same x slots, same `administered` denominator, same Wilson treatment, same hollow-mark rule, same accent colour — because this line is always the higher of the two, and **the vertical gap between them is the consummatory hold failure rate**. Giving it its own colour would imply the two measure different things rather than the same thing at two strictnesses. The one place the two panels differ is the band: each gets a Wilson interval on its *own* numerator, since the wider proportion is not the wider interval and reusing one band under both curves would overstate the tighter and understate the looser.

Why it earns a panel rather than a second line on §6.4: two lines on one axis invite reading the gap as a trend in a single quantity, which is the confusion §6.4 was split off to avoid in the first place. Stacked, the gap is still measurable by eye but is unmistakably a comparison between two figures.

> **The Squeekstreet archive is the argument for this panel.** Across its 30 sessions response accuracy climbs 0.55 → 0.99 while rewarded accuracy stays flat and even falls, 0.64 → 0.26 → 0.44; the gap widens from 0.09 to 0.60. Read on the rewarded panel alone, that cohort looks like it never learned the task or got worse at it. It learned the discrimination almost perfectly and simply does not hold for the fluid — the opposite conclusion, and one no single panel here could have reached.

### 6.6 Effort across sessions

Every accuracy in the dashboard divides by `administered`, so a steady rewarded line over collapsing trial counts is a very different cohort from the same line over steady ones (§3.8) — and nothing above this panel can tell those apart. One bar per session: total height is the cohort's pooled `trials`, the filled span is `administered`, and the remainder — the aborted trials — draws as an **outline, not a fill**: disengagement is an absence, and a solid block would read as one more outcome category. The y scale is the cohort's own maximum trial count, the one across-session panel where a count axis rather than 0–1 is the honest choice.

### 6.7 Outcome mix across sessions

§6.4 answers "how often was fluid earned"; this answers "and what happened instead". One normalised stacked bar per session — rewarded on the baseline, then hold-failed, wrong well, no response — in the same outcome colours as the session cards (§6.3), so the same behaviour is the same colour in both places. The scientific point is the drift *between* failure modes: a cohort moving from wrong-well errors to hold failures is learning the discrimination even while the rewarded line barely moves.

Normalised to each session's own administered count, deliberately unlike the §6.3 card bars: composition and effort are split across this panel and §6.6 rather than folded into one bar, because side by side each stays legible where a combined bar would hide one behind the other. A session that administered nothing leaves its slot empty rather than inventing a composition.

---

## 7. Palette Additions

`ephymeris_v1.0.md` §2.2 is canonical for theme tokens; this section is the rationale behind what it gains. All values are computed in OKLCH, verified in gamut, contrast-checked against Void `#0B0B10`, and simulated under deuteranopia and protanopia.

> **Context for the change.** §2.2's original six-token palette has no categorical ramp, so six animals could not be six colours and series had to be separated by opacity and dash alone. That constraint was lifted deliberately to make §2.1's linked highlighting work — with three panels cross-filtering, a reader must be able to identify a mark without a legend lookup. **Pulsar remains the primary accent and the no-gradient, no-glow rule is unchanged.**

### 7.1 Series ramp — six categorical colours

`--color-series-1` … `--color-series-6`, anchored on Pulsar as series-1:

| Token | Hex | OKLCH | vs Void |
|---|---|---|---|
| `series-1` | `#8B7EC8` | `oklch(0.635 0.110 291.0)` | 5.53:1 |
| `series-2` | `#229582` | `oklch(0.604 0.102 178.6)` | 5.32:1 |
| `series-3` | `#52B79D` | `oklch(0.713 0.103 173.8)` | 8.13:1 |
| `series-4` | `#9E9FF6` | `oklch(0.737 0.125 282.0)` | 8.18:1 |
| `series-5` | `#CBA23E` | `oklch(0.731 0.125 85.8)` | 8.14:1 |
| `series-6` | `#BE7031` | `oklch(0.619 0.125 56.0)` | 5.19:1 |

Worst-case pairwise separation is **ΔE ≈ 10 under normal, deuteranopic, and protanopic vision**. Chroma stays ≤ 0.125, so the ramp reads as matte beside Pulsar's 0.110. Hues steer clear of the error red (H 21) and warning amber (H 71).

> **Do not "fix" the lightness spread.** An iso-lightness ramp — six hues at identical OKLCH L and C — gives perfectly equal visual weight and stays entirely within the app's cool character. It was built and measured, and **two of its pairs collapse to ΔE 0.9 under deuteranopia**: indistinguishable. Lightness is the only channel that survives dichromacy, so a strictly equal-weight categorical ramp is inherently colour-blind-hostile. The 5.2–8.2:1 contrast spread above is the price, and it is the right one to pay.

**Colour is never the sole channel.** The highlighted series also gains stroke weight, and marks stay distinguishable in greyscale.

**Assignment is stable per animal**, by roster position within the cohort, so an animal keeps one identity across the heatmap, its curve, and its trail. Beyond six animals the ramp repeats, disambiguated by the panel that has row labels — noted in §12.

### 7.2 Diverging heatmap ramp

Seven bins, centred on chance. Quantized rather than continuous for two reasons: readers judge discrete bins far more accurately than a continuous fill, and a continuous ramp necessarily passes through a mid-lightness dead zone where an in-cell label fails contrast against **both** Starlight and Void. Every bin below clears WCAG AA.

| P(correct) | Hex | OKLCH | Label |
|---|---|---|---|
| `< 0.20` | `#D4716F` | `oklch(0.660 0.125 22.0)` | Void, 5.98:1 |
| `0.20–0.35` | `#854A49` | `oklch(0.480 0.080 22.0)` | Starlight, 5.80:1 |
| `0.35–0.45` | `#5A3E3D` | `oklch(0.395 0.040 22.0)` | Starlight, 8.13:1 |
| `0.45–0.55` | `#3D3C44` | `oklch(0.360 0.014 290.0)` | Starlight, 9.24:1 |
| `0.55–0.65` | `#3E5743` | `oklch(0.430 0.045 151.0)` | Starlight, 6.72:1 |
| `0.65–0.85` | `#447250` | `oklch(0.510 0.075 151.0)` | Starlight, 4.73:1 |
| `≥ 0.85` | `#7CC98F` | `oklch(0.770 0.113 151.0)` | Void, 9.92:1 |

**Label rule:** OKLCH L ≥ 0.60 takes a Void label, otherwise Starlight.

The ramp is built from the palette's own anchors rather than invented: the top bin **is** Ion `#7CC98F`, the existing "nominal" token, and the chance bin sits just above Halo's lightness so chance-level performance reads as "nothing happening here."

### 7.3 A finding worth recording

Void, Nebula, Halo, Static and Starlight all sit at **hue 285–295** — the entire neutral stack is tinted toward Pulsar's 291. That is *why* the app reads as one coherent thing rather than a dark theme with a purple accent bolted on, and it is the rule any future token should respect.

---

## 8. Reading, Decoding & Caching

### 8.1 Finding the files — database first, walk on demand

Run records carry a file path, and that is the primary path. It is strictly better than walking the archive: the record also carries `animal_id` (immune to renames), the box, the timings, and the stop reason — none of which a filename gives you.

But it is not *complete*. Files exist that no record points at: runs finalized while no session was active (`app.py:756-758` skips the write entirely in that case), a crash between the file write and the database commit, and files restored from the backup mirror or copied from the other lab machine.

So a **walk exists, but only under an explicit user action** (§9's rescan), matching how `sketches.refresh` and `backup.syncNow` already handle expensive reconciliation. Adopted orphans get a deterministic synthetic id so re-running is idempotent, and they **never** get fabricated session rows — those would corrupt session-number suggestion and the same-day warning.

Orphan matching degrades honestly: a folder name yields prefix, number, and date via `parse_session_folder` (which reads both the ISO and legacy `MM_DD_YY` spellings — the walk is the only code path that ever sees a legacy name). The document's `rat` field is an animal *name*, matched case-insensitively against the roster; on no match the run is kept unattributed rather than guessed at. **Renames break name matching permanently**, which is the strongest argument for database-first.

#### What adoption actually stores

Adopted runs live in their own `adopted_runs` table — not in `sessions`, not in `session_animal_runs`. Rows there carry only what a name can honestly supply: the matched `animal_id`, the file path, the prefix, session number and date from the folder, and the start time from the file's `HHMMSS` suffix. **The box number, stop reason and end time stay unknown**, and `boxNumber` is `null` on the wire rather than a plausible default — an adopted run genuinely does not know which box it ran on.

The summary and `sessions.list` then merge two sources: recorded runs and adopted ones, plus **payload-only synthetic sessions** grouped by `(prefix, number, date)`. Those synthetic sessions have stable ids (derived from the same triple) so a frontend selection survives a refresh, and they exist only in the response — nothing is written to `sessions`.

This is the *only* path by which a pre-Ephymeris archive reaches Analytics, so it has to cope with a layout this app never wrote:

| Legacy shape | Handling |
|---|---|
| Format folders named `behavior_json` / `recovery_tsv` (underscores) | The walk reads both spellings; `sibling_tsv` follows whichever layout it found, so a missing-`.json` report still says "recoverable" correctly |
| Session folders dated `MM_DD_YY` | `parse_session_folder` reads both spellings and normalizes to ISO at adoption, so the merged session axis sorts correctly |
| A hand-made prefix-grouping level (`The Remy's/2O-Bdisc/…`) | One of the shapes the walk reads — see **the walk finds format folders by name, not by depth** below |
| **Session folders straight under the cohort, with no grouping level** (`Squeekstreet Syndicate/00_01_shaping_gr_06_17_26/…`) | Same rule. A fixed two-level glob found **zero** of that archive's 444 files, which is why depth is no longer assumed |
| **Non-data folders beside and inside the format folders** (`00_session_analytics/`, `behavior_json/analytics/`) | A format folder's data is exactly its direct children, and the walk stops at one |
| **The session number written first** (`00_01_shaping_gr_…`, the inverse of this app's `<prefix>_<number>_<date>`) | `parse_session_folder` looks for a *numeric* token rather than a positional one — trailing first, then leading. Reading it positionally reported the prefix as `00_01_shaping` and the number as `gr` |
| **One folder typed with hyphens** among underscored siblings (`18-19-shaping-gr_…`) | Parsed and reported **as written**. Folding `-` to `_` would also merge `2O-Bdisc` with `2O_bdisc`, two real and distinct prefixes in the Remy archive; the tidy-up, if wanted, is a rename on disk and is the operator's to make |
| `sketch` recorded as a human label, not a folder name | Resolved through the profile's declared `legacyNames` (`data-saving.md` §6.7) |
| **A typo in one document's `rat` field** (`HmM103` beside a filename reading `HM103`) | Falls back to the animal the *filename* names — see **two recordings, not a guess** below |
| **AppleDouble sidecars** (`._name.json`) | Skipped. macOS writes one beside every real file when copying to a filesystem that can't hold its metadata — a USB stick, a share. They contain a resource fork, not JSON, so each would otherwise surface as an "unreadable" run that never existed. The real Remy archive holds **454 of them against 586 real files**: left in, junk would have been the majority of what the walk reported |
| **A consolidated copy of every session** beside the per-prefix originals (`ALL/`) | Deduplicated by run identity — see below |

**The walk finds format folders by name, not by depth.** This app files sessions under a prefix folder, but the lab's archives disagree about that level: one has it, another puts session folders straight under the cohort, and nothing stops a per-year level appearing next. Matching `behavior.json`/`behavior_json` by name wherever it sits reads all of those in one pass, and `session_folder_of` stays correct without knowing the depth because it is defined relative to the *format* folder rather than to the cohort root. A cap on the descent exists only because a cohort's data folder is user-settable and could be pointed at a drive root.

The scoping rule is unchanged and is what makes this safe: **a file is only data if it sits directly inside a format folder.** That is the sole thing standing between the archive walk and every stray `.json` on a shared drive, and it also disposes of the report folders real archives keep — `00_session_analytics/` beside the format folders, `behavior_json/analytics/` inside one — as a consequence of the rule rather than as a list of names to avoid.

A directory the walk can't read costs a warning and its own contents, never the cohort. **A bad directory is data too** — the same call §8.3 makes for a bad file, one level up. Previously a single permission bit anywhere in the tree returned an empty list for the whole archive, which is indistinguishable from "there's nothing here".

**Two recordings of the animal, not a guess.** A run's animal is written twice at finalization: into the document's `rat` field and into the filename. The lab's Squeekstreet archive has one file where the first is `HmM103` and the second is `HM103` — and with only the document consulted, that run vanishes from HM103's history, which reads as *the animal didn't run that day*. A hole that looks like data is worse than the typo.

So when the document's name matches no animal, the file stem is tried — and this is not the guessing this section rules out elsewhere. The stem must be exactly what `data-saving.md` §2 prescribes, `<animal>_<the session folder the file is actually sitting in>_<HHMMSS>`, checked against the folder on disk rather than assumed; a file that doesn't follow the convention contributes nothing. The token that survives that must still match a roster name exactly and case-folded, the same test the document's field had to pass. The document always wins where it matches, no match still means unattributed, and `RescanOrphan.animalSource` reports which recording was used — a correction the operator can't see is one they can't check.

**Duplicate copies are one run, not two.** A hand-managed archive commonly keeps a rolled-up copy of everything alongside the per-prefix folders; in the real Remy archive **290 of 296 runs exist twice**. Adopting both would silently double every animal in the heatmap and put two points per session on every curve — wrong numbers that look plausible, which is the worst failure available.

Identity is the **file stem**, not the path: `<animal>_<prefix>_<number>_<date>_<HHMMSS>` is exactly animal-plus-session-plus-start-time, and the `HHMMSS` is already what stops same-day reruns from colliding (§2 of `data-saving.md`). Two files with that stem *are* the same run wherever they sit.

Which copy survives is decided by **content, not walk order**: a copy whose document names its `sketch` can be decoded and one that doesn't cannot, so the richer one wins, with the path breaking ties for determinism. This is not hypothetical — in the real archive 30 runs carry `sketch` only in the consolidated copy, so "keep the first one found" would have discarded the only usable version of each. The count of skipped duplicates is reported on the rescan result rather than swallowed, because a file count that silently halves is the kind of thing that makes an operator doubt the whole panel.

> **The synthetic run id is keyed on that identity, not on the path** — and that distinction is load-bearing rather than stylistic. Which copy `_prefer` picks can legitimately change between scans, so a path-keyed id would mint a *second* row for a run that already had one and leave both in place: exactly the double-counting the deduplication exists to prevent, reintroduced by the mechanism meant to make rescanning idempotent. Caught by re-running the walk twice against the real archive, where the row count went 296 → 297.
>
> For the same reason, preference is judged **only on what the document says**, never on whether that sketch currently resolves. Resolution depends on settings that change between scans; letting it pick the winner makes a run's recorded path flip back and forth for reasons that have nothing to do with the data.

> **Correcting the name parser moves synthetic *session* ids; it does not move run ids.** The synthetic session id is derived from `(prefix, number, date)`, so an archive the old positional split read wrongly now groups under different ids. Adopted **run** ids are untouched — they hash the file stem, which no parser change reaches — so `INSERT OR REPLACE` still lands on the same rows and the 296 → 297 failure above cannot recur through this. Nothing persists a synthetic session id either, so no stored selection can dangle. An already-adopted archive keeps its old labels until its next rescan, which is when `adopted_runs` picks up the corrected prefix and number. Verified by re-running both real archives through the old and new splits: **Remy's 71 session-folder names split identically** (and its 428 files are found identically), while all 30 of Squeekstreet's changed.

**A sketch name is resolved when a run is read, not when it is adopted.** The path stored at adoption is a cache of that lookup, never a fact about the run. Freezing it means a cohort adopted while the Arduino Directory was unset or unreachable stays permanently undecodable until someone thinks to rescan — whereas resolving at read time lets a corrected directory take effect on the very next summary. Verified against the real archive: with the directory removed the archive read 0 of 296 scored, and restoring it returned 295 of 296 with no re-adoption.

**A data folder that isn't there is reported, not treated as an empty archive.** A cohort pointing at an unplugged drive or a volume that re-lettered otherwise returns a perfectly well-formed empty result, which reads as "this cohort has no data" when it means "I can't see where its data is". `analytics.rescan` returns `folderMissing` and the path; `analytics.summary` emits a `data-folder-missing` warning, which the Observatory renders separately from run-level warnings — calling it "1 run could not be read" would point the reader at exactly the wrong thing.

**Everything an archive walk decodes is a fallback decode** — there are no snapshots for runs recorded before this app existed — so `profileSource` is `sketch-current` for all of them. That fallback profile is still *stored* content-addressed, because otherwise a comparability group (§4.3) has no `taskName` to label itself with and the whole panel reads as unlabeled. Storing the blob does not promote the run's trust level; how much a decoding can be trusted is `profileSource`, and it stays `sketch-current`.

When a run scores nothing, its `detail` says why — and where the cause is an unresolvable sketch it **names the sketch the run asked for**. "No metrics" alone is indistinguishable from a genuinely profile-less sketch and gives the operator nothing to act on; naming it turns a blank panel into a one-line fix.

### 8.2 Which profile decodes a run — three states, not two

A recorded run must be decodable years later. `data-saving.md` §6 profiles live beside the sketch, outside the data directory, and can be edited, renamed, or removed.

**Going forward, the resolved profile is snapshotted with each run at finalization**, content-addressed so identical profiles store once and comparability (§4.3) becomes an indexed equality test rather than a blob comparison. The write path already has the profile in scope where the run record is written.

For everything recorded before that, decoding falls back to reading the current `task.json` — and that fallback has **two** outcomes, not one:

| State | Meaning | UI |
|---|---|---|
| `snapshot` | Decoded with the profile the run actually used | Trustworthy, unmarked |
| `sketch-current` | Decoded with today's `task.json` at the recorded sketch path | **Flag: profile may have changed since** |
| `unavailable` | Sketch path renamed, moved, or the Arduino Directory re-pointed | **Flag: cannot decode** |

A malformed `task.json` on the fallback path degrades to `no-metrics` rather than raising, exactly as session mapping already does today.

### 8.3 Caching

**Persist summaries; memoize series in memory.**

Summaries survive a sidecar restart, which happens on every app launch since there is deliberately no auto-respawn (`websocket-protocol.md` §8) — without persistence, every launch re-parses and re-replays the whole archive. Series are **not** persisted: they are roughly 3.6 MB of floats for a 180-run cohort, inside a database the backup manager copies wholesale to a possibly-networked target on a 5-second debounce (`data-saving.md` §8.3). A small in-memory LRU covers the real access pattern, which is a handful of runs at a time.

Cache key: file path, mtime, size, profile hash, and a **codec version**.

> **The codec version is the important one.** Without it, a fixed bug in the derivation keeps serving numbers computed by the old definition, forever, with no symptom. It is a module constant, bumped whenever the metric math changes, and it also covers fallback-decoded rows whose meaning changes when a `task.json` on disk changes.

**Every field of that key is answerable from a `stat`, so a cache hit opens nothing.** This is worth stating because it was not always true: the indexing pass used to read and parse each file and only *then* build the key and compare it, which meant the persisted cache saved the arithmetic and none of the I/O. On a 444-run archive that was 30 MB pulled across the wire on every dashboard open, on the machine whose archive lives on a network share — the case the §9 progress event exists for. Reading is now strictly behind the miss: `stat_run` settles the key, `parse_run` runs only if it doesn't match. Measured on that archive, a warm summary went from ~440 ms to ~10 ms and from 30 MB to zero bytes. The vanished-file branch deliberately stays *ahead* of the comparison, because a file that isn't there has no stat to build a key from.

**Profile resolution is memoized per pass, and deliberately not across passes.** A whole archive is usually one or two sketches, so without a memo every run pays its own `task.json` read, sha256 and `INSERT OR IGNORE`. Making that memo outlive the pass would be a regression rather than a further optimization: §8.1 resolves a sketch at *read* time precisely so a corrected Arduino Directory or an edited `task.json` takes effect on the very next summary, and a longer-lived cache freezes exactly what that rule keeps thawed. The `legacyNames` lookup is indexed once per Arduino Directory scan for the same reason at the other end — answering it per run re-read every `task.json` in the directory each time, 2220 reads for the 444-run archive against 5 now.

**The rescan and the summary that follows both read every file, and that is kept.** Avoiding it means holding a whole archive's parsed documents in memory between two independent wire commands, in the process that must never stall a session. It looks like free money and isn't.

**Never delete a cache entry because a file vanished** — mark it stale and keep serving it. A briefly unreachable network share must not erase history from the heatmap. This is the same principle the backup mirror already holds to (`data-saving.md` §8.1: the mirror is additive).

A corrupt file caches its **negative** result under the same key, so it is not re-parsed on every open, and surfaces as a warning. **A bad file is data, not an error** — one unreadable `.json` must never blank a year of history.

### 8.4 Never at the expense of a session

> **Invariant, inherited from `data-saving.md` §8.** No analytics operation may slow, stall, or fail a running session.

One indexing job at a time behind a lock, so two clients or a double-click cannot launch two archive walks. Reads are **sequential in a single worker thread, not a pool** — six boxes are `fsync`ing per strobe, and a thread pool would multiply disk contention against the write-ahead log that carries the durability guarantee. Consider refusing, or at least warning, on a rescan requested while boxes are running.

Runs are handed to that worker in **chunks**, not one at a time. This strengthens the rule rather than bending it: the runs inside a chunk are still read one after another on one thread, and chunking *reduces* the number of distinct executor threads the pass touches — it only stops the loop paying a thread hop per run, which at archive scale costs more than the reads do once the cache is warm. The chunk is small enough that a batch of misses can't hold the event loop off a live `port.output` flush.

Persisted cache writes go in **one transaction per job**. Writing them as individual commits would mark the database dirty repeatedly and trigger a whole-file copy to the backup target each time (`data-saving.md` §8.3).

---

## 9. Wire Messages (proposed)

**To be merged into `websocket-protocol.md`, which is canonical.** Four commands, one event, **no new error codes**.

The granularity follows from §2.1: selecting a cohort makes **one** summary call, and every subsequent session or animal selection filters that payload client-side. The heatmap and the strategy space are literally the same data — a cohort-wide table of per-run scalars — so one command serves both. Per-session calls would mean one round trip per column to build a single picture, re-fetched on every selector change.

| Command | Args | Result |
|---|---|---|
| `sessions.list` | `{cohortId, includeAborted?}` | `{sessions: [SessionListItem]}` |
| `analytics.summary` | `{cohortId, sessionIds?, animalIds?, minCountedTrials?}` | the cohort table — sessions, animals, run summaries, profile groups, counts, warnings |
| `analytics.series` | `{runIds: [], mode?, metricIds?}` | `{series: [RunSeries], warnings: []}` — each `RunSeries` carries `metrics` and the §4.4 `trail` |
| `analytics.rescan` | `{cohortId, adoptOrphans?}` | `{scanned, adopted, orphans, cohortId}` |

| Event | `data` |
|---|---|
| `analytics.progress` | `{cohortId, phase, done, total}` |

Notes that are design decisions rather than description:

- **`sessions.list` is a session primitive, not an analytics command**, and belongs in the `sessions.*` family — session history is independently useful. It must **never touch disk**, so the selectors populate instantly while the summary is still being computed. It returns a chronological `ordinal` computed from `(date, started_at)`; free-text session numbers are labels, never an axis.
- **`analytics.series` is plural in `runIds`** so "all six animals in this session" and "this animal across ten sessions" are each one call. This is the only command returning arrays and therefore the only place an N+1 could arise. Cap the list server-side. Do **not** decimate server-side — a downsampled learning curve is a scientific claim, and that belongs to the charting layer.
- **Run summaries are a flat list, not a dense matrix.** A matrix has nowhere to put two runs for the same animal and session, which really happens (§3.6). The frontend pivots by the rule in §3.6.
- **`analytics.progress` earns its place against the client's default 15 s reply timeout.** The first summary after upgrading is a cold index of every historical run, every one of which also takes the slow fallback-decode path. Raise the per-command timeout *and* emit progress — on a network-mounted data directory that is the difference between "working" and "hung." Publish on phase change and every N files, following `backup.status`'s discipline, not per file.

Deliberately **not** commands: across-session P(correct) (derivable from the summary — a second command would be a second, drifting definition of the same number), per-animal cross-session queries (same payload, client-side filter), and cohort/roster listing (`cohorts.list` and `cohorts.get` already serve it).

---

## 10. Schema Changes

### 10.1 The migration prerequisite — **built**

> **Was the highest-severity item in this document, and it was not an analytics bug.** It is fixed, and it landed alone as a no-behaviour-change commit so it could be verified against a real v2 database on its own.

`Database.connect` used to run `executescript(SCHEMA)` — every statement `CREATE TABLE IF NOT EXISTS` — and then stamp `PRAGMA user_version = SCHEMA_VERSION` **without ever reading the existing value**. There was no migration branch.

New *tables* were therefore fine, which is why it never bit: every schema change so far had added tables. New *columns* would have been silently skipped on an existing database, because `CREATE TABLE IF NOT EXISTS` leaves the existing table untouched — while `user_version` was bumped regardless. The database would then **claim** the new version while missing the column, and the next query would raise `OperationalError` on every session finalization, on a lab machine, mid-run.

`cohorts/db.py` now reads the version first, applies ordered `MIGRATIONS`, and commits once. `tests/test_migrations.py` covers it in 12 cases, pinning the v1 schema as a literal fixture — importing the current schema and mutating it would test today's code against itself and drift the moment someone edits `db.py`.

Four properties worth knowing before adding a migration:

- **Freshness is decided by whether `cohorts` exists, not by `user_version`.** A file from a build predating versioning reports 0 while holding real tables; trusting that 0 would be the same silent failure in a different costume. Such a file is treated as v1 so every migration applies.
- **`add_column` is idempotent**, guarded on `PRAGMA table_info`. A migration interrupted by a power loss or a kill during startup must be safe to re-run, not fatal on the next launch. New columns must be nullable or carry a constant default — SQLite cannot add a `NOT NULL` column without one.
- **Startup commits at most once**, with a test asserting it, because each commit marks the database dirty for backup (`data-saving.md` §8.3).
- **A newer database still opens**, with a loud error rather than a refusal. Every change is additive, so extra tables and columns are inert to an older build, and refusing to start would strand a lab machine that merely ran an older installer.

`MIGRATIONS` is empty today — there is nothing to migrate yet. The tests drive the branch directly by registering one, since normal use will not exercise it until the first real column lands, which is exactly when a latent bug would surface.

**Adding a column requires both halves:** `SCHEMA` updated to the final shape *and* a `MIGRATIONS` entry. Either alone leaves one class of database wrong.

### 10.2 What analytics adds

`SCHEMA_VERSION` 2 → 3:

| Change | Purpose |
|---|---|
| `task_profiles` table | Content-addressed profile snapshots (§8.2). Deduplicates identical profiles to one row and makes comparability an indexed equality test |
| `run_metrics_cache` table | Persisted summaries (§8.3). **No foreign key on the run id** — adopted orphans have no run record |
| `adopted_runs` table | Files the archive walk matched to an animal (§8.1). Deliberately separate from `sessions`/`session_animal_runs`; no foreign key on `animal_id`, for the same reason as below |
| `session_animal_runs.profile_hash` column, nullable | The snapshot link. `NULL` **is** the "recorded before snapshots existed" flag the UI needs |
| Index on `session_animal_runs(animal_id)` | Closes the full scan on per-animal cross-session queries |
| Index on `sessions(cohort_id, date)` | Makes the chronological session axis an index-ordered read |

> **Invariant.** Add the index on `animal_id`; **never** add a foreign key on it. `cohorts.update` deletes and re-inserts the entire animal set wholesale on every roster edit (`cohorts/repository.py:127-128`). With `ON DELETE CASCADE`, a single rename would destroy every historical run in the cohort. The missing foreign key noted in the schema is load-bearing, not an oversight.

This also changes `SessionAnimalRun`'s payload shape, which the contract test will **not** catch — it checks names, not shapes (`TODO.md` item 8).

---

## 11. Resolved Decisions

| Decision | Outcome |
|---|---|
| View spec scope | **Spec first, no code.** The derived-metric definitions are the scientific output and deserve the same treatment `data-saving.md` §6.5 got |
| Navigation | **Single route, persistent selectors** (§2). Selection filters; it never swaps views |
| Visualizations | **Strategy space, learning curves, cohort heatmap.** The session raster was considered and deferred (§12) |
| Strategy-space axes | **Metric values as authored**, not a signal-detection ROC — the profile carries no declaration that two metrics' response codes are the same physical port (§4.2) |
| Historical decoding | **Snapshot the profile at finalization**, with a three-state fallback for older runs (§8.2) |
| Summary statistic | **`pSession`** for every summary; `pWindow` retained only for continuity with Mission Control (§3.2) |
| Low-*n* handling | **Wilson intervals on curves, suppression on the heatmap.** The sidecar never suppresses; presentation does (§3.5) |
| Palette | **Categorical ramp plus a diverging heatmap ramp** (§7). Pulsar stays the primary accent; the no-gradient, no-glow rule is unchanged |
| Ramp lightness spread | **Accepted deliberately.** An iso-lightness ramp collapses two pairs to ΔE 0.9 under deuteranopia (§7.1) |
| Heatmap ramp | **Quantized, seven bins, diverging on chance.** Continuous fails in-cell label contrast at mid lightness (§7.2) |
| Session-end landing | **Preselect the session just finished** (§2.5) |
| Query granularity | **One summary call per cohort**, filtered client-side (§9) |
| Heatmap default metric | **Pooled accuracy** (§3.7), not the first declared one — a single condition cannot distinguish learning from a side bias |
| Strategy-space profile choice | **The cohort's most-populous profile group.** Runs on other profiles are not plotted alongside (§4.3) |
| Series payload | Ships `n` per point alongside the values — the window length, which is the sample size a band needs |
| Index creation order | Indexes are applied **after** migrations, in their own block. An index on a column a migration is adding fails on exactly the databases that migration exists for |
| Cache scope | **Persist summaries, memoize series.** Series in the database would inflate every backup forever (§8.3) |

---

## 12. Open Items / TBD

- [x] ~~The §10.1 migration branch~~ — **built and shipped alone**, `tests/test_migrations.py`, 12 cases
- [x] ~~The rest of this document~~ — **built.** `analytics/` in the sidecar, `lib/analytics/` + `components/analytics/` in the frontend, covered by `test_analytics_derive.py` and `test_analytics_service.py`
- [x] ~~**Not yet run against the lab's real archive.**~~ — **done.** Driven against the real Remy archive: 306 files, 50 sessions, 6 animals, 306 decoded. Real data differed from synthetic in exactly the ways synthetic could not anticipate, and every one of them was in the *finding* layer rather than the maths: no run records at all, `behavior_json`/`recovery_tsv` folder names, `MM_DD_YY` dates, a hand-made prefix level, and `sketch` recorded as a human label. §8.1 and `data-saving.md` §6.7 are the result. The derivation layer itself needed no change
- [ ] **The frontend hasn't been driven at real-archive volume.** The sidecar side is verified; the Observatory's three panels have only ever rendered the 18-session synthetic set. 50 sessions × 6 animals is where the heatmap's density, the session selector, and the six-colour ramp's repeat (§12) actually get tested
- [ ] **A pooled-accuracy series for the within-session view.** §3.7's pooled figure appears only across sessions: at trial resolution the conditions interleave, and pooling them into one rolling window needs an accumulator the live path doesn't have. Worth building if the per-trial pooled curve turns out to be wanted
- [ ] **The session raster / event timeline** — every strobe as a tick on a time axis, rows by strobe name. Considered and set aside for this pass, not rejected: it is the only view that surfaces a session that went *wrong* rather than badly, and the within-session question is currently answered only at trial resolution. Response latency (trigger→response, straight from the timestamps) and trial rate over session time belong with it
- [ ] **Series colour beyond six animals.** The ramp repeats; a cohort larger than six running in one group would reuse hues. Panels with row labels disambiguate, the strategy space does not
- [ ] **Statistical testing between groups.** The data model supports it, but a test needs a stated hypothesis per experiment — which the app does not currently record anywhere
- [ ] **Export** — CSV of the summary table, and figure export from any panel. Almost certainly wanted; entirely unspecified
- [ ] **Cross-animal time alignment** is out of scope by §5's reasoning. Revisit only if a real question needs it, and only with the handshake offset handled honestly
- [ ] **Orphaned archives from deleted cohorts** are unreachable — cohort delete removes the record but never the files (`cohorts.md` §9), and the walk needs the record's data folder to find them. Out of scope; noted so it is not rediscovered as a bug
- [ ] **Payload shapes here are the largest on the wire and are unguarded** by the contract test (`TODO.md` item 8). A field added on one side and forgotten on the other passes every test today
- [x] ~~**A second lab archive was invisible to the walk.**~~ — **fixed.** A cohort whose session folders sit straight under the cohort root scanned **0 of 444 files**, because the walk's depth was hard-coded to one prefix level; its folder names also split wrongly (number-first) and one document's `rat` field carried a typo. Same lesson as Remy, now twice confirmed: **every failure was in the finding layer, none in the maths.** §8.1 is the result — format folders are matched by name at any depth, the number is found by being numeric rather than by position, and the filename is a second recording of the animal. Result on that archive: 444 scanned, 444 adopted, 30 sessions, 12 animals, 444 decoded, zero warnings, and Remy byte-identical
- [ ] **`analytics.series` has no in-memory LRU.** §8.3 specifies one; the sidecar doesn't implement it, and the only series caching is client-side. Noted so the gap is registered rather than rediscovered
- [ ] The archive walk (§8.1) and the crash-recovery backfill (`data-saving.md` §11) need the same file walker and the same both-date-format parsing. **Build them to share one**, whichever lands first — §8.1's walker is now the depth-tolerant one to reuse

---

**Next:** back to the [documentation index](README.md) · [Open items register](TODO.md) · [Engineering reference](reference.md)

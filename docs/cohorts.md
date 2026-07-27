# Cohorts

> **Status** · Living spec — **Built and verified.** Data model, SQLite persistence, browser UI, procedural icons, the create/edit flow, Auto-Balance, data-folder resolution, and archive/delete are all live.
>
> **Owns** · The Cohort → Animal → Group data model, its persistence, the Cohorts tab, and the procedural cohort icon.
>
> **Read with** · [starting-a-session.md](starting-a-session.md) (runs boxes against this model) · [data-saving.md](data-saving.md) (writes beneath the `dataFolder` resolved here) · [websocket-protocol.md](websocket-protocol.md) (canonical for the commands §10 proposed)
>
> **Still open** · three small editor rough edges (§12)

**Contents** — [1. Data Model](#1-data-model) · [2. Validation](#2-validation-rules) · [3. Persistence](#3-persistence) · [4. Browser UI](#4-cohort-browser-ui) · [5. Procedural Icon](#5-procedural-icon-generation) · [6. Create / Edit](#6-create--edit--manage-flow) · [7. Auto-Balance](#7-auto-balance--group-suggestion-tooling) · [8. Data Folder](#8-data-folder-resolution) · [9. Archive / Delete](#9-archive--delete-semantics) · [10. Wire Messages](#10-wire-messages-proposed) · [11. Resolved Decisions](#11-resolved-decisions) · [12. Open Items](#12-open-items--tbd)

**First of three interdependent documents** — Cohorts → Starting a Session → Data Saving. The other two consume the model defined here.

---

## 0. Scope

This doc defines the Cohort/Animal/Group data model, its persistence, the Cohorts tab UI (browsing, creating, editing, archiving), and the procedurally generated cohort icon. It does not define how a session actually runs against a cohort (next doc) or how session data gets written to disk (doc after that) — those consume what's specified here.

---

## 1. Data Model

```
Cohort {
  id: uuid
  name: string                    // unique among active (non-archived) cohorts, see §2
  animals: Animal[]
  groups: Group[]                 // always ≥ 1 — see §2
  dataFolder: string              // absolute path, resolved once at creation — see §8
  iconSeed: id                    // the icon is derived from the cohort id itself, nothing extra stored
  createdAt, updatedAt: timestamp
  archivedAt: timestamp | null    // soft-delete, see §9
}

Animal {
  id: uuid
  name: string                    // unique within the cohort
  boxNumber: 1–6 | null           // standing/default box assignment; nullable, see §2
  groupId: uuid                   // every animal belongs to exactly one group
  sex: "M" | "F" | "unknown" | null   // enum rather than free text — needed for sex-balanced grouping, §7
  idNumber: string | null         // tag/ear-notch/RFID/etc. — kept as free text since ID schemes vary by lab
  notes: string | null            // freeform
}

Group {
  id: uuid
  name: string                    // user-defined, or auto "Group 1" / "Group 2" if left blank
  order: int                      // run order for consecutive execution — consumed by the session-start doc
}
```

A cohort can be created with zero animals and populated over following days — real lab setup is rarely a single sitting. Whether Starting a Session requires at least one populated, box-assigned group is that doc's gating concern, not a constraint enforced here.

---

## 2. Validation Rules

- **Cohort name** unique among active (non-archived) cohorts. Archived cohorts don't block reuse of a name.
- **Animal name** unique within its own cohort (not globally).
- **`boxNumber`** is an abstract slot, `1`–`6`, validated only against that fixed range — **not** checked against which physical boards happen to be bound in Settings right now. A cohort can be fully configured before any hardware is even connected, and box bindings can change independently of cohort definitions. This decoupling is deliberate.
- **`boxNumber` uniqueness is scoped to the group, not the cohort.** Two animals in *different* groups can share `boxNumber: 3` — groups run consecutively (§3, Groups), so the same physical box slot is legitimately reused across them. Two animals in the *same* group cannot share a box number. Animals with `boxNumber: null` don't collide with anything.
- **Groups always exist, even implicitly.** If the user never creates an explicit group, all animals belong to a single default group created transparently. This keeps "grouped" and "ungrouped" cohorts the same code path rather than a special case — a cohort with 3 animals and 3 boxes just happens to have exactly one group.

### Groups, concretely

Groups exist to split a cohort larger than the available box count into consecutive runs — six rats, three working boxes, so two groups of three run back-to-back rather than simultaneously. Group membership and box assignment can be done by hand, or via the Auto-Balance tool (§7), which proposes a full grouping — including sex-balancing and box assignment — for the user to review and adjust rather than building one animal at a time.

---

## 3. Persistence

Cohort/Animal/Group data lives in **SQLite**, owned by the Python sidecar — consistent with the storage layer being sidecar-owned throughout this project. Three tables (`cohorts`, `animals`, `groups`), foreign-keyed as the model above implies.

The database file lives in the **app's own data directory** (e.g. `~/Library/Application Support/Ephymeris/ephymeris.db` on macOS, `%APPDATA%/Ephymeris/ephymeris.db` on Windows) — **not** inside the user-configured `dataDirectory` setting from `ephymeris_v1.0.md` §4.5. That setting is where behavioral session output lives and gets browsed by lab members; mixing an opaque `.db` file into it would be confusing and it's not a `.json`/`.mat`/`.tsv` session artifact. Backup of this file is built and specified in `data-saving.md` §8.3 (§12).

The schema has grown past these three tables: `prefixes`, `sessions`, and `session_animal_runs` were added for `data-saving.md` §3–§4, and `analytics.md` §10.2 added two more (`task_profiles`, `run_metrics_cache`) plus a nullable `session_animal_runs.profile_hash` at schema v3. `sidecar/ephymeris_sidecar/cohorts/db.py` holds the whole schema regardless of which document motivated each table.

> **Read this before changing the schema.** Adding a *table* needs nothing but a `CREATE TABLE IF NOT EXISTS` in `SCHEMA` — it covers the fresh and the existing case alike. Adding a **column** does not work that way: the same statement leaves an existing table untouched, so the column would appear only on databases created after the change. `db.py` carries a migration branch for exactly this (`analytics.md` §10.1) — bump `SCHEMA_VERSION`, update `SCHEMA` to the final shape, **and** add a `MIGRATIONS` entry. Either half alone leaves one class of database wrong.

---

## 4. Cohort Browser UI

Replaces the `<PlaceholderView>` currently stubbed at `/cohorts` (`ephymeris_v1.0.md` §4.2) — this is that section's first real implementation, and it also makes the dashboard's "N active" tile stat (previously placeholder text) real.

- **Layout:** a responsive card grid, not a list — "visualizing and selecting" calls for something you scan visually, not read top to bottom.
- **Card material:** `Nebula` surface, `Halo` hairline border, standard `md` radius — consistent with every other elevated surface in the app.
- **Card contents:** the procedural icon (§5), cohort name (Inter, not Space Grotesk — that face stays confined to section headers per the typography rule), and a small stat line in `JetBrains Mono` (animal count, group count if >1) — mono is already the app's convention for compact data readouts.
- **Motion:** spring-based hover/press (scale up slightly, icon's twinkle animation subtly accelerates on hover) — same spring-physics convention as the rest of the app, not a new motion language.
- **Search/sort:** a simple text filter and name/recency sort above the grid. Not a design decision worth its own section — any list that can grow past a dozen items needs this, same as it would in any other app.
- **Archived cohorts are hidden by default**, behind a small "Show Archived" toggle — the main grid is for *available* cohorts, per your own framing, and archived ones would just be clutter in the common case.

### The "create new cohort" tile

Always first in the grid, visually distinct rather than just another card: dashed `Halo` border instead of solid, a single dim, slowly pulsing star instead of a full generated system — a nebula that hasn't collapsed into a star system yet — with a "+ New Cohort" label. Hover brightens the pulse. This is the "special indication" you asked for, and it's a genuine extension of the astronomy metaphor already in use for the hardware status widget, not a new visual language bolted on.

---

## 5. Procedural Icon Generation

Rather than requiring uploaded artwork (not asked for, and it'd need storage/migration handling), each cohort's icon is **derived, not stored** — computed client-side from the cohort's `id` every time it's rendered, the same instinct already used for passthrough scrollback not being persisted. Nothing about the icon needs a database column beyond the id that already exists.

**Algorithm:**
1. Seed a small deterministic PRNG from the cohort `id` (e.g. a string hash into a `mulberry32`-style generator — cheap, dependency-free, trivially portable to TypeScript).
2. **Node count** = number of animals in the cohort, capped at 8 for visual sanity. Above 8, render a denser "cluster" glyph rather than placing nodes individually.
3. **Layout:** nodes placed at seeded angle + radius within a bounded circle, angularly spaced (`360° / nodeCount`) plus small seeded jitter so it doesn't look mechanically even.
4. **Connections:** each node links to its nearest neighbor(s), rendered as thin `Pulsar` lines at reduced opacity — reusing the exact line treatment already established for the hardware constellation status widget (`hardware-interaction.md`/`ephymeris_v1.0.md` §2.7), so the two features read as the same visual family rather than two different ideas.
5. **Star color/size:** primarily `Pulsar`, with seeded per-node size/opacity variation for texture. Exactly one node per icon (seeded selection) renders in `Ion` green instead — a single "hero star" for a bit of visual pop without introducing a new hue outside the established six-token palette.
6. **No glow, no gradients** — flat, matte fills only, per the theme's explicit "protect against scope-creep-by-gradient" rule.
7. **Animation:** gentle independent twinkle per node (seeded phase/period opacity oscillation) — subtle, not distracting, and respects `prefers-reduced-motion` by falling back to a static render, same as every other ambient motion in the app.

Group membership is **not** encoded into the icon — it stays a pure "how many animals" glyph, with group count left to the text stat line. Trying to make the icon also convey grouping risks turning a fun identifier into a dense infographic, which isn't what was asked for.

---

## 6. Create / Edit / Manage Flow

Opened either from the "+ New Cohort" tile (create) or by clicking an existing card (edit) — same form, different initial state.

- **Name** — text field.
- **Data folder** — defaults per §7, with an explicit override (native directory picker).
- **Animals** — an editable list: add/remove animal, name field, sex selector (M/F/Unknown), ID number field, notes field, box-number selector (1–6 or unassigned), group assignment (dropdown, or drag-between-columns if groups > 1).
- **Groups** — a lightweight sub-panel: add/remove/rename group, reorder (drag or up/down) to set `order`, plus the Auto-Balance tool (§7). Not shown at all when there's only the implicit default group, to avoid presenting UI for a concept most cohorts won't need.
- Standard save/cancel; validation errors (§2) surface inline, not as a toast after the fact.

---

## 7. Auto-Balance / Group Suggestion Tooling

A tool inside the Groups sub-panel (§6) that proposes a full grouping rather than requiring animal-by-animal manual placement. It's a **suggestion the user reviews and can hand-edit**, not a silent bulk mutation — consistent with this project's general caution around anything that rewrites existing configuration.

### 7.1 Inputs

The user chooses one of two equivalent ways to express the target split:
- **Number of groups**, or
- **Max group size**

Whichever isn't chosen is derived from the other. A **"Balance by sex"** checkbox is available whenever at least one animal in the cohort has `sex` set to `M` or `F` (not `unknown`/null) — otherwise it's disabled, since there's nothing to balance against.

As a courtesy default, if boards are currently connected (via the app's existing live presence data), the dialog pre-fills group size with the connected box count — editable, not enforced. This is a suggested starting point, not a dependency: cohort configuration stays decoupled from live hardware state per §2, this just saves a step in the common case where the tool is being used with hardware already plugged in.

### 7.2 Hard Constraint

**No group may exceed 6 animals** — `boxNumber` only spans 1–6, so a larger group could never get fully, uniquely assigned within itself regardless of grouping strategy. If the requested configuration would violate this (e.g. "1 group" requested for 10 animals), the tool rejects the request and suggests the minimum viable group count instead: `ceil(animalCount / 6)`.

### 7.3 Algorithm

A balanced round-robin, not an optimization search — simple, deterministic, and easy to reason about:

1. Partition animals into buckets by `sex`: `M`, `F`, `unknown`/`null`.
2. Walk each bucket in turn, assigning animals to the N target groups round-robin (group index cycles 0, 1, …, N-1, 0, 1, …) so each bucket spreads as evenly as possible across groups.
3. This naturally keeps group sizes within 1 of each other, and — when sex data is present — keeps each group's sex ratio as close to the cohort's overall ratio as the numbers allow. Animals with no sex data don't skew the balance; they just fill in size-wise after the known buckets are distributed.
4. Within each resulting group, **box numbers are auto-assigned sequentially** (1, 2, 3, …) in the order animals landed in that group — turning what's normally tedious manual bookkeeping into a byproduct of grouping, rather than a separate step.

### 7.4 Flow

**Always a full re-proposal, not an incremental fill-in.** Auto-Balance considers the complete current animal roster and proposes an entirely new grouping from scratch; it doesn't try to preserve or merge with whatever grouping already exists. This is simpler to reason about than partial-merge logic, and since the result is shown as a preview before anything is written, there's no ambiguity about what changes.

1. User opens Auto-Balance, sets group count/size and (optionally) sex-balancing.
2. Tool computes and displays a **preview**: proposed groups, their animals, and auto-assigned box numbers — using the same card/list treatment as the regular Groups sub-panel, so it's not a jarring separate UI.
3. User can hand-adjust the preview (drag an animal to a different group, change a box number) before committing — the suggestion is a starting point, not a final answer.
4. **Apply** commits the preview as the cohort's new grouping via the existing `cohorts.update` command (§10) — no separate "apply" command needed, since it's just a groups/animals patch like any other edit.
5. **Cancel** discards the preview with no changes made.

---

## 8. Data Folder Resolution

- **On creation**, if the user doesn't override it: `dataFolder = <Settings.dataDirectory>/<sanitized cohort name>`. If that path already exists on disk, a numeric suffix is appended (`-2`, `-3`, …) until unique.
- **The resolved path is persisted verbatim** — it is computed once, not re-derived from the current name on every read.
- **Renaming a cohort does not move its data folder.** Name and `dataFolder` are deliberately decoupled after creation — an automatic move-on-rename is exactly the kind of implicit file operation this project has avoided elsewhere (e.g. `hardware-interaction.md`'s explicit-confirmation stance on destructive actions). The cohort detail view surfaces the real `dataFolder` path plainly at all times so there's never ambiguity about where the data actually lives.
- **Relocating is a separate, explicit action** ("Change data folder…" in the edit view) — distinct from renaming. It carries **two intents**, chosen by the "Move existing contents" toggle, and they have opposite requirements for the destination:

  | Toggle | Meaning | Destination |
  |---|---|---|
  | **On** | Move this cohort's data to the new folder | **Must be empty.** Refuses rather than merging into or overwriting |
  | **Off** | Point this cohort at data that is already there | **Expected to be full.** Nothing is moved or written; only the recorded path changes |

  The "off" case is how a cohort attaches to an archive written before this app existed, which is the whole reason orphan adoption exists (`analytics.md` §8.1). Enforcing the empty-destination rule in *both* cases made that intent impossible to express — the only control for it rejected exactly the folders it was meant to accept, and because the field then re-rendered the unchanged path, it read as the setting silently reverting. The rule protects against merge collisions, and there are none when nothing is being written.

---

## 9. Archive / Delete Semantics

Two distinct actions, not one:

- **Archive** (soft-delete) — the everyday "delete a cohort" action. Removes it from the active grid, keeps the record and its `dataFolder` fully intact, reversible via "Show Archived" → Restore. This matches the caution already shown elsewhere in this project toward anything that could destroy real data.
- **Permanent delete** — only available *from* the archived view, on an already-archived cohort. A two-step guard (archive, then separately delete) rather than a single destructive button on a live cohort. Deleting the cohort record never touches its `dataFolder` on disk — the app removes its own bookkeeping, never a user's actual data files, without a much more explicit and separate confirmation than anything specified here.

---

## 10. Wire Messages (proposed)

`websocket-protocol.md` is the single source of truth for the wire schema (with `protocol/schema.py` as the machine-readable shape authority the code mirrors are generated from). These were proposed for merge into that document rather than treated as canonical here.

> **Merged.** These now live in `websocket-protocol.md` §3.1 (commands), §4 (the `cohorts.updated` event and the `CohortSummary`/`Cohort`/`Animal`/`Group`/`GroupProposal` payload shapes), and §6 (error codes). That document is canonical; the tables below are retained as the design rationale for *why* each command exists. The contract test enforces that the generated mirrors and the spec never drift.

**Commands:**

| Command | Args | Result |
|---|---|---|
| `cohorts.list` | — | `{cohorts: [CohortSummary]}` |
| `cohorts.get` | `{id}` | full `Cohort` |
| `cohorts.create` | `{name, dataFolder?}` | `{cohort}` |
| `cohorts.update` | `{id, patch}` | `{cohort}` |
| `cohorts.archive` | `{id}` | `{cohort}` |
| `cohorts.restore` | `{id}` | `{cohort}` |
| `cohorts.delete` | `{id, confirm: true}` | `{deleted: true}` — rejected unless already archived |
| `cohorts.setDataFolder` | `{id, path, moveExisting: bool}` | `{cohort}` |

**Events:**

| Event | `data` | Notes |
|---|---|---|
| `cohorts.updated` | `{cohorts: [CohortSummary]}` | Pushed whenever the list changes — same push-on-change pattern as `sketches.updated`, keeping the dashboard tile and the grid in sync without polling |

`CohortSummary` = `{id, name, animalCount, groupCount, archived}` — enough for the grid and dashboard tile without shipping full animal/group detail until a card is actually opened.

---

## 11. Resolved Decisions

| Decision | Outcome |
|---|---|
| Dangling bullet | Typo — the five-item property list was complete |
| Name uniqueness scope | Active (non-archived) cohorts only |
| Delete semantics | Archive-by-default, permanent delete gated behind it (§9) |
| Rename/data-folder decoupling | Confirmed — renaming never moves files; relocating is a separate explicit action (§8) |
| Animal metadata | Extended with `sex`, `idNumber`, `notes` (§1) |
| Editor presentation (§6 was silent) | **Dedicated route** — `/cohorts/new` and `/cohorts/:id` rather than a modal. The roster, groups panel, and Auto-Balance preview together are more than a dialog holds comfortably. The card's icon shares a `layoutId` with the editor header, so opening one morphs the icon into place rather than cutting |
| Data folder when `dataDirectory` is unset (§8 gap) | **Explicit choice required in the create form.** Pre-filled from `Settings.dataDirectory` when set — the sidecar derives and collision-suffixes it — and required, with inline validation, when it isn't. `dataFolder` is never null, and no location is ever guessed at |
| Group reordering / animal→group assignment | **Dropdowns + up/down buttons.** §6 offers "dropdown, *or* drag" and "drag *or* up/down"; the non-drag branch satisfies the spec with no drag-and-drop dependency |
| Create-failure cleanup | **The cohort record is written before its folder is created.** Reversing that order meant a rejected duplicate name left an orphaned directory in the user's data directory (found during implementation). A folder that then fails to create rolls the record back |

No open questions remaining as of this revision.

---

## 12. Open Items / TBD

- [x] ~~Merge §10's proposed commands/events into `websocket-protocol.md` as the canonical source once reviewed — including a `cohorts.suggestGroups` command for §7's preview step~~ — **done**; nine commands, one event, five error codes, and the shared payload shapes now live there, with the contract test covering all three sources
- [ ] Custom/uploaded cohort icons as an alternative to the generated one (§5) — deferred, not asked for
- [x] ~~Ensure the Data Saving doc's backup strategy includes `ephymeris.db` (§3), not just per-session output files~~ — **built**, `data-saving.md` §8.3. Backed up to the mirror on **every commit**, debounced 5 s, plus one dated snapshot per day with the newest 14 retained. The trigger ended up broader than this item asked for: "after every cohort-affecting write" would have missed `session_animal_runs`, written at finalization during an unattended run, so the hook sits on `commit` itself and no write path can forget it. The dated snapshots exist because a single overwritten mirror would faithfully reproduce an accidental cohort deletion — §9's permanent delete removes bookkeeping only, but the bookkeeping *is* what this file holds
- [x] ~~Starting a Session doc must define what "ready to run" means against this model~~ — resolved in `starting-a-session.md` §1: **at least one group with at least one animal that has a `boxNumber` assigned.** A group with zero box-assigned animals is skipped automatically rather than blocking the cohort
- [ ] **Animals added before a cohort's first save** are written in a follow-up `cohorts.update`, since they need the group id the sidecar mints at creation. Works, but means creation isn't a single atomic call — worth revisiting if `cohorts.create` ever accepts an initial roster
- [ ] **Groups can only be added from the editor once a cohort exists**, because §6 hides the groups panel while only the implicit default group is present. A brand-new cohort therefore can't be split until after its first save. Fine in practice (Auto-Balance is the normal path to multiple groups) but worth confirming it matches expectations
- [ ] **No confirmation on archive.** §9 makes archive the reversible everyday action and gates only permanent delete, so archiving is one click. Revisit if it proves too easy to trigger accidentally on a large cohort

---

**Next:** [starting-a-session.md](starting-a-session.md) — what happens when you actually run this cohort.
[Documentation index](README.md) · [Open items register](TODO.md)

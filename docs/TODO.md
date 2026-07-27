# Consolidated TO-DO Register

> **What this is** · Every open item from all seven specification documents, plus gaps found in the codebase, in one prioritized place.
>
> **This is a derived view.** Each spec's own **Open Items / TBD** table remains the authoritative record for its area; this document aggregates and prioritizes them so nothing is visible only to someone who happened to open the right file. **When you close an item, update both the spec and this register.**
>
> **Last reconciled** · On 2026-07-26, after building `data-saving.md` §8's Backup Directory mirroring and closing items 2, 17, 18, and 19. Sidecar suite green at 372 tests; `typecheck` and `cargo test` green.
>
> **Item numbers are stable.** A closed item keeps its number and moves to [Recently closed](#recently-closed) rather than being deleted and the rest renumbered — otherwise a commit message or a note referring to "item 12" would silently start pointing at something else.

**Priority legend**

| | Meaning |
|---|---|
| **P1** | Blocks shipping v1.0 |
| **P2** | Real gap with user-visible consequences |
| **P3** | Open decision — no consequence until decided |
| **P4** | Deferred by explicit decision |

**Jump to** — [P1](#p1--blocks-shipping-v10) · [P2](#p2--real-gaps-with-user-visible-consequences) · [P3](#p3--open-decisions) · [P4](#p4--deferred-by-explicit-decision) · [Recently closed](#recently-closed) · [Documentation hygiene](#documentation-hygiene)

---

## P1 — Blocks shipping v1.0

### 1. Windows packaging is unstarted

**Source:** `ephymeris_v1.0.md` §6

Nothing about shipping exists. Four separate pieces:

- Freezing and bundling the Python sidecar — dev builds run it from `sidecar/.venv`, which won't exist on a lab machine.
- Bundling `arduino-cli` plus the `arduino:avr` core with the installer. The spec commits to no runtime internet dependency; today the app uses whatever the machine already has.
- Tauri Windows bundling and signing.
- A Windows CI build.

This is the largest single body of remaining work, and it was deliberately deferred while v1 was developed. **Nothing else on this list matters if the app can't be installed on the two lab machines it exists for.**

With item 2 closed, this is now the **only** thing standing between the current tree and a shippable v1.0.

*(Item 2, Backup Directory, is built — see [Recently closed](#recently-closed).)*

---

## P2 — Real gaps with user-visible consequences

### 3. Analytics is a stub

**Source:** `ephymeris_v1.0.md` §4.4, §6 · `websocket-protocol.md` §9

`<PlaceholderView>` only, though it now doubles as the session-end landing and acknowledges the session saved. Needs two things, in order: a view spec covering within-session, across-session, and per-cohort analysis; then the query messages to support it.

`SessionAnimalRun` records are already written at finalization specifically as forward-looking infrastructure for this — cheap now, expensive to reconstruct from files later.

### 4. Crash-recovery utility for orphaned `.tsv` files

**Source:** `data-saving.md` §7.3, §11

If the machine loses power mid-session, every strobe up to that moment is durably on disk in `.tsv` — but no `.json`/`.mat` is ever produced, because those are built only at clean finalization. Today that recovery is manual.

A small utility that reads an orphaned `.tsv` and backfills both structured formats with `stop_reason: "recovered after crash"` is cheap given the existing design. Note this is **not** session resumption (see P4).

### 5. Switch Group's second lap is untested on hardware

**Source:** `starting-a-session.md` §11

The bookkeeping that makes Switch Group advance rather than cycle is verified — the first group is recorded and skipped. What hasn't been driven end to end on real hardware is a full two-group session: switch, re-map, re-flash, run, end.

This is the highest-value remaining hardware test, and multi-group runs are a normal workflow for any cohort larger than the box count.

### 6. No frontend test runner or linter

**Source:** codebase

`tsc --noEmit` is the entire automated frontend check — there is no vitest, jest, eslint, prettier, or biome, and no test file anywhere under `src/`. The sidecar has 332 tests and the Rust shell has 2; the React layer — including Mission Control, the session flow, and every store — has none.

The wire mirrors are guarded by the contract test, so the highest-risk surface is covered. But store logic (`lib/sessions/store.ts`, `lib/hardware/store.ts`) and the session flow's step transitions are untested code paths that real sessions depend on.

### 7. Debug log export is clipboard-only

**Source:** `hardware-interaction.md` §6.5, §8

The spec asks for "copy log / save debug log"; v1 ships copy-to-clipboard via `navigator.clipboard.writeText`. Saving to a file needs a write path the shell doesn't currently have. **Decide who owns it:** `tauri-plugin-fs` plus a save dialog, or a sidecar-side export command.

### 8. The contract test guards names, not shapes

**Source:** `websocket-protocol.md` §9 · codebase

`test_protocol_contract.py`'s 69 cases prove that command names, event names, error codes, and the protocol version agree across the doc and both mirrors. That is the drift that used to bite, and it is now closed.

What remains unguarded: **payload shapes.** A field added to a result on the Python side and forgotten on the TypeScript side passes every test. The doc check is also a plain substring match, so a name mentioned anywhere in `websocket-protocol.md` — including in a resolved open item — satisfies it. Decide whether that gap is acceptable or wants a second test.

---

## P3 — Open decisions

### 9. Migrate `BoardTool` to the arduino-cli gRPC daemon

**Source:** `hardware-interaction.md` §2, §8

**Committed, not conditional** — the subprocess backend is a staging step, not the destination. It was scheduled for after flashing worked end to end so it could be validated against a known-good baseline. That milestone is reached, making this the next hardware-layer task.

Requires vendoring arduino-cli's `.proto` files and adding a `grpcio-tools` codegen step, since there is no official Python gRPC client. It also buys true line-by-line compiler streaming, which `--format json` cannot provide — output currently arrives buffered at phase end and is replayed as progress after the fact.

Weigh against the dependency policy (`reference.md` §6): this adds a substantial sidecar build-time dependency to a project that deliberately keeps runtime dependencies at two.

### 10. Multi-port batching for Debug Mode

**Source:** `hardware-interaction.md` §8 · `websocket-protocol.md` §9

Partly answered: the *session* flash sequence is strictly sequential and halts at the first failure, and that's built. Still open is whether Debug Mode wants a "flash all 6" affordance at all, whether it shares the halt policy, and whether it would be one command with six progress streams or six independent commands.

### 11. Full Settings schema

**Source:** `ephymeris_v1.0.md` §4.5, §6

The seven implemented fields — `dataDirectory`, `backupDirectory`, `arduinoDirectory`, `arduinoCliPath`, `defaultBaud`, `boxes`, `reducedMotion` — are described as a starting point, not final. Per-box COM port nicknames exist within `boxes` as `label`. The sidecar reads only five of them (`arduinoDirectory`, `arduinoCliPath`, `dataDirectory`, `defaultBaud`, `boxes`) and ignores the rest, so adding a field is deliberately a non-event.

### 12. Back-pressure policy for `port.output`

**Source:** `websocket-protocol.md` §9

Currently unbounded send, relying on the ring buffer cap. No policy exists for a frontend that cannot keep up with 20 Hz × 6 boxes. Not observed as a problem — but undefined.

### 13. Constellation adjacency pairs

**Source:** `ephymeris_v1.0.md` §2.7, §6

`components/chrome/ConstellationStatus.tsx` connects `1–2, 2–3, 4–5, 5–6, 1–4, 3–6`, forming one closed shape so no node is orphaned. **Confirm this matches the physical box arrangement on the bench** — if the rig is laid out differently, the map should mirror it. Now that only bound boxes render, a sparse selection can leave nodes with no edges, which makes the pair list more visible than it was.

> Applies to the **sidebar status widget only.** Mission Control's 3D constellation computes its links by nearest-neighbour from seeded per-animal positions and has no fixed pair list to confirm.

### 14. Box→board re-binding UX

**Source:** `hardware-interaction.md` §8

How a physically swapped board (new `hardware_id`, same cage) gets re-bound without hunting through Settings. A board swap is a routine lab event; today it means knowing to go to Settings and match a USB serial number by hand.

### 15. Live filesystem watcher for the Arduino Directory

**Source:** `arduino-directory.md` §8

Scan-on-trigger (setting change, manual refresh, Debug Mode mount) was judged sufficient, avoiding a background watcher for marginal benefit. Revisit only if that assumption proves wrong in practice.

### 16. Cohort editor rough edges

**Source:** `cohorts.md` §12

Three small, known, individually tolerable issues:

- **Creation isn't atomic.** Animals added before a cohort's first save go in a follow-up `cohorts.update`, because they need the group id the sidecar mints at creation. Worth revisiting if `cohorts.create` ever accepts an initial roster.
- **Groups can't be added to a brand-new cohort** until after its first save, because the groups panel is hidden while only the implicit default group exists. Auto-Balance is the normal path to multiple groups, so this rarely bites.
- **Archive has no confirmation.** Deliberate — archive is the reversible everyday action and only permanent delete is gated. Revisit if it proves too easy to trigger on a large cohort.

*(Items 17–19 — the date format, backup cadence specifics, and the `.tsv` open mode — are all now decided and built. See [Recently closed](#recently-closed).)*

---

## P4 — Deferred by explicit decision

These are recorded so they aren't rediscovered as oversights. Each was decided, not missed.

| Item | Decision | Source |
|---|---|---|
| **Session resumption after app/sidecar restart** | Out of scope. Materially bigger than crash recovery — reconnecting boards, resuming trial state, deciding whether the animal kept running. Mission Control recovers a *reload* fine via `sessions.status`; if the sidecar dies, the run is over and the `.tsv` is the record | `starting-a-session.md` §11, `data-saving.md` §7.3 |
| **Light mode** | Out of scope for v1, not even a placeholder toggle | `ephymeris_v1.0.md` §2.2 |
| **Auto-respawn of a crashed sidecar** | No. A silent respawn would resurrect the process without the port ownership or session state it had — worse than an honest failure the user can see | `websocket-protocol.md` §8 |
| **Auto-recovery from a mid-session board drop** | No. Always a hard stop into `ERROR`, cleared manually. Costs nothing in data because of the write-ahead log | `starting-a-session.md` §10 |
| **Custom/uploaded cohort icons** | Deferred; procedural generation from the cohort id is sufficient and stores nothing | `cohorts.md` §12 |
| **Codegen for the wire protocol** | No. The surface is small enough that a build step costs more than the contract test | `websocket-protocol.md` §8 |
| **Arbitrary sketch browse outside the Arduino Directory** | No. One source of truth makes the error and empty states unambiguous | `arduino-directory.md` §7 |
| **`scipy` for `.mat` writing** | Replaced by a hand-written MAT v5 serializer to keep sidecar runtime dependencies at two | `data-saving.md` §5.1 |

---

## Recently closed

Kept briefly so a reader returning to this register can see what moved, rather than wondering whether an item was dropped or resolved.

### ~~2. Backup Directory is a promise the app doesn't keep~~ — closed

**Was:** P1. The setting was collected, persisted, and pushed to the sidecar, and nothing read it — a search for "backup" across the sidecar tree returned zero matches.

**Now built**, in `sidecar/ephymeris_sidecar/backup/`, specified in `data-saving.md` §8 and covered by `tests/test_backup.py`. All three mechanisms exist: the finalization copy (queued, never blocking session teardown), the periodic `.tsv` mirror (10 s, self-paced, whole-file), and the `ephymeris.db` backup with dated daily snapshots.

Four decisions worth carrying forward, since each closed a question this register was tracking separately:

- **The mirror is anchored on the cohort folder, not `dataDirectory`.** It has to be — `cohorts.setDataFolder` can put a cohort anywhere, so path arithmetic against the data directory doesn't work in general. This wasn't visible until implementation started.
- **`ephymeris.db` backs up on every commit, not every "cohort-affecting write."** The original wording was too narrow: `session_animal_runs` is written at finalization during an unattended overnight run and isn't a cohort edit. Hooking `commit` itself means no write path can forget.
- **Dated snapshots, not just a live mirror.** A single overwritten copy would propagate an accidental cohort deletion within seconds — defeating one of the two failures backup exists to protect against.
- **Failure is visible.** A backup that silently stops working is the same problem this item was about. It surfaces as a persistent state on `backup.status`, not a transient toast that a dead share would fire every ten seconds.

What remains, tracked in `data-saving.md` §11: this has not yet run a full session against a real network share, which is the one thing local-filesystem tests can't exercise.

### ~~17. `MM_DD_YY` date format doesn't sort across a year boundary~~ — closed

**Was:** P3, marked "don't fix it without talking to the lab."

**The lab decided to change it.** Session folders and per-animal files now carry ISO `YYYY-MM-DD` (`data-saving.md` §2.1), which sorts chronologically as a plain string.

The non-obvious part is the **hyphen**. `MM_DD_YY` and `YYYY_MM_DD` split into the same number of underscore-separated tokens, so an existing analysis script parsing positionally would have kept running and silently read every date wrong. Hyphenating changes the token count, so such a script breaks loudly instead. Nothing already on disk is renamed, and `parse_name_date` reads both spellings — which means the "never sort these names lexically" invariant is now *more* important than before, not less, since both formats coexist indefinitely.

### ~~18. Backup cadence specifics~~ — closed

`.tsv` mirrors every **10 s, self-paced** from the end of the previous pass. `ephymeris.db` backs up on **every commit, debounced 5 s, with no periodic timer** — the timer question dissolved rather than being answered: the database only changes when something writes to it, so a timer over an idle database would re-copy identical bytes. Both in `data-saving.md` §8.2–§8.3.

### ~~19. `.tsv` files are opened in truncating write mode~~ — closed

Now opened with exclusive create (`"x"`). A collision fails the box with the offending path named in both the operator-facing error and the recorded `stop_reason`, rather than truncating.

Failing the run outright was chosen over silently disambiguating the filename: the collision is unreachable by construction, so if it ever happens something is wrong in a way worth stopping for.

### ~~`sidecar.error` is defined but never emitted~~ — closed

**Was:** P2. The event existed in the doc and both mirrors, and nothing raised it.

**Now built.** `sessions/runner.py` emits it when a mid-session `.tsv` write raises — disk full, permissions — which was always its intended first use: the failure with no command to attribute it to, and the one a user most needs to know about immediately, since it means data is silently not being saved. The strobe is dropped rather than retried and the run continues, so the operator decides what to do.

The genuinely-unused name is now **`DIR_INVALID`**, which is defined in both mirrors but never raised — directory problems surface as a `DirectoryStatus` payload instead. Documented in place rather than tracked as work.

### ~~Substantial uncommitted work in the tree~~ — closed

**Was:** documentation hygiene. Thirty modified files plus two untracked components were sitting uncommitted, spanning the session flow, the sidecar's session repository and runner, and the docs.

All landed in `878cb0c`. The tree is clean, so the doc-to-code correspondence this register asserts is now reproducible from a fresh checkout.

### ~~The guided session-flow UI is undocumented~~ — closed

The journey rail, the placement banner, and the Analytics session-end landing are specified in `starting-a-session.md` §6.5, including the rationale for the banner being deliberately off-theme in style while staying inside the palette.

---

## Documentation hygiene

Gaps in the docs and small code/doc mismatches, found while reconciling them against the code. None are bugs; each will mislead a reader who assumes otherwise.

### 20. `MetricChart.tsx` is built but wired to nothing

**Source:** codebase · `starting-a-session.md` §6.4

The zoomed star view currently shows a five-row recent-strobe feed, and the rolling live-metric charts originally specified for it are deferred — documented as an interim design.

What the doc didn't say until now: **the chart component already exists and is correct**, complete with its 0.5 chance line. Nothing imports it. Re-landing that feature is a wiring job, not a build job — but until someone does, it is dead code that reads as live.

### 21. `PlaceholderView` describes three callers and has one

**Source:** codebase · `ephymeris_v1.0.md` §4

Its doc comment still says "the three unwired sections" and it exposes a `preview` prop no caller passes. Start a Session and Cohorts both grew into real views; only Analytics still uses it. Harmless, and the last trace of the original build order.

### 22. "Six-token palette" is seven `@theme` colours

**Source:** codebase · `ephymeris_v1.0.md` §2.2

`src/styles/index.css` declares Void, Nebula, Halo, Pulsar, Ion, Starlight **and** `Static` — plus three `status-*` values. Several code comments say "the six tokens."

Resolved in the spec rather than the code: the six are the ones carrying the theme's identity, and `Static` is deliberately not among them because it is a text weight, not a colour decision. Left here so the phrasing isn't re-litigated.

### 23. `kind` in a Task Profile is a convention, not a schema gate

**Source:** codebase · `data-saving.md` §6.2

`tasks/profile.py` parses `config`, `strobes`, `liveMetrics`, `controls`, and `telemetry` from every profile regardless of `kind`, and silently ignores unknown top-level keys. A `utility` profile carrying `liveMetrics` is accepted and simply never scored.

Now documented in place. Only worth *enforcing* if a malformed profile ever actually causes confusion in the lab.

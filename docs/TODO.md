# Consolidated TO-DO Register

> **What this is** · Every open item from all eight specification documents, plus gaps found in the codebase, in one prioritized place.
>
> **This is a derived view.** Each spec's own **Open Items / TBD** table remains the authoritative record for its area; this document aggregates and prioritizes them so nothing is visible only to someone who happened to open the right file. **When you close an item, update both the spec and this register.**
>
> **Last reconciled** · On 2026-07-28, after Windows packaging landed (item 1 closed — the last P1; item 27 opened for signing/CI). Previously 2026-07-27, after building the Config tab (`ephymeris_v1.0.md` §4.6): box setup moved out of Settings, a first-run wizard, zodiac constellation layouts (superseding item 13, partially addressing item 14), and a passthrough-composed handshake test. Same day, earlier: Analytics decodes the lab's real Remy archive (item 25, item 26 opened), the wire protocol moved to build-time codegen (item 8), Analytics built end to end (item 3), item 24 fixed. Sidecar suite green at 493 tests; `typecheck` green.
>
> **Item numbers are stable.** A closed item keeps its number and moves to [Recently closed](#recently-closed) rather than being deleted and the rest renumbered — otherwise a commit message or a note referring to "item 12" would silently start pointing at something else. New items take the next free number, so they are **not** always in ascending order within a section: an item is placed next to whatever it blocks or explains.

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

**Empty.** Item 1 (Windows packaging) closed 2026-07-28 — see [Recently closed](#recently-closed). What remains of it (code signing, a CI build — item 27) does not block installing on the lab machines.

---

## P2 — Real gaps with user-visible consequences

*(Item 3, Analytics, is now built — see [Recently closed](#recently-closed).)*

### 26. The Observatory at real-archive scale — rendered, not yet judged

**Source:** `analytics.md` §12 · codebase

The Observatory now **does** render the lab's real archive: 50 sessions × 6 animals, 295 of 296 runs scored, driven in the running app against `K:\Hart Lab\01_Data\00_Behavior\Remy`. Nothing errored and every panel populated.

What hasn't happened is anyone *looking at it with a scientist's eye*. Three things are known-marginal at this scale and were only ever designed against an 18-session synthetic set: the heatmap's cell density at 50 columns, the session selector's length, and the six-colour ramp repeating past six animals. Whether the strategy space is usable when the dominant profile declares one condition (the shaping half of this archive) is a real design question — it currently shows an explanatory note instead of a plot.

A **second** real cohort now sharpens all four (item 27): Squeekstreet Syndicate is 30 sessions × **12 animals** — double the colour ramp's length, so the repeat is guaranteed rather than hypothetical — and its profile (`shaping_GR`) declares exactly **one** live metric, making the single-condition strategy space the normal case for that cohort rather than an edge of another one. Both have been driven at the service layer; neither has been judged on screen.

### 4. Crash-recovery utility for orphaned `.tsv` files

**Source:** `data-saving.md` §7.3, §11 · `analytics.md` §8.1

If the machine loses power mid-session, every strobe up to that moment is durably on disk in `.tsv` — but no `.json`/`.mat` is ever produced, because those are built only at clean finalization. Today that recovery is manual.

A small utility that reads an orphaned `.tsv` and backfills both structured formats with `stop_reason: "recovered after crash"` is cheap given the existing design. Note this is **not** session resumption (see P4).

It needs the **same archive walker** as `analytics.md` §8.1's orphan adoption — both walk cohort data folders and both must parse either date spelling. Build them to share one, whichever lands first. §8.1's is now the depth-tolerant one (format folders matched by name at any depth, pruned at the format folder) and is the version to reuse.

### 28. A finalization landing after `sessions.end` writes files with no run record

**Source:** codebase — `sessions/runner.py:275`, `app.py:_sessions_end`, `_on_animal_ended`

`_on_track` schedules `finalize_box` as a fire-and-forget task when a board reports its own end strobe. Meanwhile `_sessions_end` awaits `end_all` — which waits only briefly — and then clears `self._running_session_id`. `_on_animal_ended` records the `session_animal_runs` row *only* `if self._running_session_id is not None`, so a finalization that lands on the wrong side of that clear **writes the `.json`/`.mat` and no database row**.

The data is not lost, and the symptom is mild and recoverable: the run is invisible to `analytics.summary`'s database-first path until someone clicks Rescan, which adopts it. But it is self-inflicted — this is precisely the "runs finalized while no session was active" orphan cause `analytics.md` §8.1 lists, being manufactured by the end path itself rather than by a crash.

Found while establishing that the post-session Analytics landing does **not** need a disk rescan (`analytics.md` §2.5). The landing fix is correct as shipped; this is the residual case that keeps Rescan the honest cure rather than a redundancy. Likely fix: have `_sessions_end` await outstanding finalizations before clearing the id, or key the record-on-end guard to the run rather than to a mutable field.

### 5. Switch Group's second lap is untested on hardware

**Source:** `starting-a-session.md` §11

The bookkeeping that makes Switch Group advance rather than cycle is verified — the first group is recorded and skipped. What hasn't been driven end to end on real hardware is a full two-group session: switch, re-map, re-flash, run, end.

This is the highest-value remaining hardware test, and multi-group runs are a normal workflow for any cohort larger than the box count. Note the last-lap behavior changed with the Launch work: a `null` `nextGroupId` now completes the session sidecar-side (previously it relied on the client navigating away, which left the record stranded as `running`) — the two-group hardware pass should confirm the final status flip too.

### 6. No frontend test runner or linter

**Source:** codebase

`tsc --noEmit` is the entire automated frontend check — there is no vitest, jest, eslint, prettier, or biome, and no test file anywhere under `src/`. The sidecar has 450 tests and the Rust shell has 2; the React layer — including Mission Control, the session flow, and every store — has none.

The wire mirrors are guarded by the contract test, so the highest-risk surface is covered. But store logic (`lib/sessions/store.ts`, `lib/hardware/store.ts`) and the session flow's step transitions are untested code paths that real sessions depend on.

### 7. Debug log export is clipboard-only

**Source:** `hardware-interaction.md` §6.5, §8

The spec asks for "copy log / save debug log"; v1 ships copy-to-clipboard via `navigator.clipboard.writeText`. Saving to a file needs a write path the shell doesn't currently have. **Decide who owns it:** `tauri-plugin-fs` plus a save dialog, or a sidecar-side export command.

*(Item 8, payload-shape drift, is closed by the switch to codegen — see [Recently closed](#recently-closed).)*

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

The ten implemented fields — `dataDirectory`, `backupDirectory`, `arduinoDirectory`, `arduinoCliPath`, `defaultBaud`, `boxes`, `reducedMotion`, plus Config's shell-only `constellation`, `constellationSlots`, and `boxSetupComplete` (§4.6) — are described as a starting point, not final. Per-box COM port nicknames exist within `boxes` as `label`. The sidecar reads only six of them (`arduinoDirectory`, `arduinoCliPath`, `dataDirectory`, `backupDirectory`, `defaultBaud`, `boxes`) and ignores the rest, so adding a field is deliberately a non-event — proven again by the three Config keys, which needed no sidecar change at all.

### 12. Back-pressure policy for `port.output`

**Source:** `websocket-protocol.md` §9

Currently unbounded send, relying on the ring buffer cap. No policy exists for a frontend that cannot keep up with 20 Hz × 6 boxes. Not observed as a problem — but undefined.

*(Item 13, the constellation adjacency pairs, is superseded by the user-chosen zodiac layouts — see [Recently closed](#recently-closed).)*

### 14. Box→board re-binding UX

**Source:** `hardware-interaction.md` §8

How a physically swapped board (new `hardware_id`, same cage) gets re-bound. A board swap is a routine lab event. **Partially addressed (2026-07-27):** bindings now live in the Config tab (`ephymeris_v1.0.md` §4.6) with a re-runnable setup wizard and a per-box handshake test to confirm a swap took. Still open: proactive surfacing — "a new board appeared, bind it to box 3?" — rather than the user knowing to open Config.

### 15. Live filesystem watcher for the Arduino Directory

**Source:** `arduino-directory.md` §8

Scan-on-trigger (setting change, manual refresh, Debug Mode mount) was judged sufficient, avoiding a background watcher for marginal benefit. Revisit only if that assumption proves wrong in practice.

### 27. Installer signing and a CI build

**Source:** what remains of item 1 after packaging landed (2026-07-28)

The shipped installer is unsigned — every fresh lab machine shows the SmartScreen "Windows protected your PC" dialog once, and the install instructions have to say "More info → Run anyway". A code-signing certificate (or Azure Trusted Signing) would remove that. Separately, the installer is built by hand on a dev machine via `npm run package`; a Windows CI build would make the artifact reproducible and untie it from any one machine's `arduino-cli`. Neither blocks the two lab machines. macOS packaging has never been run and stays run-from-source by decision.

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
| **Session resumption after app/sidecar restart** | Out of scope. Materially bigger than crash recovery — reconnecting boards, resuming trial state, deciding whether the animal kept running. Mission Control recovers a *reload* fine via `sessions.status`; if the sidecar dies, the run is over and the `.tsv` is the record. Crash-orphaned `running` rows are now *surfaced* on the Launch page (`sessions.active`'s `stale` list, read-only: View in Analytics / Close out) — visibility changed, the decision did not | `starting-a-session.md` §11, `data-saving.md` §7.3 |
| **Light mode** | Out of scope for v1, not even a placeholder toggle | `ephymeris_v1.0.md` §2.2 |
| **Auto-respawn of a crashed sidecar** | No. A silent respawn would resurrect the process without the port ownership or session state it had — worse than an honest failure the user can see | `websocket-protocol.md` §8 |
| **Auto-recovery from a mid-session board drop** | No. Always a hard stop into `ERROR`, cleared manually. Costs nothing in data because of the write-ahead log | `starting-a-session.md` §10 |
| **Custom/uploaded cohort icons** | Deferred; procedural generation from the cohort id is sufficient and stores nothing | `cohorts.md` §12 |
| ~~**Codegen for the wire protocol**~~ | **Reversed 2026-07-27** while closing item 8. The original "no" was made at a dozen names; at 38 commands with payload shapes, hand-maintenance was the costlier side. Kept here so the row isn't rediscovered as still standing | `websocket-protocol.md` §8 |
| **Arbitrary sketch browse outside the Arduino Directory** | No. One source of truth makes the error and empty states unambiguous | `arduino-directory.md` §7 |
| **`scipy` for `.mat` writing** | Replaced by a hand-written MAT v5 serializer to keep sidecar runtime dependencies at two | `data-saving.md` §5.1 |

---

## Recently closed

Kept briefly so a reader returning to this register can see what moved, rather than wondering whether an item was dropped or resolved.

### ~~1. Windows packaging is unstarted~~ — closed

**Was:** the largest single body of remaining work and the last P1: no freezing, no bundling, no installer.

**Built 2026-07-28.** `npm run package` → `Ephymeris_1.0.0_x64-setup.exe` (NSIS, per-user, ~65 MB). `scripts/package-resources.mjs` stages a PyInstaller-frozen sidecar (onedir, ~24 MB), the machine's `arduino-cli`, and a cleanly seeded `arduino:avr` data dir (~322 MB — core, avr-gcc, avrdude), satisfying `hardware-interaction.md` §2's no-runtime-internet commitment. The shell resolves frozen-first in release and venv-first in dev (`src-tauri/src/sidecar.rs`), spawns with `CREATE_NO_WINDOW`, and exports `EPHYMERIS_BUNDLED_ARDUINO_*`; the sidecar copies the seed to a writable app-data dir on first use behind a completion marker (`boards/cli_tool.py`). Verified on a real install: silent install, frozen sidecar spawned from resources, seed copied, and the stdin orphan-watch still kills the sidecar when the shell dies. Signing and CI split off as item 27.

### ~~13. Constellation adjacency pairs~~ — superseded

**Was:** P3 — confirm the hand-authored `1–2, 2–3, 4–5, 5–6, 1–4, 3–6` edge list against the physical bench.

**Superseded by the Config tab's zodiac layouts** (`ephymeris_v1.0.md` §4.6, 2026-07-27): the constellation layout is now a user choice — one of twelve hand-authored zodiac asterisms, boxes assigned to stars, rearrangeable by drag — so there is no fixed pair list left to confirm. The old shape survives only as the fallback for an install that never ran box setup. If mirroring the physical bench matters to a user, any constellation's slot assignment can express it.

### ~~25. Analytics couldn't see a real cohort's data at all~~ — closed

**Was:** the last open item on Analytics, and the reason pointing a new cohort at the real Remy folder produced an empty dashboard.

**Diagnosis: three independent blockers, any one of which alone was fatal.** A pre-Ephymeris archive has *no* `session_animal_runs` rows, so the database-first path — the only one the dashboard used — correctly returned nothing. The archive walk that exists for exactly this case was `rescan`-only, and it (a) globbed only `behavior.json/`, missing the lab's `behavior_json/`, and (b) **counted matches and threw them away** — `adopted` was `len([...])` and nothing was ever persisted, so even a successful walk changed nothing a user could see.

**Now built.** Adoption is real: an `adopted_runs` table, deterministic synthetic ids, payload-only synthetic sessions merged into both `analytics.summary` and `sessions.list`, and `analytics.series` falling back to it. The walk reads both folder layouts and both date spellings; `data-saving.md` §6.7 adds `legacyNames` so a run recorded as `"Shape - L"` finds `shaping_GL`. Result on the real archive: **306 files, 306 adopted, 50 sessions, 306 decoded, zero warnings.**

**A second pass against the *lab's* copy of the archive** (`K:\Hart Lab\01_Data\00_Behavior\Remy`, rather than the dev copy) found four more blockers, all in the same "finding the files" layer and none in the maths:

- **`cohorts.setDataFolder` refused every non-empty destination**, including when it wasn't moving anything. Attaching a cohort to an existing archive — the entire premise of adoption — was therefore impossible to express, and because the field re-rendered the unchanged path afterward it read as *the setting silently reverting*. Now gated on `moveExisting` (`cohorts.md` §8).
- **454 macOS AppleDouble sidecars (`._*.json`)** against 586 real files. Each decoded as `UnicodeDecodeError` → an "unreadable" run that never existed; junk was the majority of the walk's output.
- **290 of 296 runs existed twice** — a consolidated `ALL/` copy beside the per-prefix originals — which would have doubled every animal in the heatmap. Deduplicated by run identity (the file stem), keeping the *richer* copy: 30 runs carry `sketch` only in the consolidated version, so "first found" would have discarded the only decodable one.
- **A data folder that isn't on disk read as "no data"** rather than "nowhere to look" — routine with a removable drive or a re-lettered volume.

Driving the *rescan a second time* through the running UI then exposed two more, both of which only a repeat pass could show: the synthetic run id was keyed on the **file path** rather than the run identity, so a change in which duplicate copy won minted a second row for the same run (296 → 297); and `sketch_path` was **frozen at adoption**, so runs adopted while the Arduino Directory was unavailable stayed permanently undecodable. Both fixed; resolution now happens at read time.

Final result on the lab archive: **586 scanned, 296 adopted, 290 duplicates skipped, 295 of 296 decoded, 50 sessions, zero unreadable** — stable across repeated rescans, and verified in the running Observatory rather than only at the service layer.

Four things worth carrying forward:

- **The failure was silent in the worst way.** Every command succeeded and returned a well-formed empty result. `rescan` even reported `adopted: 74` while persisting nothing — a counter incremented next to a `TODO` that was never written. A number that goes up is not evidence that anything happened.
- **Real data broke the *finding* layer, not the maths.** `derive.py` needed no change. Every blocker was in locating and attributing files — which is the part that was only ever tested against archives this app wrote itself.
- **`profileGroups` were unlabeled and nobody noticed**, because fallback-decoded profiles were hashed but never stored, so `profile_meta` found nothing. Invisible with snapshots present; universal on any pre-snapshot archive. Storing the blob does not promote trust — that is `profileSource`, which stays `sketch-current`.
- **The real archive validated §3.7's pooled-accuracy decision immediately.** remy2 scores `p_r_odor1 = 0.00` and `p_l_odor3 = 1.00` — a perfectly side-locked animal that either single metric would report as flawless. Pooled, it sits at 0.48: chance. That is the trap the spec predicted, in the lab's own data.

### ~~27. A second lab archive was invisible to the walk~~ — closed

**Source:** `analytics.md` §8.1 · a colleague's cohort, `04_Data/00_Behavior/Squeekstreet Syndicate`

**Was:** a cohort recorded on pre-Ephymeris software — 30 sessions, 444 `.json`, 801 `.tsv` — that `analytics.rescan` scanned **0 files** of. Item 25's lesson repeated on data item 25 never saw.

**Three independent blockers, only the first fatal:**

- **The walk's depth was hard-coded.** It globbed `<cohort>/*/*/behavior_json/*.json`, which assumes the prefix-grouping level the Remy archive happens to have. These session folders sit straight under the cohort root, so the glob matched nothing. Format folders are now matched **by name at any depth**, pruned so that a format folder's data is exactly its direct children — which also disposes of the `00_session_analytics/` and `behavior_json/analytics/` report folders this archive keeps, by rule rather than by name.
- **The session number was read positionally.** These folders are named number-first (`00_01_shaping_gr_06_17_26`), the inverse of `<prefix>_<number>_<date>`, so taking the trailing `_`-token reported the prefix as `00_01_shaping` and the number as `gr`. Now found by *being numeric* — trailing first, so nothing already read correctly moved.
- **One document's `rat` field was typo'd** (`HmM103`, filename `HM103_…`), which under strict document-only matching cost HM103 a day. The filename is a second independent recording of the same fact and is now consulted when the document fails, structurally (the stem must match its own session folder) and still requiring an exact roster match.

**Result: 444 scanned, 444 adopted, 0 duplicates, 30 sessions, 12 animals, 444 decoded, zero warnings**, stable across a repeated rescan with every id unchanged.

Worth carrying forward:

- **Twice now, real data has broken only the *finding* layer.** `derive.py` needed no change here either. Every blocker was in locating, naming, or attributing files — the part that synthetic fixtures cannot anticipate because they are written by the code that reads them.
- **The first archive taught the wrong lesson by being too tidy.** Remy's hand-made prefix level made a fixed two-level glob look like it had been generalized when it had only been re-specialized. One example is not a shape.
- **A regression check on a *second* corpus is what made the parser change safe to ship.** Re-running both archives through the old and new splits showed Remy's 71 folder names splitting identically and all 30 of Squeekstreet's changing — evidence rather than argument, and cheap.

### ~~8. The contract test guards names, not shapes~~ — closed

**Was:** P2, and a standing P4 decision ("no codegen") pointing the other way.

**Now closed by reversing that decision.** `protocol/schema.py` at the repo root is the machine-readable shape authority; `protocol/generate.py` (stdlib-only, any Python ≥ 3.9) generates both mirrors — `ephymeris_sidecar/protocol.py` and `src/lib/ws/protocol.ts` — at build time (`npm run gen:protocol`, auto-run by `prebuild`/`predev` via `scripts/gen-protocol.mjs`). The mirrors are committed; `test_protocol_contract.py` regenerates and fails on a stale or hand-edited copy, and still requires every name to appear in the doc.

The shape gap itself is guarded from both sides:

- **TypeScript:** generated `CommandArgsMap`/`CommandResultMap`/`EventDataMap` make `client.call` fully typed, and the frontend's domain type files (`cohorts/types.ts`, `sessions/types.ts`, `analytics/types.ts`, `settings/schema.ts`, …) re-export the generated shapes instead of hand-copying them — so stale shape use fails `typecheck`.
- **Python:** the generated module carries runtime shape specs plus a strict validator (unknown fields are errors, optional ≠ nullable, bool ≠ int). Under `EPHYMERIS_WIRE_VALIDATE=1` — on for the whole test suite, off in production — every `protocol.event()` payload and every dispatched reply is checked, and `test_wire_shapes.py` pins the real `to_json` emitters to the schema.

Building the schema against the actual emitters immediately caught two drifts the old test could not: `analytics.rescan`'s documented result (`recomputed`/`durationMs`) never matched the implementation (`orphans`/`cohortId`), and `sessions.list` returned full `Session` records (with `prefixId`/`groupRuns`) where `analytics.summary` returned a trimmed shape under the same TypeScript type — both now unified on one `SessionListItem` emitter (`Session.to_list_item`).

### ~~3. Analytics is a stub~~ — closed

**Was:** P2, and the last unbuilt feature in v1.0.

**Now built**, to [`analytics.md`](analytics.md): the Observatory dashboard on one route, three linked panels (strategy space, learning curves, cohort heatmap), a pure derivation layer, four wire commands, schema v3 with Task Profile snapshots, and the archive walk. Verified against a synthetic 4-animal, 18-session archive **and** — since 2026-07-27 — the lab's real 306-file Remy archive (item 25). The frontend has still only rendered the synthetic set.

Three things worth carrying forward:

- **The heatmap needed a pooled accuracy figure, and that was only visible once real output existed.** Keyed on a single declared metric, a completely bias-locked animal reads ~0.8 and looks healthy — because "P(R | Odor 1)" is exactly what an animal that always pokes right is best at. Pooled across conditions it sits at chance, which is the truth. Recorded as `analytics.md` §3.7.
- **`compute_series` defaults its boundary codes differently from the live path.** For a multi-metric profile that mis-scores every unanswered trial. One shared helper, and a test that replays a recorded stream through both paths and asserts they agree.
- **Indexes must be applied after migrations, not with the tables.** An index on a column a migration is adding fails on precisely the databases that migration exists for. Found by the v2→v3 test, which is the first thing that ever exercised the branch.

### ~~24. `db.connect` stamps `user_version` without reading it~~ — closed

**Was:** P2, and blocking item 3. `connect()` ran `executescript(SCHEMA)` — all `CREATE TABLE IF NOT EXISTS` — then stamped `PRAGMA user_version` without ever reading it. New *tables* were safe, which is why it never bit: every schema change so far had added tables. A new **column** would have been silently skipped on every existing database while the version was bumped anyway, and the next query would raise `OperationalError` mid-session.

**Now fixed** in `cohorts/db.py`, covered by `tests/test_migrations.py` (12 cases). `connect()` reads the version before `executescript`, applies ordered migrations, and commits once.

Four decisions in the implementation worth carrying forward:

- **Freshness is decided by whether `cohorts` exists, not by `user_version`.** A file written by a build predating versioning reports 0 while holding real tables; trusting that 0 and skipping migrations would be the same silent failure in a different costume. Such a file is treated as v1 so every migration applies.
- **`add_column` is idempotent**, guarded on `PRAGMA table_info`. A migration interrupted by a power loss or a kill during startup has to be safe to re-run, not fatal on the next launch.
- **Startup commits at most once**, and there is a test asserting it. Each commit marks the database dirty for backup, so a migration committing per step would trigger repeated whole-file copies to a possibly-networked target before the app had finished starting.
- **A newer database still opens**, with a loud error rather than a refusal. Every change so far is additive, so the extra tables and columns are inert to an older build — and refusing to start would strand a lab machine that merely ran an older installer.

`MIGRATIONS` is deliberately empty: there is no migration to run yet, because this landed alone as a no-behaviour-change commit. The tests drive the branch directly by registering one, since normal use will not exercise it until the next column lands — which is exactly when a latent bug would have surfaced.

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

### ~~20. `MetricChart.tsx` is built but wired to nothing~~ — closed

**Source:** codebase · `starting-a-session.md` §6.4

**Was:** the zoomed star view showed only a five-row strobe feed; its live charts were deferred, and the component built for them was imported by nothing.

**Closed by building the live panels** (`starting-a-session.md` §6.4, 2026-07-27) — three charts modelled on the lab's previous per-animal software: rolling P(right | odor), cumulative outcome mix, and well-hold durations. `MetricChart.tsx` was **deleted rather than wired**: Analytics had already generalised its idiom into `components/charts/UnitChart.tsx`, which is what the new panels are built on, so re-landing the old component would have meant two chart dialects instead of one.

Two decisions worth carrying forward:

- **All three panels are views of one derived trial record** (`lib/sessions/liveTrials.ts`), so they cannot disagree about what happened. That record is keyed off strobe **names** resolved through the profile, never raw codes — a sketch that renumbers its vocabulary still works, and the app keeps no per-sketch knowledge.
- **The session store keeps its own strobe log**, separate from the console ring. The ring is capped at ~2000 lines and trimmed oldest-first; a real session emits several thousand strobes, so deriving from it would have silently dropped the early trials — precisely the part of a learning curve worth watching.

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

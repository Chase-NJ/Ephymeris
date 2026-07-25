# Ephymeris — Consolidated TO-DO Register

Every open item from all seven specification documents, plus gaps found in the codebase, in one prioritized place.

**This is a derived view.** Each spec's own **Open Items / TBD** table remains the authoritative record for its area; this document aggregates and prioritizes them so nothing is only visible to someone who happened to open the right file. When you close an item, update both the spec and this register.

Last reconciled against the working tree on 2026-07-25.

**Legend:** **P1** blocks shipping v1.0 · **P2** real gap with user-visible consequences · **P3** open decision, no consequence until decided · **P4** deferred by explicit decision

---

## P1 — Blocks shipping v1.0

### 1. Windows packaging is unstarted
**Source:** `ephymeris_v1.0.md` §6

Nothing about shipping exists. Four separate pieces:

- Freezing and bundling the Python sidecar — dev builds run it from `sidecar/.venv`, which won't exist on a lab machine.
- Bundling `arduino-cli` plus the `arduino:avr` core with the installer. The spec commits to no runtime internet dependency; today the app uses whatever the machine already has.
- Tauri Windows bundling and signing.
- A Windows CI build.

This is the largest single body of remaining work, and it was deliberately deferred while v1 was developed. Nothing else on this list matters if the app can't be installed on the two lab machines it exists for.

### 2. Backup Directory is a promise the app doesn't keep
**Source:** `data-saving.md` §8, §11 · `ephymeris_v1.0.md` §6 · `cohorts.md` §12

The setting is collected, persisted, and pushed to the sidecar. Nothing ever writes to it. A user who sets it reasonably believes their data is being mirrored, and it isn't.

Three unbuilt mechanisms:
- Finalization copy of `.json`/`.mat` into the mirror.
- Periodic `.tsv` mirror (~5–10 s cadence, deliberately *not* per-line — the backup target may be slow or networked, and stalling the strobe thread on a remote write would undermine the local durability guarantee).
- `ephymeris.db` backup on app start and after every cohort-affecting write.

The `.tsv` write-ahead log means the *same-disk* crash guarantee already holds; what's missing is the different-disk guarantee against drive failure or accidental deletion.

**Decide explicitly: build it, or hide the field.** Shipping a setting that silently does nothing is the worse of the two.

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

### 6. `sidecar.error` is defined but never emitted
**Source:** `websocket-protocol.md` §4 · `data-saving.md` §7.1

The event exists in the doc and both mirrors. Nothing raises it. Its intended first use is a mid-session `.tsv` write failure (disk full, permissions) — precisely the failure with no command to attribute it to, and precisely the one a user most needs to know about immediately, since it means data is silently not being saved.

### 7. No frontend test runner or linter
**Source:** codebase

`tsc --noEmit` is the entire automated frontend check. The sidecar has 332 tests and the Rust shell has 2; the React layer — including Mission Control, the session flow, and every store — has none.

The wire mirrors are guarded by the contract test, so the highest-risk surface is covered. But store logic (`lib/sessions/store.ts`, `lib/hardware/store.ts`) and the session flow's step transitions are untested code paths that real sessions depend on.

### 8. Debug log export is clipboard-only
**Source:** `hardware-interaction.md` §6.5, §8

The spec asks for "copy log / save debug log"; v1 ships copy-to-clipboard. Saving to a file needs a write path the shell doesn't currently have. **Decide who owns it:** `tauri-plugin-fs` plus a save dialog, or a sidecar-side export command.

---

## P3 — Open decisions

### 9. Migrate `BoardTool` to the arduino-cli gRPC daemon
**Source:** `hardware-interaction.md` §2, §8

**Committed, not conditional** — the subprocess backend is a staging step, not the destination. It was scheduled for after flashing worked end to end so it could be validated against a known-good baseline. That milestone is reached, making this the next hardware-layer task.

Requires vendoring arduino-cli's `.proto` files and adding a `grpcio-tools` codegen step, since there is no official Python gRPC client. It also buys true line-by-line compiler streaming, which `--format json` cannot provide — output currently arrives buffered at phase end.

Weigh against the dependency policy (§6 of the reference): this adds a substantial sidecar build-time dependency to a project that deliberately keeps runtime dependencies at two.

### 10. Multi-port batching for Debug Mode
**Source:** `hardware-interaction.md` §8 · `websocket-protocol.md` §9

Partly answered: the *session* flash sequence is strictly sequential and halts at the first failure, and that's built. Still open is whether Debug Mode wants a "flash all 6" affordance at all, whether it shares the halt policy, and whether it would be one command with six progress streams or six independent commands.

### 11. Full Settings schema
**Source:** `ephymeris_v1.0.md` §4.5, §6

The seven implemented fields (`dataDirectory`, `backupDirectory`, `arduinoDirectory`, `arduinoCliPath`, `defaultBaud`, `boxes`, `reducedMotion`) are described as a starting point, not final. Per-box COM port nicknames exist within `boxes` as `label`. The sidecar reads only the keys it needs and ignores the rest, so adding a field is deliberately a non-event.

### 12. Back-pressure policy for `port.output`
**Source:** `websocket-protocol.md` §9

Currently unbounded send, relying on the ring buffer cap. No policy exists for a frontend that cannot keep up with 20 Hz × 6 boxes. Not observed as a problem — but undefined.

### 13. Constellation adjacency pairs
**Source:** `ephymeris_v1.0.md` §6

The implementation connects `1–2, 2–3, 4–5, 5–6, 1–4, 3–6`, forming one closed shape so no node is orphaned. **Confirm this matches the physical box arrangement on the bench** — if the rig is laid out differently, the map should mirror it. Now that only bound boxes render, a sparse selection can leave nodes with no edges, which makes the pair list more visible than it was.

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

### 17. `MM_DD_YY` date format doesn't sort across a year boundary
**Source:** `data-saving.md` §2

`12_31_26` sorts after `01_01_27` alphabetically. Preserved deliberately to match the lab's existing convention — continuity was judged to matter more than sortability. Noted, not proposed for change; don't "fix" it without talking to the lab.

### 18. Backup cadence specifics
**Source:** `data-saving.md` §11

Blocked on P1 item 2 being built at all. Two sub-questions: the exact `.tsv` mirror interval beyond "every ~5–10 s", and whether `ephymeris.db` needs a periodic timer in addition to "app start plus every cohort-affecting write" when the app runs unattended for long stretches.

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

## Documentation hygiene

Gaps in the docs themselves, found while reconciling them against the code.

### 19. ~~The guided session-flow UI is undocumented~~ — resolved
**Source:** codebase — `src/components/sessions/SessionJourney.tsx`, `RatPlacementBanner.tsx`

**Closed.** The journey rail, the placement banner, and the Analytics session-end landing are now specified in `starting-a-session.md` §6.5, including the rationale for the banner being deliberately off-theme in style while staying inside the six-token palette.

### 20. Zoomed star view diverges from its original spec
**Source:** `starting-a-session.md` §6.4

Already documented as an interim design, flagged here so it isn't forgotten: the zoomed view currently shows a five-row recent-strobe feed, and the rolling live-metric charts originally specified for it live in the general view's metric strip. They are expected to return once the zoomed view's layout settles.

### 21. Substantial uncommitted work in the tree
**Source:** `git status`

At last reconciliation, 30 modified files plus 2 untracked components were uncommitted, spanning the session flow, the sidecar's session repository and runner, and the docs. The specs have been kept current with these changes, but the work isn't committed. Worth landing so the doc-to-code correspondence this register asserts is reproducible from a clean checkout.

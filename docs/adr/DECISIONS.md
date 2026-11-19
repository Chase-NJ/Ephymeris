# Decision record

Every accepted architectural decision, in one file. Each entry says what we decided, why, what we
rejected and what it costs. It is the one place a decision's *reason* lives; the docs it touches say
only what the code does now and link here.

**How to keep it.**

- **Number entries in sequence and never reuse a number.** The next is **0012**. Code and docs cite an
  entry as `DECISIONS.md#<heading-slug>`; `test_doc_links.py` checks every citation.
- **A proposal gets its own file** in this folder (`NNNN-slug.md`, `status: proposed`) while it is
  argued and built. When it is accepted and done, fold it in here as an entry and delete the file.
  [0009](0009-run-document-v2-and-the-analysis-file.md) is the open proposal. A proposal that is
  withdrawn instead gets a short entry here saying why and what of it shipped, and its file is deleted.
- **Amend in place.** Add a dated **Amendment** to the entry rather than a new entry, unless the decision
  itself reverses.
- **Supersede, don't delete.** A reversed decision keeps a short entry saying what replaced it and what
  part of its reasoning still holds, so nobody re-argues it from scratch.
- Lessons that are not decisions (bugs that taught a rule, traps, process) go in
  [LESSONS.md](../LESSONS.md).

| # | Decision | Status | Accepted |
|---|---|---|---|
| [0001](#0001-a-hypothetical-rig-definition-is-context-local) | A hypothetical rig definition is context-local | accepted | 2026-10-10 |
| [0002](#0002-restores-upload-side-by-side) | Restores upload side by side | superseded by 0004 | 2026-10-29 |
| [0003](#0003-a-task-is-a-phase-spine-lowered-and-replayed) | A task is a phase spine, lowered and replayed | withdrawn 2026-11-19 | — |
| [0004](#0004-restores-share-one-compile-and-upload-in-turn) | Restores share one compile and upload in turn | accepted | 2026-11-05 |
| [0005](#0005-a-spine-run-strobes-each-trials-outcome-class) | A spine run strobes each trial's outcome class | withdrawn with 0003, 2026-11-19 | 2026-11-05 |
| [0006](#0006-the-shell-is-electron-not-tauri) | The shell is Electron, not Tauri | accepted, Tauri removed | 2026-11-13 |
| [0007](#0007-rhxs-own-windows-replace-the-recording-pop-ups) | RHX's own windows replace the recording pop-ups | accepted | 2026-11-15 |
| [0008](#0008-rounds-replace-groups) | Rounds replace groups | accepted | 2026-11-18 |
| [0009](0009-run-document-v2-and-the-analysis-file.md) | A run's document is nested and versioned, and a recorded run gets one analysis file | **proposed** | — |
| [0010](#0010-the-log-is-a-paper-notebook) | The Log is a paper notebook | accepted | 2026-11-19 |
| [0011](#0011-the-log-travels-in-the-session-folder) | The log travels in the session folder | accepted | 2026-11-19 |

## 0001: A hypothetical rig definition is context-local

Previews ask "what would this wiring or vocabulary break?" by validating every saved task under a
hypothetical [rig definition](../../GLOSSARY.md#rig-definition). They used to install it process-wide
with `set_rig_source` / `set_vocabulary_source` and restore it afterwards, which let any thread reading
at that moment, above all the rebuild that writes every `TaskPins.h`, generate from previewed pins or
codes. **We put the hypothetical in a `ContextVar` (`registry.hypothetical`)**, seen only by the code
that installed it and the `asyncio.to_thread` worker it runs in.

**Rejected.**

- *Pass a `ChannelMap` / `Vocabulary` explicitly* through `validate`, `failures` and the generators.
  Honest, but it threads a parameter through every path that calls `channels()` for a value that changes
  a few times a year; the registry's module-level injection exists to avoid exactly that.
- *Keep the process-wide swap and lock every reader.* Readers run on the event loop and in many unlocked
  workers; a lock held for a preview would stall the loop, and a missed reader brings the bug back
  silently.

**Consequences.** A preview must not start its own thread inside `registry.hypothetical`: a plain
`threading.Thread` starts with an empty context and would read the definition in force.
`asyncio.to_thread` copies the context and is fine.

## 0002: Restores upload side by side

**Superseded by [0004](#0004-restores-share-one-compile-and-upload-in-turn).** It let utility baseline
restores share one compile and upload to their six ports at once, to cut a cold start from six serial
flashes. The shared compile still stands. The concurrent uploads were reversed: they were safe for the
software (six ports, one read-only build) but not for the wire.

## 0003: A task is a phase spine, lowered and replayed

**Withdrawn 2026-11-19, never accepted.** The proposal made a task an ordered spine of phases from a
fixed palette, lowered to a state table that one firmware interpreter walked, and scored every run by
replaying it in a Python port of that interpreter. It was built behind a development flag and ran on a
Mega only with nothing wired; no spine run was ever recorded on a real box. We removed it from the
repository, firmware, wire and editor included, to put the lab's effort into the trial-table task (GRGL)
it was meant to replace. A successor will be proposed under a new number; the proposal's text is in git
history (`docs/adr/0003-phase-spine-task-model.md`).

**What shipped and stays.** Its rig model is in force and documented where it lives:

- the lab-wide [channel set](../../GLOSSARY.md#channel-set) beside a per-machine pin map, moved between
  machines whole ([TASKS.md](../TASKS.md#the-channel-set-and-the-pin-map));
- a channel's `type`, `mode` and `role`, its [edge codes](../TASKS.md#edge-codes), the rules RIG107 and
  RIG109, and the box utility testing each [driven output](../TASKS.md#driven-outputs);
- the outcome classes, which the [trial table](../../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#the-trial-table)
  of every run still uses.

**What it leaves behind.** A file that says the spine interpreter recorded it is reported unreadable and
never decoded ([ANALYTICS.md](../../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#why-a-run-has-no-numbers)),
and a stored task definition with a `spine` key is listed as unreadable
([TASKS.md](../TASKS.md#what-a-definition-holds)). `session_animal_runs.diverged` stays as an unused column.

## 0004: Restores share one compile and upload in turn

The flash queue once ran one whole flash at a time, rig-wide: two `arduino-cli` builds at once are slower
than one after the other on the lab machines, and a half-flashed pair is worse than a whole one. That
made a cold start six restores in a row. **Restores of the box utility now run side by side and share
one compile (`SharedBuilds`, `ports/flashing.py`), but their uploads take turns**: one rig-wide upload
lock inside the build gate, so only one `avrdude` talks to a board at a time, whoever asked for the
flash. Session and Debug flashes run alone, as before.

**Why share the compile.** The serial rule rested on the build, and an upload builds nothing: it runs
`avrdude` against the build `arduino-cli` left in its build directory, which the uploads only read.

**Why upload in turn** (the reversal of 0002). On a lab machine, one box's restore at startup failed
intermittently, and a later flash of the same box failed avrdude's read-back with a verification
mismatch. Six uploads at once is the heaviest load the rig ever puts on its USB path: every board
resetting into its bootloader and taking page writes at the same moment, through shared hubs and their
power. A marginal link survives a lone upload and fails under that load. Uploading in turn removes the
rig's only many-boards-at-once electrical event.

**Rejected.**

- *Run whole flashes, compile included, side by side.* Brings back concurrent builds, and a compile of a
  folder rewrites the build an upload of that folder is reading.
- *Defer the cold restore until a box is needed.* The placement walk is the first thing that needs every
  box, and it would then wait for six flashes in a row anyway.
- *Run whole restores one at a time through the queue's scheduling* (`_next_runnable`). A build is
  retired when its last upload ends, so each restore would compile the box utility again: several
  seconds a box on Windows, even with a warm cache.
- *Serialize only startup restores.* A wiring save or a vocabulary edit (`rebuilt()`) and **Reflash
  boxes** restore every box at once too, with the same load on the same path.
- *Parallelise every origin.* A session or Debug flash is something a person is watching; alone, it never
  shares a compile with a restore or rebuilds a folder whose build a restore is uploading.
- *Leave uploads concurrent and fix the hardware.* Fix it regardless; but uploading in turn costs about
  3 s per box at startup and makes a weak link fail less often and easier to tell from a bad board.

**Consequences.**

- A cold start takes one upload per box in turn, about 20 s for six boxes.
- A compile of a folder must wait until every upload of its older build has ended. `SharedBuilds` does
  this; a flash outside the queue would not.
- A restore takes its port before it waits its turn, so every box being restored reads as flashing until
  its own upload ends.
- Restores each hold the rig definition's read side until their upload lands, so a waiting write waits
  for the last of them.
- A cold start with a broken build fails every restore that shared the compile, the same result six
  serial compiles would reach.

## 0005: A spine run strobes each trial's outcome class

**Withdrawn 2026-11-19 with [0003](#0003-a-task-is-a-phase-spine-lowered-and-replayed)**, whose runs it
described. It had every trial of a spine run strobe its outcome class as one of eight fixed, lab-wide
`OUTCOME_*` codes, which replay predicted and checked, so a raw file could be counted without replay.
The codes had already left the shipped vocabulary on 2026-11-06, with `BLOCK_START`, so that
[stream grammar 2](../TASKS.md#stream-grammar) could be issued under the names it wanted, and no real
box recorded one. Two parts of its reasoning still hold: a trial's verdict belongs in the stream as a
code of its own, which grammar 2 does with exactly one outcome code per trial; and the wire stays a code
and a timestamp, never a code carrying a value.

## 0006: The shell is Electron, not Tauri

Ephymeris must keep running the lab's sessions for years after its author graduates, maintained by
whoever is in the lab, who will most likely know Python and perhaps TypeScript but not Rust. The shell
is small (about 700 lines of Rust: start and stop the sidecar, size the window, check for and install
updates), but it was the one part nobody after the author could change, and it rendered through a
browser engine Windows replaces underneath it. **We replace the Tauri shell with an Electron shell
written in TypeScript, and leave the sidecar, the webview and the wire as they are.**

**The decision.**

- **Electron owns what the Rust shell owned, and nothing more**: the frameless main window and recording
  pop-ups, starting the sidecar and reading its handshake line, holding its stdin open, stopping it
  before an update and on exit, folder and save dialogs, file writes, open-in-file-manager, the settings
  store and the app version.
- **The webview reaches the shell through one module**, `src/lib/shell/`, so a shell change is one
  implementation behind it rather than many edits. A test fails on any other file that names a shell API.
- **The sidecar does not change.** It binds a loopback port, prints
  `EPHYMERIS_WS_PORT=… EPHYMERIS_WS_TOKEN=…`, and watches stdin to notice a dead shell.
- **The installer stays NSIS**, built by `electron-builder`, carrying the frozen sidecar, `arduino-cli`
  with its seeded core, and the sketch library.
- **Updates keep their shape**: ask a feed, download, stop the sidecar, hand over; the operator clicks to
  install, only when no session is running. `electron-updater` replaces Tauri's updater plugin.
- **An installed Tauri copy becomes an Electron copy by an ordinary update**, once per lab PC, with
  someone watching. Settings and data carry over.

**Why.**

- **The renderer stops changing.** Tauri draws with the PC's WebView2, which Windows updates on its own
  schedule; Electron carries its own Chromium, so a copy installed in 2027 draws the same in 2032.
- **One engine everywhere.** Development on macOS was WebKit and the lab was Chromium; now both are the
  Chromium the installer carries.
- **One toolchain fewer.** Rebuilding needs Node and Python; Rust, cargo and the MSVC build tools go.
- **The shell is in a language the webview already uses.**

**Rejected.**

- *Stay on Tauri*: keeps Rust and the moving WebView2, the two things most likely to strand an
  unmaintained copy.
- *A Python shell (pywebview)*: still WebView2, and no updater, so we would write and maintain one.
- *No shell, the sidecar serves a browser tab*: no self-update, no native folder dialog, and no window
  owning the sidecar's life; an operator could close a tab mid-session, or open two.
- *Electron, updated by hand*: fixes must still reach two PCs without the author present. It stays the
  fallback if the update check ever proves unsound.

**Consequences.**

- The installer grows by about 100 MB and the app uses more memory; neither matters on two dedicated PCs.
- **The bundled Chromium is never patched unless someone rebuilds.** Acceptable only because the webview
  loads its own pages and talks to its own sidecar on loopback. A feature that loads a remote page
  reopens this decision.
- **The update address is baked into every copy.** The repository stays at `Chase-NJ/Ephymeris`, so the
  feed URL the first Electron build carries is the permanent one. Moving the repository strands copies.
- **The verbatim-path rule goes away with the Rust shell.** `simplified()` exists because Tauri's
  `resource_dir()` returns `\\?\C:\…` on Windows, which `arduino-cli` silently mishandles. Delete it
  only after the packaged Electron build has compiled a sketch on Windows.
- **The stop-before-install order is rebuilt, not assumed**: the download is complete and checked before
  the sidecar is touched, and the sidecar finishes its own shutdown (stopping the `arduino-cli` daemon)
  before the installer starts, or the installer finds `arduino-cli.exe` locked.
- **Two shells live in the repository until both lab PCs run Electron**; then `src-tauri/` goes.

> **Amendment, 2026-11-15: updates are checked by hash only.** Tried on Windows with the real app: an
> installed `1.1.3-alpha.900` updated itself to `.901` from a local feed, with the sidecar and its
> `arduino-cli` daemon running.
>
> - **What ships is the sha512 in `latest.yml`, over HTTPS from the repository.** `electron-updater`
>   refused a download whose hash did not match (`ERR_CHECKSUM_MISMATCH`) before the sidecar was
>   touched. A signed manifest would be our own Ed25519 check, but its key would sit in the same
>   repository's secrets as the feed it signs, so it buys little, and it brings back the one failure this
>   decision set out to avoid: a lost key that strands every copy. If the feed ever moves somewhere the
>   repository does not control, add the signature then.
> - **The crossover.** The Electron installer goes to `%LOCALAPPDATA%\Programs\Ephymeris`, beside the
>   Tauri copy's `%LOCALAPPDATA%\Ephymeris`. A Tauri copy is offered the Electron installer signed with
>   the Tauri updater's key; its updater stops the sidecar and launches it; the installer silently
>   uninstalls the Tauri copy (which keeps app data), makes the `Ephymeris` Start Menu and desktop
>   shortcuts, and starts the Electron copy. Neither installer touches `%APPDATA%\edu.hartlab.ephymeris`.
>   Rehearsed end to end: same data and confirmed wiring, a run on a real box, a scope window, update
>   check current.

> **Amendment, 2026-11-17: `src-tauri/` is gone.** A lab session ran on the Electron build, so the Rust
> shell, its npm packages, its CI job and the Tauri signing step left the repository; `simplified()` went
> with it, and `discovery._plain()` still strips a verbatim prefix in Python.
>
> - **The crossover stays open without Tauri in the build.** Nothing writes `latest.json` any more; it
>   stays on the `updates` branch pointing at `v2.0.0-beta`, whose Electron installer carries the Tauri
>   signature. A copy still on Tauri crosses over to that release and then follows `latest.yml`. The
>   Tauri signing key is no longer needed to ship.

## 0007: RHX's own windows replace the recording pop-ups

Ephymeris drew four recording pop-ups of its own: Spike Scope, PSTH, ISI and a probe map, each an OS
window computed from RHX's data sockets. **They are gone. RHX's own Spike Scope, ISI, PSTH and Probe Map
windows serve one channel at a time, and Ephymeris keeps only what RHX cannot show: a live firing map of
every recorded box's probe, inline in Mission Control** ([RECORDING.md](../RECORDING.md#live-firing-map)).

**Why.** The pop-ups duplicated what RHX already does, with its own threshold handling, and cost the most
fragile code the recording had: a frame layout that changed mid-run (switched on a sample marker, since a
same-size change cannot be told by framing), snippet cutting, scope keep-alives, a second provider tree
per window, and pop-up permissions in both shells. A probe map that feels live is the one view RHX has no
equivalent of across boxes, and the old one, a one-second count sent five times a second and shaded
against the busiest site, did not feel live.

**Rejected.**

- *Open RHX's windows over TCP.* The protocol has no command for it, nor to load a probe map.
- *Keep the pop-ups and fix the probe map.* Every pop-up is another window for the shell to own, and
  three of the four repeat RHX.
- *Keep a PSTH aligned to a named event.* RHX's PSTH triggers on a digital-input edge, and every event
  on a box pulses the same sync line, so only Ephymeris could align to a named event live. It is the
  real loss. It is better done offline from RHX's spike files and the `.tsv`, on complete data.

**Consequences.**

- The data sockets stream only spikes and the digital-input word, a layout fixed at `intan.configure`.
- A threshold for one channel is set in RHX's Spike Scope; `intan.configure` still sets them all.
- The shells have one window: no `openWindow`, no `scope-*` permissions.
- A live, event-aligned PSTH is not available during a session.

**Amendment, 2026-11-15.** The event-aligned PSTH returned **after** the session, as this entry said it
should: computed from RHX's saved spikes and digital inputs and the run's strobes, in Analytics
([RECORDING.md](../RECORDING.md#event-psth)). Still not live, by design.

## 0008: Rounds replace groups

A cohort's animals were divided into **groups**: each animal belonged to exactly one, held a box unique
within it, and a session ran one group at a time. The lab swaps animals between boxes and runs them out
of their usual order often enough that the fixed membership was the obstacle, not the help: every
exception meant editing the cohort first. **We removed groups. A session is a sequence of
[rounds](../../GLOSSARY.md#round), and each round's animals, boxes and tasks are chosen at set-up**
([ARCHITECTURE.md](../ARCHITECTURE.md#mapping-and-the-placement-walk)). An animal keeps one optional
[usual box](../../GLOSSARY.md#usual-box) that set-up offers first; when a round's boxes have all finished
the operator is asked whether to run more animals or end the session
([ARCHITECTURE.md](../ARCHITECTURE.md#between-rounds)).

The sidecar never enforced a group's membership or its boxes at `sessions.confirmMapping`: the constraint
lived in the cohort model and the screens, so the session path changed little.

**Rejected.**

- **Keep groups as optional presets** that pre-fill a round. Two ways to say who runs together, one of
  them stale the first time an animal is swapped, and the group step stays in the flow for everyone.
- **No stored box at all**, pre-filling from each animal's last run. The lab does have usual boxes; a
  cohort that has never run would open on an empty rig, and one odd day would become the next day's
  default.
- **A usual box that must be unique in the cohort.** A cohort of twelve on six boxes shares them by
  design. A clash matters only among the animals of one round, and set-up resolves it there.

**Costs.**

- **Schema v17 is the first migration that is not additive** ([DATA.md](../DATA.md#changing-the-schema)):
  the `groups` table and `animals.group_id` are gone, so a build older than v17 cannot open a migrated
  database. Both lab machines must be updated together.
- **Auto-Balance is gone** with the groups it balanced. Balancing a round by sex is now the operator's
  job at set-up.
- A round recorded before this keeps its group's name as `Round.label`; a round recorded since has only
  its order. Which animals ran in a round is read from the run records' start times, as before.
- An RHX recording is named for the animals recorded rather than for a group, so its name grows with the
  number of boxes recorded.

## 0010: The Log is a paper notebook

The Log was built from the same glass tiles as every other screen: a flight-recorder rail of sessions on
the left, the selected session's readout on the right. It held everything a lab notebook holds and read
like a dashboard, and it was the one place the instrument's look worked against the job: a notebook is
read in long sittings, written in with hands full, and compared page against page.
**We made the Log a paper notebook on a desk: light, typeset like a LaTeX document, one spread per
session, navigated by turning pages** ([ARCHITECTURE.md](../ARCHITECTURE.md#the-paper-exception)). It
is the single exception to "dark mode only" and to "no shadows", and it is fenced: the paper tokens, the
serif and the shadows live under `.paper` and nowhere else.

The same change gave the notebook two things it lacked. **Weigh-ins**, entered in a table on each
session's right page and kept per animal and day ([DATA.md](../DATA.md#weigh-ins)). And, for recorded
sessions, **an estimate of how much there is to sort**: how many of an animal's electrode sites carried
unit-like signal, measured after the recording stops in the pass that already reads its spikes
([RECORDING.md](../RECORDING.md#unit-like-sites)).

**Rejected.**

- **Restyle the tiles and keep the rail.** A warmer dashboard is still a dashboard: the rail and the
  page compete for the eye, and a session's content stays cut into boxes that hide how little or how
  much was written.
- **A light theme for the whole app.** The rig room is dim and the instrument screens are glanced at
  from across it; only the notebook is read.
- **Sort spikes, or cluster them, to count units.** Sorting stays in Offline Sorter
  ([ADR 0009](0009-run-document-v2-and-the-analysis-file.md)). The estimate needs no clustering: a site
  either has large spikes arriving steadily or it does not, and that is enough to order the sorting by.
- **Judge the sites in the sidecar.** The thresholds are first guesses. Kept as raw measurements and
  judged in the webview, a changed threshold re-reads every recorded run, as
  [active-site yield](../RECORDING.md#active-site-yield) already does.

**Costs.**

- **Two visual systems.** A shared control (`Button`, `Dropdown`) cannot be used on a page, so the
  notebook has its own small set; the caution in ARCHITECTURE.md is what keeps the two apart.
- **One more bundled face.** Latin Modern Roman, four files and about 190 KB, from the `latex.css`
  package, pinned exactly; nothing else of the package is imported.
- **A bright surface in a dim room.** Paper is a warm off-white, not white, and the desk stays dark, but
  the Log is now the brightest screen in the app.
- **The estimate is unvalidated against sorted data.** It counts sites, not neurons, and a site with two
  good units counts once. It ranks days; it is not a yield figure for a paper.
- **Schema v19**: two new tables and no migration ([DATA.md](../DATA.md#changing-the-schema)).

## 0011: The log travels in the session folder

A session's notes, operator, summary and weigh-ins lived only in the database of the machine that
recorded it. Its folder got `notes.md`, which no code reads. So a session copied to the other lab
machine arrived as a recovered one: its runs, no notes, and no way to add any, since a recovered
session has no record to hang a note on. **We kept the database as the place the log is kept and
worked on, and made the folder carry a complete copy a machine can read**: `log.json`, written with
every change and read back by a Rescan and before every rewrite
([DATA.md](../DATA.md#the-log-file)). A session another machine ran is recorded from it, so the day
is a session like any other on both machines.

**Rejected.**

- **The folder's file as the only home**, the database dropping its log tables or keeping them as a
  cache. One home for the fact, and nothing to merge. But a note is taken mid-session, and today it
  is one database write that never waits on the data folder; with the file as the truth, a slow or
  unplugged drive fails the note or needs a queue, and the Log needs a cache to open at all with the
  drive away. A queue and a cache in front of a file are this decision with the conflict rule
  hidden.
- **Read `notes.md` back.** It is prose for a person: no ids, no stamps, no deletions.
- **Replace the database's log with the file's on a rescan.** The older of two copies would erase
  what was written since it was made. Reading is a merge, per note.
- **Carry no deletions.** Without a marker, a note deleted here returns from the other machine's copy
  at the next read. So a deleted note and a removed weigh-in stay in the file as markers, and a
  removed weigh-in stays in the database as one (schema v20).

**Costs.**

- **Two copies, and a rule for when they disagree**: the newer wins, by the machines' own clocks. A
  machine with a wrong clock wins or loses edits it should not.
- **A session record can now come from a file.** It is recorded as ended, with no recording, and is
  never updated from the file again; one this machine ran is never touched.
- **Animals are matched by name.** A cohort on the second machine needs the same names, and a rename
  on one machine alone splits an animal's notes from it until the other is renamed.
- **Some things do not travel**: a reopened flag (it has no time of its own), and what was measured
  of a recording, which stays with the run records of the machine that recorded it.
- **Every session folder gains a file**, written at the session's end and at a rescan, and backed up
  with the rest.

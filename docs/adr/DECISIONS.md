# Decision record

Every accepted architectural decision, in one file. Each entry says what we decided, why, what we
rejected and what it costs. It is the one place a decision's *reason* lives; the docs it touches say
only what the code does now and link here.

**How to keep it.**

- **Number entries in sequence and never reuse a number.** The next is **0008**. Code and docs cite an
  entry as `DECISIONS.md#<heading-slug>`; `test_doc_links.py` checks every citation.
- **A proposal gets its own file** in this folder (`NNNN-slug.md`, `status: proposed`) while it is
  argued and built. When it is accepted and done, fold it in here as an entry and delete the file.
  [0003](0003-phase-spine-task-model.md) is the one open proposal.
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
| [0003](0003-phase-spine-task-model.md) | A task is a phase spine, lowered and replayed | **proposed**, being built | — |
| [0004](#0004-restores-share-one-compile-and-upload-in-turn) | Restores share one compile and upload in turn | accepted | 2026-11-05 |
| [0005](#0005-a-spine-run-strobes-each-trials-outcome-class) | A spine run strobes each trial's outcome class | accepted, codes withdrawn for now | 2026-11-05 |
| [0006](#0006-the-shell-is-electron-not-tauri) | The shell is Electron, not Tauri | accepted, rollout under way | 2026-11-13 |
| [0007](#0007-rhxs-own-windows-replace-the-recording-pop-ups) | RHX's own windows replace the recording pop-ups | accepted | 2026-11-15 |

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

> **Amendment, 2026-11-06.** The eight outcome codes and `BLOCK_START` were withdrawn from the shipped
> vocabulary while the spine is in development (no spine run has been recorded on a real box), so that
> [stream grammar 2](../TASKS.md#stream-grammar) could be issued under the names it wanted;
> `TRIAL_START` moved to 220, shared with the trial runner. The decision stands; a machine that runs a
> spine task adds the codes on the Strobes page until the spine ships them again.

[0003](0003-phase-spine-task-model.md#the-strobe-stream) left outcome codes out of a spine run's stream:
the board strobes what it observed and what it did, and replay supplies the meaning. That keeps the
stream honest, but a spine `.tsv` is then unreadable without replay: a script cannot count correct
trials, a Debug Mode run (no live replay) shows no verdict, and a recording has no event at the moment a
trial was decided. **Every trial a spine run marks strobes its outcome class, as one of eight fixed,
lab-wide codes, and replay predicts them.** The stream gains a verdict nobody has to trust.

**The decision.**

- **Eight structural codes**, one per class of `lowering.OUTCOME_CLASSES`: `OUTCOME_CORRECT`,
  `OUTCOME_WRONG_RESPONSE`, `OUTCOME_HOLD_BROKEN`, `OUTCOME_OMISSION`, `OUTCOME_WITHHELD`,
  `OUTCOME_FALSE_ALARM`, `OUTCOME_ABORT_BEFORE_STIMULUS`, `OUTCOME_ABORT_DURING_SAMPLING`. Their numbers
  live only in the strobe vocabulary.
- **When:** at the tick the trial enters its marked state, the one state per trial with a non-zero
  `outcome` ([TASKS.md](../TASKS.md#lowering)). For a Response window, the response's branch after any
  hold; for an early exit, the exit's end. A trial that never marks (End Session, crash, disconnect)
  strobes none; its absence is the trial table's `complete: false`.
- **Where in the tick:** last, after the outputs driven HIGH and before only `END_SESSION`. Every strobe
  of a tick shares its one sync pulse ([RECORDING.md](../RECORDING.md#the-sync-line)), so order costs
  no alignment; a tick whose only strobe is a mark still pulses.
- **Derived from what the board already reports.** The core lists the states each tick entered
  (`InterpActions.entered`); the runner looks up each one's `outcome` and strobes the code. Replay
  already predicts `entered`, and the
  [differential test](../TASKS.md#compiling-and-the-host-tests) already holds it equal between the C
  core and the Python port.
- **Versioned as `INTERP` 8.** Replay predicts outcome strobes only for runs whose header says 8 or
  later; runs at 2 to 7 replay as before.
- **Checked, never read.** Analysis still scores a spine run by replay. The outcome strobes join the
  outputs in the checksum: a mismatch at any tick makes the run **diverged**.

**Rejected.**

- *Keep the stream free of verdicts* (0003 as written): every reader of a raw file then needs replay.
- *Reuse GRGL's codes* (`END_CORRECT_ITI`, `RESP_OMIT`, …): they mix the side into the verdict, cover
  GRGL's cases rather than the eight classes, and retire at the cutover, never reissued.
- *One code carrying the class as a value*: the wire is a code and a timestamp (`^\d{1,3}\t\d+$`,
  [DATA.md](../DATA.md#crash-recovery)); a value changes the line format for every reader.
- *A strobe at each trial's end* (its ITI entry): the decision happens at the mark, and an ITI's start
  is already visible from its outputs.
- *A code for every state entry*: spends vocabulary per task or makes a code's meaning task-dependent.
  Outcome codes escape that objection only because the class set is fixed lab-wide.
- *A separate `STREAM=` announcement beside `INTERP=`*: replay keys every reproduction rule on `INTERP`,
  and two numbers would have to be kept in step on every board and header.

**Consequences.**

- One more strobe per marked trial (a correct odor 2AFC trial: 13 → 14).
- A machine seeded before the codes existed must add them at the numbers the shipped default gives;
  `SPN104` flags a missing one ([TASKS.md](../TASKS.md#spine-diagnostics)).
- The stream order changes in `BoxSpine.h` and `analytics/stream/spine.py` **together**, or every
  `INTERP` 8 run reads as diverged. The host tests check each marked trial strobes its class once, at
  its tick, last.
- A raw spine file is countable without replay, but its counts are not the scorer's: P(correct) excludes
  aborts and block criteria read class sets. Analysis keeps reading the trial table.
- Every spine task's `profile_hash` moved when next saved (the hash covers `INTERP`); no animal had run a
  spine task, so no history split. The score canary moved once.
- The codes cost no RAM: `BoxSpine.h` keeps them in `PROGMEM`.

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

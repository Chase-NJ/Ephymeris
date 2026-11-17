# Design decisions and lessons

The project's principles, the rules that are easy to break, and what was learned the hard way, on one
page. Read it before a change you are unsure of, and before you argue for something that sounds simpler.

**How this page relates to the rest.**

- Each line here is short and links to its home. Where a rule's full explanation lives in another doc,
  this page only names it; don't copy the detail here.
- **This page is the home of lessons that have no other home**: bugs that taught a rule, approaches that
  were tried and abandoned, and process. The repository's history was reset on 2026-11-15, so the commit
  messages that used to hold these are gone. A new lesson goes here as a rule with its reason, never as a
  story.
- Accepted architectural decisions, with their reasons and rejected options, live in the
  [decision record](adr/DECISIONS.md).

## Principles

The design in a dozen lines. Each is a decision the rest of the code leans on.

1. **The sidecar owns all state.** It refuses an illegal operation with a typed error code; a disabled
   button is only a courtesy, and the UI never predicts ([ARCHITECTURE.md](ARCHITECTURE.md#overview)).
2. **Nothing slow or optional may stall a session.** Backup, RHX and the live scorer may each be slow or
   dead, and the session goes on ([ARCHITECTURE.md](ARCHITECTURE.md#overview),
   [RECORDING.md](RECORDING.md#the-rule)).
3. **The `.tsv` is the record.** Every strobe is fsync'd to it live; the `.json` and `.mat` are built once,
   atomically, at a clean end ([DATA.md](DATA.md#crash-safety)). So nothing resumes a run mid-way and the
   sidecar is never respawned: either would come back without the state it had
   ([DEVELOPING.md](DEVELOPING.md#deferred-by-decision)).
4. **One wire, declared once.** `protocol/schema.py` generates every mirror; state goes in snapshots
   replayed on connect, changes in broadcasts ([ARCHITECTURE.md](ARCHITECTURE.md#wire-protocol),
   [ARCHITECTURE.md](ARCHITECTURE.md#replay-on-connect)).
5. **Codes have names; numbers live in one place.** The strobe vocabulary is the only definition of a
   code, and it is append-only ([TASKS.md](TASKS.md#strobe-vocabulary)).
6. **Pins, codes and sizes are compiled; values travel on `SET` lines.** One binary serves six
   differently tuned boxes ([TASKS.md](TASKS.md#two-places-a-value-can-come-from)).
7. **No sketch is special-cased.** A special case means the task profile is missing a declaration
   ([TASKS.md](TASKS.md#overview)).
8. **Everything is derived at read time, by one scorer** for live and offline; `analytics/stream/` is
   pure, and every number carries its n and a 95% interval
   ([ANALYTICS.md](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#start-here),
   [ANALYTICS.md](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#uncertainty)).
9. **A bad file is data, not an error.** A run with nothing countable reads `null`, never 0
   ([ANALYTICS.md](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#why-a-run-has-no-numbers)).
10. **Only starting a recording may refuse.** A session missing its electrophysiology cannot be re-run;
    after that, RHX trouble never stops behaviour ([RECORDING.md](RECORDING.md#the-rule)).
11. **Publishing is shipping, and there are no downgrades.** Fix forward
    ([ARCHITECTURE.md](ARCHITECTURE.md#updates)).
12. **Built to outlive its author.** Prefer what a successor who knows Python, and maybe TypeScript, can
    change: stdlib first, a short [dependency policy](DEVELOPING.md#dependency-policy), and the shell in
    TypeScript ([decision 0006](adr/DECISIONS.md#0006-the-shell-is-electron-not-tauri)).

## Rules that are easy to break

Each rule says what goes wrong if you forget it. The ones marked **⚠** yield plausible but wrong data
rather than an error, which is the worst kind of failure here.

### Data and names

- **⚠ Never sort names, dates or numbers as strings.** Order session names with `sessions/paths.py`'s
  `parse_name_date` ([DATA.md](DATA.md#session-order)). Dates in names are hyphenated ISO, because
  `MM_DD_YY` does not sort across years ([DATA.md](DATA.md#why-the-date-is-hyphenated)).
- **Read names as written**, never normalize them ([DATA.md](DATA.md#reading-names-other-software-wrote)).
- **A new database column** needs `SCHEMA_VERSION`, `SCHEMA`, a `MIGRATIONS` entry and a `vN.sql`
  fixture; a migration never reinterprets data ([DATA.md](DATA.md#changing-the-schema)).
- **Index `animal_id`; never give it a foreign key.** A roster save re-inserts animals, and a cascade
  would wipe history ([DATA.md](DATA.md#indexes)).
- **Keep `db.DATA_PATHS` complete.** A path column it does not classify is not moved by a relocate, and
  the next Rescan prunes the records ([DATA.md](DATA.md#data-folder)).
- **Absence counts only when the storage is reachable.** An unseen file is never read as deleted
  ([DATA.md](DATA.md#pruning), [DATA.md](DATA.md#verified-transfer)).
- **Run a cohort move on the other machine first**, or its rescan prunes the moved runs
  ([DATA.md](DATA.md#moving-animals-between-cohorts)).
- **⚠ Move the score version on any scoring change.** The cache is served verbatim
  ([DATA.md](DATA.md#caching)); `replay_version` moves with any change to the derived trial table
  ([DATA.md](DATA.md#the-derived-trial-table)).
- **In the `.mat`, a null is `NaN` or `''`, never `[]`** ([DATA.md](DATA.md#the-derived-trial-table)).
- **`to_json` must round-trip byte for byte**, and anything in it moves `profile_hash`. Never add a
  `states` or `graph` key ([TASKS.md](TASKS.md#profile-and-params-hashes),
  [DATA.md](DATA.md#the-embedded-task-profile)).

### Strobes, tasks and wiring

- **⚠ Refer to a code by name.** Never copy a number into code, `task.json`, firmware or tests
  ([TASKS.md](TASKS.md#strobe-vocabulary)). Match names anchored: an unanchored `LIGHTS_OFF` matched
  more than it meant ([ANALYTICS.md](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#engagement-ladder)).
- **Never renumber, repurpose or reissue a code.** Retire it; remove it only if no session ever recorded
  it ([TASKS.md](TASKS.md#append-only)).
- **⚠ Channel declaration order is the odor index.** Reordering silently swaps odors; use
  `declared_of_kind()` ([TASKS.md](TASKS.md#order-is-meaning)). Never find "the first emitter" by sorting
  pins: the Mega's odor pins interleave (22, 24, …, 32, then 23, …, 33).
- **⚠ A box starts only on the current build of its mapped sketch.** Every sketch prints `READY`, so
  `READY` proves nothing about what a board carries ([ARCHITECTURE.md](ARCHITECTURE.md#what-a-board-carries)).
- **Every rebuild goes through `_rebuild`**, and a preview reads a context-local hypothetical, or stale
  folders flash old pins ([TASKS.md](TASKS.md#the-rig-definition),
  [decision 0001](adr/DECISIONS.md#0001-a-hypothetical-rig-definition-is-context-local)).
- **Only wiring confirmed on this machine is in force**; anything else is held (RIG108)
  ([TASKS.md](TASKS.md#the-channel-set-and-the-pin-map)).
- **Never send a bare `START`.** It goes only after every `PARAMS <n> <crc32>` matches and nothing was
  clamped ([TASKS.md](TASKS.md#confirming-the-parameters)). Keep `SET_LINE_MAX` equal on both sides, or
  lines truncate silently ([TASKS.md](TASKS.md#the-length-cap)).
- **A firmware count moves with its key list**, or a buffer overruns ([TASKS.md](TASKS.md#firmware)).
- **Change `BoxInterp.h` with `replay.py`, and `BoxSpine.h` with `analytics/stream/spine.py`**, in one
  change. The differential test holds the first pair equal
  ([TASKS.md](TASKS.md#compiling-and-the-host-tests)).
- **Compile firmware with `--warnings all` and run the host tests.** The Arduino build hides warnings
  (`-fpermissive`) that are real bugs on AVR ([TASKS.md](TASKS.md#compiling-and-the-host-tests)).
- **A spine task's RAM is capped**, because running past it overflows the stack silently
  ([TASKS.md](TASKS.md#spine-diagnostics)).

### Ports, flashing and sessions

- **Box number 1–6 is the key everywhere**, never a COM address; COM ports renumber
  ([ARCHITECTURE.md](ARCHITECTURE.md#overview)).
- **Every port state change goes through `assert_transition`**
  ([ARCHITECTURE.md](ARCHITECTURE.md#port-state-machine)). No optimistic port state in the UI
  ([ARCHITECTURE.md](ARCHITECTURE.md#invariants)).
- **Only `FlashQueue` calls `PortManager.flash`.** There is exactly one flash queue, in the sidecar
  ([ARCHITECTURE.md](ARCHITECTURE.md#the-flash-queue)).
- **Never drop the upload's verify.** Behind a marginal USB hub, an unverified upload exits 0 with blank
  flash ([ARCHITECTURE.md](ARCHITECTURE.md#flashing)).
- **Give the `arduino-cli` daemon a held-open stdin**; `DEVNULL` kills it silently
  ([ARCHITECTURE.md](ARCHITECTURE.md#flashing)).
- **⚠ The placement walk goes in box order**, or a file is silently mislabelled
  ([ARCHITECTURE.md](ARCHITECTURE.md#mapping-and-the-placement-walk)).
- **Never sequence the runner, RHX or the baseline from a handler**; ask `held`, `in_use` or `writing`
  ([ARCHITECTURE.md](ARCHITECTURE.md#session-lifecycle)).
- **A baud mismatch looks like a dead board.** Move the host's default baud, then flash, then check each
  box; `DEFAULT_BAUD` moves only with the bundled sketches ([ARCHITECTURE.md](ARCHITECTURE.md#reset)).

### Process, shell and wire

- **Change the wire only in `protocol/schema.py`**, then `npm run gen:protocol`; never hand-edit a
  mirror ([ARCHITECTURE.md](ARCHITECTURE.md#wire-protocol)). One exception type maps to one code; never
  recode one, because the frontend branches on codes ([ARCHITECTURE.md](ARCHITECTURE.md#dispatch)).
- **Declare every field** in the schema. Under wire validation, one undeclared field aborts the whole
  connect replay.
- **Decide UI state from sidecar facts, never by counting events.** Live events are not replayed on
  connect, and a broadcast that lands during a request must not be overwritten by its reply
  ([ARCHITECTURE.md](ARCHITECTURE.md#replay-on-connect)).
- **Keep both halves of orphan protection**: the sidecar exits on stdin EOF, and the shell kills it on
  exit. An orphan holds the serial ports ([ARCHITECTURE.md](ARCHITECTURE.md#startup-handshake)).
- **`--data-dir` is `<appData>/edu.hartlab.ephymeris`, never Electron's `userData`**, or settings and
  the database look missing ([ARCHITECTURE.md](ARCHITECTURE.md#the-electron-shell)).
- **The webview reaches the shell only through `src/lib/shell/`**
  ([ARCHITECTURE.md](ARCHITECTURE.md#the-shell-module)).
- **Never delete `latest.json` from the `updates` branch, or the `v2.0.0-beta` release.** They are how
  a copy still on Tauri crosses over to Electron ([ARCHITECTURE.md](ARCHITECTURE.md#updates)).
- **Don't move the GitHub repository.** Every installed copy has the update feed's URL baked in
  ([decision 0006](adr/DECISIONS.md#0006-the-shell-is-electron-not-tauri)).

## Lessons learned the hard way

Each is a rule, then the reason it exists. Most were found on the lab PCs or on a real board, where the
tests could not see them.

### Windows

- **Strip the `\\?\` verbatim prefix from any path handed to `arduino-cli`** (`discovery._plain()`).
  Tauri's `resource_dir()` returned one; `arduino-cli` silently resolves no libraries from such a path,
  and a release could not flash
  ([ARCHITECTURE.md](ARCHITECTURE.md#which-sidecar-runs)).
- **Use UTF-8 explicitly.** Set `PYTHONUTF8=1` for the sidecar, pass `encoding="utf-8"` at every open,
  and force UTF-8 stdout in CLIs. Lab PCs default to cp1252, and one character in a file turned a suite
  red on Windows only.
- **Two `os.replace` calls onto one name must take turns.** Windows refuses the second (WinError
  32/5/13), so `write_atomic` holds a per-target lock.
- **Don't fsync a directory on Windows**; it can't.
- **Kill test processes with `Popen.kill()`, not `os.kill(SIGKILL)`.** SIGKILL doesn't exist on
  Windows, so a test using it never ran there.
- **Stamp test file times in whole seconds.** NTFS keeps 100 ns, exFAT 10 ms and FAT32 1 s; finer stamps
  round to something else, so a copied file's time only follows its original's.
- **Build the frozen sidecar on Python 3.13, and keep settle waits well above 16 ms.** 3.12's asyncio
  clock on Windows ticks every 15.6 ms ([DEVELOPING.md](DEVELOPING.md#building-the-installer)).
- **Keep `dragDropEnabled: false`**, or Windows swallows drops ([ARCHITECTURE.md](ARCHITECTURE.md#routes)).
  Give every drag a click-to-carry equivalent.
- **Echo the command line actually sent**, with paths printed plainly, not with `repr`. A hand-composed
  echo once pointed at the wrong cause.

### Freezing the sidecar (PyInstaller)

- **Import scipy and numpy on the main thread before any thread starts**, or the frozen sidecar
  deadlocks at launch ([DATA.md](DATA.md#the-mat-mirror)).
- **Call `freeze_support()` first in the entry point**, or every spawned child starts a copy of the app
  ([ARCHITECTURE.md](ARCHITECTURE.md#the-live-scorer)).
- **Collect what analysis can't see.** Code inside an `--add-data` tree is opaque to it; protobuf went
  uncollected and every packaged build quietly ran the slow backend.
- **Ask the interpreter where the package is before freezing.** A stale non-editable install in the
  venv's site-packages once shadowed the source tree.
- **A readiness self-check must actually do the work.** An import check said "ready" while every
  compile failed.

### Firmware and boards

- **`int` is 16 bits on AVR.** `const int baudRate = 115200` wraps to −15872 and the box is mute at
  every baud; a 45000 ms duration became a delay of about 49.7 days. Use `long`/`unsigned long`, and
  read the warnings the build hides.
- **Never block `loop()` on serial.** `Serial.print` blocks when the 64-byte TX buffer fills, which held
  train pulses high and stalled sync pulses. Queue strobes.
- **Read inputs once per tick, not on every `loop()` pass.** Reading per pass lost about 26 of 27 edges.
  Test an IR sensor with an opaque probe; a finger doesn't fully block it.
- **A tick that strobes only an outcome mark still needs its sync pulse**
  ([RECORDING.md](RECORDING.md#firmware-pulse)), and pulses need a LOW gap between them or edges fuse.
- **Keep channels off pins 0 and 1** (the Mega's serial), 13, and 50–53.
- **FREE_RAM reads 20–80 B below the compiler's figure**: the linker pads `.data` to an even size.
- **A freshly reset Mega has almost no entropy**, so the host draws the seed
  ([TASKS.md](TASKS.md#seed)).

### Serial, ports and flashing

- **Bound a probe by total time, not per line.** At the wrong baud a chatty board yields garbage lines
  that reset a per-line timeout forever.
- **Flush the input buffer, then reset (DTR)**, so the banner you read is this run's.
- **Cancel a stalled upload and report avrdude's last error line.** A stall is about 12 avrdude timeouts
  (about 16 s); a healthy upload shows 0–3.
- **Upload one board at a time.** `arduino-cli`'s daemon does not serialize uploads, and six at once
  failed a marginal link ([decision 0004](adr/DECISIONS.md#0004-restores-share-one-compile-and-upload-in-turn)).
- **Reader threads never block on the handler lock**; they take it in slices.
- **When a session ends, wait only on finalizations not yet done.** Gathering finished tasks spun and
  froze the event loop.
- **Keep the live scorer out of the sidecar process.** On a thread it held the GIL the session threads
  need to fsync, and a strobe write's p99 reached about 200 s under load
  ([ARCHITECTURE.md](ARCHITECTURE.md#the-live-scorer)).

### State and data

- **A mapping draft stores only overrides.** Snapshotting defaults sent stale values as operator choices
  ([TASKS.md](TASKS.md#three-layer-merge)).
- **Open the database in one transaction.** It is 30× faster, and a failed migration can't leave the
  file half-upgraded ([DATA.md](DATA.md#transactions)).
- **A machine's vocabulary is seeded once**; codes shipped later arrive only through the
  `shipped_since` watermark ([TASKS.md](TASKS.md#strobe-vocabulary)).
- **A relocate moves stored paths with the files, and fsyncs copies before deleting originals**,
  recordings under the cohort folder included.

### Webview

- **Pass shader uniforms to the material as an object**: react-three-fiber copies a JSX `uniforms` prop,
  which froze every animation ([ARCHITECTURE.md](ARCHITECTURE.md#one-sky)).
- **Route exits must always complete.** framer-motion exits that never finish pile pages up; hence
  `BoundedExit` (1200 ms) in `AppShell`, no nested `AnimatePresence`, and unclickable exiting routes.
- **Capture the pointer only after a slop threshold in screen pixels**; capturing on pointerdown
  retargets the click.
- **Fade a container's contents, not the container.** Opacity below 1 makes it a backdrop root and
  breaks blur inside it.
- **Tailwind emits `.relative` after `.absolute`**, so don't put both on one element.
- **PDF export:** ligatures off, fonts inlined, footer pinned from the top
  ([DATA.md](DATA.md#exporting-a-log)).

### Tests

- **Pin golden literals.** Hash, Wilson and parser tests that compared code with itself could not fail.
- **Fake the boundary** (filesystem, serial opener, `arduino-cli`, the live sidecar over WebSocket), not
  private methods, and hold each fake to a shared contract with the real thing.
- **Wait on a condition with a deadline, never a sleep.** Fakes open late on purpose to flush out races.
- **Restore registries with `monkeypatch.setitem`.** A test once popped a real migration for the rest of
  the run.
- **Mind the birthday bound in random tests**: 5000 draws from 2³¹ collide about once in 170 runs.
- **Show each new test failing before the fix.** Several tests in this suite were found unable to fail.

## Dead ends

Tried, then abandoned. Don't retry one without reading why.

- **A free-form task graph compiler ("Task-Graph").** Vendored, folded in as a package, then removed with
  its spec designer and ~900 tests: invalid machines were expressible and analytics would have had to
  read any graph. The phase spine replaces it
  ([0003](adr/0003-phase-spine-task-model.md#considered-options)).
- **Bundled task specs** with a shadow/baseline store: removed a day later. Nothing ships as a spec;
  saved tasks extend the bundled library.
- **A user-chosen Arduino directory, then staging sketches from sibling repos.** Sketches ship with the
  app and are read from `firmware/` in place; the box utility is generated from the rig
  ([TASKS.md](TASKS.md#library-roots)).
- **Uploading six boards at once** ([decision 0002](adr/DECISIONS.md#0002-restores-upload-side-by-side)).
- **Several wiring files** (`rig.json`, then a channel set and pin map apart): one atomic wiring document,
  confirmed per machine with an order-aware digest. The channel-set hash follows declaration order,
  because order is meaning.
- **One capped `START` line carrying every parameter.** Replaced by `SET` lines each confirmed by CRC.
  Durations over 32767 ms were first refused, then widened to `unsigned long`.
- **Scoring on a sidecar thread** (see the live scorer above).
- **Flashing `GRGL_Sim`.** It is decode-only.
- **A Task selector that hid other tasks' sessions** in Analytics: the task is disclosed instead
  ([DATA.md](DATA.md#pooling-across-tasks)).
- **Several task-designer UIs** (a two-pane wizard, a journey rail, a walkthrough coach, a parameter
  dial). The current editor is the survivor; check the user guide before designing another.
- **Three flash queues, two in React state.** They raced; there is one, in the sidecar.

## Working on this project

- **Real hardware finds what tests cannot.** Say in every change what was *not* checked on a real box or
  on Windows, and keep a list of hardware checks owed ([DEVELOPING.md](DEVELOPING.md#not-yet-done)).
  After a firmware or protocol change, the lab reflashes all six boxes on both PCs.
- **Write the why down where it survives.** Reasoning that lived only in thin commit messages was lost.
  A decision goes in the [decision record](adr/DECISIONS.md); a lesson goes here; the docs say what the
  code does now.
- **Parallel branches collide over "the next number"** (`INTERP`, schema versions, generated protocol
  files). Take the number at merge time, and regenerate after rebasing.
- **When a doc is added**, update the CLAUDE.md map, the README's documentation table and the agents'
  domain notes; `test_doc_links.py` finds new docs on its own.
- **Never let a tool read the legacy fixtures** (`sidecar/tests/fixtures/legacy_*.json`): one grep put
  720 KB into an agent's context.
- **`main` is protected** by a ruleset: changes arrive by pull request, with linear history and signed
  commits, and never by force push. Only a repository admin bypasses it.

## After the history reset

The repository started again from one commit on 2026-11-15. What that changed:

- **Versions start again at `2.0.0-beta`, the one release.** Every earlier release and tag (the last was
  `1.1.3-alpha.225`) was deleted. Installed copies never downgrade, so the beta had to sort above what
  the lab PCs ran: a `1.0.0-beta` would have been ignored by every copy.
- **Ship main's commit counter restarted.** A main build is `package.json`'s version plus
  `git rev-list --count HEAD` ([DEVELOPING.md](DEVELOPING.md#continuous-integration-and-releases)), and
  `scripts/ship-version.mjs` refuses one at or below the feed's. A future history reset needs a version
  bump past the feed for the same reason.
- **The `updates` branch was kept**: installed copies read their feed from it.
- **Some fixtures can no longer be regenerated from history.** `sidecar/tests/fixtures/schemas/` was
  copied from shipped versions in the old history, and `legacy_corpus.py` names an old commit (2b851fd)
  as the "before" side of its capture. Both stay valid as they are.
- **Code that exists only in the old history**: the Task-Graph compiler, the pre-unification GRGL and
  shaping sketches (also in the lab's separate Arduino repository), and the firmware's own history from
  before it moved into `firmware/`. A bundle of the old history was kept outside the repository.
- **Issues and pull requests on GitHub still hold design discussion** that commit messages cited.

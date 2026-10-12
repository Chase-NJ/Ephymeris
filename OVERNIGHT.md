# Review II overnight run: morning report

Everything from **Ephymeris Architecture Review II** is on `review-ii/integration`: all 20 bugs (B1–B20) and candidates 1–8. Each node went through an implementer, an independent verifier and CI before its squash merge. Nothing has touched `main`. The PR **"Review II fixes"** (`review-ii/integration` → `main`) is yours to open and merge (see below).

**Suites on `review-ii/integration` at `1c78df1`:**
- sidecar pytest: 1629 passed, 3 skipped;
- vitest: 338 passed, with the protocol mirrors current;
- firmware host tests: both pass;
- CI: all 6 checks green on every node PR, including the AVR `Firmware compile`.

At the start, the baseline was 1426 sidecar tests and 261 vitest.

Detail lives in [`FIX_LEDGER.md`](FIX_LEDGER.md): one row per bug and per candidate, with its regression test and commit. Campaign issue: #30.

## Do first

1. **Open, then merge, "Review II fixes".** The run couldn't open this PR itself: the Part 1 guardrail blocks every PR to `main`, by design. From a terminal, with this file as the body:

   ```bash
   gh pr create --draft --base main --head review-ii/integration --title "Review II fixes" --body-file OVERNIGHT.md
   ```

   `main` needs 1 approving review and has no bypass, and GitHub won't let you approve your own PR. So:
   1. Open Settings → Rules → **Protect main**.
   2. Add *Repository admin* as a bypass actor.
   3. Merge the PR.
   4. Remove the bypass.
2. **Answer the decisions below.** Each is a two-way door, and the run took the recommended option.
3. **Run the bench checklist** at the end. The tests can't reach hardware.

## Decisions waiting for you

| # | Where | What the run did | Alternative |
|---|---|---|---|
| 1 | A1 (#60) | Kept `ANIMAL_MOVE_REFUSED` for a busy rig during a move, because the move dialog branches on it to show the plan's refusals. Everything else that means "the rig is in use" now answers `RIG_IN_USE`. | Switch the move to `RIG_IN_USE` too, with a frontend change to the dialog. |
| 2 | A2 (#62) | Adopted-run ids are unique per **cohort + run identity**, not "per path" as the ticket said. Per path wouldn't fix B15, because overlapping folders see the same path. Existing ids are kept, so nothing is migrated or orphaned. | A v16 migration that re-keys the ids. |
| 3 | C5 (#65) | `derive.CODEC_VERSION` is gone. The cache version is `SCORE_VERSION` plus a computed fingerprint. | — |
| 4 | Your `CLAUDE.md` | Not edited, because it's your local file. **Reword one rule and add one.** The "Bump `CODEC_VERSION`…" rule is stale; suggested wording is in PR #65's body. Suggested new line, from DB: "Reach the database only through `db.write()`/`db.read()`; pass `tx=` to share a unit (DATA.md#transactions)." | — |
| 5 | D1 (#57) | Strict argument checking runs before every command, and there's a new code, `ARCHIVE_BUSY`. An independent audit found no frontend branch on any changed code. | Revert strictness per command. |

**Decisions you made during the run:**
- U2: the sidecar states each mapping confirmation (`ActiveSessions.confirmations`).
- U1: a Record row resets when its animal changes.
- Probe maps are remembered **per animal**; port and range are remembered per box.

## Merged

| Node | PR | Closes |
|---|---|---|
| A0 | #46 | baseline, tickets |
| F1 | #48 | B3 |
| P1 | #49 | B1 B2 B17, cand. 1 |
| S1 | #47 | B18 B19 |
| U2 | #50 | B13, cand. 8 |
| P2 | #51 | B6, cand. 2, first review item 8 |
| U1 | #54, #58 | B5 (frontend), cand. 7 |
| P3 | #52 | B20 B16 |
| D1 | #57 | B10 B12, cand. 3 |
| U1b | #59 | B5 (sidecar), cand. 7 |
| A1 | #60 | B4 B7 B11, cand. 4 |
| A2 | #62 | B15 |
| DB part 1 | #64 | B14 (session path), #55 freeze |
| C5 | #65 | B8 B9, cand. 5 |
| DB part 2 | #77 | B14, cand. 6, #55, #63 |

**Parked:** none. Two Stop-and-asks fired: U2, decided by you during the run, and D1, where an independent frontend audit confirmed nothing the frontend relies on changed. Every other node's Stop-and-ask was checked by its verifier and didn't fire.

**Not reproduced:** none. Every reviewer-confidence bug (B13–B19) reproduced before it was fixed.

## What operators will notice after upgrading

- **Probe maps start blank once.** The old per-box memory can't say which animal a map belonged to. Pick each animal's map once; after that it follows the animal.
- **The analytics cache recomputes once.** Until each cohort's Analytics is opened once, the session list and the session log show recovered runs without an end time.
- **A START line of exactly 640 characters is now refused.** The firmware only ever kept 639. No shipped profile is anywhere near that length.
- **Rescan and Recover are refused while a box is running or finishing** ("once every box has finished").
- **Re-confirming a group's mapping after the Record step** means doing the Record step again before Start: "Go through the Record step again".
- **"Sync now" can report the database copy as not done** while a write is open. The next pass copies it.

## Skipped or adapted skills

- `design-an-interface`, `resolving-merge-conflicts` and `qa` are no longer in mattpocock/skills:
  - design nodes used `codebase-design` (DESIGN-IT-TWICE);
  - conflicts were resolved by hand (there was one, a test constructor);
  - leftovers are filed with `triage`'s conventions.
- `grill-me` ran unattended: its questions and adopted answers are in the A0 ticket (#31).

## Follow-up issues

- #55, the backup freeze found during the run, is **closed**: no transaction is ever open while the database lock is free.
- #56: a poll's RHX re-adoption can race End's stop; a few ms, misleading status only.
- #63, a copied-then-moved run double counting, is **closed** by DB part 2.
- Filed by node Z (`qa`, labelled `needs-triage`):
  - #66 rig definition saved without fsync
  - #67 a `copying` resume with the source unreachable leaves copies
  - #68 a resume with the target unreachable ends `done`
  - #69 the START meter's "over by"
  - #70 a duplicate history point on reconnect
  - #71 stray `.part` files after a power cut
  - #72 rescan and tidy bodies to move into `CohortArchive`
  - #73 "Sync now" wording for a deferred copy
  - #74 four port tests still patch `serial.Serial`
  - #75 a moved run's ruling across a missing-file rescan
  - #76 probe-map parse retry after a disconnect

## Bench checklist

Run on a lab machine (Windows). Each line names the change it confirms.

**Sessions and ports**
1. **B1:** Start a box that's in ERROR after "never reported READY". It's refused, nothing is recorded, and End / Switch Group work.
2. **B2:** Start All with box 2 unstartable. Box 1 runs, the session reads running, and End finalizes box 1.
3. **B17:** Pull a board just after its end strobe, while its run finalizes. The tile shows ERROR, not IDLE.
4. **Board drop:** Pull a board mid-run. It finalizes "board disconnected" and needs Acknowledge.
5. **B6:** Start a Debug flash with a console open, then close the console from a stale view. The upload completes and the console comes back.
6. **B6:** Put a box in ERROR and close its console from a stale view. It stays ERROR with no restore. Acknowledge it, and the restore runs.
7. **Candidate 2:** With a console open on an idle box, trigger a baseline restore. The console stays and the box reads busy.
8. **Held COM port:** On Windows, hold box N's COM port in another program, then start box N. The port goes to ERROR with the open failure.

**Firmware**
9. **B3:** Flash. Send a 639-character START ending `SEED=2147483646`; the board echoes `SEED 2147483646`. The app refuses a 640-character line (TSK107 in the editor, `TASK_PROFILE_INVALID` at mapping).

**RHX recording**
10. **B20:** Drop RHX's link mid-group, then End. You get the grace period, End now stays offered, and the run is recorded. Reconnect, and RHX leaves Record by itself; the next Record step is accepted.
11. **B20:** Press Stop in RHX mid-group, then End. The run is recorded, with no grace wait.
12. **B16:** Drop the link, then start another box. The refusal names the lost link.
13. **Owed stop:** Drop the link, restart a recording **by hand** in RHX, then reconnect. That recording is left running, with a message.
14. **Abandon:** On a recording session, Start All refused at box 1, then End Session (which abandons). RHX stops and the run is recorded.
15. **Confirm on real RHX:** Does `Filename.ActiveFileTimestamp` stay the same through a recording, including across a `NewSaveFilePeriodMinutes` rollover? Is it set before samples arrive? The owed stop depends on both answers.
16. **B5:** On a recording session with boxes 1 and 3, do the Record step, go Back, move box 3's animal to box 5, then Continue. RHX's Notes name box 5's animal, with no `=?`.
17. **Stale setup:** After moving an animal in Boxes, go to Mission Control through the SessionDock without the Record step. Start All is refused with "Go through the Record step again", and RHX stays out of Record.

**Record step**
18. **Probe maps:** Record a group with Rat-07 on box 5 and probe map P7. In a later group, put Rat-07 on box 3 and a new animal on box 5. Box 3 offers P7 with box 3's own port and range; box 5 is blank.
19. **Probe maps:** Pick maps for two animals, go Back, swap them, and return. Each map is on its animal's new box, including when you swap while a map is still parsing.
20. **Placement walk:** Place, Previous, Back to boxes, Skip, All in, Flash all, Walk again, and leave mid-walk and resume. Mission Control opens when the last flash lands.

**Debug and Mission Control**
21. **B13:** Send START right after opening a console. The button waits for the profile, and the START line carries the rig's task defaults.
22. **B13:** A refused Debug START keeps the last run's live tile; an accepted one clears it.
23. **B13:** Second group: run one box alone, Back to Boxes, re-confirm the same group. That box's old run is cleared.
24. **B12:** Reload the webview during a hand-started Debug run, on a profile-less sketch and on GRGL. End is still offered.

**Archive and data**
25. **B4:** Kill the app mid-finalize. Only a `.part` is left; Recover rebuilds the run. Also truncate a `.json` by hand, then Recover.
26. **B7:** Rescan during a live session: refused. End while clicking Rescan or Recover: refused until each run is recorded, and Analytics shows each run once.
27. **B11:** Recover while a data-folder move copies to another drive: "try again when it finishes".
28. **Backup:** Recovered files reach the backup mirror without a manual Sync.
29. **B18:** Relocate a cohort onto another drive, kill the app mid-delete, unplug the old drive and restart. The journal stays committed, and a session can still be set up. Plug it back in and a session can be set up without a restart. Restart, and the originals are deleted.
30. **B14/#55:** With a backup directory set, edit a cohort, then within 5 s open Analytics on unscored runs while a session runs. Analytics completes, the runs record, and the backup updates. An overnight run shows its task name in Analytics.
31. **B15 (optional, on a copy of a lab database):** Attach two cohorts to overlapping folders and rescan each twice. Both keep their recovered runs, and the `run_flags` count is unchanged.
32. **DB part 2:** Tidy a cohort with two split days.
33. **#63:** Move an animal whose run was copied into both cohorts. Analytics shows it once in the destination, with its ruling kept.
34. **DB part 2:** Relocate a cohort onto another drive and confirm sessions, runs and rulings are intact.

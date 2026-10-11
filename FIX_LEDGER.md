# Review II fix ledger

One row per bug and per candidate from **Ephymeris Architecture Review II** (11 Oct 2026). Campaign: #30. The brief is `.claude/review-ii-run.md`. The orchestrator updates this file as nodes merge.

Status: `open` (not started) · `in progress` · `fixed` · `not reproduced` · `blocked` · `PARKED`.

## Bugs

| Bug | Status | Node | Ticket | Regression test | Commit | What changed |
|---|---|---|---|---|---|---|
| B1 | open | P1 | #32 | | | A failed Start leaves a phantom run |
| B2 | open | P1 | #32 | | | A partial Start All leaves boxes running under a configuring session |
| B3 | open | F1 | #35 | | | START line cap off by one |
| B4 | open | A1 | #41 | | | A torn .json blocks Recover for good |
| B5 | open | U1 + U1b | #38 #40 | | | Record step reuses its saved form after the mapping changes |
| B6 | open | P2 | #33 | | | Console close accepted mid-flash and from ERROR |
| B7 | open | A1 | #41 | | | Rescan during a session can count a run twice |
| B8 | open | C5 | #43 | | | Cache version doesn't cover every input |
| B9 | open | C5 | #43 | | | analytics.series scores on the event loop |
| B10 | open | D1 | #39 | | | Busy archive / box-start OSError reach the UI as INTERNAL |
| B11 | open | A1 | #41 | | | sessions.recover writes without the archive lock |
| B12 | open | D1 | #39 | | | Hand-started Debug run not replayed on connect |
| B13 | open (reviewer finding: reproduce first) | U2 | #37 | | | Debug START clears live data before it can be refused; drops task defaults |
| B14 | open (reviewer finding: reproduce first) | DB | #44 | | | Another writer's rollback discards a pending task-profile row |
| B15 | open (reviewer finding: reproduce first) | A2 | #42 | | | Adopted-run ids hash only the file stem |
| B16 | open (reviewer finding: reproduce first) | P3 | #34 | | | Per-box Start after RHX drop gets the wrong message |
| B17 | open (reviewer finding: reproduce first) | P1 | #32 | | | Board drop during finalize_box ends in IDLE, not ERROR |
| B18 | open (reviewer finding: reproduce first) | S1 | #36 | | | Transfer resume with source unreachable marks the journal done |
| B19 | open (reviewer finding: reproduce first) | S1 | #36 | | | Strobe vocabulary replaced without fsync |
| B20 | open | P3 | #34 | | | Session ending while RHX unreachable never stops or records its recording |

## Candidates

| Candidate | Node | Ticket | PR | Status |
|---|---|---|---|---|
| 1 · A box start that cannot half-happen | P1 | #32 | | open |
| 2 · Port verbs that name the states they leave | P2 | #33 | | open |
| 3 · One dispatch seam | D1 | #39 | | open |
| 4 · Every archive write goes through the archive | A1 | #41 | | open |
| 5 · One version for the analytics cache | C5 | #43 | | open |
| 6 · A database unit of work | DB | #44 | | open |
| 7 · Pure builders for the two setup commands | U1 + U1b | #38 #40 | | open |
| 8 · SessionStore notices a new run itself | U2 | #37 | | open |

## Nodes

| Node | Ticket | Status | PR | Notes |
|---|---|---|---|---|
| A0 | #31 | done | (this PR) | Baseline green; all 20 bugs still present at a407126; 15 tickets filed |
| P1 | #32 | in progress | | |
| P2 | #33 | open | | |
| P3 | #34 | open | | |
| F1 | #35 | in progress | | |
| S1 | #36 | in progress | | |
| U2 | #37 | in progress | | |
| U1 | #38 | open | | |
| D1 | #39 | open | | |
| U1b | #40 | open | | |
| A1 | #41 | open | | |
| A2 | #42 | open | | |
| C5 | #43 | open | | |
| DB | #44 | open | | |
| Z | #45 | open | | |

## Flags

- SKIPPED: `design-an-interface` is not in mattpocock/skills any more. Design nodes use `codebase-design` (its `DESIGN-IT-TWICE.md`) for the same compare-two-designs step.
- SKIPPED: `resolving-merge-conflicts` is not in mattpocock/skills any more. Conflicts are resolved by hand, keeping both intents.
- SKIPPED: `qa` is not in mattpocock/skills any more. Node Z files leftovers with `triage`'s conventions instead.
- SKIPPED: `grill-me` ran unattended: the questions and adopted answers are written into the A0 ticket.
- SETUP-GAP: none found. Hook constraint: a stale node branch is brought up to date by merging `review-ii/integration` into it, because rebasing would need a force push, which the hook blocks.

## A0 baseline

- `review-ii/integration` at `a407126` = `main` (`8cfaca0`) plus the Part 1 setup files (`.claude/`, `docs/agents/`, `.gitignore`) and one comment line in `sidecar/tests/test_doc_links.py`. No app code differs.
- CI on that tree, all 6 green: https://github.com/Chase-NJ/Ephymeris/actions/runs/38135871063 (Protocol/typecheck/vitest, Sidecar ubuntu + windows, Firmware host tests, Firmware compile, Tauri shell).
- Local (macOS): sidecar pytest 1426 passed, 3 skipped; vitest 261 passed in 31 files; firmware: the three bundled sketches compile for `arduino:avr:mega` with `--warnings all`.
- Every bug B1–B20 is still present at `a407126` (B7 partly: the next rescan prunes the duplicate, but `archive.view` itself doesn't de-duplicate).

## A0 anchors

Current locations at `a407126`, found by symbol. Line numbers are hints; re-locate by symbol before editing.

### Sessions, ports, rhx (paths under sidecar/ephymeris_sidecar/)


- B1 present. sessions/runner.py `start_box` :213-253: `_active[box] = run` :238 and deadline armed :243-246 before `_ports.start_session` :248-253. ports/manager.py `start_session` :300-316 → handler.py `start_session` :232-264 (assert_transition :253; ERROR→IN_SESSION illegal, states.py:64). `stop_box` runner.py:387-390 → manager `stop_session` :318-320 → handler `send_session_line` :266-276 raises PortBusy :273-274. `end_all` runner.py:467-468 loops stop_box with no try. Also: deadline later fires `_on_deadline`→stop_box raising in a loop callback; `_lifecycle_errors` (app.py:2048-2070) doesn't map bare PortBusy.
- B2 present. sessions/lifecycle.py `start_all` :326-338: loop :331-334, `_open_group_run` :335 and status running :336 only after. `_start_box` :585-589 wraps BoxRefused. `resume` :410-453 (first group refuses at :425-428 "configuring"). `abandon` :455-478 → `runner.clear()` :468 → runner.py:164-167 RuntimeError (unmapped). Because of B1, box k is left in `_active`, so abandon fails even when k=1; abandon → `intan.release()` :474 leaves a started RHX recording.
- B6 present (release_for part mitigated by `_decide`). ports/states.py FLASHING→{IDLE,PASSTHROUGH,ERROR} :57-59, ERROR→{IDLE} :64. handler.py `close_passthrough` :201-206 (table only), `finish_to_idle` :208-212 (no source check), `end_session` :278-283 (IDLE from any state), `release_for` :214-228, `acknowledge_error` :165-169. manager.py :211-212, :244-246, :344. app.py `_passthrough_close` :617; restore trigger app.py:524-525 (`IDLE` → `utility.ensure`). utility.py `_close_if_ours` :488-495, `_decide` :319-324 (IDLE check). flashing.py `_execute` :299-327 (`prepare` :302, `flash` :320). src/lib/hardware/useHandshakeTest.ts:68 unmount close for every in-flight box (also :130, :169).
- B16 present. intan/service.py `configured_for` :736-744 (`state in ("configured","recording")` :742); `_lost` :497-515 sets "error". lifecycle.py `start_box` :340-347 → `_begin_recording_if_any` :598-613 raises :608-612. Applies while link is down; `_after_connect` :418-421 restores "recording" if `_recording` exists.
- B17 present. runner.py `finalize_box` :407-440: pop :417, await writer :423, clean `end_session` :430-434; `board_dropped` :442-445 no-op once popped; handler `end_session` moves ERROR→IDLE.
- B20 present. intan/service.py `is_recording` :340-342; `_lost` :497-515; `_poll_once` :489-495; `_after_connect` :416-425; `release` :724-734; `configure` :518-534 raises "RHX is already recording" :533-534. lifecycle.py `_end_all_boxes` :615-637, no-recording branch :624-628 (no grace, no stop_recording, release drops `_recording`).
- app.py `_handle_state_change` :491; IN_SESSION→ERROR sniff :508-518 → `runner.board_dropped`; IDLE→`utility.ensure` :524-525.
- FakePorts: tests/test_session_runner.py:34 (never raises); imported tests/test_backup.py:38, tests/test_session_lifecycle.py:845. test_session_lifecycle.py also has FakeRunner :39, FakeIntan :101, FakeUtility :142, FakeFlashes :159.
- Fake serial classes (monkeypatching serial.Serial): test_port_handler.py:27 (patch :90-98, :277-279); test_in_session.py:21 ScriptedSerial (:78), SlowOpen :276, SlowFailingOpen :284; test_utility.py:65 (:137-138); test_flash_reset.py:50 (:93-94).
- Private `_presence` writes in tests: NONE (review's "five writes" is stale). Presence via fake tool `list_boards` + `manager.poll_once()`.
- No injectable `open_serial`: PortManager.__init__ manager.py:104-111, PortHandler.__init__ handler.py:77-82; `serial.Serial` direct at handler.py:177, :297, manager.py:408. No public `note_boards`; presence via `poll_once`→`_update_presence` manager.py:349-389.

### Data side (paths under sidecar/ephymeris_sidecar/ unless noted)


- B3 present. firmware BehaviorBox.h `readLineInto` :299, cap check :314 `if (len < cap - 1)`, `START_LINE_MAX 640` :782; GRGL.ino:113 buffer. Host tasks/start_command.py `START_LINE_MAX` :30, `_SEED_TOKEN_BUDGET` :36, check :108 (`> START_LINE_MAX` accepts 640), `with_trial_seed` :123. Tests: tests/test_task_profiles.py:654 (`<=`), tests/test_taskdef.py:155 (`<=`), equality test test_task_profiles.py:666 `test_the_start_line_cap_matches_the_firmware`; host_test/test_behaviorbox.cpp:12,305,333.
- B4 present. sessions/writer.py `finalize` :122, write_text :150/:156; sessions/recovery.py `recover_file` :179, :225/:233; analytics/reader.py `walk_orphaned_tsvs` :306, is_file :329. Safe-write pattern: cohorts/transfer.py `copy` :66, `part_of` :62, fsync :93.
- B7 partly. app.py `_analytics_rescan` :1607 (no writing check; recover checks at :1660); analytics/service.py `rescan` :373, `known` :413-415, walk :417, store_adopted :486; lifecycle `animal_ended` :482 → record_animal_run :508-509 (no archive lock); analytics/archive.py `view` :99, `ArchiveView.runs` :71 (no de-dup); `_prune` removes dup only next rescan.
- B8 present. derive.py `CODEC_VERSION = 8` :55; infer.py `INFERRED_WINDOW` :63; service.py `CacheKey` :917-923, `_scoring_profile` :960/:978, `recorded_config` :972. Pin test tests/test_analytics_derive.py:1025 (asserts ==8 at :1069).
- B9 present. service.py `MAX_SERIES_RUNS` :42, `series` :259, inline scoring :294-307; `_resolve_profile_uncached` :1096 writes via remember_profile :1155 (no persist param). 9 `service._sketch_lookup` assignments in tests/test_analytics_adoption.py.
- B11 present. app.py `_sessions_recover` :1652, to_thread recover :1669, no `_archive.exclusive()`.
- B14 present. analytics/repository.py `remember_profile` :78 (no commit); rollbacks cohorts/repository.py:133,:226, sessions/repository.py:121,:510, cohorts/relocate.py:248, cohorts/move_apply.py:124; cohorts/db.py:728 connection. 78 `with .lock:` sites, 41 commit(), 6 rollback(). Backup debounce: backup/manager.py `DB_DEBOUNCE_S=5.0` :56, `mark_db_dirty` :177, `_db_due` :295; trigger cohorts/db.py:666-669 `_TrackedConnection.commit`→on_commit, wired app.py:296.
- B15 present. service.py `_orphan_run_id` :1514/:1526; reader.py `run_identity` :135 (stem.casefold()); repository.py `store_adopted` :210 INSERT OR REPLACE :216-218; db.py:305 schema.
- B18 present. cohorts/relocate.py `resume` :269, :294-297, `_delete_sources` :483, `_files` :452 ([] if not dir); move_apply.py `resume` :483, `_clean_up` :409, :416-421; transfer.py `delete_originals` :130.
- B19 present. strobes/store.py `_write` :152, write_text :156, os.replace :157.
- Archive lock: analytics/archive.py `CohortArchive.exclusive` :190 (asyncio.Lock), taken by summary/rescan/tidy/relocate/move; not by recover nor animal_ended's run commit.

### Dispatch + frontend (app.py = sidecar/ephymeris_sidecar/app.py)


- B5 present. src/routes/SessionRecording.tsx draft key :91-92 (`record:${sessionId}:${groupId}`, unchanged on re-confirm), rows from draft :101, seeding :133-155 (`:137 if (current.length > 0) return current;`), applyAndContinue :289-328 (boxes from rows :294, INTAN_CONFIGURE :302). Sidecar app.py `_intan_configure` :1908-1947, animals from `runner.box_configs()` :1932-1933, `animals.get(b['box'], '?')` :1935; intan/service.py `configure` :518 never checks mapping.
- B10 present. ArchiveBusy→INTERNAL in app.py `_cohorts_set_data_folder` :905-906, `_cohorts_move_animals` :936-937, `_analytics_rescan` :1616-1617, `_sessions_tidy` :1637-1638. OSError on box start: `_session_errors` :2013-2045 has no OSError branch; `_lifecycle_errors` :2048-2070 re-raises (:2067) → server.py:238-240 INTERNAL; `_mapped_errors` :2199-2231 maps OSError→PORT_OPEN_FAILED (:2229-2230). Path `_port_start_session` :1825 → lifecycle.start_box → `_start_box` lifecycle.py:585-589 wraps in BoxRefused.
- B12 present. app.py `_replay_state` :451-487 (registered :268 on_client_ready) sends PORT_STATE, BOARDS_PRESENCE, SKETCHES_UPDATED, TASKS_UPDATED, COHORTS_UPDATED, PREFIXES_UPDATED, FLASH_QUEUE, UTILITY_UPDATED, BACKUP_STATUS, INTAN_STATUS; no PORT_TELEMETRY. debug_run.py `DebugRuns` :51-103, `offer` :98 `... if changed and not run.metrics.empty else None`. Frontend store.ts `debugRunning` :72, set only from port.telemetry :149-157.
- B13 present. src/components/debug/NodeDetail.tsx `sendStart` :276-292, `resetBox` :280 before PORT_SEND_START :285-286; AllBoxesPanel.tsx :358-363 (`resetBox` :360 before :362). MissionControl.tsx:316-318 resets after success. Defaults dropped: NodeDetail profile null :152, async load :184-200; AllBoxesPanel :138-150; src/lib/sessions/types.ts:145 `if (!profile) return {};`; START buttons don't wait (NodeDetail :696, AllBoxes :357).
- Error mappers: server.py `CommandError` :51, catch-all `_on_message` :201/:236-240 (→INTERNAL); app.py `_session_errors` :2013-2045, `_lifecycle_errors` :2048-2070, `_intan_errors` :2073-2097, `_cohort_errors` :2127-2156, `_logbook_errors` :2159-2177, `_mapped_errors` :2199-2231; rig/definition.py `strobe_error` :88-98. `_require_*` guards raise INTERNAL at app.py :444, 686, 764, 1501, 1506, 1674, 1839, 1888.
- SessionStore resets: `resetRun` store.ts:273 ← SessionMapping.tsx:516 (after confirmMapping); `resetBox` store.ts:289 ← NodeDetail :280, AllBoxesPanel :360, MissionControl :318, store.ts:306; `resetFinishedBoxes` store.ts:305 ← MissionControl :509 (after startAll). `attach` store.ts:95-199: session.lifecycle :122-127 (replaces `active`), port.telemetry :149-157; NO port.state subscription (comment :89).
- Cand 8 open risk: confirm_mapping lifecycle.py:214-287 always ends with `announce()` :287 → SESSION_LIFECYCLE with `build_active_payload` :92-129 (`running = {session, groupId, boxes: runner.snapshot()}`); snapshot runner.py:181-200 fields box, animalId, animalName, sketchName, sketchPath, running, startedAt, ended; no confirmation id/nonce. Identical payload only when nothing ran since the previous confirm; differs if boxes ended (ended flips), group ran (groupRuns/status), or after end_group (boxes [] → populated).
- Cand 3: protocol.py `validate_command_args` :611, no callers; server.py calls only `validate_command_result` :230. Registration app.py `register()` :175-266; replay :268. rig/definition.py imports CommandError :27, raises at :217, :240, :249. Vocabulary editor app.py :1196-1432. `self.discovery` assigned :99, :280, :1995 (`_rescan` :1994-2005); read :339, 347, 476, 598, 603, 651, 722, 1113, 1529-1538. No test calls `_on_message` directly; tests/live_sidecar.py:149-170 drives a real server over WebSocket (used by test_relocate, test_debug_flash, test_taskdef, test_strobes, test_session_lifecycle). Frontend: TASK_INVALID / RIG_INVALID only constants in src/lib/ws/protocol.ts :186/:197; no branches.
- Cand 7: src/lib/sessions/flow.ts (+test), flashCards.ts (+test). SessionRecording.tsx (657 lines): draft :89-108, seeding :131-155, port auto-assign :157-180, probe reparse :182-189, readiness :217-287, applyAndContinue :289-328. SessionMapping.tsx (1289): draft key :116-118, seeding :156-189, persist :191-193, profiles :260-287, readiness :296-333, placementOrder :346-352, walk effects :384-475 (resume :461-473), walkAgain/advance/placeAll/retreat :539-581, startPlacement :488-537 (confirmMapping :500-512, resetRun :516), auto-navigate :597-607.

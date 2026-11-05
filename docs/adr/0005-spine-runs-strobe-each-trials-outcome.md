---
status: accepted
---

# A spine run strobes each trial's outcome class

[ADR 0003](0003-phase-spine-task-model.md#the-strobe-stream) left outcome codes out of a spine run's stream: the board strobes what it observed and what it did, and replay supplies the meaning. That keeps the stream honest, but a spine `.tsv` is unreadable without replay. A script cannot count a session's correct trials, a Debug Mode run (which has no live replay) shows no verdict, and a recording has no event at the moment a trial was decided. GRGL's stream has all three, through codes such as `RESP_OMIT` and `END_CORRECT_ITI`. We decided that **every trial a spine run marks strobes its outcome class**, as one of eight fixed, lab-wide codes, and that **replay predicts them**. This adds a verdict to the stream without anyone having to trust it.

## The decision

- **Eight codes, one per outcome class:** `OUTCOME_CORRECT`, `OUTCOME_WRONG_RESPONSE`, `OUTCOME_HOLD_BROKEN`, `OUTCOME_OMISSION`, `OUTCOME_WITHHELD`, `OUTCOME_FALSE_ALARM`, `OUTCOME_ABORT_BEFORE_STIMULUS` and `OUTCOME_ABORT_DURING_SAMPLING`, the classes of `lowering.OUTCOME_CLASSES`.
  - They are structural codes, like `TRIAL_START`: the same for every task.
  - Their numbers live only in the strobe vocabulary, appended to the shipped default.
- **When:** at the tick the trial enters its marked state, the one state per trial with a non-zero `outcome` ([TASKS.md](../TASKS.md#lowering)).
  - For a Response window, that is the response's branch: the chance state for an entry with a line, after any hold is complete.
  - For an early exit, it is the exit's end.
  - A trial that never marks (cut off by End Session, a crash, or a disconnect) strobes none. Its absence is the trial table's `complete: false`.
- **Where in the tick:** last, after the outputs driven HIGH and before only `END_SESSION`, the end's tick included.
  - While each strobe has its own sync pulse, every strobe after the first in a tick lags about 0.7 ms ([RECORDING.md](../RECORDING.md#the-sync-line)).
  - The outputs carry the physical event an analysis aligns to, such as the reward valve opening, and the verdict has no physical edge. So the verdict takes the lag.
- **From what the board already reports.** The core lists the states each tick entered (`InterpActions.entered`). The runner looks up each one's `outcome` in its table and strobes the code. The core's rules do not change; only its version number does.
  - Replay already predicts `entered` tick by tick, and the [differential test](../TASKS.md#compiling-and-the-host-tests) already holds it equal between the C core and the Python port.
  - So the board and replay derive the outcome strobe from one value that the test already checks.
- **Versioned as `INTERP` 8.** A board flashed before this change sends no outcome strobes. Replay predicts them only for a run whose header says `INTERP` 8 or later. Runs at 2 to 7 replay as they do now.
- **Checked, never read.** Analysis still scores a spine run by replay, as [ADR 0003](0003-phase-spine-task-model.md#replay-and-analytics) decided. The outcome strobes join the outputs as part of the checksum. A run whose outcome strobe differs from replay's, at any tick, is **diverged**, the same as a mispredicted output.

## Considered options

- **Keep the stream free of verdicts** (ADR 0003 as written). Replay needs nothing more. But every reader of a raw file then needs replay, Debug Mode shows no verdicts, and a recording has nothing to align a decision to.
- **Reuse GRGL's codes** (`END_CORRECT_ITI`, `END_INCORRECT_ITI`, `RESP_OMIT`, `WATER_POKE_ERROR_L`, …). They mix the side into the verdict and cover GRGL's cases rather than the eight classes. They are also retired at the cutover ([ADR 0003](0003-phase-spine-task-model.md#migration)), never to be reissued.
- **One code carrying the class as a value.** The wire carries a code and a timestamp, nothing else (`^\d{1,3}\t\d+$`, [DATA.md](../DATA.md#crash-recovery)). A value would change that line format for every reader.
- **A strobe at each trial's end** (its ITI entry). Every trial reaches an ITI, but the moment the trial is decided is the mark, and an ITI's start is already visible from its outputs.
- **A code for every state entry.** Rejected in [ADR 0003](0003-phase-spine-task-model.md#considered-options) for spending vocabulary per task or making a code's meaning depend on the task. Neither objection applies to outcome codes, because the class set is fixed lab-wide, which is why this ADR draws the line there.
- **Announcing the stream rule separately** (a `STREAM=` line beside `INTERP=`). It would keep `INTERP` for the core's semantics only. But replay already keys every reproduction rule on `INTERP`, and two numbers would have to be kept in step on every board and every header.

## Consequences

- **The stream grows by one strobe per marked trial**: a correct odor 2AFC trial goes from 13 strobes to 14.
- **The vocabulary gains eight codes.** A machine seeded before they existed must add them at the numbers the shipped default gives them. `SPN104`, which flags a vocabulary missing `TRIAL_START`, flags a missing outcome code the same way ([TASKS.md](../TASKS.md#spine-diagnostics)).
- **The stream order changes in `BoxSpine.h` and `analytics/stream/spine.py` together**, or every `INTERP` 8 run reads as diverged. The host tests gain a check that each marked trial strobes its class once, at its tick, last in that tick.
- **A raw spine file is countable without replay**, but its counts are not the scorer's. P(correct) still excludes aborts, and a block's criterion still reads its class sets. Analysis keeps reading the trial table.
- **Legacy runs are unaffected.** `analytics/stream/legacy/` decodes GRGL's own codes, and the legacy adapter still produces the same trial table for both.
- **Every spine task's `profile_hash` moves when it is next saved.** The hash covers `INTERP` and the snapshot ([TASKS.md](../TASKS.md#a-spine-tasks-hash-covers-behaviour-only)), so a task's `INTERP` 7 and 8 runs sit in two comparability groups, as at every `INTERP` before. No animal had run a spine task when this was accepted, so no history splits.
- **The score canary moves once.** Its spine runs are `INTERP` 8 runs and now carry outcome codes, so every machine re-reads its archive on the first summary after the upgrade ([DATA.md](../DATA.md#caching)). No `INTERP` 7 run scores differently.
- **The codes cost the board no RAM.** `BoxSpine.h` keeps them in flash (`PROGMEM`), because a task's RAM budget does not count the runner's tables ([TASKS.md](../TASKS.md#spine-diagnostics)).

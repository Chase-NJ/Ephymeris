---
status: proposed
---

# A task is a phase spine, lowered to a state table and replayed deterministically

One rig and one task editor should express the core paradigms of systems neuroscience without a special case for each. Today's model cannot: the trial runner is one hand-written 2AFC loop (`runTrial()`), the rig has seven odor-shaped channel kinds with two response slots, and analytics and the diagram read meaning from strobe-name patterns (`ODOR_<n>_ON`, `_L`/`_R`, `^FLUID`) in 34 places. We decided:

- A task is an ordered **spine of phases** from a fixed palette.
- A session is a list of **blocks** drawing **trial types**.
- Each trial type binds the spine's **slots** to channels and maps each response to an **outcome class**.
- The generator lowers the spine into a state table in `TaskTrials.h`, and one non-blocking interpreter in `BehaviorBox.h` walks it.
- The board strobes only what it observed and what it did.
- A Python port of the interpreter replays any session exactly from its table, parameters, seed and inputs.
- Analysis reads the replay's **trial table**, never strobe names.

The lab has recorded behavior but no neural data, so new sessions need not reproduce GRGL's strobe stream. The recorded behavior archive (917 sessions at the last corpus count) must stay decodable, and the vocabulary stays append-only.

## Scope

**Target tasks**, which define done: odor 2AFC, go/no-go, and odor DNMS. They were chosen to pull in different directions:

- go/no-go removes states from the spine;
- DNMS adds stimuli, and breaks today's "a trial ends at the next onset" boundary.

**First graded paradigm:** Pavlovian trace.

| Paradigm | Verdict |
|---|---|
| 2AFC, go/no-go, N-alternative choice | Full |
| Self-initiated vs cued trials | Full |
| Detection / discrimination with discrete stimulus levels (psychometric curves) | Full |
| Adaptive staircases (level chosen from performance) | **Out**, open question 2 |
| Delayed match / non-match to sample | Full; delays varying trial by trial need open question 1 |
| Reversal learning, across or within a session | Full |
| Probabilistic reward, two-armed bandit | Full |
| Pavlovian delay and trace conditioning | Full; needs a lick sensor |
| Operant FR, VR, progressive ratio, FI, VI | Full |
| Free-operant session on one schedule | Full |
| Lick-based head-fixed tasks | Full |
| Optogenetic pulse trains | Full: whole-millisecond widths, up to 100 Hz |
| Concurrent schedules (concurrent VI–VI) | **Out**: needs phases running in parallel |
| Graph-shaped trials (two-step task) | **Out**: needs the free node canvas |
| Analog input, closed-loop control | **Out**: a digital edge covers the paradigms above |
| Sub-millisecond pulses | **Out**: needs a hardware timer outside the tick |
| Video, position tracking, multiple subjects | **Out**: not the box's job |

## The model

### Rig

- **The channel set is lab-wide.** Both lab machines must emit identical codes for the same task, and tasks must move between them without being rebuilt.
  - It is one document, the same on every machine, stamped with its own content hash.
  - The [strobe vocabulary](../TASKS.md#strobe-vocabulary) moves with it and becomes lab-wide too. It stays the only place a code number is defined.
- **What a channel declares:**
  - `name`;
  - `type`: `digital_in`, `digital_out` (level or `train` mode), `pwm_out` or `tone_out`;
  - `role`: port, stimulus, reward, cue, routing or sync;
  - for inputs, `active_level` and `debounce_ms`;
  - for a reward line, `serves`: the port it pays at;
  - the code names of its edges: `enter`/`exit`, `on`/`off` or `train_on`/`train_off`.
- **The pin map is local**: channel name → pin, per machine.
- **The generator refuses hardware the board cannot run**:
  - a PWM channel on a pin no timer drives;
  - a PWM channel on Timer2's pins (9 and 10) beside a tone channel, since `tone()` takes Timer2;
  - a second tone channel.

  Two PWM channels may share a timer: each keeps its own duty at the timer's frequency.
- **A train's width must be shorter than its period**, at save and on the board, or the line would stay on.
- **A PWM, tone or train channel never sits where the trial runner drives a plain line**, since it would be held on there.
- **Retired from the schema:** `kind`, `port_slots`, `onset_strobe`, `well`, and every lookup of a pin by channel name.
- **Codes are allocated when the channel set is edited.** Each is a fresh code named `<CHANNEL>_<EDGE>`, shown in the save preview. Renaming a channel never renames its codes.
- **One machine edits the channel set at a time**, and the other imports it. A conflicting import is refused whole, as a vocabulary import is today.

### Task definition

- **Fields:** `spine[]`, `slots[]`, `rows[]`, `blocks[]` and `params`. `params` holds only divergences from the catalogue. The definition also keeps `id`, `name`, `category` and `notes`.
- **A row (trial type)** has:
  - a stable `id` and a required `name`;
  - a **slot binding** for every slot the spine uses;
  - a **contingency map**: each watched response, and the timeout, goes to an outcome class, a reward line and a reward probability;
  - row values: weight, reward ms, probability, `level`, PWM duty, tone frequency, pulse-train frequency/width/duration.
- **A block** has:
  - its rows and their weights;
  - a selection: uniform, weighted, a shuffle bag, or anti-bias across N responses computed in integers;
  - phase-duration overrides;
  - an end rule: N trials, N drawn from [a, b], or k correct of the last n;
  - the next block, or a loop back;
  - an optional correction rule: repeat after an error, up to k times.

  Blocks replace the stage ramp, the three compiled selection modes and the per-side correction budgets.
- **Seed spines** (2AFC, go/no-go, DNMS, trace, FR/PR) start a new task. A seed carries phases and no names, so it does not bring back the presets the editor refuses ([TASKS.md](../TASKS.md#what-a-definition-holds)).

### Phase palette

| Phase | Moves on when | Exits |
|---|---|---|
| Wait | an edge on a slot's channel | timeout → abort or omission |
| Hold | an input stays active for *t* | broken → hold broken |
| Present | after *t*, or on an edge | optional abort if the hold is lost |
| Delay | after *t* | optional abort on an edge |
| Response window | a watched response, resolved by the row's contingency map; optionally the response must then be held for *t* | timeout → the map's timeout entry |
| Counter | N edges on a channel, optionally within a time limit. N is fixed (FR), drawn (VR) or read from a compiled sequence (PR) | time limit → omission |
| Outcome | the reward line opens for the row's ms with the row's probability, then the class's timeout runs | none |
| ITI | after *t* | none |

**Outcome classes:** correct, wrong response, hold broken, omission, withheld, false alarm, abort before the stimulus, abort during sampling. The class set is the scorer's vocabulary. Adding a class bumps `CODEC_VERSION`.

### Interpreter and firmware

- **A pure core:** `step(state, event, now) → actions`, in fixed-width integer types. A thin hardware layer wraps it on the board.
- **Tick rules:**
  - a 1 ms tick on `millis()`, with every input read and debounced first;
  - an input edge beats a timer in the same tick only when the state exits on that edge: a watched edge the state has no exit for (a lick being counted) moves nothing and does not hold the timer off;
  - two or more edges the state exits on, in one tick, are broken by a draw from the session RNG; a single one draws nothing;
  - a strobe carries its tick time, not its emission time.
- **Determinism rules:**
  - nothing in the loop calls `delay()`;
  - every random draw is integer.
- **New outputs:** PWM, tone, and pulse trains driven from the tick.
- **Parameters:**
  1. the host sends capped `SET k=v …` lines;
  2. the board replies `PARAMS <n> <crc32>` over its parsed block, in canonical order;
  3. the host refuses a mismatch;
  4. otherwise it sends `START SEED=<n>`.

  The CRC catches truncation, a key the firmware does not parse and a clamped value. The line cap survives as a cap on each `SET` line.
- **`INTERP=<n>` is announced before `READY`** and recorded with the run.
- **Pool selection uses a shuffle bag per block**, not a pre-generated sequence.
- **`BOX_Utility` is generated from the channel set**, so it still knows no box.

### The strobe stream

- **What it records:**
  - every edge on an input a phase is watching (watched only);
  - every edge on an output the board drives, routing lines included;
  - the structural codes `SESSION_START`, `SESSION_END`, `BLOCK_START` and `TRIAL_START`.
- **What it leaves out:** no outcome codes and no state codes.
- **A pulse train strobes only its start and end.** Replay reconstructs every pulse.
- **The outputs are the checksum.** Replay must predict every one at its tick. A run where it cannot is **diverged**: flagged, never silently scored.

### Replay and analytics

- **`analytics/stream/replay.py`** is a pure Python port of the interpreter. It keeps every `INTERP` version that has shipped and refuses an unknown one.
- **A differential test keeps the two interpreters equal.** It runs the C core (built by `host_test`) and the Python port over generated spines and randomized input logs, and fails on the first output where they differ.
- **Replay produces the trial table**, one row per trial:
  - index, block, row id and name, level;
  - the entry time of each phase;
  - response, outcome class, rewarded, reward line and ms;
  - latencies;
  - correction;
  - per-phase counts of each watched input.
- **Every metric is a function of the trial table:** `P(outcome | row)`, psychometric curves, d′, rewarded and response accuracy, the engagement ladder, learning curves, phase-window rates and the PR breakpoint. Each carries Wilson intervals, as [ANALYTICS.md](../../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#uncertainty) requires.
- **Live scoring runs the same replay**, fed edge by edge, so Mission Control and Analytics cannot disagree. The diagram and its live token draw the spine.
- **`analytics/stream/legacy/`** is the current scorer, frozen. It decodes runs whose snapshot predates the spine, and it outputs the same trial table, so one analysis spans the cutover.

### Hashes and data

- **`profile_hash` covers what the board runs and how replay scores it:** the spine, slot bindings, contingency maps, blocks, param declarations and `INTERP`, with rows keyed by stable id.
  - It leaves out every string meant for a person: names, labels, help, groups, notes. A test pins that list, and anything not on it is hashed.
  - Renaming a condition no longer splits its history. [The comparability rule](../TASKS.md#profile-and-params-hashes) keeps its meaning.
- **The `.tsv` header carries the snapshot**, `INTERP` and the channel-set hash before the first strobe ([DATA.md](../DATA.md#the-tsv-log)), so a crashed run stays replayable.
- **Finalization and recovery write the trial table into the `.json` and `.mat` as *derived*,** stamped with `INTERP` and the replay version.
  - The app never reads that copy; it always replays.
  - **Re-derive** rewrites it.
- **New SQLite columns:** `interp`, `channel_set_hash` and `diverged`.

### UI

- **The Rig page** adds a channel by type, role and pin. Its codes are shown, never typed, and Debug Mode can check it live straight away.
- **Task Export and Import** on the Task landing page. An import that disagrees with the local channel set is refused, naming the difference.
- **The task editor** draws the spine as the diagram, with the rows table and contingency maps, the block timeline and a parameter-RAM meter.
- **Simulate** runs replay against a simulated animal (always correct, random, biased, never responds) and shows the trial table, block switches and metrics before anything is flashed. It replaces `GRGL_Sim` for checking a task. A physical dry run stays a Debug Mode action.

## Worked examples

Channel names are the shipped rig's, plus `lick_spout`, `tone`, `lever` and `laser` where a paradigm needs them.

**2AFC (odor 1 → right well)**
- **Spine:** ITI → Wait(`odor_port`, light on) → Hold(pre) → Present(`sample` with vacuum, holding `odor_port`) → Wait(`odor_port` exit) → Response window(wells, hold *t*) → Outcome.
- **Row:** `sample = odor_line_1`. Map: `right_well → correct, fluid_2`; `left_well → wrong response`; `timeout → omission`.
- **Stream for a correct trial:** `TRIAL_START TRIAL_LIGHT_ON ODOR_LINE_1_ON ODOR_PORT_ENTER VACUUM_ON VACUUM_OFF ODOR_LINE_1_OFF ODOR_PORT_EXIT TRIAL_LIGHT_OFF RIGHT_WELL_ENTER FLUID_2_ON FLUID_2_OFF RIGHT_WELL_EXIT`. `VACUUM_ON` is when the odor reaches the animal.
- **Scored as:** `P(correct | row)`, rewarded vs response accuracy, and the engagement ladder.

**Go/no-go**
- **Spine:** the same, with one response port.
- **Rows:** the go row maps `port → correct`, `timeout → omission`. The no-go row maps `port → false alarm`, `timeout → withheld`.
- **Scored as:** hit rate, false-alarm rate and d′.

**N-AFC**
- **Spine:** the same, with k ports and k-entry maps.
- **Selection:** anti-bias across k responses.
- **Limit:** free pins.

**Graded detection**
- **Rows:** one per level, each with `level` set. The stimulus is a dilution line, a PWM duty value or a tone frequency.
- **The level-0 catch row** maps `port → false alarm`.
- **Scored as:** `P(response | level)`.

**DNMS**
- **Spine:** Wait → Hold → Present(`sample`) → Delay(retention, abort on exit) → Present(`test`) → Response window → Outcome.
- **Rows:** AA, AB, BA, BB. The map rewards the non-match response.
- **Scored as:** `P(correct | match or non-match)`, read per row rather than inferred from onset boundaries.

**Reversal**
- **Blocks:** block A's rows; then, after 8 correct of the last 10, block B's rows with the maps reversed.
- **Scored as:** trials to criterion per block, and perseverative errors.

**Bandit**
- **Row:** one choice row. Map: `left → correct p=0.8`, `right → correct p=0.2`.
- **Blocks:** a block with the probabilities swapped. The two loop, each lasting N drawn from 40–60.
- **Scored as:** P(choose the better side), win-stay/lose-shift, and model fits from `rewarded`.

**Pavlovian trace**
- **Spine:** ITI → Delay(baseline, watching `lick_spout`) → Present(`cs` on `tone`, watching licks) → Delay(trace, watching licks) → Outcome, with no response gate.
- **Rows:** CS+ and CS−.
- **Scored as:** anticipatory lick rate in the CS and trace windows, against the baseline window.
- **Delay conditioning** drops the trace phase.

**FR / VR / PR**
- **Spine:** Counter(`lever`, N) → Outcome → loop.
- **A counter time limit** ends the session.
- **Scored as:** response rate, inter-response times and the breakpoint.

**Cued vs self-initiated**
- The spine starts with either Wait(initiation) or ITI → Present.

**Head-fixed licks**
- **Ports:** two `digital_in` lick ports, active HIGH, debounced.
- **The response window** takes the first lick, and per-phase lick counts go in the trial table.

**Opto**
- **The output:** `laser` in `train` mode. The row sets 20 Hz, 5 ms, 1 s.
- **Stream:** `LASER_TRAIN_ON`, `LASER_TRAIN_OFF`.
- **Ephys:** record the laser TTL directly into the recording controller.

## Migration

1. **Channel set and vocabulary go lab-wide; pin maps stay local.** Allocate the fresh codes and build channel-set and task export and import. GRGL keeps running on its old codes.
2. **Interpreter core in C and the Python port**, with the differential test in `host_test` and CI.
3. **Generator lowering and the protocol.** The generator lowers the spine to the state table. `SET`, the `PARAMS` echo and `INTERP` go through `protocol/schema.py`.
4. **The analysis layer:** replay, the trial table, metrics over the table, and the legacy adapter. The adapter is pinned on the corpus to reproduce today's counted, hits, outcome tallies and engagement exactly, per sketch.
5. **The editor:** spine, rows, block timeline, simulate, task export and import.
6. **The target tasks, then the cutover.** Each target task passes simulation, a dry run with a catch vessel, and a first animal session compared against that animal's previous GRGL sessions, on both machines. Then:
   - GRGL becomes decode-only: still bundled for the archive, no longer offered at mapping or in Debug Mode;
   - its codes are retired, never reissued and never removable;
   - the cutover date is recorded here.

The legacy adapter flags two gaps rather than filling them:
- **Legacy no-go runs:** their strobes cannot tell a withhold from a false alarm.
- **Legacy per-phase counts:** these columns are empty, not zero.

## Considered options

- **A fixed runner per paradigm family** (2AFC, Pavlovian, operant). Each is easier to trust on its own, but each family is new C++, which is the special case per paradigm this decision exists to remove.
- **Versioned templates expanded from knobs** (Task-Graph's D1). Invalid machines cannot be expressed. But every new paradigm family is a new template in the generator, and a template change re-expands every saved task and moves its hash.
- **A free node canvas.** Fully general, but bad machines can be expressed and analytics would have to make sense of any graph. The spine branches only at exits, which is where every paradigm in scope branches.
- **Uploading the table at run time** (Task-Graph's transport). Every task is already compiled and flashed, so an upload path, its port state and its bench boundary would cost a great deal and buy nothing.
- **Recording every edge, always.** Richer, but every existing edge code would need a fresh code, and the sync line would carry ITI noise. A per-channel "report always" option stays possible later, with fresh codes.
- **A code for every state entry.** It makes the stream self-describing, but either spends vocabulary codes per task or makes a code's meaning depend on the task's table.
- **The C interpreter built for the host.** Identical by construction, but it puts a native build in the Windows installer and moves the science out of `stream/`, which [ANALYTICS.md](../../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#start-here) says is the only place to read it.
- **A code range reserved per machine.** It keeps two vocabularies mergeable, but the same task would then strobe different numbers on the two machines, which is ruled out.
- **Deriving a code from a channel's role and position.** Identical everywhere, but a rename or reorder moves the code. This is the derivation `generate._onset_macro` records as wrong.
- **Keeping the legacy and new scorers apart.** It would give one animal two shapes of history across the cutover.

## Consequences

- **Rules in `CLAUDE.md` and the docs change:**
  - the vocabulary is lab-wide, not per machine;
  - the `START` length cap becomes "every `SET` line is capped, and the board confirms the parameter block by CRC before `START`";
  - "nothing on disk is a trial" becomes "the app never reads the derived trial table".
- **New glossary terms** once this is accepted: spine, phase, slot, contingency map, block, outcome class, channel set, pin map, trial table, replay, diverged run.
- **The sync line lags in a burst.** Its rising edge can trail the strobe's tick time by about 0.7 ms per strobe. The lag is bounded and recorded, and must be documented in [RECORDING.md](../RECORDING.md#the-sync-line) before the first implant session relies on it.
- **Fixes worth making now, whatever this decision becomes:**
  - a generated no-go metric's `alternate` is one port, so a false alarm at the other port is excluded instead of counted;
  - TSK108 misses a table emptied by go rows with no usable response port;
  - TASKS.md documents a `countKey` that does not exist, and an abort ordering the firmware does not have;
  - the emitter kind's doc says a speaker substitutes for an odor valve with no change, which is not true;
  - the vocabulary's `pair_order` notes are wrong.
- **Removed by the model:** the by-name pin and well lookups in `generate.py`, the `^ODOR_\d+_ON$` gates in the frontend, and the two-port limit.

## Open questions

1. **Can a row override phase durations**, so a DMS delay varies trial by trial?
2. **Adaptive staircases:** out for good, or a later selection policy?
3. **Which distributions a drawn duration supports.** Uniform at least; an exponential ITI needs an integer table.
4. **The cutover date.**
5. **Who owns edits to the lab channel set.** This is process, not code.
6. **A per-channel "report always" option**, with fresh codes.
7. **Sub-millisecond pulses** through a hardware timer.
8. **The RAM budget for the tables once blocks and rows exist.** Task-Graph measured 300–522 B per table with more than 5 KB free; that needs re-measuring.

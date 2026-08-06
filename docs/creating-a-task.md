# Creating a task

This is for someone **designing an experiment**. It assumes you know what you
want the animal to do and nothing about the compiler. If you want to know how
the compiler works, read [`TaskGraph.md`](TaskGraph.md) instead.

A task is one YAML file. You will almost never write one from scratch — you pick
a paradigm, answer a few questions, and the app generates a complete document
that already compiles. Everything after that is editing.

---

## Before you start

Three things are worth knowing up front, because they surprise people.

**You cannot draw the state machine.** There is no node editor, and a document
containing a `nodes:` key is rejected. You describe the task in four layers and
the graph is *derived*. This is deliberate: it is why a task cannot have a dead
end or an unreachable state.

**The generated task already works.** A skeleton is not a stub. It compiles, it
has real durations taken from the firmware's own defaults, and it would run. Your
job is to change the parts that should differ, not to fill in blanks.

**Nothing here has run an animal yet.** Compiled tasks are bench-verified only.
See [`TaskGraph.md` §8](TaskGraph.md#8-what-is-proven-and-what-is-not).

---

## Step 1 — Start from a paradigm

**Task → New task.** Seven paradigms; each one fixes a different set of knobs and
asks you about the rest.

| paradigm | it fixes | it asks you | you get |
|---|---|---|---|
| **Two-alternative forced choice** | 1 stimulus stage, 2 ports, rewarded | which two odor lines; trials | 26 states |
| **2AFC, unrewarded** | as above, no reward | which two odor lines | 24 states |
| **Shaping — one side, ramped** | 1 port, rewarded, ramped | which port, which line, trials | 26 states |
| **Go / no-go** | withhold arm, 1 port | which line, trials | 21 states |
| **Sequence with retention** | 2 stages + gap + delay | which two lines | 29 states |
| **Three-stimulus sequence** | 3 stages | — | 31 states |
| **Shaping — no stimulus** | 0 stimuli | — | 25 states |

> **Shaping-R and Shaping-L are the same paradigm.** They differ only in the
> answer to "which port". That is the whole point of the split: widening a shaping
> task to both wells later is a *policy* edit, not a reshape — so the animal's
> history stays comparable in Analytics instead of splitting at the boundary.

### The wizard, in order

The steps follow the order a task is actually thought about: what the animal
senses, what it must do to earn the stimulus, how it answers, what counts as
right — then the numbers, which change no shape at all.

1. **What is it called?** — the id names the file and the compiled table.
2. **What does this paradigm need to know?** — the paradigm's own questions.
3. **What does the animal sample?** — stimuli and how many stages.
4. **How does a trial begin?** — the commitment hold.
5. **How does it answer?** — ports or withhold; trial types.
6. **What does a correct trial get?** — reward delivery.
7. **Does it get harder over the session?** — the ramp ([layer 4](#layer-4--policy)).
8. **How long is everything?** — the timing vector.
9. **How does the session run?** — selection, trial count, seed.

Every step recompiles. If a step leaves the task unable to compile, you see the
error there rather than at the end.

### What you get

Here is the complete `two_afc` skeleton, unedited. Roughly 120 lines, and worth
reading once in full — everything the rest of this document discusses is visible
in it.

<!-- BEGIN GENERATED two_afc SKELETON -->
```yaml
spec_version: 1
spec_id: my_task
vocab_version: 2
meta:
  label: Two-alternative forced choice
  description: One stimulus, two ports, reward at the correct one. The discriminandum is which stimulus
    was presented, and because both ports stay live the animal can be wrong as well as slow -- which is
    what separates a discrimination measure from a detection one.
topology:
  template: four_epoch
  template_version: 2
  n_sampling_stages: 1
  retention_delay: false
  response_mode: n_alternative
  response_ports:
  - right_well
  - left_well
  commit_hold: true
timing:
- id: t_zero
  ms: 0
  note: Required by every spec. Zero-duration nodes carry the second strobe of a paired emission and the
    response branch guard. See D2, D3.
- id: t_arm
  ms: 1000
  wire_key: PRD
  note: primingDelay -- odor primed before the trial light, so stimulus onset is latency-free.
- id: t_engage_win
  ms: 4000
  wire_key: S0O
  note: odorPortTimeout.
- id: t_poll_interval
  ms: 5
  wire_key: POL
  note: pollingRate -- input sampling granularity for every watched channel.
- id: t_commit_hold
  ms: 500
  wire_key: S0P
  note: odorPokeHold at BehaviorBox.h:1176 -- the pre-odor commitment hold.
- id: t_sample_hold
  ms: 500
  wire_key: S0P
  note: odorPokeHold at BehaviorBox.h:1191 -- the sampling hold. Same wire key and value as t_commit_hold,
    deliberately a DISTINCT index (D8).
- id: t_resp_win
  ms: 2000
  wire_key: S0W
  note: fluidWellPoll -- the response window.
- id: t_resp_hold
  ms: 200
  wire_key: S0H
  note: fluidWellHold -- hold at the chosen well before reward.
- id: t_iti_correct
  ms: 4000
  wire_key: ITI
  note: standardITI.
- id: t_pen_break
  ms: 10000
  wire_key: NPH
  note: noPokeHoldTimeout -- serves the sampling/commitment hold breaks and the response-hold failure.
- id: t_pen_noengage
  ms: 6000
  wire_key: LZD
  note: lazyRatDelay -- base value; policy.penalty_escalation grows it.
- id: t_pen_error
  ms: 20000
  wire_key: ERR
  note: errorDelay -- serves both wrong-port and omission (BehaviorBox.h:1038).
- id: t_reward_right
  ms: 100
  note: Pulse width IS the delivered volume at right_well.
- id: t_reward_left
  ms: 100
  note: Pulse width IS the delivered volume at left_well.
contingency:
  stimuli:
  - id: odor1
    emitter: odor_line_1
    on_code: ODOR_1_ON
  - id: odor2
    emitter: odor_line_2
    on_code: ODOR_2_ON
  ports:
    right_well:
      channel: right_well
      enter_code: WATER_POKE_R
      error_code: WATER_POKE_ERROR_R
      break_code: WATER_UNPOKE_EARLY_R
      exit_code: WATER_UNPOKE_R
      reward_line: fluid_2
      reward_duration: t_reward_right
      reward_code: FLUID_R
      reward_stop_code: STOP_FLUID_G_R
    left_well:
      channel: left_well
      enter_code: WATER_POKE_L
      error_code: WATER_POKE_ERROR_L
      break_code: WATER_UNPOKE_EARLY_L
      exit_code: WATER_UNPOKE_L
      reward_line: fluid_0
      reward_duration: t_reward_left
      reward_code: FLUID_L
      reward_stop_code: STOP_FLUID_G_L
  trial_types:
  - id: tt_odor1_right_well
    stages:
    - odor1
    target: right_well
  - id: tt_odor2_left_well
    stages:
    - odor2
    target: left_well
  context_schedule: []
  outcome_map:
    correct:
      trigger: HELD
      reward: '@target'
      terminal: TRIAL_CORRECT
      delay: t_iti_correct
      strobe: '@target.exit_code'
      note: The exit code is the ITI node's entry strobe -- the only place firmware observes the end of
        a consummatory bout.
    hold_break:
      trigger: BROKEN
      reward: null
      terminal: TRIAL_INVALID
      delay: t_pen_break
      strobe: ODOR_UNPOKE_EARLY
      note: Sampling incomplete.
    hold_fail:
      trigger: BROKEN
      reward: null
      terminal: TRIAL_INCORRECT
      delay: t_pen_break
      strobe: '@ports[$ch].break_code'
      note: Correct port reached but released before the hold completed -- a consummatory failure, not
        a wrong choice.
    no_engage:
      trigger: TIMEOUT
      reward: null
      terminal: TRIAL_INVALID
      delay: t_pen_noengage
      strobe: LAZY_RAT
      note: 'No stimulus was presented, so the trial carries no evidence about discrimination: scored
        invalid and repeated, never counted as an error.'
    omission:
      trigger: TIMEOUT
      reward: null
      terminal: TRIAL_INCORRECT
      delay: t_pen_error
      strobe: RESP_OMIT
      note: The response window expired after complete sampling.
    wrong:
      trigger: ENTER
      reward: null
      terminal: TRIAL_INCORRECT
      delay: t_pen_error
      strobe: '@ports[$ch].error_code'
      note: Sampling completed and a choice was expressed, so this is a genuine discrimination error and
        advances the session.
policy:
  selection:
    mode: anti_bias
    bias_window: 20
    debias_strength: 0.5
    p_min: 0.02
    p_max: 0.98
    max_run: 10
  correction:
    budgets:
      right_well: 0
      left_well: 0
  penalty_escalation:
    applies_to: no_engage
    step_ms: 6000
    ceiling_ms: 30000
    arm_after_stage: 0
    clears_on: TRIAL_CORRECT
  stage_schedule: []
  n_trials: 1000
  seed: host
```
<!-- END GENERATED two_afc SKELETON -->

> This block is pinned by `test_creating_a_task_example_is_current`, which
> regenerates the skeleton and compares byte for byte. The document cannot come to
> describe a task the app would not produce.

---

## Layer 1 — Topology

**What shape the experiment has.** Five knobs, and each one changes the number of
states.

| knob | values | effect |
|---|---|---|
| `n_sampling_stages` | 0–3 | stimuli sampled in sequence before answering |
| `retention_delay` | bool | a blank delay between last stimulus and response |
| `response_mode` | `n_alternative` \| `withhold` | choose a port, or withhold from one |
| `response_ports` | list of channel names | which ports are live |
| `commit_hold` | bool | require a sustained poke before spending a stimulus |

Measured against the `two_afc` baseline of **26 states, 36 edges**:

| change | result |
|---|---|
| `commit_hold: false` | 25 states, 34 edges |
| `n_sampling_stages: 2` + gap | 29 states, 41 edges |
| `n_sampling_stages: 3` | 31 states, 45 edges |
| `response_mode: withhold` | 21 states, 29 edges |
| reward removed | 24 states, 34 edges |

`commit_hold` is the one worth thinking about. It separates an incidental
beam-break from a real initiation, **before any stimulus is spent** — without it,
a rat brushing the port consumes a trial.

### The two walls

Two limits are real and neither is arbitrary. Both are **computed from the
registries rather than written down**, which is what makes them movable: you move
them by changing what the rig declares, not by editing the compiler.

> [!IMPORTANT]
> **You get as many response ports as your rig declares response channels.** The
> shipped wiring declares two of `kind: response` — `right_well` and `left_well` —
> so *Add a response option* blocks once both are bound, and the message says so
> by counting the registry. **Declare a third in the Rig tab's wiring editor and the block
> turns itself on**, with no edit anywhere in the app. The real ceiling above that
> is seven: `TG_MAX_WATCH` is eight watched channels and one of them is the
> engagement port.
>
> **You get twelve stimulus onset codes**, `ODOR_1_ON` … `ODOR_12_ON`, matching the
> twelve odor lines the board physically has. This used to be six, which meant six
> of the twelve lines could be plumbed but never announced — and a stimulus whose
> onset cannot be announced is invisible in the data, which is worse than not
> having the line. A thirteenth stimulus is still a wall.

Neither number is typed into a rule. The port wall counts `kind: response` entries
in the composed channel map; the stimulus wall counts onset codes in the strobe
vocabulary. That is why the first one is now something an operator can move from
inside the app, and the second one still isn't — a strobe code is a number the
data files and the firmware both have to agree on, so it ships.

### Changing a knob makes new fields required

This is the mechanism to understand, because it is how the whole editor behaves.
Set `retention_delay: true` on the skeleton above and the compiler says:

```
[TG303] template requires timing id 't_retention', which this spec does not declare
```

The template's `capabilities()` decides *which rows exist* for a given topology;
the compiler decides which are *valid*. The form never hides a row the topology
stopped needing — it greys it with a Remove button — and a structural block asks
`capabilities()` about the topology it **proposes** before editing anything. So
what you see is always the compiler's answer, never the editor's guess.

---

## Layer 2 — Contingency

**What means what.** Four parts: `stimuli`, `ports`, `trial_types`, `outcome_map`.

### Stimuli and ports name channels, never pins

```yaml
stimuli:
  - id: odor1
    emitter: odor_line_1     # a channel NAME
    on_code: ODOR_1_ON       # a strobe NAME
```

**TG223** rejects a channel the registry does not declare. This is why swapping
the pinout does not touch a single spec: `odor_line_1` means the same thing on
any box, and `hardware/<box>.json` is the only file that knows which pin that is.

**TG224** rejects a reward line that does not serve its port. `fluid_2` serves the
right well and `fluid_0` the left; a spec pairing them the other way compiles
into a task that rewards the wrong side, which is exactly the kind of error that
produces plausible-looking wrong data rather than a crash.

### The binding syntax

Some strobes depend on the **trial**, not the graph. Three forms:

| form | means | resolved |
|---|---|---|
| `@target` | the port this trial's type designates correct | per trial |
| `@target.exit_code` | that port's field | per trial |
| `@ports[$ch].error_code` | the field of whichever port was *actually* poked | per event |
| `@stim[$stage].emitter` | the stimulus for the current sampling stage | per stage |

`@target` and `@ports[$ch]` are genuinely different. In the `wrong` outcome the
animal poked a port that was *not* the target, so only `$ch` can name it.

> [!CAUTION]
> **TG506 checks that a binding resolves for *every* port it could select.** If
> you add a port and forget its `error_code`, the compile fails — instead of the
> task running fine until the day an animal happens to poke that port and the
> event is recorded as nothing.
>
> This is the trap when converting go/no-go to n-alternative: the withhold task
> never declared `error_code`, `break_code` or `exit_code`, and the new shape makes
> all three *reachable* on every port.

### `outcome_map`

Each entry names a class the template knows how to build. **TG302** requires the
declared set to match `capabilities()` exactly, both directions.

```yaml
wrong:
  trigger: ENTER              # which trigger routes here
  reward: null
  terminal: TRIAL_INCORRECT   # how the trial is scored
  delay: t_pen_error
  strobe: '@ports[$ch].error_code'
```

`trigger` is the field that makes go/no-go work: the same outcome classes with
inverted triggers give you a task where *withholding* is correct. It is named
`trigger` and never `on`, because YAML turns a bare `on:` into the boolean `true`
([D12](taskgraph-decisions.md#d12)) — and Phase 0 lost this field to exactly that.

---

## Layer 3 — Timing

**How long everything takes.** An ordered vector, and the order is load-bearing.

```yaml
timing:
  - id: t_zero
    ms: 0
  - id: t_arm
    ms: 1000
    wire_key: PRD
    note: primingDelay -- odor primed before the trial light.
```

> [!CAUTION]
> **Durations compile to *indices* into this vector, not to values.** That is what
> makes a shaping ramp a table rewrite rather than a recompile — and it is why you
> **append, never insert**. Inserting a row shifts every index after it.
>
> The editor's operations handle this for you (`renameTimingId` rewrites every
> reference including stage-schedule keys). Hand-editing the YAML does not.

- **`t_zero` is required** in every spec (**TG203**). Zero-duration nodes carry the
  second strobe of a paired emission and the response branch guard.
- **`wire_key`** is the `START`-line token this duration maps to on the legacy
  path. Two ids may share one ([D8](taskgraph-decisions.md#d8)) —
  `t_commit_hold` and `t_sample_hold` both carry `S0P` but are deliberately
  distinct indices, so each can ramp independently. **TG232** warns when two ids
  sharing a key hold *different* values, since the legacy path can only supply one.
- **`note:` describes the value.** If you change the value, the note is now wrong.
  The editor's operations delete a note rather than rewrite it — an op cannot
  honestly restate a rationale it did not derive.
- **Durations are `uint16`** (**TG204**). Over 65535 ms, split across two `DELAY`
  nodes.

---

## Layer 4 — Policy

**How the session is run.** Nothing here changes the machine.

```yaml
policy:
  selection:
    mode: anti_bias      # live, not a pre-generated pool
    bias_window: 20
    debias_strength: 0.5
    p_min: 0.02
    p_max: 0.98
    max_run: 10
  correction:
    budgets: {right_well: 0, left_well: 0}
  penalty_escalation:
    applies_to: no_engage
    step_ms: 6000
    ceiling_ms: 30000
    clears_on: TRIAL_CORRECT
  stage_schedule: []
  n_trials: 1000
  seed: host
```

**Anti-bias selection** is live rather than a pre-generated sequence: an animal
developing a side bias is offered the other side more often, within `p_min`/`p_max`.

**`clears_on: TRIAL_CORRECT`** matters more than it looks. The abstention penalty
must be cleared by a *completed correct trial* — a bare poke, or a poke and bail,
must not defuse it. **TG241** warns if you set this to an engagement event.

### The ramp

`stage_schedule` rewrites durations at trial boundaries. This is what a shaping
task is:

```yaml
stage_schedule:
  - at_trial: 0
    set: {t_commit_hold: 10,  t_sample_hold: 10,  t_resp_win: 10000, t_resp_hold: 10}
  - at_trial: 15
    set: {t_commit_hold: 50,  t_sample_hold: 50,  t_resp_win: 8000,  t_resp_hold: 25}
  - at_trial: 40
    set: {t_commit_hold: 150, t_sample_hold: 150, t_resp_win: 5000,  t_resp_hold: 50}
```

Two rules the wizard enforces so you cannot get them wrong:

> [!CAUTION]
> **Every row must set every ramped id** (**TG507**). The board applies exactly
> one row — the latest whose trial count has been reached. An id a row omits keeps
> whatever value it currently has, which is *not* necessarily the previous row's.
> A partial row does not fail; it produces a task that is subtly not the ramp you
> designed.
>
> **Rows must ascend by `at_trial`** (**TG205**). The scan takes the latest
> matching row, so an out-of-order schedule applies the wrong one silently.

---

## Reading the listing

Open **Listing** in the Designer. It is the review artifact — the thing to read
when you want to know what you actually built.

```
  S14  WAIT_ENTRY  t_resp_win[6]        right_well,left_well     —
       response window
         ENTER(right_well) → S15
         ENTER(left_well) → S15
         TIMEOUT → S16

  S15  DELAY       t_zero[0]            —          @ports[$ch].enter_code(65284)
       response registered
         TIMEOUT [ch == @target] → S19
         TIMEOUT → S20
```

- `t_resp_win[6]` — the id **and** its vector index.
- The watch column lists channels; `—` means the node watches nothing.
- `(65284)` is the encoded runtime binding. Anything ≥ 65280 is a binding rather
  than a real code.
- `[ch == @target]` is a guard. Guards are first-match-wins and the last edge in
  each group is the unguarded default (**TG405**).
- `→ score:wrong` marks where an outcome class is applied.

`S15` is worth staring at: it emits the poke strobe and *then* branches on
correctness, because the poke is recorded when it happens, not after the test
([D3](taskgraph-decisions.md#d3)).

---

## When it doesn't compile

Diagnostics carry a rule code, a location, and a fix. Rule codes are banded by
which pass found the problem:

| band | pass | typical cause |
|---|---|---|
| **TG1xx** | LOAD | YAML syntax; a `nodes:` key; schema violation |
| **TG2xx** | BIND | a name that does not resolve — timing id, strobe, channel, port |
| **TG3xx** | TEMPLATE | topology and declarations disagree |
| **TG4xx** | GRAPH | structural — should not happen from the editor |
| **TG5xx** | PACK | too big; a binding that cannot resolve; a partial stage row |

The three you will actually meet:

- **TG303** *"template requires timing id X"* — you changed a knob and the new
  shape needs a duration. Add it.
- **TG302** *"outcome classes disagree"* — same cause, other layer. The topology
  now produces a class you have not declared, or no longer produces one you have.
- **TG506** *"unresolvable binding"* — a port is missing a code some outcome
  needs. Usually after adding a port.

`taskgraph rules` prints all 39 with their fixes. In the app, each diagnostic
links to its decision in [`taskgraph-decisions.md`](taskgraph-decisions.md) when
one applies.

---

## Putting it on a board

**Task → your task → Bench.**

1. Flash `Bench/TaskRunner_Dev` to a box.
2. **Probe** — the board answers with `CAP PROTO=2 WIRE=1` and its capacity
   limits. A board with no `CAP` line is running legacy firmware and is refused.
3. **Upload** — the table goes across in 64-byte chunks. A ~560-byte table is
   9 chunks and about 200 ms.
4. The board replies `TABLE OK <crc32>`, or `TABLE FAIL <reason>` and keeps the
   table it had.

Baud comes from transport detection (115200/9600, cached per board), **never**
from `settings.defaultBaud`. While the bench panel is mounted the utility
baseline is held — otherwise the app would helpfully reflash `BOX_Utility` over
your interpreter and the uploaded table would die silently.

> [!CAUTION]
> **A bench upload is not a session.** `UPLOADING` and `IN_SESSION` are illegal in
> both directions and no wire command connects a spec to an animal. The bench
> panel says "not for animal use" permanently, and that is enforced in the port
> state machine rather than in the UI.

---

## See also

- [`TaskGraph.md`](TaskGraph.md) — how the compiler works, and why
- [`taskgraph-decisions.md`](taskgraph-decisions.md) — the 21 decisions, each naming its rejected alternative
- [`specs.md`](specs.md) — the editor, the diff, where specs live on disk
- [`tasks.md`](tasks.md) — the older `task.json` sketch profiles, which are a different thing

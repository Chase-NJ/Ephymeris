/*
  BoxInterp.h
  ===========
  THE PHASE INTERPRETER'S PURE CORE
  (0003-phase-spine-task-model.md#interpreter-and-firmware).

  A task's spine of phases is lowered, by the generator, to a STATE TABLE. This
  header walks that table one millisecond tick at a time:

      InterpActions interp_begin(core, table, params, seed, now);  // the session's first tick
      InterpActions interp_step(core, edges, now);                 // every tick after it

  It reads no pin, clock or serial port, and includes no Arduino header: a tick's
  input edges and its time come in, and what the board must do at that tick
  comes out. A thin hardware layer reads and debounces the inputs, calls
  interp_step(), drives the outputs and strobes the actions. Every type is
  fixed-width, so the board and the host build compute the same thing.

  analytics/stream/replay.py is a Python port of this file, line for line. The
  differential test (extras/host_test/run_diff.sh) runs both over generated
  tables and input logs and fails on the first tick where their actions differ.
  CHANGE THEM TOGETHER, and bump INTERP_VERSION when the table format or any
  rule below changes what a table does: replay keeps every version that shipped.

  ONE NUMBERING SPACE. A board announces INTERP=<n> before READY and every run
  records it (docs/TASKS.md#confirming-the-parameters). 1 is BehaviorBox.h's
  trial runner (BOX_INTERP), which every recorded GRGL run names, so this
  interpreter starts at 2: a run's header alone says whether a table ran it.
  3 adds the pick state, 4 the counter and last-trial states, and 5 blocks and
  the response state. Each changes nothing else, so replay.py runs an older
  table by the same rules and refuses only what its version lacks.


  THE TICK RULES
  --------------
  Call interp_begin() at the session's first tick, then interp_step() once for
  EVERY millisecond after it, with consecutive `now` values. A tick with no
  edges still counts: it is when timers run out. AVR millis() skips a value
  roughly every 42 ms, so the caller steps each skipped value too, with no
  edges; skipping one moves a timer exit by a tick and the run diverges.

  Within one tick, in this order:
    1. INPUTS FIRST. The tick's edges are masked by the current state's `watch`;
       only watched edges are reported, and only they can move the state.
    2. AN EDGE BEATS A TIMER. If any watched edge matches one of the state's edge
       rows, one of them is taken and the timer is not looked at. A watched
       edge with no edge row (a lick being counted) moves nothing, so it does
       not hold a timer off. Nor does a counter state's counted rise below its
       N (below): only the N-th is an exit.
    3. TWO OR MORE MATCHING EDGES are broken by a draw from the session RNG:
       the k-th match in table order, k = interp_draw(rng, matches). A single
       match draws nothing.
    4. OTHERWISE THE TIMER: the state exits to `on_timeout` once
       now - entered_at >= its duration. A timer is only checked for the state
       current at the start of a tick, so a state lasts at least one tick, even
       with a zero duration.
    5. ENTERING a state records the tick as its entry time, sets a counter
       state's N, then draws its duration, in that order. A chance or pick state
       branches at once (below); its target is entered in the same tick.
       Entering a state that starts a trial, in a table with blocks, first runs
       the block rules (BLOCKS, below): a block's N is drawn there, then the
       pick's selection, before any counter N or duration.
  A tick that reports no edge and moves nothing changes nothing at all, the RNG
  included, so a replay may jump straight to the next edge or timer.

  Every draw is an integer: interp_draw(rng, n) is avr-libc random() % n in
  uint32_t, over a generator the core carries in its own state.


  THE STATE TABLE (INTERP_VERSION 5)
  ----------------------------------
  Generated data. A table is an array of InterpStateRow, indexed 0..254, an
  array of InterpEdgeRow the states point into, the table's one
  InterpCounter (or NULL) and its InterpBlocks (or NULL). State 0 is where a session starts. INTERP_NONE (255)
  means "none" in every uint8_t field.

  Channels are bits: input i is bit i of a uint32_t, and output j is bit j of
  another, so a table speaks of at most 32 inputs and 32 outputs. Which pin
  and which strobe code a bit stands for is the hardware layer's business,
  generated from the channel set; the core never sees either.

  Durations and probabilities are not in the table. They are PARAMETER SLOTS:
  indexes into the uint32_t params[] array the session was begun with, which
  the host sets by SET lines. So a table is the same for every parameter value,
  and lowering never needs to know them.

  InterpStateRow, one per state:
    outputs     Every output that is HIGH while the core rests in this state. On
                a transition the core diffs the old resting state's outputs
                against the new one's, and reports only what changed: an output
                held across several states (the trial light from Wait through
                Present) is listed in each and strobes once.
    watch       Inputs whose edges are reported, and may move the state, while
                here. An input not in `watch` is ignored entirely.
    timer_min,  Parameter slots of the duration, in ms. Equal slots (or equal
    timer_max   values) give a fixed duration; otherwise it is drawn uniformly
                from [params[timer_min], params[timer_max]] at entry, as
                lo + interp_draw(rng, hi - lo + 1) in uint32_t: a span of the
                whole 32-bit range wraps to a draw over 0, which is lo. NONE in
                timer_min: no timer, the state waits for an edge.
    on_timeout  The state entered when the timer runs out.
    chance      NONE, or the parameter slot of a probability in permille. A
                CHANCE STATE is a branch that takes no time: on entry it draws
                interp_draw(rng, 1000) and goes on at once to on_hit when the
                draw is below params[chance], otherwise to on_miss.
    on_hit,     A chance state's two targets.
    on_miss
    edge_first, The state's edge rows: edges[edge_first .. edge_first+edge_count).
    edge_count  A pick state's edge rows are its branches instead.
    flags       INTERP_STARTS_TRIAL: entering it reports TRIAL_START.
                INTERP_PICK: a PICK STATE, a branch that takes no time, like a
                chance state: on entry it draws k = interp_draw(rng, edge_count)
                and goes on at once to the k-th edge row's next. Every entry
                draws, a single branch included. The generator makes state 0 one
                when a task has several rows, so a trial's row is the branch it
                took. In a table with blocks, a pick state that starts a trial
                draws instead by the running block (BLOCKS, below).
                INTERP_COUNT: a COUNTER STATE. Its one edge row is a counted
                rise: on entry the core sets count = 0 and N from the table's
                counter; each matching rise adds one to count, and only the one
                that brings it to N is an exit (the others move nothing, like a
                watched edge with no edge row). The exit adds one to the core's
                `step`, the counter states completed this session.
                INTERP_LAST_TRIAL: entering it reports INTERP_ACT_LAST_TRIAL; the
                session layer ends the session at the next trial start.
                INTERP_RESPONSE: a RESPONSE STATE (the Response window). Leaving it
                by an edge row makes that row's input the trial's response, the
                first only, which anti-bias reads.
    outcome     The outcome class this state records, or 0. Replay reads it off
                the states a trial entered. The core reads it only in a table
                with blocks: a trial's class is that of the last marked state it
                entered, and it is correct when that is INTERP_CORRECT (1).

  InterpEdgeRow, one per exit on an input:
    input       The input's bit number; it must be in the state's `watch`.
    edge        INTERP_RISE (the input became active) or INTERP_FALL.
    next        The state entered.
  A pick state's branch is an edge row with input 0 and edge 0.

  InterpCounter, the table's one counter, which every counter state reads:
    count_min,  Parameter slots of N, as timer_min and timer_max: equal slots fix
    count_max   it (FR); otherwise it is drawn uniformly at entry (VR), as
                lo + interp_draw(rng, hi - lo + 1), held as a uint16_t. NONE in
                both: N comes from `ratios`.
    ratios,     A compiled sequence (PR): N is ratios[min(step, ratio_count - 1)],
    ratio_count so the k-th completion needs the k-th ratio and the last repeats.

  InterpBlocks, the table's blocks (docs/TASKS.md#blocks): `rows`, one
  InterpBlock each; `entries`, one InterpEntry per branch of a trial-starting
  pick, or NULL; `overrides`, InterpOverride each, or NULL.
  InterpBlock:
    first,      The block's rows: branches first .. first+count-1 of a pick that
    count       starts a trial.
    select      How the pick draws one, all in integers from the session RNG,
                every stage drawing once even with one candidate:
                  INTERP_UNIFORM   draw(count);
                  INTERP_WEIGHTED  r = draw(sum of weights), the first branch
                                   whose running sum passes r; uniformly when the
                                   weights sum to 0;
                  INTERP_BAG       a shuffle bag of each branch's weight in
                                   tokens, at most INTERP_HISTORY (a token past
                                   the 32nd is never drawn): r = draw(tokens
                                   left), the r-th token left; refilled once
                                   empty, and emptied when the block starts;
                  INTERP_ANTIBIAS  a side, then a branch on it by weight. The
                                   sides are the branches' entries' sides, in
                                   the order each first appears; each weighs
                                   1 + L - its count among the last L responses,
                                   L the responses held (at most INTERP_HISTORY),
                                   at most params[window].
                A weight is min(params[entry.weight], INTERP_WEIGHT_MAX), and 1
                with no entries or a NONE slot.
    n_min,      Parameter slots of the block's N, drawn at its start as a counter's
    n_max       N is and held as a uint16_t; NONE: no N.
    k, n        Parameter slots of a criterion: k correct of the last n trials
                (n read as at most INTERP_HISTORY); NONE: none.
    window      Anti-bias's window slot, NONE for every response held.
    correct     The correction limit's slot, NONE for no correction.
    next        The block entered when this one ends; NONE: the blocks are done.
  InterpEntry: side (an input bit, or NONE), weight (a slot, or NONE).
  InterpOverride: while `block` runs, a state's timer or chance, or the
  counter's N, that reads slot `slot` reads `with` instead (the first match).

  BLOCKS. In a table with blocks, entering a state that starts a trial:
    1. The first time, starts block 0. Otherwise closes the last trial: its
       correctness goes into `corrects` (the block's, the latest in bit 0) and
       its response, if any, into the ring of the last INTERP_HISTORY.
    2. The running block's end rule: it has started N trials, or k of its last
       n were correct. Then its `next` starts, or with none the core reports
       INTERP_ACT_DONE: the session layer ends the session at this tick.
       Starting a block resets its trial count, `corrects`, its bag and the run
       of repeats, draws its N, and reports INTERP_ACT_BLOCK_START.
    3. Otherwise the correction rule: when the block has one, the last trial
       was marked with a class other than INTERP_CORRECT, and fewer than
       params[correct] repeats have run in a row, this trial repeats it: the
       pick takes the last trial's branch with no draw, and the core reports
       INTERP_ACT_CORRECTION.
  Every trial counts toward N and the criterion, a correction included.

  A VALID TABLE, which the core assumes and replay.py's Table refuses to break:
    - every state index, edge row and parameter slot is in range;
    - an edge row's input is watched, and a state has at most one edge row per
      (input, edge);
    - a chance state has no outputs, watch, timer or edge rows, and neither of
      its targets is a chance or pick state;
    - a pick state has no outputs, watch, timer or chance, and at least one
      branch, and no branch is a chance or pick state;
    - a counter state is neither a chance nor a pick state, has exactly one edge
      row, a RISE, and its table has a counter, whose count_min and count_max
      are both slots, or both NONE with 1 to 254 ratios, each at least 1;
    - a last-trial state neither branches nor starts a trial, so the session
      always ends at a later tick than the one that entered it;
    - a table's blocks number 1 to 254, each draws one or more branches, its
      N's and its criterion's slots are both set or both NONE, and its next is
      a block or NONE; every pick that starts a trial has a branch for each
      block's slice, and so has `entries` when it is not NULL; an override
      names a block and two slots.
    So a tick enters at most two states.


  LOWERING THE PHASES
  -------------------
  How the generator writes each phase of the ADR's palette as states. An END is
  a copy of the ITI state that carries an outcome class: where every exit that
  ends a trial early goes (docs/TASKS.md#lowering says which class each marks).
  Past the Outcome the trial is already marked, so such an exit goes to the
  row's own ITI instead, or to an unmarked end that ends the session.

    Wait(c, edge, timeout)    watch c; edge (c, RISE or FALL) -> next; timer -> an end.
    Hold(c for t)             watch c; timer t -> next; edge (c, FALL) -> an end
                              (hold broken).
    Present(o for t)          outputs o; timer t -> next. An abort on an input's
                              release or entry adds edge (h, FALL) or (h, RISE) -> an end.
    Delay(t)                  timer t -> next; aborts as for Present.
    Counter(c, N, limit)      INTERP_COUNT; watch c; edge (c, RISE) -> next, taken
                              at the N-th; timer limit -> an end (omission), a
                              last-trial state when the limit ends the session.
    Outcome(line r, ms, p)    a chance state (p -> reward, else -> class timeout,
                              outcome = the class); reward: the phase's outputs
                              and r, timer ms -> class timeout; class timeout: the
                              phase's outputs, timer -> next. A phase's outputs are
                              HIGH in every state it rests in.
    ITI(t)                    timer t -> the trial's first state, which carries
                              INTERP_STARTS_TRIAL.

  The Response window, the contingency map, several rows and blocks are written
  as docs/TASKS.md#lowering describes; they need no state kind beyond these, the
  pick state and the response state.


  THE ACTIONS OF A TICK
  ---------------------
  InterpActions, which the hardware layer strobes in this order, each mask in
  ascending bit order:
    SESSION_START (flags), watched inputs that rose and fell (rose, fell),
    TRIAL_START (flags), outputs driven LOW (off), outputs driven HIGH (on).
  INTERP_ACT_BLOCK_START (flags) is strobed as BLOCK_START, just before
  TRIAL_START. INTERP_ACT_LAST_TRIAL is never strobed: it tells the session
  layer to end the session at the next trial start; INTERP_ACT_DONE, at this
  one. INTERP_ACT_CORRECTION is never strobed: replay reads it for the trial
  table. `block` is the block running after the tick, NONE in a table without
  blocks; replay predicts it, and the differential test compares it.
  entered[] lists the states entered this tick in order, NONE-padded. It is
  never strobed (the stream carries no state codes) but replay predicts it,
  and the differential test compares it.

  Tables live in RAM as plain const arrays; the generator holds what a task's
  table, parameters and channels cost to a budget (docs/TASKS.md#spine-diagnostics).
*/

#ifndef BOX_INTERP_H
#define BOX_INTERP_H

#include <stdbool.h>
#include <stdint.h>

#define INTERP_VERSION 5

#define INTERP_NONE 0xFF       // "no state / no slot / no timer" in a uint8_t field
#define INTERP_PERMILLE 1000UL // a chance state draws over [0, 1000)

#define INTERP_RISE 1          // InterpEdgeRow.edge
#define INTERP_FALL 2

#define INTERP_STARTS_TRIAL 0x01       // InterpStateRow.flags
#define INTERP_PICK 0x02
#define INTERP_COUNT 0x04
#define INTERP_LAST_TRIAL 0x08
#define INTERP_RESPONSE 0x10

#define INTERP_ACT_SESSION_START 0x01  // InterpActions.flags
#define INTERP_ACT_TRIAL_START 0x02
#define INTERP_ACT_LAST_TRIAL 0x04
#define INTERP_ACT_BLOCK_START 0x08
#define INTERP_ACT_DONE 0x10
#define INTERP_ACT_CORRECTION 0x20

#define INTERP_UNIFORM 0               // InterpBlock.select
#define INTERP_WEIGHTED 1
#define INTERP_BAG 2
#define INTERP_ANTIBIAS 3

#define INTERP_CORRECT 1               // the outcome class `correct`: OUTCOME_CLASSES[0]
#define INTERP_HISTORY 32              // responses anti-bias can read; trials a criterion can; tokens a bag holds
#define INTERP_WEIGHT_MAX 0xFFFFUL     // a weight is read as at most this

typedef struct {
  uint8_t input;
  uint8_t edge;
  uint8_t next;
} InterpEdgeRow;

typedef struct {
  uint32_t outputs;
  uint32_t watch;
  uint8_t timer_min;
  uint8_t timer_max;
  uint8_t on_timeout;
  uint8_t chance;
  uint8_t on_hit;
  uint8_t on_miss;
  uint8_t edge_first;
  uint8_t edge_count;
  uint8_t flags;
  uint8_t outcome;
} InterpStateRow;

typedef struct {
  uint8_t first;   // its rows: branches first .. first+count-1 of a trial-starting pick
  uint8_t count;
  uint8_t select;  // INTERP_UNIFORM, _WEIGHTED, _BAG or _ANTIBIAS
  uint8_t n_min;   // parameter slots of its N, as a counter's; NONE: no N
  uint8_t n_max;
  uint8_t k;       // parameter slots of its criterion, k correct of the last n; NONE: none
  uint8_t n;
  uint8_t window;  // parameter slot of anti-bias's window, in responses; NONE: all held
  uint8_t correct; // parameter slot of its correction limit; NONE: no correction
  uint8_t next;    // the block entered when it ends; NONE: the blocks are done
} InterpBlock;

typedef struct {
  uint8_t side;    // the input bit of the row's one correct response, or NONE
  uint8_t weight;  // parameter slot of its weight; NONE weighs 1
} InterpEntry;

typedef struct {
  uint8_t block;   // while this block runs,
  uint8_t slot;    // a state or the counter reading this slot
  uint8_t with;    // reads this one instead
} InterpOverride;

/*  A table sits in RAM, and the generator holds its size to a budget at save
    (lowering.py's STATE_ROW_BYTES, EDGE_ROW_BYTES, BLOCK_BYTES, ENTRY_BYTES and
    OVERRIDE_BYTES, docs/TASKS.md#spine-diagnostics). Change a row here and those
    change with it. */
#if defined(__AVR__) && defined(__cplusplus)
static_assert(sizeof(InterpStateRow) == 18, "lowering.py's STATE_ROW_BYTES is this row's size");
static_assert(sizeof(InterpEdgeRow) == 3, "lowering.py's EDGE_ROW_BYTES is this row's size");
static_assert(sizeof(InterpBlock) == 10, "lowering.py's BLOCK_BYTES is this row's size");
static_assert(sizeof(InterpEntry) == 2, "lowering.py's ENTRY_BYTES is this row's size");
static_assert(sizeof(InterpOverride) == 3, "lowering.py's OVERRIDE_BYTES is this row's size");
#endif

/*  The table's one counter: where a counter state's N comes from. */
typedef struct {
  const uint16_t *ratios; // when count_min is NONE: N is ratios[min(step, ratio_count - 1)]
  uint8_t ratio_count;
  uint8_t count_min;      // parameter slots of N: equal fixes it, unequal draws it
  uint8_t count_max;
} InterpCounter;

/*  The table's blocks. `entries` is NULL when no block selects by weight or by
    side, and `overrides` when there are none. */
typedef struct {
  const InterpBlock *rows;
  const InterpEntry *entries;
  const InterpOverride *overrides;
  uint8_t count;
  uint8_t entry_count;
  uint8_t override_count;
} InterpBlocks;

typedef struct {
  const InterpStateRow *states;
  const InterpEdgeRow *edges;
  const InterpCounter *counter; // NULL in a table with no counter state
  const InterpBlocks *blocks;   // NULL in a table with no blocks
} InterpTable;

/*  One tick's debounced input edges, by input bit. */
typedef struct {
  uint32_t rose;
  uint32_t fell;
} InterpEdges;

typedef struct {
  uint32_t rose;      // watched inputs that rose this tick
  uint32_t fell;      // watched inputs that fell
  uint32_t on;        // outputs driven HIGH
  uint32_t off;       // outputs driven LOW
  uint8_t entered[2]; // states entered, in order; INTERP_NONE pads
  uint8_t flags;      // INTERP_ACT_*
  uint8_t block;      // the block running after this tick; INTERP_NONE before the first
} InterpActions;

/*  The whole of a running session's state. The caller owns it; only
    interp_begin() and interp_step() write it. */
typedef struct {
  const InterpTable *table;
  const uint32_t *params;
  uint32_t rng;          // avr-libc random()'s state
  uint32_t entered_at;   // the tick the resting state was entered
  uint32_t duration;     // its timer, drawn at entry
  uint32_t outputs;      // the outputs now HIGH
  uint32_t corrects;     // the block's trials, the latest in bit 0: 1 for correct
  uint32_t bag;          // the bag's drawn tokens, one bit each
  uint16_t count;        // a counter state's rises counted since entry
  uint16_t target;       // and the N it exits at, set at entry
  uint16_t block_trials; // trials started in the block, saturating
  uint16_t block_n;      // the block's N, set at its start
  uint8_t step;          // counter states completed this session, saturating at 255
  uint8_t state;         // the resting state
  uint8_t block;         // the running block; NONE before the first trial start
  uint8_t outcome;       // this trial's class: the last marked state it entered, or 0
  uint8_t response;      // this trial's response, an input bit, or NONE
  uint8_t entry;         // the branch this trial's block pick took, or NONE
  uint8_t repeats;       // correction repeats in a row
  uint8_t correcting;    // this trial repeats the last one
  uint8_t hist_len;      // responses held in hist[]
  uint8_t hist_at;       // where the next one goes
  uint8_t hist[INTERP_HISTORY];
} InterpCore;

/*  avr-libc's random(): Park and Miller's minimal standard, x' = 16807 x mod
    (2^31 - 1), by Schrage's method so no product leaves 32 bits. The same
    arithmetic as avr-libc's do_random(), including its quirks: a zero state
    is read as 123459876, and a state above 2^31 - 1 is read as a negative
    long. replay.py's avr_random() reproduces it, and test_interp.cpp pins it
    to Park and Miller's published check value. */
static inline uint32_t interp_random(uint32_t *ctx)
{
  int32_t x = (int32_t)*ctx;
  if (x == 0) x = 123459876L;
  int32_t hi = x / 127773L;
  int32_t lo = x % 127773L;
  x = 16807L * lo - 2836L * hi;
  if (x < 0) x += 0x7fffffffL;
  *ctx = (uint32_t)x;
  return *ctx % 0x80000000UL;
}

/*  interp_random() % n, with n an unsigned uint32_t over the whole range [1, 2^32 - 1],
    and 0 without a draw when n is 0. Not Arduino's random(n): that takes a signed
    long, so the two differ for n >= 2^31. Below that they agree. */
static inline uint32_t interp_draw(uint32_t *ctx, uint32_t n)
{
  if (n == 0) return 0;
  return interp_random(ctx) % n;
}

/*  True when a tick did nothing: no report, no transition. */
static inline bool interp_idle(const InterpActions *a)
{
  return a->rose == 0 && a->fell == 0 && a->entered[0] == INTERP_NONE && a->flags == 0;
}

static inline InterpActions interp__none(void)
{
  InterpActions a;
  a.rose = a.fell = a.on = a.off = 0;
  a.entered[0] = a.entered[1] = INTERP_NONE;
  a.flags = 0;
  a.block = INTERP_NONE;
  return a;
}

/*  The parameter a state or the counter reads at `slot`: the running block's
    first override of it, or its own. */
static inline uint32_t interp__param(const InterpCore *c, uint8_t slot)
{
  const InterpBlocks *b = c->table->blocks;
  if (b != NULL)
    for (uint8_t i = 0; i < b->override_count; ++i)
      if (b->overrides[i].block == c->block && b->overrides[i].slot == slot) return c->params[b->overrides[i].with];
  return c->params[slot];
}

static inline uint8_t interp__ones(uint32_t x)
{
  uint8_t n = 0;
  for (; x; x &= x - 1) ++n;
  return n;
}

/*  Start block b: its counters and its bag start over, and its N is drawn. */
static inline void interp__start_block(InterpCore *c, uint8_t b, InterpActions *a)
{
  const InterpBlock *k = &c->table->blocks->rows[b];
  c->block = b;
  c->block_trials = 0;
  c->block_n = 0;
  c->corrects = 0;
  c->bag = 0;
  c->repeats = 0;
  if (k->n_min != INTERP_NONE) {
    uint32_t lo = c->params[k->n_min];
    uint32_t hi = c->params[k->n_max];
    c->block_n = (uint16_t)(hi > lo ? lo + interp_draw(&c->rng, hi - lo + 1) : lo);
  }
  a->flags |= INTERP_ACT_BLOCK_START;
}

/*  At a trial start, whether the running block has ended: its N trials have
    started, or k of its last n were correct (n read as at most INTERP_HISTORY). */
static inline bool interp__block_ends(const InterpCore *c, const InterpBlock *k)
{
  if (k->n_min != INTERP_NONE && c->block_trials >= c->block_n) return true;
  if (k->k != INTERP_NONE) {
    uint32_t n = c->params[k->n];
    uint32_t mask = n >= INTERP_HISTORY ? 0xFFFFFFFFUL : ((uint32_t)1 << n) - 1;
    if (interp__ones(c->corrects & mask) >= c->params[k->k]) return true;
  }
  return false;
}

/*  A trial starts, in a table with blocks: the last trial goes into the
    history, the block's end rule runs, and the correction rule decides whether
    this trial repeats the last. */
static inline void interp__trial(InterpCore *c, InterpActions *a)
{
  uint8_t last_outcome = c->outcome;
  uint8_t last_entry = c->entry;
  c->entry = INTERP_NONE;
  c->correcting = 0;
  if (c->block == INTERP_NONE) {
    interp__start_block(c, 0, a);
  } else {
    c->corrects = (c->corrects << 1) | (last_outcome == INTERP_CORRECT ? 1UL : 0UL);
    if (c->response != INTERP_NONE) {
      c->hist[c->hist_at] = c->response;
      c->hist_at = (uint8_t)((c->hist_at + 1) % INTERP_HISTORY);
      if (c->hist_len < INTERP_HISTORY) ++c->hist_len;
    }
    const InterpBlock *k = &c->table->blocks->rows[c->block];
    if (interp__block_ends(c, k)) {
      if (k->next == INTERP_NONE) a->flags |= INTERP_ACT_DONE;
      else interp__start_block(c, k->next, a);
    } else if (k->correct != INTERP_NONE && last_outcome != 0 && last_outcome != INTERP_CORRECT
               && c->repeats < c->params[k->correct]) {
      ++c->repeats;
      c->correcting = 1;
      c->entry = last_entry;
      a->flags |= INTERP_ACT_CORRECTION;
    } else {
      c->repeats = 0;
    }
  }
  c->outcome = 0;
  c->response = INTERP_NONE;
  if (c->block_trials != 0xFFFF) ++c->block_trials;
}

static inline uint32_t interp__weight(const InterpCore *c, uint8_t e)
{
  const InterpBlocks *b = c->table->blocks;
  if (b->entries == NULL || b->entries[e].weight == INTERP_NONE) return 1;
  uint32_t w = c->params[b->entries[e].weight];
  return w > INTERP_WEIGHT_MAX ? INTERP_WEIGHT_MAX : w;
}

static inline uint8_t interp__side(const InterpCore *c, uint8_t e)
{
  const InterpBlocks *b = c->table->blocks;
  return b->entries == NULL ? INTERP_NONE : b->entries[e].side;
}

/*  One of block k's branches by weight: r = draw(their sum), and the first whose
    running sum passes r; uniformly, r = draw(how many), when the weights sum to
    0. With `all` false only the branches on `side` take part. */
static inline uint8_t interp__by_weight(InterpCore *c, const InterpBlock *k, bool all, uint8_t side)
{
  uint32_t total = 0, n = 0;
  for (uint8_t e = k->first; e < k->first + k->count; ++e)
    if (all || interp__side(c, e) == side) { total += interp__weight(c, e); ++n; }
  bool uniform = total == 0;
  uint32_t r = interp_draw(&c->rng, uniform ? n : total);
  for (uint8_t e = k->first; e < k->first + k->count; ++e) {
    if (!all && interp__side(c, e) != side) continue;
    uint32_t w = uniform ? 1 : interp__weight(c, e);
    if (r < w) return e;
    r -= w;
  }
  return (uint8_t)(k->first + k->count - 1); // unreachable: r is below the sum
}

/*  A shuffle bag: each branch's weight in tokens, at most INTERP_HISTORY in all
    (a token past the 32nd is never drawn), drawn without replacement and refilled
    once empty: r = draw(tokens left), and the r-th token left. Weights summing
    to 0 draw uniformly. */
static inline uint8_t interp__from_bag(InterpCore *c, const InterpBlock *k)
{
  uint32_t total = 0;
  for (uint8_t e = k->first; e < k->first + k->count; ++e) total += interp__weight(c, e);
  if (total > INTERP_HISTORY) total = INTERP_HISTORY;
  if (total == 0) return (uint8_t)(k->first + interp_draw(&c->rng, k->count));
  uint32_t full = total == INTERP_HISTORY ? 0xFFFFFFFFUL : ((uint32_t)1 << total) - 1;
  if ((c->bag & full) == full) c->bag = 0;
  uint32_t r = interp_draw(&c->rng, total - interp__ones(c->bag & full));
  uint32_t token = 0;
  for (;; ++token)
    if (!(c->bag & ((uint32_t)1 << token)) && r-- == 0) break;
  c->bag |= (uint32_t)1 << token;
  uint32_t upto = 0;
  for (uint8_t e = k->first; e < k->first + k->count; ++e) {
    upto += interp__weight(c, e);
    if (token < upto) return e;
  }
  return (uint8_t)(k->first + k->count - 1); // unreachable
}

/*  Anti-bias: a side, then a branch on it by weight. Each side in the block,
    in the order its first branch comes, weighs 1 + L - its count among the
    last L responses, L being the responses held, at most the window. */
static inline uint8_t interp__antibias(InterpCore *c, const InterpBlock *k)
{
  uint32_t len = c->hist_len;
  if (k->window != INTERP_NONE && c->params[k->window] < len) len = c->params[k->window];
  uint32_t total = 0, r = 0;
  for (uint8_t pass = 0; pass < 2; ++pass) {
    if (pass) r = interp_draw(&c->rng, total);
    for (uint8_t e = k->first; e < k->first + k->count; ++e) {
      uint8_t side = interp__side(c, e);
      bool seen = false;
      for (uint8_t f = k->first; f < e; ++f) seen = seen || interp__side(c, f) == side;
      if (seen) continue;
      uint32_t count = 0;
      for (uint32_t j = 0; j < len; ++j)
        if (c->hist[(c->hist_at + INTERP_HISTORY - 1 - j) % INTERP_HISTORY] == side) ++count;
      uint32_t w = 1 + len - count;
      if (!pass) total += w;
      else if (r < w) return interp__by_weight(c, k, false, side);
      else r -= w;
    }
  }
  return k->first; // unreachable: r is below the sum
}

/*  The branch a trial-starting pick takes in a table with blocks: the last
    trial's, for a correction, or one drawn by the running block's selection. */
static inline uint8_t interp__select(InterpCore *c)
{
  const InterpBlock *k = &c->table->blocks->rows[c->block];
  if (c->correcting && c->entry != INTERP_NONE) return c->entry;
  if (k->select == INTERP_WEIGHTED) return interp__by_weight(c, k, true, INTERP_NONE);
  if (k->select == INTERP_BAG) return interp__from_bag(c, k);
  if (k->select == INTERP_ANTIBIAS) return interp__antibias(c, k);
  return (uint8_t)(k->first + interp_draw(&c->rng, k->count));
}

/*  Enter `target` at `now`: run a trial start's block rules, follow a chance or
    pick state's branch, draw the resting state's duration, and diff its outputs
    against the previous resting state's. */
static inline void interp__enter(InterpCore *c, uint8_t target, uint32_t now, InterpActions *a)
{
  const InterpStateRow *s;
  const InterpBlocks *blocks = c->table->blocks;
  for (uint8_t hop = 0;; ++hop) {
    s = &c->table->states[target];
    a->entered[hop] = target;
    if (s->flags & INTERP_STARTS_TRIAL) {
      a->flags |= INTERP_ACT_TRIAL_START;
      if (blocks != NULL) interp__trial(c, a);
    }
    if (s->flags & INTERP_LAST_TRIAL) a->flags |= INTERP_ACT_LAST_TRIAL;
    if (s->outcome) c->outcome = s->outcome;
    c->state = target;
    c->entered_at = now;
    // A valid table never chains two branching states; hop bounds an invalid one.
    if ((s->chance == INTERP_NONE && !(s->flags & INTERP_PICK)) || hop == 1) break;
    if (s->chance != INTERP_NONE) {
      target = interp_draw(&c->rng, INTERP_PERMILLE) < interp__param(c, s->chance) ? s->on_hit : s->on_miss;
    } else if (blocks != NULL && (s->flags & INTERP_STARTS_TRIAL)) {
      c->entry = interp__select(c);
      target = c->table->edges[s->edge_first + c->entry].next;
    } else {
      target = c->table->edges[s->edge_first + interp_draw(&c->rng, s->edge_count)].next;
    }
  }
  if (s->flags & INTERP_COUNT) {
    // N first, then the duration: the order replay draws them in.
    const InterpCounter *k = c->table->counter;
    c->count = 0;
    if (k->count_min == INTERP_NONE) {
      c->target = k->ratios[c->step < k->ratio_count ? c->step : k->ratio_count - 1];
    } else {
      uint32_t lo = interp__param(c, k->count_min);
      uint32_t hi = interp__param(c, k->count_max);
      c->target = (uint16_t)(hi > lo ? lo + interp_draw(&c->rng, hi - lo + 1) : lo);
    }
  }
  c->duration = 0;
  if (s->timer_min != INTERP_NONE) {
    uint32_t lo = interp__param(c, s->timer_min);
    uint32_t hi = interp__param(c, s->timer_max);
    c->duration = hi > lo ? lo + interp_draw(&c->rng, hi - lo + 1) : lo;
  }
  uint32_t was = c->outputs;
  c->outputs = s->outputs;
  a->on = s->outputs & ~was;
  a->off = was & ~s->outputs;
}

/*  The session's first tick: seed the RNG (avr-libc srandom()), start with every
    output LOW, no block and no history, and enter state 0. */
static inline InterpActions interp_begin(InterpCore *c, const InterpTable *table,
                                         const uint32_t *params, uint32_t seed, uint32_t now)
{
  c->table = table;
  c->params = params;
  c->rng = seed;
  c->outputs = 0;
  c->count = c->target = 0;
  c->step = 0;
  c->corrects = c->bag = 0;
  c->block_trials = c->block_n = 0;
  c->block = c->response = c->entry = INTERP_NONE;
  c->outcome = c->repeats = c->correcting = 0;
  c->hist_len = c->hist_at = 0;
  for (uint8_t i = 0; i < INTERP_HISTORY; ++i) c->hist[i] = INTERP_NONE;
  InterpActions a = interp__none();
  a.flags = INTERP_ACT_SESSION_START;
  interp__enter(c, 0, now, &a);
  a.block = c->block;
  return a;
}

static inline bool interp__matches(const InterpEdgeRow *e, const InterpActions *a)
{
  uint32_t bit = (uint32_t)1 << e->input;
  return ((e->edge == INTERP_RISE ? a->rose : a->fell) & bit) != 0;
}

/*  Every tick after the first: the tick rules above. */
static inline InterpActions interp_step(InterpCore *c, InterpEdges in, uint32_t now)
{
  const InterpStateRow *s = &c->table->states[c->state];
  const InterpEdgeRow *rows = c->table->edges + s->edge_first;
  InterpActions a = interp__none();
  a.rose = in.rose & s->watch;
  a.fell = in.fell & s->watch;

  uint8_t matches = 0;
  for (uint8_t i = 0; i < s->edge_count; ++i)
    if (interp__matches(&rows[i], &a)) ++matches;

  if (matches && (s->flags & INTERP_COUNT)) {
    // A counter state's one edge row is its counted rise: an exit only at the N-th.
    ++c->count;
    if (c->count < c->target) matches = 0;
    else if (c->step != 0xFF) ++c->step;
  }

  uint8_t target = INTERP_NONE;
  if (matches) {
    uint32_t k = matches == 1 ? 0 : interp_draw(&c->rng, matches);
    for (uint8_t i = 0; i < s->edge_count; ++i)
      if (interp__matches(&rows[i], &a) && k-- == 0) {
        target = rows[i].next;
        // An edge out of a response state is the trial's response, its first only.
        if ((s->flags & INTERP_RESPONSE) && c->response == INTERP_NONE) c->response = rows[i].input;
        break;
      }
  } else if (s->timer_min != INTERP_NONE && (uint32_t)(now - c->entered_at) >= c->duration) {
    target = s->on_timeout;
  }
  if (target != INTERP_NONE) interp__enter(c, target, now, &a);
  a.block = c->block;
  return a;
}

#endif // BOX_INTERP_H

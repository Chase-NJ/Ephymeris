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
       not hold a timer off.
    3. TWO OR MORE MATCHING EDGES are broken by a draw from the session RNG:
       the k-th match in table order, k = interp_draw(rng, matches). A single
       match draws nothing.
    4. OTHERWISE THE TIMER: the state exits to `on_timeout` once
       now - entered_at >= its duration. A timer is only checked for the state
       current at the start of a tick, so a state lasts at least one tick, even
       with a zero duration.
    5. ENTERING a state records the tick as its entry time and draws its
       duration. A chance state branches at once (below); its target is entered
       in the same tick.
  A tick that reports no edge and moves nothing changes nothing at all, the RNG
  included, so a replay may jump straight to the next edge or timer.

  Every draw is an integer: interp_draw(rng, n) is Arduino's random(n), that is
  avr-libc random() % n, over a generator the core carries in its own state.


  THE STATE TABLE (INTERP_VERSION 1)
  ----------------------------------
  Generated data. A table is an array of InterpStateRow, indexed 0..254, and an
  array of InterpEdgeRow the states point into. State 0 is where a session
  starts. INTERP_NONE (255) means "none" in every uint8_t field.

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
    edge_count
    flags       INTERP_STARTS_TRIAL: entering it reports TRIAL_START.
    outcome     The outcome class this state records, or 0. The core carries it
                and never reads it; replay reads it off the states a trial
                entered.

  InterpEdgeRow, one per exit on an input:
    input       The input's bit number; it must be in the state's `watch`.
    edge        INTERP_RISE (the input became active) or INTERP_FALL.
    next        The state entered.

  A VALID TABLE, which the core assumes and replay.py's Table refuses to break:
    - every state index, edge row and parameter slot is in range;
    - an edge row's input is watched, and a state has at most one edge row per
      (input, edge);
    - a chance state has no outputs, watch, timer or edge rows, and neither of
      its targets is a chance state, so a tick enters at most two states.


  LOWERING THE FIRST PHASES
  -------------------------
  How the generator writes each phase of the ADR's palette as states:

    Wait(c, timeout -> X)     watch c; edge (c, RISE) -> next; timer -> X, or none.
    Present(o for t)          outputs o; timer t -> next. "Or on an edge e" adds
                              edge (e, RISE) -> next; "abort if the hold on h is
                              lost" adds edge (h, FALL) -> the abort state.
    Delay(t)                  timer t -> next; "abort on an edge" adds that edge row.
    Outcome(line r, ms, p)    a chance state (p -> reward, else -> class timeout,
                              outcome = the class); reward: outputs r, timer ms ->
                              class timeout; class timeout: timer -> next.
    ITI(t)                    timer t -> the trial's first state, which carries
                              INTERP_STARTS_TRIAL.


  THE ACTIONS OF A TICK
  ---------------------
  InterpActions, which the hardware layer strobes in this order, each mask in
  ascending bit order:
    SESSION_START (flags), watched inputs that rose and fell (rose, fell),
    TRIAL_START (flags), outputs driven LOW (off), outputs driven HIGH (on).
  entered[] lists the states entered this tick in order, NONE-padded. It is
  never strobed (the stream carries no state codes) but replay predicts it,
  and the differential test compares it.

  Tables live in RAM as plain const arrays for now; how much a table may cost
  is an open question (0003-phase-spine-task-model.md#open-questions, the RAM
  budget).
*/

#ifndef BOX_INTERP_H
#define BOX_INTERP_H

#include <stdbool.h>
#include <stdint.h>

#define INTERP_VERSION 1

#define INTERP_NONE 0xFF       // "no state / no slot / no timer" in a uint8_t field
#define INTERP_PERMILLE 1000UL // a chance state draws over [0, 1000)

#define INTERP_RISE 1          // InterpEdgeRow.edge
#define INTERP_FALL 2

#define INTERP_STARTS_TRIAL 0x01       // InterpStateRow.flags

#define INTERP_ACT_SESSION_START 0x01  // InterpActions.flags
#define INTERP_ACT_TRIAL_START 0x02

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
  const InterpStateRow *states;
  const InterpEdgeRow *edges;
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
} InterpActions;

/*  The whole of a running session's state. The caller owns it; only
    interp_begin() and interp_step() write it. */
typedef struct {
  const InterpTable *table;
  const uint32_t *params;
  uint32_t rng;        // avr-libc random()'s state
  uint32_t entered_at; // the tick the resting state was entered
  uint32_t duration;   // its timer, drawn at entry
  uint32_t outputs;    // the outputs now HIGH
  uint8_t state;       // the resting state
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

/*  Arduino's random(n): random() % n, and 0 without a draw when n is 0. */
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
  return a;
}

/*  Enter `target` at `now`: follow a chance state's branch, draw the resting
    state's duration, and diff its outputs against the previous resting state's. */
static inline void interp__enter(InterpCore *c, uint8_t target, uint32_t now, InterpActions *a)
{
  const InterpStateRow *s;
  for (uint8_t hop = 0;; ++hop) {
    s = &c->table->states[target];
    a->entered[hop] = target;
    if (s->flags & INTERP_STARTS_TRIAL) a->flags |= INTERP_ACT_TRIAL_START;
    c->state = target;
    c->entered_at = now;
    // A valid table never chains two chance states; hop bounds an invalid one.
    if (s->chance == INTERP_NONE || hop == 1) break;
    target = interp_draw(&c->rng, INTERP_PERMILLE) < c->params[s->chance] ? s->on_hit : s->on_miss;
  }
  c->duration = 0;
  if (s->timer_min != INTERP_NONE) {
    uint32_t lo = c->params[s->timer_min];
    uint32_t hi = c->params[s->timer_max];
    c->duration = hi > lo ? lo + interp_draw(&c->rng, hi - lo + 1) : lo;
  }
  uint32_t was = c->outputs;
  c->outputs = s->outputs;
  a->on = s->outputs & ~was;
  a->off = was & ~s->outputs;
}

/*  The session's first tick: seed the RNG (avr-libc srandom()), start with every
    output LOW, and enter state 0. */
static inline InterpActions interp_begin(InterpCore *c, const InterpTable *table,
                                         const uint32_t *params, uint32_t seed, uint32_t now)
{
  c->table = table;
  c->params = params;
  c->rng = seed;
  c->outputs = 0;
  InterpActions a = interp__none();
  a.flags = INTERP_ACT_SESSION_START;
  interp__enter(c, 0, now, &a);
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

  uint8_t target = INTERP_NONE;
  if (matches) {
    uint32_t k = matches == 1 ? 0 : interp_draw(&c->rng, matches);
    for (uint8_t i = 0; i < s->edge_count; ++i)
      if (interp__matches(&rows[i], &a) && k-- == 0) { target = rows[i].next; break; }
  } else if (s->timer_min != INTERP_NONE && (uint32_t)(now - c->entered_at) >= c->duration) {
    target = s->on_timeout;
  }
  if (target != INTERP_NONE) interp__enter(c, target, now, &a);
  return a;
}

#endif // BOX_INTERP_H

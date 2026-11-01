#include <cassert>
#include <cstdio>
#include "BoxInterp.h"

/*  Channel numbers here are arbitrary, as in the other host tests: the core
    knows bits, not the lab's wiring. */
enum { PORT = 0, LEFT = 1, RIGHT = 2 };            // inputs
enum { LIGHT = 0, ODOR = 3, FLUID = 5 };           // outputs
#define BIT(n) (1UL << (n))
#define NO INTERP_NONE

/*  Parameter slots the tables below point at. */
enum { P_100 = 0, P_0 = 1, P_10 = 2, P_12 = 3, P_ALWAYS = 4, P_NEVER = 5 };
static const uint32_t PARAMS[] = {100, 0, 10, 12, 1000, 0};

static InterpEdges edges(uint32_t rose, uint32_t fell) { InterpEdges e; e.rose = rose; e.fell = fell; return e; }
static const InterpEdges NOTHING = edges(0, 0);

static bool idle(const InterpActions &a) { return interp_idle(&a); }

/*  A two-choice trial:
      0 Wait     light on, watch PORT; PORT rise -> 1; times out after 100 -> 3
      1 Present  light + odor, watch PORT, LEFT, RIGHT; LEFT rise -> 2, RIGHT rise -> 3,
                 PORT fall -> 3 (hold lost); after 100 -> 3
      2 Reward   fluid for 10 -> 3
      3 ITI      after 100 -> 0                                                    */
static const InterpEdgeRow TRIAL_EDGES[] = {
  {PORT, INTERP_RISE, 1},
  {LEFT, INTERP_RISE, 2}, {RIGHT, INTERP_RISE, 3}, {PORT, INTERP_FALL, 3},
};
static const InterpStateRow TRIAL_STATES[] = {
  // outputs              watch                         tmin   tmax   tout chance hit miss first count flags outcome
  {BIT(LIGHT),            BIT(PORT),                    P_100, P_100, 3,   NO,    NO, NO,  0,    1,    INTERP_STARTS_TRIAL, 0},
  {BIT(LIGHT) | BIT(ODOR), BIT(PORT) | BIT(LEFT) | BIT(RIGHT), P_100, P_100, 3, NO, NO, NO, 1,    3,    0, 0},
  {BIT(FLUID),            0,                            P_10,  P_10,  3,   NO,    NO, NO,  0,    0,    0, 1},
  {0,                     0,                            P_100, P_100, 0,   NO,    NO, NO,  0,    0,    0, 0},
};
static const InterpTable TRIAL = {TRIAL_STATES, TRIAL_EDGES, NULL, NULL};

/*  BLOCKS (INTERP 5). Two rows, each a Response window:
      0 Pick     the block's draw: its branches are the blocks' rows, block by block
      1 Row A    light on, watch LEFT and RIGHT (a response state); LEFT -> 3, RIGHT -> 4;
                 after 100 -> 5
      2 Row B    odor on, the same, but RIGHT -> 3 and LEFT -> 4
      3 Correct  fluid for 10 -> 0, marked class 1 (correct)
      4 Wrong    10 -> 0, marked class 2 (wrong_response)
      5 Timeout  10 -> 0, marked with the class timeout_class() gives it: 7
                 (abort_before_stimulus) unless a test sets another
    The pick's branches: 0 A and 1 B (block 0), 2 B and 3 A (block 1).
    ERR is the default error set, wrong_response and false_alarm (classes 2
    and 6); SKIP the classes a criterion passes over, the two aborts (7, 8). */
enum { B0 = 0, B1 = 1, B2 = 2, B3 = 3, B5 = 4, B10 = 5, B100 = 6, B50 = 7 };
static const uint32_t BP[] = {0, 1, 2, 3, 5, 10, 100, 50};
static const InterpEdgeRow BLOCK_EDGES[] = {
  {0, 0, 1}, {0, 0, 2}, {0, 0, 2}, {0, 0, 1},
  {LEFT, INTERP_RISE, 3}, {RIGHT, INTERP_RISE, 4},
  {RIGHT, INTERP_RISE, 3}, {LEFT, INTERP_RISE, 4},
};
static const InterpStateRow BLOCK_STATES[] = {
  {0,          0,                     NO,   NO,   NO, NO, NO, NO, 0, 4, INTERP_STARTS_TRIAL | INTERP_PICK, 0},
  {BIT(LIGHT), BIT(LEFT) | BIT(RIGHT), B100, B100, 5,  NO, NO, NO, 4, 2, INTERP_RESPONSE, 0},
  {BIT(ODOR),  BIT(LEFT) | BIT(RIGHT), B100, B100, 5,  NO, NO, NO, 6, 2, INTERP_RESPONSE, 0},
  {BIT(FLUID), 0,                     B10,  B10,  0,  NO, NO, NO, 0, 0, 0, 1},
  {0,          0,                     B10,  B10,  0,  NO, NO, NO, 0, 0, 0, 2},
  {0,          0,                     B10,  B10,  0,  NO, NO, NO, 0, 0, 0, 7},
};
#define CLASS_BIT(c) ((uint16_t)(1U << ((c) - 1)))
static const uint16_t ERR = CLASS_BIT(2) | CLASS_BIT(6);
static const uint16_t SKIP = CLASS_BIT(7) | CLASS_BIT(8);
static InterpStateRow g_timeout_states[6];

/*  BLOCK_STATES with the timeout end (state 5) marked `cls`. */
static const InterpStateRow *timeout_class(uint8_t cls)
{
  for (int i = 0; i < 6; ++i) g_timeout_states[i] = BLOCK_STATES[i];
  g_timeout_states[5].outcome = cls;
  return g_timeout_states;
}
/*  {side, weight}: A is answered LEFT, B RIGHT. */
static const InterpEntry BLOCK_ENTRIES[] = {{LEFT, B2}, {RIGHT, B1}, {RIGHT, B1}, {LEFT, B1}};

static InterpTable blocks_table(const InterpBlocks *b)
{
  InterpTable t = {BLOCK_STATES, BLOCK_EDGES, NULL, b};
  return t;
}

/*  The response the resting row pays for, and the one it does not. */
static uint32_t right_answer(const InterpCore &c) { return c.state == 1 ? BIT(LEFT) : BIT(RIGHT); }
static uint32_t wrong_answer(const InterpCore &c) { return c.state == 1 ? BIT(RIGHT) : BIT(LEFT); }

/*  Respond at the next tick, then let the outcome's 10 ms run: the actions of the next trial's start. */
static InterpActions respond(InterpCore &c, uint32_t bit, uint32_t &t)
{
  InterpActions a = interp_step(&c, edges(bit, 0), ++t);
  assert(a.entered[0] == 3 || a.entered[0] == 4);
  t += 10;
  a = interp_step(&c, NOTHING, t);
  assert(a.entered[0] == 0 && (a.flags & INTERP_ACT_TRIAL_START));
  return a;
}

/*  Let the window run out (100) into the timeout end, then its 10 ms: the next trial's start. */
static InterpActions time_out(InterpCore &c, uint32_t &t)
{
  t += 100;
  InterpActions a = interp_step(&c, NOTHING, t);
  assert(a.entered[0] == 5);
  t += 10;
  a = interp_step(&c, NOTHING, t);
  assert(a.entered[0] == 0 && (a.flags & INTERP_ACT_TRIAL_START));
  return a;
}

static void test_blocks()
{
  // A table without blocks reports none.
  { InterpCore c; assert(interp_begin(&c, &TRIAL, PARAMS, 1, 0).block == NO); }

  // N trials, then the next block; its last trial ends the sequence (DONE).
  //   {first, count, select, n_min, n_max, k, n, window, correct, next}
  { static const InterpBlock R[] = {
      {0, 2, INTERP_UNIFORM, B2, B2, NO, NO, NO, NO, 1, ERR},
      {2, 1, INTERP_UNIFORM, B3, B3, NO, NO, NO, NO, NO, ERR}};
    static const InterpBlocks BL = {R, NULL, NULL, 2, 0, 0, SKIP};
    InterpTable T = blocks_table(&BL);
    InterpCore c; InterpActions a = interp_begin(&c, &T, BP, 1, 0);
    assert(a.block == 0 && (a.flags & INTERP_ACT_BLOCK_START) && (a.flags & INTERP_ACT_TRIAL_START));
    uint32_t t = 0;
    a = respond(c, right_answer(c), t);
    assert(a.block == 0 && !(a.flags & INTERP_ACT_BLOCK_START));
    a = respond(c, right_answer(c), t);                  // trial 3 starts block 1, which draws only B
    assert(a.block == 1 && (a.flags & INTERP_ACT_BLOCK_START) && a.entered[1] == 2);
    a = respond(c, wrong_answer(c), t);
    a = respond(c, right_answer(c), t);
    assert(a.block == 1 && !(a.flags & INTERP_ACT_DONE));
    a = respond(c, right_answer(c), t);                  // block 1's three trials are run
    assert((a.flags & INTERP_ACT_DONE) && !(a.flags & INTERP_ACT_BLOCK_START) && a.block == 1); }

  // k correct of the last n (2 of 3): errors do not count; a loop goes back.
  { static const InterpBlock R[] = {
      {0, 2, INTERP_UNIFORM, NO, NO, B2, B3, NO, NO, 1, ERR},
      {2, 1, INTERP_UNIFORM, B1, B1, NO, NO, NO, NO, 0, ERR}};
    static const InterpBlocks BL = {R, NULL, NULL, 2, 0, 0, SKIP};
    InterpTable T = blocks_table(&BL);
    InterpCore c; interp_begin(&c, &T, BP, 7, 0);
    uint32_t t = 0;
    InterpActions a = respond(c, right_answer(c), t);     // 1 of 1
    a = respond(c, wrong_answer(c), t);                   // 1 of 2
    a = respond(c, wrong_answer(c), t);                   // 1 of 3
    assert(a.block == 0);
    a = respond(c, right_answer(c), t);                   // 1 of the last 3 (W W C)
    assert(a.block == 0);
    a = respond(c, right_answer(c), t);                   // 2 of the last 3: block 1
    assert(a.block == 1 && (a.flags & INTERP_ACT_BLOCK_START));
    a = respond(c, wrong_answer(c), t);                   // block 1's one trial: loop to 0
    assert(a.block == 0 && (a.flags & INTERP_ACT_BLOCK_START));
    a = respond(c, right_answer(c), t);                   // the history starts over with the block
    assert(a.block == 0); }

  // A drawn N: lo + draw(hi - lo + 1) at the block's start, before the pick's draw.
  { static const InterpBlock R[] = {
      {0, 2, INTERP_UNIFORM, B2, B5, NO, NO, NO, NO, NO, ERR}};
    static const InterpBlocks BL = {R, NULL, NULL, 1, 0, 0, SKIP};
    InterpTable T = blocks_table(&BL);
    for (uint32_t seed = 11; seed < 11 + 40 * 7919UL; seed += 7919UL) {
      uint32_t ctx = seed;
      uint32_t want = 2 + interp_draw(&ctx, 4);
      uint8_t row = (uint8_t)(1 + interp_draw(&ctx, 2));
      InterpCore c; InterpActions a = interp_begin(&c, &T, BP, seed, 0);
      assert(a.entered[1] == row && c.rng == ctx);
      uint32_t t = 0, trials = 1;
      while (!((a = respond(c, right_answer(c), t)).flags & INTERP_ACT_DONE)) ++trials;
      assert(trials == want);
    } }

  // Correction: after an error the same row repeats, with no draw, up to k (2) times.
  { static const InterpBlock R[] = {
      {0, 2, INTERP_UNIFORM, NO, NO, NO, NO, NO, B2, NO, ERR}};
    static const InterpBlocks BL = {R, NULL, NULL, 1, 0, 0, SKIP};
    InterpTable T = blocks_table(&BL);
    InterpCore c; interp_begin(&c, &T, BP, 3, 0);
    uint32_t t = 0;
    uint8_t row = c.state;
    InterpActions a = respond(c, wrong_answer(c), t);
    assert((a.flags & INTERP_ACT_CORRECTION) && a.entered[1] == row);
    uint32_t before = c.rng;
    a = respond(c, wrong_answer(c), t);
    assert((a.flags & INTERP_ACT_CORRECTION) && a.entered[1] == row && c.rng == before);
    a = respond(c, wrong_answer(c), t);                   // past k: drawn again
    assert(!(a.flags & INTERP_ACT_CORRECTION) && c.rng != before);
    row = c.state;
    a = respond(c, wrong_answer(c), t);                   // the run of repeats starts over
    assert((a.flags & INTERP_ACT_CORRECTION) && a.entered[1] == row);
    a = respond(c, right_answer(c), t);                   // a correct trial is not repeated
    assert(!(a.flags & INTERP_ACT_CORRECTION)); }

  // Weighted: a row of weight 0 is never drawn (block 1's A, weight B0 here).
  { static const InterpEntry ENT[] = {{LEFT, B0}, {RIGHT, B1}, {RIGHT, B1}, {LEFT, B1}};
    static const InterpBlock R[] = {
      {0, 2, INTERP_WEIGHTED, NO, NO, NO, NO, NO, NO, NO, ERR}};
    static const InterpBlocks BL = {R, ENT, NULL, 1, 4, 0, SKIP};
    InterpTable T = blocks_table(&BL);
    InterpCore c; interp_begin(&c, &T, BP, 5, 0);
    uint32_t t = 0;
    for (int i = 0; i < 30; ++i) { assert(c.state == 2); respond(c, right_answer(c), t); } }

  // Weighted 2 : 1 is r = draw(3), r < 2 -> A.
  { static const InterpBlock R[] = {
      {0, 2, INTERP_WEIGHTED, NO, NO, NO, NO, NO, NO, NO, ERR}};
    static const InterpBlocks BL = {R, BLOCK_ENTRIES, NULL, 1, 4, 0, SKIP};
    InterpTable T = blocks_table(&BL);
    for (uint32_t seed = 1; seed < 40; ++seed) {
      uint32_t ctx = seed;
      uint8_t want = interp_draw(&ctx, 3) < 2 ? 1 : 2;
      InterpCore c; interp_begin(&c, &T, BP, seed, 0);
      assert(c.state == want && c.rng == ctx);
    } }

  // A shuffle bag of A twice and B once: every three trials hold exactly that.
  { static const InterpBlock R[] = {
      {0, 2, INTERP_BAG, NO, NO, NO, NO, NO, NO, NO, ERR}};
    static const InterpBlocks BL = {R, BLOCK_ENTRIES, NULL, 1, 4, 0, SKIP};
    InterpTable T = blocks_table(&BL);
    for (uint32_t seed = 1; seed < 20; ++seed) {
      InterpCore c; interp_begin(&c, &T, BP, seed, 0);
      uint32_t t = 0;
      int seen[3] = {0};
      for (int i = 0; i < 12; ++i) {
        seen[c.state]++;
        if (i % 3 == 2) { assert(seen[1] == 2 && seen[2] == 1); seen[1] = seen[2] = 0; }
        respond(c, right_answer(c), t);
      }
    } }

  // Anti-bias: each side weighs 1 + L - its count among the last L responses (L at
  // most the window, 3); then a row on the drawn side, by weight. Only an exit
  // from a response state is a response.
  { static const InterpBlock R[] = {
      {0, 2, INTERP_ANTIBIAS, NO, NO, NO, NO, B3, NO, NO, ERR}};
    static const InterpBlocks BL = {R, BLOCK_ENTRIES, NULL, 1, 4, 0, SKIP};
    InterpTable T = blocks_table(&BL);
    for (uint32_t seed = 1; seed < 40; ++seed) {
      InterpCore c;
      uint32_t ctx = seed;
      uint32_t side = interp_draw(&ctx, 2);              // no history: 1 : 1, LEFT first
      interp_draw(&ctx, side == 0 ? 2 : 1);              // the row on that side, by weight
      interp_begin(&c, &T, BP, seed, 0);
      assert(c.state == (side == 0 ? 1 : 2) && c.rng == ctx);
      uint32_t t = 0;
      for (int i = 0; i < 4; ++i) respond(c, BIT(LEFT), t);   // right or wrong, a response is a side
      // The next start's history: five LEFT, of which the window reads 3.
      ctx = c.rng;
      side = interp_draw(&ctx, 1 + 4);                   // LEFT 1 + 3 - 3 = 1, RIGHT 1 + 3 - 0 = 4
      interp_draw(&ctx, side < 1 ? 2 : 1);
      respond(c, BIT(LEFT), t);
      assert(c.state == (side < 1 ? 1 : 2) && c.rng == ctx);
    } }

  // An override: while block 1 runs, a state reading B10 reads B50.
  { static const InterpBlock R[] = {
      {0, 2, INTERP_UNIFORM, B1, B1, NO, NO, NO, NO, 1, ERR},
      {2, 1, INTERP_UNIFORM, NO, NO, NO, NO, NO, NO, NO, ERR}};
    static const InterpOverride O[] = {{1, B10, B50}};
    static const InterpBlocks BL = {R, NULL, O, 2, 0, 1, SKIP};
    InterpTable T = blocks_table(&BL);
    InterpCore c; interp_begin(&c, &T, BP, 1, 0);
    uint32_t t = 0;
    respond(c, right_answer(c), t);                       // block 0: the outcome lasted 10
    assert(c.table == &T && c.state == 2);
    interp_step(&c, edges(right_answer(c), 0), ++t);
    assert(c.duration == 50);
    assert(interp_step(&c, NOTHING, t + 49).entered[0] == NO);
    assert(interp_step(&c, NOTHING, t + 50).entered[0] == 0); }

  // The error set is compiled: a trial marked a class outside it never repeats.
  // A correct withhold (withheld, class 5) is no error; a wrong response is.
  { static const InterpBlock R[] = {
      {0, 2, INTERP_UNIFORM, NO, NO, NO, NO, NO, B2, NO, ERR}};
    static const InterpBlocks BL = {R, NULL, NULL, 1, 0, 0, SKIP};
    InterpTable T = {timeout_class(5), BLOCK_EDGES, NULL, &BL};
    InterpCore c; interp_begin(&c, &T, BP, 3, 0);
    uint32_t t = 0;
    InterpActions a = time_out(c, t);
    assert(!(a.flags & INTERP_ACT_CORRECTION));
    a = respond(c, wrong_answer(c), t);
    assert(a.flags & INTERP_ACT_CORRECTION); }
  // A block's own set: here only the timeout's class repeats.
  { static const InterpBlock R[] = {
      {0, 2, INTERP_UNIFORM, NO, NO, NO, NO, NO, B2, NO, CLASS_BIT(5)}};
    static const InterpBlocks BL = {R, NULL, NULL, 1, 0, 0, SKIP};
    InterpTable T = {timeout_class(5), BLOCK_EDGES, NULL, &BL};
    InterpCore c; interp_begin(&c, &T, BP, 3, 0);
    uint32_t t = 0;
    assert(!(respond(c, wrong_answer(c), t).flags & INTERP_ACT_CORRECTION));
    assert(time_out(c, t).flags & INTERP_ACT_CORRECTION); }

  // A criterion's window passes over aborts (SKIP); they still count toward N.
  // 2 of the last 3: C, abort, abort, C ends it, the aborts not being among the 3.
  { static const InterpBlock R[] = {
      {0, 2, INTERP_UNIFORM, NO, NO, B2, B3, NO, NO, 1, ERR},
      {2, 1, INTERP_UNIFORM, NO, NO, NO, NO, NO, NO, NO, ERR}};
    static const InterpBlocks BL = {R, NULL, NULL, 2, 0, 0, SKIP};
    InterpTable T = {timeout_class(7), BLOCK_EDGES, NULL, &BL};
    InterpCore c; interp_begin(&c, &T, BP, 9, 0);
    uint32_t t = 0;
    InterpActions a = respond(c, right_answer(c), t);
    a = time_out(c, t);
    a = time_out(c, t);
    assert(a.block == 0);
    a = respond(c, right_answer(c), t);
    assert(a.block == 1 && (a.flags & INTERP_ACT_BLOCK_START));
    // Unskipped, the aborts fill the window: C, abort, abort, C is 1 of the last 3.
    static const InterpBlocks NOSKIP = {R, NULL, NULL, 2, 0, 0, 0};
    InterpTable U = {timeout_class(7), BLOCK_EDGES, NULL, &NOSKIP};
    InterpCore d; interp_begin(&d, &U, BP, 9, 0);
    t = 0;
    respond(d, right_answer(d), t);
    time_out(d, t);
    time_out(d, t);
    assert(respond(d, right_answer(d), t).block == 0);
    // And N counts every trial, aborts included.
    static const InterpBlock RN[] = {
      {0, 2, INTERP_UNIFORM, B3, B3, NO, NO, NO, NO, NO, ERR}};
    static const InterpBlocks BN = {RN, NULL, NULL, 1, 0, 0, SKIP};
    InterpTable V = {timeout_class(7), BLOCK_EDGES, NULL, &BN};
    InterpCore e; interp_begin(&e, &V, BP, 9, 0);
    t = 0;
    time_out(e, t);
    time_out(e, t);
    assert(time_out(e, t).flags & INTERP_ACT_DONE); }
}

int main() {

  // --- interp_random: avr-libc's random(), bit for bit ---
  // Park and Miller's own check: from a seed of 1, the 10000th value of the
  // minimal standard generator is 1043618065 ("Random number generators: good
  // ones are hard to find", CACM 31(10), 1988). Its first value is 16807.
  { uint32_t ctx = 1;
    assert(interp_random(&ctx) == 16807UL);
    uint32_t v = 16807UL;
    for (int i = 1; i < 10000; ++i) v = interp_random(&ctx);
    assert(v == 1043618065UL); }

  // The first five values from seeds that exercise avr-libc's quirks: 0 is read
  // as 123459876, and a state at or above 2^31 - 1 as a negative long.
  // test_analytics_replay.py's CAPTURED_FROM_C pins the Python port to these
  // same literals; change one, change both.
  { static const uint32_t seeds[] = {1UL, 0UL, 123456789UL, 2147483646UL, 2147483647UL,
                                     0x80000000UL, 0xFFFFFFFFUL};
    static const uint32_t first5[][5] = {
      {16807UL, 282475249UL, 1622650073UL, 984943658UL, 1144108930UL},
      {520932930UL, 28925691UL, 822784415UL, 890459872UL, 145532761UL},
      {469049721UL, 2053676357UL, 1781357515UL, 1206231778UL, 891865166UL},
      {2147466840UL, 1865008398UL, 524833574UL, 1162539989UL, 1003374717UL},
      {0UL, 520932930UL, 28925691UL, 822784415UL, 890459872UL},
      {2147466840UL, 1865008398UL, 524833574UL, 1162539989UL, 1003374717UL},
      {2147466840UL, 1865008398UL, 524833574UL, 1162539989UL, 1003374717UL},
    };
    for (int s = 0; s < 7; ++s) {
      uint32_t ctx = seeds[s];
      for (int i = 0; i < 5; ++i) assert(interp_random(&ctx) == first5[s][i]);
    } }
  { uint32_t ctx = 42;                                   // CAPTURED draws, seed 42
    assert(interp_draw(&ctx, 1000) == 894UL && interp_draw(&ctx, 7) == 2UL
           && interp_draw(&ctx, 2) == 1UL && interp_draw(&ctx, 3) == 2UL); }

  // --- interp_draw: random() % n over an unsigned n; n == 0 draws nothing ---
  { uint32_t ctx = 1;
    assert(interp_draw(&ctx, 1000) == 807UL);          // 16807 % 1000
    assert(interp_draw(&ctx, 0) == 0 && ctx == 16807UL); }

  // --- interp_begin: the session starts in state 0, outputs from all-off ---
  { InterpCore c; InterpActions a = interp_begin(&c, &TRIAL, PARAMS, 1, 0);
    assert(a.flags == (INTERP_ACT_SESSION_START | INTERP_ACT_TRIAL_START));
    assert(a.entered[0] == 0 && a.entered[1] == NO);
    assert(a.on == BIT(LIGHT) && a.off == 0 && a.rose == 0 && a.fell == 0); }

  // --- a timer runs out on the tick that is exactly its duration after entry ---
  { InterpCore c; interp_begin(&c, &TRIAL, PARAMS, 1, 0);
    for (uint32_t t = 1; t < 100; ++t) assert(idle(interp_step(&c, NOTHING, t)));
    InterpActions a = interp_step(&c, NOTHING, 100);
    assert(a.entered[0] == 3 && a.entered[1] == NO && a.flags == 0);
    assert(a.off == BIT(LIGHT) && a.on == 0);
    a = interp_step(&c, NOTHING, 200);                  // the ITI loops back
    assert(a.entered[0] == 0 && a.flags == INTERP_ACT_TRIAL_START && a.on == BIT(LIGHT)); }

  // --- an input edge beats a timer in the same tick ---
  { InterpCore c; interp_begin(&c, &TRIAL, PARAMS, 1, 0);
    InterpActions a = interp_step(&c, edges(BIT(PORT), 0), 100);
    assert(a.entered[0] == 1 && a.rose == BIT(PORT));
    assert(a.on == BIT(ODOR) && a.off == 0); }        // the light stays on: no edge

  // --- edges: only watched ones are reported; a watched edge with no exit moves nothing ---
  { InterpCore c; interp_begin(&c, &TRIAL, PARAMS, 1, 0);
    InterpActions a = interp_step(&c, edges(BIT(LEFT), 0), 5);   // LEFT unwatched in Wait
    assert(idle(a));
    a = interp_step(&c, edges(0, BIT(PORT)), 6);                  // PORT fall: watched, no exit
    assert(a.fell == BIT(PORT) && a.rose == 0 && a.entered[0] == NO && a.on == 0 && a.off == 0);
    a = interp_step(&c, edges(BIT(PORT), 0), 7);
    assert(a.entered[0] == 1);
    a = interp_step(&c, edges(0, BIT(PORT)), 8);                  // hold lost: a fall exit
    assert(a.fell == BIT(PORT) && a.entered[0] == 3 && a.off == (BIT(LIGHT) | BIT(ODOR))); }

  // --- two watched edges with exits in one tick: a draw from the session RNG ---
  // From seed 1 the first value is 16807, odd, so a draw over the two
  // candidates picks the second in table order: RIGHT (-> 3), not LEFT (-> 2).
  { InterpCore c; interp_begin(&c, &TRIAL, PARAMS, 1, 0);
    interp_step(&c, edges(BIT(PORT), 0), 1);
    InterpActions a = interp_step(&c, edges(BIT(LEFT) | BIT(RIGHT), 0), 2);
    assert(a.rose == (BIT(LEFT) | BIT(RIGHT)));
    assert(a.entered[0] == 3); }
  // ... and over many seeds each side wins some, the same way every time.
  { int left = 0, right = 0;
    for (uint32_t seed = 1; seed <= 200; ++seed) {
      uint8_t first = NO;
      for (int run = 0; run < 2; ++run) {
        InterpCore c; interp_begin(&c, &TRIAL, PARAMS, seed, 0);
        interp_step(&c, edges(BIT(PORT), 0), 1);
        uint8_t got = interp_step(&c, edges(BIT(LEFT) | BIT(RIGHT), 0), 2).entered[0];
        if (run == 0) first = got; else assert(got == first);
      }
      (first == 2 ? left : right)++;
    }
    assert(left > 50 && right > 50); }
  // A single edge with an exit draws nothing.
  { InterpCore c; interp_begin(&c, &TRIAL, PARAMS, 1, 0);
    interp_step(&c, edges(BIT(PORT), 0), 1);
    uint32_t before = c.rng;
    interp_step(&c, edges(BIT(LEFT), 0), 2);
    assert(c.rng == before); }

  // --- an idle tick changes nothing, so a replay may skip it ---
  { InterpCore c; interp_begin(&c, &TRIAL, PARAMS, 7, 0);
    InterpCore before = c;
    for (uint32_t t = 1; t < 100; ++t) interp_step(&c, edges(BIT(RIGHT), 0), t);
    assert(c.rng == before.rng && c.state == before.state && c.entered_at == before.entered_at
           && c.duration == before.duration && c.outputs == before.outputs); }

  // --- a chance state: draw(1000) < p takes on_hit, else on_miss, in the same tick ---
  { static const InterpStateRow S[] = {
      {BIT(LIGHT), 0, P_10, P_10, 1,  NO,       NO, NO, 0, 0, 0, 0},
      {0,          0, NO,   NO,   NO, P_ALWAYS, 2,  3,  0, 0, 0, 1},   // p = 1000: always
      {BIT(FLUID), 0, NO,   NO,   NO, NO,       NO, NO, 0, 0, 0, 0},
      {0,          0, NO,   NO,   NO, NO,       NO, NO, 0, 0, 0, 0},
    };
    static const InterpTable T = {S, TRIAL_EDGES, NULL, NULL};
    InterpCore c; interp_begin(&c, &T, PARAMS, 1, 0);
    InterpActions a = interp_step(&c, NOTHING, 10);
    assert(a.entered[0] == 1 && a.entered[1] == 2);
    assert(a.on == BIT(FLUID) && a.off == BIT(LIGHT));   // diffed against the resting state
    assert(c.state == 2); }
  { static const InterpStateRow S[] = {
      {0, 0, NO, NO, NO, P_NEVER, 1,  2,  0, 0, 0, 0},                 // p = 0: never
      {0, 0, NO, NO, NO, NO,      NO, NO, 0, 0, 0, 0},
      {0, 0, NO, NO, NO, NO,      NO, NO, 0, 0, 0, 0},
    };
    static const InterpTable T = {S, TRIAL_EDGES, NULL, NULL};
    InterpCore c; InterpActions a = interp_begin(&c, &T, PARAMS, 1, 0);
    assert(a.entered[0] == 0 && a.entered[1] == 2); }

  // --- a drawn duration: uniform over [min, max], drawn at entry ---
  { static const InterpStateRow S[] = {
      {0, 0, P_10, P_12, 1,  NO, NO, NO, 0, 0, 0, 0},
      {0, 0, NO,   NO,   NO, NO, NO, NO, 0, 0, 0, 0},
    };
    static const InterpTable T = {S, TRIAL_EDGES, NULL, NULL};
    int seen[3] = {0, 0, 0};
    for (uint32_t seed = 1; seed <= 100; ++seed) {
      InterpCore c; interp_begin(&c, &T, PARAMS, seed, 0);
      uint32_t t = 1;
      while (interp_step(&c, NOTHING, t).entered[0] == NO) ++t;
      assert(t >= 10 && t <= 12);
      seen[t - 10]++;
    }
    assert(seen[0] && seen[1] && seen[2]); }

  // --- a state lasts at least one tick, even with a zero duration ---
  { static const InterpStateRow S[] = {
      {0, 0, P_0, P_0, 1, NO, NO, NO, 0, 0, 0, 0},
      {0, 0, P_0, P_0, 0, NO, NO, NO, 0, 0, 0, 0},
    };
    static const InterpTable T = {S, TRIAL_EDGES, NULL, NULL};
    InterpCore c; interp_begin(&c, &T, PARAMS, 1, 0);
    assert(interp_step(&c, NOTHING, 1).entered[0] == 1);
    assert(interp_step(&c, NOTHING, 2).entered[0] == 0); }

  // --- millis() wraps after 49.7 days; a timer runs straight across it ---
  { InterpCore c; interp_begin(&c, &TRIAL, PARAMS, 1, 0xFFFFFFF0UL);
    assert(idle(interp_step(&c, NOTHING, 0x53UL)));
    assert(interp_step(&c, NOTHING, 0x54UL).entered[0] == 3); }   // 0xFFFFFFF0 + 100

  // --- a pick state (INTERP 3): draw(edge_count) picks a branch, in the same tick ---
  // Its edge rows (input 0, edge 0) are its branches. From seed 1 the first
  // value is 16807, odd: the second branch. From seed 42 it ends in 894, even:
  // the first. test_analytics_replay.py pins the Python port to the same.
  { static const InterpEdgeRow E[] = {{0, 0, 1}, {0, 0, 2}};
    static const InterpStateRow S[] = {
      {0,          0, NO,    NO,    NO, NO, NO, NO, 0, 2, INTERP_STARTS_TRIAL | INTERP_PICK, 0},
      {BIT(LIGHT), 0, P_100, P_100, 0,  NO, NO, NO, 0, 0, 0, 0},
      {BIT(ODOR),  0, P_100, P_100, 0,  NO, NO, NO, 0, 0, 0, 0},
    };
    static const InterpTable T = {S, E, NULL, NULL};
    InterpCore c; InterpActions a = interp_begin(&c, &T, PARAMS, 1, 0);
    assert(a.entered[0] == 0 && a.entered[1] == 2 && c.state == 2);
    assert(a.flags == (INTERP_ACT_SESSION_START | INTERP_ACT_TRIAL_START) && a.on == BIT(ODOR));
    a = interp_begin(&c, &T, PARAMS, 42, 0);
    assert(a.entered[1] == 1 && a.on == BIT(LIGHT));
    // Entered again from a timer, it draws again; every entry is one draw.
    uint32_t ctx = c.rng;
    uint8_t want = (uint8_t)(interp_draw(&ctx, 2) + 1);
    a = interp_step(&c, NOTHING, 100);
    assert(a.entered[0] == 0 && a.entered[1] == want && a.flags == INTERP_ACT_TRIAL_START && c.rng == ctx); }

  // --- a counter state (INTERP 4): it exits on the N-th rise of its input ---
  //   0 Counter  light on, watch LEFT; the N-th LEFT rise -> 1; times out after 100 -> 2
  //   1 Reward   fluid for 10 -> 0
  //   2 End      after 10 -> 0, the session's last trial
  // N is the table's counter: params[P_COUNT] (FR), drawn from
  // [params[P_COUNT], params[P_COUNT_MAX]] (VR), or the next ratio (PR).
  { enum { P_COUNT = 6, P_COUNT_MAX = 7 };
    static const uint32_t CP[] = {100, 0, 10, 12, 1000, 0, 3, 9};
    static const InterpEdgeRow E[] = {{LEFT, INTERP_RISE, 1}};
    static const InterpStateRow S[] = {
      {BIT(LIGHT), BIT(LEFT), P_100, P_100, 2,  NO, NO, NO, 0, 1, INTERP_STARTS_TRIAL | INTERP_COUNT, 0},
      {BIT(FLUID), 0,         P_10,  P_10,  0,  NO, NO, NO, 0, 0, 0, 1},
      {0,          0,         P_10,  P_10,  0,  NO, NO, NO, 0, 0, INTERP_LAST_TRIAL, 4},
    };
    static const InterpCounter FR = {NULL, 0, P_COUNT, P_COUNT};
    static const InterpTable T_FR = {S, E, &FR, NULL};

    // FR-3: the first two rises are counted and move nothing; the third exits.
    { InterpCore c; interp_begin(&c, &T_FR, CP, 1, 0);
      InterpActions a = interp_step(&c, edges(BIT(LEFT), 0), 5);
      assert(a.rose == BIT(LEFT) && a.entered[0] == NO && a.on == 0);
      assert(interp_step(&c, edges(BIT(LEFT), 0), 6).entered[0] == NO);
      a = interp_step(&c, edges(BIT(LEFT), 0), 7);
      assert(a.entered[0] == 1 && a.on == BIT(FLUID) && a.off == BIT(LIGHT));
      // Entered again, the count starts over.
      assert(interp_step(&c, NOTHING, 17).entered[0] == 0);
      assert(interp_step(&c, edges(BIT(LEFT), 0), 18).entered[0] == NO); }

    // A counted rise below N does not hold the timer off; the N-th beats it.
    { InterpCore c; interp_begin(&c, &T_FR, CP, 1, 0);
      interp_step(&c, edges(BIT(LEFT), 0), 1);
      InterpActions a = interp_step(&c, edges(BIT(LEFT), 0), 100);
      assert(a.rose == BIT(LEFT) && a.entered[0] == 2); }
    { InterpCore c; interp_begin(&c, &T_FR, CP, 1, 0);
      interp_step(&c, edges(BIT(LEFT), 0), 1);
      interp_step(&c, edges(BIT(LEFT), 0), 2);
      assert(interp_step(&c, edges(BIT(LEFT), 0), 100).entered[0] == 1); }

    // Counting draws nothing.
    { InterpCore c; interp_begin(&c, &T_FR, CP, 1, 0);
      uint32_t before = c.rng;
      interp_step(&c, edges(BIT(LEFT), 0), 1);
      interp_step(&c, edges(BIT(LEFT), 0), 2);
      interp_step(&c, edges(BIT(LEFT), 0), 3);
      assert(c.rng == before); }

    // Entering a last-trial state reports it; the session layer ends at the next trial start.
    { InterpCore c; interp_begin(&c, &T_FR, CP, 1, 0);
      InterpActions a = interp_step(&c, NOTHING, 100);
      assert(a.entered[0] == 2 && a.flags == INTERP_ACT_LAST_TRIAL);
      a = interp_step(&c, NOTHING, 110);
      assert(a.entered[0] == 0 && a.flags == INTERP_ACT_TRIAL_START); }

    // VR: N drawn uniformly from [3, 9] at each entry, before the state's own
    // timer, from the session RNG, so the same seed draws the same N.
    { static const InterpCounter VR = {NULL, 0, P_COUNT, P_COUNT_MAX};
      static const InterpTable T_VR = {S, E, &VR, NULL};
      int seen[10] = {0};
      // Seeds past 2^31 / 16807: below that, a first draw is a multiple of 7.
      for (uint32_t seed = 1000003; seed <= 1000003 + 200 * 104729UL; seed += 104729UL) {
        InterpCore c; interp_begin(&c, &T_VR, CP, seed, 0);
        uint32_t ctx = seed;
        uint32_t want = 3 + interp_draw(&ctx, 7);
        assert(c.rng == ctx);                            // one draw at entry: N's
        uint32_t presses = 0;
        InterpActions a;
        do a = interp_step(&c, edges(BIT(LEFT), 0), ++presses); while (a.entered[0] == NO);
        assert(a.entered[0] == 1 && presses == want);
        seen[presses]++;
      }
      for (int n = 3; n <= 9; ++n) assert(seen[n] > 0); }

    // PR: N is the k-th ratio at the k-th completion, and the last repeats.
    { static const uint16_t RATIOS[] = {1, 2, 4};
      static const InterpCounter PR = {RATIOS, 3, NO, NO};
      static const InterpTable T_PR = {S, E, &PR, NULL};
      InterpCore c; interp_begin(&c, &T_PR, CP, 1, 0);
      static const uint32_t want[] = {1, 2, 4, 4, 4};
      uint32_t t = 0;
      for (int k = 0; k < 5; ++k) {
        uint32_t presses = 0;
        InterpActions a;
        do { ++presses; a = interp_step(&c, edges(BIT(LEFT), 0), ++t); } while (a.entered[0] == NO);
        assert(a.entered[0] == 1 && presses == want[k]);
        t += 10;
        assert(interp_step(&c, NOTHING, t).entered[0] == 0);
      }
      // A limit that runs out is no completion: the step stays.
      InterpCore d; interp_begin(&d, &T_PR, CP, 1, 0);
      assert(interp_step(&d, NOTHING, 100).entered[0] == 2);
      assert(interp_step(&d, NOTHING, 110).entered[0] == 0);
      assert(interp_step(&d, edges(BIT(LEFT), 0), 111).entered[0] == 1); } }

  test_blocks();

  std::printf("test_interp: all passed\n");
  return 0;
}

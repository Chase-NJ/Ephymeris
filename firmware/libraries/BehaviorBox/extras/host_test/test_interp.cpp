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
static const InterpTable TRIAL = {TRIAL_STATES, TRIAL_EDGES};

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

  // --- interp_draw: Arduino's random(n), random() % n; n == 0 draws nothing ---
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
    static const InterpTable T = {S, TRIAL_EDGES};
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
    static const InterpTable T = {S, TRIAL_EDGES};
    InterpCore c; InterpActions a = interp_begin(&c, &T, PARAMS, 1, 0);
    assert(a.entered[0] == 0 && a.entered[1] == 2); }

  // --- a drawn duration: uniform over [min, max], drawn at entry ---
  { static const InterpStateRow S[] = {
      {0, 0, P_10, P_12, 1,  NO, NO, NO, 0, 0, 0, 0},
      {0, 0, NO,   NO,   NO, NO, NO, NO, 0, 0, 0, 0},
    };
    static const InterpTable T = {S, TRIAL_EDGES};
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
    static const InterpTable T = {S, TRIAL_EDGES};
    InterpCore c; interp_begin(&c, &T, PARAMS, 1, 0);
    assert(interp_step(&c, NOTHING, 1).entered[0] == 1);
    assert(interp_step(&c, NOTHING, 2).entered[0] == 0); }

  // --- millis() wraps after 49.7 days; a timer runs straight across it ---
  { InterpCore c; interp_begin(&c, &TRIAL, PARAMS, 1, 0xFFFFFFF0UL);
    assert(idle(interp_step(&c, NOTHING, 0x53UL)));
    assert(interp_step(&c, NOTHING, 0x54UL).entered[0] == 3); }   // 0xFFFFFFF0 + 100

  std::printf("test_interp: all passed\n");
  return 0;
}

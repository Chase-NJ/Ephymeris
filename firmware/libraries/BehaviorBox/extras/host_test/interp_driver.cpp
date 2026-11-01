/*  The C half of the differential test (run_diff.sh, differential.py).

    Reads cases from stdin and runs each through BoxInterp.h exactly as a board
    would: interp_begin() at the first tick, then interp_step() on EVERY tick
    after it, edges or not. Prints every tick that did something.

    In, whitespace-separated, per case:
      CASE n_states n_edges n_params seed start ticks n_events
      n_states x  outputs watch timer_min timer_max on_timeout chance on_hit
                  on_miss edge_first edge_count flags outcome
      n_edges  x  input edge next
      n_params x  value
      n_events x  offset rose fell        (offset: ticks after start, increasing)
    Out: "INTERP <version>" once, then per case
      CASE
      now rose fell on off entered0 entered1 flags     (one line per non-idle tick)
      END

    A pulse train instead (BoxInterp.h, PULSE TRAINS), stepped as the board
    steps one, on every tick from its first, and stopped at `length`:
      In:  TRAIN hz width length
      Out: TRAIN
           tick level      (one line per edge; the pin is LOW before tick 0
                            and goes LOW at `length` if it is HIGH)
           END
*/
#include <cinttypes>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "BoxInterp.h"

static uint32_t num()
{
  unsigned long long v;
  if (std::scanf("%llu", &v) != 1) { std::fprintf(stderr, "interp_driver: bad input\n"); std::exit(2); }
  return (uint32_t)v;
}

static uint8_t byte() { return (uint8_t)num(); }

static void print(uint32_t now, const InterpActions &a)
{
  std::printf("%" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %u %u %u\n", now,
              a.rose, a.fell, a.on, a.off, a.entered[0], a.entered[1], a.flags);
}

int main()
{
  std::printf("INTERP %d\n", INTERP_VERSION);
  char word[16];
  while (std::scanf("%15s", word) == 1) {
    if (std::strcmp(word, "TRAIN") == 0) {
      uint32_t hz = num(), width = num(), length = num();
      std::printf("TRAIN\n");
      bool high = false;
      for (uint32_t t = 0; t < length; ++t) {
        bool level = interp_train_high(t, hz, width);
        if (level != high) std::printf("%" PRIu32 " %d\n", t, level ? 1 : 0);
        high = level;
      }
      if (high) std::printf("%" PRIu32 " 0\n", length);
      std::printf("END\n");
      continue;
    }
    if (std::strcmp(word, "CASE") != 0) { std::fprintf(stderr, "interp_driver: expected CASE\n"); return 2; }
    uint32_t n_states = num(), n_edges = num(), n_params = num();
    uint32_t seed = num(), start = num(), ticks = num(), n_events = num();
    std::vector<InterpStateRow> states(n_states);
    for (InterpStateRow &s : states) {
      s.outputs = num(); s.watch = num();
      s.timer_min = byte(); s.timer_max = byte(); s.on_timeout = byte();
      s.chance = byte(); s.on_hit = byte(); s.on_miss = byte();
      s.edge_first = byte(); s.edge_count = byte(); s.flags = byte(); s.outcome = byte();
    }
    std::vector<InterpEdgeRow> edges(n_edges + 1);   // +1: never an empty vector's data()
    for (uint32_t i = 0; i < n_edges; ++i) {
      edges[i].input = byte(); edges[i].edge = byte(); edges[i].next = byte();
    }
    std::vector<uint32_t> params(n_params + 1);
    for (uint32_t i = 0; i < n_params; ++i) params[i] = num();
    std::vector<uint32_t> at(n_events), rose(n_events), fell(n_events);
    for (uint32_t i = 0; i < n_events; ++i) { at[i] = num(); rose[i] = num(); fell[i] = num(); }

    InterpTable table = {states.data(), edges.data()};
    InterpCore core;
    std::printf("CASE\n");
    print(start, interp_begin(&core, &table, params.data(), seed, start));
    uint32_t next = 0;
    for (uint32_t offset = 1; offset <= ticks; ++offset) {
      InterpEdges in = {0, 0};
      if (next < n_events && at[next] == offset) { in.rose = rose[next]; in.fell = fell[next]; ++next; }
      uint32_t now = start + offset;
      InterpActions a = interp_step(&core, in, now);
      if (!interp_idle(&a)) print(now, a);
    }
    std::printf("END\n");
  }
  return 0;
}

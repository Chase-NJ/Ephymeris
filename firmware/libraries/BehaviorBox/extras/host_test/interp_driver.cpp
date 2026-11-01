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
      has_counter count_min count_max n_ratios   then n_ratios x ratio
      n_blocks n_entries n_overrides skipped     (0 0 0 0: no blocks), then
        n_blocks x first count select n_min n_max k n window correct next errors
        n_entries x side weight;  n_overrides x block slot with
      n_events x  offset rose fell        (offset: ticks after start, increasing)
    Out: "INTERP <version>" once, then per case
      CASE
      now rose fell on off entered0 entered1 flags block   (one line per non-idle tick)
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
  std::printf("%" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %" PRIu32 " %u %u %u %u\n", now,
              a.rose, a.fell, a.on, a.off, a.entered[0], a.entered[1], a.flags, a.block);
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
    InterpCounter counter;
    uint32_t has_counter = num();
    counter.count_min = byte(); counter.count_max = byte(); counter.ratio_count = byte();
    std::vector<uint16_t> ratios(counter.ratio_count + 1u);
    for (uint32_t i = 0; i < counter.ratio_count; ++i) ratios[i] = (uint16_t)num();
    counter.ratios = ratios.data();
    uint32_t n_blocks = num(), n_entries = num(), n_overrides = num(), skipped = num();
    std::vector<InterpBlock> block_rows(n_blocks + 1);
    for (uint32_t i = 0; i < n_blocks; ++i) {
      InterpBlock &b = block_rows[i];
      b.first = byte(); b.count = byte(); b.select = byte(); b.n_min = byte(); b.n_max = byte();
      b.k = byte(); b.n = byte(); b.window = byte(); b.correct = byte(); b.next = byte();
      b.errors = (uint16_t)num();
    }
    std::vector<InterpEntry> entries(n_entries + 1);
    for (uint32_t i = 0; i < n_entries; ++i) { entries[i].side = byte(); entries[i].weight = byte(); }
    std::vector<InterpOverride> overrides(n_overrides + 1);
    for (uint32_t i = 0; i < n_overrides; ++i) {
      overrides[i].block = byte(); overrides[i].slot = byte(); overrides[i].with = byte();
    }
    InterpBlocks blocks = {block_rows.data(), n_entries ? entries.data() : NULL,
                           n_overrides ? overrides.data() : NULL,
                           (uint8_t)n_blocks, (uint8_t)n_entries, (uint8_t)n_overrides,
                           (uint16_t)skipped};
    std::vector<uint32_t> at(n_events), rose(n_events), fell(n_events);
    for (uint32_t i = 0; i < n_events; ++i) { at[i] = num(); rose[i] = num(); fell[i] = num(); }

    InterpTable table = {states.data(), edges.data(), has_counter ? &counter : NULL, n_blocks ? &blocks : NULL};
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

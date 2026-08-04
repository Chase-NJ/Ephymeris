/*  Off-target layout check for TaskTable.h.
 *
 *  Runs today, unlike the interpreter tests it will eventually sit beside: the
 *  header depends only on <stdint.h>, so this needs no Arduino shim and no board.
 *
 *  What it is for: the RAM budget in docs/spikes/avr-ram.md is only valid while
 *  the records stay the size they were measured at. A field added to TgNode
 *  costs 64 bytes at the enforced limit and nobody would notice from the sketch.
 *  Worse, a layout that differs between the host build and the AVR build would
 *  corrupt every uploaded table while compiling cleanly on both. These assertions
 *  fail the build instead.
 *
 *  Usage:  sh run.sh
 */

#include <cstdio>
#include <cstring>

#include "TaskTable.h"
#include "TgLayoutAssert.h"  // generated: sizes AND field offsets, both toolchains

static int failures = 0;

static void check(bool cond, const char *what)
{
  if (cond)
  {
    std::printf("  ok    %s\n", what);
  }
  else
  {
    std::printf("  FAIL  %s\n", what);
    failures++;
  }
}

static void checkSize(const char *name, size_t actual, size_t expected)
{
  char buf[128];
  std::snprintf(buf, sizeof(buf), "sizeof(%s) == %zu (got %zu)", name, expected, actual);
  check(actual == expected, buf);
}

int main()
{
  std::printf("TgTable record layout\n");

  /* The sizes the AVR probe measured. Zero padding in all eight sweep
     configurations -- if that stops being true the budget is wrong. */
  checkSize("TgNode", sizeof(TgNode), 8);
  checkSize("TgEdge", sizeof(TgEdge), 4);
  checkSize("TgAction", sizeof(TgAction), 2);
  checkSize("TgTrialType", sizeof(TgTrialType), 8);
  checkSize("TgStageRow", sizeof(TgStageRow), 4);
  /* The record that proved the hazard: 3 bytes on AVR and 4 on the host until an
     explicit pad byte was added. Reordering the fields does not fix it. */
  checkSize("TgTimingSet", sizeof(TgTimingSet), 4);

  std::printf("\nStrobe width\n");
  /* Five real codes exceed a byte: WATER_POKE_NONE 256, WATER_POKE_ERROR_L/R
     257/258, STOP_FLUID_G_R 357, STOP_FLUID_G_L 369. A uint8 strobe field would
     truncate all five, silently. */
  check(sizeof(((TgNode *)nullptr)->strobe) == 2, "TgNode::strobe is 16-bit");
  {
    TgNode n{};
    n.strobe = 369; // STOP_FLUID_G_L, the highest code in the vocabulary
    check(n.strobe == 369, "strobe holds 369 without truncation");
    n.strobe = 999; // the wire-format ceiling: emitStrobe uses %03d
    check(n.strobe == 999, "strobe holds the 999 wire ceiling");
  }

  std::printf("\nSentinels are out of band\n");
  /* Firmware's StageStep uses 32767 as "never" while lazyDelayMax legitimately
     reaches 30000 -- a legal value one step from a magic one. Not reproduced. */
  check(TG_NO_STROBE == 0xFFFF, "TG_NO_STROBE is 0xFFFF, above the 999 code ceiling");
  check(TG_NO_TARGET == 0xFF, "TG_NO_TARGET is 0xFF");
  check(TG_NO_NODE == 0xFF, "TG_NO_NODE is 0xFF");

  std::printf("\nDurations are indices, never literals\n");
  /* The whole shaping-ramp story depends on this: a node names a timing SLOT, so
     rewriting the vector retimes the task without touching the graph. A uint8
     index also caps the timing vector at 255, comfortably above TG_MAX_TIMING. */
  check(sizeof(((TgNode *)nullptr)->durIdx) == 1, "TgNode::durIdx is a 1-byte index");

  std::printf("\nSix primitives, and only six\n");
  check(TG_DELAY == 0 && TG_WAIT_ENTRY == 1 && TG_HOLD == 2 &&
            TG_WAIT_EXIT == 3 && TG_PULSE == 4 && TG_TERMINAL == 5,
        "node type ordinals are stable (they go on the wire)");

  std::printf("\n%s\n", failures == 0 ? "PASS" : "FAIL");
  return failures == 0 ? 0 : 1;
}

/*  GATE D — the actuators, not the strobes.
 *
 *  THE ROADMAP NAMES THIS GAP IN SO MANY WORDS: "the equivalence gate proved the
 *  strobe stream; it did not prove actuator timing, and reward volume is a
 *  solenoid open-time."
 *
 *  Gates A, B and C all compare `mock.emitted` -- what the box SAID. A box can say
 *  exactly the right thing while opening the wrong valve, holding it open for the
 *  wrong duration, or leaving the vacuum closed. None of those emit a strobe, and
 *  the odor lines and the vacuum emit none at all, so on those channels the
 *  earlier gates were not weak evidence -- they were no evidence.
 *
 *  ------------------------------------------------------------------------
 *  IT COMPARES WAVEFORMS, NOT WRITES, AND THE FIRST RUN IS WHY
 *
 *  Comparing the digitalWrite log verbatim reported 1729 differences in 2000
 *  trials, every one of them the same thing: on an abort the model clears ALL
 *  emitters and the vacuum unconditionally ("clear whatever is on"), where
 *  runTrial() clears only the line it happened to raise. Those extra calls drive
 *  pins that are already LOW. At the pad they are nothing.
 *
 *  A write log is an implementation detail. What the hardware sees -- and what a
 *  scope would show, which is the whole point of Phase 5 -- is the sequence of
 *  LEVEL TRANSITIONS per pin. So that is what is compared: writes that do not
 *  change a level are not events.
 *
 *  The model's redundant clears are also the safer behaviour, since an abort path
 *  that clears whatever is on cannot leave a valve open, and that is worth keeping
 *  rather than making the two implementations match write-for-write.
 *
 *  ------------------------------------------------------------------------
 *  WHY TIME AND NOT JUST ORDER
 *
 *  Pulse width IS the delivered reward volume. A solenoid opened at the right
 *  moment for 90 ms instead of 100 delivers 10% less water, on the right pin, in
 *  the right order, with an identical strobe stream. Order-only comparison is
 *  blind to the most consequential number in the task.
 *
 *  ------------------------------------------------------------------------
 *  WHAT THIS IS NOT
 *
 *  Not a substitute for a scope. It proves the two implementations produce the
 *  same waveform on the same mock clock; it says nothing about what a real MOSFET
 *  and a real solenoid do with it. That is the bench half of Phase 5 and it needs
 *  hardware. What this removes is the possibility that a bench discrepancy is the
 *  INTERPRETER's fault rather than the rig's.
 */

#include <cstdio>
#include <cstring>
#include <vector>

#include "Arduino.h"

MockBox mock;

#ifndef TG_TABLE_HEADER
#define TG_TABLE_HEADER "grgl_table.h"
#endif
#include TG_TABLE_HEADER

#include "battery.h"

/* GRGL's two trial types, verbatim from GRGL_2-Odor.ino:43-59. */
static const TrialType goRight1(true, Odors[0], rightWell, RIGHT_WELL_FL_1,
                                BF_ODOR_1_ON, BF_FLUID_R, BF_STOP_FLUID_G_R);
static const TrialType goLeft1(true, Odors[2], leftWell, LEFT_WELL_FL_1,
                               BF_ODOR_3_ON, BF_FLUID_L, BF_STOP_FLUID_G_L);
static const TrialType *TRIALS[] = {&goRight1, &goLeft1};

static const char *pinName(int p)
{
  static char b[16];
  if (p == trialLight) return "light";
  if (p == vac) return "vac";
  for (int i = 0; i < NUM_ODORS; i++)
    if (p == Odors[i]) { std::snprintf(b, sizeof(b), "odor%d", i); return b; }
  for (int i = 0; i < NUM_FLUIDS; i++)
    if (p == Fluids[i]) { std::snprintf(b, sizeof(b), "fluid%d", i); return b; }
  std::snprintf(b, sizeof(b), "pin%d", p);
  return b;
}

/*  The waveform: level CHANGES only, in order.
 *
 *  Every pin starts LOW -- initBoxHardware() lands them there and the mock's
 *  write log begins empty -- so a LOW write before any HIGH is not a transition. */
static std::vector<MockWrite> waveform(const std::vector<MockWrite> &w)
{
  std::vector<MockWrite> out;
  for (const auto &e : w)
  {
    int level = LOW;
    for (const auto &prev : out)
      if (prev.pin == e.pin)
        level = prev.value;
    if (e.value != level)
      out.push_back(e);
  }
  return out;
}

/*  Stable-sort each same-timestamp run by pin, so a difference that is only the
    ORDER of simultaneous writes compares equal.
 *
 *  STABILITY IS LOAD-BEARING, and the first version did not have it. A pin can
 *  legitimately appear TWICE in one millisecond -- the vacuum is set on entry to
 *  the sampling hold and cleared by the abort when that hold breaks instantly, so
 *  `vac^@t vacv@t` is a real and harmless zero-length pulse. A selection sort
 *  swaps non-adjacent elements and can therefore reorder those two relative to
 *  each other, turning `^ v` into `v ^` on one side only. That reported five
 *  phantom divergences per 2000 trials, each one a pair the sort itself had
 *  flipped. Insertion sort moves elements past strictly-greater neighbours only,
 *  so equal pins keep their order. */
static std::vector<MockWrite> sortWithinMillisecond(std::vector<MockWrite> w)
{
  for (size_t i = 0; i < w.size();)
  {
    size_t j = i;
    while (j < w.size() && w[j].t == w[i].t)
      j++;
    for (size_t x = i + 1; x < j; x++)
    {
      const MockWrite key = w[x];
      size_t y = x;
      while (y > i && w[y - 1].pin > key.pin)
      {
        w[y] = w[y - 1];
        y--;
      }
      w[y] = key;
    }
    i = j;
  }
  return w;
}

static void dump(const char *label, const std::vector<MockWrite> &w)
{
  std::printf("      %-11s", label);
  for (const auto &e : w)
    std::printf(" %s%s@%lu", pinName(e.pin), e.value ? "^" : "v", e.t);
  std::printf("\n");
}

/*  Where a pin was left. Every pin starts LOW. */
static int lastLevel(const std::vector<MockWrite> &wave, int pin)
{
  int level = LOW;
  for (const auto &e : wave)
    if (e.pin == pin)
      level = e.value;
  return level;
}

/*  Total time each pin spent HIGH. For a reward line this IS the delivered
    volume; for the vacuum it is how long odor reached the animal. */
static unsigned long highTime(const std::vector<MockWrite> &wave, int pin)
{
  unsigned long total = 0, since = 0;
  bool high = false;
  for (const auto &e : wave)
  {
    if (e.pin != pin)
      continue;
    if (e.value && !high) { since = e.t; high = true; }
    else if (!e.value && high) { total += e.t - since; high = false; }
  }
  return total;
}

int main(int argc, char **argv)
{
  const unsigned long seed = (argc > 1) ? std::strtoul(argv[1], 0, 10) : 20260803UL;
  const int nTrials = (argc > 2) ? std::atoi(argv[2]) : 2000;

  Rng rng{seed};
  int checked = 0, diverged = 0, hangs = 0, volume = 0, wrongVolume = 0;
  int sameInstant = 0;
  int leftOpen = 0;

  for (int i = 0; i < nTrials; i++)
  {
    TaskParams p;
    clampTaskParams(p);
    applyStage(p, (int)rng.in(0, 120));
    const Script s = drawScript(rng, p);

    arm(s);
    TrialClock clkA;
    clkA.beginSession();
    bool hungA = false;
    try { runTrial(*TRIALS[s.trial], p, clkA, nullptr, 0); }
    catch (const MockHang &) { hungA = true; }
    const std::vector<MockWrite> a = waveform(mock.writes);

    arm(s);
    TgTable table = TG_TABLE;
    syncTiming(table, p);
    TrialClock clkB;
    clkB.beginSession();
    TgRun r;
    bool hungB = false;
    try { tgRunTrial(table, r, p, clkB, s.trial); }
    catch (const MockHang &) { hungB = true; }
    const std::vector<MockWrite> b = waveform(mock.writes);

    if (hungA || hungB)
    {
      hangs++;
      continue;
    }
    checked++;

    bool same = a.size() == b.size();
    for (size_t k = 0; same && k < a.size(); k++)
      same = a[k].pin == b[k].pin && a[k].value == b[k].value && a[k].t == b[k].t;

    /*  CLASSIFY, do not merely count. The two implementations clear the cue-off
        actuators in a different ORDER within a single millisecond: runTrial()
        writes odor then vac, the model writes vac then odor. Sorting each
        same-timestamp group by pin collapses that difference and nothing else --
        so if the sorted waveforms match, the two produce the same electrical
        result and differ only in the order of two writes microseconds apart,
        which no solenoid can resolve.

        Anything the sort does NOT explain is a real difference in what the
        hardware was told to do, and that is what this gate fails on. */
    if (!same)
    {
      const std::vector<MockWrite> sa = sortWithinMillisecond(a);
      const std::vector<MockWrite> sb = sortWithinMillisecond(b);
      bool ordering = sa.size() == sb.size();
      for (size_t k = 0; ordering && k < sa.size(); k++)
        ordering = sa[k].pin == sb[k].pin && sa[k].value == sb[k].value &&
                   sa[k].t == sb[k].t;
      if (ordering)
        sameInstant++;
      else
      {
        if (diverged < 5)
        {
          std::printf("  DIVERGENCE #%d  trial=%u engage=%lu..%lu resp=%d %lu..%lu\n",
                      diverged + 1, s.trial, s.engageAt, s.engageTo, s.respPin,
                      s.respAt, s.respTo);
          dump("runTrial", a);
          dump("interpreter", b);
        }
        diverged++;
      }
    }

    /*  REWARD VOLUME, against the SPEC rather than against the other
        implementation. Two implementations agreeing on a wrong pulse width would
        satisfy every comparison above, and this is the one number where that
        matters most: it is the single duration resolved per trial rather than
        from the timing vector, which is exactly where Phase 1's one compiler bug
        lived. */
    const uint8_t target = table.trialTypes[s.trial].target;
    if (target < table.nPorts)
    {
      const int line = table.ports[target].rewardLine;
      const unsigned long open = highTime(b, line);
      if (open)
      {
        volume++;
        const uint16_t want = table.timing[table.ports[target].rewardDurIdx];
        if (open != want)
        {
          if (wrongVolume < 3)
            std::printf("  VOLUME  %s open %lu ms, spec says %u ms\n",
                        pinName(line), open, want);
          wrongVolume++;
        }
      }
    }

    /*  NOTHING MAY BE LEFT ENERGISED. A trial that ends with a valve open is a
        flooded well or an odor line venting into an empty box, and no strobe
        anywhere reports it.

        THE TEST IS THE PIN'S LAST LEVEL, not its accumulated high-time. An
        earlier version asked whether highTime was zero, which flags a pin raised
        and cleared within the same millisecond -- a real thing that happens when a
        sampling hold breaks instantly, and entirely harmless. It reported five
        phantom faults per 2000 trials before the distinction was made. */
    for (const auto &e : b)
      if (lastLevel(b, e.pin) == HIGH)
      {
        if (leftOpen < 3)
          std::printf("  LEFT OPEN  %s still high at end of trial\n", pinName(e.pin));
        leftOpen++;
        break;
      }
  }

  std::printf("seed=%lu trials=%d checked=%d diverged=%d hangs=%d\n",
              seed, nTrials, checked, diverged, hangs);
  std::printf("same-instant-reorder=%d\n", sameInstant);
  std::printf("volume: rewards=%d wrong=%d | left-open=%d\n",
              volume, wrongVolume, leftOpen);
  return (diverged == 0 && wrongVolume == 0 && leftOpen == 0) ? 0 : 1;
}

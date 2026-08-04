/*  The watchdog: does it fire when it must, and stay silent when it must not?
 *
 *  Both halves are load-bearing, and the second is the one that is easy to get
 *  wrong. A watchdog that never fires is dead code that reads as safety. A
 *  watchdog that fires on a healthy trial ends real sessions -- which is a worse
 *  outcome than the hang it exists to prevent, because a hang is at least
 *  obviously broken.
 *
 *  Driven by the mock clock, so a 30-second ceiling costs no wall time.
 */

#include <cstdio>
#include <cstring>

#include "Arduino.h"

MockBox mock;

#include "grgl_table.h"

#include "battery.h"

static int failures = 0;

static void check(bool ok, const char *what)
{
  std::printf("%-58s %s\n", what, ok ? "ok" : "FAIL");
  if (!ok)
    failures++;
}

/*  Run one trial, returning the run state. The mock clock's own hang deadline is
    raised well past the watchdog ceiling: the point of these cases is that the
    WATCHDOG stops the trial, and a harness that stopped it first would prove
    nothing. */
static TgRun runTrial(TgTable table, const TaskParams &p, uint8_t trial, bool &hung)
{
  mock.deadline = 3600000UL;
  TrialClock clk;
  clk.beginSession();
  TgRun r;
  hung = false;
  try
  {
    tgRunTrial(table, r, p, clk, trial);
  }
  catch (const MockHang &)
  {
    hung = true;
  }
  return r;
}

int main()
{
  TaskParams p;
  clampTaskParams(p);
  applyStage(p, 0);

  TgTable table = TG_TABLE;
  syncTiming(table, p);

  /*  The engagement window does not open until the arm delay has elapsed, so a
      scripted poke before then is an animal already in the port when the trial
      starts -- which fails the commitment hold and never reaches the state under
      test. Read the delay out of the table rather than assuming it: the first
      version of this file hard-coded 100 ms and quietly tested the abort path. */
  const unsigned long windowOpens = table.timing[TG_IDX_ARM] + 200;

  /* ------------------------------------------------------------------ *
   *  1. It fires.
   *
   *  An animal that pokes the correct well, holds it, takes its reward and
   *  then NEVER LEAVES. That is the consumption WAIT_EXIT, the one state in
   *  the interpreter that can wait forever, and the exact shape of the hang
   *  the shipping firmware has today.
   * ------------------------------------------------------------------ */
  {
    Script s{};
    s.trial = 0;
    s.engageAt = windowOpens;
    s.engageTo = s.engageAt + 2UL * (unsigned long)p.odorPokeHold + 50;
    s.respPin = rightWell;
    s.respAt = s.engageTo + 50;
    s.respTo = 3600000UL; // never releases
    arm(s);

    bool hung = false;
    const TgRun r = runTrial(table, p, s.trial, hung);
    check(!hung, "an animal that never leaves the well does not hang the box");
    check(r.faulted, "  the watchdog reports a fault");
    check(!r.advanced, "  and the trial is NOT scored -- a fault has no outcome");
    check(table.nodes[r.node].type == TG_WAIT_EXIT,
          "  the faulted node is the unbounded wait, not something else");
    check(table.maxDwell[r.node] == 0,
          "  and it is one the compiler declared unboundable");
  }

  /* ------------------------------------------------------------------ *
   *  2. It fires no earlier than it should.
   * ------------------------------------------------------------------ */
  {
    Script s{};
    s.trial = 0;
    s.engageAt = windowOpens;
    s.engageTo = s.engageAt + 2UL * (unsigned long)p.odorPokeHold + 50;
    s.respPin = rightWell;
    s.respAt = s.engageTo + 50;
    s.respTo = 3600000UL;
    arm(s);
    bool hung = false;
    const unsigned long before = mock.now;
    runTrial(table, p, s.trial, hung);
    const unsigned long elapsed = mock.now - before;
    check(elapsed >= TG_WATCHDOG_CEILING_MS,
          "  it waits the full ceiling before giving up");
    check(elapsed < 2UL * TG_WATCHDOG_CEILING_MS,
          "  and gives up promptly once it has");
  }

  /* ------------------------------------------------------------------ *
   *  3. It stays silent on healthy animals -- ACROSS THE WHOLE RAMP.
   *
   *  This is the half that would have failed before taskgraph/lower.py learned
   *  to take the PEAK of each timing entry: shaping_gr's holds are compiled at
   *  10 ms and reach 500 ms by the last stage row, so budgets taken from the
   *  compiled value trip on every trial past stage four.
   * ------------------------------------------------------------------ */
  {
    Rng rng{20260803UL};
    int faults = 0, ran = 0;
    for (int i = 0; i < 4000; i++)
    {
      TaskParams q;
      clampTaskParams(q);
      applyStage(q, (int)rng.in(0, 120));
      const Script s = drawScript(rng, q);
      arm(s);

      TgTable t2 = TG_TABLE;
      syncTiming(t2, q);
      bool hung = false;
      const TgRun r = runTrial(t2, q, s.trial, hung);
      if (hung)
        continue;
      ran++;
      if (r.faulted)
      {
        if (faults < 3)
          std::printf("  FALSE TRIP node=%u engage=%lu..%lu resp=%d %lu..%lu\n",
                      r.node, s.engageAt, s.engageTo, s.respPin, s.respAt, s.respTo);
        faults++;
      }
    }
    std::printf("  %d healthy trials, %d faults\n", ran, faults);
    check(ran > 3900, "  the healthy battery actually ran");
    check(faults == 0, "no healthy trial anywhere on the stage ramp trips it");
  }

  /* ------------------------------------------------------------------ *
   *  4. Safing the hardware clears everything the table can drive.
   * ------------------------------------------------------------------ */
  {
    mock.reset();
    for (uint8_t i = 0; i < TG_TABLE.nStimuli; i++)
      digitalWrite(TG_TABLE.stimuli[i].emitter, HIGH);
    for (uint8_t i = 0; i < TG_TABLE.nPorts; i++)
      if (TG_TABLE.ports[i].rewardLine != TG_NO_TARGET)
        digitalWrite(TG_TABLE.ports[i].rewardLine, HIGH);
    digitalWrite(trialLight, HIGH);
    digitalWrite(vac, HIGH);

    const size_t mark = mock.writes.size();
    tgSafeAllOutputs(TG_TABLE);

    /*  Every pin the table left HIGH must be driven LOW. Replay the whole write
        log to find the final state of each pin -- asserting on the safing calls
        alone would miss a pin the table can turn on and cannot turn off, which
        is the failure that matters. */
    int stillHigh = 0;
    for (size_t i = 0; i < mock.writes.size(); i++)
    {
      const int pin = mock.writes[i].pin;
      int last = LOW;
      for (size_t k = 0; k < mock.writes.size(); k++)
        if (mock.writes[k].pin == pin)
          last = mock.writes[k].value;
      if (last == HIGH)
      {
        std::printf("  pin %d left HIGH after safing\n", pin);
        stillHigh++;
        break;
      }
    }
    check(mock.writes.size() > mark, "  safing actually writes pins");
    check(stillHigh == 0, "every actuator the table can drive is left LOW");
  }

  std::printf("\n%s\n", failures ? "FAIL" : "PASS");
  return failures ? 1 : 0;
}

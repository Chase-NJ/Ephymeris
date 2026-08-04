/*  GATE F — a whole session WITH POLICY.
 *
 *  Gate E runs the no-policy configuration, which is what the four shaping
 *  sketches pass and is a real thing that ships. It leaves the harder half
 *  untested: anti-bias selection, per-side correction budgets and the escalating
 *  abstention penalty.
 *
 *  Those are hard because runTrial() calls into them from INSIDE the trial --
 *  BehaviorBox.h:1084 recordChoice, :1161/:1183/:1199 recordAbstention, :1231
 *  shouldRepeat -- and tgRunTrial() calls nothing, because policy stays outside
 *  the interpreter. The session layer has to make the same calls, at the same
 *  moments, with the same arguments, from facts the walk reports.
 *
 *  If that reconstruction is wrong ANYWHERE, the two sessions diverge on trial
 *  selection within a handful of trials and never recover -- which makes this a
 *  sharp test rather than a forgiving one. The anti-bias estimator is a ring
 *  buffer over expressed sides, so a single mis-attributed vote changes every
 *  draw after it.
 *
 *  THE THREE CLASSES ARE THE SAME OBJECTS ON BOTH SIDES, constructed identically
 *  and fed the same START parameters. What is under test is not their arithmetic
 *  but WHEN they are called and WITH WHAT.
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

#include <TgSession.h>

#include "battery.h"

static const TrialType goRight1(true, Odors[0], rightWell, RIGHT_WELL_FL_1,
                                BF_ODOR_1_ON, BF_FLUID_R, BF_STOP_FLUID_G_R);
static const TrialType goLeft1(true, Odors[2], leftWell, LEFT_WELL_FL_1,
                               BF_ODOR_3_ON, BF_FLUID_L, BF_STOP_FLUID_G_L);

/*  A session's worth of scripted animals, drawn once so both sides face the same
    subject. The SIDE is not drawn here -- the selector picks it, live, and
    reproducing that is most of what this gate is about. */
struct Plan
{
  Script script[600];
  int n;
};

static Plan drawSession(Rng &rng, int trials)
{
  Plan p{};
  p.n = trials;
  for (int i = 0; i < trials; i++)
  {
    TaskParams q;
    clampTaskParams(q);
    applyStage(q, i);
    p.script[i] = drawScript(rng, q);
  }
  return p;
}

/*  Arm the scripted animal for a trial whose correct side is `right`.

    drawScript() picks its response pin from the side it was drawn for, so the
    pin has to be remapped once the selector has spoken. Without this the "wrong
    port" trials would be wrong relative to a side nobody presented. */
static void armFor(const Script &s, bool right, unsigned long now)
{
  mock.pokes.clear();
  if (s.engageTo > s.engageAt)
    mock.poke(odorPort, now + s.engageAt, now + s.engageTo);
  if (s.respPin)
  {
    const bool drawnCorrect = (s.trial == 0) == (s.respPin == rightWell);
    const int pin = drawnCorrect ? (right ? rightWell : leftWell)
                                 : (right ? leftWell : rightWell);
    mock.poke(pin, now + s.respAt, now + s.respTo);
  }
}

/* ---------------------------------------------------------------- *
 *  The current sketch's loop, policy and all
 * ---------------------------------------------------------------- */

static std::vector<MockEvent> referenceSession(const Plan &plan, const TaskParams &start,
                                               int numTrials)
{
  mock.reset();
  mock.deadline = 36000000UL;
  TaskParams p = start;

  AntiBiasSelector selector(&goRight1, &goLeft1);
  AbstentionPenalty abstention;
  CorrectionPolicy correction;
  selector.configure(p);
  abstention.configure(p);
  correction.configure(p.correctionLeft, p.correctionRight);
  TrialPolicy policy;
  policy.selector = &selector;
  policy.abstention = &abstention;
  policy.correction = &correction;

  TrialClock clock;
  clock.beginSession();
  emitStrobe(clock, BF_START_SESSION);

  int completed = 0;
  const TrialType *current = nullptr;
  for (int i = 0; i < plan.n && completed < numTrials; i++)
  {
    if (current == nullptr)
      current = selector.selectNext();
    armFor(plan.script[i], current->correctWell == rightWell, mock.now);

    if (runTrial(*current, p, clock, &policy, completed))
    {
      completed++;
      applyStage(p, completed);
      correction.onAdvance(current->correctWell == rightWell);
      current = nullptr;
    }
    else
      emitStrobe(clock, BF_INVALID_TRIAL);
  }
  emitStrobe(clock, BF_END_SESSION);
  return mock.emitted;
}

/* ---------------------------------------------------------------- *
 *  The same session, through the interpreter
 * ---------------------------------------------------------------- */

static std::vector<MockEvent> interpreterSession(const Plan &plan, const TaskParams &start,
                                                 int numTrials)
{
  mock.reset();
  mock.deadline = 36000000UL;
  TaskParams p = start;
  TgTable table = TG_TABLE;

  AntiBiasSelector selector(&goRight1, &goLeft1);
  CorrectionPolicy correction;
  selector.configure(p);
  correction.configure(p.correctionLeft, p.correctionRight);

  /*  The escalator's count, kept here rather than in AbstentionPenalty -- see
      tgPenaltyMs(). Abstentions since the last CORRECT trial. */
  uint16_t abstentions = 0;

  const uint8_t rightPort = tgPortForChannel(table, rightWell);

  TrialClock clock;
  clock.beginSession();
  emitStrobe(clock, TG_STROBE_START_SESSION);

  int completed = 0;
  bool haveSide = false, sideRight = false;
  TgRun r;
  for (int i = 0; i < plan.n && completed < numTrials; i++)
  {
    if (!haveSide)
    {
      sideRight = (selector.selectNext() == &goRight1);
      haveSide = true;
    }
    armFor(plan.script[i], sideRight, mock.now);

    const uint8_t port = sideRight ? rightPort : (uint8_t)(1 - rightPort);
    const uint8_t trialIndex = tgTrialForPort(table, port);

    tgApplyParams(table, p, TG_IDX_COMMIT_HOLD, TG_IDX_SAMPLE_HOLD,
                  TG_IDX_RESP_HOLD, TG_IDX_RESP_WIN, TG_IDX_ENGAGE_WIN);
    /*  The escalating penalty, written into the timing vector before the trial
        because the interpreter reads it when it ENTERS the penalty node. This is
        the same mechanism the stage ramp uses -- policy modulating a timing
        entry -- which is why no new machinery is needed for it. */
    table.timing[TG_IDX_PEN_NOENGAGE] =
        tgPenaltyMs(p, abstentions, escalationArmed(p, completed));

    /*  The correction budget is resolved BEFORE the trial, because the graph
        evaluates it as an edge guard on the terminal. shouldRepeat() is const,
        so asking early costs nothing and changes nothing. */
    const bool budget = correction.shouldRepeat(sideRight);

    const TgTrialResult result =
        tgSessionTrial(table, r, p, clock, trialIndex, budget);
    if (result == TG_TRIAL_FAULT)
      break;

    /*  Feed the policy from the facts the walk reported, at the same moments
        runTrial() would have. */
    uint8_t chosen = TG_NO_TARGET;
    switch (tgPolicyOutcome(r, chosen))
    {
    case TG_OUTCOME_CHOSE:
      selector.recordChoice(chosen == rightPort);
      break;
    case TG_OUTCOME_ABSTAINED:
      selector.recordAbstention(sideRight);
      /*  THE SELECTOR AND THE ESCALATOR DO NOT FIRE TOGETHER, which is easy to
          miss because both are "abstention" in ordinary speech.
          recordAbstention() is called from all three abort paths -- :1161 no
          engagement, :1183 pre-odor hold broken, :1199 sampling hold broken --
          but nextDelay() is called ONLY from :1161. A broken hold is penalised
          with noPokeHoldTimeout, a flat value, and leaves the escalator alone.
          Counting all three here escalated one step early on every hold break. */
      if (!r.engaged)
        abstentions++;
      break;
    case TG_OUTCOME_SILENT:
      break;
    }

    /*  THE ONE THING THAT IS NOT POLICY, AND IT IS A REAL FINDING.
     *
     *  runTrial() draws random(0,2) at the top of checkResponse (BehaviorBox.h:
     *  1067) to break a simultaneous left/right beam break, and it draws it on
     *  every trial that reaches the response window. tgWaitForTrigger() breaks
     *  the same tie by watch-bit order -- deterministically, which is what makes
     *  Gate B reproducible -- and draws nothing.
     *
     *  So the two consume the RNG at different rates, and after the first
     *  sampled trial their streams have parted. The selector draws from that same
     *  stream, so every subsequent side differs and the sessions diverge on trial
     *  SELECTION rather than on anything under test here.
     *
     *  Consuming a matching draw realigns them. It changes no behaviour -- these
     *  scripts never break both beams at once, so the value is never used -- and
     *  it isolates the question this gate is asking from one it is not.
     *
     *  This is NOT purely a test artifact: it means an interpreter session and a
     *  runTrial() session started from the same SEED do not present the same
     *  sequence of sides. See docs/roadmap.md, Phase 7. */
    if (r.offered)
      (void)random(0, 2);

    if (result == TG_TRIAL_ADVANCED)
    {
      completed++;
      applyStage(p, completed);
      correction.onAdvance(sideRight);
      haveSide = false;
      /*  A completed CORRECT trial clears the escalator; anything else leaves it
          (runTrial :1221, inside the OUTCOME_CORRECT branch only).

          "Correct" is entering the target AND holding it: a response-hold failure
          enters the right port and still ends on the error path, so `chosen ==
          port` alone would clear the escalator on a trial runTrial() scores as an
          error. */
      if (chosen == port && !r.broke)
        abstentions = 0;
    }
  }
  emitStrobe(clock, TG_STROBE_END_SESSION);
  return mock.emitted;
}

static const char *nameOf(int c)
{
  switch (c)
  {
  case 101: return "ODOR_1_ON";        case 103: return "ODOR_3_ON";
  case 221: return "START_SESSION";    case 222: return "LIGHTS_ON";
  case 223: return "LAZY_RAT";         case 224: return "ODOR_POKE";
  case 225: return "ODOR_UNPOKE_EARLY"; case 226: return "ODOR_UNPOKE";
  case 233: return "LIGHTS_OFF";       case 234: return "INVALID_TRIAL";
  case 242: return "END_CORRECT_ITI";  case 243: return "END_INCORRECT_ITI";
  case 246: return "END_SESSION";      case 247: return "ODOR_OFF";
  case 248: return "WATER_POKE_L";     case 249: return "WATER_POKE_R";
  case 250: return "WATER_UNPOKE_EARLY_L"; case 251: return "WATER_UNPOKE_EARLY_R";
  case 252: return "FLUID_L";          case 253: return "FLUID_R";
  case 254: return "WATER_UNPOKE_L";   case 255: return "WATER_UNPOKE_R";
  case 257: return "WATER_POKE_ERROR_L"; case 258: return "WATER_POKE_ERROR_R";
  case 262: return "RESP_OMIT";        case 263: return "WATCHDOG_FAULT";
  case 357: return "STOP_FLUID_G_R";   case 369: return "STOP_FLUID_G_L";
  default: return "?";
  }
}

int main(int argc, char **argv)
{
  const unsigned long seed = (argc > 1) ? std::strtoul(argv[1], 0, 10) : 20260803UL;
  const int sessions = (argc > 2) ? std::atoi(argv[2]) : 20;
  const int numTrials = (argc > 3) ? std::atoi(argv[3]) : 40;

  Rng rng{seed};
  int diverged = 0, compared = 0;
  long events = 0;

  for (int s = 0; s < sessions; s++)
  {
    const Plan plan = drawSession(rng, numTrials * 4);

    TaskParams start;
    clampTaskParams(start);
    /*  Policy that actually bites: escalation on, and a leading correction budget
        on both sides. A run with zero budgets would exercise the correction path
        without ever taking it. */
    start.lazyEscalationEnabled = true;
    start.correctionLeft = 3;
    start.correctionRight = 3;

    std::vector<MockEvent> a, b;
    bool hung = false;
    /*  Both sides draw from the SAME rng stream for the selector, so each is
        seeded identically before it runs. */
    randomSeed(seed + s);
    try
    {
      a = referenceSession(plan, start, numTrials);
      randomSeed(seed + s);
      b = interpreterSession(plan, start, numTrials);
    }
    catch (const MockHang &)
    {
      hung = true;
    }
    if (hung)
    {
      std::printf("  session %d hung\n", s);
      diverged++;
      continue;
    }

    compared++;
    events += (long)a.size();

    bool same = a.size() == b.size();
    for (size_t k = 0; same && k < a.size(); k++)
      same = a[k].code == b[k].code && a[k].t == b[k].t;

    if (!same)
    {
      if (diverged < 3)
      {
        std::printf("  SESSION %d DIVERGES (%zu vs %zu events)\n", s, a.size(), b.size());
        for (size_t k = 0; k < a.size() || k < b.size(); k++)
        {
          const bool differs = k >= a.size() || k >= b.size() ||
                               a[k].code != b[k].code || a[k].t != b[k].t;
          if (!differs)
            continue;
          const size_t lo = k > 6 ? k - 6 : 0;
          for (size_t q = lo; q < k + 4; q++)
            std::printf("    [%zu]%s ref=%-20s@%-7lu interp=%-20s@%lu\n", q,
                        q == k ? " >" : "  ",
                        q < a.size() ? nameOf(a[q].code) : "-",
                        q < a.size() ? a[q].t : 0,
                        q < b.size() ? nameOf(b[q].code) : "-",
                        q < b.size() ? b[q].t : 0);
          break;
        }
      }
      diverged++;
    }
  }

  std::printf("seed=%lu sessions=%d compared=%d diverged=%d events=%ld\n",
              seed, sessions, compared, diverged, events);
  return diverged == 0 ? 0 : 1;
}

/*  GATE E — a whole session, not a trial.
 *
 *  Gates A-D each compare ONE trial at a time, from a clean clock, with the
 *  session's state reset. A session is not a sequence of independent trials: the
 *  stage ramp moves with the completed count, an aborted trial re-presents the
 *  same side, INVALID_TRIAL is emitted by the loop rather than by the runner, and
 *  the clock runs continuously from START_SESSION. None of that is exercised by a
 *  per-trial gate, and all of it is what the roadmap's parallel run would
 *  actually compare.
 *
 *  So this runs a FULL SESSION both ways -- the current sketch's loop, and the
 *  same loop with tgRunTrial() substituted -- and compares the entire strobe
 *  stream, timestamps included.
 *
 *  ------------------------------------------------------------------------
 *  NO POLICY OBJECTS, AND THAT IS A REAL LIMIT
 *
 *  runTrial() calls into the policy objects from INSIDE the trial:
 *  selector->recordChoice() at BehaviorBox.h:1084, recordAbstention() at :1161,
 *  :1183 and :1199. tgRunTrial() deliberately calls nothing -- policy stays
 *  outside the interpreter, which is what keeps the interpreter fixed.
 *
 *  That means anti-bias selection, correction budgets and penalty escalation are
 *  NOT yet wired to the interpreter, and a session using them would diverge on
 *  trial selection alone. Rather than invent a hook here and validate the
 *  invention, this gate runs the configuration that already ships WITHOUT them:
 *  nullptr policy, which is exactly what the four shaping sketches pass
 *  (BehaviorBox.h:997-1015).
 *
 *  What that leaves outstanding is named in docs/roadmap.md as a Phase 7 item.
 *  It is not a small one: it is the question of how policy attaches to a
 *  table-driven interpreter at all.
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
static const TrialType *TRIALS[] = {&goRight1, &goLeft1};

/*  The sides a session will present, drawn up front so BOTH loops walk the same
    sequence. With no selector there is nothing adaptive to reproduce, and drawing
    inside each loop would make the comparison depend on the two consuming the RNG
    identically -- a coupling that has nothing to do with what is being tested. */
struct Plan
{
  uint8_t side[512];
  Script script[512];
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
    p.side[i] = (uint8_t)rng.in(0, 1);
    p.script[i] = drawScript(rng, q);
    p.script[i].trial = p.side[i];
  }
  return p;
}

/*  One session, the CURRENT sketch's loop.
 *
 *  GRGL_2-Odor.ino:142-177 with the policy objects omitted -- so the
 *  re-presentation rule is "an aborted trial repeats the same side", which is
 *  what currentTrialPtr does there and what `repeat` does here. */
static std::vector<MockEvent> referenceSession(const Plan &plan, int numTrials)
{
  mock.reset();
  /*  Ten hours of mock time. reset() lands the deadline back at ten minutes,
      which is a sensible bound for ONE trial and far too short for a session --
      the first version set it before reset() and every session "hung". */
  mock.deadline = 36000000UL;
  TaskParams p;
  clampTaskParams(p);
  TrialClock clock;
  clock.beginSession();
  emitStrobe(clock, BF_START_SESSION);

  int completed = 0;
  for (int i = 0; i < plan.n && completed < numTrials; i++)
  {
    const Script &s = plan.script[i];
    /*  Re-arm the scripted animal WITHOUT clearing the emitted stream: a session
        is one continuous recording. arm() resets everything, so the pokes are
        re-registered against the running clock by hand. */
    mock.pokes.clear();
    if (s.engageTo > s.engageAt)
      mock.poke(odorPort, mock.now + s.engageAt, mock.now + s.engageTo);
    if (s.respPin)
      mock.poke(s.respPin, mock.now + s.respAt, mock.now + s.respTo);

    if (runTrial(*TRIALS[s.trial], p, clock, nullptr, completed))
    {
      completed++;
      applyStage(p, completed);
    }
    else
      emitStrobe(clock, BF_INVALID_TRIAL);
  }
  emitStrobe(clock, BF_END_SESSION);
  return mock.emitted;
}

/*  The same session, through the interpreter. */
static std::vector<MockEvent> interpreterSession(const Plan &plan, int numTrials)
{
  mock.reset();
  mock.deadline = 36000000UL;
  TaskParams p;
  clampTaskParams(p);
  TgTable table = TG_TABLE;
  TrialClock clock;
  clock.beginSession();
  emitStrobe(clock, TG_STROBE_START_SESSION);

  int completed = 0;
  TgRun r;
  for (int i = 0; i < plan.n && completed < numTrials; i++)
  {
    const Script &s = plan.script[i];
    mock.pokes.clear();
    if (s.engageTo > s.engageAt)
      mock.poke(odorPort, mock.now + s.engageAt, mock.now + s.engageTo);
    if (s.respPin)
      mock.poke(s.respPin, mock.now + s.respAt, mock.now + s.respTo);

    tgApplyParams(table, p, TG_IDX_COMMIT_HOLD, TG_IDX_SAMPLE_HOLD,
                  TG_IDX_RESP_HOLD, TG_IDX_RESP_WIN, TG_IDX_ENGAGE_WIN);

    const TgTrialResult result =
        tgSessionTrial(table, r, p, clock, s.trial, false);
    if (result == TG_TRIAL_FAULT)
    {
      std::printf("  FAULT at trial %d, node %u\n", i, r.node);
      break;
    }
    if (result == TG_TRIAL_ADVANCED)
    {
      completed++;
      applyStage(p, completed);
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
    const Plan plan = drawSession(rng, numTrials * 3);

    std::vector<MockEvent> a, b;
    bool hung = false;
    try
    {
      a = referenceSession(plan, numTrials);
      b = interpreterSession(plan, numTrials);
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

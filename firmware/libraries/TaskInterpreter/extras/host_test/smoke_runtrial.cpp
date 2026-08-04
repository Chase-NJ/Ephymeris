/*  Can we drive the REAL runTrial() off-target and capture what it emits?
 *
 *  Everything in Phase 3 rests on this. If BehaviorBox.h cannot be run against a
 *  scripted animal on the host, the equivalence gate has to move onto a board and
 *  stops being a thing that runs in CI forever afterward.
 *
 *  BehaviorBox.h is included from the READ-ONLY reference repo. Nothing here
 *  modifies it.
 */

#include <cstdio>
#include <string>
#include <vector>

#include "Arduino.h"

MockBox mock;

#include <BehaviorBox.h>

static const char *name_of(int code)
{
  switch (code)
  {
  case BF_START_SESSION: return "START_SESSION";
  case BF_LIGHTS_ON: return "LIGHTS_ON";
  case BF_LAZY_RAT: return "LAZY_RAT";
  case BF_ODOR_POKE: return "ODOR_POKE";
  case BF_ODOR_UNPOKE_EARLY: return "ODOR_UNPOKE_EARLY";
  case BF_ODOR_UNPOKE: return "ODOR_UNPOKE";
  case BF_LIGHTS_OFF: return "LIGHTS_OFF";
  case BF_INVALID_TRIAL: return "INVALID_TRIAL";
  case BF_END_CORRECT_ITI: return "END_CORRECT_ITI";
  case BF_END_INCORRECT_ITI: return "END_INCORRECT_ITI";
  case BF_ODOR_OFF: return "ODOR_OFF";
  case BF_WATER_POKE_L: return "WATER_POKE_L";
  case BF_WATER_POKE_R: return "WATER_POKE_R";
  case BF_WATER_UNPOKE_EARLY_L: return "WATER_UNPOKE_EARLY_L";
  case BF_WATER_UNPOKE_EARLY_R: return "WATER_UNPOKE_EARLY_R";
  case BF_FLUID_L: return "FLUID_L";
  case BF_FLUID_R: return "FLUID_R";
  case BF_WATER_UNPOKE_L: return "WATER_UNPOKE_L";
  case BF_WATER_UNPOKE_R: return "WATER_UNPOKE_R";
  case BF_WATER_POKE_ERROR_L: return "WATER_POKE_ERROR_L";
  case BF_WATER_POKE_ERROR_R: return "WATER_POKE_ERROR_R";
  case BF_RESP_OMIT: return "RESP_OMIT";
  case BF_STOP_FLUID_G_L: return "STOP_FLUID_G_L";
  case BF_STOP_FLUID_G_R: return "STOP_FLUID_G_R";
  case BF_ODOR_1_ON: return "ODOR_1_ON";
  case BF_ODOR_3_ON: return "ODOR_3_ON";
  default: return "?";
  }
}

/* GRGL's two trial types, verbatim from GRGL_2-Odor.ino:43-59. */
static const TrialType goRight1(true, Odors[0], rightWell, RIGHT_WELL_FL_1,
                                BF_ODOR_1_ON, BF_FLUID_R, BF_STOP_FLUID_G_R);

static void show(const char *label, bool advanced)
{
  std::printf("  %-22s -> %s\n", label, advanced ? "ADVANCE" : "REPEAT");
  std::printf("     ");
  for (const auto &e : mock.emitted)
    std::printf("%s@%lu ", name_of(e.code), e.t);
  std::printf("\n");
}

static TaskParams fresh()
{
  TaskParams p;      // in-class defaults ARE the full-task GRGL values
  clampTaskParams(p);
  applyStage(p, 0);
  return p;
}

int main()
{
  std::printf("driving the real runTrial() off-target\n\n");

  /* --- a correct trial ------------------------------------------------- */
  {
    mock.reset();
    TaskParams p = fresh();
    TrialClock clk;
    clk.beginSession();
    /* Poke the odor port from 1.3 s, hold through both 500 ms holds, withdraw at
       2.6 s; then the right (correct) well from 2.9 s, held past fluidWellHold. */
    mock.poke(odorPort, 1300, 2600);
    mock.poke(rightWell, 2900, 60000);
    bool adv = runTrial(goRight1, p, clk, nullptr, 0);
    show("correct", adv);
  }

  /* --- abstention ------------------------------------------------------ */
  {
    mock.reset();
    TaskParams p = fresh();
    TrialClock clk;
    clk.beginSession();
    bool adv = runTrial(goRight1, p, clk, nullptr, 0);  // never pokes
    show("abstention", adv);
  }

  /* --- wrong port ------------------------------------------------------ */
  {
    mock.reset();
    TaskParams p = fresh();
    TrialClock clk;
    clk.beginSession();
    mock.poke(odorPort, 1300, 2600);
    mock.poke(leftWell, 2900, 60000);
    bool adv = runTrial(goRight1, p, clk, nullptr, 0);
    show("wrong port", adv);
  }

  /* --- broken sampling hold -------------------------------------------- */
  {
    mock.reset();
    TaskParams p = fresh();
    TrialClock clk;
    clk.beginSession();
    mock.poke(odorPort, 1300, 1900);   // lets go during the second hold
    bool adv = runTrial(goRight1, p, clk, nullptr, 0);
    show("broken sampling hold", adv);
  }

  /* --- omission -------------------------------------------------------- */
  {
    mock.reset();
    TaskParams p = fresh();
    TrialClock clk;
    clk.beginSession();
    mock.poke(odorPort, 1300, 2600);   // samples, then never responds
    bool adv = runTrial(goRight1, p, clk, nullptr, 0);
    show("omission", adv);
  }

  std::printf("\nOK: runTrial() runs off-target and its stream is captured.\n");
  return 0;
}

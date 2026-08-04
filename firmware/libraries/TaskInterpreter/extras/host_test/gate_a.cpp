/*  GATE A — the C++ interpreter must emit exactly what the Python reference does.
 *
 *  Two independent implementations of the same table, driven by the same scripted
 *  animal, compared byte for byte. Fully within our control: no firmware, no
 *  board, no recorded data.
 *
 *  WHY THIS GATE COMES FIRST. Gate B compares the interpreter against runTrial(),
 *  and until the firmware changes in docs/firmware-changes.md land, some of those
 *  differences are EXPECTED. If the interpreter also had bugs, the two kinds of
 *  difference would be indistinguishable. Passing Gate A first means every Gate B
 *  difference is unambiguously firmware-versus-model.
 *
 *  This program prints its streams; the Python side runs the same scripts through
 *  taskgraph.interpret and diffs them (tests/test_gate_a.py).
 */

#include <cstdio>
#include <cstring>

#include "Arduino.h"

MockBox mock;

#include "grgl_table.h" // generated from specs/grgl_2odor.yaml

/*  One scripted animal. The fields mirror what the Python ScriptedSubject is told,
    so the two harnesses cannot disagree about what the subject did. */
struct Script
{
  const char *name;
  unsigned long engageAt;   // when the odor port is entered; 0 = never
  unsigned long engageTo;   // when it is released
  const char *respPort;     // "left" / "right" / 0 for no response
  unsigned long respAt;
  unsigned long respTo;
  uint8_t trial;            // index into trialTypes
};

static void arm(const Script &s)
{
  mock.reset();
  if (s.engageAt)
    mock.poke(odorPort, s.engageAt, s.engageTo);
  if (s.respPort)
  {
    const int pin = (std::strcmp(s.respPort, "left") == 0) ? leftWell : rightWell;
    mock.poke(pin, s.respAt, s.respTo);
  }
}

int main()
{
  /*  GRGL's defaults ARE the full-task values, so a bare TaskParams is the right
      world for this comparison. */
  TaskParams p;
  clampTaskParams(p);
  applyStage(p, 0);

  static const Script scripts[] = {
      /* name,                 engage,      resp,           trial */
      {"correct_right",        1300, 2600, "right", 2900, 4200,  0},
      {"wrong_port",           1300, 2600, "left",  2900, 4200,  0},
      {"omission",             1300, 2600, 0,       0,     0,    0},
      {"abstention",           0,    0,    0,       0,     0,    0},
      {"break_commit_hold",    1300, 1500, 0,       0,     0,    0},
      {"break_sampling_hold",  1300, 1900, 0,       0,     0,    0},
      {"response_hold_broken", 1300, 2600, "right", 2900, 2950,  0},
      {"correct_left",         1300, 2600, "left",  2900, 4200,  1},
  };

  for (const Script &s : scripts)
  {
    arm(s);
    TrialClock clock;
    clock.beginSession();
    TgRun run;
    const bool adv = tgRunTrial(TG_TABLE, run, p, clock, s.trial);

    std::printf("%s\t%s", s.name, adv ? "ADVANCE" : "REPEAT");
    for (const auto &e : mock.emitted)
      std::printf("\t%d@%lu", e.code, e.t);
    std::printf("\n");
  }
  return 0;
}

/*
  Host test for BoxUtility.h, through Utility/BOX_Utility/BOX_Utility.ino.

  The utility's command dispatch, channel lookup, STATUS formatting and
  self-test are pure logic over digitalWrite/Serial, so they can be driven
  off-target through the instrumented shim in box_shim/Arduino.h. This does NOT
  replace flashing to the rig (only arduino-cli does the full AVR compile, and
  only a real box proves a solenoid fires), but it proves the part most likely
  to be wrong: that "TOGGLE fluid_1" opens pin 44 and nothing else.

  The box is utility_fixture.h -- smaller than the lab's on purpose, so passing
  here means the engine reads its table rather than knowing a box by heart.

  Usage:  sh run_box.sh
*/

#include <Arduino.h> // the instrumented shim (box_shim/ is first on the include path)

#include <cassert>
#include <iostream>
#include <string>

#include "strobe_fixture.h"  // arbitrary codes; the real ones are generated
#include "utility_fixture.h" // a small box; the real table is generated
#include "../../../../Utility/BOX_Utility/BOX_Utility.ino"

using namespace box_utility;

static int failures = 0;

static void expect(const char *what, bool ok)
{
  std::cout << (ok ? "  [pass] " : "  [FAIL] ") << what << "\n";
  if (!ok) failures++;
}

/* Run one command line through the sketch exactly as the app would. */
static void sendCommand(const char *line)
{
  bb_feed(line);
  ::loop();
}

static bool outputContains(const char *needle)
{
  return bb_output().find(needle) != std::string::npos;
}

static std::string lastStatusLine()
{
  const std::string &all = bb_output();
  size_t end = all.rfind("STATUS ");
  if (end == std::string::npos) return "";
  size_t stop = all.find('\n', end);
  return all.substr(end, stop == std::string::npos ? std::string::npos : stop - end);
}

static bool statusHas(const char *token)
{
  return lastStatusLine().find(token) != std::string::npos;
}

static bool allClosed()
{
  for (int i = 0; i < NUM_OUTPUTS; i++)
    if (digitalRead(outputs[i].pin) != LOW) return false;
  return true;
}

const int ODOR_1 = 22, ODOR_3 = 26, LEFT_REWARD = 42, RIGHT_REWARD = 44;
const int LIGHT = 36, VACUUM = 40, ODOR_PORT = 2, LEFT_WELL = 4, RIGHT_WELL = 3;

int main()
{
  // Beams read HIGH (clear) at rest, as INPUT_PULLUP does with an intact beam.
  for (int i = 0; i < BB_MAX_PIN; i++) bb_pinValue[i] = HIGH;
  ::setup();

  std::cout << "BoxUtility host test\n";

  // --- boot -----------------------------------------------------------------
  expect("boot lands every output LOW", allClosed());
  expect("boot pulls every beam up", bb_pinMode[ODOR_PORT] == INPUT_PULLUP &&
                                     bb_pinMode[RIGHT_WELL] == INPUT_PULLUP);
  expect("boot announces READY, like every task sketch", outputContains("READY"));
  expect("boot emits a STATUS snapshot", statusHas("mode=idle"));
  expect("STATUS carries a key per output, named as on the Rig page",
         statusHas("odor_line_1=0") && statusHas("odor_line_3=0") &&
         statusHas("fluid_1=0") && statusHas("trial_light=0") && statusHas("vacuum=0"));
  expect("STATUS carries a key per beam", statusHas("odor_port=0") && statusHas("right_well=0"));
  expect("the table, not the lab's box, decides what exists", !statusHas("odor_line_4"));

  // --- nothing runs without the app -------------------------------------------
  // This is the resting firmware on every idle box, and animals are placed into
  // boxes while it runs: a held nose poke must fire nothing.
  bb_resetCapture();
  bb_pinValue[ODOR_PORT] = LOW;
  for (int i = 0; i < 600; i++) ::loop(); // past the 1 s heartbeat
  expect("an odor poke starts nothing", !outputContains("Box self-test starting"));
  expect("an odor poke leaves the box closed", allClosed());
  expect("the poke is reported on its own key", statusHas("odor_port=1") && statusHas("left_well=0"));
  bb_pinValue[ODOR_PORT] = HIGH;

  // --- one output, by name --------------------------------------------------------
  bb_resetCapture();
  sendCommand("TOGGLE fluid_1");
  expect("TOGGLE fluid_1 opens its pin", digitalRead(RIGHT_REWARD) == HIGH);
  expect("and touches nothing else", digitalRead(LEFT_REWARD) == LOW && digitalRead(ODOR_1) == LOW);
  expect("and reports fluid_1=1", statusHas("fluid_1=1"));
  sendCommand("TOGGLE fluid_1");
  expect("TOGGLE again closes it", digitalRead(RIGHT_REWARD) == LOW);

  sendCommand("TOGGLE odor_line_3");
  sendCommand("TOGGLE vacuum");
  sendCommand("TOGGLE trial_light");
  expect("every kind is addressable by name", digitalRead(ODOR_3) == HIGH &&
                                             digitalRead(VACUUM) == HIGH && digitalRead(LIGHT) == HIGH);

  // --- ALLOFF is the safety net ----------------------------------------------------
  bb_resetCapture();
  sendCommand("ALLOFF");
  expect("ALLOFF closes every output", allClosed());
  expect("and reports it", statusHas("odor_line_3=0") && statusHas("vacuum=0"));

  // --- pulsing ------------------------------------------------------------------------
  unsigned long before = millis();
  sendCommand("PULSE fluid_0");
  expect("PULSE leaves the line closed", digitalRead(LEFT_REWARD) == LOW);
  expect("after holding it open for the pulse width", millis() - before >= 200);
  bb_resetCapture();
  sendCommand("SET PULSE=500");
  expect("SET PULSE takes an in-range width", statusHas("pulse=500"));
  before = millis();
  sendCommand("PULSE odor_line_1");
  expect("PULSE honours the new width", millis() - before >= 500);
  sendCommand("SET PULSE=99999");
  sendCommand("SET PULSE=1");
  expect("out-of-range widths are refused", pulseMs == 500);

  // --- ON / OFF, junk, case ---------------------------------------------------------
  sendCommand("ON fluid_0");
  sendCommand("ON fluid_0");
  expect("ON is idempotent, unlike TOGGLE", digitalRead(LEFT_REWARD) == HIGH);
  sendCommand("OFF fluid_0");
  expect("OFF closes", digitalRead(LEFT_REWARD) == LOW);
  sendCommand("TOGGLE odor_line_4"); // not on this box
  sendCommand("TOGGLE F1");          // the retired token
  sendCommand("WIGGLE fluid_0");     // unknown verb
  sendCommand("");
  expect("malformed and foreign commands change nothing", allClosed());
  sendCommand("toggle FLUID_1");
  expect("commands are case-insensitive", digitalRead(RIGHT_REWARD) == HIGH);
  sendCommand("alloff");

  // --- the self-test: the operator wasn't there ---------------------------------
  bb_resetCapture();
  sendCommand("SELFTEST");
  expect("self-test announces itself", outputContains("Box self-test starting"));
  expect("it names each line by its Rig label", outputContains("Odor 2 (odor_line_2)") &&
                                                outputContains("Right reward (fluid_1)"));
  expect("stimulus lines fire with the vacuum closed",
         outputContains("each fires for 500 ms with the vacuum closed"));
  expect("it blinks the cue", outputContains("Cue, six blinks: Trial light"));
  expect("it prompts for each beam by label", outputContains("block the odor port beam") &&
                                              outputContains("block the right well beam"));
  expect("the resting check passes", outputContains("[pass] every beam reads clear at rest"));
  expect("an unbroken beam is a failure", outputContains("[FAIL] odor port"));
  expect("the tally counts one check per beam, plus rest", outputContains("1 of 4 automatic checks passed"));
  expect("it completes", outputContains("Self-test complete"));
  expect("it leaves the box safe", allClosed());
  expect("and idle", statusHas("mode=idle") && statusHas("test=done"));

  // --- the self-test: working sensors ------------------------------------------------
  bb_resetCapture();
  bb_pinValue[ODOR_PORT] = LOW;
  bb_pinValue[LEFT_WELL] = LOW;
  bb_pinValue[RIGHT_WELL] = LOW;
  sendCommand("SELFTEST");
  expect("blocked beams fail the resting check", outputContains("[FAIL] every beam reads clear at rest"));
  expect("and pass their prompted checks", outputContains("[pass] odor port") &&
                                           outputContains("[pass] left well") &&
                                           outputContains("[pass] right well"));
  expect("tally counts the passes", outputContains("3 of 4 automatic checks passed"));

  std::cout << (failures == 0 ? "\nall checks passed\n" : "\nFAILURES\n");
  return failures == 0 ? 0 : 1;
}

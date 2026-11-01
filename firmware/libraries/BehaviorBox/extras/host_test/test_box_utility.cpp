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
  // Beams read HIGH (clear) at rest, as INPUT_PULLUP does with an intact beam;
  // the active-high lever reads LOW at rest.
  const int LEVER = 38;
  for (int i = 0; i < BB_MAX_PIN; i++) bb_pinValue[i] = HIGH;
  bb_pinValue[LEVER] = LOW;
  ::setup();

  std::cout << "BoxUtility host test\n";

  // --- boot -----------------------------------------------------------------
  expect("boot lands every output LOW", allClosed());
  expect("boot pulls every beam up", bb_pinMode[ODOR_PORT] == INPUT_PULLUP &&
                                     bb_pinMode[RIGHT_WELL] == INPUT_PULLUP);
  expect("and leaves an active-high input unpulled", bb_pinMode[LEVER] == INPUT);
  expect("each input reads inactive at rest by its own level", statusHas("lever=0") &&
                                                                statusHas("odor_port=0"));
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

  // --- driven outputs: a click never holds a laser on --------------------------
  const int LASER = 11, TONE = 12;
  sendCommand("ON laser");
  expect("a train starts HIGH", digitalRead(LASER) == HIGH);
  bool fell = false, rose = false;
  for (int i = 0; i < 40; i++) { // 80 ms of polling: a 20 Hz, 5 ms test train
    ::loop();
    fell |= digitalRead(LASER) == LOW;
    rose |= fell && digitalRead(LASER) == HIGH;
  }
  expect("and pulses while it is on, never held", fell && rose);
  sendCommand("OFF laser");
  expect("OFF ends the train LOW", digitalRead(LASER) == LOW);
  sendCommand("TOGGLE tone");
  expect("a tone line plays its test tone", bb_tone[TONE] == BOX_UTIL_TONE_HZ && statusHas("tone=1"));
  sendCommand("TOGGLE tone");
  expect("and stops", bb_tone[TONE] == 0);
  sendCommand("PULSE laser");
  expect("a pulsed train ends LOW", digitalRead(LASER) == LOW);

  // --- each driven output's one setting ---------------------------------------
  const int HOUSE = 45;
  bb_resetCapture();
  sendCommand("STATUS?");
  expect("STATUS carries each driven output's setting at its default",
         statusHas("house.duty=255") && statusHas("tone.hz=1000") && statusHas("laser.hz=20"));
  expect("and none for a level line", !statusHas("trial_light.") && !statusHas("fluid_0."));
  sendCommand("ON house");
  expect("a PWM line is on at its duty", bb_pwm[HOUSE] == 255);
  sendCommand("DUTY house 64");
  expect("DUTY applies at once to a line that is on", bb_pwm[HOUSE] == 64 && statusHas("house.duty=64"));
  sendCommand("DUTY house 256");
  sendCommand("DUTY house");
  sendCommand("DUTY house 6x");
  sendCommand("DUTY house -1");
  expect("a duty out of range or malformed is refused", bb_pwm[HOUSE] == 64 && setting[8] == 64);
  sendCommand("OFF house");
  expect("OFF ends the PWM LOW", digitalRead(HOUSE) == LOW && bb_pwm[HOUSE] == 0);
  sendCommand("TOGGLE house");
  expect("and the next switch-on keeps the duty", bb_pwm[HOUSE] == 64);
  sendCommand("OFF house");

  sendCommand("HZ tone 2500");
  sendCommand("ON tone");
  expect("HZ sets a tone's pitch", bb_tone[TONE] == 2500 && statusHas("tone.hz=2500"));
  sendCommand("HZ tone 30");
  sendCommand("HZ tone 65536");
  expect("a pitch outside 31..65535 Hz is refused", bb_tone[TONE] == 2500);
  sendCommand("HZ tone 65535");
  expect("and the ends are taken", bb_tone[TONE] == 65535);
  sendCommand("DUTY tone 10");
  expect("DUTY is not a tone's verb", bb_tone[TONE] == 65535 && statusHas("tone.hz=65535"));
  sendCommand("OFF tone");

  sendCommand("HZ laser 101");
  sendCommand("HZ laser 0");
  sendCommand("DUTY laser 10");
  expect("a train refuses a rate outside 1..100 Hz, and DUTY", setting[5] == 20);
  sendCommand("HZ laser 100");
  sendCommand("ON laser");
  int rises = 0;
  bool was = true;
  unsigned long from = millis();
  while (millis() - from < 100)
  {
    ::loop();
    bool now = digitalRead(LASER) == HIGH;
    if (now && !was) rises++;
    was = now;
  }
  expect("a 100 Hz train rises every 10 ms, its 5 ms pulse shorter than the period",
         rises >= 9 && rises <= 10);
  while (digitalRead(LASER) == HIGH) ::loop();
  sendCommand("HZ laser 5");
  expect("a new rate restarts the train with a fresh pulse", digitalRead(LASER) == HIGH);
  from = millis();
  while (digitalRead(LASER) == HIGH && millis() - from < 50) ::loop();
  expect("whose width is still 5 ms, give or take a poll", millis() - from <= 5 + POLL_MS + 1);
  sendCommand("HZ laser 100");
  sendCommand("OFF laser");
  sendCommand("HZ trial_light 10");
  sendCommand("DUTY fluid_0 10");
  sendCommand("HZ nothing 10");
  expect("a level line has no setting, and an unknown name changes nothing",
         setting[7] == 0 && setting[3] == 0 && allClosed());
  sendCommand("ALLOFF");
  expect("ALLOFF keeps every setting", setting[8] == 64 && setting[6] == 65535 && setting[5] == 100);

  // --- the self-test: the operator wasn't there ---------------------------------
  bb_resetCapture();
  sendCommand("SELFTEST");
  expect("self-test announces itself", outputContains("Box self-test starting"));
  expect("it names each line by its Rig label", outputContains("Odor 2 (odor_line_2)") &&
                                                outputContains("Right reward (fluid_1)"));
  expect("stimulus lines fire with the routing lines on, named by label",
         outputContains("Stimulus lines: each fires for 500 ms with Vacuum on."));
  expect("it blinks every cue, each as its drive",
         outputContains("Cue, six blinks: Trial light") && outputContains("Cue, six blinks: Laser (laser)") &&
         outputContains("Cue, six blinks: Tone (tone)") && outputContains("Cue, six blinks: House light"));
  expect("routing lines run with the stimuli, not blinked on their own", !outputContains("Routing line"));
  expect("it prompts for each input by label", outputContains("block or press the odor port within") &&
                                               outputContains("block or press the lever within"));
  expect("the resting check passes, the lever by its own level",
         outputContains("[pass] every sensor reads clear at rest"));
  expect("an untouched input is a failure", outputContains("[FAIL] odor port") &&
                                            outputContains("[FAIL] lever"));
  expect("the tally counts one check per input, plus rest", outputContains("1 of 5 automatic checks passed"));
  expect("it completes", outputContains("Self-test complete"));
  expect("it leaves the box safe", allClosed() && bb_tone[TONE] == 0 && bb_pwm[HOUSE] == 0);
  expect("and idle", statusHas("mode=idle") && statusHas("test=done"));

  // --- the self-test: the mirror lights a level cue, never a train or tone --------------
  bb_resetCapture();
  bb_pinValue[ODOR_PORT] = LOW; // held through the other prompts
  sendCommand("SELFTEST");
  {
    const std::string &out = bb_output();
    size_t sensors = out.find("Sensors: block or press the left well");
    std::string after = sensors == std::string::npos ? "" : out.substr(sensors);
    expect("an active input lights the first level cue", after.find(" trial_light=1 ") != std::string::npos);
    expect("and never a train or a tone declared before it",
           after.find(" laser=1 ") == std::string::npos && after.find(" tone=1 ") == std::string::npos);
  }
  bb_pinValue[ODOR_PORT] = HIGH;

  // --- the self-test: working sensors ------------------------------------------------
  bb_resetCapture();
  bb_pinValue[ODOR_PORT] = LOW;
  bb_pinValue[LEFT_WELL] = LOW;
  bb_pinValue[RIGHT_WELL] = LOW;
  bb_pinValue[LEVER] = HIGH;
  sendCommand("SELFTEST");
  expect("active inputs fail the resting check", outputContains("[FAIL] every sensor reads clear at rest"));
  expect("and pass their prompted checks", outputContains("[pass] odor port") &&
                                           outputContains("[pass] left well") &&
                                           outputContains("[pass] right well") &&
                                           outputContains("[pass] lever"));
  expect("tally counts the passes", outputContains("4 of 5 automatic checks passed"));

  std::cout << (failures == 0 ? "\nall checks passed\n" : "\nFAILURES\n");
  return failures == 0 ? 0 : 1;
}

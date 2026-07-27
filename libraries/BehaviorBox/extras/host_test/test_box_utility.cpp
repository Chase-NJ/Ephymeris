/*
  Host test for Utility/BOX_Utility.ino.

  The sketch's command dispatch, channel-token parsing, and STATUS formatting
  are pure logic sitting on top of digitalWrite/Serial — so they can be driven
  off-target through the instrumented shim in box_shim/Arduino.h. This does NOT
  replace flashing to the rig (only arduino-cli does the full AVR compile, and
  only a real box proves a solenoid actually fires), but it does prove the part
  most likely to be wrong: that "TOGGLE F2" opens pin 44 and nothing else.

  Usage:  sh run_box.sh
*/

#include <Arduino.h> // the instrumented shim (box_shim/ is first on the include path)

#include <cassert>
#include <iostream>
#include <string>

// The sketch under test, compiled as a translation unit.
#include "../../../../Utility/BOX_Utility/BOX_Utility.ino"

static int failures = 0;

static void check(const char *what, bool ok)
{
  std::cout << (ok ? "  [pass] " : "  [FAIL] ") << what << "\n";
  if (!ok) failures++;
}

/* Run one whole command line through the sketch exactly as the app would:
   queue it on the serial input, then let loop() pick it up. */
static void sendCommand(const char *line)
{
  bb_feed(line);
  loop();
}

static bool outputContains(const char *needle)
{
  return bb_output().find(needle) != std::string::npos;
}

/* The most recent STATUS line the sketch emitted. */
static std::string lastStatus()
{
  const std::string &all = bb_output();
  size_t end = all.rfind("STATUS ");
  if (end == std::string::npos) return "";
  size_t stop = all.find('\n', end);
  return all.substr(end, stop == std::string::npos ? std::string::npos : stop - end);
}

static bool statusHas(const char *token)
{
  std::string s = lastStatus();
  return s.find(token) != std::string::npos;
}

int main()
{
  // Beams read HIGH (clear) at rest, as INPUT_PULLUP does with an intact beam.
  for (int i = 0; i < BB_MAX_PIN; i++) bb_pinValue[i] = HIGH;
  setup();

  std::cout << "BOX_Utility host test\n";

  // --- boot state -------------------------------------------------------
  check("boot lands every output LOW", digitalRead(Fluids[0]) == LOW &&
                                       digitalRead(Odors[0]) == LOW &&
                                       digitalRead(vac) == LOW &&
                                       digitalRead(trialLight) == LOW);
  check("boot announces itself in the console", outputContains("BOX Utility ready"));
  check("boot emits a STATUS snapshot", statusHas("mode=idle"));
  check("STATUS carries a key per fluid line", statusHas("f1=0") && statusHas("f4=0"));
  check("STATUS carries a key per odor line", statusHas("o1=0") && statusHas("o12=0"));
  check("STATUS carries vac/light/pulse", statusHas("vac=0") && statusHas("light=0") &&
                                          statusHas("pulse=200"));

  // --- toggling each solenoid ------------------------------------------
  bb_resetCapture();
  sendCommand("TOGGLE F2");
  check("TOGGLE F2 opens the left-2 fluid pin", digitalRead(Fluids[1]) == HIGH);
  check("TOGGLE F2 touches nothing else", digitalRead(Fluids[0]) == LOW &&
                                          digitalRead(Fluids[2]) == LOW &&
                                          digitalRead(Fluids[3]) == LOW);
  check("TOGGLE F2 reports f2=1", statusHas("f2=1"));

  sendCommand("TOGGLE F2");
  check("TOGGLE F2 again closes it", digitalRead(Fluids[1]) == LOW);

  bb_resetCapture();
  sendCommand("TOGGLE O7");
  check("TOGGLE O7 maps to Odors[6]", digitalRead(Odors[6]) == HIGH);
  check("TOGGLE O7 reports o7=1", statusHas("o7=1"));

  sendCommand("TOGGLE O12");
  check("TOGGLE O12 maps to Odors[11]", digitalRead(Odors[11]) == HIGH);

  sendCommand("TOGGLE VAC");
  sendCommand("TOGGLE LIGHT");
  check("VAC and LIGHT are addressable", digitalRead(vac) == HIGH &&
                                         digitalRead(trialLight) == HIGH);

  // --- ALLOFF is the safety net ----------------------------------------
  bb_resetCapture();
  sendCommand("ALLOFF");
  {
    bool allClosed = true;
    for (int i = 0; i < NUM_ODORS; i++) if (digitalRead(Odors[i]) != LOW) allClosed = false;
    for (int i = 0; i < NUM_FLUIDS; i++) if (digitalRead(Fluids[i]) != LOW) allClosed = false;
    if (digitalRead(vac) != LOW || digitalRead(trialLight) != LOW) allClosed = false;
    check("ALLOFF closes every channel", allClosed);
  }
  check("ALLOFF reports the cleared state", statusHas("o7=0") && statusHas("o12=0") &&
                                            statusHas("vac=0"));

  // --- pulsing ----------------------------------------------------------
  unsigned long before = millis();
  sendCommand("PULSE F3");
  check("PULSE leaves the line closed", digitalRead(Fluids[2]) == LOW);
  check("PULSE held it open for the pulse width", millis() - before >= 200);

  bb_resetCapture();
  sendCommand("SET PULSE=500");
  check("SET PULSE takes an in-range width", statusHas("pulse=500"));
  before = millis();
  sendCommand("PULSE O1");
  check("PULSE honours the new width", millis() - before >= 500);
  check("PULSE O1 closed again", digitalRead(Odors[0]) == LOW);

  bb_resetCapture();
  sendCommand("SET PULSE=99999");
  check("an out-of-range pulse width is refused", statusHas("pulse=500"));
  sendCommand("SET PULSE=1");
  check("a too-short pulse width is refused", statusHas("pulse=500"));

  // --- explicit ON/OFF --------------------------------------------------
  sendCommand("ON F1");
  check("ON opens", digitalRead(Fluids[0]) == HIGH);
  sendCommand("ON F1");
  check("ON is idempotent, unlike TOGGLE", digitalRead(Fluids[0]) == HIGH);
  sendCommand("OFF F1");
  check("OFF closes", digitalRead(Fluids[0]) == LOW);

  // --- junk is ignored, not obeyed --------------------------------------
  sendCommand("TOGGLE O13");   // out of range
  sendCommand("TOGGLE F5");    // out of range
  sendCommand("TOGGLE NOPE");  // unknown token
  sendCommand("WIGGLE F1");    // unknown verb
  sendCommand("");             // empty
  {
    bool stillClosed = true;
    for (int i = 0; i < NUM_ODORS; i++) if (digitalRead(Odors[i]) != LOW) stillClosed = false;
    for (int i = 0; i < NUM_FLUIDS; i++) if (digitalRead(Fluids[i]) != LOW) stillClosed = false;
    check("malformed commands change nothing", stillClosed);
  }

  // --- case insensitivity (a human typing into the console) -------------
  sendCommand("toggle f4");
  check("commands are case-insensitive", digitalRead(Fluids[3]) == HIGH);
  sendCommand("alloff");

  // --- the self-test ----------------------------------------------------
  bb_resetCapture();
  // Leave every beam clear; the three prompted breaks will time out, which is
  // the honest "operator wasn't there" path and must still finish and report.
  sendCommand("SELFTEST");

  check("self-test announces itself", outputContains("Box self-test starting"));
  check("self-test walks the odor lines", outputContains("Odor lines: all 12 fired"));
  check("self-test walks the fluid lines", outputContains("Fluid lines: all 4 pulsed"));
  check("self-test blinks the light", outputContains("Trial light: done"));
  check("self-test prompts for each beam", outputContains("block the ODOR PORT beam") &&
                                           outputContains("block the LEFT WELL beam") &&
                                           outputContains("block the RIGHT WELL beam"));
  check("self-test confirms the resting-beam check", outputContains("[pass] all three beams read clear at rest"));
  check("unbroken beams are reported as failures", outputContains("[FAIL] odor port"));
  check("self-test reports a pass tally", outputContains("of 4 automatic checks passed"));
  check("self-test completes", outputContains("Self-test complete"));
  check("self-test leaves the box safe", digitalRead(Fluids[0]) == LOW &&
                                         digitalRead(Odors[0]) == LOW &&
                                         digitalRead(vac) == LOW &&
                                         digitalRead(trialLight) == LOW);
  check("self-test returns to idle", statusHas("mode=idle") && statusHas("test=done"));

  // --- a self-test that finds working sensors ---------------------------
  bb_resetCapture();
  // A beam that reads LOW is a blocked beam: the prompted checks pass at once.
  bb_pinValue[odorPort] = LOW;
  bb_pinValue[leftWell] = LOW;
  bb_pinValue[rightWell] = LOW;
  sendCommand("SELFTEST");
  check("blocked beams fail the resting check", outputContains("[FAIL] all three beams read clear at rest"));
  check("blocked beams pass their prompted check", outputContains("[pass] odor port") &&
                                                   outputContains("[pass] left well") &&
                                                   outputContains("[pass] right well"));
  check("tally counts the passes", outputContains("3 of 4 automatic checks passed"));

  std::cout << (failures == 0 ? "\nall checks passed\n" : "\nFAILURES\n");
  return failures == 0 ? 0 : 1;
}

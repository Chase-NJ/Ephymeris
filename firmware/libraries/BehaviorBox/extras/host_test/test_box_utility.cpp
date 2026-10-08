/*
  Host test for Utility/BOX_Utility.ino.

  The sketch's command dispatch, channel-token parsing, and STATUS formatting
  are pure logic sitting on top of digitalWrite/Serial — so they can be driven
  off-target through the instrumented shim in box_shim/Arduino.h. This does NOT
  replace flashing to the rig (only arduino-cli does the full AVR compile, and
  only a real box proves a solenoid actually fires), but it does prove the part
  most likely to be wrong: that "TOGGLE F2" opens pin 44 and nothing else.

  NAMING: the sketch is #included as a translation unit, so every file-scope
  name in it is in scope here — and BOX_Utility.ino already has a `check()`
  (its self-test reporter, which even prints the same "[pass]/[FAIL]" prose)
  and a `lastStatus` (its heartbeat timestamp). This harness therefore calls
  its own helpers `expect()` and `lastStatusLine()`. The sketch's names are the
  ones flashed to hardware; when they collide, THIS file yields. Renaming
  either of these back is a compile error, not a style question.

  Usage:  sh run_box.sh
*/

#include <Arduino.h> // the instrumented shim (box_shim/ is first on the include path)

#include <cassert>
#include <iostream>
#include <string>

// The sketch under test, compiled as a translation unit.
#include "strobe_fixture.h"  // arbitrary codes; the real ones are generated
#include "../../../../Utility/BOX_Utility/BOX_Utility.ino"

static int failures = 0;

static void expect(const char *what, bool ok)
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
  std::string s = lastStatusLine();
  return s.find(token) != std::string::npos;
}

int main()
{
  // Beams read HIGH (clear) at rest, as INPUT_PULLUP does with an intact beam.
  for (int i = 0; i < BB_MAX_PIN; i++) bb_pinValue[i] = HIGH;
  setup();

  std::cout << "BOX_Utility host test\n";

  // --- boot state -------------------------------------------------------
  expect("boot lands every output LOW", digitalRead(Fluids[0]) == LOW &&
                                       digitalRead(Odors[0]) == LOW &&
                                       digitalRead(vac) == LOW &&
                                       digitalRead(trialLight) == LOW);
  expect("boot announces READY, like every task sketch", outputContains("READY"));
  expect("boot announces itself in the console", outputContains("BOX Utility."));
  expect("boot emits a STATUS snapshot", statusHas("mode=idle"));

  // --- nothing runs without the app ------------------------------------
  // TEST_Box started its self-test on an odor poke. This sketch is now the
  // resting firmware on every idle box, and animals are placed into boxes
  // while it runs — a nose poke must not fire twelve odor lines into an
  // occupied chamber.
  bb_resetCapture();
  bb_pinValue[odorPort] = LOW; // a poke, held
  // Long enough to clear the 1 s STATUS heartbeat (loop() delays pollingRate
  // per pass and the shim's millis advances on delay), so there is a fresh
  // status to read — and so a *held* poke is proven harmless, not just a brief one.
  for (int i = 0; i < 600; i++) loop();
  expect("an odor poke starts nothing", !outputContains("Box self-test starting"));
  expect("an odor poke leaves the box closed", digitalRead(Odors[0]) == LOW &&
                                              digitalRead(Fluids[0]) == LOW &&
                                              digitalRead(vac) == LOW);
  expect("an odor poke leaves it idle", statusHas("mode=idle"));
  expect("the poke is still reported", statusHas("beams=100"));
  bb_pinValue[odorPort] = HIGH; // beam clear again for the checks below
  expect("STATUS carries a key per fluid line", statusHas("f1=0") && statusHas("f4=0"));
  expect("STATUS carries a key per odor line", statusHas("o1=0") && statusHas("o12=0"));
  expect("STATUS carries vac/light/pulse", statusHas("vac=0") && statusHas("light=0") &&
                                          statusHas("pulse=200"));

  // --- toggling each solenoid ------------------------------------------
  bb_resetCapture();
  sendCommand("TOGGLE F2");
  expect("TOGGLE F2 opens the left-2 fluid pin", digitalRead(Fluids[1]) == HIGH);
  expect("TOGGLE F2 touches nothing else", digitalRead(Fluids[0]) == LOW &&
                                          digitalRead(Fluids[2]) == LOW &&
                                          digitalRead(Fluids[3]) == LOW);
  expect("TOGGLE F2 reports f2=1", statusHas("f2=1"));

  sendCommand("TOGGLE F2");
  expect("TOGGLE F2 again closes it", digitalRead(Fluids[1]) == LOW);

  bb_resetCapture();
  sendCommand("TOGGLE O7");
  expect("TOGGLE O7 maps to Odors[6]", digitalRead(Odors[6]) == HIGH);
  expect("TOGGLE O7 reports o7=1", statusHas("o7=1"));

  sendCommand("TOGGLE O12");
  expect("TOGGLE O12 maps to Odors[11]", digitalRead(Odors[11]) == HIGH);

  sendCommand("TOGGLE VAC");
  sendCommand("TOGGLE LIGHT");
  expect("VAC and LIGHT are addressable", digitalRead(vac) == HIGH &&
                                         digitalRead(trialLight) == HIGH);

  // --- ALLOFF is the safety net ----------------------------------------
  bb_resetCapture();
  sendCommand("ALLOFF");
  {
    bool allClosed = true;
    for (int i = 0; i < NUM_ODORS; i++) if (digitalRead(Odors[i]) != LOW) allClosed = false;
    for (int i = 0; i < NUM_FLUIDS; i++) if (digitalRead(Fluids[i]) != LOW) allClosed = false;
    if (digitalRead(vac) != LOW || digitalRead(trialLight) != LOW) allClosed = false;
    expect("ALLOFF closes every channel", allClosed);
  }
  expect("ALLOFF reports the cleared state", statusHas("o7=0") && statusHas("o12=0") &&
                                            statusHas("vac=0"));

  // --- pulsing ----------------------------------------------------------
  unsigned long before = millis();
  sendCommand("PULSE F3");
  expect("PULSE leaves the line closed", digitalRead(Fluids[2]) == LOW);
  expect("PULSE held it open for the pulse width", millis() - before >= 200);

  bb_resetCapture();
  sendCommand("SET PULSE=500");
  expect("SET PULSE takes an in-range width", statusHas("pulse=500"));
  before = millis();
  sendCommand("PULSE O1");
  expect("PULSE honours the new width", millis() - before >= 500);
  expect("PULSE O1 closed again", digitalRead(Odors[0]) == LOW);

  // A refused SET PULSE changes nothing *and says nothing*: the dispatch
  // returns without reporting, exactly as it does for any unrecognised input.
  // So the state is asserted directly and the status is asked for — checking
  // `statusHas` against a freshly-reset capture would be testing that a
  // refusal emits a STATUS line, which it deliberately does not.
  bb_resetCapture();
  sendCommand("SET PULSE=99999");
  expect("an out-of-range pulse width is refused", pulseMs == 500);
  sendCommand("SET PULSE=1");
  expect("a too-short pulse width is refused", pulseMs == 500);
  sendCommand("STATUS?");
  expect("and the width it reports is the one it kept", statusHas("pulse=500"));

  // --- explicit ON/OFF --------------------------------------------------
  sendCommand("ON F1");
  expect("ON opens", digitalRead(Fluids[0]) == HIGH);
  sendCommand("ON F1");
  expect("ON is idempotent, unlike TOGGLE", digitalRead(Fluids[0]) == HIGH);
  sendCommand("OFF F1");
  expect("OFF closes", digitalRead(Fluids[0]) == LOW);

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
    expect("malformed commands change nothing", stillClosed);
  }

  // --- case insensitivity (a human typing into the console) -------------
  sendCommand("toggle f4");
  expect("commands are case-insensitive", digitalRead(Fluids[3]) == HIGH);
  sendCommand("alloff");

  // --- the self-test ----------------------------------------------------
  bb_resetCapture();
  // Leave every beam clear; the three prompted breaks will time out, which is
  // the honest "operator wasn't there" path and must still finish and report.
  sendCommand("SELFTEST");

  expect("self-test announces itself", outputContains("Box self-test starting"));
  expect("self-test walks the odor lines", outputContains("Odor lines: all 12 fired"));
  expect("self-test walks the fluid lines", outputContains("Fluid lines: all 4 pulsed"));
  expect("self-test blinks the light", outputContains("Trial light: done"));
  expect("self-test prompts for each beam", outputContains("block the ODOR PORT beam") &&
                                           outputContains("block the LEFT WELL beam") &&
                                           outputContains("block the RIGHT WELL beam"));
  expect("self-test confirms the resting-beam check", outputContains("[pass] all three beams read clear at rest"));
  expect("unbroken beams are reported as failures", outputContains("[FAIL] odor port"));
  expect("self-test reports a pass tally", outputContains("of 4 automatic checks passed"));
  expect("self-test completes", outputContains("Self-test complete"));
  expect("self-test leaves the box safe", digitalRead(Fluids[0]) == LOW &&
                                         digitalRead(Odors[0]) == LOW &&
                                         digitalRead(vac) == LOW &&
                                         digitalRead(trialLight) == LOW);
  expect("self-test returns to idle", statusHas("mode=idle") && statusHas("test=done"));

  // --- a self-test that finds working sensors ---------------------------
  bb_resetCapture();
  // A beam that reads LOW is a blocked beam: the prompted checks pass at once.
  bb_pinValue[odorPort] = LOW;
  bb_pinValue[leftWell] = LOW;
  bb_pinValue[rightWell] = LOW;
  sendCommand("SELFTEST");
  expect("blocked beams fail the resting check", outputContains("[FAIL] all three beams read clear at rest"));
  expect("blocked beams pass their prompted check", outputContains("[pass] odor port") &&
                                                   outputContains("[pass] left well") &&
                                                   outputContains("[pass] right well"));
  expect("tally counts the passes", outputContains("3 of 4 automatic checks passed"));

  std::cout << (failures == 0 ? "\nall checks passed\n" : "\nFAILURES\n");
  return failures == 0 ? 0 : 1;
}

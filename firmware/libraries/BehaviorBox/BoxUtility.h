/*
  BoxUtility.h
  ============
  The box utility: direct control, priming, and a hardware self-test, for
  whatever box the Rig page describes.

  This is the LOGIC, written once. The BOX -- which outputs exist, which pin
  each is on, what the operator calls it, which beams there are -- arrives as
  a table in `UtilityChannels.h`, which Ephymeris generates from the rig's
  wiring alongside `TaskPins.h` (docs/TASKS.md#the-box-utility). A sketch is
  three includes and two calls:

      #include "TaskPins.h"          // GENERATED: pins + strobe codes
      #include "UtilityChannels.h"   // GENERATED: the utility's channel table
      #include <BehaviorBox.h>
      #include <BoxUtility.h>
      void setup() { box_utility::setup(); }
      void loop()  { box_utility::loop(); }

  It used to be a hand-written sketch that knew this lab's box by heart --
  twelve odor lines named O1..O12, four fluid lines F1..F4, three beams called
  odor port / left well / right well -- so a rewired or relabelled box drove
  the right pins under the wrong names, and a box with a different count did
  not fit at all.

  HANDSHAKE
    On boot it announces READY, exactly as the behaviour sketches do, then does
    nothing until the app tells it to. It never blocks for a START: there is no
    session here.

  COMMANDS (one line each, case-insensitive, unknown lines ignored)
    TOGGLE <ch>        latch an output open/closed
    PULSE  <ch>        open it for the pulse width, then close it
    ON <ch> | OFF <ch> explicit set, for scripted use
    SET PULSE=<ms>     pulse width, 10..5000 ms (default 200)
    ALLOFF             close everything -- always safe, always available
    SELFTEST           run the full hardware test
    STOP               abort a running self-test
    STATUS?            request a fresh snapshot
  <ch> is the output's channel name on the Rig page (`odor_line_3`, `fluid_0`).

  TELEMETRY
    One STATUS line per state change plus a ~1 s heartbeat:
      STATUS mode=<idle|test> <output>=<0|1>... <input>=<1 if broken>...
             pulse=<ms> test=<phase> step=<i/n> pass=<p/n>
    Values never contain spaces (the app splits on whitespace); prose goes to
    the console as ordinary lines.

  SAFETY
    Every path that can leave fluid running -- boot, self-test entry and exit,
    STOP, ALLOFF -- closes every output, and the self-test is interruptible at
    every wait. NOTHING STARTS ON ITS OWN: this is the resting firmware on
    every idle box, and animals are placed into boxes while it runs, so a nose
    poke must never fire anything. The app is the only thing that starts
    anything.
*/

#ifndef BOX_UTILITY_H
#define BOX_UTILITY_H

#include <BehaviorBox.h>

/* What an output does, so the self-test can treat each kind as it should. */
enum BoxUtilKind : uint8_t
{
  BOX_UTIL_EMITTER,
  BOX_UTIL_REWARD,
  BOX_UTIL_CUE,
  BOX_UTIL_VACUUM
};

struct BoxUtilOutput
{
  const char *name;  // the command token and STATUS key: the Rig channel name
  const char *label; // what the operator calls it, for the console
  int pin;
  uint8_t kind;      // BoxUtilKind
};

struct BoxUtilInput
{
  const char *name;
  const char *label;
  int pin;           // INPUT_PULLUP: LOW means the beam is broken
};

#if !defined(BOX_UTILITY_OUTPUTS) || !defined(BOX_UTILITY_INPUTS)
#error "No utility channel table: Ephymeris generates UtilityChannels.h from the Rig page. Build the folder the app generated (docs/TASKS.md#the-box-utility)."
#endif

namespace box_utility
{

const BoxUtilOutput outputs[] = BOX_UTILITY_OUTPUTS;
const int NUM_OUTPUTS = BOX_UTILITY_NUM_OUTPUTS;
/* Never empty: a box with no inputs is given one sentinel row (pin -1), so the
   array is legal C++, and NUM_INPUTS says how many rows are real. */
const BoxUtilInput inputs[] = BOX_UTILITY_INPUTS;
const int NUM_INPUTS = BOX_UTILITY_NUM_INPUTS;

const unsigned long BAUD = 115200;
const int POLL_MS = 2;
const unsigned long HEARTBEAT_MS = 1000;
/* Long enough to hear a solenoid, short enough that a mis-click can't dump a
   reservoir. */
const int PULSE_MIN_MS = 10;
const int PULSE_MAX_MS = 5000;

bool isOpen[NUM_OUTPUTS];
int pulseMs = 200;
bool testRunning = false;
CommandReader commands;
unsigned long lastStatus = 0;

const char *testPhase = "-";
int testStep = 0, testSteps = 0;
int testPassed = 0, testChecks = 0;

/* ---- channels ---------------------------------------------------------- */

int outputNamed(const char *token)
{
  for (int i = 0; i < NUM_OUTPUTS; i++)
    if (strcasecmp(token, outputs[i].name) == 0)
      return i;
  return -1;
}

int countOf(uint8_t kind)
{
  int n = 0;
  for (int i = 0; i < NUM_OUTPUTS; i++)
    if (outputs[i].kind == kind)
      n++;
  return n;
}

int firstOf(uint8_t kind)
{
  for (int i = 0; i < NUM_OUTPUTS; i++)
    if (outputs[i].kind == kind)
      return i;
  return -1;
}

void setOutput(int i, bool open)
{
  isOpen[i] = open;
  digitalWrite(outputs[i].pin, open ? HIGH : LOW);
}

void setKind(uint8_t kind, bool open)
{
  for (int i = 0; i < NUM_OUTPUTS; i++)
    if (outputs[i].kind == kind)
      setOutput(i, open);
}

void allOff()
{
  for (int i = 0; i < NUM_OUTPUTS; i++)
    setOutput(i, false);
}

bool broken(int input) { return digitalRead(inputs[input].pin) == LOW; }

bool anyBroken()
{
  for (int i = 0; i < NUM_INPUTS; i++)
    if (broken(i))
      return true;
  return false;
}

/* ---- telemetry ----------------------------------------------------------- */

void reportStatus()
{
  char buf[BOX_UTILITY_STATUS_BYTES];
  int n = snprintf(buf, sizeof(buf), "mode=%s", testRunning ? "test" : "idle");
  for (int i = 0; i < NUM_OUTPUTS && n < (int)sizeof(buf); i++)
    n += snprintf(buf + n, sizeof(buf) - n, " %s=%d", outputs[i].name, isOpen[i] ? 1 : 0);
  for (int i = 0; i < NUM_INPUTS && n < (int)sizeof(buf); i++)
    n += snprintf(buf + n, sizeof(buf) - n, " %s=%d", inputs[i].name, broken(i) ? 1 : 0);
  if (n < (int)sizeof(buf))
    snprintf(buf + n, sizeof(buf) - n, " pulse=%d test=%s step=%d/%d pass=%d/%d",
             pulseMs, testPhase, testStep, testSteps, testPassed, testChecks);
  emitStatus(buf);
  lastStatus = millis();
}

/* ---- interruptible waiting -------------------------------------------------
 * Every wait inside the self-test goes through here, so STOP is honoured
 * within one polling interval however deep the test is. */
bool stopRequested() { return commands.poll() && strcasecmp(commands.line(), "STOP") == 0; }

bool waitOrStop(unsigned long ms)
{
  unsigned long start = millis();
  while (millis() - start < ms)
  {
    if (stopRequested())
      return false;
    delay(POLL_MS);
  }
  return true;
}

/* ---- the self-test -----------------------------------------------------------
 * Drives the hardware, checks what it can check, says plainly what happened.
 * Prose to the console; phase/step/passes on the STATUS strip. */

void note(const char *text) { Serial.println(text); }

void noteChannel(const char *prefix, int i)
{
  Serial.print(prefix);
  Serial.print(outputs[i].label);
  Serial.print(" (");
  Serial.print(outputs[i].name);
  Serial.println(")");
}

void beginPhase(const char *name, int steps)
{
  testPhase = name;
  testStep = 0;
  testSteps = steps;
  reportStatus();
}

void record(const char *what, bool ok)
{
  testChecks++;
  if (ok)
    testPassed++;
  Serial.print(ok ? "  [pass] " : "  [FAIL] ");
  Serial.println(what);
  reportStatus();
}

/* Fire every output of one kind in turn. Stimulus lines fire with the vacuum
   energised (closed), so each is heard and smelled rather than drawn off. */
bool cycle(uint8_t kind, const char *phase, unsigned long onMs)
{
  int steps = countOf(kind);
  if (steps == 0)
    return true;
  beginPhase(phase, steps);
  for (int i = 0; i < NUM_OUTPUTS; i++)
  {
    if (outputs[i].kind != kind)
      continue;
    testStep++;
    noteChannel("  ", i);
    setOutput(i, true);
    if (kind == BOX_UTIL_EMITTER)
      setKind(BOX_UTIL_VACUUM, true);
    reportStatus();
    bool ok = waitOrStop(onMs);
    setOutput(i, false);
    if (kind == BOX_UTIL_EMITTER)
      setKind(BOX_UTIL_VACUUM, false);
    reportStatus();
    if (!ok || !waitOrStop(300))
      return false;
  }
  return true;
}

bool testEmitters()
{
  if (countOf(BOX_UTIL_EMITTER) == 0)
    return true;
  note(countOf(BOX_UTIL_VACUUM) > 0
           ? "Stimulus lines: each fires for 500 ms with the vacuum closed."
           : "Stimulus lines: each fires for 500 ms.");
  if (!cycle(BOX_UTIL_EMITTER, "stimuli", 500))
    return false;
  note("Stimulus lines: all fired. Confirm you heard each one.");
  return true;
}

bool testRewards()
{
  if (countOf(BOX_UTIL_REWARD) == 0)
    return true;
  note("Reward lines: each opens for 500 ms.");
  if (!cycle(BOX_UTIL_REWARD, "rewards", 500))
    return false;
  note("Reward lines: all pulsed. Confirm fluid moved on each, at the well named.");
  return true;
}

bool testCues()
{
  int steps = countOf(BOX_UTIL_CUE);
  if (steps == 0)
    return true;
  beginPhase("cues", steps * 6);
  for (int i = 0; i < NUM_OUTPUTS; i++)
  {
    if (outputs[i].kind != BOX_UTIL_CUE)
      continue;
    noteChannel("Cue, six blinks: ", i);
    for (int b = 0; b < 6; b++)
    {
      testStep++;
      setOutput(i, b % 2 == 0);
      reportStatus();
      if (!waitOrStop(400))
        return false;
    }
    setOutput(i, false);
  }
  note("Cues: done. Confirm each blinked.");
  return true;
}

/* The one phase that genuinely passes or fails on its own: every beam must
   read intact at rest, then each must break when the operator blocks it. */
bool testSensors()
{
  if (NUM_INPUTS == 0)
    return true;
  beginPhase("sensors", NUM_INPUTS + 1);
  note("Sensors: leave every beam clear.");
  if (!waitOrStop(1200))
    return false;

  testStep = 1;
  bool rest = !anyBroken();
  record("every beam reads clear at rest", rest);
  if (!rest)
    note("  (a beam reading blocked while clear usually means a swapped or dead sensor)");

  int light = firstOf(BOX_UTIL_CUE);
  for (int i = 0; i < NUM_INPUTS; i++)
  {
    testStep = 2 + i;
    reportStatus();
    Serial.print("Sensors: block the ");
    Serial.print(inputs[i].label);
    Serial.println(" beam within 15 s.");
    unsigned long start = millis();
    bool broke = false;
    while (millis() - start < 15000)
    {
      if (broken(i))
      {
        broke = true;
        break;
      }
      if (stopRequested())
        return false;
      // A cue mirrors any broken beam, so the operator gets confirmation at
      // the box as well as on screen.
      if (light >= 0)
        setOutput(light, anyBroken());
      delay(POLL_MS);
    }
    if (light >= 0)
      setOutput(light, false);
    record(inputs[i].label, broke);
    if (broke && !waitOrStop(400))
      return false;
  }
  return true;
}

void runSelfTest()
{
  testRunning = true;
  testPassed = 0;
  testChecks = 0;
  allOff();
  note("");
  note("=== Box self-test starting. STOP aborts at any point. ===");
  reportStatus();

  bool completed = testEmitters() && testRewards() && testCues() && testSensors();

  allOff();
  testRunning = false;
  testPhase = completed ? "done" : "stopped";
  testStep = 0;
  testSteps = 0;
  note(completed ? "=== Self-test complete. ===" : "=== Self-test STOPPED. ===");
  char line[64];
  snprintf(line, sizeof(line), "    %d of %d automatic checks passed.", testPassed, testChecks);
  note(line);
  if (completed && testPassed < testChecks)
    note("    Re-seat the failed sensor's connector and run it again.");
  reportStatus();
}

/* ---- commands ------------------------------------------------------------- */

void pulse(int i)
{
  setOutput(i, true);
  reportStatus();
  delay(pulseMs); // short by construction; PULSE is not interruptible
  setOutput(i, false);
  reportStatus();
}

void handle(const char *line)
{
  if (strcasecmp(line, "ALLOFF") == 0)
  {
    allOff();
    reportStatus();
    return;
  }
  if (strcasecmp(line, "SELFTEST") == 0)
  {
    runSelfTest();
    return;
  }
  if (strcasecmp(line, "STATUS?") == 0)
  {
    reportStatus();
    return;
  }
  if (strncasecmp(line, "SET PULSE=", 10) == 0)
  {
    int ms = atoi(line + 10);
    if (ms >= PULSE_MIN_MS && ms <= PULSE_MAX_MS)
    {
      pulseMs = ms;
      reportStatus();
    }
    return;
  }

  const char *space = strchr(line, ' ');
  if (space == NULL)
    return; // STOP while idle, or anything unrecognised
  int i = outputNamed(space + 1);
  if (i < 0)
    return;

  if (strncasecmp(line, "TOGGLE ", 7) == 0)
  {
    setOutput(i, !isOpen[i]);
    reportStatus();
  }
  else if (strncasecmp(line, "PULSE ", 6) == 0)
    pulse(i);
  else if (strncasecmp(line, "ON ", 3) == 0)
  {
    setOutput(i, true);
    reportStatus();
  }
  else if (strncasecmp(line, "OFF ", 4) == 0)
  {
    setOutput(i, false);
    reportStatus();
  }
}

/* ---- the sketch ----------------------------------------------------------- */

void setup()
{
  initBoxHardware(); // the shared pins, including the sync line parked LOW
  // Then this box's own table, which is the authority here: every output
  // driven LOW, every beam pulled up.
  for (int i = 0; i < NUM_OUTPUTS; i++)
  {
    pinMode(outputs[i].pin, OUTPUT);
    setOutput(i, false);
  }
  for (int i = 0; i < NUM_INPUTS; i++)
    pinMode(inputs[i].pin, INPUT_PULLUP);
  Serial.begin(BAUD);

  /* Same token and shape as every task sketch. The 50 ms lets the post-reset
     serial settle -- opening the port is what reset us, so the host is
     already listening and would otherwise catch half a line. */
  delay(50);
  Serial.println("READY");
  note("BOX Utility. SELFTEST for the full check, or drive channels directly.");
  reportStatus();
}

void loop()
{
  if (commands.poll())
    handle(commands.line());
  /* Heartbeat, so a late-connecting app still learns the state -- and the
     beam readout stays live while idle. */
  if (millis() - lastStatus >= HEARTBEAT_MS)
    reportStatus();
  delay(POLL_MS);
}

} // namespace box_utility

#endif // BOX_UTILITY_H

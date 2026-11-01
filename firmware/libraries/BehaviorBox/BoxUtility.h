/*
  BoxUtility.h
  ============
  The box utility: direct control, priming, and a hardware self-test, for
  whatever box the Rig page describes.

  This is the LOGIC, written once. The BOX -- which outputs exist, which pin
  each is on, what the operator calls it, which inputs there are -- arrives as
  a table in `UtilityChannels.h`, which Ephymeris generates from the rig's
  channel set (types and roles) alongside `TaskPins.h`
  (docs/TASKS.md#the-box-utility). A sketch is three includes and two calls:

      #include "TaskPins.h"          // GENERATED: pins + strobe codes
      #include "UtilityChannels.h"   // GENERATED: the utility's channel table
      #include <BehaviorBox.h>
      #include <BoxUtility.h>
      void setup() { box_utility::setup(); }
      void loop()  { box_utility::loop(); }

  Nothing here names a channel, counts one or knows a pin:
  test_box_utility.py fails if it does.

  HANDSHAKE
    On boot it announces READY, exactly as the behaviour sketches do, then does
    nothing until the app tells it to. It never blocks for a START: there is no
    session here.

  COMMANDS (one line each, case-insensitive, unknown lines ignored)
    TOGGLE <ch>        latch an output on/off
    PULSE  <ch>        turn it on for the pulse width, then off
    ON <ch> | OFF <ch> explicit set, for scripted use
    DUTY <ch> <n>      a PWM line's duty
    HZ <ch> <n>        a tone line's pitch, or a train's rate
                       (limits and defaults: the BOX_UTIL_* defines below)
    SET PULSE=<ms>     pulse width, 10..5000 ms (default 200)
    ALLOFF             turn everything off -- always safe, always available
    SELFTEST           run the full hardware test
    STOP               abort a running self-test
    STATUS?            request a fresh snapshot
  <ch> is the output's channel name on the Rig page. A DRIVEN output is on as
  its drive says (docs/TASKS.md#driven-outputs): a PWM line at its duty, a tone
  line at its pitch, a train a test train of 5 ms pulses at its rate for as
  long as it is on, never held HIGH. A setting applies at once if the line is
  on, and is kept through OFF and ALLOFF. DUTY or HZ for the wrong kind of
  line, or out of range, changes nothing, as an out-of-range SET PULSE does.

  TELEMETRY
    One STATUS line per state change plus a ~1 s heartbeat:
      STATUS mode=<idle|test> <output>=<0|1>... <output>.<duty|hz>=<n>...
             <input>=<1 if active>... pulse=<ms> test=<phase> step=<i/n>
             pass=<p/n>
    Values never contain spaces (the app splits on whitespace); prose goes to
    the console as ordinary lines.

  SAFETY
    Every path that can leave fluid running -- boot, self-test entry and exit,
    STOP, ALLOFF -- turns every output off, and the self-test is interruptible
    at every wait. NOTHING STARTS ON ITS OWN: this is the resting firmware on
    every idle box, and animals are placed into boxes while it runs, so a nose
    poke must never fire anything. The app is the only thing that starts
    anything.
*/

#ifndef BOX_UTILITY_H
#define BOX_UTILITY_H

#include <BehaviorBox.h>
#include <BoxInterp.h> // interp_train_high(), for a train's test train

#ifndef BOX_UTILITY_HAS_TONE
#define BOX_UTILITY_HAS_TONE 0 // a table with no tone row links no tone()
#endif

/* Which group an output is tested and shown with: its channel-set role
   (docs/TASKS.md#the-box-utility). */
enum BoxUtilGroup : uint8_t
{
  BOX_UTIL_STIMULUS,
  BOX_UTIL_REWARD,
  BOX_UTIL_CUE,
  BOX_UTIL_ROUTING
};

/* How an output is driven while it is on (docs/TASKS.md#driven-outputs). */
enum BoxUtilDrive : uint8_t
{
  BOX_UTIL_LEVEL,
  BOX_UTIL_PWM,
  BOX_UTIL_TONE,
  BOX_UTIL_TRAIN
};

/* Each drive's setting: its default and the board's limits, the same as a
   spine task's row values (taskdef/spine.py's DRIVE_VALUES). */
#define BOX_UTIL_PWM_DUTY 255
#define BOX_UTIL_PWM_DUTY_MAX 255
#define BOX_UTIL_TONE_HZ 1000
#define BOX_UTIL_TONE_HZ_MIN 31
#define BOX_UTIL_TONE_HZ_MAX 65535
#define BOX_UTIL_TRAIN_HZ 20
#define BOX_UTIL_TRAIN_HZ_MIN 1
#define BOX_UTIL_TRAIN_HZ_MAX 100
#define BOX_UTIL_TRAIN_WIDTH_MS 5
/* A pulse must be shorter than the period, 1000 / hz, or the line is held
   HIGH; the width is fixed, so the fastest rate settles it for every rate. */
#if BOX_UTIL_TRAIN_WIDTH_MS >= 1000 / BOX_UTIL_TRAIN_HZ_MAX
#error "The test train's width must be shorter than the period of its fastest rate."
#endif

struct BoxUtilOutput
{
  const char *name;  // the command token and STATUS key: the Rig channel name
  const char *label; // what the operator calls it, for the console
  int pin;
  uint8_t group;     // BoxUtilGroup
  uint8_t drive;     // BoxUtilDrive
};

struct BoxUtilInput
{
  const char *name;
  const char *label;
  int pin;
  uint8_t activeHigh; // 0: active LOW (a broken IR beam), pulled up
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
uint16_t setting[NUM_OUTPUTS]; // a PWM duty, or a tone's or train's Hz; 0 for a level line
int pulseMs = 200;
bool testRunning = false;
CommandReader commands;
unsigned long lastStatus = 0;

const char *testPhase = "-";
int testStep = 0, testSteps = 0;
int testPassed = 0, testChecks = 0;

/* ---- channels ---------------------------------------------------------- */

/* The output whose name is the first `len` characters of `token`. */
int outputNamed(const char *token, size_t len)
{
  for (int i = 0; i < NUM_OUTPUTS; i++)
    if (strlen(outputs[i].name) == len && strncasecmp(token, outputs[i].name, len) == 0)
      return i;
  return -1;
}

int outputNamed(const char *token) { return outputNamed(token, strlen(token)); }

int countOf(uint8_t group)
{
  int n = 0;
  for (int i = 0; i < NUM_OUTPUTS; i++)
    if (outputs[i].group == group)
      n++;
  return n;
}

/* The first cue that is a plain level line: the one the self-test lights to
   mirror a sensor. Never a tone or a train. */
int firstLevelCue()
{
  for (int i = 0; i < NUM_OUTPUTS; i++)
    if (outputs[i].group == BOX_UTIL_CUE && outputs[i].drive == BOX_UTIL_LEVEL)
      return i;
  return -1;
}

uint16_t defaultSetting(uint8_t drive)
{
  switch (drive)
  {
  case BOX_UTIL_PWM: return BOX_UTIL_PWM_DUTY;
  case BOX_UTIL_TONE: return BOX_UTIL_TONE_HZ;
  case BOX_UTIL_TRAIN: return BOX_UTIL_TRAIN_HZ;
  default: return 0;
  }
}

unsigned long trainSince[NUM_OUTPUTS]; // when each open train started

void setOutput(int i, bool open)
{
  isOpen[i] = open;
#if BOX_UTILITY_HAS_TONE
  if (outputs[i].drive == BOX_UTIL_TONE)
  {
    if (open) tone(outputs[i].pin, setting[i]);
    else noTone(outputs[i].pin);
    return;
  }
#endif
  if (open && outputs[i].drive == BOX_UTIL_PWM)
  {
    analogWrite(outputs[i].pin, setting[i]);
    return;
  }
  if (outputs[i].drive == BOX_UTIL_TRAIN)
    trainSince[i] = millis();
  digitalWrite(outputs[i].pin, open ? HIGH : LOW); // a train starts HIGH
}

/* Every open train's pin, from millis(): called on every poll, so its edges
   land within a poll interval. */
void stepTrains()
{
  for (int i = 0; i < NUM_OUTPUTS; i++)
    if (outputs[i].drive == BOX_UTIL_TRAIN && isOpen[i])
      digitalWrite(outputs[i].pin,
                   interp_train_high((uint32_t)(millis() - trainSince[i]), setting[i],
                                     BOX_UTIL_TRAIN_WIDTH_MS) ? HIGH : LOW);
}

/* delay(), with the trains kept pulsing. */
void pause(unsigned long ms)
{
  unsigned long start = millis();
  while (millis() - start < ms)
  {
    stepTrains();
    delay(1);
  }
}

void setGroup(uint8_t group, bool open)
{
  for (int i = 0; i < NUM_OUTPUTS; i++)
    if (outputs[i].group == group)
      setOutput(i, open);
}

void allOff()
{
  for (int i = 0; i < NUM_OUTPUTS; i++)
    setOutput(i, false);
}

/* An input reads active by its own level: LOW for a pulled-up beam, HIGH for
   an active-high input such as a lever. */
bool active(int input)
{
  return digitalRead(inputs[input].pin) == (inputs[input].activeHigh ? HIGH : LOW);
}

bool anyActive()
{
  for (int i = 0; i < NUM_INPUTS; i++)
    if (active(i))
      return true;
  return false;
}

/* ---- telemetry ----------------------------------------------------------- */

void reportStatus()
{
  char buf[BOX_UTILITY_STATUS_BYTES];
  int n = snprintf(buf, sizeof(buf), "mode=%s", testRunning ? "test" : "idle");
  for (int i = 0; i < NUM_OUTPUTS && n < (int)sizeof(buf); i++)
  {
    n += snprintf(buf + n, sizeof(buf) - n, " %s=%d", outputs[i].name, isOpen[i] ? 1 : 0);
    if (outputs[i].drive != BOX_UTIL_LEVEL && n < (int)sizeof(buf))
      n += snprintf(buf + n, sizeof(buf) - n, " %s.%s=%u", outputs[i].name,
                    outputs[i].drive == BOX_UTIL_PWM ? "duty" : "hz", (unsigned)setting[i]);
  }
  for (int i = 0; i < NUM_INPUTS && n < (int)sizeof(buf); i++)
    n += snprintf(buf + n, sizeof(buf) - n, " %s=%d", inputs[i].name, active(i) ? 1 : 0);
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
    pause(POLL_MS);
  }
  return true;
}

/* ---- the self-test -----------------------------------------------------------
 * Drives the hardware, checks what it can check, says plainly what happened.
 * Prose to the console; phase/step/passes on the STATUS strip. Every output is
 * in one group, so every one is driven, each as its drive at its setting. */

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

/* Fire every output of one group in turn. Stimulus lines fire with every
   routing line on, so an odor reaches the port to be smelled rather than drawn
   off. */
bool cycle(uint8_t group, const char *phase, unsigned long onMs)
{
  int steps = countOf(group);
  if (steps == 0)
    return true;
  beginPhase(phase, steps);
  for (int i = 0; i < NUM_OUTPUTS; i++)
  {
    if (outputs[i].group != group)
      continue;
    testStep++;
    noteChannel("  ", i);
    setOutput(i, true);
    if (group == BOX_UTIL_STIMULUS)
      setGroup(BOX_UTIL_ROUTING, true);
    reportStatus();
    bool ok = waitOrStop(onMs);
    setOutput(i, false);
    if (group == BOX_UTIL_STIMULUS)
      setGroup(BOX_UTIL_ROUTING, false);
    reportStatus();
    if (!ok || !waitOrStop(300))
      return false;
  }
  return true;
}

bool testStimuli()
{
  if (countOf(BOX_UTIL_STIMULUS) == 0)
    return true;
  Serial.print("Stimulus lines: each fires for 500 ms");
  const char *joiner = " with ";
  for (int i = 0; i < NUM_OUTPUTS; i++)
    if (outputs[i].group == BOX_UTIL_ROUTING)
    {
      Serial.print(joiner);
      Serial.print(outputs[i].label);
      joiner = ", ";
    }
  note(countOf(BOX_UTIL_ROUTING) > 0 ? " on." : ".");
  if (!cycle(BOX_UTIL_STIMULUS, "stimuli", 500))
    return false;
  note("Stimulus lines: all fired. Confirm you heard or saw each one.");
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

/* Cues blink, each as its drive: a tone sounds, a train pulses. */
bool blinkGroup(uint8_t group, const char *phase, const char *prefix)
{
  int steps = countOf(group);
  if (steps == 0)
    return true;
  beginPhase(phase, steps * 6);
  for (int i = 0; i < NUM_OUTPUTS; i++)
  {
    if (outputs[i].group != group)
      continue;
    noteChannel(prefix, i);
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
  return true;
}

bool testCues()
{
  if (!blinkGroup(BOX_UTIL_CUE, "cues", "Cue, six blinks: "))
    return false;
  if (countOf(BOX_UTIL_CUE) > 0)
    note("Cues: done. Confirm each blinked, sounded or pulsed.");
  return true;
}

/* Routing lines (a vacuum) run with every stimulus line; a box with none
   blinks them here instead, so every output is driven. */
bool testRouting()
{
  if (countOf(BOX_UTIL_STIMULUS) > 0)
    return true;
  return blinkGroup(BOX_UTIL_ROUTING, "routing", "Routing line, six blinks: ");
}

/* The one phase that genuinely passes or fails on its own: every input must
   read inactive at rest, then each must go active when the operator blocks or
   presses it. */
bool testSensors()
{
  if (NUM_INPUTS == 0)
    return true;
  beginPhase("sensors", NUM_INPUTS + 1);
  note("Sensors: leave every beam clear and every input untouched.");
  if (!waitOrStop(1200))
    return false;

  testStep = 1;
  bool rest = !anyActive();
  record("every sensor reads clear at rest", rest);
  if (!rest)
    note("  (a sensor reading active at rest usually means a swapped or dead sensor)");

  int light = firstLevelCue();
  for (int i = 0; i < NUM_INPUTS; i++)
  {
    testStep = 2 + i;
    reportStatus();
    Serial.print("Sensors: block or press the ");
    Serial.print(inputs[i].label);
    Serial.println(" within 15 s.");
    unsigned long start = millis();
    bool activated = false;
    while (millis() - start < 15000)
    {
      if (active(i))
      {
        activated = true;
        break;
      }
      if (stopRequested())
        return false;
      // A level cue mirrors any active input, so the operator gets
      // confirmation at the box as well as on screen.
      if (light >= 0 && isOpen[light] != anyActive())
      {
        setOutput(light, !isOpen[light]);
        reportStatus();
      }
      pause(POLL_MS);
    }
    if (light >= 0)
      setOutput(light, false);
    record(inputs[i].label, activated);
    if (activated && !waitOrStop(400))
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

  bool completed = testStimuli() && testRewards() && testCues() && testRouting() && testSensors();

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
  pause(pulseMs); // short by construction; PULSE is not interruptible
  setOutput(i, false);
  reportStatus();
}

/* A whole unsigned decimal, or -1: "64" is 64, "", "6x" and "-1" are -1, so a
   typo never reads as a duty of 0. */
long parseCount(const char *text)
{
  if (*text == '\0')
    return -1;
  long n = 0;
  for (; *text; text++)
  {
    if (*text < '0' || *text > '9' || n > 1000000L)
      return -1;
    n = n * 10 + (*text - '0');
  }
  return n;
}

/* Whether `n` is a setting this drive takes, by the verb that sent it. */
bool takes(uint8_t drive, bool dutyVerb, long n)
{
  if (dutyVerb)
    return drive == BOX_UTIL_PWM && n <= BOX_UTIL_PWM_DUTY_MAX;
  if (drive == BOX_UTIL_TONE)
    return n >= BOX_UTIL_TONE_HZ_MIN && n <= BOX_UTIL_TONE_HZ_MAX;
  if (drive == BOX_UTIL_TRAIN)
    return n >= BOX_UTIL_TRAIN_HZ_MIN && n <= BOX_UTIL_TRAIN_HZ_MAX;
  return false;
}

/* DUTY <ch> <n> (dutyVerb) or HZ <ch> <n>: set a driven output's one setting,
   within its drive's limits, and re-drive it at once if it is on. A train
   restarts at its new rate, so no pulse runs longer than its width. */
void setSetting(const char *args, bool dutyVerb)
{
  const char *space = strrchr(args, ' ');
  if (space == NULL)
    return;
  int i = outputNamed(args, (size_t)(space - args));
  long n = parseCount(space + 1);
  if (i < 0 || n < 0 || !takes(outputs[i].drive, dutyVerb, n))
    return;
  setting[i] = (uint16_t)n;
  if (isOpen[i])
    setOutput(i, true);
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
  if (strncasecmp(line, "DUTY ", 5) == 0)
  {
    setSetting(line + 5, true);
    return;
  }
  if (strncasecmp(line, "HZ ", 3) == 0)
  {
    setSetting(line + 3, false);
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
  // driven LOW at its default setting, every input as its level asks.
  for (int i = 0; i < NUM_OUTPUTS; i++)
  {
    pinMode(outputs[i].pin, OUTPUT);
    setting[i] = defaultSetting(outputs[i].drive);
    setOutput(i, false);
  }
  for (int i = 0; i < NUM_INPUTS; i++)
    pinMode(inputs[i].pin, inputs[i].activeHigh ? INPUT : INPUT_PULLUP);
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
     input readout stays live while idle. */
  if (millis() - lastStatus >= HEARTBEAT_MS)
    reportStatus();
  pause(POLL_MS);
}

} // namespace box_utility

#endif // BOX_UTILITY_H

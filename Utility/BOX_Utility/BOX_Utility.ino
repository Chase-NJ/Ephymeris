/*==================================
BOX Utility -- the one utility sketch for a Hart-lab behavior box.

Consolidates PRIME_Lines (latch a line open), PRIME_Bolus (timed pulse), and
TEST_Box (hardware self-test) into a single sketch driven entirely from
Ephymeris Debug Mode. Priming a line and pulsing it were never different
*programs* -- they were the same solenoid with a different open time -- and
having to re-flash between them cost more than it saved.

APP CONTROL (Ephymeris Debug Mode / PASSTHROUGH; see task.json `controls`)
  Channel tokens name every controllable output:
    O1..O12   the twelve odor solenoids
    F1..F4    the four fluid lines (F1/F2 = left well, F3/F4 = right well)
    VAC       the normally-open vacuum
    LIGHT     the trial light

  Commands (one whole line each, unknown lines ignored):
    TOGGLE <ch>       latch that channel open/closed        (was PRIME_Lines)
    PULSE  <ch>       open it for the pulse width, then close (was PRIME_Bolus)
    ON <ch> | OFF <ch>  explicit set, for scripted use
    SET PULSE=<ms>    pulse width, 10..5000 ms (default 200)
    ALLOFF            close everything -- always safe, always available
    SELFTEST          run the full hardware test               (was TEST_Box)
    STOP              abort a running self-test
    STATUS?           request a fresh snapshot

TELEMETRY (task.json `telemetry`, non-persisted -- display only)
  One STATUS line per state change plus a ~1 s heartbeat, carrying a key per
  channel so the app's control grid can light each row independently:
    STATUS mode=<idle|test> o1=<0|1> ... f1=<0|1> ... vac=<0|1> light=<0|1>
           beams=<odor><left><right> pulse=<ms> test=<phase> step=<i/n> pass=<p/n>

  Prose belongs in the console, not here: STATUS values cannot contain spaces
  (the app splits on whitespace), so the self-test's running commentary and its
  pass/fail confirmations are printed as ordinary serial lines. They land in
  Debug Mode's console pane, which is exactly where a human reads them, and the
  structured strip above stays machine-parseable.

SAFETY
  Every path that can leave fluid running -- self-test entry and exit, STOP,
  ALLOFF, and boot -- closes every channel. The self-test is interruptible at
  every wait, so STOP is always honoured within ~2 ms.

MANUAL (no app)
  An odor poke while idle starts the self-test, as TEST_Box did.
==================================*/

#include <BehaviorBox.h> // shared pinout + CommandReader + emitStatus

const int pollingRate = 2;                      // IR sensor polling (ms)
const unsigned long STATUS_HEARTBEAT_MS = 1000; // re-report at least this often

/* ---- Channel model ---------------------------------------------------- *
 * One flat index space over every controllable output, so TOGGLE/PULSE/ON/OFF
 * are written once instead of per class of hardware. */
const int CH_ODOR_FIRST = 0;
const int CH_FLUID_FIRST = NUM_ODORS;                 // 12
const int CH_VAC = NUM_ODORS + NUM_FLUIDS;            // 16
const int CH_LIGHT = CH_VAC + 1;                      // 17
const int NUM_CHANNELS = CH_LIGHT + 1;                // 18

/* Pulse width bounds: long enough to hear a solenoid, short enough that a
   mis-click can't dump a reservoir. */
const int PULSE_MIN_MS = 10;
const int PULSE_MAX_MS = 5000;

bool channelOpen[NUM_CHANNELS];
int pulseMs = 200;
bool testRunning = false;

CommandReader commands;
unsigned long lastStatus = 0;
int prevOdor = HIGH;

/* Self-test bookkeeping, reported live so the strip shows progress. */
const char *testPhase = "-";
int testStep = 0, testSteps = 0;
int testPassed = 0, testChecks = 0;

/* The Arduino pin behind a channel index. */
int pinForChannel(int ch)
{
  if (ch >= CH_ODOR_FIRST && ch < CH_FLUID_FIRST)
    return Odors[ch - CH_ODOR_FIRST];
  if (ch >= CH_FLUID_FIRST && ch < CH_VAC)
    return Fluids[ch - CH_FLUID_FIRST];
  if (ch == CH_VAC)
    return vac;
  return trialLight;
}

/* Parse a channel token ("O7", "F2", "VAC", "LIGHT") into an index, or -1. */
int channelFromToken(const char *tok)
{
  if (strcasecmp(tok, "VAC") == 0)
    return CH_VAC;
  if (strcasecmp(tok, "LIGHT") == 0)
    return CH_LIGHT;
  if ((tok[0] == 'O' || tok[0] == 'o') && tok[1] != '\0')
  {
    int n = atoi(tok + 1);
    if (n >= 1 && n <= NUM_ODORS)
      return CH_ODOR_FIRST + n - 1;
  }
  if ((tok[0] == 'F' || tok[0] == 'f') && tok[1] != '\0')
  {
    int n = atoi(tok + 1);
    if (n >= 1 && n <= NUM_FLUIDS)
      return CH_FLUID_FIRST + n - 1;
  }
  return -1;
}

/* ---- State + telemetry ------------------------------------------------ */

void setChannel(int ch, bool open)
{
  channelOpen[ch] = open;
  digitalWrite(pinForChannel(ch), open ? HIGH : LOW);
}

void allOff()
{
  for (int ch = 0; ch < NUM_CHANNELS; ch++)
    setChannel(ch, false);
}

/* Emit the whole box state. One key per channel: the app's control grid lights
   each row from its own key, so no client-side bitmap decoding is needed. */
void reportStatus()
{
  char buf[220];
  int n = snprintf(buf, sizeof(buf), "mode=%s", testRunning ? "test" : "idle");

  for (int i = 0; i < NUM_ODORS; i++)
    n += snprintf(buf + n, sizeof(buf) - n, " o%d=%d", i + 1, channelOpen[CH_ODOR_FIRST + i] ? 1 : 0);
  for (int i = 0; i < NUM_FLUIDS; i++)
    n += snprintf(buf + n, sizeof(buf) - n, " f%d=%d", i + 1, channelOpen[CH_FLUID_FIRST + i] ? 1 : 0);

  snprintf(buf + n, sizeof(buf) - n,
           " vac=%d light=%d beams=%d%d%d pulse=%d test=%s step=%d/%d pass=%d/%d",
           channelOpen[CH_VAC] ? 1 : 0,
           channelOpen[CH_LIGHT] ? 1 : 0,
           digitalRead(odorPort) == LOW ? 1 : 0,
           digitalRead(leftWell) == LOW ? 1 : 0,
           digitalRead(rightWell) == LOW ? 1 : 0,
           pulseMs, testPhase, testStep, testSteps, testPassed, testChecks);

  emitStatus(buf);
  lastStatus = millis();
}

/* ---- Interruptible waiting ------------------------------------------- *
 * Every wait inside the self-test goes through here, so STOP is honoured
 * within one polling interval no matter how deep the test is. */
bool stopRequested()
{
  return commands.poll() && strcasecmp(commands.line(), "STOP") == 0;
}

bool waitOrStop(unsigned long ms)
{
  unsigned long start = millis();
  while (millis() - start < ms)
  {
    if (stopRequested())
      return false;
    delay(pollingRate);
  }
  return true;
}

/* ---- Direct control -------------------------------------------------- */

void pulseChannel(int ch)
{
  setChannel(ch, true);
  reportStatus();
  delay(pulseMs); // short by construction; PULSE is not interruptible
  setChannel(ch, false);
  reportStatus();
}

/* ---- Self-test ------------------------------------------------------- *
 * Self-contained: it drives the hardware, checks what it can check, and says
 * plainly what happened. Confirmation lines are prose in the console; the
 * strip tracks phase/step/passes. */

void note(const char *text) { Serial.println(text); }

void beginPhase(const char *name, int steps)
{
  testPhase = name;
  testStep = 0;
  testSteps = steps;
  reportStatus();
}

void check(const char *what, bool ok)
{
  testChecks++;
  if (ok)
    testPassed++;
  Serial.print(ok ? "  [pass] " : "  [FAIL] ");
  Serial.println(what);
  reportStatus();
}

/* Cycle every odor line with the vacuum closed, so each is heard and smelled. */
bool testOdors()
{
  beginPhase("odors", NUM_ODORS);
  note("Odor lines: each fires for 500 ms with the vacuum closed.");
  for (int i = 0; i < NUM_ODORS; i++)
  {
    testStep = i + 1;
    setChannel(CH_ODOR_FIRST + i, true);
    setChannel(CH_VAC, true);
    reportStatus();
    bool ok = waitOrStop(500);
    setChannel(CH_ODOR_FIRST + i, false);
    setChannel(CH_VAC, false);
    reportStatus();
    if (!ok || !waitOrStop(300))
      return false;
  }
  note("Odor lines: all 12 fired. Confirm you heard each one.");
  return true;
}

/* Pulse every fluid line so each solenoid and its mapping can be confirmed. */
bool testFluids()
{
  beginPhase("fluids", NUM_FLUIDS);
  note("Fluid lines: F1/F2 = left well, F3/F4 = right well, 500 ms each.");
  for (int i = 0; i < NUM_FLUIDS; i++)
  {
    testStep = i + 1;
    setChannel(CH_FLUID_FIRST + i, true);
    reportStatus();
    bool ok = waitOrStop(500);
    setChannel(CH_FLUID_FIRST + i, false);
    reportStatus();
    if (!ok || !waitOrStop(300))
      return false;
  }
  note("Fluid lines: all 4 pulsed. Confirm fluid moved on each.");
  return true;
}

bool testLight()
{
  beginPhase("light", 6);
  note("Trial light: six blinks.");
  for (int i = 0; i < 6; i++)
  {
    testStep = i + 1;
    setChannel(CH_LIGHT, i % 2 == 0);
    reportStatus();
    if (!waitOrStop(400))
      return false;
  }
  setChannel(CH_LIGHT, false);
  note("Trial light: done. Confirm it blinked.");
  return true;
}

/* The one phase that can genuinely pass or fail on its own: beams must read
   intact at rest, then each must break when the operator blocks it. */
bool testSensors()
{
  beginPhase("sensors", 4);
  note("Sensors: leave all three beams clear.");
  if (!waitOrStop(1200))
    return false;

  testStep = 1;
  bool rest = digitalRead(odorPort) == HIGH && digitalRead(leftWell) == HIGH &&
              digitalRead(rightWell) == HIGH;
  check("all three beams read clear at rest", rest);
  if (!rest)
    note("  (a beam reading blocked while clear usually means a swapped or dead sensor)");

  const int pins[3] = {odorPort, leftWell, rightWell};
  const char *names[3] = {"odor port", "left well", "right well"};
  const char *prompts[3] = {
      "Sensors: block the ODOR PORT beam within 15 s.",
      "Sensors: block the LEFT WELL beam within 15 s.",
      "Sensors: block the RIGHT WELL beam within 15 s.",
  };

  for (int i = 0; i < 3; i++)
  {
    testStep = 2 + i;
    reportStatus();
    note(prompts[i]);
    unsigned long start = millis();
    bool broke = false;
    while (millis() - start < 15000)
    {
      if (digitalRead(pins[i]) == LOW)
      {
        broke = true;
        break;
      }
      if (stopRequested())
        return false;
      // The trial light mirrors any broken beam, so the operator gets
      // confirmation at the box as well as on screen.
      setChannel(CH_LIGHT, digitalRead(odorPort) == LOW || digitalRead(leftWell) == LOW ||
                               digitalRead(rightWell) == LOW);
      delay(pollingRate);
    }
    setChannel(CH_LIGHT, false);
    check(names[i], broke);
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

  bool completed = testOdors() && testFluids() && testLight() && testSensors();

  allOff();
  testRunning = false;
  testPhase = completed ? "done" : "stopped";
  testStep = 0;
  testSteps = 0;
  note(completed ? "=== Self-test complete. ===" : "=== Self-test STOPPED. ===");
  {
    char line[64];
    snprintf(line, sizeof(line), "    %d of %d automatic checks passed.", testPassed, testChecks);
    note(line);
  }
  if (completed && testPassed < testChecks)
    note("    Re-seat the failed sensor's connector and run it again.");
  // Don't let a poke held through the test immediately re-trigger it.
  prevOdor = digitalRead(odorPort);
  reportStatus();
}

/* ---- Command dispatch ------------------------------------------------ */

/* Split "VERB ARG" once; returns the verb length, arg points at the rest. */
void handleCommand(const char *line)
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
    return; // STOP while idle, or anything unrecognized
  int ch = channelFromToken(space + 1);
  if (ch < 0)
    return;

  if (strncasecmp(line, "TOGGLE ", 7) == 0)
  {
    setChannel(ch, !channelOpen[ch]);
    reportStatus();
  }
  else if (strncasecmp(line, "PULSE ", 6) == 0)
    pulseChannel(ch);
  else if (strncasecmp(line, "ON ", 3) == 0)
  {
    setChannel(ch, true);
    reportStatus();
  }
  else if (strncasecmp(line, "OFF ", 4) == 0)
  {
    setChannel(ch, false);
    reportStatus();
  }
}

void setup()
{
  initBoxHardware(); // configure every pin and land all outputs LOW
  for (int ch = 0; ch < NUM_CHANNELS; ch++)
    channelOpen[ch] = false;
  Serial.begin(9600);
  note("BOX Utility ready. SELFTEST for the full check, or drive channels directly.");
  reportStatus();
}

void loop()
{
  if (commands.poll())
    handleCommand(commands.line());

  /* Manual fallback: an odor poke while idle starts the self-test. */
  int odor = digitalRead(odorPort);
  if (!testRunning && odor == LOW && prevOdor == HIGH)
    runSelfTest();
  prevOdor = odor;

  /* Heartbeat, so a late-connecting app still learns the state -- and so the
     beam readout stays live while idle. */
  if (millis() - lastStatus >= STATUS_HEARTBEAT_MS)
    reportStatus();

  delay(pollingRate);
}

/*
Author: Chase Johnston
Date: February 20, 2026
Purpose:
  Test the full functionality of a Hart-lab behavior box:
    1. Correct IR sensor pin mapping     4. Olfactometer odor delivery timing
    2. Odor poke/unpoke                  5. Fluid solenoid pin mapping
    3. Trial light                       6. PCB / LEDs

  Now app-drivable (Ephymeris Debug Mode / PASSTHROUGH). It IDLES until commanded
  instead of blocking on an odor poke, and each test is STOP-interruptible.

  APP CONTROL (task.json `controls`):
    TEST ODORS    -> cycle all 12 odor lines (+ vacuum), 500 ms each
    TEST FLUIDS   -> pulse all 4 fluid lines, 500 ms each
    TEST LIGHT    -> blink the trial light for a few seconds
    TEST SENSORS  -> live beam check: trial light follows any broken beam
    STOP          -> abort the running test, return to idle
  Non-persisted status (task.json `telemetry`), one line per step + heartbeat:
    STATUS test=<idle|odors|fluids|light|sensors> step=<i>/<n>
    STATUS test=sensors odor=<0|1> left=<0|1> right=<0|1>

  MANUAL: an odor poke while idle starts the odor test (as the old sketch did).
*/

#include <BehaviorBox.h> // shared pinout + CommandReader (serial control) + emitStatus (telemetry)

const int pollingRate = 5; // IR sensor polling (ms)
const unsigned long STATUS_HEARTBEAT_MS = 1000;

enum { IDLE, T_ODORS, T_FLUIDS, T_LIGHT, T_SENSORS };
int mode = IDLE;

CommandReader commands;
unsigned long lastStatus = 0;
int prevOdor = HIGH;

/* Emit a status line and remember when (drives the idle heartbeat). */
void status(const char *body)
{
  emitStatus(body);
  lastStatus = millis();
}
void reportStep(const char *name, int step, int n)
{
  char buf[48];
  snprintf(buf, sizeof(buf), "test=%s step=%d/%d", name, step, n);
  status(buf);
}

/* Poll for a STOP while a test runs; other commands are ignored mid-test. */
bool stopRequested()
{
  if (commands.poll() && strcmp(commands.line(), "STOP") == 0)
    return true;
  return false;
}
/* Blocking wait that stays responsive to STOP. Returns false if STOP arrived. */
bool waitOrStop(unsigned long ms)
{
  unsigned long start = millis();
  while (millis() - start < ms)
  {
    if (stopRequested())
      return false;
    delay(2);
  }
  return true;
}

/* Cycle every odor line (with the vacuum) so you can hear/smell each fire. */
void testOdors()
{
  for (int i = 0; i < NUM_ODORS; i++)
  {
    reportStep("odors", i + 1, NUM_ODORS);
    digitalWrite(Odors[i], HIGH);
    digitalWrite(vac, HIGH);
    bool ok = waitOrStop(500);
    digitalWrite(Odors[i], LOW);
    digitalWrite(vac, LOW);
    if (!ok || !waitOrStop(500))
      return;
  }
}

/* Pulse every fluid line so you can confirm each solenoid + its mapping. */
void testFluids()
{
  for (int i = 0; i < NUM_FLUIDS; i++)
  {
    reportStep("fluids", i + 1, NUM_FLUIDS);
    digitalWrite(Fluids[i], HIGH);
    bool ok = waitOrStop(500);
    digitalWrite(Fluids[i], LOW);
    if (!ok || !waitOrStop(300))
      return;
  }
}

/* Blink the trial light for a few seconds. */
void testLight()
{
  reportStep("light", 1, 1);
  unsigned long start = millis();
  while (millis() - start < 3000)
  {
    digitalWrite(trialLight, HIGH);
    if (!waitOrStop(500))
      return;
    digitalWrite(trialLight, LOW);
    if (!waitOrStop(500))
      return;
  }
}

/* Live IR-sensor check: the trial light follows any broken beam and each beam's
   state streams to the app. Runs until STOP. */
void testSensors()
{
  while (true)
  {
    int o = digitalRead(odorPort) == LOW ? 1 : 0;
    int l = digitalRead(leftWell) == LOW ? 1 : 0;
    int r = digitalRead(rightWell) == LOW ? 1 : 0;
    digitalWrite(trialLight, (o || l || r) ? HIGH : LOW);
    char buf[48];
    snprintf(buf, sizeof(buf), "test=sensors odor=%d left=%d right=%d", o, l, r);
    status(buf);
    if (!waitOrStop(150))
      return;
  }
}

/* Run one test to completion (STOP-interruptible), then return to idle. */
void runTest(int m)
{
  mode = m;
  shutdownHardware();
  switch (m)
  {
  case T_ODORS:
    testOdors();
    break;
  case T_FLUIDS:
    testFluids();
    break;
  case T_LIGHT:
    testLight();
    break;
  case T_SENSORS:
    testSensors();
    break;
  }
  shutdownHardware();
  mode = IDLE;
  prevOdor = digitalRead(odorPort); // don't let a held poke re-trigger immediately
  status("test=idle");
}

/* Dispatch a command while idle. */
void handleCommand(const char *line)
{
  if (strcmp(line, "TEST ODORS") == 0)
    runTest(T_ODORS);
  else if (strcmp(line, "TEST FLUIDS") == 0)
    runTest(T_FLUIDS);
  else if (strcmp(line, "TEST LIGHT") == 0)
    runTest(T_LIGHT);
  else if (strcmp(line, "TEST SENSORS") == 0)
    runTest(T_SENSORS);
  else if (strcmp(line, "STATUS?") == 0)
    status("test=idle");
  // STOP while idle: nothing to stop
}

void setup()
{
  initBoxHardware(); // configure every box pin + land all outputs LOW
  Serial.begin(9600);
  status("test=idle"); // announce idle so a connected app populates immediately
}

void loop()
{
  if (commands.poll())
    handleCommand(commands.line());

  /* Manual: an odor poke while idle starts the odor test. */
  int odor = digitalRead(odorPort);
  if (mode == IDLE && odor == LOW && prevOdor == HIGH)
    runTest(T_ODORS);
  prevOdor = odor;

  if (millis() - lastStatus >= STATUS_HEARTBEAT_MS)
    status("test=idle");

  delay(pollingRate);
}

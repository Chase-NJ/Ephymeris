/*==================================
PRIME Bolus (well-triggered pulse) -- now also app-controllable.

MANUAL (unchanged):
1. Upload; trial light turns ON = ready to prime.
2. Odor poke once to start (fluid set 1); poke again to shift to set 2, etc.
   1 blink = set 1, 2 blinks = set 2.
3. Break the LEFT/RIGHT well IR beam -> one timed pulse of that side's line.
   Re-clear the beam before the next pulse.

APP CONTROL (Ephymeris Debug Mode / PASSTHROUGH):
  The app drives the same actions over serial (task.json `controls`):
    SET GEAR=1 | SET GEAR=2   -> select fluid set
    PULSE L    | PULSE R      -> one timed pulse of that side's active line
    ALLOFF                    -> close all lines (safety)
  and reads a non-persisted status line (task.json `telemetry`) after every
  change + a ~1 s heartbeat:
    STATUS gear=<0|1|2> last=<L|R|->
  (gear=0 = not started; last = the most recently pulsed side). Nothing here is
  saved -- it's live display only.
==================================*/

#include <BehaviorBox.h> // shared pinout + CommandReader (serial control) + emitStatus (telemetry)

const int pollingRate = 2; // IR sensor polling (ms)
const unsigned long STATUS_HEARTBEAT_MS = 1000;

/* Fluid delivery time per fluid line, parallel to Fluids[] (in ms). */
const int fluidDeliveryTimes[NUM_FLUIDS] = {
    200, // [0]: Left-well  reward 1
    200, // [1]: Left-well  reward 2
    200, // [2]: Right-well reward 1
    200, // [3]: Right-well reward 2
};

int gear = 0;         // 0 = fluid set 1, 1 = fluid set 2
bool started = false; // becomes true after the first gear select (poke or SET GEAR)
char lastPulse = '-'; // 'L', 'R', or '-' -- most recently pulsed side

int prevOdor = HIGH;
int prevLeft = HIGH;
int prevRight = HIGH;

CommandReader commands;
unsigned long lastStatus = 0;

/* Emit the current state as a non-persisted STATUS line for the app. */
void reportStatus()
{
  char buf[48];
  snprintf(buf, sizeof(buf), "gear=%d last=%c", started ? gear + 1 : 0, lastPulse);
  emitStatus(buf);
  lastStatus = millis();
}

/* Open the fluid solenoid at Fluids[idx] for its delivery time, then close it. */
void deliver(int idx)
{
  digitalWrite(Fluids[idx], HIGH);
  delay(fluidDeliveryTimes[idx]);
  digitalWrite(Fluids[idx], LOW);
}

/* Blink the trial light off/on `times`, leaving it ON (gear indicator). */
void flashGear(int times)
{
  for (int i = 0; i < times; i++)
  {
    digitalWrite(trialLight, LOW);
    delay(200);
    digitalWrite(trialLight, HIGH);
    delay(200);
  }
}

/* Select a fluid set (0 or 1): flash the indicator and report. Shared by the
   manual odor poke and the SET GEAR command. */
void applyGear(int g)
{
  gear = g;
  started = true;
  flashGear(gear + 1);
  reportStatus();
}

/* Pulse the active set's left/right line once. Shared by the manual well break
   and the PULSE command. */
void pulseLeft()
{
  if (!started)
    return;
  deliver(gear); // Fluids[0] (set 1) or Fluids[1] (set 2)
  lastPulse = 'L';
  reportStatus();
}
void pulseRight()
{
  if (!started)
    return;
  deliver(2 + gear); // Fluids[2] (set 1) or Fluids[3] (set 2)
  lastPulse = 'R';
  reportStatus();
}

/* Handle one whole-line command from the app. Unknown lines are ignored. */
void handleCommand(const char *line)
{
  if (strcmp(line, "ALLOFF") == 0)
  {
    for (int rwd = 0; rwd < NUM_FLUIDS; rwd++)
      digitalWrite(Fluids[rwd], LOW);
    reportStatus();
  }
  else if (strncmp(line, "SET GEAR=", 9) == 0)
  {
    int g = atoi(line + 9);
    if (g == 1 || g == 2)
      applyGear(g - 1);
  }
  else if (strcmp(line, "PULSE L") == 0)
    pulseLeft();
  else if (strcmp(line, "PULSE R") == 0)
    pulseRight();
  else if (strcmp(line, "STATUS?") == 0)
    reportStatus();
}

void setup()
{
  initBoxHardware();
  digitalWrite(trialLight, HIGH); // Light ON = ready to prime
  Serial.begin(9600);
  reportStatus();
}

void loop()
{
  /* 1. App commands (non-blocking). */
  if (commands.poll())
    handleCommand(commands.line());

  /* 2. Manual triggers (unchanged behavior). */
  int odor = digitalRead(odorPort);
  int left = digitalRead(leftWell);
  int right = digitalRead(rightWell);

  if (odor == LOW && prevOdor == HIGH)
  { // Odor poke (falling edge): start, then toggle fluid set
    if (!started)
      applyGear(0);
    else
      applyGear(gear == 0 ? 1 : 0);
  }

  if (started)
  {
    if (left == LOW && prevLeft == HIGH)
      pulseLeft(); // left well break -> pulse active left line
    if (right == LOW && prevRight == HIGH)
      pulseRight(); // right well break -> pulse active right line
  }

  prevOdor = odor;
  prevLeft = left;
  prevRight = right;

  /* 3. Status heartbeat so a late-connecting app still learns the state. */
  if (millis() - lastStatus >= STATUS_HEARTBEAT_MS)
    reportStatus();

  delay(pollingRate);
}

/*==================================
PRIME Lines (well-triggered latch) -- now also app-controllable.

MANUAL (unchanged):
1. Upload; trial light turns ON = ready to prime.
2. Odor poke once to start (fluid set 1); poke again to shift to set 2, etc.
   1 blink = set 1, 2 blinks = set 2. Shifting gears CLOSES any open line.
3. Break the LEFT/RIGHT well IR beam to LATCH that side's line open; break again
   to latch it closed. Each side latches independently.

APP CONTROL (Ephymeris Debug Mode / PASSTHROUGH):
  The app drives the same actions over serial (task.json `controls`):
    SET GEAR=1 | SET GEAR=2   -> select fluid set (closes any open line first)
    TOGGLE L   | TOGGLE R     -> latch that side's active line open/closed
    ALLOFF                    -> close both lines
  and reads a non-persisted status line (task.json `telemetry`) after every
  change + a ~1 s heartbeat:
    STATUS gear=<0|1|2> left=<open|closed> right=<open|closed>
  (gear=0 = not started yet). Nothing here is saved -- it's live display only.
==================================*/

#include <BehaviorBox.h> // shared pinout + CommandReader (serial control) + emitStatus (telemetry)

const int pollingRate = 2;      // IR sensor polling (ms)
const unsigned long STATUS_HEARTBEAT_MS = 1000; // re-report status at least this often

int gear = 0;          // 0 = fluid set 1, 1 = fluid set 2
bool started = false;  // becomes true after the first gear select (poke or SET GEAR)
bool leftOpen = false; // latch state of the active left  line
bool rightOpen = false;// latch state of the active right line

// Previous sensor states for edge-detection (HIGH = beam intact / unpoked)
int prevOdor = HIGH;
int prevLeft = HIGH;
int prevRight = HIGH;

CommandReader commands;                 // non-blocking serial command reader
unsigned long lastStatus = 0;           // last time we emitted STATUS

/* Emit the current state as a non-persisted STATUS line for the app. */
void reportStatus()
{
  char buf[48];
  snprintf(buf, sizeof(buf), "gear=%d left=%s right=%s",
           started ? gear + 1 : 0,
           leftOpen ? "open" : "closed",
           rightOpen ? "open" : "closed");
  emitStatus(buf);
  lastStatus = millis();
}

/* Close every fluid line and clear the latch state. */
void closeAllFluids()
{
  for (int rwd = 0; rwd < NUM_FLUIDS; rwd++)
    digitalWrite(Fluids[rwd], LOW);
  leftOpen = false;
  rightOpen = false;
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

/* Select a fluid set (0 or 1). Closes any open line first so fluid is never left
   running across a set change, flashes the indicator, and reports status. Shared
   by the manual odor poke and the SET GEAR command. */
void applyGear(int g)
{
  closeAllFluids();
  gear = g;
  started = true;
  flashGear(gear + 1); // 1 blink = set 1, 2 blinks = set 2
  reportStatus();
}

/* Latch the active set's left/right line open or closed. Shared by the manual
   well break and the TOGGLE command. */
void toggleLeft()
{
  if (!started)
    return;
  leftOpen = !leftOpen;
  digitalWrite(Fluids[gear], leftOpen ? HIGH : LOW); // [0] set1, [1] set2
  reportStatus();
}
void toggleRight()
{
  if (!started)
    return;
  rightOpen = !rightOpen;
  digitalWrite(Fluids[2 + gear], rightOpen ? HIGH : LOW); // [2] set1, [3] set2
  reportStatus();
}

/* Handle one whole-line command from the app. Unknown lines are ignored. */
void handleCommand(const char *line)
{
  if (strcmp(line, "ALLOFF") == 0)
  {
    closeAllFluids();
    reportStatus();
  }
  else if (strncmp(line, "SET GEAR=", 9) == 0)
  {
    int g = atoi(line + 9); // 1 or 2 on the wire
    if (g == 1 || g == 2)
      applyGear(g - 1);
  }
  else if (strcmp(line, "TOGGLE L") == 0)
    toggleLeft();
  else if (strcmp(line, "TOGGLE R") == 0)
    toggleRight();
  else if (strcmp(line, "STATUS?") == 0)
    reportStatus(); // let the app request a fresh snapshot
}

void setup()
{
  initBoxHardware();              // configure every box pin + land all outputs LOW
  digitalWrite(trialLight, HIGH); // Light ON = ready to prime
  Serial.begin(9600);
  reportStatus(); // announce initial state so a connected app populates immediately
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
      applyGear(0); // first poke -> fluid set 1
    else
      applyGear(gear == 0 ? 1 : 0); // subsequent pokes toggle the set
  }

  if (started)
  {
    if (left == LOW && prevLeft == HIGH)
      toggleLeft(); // left well break -> latch active left line
    if (right == LOW && prevRight == HIGH)
      toggleRight(); // right well break -> latch active right line
  }

  prevOdor = odor;
  prevLeft = left;
  prevRight = right;

  /* 3. Status heartbeat so a late-connecting app still learns the state. */
  if (millis() - lastStatus >= STATUS_HEARTBEAT_MS)
    reportStatus();

  delay(pollingRate);
}

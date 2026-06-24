/*==================================
PRIME Lines (well-triggered latch):
1. Upload, board resets, setup runs. Trial light turns ON  = ready to prime.
2. Odor poke once to start. Trial light flashes off/on ONCE, stays on.
   -> You are now priming fluid set 1 (Left reward 1 + Right reward 1).
3. Break the LEFT  well IR beam  -> LATCH the Left  solenoid OPEN.
   Break it again                -> latch it CLOSED.
   Break the RIGHT well IR beam  -> LATCH the Right solenoid OPEN, again -> CLOSED.
   Each side latches independently; re-clear the beam between toggles.
4. Odor poke again to "shift gears" to fluid set 2 (Left reward 2 + Right reward 2).
   Trial light flashes off/on TWICE, stays on. SHIFTING GEARS CLOSES ANY OPEN
   LINE so fluid is never left running across a set change.
5. Keep odor poking to toggle between set 1 (one flash) and set 2 (two flashes).
   To end, reset / power-cycle the Arduino.
==================================*/
const int pollingRate   = 2;  // Polling rate for IR sensors (in ms)

/*===================== Pin-mapping for Arduino =====================*/
/* IR Sensors */
const int odorPort      = 2;  // Odor port
const int rightWell     = 3;  // Right-well
const int leftWell      = 4;  // Left-well

/* Trial light & normally open vacuum */
const int trialLight    = 36; // Trial light
const int vac           = 40; // N.O.V.

/* Odor solenoids */
const int Odors[] = {
  22,                         // Odor 1
  24,                         // Odor 2
  26,                         // Odor 3
  28,                         // Odor 4
  30,                         // Odor 5
  32,                         // Odor 6
  23,                         // Odor 7
  25,                         // Odor 8
  27,                         // Odor 9
  29,                         // Odor 10
  31,                         // Odor 11
  33                          // Odor 12
};

/* Fluid Solenoids */
const int Fluids[] =          // { left , left , right , right }
{
  42,                         // [0]: Left-well reward 1
  44,                         // [1]: Left-well reward 2
  46,                         // [2]: Right-well reward 1
  48,                         // [3]: Right-well reward 2
};
/*===================================================================*/

/*=== Utility functions ===*/

/*  void closeAllFluids() {...} ->
  Closes every fluid solenoid. Used on startup and on every gear shift so
  no line is ever left latched open when the active fluid set changes.
*/
void closeAllFluids() {
  for (int rwd = 0; rwd < 4; rwd++) {
    digitalWrite(Fluids[rwd], LOW);
  }
}

/*  void flashGear(int times) {...} ->
  With the trial light starting ON, blinks it off-then-on `times` times
  and leaves it ON. Used to indicate which fluid set ("gear") is active:
  1 blink = set 1, 2 blinks = set 2.
*/
void flashGear(int times) {
  for (int i = 0; i < times; i++) {
    digitalWrite(trialLight, LOW);
    delay(200);
    digitalWrite(trialLight, HIGH);
    delay(200);
  }
}

void setup() {
  /*=== Setup Arduino pins ===*/
  for (int odor = 0; odor < 12; odor++) {         // Odor solenoids
    pinMode(Odors[odor], OUTPUT);
  }
  for (int rwd = 0; rwd < 4; rwd++) {             // Fluid solenoids
    pinMode(Fluids[rwd], OUTPUT);
  }
  pinMode(odorPort, INPUT_PULLUP);                // IR Sensors
  pinMode(leftWell, INPUT_PULLUP);
  pinMode(rightWell, INPUT_PULLUP);
  pinMode(trialLight, OUTPUT);                    // Trial light
  pinMode(vac, OUTPUT);                           // N.O.V.
  /*==========================*/

  /*=== Make sure everything's chill... ===*/
  for (int odor = 0; odor < 12; odor++) {
    digitalWrite(Odors[odor], LOW);
  }
  closeAllFluids();
  digitalWrite(vac, LOW);
  /*=======================================*/

  digitalWrite(trialLight, HIGH);                 // Light ON = ready to prime
}

int  gear        = 0;       // 0 = fluid set 1, 1 = fluid set 2
bool started     = false;   // becomes true after the first odor poke
bool leftOpen    = false;   // latch state of the active left  line
bool rightOpen   = false;   // latch state of the active right line

// Previous sensor states for edge-detection (HIGH = beam intact / unpoked)
int prevOdor  = HIGH;
int prevLeft  = HIGH;
int prevRight = HIGH;

void loop() {
  int odor  = digitalRead(odorPort);
  int left  = digitalRead(leftWell);
  int right = digitalRead(rightWell);

  /* Odor poke (falling edge): start, then toggle fluid set / "gear" */
  if (odor == LOW && prevOdor == HIGH) {
    if (!started) {
      started = true;
      gear = 0;                       // first poke -> fluid set 1
    } else {
      gear = (gear == 0) ? 1 : 0;     // subsequent pokes toggle the set
      closeAllFluids();               // never leave a line open across a shift
      leftOpen  = false;
      rightOpen = false;
    }
    flashGear(gear + 1);              // 1 blink = set 1, 2 blinks = set 2
  }

  if (started) {
    /* Left well break (falling edge) -> latch this set's left line on/off */
    if (left == LOW && prevLeft == HIGH) {
      leftOpen = !leftOpen;
      digitalWrite(Fluids[gear], leftOpen ? HIGH : LOW);     // [0] set1, [1] set2
    }
    /* Right well break (falling edge) -> latch this set's right line on/off */
    if (right == LOW && prevRight == HIGH) {
      rightOpen = !rightOpen;
      digitalWrite(Fluids[2 + gear], rightOpen ? HIGH : LOW); // [2] set1, [3] set2
    }
  }

  prevOdor  = odor;
  prevLeft  = left;
  prevRight = right;

  delay(pollingRate);
}

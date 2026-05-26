/*==================================
To Prime Fluids:
1. Odor poke once to start main loop.
2. When light is flashing, you are inbetween fluid solenoids.
3. A solid light means you are currently priming a fluid line.
4. Odor poke -> Unpoke to cycle fluid lines.
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

/*  bool verifySensor(int pin, int duration) {...} ->
  Takes a pin (IR sensor) and a duration (ms).
  Returns FALSE if sensor is interrupted.
  Returns TRUE if sensor is uninterrupted.
*/
bool verifySensor(int pin, int duration) {
  unsigned long start = millis();
  while (millis() - start < duration) {
    if (digitalRead(pin) == HIGH) {
      return false;                               // For Input Pullup, HIGH = rat unpoked
    }
    delay(pollingRate);                           // polling rate = 2ms
  }
  return true;
}

/*  void flashLight(int duration) {...} ->
  Flashes the trial light every 200ms, given a duration in ms.
*/
void flashLight(int duration) {
  unsigned long start = millis();
  while (millis() - start < duration) {
    digitalWrite(trialLight, HIGH);
    delay(200);
    digitalWrite(trialLight, LOW);
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
  for (int rwd = 0; rwd < 4; rwd++) {
    digitalWrite(Fluids[rwd], LOW);
  }
  digitalWrite(trialLight, LOW);
  digitalWrite(vac, LOW);
  /*=======================================*/
  
  while (digitalRead(odorPort)) {                 // Odor poke to start main loop
    delay(pollingRate);
  }
}

int fl = 0;   // Fluid pin index
void loop() {
  while (digitalRead(odorPort)) {
    digitalWrite(trialLight, HIGH);
    delay(200);
    digitalWrite(trialLight, LOW);
  }
  while (digitalRead(odorPort) == LOW) {
    digitalWrite(trialLight, HIGH);
    delay(200);
    digitalWrite(trialLight, LOW);
  }

  digitalWrite(trialLight, HIGH);
  digitalWrite(Fluids[fl], HIGH);

  while (digitalRead(odorPort)) {
    delay(pollingRate);
  }
  while (digitalRead(odorPort) == LOW) {
    digitalWrite(trialLight, HIGH);
    delay(200);
    digitalWrite(trialLight, LOW);
  }

  digitalWrite(Fluids[fl], LOW);
  if (fl >= 3) {
    fl = 0;
  } else {
    fl++;
  }

  delay(1000);
}

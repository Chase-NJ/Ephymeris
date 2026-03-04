/*
Author: Chase Johnston (Nov 20, 2025)
Purpose: A simple driver for our olfactometer.
*/

// Pin assignments
const int olfac = A0;           // Olfactometer line solenoid, configured such that Isoflurane cannot flow at same time
const int button = A1;          // Button
const int signal = A2;          // Pulse from signal generator
const int nitrogen = A4;        // Nitrogen line
const int odor1 = 2;
const int odor2 = 3;
const int odor3 = 4;

// Constants
const int purgeDuration = 5000;     // Duration to purge line with clean air

void setup() {
  // Inputs
  pinMode(signal, INPUT_PULLUP);
  pinMode(button, INPUT);

  // Outputs
  pinMode(olfac, OUTPUT);
  pinMode(odor1, OUTPUT);
  pinMode(odor2, OUTPUT);
  pinMode(odor3, OUTPUT);
  pinMode(nitrogen, OUTPUT);

  // Make sure everything's chill...
  digitalWrite(odor1, LOW);
  digitalWrite(odor2, LOW);
  digitalWrite(odor3, LOW);
  digitalWrite(olfac, LOW);
  digitalWrite(nitrogen, LOW);
}

/*
For olfac:
  - HIGH   = Isoflurane off, stimulus sent to rat
  - LOW  = Isoflurane on, stimulus not going to rat
*/
int odor = 0;
void loop() {
  if (digitalRead(signal)) {
    switch (odor) {
      case 0:
        digitalWrite(odor1, HIGH);
        digitalWrite(olfac, HIGH);
        break;
      case 1:
        digitalWrite(odor2, HIGH);
        digitalWrite(olfac, HIGH);
        break;
      case 2:
        digitalWrite(odor3, HIGH);
        digitalWrite(olfac, HIGH);
        break;
      case 3:
        digitalWrite(nitrogen, HIGH);
        break;
    }
  } else {
    digitalWrite(odor1, LOW);
    digitalWrite(odor2, LOW);
    digitalWrite(odor3, LOW);
    digitalWrite(nitrogen, LOW);
    digitalWrite(olfac, LOW);
  }
}

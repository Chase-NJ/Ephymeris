/*
Author: Chase Johnston
Date: February 24, 2026
Purpose:
  To provide quick access to the appropriate pin mappings and setup function
  for the Hart lab olfactometers.
*/

// Pin mappings:

// Infrared sensors
const int odorPortPin = 2;   // odor port entry
const int rightWellPin = 3;  // right well entry
const int leftWellPin = 4;   // left well entry

// Odors
const int Odors[] = 
{ 
  22,   // Odor 1
  24,   // Odor 2
  26,   // Odor 3
  28,   // Odor 4
  30,   // Odor 5
  32,   // Odor 6
  23,   // Odor 7
  25,   // Odor 8
  27,   // Odor 9
  29,   // Odor 10
  31,   // Odor 11
  33    // Odor 12
};      // Odor solenoids

// Rewards & N.O. VAC
const int vac = 40;
const int Fluids[] =
{
  42,   // Reward solenoid 1
  44,   // Reward solenoid 2
  46,   // Reward solenoid 3
  48,   // Reward solenoid 4
}

// Trial light
const int trialLightPin = 36;

void setup() {
  // Setup IR Sensors
  pinMode(odorPortPin, INPUT_PULLUP);
  pinMode(leftWellPin, INPUT_PULLUP);
  pinMode(rightWellPin, INPUT_PULLUP);

  // Outputs
    // Odors:
  for (int i = 0; i < 12; i++) {
    pinMode(Odors[i], OUTPUT);
  }
    // Rewards:
  for (int i = 0; i < 4; i++) {
    pinMode(Fluids[i], OUTPUT);
  }
    // Trial light & N.O. VAC
  pinMode(trialLightPin, OUTPUT);
  pinMode(vac, OUTPUT);

  // Make sure everything's chill...
  for (int odor = 0; odor < 12; odor++) {
    digitalWrite(Odors[odor], LOW);
  }
  for (int rwd = 0; rwd < 4; rwd++) {
    digitalWrite(Fluids[rwd], LOW);
  }

  /* BEGIN YOUR CODE HERE */

}

void loop() {
  /* FILL IN MAIN LOOP */
}

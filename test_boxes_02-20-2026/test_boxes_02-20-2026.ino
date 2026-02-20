/*
Author: Chase Johnston
Date: February 20, 2026
Purpose:
  A sketch to test the full functionality of the Hart lab behavior boxes.
  Critical functions being tested:
    1. Correct infrared sensor pin mapping
    2. Odor poke/unpoke
    3. Trial light working as intended
    4. Olfactometer system successfully delivers odor at correct time
    5. Fluid solenoid pin mapping
    6. PCB/LEDs functioning as expected
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
const int Rewards[] =
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
    pinMode(Rewards[i], OUTPUT);
  }
    // Trial light & N.O. VAC
  pinMode(trialLightPin, OUTPUT);
  pinMode(vac, OUTPUT);

  // Make sure everything's chill...
  for (int odor = 0; odor < 12; odor++) {
    digitalWrite(Odors[odor], LOW);
  }
  for (int rwd = 0; rwd < 4; rwd++) {
    digitalWrite(Rewards[rwd], LOW);
  }

  while (digitalRead(odorPortPin)) {  // Wait for odor poke to start loop
    delay(1);
  }
}

void loop() {
  testSensors();
}

// Function for testing the infrared sensors for odor port, left, and right fluid wells.
void testSensors() {
  while (digitalRead(odorPortPin)== LOW ) {
     digitalWrite(trialLightPin, HIGH);
     delay(100);
     digitalWrite(trialLightPin, LOW);
     delay(100);
  }

  digitalWrite(trialLightPin, LOW);
  delay(1000);

  while (digitalRead(leftWellPin) == LOW ) {
     digitalWrite(trialLightPin, HIGH);
     delay(5);
  }

  digitalWrite(trialLightPin,LOW);
  delay(1000);
  
  while (digitalRead(rightWellPin) == LOW ) {
     digitalWrite(trialLightPin, HIGH);
     delay(5);
  }

  digitalWrite(trialLightPin,LOW);
  delay(1000);
}

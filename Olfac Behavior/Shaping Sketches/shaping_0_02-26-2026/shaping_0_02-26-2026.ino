/*
Author: Chase Johnston
Date: February 26, 2026
Purpose:
  Sketch that adheres to the constraints of shaping stage 0.
  We're getting the new rats acclimated to their environment,
  before introducing new variables.

  Stage 0 constraints:
    - No odors
    - No N.O.V.
  
  Ctrl-F 'SHAPING STAGE 0' to see specific changes
*/

/*=== Named CONSTANTS for trial events/MatLab ==============================================================*/
#define BF_START_SESSION 221
#define BF_LIGHTS_ON 222
#define BF_LAZY_RAT 223
#define BF_ODOR_POKE 224
#define BF_ODOR_UNPOKE_EARLY 225
#define BF_ODOR_UNPOKE 226
#define BF_ODOR_OFF 247
#define BF_WATER_POKE_L 248
#define BF_WATER_POKE_R 249
#define BF_WATER_UNPOKE_EARLY_L 250
#define BF_WATER_UNPOKE_EARLY_R 251
#define BF_WATER_UNPOKE_L 254
#define BF_WATER_UNPOKE_R 255
#define BF_WATER_POKE_ERROR_L 257
#define BF_WATER_POKE_ERROR_R 258
#define BF_LICKING 231
#define BF_LIGHTS_OFF 233
#define BF_INVALID_TRIAL 234                                // Early unpoke occurs that aborts the trial, or a no-go trial.
#define BF_FLUID_L 252                                      // Delivered at start of first drop on left.
#define BF_FLUID_R 253                                      // Delivered at start of first drop on right.

// Right
#define BF_DELIVER_FLUID_G_R 229
#define BF_DELIVER_FLUID_P_R 230
#define BF_DELIVER_FLUID_B_R 308
#define BF_STOP_FLUID_G_R 357
#define BF_STOP_FLUID_P_R 358
#define BF_STOP_FLUID_B_R 359

// Left
#define BF_DELIVER_FLUID_G_L 366
#define BF_DELIVER_FLUID_P_L 367
#define BF_DELIVER_FLUID_B_L 368
#define BF_STOP_FLUID_G_L 369
#define BF_STOP_FLUID_P_L 370
#define BF_STOP_FLUID_B_L 371

// General
#define BF_MISSED_DROPS(x)                                  // 350-353 for 0-3 missed boli
#define BF_END_CORRECT_ITI 242
#define BF_END_INCORRECT_ITI 243
#define BF_PAUSE_SESSION 244                                // User hit cntrl-X
#define BF_RESUME_SESSION 245                               // User hit cntrl-Y
#define BF_END_SESSION 246                                  // User hit cntrl-N

#define BF_ODOR_POKE_ITI 360
#define BF_FLUID_POKE_ITI 361                               // Right Well
#define BF_FLUID_POKE_L_ITI 382                             // Left Well
#define BF_WATER_POKE_NONE 256                              // After a No-Go

// Trial Codes                                                                [CNJ: 02-26-2026]
#define GO_RIGHT_TRIAL 2
#define GO_LEFT_TRIAL 4

/*==========================================================================================================*/

/*======================================= Experiment Hyperparameters =======================================*/

/*=== Trial Timing Parameters (in ms) ===*/
const int errorDelay =            1000;   // Timeout for incorrect response.
const int odorPortTimeout =       8000;   // Window rat has to poke following light on.
const int odorDeliveryDuration =  50;     // Duration rat must hold poke before odor delivery AND during odor sampling.
const int fluidWellHold =         100;    // Duration rat must hold poke before fluid delivery (on correct trials).
const int fluidWellPoll =         10000;  // Window rat has to respond following successful odor sampling.
const int nogoWellPoll =          2000;   // Duration rat must withold response on NO-GO trials, following successful odor sampling.
const int earlyWellUnpoke =       1000;   // Timeout for early fluid-well unpoke (rat did not hold for fluidWellHold duration)
const int lazyRatDelay =          4000;   // Timeout for failure to initiate trial (poke once light on)
const int noPokeHoldTimeout =     4000;   // Timeout for failure to hold poke
const int standardITI =           1000;   // Intertrial interval on correct trials
const int FluidPinTimes[] = { 
                                  70,     // Left-well 1st fluid duration
                                  70,     // Left-well 2nd fluid duration
                                  70,     // Right-well 1st fluid duration
                                  70      // Right-well 2nd fluid duration
};
const int pollingRate =           2;      // Polling rate for our IR sensors (in ms)

/*=== Trial Sequence Parameters (trial codes) ===*/
const long trialSeed =            12345;  // Seed for reproducible trial sequence
const int goRightPercent =        50;     // Percentage of trials that are GO_RIGHT_TRIAL (0-100)

/*=======================================*/

int trialCodes[1000];                     // Populated in setup() via seeded randomness

int numTrials;                            // Number of trials, initialized in setup().
int trialNumber;                          // Index in the trialCodes array corresponding to the current trial.

unsigned long currentTS = 0;
unsigned long startTime = 0;
unsigned long RecStart = 0;

/*===================== Pin-mapping for Arduino =====================*/
//== IR SENSORS
const int odorPortPin = 2;    // Odor port
const int rightWellPin = 3;   // Right-well
const int leftWellPin = 4;    // Left-well

//== ODORS
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

//== REWARDS
const int Fluids[] =          // Fluid solenoids (left, left, right, right)   [CNJ: 02-26-2026]
{
  42,                         // Left-well reward 1
  44,                         // Left-well reward 2
  46,                         // Right-well reward 1
  48,                         // Right-well reward 2
};

const int trialLightPin = 36; // Trial light
const int vacSol = 40;        // N.O.V.
/*===================================================================*/

/*==========================================================================================================*/

void setup() {
  // Inputs (IR sensors)
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
  pinMode(vacSol, OUTPUT);

  // Make sure everything's chill...
  for (int odor = 0; odor < 12; odor++) {
    digitalWrite(Odors[odor], LOW);
  }
  for (int rwd = 0; rwd < 4; rwd++) {
    digitalWrite(Fluids[rwd], LOW);
  }

  Serial.begin(9600);                                       // Initialize serial com

  // Seed RNG and populate trialCodes
  randomSeed(trialSeed);
  for (int i = 0; i < 1000; i++) {
    trialCodes[i] = (random(100) < goRightPercent) ? GO_RIGHT_TRIAL : GO_LEFT_TRIAL;
  }

  trialNumber = 0;                                          // Start at trial 0
  numTrials = sizeof(trialCodes) / sizeof(trialCodes[0]);   // Number of trials we're running

  while (digitalRead(odorPortPin)) {                        // Odor poke to start main loop
    delay(pollingRate);
  }
  RecStart = millis();
  recordEvent(BF_START_SESSION);
}

/*
 *  MAIN LOOP:  Iterates through trialCodes, administering correct trial
 *              based on current trial code.
*/
void loop() {
  if (trialNumber >= numTrials) {
    return;                                                 // We ran out of trials...?
  }

  if (odorPortEntry(trialCodes[trialNumber]) == 1) {        // Odor poke and unpoke successful. Proceed with trial.
    switch(trialCodes[trialNumber]) {                       // Switch on trial code
      case 1:
        goRightTrial();                                     // SHAPING STAGE 0: Trial codes array filled with GO-RIGHT trials 
        break;
      case 2:
        goRightTrial();
        break;
      case 3:
        goLeftTrial();
        break;
      case 4:
        goLeftTrial();
        break;
      case 5:
        nogoTrial();
        break;
      case 6:
        nogoTrial();
        break;
    }
    trialNumber++;                                          // Increment trial number
  } else{
    return;                                                 // TRIAL ABORTED: Repeat current trial
  }
}

//==========================================================================================================
// Trial Logic functions:

/* 
 *   Initial odor port poke conditions. Returns 1 if all goes well,
 *   0 otherwise. 
*/
int odorPortEntry(int trialCode) {
  delay(100);                                               // let everything cool their jets
  
  /* Start a new trial */
  digitalWrite(trialLightPin, HIGH);
  recordEvent(BF_LIGHTS_ON);

/*
  // PRIME ODOR LINE                                                                                      [EEH: 06-20-2025]
    if (trialCode == 1) {                                   // GO-RIGHT (odor pin 1)
       digitalWrite(odorDeliveryPin1, HIGH);        
     } else if (trialCode == 2) {                           // GO-RIGHT (odor pin 2)
       digitalWrite(odorDeliveryPin2, HIGH);
     } else if (trialCode == 3) {                           // GO-LEFT (odor pin 3)
       digitalWrite(odorDeliveryPin3, HIGH);
     } else if (trialCode == 4) {                           // GO-LEFT (odor pin 4)
       digitalWrite(odorDeliveryPin4, HIGH);
     } else if (trialCode == 5) {                           // NO-GO (odor pin 5)
       digitalWrite(odorDeliveryPin5, HIGH);
     } else if (trialCode == 6) {                           // NO-GO (odor pin 6)
       digitalWrite(odorDeliveryPin6, HIGH);
    }
*/

// SHAPING STAGE 0: NO ODORS DURING SHAPING, so no need to prime them ^_^                                 [CNJ: 02-26-2026]

  // Wait for the rat to poke the odor port
  unsigned long startTime = millis();
  while (digitalRead(odorPortPin)) {
    if (millis() - startTime >= odorPortTimeout) {          // Abort trial if timeout
      digitalWrite(trialLightPin, LOW);
      recordEvent(BF_LIGHTS_OFF);                           // 233 - light's off
      recordEvent(BF_LAZY_RAT);                             // 223 - lazy rat, did not poke during light
       
     // TURN OFF ODOR IF TRIAL NOT INITIATED
     if (trialCode == 1) {                                  // GO-RIGHT (odor pin 1)
      digitalWrite(Odors[0], LOW);
    } else if (trialCode == 2) {                            // GO-RIGHT (odor pin 2)
      digitalWrite(Odors[1], LOW);
    } else if (trialCode == 3) {                            // GO-LEFT (odor pin 3)
      digitalWrite(Odors[2], LOW);
    } else if (trialCode == 4) {                            // GO-LEFT (odor pin 4)
      digitalWrite(Odors[3], LOW);
    } else if (trialCode == 5) {                            // NO-GO (odor pin 5)
      digitalWrite(Odors[4], LOW);
    } else if (trialCode == 6) {                            // NO-GO (odor pin 6)
      digitalWrite(Odors[5], LOW);
    }
      delay(lazyRatDelay);                                  // TIMEOUT FOR LAZY RAT (failure to initiate)
      return 0;
    }
    delay(pollingRate);                                               // Polling rate = 2ms
  }

  recordEvent(BF_ODOR_POKE);                                // 224: Rat poked the odor port
  if (verifySensor(odorPortPin, odorDeliveryDuration)) {    // HOLD THE POKE!!
    // digitalWrite(vacSol, HIGH);                          // SHAPING STAGE 0: No vacsol bc no odors     [CNJ: 02-26-2026]
    if (trialCode == 1) {                                   // GO-RIGHT trial code
      // digitalWrite(Odors[0], HIGH);                      // SHAPING STAGE 0: No odors                  [CNJ: 02-26-2026]
      recordEvent(1);                                       // Record go-right trial
      if (verifySensor(odorPortPin, odorDeliveryDuration)) {// HOLD POKE
        digitalWrite(Odors[0], LOW);
        recordEvent(BF_ODOR_OFF);
      } else {                                              // FAILED to HOLD POKE
        digitalWrite(Odors[0], LOW);
        digitalWrite(vacSol, LOW);
        recordEvent(BF_ODOR_OFF);
        recordEvent(999);                                   // 999 signals aborted after odor on (rat unpoked too early)
        digitalWrite(trialLightPin, LOW);
        recordEvent(BF_LIGHTS_OFF);
        delay(noPokeHoldTimeout);                           // Trial aborted, timeout
        return 0;
      }

    } else if (trialCode == 2) {                            // GO-RIGHT (odor pin 2) Trial odor solenoid
      digitalWrite(Odors[1], HIGH);
      recordEvent(2);                                       // GO-RIGHT trial code
      if (verifySensor(odorPortPin, odorDeliveryDuration)) {// HOLD POKE
        digitalWrite(Odors[1], LOW);
        recordEvent(BF_ODOR_OFF);
      } else {                                              // FAILED to HOLD POKE
        digitalWrite(Odors[1], LOW);
        digitalWrite(vacSol,LOW);
        recordEvent(BF_ODOR_OFF);
        recordEvent(999);                                   // 999 signals aborted after odor on (rat unpoked too early).
        digitalWrite(trialLightPin, LOW);
        recordEvent(BF_LIGHTS_OFF);
        delay(noPokeHoldTimeout);                           // Trial aborted, 4 second timeout.
        return 0;
      }

    } else if (trialCode == 3) {                            // GO-LEFT (odor pin 3) Trial odor solenoid
      digitalWrite(Odors[2], HIGH);
      recordEvent(3);                                       // GO-LEFT code as int.
      if (verifySensor(odorPortPin, odorDeliveryDuration)) {// HOLD POKE
        digitalWrite(Odors[2], LOW);
        recordEvent(BF_ODOR_OFF);
      } else {                                              // FAILED to HOLD POKE
        digitalWrite(Odors[2], LOW);
        recordEvent(BF_ODOR_OFF);
        digitalWrite(vacSol, LOW);
        recordEvent(999);                                   // 999 signals aborted after odor on (rat unpoked too early).
        digitalWrite(trialLightPin, LOW);
        recordEvent(BF_LIGHTS_OFF);
        delay(noPokeHoldTimeout);                           // Trial aborted, 4 second timeout.
        return 0;
      }

    } else if (trialCode == 4) {                            // GO-LEFT (odor pin 4) Trial odor solenoid
      digitalWrite(Odors[3], HIGH);
      recordEvent(4);                                       // GO-LEFT code as int.
      if (verifySensor(odorPortPin, odorDeliveryDuration)) {// HOLD POKE
        digitalWrite(Odors[3], LOW);
        recordEvent(BF_ODOR_OFF);
      } else {                                              // FAILED to HOLD POKE
        digitalWrite(Odors[3], LOW);
        recordEvent(BF_ODOR_OFF);
        digitalWrite(vacSol,LOW);
        recordEvent(999);                                   // 999 signals aborted after odor on (rat unpoked too early).
        digitalWrite(trialLightPin, LOW);
        recordEvent(BF_LIGHTS_OFF);
        delay(noPokeHoldTimeout);                           // Trial aborted, 4 second timeout.
        return 0;
      }

    } else if (trialCode == 5) {                            // NO-GO (odor pin 5) Trial odor solenoid
      digitalWrite(Odors[4], HIGH);
      recordEvent(105);                                     // GO-LEFT code as int.
      if (verifySensor(odorPortPin, odorDeliveryDuration)) {// HOLD POKE
        digitalWrite(Odors[4], LOW);
        recordEvent(BF_ODOR_OFF);
      } else {                                              // FAILED to HOLD POKE
        digitalWrite(Odors[4], LOW);
        recordEvent(BF_ODOR_OFF);
        digitalWrite(vacSol,LOW);
        recordEvent(999);                                   // 999 signals aborted after odor on (rat unpoked too early).
        digitalWrite(trialLightPin, LOW);
        recordEvent(BF_LIGHTS_OFF);
        delay(noPokeHoldTimeout);                           // Trial aborted, 4 second timeout.
        return 0;
      }


    } else if (trialCode == 6) {                            // NO-GO (odor pin 6) Trial odor solenoid
      digitalWrite(Odors[5], HIGH);
      recordEvent(106);                                     // NO-GO code.
      if (verifySensor(odorPortPin, odorDeliveryDuration)) {// HOLD POKE
        digitalWrite(Odors[5], LOW);
        recordEvent(BF_ODOR_OFF);
      } else {                                              // FAILED to HOLD POKE
        digitalWrite(Odors[5], LOW);
        recordEvent(BF_ODOR_OFF);
        digitalWrite(vacSol,LOW);
        recordEvent(999);                                   // 999 signals aborted after odor on (rat unpoked too early).
        digitalWrite(trialLightPin, LOW);
        recordEvent(BF_LIGHTS_OFF);
        delay(noPokeHoldTimeout);                           // Trial aborted, 4 second timeout.
        return 0;
      }
    }
  } else {
    digitalWrite(trialLightPin, LOW);
    recordEvent(BF_LIGHTS_OFF);
    recordEvent(BF_ODOR_UNPOKE_EARLY);                      // 225 (rat did not hold poke)
    digitalWrite(vacSol,LOW);
    delay(noPokeHoldTimeout);                               // Intertrial interval for failure to hold poke
    return 0;
  }

  // Unpoke after being in odor port for at least 1 second.
  while (digitalRead(odorPortPin) == LOW) {
    delay(pollingRate);                                     // polling rate = 2ms
  }
  // Rat held poke for 500ms, received odor for 500ms (holding poke), and unpoked.
  digitalWrite(vacSol,LOW);                                 // Rat finished odor sampling, close N.O. VAC
  recordEvent(BF_ODOR_UNPOKE);
  recordEvent(BF_LIGHTS_OFF);
  return 1;                                                 // Everything went well!
}

//==========================================================================================================
// Self-Contained Trial functions:

//====================================================================================
// GO-LEFT trial:

void goLeftTrial() {
  unsigned long start = millis();
  bool leftWellTriggered = false;
  bool rightWellTriggered = false;
  digitalWrite(vacSol,LOW);

  while (millis() - start < fluidWellPoll) {          // Poll left and right fluid wells for 2 seconds
    int leftStatus = digitalRead(leftWellPin);
    int rightStatus = digitalRead(rightWellPin);

    if (leftStatus == LOW) {                          // Entered left fluid well
      recordEvent(BF_WATER_POKE_L);
      leftWellTriggered = true;

      if (verifySensor(leftWellPin, fluidWellHold)) { // Hold poke
        digitalWrite(Fluids[0], HIGH);                // Give the rat its reward!
        recordEvent(BF_FLUID_L);
        delay(FluidPinTimes[1]);                      // Let it enjoy this moment - indexing solenoid 3 delay
        digitalWrite(Fluids[0], LOW);                 // Before taking it away again...
        recordEvent(BF_STOP_FLUID_G_L);

        // Wait for it to unpoke fluid well
        while (digitalRead(leftWellPin) == LOW) {
          delay(pollingRate);                         // polling rate = 2ms
        }
        recordEvent(BF_WATER_UNPOKE_L);
        recordEvent(BF_END_CORRECT_ITI);              // CORRECT CHOICE!
        digitalWrite(trialLightPin, LOW);
        break;                                        // Stop polling
      } else {
        recordEvent(BF_WATER_UNPOKE_EARLY_L);         // left fluid well too quickly
        digitalWrite(trialLightPin, LOW);
        break;                                        // Stop polling
      }
    }

    if (rightStatus == LOW) {                         // Entered right fluid well
      recordEvent(BF_WATER_POKE_R);
      rightWellTriggered = true;

      if (verifySensor(rightWellPin, fluidWellHold)) {// Hold poke
        while (digitalRead(rightWellPin) == LOW) {    // Wait for it to unpoke fluid well
          delay(pollingRate);                         // polling rate = 2ms
        }

        recordEvent(BF_WATER_UNPOKE_R);
        digitalWrite(trialLightPin, LOW);
        delay(errorDelay);
        recordEvent(BF_END_INCORRECT_ITI);            // INCORRECT CHOICE!
        break;                                        // Our friend is confused...
      } else {
        recordEvent(BF_WATER_UNPOKE_EARLY_R);         // left fluid well too quickly
        digitalWrite(trialLightPin, LOW);
        delay(errorDelay);
        break;                                        // Stop polling
      }

    }
    delay(pollingRate);                               // polling rate = 2ms
  }

  if (!leftWellTriggered && !rightWellTriggered) {    // Did nothing for 2 seconds. Send failure to respond code.
    digitalWrite(trialLightPin, LOW); 
    delay(errorDelay);
    recordEvent(BF_END_INCORRECT_ITI);                // Failure to respond is INCORRECT CHOICE!
  }

  digitalWrite(trialLightPin, LOW);                   // Turn off trial light to mark end of current trial.
  recordEvent(BF_LIGHTS_OFF);
  delay(standardITI);                                 // 1 second intertrial interval.
}


//====================================================================================
// GO-RIGHT trial:

void goRightTrial() {
  unsigned long start = millis();
  bool leftWellTriggered = false;
  bool rightWellTriggered = false;
  digitalWrite(vacSol, LOW);

  while (millis() - start < fluidWellPoll) {          // Poll left and right fluid wells 
    int leftStatus = digitalRead(leftWellPin);
    int rightStatus = digitalRead(rightWellPin);

    if (leftStatus == LOW) {                          // Entered left fluid well
      recordEvent(BF_WATER_POKE_L);
      leftWellTriggered = true;

      if (verifySensor(leftWellPin, fluidWellHold)) { // Hold poke
        while (digitalRead(leftWellPin) == LOW) {     // Wait for unpoke
          delay(pollingRate);                         // polling rate = 2ms
        }
        recordEvent(BF_WATER_UNPOKE_L);
        digitalWrite(trialLightPin, LOW);
        delay(errorDelay);
        recordEvent(BF_END_INCORRECT_ITI);
        break;                                        // Our friend is confused...
      } else {
        recordEvent(BF_WATER_UNPOKE_EARLY_L);         // left fluid well too quickly
        digitalWrite(trialLightPin, LOW);
        delay(errorDelay);
        break;                                        // Stop polling
      }
    }

    if (rightStatus == LOW) {                         // Entered right fluid well
      recordEvent(BF_WATER_POKE_R);
      rightWellTriggered = true;

      if (verifySensor(rightWellPin, fluidWellHold)) {

        digitalWrite(Fluids[2], HIGH);                // Give the rat its Kool-Aid!
        recordEvent(BF_FLUID_R);
        delay(FluidPinTimes[3]);                      // Let it enjoy this moment - indexing solenoid 1 delay
        digitalWrite(Fluids[2], LOW);                 // Before taking it away again...
        recordEvent(BF_STOP_FLUID_G_R);

        // Wait for it to unpoke fluid well
        while (digitalRead(rightWellPin) == LOW) {
          delay(pollingRate);                         // polling rate = 2ms
        }
        recordEvent(BF_WATER_UNPOKE_R);
        recordEvent(BF_END_CORRECT_ITI);              // 242: Correct choice
        digitalWrite(trialLightPin, LOW);
        break;                                        // Stop polling
      } else {
        recordEvent(BF_WATER_UNPOKE_EARLY_R);         // left fluid well too quickly
        break;                                        // Stop polling
      }
    }
    delay(pollingRate);                               // polling rate = 2ms
  }

  // Did nothing for 2 seconds. Send failure to respond code.
  if (!leftWellTriggered && !rightWellTriggered) {
    digitalWrite(trialLightPin, LOW);
    delay(errorDelay);
    recordEvent(BF_END_INCORRECT_ITI);                // Failure to respond is INCORRECT CHOICE!
  }

  digitalWrite(trialLightPin, LOW);                   // Turn off trial light to mark end of current trial.
  recordEvent(BF_LIGHTS_OFF);
  delay(standardITI);                                 // Intertrial interval.
}

//====================================================================================
// NO-GO trial:

void nogoTrial() {
  unsigned long start = millis();
  digitalWrite(vacSol,LOW);

  while (millis() - start < nogoWellPoll) {           // Poll left and right fluid wells 
    int leftStatus = digitalRead(leftWellPin);
    int rightStatus = digitalRead(rightWellPin);

    if (leftStatus == LOW) {                          // Entered left fluid well
      recordEvent(BF_WATER_POKE_L);

      if (verifySensor(leftWellPin, fluidWellHold)) { // Hold poke
        // Wait for it to unpoke fluid well
        while (digitalRead(leftWellPin) == LOW) {
          delay(pollingRate);                         // polling rate = 2ms
        }
        recordEvent(BF_WATER_UNPOKE_L);
        digitalWrite(trialLightPin, LOW);
        delay(errorDelay);
        recordEvent(BF_END_INCORRECT_ITI);
        break;                                        // Our friend is confused...
      } else {
        recordEvent(BF_WATER_UNPOKE_EARLY_L);         // left fluid well too quickly
        digitalWrite(trialLightPin, LOW);
        delay(errorDelay);
        break;                                        // Stop polling
      }
    }

    if (rightStatus == LOW) {                         // Entered right fluid well
      recordEvent(BF_WATER_POKE_R);

      if (verifySensor(rightWellPin, fluidWellHold)) {
        while (digitalRead(rightWellPin) == LOW) {    // Hold poke
          delay(pollingRate);                         // polling rate = 2ms
        }
        recordEvent(BF_WATER_UNPOKE_R);
        digitalWrite(trialLightPin, LOW);
        delay(errorDelay);
        recordEvent(BF_END_INCORRECT_ITI);
        break;                                        // Our friend is confused...
      } else {
        recordEvent(BF_WATER_UNPOKE_EARLY_R);         // left fluid well too quickly
        digitalWrite(trialLightPin, LOW);
        delay(errorDelay);
        break;                                        // Stop polling
      }
    }
    delay(pollingRate);                               // polling rate = 2ms
  }

  digitalWrite(trialLightPin, LOW);                   // Mark end of current trial
  recordEvent(BF_LIGHTS_OFF);
  delay(standardITI);                                 // Intertrial interval
}

//==========================================================================================================

//=========================================================================================================>
// UTILITY FUNCTIONS:

/*
 *  Given an eventCode (an int), outputs the code in a standardized 3-digit format.
 *  Handles sending eventCode and a timestamp to MatLab.
*/
void recordEvent(int eventCode) {
  if (eventCode < 0 || eventCode > 999) {             // Make sure it's not 4 digits
    Serial.println("An invalid event ID was given!");
    return;
  }

  if (eventCode >= 100) {                             // 3 digit code, we just print
    Serial.print(eventCode);
    Serial.print("\t");
    Serial.println(millis() - RecStart);
  } else if (eventCode >= 10) {                       // 2 digit code, prepend 1 zero.
    Serial.print("0");
    Serial.print(eventCode);
    Serial.print("\t");
    Serial.println(millis() - RecStart);
  } else {                                            // must be 1 digit
    Serial.print("00");
    Serial.print(eventCode);
    Serial.print("\t");
    Serial.println(millis() - RecStart);
  }
}

/*
 *  Takes a pin (IR sensor) and a duration (ms).
 *  Returns FALSE if sensor is interrupted.
 *  Returns TRUE if sensor is uninterrupted.
*/
bool verifySensor(int pin, int duration) {
  unsigned long start = millis();
  while (millis() - start < duration) {
    if (digitalRead(pin) == HIGH) {
      return false;                                   // For Input Pullup, HIGH = rat unpoked
    }
    delay(pollingRate);                               // polling rate = 2ms
  }
  return true;
}

/*
 *  Flashes the trial light every 200ms, given a duration in ms.
*/
void flashLight(int duration) {
  unsigned long start = millis();
  while (millis() - start < duration) {
    digitalWrite(trialLightPin, HIGH);
    delay(500);
    digitalWrite(trialLightPin, LOW);
    delay(500);
  }
}
//=========================================================================================================>

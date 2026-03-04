// Preprocessor doesn't use memory (on the arduino)... Nice!
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
#define BF_INVALID_TRIAL 234  // Strobe delivered after trial when an early unpoke occurs that aborts the trial, or a no-go trial.
#define BF_FLUID_L 252        // Delivered at start of first drop on left.
#define BF_FLUID_R 253        // Delivered at start of first drop on right.

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

#define BF_MISSED_DROPS(x)  // 350-353 for 0-3 missed boli. Sent at end of trial indicating whether the rat waited for all the boli.
#define BF_END_CORRECT_ITI 242
#define BF_END_INCORRECT_ITI 243
#define BF_PAUSE_SESSION 244   // User hit cntrl-X
#define BF_RESUME_SESSION 245  // User hit cntrl-Y
#define BF_END_SESSION 246     // User hit cntrl-N

// 3 strobes below are sent every 100ms as long as the rat is poking during the ITI.
#define BF_ODOR_POKE_ITI 360
#define BF_FLUID_POKE_ITI 361    // Right Well
#define BF_FLUID_POKE_L_ITI 382  // Left Well
#define BF_WATER_POKE_NONE 256   // After a No-Go

// Define pins for inputs and outputs
const int odorPortPin = 2;   // EEH infrared sensor for odor port entry
const int leftWellPin = 4;   // EEH infrared sensor for left fluid well entry
const int rightWellPin = 3;  // EEH infrared sensor for right fluid well entry

const int odorDeliveryPin1 = 22;   // EEH arbitrary for now -- this odor (solenoid) will be GO-LEFT (see commented out notes lines 151-159)
const int odorDeliveryPin2 = 24;   // EEH arbitrary for now - this odor (solenoid) will be GO-RIGHT (see commented out notes lines 151-159)
const int odorDeliveryPin3 = 26;   // EEH arbitrary for now - this odor (solenoid) will be NO-GO (see commented out notes lines 151-159)
const int odorDeliveryPin4 = 28;   // EEH
const int odorDeliveryPin5 = 30;   // EEH
const int odorDeliveryPin6 = 32;   // EEH
const int odorDeliveryPin7 = 23;   // EEH
const int odorDeliveryPin8 = 25;   // EEH
const int odorDeliveryPin9 = 27;   // EEH
const int odorDeliveryPin10 = 29;  // EEH
const int odorDeliveryPin11 = 31;  // EEH
const int odorDeliveryPin12 = 33;  // EEH

const int trialLightPin = 36;
const int testLightPin = 13;  // Ansel gave me an extra LED for testing. Connected to pin 13 for now.
const int vacSol = 40;         // EEH arbitrary for now

const int rwdSol1 = 42;  // EEH arbitrary for now. fluid solenoid - reward delivery for correctly performed GO-trials
const int rwdSol2 = 44;  // EEH
const int rwdSol3 = 46;  // EEH
const int rwdSol4 = 48;  // EEH

// Define trial timing parameters
const int odorPortTimeout = 4000;      // 4 seconds
const int odorPortDuration = 1000;     // 1 second
const int odorPortDuration2 = 1001;    // EEH cant remember why i had 2 different odor port durations but does not matter for now
const int odorDeliveryDuration = 500;  // 0.5 seconds

unsigned long currentTS = 0;
unsigned long startTime = 0;
unsigned long RecStart = 0;

// bool odordelivered = false; CNJ: I think I can get rid of this hopefully

// CNJ: Storing trial codes in an int array so we can iterate over them.
int trialCodes[5];  // Hard-coded size 5 for now, can change later.
int numTrials;      // Number of trials we are running. This will be initialized in setup().
int trialNumber;    // Index in the trialCodes array corresponding to the current trial.
int OdorPins[] = { 22, 24, 26, 28, 30, 32, 23, 25, 27, 29, 31, 33 };
int FluidPins[] = { 42 , 44 , 46 , 48 };
int FluidPinTimes[] = { 70 , 70 , 70 , 70 };

/*
CNJ:
  Disclaimer:
    This will look very different from the initial shell code you sent.
    All of the decisions I made and any changes I made to your original code
    were done for some specific reason or another. I try to comment why I do
    certain things as they come up in the code. If you have any questions or need me
    to explain certain decisions/parts of the code I'm more than happy to.
    All of this should be easily modifiable for a final implementation.

  What I've done:

  Useful Helper Functions:
  - Wrote the recordEvent(int eventCode) function           (Declaration on line 539).
    - This will output an eventID and timestamp (millis() - recStart) to serial monitor.
    - Highly useful given how often we are writing to serial monitor/matlab.

  - Wrote the verifySensor(int pin, int duration) function  (Declaration on line 564).
    - This checks that an infrared sensor (INPUT_PULLUP) is "activated" for the entire
      given duration.
    - This is useful, as we often need to check that the rat stays "poked" for a
      certain amount of time.

  - Wrote the flashLight(int pin, int duration) function    (Declaration on line 577).
    - This flashes the light corresponding to pin every 500ms until the duration has elapsed.
    - Mainly using this for testing purposes so I can more easily tell when certain
      conditions have been fulfilled.
    - Remove later...

  Trial Logic Functions:
  - Wrote the testOdorsTrial() function                        (Declaration on line 342).
    - Handles all conditionals and errors for a GO-LEFT trial code, including writing appropriate data to matlab.

  - Wrote the primeFluids() function                       (Declaration on line 409).
    - Handles all conditionals and errors for a GO-RIGHT trial code.

  - Wrote the nogoTrial() function                          (Declaration on line 388).
    - Handles all conditionals and errors for a NO-GO trial code.

  - Wrote the odorPortEntry(int trialCode) function         (Declaration on line 243).
    - I had to do this because I needed to distinguish aborted trials from normal ones (by having odorPortEntry return 0 or 1).
      - 0 tells us that trial was aborted (0 is false in arduino)
      - 1 tells us that odor poke/unpoke was successful (1 is true in arduino)
    - Handles the conditions for initial odor port poke and unpoke.
    - Handles aborting trials if applicable (does not iterate through trialCodes array, meaning we repeat the same trial on aborted trials).

  The main loop:
  - Iterates through the trialCodes array, delivering the correct odor solenoid
    based on trial type and subsequently performing the correct trial if odor poke/unpoke
    succeeds.
  - On non-aborted trials, we increment trialNumber to move on to the next trial.
  - On aborted trials, we simply begin the loop again with the same trial code (don't increment trialNumber).
  - Uses a switch statement to perform the correct trial type based on current trial code.
  - I have it doing nothing after we iterate through all the trials for now. If there is specific
    behavior you want it to have following completion of all trials, that can be added.

  Final Notes:
  - Obviously, this isn't the final implementation (need more odorPort pins and reward delivery pins)

  - Didn't know exactly what event codes to record in certain instances, but these can be easily
    changed later.

  - Did not know what vacSol was supposed to be used for.

  - The trialCodes array, which I'm using to store the trial types that tell us which trial to perform
    can be easily changed later to account for the actual trials we want.
    - This array's size must be declared at compile time, meaning it will not change.
    - I chose to populate the array with some placeholder trial codes for now in the setup() function.
      You could just as easily declare the values in the initial declaration of trialCodes.

  - You might be wondering why trialCodes stores ints instead of strings (ints are not always 3 digits).
    - The recordEvent function handles correctly outputting these ints to matlab in 3-digit format.
    - Ints are useful to work with, as they allow me to use the switch statement and avoid using
      C-style strings (char arrays) which can be more trouble than it's worth in this context.

  - I added all the constants (event ID codes) you gave as a preprocessor macros.
    - This let's me use the names of the codes (i.e. BF_LAZY_RAT) in code so we know what event we're recording.
    - Because I added it as a preprocessor directive, all of these values don't consume the limited arduino memory.
      - Essentially what the preprocessor is doing is replacing every occurence of (event ID name) with (event ID value)
        before compilation, thus not using memory.
*/

void setup() {
  // Set pin modes as inputs or outputs

  //EEH inputs - infrared sensors are input_pullup. uses the board's internal pullup resistor
  pinMode(odorPortPin, INPUT_PULLUP);
  pinMode(leftWellPin, INPUT_PULLUP);
  pinMode(rightWellPin, INPUT_PULLUP);

  // EEH outputs
  pinMode(odorDeliveryPin1, OUTPUT);
  pinMode(odorDeliveryPin2, OUTPUT);
  pinMode(odorDeliveryPin3, OUTPUT);
  pinMode(odorDeliveryPin4, OUTPUT);
  pinMode(odorDeliveryPin5, OUTPUT);
  pinMode(odorDeliveryPin6, OUTPUT);
  pinMode(odorDeliveryPin7, OUTPUT);
  pinMode(odorDeliveryPin8, OUTPUT);
  pinMode(odorDeliveryPin9, OUTPUT);
  pinMode(odorDeliveryPin10, OUTPUT);
  pinMode(odorDeliveryPin11, OUTPUT);
  pinMode(odorDeliveryPin12, OUTPUT);


  pinMode(trialLightPin, OUTPUT);
  pinMode(testLightPin, OUTPUT);  // CNJ: Test light pin is output
  pinMode(vacSol, OUTPUT);
  pinMode(rwdSol1, OUTPUT);
  pinMode(rwdSol2, OUTPUT);
  pinMode(rwdSol3, OUTPUT);
  pinMode(rwdSol4, OUTPUT);

  // Initialize trial light off
  digitalWrite(trialLightPin, LOW);
  digitalWrite(vacSol, LOW);

  // Initialize serial com
  Serial.begin(9600);

  // Initializing the trialCodes array with some placeholder trialCodes for testing.
  trialCodes[0] = 0;    // testOdors CHANGE BACK TO 01231
  trialCodes[1] = 1;    // test fluids
  trialCodes[2] = 2;    // prime fluids
  trialCodes[3] = 3;   // test sensors
  trialCodes[4] = 1;    // test fluids
  // We can change this initialization later to store the official codes.
  // Might be useful to write a script that can take an input file and handle that for us.
  trialNumber = 0;                                         // Begin iteration through trialCodes array at index 0.
  numTrials = sizeof(trialCodes) / sizeof(trialCodes[0]);  // bytes in whole array / bytes in 1 element gives us # of elements (trials in this case).

  // I kept this because it's useful for testing
  while (digitalRead(odorPortPin)) {  // EEH wait for odor poke to start main loop - CHANGE THIS LATER ...
    delay(1);
  }

  Serial.print(221);  //221 is session start. sends to matlab EEH
  Serial.print("\t");
  Serial.println(millis());
  RecStart = millis();
}

void loop() {
  if (trialNumber >= numTrials) {
    return;  // We have iterated through all trials so do nothing (for now)
  }
  // Begin by running initial odor port entry sequence. (This will also handle aborting trials if necessary)
  if (odorPortEntry(trialCodes[trialNumber]) == 1) {  // Odor poke and unpoke successful. Proceed with trial.
                                                      // Switches based on trial code.
    switch (trialCodes[trialNumber]) {
      case 0:
        testOdorsTrial();
        break;
      case 1:
        testFluids();
        break;
      case 2:
        primeFluids();
        break;
     case 3:
       testSensors();
        break;

    }
    trialNumber++;  // Even if we error trial, we increment trialNumber, iterating to next trial code.
  } else {
    // Odor poke and unpoke unsuccessful. Trial aborted. Repeat current trial.
    return;
  }
}

// CNJ:
//
// I am writing a function for the initial odor port poke conditions, as I will need to return something indicating we aborted, so as to not increment the array of trial codes.
// This is also useful for debugging since we can isolate issues to 1 of 4 main functions (odor port entry, and the 3 trial-handling functions).

// Handles conditionals/error codes for initial odor port entry. CNJ: (Basically just copy pasted your initial shell into here with some slight modifications).
// Function takes a trialCode (int) to deliver the appropriate odor solenoid based on trial type.
int odorPortEntry(int trialCode) {
  // let everything cool their jets
  delay(100);

  // Start a new trial
  digitalWrite(trialLightPin, HIGH);
  recordEvent(BF_LIGHTS_ON);  // CNJ: Wrote this because we write events to Matlab frequently.
  delay(10);                  // just so light on to odor port entry time is not instant...

  // Wait for the rat to poke the odor port
  unsigned long startTime = millis();
  while (digitalRead(odorPortPin)) {
    if (millis() - startTime >= odorPortTimeout) {
      // Abort trial if timeout
      digitalWrite(trialLightPin, LOW);
      recordEvent(BF_LIGHTS_OFF);  // CNJ: 233 "Light's Off." Added this to record the fact that we turn off the light but can be removed if I'm misunderstanding.
      recordEvent(BF_LAZY_RAT);    // EEH 223 - lazy rat, did not poke during light
      delay(1000);                 // 4 second intertrial interval (aka timeout) for failure to initiate
      return 0;
    }
    delay(2);  // Poll odor port every 2 milliseconds
  }
  recordEvent(BF_ODOR_POKE);  // 224: Rat poked the odor port

  // Rat poked the odor port, wait for him to remain in it for the full duration
  if (verifySensor(odorPortPin, odorDeliveryDuration)) {
    // Rat stayed in odor port for long enough, deliver the correct odor solenoid based on trial type.
    if (trialCode == 0) {  // test odors, will trigger odor solenoid1
       digitalWrite(odorDeliveryPin1, HIGH);
      recordEvent(0);                                         // GO-LEFT code.
      if (verifySensor(odorPortPin, odorDeliveryDuration)) {  // Ensure rat stays in odor port for duration of odor delivery
         digitalWrite(odorDeliveryPin1, LOW);
        recordEvent(BF_ODOR_OFF);
      } else {  // Rat did not hold poke for odor delivery duration
        digitalWrite(odorDeliveryPin1, LOW);
        recordEvent(BF_ODOR_OFF);
        recordEvent(999);  // 999 signals aborted after odor on (rat unpoked too early).
        digitalWrite(trialLightPin, LOW);
        recordEvent(BF_LIGHTS_OFF);
        // CNJ: Might want to consider adding something here to ensure rat unpokes even on aborted trials.
        delay(1000);  // Trial aborted, 4 second timeout.
        return 0;
      }
    } else if (trialCode == 1) {  // test fluids, will trigger odor2 pin
       digitalWrite(odorDeliveryPin2, HIGH);
      recordEvent(1);                                         // GO-RIGHT code as int.
      if (verifySensor(odorPortPin, odorDeliveryDuration)) {  // Ensure rat stays in odor port for duration of odor delivery
        digitalWrite(odorDeliveryPin2, LOW);
        recordEvent(BF_ODOR_OFF);
      } else {  // Rat did not hold poke for odor delivery duration
        digitalWrite(odorDeliveryPin2, LOW);
        recordEvent(BF_ODOR_OFF);
        recordEvent(999);  // 999 signals aborted after odor on (rat unpoked too early).
        digitalWrite(trialLightPin, LOW);
        recordEvent(BF_LIGHTS_OFF);
        delay(1000);  // Trial aborted, 4 second timeout.
        return 0;
      }
    } else if (trialCode == 2) {  // prime fluids, will trigger odor3
      digitalWrite(odorDeliveryPin3, HIGH);
      recordEvent(100);                                       // NO-GO code.
      if (verifySensor(odorPortPin, odorDeliveryDuration)) {  // Ensure rat stays in odor port for duration of odor delivery
        digitalWrite(odorDeliveryPin3, LOW);
        recordEvent(BF_ODOR_OFF);
      } else {  // Rat did not hold poke for odor delivery duration
        digitalWrite(odorDeliveryPin3, LOW);
        recordEvent(BF_ODOR_OFF);
        recordEvent(999);  // 999 signals aborted after odor on (rat unpoked too early).
        digitalWrite(trialLightPin, LOW);
        recordEvent(BF_LIGHTS_OFF);
        delay(1000);  // Trial aborted, 4 second timeout.
        return 0;
      }
    } else if (trialCode == 3) {  // test sensors, will trigger odor4
      digitalWrite(odorDeliveryPin4, HIGH);
      recordEvent(100);                                       // NO-GO code.
      if (verifySensor(odorPortPin, odorDeliveryDuration)) {  // Ensure rat stays in odor port for duration of odor delivery
        digitalWrite(odorDeliveryPin4, LOW);
        recordEvent(BF_ODOR_OFF);
      } else {  // Rat did not hold poke for odor delivery duration
        digitalWrite(odorDeliveryPin4, LOW);
        recordEvent(BF_ODOR_OFF);
        recordEvent(999);  // 999 signals aborted after odor on (rat unpoked too early).
        digitalWrite(trialLightPin, LOW);
        recordEvent(BF_LIGHTS_OFF);
        delay(1000);  // Trial aborted, 4 second timeout.
        return 0;
      }
    }
  } else {
    // Rat didn't stay in the odor port for long enough (didn't deliver odor), abort the trial
    digitalWrite(trialLightPin, LOW);
    recordEvent(BF_LIGHTS_OFF);
    recordEvent(BF_ODOR_UNPOKE_EARLY);  // 225 (rat did not hold poke)
    delay(1000);                        // 4 second intertrial interval for failure to hold poke
    return 0;
  }

  // Unpoke after being in odor port for at least 1 second.
  while (digitalRead(odorPortPin) == LOW) {
    delay(2);  // poll every 2ms
  }
  // CNJ: If we reach this point we know for certain: Rat held poke for 500ms, received odor for 500ms (holding poke), and unpoked.
  // Thus, we can simply record the unpoke and perform cleanup operations.
  recordEvent(BF_ODOR_UNPOKE);
  digitalWrite(trialLightPin, LOW);
  recordEvent(BF_LIGHTS_OFF);
  delay(500);  // 1 second intertrial interval.
  return 1;     // Return 1 to signal to the main loop that everything went well.
}

// Self-Contained Trial functions:

// Function for performing a test odors trials.
void testOdorsTrial() {
  unsigned long start = millis();
  int odorPortStatus = digitalRead(odorPortPin);
  delay(500);
  
  for (int odorSolenoid = 0; odorSolenoid < 12; odorSolenoid++) {
    delay(50);
    digitalWrite(OdorPins[odorSolenoid],HIGH);
    digitalWrite(vacSol,HIGH);
    unsigned long waitStart = millis();
     while (digitalRead(odorPortPin)== HIGH && millis() - waitStart < 30000) {
     delay(20);
     }
digitalWrite(OdorPins[odorSolenoid],LOW);
digitalWrite(vacSol,LOW);
delay(100);
  }
  delay(250);
}


// Function for performing a primeFluids (trial code 001) trial.
void primeFluids() {
  delay(500);

    for (int fluidSolenoid = 0; fluidSolenoid < 5 ; fluidSolenoid++) {
    delay(500);
    digitalWrite(FluidPins[fluidSolenoid],HIGH);
    unsigned long waitStart = millis();
     while (digitalRead(odorPortPin)== HIGH && millis() - waitStart < 60000) {
     delay(20);
     }
  digitalWrite(FluidPins[fluidSolenoid],LOW);
   delay(250);
  }
  delay(500);
}


// Function for performing a testFluids (trial code 001) trial.
void testFluids() {

  delay(1000);

    for (int fluidSolenoid = 0; fluidSolenoid < 5 ; fluidSolenoid++) {
    delay(500);
    digitalWrite(FluidPins[fluidSolenoid],HIGH); // drop 1
    delay(FluidPinTimes[fluidSolenoid]);
    digitalWrite(FluidPins[fluidSolenoid],LOW);
    delay(2000);

    digitalWrite(FluidPins[fluidSolenoid],HIGH); // drop 2
    delay(FluidPinTimes[fluidSolenoid]);
    digitalWrite(FluidPins[fluidSolenoid],LOW);
    delay(2000);

    digitalWrite(FluidPins[fluidSolenoid],HIGH); // drop 3
    delay(FluidPinTimes[fluidSolenoid]);
    digitalWrite(FluidPins[fluidSolenoid],LOW);
    delay(2000);

    digitalWrite(FluidPins[fluidSolenoid],HIGH); // drop 4
    delay(FluidPinTimes[fluidSolenoid]);
    digitalWrite(FluidPins[fluidSolenoid],LOW);
    delay(2000);
  }
}

// Function for performing a testSensors (trial code xx) trial.
void testSensors() {
  delay(5);
  unsigned long waitStart = millis();
  bool leftWellTriggered = false;
  bool rightWellTriggered = false;
  int odorPortStatus = digitalRead(odorPortPin);

  while ( millis() - waitStart < 10000) {
   
     while (digitalRead(odorPortPin)== LOW ) {
     digitalWrite(trialLightPin,HIGH);
     delay(10);
     digitalWrite(trialLightPin,LOW);
     delay(40);
     }
     digitalWrite(trialLightPin,LOW);

    while (digitalRead(leftWellPin)== LOW ) {
     digitalWrite(trialLightPin,HIGH);
     delay(5);
     }
     digitalWrite(trialLightPin,LOW);
  
    while (digitalRead(rightWellPin)== LOW ) {
     digitalWrite(trialLightPin,HIGH);
     delay(20);
     digitalWrite(trialLightPin,LOW);
     delay(10);
     }
     digitalWrite(trialLightPin,LOW);

  }

delay(5);
digitalWrite(trialLightPin,LOW);
}




// Function for outputting a code and timestamp to serial monitor/matlab.
// CNJ: Because it's conveient if our trialCodes array stores ints and not strings
// (switch statments in arduino dont work with strings), this function checks the
// number of digits in an event code and prepends 0's if it's < 3.
void recordEvent(int eventCode) {
  if (eventCode < 0 || eventCode > 999) {  // Make sure it's not 4 digits (could change this later).
    Serial.println("An invalid event ID was given!");
    return;
  }

  if (eventCode >= 100) {  // 3 digit code, we just print
    Serial.print(eventCode);
    Serial.print("\t");
    Serial.println(millis() - RecStart);
  } else if (eventCode >= 10) {  // 2 digit code, prepend 1 zero.
    Serial.print("0");
    Serial.print(eventCode);
    Serial.print("\t");
    Serial.println(millis() - RecStart);
  } else {  // must be 1 digit
    Serial.print("00");
    Serial.print(eventCode);
    Serial.print("\t");
    Serial.println(millis() - RecStart);
  }
}

// Given a pin (IR Sensor) and a duration (in ms), this function ensures that sensor is activated for the entire duration, uninterrupted.
// It returns false if sensor is interrupted (rat exits fluid well too fast). Otherwise it returns true.
bool verifySensor(int pin, int duration) {
  unsigned long start = millis();
  while (millis() - start < duration) {
    if (digitalRead(pin) == HIGH) {
      return false;  // For Input Pullup, when we read HIGH, it means the rat left the sensor too soon.
    }
    delay(2);  // Poll every 2ms (might need to change this if sensor is being weird).
  }
  return true;
}

// Function flashes the trial light every 500ms. Takes a duration in ms (must be divisible by 1000ms).
// CNJ: I'm using this for testing purposes, can remove later.
// void flashLight(int pin, int duration) {
//   unsigned long start = millis();
//   while (millis() - start < duration) {
//     digitalWrite(pin, HIGH);
//     delay(500); // Turn on trial light for 500ms
//     digitalWrite(pin, LOW);
//     delay(500); // Turn off trial light for 500ms
//   }
//   digitalWrite(pin, LOW); // Ensure light is off at the end.
// }

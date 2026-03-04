// Trial timestamp constants
#define BF_START_SESSION 221                  // Start of data collection
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
#define BF_INVALID_TRIAL 234
#define BF_FLUID_L 252
#define BF_FLUID_R 253

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

#define BF_MISSED_DROPS(x)                    // 350-353 for 0-3 missed boli.
#define BF_END_CORRECT_ITI 242
#define BF_END_INCORRECT_ITI 243
#define BF_PAUSE_SESSION 244                  // User hit cntrl-X
#define BF_RESUME_SESSION 245                 // User hit cntrl-Y
#define BF_END_SESSION 246                    // User hit cntrl-N

// 3 strobes below are sent every 100ms as long as the rat is poking during the ITI.
#define BF_ODOR_POKE_ITI 360
#define BF_FLUID_POKE_ITI 361                 // Right Well
#define BF_FLUID_POKE_L_ITI 382               // Left Well
#define BF_WATER_POKE_NONE 256                // After a No-Go

// Define pins for inputs and outputs
const int odorPortPin = 2;
const int leftWellPin = 4;
const int rightWellPin = 3;
const int trialLightPin = 36;

// Odor solenoids
const int Odors[] = { 
                      22, 24, 26, 28, 
                      30, 32, 23, 25,
                      27, 29, 31, 33
                    };

const int vacSol = 40;

// Reward fluid well pins
int FluidPins[] =     { 42 , 44 , 46 , 48 };
int FluidPinTimes[] = { 70 , 70 , 70 , 70 };

// Trial timing params
const int odorPortTimeout = 4000;           // 4 seconds
const int odorPortDuration = 1000;          // 1 second
const int odorDeliveryDuration = 500;       // 0.5 seconds
unsigned long currentTS = 0;
unsigned long startTime = 0;
unsigned long RecStart = 0;


int trialCodes[] = { 0, 1, 2, 3, 1 };       // Iterate through trial types
int numTrials;                              // Number of trials we are running, initialized in setup().
int trialNumber = 0;                        // Begin iteration with 1st trial

void setup() {
  // Inputs, ensure infrared sensors are INPUT_PULLUP
  pinMode(odorPortPin, INPUT_PULLUP);
  pinMode(leftWellPin, INPUT_PULLUP);
  pinMode(rightWellPin, INPUT_PULLUP);

  // Outputs
  for (int i = 0; i < 12; i++) {
    pinMode(Odors[i], OUTPUT);
  }
  for (int i = 0; i < 4; i++) {
    pinMode(FluidPins[i], OUTPUT);
  }
  pinMode(trialLightPin, OUTPUT);
  pinMode(vacSol, OUTPUT);

  // Make sure everything is chill...
  digitalWrite(trialLightPin, LOW);
  digitalWrite(vacSol, LOW);
  Serial.begin(9600);

  numTrials = sizeof(trialCodes) / sizeof(trialCodes[0]);  // Total number of trials to be run
  
  // Wait for odor poke to start main loop
  while (digitalRead(odorPortPin)) {
    delay(1);
  }

  // BEGIN THE TRIALS!!!
  Serial.print(221);
  Serial.print("\t");
  Serial.println(millis());
  RecStart = millis();
}

void loop() {
  if (trialNumber >= numTrials) {
    return;  // Rat did all that was asked of him... :)
  }
  // Odor port entry sequence
  if (odorPortEntry(trialCodes[trialNumber]) == 1) {
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
    trialNumber++;  // Go to next trial code
  } else {
    return;         // Trial aborted. Repeat current trial.
  }
}

// Handles conditionals/error codes for initial odor port entry.
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
    delay(250);
    digitalWrite(OdorPins[odorSolenoid],HIGH);
    digitalWrite(vacSol,HIGH);
    unsigned long waitStart = millis();
     while (digitalRead(odorPortPin)== HIGH && millis() - waitStart < 30000) {
     delay(20);
     }
digitalWrite(OdorPins[odorSolenoid],LOW);
digitalWrite(vacSol,LOW);
delay(250);
  }
  delay(500);
}


// Function for performing a primeFluids (trial code 001) trial.
void primeFluids() {
  unsigned long start = millis();
  bool leftWellTriggered = false;
  bool rightWellTriggered = false;
  int odorPortStatus = digitalRead(odorPortPin);
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
    delay(500);

    digitalWrite(FluidPins[fluidSolenoid],HIGH); // drop 2
    delay(FluidPinTimes[fluidSolenoid]);
    digitalWrite(FluidPins[fluidSolenoid],LOW);
    delay(500);

    digitalWrite(FluidPins[fluidSolenoid],HIGH); // drop 3
    delay(FluidPinTimes[fluidSolenoid]);
    digitalWrite(FluidPins[fluidSolenoid],LOW);
    delay(500);

    digitalWrite(FluidPins[fluidSolenoid],HIGH); // drop 4
    delay(FluidPinTimes[fluidSolenoid]);
    digitalWrite(FluidPins[fluidSolenoid],LOW);
    delay(500);
  }
}

// Function for performing a testSensors (trial code xx) trial.
void testSensors() {
  delay(5);
  unsigned long waitStart = millis();
  bool leftWellTriggered = false;
  bool rightWellTriggered = false;
  int odorPortStatus = digitalRead(odorPortPin);

  while ( millis() - waitStart < 20000) {
   
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

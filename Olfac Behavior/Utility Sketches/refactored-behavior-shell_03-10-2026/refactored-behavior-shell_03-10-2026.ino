/*
Author: Chase Johnston
Date: March 10, 2026
Purpose:
  Refactor existing behavior shell, maintaining identical functionality
  while improving the following areas:
    1. Readability
    2. Expandability
    3. User friendliness
*/

/*=== Experiment Hyperparameters ===*/
/* Trial timing parameters (in ms) */
const int errorDelay           =  2000;   // Timeout for incorrect response.
const int odorPortTimeout      =  8000;   // Window rat has to poke following light on.
const int odorPokeHold         =  1000;   // Duration rat must hold poke before odor delivery AND during odor sampling.
const int fluidWellHold        =  100;    // Duration rat must hold poke before fluid delivery (on correct trials).
const int fluidWellPoll        =  10000;  // Window rat has to respond following successful odor sampling.
const int nogoWellPoll         =  2000;   // Duration rat must withold response on NO-GO trials, following successful odor sampling.
const int earlyWellUnpoke      =  1000;   // Timeout for early fluid-well unpoke (rat did not hold for fluidWellHold duration)
const int lazyRatDelay         =  4000;   // Timeout for failure to initiate trial (poke once light on)
const int noPokeHoldTimeout    =  4000;   // Timeout for failure to hold poke
const int standardITI          =  1000;   // Intertrial interval on correct trials
const int FluidPinTimes[] = { 
                                  100,    // Left-well 1st fluid duration
                                  100,    // Left-well 2nd fluid duration
                                  100,    // Right-well 1st fluid duration
                                  100     // Right-well 2nd fluid duration
};
const int pollingRate          =  2;      // Polling rate for our IR sensors (in ms)
const int primingDelay         =  1000;   // Time odor is primed prior to trial light on
/*==================================*/

/*=== Preprocessor Macros (Trial events) ===*/
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
#define BF_LIGHTS_OFF 233             // Trial light off
#define BF_INVALID_TRIAL 234          // Early unpoke occurs that aborts the trial, or a no-go trial.
#define BF_FLUID_L 252                // Delivered at start of first drop on left.
#define BF_FLUID_R 253                // Delivered at start of first drop on right.
#define BF_DELIVER_FLUID_G_R 229
#define BF_DELIVER_FLUID_P_R 230
#define BF_DELIVER_FLUID_B_R 308
#define BF_STOP_FLUID_G_R 357
#define BF_STOP_FLUID_P_R 358
#define BF_STOP_FLUID_B_R 359
#define BF_DELIVER_FLUID_G_L 366
#define BF_DELIVER_FLUID_P_L 367
#define BF_DELIVER_FLUID_B_L 368
#define BF_STOP_FLUID_G_L 369
#define BF_STOP_FLUID_P_L 370
#define BF_STOP_FLUID_B_L 371
#define BF_MISSED_DROPS(x)            // 350-353 for 0-3 missed boli
#define BF_END_CORRECT_ITI 242
#define BF_END_INCORRECT_ITI 243
#define BF_PAUSE_SESSION 244          // User hit cntrl-X
#define BF_RESUME_SESSION 245         // User hit cntrl-Y
#define BF_END_SESSION 246            // User hit cntrl-N
#define BF_ODOR_POKE_ITI 360
#define BF_FLUID_POKE_ITI 361         // Right Well
#define BF_FLUID_POKE_L_ITI 382       // Left Well
#define BF_WATER_POKE_NONE 256        // After a No-Go

/*=== TrialType Macros ===*/
#define GO_R_1 0                      // Go-right trial odor 1
#define GO_R_2 1                      // Go-right trial odor 2
#define GO_L_1 2                      // Go-left trial odor 1
#define GO_L_2 3                      // Go-left trial odor 2
#define NO_GO_1 4                     // No-go trial odor 1
#define NO_GO_2 5                     // No-go trial odor 2
#define SENTINEL -1                   // Sentinel value, allows for useful checks...

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

/*=== MAJOR REFACTOR: TrialType & TrialWeight structs ===*/                            // [CNJ: 03/10/2026]

/* A struct that defines the differences between trial types */
struct TrialType {
  bool isGo;
  int odorPin;                // Odor solenoid pin
  int correctWell;            // pin of correct well, or -1 for no-go
  int rewardIndex;            // Index into Fluids[] AND FluidPinTimes[], or -1 for no-go
  int fluidEventCode;         // MatLab code for fluid delivery
  int stopFluidCode;          // MatLab code for fluid stop

  /* Constructor for a TrialType object */
  TrialType(bool isGo, int odorPin, int correctWell, int rewardIndex, int fluidEventCode, int stopFluidCode)
    : isGo(isGo), 
    odorPin(odorPin), 
    correctWell(correctWell), 
    rewardIndex(rewardIndex), 
    fluidEventCode(fluidEventCode), 
    stopFluidCode(stopFluidCode) {}
};

/* A struct that allows us to manipulate the proportion of trial types we administer */
struct TrialWeight {
  const TrialType* type;
  int weight;

  /* Constructor for a TrialWeight object */
  TrialWeight(const TrialType& type, int weight)
    : type(&type), weight(weight) {}
};

/* 
  For now, we have 6 trial types. Here, we define them using the TrialTypes struct. 
  Note that the constant "SENTINEL" value used during the definition of our 2 no-go
  trial types acts as a placeholder (it's actual value is -1), since there is no
  "correctWell" and thus, no rewardIndex, eventCode, etc. This is not a big deal since
  I wrote this shell to use that behavior.
*/
  // Go-Right:
const TrialType goRight1(true, Odors[0], rightWell, 2, BF_DELIVER_FLUID_G_R, BF_STOP_FLUID_G_R);
const TrialType goRight2(true, Odors[1], rightWell, 2, BF_DELIVER_FLUID_G_R, BF_STOP_FLUID_G_R);
  // Go-Left:
const TrialType goLeft1(true, Odors[2], leftWell, 0, BF_DELIVER_FLUID_G_L, BF_STOP_FLUID_G_L);
const TrialType goLeft2(true, Odors[3], leftWell, 0, BF_DELIVER_FLUID_G_L, BF_STOP_FLUID_G_L);
  // No-Go:
const TrialType noGo1(false, Odors[4], SENTINEL, SENTINEL, SENTINEL, SENTINEL);
const TrialType noGo2(false, Odors[5], SENTINEL, SENTINEL, SENTINEL, SENTINEL);

/* 
  To adjust the trial proportions, simply adjust the ratio of
  the integers (weights) associated with each trial type below.
  For example:
    1. 50%    Go-right, 50%   Go-left, 0%     No-go ->  1; 1; 1; 1; 0; 0
    2. 33.3%  Go-right, 33.3% Go-left, 33.3%  No-go ->  1; 1; 1; 1; 1; 1
    3. 66.6%  Go-right, 33.3% Go-left, 0%     No-go ->  2; 2; 1; 1; 0; 0
*/
const TrialWeight pool[] = {  /* Pool of available trial types and their weights (proportions) */
  { goRight1, 1 },            // Go-right trial --  odor 1
  { goRight2, 1 },            // Go-right trial --  odor 2
  { goLeft1,  1 },            // Go-left trial  --  odor 3
  { goLeft2,  1 },            // Go-left trial  --  odor 4
  { noGo1,    0 },            // No-go trial    --  odor 5
  { noGo2,    0 },            // No-go trial    --  odor 6
};

/*=== Trial sequence parameters ===*/
const int numTrials            = 1000;    // Number of trials to be run (size of trialCodes array)
const long trialSeed           = 12345;   // Seed for reproducible trial sequence
int currentTrial               = 0;       // Index in trials[]
bool sessionComplete           = false;   // If rat somehow completes 1000 trials...
unsigned long currentTS        = 0;       // Current time step
unsigned long startTime        = 0;       // Session start time
unsigned long RecStart         = 0;       // Recording start time
TrialType* trials[numTrials];             // Populated in setup() via seeded randomness
/*=================================*/

/*=== Utility functions ===*/

/*  void generateTrials(...) {...} ->
  Given an empty trials array, our TrialWeight pool, and a seed, this
  function populates our trials array with the desired TrialTypes,
  according to the proportions defined by TrialWeight pool[].
  This function uses seeded randomness for reproducability of the
  trial sequence.
*/
void generateTrials(const TrialType* trials[], int numTrials, long seed,
                           const TrialWeight pool[], int poolSize) {
  int totalWeight = 0;
  for (int i = 0; i < poolSize; i++) totalWeight += pool[i].weight;

  randomSeed(seed);                               // Seed our RNG
  for (int i = 0; i < numTrials; i++) {           // Iterate through trials array
    int roll = random(0, totalWeight);            // Roll a random number from 0 to { combined weight }
    int cumulative = 0;                           // Running total of weights from TrialWeights
    for (int j = 0; j < poolSize; j++) {          // Iterate through TrialWeights pool
      cumulative += pool[j].weight;               // Add current weight to running total
      if (roll < cumulative) {
        trials[i] = pool[j].type;                 // If our roll > our current running total, insert trial
        break;
      }
    }
  }
}

/*  void recordEvent(int eventCode) {...} ->
  Given an eventCode (an int), outputs the code in a standardized 3-digit format.
  Handles sending eventCode and a timestamp to MatLab.
*/
void recordEvent(int eventCode) {
  if (eventCode < 0 || eventCode > 999) {         // Make sure it's not 4 digits
    Serial.println("An invalid event ID was given!");
    return;
  }
  if (eventCode >= 100) {                         // 3 digit code, we just print
    Serial.print(eventCode);
    Serial.print("\t");
    Serial.println(millis() - RecStart);
  } else if (eventCode >= 10) {                   // 2 digit code, prepend 1 zero.
    Serial.print("0");
    Serial.print(eventCode);
    Serial.print("\t");
    Serial.println(millis() - RecStart);
  } else {                                        // must be 1 digit
    Serial.print("00");
    Serial.print(eventCode);
    Serial.print("\t");
    Serial.println(millis() - RecStart);
  }
}

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

/*=== Trial Logic Functions ===*/
bool odorSampling(TrialType trial) {
  digitalWrite(trial.odorPin, HIGH);              // 1. Prime the correct odor
  delay(primingDelay);                            // 2. Wait for priming delay
  digitalWrite(trialLight, HIGH);                 // 3. Turn on the trial light
  recordEvent(BF_LIGHTS_ON);

  unsigned long waitStart = millis();
  while (digitalRead(odorPort) == HIGH) {         // 4. Await rat to poke odorPort
    if (millis() - waitStart >= odorPortTimeout) {
      // Error 1: Rat failed to poke in time
      digitalWrite(trialLight, LOW);
      digitalWrite(trial.odorPin, LOW);
      recordEvent(BF_LAZY_RAT);
      delay(lazyRatDelay);
      return false;
    }
    delay(pollingRate);
  }
  recordEvent(BF_ODOR_POKE);

  if (!verifySensor(odorPort, odorPokeHold)) {    // 5. Verify rat holds poke (pre-odor hold)
    // Error 2: Rat didn't hold poke before vac close
    digitalWrite(trialLight, LOW);
    digitalWrite(trial.odorPin, LOW);
    recordEvent(BF_ODOR_UNPOKE_EARLY);
    delay(noPokeHoldTimeout);
    return false;
  }

  digitalWrite(vac, HIGH);                        // 6. Close vac (N.O.V.), directing odor to rat

  if (!verifySensor(odorPort, odorPokeHold)) {    // 7. Verify rat samples odor for odorPokeHold
    // Error 3: Rat didn't sample odor long enough
    digitalWrite(trialLight, LOW);
    digitalWrite(trial.odorPin, LOW);
    digitalWrite(vac, LOW);
    recordEvent(BF_ODOR_UNPOKE_EARLY);
    delay(noPokeHoldTimeout);
    return false;
  }

  digitalWrite(trial.odorPin, LOW);               // 8. Turn off odor, open vac
  digitalWrite(vac, LOW);
  recordEvent(BF_ODOR_OFF);

  while (digitalRead(odorPort) == LOW) {          // 9. Await unpoke
    delay(pollingRate);
  }
  recordEvent(BF_ODOR_UNPOKE);

  digitalWrite(trialLight, LOW);
  checkResponse(trial);                           // 10. Successful odor sampling — call checkResponse
  return true;
}

void checkResponse(TrialType trial) {
  if (trial.isGo) {                               // GO TRIAL -> poll both wells for fluidWellPoll
    unsigned long pollStart = millis();
    int pokedWell = SENTINEL;

    while (millis() - pollStart < fluidWellPoll) {// 1. Poll both wells
      if (digitalRead(rightWell) == LOW) {
        pokedWell = rightWell;
        recordEvent(BF_WATER_POKE_R);
        break;
      }
      if (digitalRead(leftWell) == LOW) {
        pokedWell = leftWell;
        recordEvent(BF_WATER_POKE_L);
        break;
      }
      delay(pollingRate);
    }

    if (pokedWell == SENTINEL) {
      // No response within timeout
      delay(errorDelay);
      return;
    }

    if (pokedWell != trial.correctWell) {
      // Error 1: Wrong well
      recordEvent(pokedWell == rightWell ? BF_WATER_POKE_ERROR_R : BF_WATER_POKE_ERROR_L);
      delay(errorDelay);
      return;
    }

    if (!verifySensor(pokedWell, fluidWellHold)) {// 3. Correct well — verify hold
      // Error 3: Didn't hold poke
      recordEvent(pokedWell == rightWell ? BF_WATER_UNPOKE_EARLY_R : BF_WATER_UNPOKE_EARLY_L);
      delay(earlyWellUnpoke);
      return;
    }

    giveReward(trial);                            // 4. Held — deliver reward
    while (digitalRead(pokedWell)) {              // Await well unpoke
      delay(pollingRate);
    }
    delay(standardITI);                           // 5. Correct-response ITI

  } else {
    unsigned long pollStart = millis();           // NO-GO TRIAL -> poll both wells for nogoWellPoll
    while (millis() - pollStart < nogoWellPoll) { // 1. Poll both wells
      if (digitalRead(rightWell) == LOW) {
        // Error 2: Rat responded on nogo
        recordEvent(BF_WATER_POKE_R);
        delay(errorDelay);
        return;
      }
      if (digitalRead(leftWell) == LOW) {
        // Error 2: Rat responded on nogo
        recordEvent(BF_WATER_POKE_L);
        delay(errorDelay);
        return;
      }
      delay(pollingRate);
    }

    delay(standardITI);                           // 2. Correctly withheld response
  }
}

void giveReward(TrialType trial) {
  int fluidPin      = Fluids[trial.rewardIndex];
  int fluidDuration = FluidPinTimes[trial.rewardIndex];

  recordEvent(trial.fluidEventCode);              // Log fluid delivery
  digitalWrite(fluidPin, HIGH);                   // Open fluid solenoid
  delay(fluidDuration);                           // Hold open for FluidPinTime
  digitalWrite(fluidPin, LOW);                    // Close fluid solenoid
  recordEvent(trial.stopFluidCode);               // Log fluid stop
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

  /*=== Populate trials array using seeded randomness */
  generateTrials(trials, numTrials, trialSeed, pool, sizeof(pool) / sizeof(pool[0]));
  
  while (digitalRead(odorPort)) {                 // Odor poke to start main loop
    delay(pollingRate);
  }
  Serial.begin(9600);                             // Initialize serial com
  RecStart = millis();
  recordEvent(BF_START_SESSION);                  // Mark start of session in MatLab

}

void loop() {
  if (sessionComplete) return;

  if (odorSampling(*trials[currentTrial])) {
    currentTrial++;                               // Advance only on successful trial
  } else {
    recordEvent(BF_INVALID_TRIAL);                // Trial aborted!!
  }

  if (currentTrial >= numTrials) {
    recordEvent(BF_END_SESSION);
    sessionComplete = true;
  }
}

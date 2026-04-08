/*
Author: Chase Johnston
Date: April 7th, 2026
Purpose:
  1. Update generateTrials function to ensure equal proportions across
      blocks of 30 trials.
  2. Added an Interrupt Service Routine (ISR) that constantly monitors
      intan's "mark-out" signal for a falling edge. When it detects one,
      we use a flag to mark that it happened, and check for it throughout
      the trial. In this way, we abort the trial at the moment we stop
      recording with Intan, ensuring the digitalIn and MatLab timestamps
      arrays are always the same size!
*/

/*============= Experiment Hyperparameters =============*/
/* Trial timing parameters (in ms) */
const int baudRate             =  9600;   // Baud rate for communication with MatLab via serial port
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
                                  100,    // Left-well  1
                                  100,    // Left-well  2
                                  100,    // Right-well 1
                                  100     // Right-well 2
};
/*======================================================*/

/* ======== Trial sequence parameters ======== */
const int pollingRate          =  2;      // Polling rate for our IR sensors (in ms)
const int primingDelay         =  1000;   // Time odor is primed prior to trial light on
const int numTrials            =  1000;   // Number of trials to be run (size of trialCodes array)
const int blockSize            =  30;     // Trials per block (proportions enforced within each block)
const long trialSeed           =  12345;  // Seed for reproducible trial sequence
int currentTrial               =  0;      // Index in trials[]
bool sessionComplete           =  false;  // If rat somehow completes 1000 trials...
volatile bool intanFell        =  false;  // Set by ISR on falling edge of intanMarkOut

/* Trial Timing */
struct TrialClock {
  unsigned long recStart       =  0;      // Timestamp at recording start
  unsigned long currentTS      =  0;      // Current timestamp

  void beginSession() {
    currentTS = millis();
    recStart = currentTS;
  }

  unsigned long elapsed() {
    currentTS = millis();
    return currentTS - recStart;          // millis() - recStart 
  }
};

TrialClock clock;                         // Encapsulates the logic for trial timestamps

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

/*===================== Pin-mapping for Arduino =====================*/
/* Intan Mark-out Input Pin */
const int intanMarkOut  = 18; // 5V Intan mark-out signal (interrupt-capable pin)
const int intanTimeSync = 9;  // Digital output signal for time synchronization with Intan

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
/* === TrialType Macros === */
#define LEFT_WELL_FL_1 0              // Index into Fluids[] & FluidPinTimes[] for fluid sol 1
#define LEFT_WELL_FL_2 1              // Index into Fluids[] & FluidPinTimes[] for fluid sol 2
#define RIGHT_WELL_FL_1 2             // Index into Fluids[] & FluidPinTimes[] for fluid sol 3
#define RIGHT_WELL_FL_2 3             // Index into Fluids[] & FluidPinTimes[] for fluid sol 4
#define SENTINEL -1                   // Sentinel value. Enables implementation of no-go trials.

/* Distinct Odor-ON Macros (Change these numbers to be whatever you want the actual codes to be) */
#define BF_ODOR_1_ON 101
#define BF_ODOR_2_ON 102
#define BF_ODOR_3_ON 103
#define BF_ODOR_4_ON 104
#define BF_ODOR_5_ON 105
#define BF_ODOR_6_ON 106

/* A struct that defines the differences between trial types */
struct TrialType {
  const bool isGo;
  const int odorPin;                // Odor solenoid pin
  const int correctWell;            // pin of correct well, or -1 for no-go
  const int rewardIndex;            // Index into Fluids[] AND FluidPinTimes[], or -1 for no-go
  const int odorOnCode;             // MatLab code for Odor on (distinct between odors)
  const int fluidEventCode;         // MatLab code for fluid delivery
  const int stopFluidCode;          // MatLab code for fluid stop

  /* Constructor for a TrialType object */
  TrialType(bool isGo, int odorPin, int correctWell, int rewardIndex, int odorOnCode, int fluidEventCode, int stopFluidCode)
    : isGo(isGo), 
    odorPin(odorPin), 
    correctWell(correctWell), 
    rewardIndex(rewardIndex),
    odorOnCode(odorOnCode), 
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

/* ===== TRIAL TYPES ===== */
// --> !!! REMEMBER: Once you CREATE a TrialType, you must also ADD IT TO THE TrialWeight POOL BELOW.
// Go Trials:
const TrialType goRight1(
  true,                   // Is this a go trial?
  Odors[0],               // Odor 1
  rightWell,              // Correct response: right fluid well
  RIGHT_WELL_FL_1,        // Index into Fluids[] & FluidPinTimes[]
  BF_ODOR_1_ON,           // MatLab code for odor on
  BF_DELIVER_FLUID_G_R,   // MatLab code for right fluid
  BF_STOP_FLUID_G_R       // MatLab code for stop right fluid
);
const TrialType goRight2(
  true, 
  Odors[1],               // Odor 2
  rightWell, 
  RIGHT_WELL_FL_1, 
  BF_ODOR_2_ON, 
  BF_DELIVER_FLUID_G_R, 
  BF_STOP_FLUID_G_R
);
const TrialType goLeft1(
  true, 
  Odors[2],               // Odor 3
  leftWell, 
  LEFT_WELL_FL_1, 
  BF_ODOR_3_ON, 
  BF_DELIVER_FLUID_G_L, 
  BF_STOP_FLUID_G_L
);
const TrialType goLeft2(
  true, 
  Odors[3],               // Odor 4
  leftWell, 
  LEFT_WELL_FL_1, 
  BF_ODOR_4_ON, 
  BF_DELIVER_FLUID_G_L, 
  BF_STOP_FLUID_G_L
);

/* Pool of available trials and their weights */
const TrialWeight pool[] = {
  { goRight1, 1 },            // Go-right trial --  odor 1
  { goRight2, 1 },            // Go-right trial --  odor 2
  { goLeft1,  1 },            // Go-left trial  --  odor 3
  { goLeft2,  1 },            // Go-left trial  --  odor 4
};

TrialType* trials[numTrials]; // Populated in setup() w/ seeded randomness

void setup() {
  /*=== Setup Arduino pins ===*/
  for (int odor = 0; odor < 12; odor++) {         // Odor solenoids
    pinMode(Odors[odor], OUTPUT);
  }
  for (int rwd = 0; rwd < 4; rwd++) {             // Fluid solenoids
    pinMode(Fluids[rwd], OUTPUT);
  }
  pinMode(intanMarkOut, INPUT);                   // Intan mark-out 5V signal
  attachInterrupt(digitalPinToInterrupt(intanMarkOut), intanFallingISR, FALLING);

  pinMode(intanTimeSync, OUTPUT);                 // 5V Digital output for time sync with Intan
  pinMode(odorPort, INPUT_PULLUP);                // IR Sensors
  pinMode(leftWell, INPUT_PULLUP);
  pinMode(rightWell, INPUT_PULLUP);
  pinMode(trialLight, OUTPUT);                    // Trial light
  pinMode(vac, OUTPUT);                           // N.O.V.

  /*=== Make sure everything's chill... ===*/
  shutdownHardware();

  /* Populate trials array using seeded randomness */
  generateTrials(trials, numTrials, trialSeed, pool, sizeof(pool) / sizeof(pool[0]));
  sessionComplete = true;                         // This causes our main loop to wait for Intan mark out to run behavior
  Serial.begin(baudRate);                         // Initialize serial com with baud rate
}

void loop() {
  /* Wait for Intan mark-out to start session!
   * We set sessionComplete = true in the setup() to satisfy this conditional
   * for the first iteration of the main loop.
  */
  if (digitalRead(intanMarkOut) == HIGH && sessionComplete) beginNewSession();
  if (intanFell) { endCurrentSession(); return; }
  if (sessionComplete) return;

  /* Run our behavior! */
  if (odorSampling(*trials[currentTrial])) {
    currentTrial++;                                     // Advance only on successful trial
    if (currentTrial >= numTrials) endCurrentSession(); // If rat completes all trials
  } else {
    if (!intanFell) recordEvent(BF_INVALID_TRIAL);      // Trial aborted (not by Intan)
  }
  if (intanFell) endCurrentSession();
}

/* ===================================== Utility functions ===================================== */

/* ISR for Intan mark-out falling edge */
void intanFallingISR() {
  intanFell = true;
}

/* Blanket turn-off of all outputs (safe to call at any time) */
void shutdownHardware() {
  for (int i = 0; i < 12; i++) digitalWrite(Odors[i], LOW);
  for (int i = 0; i < 4; i++) digitalWrite(Fluids[i], LOW);
  digitalWrite(trialLight, LOW);
  digitalWrite(vac, LOW);
}

/* Interruptible delay — returns false if intanFell fires during the wait */
bool checkedDelay(unsigned long ms) {
  unsigned long start = millis();
  while (millis() - start < ms) {
    if (intanFell) return false;
    delay(pollingRate);
  }
  return true;
}

/* Housekeeping for starting a new experiment session */
void beginNewSession() {
  intanFell = false;                              // Clear stale flag from previous session
  sessionComplete = false;
  currentTrial = 0;                               // Start at beginning of Trials array
  clock.beginSession();
  recordEvent(BF_START_SESSION);                  // Mark start of session in MatLab
}

/* Housekeeping for ending the current experiment session */
void endCurrentSession() {
  shutdownHardware();
  sessionComplete = true;
  recordEvent(BF_END_SESSION);
}

/*  void generateTrials(...) {...} ->
  Given an empty trials array, our TrialWeight pool, and a seed, this
  function populates our trials array with the desired TrialTypes,
  according to the proportions defined by TrialWeight pool[].

  Trials are generated in blocks of blockSize. Within each block,
  exact proportions are enforced (with any remainder slots assigned
  via weighted random), and the block is then shuffled.
*/
void generateTrials(const TrialType* trials[], int numTrials, long seed,
                           const TrialWeight pool[], int poolSize) {
  int totalWeight = 0;
  for (int i = 0; i < poolSize; i++) totalWeight += pool[i].weight;

  randomSeed(seed);                               // Seed our RNG

  for (int blockStart = 0; blockStart < numTrials; blockStart += blockSize) {
    int curBlockSize = min(blockSize, numTrials - blockStart);
    int filled = 0;

    // 1. Fill block with exact proportional counts
    for (int i = 0; i < poolSize; i++) {
      int count = (long)curBlockSize * pool[i].weight / totalWeight;
      for (int j = 0; j < count; j++) {
        trials[blockStart + filled++] = pool[i].type;
      }
    }

    // 2. Distribute any remainder slots via weighted random
    while (filled < curBlockSize) {
      int roll = random(0, totalWeight);
      int cumulative = 0;
      for (int j = 0; j < poolSize; j++) {
        cumulative += pool[j].weight;
        if (roll < cumulative) {
          trials[blockStart + filled++] = pool[j].type;
          break;
        }
      }
    }

    // 3. Fisher-Yates shuffle the block
    for (int i = curBlockSize - 1; i > 0; i--) {
      int j = random(0, i + 1);
      const TrialType* temp = trials[blockStart + i];
      trials[blockStart + i] = trials[blockStart + j];
      trials[blockStart + j] = temp;
    }
  }
}

/*  void recordEvent(int eventCode) {...} ->
  Given an eventCode (an int), outputs the code in a standardized 3-digit format.

  Handles sending eventCode and a timestamp to MatLab.
  
  Also handles sending a short digital 5V pulse to a recording                         // [CNJ: 04/03/2026]
   controller (if you have one connected).  
*/
void recordEvent(int eventCode) {
  unsigned long timestamp = clock.elapsed();
  char buf[16];

  digitalWrite(intanTimeSync, HIGH);              // Pulse Intan recording controller
  delay(pollingRate);
  digitalWrite(intanTimeSync, LOW);

  sprintf(buf, "%03d\t%lu", eventCode, timestamp);// Store print line to MatLab in a buffer
  Serial.println(buf);                            // Print buffer to serial
}

/*  bool verifySensor(int pin, int duration) {...} ->
  Takes a pin (IR sensor) and a duration (ms).
  Returns FALSE if sensor is interrupted.
  Returns TRUE if sensor is uninterrupted.
*/
bool verifySensor(int pin, int duration) {
  unsigned long start = millis();
  while (millis() - start < duration) {
    if (intanFell) return false;                  // Abort on Intan falling edge
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
    delay(pollingRate);
    digitalWrite(trialLight, LOW);
    delay(pollingRate);
  }
}

/*===============================================================================================*/

/*=== Trial Logic Functions ===*/
bool odorSampling(TrialType trial) {
  digitalWrite(trial.odorPin, HIGH);              // 1. Prime the correct odor
  if (!checkedDelay(primingDelay)) return false;  // 2. Wait for priming delay
  digitalWrite(trialLight, HIGH);                 // 3. Turn on the trial light
  recordEvent(BF_LIGHTS_ON);

  unsigned long waitStart = millis();
  while (digitalRead(odorPort) == HIGH) {         // 4. Await rat to poke odorPort
    if (intanFell) return false;
    if (millis() - waitStart >= odorPortTimeout) {
      // Error 1: Rat failed to poke in time
      digitalWrite(trialLight, LOW);
      digitalWrite(trial.odorPin, LOW);
      recordEvent(BF_LAZY_RAT);
      checkedDelay(lazyRatDelay);
      return false;
    }
    delay(pollingRate);
  }
  recordEvent(BF_ODOR_POKE);

  if (!verifySensor(odorPort, odorPokeHold)) {    // 5. Verify rat holds poke (pre-odor hold)
    // Error 2: Rat didn't hold poke before vac close
    digitalWrite(trialLight, LOW);
    digitalWrite(trial.odorPin, LOW);
    if (intanFell) return false;
    recordEvent(BF_ODOR_UNPOKE_EARLY);
    checkedDelay(noPokeHoldTimeout);
    return false;
  }

  recordEvent(trial.odorOnCode);                  // Send code to MatLab for trial-specific odor
  digitalWrite(vac, HIGH);                        // 6. Close vac (N.O.V.), directing odor to rat

  if (!verifySensor(odorPort, odorPokeHold)) {    // 7. Verify rat samples odor for odorPokeHold
    // Error 3: Rat didn't sample odor long enough
    digitalWrite(trialLight, LOW);
    digitalWrite(trial.odorPin, LOW);
    digitalWrite(vac, LOW);
    if (intanFell) return false;
    recordEvent(BF_ODOR_UNPOKE_EARLY);
    checkedDelay(noPokeHoldTimeout);
    return false;
  }

  digitalWrite(trial.odorPin, LOW);               // 8. Turn off odor, open vac
  digitalWrite(vac, LOW);
  recordEvent(BF_ODOR_OFF);

  while (digitalRead(odorPort) == LOW) {          // 9. Await unpoke
    if (intanFell) return false;
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
      if (intanFell) return;
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
      checkedDelay(errorDelay);
      return;
    }

    if (pokedWell != trial.correctWell) {
      // Error 1: Wrong well
      recordEvent(pokedWell == rightWell ? BF_WATER_POKE_ERROR_R : BF_WATER_POKE_ERROR_L);
      checkedDelay(errorDelay);
      return;
    }

    if (!verifySensor(pokedWell, fluidWellHold)) {// 3. Correct well — verify hold
      // Error 3: Didn't hold poke
      if (intanFell) return;
      recordEvent(pokedWell == rightWell ? BF_WATER_UNPOKE_EARLY_R : BF_WATER_UNPOKE_EARLY_L);
      checkedDelay(earlyWellUnpoke);
      return;
    }

    giveReward(trial);                            // 4. Held — deliver reward
    while (digitalRead(pokedWell)) {              // Await well unpoke
      if (intanFell) return;
      delay(pollingRate);
    }
    checkedDelay(standardITI);                    // 5. Correct-response ITI

  } else {
    unsigned long pollStart = millis();           // NO-GO TRIAL -> poll both wells for nogoWellPoll
    while (millis() - pollStart < nogoWellPoll) { // 1. Poll both wells
      if (intanFell) return;
      if (digitalRead(rightWell) == LOW) {
        // Error 2: Rat responded on nogo
        recordEvent(BF_WATER_POKE_R);
        checkedDelay(errorDelay);
        return;
      }
      if (digitalRead(leftWell) == LOW) {
        // Error 2: Rat responded on nogo
        recordEvent(BF_WATER_POKE_L);
        checkedDelay(errorDelay);
        return;
      }
      delay(pollingRate);
    }

    checkedDelay(standardITI);                    // 2. Correctly withheld response
  }
}

void giveReward(TrialType trial) {
  int fluidPin      = Fluids[trial.rewardIndex];
  int fluidDuration = FluidPinTimes[trial.rewardIndex];

  recordEvent(trial.fluidEventCode);              // Log fluid delivery
  digitalWrite(fluidPin, HIGH);                   // Open fluid solenoid
  checkedDelay(fluidDuration);                    // Hold open for FluidPinTime
  digitalWrite(fluidPin, LOW);                    // Close fluid solenoid
  recordEvent(trial.stopFluidCode);               // Log fluid stop
}

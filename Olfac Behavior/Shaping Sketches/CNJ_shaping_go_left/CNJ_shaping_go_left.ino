/*
Author: Chase Johnston
Date: May 8th, 2026
Purpose:
  Implement correct shaping paradigm:
  - Adjust odorPokeHold, fluidWellHold, fluidWellPoll, and odorPortTimeout as experiment progresses.
  - We are shaping them on a goRight trial using 
*/

/*============= Experiment Hyperparameters =============*/
/* Trial timing parameters (in ms) */
const int baudRate             =  9600;   // Baud rate for communication with MatLab via serial port
const int errorDelay           =  20000;  // Timeout for incorrect response.
int odorPortTimeout            =  8000;   // Window rat has to poke following light on.
int odorPokeHold               =  50;     // Duration rat must hold poke before odor delivery AND during odor sampling. (ms)
int fluidWellHold              =  100;    // Duration rat must hold poke before fluid delivery (on correct trials). (ms)
int fluidWellPoll              =  10000;  // Window rat has to respond following successful odor sampling.
const int nogoWellPoll         =  2000;   // Duration rat must withold response on NO-GO trials, following successful odor sampling.
const int lazyRatDelay         =  4000;   // Timeout for failure to initiate trial (poke once light on)
const int noPokeHoldTimeout    =  4000;   // Timeout for failure to hold poke
const int standardITI          =  4000;   // Intertrial interval on correct trials
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
#define BF_START_SESSION        221       // Sent at recording start (timestamp 0)
#define BF_LIGHTS_ON            222       // Sent when trialLight is written HIGH
#define BF_LAZY_RAT             223       // Sent when rat fails to initiate trial
#define BF_ODOR_POKE            224       // Sent when rat pokes odor port
#define BF_ODOR_UNPOKE_EARLY    225       // Sent when rat fails to hold odor poke for odorPokeHold
#define BF_ODOR_UNPOKE          226       // Sent after rat successfully samples odor
#define BF_ODOR_OFF             247       // Sent when we close N.O.V. (directing odor AWAY from odor port)
#define BF_WATER_POKE_L         248       // Sent when rat pokes left fluid well
#define BF_WATER_POKE_R         249       // Sent when rat pokes right fluid well
#define BF_WATER_UNPOKE_EARLY_L 250       // Sent when rat fails to hold for fluidWellHold
#define BF_WATER_UNPOKE_EARLY_R 251       // Sent when rat fails to hold for fluidWellHold
#define BF_WATER_UNPOKE_L       254       // Sent when rat unpokes left well
#define BF_WATER_UNPOKE_R       255       // Sent when rat unpokes right well
#define BF_WATER_POKE_ERROR_L   257       // Sent when rat incorrectly responds at left well
#define BF_WATER_POKE_ERROR_R   258       // Sent when rat incorrectly responds at right well
#define BF_LIGHTS_OFF           233       // Trial light off
#define BF_INVALID_TRIAL        234       // Trial is aborted (either lazy rat or poke hold failure)
#define BF_FLUID_L              252       // Delivered at start of first drop on left.
#define BF_FLUID_R              253       // Delivered at start of first drop on right.
#define BF_STOP_FLUID_G_R       357       // Sent when we stop right well fluid delivery
#define BF_STOP_FLUID_G_L       369       // Sent when we stop left well fluid delivery
#define BF_END_CORRECT_ITI      242       // Sent after correct response intertrial interval
#define BF_END_INCORRECT_ITI    243       // Sent after errorDelay intertrial interval
#define BF_END_SESSION          246       // Sent at end of session (sessionComplete = true)
#define BF_WATER_POKE_NONE      256       // After a correct response on a No-Go trial

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
  BF_FLUID_R,             // MatLab code for right fluid
  BF_STOP_FLUID_G_R       // MatLab code for stop right fluid
);
const TrialType goRight2(
  true, 
  Odors[1],               // Odor 2
  rightWell, 
  RIGHT_WELL_FL_1, 
  BF_ODOR_2_ON, 
  BF_FLUID_R, 
  BF_STOP_FLUID_G_R
);
const TrialType goLeft1(
  true, 
  Odors[2],               // Odor 3
  leftWell, 
  LEFT_WELL_FL_1, 
  BF_ODOR_3_ON, 
  BF_FLUID_L, 
  BF_STOP_FLUID_G_L
);
const TrialType goLeft2(
  true, 
  Odors[3],               // Odor 4
  leftWell, 
  LEFT_WELL_FL_1, 
  BF_ODOR_4_ON, 
  BF_FLUID_L, 
  BF_STOP_FLUID_G_L
);

/* Pool of available trials and their weights */                      // SHAPING: Shaping with 1 odor, a go-left.
const TrialWeight pool[] = {
  { goRight1, 0 },            // Go-right trial --  odor 1
  { goRight2, 0 },
  { goLeft1,  1 },            // Go-left trial --   odor 3
  { goLeft2,  0 }
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
  pinMode( odorPort , INPUT_PULLUP );             // IR Sensors
  pinMode( leftWell , INPUT_PULLUP );
  pinMode( rightWell , INPUT_PULLUP );

  pinMode( trialLight , OUTPUT );                 // Trial light
  pinMode( vac , OUTPUT );                        // N.O.V.

  /*=== Make sure everything's chill... ===*/
  shutdownHardware();

  /* Populate trials array using seeded randomness */
  generateTrials(
    trials,     // Empty trials array of size numTrials
    numTrials,  // Cutoff number
    trialSeed,  // Seed for reproducability
    pool,       // Pool of available TrialTypes
    sizeof(pool) / sizeof(pool[0])
  );
  sessionComplete = true;                         // This causes our main loop to wait for Intan mark out to run behavior
  Serial.begin(baudRate);                         // Initialize serial com with baud rate

  /* Wait for odor poke to begin */
  while (digitalRead(odorPort) == HIGH) {
    delay(pollingRate);
  }
  while (digitalRead(odorPort) == LOW) {
    digitalWrite(trialLight, HIGH);
    delay(pollingRate);
    digitalWrite(trialLight, LOW);
    delay(pollingRate);
  }

  beginNewSession();                              // Start session!
}

// Stage 1: 100ms Total Time in Port (ttip), 100ms fluid well hold, 10sec fluid well poll
void loop() {
  if (sessionComplete) return;

  /* Run our behavior! */
  if (odorSampling(*trials[currentTrial])) {
    currentTrial++;                                     // Advance only on successful trial
    if (currentTrial >= numTrials) endCurrentSession(); // If rat completes all trials

    /* Behavior shaping logic: */
    switch (currentTrial) {
      case 25:              // Stage 2: 250ms total time in port (ttip), 250ms fluid hold, 5sec fluid well poll
        odorPokeHold = 125;
        fluidWellHold = 250;
        fluidWellPoll = 5000;
        break;
      case 50:              // Stage 3: 500ms ttip, 500ms fluid hold, odor port timeout = 4 secs., 2sec fluid well poll
        odorPokeHold = 250;
        fluidWellHold = 500;
        odorPortTimeout = 4000;
        fluidWellPoll = 2000;
        break;
      case 100:             // Stage 4: 1 second ttip, 500ms fluid hold
        odorPokeHold = 500;
        break;
      default:
        // do nothing
        break;
    }
  } else {
    recordEvent(BF_INVALID_TRIAL);                      // Trial aborted
  }
}

/* ===================================== Utility functions ===================================== */

/* Blanket turn-off of all outputs (safe to call at any time) */
void shutdownHardware() {
  for (int i = 0; i < 12; i++) digitalWrite(Odors[i], LOW);
  for (int i = 0; i < 4; i++) digitalWrite(Fluids[i], LOW);
  digitalWrite(trialLight, LOW);
  digitalWrite(vac, LOW);
}

/* Housekeeping for starting a new experiment session */
void beginNewSession() {
  clock.beginSession();                           // Initialize clock on rising edge

  sessionComplete = false;
  currentTrial = 0;                               // Start at beginning of Trials array
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
*/
void recordEvent(int eventCode) {
  unsigned long timestamp = clock.elapsed();
  char buf[16];

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

  recordEvent(trial.odorOnCode);                  // Send code to MatLab for trial-specific odor
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
  if (checkResponse(trial)) {                     // 10. Successful odor sampling — call checkResponse
    delay(standardITI);                           // Correct response ITI
    recordEvent(BF_END_CORRECT_ITI);
  } else {
    delay(errorDelay);
    recordEvent(BF_END_INCORRECT_ITI);
  }
  return true;
}

bool checkResponse(TrialType trial) {
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
      return false;
    }

    if (pokedWell != trial.correctWell) {
      // Error 1: Wrong well
      recordEvent(pokedWell == rightWell ? BF_WATER_POKE_ERROR_R : BF_WATER_POKE_ERROR_L);
      return false;
    }

    if (!verifySensor(pokedWell, fluidWellHold)) {// 3. Correct well — verify hold
      // Error 2: Didn't hold poke
      recordEvent(pokedWell == rightWell ? BF_WATER_UNPOKE_EARLY_R : BF_WATER_UNPOKE_EARLY_L);
      return false;
    }

    giveReward(trial);                            // 4. Held — deliver reward
    while (digitalRead(pokedWell)) {              // Await well unpoke
      delay(pollingRate);
    }

  } else {
    unsigned long pollStart = millis();           // NO-GO TRIAL -> poll both wells for nogoWellPoll
    while (millis() - pollStart < nogoWellPoll) { // 1. Poll both wells
      if (digitalRead(rightWell) == LOW) {
        // Error 3: Rat responded on nogo
        recordEvent(BF_WATER_POKE_R);
        return false;
      }
      if (digitalRead(leftWell) == LOW) {
        // Error 3: Rat responded on nogo
        recordEvent(BF_WATER_POKE_L);
        return false;
      }
      delay(pollingRate);
    }
    recordEvent(BF_WATER_POKE_NONE);              // No-go trial! :)
  }

  return true;                                    // Rat responded correctly
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

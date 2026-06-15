/*
Author: Chase Johnston
Date: June 11th, 2026
Purpose:
  A binary odor discrimination task.
    Odor 1 - Go-right - SANDALWOOD      ->  ~50% of trials
    Odor 3 - Go-left  - ORANGE EXTRACT  ->  ~50% of trials

  This update closes three non-odor routes to reward, so the rat is
  pushed onto the odor as the only reliable predictor of the rewarded side:

  - Per-session random seed: the RNG is seeded from micros() captured the
    instant START is received (entropy from the operator's click), so the
    trial stream differs every session. The seed is emitted on its own
    "SEED\t<value>" line so the host can log it for reconstruction. Set
    USE_FIXED_SEED to fall back to the reproducible trialSeed instead.

  - Adaptive anti-bias selection: trials are chosen live (selectNextTrial)
    rather than from a fixed pre-generated array. The next trial's correct
    side is drawn with a probability nudged AGAINST the rat's recent
    expressed side preference (clamped so it never becomes deterministic
    alternation), with a hard cap on consecutive identical correct sides.
    A persistent fixed-side strategy is therefore unprofitable.

  - Dummy-click masking: with one solenoid per odor, the odor valve's click
    can predict side. During priming we fire a randomized subset of the four
    spare valves (Odors[8..11]) at randomized offsets, so the acoustic scene
    is decorrelated from the rewarded side. NOTE: cannot perfectly hide which
    real valve fired, a shared final-valve manifold is the only guarantee.

  Also: well polling order is randomized per trial so a near-simultaneous
  L/R double-break no longer always resolves to the right well.

  Per-outcome response timeouts: checkResponse returns the delay to administer
  (standardITI = correct, noPokeHoldTimeout = failed to hold correct well,
  errorDelay = wrong well / no response).

  Correction trials: the Python GUI sends the number of leading correction
  trials with the START token ("START 10"). While currentTrial is within that
  block, an incorrect response repeats the same trial (we only advance on a
  correct response). Past the block, we advance regardless of correctness.
*/

/*============= Experiment Hyperparameters =============*/
/* Trial timing parameters (in ms) */
const int baudRate             =  9600;   // Baud rate for communication with MatLab via serial port
const int errorDelay           =  20000;  // Timeout for incorrect response.
const int odorPortTimeout      =  4000;   // Window rat has to poke following light on.
const int odorPokeHold         =  500;    // Duration rat must hold poke before odor delivery AND during odor sampling. (ms)
const int fluidWellHold        =  500;    // Duration rat must hold poke before fluid delivery (on correct trials). (ms)
const int fluidWellPoll        =  2000;   // Window rat has to respond following successful odor sampling.
const int nogoWellPoll         =  2000;   // Duration rat must withold response on NO-GO trials, following successful odor sampling.
const int lazyRatDelay         =  4000;   // Timeout for failure to initiate trial (poke once light on)
const int noPokeHoldTimeout    =  5000;   // Timeout for failure to hold poke
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
const int primingJitter        =  200;    // +/- ms jitter on primingDelay (breaks click->light latency cue)
const int numTrials            =  1000;   // Number of trials to be run (session cap)
const long trialSeed           =  12345;  // Reproducible-mode seed (used only when USE_FIXED_SEED)
#define USE_FIXED_SEED 0                   // 1 -> seed from trialSeed; 0 -> seed from micros() at START
int currentTrial               =  0;      // # of trials advanced this session
int numCorrectionTrials        =  0;      // # of leading correction trials (set by GUI via START)
bool sessionComplete           =  false;  // If rat somehow completes numTrials...

/* ===== Adaptive anti-bias selection ===== */
const int   biasWindow         =  20;     // sliding window of recent expressed choices
const float debiasStrength     =  0.5;    // how hard to push the correct side against the rat's bias
const float pSideMin           =  0.10;   // clamp on P(correct side) so selection never goes deterministic
const float pSideMax           =  0.90;
const int   maxConsecutiveSide =  3;      // hard cap on consecutive identical correct sides

/* ===== Dummy-click masking ===== */
const int DUMMY_OFFSET         =  8;      // Odors[8..11] are spare, unodorized dummy-click valves
const int NUM_DUMMY            =  4;      // number of dummy valves
const int dummyPulseMs         =  20;     // brief energize -> audible click, no meaningful flow

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

/* Distinct Odor-ON Macros */
#define BF_ODOR_1_ON 101
#define BF_ODOR_2_ON 102
#define BF_ODOR_3_ON 103
#define BF_ODOR_4_ON 104
#define BF_ODOR_5_ON 105
#define BF_ODOR_6_ON 106

/* Dummy-click strobes: dummy valve i (Odors[DUMMY_OFFSET + i]) -> BF_DUMMY_CLICK_BASE + i */
#define BF_DUMMY_CLICK_BASE 110           // 110, 111, 112, 113 for the four spare valves

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

/*=== TrialType struct ===*/                                                          // [CNJ: 03/10/2026]
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

/* ===== TRIAL TYPES ===== */
// Two go trials -- one per side. selectNextTrial() (below) picks between
// these live, using the adaptive anti-bias logic, rather than a fixed pool.
// Go Trials:
const TrialType goRight1(
  true,                   // Is this a go trial?
  Odors[0],               // Odor 1
  rightWell,              // Correct response: right fluid well
  RIGHT_WELL_FL_1,        // Index into Fluids[] & FluidPinTimes[]
  BF_ODOR_1_ON,           // Strobe for odor on
  BF_FLUID_R,             // Strobe for right fluid
  BF_STOP_FLUID_G_R       // Strobe for stop right fluid
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

/* ===== Anti-bias selector state =====
   Tracks the rat's recent EXPRESSED side preference (which well it poked,
   correct or wrong) in a ring buffer, so selectNextTrial() can push the
   next correct side against any developing bias. */
int  choiceRing[biasWindow];       // 1 = went right, 0 = went left
int  choiceRingLen = 0;            // # of valid entries (<= biasWindow)
int  choiceRingIdx = 0;            // next write position
int  rightInWindow = 0;            // running count of rights in the ring

int  lastSelectedSide = SENTINEL;  // rightWell / leftWell of the last fresh selection
int  selectedSideRun  = 0;         // consecutive fresh selections on lastSelectedSide

const TrialType* currentTrialPtr = nullptr;  // current trial; re-selected only when we advance

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

  sessionComplete = true;                         // session start / end guard
  Serial.begin(baudRate);                         // Initialize serial com with baud rate

  /* Wait for the START token from the Python GUI.
     1. The host opens the port (which resets the Mega via DTR).
     2. We land here, announce READY so the GUI can arm its START button.
     3. Block until we receive a "START" line, optionally carrying the
        correction-trial count (e.g. "START 10"; a bare "START" means 0). */
  digitalWrite(trialLight, HIGH);                 // Light on == armed, waiting for GO
  delay(50);                                      // Let the post-reset serial settle
  Serial.println("READY");                        // Tell the GUI we're ready to begin

  char cmd[16];
  while (true) {
    if (readLineInto(cmd, sizeof(cmd)) && strncmp(cmd, "START", 5) == 0
        && (cmd[5] == '\0' || cmd[5] == ' ')) {
      numCorrectionTrials = atoi(cmd + 5);        // optional count after START; 0 if absent
      break;                                      // START received -- begin session
    }
  }

  /* Seed the RNG the instant START arrives -- the entropy is the operator's
     click timing, so every session draws a fresh trial stream. Emit the seed
     on its own line so the host can log it and reconstruct the session. */
  unsigned long sessionSeed = USE_FIXED_SEED ? (unsigned long)trialSeed : micros();
  randomSeed(sessionSeed);
  Serial.print("SEED\t");
  Serial.println(sessionSeed);

  digitalWrite(trialLight, LOW);
  beginNewSession();                              // Start session! (stamps t=0, fires BF_START_SESSION)
}

// Main loop:
void loop() {
  if (sessionComplete) return;

  /* Honor a remote STOP from the host GUI. Checked once per trial
     boundary (not mid-trial), so a stop never truncates a trial --
     this keeps the strobe stream's triplet structure intact for
     downstream analysis. If a STOP is seen we end cleanly here and
     fall through; the sessionComplete guard above idles us next pass. */
  if (checkForStop()) {
    endCurrentSession();
    return;
  }

  /* Pick the next trial live. We only re-select when the previous trial
     ADVANCED; a trial that returns false (an abort, or an in-block
     correction error) keeps currentTrialPtr so the SAME side is re-presented
     -- preserving the original repeat-the-same-trial semantics. */
  if (currentTrialPtr == nullptr) {
    currentTrialPtr = selectNextTrial();
  }

  /* Run our behavior! */
  if (odorSampling(*currentTrialPtr)) {
    currentTrial++;                                     // Advance only on a completed/advancing trial
    currentTrialPtr = nullptr;                          // force a fresh selection next loop
    if (currentTrial >= numTrials) endCurrentSession(); // If rat completes all trials
  } else {
    recordEvent(BF_INVALID_TRIAL);                      // Trial aborted -- repeat the same side
  }
}

/* ===================================== Utility functions ===================================== */
/*  bool checkForStop() {...} ->
  Non-blocking poll for a "STOP" line from the host GUI, called once
  per trial boundary in loop(). Unlike readLineInto (which blocks and
  is only safe in setup), this consumes ONLY bytes already sitting in
  the serial buffer and returns immediately if none are present, so it
  never stalls the behavior loop. A partial line is held in a static
  buffer across calls and completed on a later pass. Returns true once
  a full "STOP" line has been received. Any other complete line is
  discarded (we only recognize STOP while running). */
bool checkForStop() {
  static char buf[8];
  static size_t len = 0;

  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      bool isStop = (len > 0 && strcmp(buf, "STOP") == 0);
      len = 0;                                        // reset for next line
      if (isStop) return true;
    } else {
      if (len < sizeof(buf) - 1) {
        buf[len++] = c;
        buf[len] = '\0';                             // keep null-terminated for strcmp
      }
      // else: overflow byte -- drop it, line can't be "STOP" anyway
    }
  }
  return false;
}

/*  bool readLineInto(char* dst, size_t cap) {...} ->
  Reads one line from Serial into dst, terminating on CR or LF and
  tolerating a trailing CR+LF pair (the host's println may send either).
  Null-terminates dst and strips the line ending. Returns true once a
  complete, non-empty line has been read; returns false on an empty line
  (e.g. a lone terminator) so the caller simply tries again. Lines longer
  than cap-1 are truncated; the overflow tail is drained so it can't leak
  into the next read.
*/
bool readLineInto(char* dst, size_t cap) {
  size_t len = 0;
  while (true) {
    while (Serial.available() == 0) {
      delay(pollingRate);                         // idle politely until a byte arrives
    }
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      if (len == 0) {
        return false;                             // lone terminator -- nothing to report yet
      }
      dst[len] = '\0';
      return true;
    }
    if (len < cap - 1) {
      dst[len++] = c;                             // accumulate
    }
    // else: token longer than expected -- drop the overflow byte
  }
}

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
  recordEvent(BF_START_SESSION);                  // Mark start
}

/* Housekeeping for ending the current experiment session */
void endCurrentSession() {
  shutdownHardware();
  sessionComplete = true;
  recordEvent(BF_END_SESSION);
}

/*  float frand() {...} ->
  Uniform random float in [0, 1), built on Arduino's random(). */
float frand() {
  return random(0, 10000) / 10000.0;
}

/*  void recordChoice(bool wentRight) {...} ->
  Push the rat's expressed side choice into the sliding-window ring buffer,
  evicting the oldest entry once the window is full and keeping rightInWindow
  in sync. Called from checkResponse whenever the rat pokes a fluid well
  (correct OR wrong) -- i.e. on every administered trial where a choice was
  actually expressed. No-response trials don't call this, so they don't move
  the bias estimate. */
void recordChoice(bool wentRight) {
  if (choiceRingLen == biasWindow) {
    rightInWindow -= choiceRing[choiceRingIdx];   // evict oldest before overwrite
  } else {
    choiceRingLen++;
  }
  choiceRing[choiceRingIdx] = wentRight ? 1 : 0;
  rightInWindow += choiceRing[choiceRingIdx];
  choiceRingIdx = (choiceRingIdx + 1) % biasWindow;
}

/*  const TrialType* selectNextTrial() {...} ->
  Adaptive anti-bias trial selection. Draws the next trial's correct side
  from a probability nudged AGAINST the rat's recent expressed side bias:
  if the rat has been over-choosing right, P(correct side = right) drops, so
  more left trials are presented and a fixed-side strategy stops paying. The
  probability is CLAMPED to [pSideMin, pSideMax] so selection never collapses
  into deterministic alternation (which would itself be a non-odor cue). A
  hard cap (maxConsecutiveSide) prevents long same-side runs from the draw. */
const TrialType* selectNextTrial() {
  float pRight = 0.5;
  if (choiceRingLen > 0) {
    // bias in [-1, 1]: +1 = always right, -1 = always left.
    float bias = (2.0 * rightInWindow - choiceRingLen) / (float)choiceRingLen;
    pRight = 0.5 - debiasStrength * bias;
    if (pRight < pSideMin) pRight = pSideMin;
    if (pRight > pSideMax) pRight = pSideMax;
  }

  bool chooseRight = frand() < pRight;
  int  candidateSide = chooseRight ? rightWell : leftWell;

  // Hard cap: if this would extend a same-side run past the cap, flip it.
  if (candidateSide == lastSelectedSide && selectedSideRun >= maxConsecutiveSide) {
    chooseRight = !chooseRight;
    candidateSide = chooseRight ? rightWell : leftWell;
  }

  if (candidateSide == lastSelectedSide) {
    selectedSideRun++;
  } else {
    lastSelectedSide = candidateSide;
    selectedSideRun = 1;
  }

  return chooseRight ? &goRight1 : &goLeft1;
}

/*  void fireDummyClicks(int windowMs) {...} ->
  Spread a randomized set of dummy valve clicks across the priming window so
  the odor valve's own click can't single out the rewarded side. The window
  is split into NUM_DUMMY slots; each spare valve fires with ~50% probability
  at a random offset within its slot (with at least one click guaranteed), and
  each fire is strobed (BF_DUMMY_CLICK_BASE + i) for offline verification.
  These valves are unodorized and never open the NOV path, so they emit only
  sound. Consumes ~windowMs total, replacing the plain priming delay. */
void fireDummyClicks(int windowMs) {
  int slot = windowMs / NUM_DUMMY;
  if (slot < dummyPulseMs + 2) slot = dummyPulseMs + 2;   // floor so a pulse fits
  bool firedAny = false;

  for (int i = 0; i < NUM_DUMMY; i++) {
    unsigned long slotStart = millis();
    bool fire = (random(0, 2) == 0);
    if (i == NUM_DUMMY - 1 && !firedAny) fire = true;      // guarantee >= 1 click

    if (fire) {
      int pre = random(0, slot - dummyPulseMs);            // random offset within the slot
      delay(pre);
      digitalWrite(Odors[DUMMY_OFFSET + i], HIGH);
      recordEvent(BF_DUMMY_CLICK_BASE + i);
      delay(dummyPulseMs);
      digitalWrite(Odors[DUMMY_OFFSET + i], LOW);
      firedAny = true;
    }
    while (millis() - slotStart < (unsigned long)slot) {   // pad out the slot
      delay(1);
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
  digitalWrite(trial.odorPin, HIGH);              // 1. Prime the correct odor (this valve also clicks)
  int thisPriming = primingDelay + (int)random(-primingJitter, primingJitter + 1);
  fireDummyClicks(thisPriming);                   // 2. Mask that click with randomized dummy clicks across priming
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
  int responseDelay = checkResponse(trial);       // 10. Successful odor sampling — delay (ms) for this outcome
  delay(responseDelay);                           // Administer the outcome-specific delay
  if (responseDelay == standardITI) {
    recordEvent(BF_END_CORRECT_ITI);              // Correct response
    return true;                                  // Advance to next trial
  } else {
    recordEvent(BF_END_INCORRECT_ITI);            // Incorrect response (hold failure or wrong well)
    // Correction trials: while currentTrial is within the leading
    // numCorrectionTrials, an incorrect response repeats the same trial
    // (return false -> loop() logs BF_INVALID_TRIAL and holds currentTrial).
    // Past the correction block, advance regardless of correctness.
    return (currentTrial >= numCorrectionTrials);
  }
}

/*  int checkResponse(TrialType trial) {...} ->
  Polls the fluid wells after successful odor sampling and returns the
  intertrial delay (ms) to administer for the resulting outcome:
    standardITI       -> correct (held the correct well, or correctly withheld on no-go)
    noPokeHoldTimeout -> poked the correct well but failed to hold it
    errorDelay        -> poked the wrong well, gave no response, or responded on a no-go
*/
int checkResponse(TrialType trial) {
  if (trial.isGo) {                               // GO TRIAL -> poll both wells for fluidWellPoll
    unsigned long pollStart = millis();
    int pokedWell = SENTINEL;
    bool rightFirst = (random(0, 2) == 0);        // randomize order: a simultaneous L/R break no longer always -> right

    while (millis() - pollStart < fluidWellPoll) {// 1. Poll both wells (tie broken by random order)
      int rRead = digitalRead(rightWell);
      int lRead = digitalRead(leftWell);
      if (rRead == LOW && lRead == LOW) {
        pokedWell = rightFirst ? rightWell : leftWell;
      } else if (rRead == LOW) {
        pokedWell = rightWell;
      } else if (lRead == LOW) {
        pokedWell = leftWell;
      }
      if (pokedWell != SENTINEL) {
        recordEvent(pokedWell == rightWell ? BF_WATER_POKE_R : BF_WATER_POKE_L);
        recordChoice(pokedWell == rightWell);     // feed the rat's expressed side into the anti-bias estimate
        break;
      }
      delay(pollingRate);
    }

    if (pokedWell == SENTINEL) {
      // No response within timeout
      return errorDelay;
    }

    if (pokedWell != trial.correctWell) {
      // Error 1: Wrong well
      recordEvent(pokedWell == rightWell ? BF_WATER_POKE_ERROR_R : BF_WATER_POKE_ERROR_L);
      return errorDelay;
    }

    if (!verifySensor(pokedWell, fluidWellHold)) {// 3. Correct well — verify hold
      // Error 2: Didn't hold poke
      recordEvent(pokedWell == rightWell ? BF_WATER_UNPOKE_EARLY_R : BF_WATER_UNPOKE_EARLY_L);
      return noPokeHoldTimeout;
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
        return errorDelay;
      }
      if (digitalRead(leftWell) == LOW) {
        // Error 3: Rat responded on nogo
        recordEvent(BF_WATER_POKE_L);
        return errorDelay;
      }
      delay(pollingRate);
    }
    recordEvent(BF_WATER_POKE_NONE);              // No-go trial! :)
  }

  return standardITI;                             // Rat responded correctly
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

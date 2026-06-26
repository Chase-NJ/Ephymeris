/*
Author: Chase Johnston
Date: June 25th, 2026
Purpose:
  GRGL_2-Odor_EZ -- an EASED-IN variant of the binary odor discrimination task,
  for transitioning a struggling rat (remy3) onto the full 2-odor task.
    Odor 1 - Go-right - SANDALWOOD      ->  ~50% of trials
    Odor 3 - Go-left  - ORANGE EXTRACT  ->  ~50% of trials

  Notable Features:
  - Anti-bias selection
  - Integration with Python GUI
  - Per-side correction trials
  - Togglable lazy rat delay escalation

  WHAT DIFFERS FROM GRGL_2-Odor:
  This variant RAMPS the four hold/timing parameters (odorPokeHold,
  fluidWellHold, fluidWellPoll, odorPortTimeout) from very forgiving values
  up to the full-task values over the first ~100 completed trials, mirroring
  the staged shaping in shaping_GL.ino.

  Runtime config arrives from the GUI in the START command (see protocol.py /
  GRGLSession.h): START CL=<int> CR=<int> LAZY=<0|1>  -- per-side correction
  budgets + the escalating-lazy-penalty toggle. Bare START = CL=0 CR=0 LAZY=1.
  Here the LAZY toggle COMPOSES with the shaping stage gate (lazyRampActive):
  escalation needs both the toggle on AND the holds ramped in.
*/

#include <GRGLSession.h> // shared session logic (one source for both sketches)

/*============= Experiment Hyperparameters =============*/
/* Trial timing parameters (in ms) */
const int baudRate = 9600;           // Baud rate for communication with MatLab via serial port
const int errorDelay = 20000;        // Timeout for incorrect response.
// --- RAMPED PARAMETERS (EZ variant) -------------------------------------
// These four are mutable and start FORGIVING, then ramp toward the full-task
// values in applyShapingRamp() below. Full-task targets are 4000 / 500 / 500 / 2000.
int odorPortTimeout = 8000;          // [ramps 8000 -> 4000] Window rat has to poke following light on.
int odorPokeHold = 10;               // [ramps 10 -> 500]   Hold before odor + during odor sampling. (ms)
int fluidWellHold = 10;              // [ramps 10 -> 500]   Hold at fluid well before reward. (ms)
int fluidWellPoll = 10000;           // [ramps 10000 -> 2000] Window to respond after odor sampling.
// ------------------------------------------------------------------------
const int nogoWellPoll = 2000;       // Duration rat must withold response on NO-GO trials, following successful odor sampling.
const int lazyRatDelay = 6000;       // Base timeout for failure to initiate trial. Now >= standardITI so
                                     // not-playing is never cheaper than playing-and-winning.
const int lazyEscalateStep = 6000;   // Added per CONSECUTIVE lazy trial (escalating abstention cost)
const int lazyDelayMax = 30000;      // Ceiling on the escalated lazy penalty
const int noPokeHoldTimeout = 10000; // Timeout for failure to hold poke
const int standardITI = 4000;        // Intertrial interval on correct trials
const int FluidPinTimes[] = {
    100, // Left-well  1
    100, // Left-well  2
    100, // Right-well 1
    100  // Right-well 2
};
/*======================================================*/

/* ======== Trial sequence parameters ======== */
const int pollingRate = 2;     // Polling rate for our IR sensors (in ms)
const int primingDelay = 1000; // Time odor is primed prior to trial light on (fixed, controlled latency)
const int numTrials = 1000;    // Number of trials to be run (session cap)
const long trialSeed = 12345;  // Reproducible-mode seed (used only when USE_FIXED_SEED)
#define USE_FIXED_SEED 0       // 1 -> seed from trialSeed; 0 -> seed from micros() at START
int currentTrial = 0;          // # of trials advanced this session
bool sessionComplete = false;  // If rat somehow completes numTrials...
int advanceCount = 0;          // # of COMPLETED (advancing) trials -- drives the shaping ramp
bool lazyRampActive = false;   // escalating lazy penalty is suppressed until the holds ramp in
// Correction budgets + lazy-penalty escalation now live in CorrectionPolicy /
// AbstentionPenalty (GRGLSession.h), configured from the START command.

/* ===== Adaptive anti-bias selection ===== */
const int biasWindow = 20;        // sliding window of recent expressed choices
const float debiasStrength = 0.5; // how hard to push the correct side against the rat's bias
const float pSideMin = 0.05;      // clamp on P(correct side); near-0 lets a fixed-side rat be starved hard,
const float pSideMax = 0.95;      // while still never going fully deterministic (which would itself be a cue)
const int maxConsecutiveSide = 6; // hard cap on consecutive identical correct sides. Raised so the anti-bias
                                  // draw isn't forced to hand a fixed-side rat a "free" opposite-side trial
                                  // every 3rd trial -- that floor was ~1/3 of remy2's entire reward income.

/* Trial Timing -- TrialClock now lives in GRGLSession.h (shared). */
TrialClock clock; // Encapsulates the logic for trial timestamps

/*=== Preprocessor Macros (Trial events) ===*/
#define BF_START_SESSION 221        // Sent at recording start (timestamp 0)
#define BF_LIGHTS_ON 222            // Sent when trialLight is written HIGH
#define BF_LAZY_RAT 223             // Sent when rat fails to initiate trial
#define BF_ODOR_POKE 224            // Sent when rat pokes odor port
#define BF_ODOR_UNPOKE_EARLY 225    // Sent when rat fails to hold odor poke for odorPokeHold
#define BF_ODOR_UNPOKE 226          // Sent after rat successfully samples odor
#define BF_ODOR_OFF 247             // Sent when we close N.O.V. (directing odor AWAY from odor port)
#define BF_WATER_POKE_L 248         // Sent when rat pokes left fluid well
#define BF_WATER_POKE_R 249         // Sent when rat pokes right fluid well
#define BF_WATER_UNPOKE_EARLY_L 250 // Sent when rat fails to hold for fluidWellHold
#define BF_WATER_UNPOKE_EARLY_R 251 // Sent when rat fails to hold for fluidWellHold
#define BF_WATER_UNPOKE_L 254       // Sent when rat unpokes left well
#define BF_WATER_UNPOKE_R 255       // Sent when rat unpokes right well
#define BF_WATER_POKE_ERROR_L 257   // Sent when rat incorrectly responds at left well
#define BF_WATER_POKE_ERROR_R 258   // Sent when rat incorrectly responds at right well
#define BF_LIGHTS_OFF 233           // Trial light off
#define BF_INVALID_TRIAL 234        // Trial is aborted (either lazy rat or poke hold failure)
#define BF_FLUID_L 252              // Delivered at start of first drop on left.
#define BF_FLUID_R 253              // Delivered at start of first drop on right.
#define BF_STOP_FLUID_G_R 357       // Sent when we stop right well fluid delivery
#define BF_STOP_FLUID_G_L 369       // Sent when we stop left well fluid delivery
#define BF_END_CORRECT_ITI 242      // Sent after correct response intertrial interval
#define BF_END_INCORRECT_ITI 243    // Sent after errorDelay intertrial interval
#define BF_END_SESSION 246          // Sent at end of session (sessionComplete = true)
#define BF_WATER_POKE_NONE 256      // After a correct response on a No-Go trial

/* === TrialType Macros === */
#define LEFT_WELL_FL_1 0  // Index into Fluids[] & FluidPinTimes[] for fluid sol 1
#define LEFT_WELL_FL_2 1  // Index into Fluids[] & FluidPinTimes[] for fluid sol 2
#define RIGHT_WELL_FL_1 2 // Index into Fluids[] & FluidPinTimes[] for fluid sol 3
#define RIGHT_WELL_FL_2 3 // Index into Fluids[] & FluidPinTimes[] for fluid sol 4
#define SENTINEL -1       // Sentinel value. Enables implementation of no-go trials.

/* Distinct Odor-ON Macros */
#define BF_ODOR_1_ON 101
#define BF_ODOR_2_ON 102
#define BF_ODOR_3_ON 103
#define BF_ODOR_4_ON 104
#define BF_ODOR_5_ON 105
#define BF_ODOR_6_ON 106

/*===================== Pin-mapping for Arduino =====================*/
/* IR Sensors */
const int odorPort = 2;  // Odor port
const int rightWell = 3; // Right-well
const int leftWell = 4;  // Left-well

/* Trial light & normally open vacuum */
const int trialLight = 36; // Trial light
const int vac = 40;        // N.O.V.

/* Odor solenoids */
const int Odors[] = {
    22, // Odor 1
    24, // Odor 2
    26, // Odor 3
    28, // Odor 4
    30, // Odor 5
    32, // Odor 6
    23, // Odor 7
    25, // Odor 8
    27, // Odor 9
    29, // Odor 10
    31, // Odor 11
    33  // Odor 12
};

/* Fluid Solenoids */
const int Fluids[] = // { left , left , right , right }
    {
        42, // [0]: Left-well reward 1
        44, // [1]: Left-well reward 2
        46, // [2]: Right-well reward 1
        48, // [3]: Right-well reward 2
};
/*===================================================================*/

/* TrialType struct now lives in GRGLSession.h (shared by both sketches). The
   concrete go-trial instances below stay here -- they reference this sketch's
   pins and strobe codes. */

/* ===== TRIAL TYPES ===== */
// Two go trials -- one per side. The AntiBiasSelector (selector.selectNext())
// picks between these live, using the adaptive anti-bias logic, not a fixed pool.
// Go Trials:
const TrialType goRight1(
    true,             // Is this a go trial?
    Odors[0],         // Odor 1
    rightWell,        // Correct response: right fluid well
    RIGHT_WELL_FL_1,  // Index into Fluids[] & FluidPinTimes[]
    BF_ODOR_1_ON,     // Strobe for odor on
    BF_FLUID_R,       // Strobe for right fluid
    BF_STOP_FLUID_G_R // Strobe for stop right fluid
);
const TrialType goLeft1(
    true,
    Odors[2], // Odor 3
    leftWell,
    LEFT_WELL_FL_1,
    BF_ODOR_3_ON,
    BF_FLUID_L,
    BF_STOP_FLUID_G_L);

/* ===== Session objects (GRGLSession.h) =====
   The anti-bias ring buffer + selection, the lazy-penalty escalator, the
   per-side correction budgets, and the START-parsed config are each owned by a
   small class now, so adding the next policy/toggle is a localized change. The
   anti-bias tuning constants above (which differ between the two sketches) are
   passed in here. */
SessionConfig sessionCfg; // populated from START in setup()
AntiBiasSelector selector(&goRight1, &goLeft1, biasWindow, debiasStrength,
                          pSideMin, pSideMax, maxConsecutiveSide);
AbstentionPenalty abstention(lazyRatDelay, lazyEscalateStep, lazyDelayMax);
CorrectionPolicy correction;

const TrialType *currentTrialPtr = nullptr; // current trial; re-selected only when we advance

void setup()
{
  /*=== Setup Arduino pins ===*/
  for (int odor = 0; odor < 12; odor++)
  { // Odor solenoids
    pinMode(Odors[odor], OUTPUT);
  }
  for (int rwd = 0; rwd < 4; rwd++)
  { // Fluid solenoids
    pinMode(Fluids[rwd], OUTPUT);
  }
  pinMode(odorPort, INPUT_PULLUP); // IR Sensors
  pinMode(leftWell, INPUT_PULLUP);
  pinMode(rightWell, INPUT_PULLUP);

  pinMode(trialLight, OUTPUT); // Trial light
  pinMode(vac, OUTPUT);        // N.O.V.

  /*=== Make sure everything's chill... ===*/
  shutdownHardware();

  sessionComplete = true; // session start / end guard
  Serial.begin(baudRate); // Initialize serial com with baud rate

  /* Wait for the START token from the Python GUI.
     1. The host opens the port (which resets the Mega via DTR).
     2. We land here, announce READY so the GUI can arm its START button.
     3. Block until we receive a "START" line, optionally carrying runtime
        config: "START CL=<int> CR=<int> LAZY=<0|1>" (per-side correction
        budgets + lazy-escalation toggle). A bare "START" uses the defaults
        (CL=0 CR=0 LAZY=1) -- the legacy behavior. parseStartCommand() mirrors
        protocol.build_start_command in the Python package. */
  digitalWrite(trialLight, HIGH); // Light on == armed, waiting for GO
  delay(50);                      // Let the post-reset serial settle
  Serial.println("READY");        // Tell the GUI we're ready to begin

  char cmd[48]; // big enough for the key=value token form
  while (true)
  {
    if (readLineInto(cmd, sizeof(cmd)) && strncmp(cmd, "START", 5) == 0 && (cmd[5] == '\0' || cmd[5] == ' '))
    {
      parseStartCommand(cmd, sessionCfg); // fill sessionCfg (defaults preserved)
      correction.configure(sessionCfg.correctionLeft, sessionCfg.correctionRight);
      abstention.setEnabled(sessionCfg.lazyEscalationEnabled);
      break; // START received -- begin session
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
  beginNewSession(); // Start session! (stamps t=0, fires BF_START_SESSION)
}

// Main loop:
void loop()
{
  if (sessionComplete)
    return;

  /* Honor a remote STOP from the host GUI. Checked once per trial
     boundary (not mid-trial), so a stop never truncates a trial --
     this keeps the strobe stream's triplet structure intact for
     downstream analysis. If a STOP is seen we end cleanly here and
     fall through; the sessionComplete guard above idles us next pass. */
  if (checkForStop())
  {
    endCurrentSession();
    return;
  }

  /* Pick the next trial live. We only re-select when the previous trial
     ADVANCED; a trial that returns false (an abort, or an in-block
     correction error) keeps currentTrialPtr so the SAME side is re-presented
     -- preserving the original repeat-the-same-trial semantics. */
  if (currentTrialPtr == nullptr)
  {
    currentTrialPtr = selector.selectNext();
  }

  /* Run our behavior! */
  if (odorSampling(*currentTrialPtr))
  {
    currentTrial++;     // Advance only on a completed/advancing trial
    advanceCount++;     // EZ: count completed trials to drive the shaping ramp
    applyShapingRamp(); // EZ: update hold/timing params for the new advanceCount
    // Consume this side's leading correction budget (a correct trial, or an
    // already-past-budget advance). A correction REPEAT returns false above and
    // never reaches here, so it doesn't consume budget.
    correction.onAdvance(currentTrialPtr->correctWell == rightWell);
    currentTrialPtr = nullptr; // force a fresh selection next loop
    if (currentTrial >= numTrials)
      endCurrentSession(); // If rat completes all trials
  }
  else
  {
    recordEvent(BF_INVALID_TRIAL); // Trial aborted -- repeat the same side
  }
}

/*  void applyShapingRamp() {...} ->
  EZ-variant shaping. Called once per COMPLETED trial (advanceCount just
  incremented). Steps the four ramped hold/timing parameters from forgiving
  starting values toward the full-task values, mirroring the staged structure
  of shaping_GL.ino but adapted to this task's two-odor, anti-bias loop.

  Ramp is keyed off advanceCount (completed trials), NOT currentTrial, so a
  rat that aborts a lot still advances stages at the pace of its real
  successes -- it can't be rushed into a hard stage by burning trials.

  Stage map (completed-trial thresholds):
    < 15  Stage 0  ttip=10   wellHold=10   pollWin=10s  portTO=8s   (just touch-and-go)
    15    Stage 1  ttip=100  wellHold=50   pollWin=10s  portTO=8s
    30    Stage 2  ttip=200  wellHold=200  pollWin=5s   portTO=6s
    50    Stage 3  ttip=350  wellHold=350  pollWin=3s   portTO=4s
    80    Stage 4  ttip=500  wellHold=500  pollWin=2s   portTO=4s   (== full task)

  Once Stage 4 (full task) is reached the escalating lazy penalty is switched
  ON (lazyRampActive); before that, abstention is penalized only at the flat
  base rate (see odorSampling) so a rat that genuinely can't hold yet isn't
  buried in escalating timeouts.

  Thresholds use >= with descending order so a resumed/oversized advanceCount
  always lands on the correct stage (idempotent -- safe to call every trial). */
void applyShapingRamp()
{
  if (advanceCount >= 80)
  { // Stage 4 -- full task
    odorPokeHold = 500;
    fluidWellHold = 350;
    fluidWellPoll = 2000;
    odorPortTimeout = 4000;
    lazyRampActive = true;
  }
  else if (advanceCount >= 50)
  { // Stage 3
    odorPokeHold = 350;
    fluidWellHold = 350;
    fluidWellPoll = 3000;
    odorPortTimeout = 4000;
    lazyRampActive = false;
  }
  else if (advanceCount >= 30)
  { // Stage 2
    odorPokeHold = 200;
    fluidWellHold = 200;
    fluidWellPoll = 5000;
    odorPortTimeout = 6000;
    lazyRampActive = false;
  }
  else if (advanceCount >= 15)
  { // Stage 1
    odorPokeHold = 100;
    fluidWellHold = 50;
    fluidWellPoll = 10000;
    odorPortTimeout = 8000;
    lazyRampActive = false;
  }
  // else: Stage 0 -- keep the forgiving initial values set at declaration.
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
bool checkForStop()
{
  static char buf[8];
  static size_t len = 0;

  while (Serial.available() > 0)
  {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n')
    {
      bool isStop = (len > 0 && strcmp(buf, "STOP") == 0);
      len = 0; // reset for next line
      if (isStop)
        return true;
    }
    else
    {
      if (len < sizeof(buf) - 1)
      {
        buf[len++] = c;
        buf[len] = '\0'; // keep null-terminated for strcmp
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
bool readLineInto(char *dst, size_t cap)
{
  size_t len = 0;
  while (true)
  {
    while (Serial.available() == 0)
    {
      delay(pollingRate); // idle politely until a byte arrives
    }
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n')
    {
      if (len == 0)
      {
        return false; // lone terminator -- nothing to report yet
      }
      dst[len] = '\0';
      return true;
    }
    if (len < cap - 1)
    {
      dst[len++] = c; // accumulate
    }
    // else: token longer than expected -- drop the overflow byte
  }
}

/* Blanket turn-off of all outputs (safe to call at any time) */
void shutdownHardware()
{
  for (int i = 0; i < 12; i++)
    digitalWrite(Odors[i], LOW);
  for (int i = 0; i < 4; i++)
    digitalWrite(Fluids[i], LOW);
  digitalWrite(trialLight, LOW);
  digitalWrite(vac, LOW);
}

/* Housekeeping for starting a new experiment session */
void beginNewSession()
{
  clock.beginSession(); // Initialize clock on rising edge

  sessionComplete = false;
  currentTrial = 0;              // Start at beginning of Trials array
  recordEvent(BF_START_SESSION); // Mark start
}

/* Housekeeping for ending the current experiment session */
void endCurrentSession()
{
  shutdownHardware();
  sessionComplete = true;
  recordEvent(BF_END_SESSION);
}

/* frand(), recordChoice(), recordAbstention(), and selectNextTrial() now live
   in GRGLSession.h: grglFrand() and the AntiBiasSelector class (the `selector`
   instance above). Call sites use selector.recordChoice / recordAbstention /
   selectNext. */

/*  void recordEvent(int eventCode) {...} ->
  Given an eventCode (an int), outputs the code in a standardized 3-digit format.

  Handles sending eventCode and a timestamp to MatLab.
*/
void recordEvent(int eventCode)
{
  unsigned long timestamp = clock.elapsed();
  char buf[16];

  sprintf(buf, "%03d\t%lu", eventCode, timestamp); // Store print line to MatLab in a buffer
  Serial.println(buf);                             // Print buffer to serial
}

/*  bool verifySensor(int pin, int duration) {...} ->
  Takes a pin (IR sensor) and a duration (ms).
  Returns FALSE if sensor is interrupted.
  Returns TRUE if sensor is uninterrupted.
*/
bool verifySensor(int pin, int duration)
{
  unsigned long start = millis();
  while (millis() - start < duration)
  {
    if (digitalRead(pin) == HIGH)
    {
      return false; // For Input Pullup, HIGH = rat unpoked
    }
    delay(pollingRate); // polling rate = 2ms
  }
  return true;
}

/*  void flashLight(int duration) {...} ->
  Flashes the trial light every 200ms, given a duration in ms.
*/
void flashLight(int duration)
{
  unsigned long start = millis();
  while (millis() - start < duration)
  {
    digitalWrite(trialLight, HIGH);
    delay(pollingRate);
    digitalWrite(trialLight, LOW);
    delay(pollingRate);
  }
}

/*===============================================================================================*/

/*=== Trial Logic Functions ===*/
bool odorSampling(TrialType trial)
{
  digitalWrite(trial.odorPin, HIGH); // 1. Prime the correct odor
  delay(primingDelay);               // 2. Fixed priming delay (controlled temporal environment)
  digitalWrite(trialLight, HIGH);    // 3. Turn on the trial light
  recordEvent(BF_LIGHTS_ON);

  unsigned long waitStart = millis();
  while (digitalRead(odorPort) == HIGH)
  { // 4. Await rat to poke odorPort
    if (millis() - waitStart >= odorPortTimeout)
    {
      // Error 1: Rat failed to poke in time
      digitalWrite(trialLight, LOW);
      digitalWrite(trial.odorPin, LOW);
      recordEvent(BF_LAZY_RAT);
      selector.recordAbstention(trial.correctWell == rightWell); // abstention feeds the bias estimate
      // EZ: escalation is only stage-allowed once the holds have ramped in
      // (lazyRampActive) -- so an early-stage rat that can't hold yet gets the
      // flat base penalty. The LAZY toggle composes with that gate: nextDelay
      // escalates only if BOTH the toggle is on AND lazyRampActive. OFF, or a
      // pre-ramp stage -> flat lazyRatDelay, no consecutiveLazy growth.
      delay(abstention.nextDelay(lazyRampActive));
      return false;
    }
    delay(pollingRate);
  }
  recordEvent(BF_ODOR_POKE);
  abstention.reset(); // EZ: rat engaged -- reset the abstention escalator on poke
                      // (the full task instead resets only on a completed correct trial)

  if (!verifySensor(odorPort, odorPokeHold))
  { // 5. Verify rat holds poke (pre-odor hold)
    // Error 2: Rat didn't hold poke before vac close
    digitalWrite(trialLight, LOW);
    digitalWrite(trial.odorPin, LOW);
    recordEvent(BF_ODOR_UNPOKE_EARLY);
    delay(noPokeHoldTimeout);
    return false;
  }

  recordEvent(trial.odorOnCode); // Send code to MatLab for trial-specific odor
  digitalWrite(vac, HIGH);       // 6. Close vac (N.O.V.), directing odor to rat

  if (!verifySensor(odorPort, odorPokeHold))
  { // 7. Verify rat samples odor for odorPokeHold
    // Error 3: Rat didn't sample odor long enough
    digitalWrite(trialLight, LOW);
    digitalWrite(trial.odorPin, LOW);
    digitalWrite(vac, LOW);
    recordEvent(BF_ODOR_UNPOKE_EARLY);
    delay(noPokeHoldTimeout);
    return false;
  }

  digitalWrite(trial.odorPin, LOW); // 8. Turn off odor, open vac
  digitalWrite(vac, LOW);
  recordEvent(BF_ODOR_OFF);

  while (digitalRead(odorPort) == LOW)
  { // 9. Await unpoke
    delay(pollingRate);
  }
  recordEvent(BF_ODOR_UNPOKE);

  digitalWrite(trialLight, LOW);
  int responseDelay = checkResponse(trial); // 10. Successful odor sampling — delay (ms) for this outcome
  delay(responseDelay);                     // Administer the outcome-specific delay
  if (responseDelay == standardITI)
  {
    recordEvent(BF_END_CORRECT_ITI); // Correct response
    return true;                     // Advance to next trial
  }
  else
  {
    recordEvent(BF_END_INCORRECT_ITI); // Incorrect response (hold failure or wrong well)
    // Per-side correction: while THIS side is still under its leading budget,
    // an incorrect response repeats the same trial (return false -> loop() logs
    // BF_INVALID_TRIAL and holds currentTrialPtr, re-presenting the same side).
    // Past that side's budget, advance regardless of correctness.
    return !correction.shouldRepeat(trial.correctWell == rightWell);
  }
}

/*  int checkResponse(TrialType trial) {...} ->
  Polls the fluid wells after successful odor sampling and returns the
  intertrial delay (ms) to administer for the resulting outcome:
    standardITI       -> correct (held the correct well, or correctly withheld on no-go)
    noPokeHoldTimeout -> poked the correct well but failed to hold it
    errorDelay        -> poked the wrong well, gave no response, or responded on a no-go
*/
int checkResponse(TrialType trial)
{
  if (trial.isGo)
  { // GO TRIAL -> poll both wells for fluidWellPoll
    unsigned long pollStart = millis();
    int pokedWell = SENTINEL;
    bool rightFirst = (random(0, 2) == 0); // randomize order: a simultaneous L/R break no longer always -> right

    while (millis() - pollStart < fluidWellPoll)
    { // 1. Poll both wells (tie broken by random order)
      int rRead = digitalRead(rightWell);
      int lRead = digitalRead(leftWell);
      if (rRead == LOW && lRead == LOW)
      {
        pokedWell = rightFirst ? rightWell : leftWell;
      }
      else if (rRead == LOW)
      {
        pokedWell = rightWell;
      }
      else if (lRead == LOW)
      {
        pokedWell = leftWell;
      }
      if (pokedWell != SENTINEL)
      {
        recordEvent(pokedWell == rightWell ? BF_WATER_POKE_R : BF_WATER_POKE_L);
        selector.recordChoice(pokedWell == rightWell); // feed the rat's expressed side into the anti-bias estimate
        break;
      }
      delay(pollingRate);
    }

    if (pokedWell == SENTINEL)
    {
      // No response within timeout
      return errorDelay;
    }

    if (pokedWell != trial.correctWell)
    {
      // Error 1: Wrong well
      recordEvent(pokedWell == rightWell ? BF_WATER_POKE_ERROR_R : BF_WATER_POKE_ERROR_L);
      return errorDelay;
    }

    if (!verifySensor(pokedWell, fluidWellHold))
    { // 3. Correct well — verify hold
      // Error 2: Didn't hold poke
      recordEvent(pokedWell == rightWell ? BF_WATER_UNPOKE_EARLY_R : BF_WATER_UNPOKE_EARLY_L);
      return noPokeHoldTimeout;
    }

    giveReward(trial); // 4. Held — deliver reward
    while (digitalRead(pokedWell))
    { // Await well unpoke
      delay(pollingRate);
    }
  }
  else
  {
    unsigned long pollStart = millis(); // NO-GO TRIAL -> poll both wells for nogoWellPoll
    while (millis() - pollStart < nogoWellPoll)
    { // 1. Poll both wells
      if (digitalRead(rightWell) == LOW)
      {
        // Error 3: Rat responded on nogo
        recordEvent(BF_WATER_POKE_R);
        return errorDelay;
      }
      if (digitalRead(leftWell) == LOW)
      {
        // Error 3: Rat responded on nogo
        recordEvent(BF_WATER_POKE_L);
        return errorDelay;
      }
      delay(pollingRate);
    }
    recordEvent(BF_WATER_POKE_NONE); // No-go trial! :)
  }

  return standardITI; // Rat responded correctly
}

void giveReward(TrialType trial)
{
  int fluidPin = Fluids[trial.rewardIndex];
  int fluidDuration = FluidPinTimes[trial.rewardIndex];

  recordEvent(trial.fluidEventCode); // Log fluid delivery
  digitalWrite(fluidPin, HIGH);      // Open fluid solenoid
  delay(fluidDuration);              // Hold open for FluidPinTime
  digitalWrite(fluidPin, LOW);       // Close fluid solenoid
  recordEvent(trial.stopFluidCode);  // Log fluid stop
}

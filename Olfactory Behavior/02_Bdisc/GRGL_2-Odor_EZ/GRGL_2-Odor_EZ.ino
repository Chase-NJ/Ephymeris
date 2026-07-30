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

  Runtime config arrives from the GUI in the START command (see BehaviorBox.h /
  the app's start-command builder): START CL=<int> CR=<int> LAZY=<0|1>  -- per-side
  correction budgets + the escalating-lazy-penalty toggle. Bare START = CL=0 CR=0
  LAZY=1. Here the LAZY toggle COMPOSES with the shaping stage gate (lazyRampActive):
  escalation needs both the toggle on AND the holds ramped in.
*/

#include <BehaviorBox.h> // the single shared header for every sketch (pins, strobes, session policy)

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
const int pollingRate = 5;     // Polling rate for our IR sensors (in ms)
const int primingDelay = 1000; // Time odor is primed prior to trial light on (fixed, controlled latency)
const int numTrials = 1000;    // Number of trials to be run (session cap)
int currentTrial = 0;          // # of trials advanced this session
bool sessionComplete = false;  // If rat somehow completes numTrials...
int advanceCount = 0;          // # of COMPLETED (advancing) trials -- drives the shaping ramp
bool lazyRampActive = false;   // escalating lazy penalty is suppressed until the holds ramp in
// Correction budgets + lazy-penalty escalation now live in CorrectionPolicy /
// AbstentionPenalty (BehaviorBox.h), configured from the START command.

/* ===== Adaptive anti-bias selection ===== */
const int biasWindow = 20;        // sliding window of recent expressed choices
const float debiasStrength = 0.5; // how hard to push the correct side against the rat's bias
const float pSideMin = 0.05;      // clamp on P(correct side); near-0 lets a fixed-side rat be starved hard,
const float pSideMax = 0.95;      // while still never going fully deterministic (which would itself be a cue)
const int maxConsecutiveSide = 6; // hard cap on consecutive identical correct sides. Raised so the anti-bias
                                  // draw isn't forced to hand a fixed-side rat a "free" opposite-side trial
                                  // every 3rd trial -- that floor was ~1/3 of remy2's entire reward income.

/* Trial Timing -- TrialClock lives in BehaviorBox.h (shared). */
TrialClock clock; // Encapsulates the logic for trial timestamps

/* The box pinout, the BF_* strobe codes, the Fluids[] index macros
   (LEFT_WELL_FL_1 ... SENTINEL), and the distinct BF_ODOR_n_ON codes all live in
   BehaviorBox.h now. The concrete go-trial instances below stay here -- they wire
   this sketch's odor/strobe choices into the shared TrialType. */

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

/* ===== Session objects (BehaviorBox.h) =====
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
  initBoxHardware(); // configure every box pin + land all outputs LOW (BehaviorBox.h)

  sessionComplete = true; // session start / end guard
  Serial.begin(baudRate); // Initialize serial com with baud rate

  /* Wait for the START token from the Python GUI.
     1. The host opens the port (which resets the Mega via DTR).
     2. We land here, announce READY so the GUI can arm its START button.
     3. Block until we receive a "START" line, optionally carrying runtime
        config: "START CL=<int> CR=<int> LAZY=<0|1> SEED=<uint32>" (per-side
        correction budgets, the lazy-escalation toggle, and this run's RNG
        seed). A bare "START" uses the defaults (CL=0 CR=0 LAZY=1) and a
        self-seeded RNG -- the legacy behavior. parseStartCommand() mirrors
        protocol.build_start_command in the Python package. */
  digitalWrite(trialLight, HIGH); // Light on == armed, waiting for GO
  delay(50);                      // Let the post-reset serial settle
  Serial.println("READY");        // Tell the GUI we're ready to begin

  char cmd[96]; // must hold the whole key=value line, SEED token included --
                // readLineInto() truncates at this cap, and a SEED lost there
                // silently drops the session back onto the weak clock fallback
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

  /* Seed the RNG before anything draws from it, and echo the seed so the host
     records the state this session actually ran on. The value comes from the
     app (SEED=<n>, drawn from an OS CSPRNG at the start click); micros() is
     only the fallback for an older host, and is weak for the reason spelled
     out over beginSessionRng() in BehaviorBox.h. */
  beginSessionRng(sessionCfg);

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
/* checkForStop(), readLineInto(), shutdownHardware(), verifySensor(), and
   flashLight() now live in BehaviorBox.h (shared by every sketch). */

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

/* grglFrand(), the anti-bias ring buffer + selection, verifySensor(), and
   flashLight() now live in BehaviorBox.h. Call sites use the `selector` instance
   and the shared helpers (verifySensor is called with this sketch's pollingRate). */

/* recordEvent -> emitStrobe (BehaviorBox.h) bound to this sketch's clock, so
   every call site below stays unchanged. */
void recordEvent(int eventCode) { emitStrobe(clock, eventCode); }

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

  if (!verifySensor(odorPort, odorPokeHold, pollingRate))
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

  if (!verifySensor(odorPort, odorPokeHold, pollingRate))
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

    if (!verifySensor(pokedWell, fluidWellHold, pollingRate))
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

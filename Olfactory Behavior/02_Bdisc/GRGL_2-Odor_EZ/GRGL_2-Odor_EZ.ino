/*
Author: Chase Johnston
Date: July 29th, 2026
Purpose:
  A binary odor discrimination task.
  The eased variant: the same task entered through a forgiving ramp instead of
  at full strictness, with the abstention penalty held flat until the last stage.
    Odor 1 - Go-right - SANDALWOOD      ->  ~50% of trials (assuming no per-rat bias)
    Odor 3 - Go-left  - ORANGE EXTRACT  ->  ~50% of trials (assuming no per-rat bias)

  Notable Features:
  - Anti-bias selection
  - Integration with the Ephymeris app
  - Per-side correction trials
  - Togglable (and stage-gated) lazy rat delay escalation

  This sketch is ONLY: the two go-trial types, the session policy objects, and
  the setup/loop wiring. The trial runner lives in BehaviorBox.h, shared with
  every other behavior sketch -- which is what keeps this sketch and its GRGL_2-Odor base sketch
  from drifting apart, as two hand-maintained copies of the loop had.

  EVERY timing, hold, window, penalty, reward volume, anti-bias clamp and stage
  threshold arrives from the app on the START line and is declared in this
  sketch's task.json -- tuned per run in the Config page, not by reflashing. The
  values applied by applyEasedDiscriminationDefaults() below are only
  the bare-START fallback for a hand-typed console session or an older host.
*/

#include <BehaviorBox.h> // pins, strobes, TaskParams, session policy + the shared trial runner

/* ======== Session wiring ======== */
const unsigned long baudRate = 115200;    // Serial baud (matches the app)
int currentTrial = 0;         // # of trials advanced this session
bool sessionComplete = false; // Session start / end guard

TaskParams params; // every tunable, filled from the START line (BehaviorBox.h)
TrialClock clock;  // trial timestamps

/* recordEvent -> emitStrobe (BehaviorBox.h) bound to this sketch's clock. */
void recordEvent(int eventCode) { emitStrobe(clock, eventCode); }

/* ===== TRIAL TYPES =====
   Two go trials -- one per side. The AntiBiasSelector picks between them live,
   using the adaptive anti-bias logic, not a fixed pool. */
const TrialType goRight1(
    true,             // Is this a go trial?
    Odors[0],         // Odor 1
    rightWell,        // Correct response: right fluid well
    RIGHT_WELL_FL_1,  // Index into Fluids[] & params.fluidPinTimes[]
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

/* ===== Session policy (BehaviorBox.h) =====
   The anti-bias ring buffer + selection, the lazy-penalty escalator and the
   per-side correction budgets each live in their own small class. They are
   globals, so they are constructed long before START arrives -- each one adopts
   the run's parameters in configure(), called once after the line is parsed. */
AntiBiasSelector selector(&goRight1, &goLeft1);
AbstentionPenalty abstention;
CorrectionPolicy correction;
TrialPolicy policy; // the three, handed to the shared runner

const TrialType *currentTrialPtr = nullptr; // re-selected only when we advance

/* Housekeeping for starting a new experiment session */
void beginNewSession()
{
  clock.beginSession(); // Initialize clock on rising edge
  sessionComplete = false;
  currentTrial = 0;
  recordEvent(BF_START_SESSION); // Mark start
}

/* Housekeeping for ending the current experiment session */
void endCurrentSession()
{
  shutdownHardware();
  sessionComplete = true;
  recordEvent(BF_END_SESSION);
}

void setup()
{
  initBoxHardware(); // configure every box pin + land all outputs LOW

  sessionComplete = true;
  Serial.begin(baudRate);

  /* Bare-START fallback only -- the app overwrites all of this from task.json. */
  applyEasedDiscriminationDefaults(params);

  /* Wait for the START token from the app.
     1. The host opens the port (which resets the Mega via DTR).
     2. We land here, announce READY so the app can arm its start button.
     3. Block until a "START" line arrives carrying this run's parameters and
        its SEED. A bare "START" keeps every default set above. */
  digitalWrite(trialLight, HIGH); // Light on == armed, waiting for GO
  delay(50);                      // Let the post-reset serial settle
  Serial.println("READY");        // Tell the app we're ready to begin

  char cmd[START_LINE_MAX]; // must hold the WHOLE line: readLineInto() truncates
                            // at this cap and a token lost there is silent -- the
                            // session then runs on a value nobody chose.
  while (true)
  {
    if (readLineInto(cmd, sizeof(cmd)) && strncmp(cmd, "START", 5) == 0 && (cmd[5] == '\0' || cmd[5] == ' '))
    {
      parseStartCommand(cmd, params); // fill params (anything unsent keeps its default)
      break;                          // START received -- begin session
    }
  }

  selector.configure(params);
  abstention.configure(params);
  correction.configure(params.correctionLeft, params.correctionRight);
  policy.selector = &selector;
  policy.abstention = &abstention;
  policy.correction = &correction;

  /* Seed the RNG before anything draws from it, and echo the seed so the host
     records the state this session actually ran on. The value comes from the
     app (SEED=<n>, drawn from an OS CSPRNG at the start click); micros() is
     only the fallback for an older host, and is weak for the reason spelled
     out over beginSessionRng() in BehaviorBox.h. */
  beginSessionRng(params);

  // The "armed" indicator going out, not a trial event: the clock is
  // stamped by beginNewSession() on the next line, so a BF_LIGHTS_OFF here
  // would carry a pre-session timestamp and precede BF_START_SESSION.
  digitalWrite(trialLight, LOW);
  beginNewSession(); // Start session! (stamps t=0, fires BF_START_SESSION)
}

void loop()
{
  if (sessionComplete)
    return;

  /* Honor a remote STOP from the host. Checked once per trial boundary (not
     mid-trial), so a stop never truncates a trial -- this keeps the strobe
     stream's structure intact for downstream analysis. */
  if (checkForStop())
  {
    endCurrentSession();
    return;
  }

  /* Pick the next trial live. We only re-select when the previous trial
     ADVANCED; a trial that returns false (an abort, or an in-block correction
     error) keeps currentTrialPtr so the SAME side is re-presented. */
  if (currentTrialPtr == nullptr)
    currentTrialPtr = selector.selectNext();

  if (runTrial(*currentTrialPtr, params, clock, &policy, currentTrial))
  {
    currentTrial++;                   // Advance only on a completed/advancing trial
    applyStage(params, currentTrial); // Ramp holds/windows for the new count
    // Consume this side's leading correction budget. A correction REPEAT returns
    // false above and never reaches here, so it doesn't consume budget.
    correction.onAdvance(currentTrialPtr->correctWell == rightWell);
    currentTrialPtr = nullptr; // force a fresh selection next loop
    if (currentTrial >= params.numTrials)
      endCurrentSession();
  }
  else
  {
    recordEvent(BF_INVALID_TRIAL); // Trial aborted -- repeat the same side
  }
}

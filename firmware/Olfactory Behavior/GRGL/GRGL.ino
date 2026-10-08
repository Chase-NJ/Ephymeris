/*
Author: Chase Johnston
Purpose:
  THE olfactory behaviour task. One sketch for every profile the lab runs --
  two-odor discrimination, shaping, eased variants of either.

  It replaced six near-identical sketches (GRGL_2-Odor, GRGL_2-Odor_EZ,
  shaping_GR/GL and their _EZ siblings). Those differed by ONE substantive line
  each: which bare-START defaults they applied, and which pool weight they set.
  Everything an experiment actually varies -- the trial table, the pin map, the
  ramp, every timing and penalty -- now arrives from Ephymeris instead:

    * at COMPILE time, in the two generated headers included below. The trial
      table, the pin map, the strobe selection, how many ramp rows exist and
      which selector runs. None of these fit on a START line, and pins have to
      be constants anyway.
    * at START time, on the START line. Every timing, hold, window, penalty,
      per-condition reward volume, pool weight, anti-bias clamp and stage
      threshold. So tuning a run costs a serial line, not a rebuild -- which is
      what lets one flashed binary serve six boxes running the same task with
      different reward volumes.

  Features, all of them driven by the profile rather than by this file:
  - anti-bias selection (uniform or weighted within a side), or a
    block-shuffled weighted pool
  - a shaping ramp of any length, including none
  - the escalating lazy-rat penalty, stage-gated
  - per-side correction trials

  This sketch is ONLY the session policy objects and the setup/loop wiring. The
  trial runner lives in BehaviorBox.h, shared with every other sketch here --
  which is what kept the six copies from drifting, and is why deleting them cost
  nothing.
*/

#include "TaskPins.h"    // GENERATED: pins, strobes, counts, selection mode.
                         // Must precede BehaviorBox.h -- it overrides that
                         // header's guarded defaults, and cannot name a type.
#include <BehaviorBox.h> // the trial runner, TaskParams, the policy classes
#include "TaskTrials.h"  // GENERATED: kTrials[] / kTrialCount. Needs TrialType.

/* ======== Session wiring ======== */
int currentTrial = 0;         // # of trials advanced this session
bool sessionComplete = false; // Session start / end guard

TaskParams params; // every tunable, filled from the START line (BehaviorBox.h)
TrialClock clock;  // trial timestamps

/* recordEvent -> emitStrobe (BehaviorBox.h) bound to this sketch's clock. */
void recordEvent(int eventCode) { emitStrobe(clock, eventCode); }

/* ===== Session policy (BehaviorBox.h) =====
   The anti-bias ring buffer + selection, the lazy-penalty escalator and the
   per-side correction budgets each live in their own small class. They are
   globals, so they are constructed long before START arrives -- each one adopts
   the run's parameters in configure(), called once after the line is parsed. */
#if BOX_SELECTION_MODE == BOX_SELECT_WEIGHTED
/* Same side draw as anti-bias; the pick WITHIN the side follows poolWeights,
   so a stimulus still being learned can be shown more often than a known one. */
WeightedAntiBiasSelector selector(kTrials, kTrialCount);
#else
AntiBiasSelector selector(kTrials, kTrialCount);
#endif
AbstentionPenalty abstention;
CorrectionPolicy correction;
TrialPolicy policy; // the three, handed to the shared runner

const TrialType *currentTrialPtr = nullptr; // re-selected only when we advance

#if BOX_SELECTION_MODE == BOX_SELECT_POOL
/*  Pool mode: the whole sequence is drawn once, at START, from the profile's
    weights. `MAX_TRIALS` is the compile-time size of the array; params.numTrials
    is the runtime cap and is clamped to it in setup(). */
const int MAX_TRIALS = 1000;
TrialWeight pool[BOX_MAX_TRIAL_TYPES];
const TrialType *trials[MAX_TRIALS];
#endif

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
  Serial.begin(BOX_BAUD_RATE);

  /* Wait for the START token from the app.
     1. The host opens the port (which resets the Mega via DTR).
     2. We land here, announce READY so the app can arm its start button.
     3. Block until a "START" line arrives carrying this run's parameters and
        its SEED. A bare "START" keeps every default in TaskParams -- the
        full-task values, for a hand-typed console session or an older host. */
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

  /* Each type's reward volume: the value compiled into TaskTrials.h unless the
     line carried RW<slot+1> for it. Before the first trial, after the parse. */
  applyRewardTimes(params, kTrials, kTrialCount);

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

#if BOX_SELECTION_MODE == BOX_SELECT_POOL
  /* Seed FIRST, then build the sequence -- generateTrials() draws from the
     already-seeded stream and must never seed itself. Two seeding sites is how
     a fixed seed creeps back in unnoticed, and it did: every shaping session
     ever run drew the identical trial order because the sequence was built in
     setup() from a compile-time constant, before START had even arrived. */
  if (params.numTrials > MAX_TRIALS)
    params.numTrials = MAX_TRIALS; // trials[] is a fixed allocation
  for (int i = 0; i < kTrialCount; i++)
    pool[i] = TrialWeight(kTrials[i], params.poolWeights[i]);
  generateTrials(trials, params.numTrials, params.blockSize, pool, kTrialCount);
#endif

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

#if BOX_SELECTION_MODE == BOX_SELECT_POOL
  /* The sequence was drawn at START; walk it. No policy: a pool task has no
     anti-bias estimate, no escalating abstention penalty and no correction
     budgets, and advances on any COMPLETED trial. */
  if (runTrial(*trials[currentTrial], params, clock, nullptr, currentTrial))
  {
    currentTrial++;                   // Advance only on a completed trial
    applyStage(params, currentTrial); // Ramp holds/windows for the new count
    if (currentTrial >= params.numTrials)
      endCurrentSession();
  }
  else
  {
    recordEvent(BF_INVALID_TRIAL); // Trial aborted -- repeat the same slot
  }
#else
  /* Anti-bias and weighted anti-bias both land here; the two selectors differ
     only inside selectNext().
     Pick the next trial live. We only re-select when the previous trial
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
#endif
}

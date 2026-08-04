/*
Author: Chase Johnston
Date: July 29th, 2026
Purpose:
  Shaping paradigm -- a go-RIGHT trial on Odor 1 (SANDALWOOD), eased in.

  The eased variant of shaping_GR: the same paradigm on a longer, softer ramp,
  for an animal that is struggling with the standard shaping schedule.

  This sketch is ONLY: the four trial types, the trial POOL (its default weights
  are the sole thing that differs between the shaping sketches), and the
  setup/loop wiring. The trial runner and the staged ramp live in BehaviorBox.h,
  shared with every other behavior sketch.

  EVERY timing, hold, window, penalty, reward volume, pool weight and stage
  threshold now arrives from the app on the START line and is declared in this
  sketch's task.json -- so they are tuned per sketch and per run, in the Config
  page, instead of by editing and reflashing this file. The values applied by
  applyEasedShapingDefaults() below are only the bare-START fallback for a
  hand-typed console session or an older host.
*/

#include <BehaviorBox.h> // pins, strobes, TaskParams + the shared trial runner

/* ======== Session wiring ======== */
const unsigned long baudRate = 115200;    // Serial baud (matches the app)
const int MAX_TRIALS = 1000;  // Compile-time size of trials[]; params.numTrials
                              // is the runtime cap and is clamped to it below.
int currentTrial = 0;         // Index into trials[]
bool sessionComplete = false; // Session start / end guard

TaskParams params; // every tunable, filled from the START line (BehaviorBox.h)
TrialClock clock;  // trial timestamps

/* recordEvent -> emitStrobe (BehaviorBox.h) bound to this sketch's clock. */
void recordEvent(int eventCode) { emitStrobe(clock, eventCode); }

/* ===== TRIAL TYPES ===== */
// Odors[], the wells, the Fluids[] index macros, and the BF_* codes all come
// from BehaviorBox.h. Two go-right + two go-left options; the pool below decides
// which are actually presented.
const TrialType goRight1(true, Odors[0], rightWell, RIGHT_WELL_FL_1, BF_ODOR_1_ON, BF_FLUID_R, BF_STOP_FLUID_G_R);
const TrialType goRight2(true, Odors[1], rightWell, RIGHT_WELL_FL_1, BF_ODOR_2_ON, BF_FLUID_R, BF_STOP_FLUID_G_R);
const TrialType goLeft1(true, Odors[2], leftWell, LEFT_WELL_FL_1, BF_ODOR_3_ON, BF_FLUID_L, BF_STOP_FLUID_G_L);
const TrialType goLeft2(true, Odors[3], leftWell, LEFT_WELL_FL_1, BF_ODOR_4_ON, BF_FLUID_L, BF_STOP_FLUID_G_L);

/* Pool of available trials. The weights are placeholders -- they are overwritten
   from params.poolWeights (PW1..PW4) after START, so the shaped side is an
   operator setting rather than the one line that used to distinguish the two
   shaping sketches. THE ORDER IS THE CONTRACT: PW1..PW4 map to these four slots
   in order, and task.json labels them accordingly. */
TrialWeight pool[] = {
    {goRight1, 0}, // PW1 -- go-right, odor 1
    {goRight2, 0}, // PW2 -- go-right, odor 2
    {goLeft1, 0},  // PW3 -- go-left,  odor 3
    {goLeft2, 0}};

const TrialType *trials[MAX_TRIALS]; // populated in setup() with seeded randomness

/* Housekeeping for starting a new experiment session */
void beginNewSession()
{
  clock.beginSession();
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
  applyEasedShapingDefaults(params);
  /* Default shaped side: go-RIGHT on odor 1. */
  params.poolWeights[0] = 1;
  params.poolWeights[1] = 0;
  params.poolWeights[2] = 0;
  params.poolWeights[3] = 0;

  /* Handshake with the app: announce READY, then block until a "START" line
     carrying this run's parameters (and its SEED). */
  digitalWrite(trialLight, HIGH); // armed, waiting for GO
  delay(50);                      // let the post-reset serial settle
  Serial.println("READY");

  char cmd[START_LINE_MAX]; // must hold the WHOLE line: readLineInto() truncates
                            // at this cap and a token lost there is silent -- the
                            // session then runs on a value nobody chose.
  while (true)
  {
    if (readLineInto(cmd, sizeof(cmd)) && strncmp(cmd, "START", 5) == 0 && (cmd[5] == '\0' || cmd[5] == ' '))
    {
      parseStartCommand(cmd, params); // fill params (anything unsent keeps its default)
      break;                          // START received
    }
  }

  if (params.numTrials > MAX_TRIALS)
    params.numTrials = MAX_TRIALS; // trials[] is a fixed allocation
  for (int i = 0; i < 4; i++)
    pool[i].weight = params.poolWeights[i];

  /* Seed FIRST, then build the sequence.
     Both halves of that order matter, and both were wrong before. The seed came
     from a compile-time constant (12345), and the sequence was generated in
     setup() before START had even arrived -- so every shaping session ever run,
     on every box, drew the identical trial order. The seed now comes from the
     app on the START line (an OS CSPRNG draw taken at the operator's start
     click) and the pool is sampled from that stream. */
  beginSessionRng(params);
  generateTrials(trials, params.numTrials, params.blockSize, pool, 4);

  // The "armed" indicator going out, not a trial event: the clock is
  // stamped by beginNewSession() on the next line, so a BF_LIGHTS_OFF here
  // would carry a pre-session timestamp and precede BF_START_SESSION.
  digitalWrite(trialLight, LOW);
  beginNewSession(); // stamps t=0, fires BF_START_SESSION
}

void loop()
{
  if (sessionComplete)
    return;

  /* Honor a remote STOP at the trial boundary (never mid-trial, so the strobe
     stream's structure stays intact for downstream analysis). */
  if (checkForStop())
  {
    endCurrentSession();
    return;
  }

  /* Run one trial through the shared runner. nullptr = no session policy:
     shaping has no anti-bias selection, no escalating abstention penalty and no
     correction budgets, and advances on any COMPLETED trial. */
  if (runTrial(*trials[currentTrial], params, clock, nullptr, currentTrial))
  {
    currentTrial++;                  // advance only on a completed trial
    applyStage(params, currentTrial); // ramp holds/windows for the new count
    if (currentTrial >= params.numTrials)
      endCurrentSession();
  }
  else
  {
    recordEvent(BF_INVALID_TRIAL); // trial aborted -- repeat the same slot
  }
}

/*
Author: Chase Johnston
Date: May 8th, 2026
Purpose:
  Shaping paradigm -- a go-RIGHT trial on Odor 1 (SANDALWOOD).

  The entire shaping behavior (the trial runner + the staged ramp of
  odorPokeHold / fluidWellHold / fluidWellPoll / odorPortTimeout) lives in
  BehaviorBox.h, shared with shaping_GL. This sketch is ONLY: the four trial
  types, the trial POOL (which is the sole thing that differs from shaping_GL --
  here go-right has all the weight), and the setup/loop wiring.

  Adjust the holds/windows by editing shapingApplyStage()'s stage schedule in
  BehaviorBox.h (shared by both shaping sketches).
*/

#include <BehaviorBox.h> // pins, strobes, ShapingTimings + the shared shaping runner

/* ======== Session parameters ======== */
const int baudRate = 9600;    // Serial baud (matches the app)
const int numTrials = 1000;   // Session cap (size of trials[])
const int blockSize = 30;     // Trials per block (pool proportions enforced within each block)
int currentTrial = 0;         // Index into trials[]
bool sessionComplete = false; // Session start / end guard

SessionConfig sessionCfg; // populated from the START line in setup()

ShapingTimings timing; // mutable holds/windows the stage schedule ramps (BehaviorBox.h)
TrialClock clock;      // trial timestamps

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

/* Pool of available trials + weights. THE ONLY DIFFERENCE from shaping_GL:
   here the go-RIGHT trial (Odor 1) carries all the weight. */
const TrialWeight pool[] = {
    {goRight1, 1}, // Go-right -- odor 1 (the shaped side)
    {goRight2, 0},
    {goLeft1, 0}, // Go-left  -- odor 3
    {goLeft2, 0}};

const TrialType *trials[numTrials]; // populated in setup() with seeded randomness

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

  /* Handshake with the app: announce READY, then block until a "START" line.
     Shaping declares no config fields of its own, so the only token it reads is
     the run's SEED; any other key the host appends is accepted and ignored. */
  digitalWrite(trialLight, HIGH); // armed, waiting for GO
  delay(50);                      // let the post-reset serial settle
  Serial.println("READY");

  char cmd[96]; // must hold the whole line, SEED token included -- readLineInto()
                // truncates at this cap, and a SEED lost there drops the session
                // back onto the weak clock fallback
  while (true)
  {
    if (readLineInto(cmd, sizeof(cmd)) && strncmp(cmd, "START", 5) == 0 && (cmd[5] == '\0' || cmd[5] == ' '))
    {
      parseStartCommand(cmd, sessionCfg);
      break; // START received
    }
  }

  /* Seed FIRST, then build the sequence.
     Both halves of that order matter, and both were wrong before. The seed came
     from a compile-time constant (12345), and the sequence was generated in
     setup() before START had even arrived -- so every shaping session ever run,
     on every box, drew the identical trial order. The seed now comes from the
     app on the START line (an OS CSPRNG draw taken at the operator's start
     click) and the pool is sampled from that stream. */
  beginSessionRng(sessionCfg);
  generateTrials(trials, numTrials, blockSize, pool, sizeof(pool) / sizeof(pool[0]));

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

  /* Run one shaping trial (shared runner in BehaviorBox.h). */
  if (shapingOdorSampling(*trials[currentTrial], timing, clock))
  {
    currentTrial++;                       // advance only on a completed trial
    shapingApplyStage(timing, currentTrial); // ramp holds/windows for the new count
    if (currentTrial >= numTrials)
      endCurrentSession();
  }
  else
  {
    recordEvent(BF_INVALID_TRIAL); // trial aborted -- repeat the same slot
  }
}

/*
GRGL_Sim.ino -- serial simulator for the GRGL 2-odor task.
Author: Chase Johnston

Emits the strobe stream the real GRGL_2-Odor sketch would, over the same serial
protocol (announce "READY", wait for a "START" line, emit a "SEED<TAB>value"
line, then send tab-separated "CODE<TAB>MS" lines), so the app can be exercised
end-to-end without an Arduino wired to the rig. No pins are driven -- this only
talks serial, so it runs on any board.

A "STOP" line is honoured at the next trial boundary, exactly as the real
firmware's checkForStop(): the trial in progress completes, then the session
ends early with BF_END_SESSION -- so the host's Stop button and the session time
limit both work against the sim.

IT RUNS ON THE REAL PARAMETERS. Every phase duration below is read from the same
TaskParams the real firmware fills from the START line, and the anti-bias draw
is the firmware's own AntiBiasSelector rather than a copy of it. That is the
point of the sim: it is the one sketch you can flash to a bare board and use to
prove the app's whole parameter path -- a fully-declared task.json, a ~500-char
START line, every token landing on the value the operator typed -- without an
animal, a solenoid or a drop of fluid. A sim carrying its own private constants
would pass while the rig's parameter path was broken. It also walks the stage
ramp, so a ramped profile's stage boundaries are visible in the stream.

It models a WELL-DISCRIMINATING, WARMING-UP, SATIATING rat so the live views all
have something to render:
  - Discrimination: POLICY_ODOR ramps accuracy ~10% -> ~80% SYMMETRICALLY for
    both odor->side directions, so the scissor's two blades both open.
  - Warm-up: early trials abstain more (low engagement), easing to a steady
    mid-session rate -- an engagement warm-up on top of the accuracy ramp.
  - Satiation: abstention rises again over the last ~15% (FATIGUE_FRAC), but
    stays < 1 so administered trials persist to the end.
MOVEMENT TIMES are drawn per trial (correct faster/tighter, errors slower/wider,
go-left a touch slower) so the RT distributions stay distinct.

TIMING IS REAL TIME. Every inter-strobe gap is the actual phase duration the
real firmware would spend there, taken from the same TaskParams -- so the
timestamps this sketch prints are the timestamps a real run of the same START
line would print, and a simulated session takes as long as the real one. That
includes the slow parts: a 20 s errorDelay is twenty seconds here too, and the
abstention penalty escalates exactly as runTrial() escalates it. Anything the
app derives from inter-event timing (hold durations, movement times, session
length, the live views' pacing) is therefore being fed the real distribution
rather than a compressed one.

SIM_SPEEDUP survives as a debugging escape hatch, and 1 is the only value that
tells the truth. Raising it divides every gap in ONE place (emit() and the
inter-trial gap), leaving codes and order identical but making the printed
timestamps a fraction of a real session's millis() -- useful for a quick smoke
test of the app's whole strobe path, never for anything that reads the clock.

Outcomes covered, with the strobe sequence each emits (mirrors runTrial() /
checkResponse() in BehaviorBox.h):

  Administered Go trial = LIGHTS_ON, ODOR_POKE, ODOR_x_ON,
                          ODOR_OFF, ODOR_UNPOKE, LIGHTS_OFF, then one well outcome:
    reward        -> WATER_POKE(side), FLUID(side), STOP_FLUID(side),
                     WATER_UNPOKE(side), END_CORRECT_ITI
    hold-fail     -> WATER_POKE(side), WATER_UNPOKE_EARLY(side),
                     END_INCORRECT_ITI   (correct well, released before the
                     fluidWellHold -- a consummatory hold failure, NOT a wrong
                     choice; terminates with END_INCORRECT_ITI exactly as the
                     firmware does after delay(noPokeHoldTimeout))
    wrong well    -> WATER_POKE(other), WATER_POKE_ERROR(other),
                     END_INCORRECT_ITI

  Aborted trial (no ODOR_UNPOKE; firmware strobes INVALID_TRIAL too):
    lazy rat            -> LIGHTS_ON, LIGHTS_OFF, LAZY_RAT, INVALID_TRIAL
    early odor (pre-vac)-> LIGHTS_ON, ODOR_POKE, LIGHTS_OFF,
                           ODOR_UNPOKE_EARLY, INVALID_TRIAL   (no odor-on code)
    early odor (sample) -> LIGHTS_ON, ODOR_POKE, ODOR_x_ON, LIGHTS_OFF,
                           ODOR_UNPOKE_EARLY, INVALID_TRIAL
*/

#include <BehaviorBox.h> // strobe vocabulary, TaskParams, the shared anti-bias selector

const int baudRate = 9600; // must match the app

/* ===== Real-time by default =====
   1 = every gap is the real phase duration, which is the point of the sketch.
   A larger value divides every delay in ONE place (emit() + interTrialGap()),
   compressing the session to 1/SIM_SPEEDUP wall-clock time with the codes and
   their order unchanged. Only ever raise it for a throwaway smoke test: the
   printed timestamps stop being a real session's, so every duration the app
   derives from them (movement times, hold failures, session length) is wrong by
   that factor -- silently, because the stream still looks perfectly well-formed. */
const int SIM_SPEEDUP = 1;

/* Every phase duration comes from here, filled by the START line. */
TaskParams params;

/* Small rat-controlled beam latencies the firmware spends polling IR sensors.
   Not firmware parameters -- they fill the phases the rat drives, which are the
   only gaps in the stream a parameter cannot supply. Everything else comes from
   params.

   There is deliberately no constant for the wrong-well rejection: checkResponse()
   strobes WATER_POKE_x and then WATER_POKE_ERROR_x back to back with no delay
   between them, because the same beam-break that reports the poke is what
   classifies it. The gap in the real stream is one serial line's transmission
   time, which the sim inherits for free by printing the same two lines. */
const int APPROACH_TIME = 300; // lights on -> odor poke (an engaged rat)
const int WITHDRAW_TIME = 150; // odor off -> odor unpoke; fluid well unpoke

/* Session shape (the rat model, not the task -- the task is params). */
const float SIM_START_ACC = 0.10; // POLICY_ODOR accuracy at trial 0
const float SIM_END_ACC = 0.80;   // POLICY_ODOR accuracy by the last trial

/* Engagement model (abstention probability over the session). A U-shape: high
   early (warm-up), low and steady mid-session, rising late (satiation). */
const float WARMUP_FRAC = 0.15;   // engagement warms up over the first ~15%
const float FATIGUE_FRAC = 0.85;  // satiation: aborts rise over the last ~15%
const float ABORT_WARMUP = 0.35;  // abstain prob at trial 0
const float ABORT_STEADY = 0.07;  // steady mid-session abstain prob
const float ABORT_FATIGUE = 0.22; // late satiation abstain prob (< 1)

/* Hold-fail: on a correct-well trial the rat sometimes releases before the
   fluidWellHold. Intentional sim artifact: the RIGHT well leaks more than the
   LEFT, so the lateralized hold-time views have a side asymmetry to show. */
const float HOLD_FAIL_PROB_R = 0.18;
const float HOLD_FAIL_PROB_L = 0.06;

/* Simulated-rat policy -- how the rat picks a well given the correct side. */
#define POLICY_ALWAYS_RIGHT 0 // ignores odor, always goes right (shows anti-bias at work)
#define POLICY_RANDOM 1       // ignores odor, 50/50
#define POLICY_ODOR 2         // uses odor: picks correct side with ramping accuracy
const int SIM_POLICY = POLICY_ODOR;

/* The trial types and the selector are the firmware's own (BehaviorBox.h), not a
   mirror of them -- the sim's job is to exercise the real logic. */
const TrialType simGoRight(true, Odors[0], rightWell, RIGHT_WELL_FL_1, BF_ODOR_1_ON, BF_FLUID_R, BF_STOP_FLUID_G_R);
const TrialType simGoLeft(true, Odors[2], leftWell, LEFT_WELL_FL_1, BF_ODOR_3_ON, BF_FLUID_L, BF_STOP_FLUID_G_L);
AntiBiasSelector selector(&simGoRight, &simGoLeft);

/* The lazy penalty is the firmware's own escalator, for the same reason the
   selector is: a flat lazyRatDelay is not what a real abstention costs. GRGL
   2-Odor hands runTrial() an AbstentionPenalty, so consecutive abstentions are
   charged base + n*step up to lazyDelayMax -- 6 s, then 12 s, then 18 s on the
   defaults. The sim's rat abstains in runs (35% early, 22% late), so a flat
   penalty understated a warm-up by tens of seconds per run of them. */
AbstentionPenalty abstention;

unsigned long sessionStart = 0;

/* Print one event in the rig's standard "CODE<TAB>MS" format, then wait out the
   phase that follows it. `gap` is the REAL duration of that phase, so at the
   default SIM_SPEEDUP of 1 the wait is exactly what the firmware would spend
   there; this division is the one place the whole stream could be compressed. */
void emit(int code, int gap)
{
  unsigned long ts = millis() - sessionStart;
  char buf[16];
  sprintf(buf, "%03d\t%lu", code, ts);
  Serial.println(buf);
  int d = gap / SIM_SPEEDUP;
  if (d > 0)
    delay(d);
}

/* The inter-trial gap: the firmware's odor priming before the next lights-on. */
void interTrialGap()
{
  delay(params.primingDelay / SIM_SPEEDUP);
}

/* Accuracy "learning curve" for POLICY_ODOR: a cubic smoothstep S-curve from
   SIM_START_ACC up to SIM_END_ACC across the WHOLE session. Smoothstep stays low
   early (the rat struggles), accelerates through chance mid-session, and
   plateaus near SIM_END_ACC by the end. */
float rewardProb(int i)
{
  if (params.numTrials <= 1)
    return SIM_END_ACC;
  float frac = (float)i / (params.numTrials - 1);
  if (frac < 0) frac = 0;
  if (frac > 1) frac = 1;
  float s = frac * frac * (3.0 - 2.0 * frac); // smoothstep (slow-fast-slow S)
  return SIM_START_ACC + (SIM_END_ACC - SIM_START_ACC) * s;
}

/* Abstention probability for trial i -- the engagement curve. A U-shape: high
   early (warm-up), low and steady mid-session, rising to ABORT_FATIGUE over the
   last (1 - FATIGUE_FRAC). Always < 1, so administered trials persist at both
   ends. */
float abortProbAt(int i)
{
  int warmEnd = (int)(WARMUP_FRAC * params.numTrials);
  int fatigueStart = (int)(FATIGUE_FRAC * params.numTrials);
  if (warmEnd > 0 && i < warmEnd)
  {
    float w = (float)i / warmEnd;
    return ABORT_WARMUP + (ABORT_STEADY - ABORT_WARMUP) * w;
  }
  if (i >= fatigueStart)
    return ABORT_FATIGUE;
  return ABORT_STEADY;
}

/* Simulated rat: returns true if the rat pokes the RIGHT well this trial.
   correctIsRight = the trial's correct side; i = trial index (for the ramp). */
bool ratGoesRight(bool correctIsRight, int i)
{
  switch (SIM_POLICY)
  {
  case POLICY_ALWAYS_RIGHT:
    return true;
  case POLICY_ODOR:
  {
    bool correctPick = grglFrand() < rewardProb(i); // accuracy ramps with learning
    return correctPick ? correctIsRight : !correctIsRight;
  }
  case POLICY_RANDOM:
  default:
    return grglFrand() < 0.5;
  }
}

/* Draw a plausible movement time (ms): correct choices are faster and tighter,
   errors slower and more variable; go-left a touch slower so the two directions
   separate. Clamped inside the run's own response window -- which is now an
   operator setting, so the old fixed 1950 ms ceiling could sit outside it. */
int movementTime(bool goRight, bool correct)
{
  int base = correct ? 400 : 850;
  int jitter = correct ? 150 : 300;
  if (!goRight)
    base += 100;
  int m = base + (int)random(-jitter, jitter + 1);
  int cap = params.fluidWellPoll - 50;
  if (cap < 100)
    cap = 100;
  if (m < 80) m = 80;
  if (m > cap) m = cap;
  return m;
}

/* Real-scale ms the rat managed to hold the correct well before releasing on a
   hold-fail -- always below the run's fluidWellHold. Mostly near-misses hugging
   the threshold, with a tail of earlier releases. Scaled off the parameter
   rather than the old hard-coded 500, which on an eased profile's 10 ms hold
   would have asked random() for an empty range. */
int holdFailDuration()
{
  int hold = params.fluidWellHold;
  if (hold < 10)
    return hold > 1 ? (int)random(1, hold) : 0;
  if (grglFrand() < 0.6)
    return random(hold * 4 / 5, hold - 1); // near-miss cluster
  return random(hold / 5, hold * 4 / 5);   // earlier releases
}

/* A partial odor-port hold (ms) for an early-unpoke abort: below the run's
   odorPokeHold, which the firmware requires. */
int partialOdorHold()
{
  int hold = params.odorPokeHold;
  if (hold < 10)
    return hold > 1 ? (int)random(1, hold) : 0;
  return random(hold / 4, hold - 5);
}

/* Well outcomes for an administered Go trial. */
#define OUT_REWARD 0     // correct well, held to fluid        -> reward
#define OUT_WRONG_WELL 1 // wrong well                         -> error
#define OUT_HOLD_FAIL 2  // correct well, released before hold -> hold-fail

/* One administered Go trial: odor sampled to completion, then a well outcome.
   goRight -> odor 1 / right well is correct; else odor 3 / left well. Each gap
   is the real phase that follows the strobe; emit() compresses by SIM_SPEEDUP. */
void goTrial(bool goRight, int outcome)
{
  emit(BF_LIGHTS_ON, APPROACH_TIME);          // lights on -> rat pokes odor port
  emit(BF_ODOR_POKE, params.odorPokeHold);    // pre-odor hold before odor delivery
  emit(goRight ? BF_ODOR_1_ON : BF_ODOR_3_ON,
       params.odorPokeHold);                  // vac closed, odor sample hold
  emit(BF_ODOR_OFF, WITHDRAW_TIME);           // odor off -> rat withdraws
  bool correct = (outcome != OUT_WRONG_WELL); // reward & hold-fail are both correct-well
  emit(BF_ODOR_UNPOKE, 0);   // withdrew from the port; the light drops next
  emit(BF_LIGHTS_OFF, movementTime(goRight, correct)); // then movement to the well
  int rewardIndex = goRight ? RIGHT_WELL_FL_1 : LEFT_WELL_FL_1;
  switch (outcome)
  {
  case OUT_REWARD: // correct well, held to fluid
    emit(goRight ? BF_WATER_POKE_R : BF_WATER_POKE_L,
         params.fluidWellHold); // hold cleared -> fluid
    emit(goRight ? BF_FLUID_R : BF_FLUID_L, params.fluidPinTimes[rewardIndex]);
    emit(goRight ? BF_STOP_FLUID_G_R : BF_STOP_FLUID_G_L,
         WITHDRAW_TIME); // drinking, then the animal withdraws
    emit(goRight ? BF_WATER_UNPOKE_R : BF_WATER_UNPOKE_L,
         params.standardITI); // left the well -- the ITI runs from here
    emit(BF_END_CORRECT_ITI, 0);
    // Where runTrial() clears it: only a COMPLETED CORRECT trial defuses the
    // escalator. A hold-fail or a wrong well ends on END_INCORRECT_ITI and
    // leaves the counter standing, and so must the two cases below.
    abstention.reset();
    break;
  case OUT_HOLD_FAIL: // correct well, released early
    // Mirrors checkResponse(): WATER_POKE(correct side) then, when the hold
    // fails, WATER_UNPOKE_EARLY(correct side); the firmware then waits
    // noPokeHoldTimeout and runTrial() emits END_INCORRECT_ITI.
    emit(goRight ? BF_WATER_POKE_R : BF_WATER_POKE_L,
         holdFailDuration()); // released before fluidWellHold
    emit(goRight ? BF_WATER_UNPOKE_EARLY_R : BF_WATER_UNPOKE_EARLY_L,
         params.noPokeHoldTimeout); // failure-to-hold timeout
    emit(BF_END_INCORRECT_ITI, 0);
    break;
  case OUT_WRONG_WELL: // poke the OTHER well, then its error
    emit(goRight ? BF_WATER_POKE_L : BF_WATER_POKE_R, 0); // classified immediately
    emit(goRight ? BF_WATER_POKE_ERROR_L : BF_WATER_POKE_ERROR_R,
         params.errorDelay); // wrong-well timeout
    emit(BF_END_INCORRECT_ITI, 0);
    break;
  }
}

/* Lazy rat: light on, rat never engages the odor port, board times out after the
   full odorPortTimeout, then serves the abstention penalty before the trial
   aborts. `completedTrials` is the advancing-trial count, which is the only thing
   runTrial() uses it for -- escalationArmed() holds the escalator off until the
   run has reached lazyEscalationStage, so an animal still being shaped is never
   escalated against. */
void lazyTrial(int completedTrials)
{
  emit(BF_LIGHTS_ON, params.odorPortTimeout); // whole poke window elapses, no poke
  emit(BF_LIGHTS_OFF, 0);
  emit(BF_LAZY_RAT,
       (int)abstention.nextDelay(escalationArmed(params, completedTrials)));
  emit(BF_INVALID_TRIAL, 0);
}

/* Early odor unpoke before the vacuum closed -- odor was never delivered, so NO
   odor-on code is sent. The firmware waits noPokeHoldTimeout on a failed hold. */
void earlyOdorPreVac()
{
  emit(BF_LIGHTS_ON, APPROACH_TIME);
  emit(BF_ODOR_POKE, partialOdorHold()); // bails before the pre-odor hold completes
  emit(BF_LIGHTS_OFF, 0);
  emit(BF_ODOR_UNPOKE_EARLY, params.noPokeHoldTimeout);
  emit(BF_INVALID_TRIAL, 0);
}

/* Early odor unpoke during sampling -- odor-on IS sent (the rat cleared the
   pre-odor hold), but it left before ODOR_OFF, so there's no ODOR_OFF /
   ODOR_UNPOKE (not administered). */
void earlyOdorSampling(bool goRight)
{
  emit(BF_LIGHTS_ON, APPROACH_TIME);
  emit(BF_ODOR_POKE, params.odorPokeHold); // cleared pre-odor hold -> odor on
  emit(goRight ? BF_ODOR_1_ON : BF_ODOR_3_ON,
       partialOdorHold()); // bails during the sample hold
  emit(BF_LIGHTS_OFF, 0);
  emit(BF_ODOR_UNPOKE_EARLY, params.noPokeHoldTimeout);
  emit(BF_INVALID_TRIAL, 0);
}

/* Mirror the real handshake: announce READY, block until a "START" line, and
   parse its key=value config exactly as the real firmware does -- one buffer,
   one cap, the shared parser. */
void waitForStart(TaskParams &p)
{
  char buf[START_LINE_MAX]; // the firmware's cap, from the shared header
  Serial.println("READY");
  while (true)
  {
    if (readLineInto(buf, sizeof(buf)) && strncmp(buf, "START", 5) == 0 && (buf[5] == '\0' || buf[5] == ' '))
    {
      parseStartCommand(buf, p);
      return;
    }
  }
}

/* Mid-session STOP uses BehaviorBox.h's own checkForStop() -- the exact
   non-blocking poll the real firmware calls once per trial boundary. The sim
   spends its whole session inside delay()s, so a STOP sent by the host just
   accumulates in the RX buffer until the next boundary drains it. */

void setup()
{
  Serial.begin(baudRate);
  delay(50); // let the post-reset serial settle

  /* Bare-START fallback only -- the app always sends NT. Kept well below the real
     task's 1000 because at real timing that is hours: 200 trials is already
     ~40 min, which is long enough to watch the ramp move and short enough that a
     bare START is not an accidental afternoon. */
  params.numTrials = 200;

  waitForStart(params);

  // Seed and report it, exactly as the firmware does on START -- host-supplied
  // SEED, clock fallback, same echo (BehaviorBox.h). Sharing the real helper is
  // the point: a sim that seeded itself would pass while the rig's seeding path
  // was broken.
  beginSessionRng(params);
  selector.configure(params);
  abstention.configure(params); // base, step, ceiling and the GUI on/off toggle

  sessionStart = millis();
  emit(BF_START_SESSION, params.primingDelay); // odor priming before the first lights-on

  int completed = 0; // advancing trials, which is what the stage ramp counts
  for (int i = 0; i < params.numTrials; i++)
  {
    // 0. Trial boundary: honour a STOP that arrived during the last trial --
    //    the same once-per-boundary check the real firmware makes.
    if (checkForStop())
      break;

    // 1. The firmware's own selector picks this trial's correct side.
    bool goRight = (selector.selectNext() == &simGoRight);

    // 2. Engagement: abstain more early (warm-up) and late (satiation), steady
    //    in between. Always < 1, so administered trials persist at both ends.
    if (grglFrand() < abortProbAt(i))
    {
      float a = grglFrand();
      if (a < 0.70)
        lazyTrial(completed); // no expressed choice -> bias unchanged
      else if (a < 0.85)
        earlyOdorPreVac();
      else
        earlyOdorSampling(goRight);
      interTrialGap();
      continue; // an abort does not advance, so the ramp does not move
    }

    // 3. Administered trial: the simulated rat picks a well per its policy.
    bool ratRight = ratGoesRight(goRight, i);
    bool correct = (ratRight == goRight);
    int outcome;
    if (!correct)
    {
      outcome = OUT_WRONG_WELL; // wrong well -> discrimination error
    }
    else
    {
      // Correct side reached -- but the rat sometimes releases before the
      // fluidWellHold (a hold-fail), more often on the right well (sim artifact).
      float pHoldFail = goRight ? HOLD_FAIL_PROB_R : HOLD_FAIL_PROB_L;
      outcome = (grglFrand() < pHoldFail) ? OUT_HOLD_FAIL : OUT_REWARD;
    }
    goTrial(goRight, outcome);
    selector.recordChoice(ratRight); // expressed side feeds the anti-bias estimate

    completed++;
    applyStage(params, completed); // walk the ramp, so a staged profile is visible
    interTrialGap();
  }

  emit(BF_END_SESSION, 0);
}

void loop()
{
  // One-shot script runs in setup(); nothing to do once the session ends.
}

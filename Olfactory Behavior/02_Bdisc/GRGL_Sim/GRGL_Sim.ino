/*
GRGL_Sim.ino — serial simulator for the GRGL 2-odor task.
Author: Chase Johnston

Emits the strobe stream the real GRGL_2-Odor sketch would, over the same
serial protocol (announce "READY", wait for a "START" line, emit a
"SEED<TAB>value" line, then send tab-separated "CODE<TAB>MS" lines), so
dashboard.py / read_arduino.py can be exercised end-to-end without an Arduino
wired to the rig. No pins are driven — this only talks serial, so it runs on
any board.

A "STOP" line is honoured at the next trial boundary, exactly as the real
firmware's checkForStop(): the trial in progress completes, then the session
ends early with BF_END_SESSION — so the host's Stop button and the session
time limit both work against the sim.

This build mirrors the firmware's two confound-closing changes so they can
be validated off-rig:
  - SEED line: the host's SEED=<n> token is parsed off the START line, used
    verbatim, and echoed back as "SEED<TAB>value", so the app's seed-issuing
    and seed-capture paths are both exercised end to end.
  - Adaptive anti-bias selection: the SAME selectNextTrial() logic as the
    firmware chooses each trial's correct side against the rat's recent
    expressed bias. A configurable SIM_POLICY models the rat — the default
    POLICY_ODOR models a rat that LEARNS the odor->side mapping over the
    session (accuracy ramps from ~10% to ~80%); switch to POLICY_ALWAYS_RIGHT
    to instead watch the debias push the correct side toward LEFT while a
    right-biased rat's reward rate falls.

It models a WELL-DISCRIMINATING, WARMING-UP, SATIATING rat so the live
dashboard's learning views (the scissor plot, the chose-correct-vs-earned
stack, the lateralized hold-time strip) all have something to render:
  - Discrimination: POLICY_ODOR ramps accuracy ~10% -> ~80% SYMMETRICALLY for
    both odor->side directions, so the scissor's two blades both open.
  - Warm-up: early trials abstain more (low engagement), easing to a steady
    mid-session rate -- an engagement warm-up on top of the accuracy ramp.
  - Satiation: abstention rises again over the last ~15% (FATIGUE_FRAC), but
    stays < 1 so administered trials persist to the end.
MOVEMENT TIMES are drawn per trial (correct faster/tighter, errors
slower/wider, go-left a touch slower) so the RT distributions stay distinct.

TIMING IS A FAITHFUL 1/4-SCALE MODEL OF THE REAL FIRMWARE. Every inter-strobe
gap is built from the real GRGL_2-Odor.ino phase duration it represents (see
the REAL_* constants below), then divided by SIM_SPEEDUP (=4) in ONE place --
emit() and the inter-trial gap -- so the whole stream runs at exactly 1/4
wall-clock time with the strobe codes and their order left identical to the
firmware. The timestamps the sim PRINTS are therefore ~1/4 of a real session's
millis(); that is intended (faster-than-real replay for exercising the GUI).
One consequence worth noting: the well-hold durations the dashboard's A3 strip
reads off the printed stream are likewise ~1/4 scale, so against the strip's
real 500 ms fluidWellHold line the simulated holds sit low -- a real (un-sped)
session is what makes those dots hug the line.

Outcomes covered, with the strobe sequence each emits (mirrors the real
sketch's control flow in odorSampling()/checkResponse()):

  Administered Go trial = LIGHTS_ON, ODOR_POKE, ODOR_x_ON,
                          ODOR_OFF, ODOR_UNPOKE, then one well outcome:
    reward        -> WATER_POKE(side), FLUID(side), STOP_FLUID(side),
                     END_CORRECT_ITI
    hold-fail     -> WATER_POKE(side), WATER_UNPOKE_EARLY(side),
                     END_INCORRECT_ITI   (correct well, released before the
                     fluidWellHold -- a consummatory hold failure, NOT a wrong
                     choice; terminates with END_INCORRECT_ITI exactly as the
                     firmware does after delay(noPokeHoldTimeout) -- the
                     firmware emits INVALID_TRIAL only from loop() as a
                     correction-repeat marker, which the default sim never hits)
    wrong well    -> WATER_POKE(other), WATER_POKE_ERROR(other),
                     END_INCORRECT_ITI

  Aborted trial (no ODOR_UNPOKE; firmware strobes INVALID_TRIAL too):
    lazy rat            -> LIGHTS_ON, LAZY_RAT, INVALID_TRIAL
    early odor (pre-vac)-> LIGHTS_ON, ODOR_POKE, ODOR_UNPOKE_EARLY,
                           INVALID_TRIAL                 (no odor-on code)
    early odor (sample) -> LIGHTS_ON, ODOR_POKE, ODOR_x_ON,
                           ODOR_UNPOKE_EARLY, INVALID_TRIAL
*/

#include <BehaviorBox.h> // shared strobe vocabulary (the BF_* codes); the sim keeps its own self-contained rat model

const int  baudRate   = 9600;   // must match read_arduino.py

/* ===== 4x-faster-than-real timing model =====
   SIM_SPEEDUP divides every delay in ONE place (emit() + interTrialGap()), so
   the whole simulated session runs at exactly 1/SIM_SPEEDUP wall-clock time.
   The REAL_* values are the actual GRGL_2-Odor.ino phase durations (ms); each
   inter-strobe gap below is assembled from them so it models the real phase it
   represents. Strobe codes/order are unchanged -- only timing compresses. */
const int SIM_SPEEDUP = 4;

const int REAL_PRIMING_DELAY     = 1000;  // odor primed before lights on (primingDelay)
const int REAL_ODOR_PORT_TIMEOUT = 4000;  // window to poke after lights on (odorPortTimeout)
const int REAL_ODOR_POKE_HOLD    = 500;   // pre-odor hold AND odor sample hold (odorPokeHold)
const int REAL_FLUID_WELL_HOLD   = 500;   // correct-well hold before fluid (fluidWellHold)
const int REAL_FLUID_WELL_POLL   = 2000;  // response window after sampling (fluidWellPoll)
const int REAL_STANDARD_ITI      = 4000;  // inter-trial interval, correct (standardITI)
const int REAL_ERROR_DELAY       = 20000; // timeout after a wrong well (errorDelay)
const int REAL_LAZY_RAT_DELAY     = 6000;  // base lazy timeout (lazyRatDelay)
const int REAL_NO_POKE_HOLD_TO   = 10000; // failure-to-hold timeout (noPokeHoldTimeout)
const int REAL_FLUID_DURATION    = 100;   // drop delivery (FluidPinTimes)

/* Small rat-controlled beam latencies the firmware spends polling IR sensors.
   Not separate firmware constants -- they fill the phases the rat drives (the
   poke after lights-on, the withdrawal, the immediate wrong-well rejection). */
const int APPROACH_TIME    = 300;  // lights on -> odor poke (an engaged rat)
const int WITHDRAW_TIME    = 150;  // odor off -> odor unpoke; fluid well unpoke
const int WRONG_WELL_REACT = 50;   // wrong-well poke -> its error strobe (immediate)

/* Session shape. */
const int   NUM_TRIALS    = 200;   // total trials in the run
const float SIM_START_ACC = 0.10;  // POLICY_ODOR accuracy at trial 0 (struggling, within 0-20%)
const float SIM_END_ACC   = 0.80;  // POLICY_ODOR accuracy by the last trial (~80%, good discriminator)

/* Engagement model (abstention probability over the session). A U-shape: high
   early (warm-up), low and steady mid-session, rising late (satiation). */
const float WARMUP_FRAC   = 0.15;  // engagement warms up over the first ~15% of trials
const float FATIGUE_FRAC  = 0.85;  // satiation: aborts rise again over the last ~15%
const float ABORT_WARMUP  = 0.35;  // abstain prob at trial 0 (low early engagement)
const float ABORT_STEADY  = 0.07;  // steady mid-session abstain prob
const float ABORT_FATIGUE = 0.22;  // late satiation abstain prob (< 1: admin trials persist)

/* Hold-fail: on a correct-well trial the rat sometimes releases before the
   fluidWellHold (a consummatory failure, not a wrong choice). Intentional sim
   artifact: the RIGHT well leaks more than the LEFT, so the A3 lateralized
   hold-time strip has a side asymmetry to show. */
const float HOLD_FAIL_PROB_R = 0.18;  // right correct-well early-release rate
const float HOLD_FAIL_PROB_L = 0.06;  // left  correct-well early-release rate

/* Simulated-rat policy -- how the rat picks a well given the correct side. */
#define POLICY_ALWAYS_RIGHT 0   // ignores odor, always goes right (shows anti-bias at work)
#define POLICY_RANDOM       1   // ignores odor, 50/50
#define POLICY_ODOR         2   // uses odor: picks correct side with ramping accuracy
const int SIM_POLICY = POLICY_ODOR;

/* ===== Anti-bias selector (mirrors GRGL_2-Odor.ino) ===== */
const int   biasWindow         =  20;
const float debiasStrength     =  0.5;
const float pSideMin           =  0.10;
const float pSideMax           =  0.90;
const int   maxConsecutiveSide =  3;

int  choiceRing[biasWindow];
int  choiceRingLen = 0;
int  choiceRingIdx = 0;
int  rightInWindow = 0;

#define SIDE_NONE  -1
#define SIDE_LEFT   0
#define SIDE_RIGHT  1
int  lastSelectedSide = SIDE_NONE;
int  selectedSideRun  = 0;

/* Strobe codes (BF_*) come from BehaviorBox.h now -- the sim emits the exact
   same vocabulary as the real GRGL_2-Odor firmware, from one source. */

unsigned long sessionStart = 0;

/* Print one event in the rig's standard "CODE<TAB>MS" format, then wait
   `gap` real-firmware ms (divided by SIM_SPEEDUP) before the next strobe.
   `gap` is the REAL duration of the phase that follows this strobe; dividing
   here is the single point that makes the whole stream 1/SIM_SPEEDUP-scale.
   The gap after ODOR_UNPOKE doubles as the movement time, since the next
   strobe is the well poke; the gap after a correct WATER_POKE is the well
   hold (fluidWellHold for a reward, a shorter near-miss for a hold-fail). */
void emit(int code, int gap) {
  unsigned long ts = millis() - sessionStart;
  char buf[16];
  sprintf(buf, "%03d\t%lu", code, ts);
  Serial.println(buf);
  int d = gap / SIM_SPEEDUP;
  if (d > 0) delay(d);
}

/* The inter-trial gap: the firmware's odor priming before the next lights-on.
   The other place (besides emit) where SIM_SPEEDUP is applied. */
void interTrialGap() {
  delay(REAL_PRIMING_DELAY / SIM_SPEEDUP);
}

/* Uniform random float in [0, 1). */
float frand() {
  return random(0, 10000) / 10000.0;
}

/* ----- Anti-bias selector, identical logic to the firmware ----- */
void recordChoice(bool wentRight) {
  if (choiceRingLen == biasWindow) {
    rightInWindow -= choiceRing[choiceRingIdx];
  } else {
    choiceRingLen++;
  }
  choiceRing[choiceRingIdx] = wentRight ? 1 : 0;
  rightInWindow += choiceRing[choiceRingIdx];
  choiceRingIdx = (choiceRingIdx + 1) % biasWindow;
}

/* Returns true if the next trial's CORRECT side is right. */
bool selectNextGoRight() {
  float pRight = 0.5;
  if (choiceRingLen > 0) {
    float bias = (2.0 * rightInWindow - choiceRingLen) / (float)choiceRingLen;
    pRight = 0.5 - debiasStrength * bias;
    if (pRight < pSideMin) pRight = pSideMin;
    if (pRight > pSideMax) pRight = pSideMax;
  }

  bool chooseRight = frand() < pRight;
  int  candidateSide = chooseRight ? SIDE_RIGHT : SIDE_LEFT;

  if (candidateSide == lastSelectedSide && selectedSideRun >= maxConsecutiveSide) {
    chooseRight = !chooseRight;
    candidateSide = chooseRight ? SIDE_RIGHT : SIDE_LEFT;
  }

  if (candidateSide == lastSelectedSide) {
    selectedSideRun++;
  } else {
    lastSelectedSide = candidateSide;
    selectedSideRun = 1;
  }
  return chooseRight;
}

/* Simulated rat: returns true if the rat pokes the RIGHT well this trial.
   correctIsRight = the trial's correct side; i = trial index (for the ramp). */
bool ratGoesRight(bool correctIsRight, int i) {
  switch (SIM_POLICY) {
    case POLICY_ALWAYS_RIGHT:
      return true;
    case POLICY_ODOR: {
      float p = rewardProb(i);                  // accuracy ramps with learning
      bool correctPick = frand() < p;
      return correctPick ? correctIsRight : !correctIsRight;
    }
    case POLICY_RANDOM:
    default:
      return frand() < 0.5;
  }
}

/* Draw a plausible movement time (ms): correct choices are faster and
   tighter, errors slower and more variable; Go-Left a touch slower so the
   two directions separate. Clamped to the response window. */
int movementTime(bool goRight, bool correct) {
  int base   = correct ? 400 : 850;
  int jitter = correct ? 150 : 300;
  if (!goRight) base += 100;
  int m = base + (int)random(-jitter, jitter + 1);
  if (m < 80)   m = 80;
  if (m > 1950) m = 1950;
  return m;
}

/* Real-scale ms the rat managed to hold the correct well before releasing on a
   hold-fail -- always below REAL_FLUID_WELL_HOLD (500). Mostly near-misses
   hugging the threshold (so the A3 strip shows dots landing just under the
   line) with a tail of earlier releases. Passes through emit()'s /SIM_SPEEDUP
   like every other gap. */
int holdFailDuration() {
  if (frand() < 0.6) return random(420, REAL_FLUID_WELL_HOLD - 4);  // near-miss cluster
  return random(180, 420);                                          // earlier releases
}

/* A partial odor-port hold (ms) for an early-unpoke abort: below the
   REAL_ODOR_POKE_HOLD (500) the firmware requires. */
int partialOdorHold() {
  return random(150, REAL_ODOR_POKE_HOLD - 20);
}

/* Well outcomes for an administered Go trial. */
#define OUT_REWARD      0   // correct well, held to fluid        -> reward
#define OUT_WRONG_WELL  1   // wrong well                         -> error
#define OUT_HOLD_FAIL   2   // correct well, released before hold -> hold-fail

/* One administered Go trial: odor sampled to completion, then a well outcome.
   goRight -> odor 1 / right well is correct; else odor 3 / left well. Each gap
   models the real firmware phase that follows the strobe (see the REAL_*
   constants); emit() compresses them by SIM_SPEEDUP. */
void goTrial(bool goRight, int outcome) {
  emit(BF_LIGHTS_ON, APPROACH_TIME);              // lights on -> rat pokes odor port
  emit(BF_ODOR_POKE, REAL_ODOR_POKE_HOLD);        // pre-odor hold before odor delivery
  emit(goRight ? BF_ODOR_1_ON : BF_ODOR_3_ON,
       REAL_ODOR_POKE_HOLD);                       // vac closed, odor sample hold
  emit(BF_ODOR_OFF, WITHDRAW_TIME);               // odor off -> rat withdraws
  bool correct = (outcome != OUT_WRONG_WELL);     // reward & hold-fail are both correct-well
  emit(BF_ODOR_UNPOKE, movementTime(goRight, correct));  // movement to the well
  switch (outcome) {
    case OUT_REWARD:                               // correct well, held to fluid
      emit(goRight ? BF_WATER_POKE_R : BF_WATER_POKE_L,
           REAL_FLUID_WELL_HOLD);                   // hold cleared -> fluid
      emit(goRight ? BF_FLUID_R : BF_FLUID_L, REAL_FLUID_DURATION);
      emit(goRight ? BF_STOP_FLUID_G_R : BF_STOP_FLUID_G_L,
           REAL_STANDARD_ITI);                      // well unpoke + correct ITI
      emit(BF_END_CORRECT_ITI, 0);
      break;
    case OUT_HOLD_FAIL:                            // correct well, released early
      // Mirrors checkResponse(): WATER_POKE(correct side) then, when the hold
      // fails, WATER_UNPOKE_EARLY(correct side); the firmware then waits
      // noPokeHoldTimeout and odorSampling() emits END_INCORRECT_ITI.
      emit(goRight ? BF_WATER_POKE_R : BF_WATER_POKE_L,
           holdFailDuration());                     // released before fluidWellHold
      emit(goRight ? BF_WATER_UNPOKE_EARLY_R : BF_WATER_UNPOKE_EARLY_L,
           REAL_NO_POKE_HOLD_TO);                    // failure-to-hold timeout
      emit(BF_END_INCORRECT_ITI, 0);
      break;
    case OUT_WRONG_WELL:                           // poke the OTHER well, then its error
      emit(goRight ? BF_WATER_POKE_L : BF_WATER_POKE_R, WRONG_WELL_REACT);
      emit(goRight ? BF_WATER_POKE_ERROR_L : BF_WATER_POKE_ERROR_R,
           REAL_ERROR_DELAY);                        // wrong-well timeout
      emit(BF_END_INCORRECT_ITI, 0);
      break;
  }
}

/* Lazy rat: light on, rat never engages the odor port, board times out after
   the full odorPortTimeout, then waits the lazyRatDelay before loop() aborts. */
void lazyTrial() {
  emit(BF_LIGHTS_ON, REAL_ODOR_PORT_TIMEOUT);  // whole poke window elapses, no poke
  emit(BF_LAZY_RAT, REAL_LAZY_RAT_DELAY);      // base lazy timeout
  emit(BF_INVALID_TRIAL, 0);
}

/* Early odor unpoke before the vacuum closed -- odor was never delivered,
   so NO odor-on code is sent. The firmware waits noPokeHoldTimeout on a
   failed hold before loop() aborts the trial. */
void earlyOdorPreVac() {
  emit(BF_LIGHTS_ON, APPROACH_TIME);
  emit(BF_ODOR_POKE, partialOdorHold());        // bails before the pre-odor hold completes
  emit(BF_ODOR_UNPOKE_EARLY, REAL_NO_POKE_HOLD_TO);
  emit(BF_INVALID_TRIAL, 0);
}

/* Early odor unpoke during sampling -- odor-on IS sent (the rat cleared the
   pre-odor hold), but it left before ODOR_OFF, so there's no ODOR_OFF /
   ODOR_UNPOKE (not administered). */
void earlyOdorSampling(bool goRight) {
  emit(BF_LIGHTS_ON, APPROACH_TIME);
  emit(BF_ODOR_POKE, REAL_ODOR_POKE_HOLD);      // cleared pre-odor hold -> odor on
  emit(goRight ? BF_ODOR_1_ON : BF_ODOR_3_ON,
       partialOdorHold());                       // bails during the sample hold
  emit(BF_ODOR_UNPOKE_EARLY, REAL_NO_POKE_HOLD_TO);
  emit(BF_INVALID_TRIAL, 0);
}

/* Accuracy "learning curve" for POLICY_ODOR: a cubic smoothstep S-curve from
   SIM_START_ACC up to SIM_END_ACC across the WHOLE session. Smoothstep stays
   low early (the rat struggles for the first chunk of trials), accelerates
   through chance mid-session, and plateaus near SIM_END_ACC by the end -- a
   realistic within-session learning trajectory. */
float rewardProb(int i) {
  if (NUM_TRIALS <= 1) return SIM_END_ACC;
  float frac = (float)i / (NUM_TRIALS - 1);     // 0 .. 1 across the session
  if (frac < 0) frac = 0;
  if (frac > 1) frac = 1;
  float s = frac * frac * (3.0 - 2.0 * frac);   // smoothstep (slow-fast-slow S)
  return SIM_START_ACC + (SIM_END_ACC - SIM_START_ACC) * s;
}

/* Abstention probability for trial i -- the engagement curve. A U-shape:
   high early (the rat is warming up: ABORT_WARMUP easing linearly down to
   ABORT_STEADY over the first WARMUP_FRAC of the session), low and steady
   through mid-session, then rising to ABORT_FATIGUE over the last
   (1 - FATIGUE_FRAC) as the rat satiates. Always < 1, so administered trials
   persist at both ends. */
float abortProbAt(int i) {
  int warmEnd = (int)(WARMUP_FRAC * NUM_TRIALS);
  int fatigueStart = (int)(FATIGUE_FRAC * NUM_TRIALS);
  if (warmEnd > 0 && i < warmEnd) {
    float w = (float)i / warmEnd;               // 0 -> 1 across the warm-up
    return ABORT_WARMUP + (ABORT_STEADY - ABORT_WARMUP) * w;
  }
  if (i >= fatigueStart) return ABORT_FATIGUE;
  return ABORT_STEADY;
}

/* Mirror the real handshake: announce READY, block until a "START" line, and
   parse its key=value config the way the real firmware does — including this
   run's SEED, which is what the sim has to honour if it is to exercise the
   host's seeding path rather than a private one. */
void waitForStart(SessionConfig &cfg) {
  char buf[96];   // same cap as the real sketches: a truncated line loses SEED
  size_t len = 0;
  Serial.println("READY");
  while (true) {
    while (Serial.available() == 0) delay(2);
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      if (len > 0 && strncmp(buf, "START", 5) == 0) {
        parseStartCommand(buf, cfg);
        return;
      }
      len = 0;
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = c;
      buf[len] = '\0';
    }
  }
}

/* Mid-session STOP uses BehaviorBox.h's own checkForStop() — the exact
   non-blocking poll the real firmware calls once per trial boundary. The sim
   spends its whole session inside delay()s, so a STOP sent by the host just
   accumulates in the RX buffer until the next boundary drains it. */

void setup() {
  SessionConfig sessionCfg;
  Serial.begin(baudRate);
  delay(50);                 // let the post-reset serial settle
  waitForStart(sessionCfg);

  // Seed and report it, exactly as the firmware does on START — host-supplied
  // SEED, clock fallback, same echo (BehaviorBox.h). Sharing the real helper is
  // the point: a sim that seeded itself would pass while the rig's seeding path
  // was broken.
  beginSessionRng(sessionCfg);

  sessionStart = millis();
  emit(BF_START_SESSION, REAL_PRIMING_DELAY);  // odor priming before the first lights-on

  for (int i = 0; i < NUM_TRIALS; i++) {
    // 0. Trial boundary: honour a STOP that arrived during the last trial —
    //    the same once-per-boundary check the real firmware makes, so the
    //    host's Stop button (and the session time limit) end the sim early.
    if (checkForStop()) break;

    // 1. The anti-bias selector picks this trial's correct side.
    bool goRight = selectNextGoRight();

    // 2. Engagement: abstain more early (warm-up) and late (satiation), steady
    //    in between (abortProbAt). Always < 1, so administered trials persist
    //    at both ends to show the rat's learned ~80% accuracy.
    if (frand() < abortProbAt(i)) {
      float a = frand();
      if (a < 0.70)      lazyTrial();          // no expressed choice -> bias unchanged
      else if (a < 0.85) earlyOdorPreVac();
      else               earlyOdorSampling(goRight);
      interTrialGap();
      continue;
    }

    // 3. Administered trial: the simulated rat picks a well per its policy.
    bool ratRight = ratGoesRight(goRight, i);
    bool correct  = (ratRight == goRight);
    int  outcome;
    if (!correct) {
      outcome = OUT_WRONG_WELL;                // wrong well -> discrimination error
    } else {
      // Correct side reached -- but the rat sometimes releases before the
      // fluidWellHold (a hold-fail), more often on the right well (sim artifact).
      float pHoldFail = goRight ? HOLD_FAIL_PROB_R : HOLD_FAIL_PROB_L;
      outcome = (frand() < pHoldFail) ? OUT_HOLD_FAIL : OUT_REWARD;
    }
    goTrial(goRight, outcome);
    recordChoice(ratRight);                    // expressed side (correct on a hold-fail) feeds the anti-bias estimate

    interTrialGap();
  }

  emit(BF_END_SESSION, 0);
}

void loop() {
  // One-shot script runs in setup(); nothing to do once the session ends.
}

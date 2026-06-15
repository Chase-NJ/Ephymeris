/*
GRGL_Sim.ino — serial simulator for the GRGL 2-odor task.
Author: Chase Johnston

Emits the strobe stream the real GRGL_2-Odor sketch would, over the same
serial protocol (announce "READY", wait for a "START" line, emit a
"SEED<TAB>value" line, then send tab-separated "CODE<TAB>MS" lines), so
dashboard.py / read_arduino.py can be exercised end-to-end without an Arduino
wired to the rig. No pins are driven — this only talks serial, so it runs on
any board.

This build mirrors the firmware's three confound-closing changes so they can
be validated off-rig:
  - SEED line: emitted right after START (seed = micros()), so the host's
    seed-capture / JSON+MAT logging path is exercised.
  - Adaptive anti-bias selection: the SAME selectNextTrial() logic as the
    firmware chooses each trial's correct side against the rat's recent
    expressed bias. A configurable SIM_POLICY models the rat — the default
    POLICY_ALWAYS_RIGHT lets you watch the debias push the correct side toward
    LEFT while the right-biased rat's reward rate falls.
  - Dummy clicks: a randomized subset of dummy-click strobes (110..113) is
    emitted before each trial's LIGHTS_ON, so the host's dummy-code
    registration is exercised.

It also stays NON-STATIONARY for the dashboard's live trends: reward depends
on the simulated rat's policy (POLICY_ODOR ramps accuracy as learning), and
lazy/abort trials cluster late (satiation/fatigue) so the engagement dot flips
green -> red. MOVEMENT TIMES are drawn per trial (correct faster/tighter,
errors slower/wider, go-left a touch slower) so the RT histogram's four
GR/GL x correct/error distributions stay distinct.

Outcomes covered, with the strobe sequence each emits (mirrors the real
sketch's control flow in odorSampling()/checkResponse()):

  Administered Go trial = [dummy clicks], LIGHTS_ON, ODOR_POKE, ODOR_x_ON,
                          ODOR_OFF, ODOR_UNPOKE, then one well outcome:
    reward        -> WATER_POKE(side), FLUID(side), STOP_FLUID(side),
                     END_CORRECT_ITI
    wrong well    -> WATER_POKE(other), WATER_POKE_ERROR(other),
                     END_INCORRECT_ITI

  Aborted trial ([dummy clicks] then no ODOR_UNPOKE; firmware strobes
  INVALID_TRIAL too):
    lazy rat            -> LIGHTS_ON, LAZY_RAT, INVALID_TRIAL
    early odor (pre-vac)-> LIGHTS_ON, ODOR_POKE, ODOR_UNPOKE_EARLY,
                           INVALID_TRIAL                 (no odor-on code)
    early odor (sample) -> LIGHTS_ON, ODOR_POKE, ODOR_x_ON,
                           ODOR_UNPOKE_EARLY, INVALID_TRIAL
*/

const int  baudRate   = 9600;   // must match read_arduino.py
const int  STROBE_GAP = 100;    // ms between strobes within a trial
const int  TRIAL_GAP  = 300;    // ms between trials

/* Session shape. */
const int   NUM_TRIALS   = 60;    // total trials in the run
const float RAMP_FRAC    = 0.60;  // POLICY_ODOR accuracy ramps over the first 60%
const float FATIGUE_FRAC = 0.78;  // aborts cluster from the last ~22% on

/* Simulated-rat policy -- how the rat picks a well given the correct side. */
#define POLICY_ALWAYS_RIGHT 0   // ignores odor, always goes right (shows anti-bias at work)
#define POLICY_RANDOM       1   // ignores odor, 50/50
#define POLICY_ODOR         2   // uses odor: picks correct side with ramping accuracy
const int SIM_POLICY = POLICY_ALWAYS_RIGHT;

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

/* ===== Dummy-click masking ===== */
#define NUM_DUMMY 4
#define BF_DUMMY_CLICK_BASE 110

/* Strobe codes (subset of GRGL_2-Odor.ino) */
#define BF_START_SESSION        221
#define BF_LIGHTS_ON            222
#define BF_LAZY_RAT             223
#define BF_ODOR_POKE            224
#define BF_ODOR_UNPOKE_EARLY    225
#define BF_ODOR_UNPOKE          226
#define BF_INVALID_TRIAL        234
#define BF_END_CORRECT_ITI      242
#define BF_END_INCORRECT_ITI    243
#define BF_END_SESSION          246
#define BF_ODOR_OFF             247
#define BF_WATER_POKE_L         248
#define BF_WATER_POKE_R         249
#define BF_WATER_UNPOKE_EARLY_L 250
#define BF_WATER_UNPOKE_EARLY_R 251
#define BF_FLUID_L              252
#define BF_FLUID_R              253
#define BF_WATER_POKE_ERROR_L   257
#define BF_WATER_POKE_ERROR_R   258
#define BF_STOP_FLUID_G_R       357
#define BF_STOP_FLUID_G_L       369
#define BF_ODOR_1_ON            101
#define BF_ODOR_3_ON            103

unsigned long sessionStart = 0;

/* Print one event in the rig's standard "CODE<TAB>MS" format, then wait
   `gap` ms before the next strobe. The gap after ODOR_UNPOKE doubles as the
   movement time, since the next strobe is the well poke. */
void emit(int code, int gap = STROBE_GAP) {
  unsigned long ts = millis() - sessionStart;
  char buf[16];
  sprintf(buf, "%03d\t%lu", code, ts);
  Serial.println(buf);
  delay(gap);
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

/* Emit a randomized subset of dummy-click strobes (>= 1), mirroring the
   firmware's fireDummyClicks() acoustic masking. Sound only -- no odor. */
void emitDummyClicks() {
  bool firedAny = false;
  for (int i = 0; i < NUM_DUMMY; i++) {
    bool fire = (random(0, 2) == 0);
    if (i == NUM_DUMMY - 1 && !firedAny) fire = true;   // guarantee >= 1
    if (fire) {
      emit(BF_DUMMY_CLICK_BASE + i, 20);
      firedAny = true;
    }
  }
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

/* Well outcomes for an administered Go trial. */
#define OUT_REWARD      0   // correct well, held       -> reward
#define OUT_WRONG_WELL  1   // wrong well               -> error

/* One administered Go trial: odor sampled to completion, then a well outcome.
   goRight -> odor 1 / right well is correct; else odor 3 / left well. */
void goTrial(bool goRight, int outcome) {
  emit(BF_LIGHTS_ON);
  emit(BF_ODOR_POKE);
  emit(goRight ? BF_ODOR_1_ON : BF_ODOR_3_ON);
  emit(BF_ODOR_OFF);
  bool correct = (outcome != OUT_WRONG_WELL);
  emit(BF_ODOR_UNPOKE, movementTime(goRight, correct));
  switch (outcome) {
    case OUT_REWARD:
      emit(goRight ? BF_WATER_POKE_R : BF_WATER_POKE_L);
      emit(goRight ? BF_FLUID_R : BF_FLUID_L);
      emit(goRight ? BF_STOP_FLUID_G_R : BF_STOP_FLUID_G_L);
      emit(BF_END_CORRECT_ITI);
      break;
    case OUT_WRONG_WELL:                 // poke the OTHER well, then its error
      emit(goRight ? BF_WATER_POKE_L : BF_WATER_POKE_R);
      emit(goRight ? BF_WATER_POKE_ERROR_L : BF_WATER_POKE_ERROR_R);
      emit(BF_END_INCORRECT_ITI);
      break;
  }
}

/* Lazy rat: light on, rat never engages the odor port, board times out. */
void lazyTrial() {
  emit(BF_LIGHTS_ON);
  emit(BF_LAZY_RAT);
  emit(BF_INVALID_TRIAL);
}

/* Early odor unpoke before the vacuum closed -- odor was never delivered,
   so NO odor-on code is sent. */
void earlyOdorPreVac() {
  emit(BF_LIGHTS_ON);
  emit(BF_ODOR_POKE);
  emit(BF_ODOR_UNPOKE_EARLY);
  emit(BF_INVALID_TRIAL);
}

/* Early odor unpoke during sampling -- odor-on IS sent, but the rat left
   before ODOR_OFF, so there's no ODOR_OFF / ODOR_UNPOKE (not administered). */
void earlyOdorSampling(bool goRight) {
  emit(BF_LIGHTS_ON);
  emit(BF_ODOR_POKE);
  emit(goRight ? BF_ODOR_1_ON : BF_ODOR_3_ON);
  emit(BF_ODOR_UNPOKE_EARLY);
  emit(BF_INVALID_TRIAL);
}

/* Accuracy ramp for POLICY_ODOR: from 25% up to 90% over the first RAMP_FRAC
   of the session, then a plateau. */
float rewardProb(int i) {
  int rampEnd = (int)(RAMP_FRAC * NUM_TRIALS);
  if (rampEnd < 1 || i >= rampEnd) return 0.90;
  return 0.25 + 0.65 * ((float)i / rampEnd);
}

/* Mirror the real handshake: announce READY, block until a "START" line
   (also accepts "START <n>" correction-trial form; the count is ignored). */
void waitForStart() {
  char buf[16];
  size_t len = 0;
  Serial.println("READY");
  while (true) {
    while (Serial.available() == 0) delay(2);
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      if (len > 0 && strncmp(buf, "START", 5) == 0) return;
      len = 0;
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = c;
      buf[len] = '\0';
    }
  }
}

void setup() {
  Serial.begin(baudRate);
  delay(50);                 // let the post-reset serial settle
  waitForStart();

  // Seed and report it, exactly as the firmware does on START.
  unsigned long sessionSeed = micros();
  randomSeed(sessionSeed);
  Serial.print("SEED\t");
  Serial.println(sessionSeed);

  sessionStart = millis();
  emit(BF_START_SESSION);

  int fatigueStart = (int)(FATIGUE_FRAC * NUM_TRIALS);
  for (int i = 0; i < NUM_TRIALS; i++) {
    // 1. The anti-bias selector picks this trial's correct side.
    bool goRight = selectNextGoRight();

    // 2. Dummy clicks precede LIGHTS_ON on every trial (administered or abort).
    emitDummyClicks();

    // 3. Disengagement ramps up late (satiation/fatigue).
    float abortProb = (i >= fatigueStart) ? 0.65 : 0.06;
    if (frand() < abortProb) {
      float a = frand();
      if (a < 0.70)      lazyTrial();          // no expressed choice -> bias unchanged
      else if (a < 0.85) earlyOdorPreVac();
      else               earlyOdorSampling(goRight);
      delay(TRIAL_GAP);
      continue;
    }

    // 4. Administered trial: the simulated rat picks a well per its policy.
    bool ratRight = ratGoesRight(goRight, i);
    bool correct  = (ratRight == goRight);
    goTrial(goRight, correct ? OUT_REWARD : OUT_WRONG_WELL);
    recordChoice(ratRight);                    // feed the rat's expressed side into the anti-bias estimate

    delay(TRIAL_GAP);
  }

  emit(BF_END_SESSION);
}

void loop() {
  // One-shot script runs in setup(); nothing to do once the session ends.
}

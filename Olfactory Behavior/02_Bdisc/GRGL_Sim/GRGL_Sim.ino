/*
GRGL_Sim.ino — serial simulator for the GRGL 2-odor task.
Author: Chase Johnston

Emits the exact strobe stream the real GRGL_2-Odor sketch would, over the
same serial protocol (announce "READY", wait for a "START" line, then send
tab-separated "CODE<TAB>MS" lines), so dashboard.py / read_arduino.py can be
exercised end-to-end without an Arduino wired to the rig. No pins are driven
— this only talks serial, so it runs on any board.

This "rich" build is also NON-STATIONARY, so the dashboard's live tile trends
actually move: each trial's outcome is generated on the fly, with
  - a LEARNING ramp -- reward probability climbs from ~25% to ~90% over the
    first stretch, so the rolling per-odor accuracy lines bend upward (Odor 3
    / go-left lags, so the GR/GL gap shows side bias); and
  - SATIATION/FATIGUE -- lazy/abort trials cluster in the last ~20%, so the
    engagement dot flips from green to red live.
MOVEMENT TIMES are still drawn per trial (correct choices faster/tighter,
errors slower/wider, a mild go-left slowness) so the pop-out RT histogram's
four GR/GL x correct/error distributions stay distinct. Tune NUM_TRIALS,
RAMP_FRAC, and FATIGUE_FRAC below to reshape the run.

Outcomes covered, with the strobe sequence each emits (mirrors the real
sketch's control flow in odorSampling()/checkResponse()):

  Administered Go trial = LIGHTS_ON, ODOR_POKE, ODOR_x_ON, ODOR_OFF,
                          ODOR_UNPOKE, then one well outcome:
    reward        -> WATER_POKE(side), FLUID(side), STOP_FLUID(side),
                     END_CORRECT_ITI
    wrong well    -> WATER_POKE(other), WATER_POKE_ERROR(other),
                     END_INCORRECT_ITI
    early well    -> WATER_POKE(side), WATER_UNPOKE_EARLY(side),
                     END_INCORRECT_ITI
    no response   -> (no well poke) END_INCORRECT_ITI

  Aborted trial (no ODOR_UNPOKE; firmware strobes INVALID_TRIAL too):
    lazy rat            -> LIGHTS_ON, LAZY_RAT, INVALID_TRIAL
    early odor (pre-vac)-> LIGHTS_ON, ODOR_POKE, ODOR_UNPOKE_EARLY,
                           INVALID_TRIAL                 (no odor-on code)
    early odor (sample) -> LIGHTS_ON, ODOR_POKE, ODOR_x_ON,
                           ODOR_UNPOKE_EARLY, INVALID_TRIAL
*/

const int  baudRate   = 9600;   // must match read_arduino.py
const int  STROBE_GAP = 100;    // ms between strobes within a trial
const int  TRIAL_GAP  = 300;    // ms between trials

/* Session shape (non-stationary trial generation). */
const int   NUM_TRIALS   = 60;    // total trials in the run
const float RAMP_FRAC    = 0.60;  // reward prob ramps over the first 60%
const float FATIGUE_FRAC = 0.78;  // aborts cluster from the last ~22% on

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

/* Well outcomes for an administered Go trial (rat sampled the odor fully). */
#define OUT_REWARD      0   // correct well, held       -> reward
#define OUT_WRONG_WELL  1   // wrong well               -> error
#define OUT_EARLY_WELL  2   // correct well, released early
#define OUT_NO_RESPONSE 3   // never poked a fluid well

/* One administered Go trial: odor sampled to completion, then a well outcome.
   goRight -> odor 1 / right well is correct; else odor 3 / left well. */
void goTrial(bool goRight, int outcome) {
  emit(BF_LIGHTS_ON);
  emit(BF_ODOR_POKE);
  emit(goRight ? BF_ODOR_1_ON : BF_ODOR_3_ON);
  emit(BF_ODOR_OFF);
  // The delay after ODOR_UNPOKE is the movement time to the first well poke.
  // No-response trials have no poke, so use a normal strobe gap there.
  bool hasPoke = (outcome != OUT_NO_RESPONSE);
  bool correct = (outcome != OUT_WRONG_WELL);   // early-well is still a correct choice
  emit(BF_ODOR_UNPOKE, hasPoke ? movementTime(goRight, correct) : STROBE_GAP);
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
    case OUT_EARLY_WELL:                 // correct well, released before hold
      emit(goRight ? BF_WATER_POKE_R : BF_WATER_POKE_L);
      emit(goRight ? BF_WATER_UNPOKE_EARLY_R : BF_WATER_UNPOKE_EARLY_L);
      emit(BF_END_INCORRECT_ITI);
      break;
    case OUT_NO_RESPONSE:                // no well poke at all
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

/* Uniform random float in [0, 1). */
float frand() {
  return random(0, 10000) / 10000.0;
}

/* Reward probability for trial i: a learning ramp from 25% up to 90% over
   the first RAMP_FRAC of the session, then a plateau. (Go-Left's bias is
   applied at the call site.) */
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

  randomSeed(micros());      // vary the draws per run
  sessionStart = millis();
  emit(BF_START_SESSION);

  // Generate each trial on the fly so the session is non-stationary: reward
  // probability ramps up early (learning), and aborts cluster late
  // (satiation/fatigue). Direction is ~50/50; Go-Left (Odor 3) lags so the
  // per-odor lines separate into a visible bias.
  int fatigueStart = (int)(FATIGUE_FRAC * NUM_TRIALS);
  for (int i = 0; i < NUM_TRIALS; i++) {
    bool goRight = frand() < 0.5;
    float abortProb = (i >= fatigueStart) ? 0.65 : 0.06;

    if (frand() < abortProb) {
      // Disengagement: mostly lazy, with the odd early-odor abort.
      float a = frand();
      if (a < 0.70)      lazyTrial();
      else if (a < 0.85) earlyOdorPreVac();
      else               earlyOdorSampling(goRight);
    } else {
      float p = rewardProb(i);
      if (!goRight) p -= 0.18;            // Odor 3 (go-left) lags -> bias
      if (frand() < p) {
        goTrial(goRight, OUT_REWARD);
      } else {
        float e = frand();               // an unrewarded administered trial
        if (e < 0.70)      goTrial(goRight, OUT_WRONG_WELL);
        else if (e < 0.90) goTrial(goRight, OUT_EARLY_WELL);
        else               goTrial(goRight, OUT_NO_RESPONSE);
      }
    }
    delay(TRIAL_GAP);
  }

  emit(BF_END_SESSION);
}

void loop() {
  // One-shot script runs in setup(); nothing to do once the session ends.
}

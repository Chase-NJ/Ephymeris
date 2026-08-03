/*
  BehaviorBox.h
  =============
  Author: Chase Johnston (2026)

  THE single shared header for every sketch in this repo -- behavior tasks
  (GRGL / shaping), the simulator, and the utility/cleaning sketches all include
  it. It is the one source of truth for:

    * the Hart-lab behavior-box PINOUT (IR sensors, trial light, N.O. vacuum,
      12 odor solenoids, 4 fluid solenoids) -- identical on all 6 boxes, so it
      lives here instead of being copy-pasted into each sketch;
    * the STROBE VOCABULARY (the BF_* host codes) -- one definition mirrored by
      every task.json `strobes` map;
    * the SERIAL PROTOCOL helpers shared with the Ephymeris app: the strobe
      emitter, the blocking START reader, the non-blocking STOP poll, and (for
      utility sketches) a non-blocking command reader + a STATUS emitter;
    * TaskParams -- EVERY operator-tunable parameter, and the one declarative
      list (TASK_PARAM_LIST) from which the START-line parser is generated. The
      app fills this from the sketch's task.json, so a parameter is tuned per
      sketch and per run instead of being recompiled;
    * the reusable TRIAL primitives (TrialClock, TrialType, TrialWeight +
      generateTrials) and the session POLICY classes (anti-bias selection,
      the lazy-penalty escalator, per-side correction budgets);
    * the TRIAL RUNNER -- one loop for every behavior sketch. Shaping and GRGL
      run the same trial and differ only in which policies they hand it, so all
      five behavior sketches are a trial pool plus setup/loop wiring.

  Reached by every sketch as an Arduino library: the Ephymeris sidecar passes the
  repo-root `libraries/` folder to `arduino-cli compile --libraries <...>`
  (arduino-directory.md §4), and the Arduino IDE finds it too when the sketchbook
  is the repo root. A sketch includes it with angle brackets:

      #include <BehaviorBox.h>

  Microcontroller-appropriate: plain structs/classes, no dynamic allocation, no
  virtual dispatch in any trial loop. Tuning constants that DIFFER between
  sketches stay in the sketches (constructor args / config structs); the shared
  behavior and the call-site wiring that genuinely differs stay where they
  belong.

  Host compile-check: extras/host_test/ compiles this header off-target against a
  minimal Arduino.h shim and exercises the policy classes. It does NOT replace
  flashing to the rig -- only arduino-cli does the full AVR compile.
*/

#ifndef BEHAVIOR_BOX_H
#define BEHAVIOR_BOX_H

#include <Arduino.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ============================================================= *
 *  1. PINOUT -- identical on every box (was duplicated per sketch)
 * ============================================================= */
/* IR sensors */
const int odorPort  = 2;  // Odor port
const int rightWell = 3;  // Right-well
const int leftWell  = 4;  // Left-well

/* Trial light & normally-open vacuum */
const int trialLight = 36; // Trial light
const int vac        = 40; // N.O.V.

const int NUM_ODORS  = 12;
const int NUM_FLUIDS = 4;

/* Odor solenoids */
const int Odors[NUM_ODORS] = {
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

/* Fluid solenoids: { left , left , right , right } */
const int Fluids[NUM_FLUIDS] = {
    42, // [0]: Left-well  reward 1
    44, // [1]: Left-well  reward 2
    46, // [2]: Right-well reward 1
    48  // [3]: Right-well reward 2
};

/* ============================================================= *
 *  2. STROBE VOCABULARY -- BF_* host codes (mirror of task.json `strobes`)
 * ============================================================= */
#define BF_START_SESSION        221 // Sent at recording start (timestamp 0)
#define BF_LIGHTS_ON            222 // Sent when trialLight is written HIGH
#define BF_LAZY_RAT             223 // Sent when rat fails to initiate trial
#define BF_ODOR_POKE            224 // Sent when rat pokes odor port
#define BF_ODOR_UNPOKE_EARLY    225 // Sent when rat fails to hold odor poke for odorPokeHold
#define BF_ODOR_UNPOKE          226 // Sent after rat successfully samples odor
#define BF_LIGHTS_OFF           233 // Sent when trialLight is written LOW inside a trial
#define BF_INVALID_TRIAL        234 // Trial aborted (lazy rat or poke-hold failure)
#define BF_END_CORRECT_ITI      242 // Sent after correct-response intertrial interval
#define BF_END_INCORRECT_ITI    243 // Sent after errorDelay intertrial interval
#define BF_END_SESSION          246 // Sent at end of session (sessionComplete = true)
#define BF_ODOR_OFF             247 // Sent when we close N.O.V. (directing odor AWAY from port)
#define BF_WATER_POKE_L         248 // Sent when rat pokes left fluid well
#define BF_WATER_POKE_R         249 // Sent when rat pokes right fluid well
#define BF_WATER_UNPOKE_EARLY_L 250 // Sent when rat fails to hold left well for fluidWellHold
#define BF_WATER_UNPOKE_EARLY_R 251 // Sent when rat fails to hold right well for fluidWellHold
#define BF_FLUID_L              252 // Delivered at start of first drop on left
#define BF_FLUID_R              253 // Delivered at start of first drop on right
#define BF_WATER_UNPOKE_L       254 // Sent when rat unpokes left well
#define BF_WATER_UNPOKE_R       255 // Sent when rat unpokes right well
#define BF_WATER_POKE_NONE      256 // After a correct response on a No-Go trial
#define BF_WATER_POKE_ERROR_L   257 // Sent when rat incorrectly responds at left well
#define BF_WATER_POKE_ERROR_R   258 // Sent when rat incorrectly responds at right well
#define BF_RESP_OMIT            262 // Response window expired after complete sampling
#define BF_STOP_FLUID_G_R       357 // Sent when we stop right-well fluid delivery
#define BF_STOP_FLUID_G_L       369 // Sent when we stop left-well fluid delivery

/* Distinct Odor-ON codes (one per odor line the task presents) */
#define BF_ODOR_1_ON 101
#define BF_ODOR_2_ON 102
#define BF_ODOR_3_ON 103
#define BF_ODOR_4_ON 104
#define BF_ODOR_5_ON 105
#define BF_ODOR_6_ON 106

/* Indices into Fluids[] / FluidPinTimes[] (+ the no-go sentinel) */
#define LEFT_WELL_FL_1  0
#define LEFT_WELL_FL_2  1
#define RIGHT_WELL_FL_1 2
#define RIGHT_WELL_FL_2 3
#define SENTINEL       -1

/* ============================================================= *
 *  3. TRIAL PRIMITIVES
 * ============================================================= */
/* Encapsulates trial timestamps relative to recording start (millis-based). */
struct TrialClock
{
  unsigned long recStart  = 0;
  unsigned long currentTS = 0;

  void beginSession()
  {
    currentTS = millis();
    recStart  = currentTS;
  }

  unsigned long elapsed()
  {
    currentTS = millis();
    return currentTS - recStart;
  }
};

/* Uniform random float in [0, 1), built on Arduino's random(). */
inline float grglFrand()
{
  return random(0, 10000) / 10000.0;
}

/* Defines the differences between trial types. The concrete goRight/goLeft
   instances stay in each sketch (they reference that sketch's odor/strobe
   choices); this struct + the selectors/pools below are pin-agnostic. */
struct TrialType
{
  const bool isGo;
  const int odorPin;        // Odor solenoid pin
  const int correctWell;    // pin of correct well, or -1 for no-go
  const int rewardIndex;    // Index into Fluids[] AND FluidPinTimes[], or -1 for no-go
  const int odorOnCode;     // host code for Odor on (distinct between odors)
  const int fluidEventCode; // host code for fluid delivery
  const int stopFluidCode;  // host code for fluid stop

  TrialType(bool isGo, int odorPin, int correctWell, int rewardIndex,
            int odorOnCode, int fluidEventCode, int stopFluidCode)
      : isGo(isGo), odorPin(odorPin), correctWell(correctWell),
        rewardIndex(rewardIndex), odorOnCode(odorOnCode),
        fluidEventCode(fluidEventCode), stopFluidCode(stopFluidCode) {}
};

/* Lets a task manipulate the proportion of each trial type it administers.
   Used by the block-shuffled generateTrials() below (shaping sketches). */
struct TrialWeight
{
  const TrialType *type;
  int weight;

  TrialWeight(const TrialType &type, int weight) : type(&type), weight(weight) {}
};

/*  void generateTrials(...) ->
    Populate `trials` with pointers drawn from `pool` in the proportions its
    weights imply. Generated in blocks of `blockSize`: within each block, exact
    proportional counts are placed first, any remainder slots are filled by
    weighted random draw, then the block is Fisher-Yates shuffled. (Moved here
    verbatim from the shaping sketches so both share one copy.)

    DRAWS FROM THE ALREADY-SEEDED STREAM. This used to take a `seed` and call
    randomSeed() itself, which is why the shaping sketches ran an identical
    trial sequence every session forever: the sketches passed a compile-time
    constant, and the sequence was built in setup() before START had even
    arrived. Seeding is beginSessionRng()'s job and happens exactly once per
    run; call it first, then call this. Two seeding sites is how a fixed seed
    creeps back in unnoticed. */
inline void generateTrials(const TrialType *trials[], int numTrials, int blockSize,
                           TrialWeight pool[], int poolSize)
{
  int totalWeight = 0;
  for (int i = 0; i < poolSize; i++)
    totalWeight += pool[i].weight;

  /* Pool weights are operator-typed now (PW1..PW4 on the START line), and an
     all-zero pool would divide by zero below -- on AVR that is a silent wrong
     answer, not a trap. Fall back to equal weights: a uniform pool is a defined
     session, where a hung box mid-shaping is not. */
  if (totalWeight <= 0)
  {
    for (int i = 0; i < poolSize; i++)
      pool[i].weight = 1;
    totalWeight = poolSize;
  }

  for (int blockStart = 0; blockStart < numTrials; blockStart += blockSize)
  {
    int curBlockSize = min(blockSize, numTrials - blockStart);
    int filled = 0;

    // 1. Fill block with exact proportional counts
    for (int i = 0; i < poolSize; i++)
    {
      int count = (long)curBlockSize * pool[i].weight / totalWeight;
      for (int j = 0; j < count; j++)
        trials[blockStart + filled++] = pool[i].type;
    }

    // 2. Distribute any remainder slots via weighted random
    while (filled < curBlockSize)
    {
      int roll = random(0, totalWeight);
      int cumulative = 0;
      for (int j = 0; j < poolSize; j++)
      {
        cumulative += pool[j].weight;
        if (roll < cumulative)
        {
          trials[blockStart + filled++] = pool[j].type;
          break;
        }
      }
    }

    // 3. Fisher-Yates shuffle the block
    for (int i = curBlockSize - 1; i > 0; i--)
    {
      int j = random(0, i + 1);
      const TrialType *temp = trials[blockStart + i];
      trials[blockStart + i] = trials[blockStart + j];
      trials[blockStart + j] = temp;
    }
  }
}

/* ============================================================= *
 *  4. SERIAL PROTOCOL helpers (shared with the Ephymeris app)
 * ============================================================= */
/*  void emitStrobe(TrialClock&, int) ->
    Emit one strobe in the canonical "%03d\t<ms>" form the app's IN_SESSION
    parser accepts (^\d{1,3}\t\d+$). Each sketch keeps a 1-line `recordEvent`
    wrapper bound to its own clock, so existing call sites stay unchanged. */
inline void emitStrobe(TrialClock &clock, int eventCode)
{
  unsigned long timestamp = clock.elapsed();
  char buf[16];
  snprintf(buf, sizeof(buf), "%03d\t%lu", eventCode, timestamp);
  Serial.println(buf);
}

/*  bool readLineInto(char* dst, size_t cap) ->
    BLOCKING single-line read (safe only in setup()): terminate on CR or LF,
    tolerate a trailing CR+LF, null-terminate, strip the ending. Returns true on
    a complete non-empty line, false on a lone terminator (caller retries).
    Overlong lines are truncated and the tail drained. Used to await START. */
inline bool readLineInto(char *dst, size_t cap)
{
  size_t len = 0;
  while (true)
  {
    while (Serial.available() == 0)
      delay(2); // idle politely until a byte arrives
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n')
    {
      if (len == 0)
        return false;
      dst[len] = '\0';
      return true;
    }
    if (len < cap - 1)
      dst[len++] = c;
    // else: overflow byte -- drop it
  }
}

/*  bool checkForStop() ->
    NON-BLOCKING poll for a "STOP" line, called once per trial boundary in
    loop(). Consumes only bytes already buffered; a partial line is held across
    calls. Returns true once a full "STOP" line arrives; any other complete line
    is discarded (we only recognize STOP while a session runs). */
inline bool checkForStop()
{
  static char buf[8];
  static size_t len = 0;

  while (Serial.available() > 0)
  {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n')
    {
      bool isStop = (len > 0 && strcmp(buf, "STOP") == 0);
      len = 0;
      if (isStop)
        return true;
    }
    else if (len < sizeof(buf) - 1)
    {
      buf[len++] = c;
      buf[len] = '\0';
    }
    // else: overflow byte -- drop it, line can't be "STOP" anyway
  }
  return false;
}

/*  CommandReader ->
    NON-BLOCKING line reader for the utility/cleaning sketches, which run in the
    app's PASSTHROUGH mode and are driven by whole-line text commands (e.g.
    "SET GEAR=1", "TOGGLE L"). Drains Serial across loop() passes; poll() returns
    true exactly once per completed line, whose text is then in line(). Unlike
    checkForStop() it recognizes any line, not just STOP. */
class CommandReader
{
public:
  bool poll()
  {
    while (Serial.available() > 0)
    {
      char c = (char)Serial.read();
      if (c == '\r' || c == '\n')
      {
        if (_len > 0)
        {
          _buf[_len] = '\0';
          _len = 0;
          return true;
        }
      }
      else if (_len < CAP - 1)
      {
        _buf[_len++] = c;
      }
      // else: overflow byte -- drop it
    }
    return false;
  }

  const char *line() const { return _buf; }

private:
  static const size_t CAP = 48;
  char _buf[CAP] = {0};
  size_t _len = 0;
};

/*  void emitStatus(const char* body) ->
    Emit a non-persisted STATUS line for the app to parse and display live
    (task.json `telemetry`). Deliberately "STATUS "-prefixed and space/key=value
    shaped so it can never be mistaken for a strobe. Utility sketches run in
    PASSTHROUGH, where nothing is stored, so this is display-only telemetry.
    Cadence is the caller's business (emit on state change + a slow heartbeat). */
inline void emitStatus(const char *body)
{
  Serial.print("STATUS ");
  Serial.println(body);
}

/* ============================================================= *
 *  5. HARDWARE helpers (keyed off the shared pinout above)
 * ============================================================= */
/*  Blanket turn-off of all outputs (safe to call at any time).

    Deliberately emits NO strobe, including no BF_LIGHTS_OFF. It is called from
    initBoxHardware() in setup() -- before the clock has been stamped, so a
    timestamp here would be meaningless -- and from the utility sketches, which
    have no session at all. The trial light's own edges are reported from
    runTrial(), where a trial is actually in progress. */
inline void shutdownHardware()
{
  for (int i = 0; i < NUM_ODORS; i++)
    digitalWrite(Odors[i], LOW);
  for (int i = 0; i < NUM_FLUIDS; i++)
    digitalWrite(Fluids[i], LOW);
  digitalWrite(trialLight, LOW);
  digitalWrite(vac, LOW);
}

/* Configure every box pin (IR inputs, solenoid + light + vac outputs) and land
   all outputs LOW. Replaces the identical pinMode boilerplate in each setup(). */
inline void initBoxHardware()
{
  for (int i = 0; i < NUM_ODORS; i++)
    pinMode(Odors[i], OUTPUT);
  for (int i = 0; i < NUM_FLUIDS; i++)
    pinMode(Fluids[i], OUTPUT);
  pinMode(odorPort, INPUT_PULLUP);
  pinMode(leftWell, INPUT_PULLUP);
  pinMode(rightWell, INPUT_PULLUP);
  pinMode(trialLight, OUTPUT);
  pinMode(vac, OUTPUT);
  shutdownHardware();
}

/*  bool verifySensor(int pin, int duration, int pollMs) ->
    Returns false the moment the IR beam at `pin` reads HIGH (unpoked) within
    `duration` ms; true if it stayed LOW (held) the whole time. `pollMs` is the
    per-sketch sensor polling interval. */
inline bool verifySensor(int pin, int duration, int pollMs)
{
  unsigned long start = millis();
  while (millis() - start < duration)
  {
    if (digitalRead(pin) == HIGH)
      return false; // INPUT_PULLUP: HIGH = beam intact = unpoked
    delay(pollMs);
  }
  return true;
}

/*  void flashLight(int duration, int pollMs) ->
    Blink the trial light at the sketch's polling cadence for `duration` ms.
    No strobes: one BF_LIGHTS_OFF per blink would bury a session's real light
    edges under hundreds of decorative ones. */
inline void flashLight(int duration, int pollMs)
{
  unsigned long start = millis();
  while (millis() - start < duration)
  {
    digitalWrite(trialLight, HIGH);
    delay(pollMs);
    digitalWrite(trialLight, LOW);
    delay(pollMs);
  }
}

/* ============================================================= *
 *  6. TASK PARAMETERS -- the whole START-command surface
 * ============================================================= */
/* Largest sliding bias window the anti-bias selector's ring buffer can hold. */
#define BEHAVIOR_MAX_BIAS_WINDOW 32

/*  Number of rows in the ramp table. Five is what both existing schedules use
    (a forgiving stage 0 plus four steps toward the full task). */
#define NUM_STAGES 5

/*  One row of the ramp: the four holds/windows that a shaping schedule walks,
    and the completed-trial count at which this row takes over. */
struct StageStep
{
  int trials;          // completed trials at which this row engages
  int odorPokeHold;    // hold before odor delivery AND during sampling (ms)
  int fluidWellHold;   // hold at the fluid well before reward (ms)
  int fluidWellPoll;   // window to respond after successful sampling (ms)
  int odorPortTimeout; // window to poke following trial light on (ms)
};

/*  EVERY operator-tunable parameter, in one struct.

    This replaces the old split between SessionConfig (three GUI fields) and
    ShapingTimings (twelve compile-time ones shared by both shaping sketches, so
    that retuning shaping_GR silently retuned shaping_GL too). Each sketch now
    owns its own instance and the host fills it from the START line, which is
    what makes the values per-sketch, per-run, and recorded with the data.

    The in-class defaults are the FULL-TASK (GRGL_2-Odor) values, so a bare
    "START" with no tokens still reproduces exactly the legacy behavior. Shaping
    sketches call applyShapingDefaults() for their own bare-START baseline.

    Adding a parameter is two lines: a field here and a row in TASK_PARAM_LIST. */
struct TaskParams
{
  /* --- timings the ramp never touches --- */
  int errorDelay = 20000;         // timeout after an incorrect response
  int nogoWellPoll = 2000;        // withhold window on no-go trials
  int lazyRatDelay = 6000;        // base penalty for failing to initiate
  int lazyEscalateStep = 6000;    // added per CONSECUTIVE lazy trial
  int lazyDelayMax = 30000;       // ceiling on the escalated lazy penalty
  int noPokeHoldTimeout = 10000;  // penalty for failing to hold a poke
  int standardITI = 4000;         // intertrial interval on correct trials
  int primingDelay = 1000;        // odor primed before the trial light
  int pollingRate = 5;            // IR sensor polling interval (ms)
  int fluidPinTimes[NUM_FLUIDS] = {100, 100, 100, 100}; // per-line open time = reward volume

  /* --- session policy --- */
  int correctionLeft = 0;            // CL: leading correction budget, LEFT-correct trials
  int correctionRight = 0;           // CR: leading correction budget, RIGHT-correct trials
  bool lazyEscalationEnabled = true; // LAZY: escalating lazy-rat penalty on/off
  int lazyEscalationStage = 0;       // escalation arms once this stage row is live.
                                     // 0 == from trial 0 (the full task); an eased
                                     // sketch points this at its last row so a rat
                                     // still being shaped is never escalated against.

  /* --- trial generation --- */
  int numTrials = 1000;              // session cap
  int blockSize = 30;                // pool proportions enforced within each block
  int poolWeights[4] = {1, 0, 0, 0}; // shaping only; ignored where selection is live

  /* --- adaptive anti-bias selection (ignored by shaping) --- */
  int biasWindow = 20;         // sliding window of recent expressed choices
  int maxConsecutiveSide = 10; // hard cap on consecutive identical correct sides
  float debiasStrength = 0.5f; // how hard to push against the rat's bias
  float pSideMin = 0.02f;      // clamp on P(correct side) -- never fully
  float pSideMax = 0.98f;      // deterministic, which would itself be a cue

  /* --- the ramp ---
     Row 0 is live from trial 0. A task that does not ramp leaves rows 1..4 at
     the sentinel count, which no session can reach, so they never engage. */
  StageStep stage[NUM_STAGES] = {
      {0, 500, 200, 2000, 4000},
      {32767, 500, 200, 2000, 4000},
      {32767, 500, 200, 2000, 4000},
      {32767, 500, 200, 2000, 4000},
      {32767, 500, 200, 2000, 4000}};

  /* --- live holds/windows, rewritten by applyStage() ---
     The trial runner reads ONLY these four; nothing reads stage[] directly. */
  int odorPokeHold = 500;
  int fluidWellHold = 200;
  int fluidWellPoll = 2000;
  int odorPortTimeout = 4000;

  /* --- the run's RNG seed ---
     0 == the host sent none (an older app); beginSessionRng() then falls back to
     the board's own clock. */
  unsigned long trialSeed = 0;
};

/*  int liveStage(const TaskParams&, int completedTrials) ->
    Index of the ramp row in force at this trial count. Scans DESCENDING with
    >=, so it is idempotent: calling it twice, or skipping a count, lands on the
    same row. The shaping schedule this replaces was a switch on the EXACT trial
    index, which fired once and only if the counter hit that value precisely. */
inline int liveStage(const TaskParams &p, int completedTrials)
{
  for (int i = NUM_STAGES - 1; i > 0; --i)
    if (completedTrials >= p.stage[i].trials)
      return i;
  return 0;
}

/*  void applyStage(TaskParams&, int completedTrials) ->
    Copy the live ramp row into the four working holds/windows. Call once per
    completed trial (and once before the first trial). */
inline void applyStage(TaskParams &p, int completedTrials)
{
  const StageStep &s = p.stage[liveStage(p, completedTrials)];
  p.odorPokeHold = s.odorPokeHold;
  p.fluidWellHold = s.fluidWellHold;
  p.fluidWellPoll = s.fluidWellPoll;
  p.odorPortTimeout = s.odorPortTimeout;
}

/*  bool escalationArmed(const TaskParams&, int completedTrials) ->
    Whether the lazy penalty is allowed to escalate yet (see lazyEscalationStage). */
inline bool escalationArmed(const TaskParams &p, int completedTrials)
{
  return liveStage(p, completedTrials) >= p.lazyEscalationStage;
}

/*  void applyShapingDefaults(TaskParams&) ->
    The shaping sketches' bare-START baseline: the original ShapingTimings values
    and the original 20/25/50/100 stage schedule. Only a bare START (an older
    host, or a hand-typed console session) ever sees these -- the app sends every
    field from the sketch's task.json. */
inline void applyShapingDefaults(TaskParams &p)
{
  p.errorDelay = 20000;
  p.nogoWellPoll = 2000;
  p.lazyRatDelay = 4000;
  p.noPokeHoldTimeout = 5000;
  p.standardITI = 4000;
  p.primingDelay = 1000;
  p.pollingRate = 2;
  //                trials  poke  well  pollWindow  portTimeout
  p.stage[0] = StageStep{0, 10, 10, 10000, 8000};
  p.stage[1] = StageStep{20, 100, 50, 10000, 8000};
  p.stage[2] = StageStep{25, 125, 250, 5000, 8000};
  p.stage[3] = StageStep{50, 250, 500, 2000, 4000};
  p.stage[4] = StageStep{100, 500, 500, 2000, 4000};
  applyStage(p, 0);
}

/*  void applyEasedShapingDefaults(TaskParams&) ->
    The shaping_*_EZ baseline: the same schedule stretched out and started softer,
    for an animal that is struggling with the standard shaping ramp. Same shape,
    more trials per step and a longer runway before the holds bite. */
inline void applyEasedShapingDefaults(TaskParams &p)
{
  applyShapingDefaults(p);
  p.lazyRatDelay = 3000;       // a shorter penalty: re-engaging is what we want
  p.noPokeHoldTimeout = 3000;
  //                trials  poke  well  pollWindow  portTimeout
  p.stage[0] = StageStep{0, 10, 10, 15000, 12000};
  p.stage[1] = StageStep{40, 50, 25, 12000, 10000};
  p.stage[2] = StageStep{80, 125, 100, 8000, 8000};
  p.stage[3] = StageStep{140, 250, 250, 5000, 6000};
  p.stage[4] = StageStep{220, 500, 500, 2000, 4000};
  applyStage(p, 0);
}

/*  void applyEasedDiscriminationDefaults(TaskParams&) ->
    The GRGL_2-Odor_EZ baseline: the full discrimination task, entered through a
    forgiving ramp instead of at full strictness. The anti-bias clamps are pulled
    in as well, so a rat still learning the contingency is not starved as hard as
    the full task starves a fixed-side rat.

    lazyEscalationStage points at the last row: escalating the abstention penalty
    against an animal that is still being shaped punishes it for the ramp. */
inline void applyEasedDiscriminationDefaults(TaskParams &p)
{
  p.lazyEscalationStage = NUM_STAGES - 1;
  p.pSideMin = 0.05f;
  p.pSideMax = 0.95f;
  p.maxConsecutiveSide = 6;
  //                trials  poke  well  pollWindow  portTimeout
  p.stage[0] = StageStep{0, 10, 10, 10000, 8000};
  p.stage[1] = StageStep{15, 100, 50, 10000, 8000};
  p.stage[2] = StageStep{30, 200, 200, 5000, 6000};
  p.stage[3] = StageStep{50, 350, 350, 3000, 4000};
  /* Row 4 IS the full task, so it matches GRGL_2-Odor exactly. It used to set a
     350 ms well hold, against both its own docblock and the 200 ms the real task
     uses -- which made the eased sketch's final stage stricter than the task it
     was easing into. */
  p.stage[4] = StageStep{80, 500, 200, 2000, 4000};
  applyStage(p, 0);
}

/*  TASK_PARAM_LIST -- the single declarative list of wire keys.

    Every key the START grammar accepts appears here exactly once, and the parser
    below is generated from it. Adding a parameter means adding one row; there is
    no second place that can fall out of sync.

    Expand it by defining P_INT / P_FLOAT / P_BOOL / P_ULONG / P_STAGE first.
    Keys are short on purpose: the whole line has to fit START_LINE_MAX, and a
    fully-declared eased task sends close to fifty of them. */
#define TASK_PARAM_LIST                     \
  P_INT("ERR", errorDelay)                  \
  P_INT("NWP", nogoWellPoll)                \
  P_INT("LZD", lazyRatDelay)                \
  P_INT("LZS", lazyEscalateStep)            \
  P_INT("LZM", lazyDelayMax)                \
  P_INT("NPH", noPokeHoldTimeout)           \
  P_INT("ITI", standardITI)                 \
  P_INT("PRM", primingDelay)                \
  P_INT("POL", pollingRate)                 \
  P_INT("FL1", fluidPinTimes[0])            \
  P_INT("FL2", fluidPinTimes[1])            \
  P_INT("FL3", fluidPinTimes[2])            \
  P_INT("FL4", fluidPinTimes[3])            \
  P_INT("CL", correctionLeft)               \
  P_INT("CR", correctionRight)              \
  P_INT("LZG", lazyEscalationStage)         \
  P_INT("NT", numTrials)                    \
  P_INT("BS", blockSize)                    \
  P_INT("PW1", poolWeights[0])              \
  P_INT("PW2", poolWeights[1])              \
  P_INT("PW3", poolWeights[2])              \
  P_INT("PW4", poolWeights[3])              \
  P_INT("BW", biasWindow)                   \
  P_INT("MCS", maxConsecutiveSide)          \
  P_FLOAT("DBS", debiasStrength)            \
  P_FLOAT("PMN", pSideMin)                  \
  P_FLOAT("PMX", pSideMax)                  \
  P_BOOL("LAZY", lazyEscalationEnabled)     \
  P_ULONG("SEED", trialSeed)                \
  P_STAGE(0) P_STAGE(1) P_STAGE(2) P_STAGE(3) P_STAGE(4)

/*  One ramp row's five keys: S<n>T trials, S<n>P poke hold, S<n>H well hold,
    S<n>W well poll, S<n>O odor-port timeout. */
#define TASK_STAGE_KEYS(n)                  \
  P_INT("S" #n "T", stage[n].trials)        \
  P_INT("S" #n "P", stage[n].odorPokeHold)  \
  P_INT("S" #n "H", stage[n].fluidWellHold) \
  P_INT("S" #n "W", stage[n].fluidWellPoll) \
  P_INT("S" #n "O", stage[n].odorPortTimeout)

/*  Hard cap on a START line, mirrored by the host's build_start_command
    (sidecar/ephymeris_sidecar/tasks/start_command.py). There is no shared source
    across the two repos, so the two constants must be changed together: the host
    refuses to build a line longer than this, and readLineInto() truncates
    anything longer than this SILENTLY -- a lost token is not an error the board
    can see, it just runs on the wrong value. */
#define START_LINE_MAX 640

/*  void clampTaskParams(TaskParams&) ->
    Hold every field to a range the trial runner can survive. This matters more
    than it used to: the values are typed by an operator now, not compiled in,
    and a zero polling rate or a bias window past the ring buffer would be a hang
    or an overrun rather than a bad session. */
inline void clampTaskParams(TaskParams &p)
{
  if (p.correctionLeft < 0) p.correctionLeft = 0;
  if (p.correctionRight < 0) p.correctionRight = 0;
  if (p.pollingRate < 1) p.pollingRate = 1;
  if (p.numTrials < 1) p.numTrials = 1;
  if (p.blockSize < 1) p.blockSize = 1;
  if (p.biasWindow < 1) p.biasWindow = 1;
  if (p.biasWindow > BEHAVIOR_MAX_BIAS_WINDOW) p.biasWindow = BEHAVIOR_MAX_BIAS_WINDOW;
  if (p.maxConsecutiveSide < 1) p.maxConsecutiveSide = 1;
  if (p.lazyEscalationStage < 0) p.lazyEscalationStage = 0;
  if (p.lazyEscalationStage >= NUM_STAGES) p.lazyEscalationStage = NUM_STAGES - 1;
  if (p.pSideMin < 0.0f) p.pSideMin = 0.0f;
  if (p.pSideMax > 1.0f) p.pSideMax = 1.0f;
  if (p.pSideMax < p.pSideMin) p.pSideMax = p.pSideMin;
  for (int i = 0; i < NUM_FLUIDS; i++)
    if (p.fluidPinTimes[i] < 0) p.fluidPinTimes[i] = 0;
  for (int i = 0; i < 4; i++)
    if (p.poolWeights[i] < 0) p.poolWeights[i] = 0;
}

/*  void parseStartCommand(char* line, TaskParams& p) ->
    Parse a START line into p. Grammar (mirrors the app's start-command builder):

        START <KEY>=<value> <KEY>=<value> ...

    Order-independent; unknown keys ignored; any missing key keeps p's current
    value, so a bare "START" reproduces the sketch's compiled-in behavior and an
    older host talking to newer firmware still runs.

    PARSES IN PLACE. It used to strncpy into a private 96-byte buffer, which gave
    the line TWO independent caps -- the caller's and this one's -- either of
    which could silently drop a token. `line` is the caller's own buffer and is
    modified (strtok); it must be at least the length of the line it holds. */
inline void parseStartCommand(char *line, TaskParams &p)
{
  for (char *tok = strtok(line, " "); tok != NULL; tok = strtok(NULL, " "))
  {
    char *eq = strchr(tok, '=');
    if (eq == NULL)
      continue; // the leading "START" token, and any bare word
    *eq = '\0';
    const char *k = tok;
    const char *v = eq + 1;

// atoi() is a 16-bit parse on AVR, which is fine for every int field (the
// largest, lazyDelayMax, is 30000). SEED is the one value that spans the full
// 31-bit Park-Miller range, so it -- and only it -- needs strtoul.
#define P_INT(key, field)   if (strcmp(k, key) == 0) { p.field = atoi(v); continue; }
#define P_FLOAT(key, field) if (strcmp(k, key) == 0) { p.field = (float)atof(v); continue; }
#define P_BOOL(key, field)  if (strcmp(k, key) == 0) { p.field = (atoi(v) != 0); continue; }
#define P_ULONG(key, field) if (strcmp(k, key) == 0) { p.field = strtoul(v, NULL, 10); continue; }
#define P_STAGE(n)          TASK_STAGE_KEYS(n)
    TASK_PARAM_LIST
#undef P_INT
#undef P_FLOAT
#undef P_BOOL
#undef P_ULONG
#undef P_STAGE
  }
  clampTaskParams(p);
  applyStage(p, 0); // the live holds must reflect row 0 before trial 1 runs
}

/*  unsigned long beginSessionRng(const TaskParams& p) ->
    Seed this run's RNG and announce the seed. Call once, immediately after the
    START line is parsed and BEFORE anything draws a random number.

    THE SEED COMES FROM THE HOST. The app draws it from an OS CSPRNG at the
    instant the operator starts the box (see the sidecar's tasks/seed.py) and
    sends it as SEED=<n>. That is not a convenience -- a board cannot do this
    job. Opening the serial port is both what starts the run and what resets the
    Mega over DTR, so micros() here is NOT the operator's click: it is the fixed
    interval from reset to START, the same few milliseconds every time, at 4 us
    resolution. Seeding from it gives a few hundred reachable sequences, and two
    sessions drawing the identical trial order is then a matter of when, not if.

    The micros() fallback survives for exactly one case: an older app that sends
    no SEED token. It is weak on purpose -- reproducing the old behavior beats
    refusing to run -- and the app logs a warning when the echoed seed doesn't
    match what it sent.

    Held to [1, 2^31-2] either way. randomSeed(0) is a documented no-op in the
    Arduino core (it skips srandom entirely, leaving the default state), and
    avr-libc's random() is Park-Miller, whose state space ends at 2^31-2. The
    value announced is therefore exactly the state the generator is running on. */
inline unsigned long beginSessionRng(const TaskParams &p)
{
  unsigned long seed = p.trialSeed;
  if (seed == 0)
    seed = micros();
  // Fold into the Park-Miller state space. Modulus 2^31-1, so every value the
  // host can legally send maps to ITSELF -- the clamp only ever moves an
  // out-of-range micros() fallback, and never rewrites a seed we then log.
  seed %= 2147483647UL;
  if (seed == 0)
    seed = 1UL;

  randomSeed(seed);
  Serial.print("SEED\t");
  Serial.println(seed);
  return seed;
}

/* ============================================================= *
 *  7. SESSION POLICY (anti-bias selection, penalties, correction budgets)
 * ============================================================= */
/*  Adaptive anti-bias trial selection. Owns the sliding-window estimate of the
    rat's recent expressed side preference and the next-side draw that pushes
    AGAINST it, clamped so selection never collapses into a deterministic
    (cue-able) pattern, with a hard cap on same-side runs. Pin-agnostic: speaks
    in bool wentRight / presentedRight and returns one of the two go-trials
    passed at construction. Tuning constants that differ between sketches are
    constructor arguments. */
class AntiBiasSelector
{
public:
  AntiBiasSelector(const TrialType *goRight, const TrialType *goLeft,
                   int biasWindow = 20, float debiasStrength = 0.5f,
                   float pSideMin = 0.02f, float pSideMax = 0.98f,
                   int maxConsecutiveSide = 10)
      : _goRight(goRight), _goLeft(goLeft),
        _window(biasWindow < BEHAVIOR_MAX_BIAS_WINDOW ? biasWindow : BEHAVIOR_MAX_BIAS_WINDOW),
        _debias(debiasStrength), _pMin(pSideMin), _pMax(pSideMax),
        _maxRun(maxConsecutiveSide) {}

  /*  Adopt the run's tuning from the parsed START line. Necessary because the
      selector is a global, constructed long before START arrives; call once,
      after parseStartCommand(), and before the first selectNext(). Safe to call
      on a fresh selector only -- it resizes the ring, so it discards history. */
  void configure(const TaskParams &p)
  {
    _window = p.biasWindow < BEHAVIOR_MAX_BIAS_WINDOW ? p.biasWindow : BEHAVIOR_MAX_BIAS_WINDOW;
    if (_window < 1)
      _window = 1;
    _debias = p.debiasStrength;
    _pMin = p.pSideMin;
    _pMax = p.pSideMax;
    _maxRun = p.maxConsecutiveSide;
    _len = _idx = _rightInWindow = 0;
  }

  /* Push the rat's expressed side choice (correct OR wrong well) into the ring,
     evicting the oldest once full and keeping the running right-count in sync. */
  void recordChoice(bool wentRight)
  {
    if (_len == _window)
      _rightInWindow -= _ring[_idx];
    else
      _len++;
    _ring[_idx] = wentRight ? 1 : 0;
    _rightInWindow += _ring[_idx];
    _idx = (_idx + 1) % _window;
  }

  /* A lazy/no-poke trial expresses no side but must not be invisible to the
     estimator -- log a weak vote AGAINST engaging the presented side. */
  void recordAbstention(bool presentedRight) { recordChoice(presentedRight); }

  /* Draw the next trial's correct side, nudged against recent bias and capped. */
  const TrialType *selectNext()
  {
    float pRight = 0.5;
    if (_len > 0)
    {
      float bias = (2.0 * _rightInWindow - _len) / (float)_len; // [-1,1]
      pRight = 0.5 - _debias * bias;
      if (pRight < _pMin)
        pRight = _pMin;
      if (pRight > _pMax)
        pRight = _pMax;
    }

    bool chooseRight = grglFrand() < pRight;

    // Hard cap: if this would extend a same-side run past the cap, flip it.
    if (_hasLast && chooseRight == _lastWasRight && _selectedRun >= _maxRun)
      chooseRight = !chooseRight;

    if (_hasLast && chooseRight == _lastWasRight)
      _selectedRun++;
    else
    {
      _lastWasRight = chooseRight;
      _hasLast = true;
      _selectedRun = 1;
    }

    return chooseRight ? _goRight : _goLeft;
  }

private:
  const TrialType *_goRight;
  const TrialType *_goLeft;
  int _window;
  float _debias, _pMin, _pMax;
  int _maxRun;

  int _ring[BEHAVIOR_MAX_BIAS_WINDOW] = {0};
  int _len = 0, _idx = 0, _rightInWindow = 0;
  bool _lastWasRight = false, _hasLast = false;
  int _selectedRun = 0;
};

/*  The lazy-rat timeout and its escalation. Owns the consecutive-abstention
    counter and the GUI on/off toggle. nextDelay(stageAllowsEscalation):
      * enabled AND stageAllowsEscalation -> escalating (base + consecutive*step,
        clamped to max), and bumps the counter;
      * otherwise                          -> flat base, counter untouched.
    reset() zeroes the counter at each sketch's own engage point. */
class AbstentionPenalty
{
public:
  AbstentionPenalty(long baseDelay = 6000, long step = 6000, long maxDelay = 30000)
      : _base(baseDelay), _step(step), _max(maxDelay) {}

  /* Adopt the run's tuning + the GUI toggle from the parsed START line. */
  void configure(const TaskParams &p)
  {
    _base = p.lazyRatDelay;
    _step = p.lazyEscalateStep;
    _max = p.lazyDelayMax;
    _enabled = p.lazyEscalationEnabled;
    _consecutive = 0;
  }

  void setEnabled(bool enabled) { _enabled = enabled; }
  void reset() { _consecutive = 0; }

  long nextDelay(bool stageAllowsEscalation)
  {
    if (_enabled && stageAllowsEscalation)
    {
      long d = _base + (long)_consecutive * _step;
      if (d > _max)
        d = _max;
      _consecutive++;
      return d;
    }
    return _base;
  }

private:
  long _base, _step, _max;
  bool _enabled = true;
  int _consecutive = 0;
};

/*  Per-side leading correction trials. Each side has an independent budget,
    consumed by COMPLETED (advancing) trials on that side; a correction REPEAT
    (an under-budget error) re-presents the same side without consuming budget.
    Defaults (0/0) => never repeat => legacy bare-START behavior. */
class CorrectionPolicy
{
public:
  void configure(int leftBudget, int rightBudget)
  {
    _leftBudget = leftBudget;
    _rightBudget = rightBudget;
  }

  bool shouldRepeat(bool correctIsRight) const
  {
    return correctIsRight ? (_advancedRight < _rightBudget)
                          : (_advancedLeft < _leftBudget);
  }

  void onAdvance(bool correctIsRight)
  {
    if (correctIsRight)
      _advancedRight++;
    else
      _advancedLeft++;
  }

private:
  int _leftBudget = 0, _rightBudget = 0;
  int _advancedLeft = 0, _advancedRight = 0;
};

/* ============================================================= *
 *  8. TRIAL RUNNER -- one loop, shared by every behavior sketch
 * ============================================================= */
/*  The shaping sketches and the GRGL sketches ran two copies of what is
    structurally the same trial: prime odor, light on, await poke, verify the
    pre-odor hold, present odor, verify the sampling hold, await unpoke, poll the
    wells, administer an outcome delay. They differed only in POLICY -- GRGL adds
    anti-bias selection, an escalating abstention penalty, and per-side
    correction budgets; shaping has none of the three and advances on any
    completed trial.

    So the policy is passed in and the loop is written once. A sketch with no
    policy passes nullptr and gets the shaping semantics; GRGL passes its three
    objects. This is what makes GRGL_2-Odor and GRGL_2-Odor_EZ differ by nothing
    but their task.json defaults, and it retires the three ways the EZ copy had
    already drifted from the original (see the repo history for that loop). */
struct TrialPolicy
{
  AntiBiasSelector *selector = nullptr;   // nullptr -> fixed pool, no bias estimate
  AbstentionPenalty *abstention = nullptr;// nullptr -> flat lazyRatDelay
  CorrectionPolicy *correction = nullptr; // nullptr -> advance on any completed trial
};

/*  How a trial ended. Returned by checkResponse() instead of the delay itself.

    The delay used to BE the return value, and the caller recovered the outcome
    by comparing it back against standardITI. That worked only because the three
    delays were compiled-in and happened to differ. They are operator-typed now:
    an operator who sets errorDelay to the same value as standardITI would make
    every error emit BF_END_CORRECT_ITI and clear the abstention escalator, with
    nothing anywhere reporting a problem. */
enum TrialOutcome
{
  OUTCOME_CORRECT,   // held the correct well, or correctly withheld on a no-go
  OUTCOME_HOLD_FAIL, // poked the correct well but failed to hold it
  OUTCOME_ERROR      // wrong well, no response, or responded on a no-go
};

inline int outcomeDelay(TrialOutcome outcome, const TaskParams &p)
{
  if (outcome == OUTCOME_CORRECT)
    return p.standardITI;
  if (outcome == OUTCOME_HOLD_FAIL)
    return p.noPokeHoldTimeout;
  return p.errorDelay;
}

/* Open this trial's fluid line for its configured duration (the reward volume). */
inline void deliverReward(const TrialType &trial, const TaskParams &p, TrialClock &clock)
{
  int fluidPin = Fluids[trial.rewardIndex];
  int fluidDuration = p.fluidPinTimes[trial.rewardIndex];

  emitStrobe(clock, trial.fluidEventCode); // log fluid delivery
  digitalWrite(fluidPin, HIGH);            // open fluid solenoid
  delay(fluidDuration);                    // hold open
  digitalWrite(fluidPin, LOW);             // close fluid solenoid
  emitStrobe(clock, trial.stopFluidCode);  // log fluid stop
}

/*  Poll the fluid wells after successful odor sampling and classify the outcome. */
inline TrialOutcome checkResponse(const TrialType &trial, const TaskParams &p,
                                  TrialClock &clock, TrialPolicy *policy)
{
  if (trial.isGo)
  {
    unsigned long pollStart = millis();
    int pokedWell = SENTINEL;
    /* Randomize the tie-break only where both sides are live. A simultaneous
       L/R beam break otherwise always resolves right, which on a two-sided task
       is a systematic bias. On a one-sided shaping pool it is just the original
       fixed order, and randomizing there would turn a correct double-break into
       a coin flip -- so shaping (no policy) keeps right-first. */
    bool rightFirst = (policy != nullptr) ? (random(0, 2) == 0) : true;

    while (millis() - pollStart < (unsigned long)p.fluidWellPoll)
    { // 1. Poll both wells (tie broken by the order above)
      int rRead = digitalRead(rightWell);
      int lRead = digitalRead(leftWell);
      if (rRead == LOW && lRead == LOW)
        pokedWell = rightFirst ? rightWell : leftWell;
      else if (rRead == LOW)
        pokedWell = rightWell;
      else if (lRead == LOW)
        pokedWell = leftWell;

      if (pokedWell != SENTINEL)
      {
        emitStrobe(clock, pokedWell == rightWell ? BF_WATER_POKE_R : BF_WATER_POKE_L);
        if (policy && policy->selector) // the expressed side feeds the bias estimate
          policy->selector->recordChoice(pokedWell == rightWell);
        break;
      }
      delay(p.pollingRate);
    }

    if (pokedWell == SENTINEL)
    { /* Say so. END_INCORRECT_ITI is reached by three different outcomes, so
         without this the class is recoverable only from the PRECEDING strobe --
         and an omission has none. */
      emitStrobe(clock, BF_RESP_OMIT);
      return OUTCOME_ERROR; // 2. No response within the window
    }

    if (pokedWell != trial.correctWell)
    {
      emitStrobe(clock, pokedWell == rightWell ? BF_WATER_POKE_ERROR_R : BF_WATER_POKE_ERROR_L);
      return OUTCOME_ERROR; // Wrong well
    }

    if (!verifySensor(pokedWell, p.fluidWellHold, p.pollingRate))
    { // 3. Correct well -- verify the hold
      emitStrobe(clock, pokedWell == rightWell ? BF_WATER_UNPOKE_EARLY_R : BF_WATER_UNPOKE_EARLY_L);
      return OUTCOME_HOLD_FAIL;
    }

    deliverReward(trial, p, clock); // 4. Held -- deliver reward
    while (digitalRead(pokedWell) == LOW) // Await well unpoke
      delay(p.pollingRate);
    /* The consummatory bout's end, and the only place the firmware actually
       observes the animal leaving a well. The other two exits are already
       reported by more specific codes -- WATER_UNPOKE_EARLY_* when the hold
       failed, and nothing at all on a wrong-well answer, where the firmware
       returns immediately and never waits for the withdrawal. */
    emitStrobe(clock, pokedWell == rightWell ? BF_WATER_UNPOKE_R : BF_WATER_UNPOKE_L);
  }
  else
  {
    unsigned long pollStart = millis(); // NO-GO -> poll both wells for nogoWellPoll
    while (millis() - pollStart < (unsigned long)p.nogoWellPoll)
    {
      if (digitalRead(rightWell) == LOW)
      {
        emitStrobe(clock, BF_WATER_POKE_R);
        return OUTCOME_ERROR; // Responded on a no-go
      }
      if (digitalRead(leftWell) == LOW)
      {
        emitStrobe(clock, BF_WATER_POKE_L);
        return OUTCOME_ERROR; // Responded on a no-go
      }
      delay(p.pollingRate);
    }
    emitStrobe(clock, BF_WATER_POKE_NONE); // Correctly withheld
  }

  return OUTCOME_CORRECT;
}

/*  bool runTrial(...) ->
    Run one trial. Returns true when the trial ADVANCES the session, false when
    the caller should re-present the same trial (an abort, or an under-budget
    correction error). `completedTrials` is the advancing-trial count, used only
    to decide whether the lazy penalty may escalate yet. */
inline bool runTrial(const TrialType &trial, TaskParams &p, TrialClock &clock,
                     TrialPolicy *policy, int completedTrials)
{
  digitalWrite(trial.odorPin, HIGH); // 1. Prime the correct odor
  delay(p.primingDelay);             // 2. Fixed priming delay (controlled latency)
  digitalWrite(trialLight, HIGH);    // 3. Trial light on
  emitStrobe(clock, BF_LIGHTS_ON);

  unsigned long waitStart = millis();
  while (digitalRead(odorPort) == HIGH)
  { // 4. Await the odor poke
    if (millis() - waitStart >= (unsigned long)p.odorPortTimeout)
    {
      digitalWrite(trialLight, LOW);
      digitalWrite(trial.odorPin, LOW);
      emitStrobe(clock, BF_LAZY_RAT);
      emitStrobe(clock, BF_LIGHTS_OFF);
      if (policy && policy->selector) // abstention feeds the bias estimate too
        policy->selector->recordAbstention(trial.correctWell == rightWell);
      if (policy && policy->abstention)
        delay(policy->abstention->nextDelay(escalationArmed(p, completedTrials)));
      else
        delay(p.lazyRatDelay);
      return false; // Error 1: failed to initiate in time
    }
    delay(p.pollingRate);
  }
  emitStrobe(clock, BF_ODOR_POKE);
  /* NOTE: the abstention escalator is NOT reset here. A bare odor-poke (or a
     poke-and-bail) must not defuse the lazy penalty -- only a completed CORRECT
     trial clears it, in the OUTCOME_CORRECT branch below. This closes the
     poke-to-reset loophole, which the old EZ copy of this loop had reopened. */

  if (!verifySensor(odorPort, p.odorPokeHold, p.pollingRate))
  { // 5. Verify the pre-odor hold
    digitalWrite(trialLight, LOW);
    digitalWrite(trial.odorPin, LOW);
    emitStrobe(clock, BF_ODOR_UNPOKE_EARLY);
    emitStrobe(clock, BF_LIGHTS_OFF);
    if (policy && policy->selector) // poke-and-bail still counts as not-engaging
      policy->selector->recordAbstention(trial.correctWell == rightWell);
    delay(p.noPokeHoldTimeout);
    return false; // Error 2: didn't hold before the vac closed
  }

  emitStrobe(clock, trial.odorOnCode); // Trial-specific odor on
  digitalWrite(vac, HIGH);             // 6. Close the N.O.V., directing odor to the rat

  if (!verifySensor(odorPort, p.odorPokeHold, p.pollingRate))
  { // 7. Verify the odor-sampling hold
    digitalWrite(trialLight, LOW);
    digitalWrite(trial.odorPin, LOW);
    digitalWrite(vac, LOW);
    emitStrobe(clock, BF_ODOR_UNPOKE_EARLY);
    emitStrobe(clock, BF_LIGHTS_OFF);
    if (policy && policy->selector)
      policy->selector->recordAbstention(trial.correctWell == rightWell);
    delay(p.noPokeHoldTimeout);
    return false; // Error 3: didn't sample long enough
  }

  digitalWrite(trial.odorPin, LOW); // 8. Odor off, open the vac
  digitalWrite(vac, LOW);
  emitStrobe(clock, BF_ODOR_OFF);

  while (digitalRead(odorPort) == LOW) // 9. Await the unpoke
    delay(p.pollingRate);
  emitStrobe(clock, BF_ODOR_UNPOKE);

  digitalWrite(trialLight, LOW);
  emitStrobe(clock, BF_LIGHTS_OFF);
  TrialOutcome outcome = checkResponse(trial, p, clock, policy); // 10. Outcome
  delay(outcomeDelay(outcome, p));                               // 11. Its delay

  if (outcome == OUTCOME_CORRECT)
  {
    emitStrobe(clock, BF_END_CORRECT_ITI);
    if (policy && policy->abstention)
      policy->abstention->reset(); // only a completed CORRECT trial clears it
    return true;
  }

  emitStrobe(clock, BF_END_INCORRECT_ITI);
  /* Per-side correction: while THIS side is still under its leading budget, an
     incorrect response repeats the same trial (return false -> the caller logs
     BF_INVALID_TRIAL and re-presents the same side). Past that side's budget,
     advance regardless of correctness. A sketch with no correction policy
     (shaping) advances on any completed trial, as it always has. */
  if (policy && policy->correction)
    return !policy->correction->shouldRepeat(trial.correctWell == rightWell);
  return true;
}

#endif // BEHAVIOR_BOX_H

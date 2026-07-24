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
    * the reusable TRIAL primitives (TrialClock, TrialType, TrialWeight +
      generateTrials) and the GRGL session POLICY classes (anti-bias selection,
      the lazy-penalty escalator, per-side correction budgets);
    * the shaping trial runner, so shaping_GL and shaping_GR differ only in their
      trial pool, not in a duplicated ~140-line behavior loop.

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
#define BF_LIGHTS_OFF           233 // Trial light off
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
    verbatim from the shaping sketches so both share one copy.) */
inline void generateTrials(const TrialType *trials[], int numTrials, int blockSize,
                           long seed, const TrialWeight pool[], int poolSize)
{
  int totalWeight = 0;
  for (int i = 0; i < poolSize; i++)
    totalWeight += pool[i].weight;

  randomSeed(seed);

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
/* Blanket turn-off of all outputs (safe to call at any time). */
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
    Blink the trial light at the sketch's polling cadence for `duration` ms. */
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
 *  6. GRGL SESSION POLICY (used by GRGL_2-Odor and GRGL_2-Odor_EZ)
 * ============================================================= */
/* Runtime parameters carried from the GUI to the board in the START command.
   Add a field here + one branch in parseStartCommand() and it flows everywhere. */
struct SessionConfig
{
  int correctionLeft = 0;            // CL: leading correction budget, LEFT-correct trials
  int correctionRight = 0;           // CR: leading correction budget, RIGHT-correct trials
  bool lazyEscalationEnabled = true; // LAZY: escalating lazy-rat penalty on/off
};

/*  void parseStartCommand(const char* line, SessionConfig& cfg) ->
    Parse a START line into cfg. Grammar (mirrors the app's start-command builder):

        START CL=<int> CR=<int> LAZY=<0|1>

    Order-independent; unknown keys ignored; any missing key keeps cfg's default
    (CL=0 CR=0 LAZY=1), so a bare "START" reproduces the legacy behavior. */
inline void parseStartCommand(const char *line, SessionConfig &cfg)
{
  char buf[64];
  strncpy(buf, line, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = '\0';

  char *tok = strtok(buf, " ");
  while (tok != NULL)
  {
    char *eq = strchr(tok, '=');
    if (eq != NULL)
    {
      *eq = '\0';
      const char *key = tok;
      const char *val = eq + 1;
      if (strcmp(key, "CL") == 0)
      {
        int v = atoi(val);
        cfg.correctionLeft = (v > 0) ? v : 0;
      }
      else if (strcmp(key, "CR") == 0)
      {
        int v = atoi(val);
        cfg.correctionRight = (v > 0) ? v : 0;
      }
      else if (strcmp(key, "LAZY") == 0)
      {
        cfg.lazyEscalationEnabled = (atoi(val) != 0);
      }
      // unknown keys (and the leading "START" token) are ignored
    }
    tok = strtok(NULL, " ");
  }
}

/* Largest sliding bias window the selector's ring buffer can hold. */
#define BEHAVIOR_MAX_BIAS_WINDOW 32

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
                   int biasWindow, float debiasStrength,
                   float pSideMin, float pSideMax, int maxConsecutiveSide)
      : _goRight(goRight), _goLeft(goLeft),
        _window(biasWindow < BEHAVIOR_MAX_BIAS_WINDOW ? biasWindow : BEHAVIOR_MAX_BIAS_WINDOW),
        _debias(debiasStrength), _pMin(pSideMin), _pMax(pSideMax),
        _maxRun(maxConsecutiveSide) {}

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
  AbstentionPenalty(long baseDelay, long step, long maxDelay)
      : _base(baseDelay), _step(step), _max(maxDelay) {}

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
 *  7. SHAPING RUNNER (shared by shaping_GL and shaping_GR)
 * ============================================================= */
/*  The two shaping sketches ran a byte-identical behavior loop and differed only
    in which odor got weight in the pool. That loop lives here now so the sketches
    stay tiny (pool + a few calls). The mutable timings that the stage schedule
    ramps live in ShapingTimings so each sketch owns its own copy. */
struct ShapingTimings
{
  int errorDelay = 20000;      // Timeout for incorrect response
  int odorPortTimeout = 8000;  // Window to poke following light on
  int odorPokeHold = 10;       // Hold before odor delivery AND during sampling (ms)
  int fluidWellHold = 10;      // Hold before fluid delivery on correct trials (ms)
  int fluidWellPoll = 10000;   // Window to respond following successful sampling
  int nogoWellPoll = 2000;     // Withhold window on no-go trials
  int lazyRatDelay = 4000;     // Timeout for failure to initiate trial
  int noPokeHoldTimeout = 5000;// Timeout for failure to hold poke
  int standardITI = 4000;      // Intertrial interval on correct trials
  int primingDelay = 1000;     // Odor priming before trial light on
  int pollingRate = 2;         // IR sensor polling interval (ms)
  int fluidPinTimes[NUM_FLUIDS] = {100, 100, 100, 100}; // per-line open time (ms)
};

/*  Ramp holds/windows as the rat advances (the original per-trial-count stage
    schedule). Called once per completed trial with the new trial count. */
inline void shapingApplyStage(ShapingTimings &t, int currentTrial)
{
  switch (currentTrial)
  {
  case 20: // Stage: longer holds begin
    t.odorPokeHold = 100;
    t.fluidWellHold = 50;
    break;
  case 25: // Stage 2: 250ms ttip, 250ms fluid hold, 5s well poll
    t.odorPokeHold = 125;
    t.fluidWellHold = 250;
    t.fluidWellPoll = 5000;
    break;
  case 50: // Stage 3: 500ms ttip, 500ms fluid hold, 4s odor timeout, 2s well poll
    t.odorPokeHold = 250;
    t.fluidWellHold = 500;
    t.odorPortTimeout = 4000;
    t.fluidWellPoll = 2000;
    break;
  case 100: // Stage 4: 1s ttip, 500ms fluid hold
    t.odorPokeHold = 500;
    break;
  default:
    break;
  }
}

inline void shapingGiveReward(const TrialType &trial, ShapingTimings &t, TrialClock &clock)
{
  int fluidPin = Fluids[trial.rewardIndex];
  int fluidDuration = t.fluidPinTimes[trial.rewardIndex];

  emitStrobe(clock, trial.fluidEventCode); // Log fluid delivery
  digitalWrite(fluidPin, HIGH);            // Open fluid solenoid
  delay(fluidDuration);                    // Hold open
  digitalWrite(fluidPin, LOW);             // Close fluid solenoid
  emitStrobe(clock, trial.stopFluidCode);  // Log fluid stop
}

/*  Poll the wells after successful odor sampling; return the intertrial delay to
    administer for the outcome (standardITI = correct, noPokeHoldTimeout = poked
    correct well but didn't hold, errorDelay = wrong well / no response / no-go
    violated). Shaping polls right-then-left in fixed order (no anti-bias). */
inline int shapingCheckResponse(const TrialType &trial, ShapingTimings &t, TrialClock &clock)
{
  if (trial.isGo)
  {
    unsigned long pollStart = millis();
    int pokedWell = SENTINEL;

    while (millis() - pollStart < (unsigned long)t.fluidWellPoll)
    {
      if (digitalRead(rightWell) == LOW)
      {
        pokedWell = rightWell;
        emitStrobe(clock, BF_WATER_POKE_R);
        break;
      }
      if (digitalRead(leftWell) == LOW)
      {
        pokedWell = leftWell;
        emitStrobe(clock, BF_WATER_POKE_L);
        break;
      }
      delay(t.pollingRate);
    }

    if (pokedWell == SENTINEL)
      return t.errorDelay; // No response within timeout

    if (pokedWell != trial.correctWell)
    {
      emitStrobe(clock, pokedWell == rightWell ? BF_WATER_POKE_ERROR_R : BF_WATER_POKE_ERROR_L);
      return t.errorDelay; // Wrong well
    }

    if (!verifySensor(pokedWell, t.fluidWellHold, t.pollingRate))
    {
      emitStrobe(clock, pokedWell == rightWell ? BF_WATER_UNPOKE_EARLY_R : BF_WATER_UNPOKE_EARLY_L);
      return t.noPokeHoldTimeout; // Didn't hold
    }

    shapingGiveReward(trial, t, clock); // Held -- deliver reward
    while (digitalRead(pokedWell))      // Await well unpoke
      delay(t.pollingRate);
  }
  else
  {
    unsigned long pollStart = millis(); // NO-GO -> poll both wells for nogoWellPoll
    while (millis() - pollStart < (unsigned long)t.nogoWellPoll)
    {
      if (digitalRead(rightWell) == LOW)
      {
        emitStrobe(clock, BF_WATER_POKE_R);
        return t.errorDelay; // Responded on no-go
      }
      if (digitalRead(leftWell) == LOW)
      {
        emitStrobe(clock, BF_WATER_POKE_L);
        return t.errorDelay; // Responded on no-go
      }
      delay(t.pollingRate);
    }
    emitStrobe(clock, BF_WATER_POKE_NONE); // Correctly withheld
  }

  return t.standardITI; // Correct
}

/*  Run one shaping trial. Returns true on any COMPLETED trial (shaping advances
    on completion regardless of correctness), false on an abort (lazy / poke-hold
    failure) so the caller repeats. Mirrors the GRGL odor-sampling flow minus the
    anti-bias / correction / abstention policy. */
inline bool shapingOdorSampling(const TrialType &trial, ShapingTimings &t, TrialClock &clock)
{
  digitalWrite(trial.odorPin, HIGH); // 1. Prime the correct odor
  delay(t.primingDelay);             // 2. Fixed priming delay
  digitalWrite(trialLight, HIGH);    // 3. Trial light on
  emitStrobe(clock, BF_LIGHTS_ON);

  unsigned long waitStart = millis();
  while (digitalRead(odorPort) == HIGH)
  { // 4. Await odor poke
    if (millis() - waitStart >= (unsigned long)t.odorPortTimeout)
    {
      digitalWrite(trialLight, LOW);
      digitalWrite(trial.odorPin, LOW);
      emitStrobe(clock, BF_LAZY_RAT);
      delay(t.lazyRatDelay);
      return false; // Error 1: failed to poke in time
    }
    delay(t.pollingRate);
  }
  emitStrobe(clock, BF_ODOR_POKE);

  if (!verifySensor(odorPort, t.odorPokeHold, t.pollingRate))
  { // 5. Verify pre-odor hold
    digitalWrite(trialLight, LOW);
    digitalWrite(trial.odorPin, LOW);
    emitStrobe(clock, BF_ODOR_UNPOKE_EARLY);
    delay(t.noPokeHoldTimeout);
    return false; // Error 2: didn't hold before vac close
  }

  emitStrobe(clock, trial.odorOnCode); // Trial-specific odor on
  digitalWrite(vac, HIGH);             // 6. Close vac, direct odor to rat

  if (!verifySensor(odorPort, t.odorPokeHold, t.pollingRate))
  { // 7. Verify odor sampling hold
    digitalWrite(trialLight, LOW);
    digitalWrite(trial.odorPin, LOW);
    digitalWrite(vac, LOW);
    emitStrobe(clock, BF_ODOR_UNPOKE_EARLY);
    delay(t.noPokeHoldTimeout);
    return false; // Error 3: didn't sample long enough
  }

  digitalWrite(trial.odorPin, LOW); // 8. Odor off, open vac
  digitalWrite(vac, LOW);
  emitStrobe(clock, BF_ODOR_OFF);

  while (digitalRead(odorPort) == LOW) // 9. Await unpoke
    delay(t.pollingRate);
  emitStrobe(clock, BF_ODOR_UNPOKE);

  digitalWrite(trialLight, LOW);
  int responseDelay = shapingCheckResponse(trial, t, clock); // 10. Outcome + delay
  delay(responseDelay);
  if (responseDelay == t.standardITI)
    emitStrobe(clock, BF_END_CORRECT_ITI);
  else
    emitStrobe(clock, BF_END_INCORRECT_ITI);
  return true; // Shaping advances on any completed trial
}

#endif // BEHAVIOR_BOX_H

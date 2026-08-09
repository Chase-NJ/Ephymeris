/*
  BehaviorBox.h
  =============
  Author: Chase Johnston (2026)

  THE single shared header for every sketch in this repo -- the GRGL task, the
  simulator, and the utility/cleaning sketch all include it. It is the one
  source of truth for:

    * the SERIAL PROTOCOL helpers shared with the Ephymeris app: the strobe
      emitter, the blocking START reader, the non-blocking STOP poll, and (for
      utility sketches) a non-blocking command reader + a STATUS emitter;
    * TaskParams -- EVERY operator-tunable parameter, and the one declarative
      list (TASK_PARAM_LIST) from which the START-line parser is generated. The
      app fills this from the task profile's task.json, so a parameter is tuned
      per profile and per run instead of being recompiled;
    * the reusable TRIAL primitives (TrialClock, TrialType, TrialWeight +
      generateTrials) and the session POLICY classes (anti-bias selection,
      the lazy-penalty escalator, per-side correction budgets);
    * the TRIAL RUNNER -- one loop for every behavior task. A weighted pool and
      live anti-bias selection run the same trial and differ only in which
      policies they hand it, which is why GRGL.ino covers both in ~110 lines.

  It pulls the box's PINOUT and STROBE VOCABULARY in from BoxPins.h and
  BoxStrobes.h. Both are guarded, so a sketch that includes a GENERATED
  `TaskPins.h` first compiles against this rig's own wiring -- that is how a
  task profile authored in Ephymeris reaches the firmware, and it is the reason
  neither is a `const int` here any more.

  WHAT IS DELIBERATELY NOT HERE: the trial table. Trial types name pins and
  strobe codes and are per-profile, so they live in the sketch (generated as
  `TaskTrials.h`, or hand-written for a one-off). This header knows what a
  TrialType IS and never which ones exist.

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
 *  1. THE BOX ITSELF -- pins and strobe codes
 * ============================================================= *
 *  Both are guarded definitions in their own headers so a GENERATED header can
 *  override them. A sketch that includes `TaskPins.h` before this file compiles
 *  against this rig's own wiring and vocabulary; one that includes nothing gets
 *  the box as built. See BoxPins.h.
 *
 *  Included here rather than left to each sketch so that a sketch cannot get
 *  half of it -- the trial runner below reads `odorPort`, `Fluids[]` and the
 *  BF_* codes directly. */
#include "BoxPins.h"
#include "BoxStrobes.h"

/* ============================================================= *
 *  2. TRIAL PRIMITIVES
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
   Used by the block-shuffled generateTrials() below (pool-mode tasks). */
struct TrialWeight
{
  const TrialType *type;
  int weight;

  /*  The default exists so a sketch can declare `TrialWeight pool[N];` at file
      scope and fill it after START, once the weights have arrived. A zero
      weight is never drawn, so an unfilled slot is inert rather than wrong --
      and generateTrials() falls back to equal weights if EVERY slot is zero,
      because a division by the total is the alternative. */
  TrialWeight() : type(NULL), weight(0) {}
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
 *  3. SERIAL PROTOCOL helpers (shared with the Ephymeris app)
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
 *  4. HARDWARE helpers (keyed off the shared pinout above)
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
 *  5. TASK PARAMETERS -- the whole START-command surface
 * ============================================================= */
/* Largest sliding bias window the anti-bias selector's ring buffer can hold. */
#define BEHAVIOR_MAX_BIAS_WINDOW 32

/*  Number of rows in the ramp table.

    GUARDED, so a generated `TaskPins.h` sets it -- a profile that ramps over
    three stages compiles three rows and sends fifteen fewer START tokens, and
    one that does not ramp at all compiles one. Five is the lab's historical
    schedule (a forgiving stage 0 plus four steps toward the full task) and is
    what a sketch with no generated header still gets.

    IT MUST MOVE WITH BOX_STAGE_KEY_LIST BELOW. The count sizes `stage[]`; the
    key list decides which rows the START parser can reach. A count of 5 with a
    key list of 3 leaves rows 3 and 4 unreachable but allocated -- harmless. The
    reverse silently writes past the end of the array. */
#ifndef NUM_STAGES
#define NUM_STAGES 5
#endif

/*  How many trial types a profile may declare.

    GUARDED for the same reason as NUM_STAGES: a generated header declares the
    profile's own count, and it must move with BOX_POOL_KEY_LIST below. Four is
    the historical shaping pool -- two go-right options and two go-left.

    ONE CAP, TWO READERS. It sizes `poolWeights[]`, so the weighted pool cannot
    address a type it has no weight for; and it sizes AntiBiasSelector's two
    side lists, so live selection cannot address one it never indexed. Splitting
    them into two constants would mean a table legal for one selection mode and
    silently truncated by the other. */
#ifndef BOX_MAX_TRIAL_TYPES
#define BOX_MAX_TRIAL_TYPES 4
#endif

/*  The trial count no session reaches, so a ramp row carrying it never engages.
    32767 rather than a rounder large number because `trials` is an int and an
    int is 16 bits on AVR -- 100000 wraps to -31072, a count every trial
    satisfies, which is the last row engaging from trial 0. */
#define STAGE_UNREACHABLE 32767

/*  One row of the ramp: the four holds/windows that a shaping schedule walks,
    and the completed-trial count at which this row takes over.

    Deliberately a plain aggregate -- no default member initialisers -- so that
    `StageStep{0, 10, 10, 10000, 8000}` stays legal under C++11, which is what
    the Arduino AVR core compiles with. TaskParams' constructor fills the array. */
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

    The in-class defaults are the FULL-TASK values, so a bare "START" with no
    tokens still reproduces exactly the legacy behavior. That path is only ever
    a hand-typed console session or an older host -- the app sends every field
    the profile declares.

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
  /*  Per-line open time; the open time IS the delivered volume. The initialiser
      names four because FL1-FL4 are four wire keys and this box has four lines
      -- a box generation with more would zero-fill the tail, and a 0 ms reward
      is a dry well that reports a correct trial. The assert below is what makes
      that a build failure instead. */
  int fluidPinTimes[NUM_FLUIDS] = {100, 100, 100, 100};

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
  int poolWeights[BOX_MAX_TRIAL_TYPES] = {1}; // pool mode only; ignored where selection is live
                                              // (the rest zero-fill, which is what
                                              // "present only the first type" means)

  /* --- adaptive anti-bias selection (ignored by shaping) --- */
  int biasWindow = 20;         // sliding window of recent expressed choices
  int maxConsecutiveSide = 10; // hard cap on consecutive identical correct sides
  float debiasStrength = 0.5f; // how hard to push against the rat's bias
  float pSideMin = 0.02f;      // clamp on P(correct side) -- never fully
  float pSideMax = 0.98f;      // deterministic, which would itself be a cue

  /* --- the ramp ---
     Filled by the constructor below rather than a brace initialiser, because
     NUM_STAGES is a generated constant now and a fixed five-row list would not
     track it. Row 0 is live from trial 0; every later row starts at the
     unreachable count, so a task that does not ramp never engages one. */
  StageStep stage[NUM_STAGES];

  /*  Fills `stage[]`, and exists so that no sketch can forget to.

      A brace initialiser cannot follow a generated NUM_STAGES, and a shorter
      literal list would leave the tail zero-filled -- `trials == 0` on the last
      row, which is that row engaging from trial 0 and the ramp appearing never
      to have advanced. This is the one construction that cannot get it wrong. */
  TaskParams()
  {
    for (int i = 0; i < NUM_STAGES; i++)
      stage[i] = StageStep{STAGE_UNREACHABLE, 500, 200, 2000, 4000};
    /*  Row 0's own `trials` is never read -- liveStage() scans down to i > 0 and
        falls through to 0 -- but it is set anyway so a printed table reads
        honestly and so nothing downstream has to know that. */
    stage[0].trials = 0;
  }

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

/*  See fluidPinTimes above: the four FL* wire keys and the four-element
    initialiser both assume this. A box generation that re-declares
    BOX_NUM_FLUIDS must extend both, and should fail here rather than water one
    well for 0 ms. */
static_assert(NUM_FLUIDS == 4,
              "fluidPinTimes and the FL1-FL4 wire keys both assume four fluid "
              "lines; extend TASK_PARAM_LIST and the initialiser together");

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

/*  Which pool slots and which ramp rows the START grammar can reach.

    GUARDED, and each must agree with its count above -- BOX_MAX_TRIAL_TYPES and
    NUM_STAGES. A key list SHORTER than its count leaves the tail unreachable
    from the wire, which is merely wasteful; a key list LONGER writes past the
    end of the array, which is not. A generated `TaskPins.h` emits both halves
    together, which is the only reason this is safe to make variable.

    The defaults are the historical four-slot pool and five-row ramp, so a
    sketch with no generated header parses exactly the line it always did. */
#ifndef BOX_POOL_KEY_LIST
#define BOX_POOL_KEY_LIST                   \
  P_INT("PW1", poolWeights[0])              \
  P_INT("PW2", poolWeights[1])              \
  P_INT("PW3", poolWeights[2])              \
  P_INT("PW4", poolWeights[3])
#endif

#ifndef BOX_STAGE_KEY_LIST
#define BOX_STAGE_KEY_LIST                  \
  P_STAGE(0) P_STAGE(1) P_STAGE(2) P_STAGE(3) P_STAGE(4)
#endif

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
  P_INT("BW", biasWindow)                   \
  P_INT("MCS", maxConsecutiveSide)          \
  P_FLOAT("DBS", debiasStrength)            \
  P_FLOAT("PMN", pSideMin)                  \
  P_FLOAT("PMX", pSideMax)                  \
  P_BOOL("LAZY", lazyEscalationEnabled)     \
  P_ULONG("SEED", trialSeed)                \
  BOX_POOL_KEY_LIST                         \
  BOX_STAGE_KEY_LIST

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
  for (int i = 0; i < BOX_MAX_TRIAL_TYPES; i++)
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
 *  6. SESSION POLICY (anti-bias selection, penalties, correction budgets)
 * ============================================================= */
/*  Adaptive anti-bias trial selection. Owns the sliding-window estimate of the
    rat's recent expressed side preference and the next-side draw that pushes
    AGAINST it, clamped so selection never collapses into a deterministic
    (cue-able) pattern, with a hard cap on same-side runs.

    IT SELECTS A SIDE, NOT A TRIAL TYPE. The bias estimate is over the animal's
    expressed left/right choices, so a side is the only thing it has an opinion
    about; having drawn one it picks UNIFORMLY among that side's types. With one
    type per side -- the shipped 2-odor task -- that draw has a single candidate
    and the behaviour is bit-for-bit what the two-pointer version did. With two
    odors meaning go-right, it presents them equally often while still
    de-biasing the side, which is the thing the animal can be biased about.

    Pin-agnostic: it speaks in `bool wentRight` / `presentedRight` and reads the
    trial table it was handed. A type's side is `correctWell == rightWell`, so
    nothing here knows a pin number.

    A NO-GO TYPE IS NEVER SELECTED. It has no correct side (`correctWell` is the
    sentinel), so it belongs to neither list and this class cannot present it —
    a withhold task uses the weighted pool instead. */
class AntiBiasSelector
{
public:
  /*  `types` is the profile's trial table and must outlive the selector; both
      are file-scope in a sketch, so this is a pointer rather than a copy. */
  AntiBiasSelector(const TrialType *types, int count,
                   int biasWindow = 20, float debiasStrength = 0.5f,
                   float pSideMin = 0.02f, float pSideMax = 0.98f,
                   int maxConsecutiveSide = 10)
      : _window(biasWindow < BEHAVIOR_MAX_BIAS_WINDOW ? biasWindow : BEHAVIOR_MAX_BIAS_WINDOW),
        _debias(debiasStrength), _pMin(pSideMin), _pMax(pSideMax),
        _maxRun(maxConsecutiveSide)
  {
    bind(types, count);
  }

  /*  Split the trial table into the two side lists, once.

      Done here rather than scanned per selection because the table is fixed for
      the run and `selectNext()` is on the trial path. `_nRight`/`_nLeft` being
      zero is not an error to trap on a microcontroller -- `selectNext()` falls
      back to the other side, and to type 0 if the table has no go trials at
      all, so a mis-declared profile runs one condition rather than hanging or
      dereferencing nothing. */
  void bind(const TrialType *types, int count)
  {
    _types = types;
    _nRight = _nLeft = 0;
    for (int i = 0; i < count && i < BOX_MAX_TRIAL_TYPES; i++)
    {
      if (!types[i].isGo || types[i].correctWell == SENTINEL)
        continue;
      if (types[i].correctWell == rightWell)
        _right[_nRight++] = i;
      else
        _left[_nLeft++] = i;
    }
  }

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

    return pickFrom(chooseRight);
  }

private:
  /*  One type from the chosen side, uniformly.

      Falls through to the other side when the chosen one is empty rather than
      returning nothing: a table with go-right types only is a legal one-sided
      task, and it should run rather than fault. The final `&_types[0]` is only
      reachable if the table declares no go trials at all, which the app refuses
      to generate -- it exists so this returns a valid pointer on every path. */
  const TrialType *pickFrom(bool wantRight) const
  {
    const int *side = wantRight ? _right : _left;
    int n = wantRight ? _nRight : _nLeft;
    if (n == 0)
    {
      side = wantRight ? _left : _right;
      n = wantRight ? _nLeft : _nRight;
    }
    if (n == 0)
      return &_types[0];
    return &_types[side[n == 1 ? 0 : (int)random(0, n)]];
  }

  const TrialType *_types = NULL;
  int _right[BOX_MAX_TRIAL_TYPES] = {0};
  int _left[BOX_MAX_TRIAL_TYPES] = {0};
  int _nRight = 0, _nLeft = 0;
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
 *  7. TRIAL RUNNER -- one loop, shared by every behavior sketch
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

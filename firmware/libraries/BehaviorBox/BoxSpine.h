/*
  BoxSpine.h
  ==========
  THE PHASE INTERPRETER'S HARDWARE LAYER: the one runner of every phase-spine
  task (0003-phase-spine-task-model.md#interpreter-and-firmware).

  BoxInterp.h's pure core walks a state table one millisecond tick at a time.
  This header is the thin layer the core's header asks for around it: it reads
  and debounces the inputs, steps the core on every tick, drives the outputs,
  and strobes what the core reports. What the task IS arrives as data in a
  generated TaskSpine.h -- the state table, which pin and which strobe codes
  each channel bit is, and the parameter keys -- so no firmware is written per
  task. A spine task's sketch is the whole of:

      #include "TaskPins.h"   // GENERATED: this rig's pins and every BF_ code
      #include "TaskSpine.h"  // GENERATED: the table, the channels, the parameters
      #include <BehaviorBox.h>
      #include <BoxInterp.h>
      #include <BoxSpine.h>
      void setup() { box_spine::setup(); }
      void loop() { box_spine::loop(); }


  THE HANDSHAKE (docs/TASKS.md#confirming-the-parameters), BehaviorBox.h's own
  pieces over a block of uint32_t parameter slots instead of TaskParams:
    INTERP=<INTERP_VERSION>, FREE_RAM=<n>, READY
    BEGIN                 back to the table's defaults; the audit cleared
    SET <KEY>=<v> ...     each answered CLAMPED <KEY> (a value not held exactly as
                          written: junk, a sign, outside the slot's [min, max], or
                          a pair's high end below its low end, SPINE_PAIRS: a drawn
                          N, a block's drawn N, a criterion's k and n), then
                          PARAMS <n> <crc32>, the running total
    START SEED=<n>        the core's RNG seeded with it, echoed as SEED <n>


  THE STREAM (0003-phase-spine-task-model.md#the-strobe-stream). Only what the
  board observed and what it did, each strobe stamped with the TICK, in the
  core's order within a tick:
    START_SESSION, watched inputs that rose (their channel's enter code), that
    fell (exit), BLOCK_START (a block's first trial), TRIAL_START, outputs
    driven LOW (off), driven HIGH (on).
  An input edge no state is watching is never strobed: the core ignores it, so
  replay needs only what was strobed.


  DRIVEN OUTPUTS (docs/TASKS.md#driven-outputs). An output bit the table drives
  HIGH is a level line, unless TaskSpine.h's SPINE_DRIVES names it:
    PWM    analogWrite(pin, duty), the duty its parameter slot holds
    TONE   tone(pin, hz); off is noTone(pin)
    TRAIN  a pulse train from parameter slots hz, width, ms: BoxInterp.h's
           interp_train_high() on every tick, the pin written only when its
           level changes. A train with a non-zero ms RUNS OUT that many ticks
           after it started: it goes LOW and strobes its off code (TRAIN_OFF)
           at that tick, among the tick's offs, though the core still holds
           the bit HIGH. A train strobes nothing else: never a pulse's edge.
  So the board's LIVE outputs are the core's less every train that ran out. The
  end rule's "every output still HIGH" means the live ones, and a train that
  ran out is not turned off twice. A task with no driven output compiles none
  of this (SPINE_NUM_DRIVES 0).
  A train whose width is not shorter than its period, 1000 / hz, would hold
  its line HIGH. Each value alone is in range, so the pair is judged over the
  whole block after every SET line (CLAMPED <width key>), and a hand-typed
  START that leaves one is answered the same way and starts nothing.


  THE SESSION END RULE, which replay reproduces:
    The session ends at the tick that would start trial NT+1, where NT is
    parameter slot SPINE_TRIALS_SLOT (the session's trial cap, when the task
    has one), at the trial start where the last block ends (the core reports
    INTERP_ACT_DONE), or at the first trial start after a STOP line or after a
    LAST-TRIAL state was entered (the core reports INTERP_ACT_LAST_TRIAL: a
    Counter's time limit that ends the session). At that tick the board strobes
    the tick's watched input edges, then the off code of every output still
    HIGH, then END_SESSION, and nothing else: no BLOCK_START or TRIAL_START,
    and the new trial's outputs are not driven.
  So STOP never cuts a trial short, as with the trial runner.


  TICKS. One tick per millisecond of millis(). AVR millis() skips a value
  roughly every 42 ms; each skipped value is stepped too, with no edges, as
  BoxInterp.h's tick rules require. Inputs are read once per loop() pass and
  their edges land on the latest tick. Nothing here calls delay() once the
  session runs; the strobe's sync pulse waits a few hundred microseconds, the
  bounded lag RECORDING.md#the-sync-line describes.
*/

#ifndef BOX_SPINE_H
#define BOX_SPINE_H

#include <BehaviorBox.h>
#include <BoxInterp.h>

#ifndef SPINE_STATES
#error "BoxSpine.h runs a generated TaskSpine.h, and none was included first. Build the folder Ephymeris generates for a spine task."
#endif
#if SPINE_INTERP != INTERP_VERSION
#error "TaskSpine.h was lowered for another table format than this BoxInterp.h runs: save the task again."
#endif
#if SPINE_NUM_INPUTS > 32 || SPINE_NUM_OUTPUTS > 32
#error "a state table speaks of at most 32 inputs and 32 outputs"
#endif
#ifndef SPINE_NUM_DRIVES
#error "TaskSpine.h names no SPINE_NUM_DRIVES: save the task again."
#endif
#if !defined(SPINE_RATIOS) || !defined(SPINE_COUNT_MIN)
#error "TaskSpine.h names no counter (SPINE_COUNT_MIN, SPINE_RATIOS): save the task again."
#endif
#if !defined(SPINE_NUM_BLOCKS) || !defined(SPINE_TRIALS_SLOT) || !defined(SPINE_NUM_PAIRS) \
    || !defined(SPINE_BLOCK_SKIPPED) || !defined(SPINE_BLOCK_HITS)
#error "TaskSpine.h names no blocks (SPINE_NUM_BLOCKS, SPINE_TRIALS_SLOT, SPINE_NUM_PAIRS, SPINE_BLOCK_SKIPPED, SPINE_BLOCK_HITS): save the task again."
#endif

/* The generator holds a task's RAM to a budget at save, counting these rows and
   arrays at their AVR sizes (taskdef/spine.py's PARAM_BYTES, INPUT_BYTES,
   OUTPUT_BYTES, RATIO_BYTES for kRatios and PAIR_BYTES for kPairs below,
   DRIVE_BYTES, DRIVE_RUN_BYTES and TONE_RAM_BYTES, and lowering.py's row
   sizes; docs/TASKS.md#spine-diagnostics). test_spine_task.py holds the
   count to a Mega build: change a struct or array here and it fails. */

/* SpineDrive.kind, which TaskSpine.h's SPINE_DRIVES names. */
#define SPINE_DRIVE_PWM 1
#define SPINE_DRIVE_TONE 2
#define SPINE_DRIVE_TRAIN 3

/* One driven output bit: which bit, how it is driven, and its first parameter
   slot (a train's hz; its width and ms are the next two). */
struct SpineDrive
{
  uint8_t output;
  uint8_t kind;
  uint8_t param;
};

/* One input bit: its pin, which level is ACTIVE, and the codes of its edges. */
struct SpineInput
{
  uint8_t pin;
  uint8_t activeHigh;  // 0: active LOW (a broken IR beam), pulled up
  uint16_t debounceMs; // the level must hold this long before it counts
  int riseCode;        // became active: the channel's `enter` code
  int fallCode;        // became inactive: its `exit` code
};

/* One output bit: its pin and the codes of its edges. */
struct SpineOutput
{
  uint8_t pin;
  int onCode;
  int offCode;
};

/* One parameter slot: its wire key, the default it holds before any SET, and
   the range the board holds it to. */
struct SpineParam
{
  const char *key;
  uint32_t value;
  uint32_t min;
  uint32_t max;
};

/*  The session layer's pure part: the core, and the end rule above. No pin,
    clock or serial port, so the host test drives it like the core. */
struct SpineRun
{
  InterpCore core;
  uint32_t start;  // the session's first tick; strobes are stamped relative to it
  uint32_t trials; // trials started
  bool last;       // a last-trial state was entered: end at the next trial start
  bool ended;
};

struct SpineTick
{
  InterpActions actions;
  bool ends;       // the session ends at this tick (the end rule)
  uint32_t endOff; // then: the outputs that were HIGH, to drive LOW
  uint32_t off;    // otherwise: the outputs driven LOW and HIGH this tick, the
  uint32_t on;     // core's, and any train that ran out (spine_drives_step)
};

/*  The driven outputs' pure part: which outputs are live, and when each
    train started. No pin; the host test drives it like the rest. */
struct SpineDriveRun
{
  const SpineDrive *drives;
  uint8_t count;
  uint32_t *since; // per drive: the tick its train started
  uint32_t live;   // outputs HIGH on the board
};

/*  Whether a train of this rate and width is pulses at all: a width at least the
    period, 1000 / hz, holds the line HIGH (BoxInterp.h, PULSE TRAINS). The
    generator refuses one at save (SPN112); the board refuses one a SET makes. */
inline bool spine_train_fits(uint32_t hz, uint32_t width)
{
  return hz >= 1 && width >= 1 && width < 1000UL / hz;
}

inline void spine__trains_started(SpineDriveRun &d, uint32_t on, uint32_t now)
{
  for (uint8_t i = 0; i < d.count; i++)
    if (d.drives[i].kind == SPINE_DRIVE_TRAIN && (on & ((uint32_t)1 << d.drives[i].output)))
      d.since[i] = now;
}

/*  The session's first tick: its outputs are the live ones. */
inline void spine_drives_begin(SpineDriveRun &d, const InterpActions &a, uint32_t now)
{
  d.live = a.on;
  spine__trains_started(d, a.on, now);
}

/*  Every tick after: a live train whose ms has run out goes LOW, and the core's
    off for a train that already did is dropped. At the end, every live output
    goes LOW. */
inline void spine_drives_step(SpineDriveRun &d, const uint32_t *params, SpineTick &t, uint32_t now)
{
  uint32_t ranOut = 0;
  for (uint8_t i = 0; i < d.count; i++)
  {
    const SpineDrive &s = d.drives[i];
    uint32_t bit = (uint32_t)1 << s.output;
    uint32_t ms = s.kind == SPINE_DRIVE_TRAIN ? params[s.param + 2] : 0;
    if ((d.live & bit) && ms != 0 && (uint32_t)(now - d.since[i]) >= ms)
      ranOut |= bit;
  }
  if (t.ends)
  {
    t.endOff = d.live;
    d.live = 0;
    return;
  }
  t.off = (t.off | ranOut) & d.live;
  d.live = (d.live & ~t.off) | t.on;
  spine__trains_started(d, t.on, now);
}

inline InterpActions spine_begin(SpineRun &r, const InterpTable *table, const uint32_t *params,
                                 uint32_t seed, uint32_t now)
{
  r.start = now;
  r.last = false;
  r.ended = false;
  InterpActions a = interp_begin(&r.core, table, params, seed, now);
  r.trials = (a.flags & INTERP_ACT_TRIAL_START) ? 1 : 0;
  return a;
}

/*  One tick after the first. `maxTrials` is NT; `stop` whether a STOP has arrived. */
inline SpineTick spine_step(SpineRun &r, InterpEdges edges, uint32_t now, uint32_t maxTrials, bool stop)
{
  SpineTick t;
  uint32_t was = r.core.outputs;
  t.actions = interp_step(&r.core, edges, now);
  t.ends = false;
  t.endOff = 0;
  t.off = t.actions.off;
  t.on = t.actions.on;
  if (t.actions.flags & INTERP_ACT_LAST_TRIAL)
    r.last = true;
  if (t.actions.flags & INTERP_ACT_TRIAL_START)
  {
    if (stop || r.last || r.trials >= maxTrials || (t.actions.flags & INTERP_ACT_DONE))
    {
      t.ends = true;
      t.endOff = was;
      r.ended = true;
    }
    else
      r.trials++;
  }
  return t;
}

namespace box_spine
{

static const InterpStateRow kStates[] = SPINE_STATES;
static const InterpEdgeRow kEdges[] = SPINE_EDGES;
static const SpineInput kInputs[] = SPINE_INPUTS;
static const SpineOutput kOutputs[] = SPINE_OUTPUTS;
static const SpineParam kParams[] = SPINE_PARAMS;
static const uint16_t kRatios[] = SPINE_RATIOS;
static const InterpCounter kCounter = {kRatios, SPINE_NUM_RATIOS, SPINE_COUNT_MIN, SPINE_COUNT_MAX};
static const InterpBlock kBlockRows[] = SPINE_BLOCKS;
#if SPINE_NUM_ENTRIES > 0
static const InterpEntry kEntries[] = SPINE_ENTRIES;
#define BOX_SPINE_ENTRIES kEntries
#else
#define BOX_SPINE_ENTRIES NULL
#endif
#if SPINE_NUM_OVERRIDES > 0
static const InterpOverride kOverrides[] = SPINE_OVERRIDES;
#define BOX_SPINE_OVERRIDES kOverrides
#else
#define BOX_SPINE_OVERRIDES NULL
#endif
#if SPINE_NUM_PAIRS > 0
/* {low, high}: parameter slots held in order (takeTokens). */
static const uint8_t kPairs[][2] = SPINE_PAIRS;
#endif
static const InterpBlocks kBlocks = {kBlockRows, BOX_SPINE_ENTRIES, BOX_SPINE_OVERRIDES,
                                     SPINE_NUM_BLOCKS, SPINE_NUM_ENTRIES, SPINE_NUM_OVERRIDES,
                                     SPINE_BLOCK_SKIPPED, SPINE_BLOCK_HITS};
static const InterpTable kTable = {kStates, kEdges, &kCounter, &kBlocks};

/* The run's parameter block, filled from the table's defaults and the SET lines. */
static uint32_t params[SPINE_NUM_PARAMS];

static SpineRun run;
static bool level[SPINE_NUM_INPUTS > 0 ? SPINE_NUM_INPUTS : 1];  // debounced: active?
static bool raw[SPINE_NUM_INPUTS > 0 ? SPINE_NUM_INPUTS : 1];    // as last read
static uint32_t rawSince[SPINE_NUM_INPUTS > 0 ? SPINE_NUM_INPUTS : 1];
static uint32_t lastTick = 0;
static bool stopRequested = false;
static bool done = true;

/*  The session's trial cap: NT's slot, or none, when the blocks alone end it. */
inline uint32_t maxTrials()
{
#if SPINE_TRIALS_SLOT != INTERP_NONE
  return params[SPINE_TRIALS_SLOT];
#else
  return 0xFFFFFFFFUL;
#endif
}

#if SPINE_NUM_DRIVES > 0
static const SpineDrive kDrives[] = SPINE_DRIVES;
static uint32_t driveSince[SPINE_NUM_DRIVES];
static bool driveHigh[SPINE_NUM_DRIVES]; // a train's pin, as last written
static SpineDriveRun drives = {kDrives, SPINE_NUM_DRIVES, driveSince, 0};

inline int driveOf(int output)
{
  for (int i = 0; i < SPINE_NUM_DRIVES; i++)
    if (kDrives[i].output == output) return i;
  return -1;
}

inline bool trainHigh(int i, uint32_t now)
{
  return interp_train_high((uint32_t)(now - driveSince[i]), params[kDrives[i].param],
                           params[kDrives[i].param + 1]);
}
#endif

/*  Drive output bit j LOW or HIGH, as its drive says (DRIVEN OUTPUTS). */
inline void drive(int j, bool high, uint32_t now)
{
  uint8_t pin = kOutputs[j].pin;
#if SPINE_NUM_DRIVES > 0
  int i = driveOf(j);
  uint8_t kind = i < 0 ? 0 : kDrives[i].kind;
#if SPINE_HAS_TONE
  if (kind == SPINE_DRIVE_TONE)
  {
    if (high) tone(pin, (unsigned int)params[kDrives[i].param]);
    else noTone(pin);
    return;
  }
#endif
  if (high && kind == SPINE_DRIVE_PWM)
  {
    analogWrite(pin, (int)params[kDrives[i].param]);
    return;
  }
  if (kind == SPINE_DRIVE_TRAIN)
  {
    driveHigh[i] = high && trainHigh(i, now);
    digitalWrite(pin, driveHigh[i] ? HIGH : LOW);
    return;
  }
#else
  (void)now;
#endif
  digitalWrite(pin, high ? HIGH : LOW);
}

/*  Every live train's pin at tick `now`, written only when its level changes. */
inline void stepTrains(uint32_t now)
{
#if SPINE_NUM_DRIVES > 0
  for (int i = 0; i < SPINE_NUM_DRIVES; i++)
  {
    if (kDrives[i].kind != SPINE_DRIVE_TRAIN || !(drives.live & ((uint32_t)1 << kDrives[i].output)))
      continue;
    bool high = trainHigh(i, now);
    if (high != driveHigh[i])
    {
      digitalWrite(kOutputs[kDrives[i].output].pin, high ? HIGH : LOW);
      driveHigh[i] = high;
    }
  }
#else
  (void)now;
#endif
}

inline void defaults()
{
  for (int s = 0; s < SPINE_NUM_PARAMS; s++)
    params[s] = kParams[s].value;
}

/*  Take one `SET`/`START` line's tokens into params. With an audit, count and
    hash each one as written and note whether it was held exactly. */
inline void takeTokens(char *line, ParamAudit *audit)
{
  for (char *tok = strtok(line, " "); tok != NULL; tok = strtok(NULL, " "))
  {
    char *eq = strchr(tok, '=');
    if (eq == NULL)
      continue; // the verb
    *eq = '\0';
    const char *k = tok;
    const char *v = eq + 1;
    for (int s = 0; s < SPINE_NUM_PARAMS; s++)
    {
      if (strcmp(k, kParams[s].key) != 0)
        continue;
      bool exact;
      unsigned long x = parseUlongField(v, exact);
      if (x < kParams[s].min) { x = kParams[s].min; exact = false; }
      if (x > kParams[s].max) { x = kParams[s].max; exact = false; }
#if SPINE_NUM_PAIRS > 0
      // A pair's high end below its low end: a drawn N fixed at its low end (VR
      // run as FR), or a criterion that can never be met. The host sends the low
      // end first (slot order), so the pair is judged when the high end arrives,
      // and held as a range, CLAMPED.
      for (int p = 0; p < SPINE_NUM_PAIRS; p++)
        if (s == kPairs[p][1] && x < params[kPairs[p][0]]) { x = params[kPairs[p][0]]; exact = false; }
#endif
      params[s] = (uint32_t)x;
      if (audit)
      {
        if (exact) audit->noteExact(kParams[s].key);
        else audit->noteInexact(kParams[s].key);
        auditAccept(*audit, k, v);
      }
      break;
    }
  }
}

/*  Answer one SET line: CLAMPED for each value not held as written, then the
    running PARAMS. As applySetLine() does for the trial runner. */
/*  CLAMPED <width key> for every train whose width, as the block stands, is not
    shorter than its period: each value in its own range, the pair would hold
    the line HIGH. Judged over the whole block after every line, as the host
    reads only the last line's answer. True when any was. */
inline bool clampTrains()
{
  bool any = false;
#if SPINE_NUM_DRIVES > 0
  char buf[32];
  for (int i = 0; i < SPINE_NUM_DRIVES; i++)
  {
    uint8_t p = kDrives[i].param;
    if (kDrives[i].kind != SPINE_DRIVE_TRAIN || spine_train_fits(params[p], params[p + 1]))
      continue;
    snprintf(buf, sizeof(buf), "CLAMPED %s", kParams[p + 1].key);
    Serial.println(buf);
    any = true;
  }
#endif
  return any;
}

inline void answerSet(char *line, ParamAudit &audit)
{
  takeTokens(line, &audit);
  char buf[32];
  for (int i = 0; i < audit.inexactCount; i++)
  {
    snprintf(buf, sizeof(buf), "CLAMPED %s", audit.inexact[i]);
    Serial.println(buf);
  }
  if (audit.inexactLost)
    Serial.println("CLAMPED *");
  clampTrains();
  snprintf(buf, sizeof(buf), "PARAMS %d %lu", audit.accepted, (unsigned long)audit.finalCrc());
  Serial.println(buf);
}

/*  Block until START, answering BEGIN and SET. Returns the seed the run uses:
    the host's SEED=<n>, else micros() for a hand-typed START, folded into
    avr-libc random()'s state space [1, 2^31 - 2] as beginSessionRng() does. */
inline uint32_t awaitStart()
{
  char cmd[SET_LINE_MAX];
  ParamAudit audit;
  unsigned long seed = 0;
  defaults();
  while (true)
  {
    if (!readLineInto(cmd, sizeof(cmd)))
      continue;
    if (lineIsCommand(cmd, "BEGIN"))
    {
      defaults();
      audit = ParamAudit();
    }
    else if (lineIsCommand(cmd, "SET"))
      answerSet(cmd, audit);
    else if (lineIsCommand(cmd, "START"))
    {
      // START may carry SEED=<n> and, typed by hand, parameters of its own. SEED
      // is no parameter key, so takeTokens() passes over it. A train they leave
      // not fitting is refused here: no run starts on it.
      const char *at = strstr(cmd, "SEED=");
      seed = at != NULL && (at == cmd || at[-1] == ' ') ? strtoul(at + 5, NULL, 10) : 0;
      takeTokens(cmd, NULL);
      if (!clampTrains())
        break;
    }
  }
  if (seed == 0)
    seed = micros();
  seed %= 2147483647UL;
  if (seed == 0)
    seed = 1UL;
  char buf[24];
  snprintf(buf, sizeof(buf), "SEED\t%lu", seed);
  Serial.println(buf);
  return (uint32_t)seed;
}

inline bool readActive(const SpineInput &in)
{
  int v = digitalRead(in.pin);
  return in.activeHigh ? v == HIGH : v == LOW;
}

/*  Read every input once and debounce it at tick `now`: an edge is the
    debounced level changing, after the raw level has held debounceMs. */
inline InterpEdges sample(uint32_t now)
{
  InterpEdges e = {0, 0};
  for (int i = 0; i < SPINE_NUM_INPUTS; i++)
  {
    bool r = readActive(kInputs[i]);
    if (r != raw[i])
    {
      raw[i] = r;
      rawSince[i] = now;
    }
    if (raw[i] != level[i] && (uint32_t)(now - rawSince[i]) >= kInputs[i].debounceMs)
    {
      level[i] = raw[i];
      if (level[i]) e.rose |= (uint32_t)1 << i;
      else e.fell |= (uint32_t)1 << i;
    }
  }
  return e;
}

/*  Drive and strobe one tick's actions, in the core's order (THE STREAM). */
inline void emitTick(const SpineTick &t, uint32_t now)
{
  const InterpActions &a = t.actions;
  bool ends = t.ends;
  unsigned long ts = (unsigned long)(uint32_t)(now - run.start);
  uint32_t off = ends ? t.endOff : t.off;
  uint32_t on = ends ? 0 : t.on;
  // The pins first, so the physical edge is as close to its tick as it can be.
  // Every off before any on: a driven slot's rows are two bits on one pin.
  for (int j = 0; j < SPINE_NUM_OUTPUTS; j++)
    if (off & ((uint32_t)1 << j)) drive(j, false, now);
  for (int j = 0; j < SPINE_NUM_OUTPUTS; j++)
    if (on & ((uint32_t)1 << j)) drive(j, true, now);
  if (a.flags & INTERP_ACT_SESSION_START) emitStrobeAt(BF_START_SESSION, ts);
  for (int i = 0; i < SPINE_NUM_INPUTS; i++)
    if (a.rose & ((uint32_t)1 << i)) emitStrobeAt(kInputs[i].riseCode, ts);
  for (int i = 0; i < SPINE_NUM_INPUTS; i++)
    if (a.fell & ((uint32_t)1 << i)) emitStrobeAt(kInputs[i].fallCode, ts);
  if (!ends && (a.flags & INTERP_ACT_BLOCK_START)) emitStrobeAt(BF_BLOCK_START, ts);
  if (!ends && (a.flags & INTERP_ACT_TRIAL_START)) emitStrobeAt(BF_TRIAL_START, ts);
  for (int j = 0; j < SPINE_NUM_OUTPUTS; j++)
    if (off & ((uint32_t)1 << j)) emitStrobeAt(kOutputs[j].offCode, ts);
  for (int j = 0; j < SPINE_NUM_OUTPUTS; j++)
    if (on & ((uint32_t)1 << j)) emitStrobeAt(kOutputs[j].onCode, ts);
  if (ends) emitStrobeAt(BF_END_SESSION, ts);
}

inline void setup()
{
  initBoxHardware(); // every output of the box as built LOW, its beams pulled up
  for (int i = 0; i < SPINE_NUM_INPUTS; i++)
    pinMode(kInputs[i].pin, kInputs[i].activeHigh ? INPUT : INPUT_PULLUP);
  for (int j = 0; j < SPINE_NUM_OUTPUTS; j++)
  {
    pinMode(kOutputs[j].pin, OUTPUT);
    digitalWrite(kOutputs[j].pin, LOW);
  }
  Serial.begin(BOX_BAUD_RATE);
  delay(50); // let the post-reset serial settle
  announceReadyAs(INTERP_VERSION);
  uint32_t seed = awaitStart();

  uint32_t now = millis();
  for (int i = 0; i < SPINE_NUM_INPUTS; i++)
  {
    // The level at the session's start is where it stands: no edge for it.
    level[i] = raw[i] = readActive(kInputs[i]);
    rawSince[i] = now;
  }
  stopRequested = false;
  done = false;
  lastTick = now;
  SpineTick first;
  first.actions = spine_begin(run, &kTable, params, seed, now);
  first.ends = false;
  first.endOff = 0;
  first.off = first.actions.off;
  first.on = first.actions.on;
#if SPINE_NUM_DRIVES > 0
  spine_drives_begin(drives, first.actions, now);
#endif
  emitTick(first, now);
}

inline void loop()
{
  if (done)
    return;
  if (checkForStop())
    stopRequested = true;
  uint32_t now = millis();
  InterpEdges in = sample(now);
  while (lastTick != now)
  {
    ++lastTick;
    InterpEdges none = {0, 0};
    SpineTick t = spine_step(run, lastTick == now ? in : none, lastTick, maxTrials(), stopRequested);
#if SPINE_NUM_DRIVES > 0
    spine_drives_step(drives, params, t, lastTick);
#endif
    if (t.ends || !interp_idle(&t.actions) || t.off != 0 || t.on != 0)
      emitTick(t, lastTick);
    if (t.ends)
    {
      shutdownHardware();
      done = true;
      return;
    }
    stepTrains(lastTick);
  }
}

} // namespace box_spine

#endif // BOX_SPINE_H

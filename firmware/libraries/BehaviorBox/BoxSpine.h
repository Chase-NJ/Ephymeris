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
                          written: junk, a sign, outside the slot's [min, max]),
                          then PARAMS <n> <crc32>, the running total
    START SEED=<n>        the core's RNG seeded with it, echoed as SEED <n>


  THE STREAM (0003-phase-spine-task-model.md#the-strobe-stream). Only what the
  board observed and what it did, each strobe stamped with the TICK, in the
  core's order within a tick:
    START_SESSION, watched inputs that rose (their channel's enter code), that
    fell (exit), TRIAL_START, outputs driven LOW (off), driven HIGH (on).
  An input edge no state is watching is never strobed: the core ignores it, so
  replay needs only what was strobed.


  THE SESSION END RULE, which replay reproduces:
    The session ends at the tick that would start trial NT+1, where NT is
    parameter slot 0 (the block's trial count), or at the first trial start
    after a STOP line. At that tick the board strobes the tick's watched input
    edges, then the off code of every output still HIGH, then END_SESSION, and
    nothing else: no TRIAL_START, and the new trial's outputs are not driven.
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
#if SPINE_NUM_PARAMS < 1
#error "a spine task's parameter slot 0 is its block's trial count"
#endif

/* The generator holds a task's RAM to a budget at save, counting these rows and
   arrays at their AVR sizes (taskdef/spine.py's PARAM_BYTES, INPUT_BYTES and
   OUTPUT_BYTES; docs/TASKS.md#spine-diagnostics). test_spine_task.py holds the
   count to a Mega build: change a struct or array here and it fails. */

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
  bool ended;
};

struct SpineTick
{
  InterpActions actions;
  bool ends;       // the session ends at this tick (the end rule)
  uint32_t endOff; // then: the outputs that were HIGH, to drive LOW
};

inline InterpActions spine_begin(SpineRun &r, const InterpTable *table, const uint32_t *params,
                                 uint32_t seed, uint32_t now)
{
  r.start = now;
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
  if (t.actions.flags & INTERP_ACT_TRIAL_START)
  {
    if (stop || r.trials >= maxTrials)
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
static const InterpTable kTable = {kStates, kEdges};

/* The run's parameter block, filled from the table's defaults and the SET lines. */
static uint32_t params[SPINE_NUM_PARAMS];

static SpineRun run;
static bool level[SPINE_NUM_INPUTS > 0 ? SPINE_NUM_INPUTS : 1];  // debounced: active?
static bool raw[SPINE_NUM_INPUTS > 0 ? SPINE_NUM_INPUTS : 1];    // as last read
static uint32_t rawSince[SPINE_NUM_INPUTS > 0 ? SPINE_NUM_INPUTS : 1];
static uint32_t lastTick = 0;
static bool stopRequested = false;
static bool done = true;

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
      break;
  }
  // START may carry SEED=<n> and, typed by hand, parameters of its own. SEED is
  // no parameter key, so takeTokens() passes over it.
  unsigned long seed = 0;
  const char *at = strstr(cmd, "SEED=");
  if (at != NULL && (at == cmd || at[-1] == ' '))
    seed = strtoul(at + 5, NULL, 10);
  takeTokens(cmd, NULL);
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
inline void emitTick(const InterpActions &a, uint32_t now, bool ends, uint32_t endOff)
{
  unsigned long ts = (unsigned long)(uint32_t)(now - run.start);
  uint32_t off = ends ? endOff : a.off;
  uint32_t on = ends ? 0 : a.on;
  // The pins first, so the physical edge is as close to its tick as it can be.
  for (int j = 0; j < SPINE_NUM_OUTPUTS; j++)
  {
    if (off & ((uint32_t)1 << j)) digitalWrite(kOutputs[j].pin, LOW);
    if (on & ((uint32_t)1 << j)) digitalWrite(kOutputs[j].pin, HIGH);
  }
  if (a.flags & INTERP_ACT_SESSION_START) emitStrobeAt(BF_START_SESSION, ts);
  for (int i = 0; i < SPINE_NUM_INPUTS; i++)
    if (a.rose & ((uint32_t)1 << i)) emitStrobeAt(kInputs[i].riseCode, ts);
  for (int i = 0; i < SPINE_NUM_INPUTS; i++)
    if (a.fell & ((uint32_t)1 << i)) emitStrobeAt(kInputs[i].fallCode, ts);
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
  emitTick(spine_begin(run, &kTable, params, seed, now), now, false, 0);
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
    SpineTick t = spine_step(run, lastTick == now ? in : none, lastTick, params[0], stopRequested);
    if (t.ends || !interp_idle(&t.actions))
      emitTick(t.actions, lastTick, t.ends, t.endOff);
    if (t.ends)
    {
      shutdownHardware();
      done = true;
      return;
    }
  }
}

} // namespace box_spine

#endif // BOX_SPINE_H

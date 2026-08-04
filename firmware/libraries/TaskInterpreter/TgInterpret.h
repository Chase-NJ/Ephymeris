#ifndef TG_INTERPRET_H
#define TG_INTERPRET_H

/* ============================================================= *
 *  The fixed interpreter: walks one trial of a compiled table.
 *
 *  This is the whole of what replaces runTrial(). It knows the six primitives and
 *  nothing about any task -- no odors, no wells, no shaping schedule. Everything
 *  task-specific arrives in the table.
 *
 *  THE INVARIANT LIVES IN tgEnterNode(). Every strobe in the stream is emitted by
 *  exactly one call to it, so which edge fired is always recoverable from which
 *  strobe appeared, and every timestamp is a state-entry time. NOTHING ELSE HERE
 *  MAY CALL emitStrobe(). A paired emission is two nodes, the second with a zero
 *  duration -- measured on hardware at 0 ms skew, so it costs nothing.
 *
 *  NO RUNTIME STAGE COUNTER. The sampling unroll is static, so which stage a node
 *  presents is carried in its binding selector. A counter would be state the graph
 *  already encodes, and the only thing it could add is a way to drift.
 *
 *  No dynamic allocation and no virtual dispatch, per the Phase 0 constraint.
 * ============================================================= */

#include <BehaviorBox.h> // pins, emitStrobe, verifySensor, TaskParams, TrialClock
#include "TaskLimits.h"
#include "TaskTable.h"

/*  A table the interpreter can walk. Fixed-size storage, so the footprint is a
    guarantee rather than a hope: a box cannot run out of memory partway through a
    session because one spec was larger than the last.

    THIS IS THE ONLY TABLE SHAPE. Phase 0 left a second one -- a `TaskTable`
    skeleton in TaskInterpreter.h -- and by Phase 3 the two had diverged: the
    skeleton had no ports, stimuli or watch arrays, and this one had no stage
    schedule. An upload path written against the wrong one would have filled a
    struct nothing walks, which is the same class of failure as the mirrored
    constants this project keeps finding. The skeleton is gone. */
struct TgTable
{
  TgNode nodes[TG_MAX_STATES];
  TgEdge edges[TG_MAX_EDGES];
  uint16_t timing[TG_MAX_TIMING];
  TgAction actions[TG_MAX_ACTIONS];
  TgTrialType trialTypes[TG_MAX_TRIAL_TYPES];
  TgPort ports[TG_MAX_PORTS];
  TgStimulus stimuli[TG_MAX_STIMULI];

  /*  The stage ramp: rows addressed by completed-trial count, each rewriting some
      number of timing entries. Generalises applyStage() (BehaviorBox.h:567-574)
      from four fixed fields to N addressed by index.

      ON-BOARD, deliberately. The host could rewrite the timing vector between
      trials instead, but that puts a serial round-trip -- which can fail, with an
      animal in the box -- inside the trial loop for something the firmware already
      does locally today. */
  TgStageRow stageRows[TG_MAX_STAGE_ROWS];
  TgTimingSet timingSets[TG_MAX_TIMING_SETS];

  /*  Worst-case dwell per node, in ms, computed by the compiler. Zero means the
      compiler could not bound it -- sampling release and consumption, which wait
      on the subject rather than on a clock -- and the watchdog falls back to its
      session-wide ceiling there. A parallel array rather than a TgNode field
      because TgNode is exactly 8 bytes and the RAM budget assumes it stays that
      way. */
  uint16_t maxDwell[TG_MAX_STATES];

  /*  Watch-mask bit -> pin, and bit -> port index. The mask indexes WATCHABLE
      channels, so this is what turns a set bit back into something readable.
      A bit whose port is TG_NO_TARGET is the engagement channel, which is not a
      response port and has no TgPort row. */
  uint8_t watchPin[TG_MAX_WATCH];
  uint8_t watchPort[TG_MAX_WATCH];

  /*  Provenance, carried from the upload and echoed so a session is exactly
      reconstructable (docs/protocol-negotiation.md).

      THE POSITION IS LOAD-BEARING, and a real board is what proved it. These two
      uint32s used to sit AFTER the ten byte counts, at offset 2010 -- which AVR
      accepts, having no alignment requirement, and which the host pads forward to
      2012. sizeof(TgTable) was 2019 on avr-g++ and 2024 on clang++, with every
      field after the counts at a different offset on each. The board announced
      TABLEBYTES=2019 while the host test measured 2024, and that mismatch is the
      only reason anyone noticed.

      Placed here, the arrays above sum to a multiple of 4, so both toolchains
      agree without padding. Same hazard as TgTimingSet, one level up, and the
      generated record assertions could not see it because TgTable is not a wire
      record. */
  uint32_t specHash;
  uint32_t tableCrc;

  uint8_t nNodes, nEdges, nTiming, nActions;
  uint8_t nTrialTypes, nPorts, nStimuli, nWatch;
  uint8_t nStageRows, nTimingSets;

  /*  False until a whole-table CRC has verified. The interpreter never checks
      this -- the SKETCH refuses to start a session on it, which is the point:
      running a partially-received table is the silent-truncation bug this
      protocol exists to make structurally impossible. */
  bool valid;

  /*  Explicit, so the struct ends on a 4-byte boundary and neither toolchain adds
      trailing padding of its own. Padding rather than leaving it implicit, for
      the reason TgTimingSet documents: implicit padding is the compiler's
      decision, and the two compilers decide differently. */
  uint8_t _pad;
};

/*  What TgTable must measure, derived rather than written down.
 *
 *  Compiled under BOTH toolchains, which is what makes it a check rather than a
 *  restatement: if either one pads a field, its sizeof stops matching this sum
 *  and the build fails there. A literal would have to be updated by hand every
 *  time a limit moved, and would then only ever be right on the machine of
 *  whoever last updated it. */
#define TG_TABLE_BYTES                                                     \
  (sizeof(TgNode) * TG_MAX_STATES + sizeof(TgEdge) * TG_MAX_EDGES +        \
   sizeof(uint16_t) * TG_MAX_TIMING + sizeof(TgAction) * TG_MAX_ACTIONS +  \
   sizeof(TgTrialType) * TG_MAX_TRIAL_TYPES + sizeof(TgPort) * TG_MAX_PORTS + \
   sizeof(TgStimulus) * TG_MAX_STIMULI +                                   \
   sizeof(TgStageRow) * TG_MAX_STAGE_ROWS +                                \
   sizeof(TgTimingSet) * TG_MAX_TIMING_SETS +                              \
   sizeof(uint16_t) * TG_MAX_STATES + 2u * TG_MAX_WATCH +                  \
   2u * sizeof(uint32_t) + 10u /* counts */ + 1u /* valid */ + 1u /* _pad */)

#if __cplusplus >= 201103L
static_assert(sizeof(TgTable) == TG_TABLE_BYTES,
              "TgTable has padding one toolchain adds and the other does not. "
              "This was live: 2019 bytes on avr-g++ against 2024 on clang++, "
              "because two uint32 fields sat at an odd-of-4 offset.");
#endif

/*  Where the walk is. Deliberately tiny: anything more would be state the GRAPH
    should have expressed. */
struct TgRun
{
  uint8_t node;
  uint8_t trial;        // index into trialTypes
  uint8_t enteredPort;  // index into ports, set by ENTER; TG_NO_TARGET otherwise
  bool advanced;

  /*  When the resident node was entered. The watchdog measures against this
      rather than against a loop counter, so it reports what actually happened
      rather than what the loop believed it did. */
  unsigned long enteredAt;

  /*  A state overran its budget and the trial was abandoned. Distinct from
      `advanced`, which is a SCORE: a faulted trial has no outcome, and treating
      it as a repeat would quietly re-present a trial the box could not finish. */
  bool faulted;

  /*  FACTS FOR THE POLICY LAYER, and only facts.
   *
   *  runTrial() calls the policy objects from inside the trial -- recordChoice()
   *  at BehaviorBox.h:1084, recordAbstention() at :1161, :1183 and :1199. The
   *  interpreter calls nothing: policy stays outside, which is what keeps the
   *  interpreter fixed and task-agnostic.
   *
   *  So it reports what HAPPENED and the session layer decides what that means.
   *  These two, with `enteredPort`, are exactly enough to reconstruct every one of
   *  those four call sites -- see tgPolicyOutcome().
   *
   *  Neither is task knowledge. `engaged` is "an ENTER fired on a channel that is
   *  not a response port", which the watch mapping already distinguishes; `broke`
   *  is "a BROKEN trigger fired". Both are properties of the walk. */
  bool engaged;
  bool broke;

  /*  A response window was opened -- the walk reached a WAIT_ENTRY watching at
      least one response port.
   *
   *  This is what separates "never got that far" from "got there and did
   *  nothing", and `broke` cannot: a sampling hold breaks BEFORE the response
   *  window and a response hold breaks AFTER it, and both set `broke`. runTrial()
   *  crosses exactly this line when it calls checkResponse(). */
  bool offered;
};

/* ---------------------------------------------------------------- *
 *  Binding resolution
 * ---------------------------------------------------------------- */

/*  Which port a binding is about.

    `@ports[$ch]` means the port just entered; `@target` means the port this trial
    calls correct. They coincide on the correct path and DIFFER on the wrong-port
    path -- which is the case that makes keeping them separate matter at all. */
inline uint8_t tgBindPort(const TgTable &t, const TgRun &r, uint8_t sel)
{
  if (sel >= TG_BIND_TARGET_REWARD)
    return t.trialTypes[r.trial].target;
  return r.enteredPort;
}

inline uint8_t tgStimulusOfStage(const TgTable &t, const TgRun &r, uint8_t stage)
{
  const uint8_t *stims = &t.trialTypes[r.trial].stimulus0;
  return (stage < 4) ? stims[stage] : TG_NO_TARGET;
}

/*  Resolve a node's entry strobe for THIS trial. */
inline uint16_t tgResolveStrobe(const TgTable &t, const TgRun &r, uint16_t strobe)
{
  if (!TG_IS_BOUND(strobe))
    return strobe;

  const uint8_t sel = TG_SELECTOR(strobe);

  if (sel <= TG_BIND_STIM_ON_3) // selectors 0..3 are sampling stages 0..3
  {
    const uint8_t si = tgStimulusOfStage(t, r, sel);
    return (si < t.nStimuli) ? t.stimuli[si].onCode : TG_NO_STROBE;
  }

  const uint8_t p = tgBindPort(t, r, sel);
  if (p >= t.nPorts)
    return TG_NO_STROBE;
  const TgPort &port = t.ports[p];

  switch (sel)
  {
  case TG_BIND_PORT_ENTER:         return port.enterCode;
  case TG_BIND_PORT_ERROR:         return port.errorCode;
  case TG_BIND_PORT_BREAK:         return port.breakCode;
  case TG_BIND_PORT_EXIT:          return port.exitCode;
  case TG_BIND_TARGET_EXIT:        return port.exitCode;
  case TG_BIND_TARGET_REWARD:      return port.rewardCode;
  case TG_BIND_TARGET_REWARD_STOP: return port.rewardStopCode;
  default:                         return TG_NO_STROBE;
  }
}

/*  Apply one entry action. Returns without doing anything if the channel does not
    resolve, which is how a port with no reward line stays harmless. */
inline void tgApplyAction(const TgTable &t, const TgRun &r, const TgAction &a)
{
  const uint8_t ch = a.channel;

  if (ch == TG_CH_BIND_ALL_EMITTERS)
  {
    /*  An abort path: clear whatever is on, without needing to know which stage
        put it there. Cheaper and more robust than tracking it. */
    for (uint8_t i = 0; i < t.nStimuli; i++)
      digitalWrite(t.stimuli[i].emitter, a.op ? HIGH : LOW);
    return;
  }
  if (ch >= TG_CH_BIND_STIM_EMITTER_0 && ch < TG_CH_BIND_STIM_EMITTER_0 + 4)
  {
    const uint8_t si = tgStimulusOfStage(t, r, ch - TG_CH_BIND_STIM_EMITTER_0);
    if (si < t.nStimuli)
      digitalWrite(t.stimuli[si].emitter, a.op ? HIGH : LOW);
    return;
  }
  if (ch == TG_CH_BIND_TARGET_REWARD_LINE)
  {
    const uint8_t p = t.trialTypes[r.trial].target;
    if (p < t.nPorts && t.ports[p].rewardLine != TG_NO_TARGET)
      digitalWrite(t.ports[p].rewardLine, a.op ? HIGH : LOW);
    return;
  }
  if (ch != TG_NO_TARGET)
    digitalWrite(ch, a.op ? HIGH : LOW);
}

/*  A node's duration, in ms. */
inline uint16_t tgDuration(const TgTable &t, const TgRun &r, const TgNode &n)
{
  if (n.type == TG_WAIT_EXIT || n.type == TG_TERMINAL)
    return 0;
  if (n.durIdx == TG_DUR_FROM_TRIAL)
  {
    const uint8_t p = t.trialTypes[r.trial].target;
    if (p >= t.nPorts)
      return 0;
    const uint8_t di = t.ports[p].rewardDurIdx;
    return (di < t.nTiming) ? t.timing[di] : 0;
  }
  return (n.durIdx < t.nTiming) ? t.timing[n.durIdx] : 0;
}

/* ---------------------------------------------------------------- *
 *  The watchdog
 * ---------------------------------------------------------------- */

/*  Not a trigger. Returned by tgWaitForTrigger() when a state overran, and
    deliberately outside TgTrigger's range so it can never match an edge and can
    never appear in a table. Adding a real trigger would have been a wire change
    for something no graph can express. */
#define TG_TRIG_FAULT 0xFF

/*  How long this node may remain resident before something is wrong.
 *
 *  The compiler's per-node budget when it has one, the session ceiling when it
 *  does not. Zero means the compiler could not bound the node -- the two
 *  WAIT_EXIT states, which wait on the SUBJECT rather than on a clock -- and it
 *  is a safe sentinel because a node whose real bound is zero cannot overrun.
 *
 *  THE BUDGETS ARE PEAK VALUES, NOT COMPILED ONES. The stage ramp rewrites the
 *  timing vector at runtime, so a budget taken from the compiled default would be
 *  50x too small on three of shaping_gr's nodes by the last stage row -- and
 *  would end healthy sessions on a false alarm, which is worse than the hang this
 *  exists to prevent. taskgraph/lower.py::_peak_timing is where that is handled.
 *
 *  GENEROUS ON PURPOSE. This is a net for a box that has stopped, not a
 *  behavioural criterion. The margin is the whole design: 30 s against a longest
 *  recorded sampling release of 21.1 s across 75,590 of them. */
inline unsigned long tgDwellLimit(const TgTable &t, uint8_t node)
{
  const uint16_t budget = t.maxDwell[node];
  return budget ? (unsigned long)budget + TG_WATCHDOG_GRACE_MS
                : (unsigned long)TG_WATCHDOG_CEILING_MS;
}

/*  Has the resident node overrun?
 *
 *  Wall-clock against the node's own entry time, so it measures what actually
 *  happened rather than what the loop believes it did. */
inline bool tgOverran(const TgTable &t, const TgRun &r, unsigned long enteredAt)
{
  return (millis() - enteredAt) > tgDwellLimit(t, r.node);
}

/*  Every actuator the table can drive, off.
 *
 *  TABLE-DRIVEN, not a pin list. A hard-coded list would be a fourth mirror of
 *  the pinout and would go stale the first time a task used a line nobody thought
 *  to add -- leaving a solenoid open on the one path where that matters most.
 *  What the table can turn on is exactly what it must be able to turn off. */
inline void tgSafeAllOutputs(const TgTable &t)
{
  for (uint8_t i = 0; i < t.nActions; i++)
  {
    const uint8_t ch = t.actions[i].channel;
    if (ch < TG_CH_BIND_STIM_EMITTER_0)
      digitalWrite(ch, LOW);
  }
  for (uint8_t i = 0; i < t.nStimuli; i++)
    digitalWrite(t.stimuli[i].emitter, LOW);
  for (uint8_t i = 0; i < t.nPorts; i++)
    if (t.ports[i].rewardLine != TG_NO_TARGET)
      digitalWrite(t.ports[i].rewardLine, LOW);
}

/*  The single channel a HOLD or WAIT_EXIT watches.

    A zero mask means the watch is runtime-bound -- the engaged port, or the
    target when nothing has been entered yet. TG406 guarantees these node types
    watch exactly one channel, which is what lets this return a single pin. */
inline uint8_t tgWatchedPin(const TgTable &t, const TgRun &r, const TgNode &n)
{
  for (uint8_t b = 0; b < t.nWatch; b++)
    if (n.watchMask & (uint8_t)(1u << b))
      return t.watchPin[b];

  const uint8_t p = (r.enteredPort != TG_NO_TARGET) ? r.enteredPort
                                                    : t.trialTypes[r.trial].target;
  return (p < t.nPorts) ? t.ports[p].channel : TG_NO_TARGET;
}

/* ---------------------------------------------------------------- *
 *  The walk
 * ---------------------------------------------------------------- */

/*  Enter a node: apply its entry actions, then emit its entry strobe.
 *
 *  ACTIONS BEFORE STROBE, always. The strobe reports that the hardware change has
 *  happened, so emitting it first would timestamp an event before it occurred --
 *  by well under a millisecond, but the recording is the only account anyone gets.
 *
 *  THE ONLY emitStrobe() CALL IN THE INTERPRETER. */
inline void tgEnterNode(const TgTable &t, TgRun &r, TrialClock &clock, uint8_t node)
{
  r.node = node;
  r.enteredAt = millis();
  const TgNode &n = t.nodes[node];

  /*  Entering a window that watches a response port IS the response window
      opening. Derived from the watch mapping rather than from a node label, so it
      stays true for a task with three ports or none. */
  if (n.type == TG_WAIT_ENTRY)
    for (uint8_t b = 0; b < t.nWatch; b++)
      if ((n.watchMask & (uint8_t)(1u << b)) && t.watchPort[b] != TG_NO_TARGET)
      {
        r.offered = true;
        break;
      }

  for (uint8_t i = 0; i < n.actionCount; i++)
    tgApplyAction(t, r, t.actions[n.actionIdx + i]);

  const uint16_t code = tgResolveStrobe(t, r, n.strobe);
  if (code != TG_NO_STROBE)
    emitStrobe(clock, (int)code);
}

/*  Poll until the resident node resolves, and report which trigger fired.
 *
 *  Time advances through delay(), exactly as runTrial() does, so both are driven
 *  by one clock and a byte-for-byte comparison is meaningful. */
inline uint8_t tgWaitForTrigger(const TgTable &t, TgRun &r, const TaskParams &p)
{
  const TgNode &n = t.nodes[r.node];
  const uint16_t limit = tgDuration(t, r, n);

  switch (n.type)
  {
  case TG_DELAY:
    delay(limit);
    return TG_TRIG_TIMEOUT;

  case TG_PULSE:
    delay(limit);
    return TG_TRIG_DONE;

  case TG_TERMINAL:
    return r.advanced ? TG_TRIG_ADVANCE : TG_TRIG_REPEAT;

  case TG_WAIT_ENTRY:
  {
    const unsigned long start = millis();
    while (millis() - start < (unsigned long)limit)
    {
      /*  Every watched channel gets its own check, in bit order. That ordering is
          the tie-break when two beams break in the same poll, and it has to be
          deterministic or the equivalence gate becomes a coin flip. */
      for (uint8_t b = 0; b < t.nWatch; b++)
      {
        if (!(n.watchMask & (uint8_t)(1u << b)))
          continue;
        if (digitalRead(t.watchPin[b]) == LOW)
        {
          /*  A bit whose port is TG_NO_TARGET is the engagement channel -- it is
              watchable but is not a response port and has no TgPort row. Keeping
              the two apart here is what lets the session layer tell "never
              engaged" from "engaged and then did nothing", which runTrial()
              distinguishes and which no strobe on the omission path reports. */
          if (t.watchPort[b] == TG_NO_TARGET)
            r.engaged = true;
          else
            r.enteredPort = t.watchPort[b];
          return TG_TRIG_ENTER;
        }
      }
      /*  Bounded by its own window, so this can only fire if the loop itself is
          not progressing -- a clock that stopped, a poll that blocks. Cheap
          insurance in the one place it can still be taken. */
      if (tgOverran(t, r, r.enteredAt))
        return TG_TRIG_FAULT;
      delay(p.pollingRate);
    }
    return TG_TRIG_TIMEOUT;
  }

  case TG_HOLD:
    return verifySensor(tgWatchedPin(t, r, n), (int)limit, p.pollingRate)
               ? TG_TRIG_HELD
               : TG_TRIG_BROKEN;

  case TG_WAIT_EXIT:
  {
    /*  No timeout, by definition -- one of the two states only the runtime
        watchdog can bound, which is exactly why the compiler enumerates them.
        THIS IS THE LOOP THE WATCHDOG EXISTS FOR: it is the only place in the
        interpreter that can wait forever, and the shipping firmware's equivalent
        did exactly that (docs/firmware-changes.md #0). */
    const uint8_t pin = tgWatchedPin(t, r, n);
    while (digitalRead(pin) == LOW)
    {
      if (tgOverran(t, r, r.enteredAt))
        return TG_TRIG_FAULT;
      delay(p.pollingRate);
    }
    return TG_TRIG_EXIT;
  }
  }
  return TG_TRIG_TIMEOUT;
}

/*  Which edge a trigger takes, and what it does.
 *
 *  FIRST MATCH WINS, and the compiler guarantees the unguarded default is emitted
 *  last (TG405) -- which is what lets this be one forward scan with no precedence
 *  logic of its own. */
inline const TgEdge *tgResolveEdge(const TgTable &t, const TgRun &r, uint8_t trigger,
                                   bool correctionBudget)
{
  const TgNode &n = t.nodes[r.node];
  const uint8_t end = (r.node + 1 < t.nNodes) ? t.nodes[r.node + 1].edgeIdx : t.nEdges;

  for (uint8_t i = n.edgeIdx; i < end; i++)
  {
    const TgEdge &e = t.edges[i];
    if (e.trigger != trigger)
      continue;
    if (e.guard == TG_GUARD_IS_TARGET && r.enteredPort != t.trialTypes[r.trial].target)
      continue;
    if (e.guard == TG_GUARD_CORRECTION && !correctionBudget)
      continue;
    return &e;
  }
  return 0;
}

/* ---------------------------------------------------------------- *
 *  The stage ramp
 * ---------------------------------------------------------------- */

/*  Rewrite the timing vector for the stage row live at this trial count.
 *
 *  Generalises applyStage() (BehaviorBox.h:567-574) from four hard-coded fields to
 *  N addressed by index. Call it between trials, never during one -- a hold whose
 *  duration changed underneath it would be neither the old value nor the new one.
 *
 *  SCANS DESCENDING AND TAKES THE FIRST ROW THAT APPLIES, which is what makes it
 *  idempotent: calling it twice, or skipping a trial count entirely, lands on the
 *  same row. The switch-on-exact-count it replaces did not have that property, so
 *  a session that skipped the trigger count kept the previous stage's timings for
 *  the rest of the run.
 *
 *  Applying ONE row rather than replaying every row up to here is only correct
 *  because each row restates every entry the schedule touches. TG507 enforces
 *  that; without it, a row that omitted an entry an earlier row set would leave a
 *  stale value with nothing reporting it. */
inline void tgApplyStage(TgTable &t, uint16_t completedTrials)
{
  for (uint8_t i = t.nStageRows; i > 0; i--)
  {
    const TgStageRow &row = t.stageRows[i - 1];
    if (completedTrials < row.atTrial)
      continue;
    for (uint8_t k = 0; k < row.count; k++)
    {
      const TgTimingSet &s = t.timingSets[row.firstIdx + k];
      if (s.idx < t.nTiming)
        t.timing[s.idx] = s.ms;
    }
    return;
  }
}

/*  Run one trial. Returns true when the session should ADVANCE.
 *
 *  Mirrors runTrial()'s contract exactly, so a sketch can call either.
 *  `correctionBudget` is the caller's answer to "does this side still have
 *  budget?" -- policy stays outside the interpreter, which is what keeps the
 *  interpreter fixed. */
inline bool tgRunTrial(const TgTable &t, TgRun &r, const TaskParams &p,
                       TrialClock &clock, uint8_t trialIndex,
                       bool correctionBudget = false, uint16_t maxSteps = 200)
{
  r.trial = trialIndex;
  r.enteredPort = TG_NO_TARGET;
  r.advanced = false;
  r.faulted = false;
  r.engaged = false;
  r.broke = false;
  r.offered = false;

  tgEnterNode(t, r, clock, 0);

  for (uint16_t step = 0; step < maxSteps; step++)
  {
    if (t.nodes[r.node].type == TG_TERMINAL)
      return r.advanced;

    const uint8_t trigger = tgWaitForTrigger(t, r, p);
    /*  A state overran. The trial is abandoned WITHOUT a score -- it has no
        outcome, and calling it a repeat would quietly re-present a trial the box
        could not finish. Reporting, safing the hardware and ending the session
        belong to the caller, which is also what keeps tgEnterNode() the only
        emitStrobe() in here. */
    if (trigger == TG_TRIG_FAULT)
    {
      r.faulted = true;
      return false;
    }
    if (trigger == TG_TRIG_BROKEN)
      r.broke = true;
    const TgEdge *e = tgResolveEdge(t, r, trigger, correctionBudget);
    if (!e)
      return false; // TG401 makes this unreachable; fail closed if it is not

    /*  Scoring is an EDGE effect, which is what lets go/no-go invert the meaning
        of TIMEOUT without the interpreter knowing anything about response modes. */
    if (e->effect == TG_EFFECT_ADVANCE)
      r.advanced = true;
    else if (e->effect == TG_EFFECT_REPEAT)
      r.advanced = false;

    tgEnterNode(t, r, clock, e->target);
  }
  return false;
}

#endif // TG_INTERPRET_H

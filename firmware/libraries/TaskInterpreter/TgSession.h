#ifndef TG_SESSION_H
#define TG_SESSION_H

/* ============================================================= *
 *  The session layer: everything around a trial, not inside one.
 *
 *  This is a TRANSCRIPTION of GRGL_2-Odor.ino's loop with one substitution --
 *  runTrial() becomes tgRunTrial(). Deliberately, and the diff is the point: the
 *  roadmap's Phase 5 exit criterion is a parallel run showing no behavioural or
 *  structural divergence, and every difference this layer introduces is a
 *  difference that run would have to explain away.
 *
 *  ---------------------------------------------------------------
 *  WHERE THE PARAMETERS COME FROM, AND WHY IT IS NOT THE TABLE
 *
 *  The uploaded table carries a timing vector and a stage schedule. This sketch
 *  OVERRIDES both from the START line, exactly as the current sketch does.
 *
 *  That looks backwards for a project whose point is that tasks become data, and
 *  it is temporary. The reason is the parallel run: Gates B and D proved
 *  equivalence with the timings coming from TaskParams, so a sketch that took
 *  them from the table instead would be running a configuration nothing has
 *  validated -- and any divergence in the parallel run would then be ambiguous
 *  between "the interpreter is wrong" and "the spec's numbers differ from the
 *  app's". Phase 7 flips the authority once the run has held.
 *
 *  What the table DOES supply, and what nothing else can: the topology, the
 *  strobe codes, the runtime bindings, which line rewards which port, and the
 *  per-node watchdog budgets.
 *
 *  ---------------------------------------------------------------
 *  THE INTERPRETER NEEDS EXACTLY ONE FIELD FROM TaskParams: pollingRate. Every
 *  other number it uses comes from the table. That is worth knowing when reading
 *  what follows -- the params here are for the POLICY objects and for the timing
 *  push below, not for the walk.
 * ============================================================= */

#include "TgInterpret.h"
#include "TgStrobes.h"

/*  How a trial ended, from the session's point of view. */
enum TgTrialResult : uint8_t
{
  TG_TRIAL_ADVANCED = 0, // scored, session moves on
  TG_TRIAL_REPEAT,       // aborted or an in-budget correction error
  TG_TRIAL_FAULT         // a state overran; the session must stop
};

struct TgSession
{
  uint16_t completed = 0;
  bool over = true;
  bool faulted = false;
};

/*  Push the live TaskParams timings into the table.
 *
 *  THIS IS THE OVERRIDE described above, in one place so it is easy to find and
 *  easy to delete in Phase 7. It is the same operation the equivalence gates
 *  perform (extras/host_test/battery.h::syncTiming), which is what makes the
 *  sketch run the configuration those gates validated rather than a neighbouring
 *  one.
 *
 *  Timing entries are addressed BY NAME through the generated TG_IDX_* symbols,
 *  which the caller supplies, because a numeric index would silently point at a
 *  different duration the moment a spec gained an entry above it. */
inline void tgApplyParams(TgTable &t, const TaskParams &p,
                          uint8_t commitHold, uint8_t sampleHold,
                          uint8_t respHold, uint8_t respWin, uint8_t engageWin)
{
  if (commitHold < t.nTiming) t.timing[commitHold] = (uint16_t)p.odorPokeHold;
  if (sampleHold < t.nTiming) t.timing[sampleHold] = (uint16_t)p.odorPokeHold;
  if (respHold < t.nTiming) t.timing[respHold] = (uint16_t)p.fluidWellHold;
  if (respWin < t.nTiming) t.timing[respWin] = (uint16_t)p.fluidWellPoll;
  if (engageWin < t.nTiming) t.timing[engageWin] = (uint16_t)p.odorPortTimeout;
}

/* ---------------------------------------------------------------- *
 *  Policy
 *
 *  runTrial() calls the policy objects from INSIDE the trial. tgRunTrial() calls
 *  nothing, so the session layer has to make those same calls from outside, at
 *  the same moments, with the same arguments.
 *
 *  THE THREE CLASSES ARE REUSED VERBATIM, not reimplemented. AntiBiasSelector,
 *  AbstentionPenalty and CorrectionPolicy are BehaviorBox's, they are pure state
 *  machines over booleans, and their tuning arrives on the START line. A second
 *  implementation of the anti-bias estimator would be a mirror of the one piece
 *  of this system whose output is a probability -- the hardest possible thing to
 *  notice drifting.
 *
 *  What is NOT reused is the ESCALATOR'S CALL SITE. See tgPenaltyMs().
 * ---------------------------------------------------------------- */

/*  What a finished trial means to the policy layer.
 *
 *  Reconstructs runTrial()'s four call sites from the three facts the walk
 *  reports, and the mapping is exact:
 *
 *    :1084  a well was poked           -> recordChoice(side)      TG_OUTCOME_CHOSE
 *    :1161  never engaged              -> recordAbstention        TG_OUTCOME_ABSTAINED
 *    :1183  pre-odor hold broken       -> recordAbstention        TG_OUTCOME_ABSTAINED
 *    :1199  sampling hold broken       -> recordAbstention        TG_OUTCOME_ABSTAINED
 *    :1091  sampled, no response       -> NOTHING                 TG_OUTCOME_SILENT
 *
 *  THE ORDER OF THE TESTS MATTERS. A response hold broken at the well
 *  (WATER_UNPOKE_EARLY) sets `broke` AND entered a port -- and runTrial() records
 *  a CHOICE there, not an abstention, because the animal did express a side. So
 *  the port test comes first. Getting that backwards would feed the bias
 *  estimator a vote in the wrong direction on every response-hold failure. */
enum TgPolicyOutcome : uint8_t
{
  TG_OUTCOME_SILENT = 0, // the omission path: policy hears nothing
  TG_OUTCOME_CHOSE,      // a side was expressed; `port` says which
  TG_OUTCOME_ABSTAINED   // no side expressed, and it was not an omission
};

inline TgPolicyOutcome tgPolicyOutcome(const TgRun &r, uint8_t &port)
{
  if (r.enteredPort != TG_NO_TARGET)
  {
    port = r.enteredPort;
    return TG_OUTCOME_CHOSE;
  }
  /*  Reaching the response window and doing nothing is the OMISSION, and
      runTrial() tells the policy nothing about it (:1091 returns before any
      policy call). Not reaching it is one of the three abort paths.

      `offered` rather than `broke` is the test, because a sampling hold breaks
      BEFORE the window and a response hold breaks AFTER it -- both set `broke`,
      and only one of them is an abstention. */
  return r.offered ? TG_OUTCOME_SILENT : TG_OUTCOME_ABSTAINED;
}

/*  The no-engagement penalty for the trial ABOUT to run, in ms.
 *
 *  WHY THIS IS COMPUTED HERE RATHER THAN BY AbstentionPenalty. That class's
 *  nextDelay() returns the current value AND increments, and it is called by
 *  runTrial() at the instant the abstention happens -- inside the trial. The
 *  interpreter reads the penalty from the timing vector when it ENTERS the
 *  penalty node, so the value has to be in the table before the trial starts.
 *
 *  Pre-calling nextDelay() every trial would count trials rather than
 *  abstentions: a wrong-well trial would escalate the penalty where runTrial()
 *  leaves it alone. There is no way to peek without consuming -- `_consecutive`
 *  is private and the class has no accessor -- and BehaviorBox.h is a read-only
 *  reference, so adding one is not available.
 *
 *  So the count is kept here and the formula is applied from the START line's own
 *  values. It is four lines and its inputs are the same four fields configure()
 *  reads. tests/test_gate_f.py holds it against AbstentionPenalty over thousands
 *  of sequences rather than trusting the transcription.
 *
 *  `abstentions` is the count since the last CORRECT trial -- not since the last
 *  non-abstention. runTrial() resets the escalator only in the OUTCOME_CORRECT
 *  branch (:1221), so a wrong answer does not clear it. */
inline uint16_t tgPenaltyMs(const TaskParams &p, uint16_t abstentions, bool armed)
{
  if (!p.lazyEscalationEnabled || !armed)
    return (uint16_t)p.lazyRatDelay;
  long d = (long)p.lazyRatDelay + (long)abstentions * (long)p.lazyEscalateStep;
  if (d > (long)p.lazyDelayMax)
    d = p.lazyDelayMax;
  return (uint16_t)d;
}

/*  Which port index a pin belongs to, and which trial type targets a port.
 *
 *  The selector speaks in sides; the interpreter speaks in trial-type indices.
 *  These two are the whole of the translation, and both read the TABLE rather
 *  than assuming an ordering -- a spec that listed its trial types the other way
 *  round would otherwise silently swap the sides. */
inline uint8_t tgPortForChannel(const TgTable &t, uint8_t pin)
{
  for (uint8_t i = 0; i < t.nPorts; i++)
    if (t.ports[i].channel == pin)
      return i;
  return TG_NO_TARGET;
}

inline uint8_t tgTrialForPort(const TgTable &t, uint8_t port)
{
  for (uint8_t i = 0; i < t.nTrialTypes; i++)
    if (t.trialTypes[i].target == port)
      return i;
  return 0;
}

/*  Run one trial and report how it ended.
 *
 *  Mirrors GRGL_2-Odor.ino:162-176: a trial that does not advance re-presents the
 *  SAME side; one that advances increments the count and ramps the stage.
 *
 *  THE CALLER MUST NOT EMIT INVALID_TRIAL. The current sketch does, at :175,
 *  because runTrial() cannot -- and the first version of this function copied that
 *  faithfully and emitted it twice, which is what Gate E found on its first run.
 *
 *  In the model, INVALID_TRIAL is a TERMINAL NODE's entry strobe (D20). It has to
 *  be: a wrong answer under an unspent correction budget emits END_INCORRECT_ITI
 *  and then INVALID_TRIAL, and two strobes in that order means two nodes in that
 *  order. That decision came out of the corpus -- the version that made them
 *  alternative terminal strobes rejected every recorded session that had ever run
 *  with a correction budget, and no others.
 *
 *  So the interpreter emits it, from tgEnterNode() like every other strobe, and
 *  the invariant holds: every timestamp in a recording is a state-entry time. */
inline TgTrialResult tgSessionTrial(TgTable &t, TgRun &r, const TaskParams &p,
                                    TrialClock &clock, uint8_t trialIndex,
                                    bool correctionBudget)
{
  const bool advanced = tgRunTrial(t, r, p, clock, trialIndex, correctionBudget);

  if (r.faulted)
    return TG_TRIAL_FAULT;
  return advanced ? TG_TRIAL_ADVANCED : TG_TRIAL_REPEAT;
}

#endif // TG_SESSION_H

#ifndef TASK_INTERPRETER_H
#define TASK_INTERPRETER_H

/* ============================================================= *
 *  TaskInterpreter.h -- the box-facing entry point.
 *
 *  Two things a sketch needs and the interpreter itself does not: the capability
 *  announcement that precedes READY, and the footprint assertion that keeps the
 *  RAM budget honest. The walk is TgInterpret.h; the layout is TaskTable.h.
 *
 *  THERE IS ONE TABLE SHAPE, `TgTable`, AND IT LIVES IN TgInterpret.h. This file
 *  used to declare a second one -- a Phase 0 skeleton, written before the
 *  interpreter existed -- and by the end of Phase 3 the two had drifted apart:
 *  the skeleton had no ports, stimuli or watch arrays, and the real one had no
 *  stage schedule. Phase 4 uploads a table, so a second shape stopped being
 *  harmless the moment something had to fill one. It is deleted rather than
 *  updated: this repo has already spent real effort on mirrored constants
 *  (START_LINE_MAX, baudRate) and a mirrored struct is the same bug with a worse
 *  failure mode.
 *
 *  ADD, DON'T MODIFY. This sits ALONGSIDE BehaviorBox.h and consumes it; it
 *  replaces nothing. runTrial() keeps shipping untouched until Phase 7, so the
 *  rig is never down because the generator is half-finished. The hardware and
 *  pinout layer in BehaviorBox.h is sound and orthogonal and is meant to survive
 *  the migration intact -- pins, initBoxHardware(), emitStrobe(), verifySensor()
 *  and the three policy classes are all reused here rather than reimplemented.
 * ============================================================= */

#include "TgInterpret.h" // the walk, and TgTable -- which pulls in BehaviorBox.h
#include "TgReceive.h"   // the upload: chunked, checksummed, and refusable
#include "TaskLimits.h"
#include "TgStrobes.h" // generated; the one definition of every strobe code
#include "TgWire.h"    // generated; TG_WIRE_FORMAT, announced so a host can check it

/* ---------------------------------------------------------------- *
 *  The watchdog's other half
 * ---------------------------------------------------------------- */

/*  A state overran. Safe the hardware, say so, and let the session end.
 *
 *  THIS LIVES HERE, NOT IN THE INTERPRETER, and that is the whole reason
 *  tgRunTrial() only sets a flag. Every strobe inside the interpreter is emitted
 *  by exactly one call to tgEnterNode(), which is what makes every timestamp in a
 *  recording a state-entry time and what makes "which edge fired" recoverable
 *  from "which strobe appeared". A fault is not a state entry -- it is the
 *  absence of one -- so emitting it from in there would cost that invariant for
 *  the sake of one line.
 *
 *  It is the same split the existing firmware already uses: INVALID_TRIAL is
 *  emitted by the sketch loop, not by runTrial(), because it reports something
 *  about the SESSION rather than about a state.
 *
 *  ORDER IS DELIBERATE. Hardware first, strobe second. The strobe records that
 *  the shutdown happened, so emitting it before the outputs were actually cleared
 *  would timestamp a claim ahead of the fact -- and this is precisely the record
 *  someone will read when asking what the box was doing when it stopped. */
inline void tgHandleFault(const TgTable &table, TrialClock &clock, const TgRun &run)
{
  tgSafeAllOutputs(table);
  emitStrobe(clock, TG_STROBE_WATCHDOG_FAULT);

  /*  Which state, in a form a person can act on. Informational rather than a
      strobe, because the code says "a fault happened" and this says which node --
      and inventing a per-node strobe code would be an unbounded vocabulary. */
  Serial.print(F("INFO\tFAULT node="));
  Serial.print(run.node);
  Serial.print(F(" dwell="));
  Serial.print(tgDwellLimit(table, run.node));
  Serial.println(F(" ms exceeded"));
}
/*  Generated size AND field-offset assertions. Included HERE, not only in the host
    tests, so an AVR build checks them too -- which is the only construction that
    catches a layout differing between the two toolchains. TgTimingSet was exactly
    that: 3 bytes on AVR, 4 on the host, compiling cleanly on both. */
#include "TgLayoutAssert.h"

/*  Announce capabilities. The CALLER emits the bare READY afterwards.

    ORDER IS LOAD-BEARING. The host matches readiness as an exact whole line
    (Ephymeris ports/handler.py:337) but IGNORES any line arriving before it, so
    CAP lines must precede a bare READY. Appending to the READY line instead
    would make every currently-deployed host fail with "board never reported
    READY". This ordering is what lets a migrated box keep working against an
    un-migrated host with zero changes on the host side, which is what makes a
    box-by-box rollout possible. See docs/protocol-negotiation.md.

    EVERY NUMBER HERE IS GENERATED, from schema/limits.v1.json via TaskLimits.h.
    That is the whole point of announcing them: a host that compiled its own copy
    of MAXSTATES would be the third instance of the mirroring pattern this repo
    already documents twice, and the failure mode is a silently truncated table.

    Header-only and inline, matching BehaviorBox.h's convention -- these
    libraries are bare folders with no library.properties, so a .cpp would not be
    compiled by the Arduino build without extra plumbing. */
inline void tgAnnounceCapabilities()
{
  /* Tab after the keyword mirrors the existing SEED\t<value> convention rather
     than inventing a second shape. Unknown keys are ignored by both sides, which
     is what makes the vocabulary extensible without a version bump. */
  Serial.print(F("CAP\tPROTO="));
  Serial.print(TG_PROTO_VERSION);
  Serial.print(F(" TASKGRAPH=1 SPEC="));
  Serial.print(TG_SPEC_VERSION);
  Serial.print(F(" VOCAB="));
  Serial.print(TG_VOCAB_VERSION);
  Serial.print(F(" CHANNELS="));
  Serial.print(TG_CHANNELS_VERSION);
  /*  WIRE is the byte layout of an uploaded table, and it is the one capability
      a host cannot infer from the others. PROTO says how we talk; WIRE says how
      the table is packed. They move independently -- a section added to the table
      bumps WIRE and leaves PROTO alone -- and a host that packed to a format the
      board does not know would otherwise find out by CRC failure rather than by
      being told. */
  Serial.print(F(" WIRE="));
  Serial.println(TG_WIRE_FORMAT);

  Serial.print(F("CAP\tMAXSTATES="));
  Serial.print(TG_MAX_STATES);
  Serial.print(F(" MAXEDGES="));
  Serial.print(TG_MAX_EDGES);
  Serial.print(F(" MAXTIMING="));
  Serial.print(TG_MAX_TIMING);
  Serial.print(F(" MAXACTIONS="));
  Serial.print(TG_MAX_ACTIONS);
  Serial.print(F(" MAXTRIALTYPES="));
  Serial.println(TG_MAX_TRIAL_TYPES);

  /*  The rest of the capacity, so the host can refuse an over-large table with a
      message naming both numbers instead of the board silently truncating one.
      MAXWATCH is the hard one: it is the width of TgNode.watchMask, so a ninth
      channel has no bit and would be silently unwatched. */
  Serial.print(F("CAP\tMAXPORTS="));
  Serial.print(TG_MAX_PORTS);
  Serial.print(F(" MAXSTIMULI="));
  Serial.print(TG_MAX_STIMULI);
  Serial.print(F(" MAXWATCH="));
  Serial.print(TG_MAX_WATCH);
  Serial.print(F(" MAXSTAGEROWS="));
  Serial.print(TG_MAX_STAGE_ROWS);
  Serial.print(F(" MAXTIMINGSETS="));
  Serial.println(TG_MAX_TIMING_SETS);

  Serial.print(F("CAP\tLINEMAX="));
  Serial.print(TG_START_LINE_MAX);
  Serial.print(F(" BAUD="));
  Serial.println(TG_BAUD_RATE);
}

/* ---------------------------------------------------------------- *
 *  Footprint assertion.
 *
 *  The RAM spike's conclusion, made mechanical. If someone raises a limit in
 *  TaskLimits.h without re-running the spike, the build fails here rather than
 *  the box discovering it mid-session with an animal in it.
 *
 *  2600 bytes is the measured table cost at the current limits (1440) plus room
 *  for the counts and provenance fields, against a peak stack measured at 777
 *  bytes and GRGL's 766 bytes of existing globals. See docs/spikes/avr-ram.md.
 * ---------------------------------------------------------------- */
#if __cplusplus >= 201103L
static_assert(sizeof(TgTable) <= 2600,
              "TgTable exceeds its measured budget -- re-run the AVR RAM spike "
              "(docs/spikes/avr-ram.md) before raising a limit in TaskLimits.h");
#endif

#endif // TASK_INTERPRETER_H

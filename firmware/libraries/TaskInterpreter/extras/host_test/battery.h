#ifndef TG_BATTERY_H
#define TG_BATTERY_H

/*  The randomised animal, shared by every gate that needs one.
 *
 *  WHY THE BATTERY IS RANDOMISED. Hand-written cases test what the author thought
 *  of. The interesting failures in a trial loop are boundaries -- a hold released
 *  one poll before it completes, a response landing on the last millisecond of its
 *  window -- and those are found by generating thousands of animals, not by
 *  imagining them.
 *
 *  Deterministic: one seed, printed by the caller, so any failure is reproducible
 *  exactly.
 *
 *  WHY IT LIVES IN A HEADER. Gate B compares the interpreter against runTrial();
 *  Gate C compares an UPLOADED table against a compiled-in one. Both need the same
 *  animals, and a second copy of this generator would let the two gates silently
 *  diverge on what they were testing -- the mirroring failure this project keeps
 *  finding in constants, applied to a test fixture, where it would be harder to
 *  see and just as wrong.
 */

#include <BehaviorBox.h> // TaskParams and the pin names the scripts address

#include "Arduino.h"

/*  INCLUDE THIS AFTER THE GENERATED TABLE HEADER. syncTiming() addresses timing
    entries by their TG_IDX_* names, which are macros the table header defines --
    and a macro has to exist before the template that uses it is parsed, not
    merely before it is instantiated. Addressing them by number instead would
    silently point at the wrong duration the moment a spec gained an entry. */

struct Rng
{
  unsigned long s;
  unsigned long next() { s = s * 1103515245UL + 12345UL; return (s >> 16) & 0x7FFF; }
  unsigned long in(unsigned long lo, unsigned long hi) { return lo + next() % (hi - lo + 1); }
  bool chance(int pct) { return (int)(next() % 100) < pct; }
};

struct Script
{
  uint8_t trial;
  unsigned long engageAt, engageTo;
  int respPin;              // 0 = no response
  unsigned long respAt, respTo;
};

/*  Draw an animal, weighted so every outcome class appears often enough to matter
    and boundaries are hit deliberately: a hold released exactly at its threshold,
    a response arriving on the final millisecond of its window. */
inline Script drawScript(Rng &rng, const TaskParams &p)
{
  Script s{};
  s.trial = (uint8_t)rng.in(0, 1);
  const int correct = (s.trial == 0) ? rightWell : leftWell;
  const int wrong = (s.trial == 0) ? leftWell : rightWell;

  if (rng.chance(12)) // abstains
    return s;

  s.engageAt = rng.in(1, (unsigned long)p.odorPortTimeout - 1);

  const unsigned long bothHolds = 2UL * (unsigned long)p.odorPokeHold;
  if (rng.chance(18)) // lets go somewhere inside the two holds
  {
    s.engageTo = s.engageAt + rng.in(0, bothHolds);
    return s;
  }
  /*  Held long enough to sample, then withdraws. The +1 matters: verifySensor
      needs the beam intact strictly AFTER the hold, and an off-by-one here is the
      difference between a sampled trial and a broken one. */
  s.engageTo = s.engageAt + bothHolds + rng.in(1, 400);

  if (rng.chance(15)) // samples, then does nothing
    return s;

  s.respPin = rng.chance(28) ? wrong : correct;
  const unsigned long open = s.engageTo;
  s.respAt = open + rng.in(1, (unsigned long)p.fluidWellPoll - 1);
  s.respTo = s.respAt + (rng.chance(20) ? rng.in(0, (unsigned long)p.fluidWellHold)
                                        : (unsigned long)p.fluidWellHold + rng.in(1, 3000));
  return s;
}

inline void arm(const Script &s)
{
  mock.reset();
  if (s.engageTo > s.engageAt)
    mock.poke(odorPort, s.engageAt, s.engageTo);
  if (s.respPin)
    mock.poke(s.respPin, s.respAt, s.respTo);
}

/*  The four live holds are layer-3 values the stage ramp rewrites. applyStage()
    moves them in TaskParams; the interpreter reads them from the timing vector, so
    a caller driving both has to move both. This is the same mechanism a real
    sketch uses -- and the same one tgApplyStage() uses on the board. */
template <class Table>
inline void syncTiming(Table &t, const TaskParams &p)
{
  t.timing[TG_IDX_COMMIT_HOLD] = (uint16_t)p.odorPokeHold;
  t.timing[TG_IDX_SAMPLE_HOLD] = (uint16_t)p.odorPokeHold;
  t.timing[TG_IDX_RESP_HOLD] = (uint16_t)p.fluidWellHold;
  t.timing[TG_IDX_RESP_WIN] = (uint16_t)p.fluidWellPoll;
  t.timing[TG_IDX_ENGAGE_WIN] = (uint16_t)p.odorPortTimeout;
}

#endif // TG_BATTERY_H

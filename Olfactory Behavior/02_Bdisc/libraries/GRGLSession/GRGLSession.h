/*
  GRGLSession.h
  =============
  Author: Chase Johnston (2026)

  Shared session logic for the GRGL 2-Odor discrimination task, used by BOTH
  sketches (GRGL_2-Odor and GRGL_2-Odor_EZ) so the per-side correction, anti-bias
  selection, and lazy-penalty logic is defined ONCE here, not duplicated.

  This is a header-only Arduino library. It is reached by each sketch via
  `arduino-cli compile --libraries <.../02_Bdisc/libraries>` (wired in the Python
  upload_sketch.py). To compile-check a sketch in the Arduino IDE, add that
  `libraries` folder to the IDE's library search path.

  Microcontroller-appropriate OOP: plain classes/structs, no dynamic allocation,
  no virtual dispatch in the trial loop. Per-sketch differences are kept OUT of
  this file: tuning constants that differ between sketches are constructor
  arguments, and the call SITES (where each class's methods fire) stay in each
  sketch -- because the two sketches reset/aggregate this state at different
  points (e.g. the EZ variant resets the lazy escalator on odor poke and gates
  escalation behind its shaping stage, while the full task resets it only on a
  completed correct trial).

  Classes:
    SessionConfig       START-parsed runtime params + parseStartCommand()
    AntiBiasSelector    ring-buffer bias estimate + next-side selection
    AbstentionPenalty   lazy-rat timeout (flat or escalating) + the on/off toggle
    CorrectionPolicy    per-side leading correction-trial budgets
  Plus the shared TrialType / TrialClock structs and a frand() helper.
*/

#ifndef GRGL_SESSION_H
#define GRGL_SESSION_H

#include <Arduino.h>
#include <stdlib.h>
#include <string.h>

// Largest sliding bias window the selector's ring buffer can hold. Both sketches
// use 20; the fixed array avoids any dynamic allocation on the MCU.
#define GRGL_MAX_BIAS_WINDOW 32

/* ===================== Shared trial data structs ===================== */
/* A struct that defines the differences between trial types. (Moved here from
   the sketches so AntiBiasSelector can return a TrialType*.) The concrete
   goRight/goLeft instances stay in each sketch, since they reference that
   sketch's pins and strobe codes. */
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

/* Encapsulates trial timestamps relative to recording start (millis-based). */
struct TrialClock
{
  unsigned long recStart = 0;
  unsigned long currentTS = 0;

  void beginSession()
  {
    currentTS = millis();
    recStart = currentTS;
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

/* ===================== SessionConfig + START parser ===================== */
/* Runtime parameters carried from the GUI to the board in the START command.
   This is the obvious home for the next GUI-configurable toggle: add a field
   here and one branch in parseStartCommand(), and it flows everywhere. */
struct SessionConfig
{
  int correctionLeft = 0;        // CL: leading correction budget, LEFT-correct trials
  int correctionRight = 0;       // CR: leading correction budget, RIGHT-correct trials
  bool lazyEscalationEnabled = true; // LAZY: escalating lazy-rat penalty on/off
};

/*  void parseStartCommand(const char* line, SessionConfig& cfg) ->
    Parse a START line into cfg. Grammar (mirrors protocol.build_start_command
    in the Python package -- that docstring is the canonical spec):

        START CL=<int> CR=<int> LAZY=<0|1>

    Order-independent; unknown keys ignored; any missing key keeps cfg's default
    (CL=0 CR=0 LAZY=1), so a bare "START" reproduces the legacy behavior. cfg
    must already hold the defaults (it does, by construction) before the call. */
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
      *eq = '\0'; // split key / value at '='
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

/* ===================== AntiBiasSelector ===================== */
/*  Adaptive anti-bias trial selection. Encapsulates the sliding-window estimate
    of the rat's recent EXPRESSED side preference (the ring buffer + running
    right-count) and the next-side draw that pushes AGAINST that bias, clamped so
    selection never collapses into a deterministic (cue-able) alternation, with a
    hard cap on same-side runs.

    Pin-agnostic: it speaks in `bool wentRight` / `bool presentedRight` and
    returns a TrialType* (the two go-trials are passed in at construction), so it
    carries no hardware knowledge. The tuning constants that DIFFER between the
    two sketches (pSideMin/Max, maxConsecutiveSide) are constructor arguments. */
class AntiBiasSelector
{
public:
  AntiBiasSelector(const TrialType *goRight, const TrialType *goLeft,
                   int biasWindow, float debiasStrength,
                   float pSideMin, float pSideMax, int maxConsecutiveSide)
      : _goRight(goRight), _goLeft(goLeft),
        _window(biasWindow < GRGL_MAX_BIAS_WINDOW ? biasWindow : GRGL_MAX_BIAS_WINDOW),
        _debias(debiasStrength), _pMin(pSideMin), _pMax(pSideMax),
        _maxRun(maxConsecutiveSide) {}

  /* Push the rat's expressed side choice (correct OR wrong well) into the ring,
     evicting the oldest once full and keeping the running right-count in sync.
     Called on every administered trial where a choice was expressed. */
  void recordChoice(bool wentRight)
  {
    if (_len == _window)
      _rightInWindow -= _ring[_idx]; // evict oldest before overwrite
    else
      _len++;
    _ring[_idx] = wentRight ? 1 : 0;
    _rightInWindow += _ring[_idx];
    _idx = (_idx + 1) % _window;
  }

  /* A lazy/no-poke (or poke-and-bail) trial expresses no side, but must not be
     invisible to the estimator -- otherwise a rat games it by simply not playing.
     We log a weak vote AGAINST having engaged the presented side. */
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

  int _ring[GRGL_MAX_BIAS_WINDOW] = {0};
  int _len = 0, _idx = 0, _rightInWindow = 0;
  bool _lastWasRight = false, _hasLast = false;
  int _selectedRun = 0;
};

/* ===================== AbstentionPenalty ===================== */
/*  The lazy-rat timeout and its escalation. Owns the consecutive-abstention
    counter and the GUI on/off toggle; the escalation math lives here once.

    nextDelay(stageAllowsEscalation) returns the ms timeout for one abstention:
      * enabled AND stageAllowsEscalation -> escalating
        (base + consecutive*step, clamped to max), and bumps the counter;
      * otherwise                          -> flat base, counter untouched.
    The full task passes stageAllowsEscalation = true; the EZ variant passes its
    `lazyRampActive` so escalation only kicks in once the holds have ramped, and
    the toggle COMPOSES with that gate (never overrides it).

    reset() zeroes the counter; each sketch calls it at its own engage point
    (full task: a completed correct trial; EZ: an odor poke). */
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
      _consecutive++; // escalate the NEXT consecutive abstention
      return d;
    }
    return _base; // flat base penalty; no escalation, no counter growth
  }

private:
  long _base, _step, _max;
  bool _enabled = true;
  int _consecutive = 0;
};

/* ===================== CorrectionPolicy ===================== */
/*  Per-side leading correction trials. Each side has an independent budget,
    consumed by COMPLETED (advancing) trials on that side; a correction REPEAT
    (an under-budget error) does not consume budget -- it re-presents the same
    side until answered, then the eventual completion consumes one unit.

    shouldRepeat(correctIsRight) -> repeat-on-error while that side is still under
    budget. onAdvance(correctIsRight) -> call once per advancing trial to consume
    its side's budget. Defaults (0/0) => never repeat => legacy bare-START behavior. */
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

#endif // GRGL_SESSION_H

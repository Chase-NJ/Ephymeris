/*
  TaskPins.h -- GENERATED, or the shipped default when nothing generated it.

  Ephymeris writes this file when it materialises a task profile: the operator's
  channel->pin map from the Rig tab, the profile's strobe selection, its stage
  count and its trial-type count, all as plain preprocessor definitions. It is
  included BEFORE <BehaviorBox.h>, whose own BoxPins.h / BoxStrobes.h guard every
  definition, so whatever is set here wins and everything else falls back to the
  box as built.

  THIS COPY IS THE DEFAULT. It declares only the two counts, so a checkout
  compiles and runs the historical GRGL 2-odor task with no app involved. Every
  pin and strobe below is therefore inherited, and that is deliberate: a second
  transcription of the pinout is exactly the mirroring this arrangement exists
  to end.

  Pure preprocessor. No types, no includes -- it is read before BehaviorBox.h has
  defined anything, and a `TrialType` here would not compile. The trial table
  lives in TaskTrials.h, which is included after.
*/

#ifndef TASK_PINS_H
#define TASK_PINS_H

/*  How many rows the ramp has, and which of them the START grammar can reach.
    The two must agree -- see BehaviorBox.h §5. GRGL does not ramp: it declares
    one row, which is the full task, and sends four stage tokens instead of
    twenty-five. */
#define NUM_STAGES 1
#define BOX_STAGE_KEY_LIST P_STAGE(0)

/*  How many trial types the table declares, and the two per-type key lists:
    pool weights and reward volumes, one of each per slot. Plain anti-bias
    selection ignores the weights, but they are still parsed: the same firmware
    runs a pool or weighted task, and the profile decides which by
    BOX_SELECTION_MODE below. */
#define BOX_MAX_TRIAL_TYPES 2
#define BOX_POOL_KEY_LIST      \
  P_INT("PW1", poolWeights[0]) \
  P_INT("PW2", poolWeights[1])
#define BOX_REWARD_KEY_LIST    \
  P_INT("RW1", rewardTimes[0]) \
  P_INT("RW2", rewardTimes[1])

/*  Which selector the loop uses.
      BOX_SELECT_ANTIBIAS -- draw a side against the animal's recent bias, then
                             a type from that side. Adds the abstention
                             escalator and per-side correction budgets.
      BOX_SELECT_POOL     -- a block-shuffled sequence built from poolWeights,
                             generated once at START. No policy objects, and a
                             completed trial always advances.
      BOX_SELECT_WEIGHTED -- the anti-bias side draw, then a type from that
                             side by poolWeights. For over-presenting a
                             stimulus the animal is still learning.
    Numbers rather than a bool so a further mode reads as an addition rather
    than an inversion. BehaviorBox.h guards the same three, so a header that
    omits them still compiles anti-bias. */
#define BOX_SELECT_ANTIBIAS 0
#define BOX_SELECT_POOL 1
#define BOX_SELECT_WEIGHTED 2
#define BOX_SELECTION_MODE BOX_SELECT_ANTIBIAS

#endif // TASK_PINS_H

/*
  TaskTrials.h -- GENERATED, or the shipped default when nothing generated it.

  THE TRIAL TABLE: which odor line is presented, which port answers it, which
  fluid line pays, and which strobe codes report all three. Ephymeris writes this
  from the profile's trial-type editor, resolving every channel NAME against the
  rig's wiring -- so "odor line 3 means go-left here" is an edit on one screen
  rather than a firmware change.

  Included AFTER <BehaviorBox.h>, because it constructs TrialType and needs the
  pin and strobe names. TaskPins.h is the half that comes first.

  THIS COPY IS THE DEFAULT: the lab's historical GRGL 2-odor discrimination.
    Odor 1  ->  go RIGHT  (sandalwood)
    Odor 3  ->  go LEFT   (orange extract)
  A checkout compiles and runs exactly that with no app involved.

  THE ORDER IS THE CONTRACT. Slot i here is `poolWeights[i]` (wire key PW<i+1>)
  AND `rewardTimes[i]` (wire key RW<i+1>), so reordering the table silently
  re-weights a pool task and re-pays every condition. The generator emits the
  table and both key lists together; a hand edit must too.
*/

#ifndef TASK_TRIALS_H
#define TASK_TRIALS_H

/*  `kTrials` is read by the selectors and by runTrial(). NOT const: each row's
    reward volume is the profile's default and the START line overwrites it
    (applyRewardTimes, RW<slot+1>). Everything else in a row stays const. */
static TrialType kTrials[] = {
    TrialType(
        true,              // go trial
        Odors[0],          // odor line 1
        rightWell,         // correct response port
        RIGHT_WELL_FL_1,   // index into Fluids[]
        BF_ODOR_1_ON,      // stimulus onset
        BF_FLUID_R,        // reward delivered
        BF_STOP_FLUID_G_R, // reward line closed
        100                // reward volume (ms open); RW1 overrides
        ),
    TrialType(
        true,
        Odors[2],          // odor line 3
        leftWell,
        LEFT_WELL_FL_1,
        BF_ODOR_3_ON,
        BF_FLUID_L,
        BF_STOP_FLUID_G_L,
        100                // RW2 overrides
        ),
};

static const int kTrialCount = (int)(sizeof(kTrials) / sizeof(kTrials[0]));

/*  The table cannot be longer than the arrays that index it -- poolWeights[],
    rewardTimes[] and the selector's two side lists are all BOX_MAX_TRIAL_TYPES
    long. Generated
    together, so this only fires on a hand edit; it fires at build time, which is
    the point. */
static_assert(kTrialCount <= BOX_MAX_TRIAL_TYPES,
              "more trial types than BOX_MAX_TRIAL_TYPES -- raise it in "
              "TaskPins.h, or the pool weights, the reward volumes and the "
              "side lists cannot address them all");

#endif // TASK_TRIALS_H

/*
  TaskPins.h -- the TASK SIMULATOR's stand-in for the header Ephymeris generates
  beside every sketch (docs/TASKS.md#simulating-a-task).

  A generated TaskPins.h fixes one task's sizes, pins and strobe codes at compile
  time. The simulator is built once and must run any task, so here:

    * the counts are ceilings. The ramp and the two per-type key lists are as
      long as the simulator will accept; a ramp row the host never sends stays
      at STAGE_UNREACHABLE and a weight it never sends stays 0, which is how
      BehaviorBox.h already treats an unsent slot, so a smaller task runs
      exactly as its own build would;
    * every BF_* code is read from a table the host fills before the session
      (tasksim.cpp), from the machine's own vocabulary, by name. The trial
      runner only ever passes a code to emitStrobe(), so a variable serves;
    * the pins are arbitrary. Nothing outside the simulator sees a pin: the
      host speaks of the light, the vacuum, an odor line and a fluid line.

  Pure preprocessor plus one array, as the generated header is: it is read
  before BehaviorBox.h has defined anything.
*/

#ifndef TASK_PINS_H
#define TASK_PINS_H

#define NUM_STAGES 16
#define BOX_STAGE_KEY_LIST                                              \
  P_STAGE(0) P_STAGE(1) P_STAGE(2) P_STAGE(3) P_STAGE(4) P_STAGE(5)     \
  P_STAGE(6) P_STAGE(7) P_STAGE(8) P_STAGE(9) P_STAGE(10) P_STAGE(11)   \
  P_STAGE(12) P_STAGE(13) P_STAGE(14) P_STAGE(15)

#define BOX_MAX_TRIAL_TYPES 24
#define BOX_POOL_KEY_LIST                                               \
  P_INT("PW1", poolWeights[0]) P_INT("PW2", poolWeights[1])             \
  P_INT("PW3", poolWeights[2]) P_INT("PW4", poolWeights[3])             \
  P_INT("PW5", poolWeights[4]) P_INT("PW6", poolWeights[5])             \
  P_INT("PW7", poolWeights[6]) P_INT("PW8", poolWeights[7])             \
  P_INT("PW9", poolWeights[8]) P_INT("PW10", poolWeights[9])            \
  P_INT("PW11", poolWeights[10]) P_INT("PW12", poolWeights[11])         \
  P_INT("PW13", poolWeights[12]) P_INT("PW14", poolWeights[13])         \
  P_INT("PW15", poolWeights[14]) P_INT("PW16", poolWeights[15])         \
  P_INT("PW17", poolWeights[16]) P_INT("PW18", poolWeights[17])         \
  P_INT("PW19", poolWeights[18]) P_INT("PW20", poolWeights[19])         \
  P_INT("PW21", poolWeights[20]) P_INT("PW22", poolWeights[21])         \
  P_INT("PW23", poolWeights[22]) P_INT("PW24", poolWeights[23])
#define BOX_REWARD_KEY_LIST                                             \
  P_INT("RW1", rewardTimes[0]) P_INT("RW2", rewardTimes[1])             \
  P_INT("RW3", rewardTimes[2]) P_INT("RW4", rewardTimes[3])             \
  P_INT("RW5", rewardTimes[4]) P_INT("RW6", rewardTimes[5])             \
  P_INT("RW7", rewardTimes[6]) P_INT("RW8", rewardTimes[7])             \
  P_INT("RW9", rewardTimes[8]) P_INT("RW10", rewardTimes[9])            \
  P_INT("RW11", rewardTimes[10]) P_INT("RW12", rewardTimes[11])         \
  P_INT("RW13", rewardTimes[12]) P_INT("RW14", rewardTimes[13])         \
  P_INT("RW15", rewardTimes[14]) P_INT("RW16", rewardTimes[15])         \
  P_INT("RW17", rewardTimes[16]) P_INT("RW18", rewardTimes[17])         \
  P_INT("RW19", rewardTimes[18]) P_INT("RW20", rewardTimes[19])         \
  P_INT("RW21", rewardTimes[20]) P_INT("RW22", rewardTimes[21])         \
  P_INT("RW23", rewardTimes[22]) P_INT("RW24", rewardTimes[23])

/*  One simulator is built per selection mode, because the sketch picks its
    selector with #if (GRGL.ino). The build passes BBSIM_SELECTION_MODE. */
#define BOX_SELECT_ANTIBIAS 0
#define BOX_SELECT_POOL 1
#define BOX_SELECT_WEIGHTED 2
#ifndef BBSIM_SELECTION_MODE
#error "Build the task simulator with -DBBSIM_SELECTION_MODE=0, 1 or 2 (simulation/build.py)."
#endif
#define BOX_SELECTION_MODE BBSIM_SELECTION_MODE

/*  No sync line: there is no recording to pulse for, and the pulse's
    microsecond waits are not part of the trial's millisecond clock. */
#define BOX_PIN_SYNC_OUT -1

#define BOX_NUM_ODORS 24
#define BOX_ODOR_PINS {10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, \
                       22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33}
#define BOX_NUM_FLUIDS 8
#define BOX_FLUID_PINS {42, 43, 44, 45, 46, 47, 48, 49}

/*  Every code the trial runner and the sketch emit by name. A row's own codes
    (its onset, its fluid pair, its TRIAL_TYPE) arrive on its ROW line instead. */
#define BBSIM_CODE_NAMES(X)                                             \
  X(CORRECT) X(END_SESSION) X(END_TRIAL) X(INVALID_TRIAL) X(LAZY_RAT)   \
  X(LIGHTS_OFF) X(LIGHTS_ON) X(ODOR_OFF) X(ODOR_POKE) X(ODOR_UNPOKE)    \
  X(ODOR_UNPOKE_EARLY) X(ODOR_UNPOKE_EARLY_SAMPLING) X(RESP_OMIT)       \
  X(START_SESSION) X(TRIAL_GO_LEFT) X(TRIAL_GO_RIGHT) X(TRIAL_NO_GO)    \
  X(TRIAL_START) X(WATER_POKE_ERROR_L) X(WATER_POKE_ERROR_R)            \
  X(WATER_POKE_L) X(WATER_POKE_NONE) X(WATER_POKE_R)                    \
  X(WATER_UNPOKE_EARLY_L) X(WATER_UNPOKE_EARLY_R) X(WATER_UNPOKE_L)     \
  X(WATER_UNPOKE_R)

enum
{
#define X(name) BBSIM_##name,
  BBSIM_CODE_NAMES(X)
#undef X
  BBSIM_CODE_COUNT
};
static int bbsim_code[BBSIM_CODE_COUNT];

#define BF_CORRECT (bbsim_code[BBSIM_CORRECT])
#define BF_END_SESSION (bbsim_code[BBSIM_END_SESSION])
#define BF_END_TRIAL (bbsim_code[BBSIM_END_TRIAL])
#define BF_INVALID_TRIAL (bbsim_code[BBSIM_INVALID_TRIAL])
#define BF_LAZY_RAT (bbsim_code[BBSIM_LAZY_RAT])
#define BF_LIGHTS_OFF (bbsim_code[BBSIM_LIGHTS_OFF])
#define BF_LIGHTS_ON (bbsim_code[BBSIM_LIGHTS_ON])
#define BF_ODOR_OFF (bbsim_code[BBSIM_ODOR_OFF])
#define BF_ODOR_POKE (bbsim_code[BBSIM_ODOR_POKE])
#define BF_ODOR_UNPOKE (bbsim_code[BBSIM_ODOR_UNPOKE])
#define BF_ODOR_UNPOKE_EARLY (bbsim_code[BBSIM_ODOR_UNPOKE_EARLY])
#define BF_ODOR_UNPOKE_EARLY_SAMPLING (bbsim_code[BBSIM_ODOR_UNPOKE_EARLY_SAMPLING])
#define BF_RESP_OMIT (bbsim_code[BBSIM_RESP_OMIT])
#define BF_START_SESSION (bbsim_code[BBSIM_START_SESSION])
#define BF_TRIAL_GO_LEFT (bbsim_code[BBSIM_TRIAL_GO_LEFT])
#define BF_TRIAL_GO_RIGHT (bbsim_code[BBSIM_TRIAL_GO_RIGHT])
#define BF_TRIAL_NO_GO (bbsim_code[BBSIM_TRIAL_NO_GO])
#define BF_TRIAL_START (bbsim_code[BBSIM_TRIAL_START])
#define BF_WATER_POKE_ERROR_L (bbsim_code[BBSIM_WATER_POKE_ERROR_L])
#define BF_WATER_POKE_ERROR_R (bbsim_code[BBSIM_WATER_POKE_ERROR_R])
#define BF_WATER_POKE_L (bbsim_code[BBSIM_WATER_POKE_L])
#define BF_WATER_POKE_NONE (bbsim_code[BBSIM_WATER_POKE_NONE])
#define BF_WATER_POKE_R (bbsim_code[BBSIM_WATER_POKE_R])
#define BF_WATER_UNPOKE_EARLY_L (bbsim_code[BBSIM_WATER_UNPOKE_EARLY_L])
#define BF_WATER_UNPOKE_EARLY_R (bbsim_code[BBSIM_WATER_UNPOKE_EARLY_R])
#define BF_WATER_UNPOKE_L (bbsim_code[BBSIM_WATER_UNPOKE_L])
#define BF_WATER_UNPOKE_R (bbsim_code[BBSIM_WATER_UNPOKE_R])

#endif // TASK_PINS_H

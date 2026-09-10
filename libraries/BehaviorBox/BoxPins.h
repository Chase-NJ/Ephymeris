/*
  BoxPins.h
  =========
  WHERE EVERY CHANNEL IS ON THIS BOX.

  The values below are the Hart-lab behavior box as built: three IR sensors, a
  trial light, a normally-open vacuum, twelve odor solenoids and four fluid
  solenoids. They were `const int` in BehaviorBox.h until the wiring became
  something an operator could change.

  EVERY DEFINITION IS GUARDED. A sketch that includes a generated `TaskPins.h`
  BEFORE <BehaviorBox.h> overrides whichever of these it declares, and inherits
  the rest. That is the whole mechanism by which Ephymeris compiles a task
  profile against this rig's own wiring:

      #include "TaskPins.h"     // generated -- pins, stage count, baud
      #include <BehaviorBox.h>  // everything else

  A sketch with no generated header (the utility sketch, the simulator, anything
  opened straight from the Arduino IDE) compiles against the numbers here and
  behaves exactly as it always did.

  THE PIN NUMBERS ARE NOT MONOTONIC past odor line 6 -- 22,24,26,28,30,32 then
  23,25,27,29,31,33. Nothing may compute a pin from an index; every consumer
  reads the table.
*/

#ifndef BOX_PINS_H
#define BOX_PINS_H

/* ---- IR sensors ---------------------------------------------------------- */
#ifndef BOX_PIN_ODOR_PORT
#define BOX_PIN_ODOR_PORT 2
#endif
#ifndef BOX_PIN_RIGHT_WELL
#define BOX_PIN_RIGHT_WELL 3
#endif
#ifndef BOX_PIN_LEFT_WELL
#define BOX_PIN_LEFT_WELL 4
#endif

/* ---- Trial light & normally-open vacuum ---------------------------------- */
#ifndef BOX_PIN_TRIAL_LIGHT
#define BOX_PIN_TRIAL_LIGHT 36
#endif
#ifndef BOX_PIN_VACUUM
#define BOX_PIN_VACUUM 40
#endif

/* ---- Solenoid banks ------------------------------------------------------ */
/*  NUM_ODORS/NUM_FLUIDS are the SIZE of the tables below and are not a task
    setting -- a box has the lines it has. A different box generation overrides
    the tables and these together, or the initialiser does not fit. */
#ifndef BOX_NUM_ODORS
#define BOX_NUM_ODORS 12
#endif
#ifndef BOX_NUM_FLUIDS
#define BOX_NUM_FLUIDS 4
#endif

#ifndef BOX_ODOR_PINS
#define BOX_ODOR_PINS {22, 24, 26, 28, 30, 32, 23, 25, 27, 29, 31, 33}
#endif

/*  Fluid lines, in the order the reward index addresses them:
    { left 1, left 2, right 1, right 2 }. */
#ifndef BOX_FLUID_PINS
#define BOX_FLUID_PINS {42, 44, 46, 48}
#endif

/* ---- The names the trial runner and every sketch use --------------------- */
const int odorPort  = BOX_PIN_ODOR_PORT;
const int rightWell = BOX_PIN_RIGHT_WELL;
const int leftWell  = BOX_PIN_LEFT_WELL;

const int trialLight = BOX_PIN_TRIAL_LIGHT;
const int vac        = BOX_PIN_VACUUM;

const int NUM_ODORS  = BOX_NUM_ODORS;
const int NUM_FLUIDS = BOX_NUM_FLUIDS;

const int Odors[NUM_ODORS]   = BOX_ODOR_PINS;
const int Fluids[NUM_FLUIDS] = BOX_FLUID_PINS;

/*  Indices into Fluids[], plus the sentinel a
    no-go trial type carries where a reward index would be. Names rather than
    numbers at the call site, because 0 and 2 are indistinguishable in a
    constructor argument list and one of them waters the wrong well. */
#define LEFT_WELL_FL_1  0
#define LEFT_WELL_FL_2  1
#define RIGHT_WELL_FL_1 2
#define RIGHT_WELL_FL_2 3
#define SENTINEL       -1

/*  Serial rate. Declared here rather than per-sketch because it is a property
    of the link to the host, and it used to be restated in nine files. Ephymeris
    pushes the same number as `settings.defaultBaud`; a mismatch is silent --
    the console prints nothing legible rather than reporting an error, so it
    reads as a dead board. */
#ifndef BOX_BAUD_RATE
#define BOX_BAUD_RATE 115200
#endif

#endif // BOX_PINS_H

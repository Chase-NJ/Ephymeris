/*==================================
BOX Utility -- the one utility sketch for a behaviour box.

Direct control, priming and a hardware self-test, driven entirely from
Ephymeris Debug Mode, and the resting firmware the app keeps on every idle box
(the hardware utility baseline). Everything it does is in the shared library's
BoxUtility.h; everything it knows about THIS box -- which outputs and beams
exist, their pins, what the Rig page calls them -- is in UtilityChannels.h,
which Ephymeris generates from the rig's wiring, together with this folder's
task.json controls (docs/TASKS.md#the-box-utility).

So there is nothing here to edit for a rewired or relabelled box: change the
Rig page, and the app rebuilds this sketch to match.

It consolidates three retired sketches: PRIME_Lines (latch a line open),
PRIME_Bolus (timed pulse) and TEST_Box (self-test). Archived runs that name
them still decode through task.json's legacyNames.
==================================*/

#include "TaskPins.h"        // GENERATED: this rig's pins and strobe codes. First.
#include "UtilityChannels.h" // GENERATED: this rig's outputs and beams, by name.
#include <BehaviorBox.h>
#include <BoxUtility.h>

void setup() { box_utility::setup(); }

void loop() { box_utility::loop(); }

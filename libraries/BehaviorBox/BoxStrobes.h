/*
  BoxStrobes.h
  ============
  THE STROBE VOCABULARY -- the BF_* codes this firmware emits.

  APPEND-ONLY, AND THAT IS A DATA GUARANTEE RATHER THAN A STYLE. Four years of
  recorded sessions carry these numbers. A code is never renumbered, never
  repurposed and never deleted, because reissuing one silently merges two
  unrelated event types in any analysis that spans the change -- an error that
  produces a plausible answer instead of a failure.

  The authority is Ephymeris' `rig/schema/strobe_vocab.v1.json`, which also
  records the codes whose emitters are gone (reserved forever, never reissued)
  and the per-port families a response port reports with. This file is the
  firmware's half of that mirror, and a generated `TaskPins.h` may override any
  of it -- which is how a profile that presents odor line 7 gets an onset code
  the vocabulary already reserves.

  ODOR ONSET CODES RUN 101-109 AND THEN 114-116. The gap is not an oversight
  and not a pattern to extrapolate from: 110-113 are retired codes that 29
  recorded sessions contain, so they can never be reissued. Nothing may compute
  a code from an odor index -- odor 9 is 109 and odor 10 is 114.
*/

#ifndef BOX_STROBES_H
#define BOX_STROBES_H

/* ---- Session and trial structure ----------------------------------------- */
#ifndef BF_START_SESSION
#define BF_START_SESSION 221 // Sent at recording start (timestamp 0)
#endif
#ifndef BF_LIGHTS_ON
#define BF_LIGHTS_ON 222 // Sent when trialLight is written HIGH
#endif
#ifndef BF_LAZY_RAT
#define BF_LAZY_RAT 223 // Sent when rat fails to initiate trial
#endif
#ifndef BF_ODOR_POKE
#define BF_ODOR_POKE 224 // Sent when rat pokes odor port
#endif
#ifndef BF_ODOR_UNPOKE_EARLY
#define BF_ODOR_UNPOKE_EARLY 225 // Sent when rat fails to hold odor poke for odorPokeHold
#endif
#ifndef BF_ODOR_UNPOKE
#define BF_ODOR_UNPOKE 226 // Sent after rat successfully samples odor
#endif
#ifndef BF_LIGHTS_OFF
#define BF_LIGHTS_OFF 233 // Sent when trialLight is written LOW inside a trial
#endif
#ifndef BF_INVALID_TRIAL
#define BF_INVALID_TRIAL 234 // Trial aborted (lazy rat or poke-hold failure)
#endif
#ifndef BF_END_CORRECT_ITI
#define BF_END_CORRECT_ITI 242 // Sent after correct-response intertrial interval
#endif
#ifndef BF_END_INCORRECT_ITI
#define BF_END_INCORRECT_ITI 243 // Sent after errorDelay intertrial interval
#endif
#ifndef BF_END_SESSION
#define BF_END_SESSION 246 // Sent at end of session (sessionComplete = true)
#endif
#ifndef BF_ODOR_OFF
#define BF_ODOR_OFF 247 // Sent when we close N.O.V. (directing odor AWAY from port)
#endif
#ifndef BF_RESP_OMIT
#define BF_RESP_OMIT 262 // Response window expired after complete sampling
#endif

/* ---- Response ports ------------------------------------------------------ *
   Six codes per port, and the app resolves which six by the port's declared
   SLOT rather than by its name. Slots 1 and 2 are these historical _L and _R
   families, so a recorded session decodes exactly as it always did. */
#ifndef BF_WATER_POKE_L
#define BF_WATER_POKE_L 248 // Sent when rat pokes left fluid well
#endif
#ifndef BF_WATER_POKE_R
#define BF_WATER_POKE_R 249 // Sent when rat pokes right fluid well
#endif
#ifndef BF_WATER_UNPOKE_EARLY_L
#define BF_WATER_UNPOKE_EARLY_L 250 // Sent when rat fails to hold left well for fluidWellHold
#endif
#ifndef BF_WATER_UNPOKE_EARLY_R
#define BF_WATER_UNPOKE_EARLY_R 251 // Sent when rat fails to hold right well for fluidWellHold
#endif
#ifndef BF_FLUID_L
#define BF_FLUID_L 252 // Delivered at start of first drop on left
#endif
#ifndef BF_FLUID_R
#define BF_FLUID_R 253 // Delivered at start of first drop on right
#endif
#ifndef BF_WATER_UNPOKE_L
#define BF_WATER_UNPOKE_L 254 // Sent when rat unpokes left well
#endif
#ifndef BF_WATER_UNPOKE_R
#define BF_WATER_UNPOKE_R 255 // Sent when rat unpokes right well
#endif
#ifndef BF_WATER_POKE_NONE
#define BF_WATER_POKE_NONE 256 // After a correct response on a No-Go trial
#endif
#ifndef BF_WATER_POKE_ERROR_L
#define BF_WATER_POKE_ERROR_L 257 // Sent when rat incorrectly responds at left well
#endif
#ifndef BF_WATER_POKE_ERROR_R
#define BF_WATER_POKE_ERROR_R 258 // Sent when rat incorrectly responds at right well
#endif
#ifndef BF_STOP_FLUID_G_R
#define BF_STOP_FLUID_G_R 357 // Sent when we stop right-well fluid delivery
#endif
#ifndef BF_STOP_FLUID_G_L
#define BF_STOP_FLUID_G_L 369 // Sent when we stop left-well fluid delivery
#endif

/* ---- Stimulus onset, one code per odor line ------------------------------ */
#ifndef BF_ODOR_1_ON
#define BF_ODOR_1_ON 101
#endif
#ifndef BF_ODOR_2_ON
#define BF_ODOR_2_ON 102
#endif
#ifndef BF_ODOR_3_ON
#define BF_ODOR_3_ON 103
#endif
#ifndef BF_ODOR_4_ON
#define BF_ODOR_4_ON 104
#endif
#ifndef BF_ODOR_5_ON
#define BF_ODOR_5_ON 105
#endif
#ifndef BF_ODOR_6_ON
#define BF_ODOR_6_ON 106
#endif
/*  Lines 7-12 were plumbed and unusable as discriminanda for years, because
    only six could announce an onset. They continue the original run as closely
    as the reserved block allows: 107-109, then a jump to 114.

    THE JUMP IS PERMANENT. 110-113 are the retired dummy-solenoid-click codes,
    present in 29 recorded sessions, and a number that has been emitted once can
    never be reissued -- a 110 in a file would otherwise mean one thing before a
    date and another after it. This is the live example of why nothing computes
    an odor's code from its index. */
#ifndef BF_ODOR_7_ON
#define BF_ODOR_7_ON 107
#endif
#ifndef BF_ODOR_8_ON
#define BF_ODOR_8_ON 108
#endif
#ifndef BF_ODOR_9_ON
#define BF_ODOR_9_ON 109
#endif
/*  110-113 are retired. See above. */
#ifndef BF_ODOR_10_ON
#define BF_ODOR_10_ON 114
#endif
#ifndef BF_ODOR_11_ON
#define BF_ODOR_11_ON 115
#endif
#ifndef BF_ODOR_12_ON
#define BF_ODOR_12_ON 116
#endif

#endif // BOX_STROBES_H

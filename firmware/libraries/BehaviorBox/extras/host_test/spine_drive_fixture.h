/*
  spine_drive_fixture.h -- spine_fixture.h's table, with DRIVEN OUTPUTS, for the
  host test of BoxSpine.h only (docs/TASKS.md#driven-outputs).

  The same six states, but the Present (state 1) also holds three driven
  outputs HIGH, each from its own parameter slots:

    bit 3  a PWM line on pin 45 at duty PD
    bit 4  a tone on pin 12 at TF Hz
    bit 5  a pulse train on pin 11 at TH Hz, TW ms wide, for TL ms

  The channel codes are fixture codes, as in spine_fixture.h.
*/
#ifndef SPINE_FIXTURE_H
#define SPINE_FIXTURE_H

#define BF_PORT_ENTER 40
#define BF_PORT_EXIT 41
#define BF_LIGHT_ON 42
#define BF_LIGHT_OFF 43
#define BF_SAMPLE_ON 44
#define BF_SAMPLE_OFF 45
#define BF_FLUID_ON 46
#define BF_FLUID_OFF 47
#define BF_LED_ON 48
#define BF_LED_OFF 49
#define BF_TONE_ON 50
#define BF_TONE_OFF 51
#define BF_LASER_TRAIN_ON 52
#define BF_LASER_TRAIN_OFF 53
#define BF_BLOCK_START 54

#define SPINE_INTERP 6

#define SPINE_NUM_STATES 6
#define SPINE_STATES { \
  {0x1UL, 0x1UL, 255, 255, 255, 255, 255, 255, 0, 1, 1, 0}, \
  {0x3BUL, 0x1UL, 1, 1, 2, 255, 255, 255, 1, 1, 0, 0}, \
  {0x0UL, 0x0UL, 255, 255, 255, 5, 3, 4, 0, 0, 0, 1}, \
  {0x4UL, 0x0UL, 4, 4, 4, 255, 255, 255, 0, 0, 0, 0}, \
  {0x0UL, 0x0UL, 2, 2, 5, 255, 255, 255, 0, 0, 0, 0}, \
  {0x0UL, 0x0UL, 3, 3, 0, 255, 255, 255, 0, 0, 0, 0} }
#define SPINE_NUM_EDGES 2
#define SPINE_EDGES { {0, 1, 1}, {0, 2, 5} }

#define SPINE_COUNT_MIN 255
#define SPINE_COUNT_MAX 255
#define SPINE_NUM_RATIOS 0
#define SPINE_RATIOS { 0 }

#define SPINE_NUM_INPUTS 1
#define SPINE_INPUTS { {2, 0, 0, BF_PORT_ENTER, BF_PORT_EXIT} }
#define SPINE_NUM_OUTPUTS 6
#define SPINE_OUTPUTS { {36, BF_LIGHT_ON, BF_LIGHT_OFF}, {22, BF_SAMPLE_ON, BF_SAMPLE_OFF}, \
  {44, BF_FLUID_ON, BF_FLUID_OFF}, {45, BF_LED_ON, BF_LED_OFF}, {12, BF_TONE_ON, BF_TONE_OFF}, \
  {11, BF_LASER_TRAIN_ON, BF_LASER_TRAIN_OFF} }
#define SPINE_NUM_DRIVES 3
#define SPINE_DRIVES { {3, SPINE_DRIVE_PWM, 6}, {4, SPINE_DRIVE_TONE, 7}, {5, SPINE_DRIVE_TRAIN, 8} }
#define SPINE_HAS_TONE 1

#define SPINE_NUM_PARAMS 11
#define SPINE_PARAMS { \
  {"NT", 2UL, 1UL, 10000UL}, \
  {"T1", 100UL, 0UL, 3600000UL}, \
  {"T2", 0UL, 0UL, 3600000UL}, \
  {"T3", 50UL, 0UL, 3600000UL}, \
  {"RW", 30UL, 0UL, 5000UL}, \
  {"RP", 1000UL, 0UL, 1000UL}, \
  {"PD", 128UL, 0UL, 255UL}, \
  {"TF", 4000UL, 31UL, 65535UL}, \
  {"TH", 20UL, 1UL, 100UL}, \
  {"TW", 5UL, 1UL, 999UL}, \
  {"TL", 60UL, 0UL, 3600000UL} }

/* One block that never ends: NT caps the session. */
#define SPINE_TRIALS_SLOT 0
#define SPINE_NUM_BLOCKS 1
#define SPINE_BLOCKS { {0, 1, 0, 255, 255, 255, 255, 255, 255, 255, 0} }
#define SPINE_BLOCK_SKIPPED 192
#define SPINE_NUM_ENTRIES 0
#define SPINE_NUM_OVERRIDES 0
#define SPINE_NUM_PAIRS 0

#endif // SPINE_FIXTURE_H

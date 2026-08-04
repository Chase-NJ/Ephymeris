#ifndef TASK_TABLE_H
#define TASK_TABLE_H

/* ============================================================= *
 *  TaskTable.h -- the wire and memory layout of a compiled task.
 *
 *  This is the contract between the Python compiler and the firmware
 *  interpreter. It is the ONE file that both sides must agree on byte for byte,
 *  so it deliberately contains no logic: only records, their field order, and
 *  the static assertions that keep them the size the RAM budget assumes.
 *
 *  DEPENDS ONLY ON <stdint.h> AND THE GENERATED LIMITS, ON PURPOSE. No
 *  Arduino.h, no BehaviorBox.h. That is what lets extras/host_test/ compile and
 *  check the layout on the host with a plain clang++ invocation, and what will
 *  let the Python compiler's own tests parse this header rather than duplicating
 *  the numbers. TaskLimits.h itself includes nothing, so the property survives.
 *
 *  Sizes here are MEASURED, not chosen. See docs/spikes/avr-ram.md: an
 *  ATmega2560 build of the probe matched the arithmetic below exactly, with zero
 *  struct padding, in all eight sweep configurations.
 * ============================================================= */

#include <stdint.h>

#include "TaskLimits.h" // generated; owns TG_NO_STROBE and every capacity number

/*  Why the table lives in SRAM and not PROGMEM.

    An uploaded table CANNOT live in PROGMEM: flash is not writable at runtime
    without a bootloader trick this project is not doing, so PROGMEM would only
    help for a table compiled in -- which defeats the entire point of shipping
    tasks as data. The whole table is therefore SRAM, and that is the assumption
    the budget in docs/spikes/avr-ram.md is built on.

    PROGMEM remains right for two things, neither of which is the table: the
    strobe NAME table (debug output only), and a fallback template compiled in so
    a box with no uploaded table refuses cleanly instead of running garbage. */

/* ---------------------------------------------------------------- *
 *  Node types -- the six primitives. Nothing else is representable,
 *  which is what keeps the interpreter fixed and the graph tractable.
 * ---------------------------------------------------------------- */
enum TgNodeType : uint8_t
{
  TG_DELAY = 0,      // fixed timer; watches nothing; exits on TIMEOUT
  TG_WAIT_ENTRY = 1, // window to act within; exits on ENTER(ch) or TIMEOUT
  TG_HOLD = 2,       // duration that must be sustained; exits HELD or BROKEN
  TG_WAIT_EXIT = 3,  // no timeout; exits on EXIT
  TG_PULSE = 4,      // actuator open-time == delivered magnitude; exits DONE
  TG_TERMINAL = 5    // returns to trial selection; exits ADVANCE or REPEAT
};

enum TgTrigger : uint8_t
{
  TG_TRIG_TIMEOUT = 0,
  TG_TRIG_ENTER = 1,
  TG_TRIG_HELD = 2,
  TG_TRIG_BROKEN = 3,
  TG_TRIG_EXIT = 4,
  TG_TRIG_DONE = 5,
  TG_TRIG_ADVANCE = 6,
  TG_TRIG_REPEAT = 7
};

/*  Sentinels. Out-of-band on purpose.

    Firmware's StageStep uses 32767 as its "never" trial count while
    lazyDelayMax legitimately reaches 30000 -- a legal value one step away from a
    magic one (BehaviorBox.h:531-536). That collision is not reproduced here:
    every sentinel below is outside the range its field can legally hold.
    See docs/decisions.md D6.

    TG_NO_STROBE lives in the generated TaskLimits.h, next to TG_STROBE_MAX --
    the two are only meaningful in relation to each other, and a sentinel defined
    apart from the range it sits outside of is a sentinel that can drift into it. */

/*  RUNTIME BINDINGS.

    Seven states emit a strobe that depends on the TRIAL rather than on the graph:
    which stimulus was presented, which port was poked, which line rewarded. The
    compiler's listing shows those as `@ports[$ch].enter_code`, but that string
    never reaches the board -- so the selector rides in the strobe field itself.

    Real codes are capped at 999 by the wire format, so anything at or above
    TG_BIND_BASE is unambiguously a binding and no extra field is needed. */
#define TG_BIND_BASE 0xFF00
#define TG_BIND(sel) ((uint16_t)(TG_BIND_BASE | (sel)))
#define TG_IS_BOUND(s) ((s) >= TG_BIND_BASE && (s) != TG_NO_STROBE)
#define TG_SELECTOR(s) ((uint8_t)((s) & 0xFF))

/*  Selectors 0..3 are stimulus-on for sampling stages 0..3. The stage is known at
    COMPILE time -- the unroll is static -- so carrying it here means the
    interpreter needs no stage counter, and therefore has no stage counter to
    drift. */
#define TG_BIND_STIM_ON_0 0
#define TG_BIND_STIM_ON_3 3
#define TG_BIND_PORT_ENTER 4         // indexed by the channel that fired
#define TG_BIND_PORT_ERROR 5
#define TG_BIND_PORT_BREAK 6
#define TG_BIND_PORT_EXIT 7
#define TG_BIND_TARGET_REWARD 8      // indexed by the trial's target port
#define TG_BIND_TARGET_REWARD_STOP 9
#define TG_BIND_TARGET_EXIT 10

/*  Actuator channels can be trial-bound too. Pins are <= 53, so the high byte is
    free for the same trick. */
#define TG_CH_BIND_STIM_EMITTER_0 0xF0     // + stage
#define TG_CH_BIND_TARGET_REWARD_LINE 0xF4
#define TG_CH_BIND_ALL_EMITTERS 0xF5       // abort paths: clear whatever is on

/*  Guard and effect opcodes. Small closed sets the interpreter switches on, so
    they are numbers on the wire and names in the listing. Stable by hand rather
    than assigned on demand: a table that renumbered itself as specs changed would
    be fine in Python and catastrophic on the wire. */
#define TG_GUARD_NONE 0
#define TG_GUARD_IS_TARGET 1
#define TG_GUARD_CORRECTION 2

#define TG_EFFECT_NONE 0
#define TG_EFFECT_ADVANCE 1
#define TG_EFFECT_REPEAT 2

/*  A duration resolved per trial rather than from the timing vector: the reward
    pulse, whose width comes from the chosen port. Out of band because
    TG_MAX_TIMING is 64, so 0xFF can never be a real index. */
#define TG_DUR_FROM_TRIAL 0xFF
#define TG_NO_TARGET 0xFF    // withhold trial: no correct port exists
#define TG_NO_NODE 0xFF      // unreachable / unset

/* ---------------------------------------------------------------- *
 *  Records
 * ---------------------------------------------------------------- */

/*  One node. 8 bytes.

    `strobe` is uint16 and that is NOT negotiable. Five codes already exceed a
    byte -- WATER_POKE_NONE 256, WATER_POKE_ERROR_L/R 257/258, STOP_FLUID_G_R 357,
    STOP_FLUID_G_L 369 (BehaviorBox.h:117-121). Narrowing this to uint8 to save
    24 bytes on a 64-state table would silently truncate five real events.
    See docs/decisions.md D5. */
struct TgNode
{
  uint8_t type;        // TgNodeType
  uint8_t durIdx;      // index into the timing vector -- NEVER a literal duration
  uint16_t strobe;     // entry strobe, or TG_NO_STROBE
  uint8_t watchMask;   // input channels polled while resident
  uint8_t actionIdx;   // first entry action
  uint8_t actionCount; // number of entry actions
  uint8_t edgeIdx;     // first outgoing edge; count is implicit to the next node
};

/*  One edge. 4 bytes. Edges are stored contiguously per node, so a node holds an
    offset rather than a pointer: no dynamic allocation and no indirection in the
    trial loop, per the Phase 0 constraint. */
struct TgEdge
{
  uint8_t trigger; // TgTrigger
  uint8_t guard;   // predicate over the trial binding, e.g. port == target
  uint8_t target;  // destination node index
  uint8_t effect;  // score / advance / repeat / update policy
};

/*  One entry action: set or clear an actuator channel, applied the instant the
    node is entered. 2 bytes. */
struct TgAction
{
  uint8_t channel;
  uint8_t op; // 0 = clear, 1 = set
};

/*  One trial type. 8 bytes. Mirrors firmware's TrialType (BehaviorBox.h:169-184)
    so the Phase 3 equivalence gate compares like with like.

    The stimulus slots are spelled out rather than declared as stimulus[4] so the
    generated layout assertions can take offsetof() on each one. An array would
    hide a field-order change from the very check that exists to catch it. */
struct TgTrialType
{
  uint8_t stimulus0;    // INDEX into the stimulus table, not a pin
  uint8_t stimulus1;
  uint8_t stimulus2;
  uint8_t stimulus3;
  uint8_t target;       // correct port, or TG_NO_TARGET on a withhold trial
  uint8_t weight;       // relative frequency; ignored where selection is live
  uint8_t rewardLine;   // actuator channel opened on reward
  uint8_t rewardDurIdx; // timing index -- pulse width IS the delivered volume
};

/*  One response port. 16 bytes.

    What a `@ports[$ch]` binding resolves against. Without it the board knows a
    poke happened but not which code reports it -- which is the difference between
    a recording and a recording you can analyse. */
struct TgPort
{
  uint8_t channel;          // input pin
  uint8_t rewardLine;       // actuator pin, or TG_NO_TARGET
  uint16_t enterCode;       // poked -- emitted BEFORE correctness is known
  uint16_t errorCode;       // poked, and it was the wrong port
  uint16_t breakCode;       // released before the response hold completed
  uint16_t exitCode;        // left the port after a completed bout
  uint16_t rewardCode;
  uint16_t rewardStopCode;
  uint8_t rewardDurIdx;     // timing index -- pulse width IS the volume
  uint8_t _pad;
};

/*  One stimulus. 4 bytes. `onCode` is the one strobe in the whole graph that
    identifies WHAT was presented. */
struct TgStimulus
{
  uint8_t emitter;          // actuator pin
  uint8_t _pad;
  uint16_t onCode;
};

/*  One stage-schedule row. 4 bytes. Generalises applyStage()
    (BehaviorBox.h:567-574) from four fixed fields to N addressed by index. */
struct TgStageRow
{
  uint16_t atTrial; // completed-trial count at which this row engages
  uint8_t count;    // how many timing entries it rewrites
  uint8_t firstIdx; // first rewrite record
};

/*  One timing rewrite performed by a stage row. 4 bytes.

    THE EXPLICIT PAD IS LOAD-BEARING. Without it this record is
    {uint8 idx; uint16 ms;}, which measures 3 bytes under
    `avr-g++ -mmcu=atmega2560` and 4 under `clang++`: AVR has no alignment
    requirement for uint16 while the host wants it 2-byte aligned. Reordering the
    fields does NOT fix it -- both orders still measure 3/4.

    That is exactly the hazard this file's own header warns about, and it was live
    here: TgTimingSet was also the only record with no static_assert, and the only
    one absent from extras/host_test/. Both are now generated, and they compile
    under both toolchains.

    Padding rather than __attribute__((packed)): packed would give 3 bytes
    everywhere, but makes every field access unaligned on the host, and one byte
    is not worth a permanent footgun in the trial loop. */
struct TgTimingSet
{
  uint8_t idx;    // which timing entry
  uint8_t _pad;   // never read; see above
  uint16_t ms;    // its new value
};

/* ---------------------------------------------------------------- *
 *  Layout assertions.
 *
 *  These are the RAM spike's conclusions made mechanical. If a field is added
 *  or reordered and a record grows, the build fails HERE rather than silently
 *  eating the headroom the budget assumes -- or worse, compiling on the host at
 *  one size and on AVR at another, which would corrupt every uploaded table.
 * ---------------------------------------------------------------- */
/*  The authoritative assertions are GENERATED, in TgLayoutAssert.h -- one
    static_assert per record size AND per field offset, emitted from the layout
    table the Python compiler packs against. Include that header from anything
    that touches a table.

    Hand-written assertions are only ever added to records someone already
    suspected, which is why the one record that actually diverged was the one
    without them. The sizes below are kept as a fast local sanity check. */
#if __cplusplus >= 201103L
static_assert(sizeof(TgNode) == 8, "TgNode must stay 8 bytes -- see docs/spikes/avr-ram.md");
static_assert(sizeof(TgEdge) == 4, "TgEdge must stay 4 bytes");
static_assert(sizeof(TgAction) == 2, "TgAction must stay 2 bytes");
static_assert(sizeof(TgTrialType) == 8, "TgTrialType must stay 8 bytes");
static_assert(sizeof(TgStageRow) == 4, "TgStageRow must stay 4 bytes");
static_assert(sizeof(TgTimingSet) == 4, "TgTimingSet must stay 4 bytes on BOTH toolchains");
static_assert(sizeof(TgPort) == 16, "TgPort must stay 16 bytes");
static_assert(sizeof(TgStimulus) == 4, "TgStimulus must stay 4 bytes");
#endif

#endif // TASK_TABLE_H

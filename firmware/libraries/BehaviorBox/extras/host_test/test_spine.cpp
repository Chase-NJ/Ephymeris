/*
  Host test for BoxSpine.h, the phase interpreter's hardware layer.

  Drives the runner through the instrumented shim (box_shim/Arduino.h): pins
  are a table a test can set, Serial is a queue in and a capture out, and
  millis() is whatever the test says it is. The table is spine_fixture.h,
  written by hand; the strobe codes are fixture codes. So what passes here is
  the runner reading its table: the handshake, the tick order of the strobes,
  stepping skipped millis() values, and the session end rule.

  Each scenario runs in its own process (the runner's state is the sketch's
  own, as on a board): run_spine.sh runs `test_spine handshake`, `stream`,
  `stop`, `last`, `blocks`, `pairs` and `passes` (several loop() passes in one
  millisecond, as on a Mega), the sync pulse under the shim's real timing,
  `sync_tick` (one per tick that strobes, a burst waiting on nothing) and
  `sync_close` (two ticks stepped in one pass), then, built over spine_drive_fixture.h (-DSPINE_FIXTURE_DRIVES),
  the driven outputs: `test_spine_drives drives`, `train_held`, `train_refused`,
  and, under the shim's real serial timing, `train_timing` and `train_buffer`.

  Usage:  sh run_spine.sh
*/

#include <Arduino.h> // the instrumented shim (box_shim/ is first on the include path)

#include <iostream>
#include <string>
#include <utility>
#include <vector>

#include "strobe_fixture.h"
#ifdef SPINE_FIXTURE_DRIVES
#include "spine_drive_fixture.h"
#else
#include "spine_fixture.h"
#endif
#include <BehaviorBox.h>
#include <BoxInterp.h>
#include <BoxSpine.h>

/* The sketch, as the generator writes every spine task's `.ino`. */
void setup() { box_spine::setup(); }
void loop() { box_spine::loop(); }

static int failures = 0;

static void expect(const std::string &what, bool ok)
{
  std::cout << (ok ? "  [pass] " : "  [FAIL] ") << what << "\n";
  if (!ok) failures++;
}

static std::vector<std::string> lines()
{
  std::vector<std::string> out;
  const std::string &all = bb_output();
  size_t at = 0;
  while (at < all.size()) {
    size_t nl = all.find('\n', at);
    if (nl == std::string::npos) nl = all.size();
    size_t end = nl > at && all[nl - 1] == '\r' ? nl - 1 : nl; // println ends a line "\r\n"
    out.push_back(all.substr(at, end - at));
    at = nl + 1;
  }
  return out;
}

/* Every strobe printed so far, as (code, timestamp). */
static std::vector<std::pair<int, unsigned long>> strobes()
{
  std::vector<std::pair<int, unsigned long>> out;
  for (const std::string &l : lines()) {
    int code; unsigned long ts; char tail;
    if (l.size() > 4 && l[3] == '\t' && sscanf(l.c_str(), "%d\t%lu%c", &code, &ts, &tail) == 2)
      out.push_back(std::make_pair(code, ts));
  }
  return out;
}

static size_t indexOf(const std::string &line)
{
  std::vector<std::string> all = lines();
  for (size_t i = 0; i < all.size(); i++)
    if (all[i] == line) return i;
  return (size_t)-1;
}

static unsigned long t0 = 0;
static bool changed = false; // a pin moved: the next tick must be the very next ms

/* Run the board up to session time `t`, one loop() per tick, but now and then
   letting millis() skip a value as an AVR's does: the runner must step it. */
static void advanceTo(unsigned long t)
{
  while (bb_ms < t0 + t) {
    bool skip = !changed && bb_ms % 7 == 0 && bb_ms + 2 <= t0 + t;
    bb_ms += skip ? 2 : 1;
    changed = false;
    ::loop();
  }
}

/* The port beam: active LOW, so broken (a poke) is LOW. */
static void port(bool poked, unsigned long at)
{
  advanceTo(at - 1);
  bb_pinValue[2] = poked ? LOW : HIGH;
  changed = true;
  advanceTo(at);
}

static void boot()
{
  bb_pinValue[2] = HIGH; // the beam clear
  ::setup();
  t0 = millis();
}

static void handshake()
{
  bb_feed("BEGIN");
  bb_feed("SET NT=2 T1=100");
  bb_feed("SET RW=30");
  bb_feed("SET RP=1001");
  bb_feed("BEGIN");
  bb_feed("SET NT=abc T1=-5");
  bb_feed("BEGIN");
  bb_feed("SET NT=2 T1=100");
  bb_feed("START SEED=7");
  boot();
  std::vector<std::string> l = lines();
  expect("INTERP, then FREE_RAM, then SYNC=TICK, then READY, first", l.size() > 4 && l[0] == "INTERP=8" &&
         l[1].compare(0, 9, "FREE_RAM=") == 0 && l[2] == "SYNC=TICK" && l[3] == "READY");
  expect("each SET answered with the running count and CRC",
         indexOf("PARAMS 2 1564777853") < indexOf("PARAMS 3 2992546637"));
  expect("a value past its bound is CLAMPED", indexOf("CLAMPED RP") + 1 == indexOf("PARAMS 4 119361984"));
  expect("junk and a sign are CLAMPED too", indexOf("CLAMPED NT") != (size_t)-1 &&
         indexOf("CLAMPED T1") != (size_t)-1 && indexOf("PARAMS 2 1290238464") != (size_t)-1);
  expect("BEGIN forgets the earlier block", l.size() > 13 && l[l.size() - 6] == "PARAMS 2 1564777853");
  expect("START echoes the seed it runs on", indexOf("SEED\t7") != (size_t)-1);
  expect("the session opens at t=0", indexOf("017\t0") == indexOf("SEED\t7") + 1);
  expect("the session's trial cap is what was SET", box_spine::params[0] == 2);
}

static void stream()
{
  bb_feed("BEGIN");
  bb_feed("SET NT=2 T1=100 T3=50 RW=30 RP=1000");
  bb_feed("START SEED=7");
  boot();
  port(true, 10);
  advanceTo(120);
  expect("the reward line is open during the reward", bb_pinValue[44] == HIGH);
  port(false, 150); // unwatched: nothing strobes
  port(true, 300);
  port(false, 350); // a release during the present: abort to the ITI
  advanceTo(420);
  port(true, 450);  // the session is over: nothing strobes
  advanceTo(500);

  const std::vector<std::pair<int, unsigned long>> want = {
    {BF_START_SESSION, 0}, {BF_BLOCK_START, 0}, {BF_TRIAL_START, 0}, {BF_LIGHT_ON, 0},
    {BF_PORT_ENTER, 10}, {BF_SAMPLE_ON, 10},
    {BF_LIGHT_OFF, 110}, {BF_SAMPLE_OFF, 110}, {BF_FLUID_ON, 110}, {BF_OUTCOME_CORRECT, 110},
    {BF_FLUID_OFF, 140},
    {BF_BLOCK_START, 191}, {BF_TRIAL_START, 191}, {BF_LIGHT_ON, 191},
    {BF_PORT_ENTER, 300}, {BF_SAMPLE_ON, 300},
    {BF_PORT_EXIT, 350}, {BF_LIGHT_OFF, 350}, {BF_SAMPLE_OFF, 350}, {BF_OUTCOME_ABORT_DURING_SAMPLING, 350},
    {BF_END_SESSION, 400},
  };
  std::vector<std::pair<int, unsigned long>> got = strobes();
  expect("the stream is edges, structure and each trial's outcome, in tick order, at tick times", got == want);
  if (got != want)
    for (auto &s : got) std::cout << "      " << s.first << "\t" << s.second << "\n";
  expect("every output is LOW once the session ends",
         bb_pinValue[36] == LOW && bb_pinValue[22] == LOW && bb_pinValue[44] == LOW);
}

static void stop()
{
  bb_feed("START SEED=7"); // a hand-typed console: the compiled defaults
  boot();
  advanceTo(20);
  bb_feed("STOP");
  port(true, 30);
  advanceTo(400);
  std::vector<std::pair<int, unsigned long>> got = strobes();
  // Trial 1 runs out: present 100, reward 30, class timeout 0, ITI 50.
  expect("STOP is honoured at the next trial start, not mid-trial",
         !got.empty() && got.back() == std::make_pair(BF_END_SESSION, 211UL));
  bool second = false;
  for (auto &s : got) second |= s.first == BF_TRIAL_START && s.second == 211UL;
  expect("the trial STOP ended is never reported", !second);
}

static void last()
{
  bb_feed("BEGIN");
  bb_feed("SET NT=10 T1=100 T3=50");
  bb_feed("START SEED=7");
  boot();
  port(true, 10);
  port(false, 50); // a release during the present: its end is the session's last trial
  advanceTo(400);
  std::vector<std::pair<int, unsigned long>> got = strobes();
  // The end is an ITI of T3 = 50: the session ends where trial 2 would start.
  expect("a last-trial state ends the session at the next trial start, before NT",
         !got.empty() && got.back() == std::make_pair(BF_END_SESSION, 100UL));
  bool second = false;
  for (auto &s : got) second |= s.first == BF_TRIAL_START && s.second == 100UL;
  expect("the trial it ended is never reported", !second);
}

static void blocks()
{
  bb_feed("BEGIN");
  bb_feed("SET NT=10 T1=100 T3=50 BN1=1 BN2=1 BNX2=1");
  bb_feed("START SEED=7");
  boot();
  port(true, 10);
  port(false, 200); // not watched in the ITI: nothing strobes
  port(true, 300);
  advanceTo(600);
  std::vector<std::pair<int, unsigned long>> got = strobes();
  // Block 0 runs one trial; block 1 one more, then the blocks are done: the
  // session ends where trial 3 would start, well before NT.
  bool second = false;
  for (auto &s : got) second |= s.first == BF_BLOCK_START && s.second == 191UL;
  expect("the second block starts with BLOCK_START, before its TRIAL_START", second);
  expect("the last block's end ends the session at the next trial start",
         !got.empty() && got.back() == std::make_pair(BF_END_SESSION, 481UL));
  bool third = false;
  for (auto &s : got) third |= (s.first == BF_TRIAL_START || s.first == BF_BLOCK_START) && s.second == 481UL;
  expect("neither the trial nor a block is reported at the end", !third);
}

/* A Mega runs loop() some 27 times a millisecond, so a poke is read on
   whichever pass sees it, rarely the first of its ms. It must still reach the
   core: a poke and a release, each read on a later pass, both strobe and both
   move the trial, within the ms after. */
static void passes()
{
  bb_feed("BEGIN");
  bb_feed("SET NT=2 T1=100 T3=50 RW=30 RP=1000");
  bb_feed("START SEED=7");
  boot();
  advanceTo(10);
  ::loop();
  bb_pinValue[2] = LOW; // the poke, between two passes of ms 10
  ::loop();
  ::loop();
  advanceTo(50);
  ::loop();
  bb_pinValue[2] = HIGH; // the release, during the present
  ::loop();
  ::loop();
  advanceTo(120);
  std::vector<std::pair<int, unsigned long>> got = strobes();
  auto at = [&](int code) {
    for (auto &s : got)
      if (s.first == code) return (long)s.second;
    return -1L;
  };
  long enter = at(BF_PORT_ENTER), leave = at(BF_PORT_EXIT);
  expect("a poke read on a later pass of its ms strobes", enter == 10 || enter == 11);
  expect("and starts the present", enter >= 0 && at(BF_SAMPLE_ON) == enter);
  expect("a release read so aborts it", (leave == 50 || leave == 51) && at(BF_SAMPLE_OFF) == leave);
  if (enter < 0 || leave < 0)
    for (auto &s : got) std::cout << "      " << s.first << "\t" << s.second << "\n";
}

static void pairs()
{
  bb_feed("BEGIN");
  bb_feed("SET BN2=5 BNX2=3");
  bb_feed("START SEED=7");
  boot();
  expect("a drawn N's high end below its low end is CLAMPED", indexOf("CLAMPED BNX2") != (size_t)-1);
  expect("and held as the range's low end", box_spine::params[8] == 5);
}

/* ---- The sync pulse, under the shim's real timing ------------------------ */
/* Every pin write, with the micros() it happened at, and a Mega's loop(): a
   pass every PASS_US, some 27 a millisecond. */
struct Write { int pin; int level; unsigned long us; };
static std::vector<Write> writes;
static unsigned long longestPass = 0;
static const unsigned long PASS_US = 37;
static const int SYNC = BOX_PIN_SYNC_OUT;

static void logWrite(int pin, int value, unsigned long us) { writes.push_back({pin, value, us}); }

/* loop() pass after pass until session time `t` (ms), each pass's own cost
   measured: a pass that waits is a pass that runs long. */
static void passTo(unsigned long t)
{
  while (micros() < (t0 + t) * 1000UL) {
    unsigned long before = micros();
    ::loop();
    if (micros() - before > longestPass) longestPass = micros() - before;
    bb_advanceUs(PASS_US);
  }
}

/* The sync line's edges: (rise, fall) in micros(), a fall of 0 if none yet. */
static std::vector<std::pair<unsigned long, unsigned long>> pulses()
{
  std::vector<std::pair<unsigned long, unsigned long>> out;
  int level = LOW;
  for (const Write &w : writes) {
    if (w.pin != SYNC || w.level == level) continue;
    level = w.level;
    if (level == HIGH) out.push_back(std::make_pair(w.us, 0UL));
    else if (!out.empty()) out.back().second = w.us;
  }
  return out;
}

/* The distinct tick times the stream strobed, in order. */
static std::vector<unsigned long> strobedTicks()
{
  std::vector<unsigned long> out;
  for (auto &s : strobes())
    if (out.empty() || out.back() != s.second) out.push_back(s.second);
  return out;
}

static void dumpPulses()
{
  for (auto &p : pulses()) std::cout << "      rise " << p.first << " fall " << p.second << "\n";
  for (auto &s : strobes()) std::cout << "      " << s.first << "\t" << s.second << "\n";
}

/* Width at least BOX_SYNC_PULSE_US and at most a pass more; LOW at least
   BOX_SYNC_GAP_US before every rise; every pulse has fallen. */
static void expectPulseShape()
{
  auto got = pulses();
  bool width = true, gap = true, fell = true;
  for (size_t i = 0; i < got.size(); i++) {
    fell &= got[i].second != 0;
    unsigned long high = got[i].second - got[i].first;
    width &= got[i].second == 0 || (high >= BOX_SYNC_PULSE_US && high <= BOX_SYNC_PULSE_US + 2 * PASS_US);
    if (i) gap &= got[i].first - got[i - 1].second >= BOX_SYNC_GAP_US;
  }
  expect("every pulse is HIGH its width, within a pass", width);
  expect("every rise follows at least the gap of LOW", gap);
  expect("every pulse falls, the session's last included", fell);
}

/* A spine run pulses once per tick that strobes, rising with that tick's
   pins; a burst neither waits on the pulse nor on a full TX buffer, so the
   next tick's pins are written on time. The poke at 300 strobes two lines into
   a TX buffer already full, and the release at 301 strobes three more. */
static void syncTick()
{
  bb_onPinWrite = logWrite;
  bb_feed("BEGIN");
  bb_feed("SET NT=2 T1=100 T3=50 RW=30 RP=1000");
  bb_feed("START SEED=7");
  boot();
  bb_realTiming(115200);
  passTo(10);
  bb_pinValue[2] = LOW;
  passTo(150);
  bb_pinValue[2] = HIGH; // unwatched
  passTo(300);
  std::string backlog(61, '#');
  backlog += "\r\n";
  Serial.write(backlog.c_str(), backlog.size()); // 63 bytes: the buffer is full
  bb_pinValue[2] = LOW;
  passTo(301);
  bb_pinValue[2] = HIGH; // a release during the present: abort to the ITI
  passTo(450);

  std::vector<unsigned long> ticks = strobedTicks();
  auto got = pulses();
  expect("the run ended", !strobes().empty() && strobes().back().first == BF_END_SESSION);
  expect("exactly one pulse per tick that strobes", got.size() == ticks.size() && ticks.size() == 8);
  bool onTime = true;
  for (size_t i = 0; i < got.size() && i < ticks.size(); i++) {
    unsigned long tick = (t0 + ticks[i]) * 1000UL;
    onTime &= got[i].first >= tick && got[i].first - tick <= PASS_US;
  }
  expect("each rises in its tick's first pass", onTime);
  // Every output write a tick makes, from the session's first to the tick
  // before its end, is at most a few us before that tick's rise.
  bool withPins = true;
  unsigned long ended = (t0 + ticks.back()) * 1000UL;
  for (const Write &w : writes) {
    if ((w.pin != 36 && w.pin != 22 && w.pin != 44) || w.us < t0 * 1000UL || w.us >= ended) continue;
    bool near = false;
    for (auto &p : got) near |= p.first >= w.us && p.first - w.us <= 5;
    withPins &= near;
  }
  expect("the rise is within 5 us of its tick's output writes", withPins);
  // The pins of every output strobe are written in the first pass of its tick.
  const std::vector<std::pair<int, int>> pinOf = {
    {36, HIGH}, {36, LOW}, {22, HIGH}, {22, LOW}, {44, HIGH}, {44, LOW}};
  const std::vector<int> codes = {BF_LIGHT_ON, BF_LIGHT_OFF, BF_SAMPLE_ON, BF_SAMPLE_OFF, BF_FLUID_ON, BF_FLUID_OFF};
  bool pinsOnTime = true;
  for (auto &s : strobes())
    for (size_t c = 0; c < codes.size(); c++) {
      if (s.first != codes[c] || s.second == 0) continue;
      unsigned long tick = (t0 + s.second) * 1000UL;
      bool found = false;
      for (const Write &w : writes)
        if (w.pin == pinOf[c].first && w.level == pinOf[c].second && w.us >= tick && w.us - tick <= PASS_US)
          found = true;
      pinsOnTime &= found;
    }
  expect("the tick after a burst still writes its pins on time", pinsOnTime);
  std::cout << "  longest pass " << longestPass << " us, writes blocked " << bb_txBlockedUs << " us\n";
  expect("no pass waits: not on the pulse, not on the TX buffer", longestPass <= 4 * PASS_US);
  expect("no strobe was printed into a full buffer", bb_txBlockedUs == 0);
  expectPulseShape();
  if (failures) dumpPulses();
}

/* Two ticks that strobe, stepped in one pass (millis() skips 110): the second
   is owed its rise, raised once the first has fallen and the gap has run. Two
   edges, never one, and the second at most a pulse, a gap and a pass late. */
static void syncClose()
{
  bb_onPinWrite = logWrite;
  bb_feed("BEGIN");
  bb_feed("SET NT=2 T1=100 T3=50 RW=1 RP=1000");
  bb_feed("START SEED=7");
  boot();
  bb_realTiming(115200);
  passTo(10);
  bb_pinValue[2] = LOW;
  passTo(109);
  bb_advanceUs((t0 + 111) * 1000UL - micros()); // the pass at 110 never comes
  passTo(300);

  auto got = pulses();
  std::vector<unsigned long> ticks = strobedTicks();
  bool both = false;
  for (size_t i = 0; i + 1 < ticks.size(); i++)
    if (ticks[i] == 110 && ticks[i + 1] == 111) {
      both = true;
      unsigned long tick = (t0 + 111) * 1000UL;
      expect("the first rises at once, in the pass that steps both", got.size() > i && got[i].first == tick);
      expect("the second is owed: it rises after a pulse and a gap, within a pass",
             got.size() > i + 1 && got[i + 1].first >= got[i].first + BOX_SYNC_PULSE_US + BOX_SYNC_GAP_US &&
             got[i + 1].first <= got[i].first + BOX_SYNC_PULSE_US + BOX_SYNC_GAP_US + 2 * PASS_US);
    }
  expect("the reward opened and closed in consecutive ticks", both);
  expect("still one pulse per tick that strobes", got.size() == ticks.size());
  expectPulseShape();
  if (failures) dumpPulses();
}
/* A tick that strobes only a trial's mark still pulses
   (0005-spine-runs-strobe-each-trials-outcome.md): built with
   SPINE_FIXTURE_QUIET_PRESENT, the Present drives nothing, and RP 0 sends the
   chance state to the class timeout, so the tick it ends strobes
   OUTCOME_CORRECT and nothing else. */
static void syncMark()
{
  bb_onPinWrite = logWrite;
  bb_feed("BEGIN");
  bb_feed("SET NT=1 T1=100 T3=50 RW=30 RP=0");
  bb_feed("START SEED=7");
  boot();
  bb_realTiming(115200);
  passTo(10);
  bb_pinValue[2] = LOW;
  passTo(300);

  std::vector<std::pair<int, unsigned long>> at110;
  for (auto &s : strobes())
    if (s.second == 110) at110.push_back(s);
  expect("the Present's end strobes only the trial's mark",
         at110 == std::vector<std::pair<int, unsigned long>>({{BF_OUTCOME_CORRECT, 110}}));
  auto got = pulses();
  std::vector<unsigned long> ticks = strobedTicks();
  expect("still one pulse per tick that strobes", got.size() == ticks.size());
  bool rose = false;
  for (auto &p : got) rose |= p.first >= (t0 + 110) * 1000UL && p.first - (t0 + 110) * 1000UL <= PASS_US;
  expect("the mark's tick pulses in its first pass", rose);
  expectPulseShape();
  if (failures) dumpPulses();
}
#ifdef SPINE_FIXTURE_DRIVES
static void dump(const std::vector<std::pair<int, unsigned long>> &got)
{
  for (auto &s : got) std::cout << "      " << s.first << "\t" << s.second << "\n";
}

/* The Present holds a PWM line, a tone and a 20 Hz, 5 ms train that runs out
   after 60 ms, so its TRAIN_OFF comes before the phase ends; then the reward. */
static void drives()
{
  bb_feed("SET NT=1 T1=100 T3=50 RW=30 RP=1000 PD=128 TF=4000 TH=20 TW=5 TL=60");
  bb_feed("START SEED=7");
  boot();
  port(true, 10);
  expect("the PWM line runs at its duty", bb_pwm[45] == 128);
  expect("the tone plays at its pitch", bb_tone[12] == 4000);
  expect("the train starts HIGH", bb_pinValue[11] == HIGH);
  std::vector<unsigned long> rises, falls;
  int was = HIGH;
  for (unsigned long t = 11; t <= 120; t++) {
    advanceTo(t);
    if (bb_pinValue[11] != was) (bb_pinValue[11] == HIGH ? rises : falls).push_back(t);
    was = bb_pinValue[11];
  }
  expect("each pulse lands on its tick, skipped millis() values included",
         rises == std::vector<unsigned long>({60}) && falls == std::vector<unsigned long>({15, 65}));
  expect("the PWM line and the tone stop with their phase", bb_pwm[45] == 0 && bb_tone[12] == 0);
  advanceTo(300);

  const std::vector<std::pair<int, unsigned long>> want = {
    {BF_START_SESSION, 0}, {BF_BLOCK_START, 0}, {BF_TRIAL_START, 0}, {BF_LIGHT_ON, 0},
    {BF_PORT_ENTER, 10}, {BF_SAMPLE_ON, 10}, {BF_LED_ON, 10}, {BF_TONE_ON, 10}, {BF_LASER_TRAIN_ON, 10},
    {BF_LASER_TRAIN_OFF, 70},
    {BF_LIGHT_OFF, 110}, {BF_SAMPLE_OFF, 110}, {BF_LED_OFF, 110}, {BF_TONE_OFF, 110}, {BF_FLUID_ON, 110},
    {BF_OUTCOME_CORRECT, 110},
    {BF_FLUID_OFF, 140},
    {BF_END_SESSION, 191},
  };
  std::vector<std::pair<int, unsigned long>> got = strobes();
  expect("a train strobes its start and its running out, never a pulse", got == want);
  if (got != want) dump(got);
}

/* A width not shorter than the period would hold the line HIGH: a steady output
   where a train was asked for. Each range alone holds it, so the board judges
   the pair after every SET line, and refuses a hand-typed START with one. */
static void trainRefused()
{
  bb_feed("SET TH=100 TW=15");         // 15 ms at 100 Hz: a 10 ms period
  bb_feed("SET TH=20");                // 15 ms at 20 Hz: fine again
  bb_feed("START SEED=7 TW=60");       // 60 ms at 20 Hz: refused, not started
  bb_feed("START SEED=7 TW=5");
  boot();
  std::vector<std::string> l = lines();
  size_t first = (size_t)-1, second = (size_t)-1;
  for (size_t i = 0; i < l.size(); i++)
    if (l[i].compare(0, 9, "PARAMS 2 ") == 0 && first == (size_t)-1) first = i;
    else if (l[i].compare(0, 9, "PARAMS 3 ") == 0) second = i;
  expect("a width past the period is CLAMPED with its SET line",
         first != (size_t)-1 && first > 0 && l[first - 1] == "CLAMPED TW");
  expect("and clears once the pair fits", second != (size_t)-1 && l[second - 1] != "CLAMPED TW");
  size_t refused = (size_t)-1;
  for (size_t i = second + 1; i < l.size(); i++)
    if (l[i] == "CLAMPED TW") refused = i;
  expect("a START that makes the pair not fit is refused", refused != (size_t)-1 &&
         refused < indexOf("SEED\t7") && indexOf("SEED\t7") != (size_t)-1);
  expect("the run starts on the START that fits", box_spine::params[9] == 5);
}

/* A train of length 0 runs as long as its phase holds it, and stops once. */
static void trainHeld()
{
  bb_feed("SET NT=1 T1=100 T3=50 RW=30 RP=1000 TL=0");
  bb_feed("START SEED=7");
  boot();
  port(true, 10);
  advanceTo(300);
  std::vector<std::pair<int, unsigned long>> got = strobes();
  bool offAt110 = false;
  int offs = 0;
  for (auto &s : got) {
    offAt110 |= s == std::make_pair(BF_LASER_TRAIN_OFF, 110UL);
    offs += s.first == BF_LASER_TRAIN_OFF;
  }
  expect("a train of length 0 stops with its phase, once", offAt110 && offs == 1);
  if (!offAt110 || offs != 1) dump(got);
  expect("its pin is LOW after", bb_pinValue[11] == LOW);
}

/* On a board a strobe takes time: its sync pulse and gap (about 0.7 ms), and,
   once 64 bytes are queued, a print that blocks until the wire drains. The tick
   a train starts in strobes four other events too. Under the shim's real
   timing, every pulse of a 100 Hz, 1 ms train must still fall within 1 ms of
   its width, however long that tick's strobes take. */
static unsigned long trainRose = 0, trainLongest = 0;
static bool trainIsHigh = false;
static int trainPulses = 0;

static void watchTrain(int pin, int value, unsigned long us)
{
  if (pin != 11) return;
  if (value && !trainIsHigh) { trainIsHigh = true; trainRose = us; trainPulses++; }
  else if (!value && trainIsHigh) {
    trainIsHigh = false;
    if (us - trainRose > trainLongest) trainLongest = us - trainRose;
  }
}

static void trainTiming()
{
  bb_feed("SET NT=1 T1=100 T3=50 RW=30 RP=1000 TH=100 TW=1 TL=0");
  bb_feed("START SEED=7");
  boot();
  bb_realTiming(115200);
  bb_onPinWrite = watchTrain;
  port(true, 10);
  advanceTo(300);
  std::cout << "  pulses " << trainPulses << ", longest HIGH " << trainLongest << " us, writes blocked "
            << bb_txBlockedUs << " us\n";
  expect("the train pulsed through its phase", trainPulses >= 9);
  expect("no pulse is HIGH more than 1 ms past its 1 ms width", trainLongest <= 2000);
  expect("and its strobes are the same", bb_output().find("052\t10") != std::string::npos);
}

/* The same, with the TX buffer FULL when the train starts: a session long
   enough that every strobe carries a seven-digit timestamp, and the tick
   before's lines still draining. A print into a full buffer blocks, so the
   runner must wait for room for each line, stepping the trains, rather than
   print into it. */
static void trainBuffer()
{
  bb_feed("SET NT=1 T1=100 T3=50 RW=30 RP=1000 TH=100 TW=1 TL=0");
  bb_feed("START SEED=7");
  boot();
  advanceTo(999999);
  bb_realTiming(115200);
  bb_onPinWrite = watchTrain;
  std::string backlog(61, '#');
  backlog += "\r\n";
  Serial.write(backlog.c_str(), backlog.size()); // 63 bytes: the buffer is full
  port(true, 1000000);
  advanceTo(1000300);
  std::cout << "  pulses " << trainPulses << ", longest HIGH " << trainLongest << " us, writes blocked "
            << bb_txBlockedUs << " us\n";
  expect("the train started with seven-digit strobes", bb_output().find("052\t1000000\r\n") != std::string::npos);
  expect("the train pulsed through its phase", trainPulses >= 9);
  expect("no strobe was printed into a full buffer", bb_txBlockedUs == 0);
  expect("no pulse is HIGH more than 1 ms past its 1 ms width", trainLongest <= 2000);
}
#endif

int main(int argc, char **argv)
{
  std::string which = argc > 1 ? argv[1] : "";
  std::cout << "test_spine " << which << "\n";
#ifdef SPINE_FIXTURE_DRIVES
  if (which == "drives") drives();
  else if (which == "train_held") trainHeld();
  else if (which == "train_refused") trainRefused();
  else if (which == "train_timing") trainTiming();
  else if (which == "train_buffer") trainBuffer();
#else
  if (which == "handshake") handshake();
  else if (which == "stream") stream();
  else if (which == "stop") stop();
  else if (which == "last") last();
  else if (which == "blocks") blocks();
  else if (which == "pairs") pairs();
  else if (which == "passes") passes();
  else if (which == "sync_tick") syncTick();
  else if (which == "sync_close") syncClose();
  else if (which == "sync_mark") syncMark();
#endif
  else { std::cout << "  [FAIL] unknown scenario\n"; return 2; }
  return failures == 0 ? 0 : 1;
}

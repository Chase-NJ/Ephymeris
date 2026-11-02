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
  millisecond, as on a Mega), then, built over spine_drive_fixture.h (-DSPINE_FIXTURE_DRIVES),
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
  expect("INTERP, then FREE_RAM, then READY, first", l.size() > 3 && l[0] == "INTERP=6" &&
         l[1].compare(0, 9, "FREE_RAM=") == 0 && l[2] == "READY");
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
    {BF_LIGHT_OFF, 110}, {BF_SAMPLE_OFF, 110}, {BF_FLUID_ON, 110},
    {BF_FLUID_OFF, 140},
    {BF_BLOCK_START, 191}, {BF_TRIAL_START, 191}, {BF_LIGHT_ON, 191},
    {BF_PORT_ENTER, 300}, {BF_SAMPLE_ON, 300},
    {BF_PORT_EXIT, 350}, {BF_LIGHT_OFF, 350}, {BF_SAMPLE_OFF, 350},
    {BF_END_SESSION, 400},
  };
  std::vector<std::pair<int, unsigned long>> got = strobes();
  expect("the stream is edges and structure, in tick order, at tick times", got == want);
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
#endif
  else { std::cout << "  [FAIL] unknown scenario\n"; return 2; }
  return failures == 0 ? 0 : 1;
}

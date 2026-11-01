/*
  Host test for BoxSpine.h, the phase interpreter's hardware layer.

  Drives the runner through the instrumented shim (box_shim/Arduino.h): pins
  are a table a test can set, Serial is a queue in and a capture out, and
  millis() is whatever the test says it is. The table is spine_fixture.h,
  written by hand; the strobe codes are fixture codes. So what passes here is
  the runner reading its table: the handshake, the tick order of the strobes,
  stepping skipped millis() values, and the session end rule.

  Each scenario runs in its own process (the runner's state is the sketch's
  own, as on a board): run_spine.sh runs `test_spine handshake`, `stream` and
  `stop`.

  Usage:  sh run_spine.sh
*/

#include <Arduino.h> // the instrumented shim (box_shim/ is first on the include path)

#include <iostream>
#include <string>
#include <utility>
#include <vector>

#include "strobe_fixture.h"
#include "spine_fixture.h"
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
    out.push_back(all.substr(at, nl - at));
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
  expect("INTERP, then FREE_RAM, then READY, first", l.size() > 3 && l[0] == "INTERP=3" &&
         l[1].compare(0, 9, "FREE_RAM=") == 0 && l[2] == "READY");
  expect("each SET answered with the running count and CRC",
         indexOf("PARAMS 2 1564777853") < indexOf("PARAMS 3 2992546637"));
  expect("a value past its bound is CLAMPED", indexOf("CLAMPED RP") + 1 == indexOf("PARAMS 4 119361984"));
  expect("junk and a sign are CLAMPED too", indexOf("CLAMPED NT") != (size_t)-1 &&
         indexOf("CLAMPED T1") != (size_t)-1 && indexOf("PARAMS 2 1290238464") != (size_t)-1);
  expect("BEGIN forgets the earlier block", l.size() > 12 && l[l.size() - 5] == "PARAMS 2 1564777853");
  expect("START echoes the seed it runs on", indexOf("SEED\t7") != (size_t)-1);
  expect("the session opens at t=0", indexOf("017\t0") == indexOf("SEED\t7") + 1);
  expect("the block's trial count is what was SET", box_spine::params[0] == 2);
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
    {BF_START_SESSION, 0}, {BF_TRIAL_START, 0}, {BF_LIGHT_ON, 0},
    {BF_PORT_ENTER, 10}, {BF_SAMPLE_ON, 10},
    {BF_LIGHT_OFF, 110}, {BF_SAMPLE_OFF, 110}, {BF_FLUID_ON, 110},
    {BF_FLUID_OFF, 140},
    {BF_TRIAL_START, 191}, {BF_LIGHT_ON, 191},
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

int main(int argc, char **argv)
{
  std::string which = argc > 1 ? argv[1] : "";
  std::cout << "test_spine " << which << "\n";
  if (which == "handshake") handshake();
  else if (which == "stream") stream();
  else if (which == "stop") stop();
  else { std::cout << "  [FAIL] unknown scenario\n"; return 2; }
  return failures == 0 ? 0 : 1;
}

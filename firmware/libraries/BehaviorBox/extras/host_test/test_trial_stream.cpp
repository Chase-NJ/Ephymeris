/*
  Host test for the trial runner's strobe stream (stream grammar 2,
  docs/TASKS.md#stream-grammar).

  Every outcome a trial can have is driven through emitTrialHeader(),
  runTrial() and emitTrialFooter() by scripting the three IR beams against
  the shim's clock, and the exact sequence each one printed is asserted
  against the reference table. Then the two properties every trial shares,
  whatever happened in it: exactly one outcome code, and END_TRIAL last.

  The codes are strobe_fixture.h's, deliberately not the lab's: a sequence is
  asserted by NAME, so passing here says nothing about any number.

  Usage:  sh run_stream.sh
*/

#include <Arduino.h> // the instrumented shim (box_shim/ is first on the include path)

#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "strobe_fixture.h" // arbitrary codes; the real ones are generated
#include "BehaviorBox.h"

static int failures = 0;

// ---- scripting the beams ---------------------------------------------------

/* An IR beam is LOW (broken: the animal is in the port) from `from` until
   `to`, in the shim's milliseconds. Anything unscripted reads HIGH, as an
   INPUT_PULLUP beam does when nobody is in it. */
struct Low { int pin; unsigned long from; unsigned long to; };
static std::vector<Low> lows;

static int scriptedRead(int pin)
{
  if (pin != odorPort && pin != leftWell && pin != rightWell) return -1;
  for (const Low &w : lows)
    if (w.pin == pin && bb_ms >= w.from && bb_ms < w.to) return LOW;
  return HIGH;
}

/* The codes the shim's serial captured, in order: every "%03d\t<ms>" line. */
static std::vector<int> captured()
{
  std::vector<int> out;
  const std::string &text = bb_output();
  size_t at = 0;
  while (at < text.size()) {
    size_t end = text.find("\r\n", at);
    if (end == std::string::npos) end = text.size();
    std::string line = text.substr(at, end - at);
    if (line.size() >= 5 && line[3] == '\t') out.push_back(atoi(line.substr(0, 3).c_str()));
    at = end + 2;
  }
  return out;
}

static const char *nameOf(int code)
{
  switch (code) {
#define N(x) case BF_##x: return #x;
    N(END_SESSION) N(FLUID_L) N(FLUID_R) N(INVALID_TRIAL) N(LAZY_RAT) N(LIGHTS_OFF) N(LIGHTS_ON)
    N(ODOR_1_ON) N(ODOR_3_ON) N(ODOR_OFF) N(ODOR_POKE) N(ODOR_UNPOKE) N(ODOR_UNPOKE_EARLY)
    N(RESP_OMIT) N(START_SESSION) N(STOP_FLUID_G_L) N(STOP_FLUID_G_R) N(WATER_POKE_ERROR_L)
    N(WATER_POKE_ERROR_R) N(WATER_POKE_L) N(WATER_POKE_NONE) N(WATER_POKE_R)
    N(WATER_UNPOKE_EARLY_L) N(WATER_UNPOKE_EARLY_R) N(WATER_UNPOKE_L) N(WATER_UNPOKE_R)
    N(TRIAL_START) N(TRIAL_GO_LEFT) N(TRIAL_GO_RIGHT) N(TRIAL_NO_GO) N(CORRECT) N(END_TRIAL)
    N(ODOR_UNPOKE_EARLY_SAMPLING) N(TRIAL_TYPE_1) N(TRIAL_TYPE_2)
#undef N
  }
  return "?";
}

static std::string spell(const std::vector<int> &codes)
{
  std::string out;
  for (int c : codes) { if (!out.empty()) out += " "; out += nameOf(c); }
  return out;
}

static void expectSequence(const char *what, const std::vector<int> &got, const std::vector<int> &want)
{
  bool ok = got == want;
  printf("  [%s] %s\n", ok ? "pass" : "FAIL", what);
  if (!ok) {
    printf("         got  %s\n         want %s\n", spell(got).c_str(), spell(want).c_str());
    failures++;
  }
}

// ---- one trial, framed as the sketch loop frames it ------------------------

static TrialClock clock_;

static std::vector<int> trial(const TrialType &t, TaskParams &p, TrialPolicy *policy, int completed,
                              std::vector<Low> script)
{
  bb_resetCapture();
  unsigned long t0 = bb_ms;
  lows.clear();
  for (Low &w : script) lows.push_back({w.pin, t0 + w.from, t0 + w.to});
  emitTrialHeader(clock_, t);
  bool advanced = runTrial(t, p, clock_, policy, completed);
  emitTrialFooter(clock_, !advanced);
  bb_ms += 1000; // the next trial starts on a fresh second
  return captured();
}

static void parseStart(const char *line, TaskParams &p)
{
  char buf[512];
  strncpy(buf, line, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = '\0';
  parseStartCommand(buf, p);
}

int main()
{
  bb_onPinRead = scriptedRead;
  bb_ms = 0;
  clock_.beginSession();

  /* Short everything, so a trial takes a few hundred shim-milliseconds: a 1 ms
     priming delay and poll, 10 ms holds, a 200 ms response window, a 100 ms
     odor-port window, a 50 ms no-go window and 5 ms delays and rewards. */
  TaskParams p;
  parseStart("START PRM=1 POL=1 S0P=10 S0H=10 S0W=200 S0O=100 ERR=5 ITI=5 NPH=5 NWP=50 LZD=5 LAZY=0 RW1=5 RW2=5", p);

  TrialType goR(true, 1, rightWell, 2, BF_ODOR_1_ON, BF_FLUID_R, BF_STOP_FLUID_G_R, 5, BF_TRIAL_TYPE_1);
  TrialType goL(true, 3, leftWell, 0, BF_ODOR_3_ON, BF_FLUID_L, BF_STOP_FLUID_G_L, 5, BF_TRIAL_TYPE_2);
  TrialType noGo(false, 3, SENTINEL, SENTINEL, BF_ODOR_3_ON, 0, 0, 0, BF_TRIAL_TYPE_2);

  AbstentionPenalty abstention; abstention.configure(p);
  TrialPolicy plain; plain.abstention = &abstention; // anti-bias, no correction budget
  CorrectionPolicy correction; correction.configure(1, 1);
  TrialPolicy correcting; correcting.abstention = &abstention; correcting.correction = &correction;

  // The timeline every administered trial shares, after the header: light on at
  // 1 ms, the odor port entered at 5 and left at 40, the odor delivered after
  // the 10 ms pre-odor hold and released after the 10 ms sampling hold.
  const Low sampled = {odorPort, 5, 40};
  const std::vector<int> headerR = {BF_TRIAL_START, BF_TRIAL_GO_RIGHT, BF_TRIAL_TYPE_1};
  const std::vector<int> headerL = {BF_TRIAL_START, BF_TRIAL_GO_LEFT, BF_TRIAL_TYPE_2};
  const std::vector<int> headerN = {BF_TRIAL_START, BF_TRIAL_NO_GO, BF_TRIAL_TYPE_2};
  const std::vector<int> timeline = {BF_LIGHTS_ON, BF_ODOR_POKE, BF_ODOR_1_ON, BF_ODOR_OFF, BF_ODOR_UNPOKE, BF_LIGHTS_OFF};
  const std::vector<int> timelineL = {BF_LIGHTS_ON, BF_ODOR_POKE, BF_ODOR_3_ON, BF_ODOR_OFF, BF_ODOR_UNPOKE, BF_LIGHTS_OFF};
  auto seq = [](std::vector<int> a, const std::vector<int> &b, const std::vector<int> &c) {
    a.insert(a.end(), b.begin(), b.end());
    a.insert(a.end(), c.begin(), c.end());
    return a;
  };

  std::vector<std::vector<int>> every;
  printf("stream grammar 2: the reference sequences\n");

  every.push_back(trial(goR, p, &plain, 0, {sampled, {rightWell, 50, 80}}));
  expectSequence("correct", every.back(), seq(headerR, timeline,
      {BF_WATER_POKE_R, BF_CORRECT, BF_FLUID_R, BF_STOP_FLUID_G_R, BF_WATER_UNPOKE_R, BF_END_TRIAL}));

  every.push_back(trial(goL, p, &plain, 1, {sampled, {leftWell, 50, 80}}));
  expectSequence("correct, left", every.back(), seq(headerL, timelineL,
      {BF_WATER_POKE_L, BF_CORRECT, BF_FLUID_L, BF_STOP_FLUID_G_L, BF_WATER_UNPOKE_L, BF_END_TRIAL}));

  every.push_back(trial(goR, p, &plain, 2, {sampled, {leftWell, 50, 80}}));
  expectSequence("wrong well", every.back(), seq(headerR, timeline,
      {BF_WATER_POKE_L, BF_WATER_POKE_ERROR_L, BF_END_TRIAL}));

  every.push_back(trial(goR, p, &plain, 3, {sampled, {rightWell, 50, 55}}));
  expectSequence("hold failed", every.back(), seq(headerR, timeline,
      {BF_WATER_POKE_R, BF_WATER_UNPOKE_EARLY_R, BF_END_TRIAL}));

  every.push_back(trial(goR, p, &plain, 4, {sampled}));
  expectSequence("no response", every.back(), seq(headerR, timeline, {BF_RESP_OMIT, BF_END_TRIAL}));

  every.push_back(trial(noGo, p, &plain, 5, {sampled}));
  expectSequence("no-go withheld", every.back(), seq(headerN, timelineL, {BF_WATER_POKE_NONE, BF_END_TRIAL}));

  every.push_back(trial(noGo, p, &plain, 6, {sampled, {rightWell, 50, 60}}));
  expectSequence("no-go poked", every.back(), seq(headerN, timelineL,
      {BF_WATER_POKE_R, BF_WATER_POKE_ERROR_R, BF_END_TRIAL}));

  every.push_back(trial(goR, p, &plain, 7, {}));
  expectSequence("lazy", every.back(), seq(headerR, {},
      {BF_LIGHTS_ON, BF_LAZY_RAT, BF_LIGHTS_OFF, BF_INVALID_TRIAL, BF_END_TRIAL}));

  every.push_back(trial(goR, p, &plain, 8, {{odorPort, 5, 10}}));
  expectSequence("early unpoke, before odor", every.back(), seq(headerR, {},
      {BF_LIGHTS_ON, BF_ODOR_POKE, BF_ODOR_UNPOKE_EARLY, BF_LIGHTS_OFF, BF_INVALID_TRIAL, BF_END_TRIAL}));

  every.push_back(trial(goR, p, &plain, 9, {{odorPort, 5, 20}}));
  expectSequence("early unpoke, sampling", every.back(), seq(headerR, {},
      {BF_LIGHTS_ON, BF_ODOR_POKE, BF_ODOR_1_ON, BF_ODOR_UNPOKE_EARLY_SAMPLING, BF_LIGHTS_OFF,
       BF_INVALID_TRIAL, BF_END_TRIAL}));

  printf("the footer\n");
  every.push_back(trial(goR, p, &correcting, 10, {sampled, {leftWell, 50, 80}}));
  expectSequence("an error a correction budget repeats", every.back(), seq(headerR, timeline,
      {BF_WATER_POKE_L, BF_WATER_POKE_ERROR_L, BF_INVALID_TRIAL, BF_END_TRIAL}));
  correction.onAdvance(true); // the right side's one correction trial is spent
  every.push_back(trial(goR, p, &correcting, 11, {sampled, {leftWell, 50, 80}}));
  expectSequence("an error past the budget advances", every.back(), seq(headerR, timeline,
      {BF_WATER_POKE_L, BF_WATER_POKE_ERROR_L, BF_END_TRIAL}));
  every.push_back(trial(noGo, p, &correcting, 12, {sampled, {rightWell, 50, 60}}));
  expectSequence("a no-go false alarm never repeats", every.back(), seq(headerN, timelineL,
      {BF_WATER_POKE_R, BF_WATER_POKE_ERROR_R, BF_END_TRIAL}));
  every.push_back(trial(goR, p, nullptr, 13, {sampled, {leftWell, 50, 80}}));
  expectSequence("no policy (a pool task) advances on any completed trial", every.back(),
      seq(headerR, timeline, {BF_WATER_POKE_L, BF_WATER_POKE_ERROR_L, BF_END_TRIAL}));

  printf("the tie-break\n");
  // Both beams broken at once: right first on an even completed count, left on
  // an odd one, and never a draw from the session RNG.
  every.push_back(trial(goR, p, &plain, 20, {sampled, {rightWell, 50, 80}, {leftWell, 50, 80}}));
  expectSequence("a double break on an even count resolves right", every.back(), seq(headerR, timeline,
      {BF_WATER_POKE_R, BF_CORRECT, BF_FLUID_R, BF_STOP_FLUID_G_R, BF_WATER_UNPOKE_R, BF_END_TRIAL}));
  every.push_back(trial(goR, p, &plain, 21, {sampled, {rightWell, 50, 80}, {leftWell, 50, 80}}));
  expectSequence("a double break on an odd count resolves left", every.back(), seq(headerR, timeline,
      {BF_WATER_POKE_L, BF_WATER_POKE_ERROR_L, BF_END_TRIAL}));
  every.push_back(trial(goR, p, nullptr, 21, {sampled, {rightWell, 50, 80}, {leftWell, 50, 80}}));
  expectSequence("a one-sided pool keeps right first", every.back(), seq(headerR, timeline,
      {BF_WATER_POKE_R, BF_CORRECT, BF_FLUID_R, BF_STOP_FLUID_G_R, BF_WATER_UNPOKE_R, BF_END_TRIAL}));

  printf("every trial\n");
  const std::vector<int> outcomes = {
      BF_CORRECT, BF_WATER_POKE_ERROR_L, BF_WATER_POKE_ERROR_R, BF_WATER_UNPOKE_EARLY_L,
      BF_WATER_UNPOKE_EARLY_R, BF_RESP_OMIT, BF_WATER_POKE_NONE, BF_LAZY_RAT, BF_ODOR_UNPOKE_EARLY,
      BF_ODOR_UNPOKE_EARLY_SAMPLING};
  bool oneOutcome = true, endsWithEndTrial = true, headed = true;
  for (const std::vector<int> &codes : every) {
    int n = 0;
    for (int c : codes) for (int o : outcomes) if (c == o) n++;
    if (n != 1) oneOutcome = false;
    if (codes.empty() || codes.back() != BF_END_TRIAL) endsWithEndTrial = false;
    if (codes.size() < 3 || codes[0] != BF_TRIAL_START) headed = false;
    if (codes.size() >= 3 && codes[1] != BF_TRIAL_GO_LEFT && codes[1] != BF_TRIAL_GO_RIGHT && codes[1] != BF_TRIAL_NO_GO) headed = false;
  }
  printf("  [%s] exactly one outcome code per trial\n", oneOutcome ? "pass" : "FAIL"); if (!oneOutcome) failures++;
  printf("  [%s] every trial ends with END_TRIAL\n", endsWithEndTrial ? "pass" : "FAIL"); if (!endsWithEndTrial) failures++;
  printf("  [%s] every trial opens with the header\n", headed ? "pass" : "FAIL"); if (!headed) failures++;
  bool retired = true;
  for (const std::vector<int> &codes : every) for (int c : codes) if (c == 1 || c == 2) retired = false;
  (void)retired;

  if (failures) { printf("%d FAILURE(S)\n", failures); return 1; }
  printf("ALL TRIAL STREAM TESTS PASSED\n");
  return 0;
}

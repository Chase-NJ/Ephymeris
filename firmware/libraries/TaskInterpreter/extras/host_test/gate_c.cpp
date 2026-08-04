/*  GATE C — a table that went over the wire must be the table that was compiled.
 *
 *  Gates A and B proved the interpreter walks a COMPILED-IN table correctly. Every
 *  one of those results is about a `static const TgTable` the C++ compiler laid
 *  out. A real box never sees that table: it sees bytes, framed into lines, hex
 *  encoded, checksummed, and decoded field by field by TgReceive.h. Gate C is the
 *  step that connects the two, and without it "the interpreter is correct" is a
 *  statement about an artifact no board will ever hold.
 *
 *  ------------------------------------------------------------------------
 *  TWO CLAIMS, AND THE SECOND IS NOT IMPLIED BY THE FIRST
 *
 *  STRUCTURAL — every field of the received table equals the compiled-in one.
 *  Exhaustive and cheap, and it localises a failure to a field name rather than to
 *  "seed 1 diverged at trial 812".
 *
 *  BEHAVIOURAL — the two tables, driven by the same randomised animals, produce
 *  byte-identical strobe streams. This is the claim that matters, and it is the
 *  one a structural check cannot make on its own: a field can compare equal and
 *  still be read through a different path, and a decode that transposed two
 *  UNUSED fields would pass structurally while meaning nothing.
 *
 *  Run together, they say: the wire preserves the table, and the table preserves
 *  the behaviour. That is the whole of what Phase 4 has to establish before a
 *  board runs anything.
 *
 *  ------------------------------------------------------------------------
 *  The upload arrives on stdin as protocol lines, produced by the same
 *  `taskgraph.transport.frame()` a real host will use. Nothing here knows how to
 *  build them, deliberately: a gate that framed its own input would be testing a
 *  framer nobody ships.
 */

#include <cstdio>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

#include "Arduino.h"

MockBox mock;

#include <TgReceive.h>

/*  The compiled-in reference: specs/grgl_2odor.yaml through the C emitter, which
    is the exact artifact Gates A and B validated. */
#include "grgl_table.h"

#include "battery.h" // the shared randomised animal; needs TG_IDX_* above

static TgTable received;
static TgRx rx;

/* ---------------------------------------------------------------- *
 *  Structural comparison
 * ---------------------------------------------------------------- */

static int differences = 0;

static void differ(const char *what, long a, long b, int index = -1)
{
  if (differences < 20)
  {
    if (index >= 0)
      std::printf("  DIFF %s[%d]  compiled=%ld received=%ld\n", what, index, a, b);
    else
      std::printf("  DIFF %s  compiled=%ld received=%ld\n", what, a, b);
  }
  differences++;
}

#define CMP(field) \
  if ((long)a.field != (long)b.field) differ(#field, (long)a.field, (long)b.field)
#define CMPI(field, i) \
  if ((long)a.field != (long)b.field) differ(#field, (long)a.field, (long)b.field, i)

static void compareTables(const TgTable &a, const TgTable &b)
{
  CMP(nNodes); CMP(nEdges); CMP(nTiming); CMP(nActions);
  CMP(nTrialTypes); CMP(nPorts); CMP(nStimuli); CMP(nWatch);
  CMP(nStageRows); CMP(nTimingSets);
  CMP(specHash);
  /*  tableCrc and valid are NOT compared. The compiled-in table has neither -- it
      never crossed a wire, so there is nothing to have checksummed it. That
      asymmetry is the point of both fields. */

  if (a.nNodes != b.nNodes || a.nEdges != b.nEdges)
    return; // counts disagree; indexing past them would report noise

  for (uint8_t i = 0; i < a.nNodes; i++)
  {
    CMPI(nodes[i].type, i); CMPI(nodes[i].durIdx, i); CMPI(nodes[i].strobe, i);
    CMPI(nodes[i].watchMask, i); CMPI(nodes[i].actionIdx, i);
    CMPI(nodes[i].actionCount, i); CMPI(nodes[i].edgeIdx, i);
    CMPI(maxDwell[i], i);
  }
  for (uint8_t i = 0; i < a.nEdges; i++)
  {
    CMPI(edges[i].trigger, i); CMPI(edges[i].guard, i);
    CMPI(edges[i].target, i); CMPI(edges[i].effect, i);
  }
  for (uint8_t i = 0; i < a.nTiming; i++)
    CMPI(timing[i], i);
  for (uint8_t i = 0; i < a.nActions; i++)
  {
    CMPI(actions[i].channel, i); CMPI(actions[i].op, i);
  }
  for (uint8_t i = 0; i < a.nTrialTypes; i++)
  {
    CMPI(trialTypes[i].stimulus0, i); CMPI(trialTypes[i].stimulus1, i);
    CMPI(trialTypes[i].stimulus2, i); CMPI(trialTypes[i].stimulus3, i);
    CMPI(trialTypes[i].target, i); CMPI(trialTypes[i].weight, i);
    CMPI(trialTypes[i].rewardLine, i); CMPI(trialTypes[i].rewardDurIdx, i);
  }
  for (uint8_t i = 0; i < a.nPorts; i++)
  {
    CMPI(ports[i].channel, i); CMPI(ports[i].rewardLine, i);
    CMPI(ports[i].enterCode, i); CMPI(ports[i].errorCode, i);
    CMPI(ports[i].breakCode, i); CMPI(ports[i].exitCode, i);
    CMPI(ports[i].rewardCode, i); CMPI(ports[i].rewardStopCode, i);
    CMPI(ports[i].rewardDurIdx, i);
  }
  for (uint8_t i = 0; i < a.nStimuli; i++)
  {
    CMPI(stimuli[i].emitter, i); CMPI(stimuli[i].onCode, i);
  }
  for (uint8_t i = 0; i < a.nStageRows; i++)
  {
    CMPI(stageRows[i].atTrial, i); CMPI(stageRows[i].count, i);
    CMPI(stageRows[i].firstIdx, i);
  }
  for (uint8_t i = 0; i < a.nTimingSets; i++)
  {
    CMPI(timingSets[i].idx, i); CMPI(timingSets[i].ms, i);
  }
  for (uint8_t i = 0; i < TG_WATCH_SLOTS; i++)
  {
    CMPI(watchPin[i], i); CMPI(watchPort[i], i);
  }
}

/* ---------------------------------------------------------------- *
 *  Behavioural comparison
 * ---------------------------------------------------------------- */

static const char *nameOf(int c)
{
  switch (c)
  {
  case 101: return "ODOR_1_ON";        case 103: return "ODOR_3_ON";
  case 222: return "LIGHTS_ON";        case 223: return "LAZY_RAT";
  case 224: return "ODOR_POKE";        case 225: return "ODOR_UNPOKE_EARLY";
  case 226: return "ODOR_UNPOKE";      case 233: return "LIGHTS_OFF";
  case 242: return "END_CORRECT_ITI";  case 243: return "END_INCORRECT_ITI";
  case 247: return "ODOR_OFF";         case 248: return "WATER_POKE_L";
  case 249: return "WATER_POKE_R";     case 250: return "WATER_UNPOKE_EARLY_L";
  case 251: return "WATER_UNPOKE_EARLY_R"; case 252: return "FLUID_L";
  case 253: return "FLUID_R";          case 254: return "WATER_UNPOKE_L";
  case 255: return "WATER_UNPOKE_R";   case 257: return "WATER_POKE_ERROR_L";
  case 258: return "WATER_POKE_ERROR_R"; case 262: return "RESP_OMIT";
  case 357: return "STOP_FLUID_G_R";   case 369: return "STOP_FLUID_G_L";
  default: return "?";
  }
}

static void dump(const char *label, const std::vector<MockEvent> &v)
{
  std::printf("      %-11s", label);
  for (const auto &e : v)
    std::printf(" %s@%lu", nameOf(e.code), e.t);
  std::printf("\n");
}

/*  One trial on one table, returning the stream it produced. */
static std::vector<MockEvent> runOn(TgTable table, const Script &s, const TaskParams &p)
{
  arm(s);
  syncTiming(table, p);
  TrialClock clk;
  clk.beginSession();
  TgRun r;
  tgRunTrial(table, r, p, clk, s.trial);
  return mock.emitted;
}

int main(int argc, char **argv)
{
  const unsigned long seed = (argc > 1) ? std::strtoul(argv[1], 0, 10) : 20260803UL;
  const int nTrials = (argc > 2) ? std::atoi(argv[2]) : 2000;

  /* ---- receive ---- */
  rx.table = &received;
  std::string line;
  while (std::getline(std::cin, line))
  {
    while (!line.empty() && (line.back() == '\r' || line.back() == '\n'))
      line.pop_back();
    if (line.size() > TG_RX_LINE_MAX)
    {
      tgRxFail(rx, TG_FAIL_LINE);
      break;
    }
    if (!tgFeedLine(rx, line.c_str()))
      break;
  }

  if (!received.valid)
  {
    std::printf("upload=FAILED reason=%s\n", tgFailName(rx.fail));
    std::printf("structural=1 behavioural=1\n"); // a refused table fails the gate
    return 1;
  }
  std::printf("upload=OK crc=%08lx\n", (unsigned long)received.tableCrc);

  /* ---- structural ---- */
  compareTables(TG_TABLE, received);
  std::printf("structural=%d\n", differences);

  /* ---- behavioural ---- */
  Rng rng{seed};
  int checked = 0, diverged = 0, hangs = 0;
  int outcomes[6] = {0, 0, 0, 0, 0, 0};

  for (int i = 0; i < nTrials; i++)
  {
    TaskParams p;
    clampTaskParams(p);
    applyStage(p, (int)rng.in(0, 120));
    const Script s = drawScript(rng, p);

    std::vector<MockEvent> a, b;
    bool hung = false;
    try
    {
      a = runOn(TG_TABLE, s, p);
      b = runOn(received, s, p);
    }
    catch (const MockHang &)
    {
      hung = true;
    }
    if (hung)
    {
      hangs++;
      continue;
    }

    checked++;
    for (const auto &e : a)
    {
      if (e.code == 242) outcomes[0]++;
      else if (e.code == 257 || e.code == 258) outcomes[1]++;
      else if (e.code == 262) outcomes[2]++;
      else if (e.code == 223) outcomes[3]++;
      else if (e.code == 225) outcomes[4]++;
      else if (e.code == 250 || e.code == 251) outcomes[5]++;
    }

    bool same = a.size() == b.size();
    for (size_t k = 0; same && k < a.size(); k++)
      same = a[k].code == b[k].code && a[k].t == b[k].t;
    if (!same)
    {
      if (diverged < 5)
      {
        std::printf("  DIVERGENCE #%d  trial=%u engage=%lu..%lu resp=%d %lu..%lu\n",
                    diverged + 1, s.trial, s.engageAt, s.engageTo, s.respPin,
                    s.respAt, s.respTo);
        dump("compiled", a);
        dump("uploaded", b);
      }
      diverged++;
    }
  }

  std::printf("seed=%lu trials=%d checked=%d behavioural=%d hangs=%d\n",
              seed, nTrials, checked, diverged, hangs);
  std::printf("coverage correct=%d wrong=%d omission=%d abstain=%d holdbreak=%d holdfail=%d\n",
              outcomes[0], outcomes[1], outcomes[2], outcomes[3], outcomes[4], outcomes[5]);
  return (differences == 0 && diverged == 0 && hangs == 0) ? 0 : 1;
}

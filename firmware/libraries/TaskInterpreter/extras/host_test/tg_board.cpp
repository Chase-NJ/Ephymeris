/*  A board that speaks the upload protocol, off-target.
 *
 *  Reads protocol lines on stdin, writes the board's replies to stdout, and ends
 *  with a STATUS line describing the table it is holding. That is the whole
 *  interface, and it is deliberately dumb: every scenario -- a flipped bit, a
 *  chunk out of order, a header claiming 200 nodes -- is constructed on the
 *  PYTHON side, where mutating a byte is one line, instead of being enumerated
 *  here as C++ special cases.
 *
 *  WHY A SIMULATOR RATHER THAN A UNIT TEST. The thing worth testing is not
 *  "does tgAdoptHeader reject a bad count" but "does a board handed this exact
 *  byte stream refuse to run". Driving the real entry point with real lines means
 *  the test exercises the parser, the state machine, the CRC and the record
 *  decode together -- and the same binary becomes the far end of Gate C.
 *
 *  It runs the SAME TgReceive.h an ATmega2560 runs. No mock of the receiver
 *  exists; the only thing mocked is Serial and the clock.
 */

#include <cstdio>
#include <cstring>
#include <iostream>
#include <string>

#include "Arduino.h"

MockBox mock;

#include <TaskInterpreter.h> // the receiver, and the CAP announce a real board makes

static TgTable table;
static TgRx rx;

/*  Everything the board has said since the last call. The shim captures Serial
    into mock.out; a real board would have put it on the wire immediately, so it
    is drained after every line rather than at the end -- which keeps the
    transcript interleaved the way a host actually sees it. */
static void drain()
{
  static size_t sent = 0;
  for (; sent < mock.out.size(); sent++)
    std::printf("%s\n", mock.out[sent].c_str());
  /*  Line-buffered like a serial port. Without this the pipe is block-buffered
      and the simulator answers only at exit -- which turns an interactive
      protocol into a batch one, and would let the uploader's ACK handling go
      completely untested. */
  std::fflush(stdout);
}

int main()
{
  rx.table = &table;

  /*  The same banner a flashed board emits, from the same function. A simulator
      that skipped it would let the uploader's capability check -- the entire
      reason CAP exists -- go untested until it met real hardware. */
  tgAnnounceCapabilities();
  Serial.println(F("READY"));
  drain();

  std::string line;
  while (std::getline(std::cin, line))
  {
    while (!line.empty() && (line.back() == '\r' || line.back() == '\n'))
      line.pop_back();

    /*  The line-length ceiling the sketch enforces, applied here so the
        truncation case is reachable from a test. This is the bug the whole
        protocol exists to close: readLineInto() silently drops the tail of an
        overlong line, and "a lost token is not an error the board can see".
        Here it is an error the board can see. */
    if (line.size() > TG_RX_LINE_MAX)
      tgRxFail(rx, TG_FAIL_LINE), tgReportFailure(rx);
    else if (!tgFeedLine(rx, line.c_str()))
      tgReportFailure(rx);
    drain();
  }

  /*  What the board would run, if asked. `valid` is the only thing standing
      between a partially-received table and a session, so it is first. */
  std::printf("STATUS valid=%d crc=%08lx spechash=%08lx state=%u fail=%s\n",
              table.valid ? 1 : 0, (unsigned long)table.tableCrc,
              (unsigned long)table.specHash, rx.state, tgFailName(rx.fail));
  std::printf("COUNTS %u %u %u %u %u %u %u %u %u %u\n",
              table.nNodes, table.nEdges, table.nTiming, table.nActions,
              table.nTrialTypes, table.nPorts, table.nStimuli, table.nWatch,
              table.nStageRows, table.nTimingSets);

  /*  A digest of the decoded table, so a test can prove the bytes landed in the
      right FIELDS and not merely that the right number of them arrived. A CRC
      that passes while a record decode is transposed would otherwise look like a
      success. */
  if (table.nNodes)
    std::printf("NODE0 %u %u %u %u %u %u %u\n", table.nodes[0].type,
                table.nodes[0].durIdx, table.nodes[0].strobe, table.nodes[0].watchMask,
                table.nodes[0].actionIdx, table.nodes[0].actionCount,
                table.nodes[0].edgeIdx);
  if (table.nNodes > 1)
  {
    const TgNode &n = table.nodes[table.nNodes - 1];
    std::printf("NODEN %u %u %u %u %u %u %u\n", n.type, n.durIdx, n.strobe,
                n.watchMask, n.actionIdx, n.actionCount, n.edgeIdx);
  }
  if (table.nPorts)
  {
    const TgPort &p = table.ports[0];
    std::printf("PORT0 %u %u %u %u %u %u %u %u %u\n", p.channel, p.rewardLine,
                p.enterCode, p.errorCode, p.breakCode, p.exitCode, p.rewardCode,
                p.rewardStopCode, p.rewardDurIdx);
  }
  if (table.nTiming)
  {
    std::printf("TIMING");
    for (uint8_t i = 0; i < table.nTiming; i++)
      std::printf(" %u", table.timing[i]);
    std::printf("\n");
  }
  if (table.nNodes)
  {
    std::printf("DWELL");
    for (uint8_t i = 0; i < table.nNodes; i++)
      std::printf(" %u", table.maxDwell[i]);
    std::printf("\n");
  }
  std::printf("WATCH");
  for (uint8_t i = 0; i < TG_WATCH_SLOTS; i++)
    std::printf(" %u/%u", table.watchPin[i], table.watchPort[i]);
  std::printf("\n");
  return table.valid ? 0 : 1;
}

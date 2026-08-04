/*
Author: Chase Johnston
Purpose:
  Development sketch for the table-driven task interpreter.

  IT ANNOUNCES, AND IT RECEIVES. The CAP handshake and the table upload are both
  live here: a host can hand this board a compiled table and it will accept a good
  one, refuse a bad one, and say which. What it deliberately does NOT do is run a
  session -- the interpreter is proved off-target (Phase 3: byte-identical strobe
  streams against runTrial() across a randomised battery) but has never driven a
  pin, and the sketch that runs a trial is a separate, later decision.

  ADD, DON'T MODIFY. This does not replace any sketch in the firmware repo. The
  existing behaviour sketches keep running and shipping unchanged; runTrial() is
  not touched until Phase 7. A box runs this only when someone deliberately
  flashes it.

  NOT FOR ANIMAL USE. It drives no trial and delivers no reward.
*/

#include <BehaviorBox.h>     // pins, strobes, TaskParams -- the reference repo's shared layer
#include <TaskInterpreter.h> // this repo's libraries/TaskInterpreter/

/*  The one table shape, from TgInterpret.h. Reserved at full capacity so the
    footprint cannot depend on which spec was last uploaded: a box must not run
    out of memory partway through a session because this table is bigger than the
    last one. `valid` stays false until a whole-table CRC verifies. */
TgTable table;
TgRx rx;
TgRun run;
TrialClock clock;
TaskParams params;

/*  Line assembly lives HERE, not in TgReceive.h.

    The receiver takes complete lines and is therefore testable off-target by
    handing it strings -- which is how all fourteen of its failure modes are
    exercised without a board. What is left here is the part that genuinely needs
    a serial port: buffering, and the length ceiling.

    THE CEILING IS THE POINT. readLineInto() in BehaviorBox.h truncates an
    overlong line and drops the rest, and its own comment says why that is bad:
    "a lost token is not an error the board can see, it just runs on the wrong
    value." An overlong line here is an error the board CAN see, and says so. */
static char line[TG_RX_LINE_MAX + 1];
static uint16_t lineLen = 0;
static bool lineOverflowed = false;

static void handleLine()
{
  if (lineOverflowed)
  {
    tgRxFail(rx, TG_FAIL_LINE);
    tgReportFailure(rx);
  }
  else if (!tgFeedLine(rx, line))
  {
    tgReportFailure(rx);
  }
  lineLen = 0;
  lineOverflowed = false;
}

void setup()
{
  initBoxHardware(); // configure every box pin + land all outputs LOW
  Serial.begin(TG_BAUD_RATE);

  rx.table = &table;

  /* Capabilities BEFORE a bare READY, never appended to it.

     The host matches readiness as an exact whole line (Ephymeris
     ports/handler.py:337) and ignores anything preceding it, so this ordering is
     what lets an un-migrated host talk to a migrated box with no changes at all:
     it logs the CAP lines to scrollback and proceeds down the existing START
     path. Reverse the order and every deployed host fails with "board never
     reported READY". */
  tgAnnounceCapabilities();

  /*  The table's footprint, now a number the linker also agrees with.

      This line used to carry a caveat: nothing wrote `table`, so the optimiser
      folded every read of it to zero, proved the object dead, and --gc-sections
      removed all 2 KB -- the build reported 212 bytes of globals for a sketch
      reserving a 2020-byte table. Receiving a table from the wire is what makes
      the object live, so the map file and this constant now say the same thing.
      That is the same trap the first AVR RAM sweep fell into
      (docs/spikes/avr-ram.md), and the reason that sweep ended up loading its
      probe from Serial too.

      It also caught a real bug: the board reported 2019 here while the host test
      measured 2024, because two uint32 fields sat at an offset AVR and the host
      align differently. Keep the line. */
  Serial.print(F("INFO\tTABLEBYTES="));
  Serial.println((unsigned int)sizeof(TgTable));

  Serial.println(F("READY"));
}

void loop()
{
  while (Serial.available())
  {
    const int c = Serial.read();
    if (c < 0)
      break;
    if (c == '\n' || c == '\r')
    {
      /*  Ignore the empty line a CRLF pair produces, rather than feeding "" to
          the receiver -- a bare LF after CR is not a message. */
      if (lineLen || lineOverflowed)
      {
        line[lineLen] = 0;
        handleLine();
      }
      continue;
    }
    if (lineLen >= TG_RX_LINE_MAX)
    {
      /*  Keep consuming to the terminator so the REST of an overlong line is not
          reinterpreted as the next command. Truncating and resyncing mid-line is
          how a dropped token becomes a plausible-looking different one. */
      lineOverflowed = true;
      continue;
    }
    line[lineLen++] = (char)c;
  }

  /*  No trial loop. The interpreter is finished and proved off-target, but
      running a session is a decision about an animal in a box, and it gets its
      own sketch and its own review rather than appearing here because the parts
      happened to be ready. */
}

/*
  tasksim.cpp -- the task simulator: the real sketch and the real trial runner,
  run on the host against a clock that only moves when the firmware waits
  (docs/TASKS.md#simulating-a-task).

  Nothing of the task is restated here. GRGL.ino is included as it stands, with
  the simulator's TaskPins.h and TaskTrials.h beside it in place of the two
  generated headers, on the instrumented host shim (host_test/box_shim). What
  this file adds is the box around the firmware: who types on the serial line,
  and what breaks the three IR beams.

  IT KNOWS NO ANIMAL. It reports every output the firmware switches -- the
  trial light, the vacuum, an odor line, a fluid line -- and is told when each
  beam is broken. Whatever decides that lives in the host (the sidecar's
  simulation package), which sees only what an animal in the box could: light,
  odor and water.

  THE CONVERSATION, line by line, the host on stdin and this program on stdout:

    1. The table, before the sketch's own globals are built:
         CODE <NAME> <code>      one per vocabulary name; unknown names are ignored
         ROW <go> <odor> <L|R|N> <reward> <onset> <fluid> <stop> <ms> <type>
         STOP_AT <ms>            the host's STOP line arrives at this session time
         LIMIT <ms>              give up with @ABORT past this much session time
         END
    2. The start handshake, the firmware's own (docs/TASKS.md#the-start-line):
       every stdin line goes to its serial input, every serial line it prints
       comes back, until a START line has gone in.
    3. The session. Serial output (the strobes) still comes back as printed.
       Each time an output changes level:
         @ <session ms> <light|vac|odor<i>|fluid<i>> <0|1>
       and the firmware waits for the host's answer, any of
         L <odor|right|left> <from ms> <to ms>   that beam is broken for [from, to)
         X <odor|right|left>                     forget that beam's windows
       closed by a line holding only a full stop. `@STOP <session ms>` marks
       the trial boundary at which the sketch found the STOP line waiting.
    4. @END when the sketch has ended its session.

  All times are milliseconds since START_SESSION, the clock the strobes carry.

  Built by `build.py` in the folder above (`python -m ephymeris_sidecar.simulation
  --out DIR`), once per selection mode. It lives with the code that drives it
  rather than with the firmware: the conversation above has two ends, and
  `session.py` is the other.
*/

#include <Arduino.h>
#include <new>
#include "TaskPins.h"

struct BbsimRow
{
  bool isGo;
  int odorIndex;
  char side;
  int rewardIndex;
  int onsetCode, fluidCode, stopFluidCode, rewardMs, typeCode;
};
static std::vector<BbsimRow> bbsim_rows;

struct BbsimWindow
{
  unsigned long from, to;
};
enum { BBSIM_BEAM_ODOR, BBSIM_BEAM_RIGHT, BBSIM_BEAM_LEFT, BBSIM_BEAM_COUNT };
static std::vector<BbsimWindow> bbsim_windows[BBSIM_BEAM_COUNT];

static bool bbsim_inSession = false;
static unsigned long bbsim_limitMs = 24UL * 60UL * 60UL * 1000UL;
static unsigned long bbsim_stopAtMs = 0;
static bool bbsim_stopping = false;
static bool bbsim_stopSaid = false;
static int bbsim_level[BB_MAX_PIN];

static void bbsim_abort(const char *why)
{
  fwrite(bb_serialOut.data(), 1, bb_serialOut.size(), stdout);
  printf("@ABORT %s\n", why);
  fflush(stdout);
  exit(3);
}

static bool bbsim_readLine(char *line, size_t cap)
{
  if (!fgets(line, (int)cap, stdin))
    return false;
  size_t n = strlen(line);
  while (n > 0 && (line[n - 1] == '\n' || line[n - 1] == '\r'))
    line[--n] = '\0';
  return true;
}

static void bbsim_flush()
{
  if (!bb_serialOut.empty())
  {
    fwrite(bb_serialOut.data(), 1, bb_serialOut.size(), stdout);
    bb_serialOut.clear();
  }
  fflush(stdout);
}

static const char *const bbsim_codeNames[BBSIM_CODE_COUNT] = {
#define X(name) #name,
    BBSIM_CODE_NAMES(X)
#undef X
};

static bool bbsim_loadTable()
{
  char line[512];
  bool named[BBSIM_CODE_COUNT] = {false};
  while (bbsim_readLine(line, sizeof(line)))
  {
    char name[64];
    int code;
    BbsimRow row;
    int go;
    unsigned long limit;
    if (strcmp(line, "END") == 0)
    {
      for (int i = 0; i < BBSIM_CODE_COUNT; i++)
        if (!named[i])
        {
          snprintf(line, sizeof(line), "no code for %s", bbsim_codeNames[i]);
          bbsim_abort(line);
        }
      if (bbsim_rows.empty())
        bbsim_abort("no trial rows");
      return true;
    }
    if (sscanf(line, "CODE %63s %d", name, &code) == 2)
    {
      for (int i = 0; i < BBSIM_CODE_COUNT; i++)
        if (strcmp(name, bbsim_codeNames[i]) == 0)
        {
          bbsim_code[i] = code;
          named[i] = true;
        }
    }
    else if (sscanf(line, "ROW %d %d %c %d %d %d %d %d %d", &go, &row.odorIndex, &row.side,
                    &row.rewardIndex, &row.onsetCode, &row.fluidCode, &row.stopFluidCode,
                    &row.rewardMs, &row.typeCode) == 9)
    {
      row.isGo = go != 0;
      if ((int)bbsim_rows.size() >= BOX_MAX_TRIAL_TYPES)
        bbsim_abort("more trial rows than the simulator was built for");
      if (row.odorIndex < 0 || row.odorIndex >= BOX_NUM_ODORS)
        bbsim_abort("an odor line the simulator was not built with");
      if (row.isGo && (row.rewardIndex < 0 || row.rewardIndex >= BOX_NUM_FLUIDS))
        bbsim_abort("a fluid line the simulator was not built with");
      if (row.isGo && row.side != 'L' && row.side != 'R')
        bbsim_abort("a go row with no side");
      bbsim_rows.push_back(row);
    }
    else if (sscanf(line, "LIMIT %lu", &limit) == 1)
      bbsim_limitMs = limit;
    else if (sscanf(line, "STOP_AT %lu", &limit) == 1)
    {
      bbsim_stopAtMs = limit;
      bbsim_stopping = true;
    }
    else
      bbsim_abort("a table line the simulator cannot read");
  }
  bbsim_abort("the table ended before END");
  return false;
}
static const bool bbsim_tableLoaded = bbsim_loadTable();

/*  <ctime> declares clock(); the sketch names its TrialClock the same. */
#define clock bbsim_sketchClock
#include "GRGL.ino"

static unsigned long bbsim_sessionMs() { return millis() - clock.recStart; }

static int bbsim_beamOf(const char *name)
{
  if (strcmp(name, "odor") == 0) return BBSIM_BEAM_ODOR;
  if (strcmp(name, "right") == 0) return BBSIM_BEAM_RIGHT;
  if (strcmp(name, "left") == 0) return BBSIM_BEAM_LEFT;
  bbsim_abort("an answer names no beam");
  return -1;
}

static void bbsim_hearAnswer()
{
  char line[128];
  while (bbsim_readLine(line, sizeof(line)))
  {
    char beam[16];
    unsigned long from, to;
    if (strcmp(line, ".") == 0)
      return;
    if (sscanf(line, "L %15s %lu %lu", beam, &from, &to) == 3)
    {
      BbsimWindow window = {clock.recStart + from, clock.recStart + to};
      bbsim_windows[bbsim_beamOf(beam)].push_back(window);
    }
    else if (sscanf(line, "X %15s", beam) == 1)
      bbsim_windows[bbsim_beamOf(beam)].clear();
    else
      bbsim_abort("an answer the simulator cannot read");
  }
  exit(4);
}

static void bbsim_onPinWrite(int pin, int value, unsigned long)
{
  if (bbsim_level[pin] == value)
    return;
  bbsim_level[pin] = value;
  if (!bbsim_inSession)
    return;

  char name[16] = "";
  if (pin == trialLight)
    snprintf(name, sizeof(name), "light");
  else if (pin == vac)
    snprintf(name, sizeof(name), "vac");
  for (int i = 0; i < NUM_ODORS && !name[0]; i++)
    if (pin == Odors[i])
      snprintf(name, sizeof(name), "odor%d", i);
  for (int i = 0; i < NUM_FLUIDS && !name[0]; i++)
    if (pin == Fluids[i])
      snprintf(name, sizeof(name), "fluid%d", i);
  if (!name[0])
    return;

  bbsim_flush();
  printf("@ %lu %s %d\n", bbsim_sessionMs(), name, value);
  fflush(stdout);
  bbsim_hearAnswer();
}

static int bbsim_onPinRead(int pin)
{
  int beam = pin == odorPort ? BBSIM_BEAM_ODOR
           : pin == rightWell ? BBSIM_BEAM_RIGHT
           : pin == leftWell ? BBSIM_BEAM_LEFT : -1;
  if (beam < 0)
    return -1;
  unsigned long now = millis();
  if (bbsim_inSession && bbsim_sessionMs() > bbsim_limitMs)
    bbsim_abort("the session ran past its limit");
  const std::vector<BbsimWindow> &windows = bbsim_windows[beam];
  for (size_t i = 0; i < windows.size(); i++)
    if (now >= windows[i].from && now < windows[i].to)
      return LOW;
  return HIGH;
}

/*  The serial line while the firmware waits for its start: one stdin line per
    ask. Once START has gone in, the sketch only asks at a trial boundary, for
    STOP: it finds one from the session time the host named, as it would a line
    a host had sent at that moment and the board had buffered since. */
static void bbsim_onSerialEmpty()
{
  if (bbsim_inSession)
  {
    if (bbsim_stopping && !bbsim_stopSaid && bbsim_sessionMs() >= bbsim_stopAtMs)
    {
      bbsim_stopSaid = true;
      bb_feed("STOP");
      bbsim_flush();
      printf("@STOP %lu\n", bbsim_sessionMs());
      fflush(stdout);
    }
    return;
  }
  char line[512];
  bbsim_flush();
  if (!bbsim_readLine(line, sizeof(line)))
    exit(0);
  bb_feed(line);
  if (strncmp(line, "START", 5) == 0)
    bbsim_inSession = true;
}

int main()
{
  bb_onPinRead = bbsim_onPinRead;
  bb_onPinWrite = bbsim_onPinWrite;
  bb_onSerialEmpty = bbsim_onSerialEmpty;
  setup();
  while (!sessionComplete)
    loop();
  bbsim_flush();
  printf("@END\n");
  fflush(stdout);
  return 0;
}

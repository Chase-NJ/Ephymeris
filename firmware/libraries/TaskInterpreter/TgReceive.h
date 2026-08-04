#ifndef TG_RECEIVE_H
#define TG_RECEIVE_H

/* ============================================================= *
 *  Receiving a table, and refusing a bad one.
 *
 *  THE BUG THIS EXISTS TO CLOSE is named by the firmware itself, at
 *  BehaviorBox.h:701-706, about the START line: "a lost token is not an error
 *  the board can see, it just runs on the wrong value." A truncated START line
 *  produces a session nobody specified, silently. The uploaded table is a far
 *  bigger surface for the same failure, so this path is built so that a table
 *  which arrives wrong is REFUSED rather than run.
 *
 *  Three independent things have to agree before a table is usable:
 *
 *    1. the byte count the host declared in TABLE BEGIN;
 *    2. the byte count implied by the header's own record counts;
 *    3. the CRC32 -- stated twice, once in TABLE BEGIN and once as the payload's
 *       last four bytes.
 *
 *  Any disagreement fails the upload. `table.valid` stays false, and the SKETCH
 *  refuses to start a session on that -- which is why the flag lives on the table
 *  rather than in here.
 *
 *  ---------------------------------------------------------------
 *  NO STAGING BUFFER, AND NO memcpy.
 *
 *  Bytes are decoded into TgTable one RECORD at a time, through a 24-byte
 *  staging buffer, so a record straddling two chunks costs nothing and the peak
 *  RAM cost of an upload is 24 bytes rather than a second copy of the table. It
 *  also means the in-memory layout of TgTable is not part of the wire contract:
 *  every field is written by name from generated offsets. That distinction is
 *  not academic -- TgTable measured 2019 bytes on avr-g++ against 2024 on
 *  clang++ until Phase 4 caught it, and a memcpy-based receiver would have been
 *  silently wrong on one of the two.
 *
 *  A PARTIALLY WRITTEN TABLE IS THE NORMAL FAILURE STATE. Refusing after the
 *  fact means the table has already been overwritten, which is exactly why
 *  `valid` is cleared the moment BEGIN arrives and set only after the CRC
 *  verifies. There is no window in which a stale table looks current.
 * ============================================================= */

#include "TgInterpret.h"
#include "TgWire.h"

/* ---------------------------------------------------------------- *
 *  CRC32 — IEEE 802.3, reflected, the one zlib computes
 * ---------------------------------------------------------------- */

/*  Bitwise rather than table-driven, deliberately. A 256-entry table is 1 KB of
    flash, and a 16-entry nibble table still costs SRAM on AVR unless it goes in
    PROGMEM -- which needs <avr/pgmspace.h> and would stop this header compiling
    off-target, where every test of it runs. Eight shift-xors per byte is ~2 us at
    16 MHz against the 87 us a byte takes to arrive at 115200, so the wire is the
    bottleneck by a factor of forty and the table would buy nothing. */
inline uint32_t tgCrc32Update(uint32_t crc, uint8_t byte)
{
  crc ^= byte;
  for (uint8_t k = 0; k < 8; k++)
    crc = (crc >> 1) ^ ((crc & 1u) ? 0xEDB88320UL : 0UL);
  return crc;
}

#define TG_CRC32_INIT 0xFFFFFFFFUL
#define TG_CRC32_FINAL(c) ((c) ^ 0xFFFFFFFFUL)

/* ---------------------------------------------------------------- *
 *  Failure reasons
 *
 *  Reported as words, not numbers. The line lands in the host's scrollback and
 *  in a human's terminal, and "TABLE FAIL TOO_LARGE" is actionable where
 *  "TABLE FAIL 4" sends someone to grep the firmware.
 * ---------------------------------------------------------------- */
enum TgRxFail : uint8_t
{
  TG_FAIL_NONE = 0,
  TG_FAIL_STATE,      // a command arrived out of order
  TG_FAIL_SYNTAX,     // a line did not parse
  TG_FAIL_LINE,       // a line was longer than the buffer -- the truncation bug
  TG_FAIL_HEX,        // a chunk carried something that is not hex
  TG_FAIL_SEQ,        // chunk index was not the one expected
  TG_FAIL_CHUNK_CRC,  // a chunk's own checksum did not match
  TG_FAIL_OVERRUN,    // more bytes arrived than the host declared
  TG_FAIL_TRUNCATED,  // END arrived before the declared byte count
  TG_FAIL_MAGIC,      // the payload does not begin "TGTB"
  TG_FAIL_WIRE,       // an unknown wire-format version
  TG_FAIL_TOO_LARGE,  // a record count exceeds this board's capacity
  TG_FAIL_SIZE,       // declared size disagrees with the header's own counts
  TG_FAIL_CRC         // the whole-table CRC did not verify
};

inline const char *tgFailName(uint8_t f)
{
  switch (f)
  {
  case TG_FAIL_NONE: return "NONE";
  case TG_FAIL_STATE: return "STATE";
  case TG_FAIL_SYNTAX: return "SYNTAX";
  case TG_FAIL_LINE: return "LINE";
  case TG_FAIL_HEX: return "HEX";
  case TG_FAIL_SEQ: return "SEQ";
  case TG_FAIL_CHUNK_CRC: return "CHUNK_CRC";
  case TG_FAIL_OVERRUN: return "OVERRUN";
  case TG_FAIL_TRUNCATED: return "TRUNCATED";
  case TG_FAIL_MAGIC: return "MAGIC";
  case TG_FAIL_WIRE: return "WIRE";
  case TG_FAIL_TOO_LARGE: return "TOO_LARGE";
  case TG_FAIL_SIZE: return "SIZE";
  case TG_FAIL_CRC: return "CRC";
  }
  return "UNKNOWN";
}

/* ---------------------------------------------------------------- *
 *  Section geometry
 * ---------------------------------------------------------------- */

/*  Bytes per record in each section. Taken from sizeof() rather than written
    down, so a record that grows moves this with it -- and TgLayoutAssert.h has
    already fixed those sizes under both toolchains. */
inline uint8_t tgSectionStride(uint8_t section)
{
  switch (section)
  {
  case TG_SEC_NODES: return (uint8_t)sizeof(TgNode);
  case TG_SEC_EDGES: return (uint8_t)sizeof(TgEdge);
  case TG_SEC_TIMING: return 2;
  case TG_SEC_ACTIONS: return (uint8_t)sizeof(TgAction);
  case TG_SEC_TRIAL_TYPES: return (uint8_t)sizeof(TgTrialType);
  case TG_SEC_PORTS: return (uint8_t)sizeof(TgPort);
  case TG_SEC_STIMULI: return (uint8_t)sizeof(TgStimulus);
  case TG_SEC_STAGE_ROWS: return (uint8_t)sizeof(TgStageRow);
  case TG_SEC_TIMING_SETS: return (uint8_t)sizeof(TgTimingSet);
  case TG_SEC_MAX_DWELL: return 2;
  case TG_SEC_WATCH_PIN: return 1;
  case TG_SEC_WATCH_PORT: return 1;
  }
  return 0;
}

/*  How many records a section holds, once the header has been decoded. */
inline uint8_t tgSectionCount(const TgTable &t, uint8_t section)
{
  switch (section)
  {
  case TG_SEC_NODES: return t.nNodes;
  case TG_SEC_EDGES: return t.nEdges;
  case TG_SEC_TIMING: return t.nTiming;
  case TG_SEC_ACTIONS: return t.nActions;
  case TG_SEC_TRIAL_TYPES: return t.nTrialTypes;
  case TG_SEC_PORTS: return t.nPorts;
  case TG_SEC_STIMULI: return t.nStimuli;
  case TG_SEC_STAGE_ROWS: return t.nStageRows;
  case TG_SEC_TIMING_SETS: return t.nTimingSets;
  /*  maxDwell is per NODE, not a count of its own -- it is a parallel array. A
      separate count would be a second thing that could disagree with nNodes. */
  case TG_SEC_MAX_DWELL: return t.nNodes;
  /*  The watch arrays are packed at full extent, so "what is in the rest" is
      not a question the receiver has to answer. */
  case TG_SEC_WATCH_PIN: return TG_WATCH_SLOTS;
  case TG_SEC_WATCH_PORT: return TG_WATCH_SLOTS;
  }
  return 0;
}

/* ---------------------------------------------------------------- *
 *  Reading the table back
 * ---------------------------------------------------------------- */

/*  CRC32 of the table RE-SERIALISED from its decoded fields.
 *
 *  WHAT THIS PROVES THAT `tableCrc` DOES NOT. tableCrc is taken over the bytes
 *  that ARRIVED. It says the transfer was intact and says nothing about where
 *  those bytes were then put. A decode that swapped two uint16 fields, or that
 *  read a record at the wrong stride, produces a perfect tableCrc and a wrong
 *  table.
 *
 *  Because this walks the fields in exactly the packer's order and writes them
 *  byte-wise the same way, a correct decode reproduces the body verbatim -- so
 *  the digest must equal CRC32 of the packed body, which the host already has.
 *  No new arithmetic on either side; the comparison is a slice.
 *
 *  IT IS THE ONLY WAY TO CHECK AN AVR DECODE FROM OUTSIDE. Gate C proves the
 *  round trip with the host's compiler. This is the same claim asked of the board
 *  that will actually run the session, and it costs one line of output. */
inline uint32_t tgTableDigest(const TgTable &t)
{
  uint32_t c = TG_CRC32_INIT;
#define TG_D8(v) (c = tgCrc32Update(c, (uint8_t)(v)))
#define TG_D16(v) (TG_D8((v) & 0xFF), TG_D8(((v) >> 8) & 0xFF))

  for (uint8_t i = 0; i < t.nNodes; i++)
  {
    const TgNode &n = t.nodes[i];
    TG_D8(n.type); TG_D8(n.durIdx); TG_D16(n.strobe); TG_D8(n.watchMask);
    TG_D8(n.actionIdx); TG_D8(n.actionCount); TG_D8(n.edgeIdx);
  }
  for (uint8_t i = 0; i < t.nEdges; i++)
  {
    const TgEdge &e = t.edges[i];
    TG_D8(e.trigger); TG_D8(e.guard); TG_D8(e.target); TG_D8(e.effect);
  }
  for (uint8_t i = 0; i < t.nTiming; i++)
    TG_D16(t.timing[i]);
  for (uint8_t i = 0; i < t.nActions; i++)
  {
    TG_D8(t.actions[i].channel); TG_D8(t.actions[i].op);
  }
  for (uint8_t i = 0; i < t.nTrialTypes; i++)
  {
    const TgTrialType &r = t.trialTypes[i];
    TG_D8(r.stimulus0); TG_D8(r.stimulus1); TG_D8(r.stimulus2); TG_D8(r.stimulus3);
    TG_D8(r.target); TG_D8(r.weight); TG_D8(r.rewardLine); TG_D8(r.rewardDurIdx);
  }
  for (uint8_t i = 0; i < t.nPorts; i++)
  {
    const TgPort &p = t.ports[i];
    TG_D8(p.channel); TG_D8(p.rewardLine);
    TG_D16(p.enterCode); TG_D16(p.errorCode); TG_D16(p.breakCode);
    TG_D16(p.exitCode); TG_D16(p.rewardCode); TG_D16(p.rewardStopCode);
    TG_D8(p.rewardDurIdx); TG_D8(0); // the explicit pad, which the packer sends
  }
  for (uint8_t i = 0; i < t.nStimuli; i++)
  {
    TG_D8(t.stimuli[i].emitter); TG_D8(0); TG_D16(t.stimuli[i].onCode);
  }
  for (uint8_t i = 0; i < t.nStageRows; i++)
  {
    TG_D16(t.stageRows[i].atTrial);
    TG_D8(t.stageRows[i].count); TG_D8(t.stageRows[i].firstIdx);
  }
  for (uint8_t i = 0; i < t.nTimingSets; i++)
  {
    TG_D8(t.timingSets[i].idx); TG_D8(0); TG_D16(t.timingSets[i].ms);
  }
  for (uint8_t i = 0; i < t.nNodes; i++)
    TG_D16(t.maxDwell[i]);
  for (uint8_t i = 0; i < TG_WATCH_SLOTS; i++)
    TG_D8(t.watchPin[i]);
  for (uint8_t i = 0; i < TG_WATCH_SLOTS; i++)
    TG_D8(t.watchPort[i]);

#undef TG_D8
#undef TG_D16
  return TG_CRC32_FINAL(c);
}

/* ---------------------------------------------------------------- *
 *  The receiver
 * ---------------------------------------------------------------- */

enum TgRxState : uint8_t
{
  TG_RX_IDLE = 0, // nothing in progress
  TG_RX_HEADER,   // collecting the 24-byte header
  TG_RX_BODY,     // walking sections
  TG_RX_TRAILER,  // collecting the trailing CRC
  TG_RX_FULL,     // every declared byte received; awaiting END
  TG_RX_DONE,     // verified; table.valid is set
  TG_RX_FAILED
};

struct TgRx
{
  TgTable *table = 0;
  uint8_t state = TG_RX_IDLE;
  uint8_t fail = TG_FAIL_NONE;

  /*  One record at a time. 24 bytes covers the header, which is larger than any
      record (TgPort, 16), so one buffer serves both phases. */
  uint8_t buf[TG_HDR_SIZE];
  uint8_t fill = 0;

  uint8_t section = 0;
  uint8_t index = 0;

  uint16_t received = 0;    // payload bytes consumed, including the trailing CRC
  uint16_t declaredBytes = 0;
  uint32_t declaredCrc = 0;
  uint32_t trailerCrc = 0;
  uint32_t crc = TG_CRC32_INIT; // running, over everything but the last 4 bytes
  uint16_t nextChunk = 0;
};

/*  THE FIRST FAILURE WINS.
 *
 *  A host does not stop mid-sentence: by the time TABLE FAIL reaches it, several
 *  more chunks are already on the wire, and each one arriving into a failed
 *  upload is trivially "out of state". Letting those overwrite the reason turns
 *  every diagnosis into TG_FAIL_STATE and throws away the only useful fact --
 *  that the third chunk's checksum was wrong, or that the header claimed 200
 *  nodes.
 *
 *  Found by a test expecting MAGIC and getting STATE. */
inline bool tgRxFail(TgRx &rx, uint8_t reason)
{
  if (rx.state != TG_RX_FAILED)
  {
    rx.state = TG_RX_FAILED;
    rx.fail = reason;
    return false;
  }
  return false;
}

/* ---------------------------------------------------------------- *
 *  Decoding one completed record into the table
 * ---------------------------------------------------------------- */

inline void tgStoreRecord(TgRx &rx)
{
  TgTable &t = *rx.table;
  const uint8_t *b = rx.buf;
  const uint8_t i = rx.index;

  switch (rx.section)
  {
  case TG_SEC_NODES:
  {
    TgNode &n = t.nodes[i];
    n.type = b[0];
    n.durIdx = b[1];
    n.strobe = tgRdU16(b, 2);
    n.watchMask = b[4];
    n.actionIdx = b[5];
    n.actionCount = b[6];
    n.edgeIdx = b[7];
    break;
  }
  case TG_SEC_EDGES:
  {
    TgEdge &e = t.edges[i];
    e.trigger = b[0];
    e.guard = b[1];
    e.target = b[2];
    e.effect = b[3];
    break;
  }
  case TG_SEC_TIMING:
    t.timing[i] = tgRdU16(b, 0);
    break;
  case TG_SEC_ACTIONS:
    t.actions[i].channel = b[0];
    t.actions[i].op = b[1];
    break;
  case TG_SEC_TRIAL_TYPES:
  {
    TgTrialType &r = t.trialTypes[i];
    r.stimulus0 = b[0];
    r.stimulus1 = b[1];
    r.stimulus2 = b[2];
    r.stimulus3 = b[3];
    r.target = b[4];
    r.weight = b[5];
    r.rewardLine = b[6];
    r.rewardDurIdx = b[7];
    break;
  }
  case TG_SEC_PORTS:
  {
    TgPort &p = t.ports[i];
    p.channel = b[0];
    p.rewardLine = b[1];
    p.enterCode = tgRdU16(b, 2);
    p.errorCode = tgRdU16(b, 4);
    p.breakCode = tgRdU16(b, 6);
    p.exitCode = tgRdU16(b, 8);
    p.rewardCode = tgRdU16(b, 10);
    p.rewardStopCode = tgRdU16(b, 12);
    p.rewardDurIdx = b[14];
    p._pad = 0;
    break;
  }
  case TG_SEC_STIMULI:
    t.stimuli[i].emitter = b[0];
    t.stimuli[i]._pad = 0;
    t.stimuli[i].onCode = tgRdU16(b, 2);
    break;
  case TG_SEC_STAGE_ROWS:
    t.stageRows[i].atTrial = tgRdU16(b, 0);
    t.stageRows[i].count = b[2];
    t.stageRows[i].firstIdx = b[3];
    break;
  case TG_SEC_TIMING_SETS:
    t.timingSets[i].idx = b[0];
    t.timingSets[i]._pad = 0;
    t.timingSets[i].ms = tgRdU16(b, 2);
    break;
  case TG_SEC_MAX_DWELL:
    t.maxDwell[i] = tgRdU16(b, 0);
    break;
  case TG_SEC_WATCH_PIN:
    t.watchPin[i] = b[0];
    break;
  case TG_SEC_WATCH_PORT:
    t.watchPort[i] = b[0];
    break;
  }
}

/* ---------------------------------------------------------------- *
 *  The header
 * ---------------------------------------------------------------- */

/*  Validate and adopt the 24-byte header.
 *
 *  EVERY COUNT IS CHECKED AGAINST CAPACITY BEFORE ANY OF IT IS USED. The arrays
 *  are statically sized, so an over-large count is not a slow table -- it is a
 *  write past the end of a global, which on AVR corrupts whatever is next in
 *  SRAM and produces a fault nobody can trace back to here.
 */
inline bool tgAdoptHeader(TgRx &rx)
{
  TgTable &t = *rx.table;
  const uint8_t *b = rx.buf;

  if (b[0] != TG_MAGIC_0 || b[1] != TG_MAGIC_1 || b[2] != TG_MAGIC_2 || b[3] != TG_MAGIC_3)
    return tgRxFail(rx, TG_FAIL_MAGIC);
  if (b[TG_HDR_WIRE_FORMAT] != TG_WIRE_FORMAT)
    return tgRxFail(rx, TG_FAIL_WIRE);

  const uint8_t n[10] = {
      b[TG_HDR_N_NODES], b[TG_HDR_N_EDGES], b[TG_HDR_N_TIMING], b[TG_HDR_N_ACTIONS],
      b[TG_HDR_N_TRIAL_TYPES], b[TG_HDR_N_PORTS], b[TG_HDR_N_STIMULI], b[TG_HDR_N_WATCH],
      b[TG_HDR_N_STAGE_ROWS], b[TG_HDR_N_TIMING_SETS]};
  const uint8_t cap[10] = {
      TG_MAX_STATES, TG_MAX_EDGES, TG_MAX_TIMING, TG_MAX_ACTIONS,
      TG_MAX_TRIAL_TYPES, TG_MAX_PORTS, TG_MAX_STIMULI, TG_MAX_WATCH,
      TG_MAX_STAGE_ROWS, TG_MAX_TIMING_SETS};
  for (uint8_t k = 0; k < 10; k++)
    if (n[k] > cap[k])
      return tgRxFail(rx, TG_FAIL_TOO_LARGE);

  t.nNodes = n[0];
  t.nEdges = n[1];
  t.nTiming = n[2];
  t.nActions = n[3];
  t.nTrialTypes = n[4];
  t.nPorts = n[5];
  t.nStimuli = n[6];
  t.nWatch = n[7];
  t.nStageRows = n[8];
  t.nTimingSets = n[9];
  t.specHash = tgRdU32(b, TG_HDR_SPEC_HASH);

  /*  The size the header itself implies, against the size the host declared.
      Two numbers from two places that must agree -- and they are checked BEFORE a
      body byte is stored, so a header claiming 200 nodes in a 500-byte upload is
      refused rather than discovered 300 bytes later. */
  uint16_t want = TG_HDR_SIZE + TG_CRC_SIZE;
  for (uint8_t s = 0; s < TG_SEC_COUNT; s++)
    want = (uint16_t)(want + (uint16_t)tgSectionCount(t, s) * tgSectionStride(s));
  if (want != rx.declaredBytes)
    return tgRxFail(rx, TG_FAIL_SIZE);

  rx.section = 0;
  rx.index = 0;
  rx.state = TG_RX_BODY;
  /*  Skip sections a table does not use -- a spec with no stage schedule has
      zero rows -- so the first body byte lands in the right place. */
  while (rx.state == TG_RX_BODY && rx.section < TG_SEC_COUNT &&
         tgSectionCount(t, rx.section) == 0)
    rx.section++;
  if (rx.section >= TG_SEC_COUNT)
    rx.state = TG_RX_TRAILER;
  return true;
}

/* ---------------------------------------------------------------- *
 *  One payload byte
 * ---------------------------------------------------------------- */

inline bool tgRxByte(TgRx &rx, uint8_t byte)
{
  if (rx.state == TG_RX_FAILED)
    return false;
  if (rx.received >= rx.declaredBytes)
    return tgRxFail(rx, TG_FAIL_OVERRUN);

  rx.received++;
  /*  The CRC covers everything except its own four bytes. Updated here, before
      any decision about where the byte goes, so a byte can never be counted into
      the checksum twice or missed on a branch. */
  if (rx.received <= (uint16_t)(rx.declaredBytes - TG_CRC_SIZE))
    rx.crc = tgCrc32Update(rx.crc, byte);

  switch (rx.state)
  {
  case TG_RX_HEADER:
    rx.buf[rx.fill++] = byte;
    if (rx.fill == TG_HDR_SIZE)
    {
      rx.fill = 0;
      return tgAdoptHeader(rx);
    }
    return true;

  case TG_RX_BODY:
  {
    rx.buf[rx.fill++] = byte;
    if (rx.fill < tgSectionStride(rx.section))
      return true;
    rx.fill = 0;
    tgStoreRecord(rx);
    rx.index++;
    while (rx.section < TG_SEC_COUNT &&
           rx.index >= tgSectionCount(*rx.table, rx.section))
    {
      rx.section++;
      rx.index = 0;
    }
    if (rx.section >= TG_SEC_COUNT)
      rx.state = TG_RX_TRAILER;
    return true;
  }

  case TG_RX_TRAILER:
    rx.buf[rx.fill++] = byte;
    if (rx.fill == TG_CRC_SIZE)
    {
      rx.trailerCrc = tgRdU32(rx.buf, 0);
      rx.fill = 0;
      rx.state = TG_RX_FULL;
    }
    return true;

  default:
    return tgRxFail(rx, TG_FAIL_STATE);
  }
}

/* ---------------------------------------------------------------- *
 *  Line handling
 * ---------------------------------------------------------------- */

inline int tgHexVal(char c)
{
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

/*  Parse an unsigned value; base 16 when `hex`. Returns the first character not
    consumed, or 0 on a value with no digits at all. */
inline const char *tgParseU32(const char *s, uint32_t &out, bool hex)
{
  uint32_t v = 0;
  const char *start = s;
  while (*s)
  {
    int d = hex ? tgHexVal(*s) : ((*s >= '0' && *s <= '9') ? *s - '0' : -1);
    if (d < 0)
      break;
    v = v * (hex ? 16u : 10u) + (uint32_t)d;
    s++;
  }
  if (s == start)
    return 0;
  out = v;
  return s;
}

/*  Print a uint32 as eight hex digits.

    Hex on the wire for both the CRC and the spec hash, in both directions: they
    are bit patterns, not quantities, and `0e6867ed` is what the compiler prints
    and what a person compares by eye. Formatted here rather than through
    Serial.println(v, HEX), which drops leading zeros -- so a CRC beginning 0x00
    would come back seven characters wide and a host comparing strings would
    reject a table that was fine. */
inline void tgPrintHex32(uint32_t v)
{
  char b[9];
  for (int8_t i = 7; i >= 0; i--)
  {
    const uint8_t nib = (uint8_t)(v & 0xF);
    b[i] = (char)(nib < 10 ? '0' + nib : 'a' + (nib - 10));
    v >>= 4;
  }
  b[8] = 0;
  Serial.print(b);
}

inline const char *tgSkipSpace(const char *s)
{
  while (*s == ' ' || *s == '\t')
    s++;
  return s;
}

inline bool tgStartsWith(const char *s, const char *prefix)
{
  while (*prefix)
    if (*s++ != *prefix++)
      return false;
  return true;
}

/*  Handle one complete protocol line. Returns false on a line that failed the
    upload; the reason is in rx.fail and has already been reported.

    SEPARATE FROM READING, on purpose. Line assembly is the sketch's problem --
    it owns the timeout policy and the port -- while everything decided here is
    testable off-target by handing it strings, which is how every negative case
    below gets exercised without a board. */
inline bool tgFeedLine(TgRx &rx, const char *line)
{
  if (!tgStartsWith(line, "TABLE "))
    return true; // not ours; the sketch's other commands still work
  const char *p = tgSkipSpace(line + 6);

  /* ---- BEGIN <spec_id> <spec_hash> <n_bytes> <crc32> ---- */
  if (tgStartsWith(p, "BEGIN"))
  {
    p = tgSkipSpace(p + 5);
    while (*p && *p != ' ')
      p++; // spec_id: carried for the host's benefit, not used here
    p = tgSkipSpace(p);
    uint32_t hash = 0, nbytes = 0, crc = 0;
    p = tgParseU32(p, hash, true);
    if (!p) return tgRxFail(rx, TG_FAIL_SYNTAX);
    p = tgSkipSpace(p);
    p = tgParseU32(p, nbytes, false);
    if (!p) return tgRxFail(rx, TG_FAIL_SYNTAX);
    p = tgSkipSpace(p);
    p = tgParseU32(p, crc, true);
    if (!p) return tgRxFail(rx, TG_FAIL_SYNTAX);

    if (nbytes <= TG_HDR_SIZE + TG_CRC_SIZE || nbytes > (uint32_t)TG_TABLE_BYTES)
      return tgRxFail(rx, TG_FAIL_SIZE);

    /*  Invalidate FIRST. Everything after this point overwrites the live table,
        so there must be no instant at which a half-replaced table still claims to
        be the one that was verified. */
    rx.table->valid = false;
    rx.table->tableCrc = 0;

    rx.state = TG_RX_HEADER;
    rx.fail = TG_FAIL_NONE;
    rx.fill = 0;
    rx.section = 0;
    rx.index = 0;
    rx.received = 0;
    rx.nextChunk = 0;
    rx.crc = TG_CRC32_INIT;
    rx.trailerCrc = 0;
    rx.declaredBytes = (uint16_t)nbytes;
    rx.declaredCrc = crc;

    Serial.print(F("TABLE ACK "));
    Serial.println(0);
    return true;
  }

  /* ---- CHUNK <index> <hex> <chunk_crc> ---- */
  if (tgStartsWith(p, "CHUNK"))
  {
    /*  Chunks still in flight when the failure was reported. The host has
        already been told once; saying it again for every remaining chunk of a
        700-byte table would bury the one line that matters under ten copies of a
        worse one. */
    if (rx.state == TG_RX_FAILED)
      return true;
    if (rx.state != TG_RX_HEADER && rx.state != TG_RX_BODY && rx.state != TG_RX_TRAILER)
      return tgRxFail(rx, TG_FAIL_STATE);
    p = tgSkipSpace(p + 5);
    uint32_t idx = 0;
    p = tgParseU32(p, idx, false);
    if (!p) return tgRxFail(rx, TG_FAIL_SYNTAX);
    if (idx != rx.nextChunk)
      return tgRxFail(rx, TG_FAIL_SEQ);
    p = tgSkipSpace(p);

    /*  The chunk's own checksum is verified BEFORE any of its bytes are stored.
        Storing first and checking after would leave the table holding bytes the
        host is about to resend, and a resend that then failed would leave the
        table a mix of two attempts. */
    const char *hexStart = p;
    uint16_t nHex = 0;
    while (tgHexVal(p[nHex]) >= 0)
      nHex++;
    if (nHex == 0 || (nHex & 1))
      return tgRxFail(rx, TG_FAIL_HEX);
    p = tgSkipSpace(hexStart + nHex);
    uint32_t want = 0;
    p = tgParseU32(p, want, true);
    if (!p) return tgRxFail(rx, TG_FAIL_SYNTAX);

    uint32_t c = TG_CRC32_INIT;
    for (uint16_t k = 0; k < nHex; k += 2)
      c = tgCrc32Update(c, (uint8_t)((tgHexVal(hexStart[k]) << 4) | tgHexVal(hexStart[k + 1])));
    if (TG_CRC32_FINAL(c) != want)
      return tgRxFail(rx, TG_FAIL_CHUNK_CRC);

    for (uint16_t k = 0; k < nHex; k += 2)
      if (!tgRxByte(rx, (uint8_t)((tgHexVal(hexStart[k]) << 4) | tgHexVal(hexStart[k + 1]))))
        return false;

    rx.nextChunk++;
    Serial.print(F("TABLE ACK "));
    Serial.println(rx.nextChunk);
    return true;
  }

  /* ---- END ---- */
  if (tgStartsWith(p, "END"))
  {
    if (rx.state == TG_RX_FAILED)
      return true; // already reported, with the reason that actually explains it
    if (rx.state != TG_RX_FULL)
      return tgRxFail(rx, TG_FAIL_TRUNCATED);

    const uint32_t got = TG_CRC32_FINAL(rx.crc);
    /*  Both statements of the CRC must agree with the bytes AND with each other.
        The trailing copy catches a truncated transfer; the BEGIN copy catches a
        table that arrived intact and is not the one the host meant to send --
        which the trailing copy alone cannot see, because it travels with the
        payload it describes. */
    if (got != rx.trailerCrc || got != rx.declaredCrc)
      return tgRxFail(rx, TG_FAIL_CRC);

    rx.table->tableCrc = got;
    rx.table->valid = true;
    rx.state = TG_RX_DONE;
    Serial.print(F("TABLE OK "));
    tgPrintHex32(got);
    /*  The digest of the DECODED table, alongside the checksum of the bytes that
        produced it. The host compares it against CRC32 of the body it sent, which
        it already has -- so a board that received perfectly and decoded into the
        wrong fields is caught by the host rather than by an animal. */
    Serial.print(F(" DIGEST="));
    tgPrintHex32(tgTableDigest(*rx.table));
    Serial.println();
    return true;
  }

  return tgRxFail(rx, TG_FAIL_SYNTAX);
}

/*  Report a failed upload. Called by the sketch after tgFeedLine() returns false,
    so that the reporting happens in one place rather than at each of the fourteen
    ways an upload can go wrong. */
inline void tgReportFailure(const TgRx &rx)
{
  Serial.print(F("TABLE FAIL "));
  Serial.println(tgFailName(rx.fail));
}

#endif // TG_RECEIVE_H

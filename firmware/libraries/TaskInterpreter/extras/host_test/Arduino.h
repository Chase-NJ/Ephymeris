/*  A SCRIPTABLE Arduino shim, for the equivalence gate.
 *
 *  The reference repo's shim exists to make BehaviorBox.h *parse* off-target: its
 *  millis() never advances and its digitalRead() always returns HIGH, which is
 *  enough to exercise the pure policy classes and nothing else. Phase 3 needs to
 *  actually RUN runTrial() and capture what it emits, so this replaces it.
 *
 *  THREE THINGS MAKE THE GATE POSSIBLE, and all three are here rather than in the
 *  test, so that runTrial() and the interpreter are driven by the identical world:
 *
 *  1. TIME ADVANCES ON delay(). runTrial() does all its waiting through
 *     delay(pollingRate) inside polling loops and delay(penalty) for timeouts. A
 *     mock where delay(n) adds n to the clock makes the whole trial deterministic
 *     with no real sleeping and no wall-clock flakiness.
 *
 *  2. SENSORS ARE A FUNCTION OF TIME. A script declares intervals during which a
 *     channel reads LOW (INPUT_PULLUP: LOW == beam broken == poked). Both
 *     implementations then see exactly the same animal, which is the only way a
 *     byte-for-byte comparison means anything.
 *
 *  3. SERIAL IS CAPTURED, NOT DISCARDED. emitStrobe() formats "%03d\t%lu" and
 *     calls Serial.println(), so capturing that line is capturing the strobe
 *     stream in precisely the form the host would receive it.
 */
#ifndef ARDUINO_H_SHIM
#define ARDUINO_H_SHIM

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

/* ---------------------------------------------------------------- *
 *  Mock world
 * ---------------------------------------------------------------- */

struct MockEvent
{
  int code;
  unsigned long t;
};

/*  One actuator write: which pin, to what, when. */
struct MockWrite
{
  int pin;
  int value;
  unsigned long t;
};

/*  One scripted sensor interval: `pin` reads LOW (poked) on [from, to). */
struct MockPoke
{
  int pin;
  unsigned long from;
  unsigned long to;
};

/*  Thrown when mock time runs past the deadline.
 *
 *  A GATE MUST NOT HANG. The failure this whole project is designed against is a
 *  box that stops with an animal in it, so a harness that reproduces that failure
 *  by stopping too has turned the most important result it can produce into a
 *  timeout nobody can read. Turning it into a catchable event makes a hang a
 *  REPORTABLE divergence, with the script that caused it.
 *
 *  This is not hypothetical: the first Gate B run hit one in runTrial() itself. */
struct MockHang
{
  unsigned long at;
};

struct MockBox
{
  unsigned long now = 0;
  /*  Ten minutes of mock time. Longer than any real trial by a wide margin --
      the longest legal path is an abstention penalty at its 30 s ceiling -- so
      crossing it means something is not progressing rather than merely slow. */
  unsigned long deadline = 600000UL;
  std::vector<MockPoke> pokes;
  std::vector<MockEvent> emitted;
  /*  Every pin written, in order, WITH THE TIME.
   *
   *  The strobe stream is what Gates A-C compare; this is what catches a
   *  correct-looking stream driving the wrong hardware -- and it is the only
   *  record of the actuators that emit no strobe at all, the vacuum and the odor
   *  lines.
   *
   *  THE TIMESTAMP IS THE WHOLE POINT, and it was missing. Without it this log
   *  says a solenoid opened and closed and cannot say for how long -- and pulse
   *  width IS the delivered reward volume, so "the right pins in the right order"
   *  is not the same claim as "the right amount of water". */
  std::vector<MockWrite> writes;

  /*  Everything printed, as whole lines. The strobe stream above is a PARSED
      view of a subset; this is the raw text, which is what the upload protocol
      speaks. A receiver test has to assert on "TABLE FAIL CRC", and a strobe
      parser cannot see that line at all.

      `partial` accumulates print() calls until a println() closes the line, so a
      response assembled from six Serial.print() calls arrives here as one string
      -- the same way it arrives at a host reading a serial port. */
  std::vector<std::string> out;
  std::string partial;

  /*  What the board reads. Scripted input, consumed by available()/read(). */
  std::string in;
  size_t inPos = 0;

  void reset()
  {
    now = 0;
    deadline = 600000UL;
    pokes.clear();
    emitted.clear();
    writes.clear();
    out.clear();
    partial.clear();
    in.clear();
    inPos = 0;
  }

  void feed(const std::string &s) { in += s; }

  /*  The last printed line, or "" -- the common assertion in a protocol test. */
  const std::string &last() const
  {
    static const std::string none;
    return out.empty() ? none : out.back();
  }

  /*  A pin reads LOW while any scripted interval covers the current time.
      Intervals are half-open so two back-to-back pokes do not overlap by a
      millisecond -- an off-by-one there would look like a sensor bounce. */
  bool poked(int pin) const
  {
    for (const auto &p : pokes)
      if (p.pin == pin && now >= p.from && now < p.to)
        return true;
    return false;
  }

  void poke(int pin, unsigned long from, unsigned long to)
  {
    pokes.push_back({pin, from, to});
  }
};

extern MockBox mock;

/* ---- timing ---- */
inline unsigned long millis() { return mock.now; }
inline unsigned long micros() { return mock.now * 1000UL; }
inline void delay(unsigned long ms)
{
  mock.now += ms;
  if (mock.now > mock.deadline)
    throw MockHang{mock.now};
}
inline void delayMicroseconds(unsigned long us) { mock.now += us / 1000UL; }

/* ---- random ----
   srand/rand, seeded per test. runTrial() calls random(0,2) to break a
   simultaneous left/right beam break, so the gate has to control it: an
   uncontrolled coin flip there would make the comparison fail intermittently and
   look like an interpreter bug. */
inline long _bb_random(long lo, long hi) { return lo + (long)(rand() % (hi - lo)); }
#define random(...) _bb_random(__VA_ARGS__)
inline void randomSeed(unsigned long s) { srand((unsigned)s); }

/* ---- min/max ---- */
template <class T> T _bb_min(T a, T b) { return a < b ? a : b; }
template <class T> T _bb_max(T a, T b) { return a > b ? a : b; }
#ifndef min
#define min(a, b) _bb_min(a, b)
#endif
#ifndef max
#define max(a, b) _bb_max(a, b)
#endif

/* ---- digital I/O ---- */
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
inline void pinMode(int, int) {}
inline void digitalWrite(int pin, int v) { mock.writes.push_back({pin, v, mock.now}); }
/*  INPUT_PULLUP: HIGH = beam intact = unpoked. verifySensor() and the well polls
    both read it that way, so the polarity has to match or every hold inverts. */
inline int digitalRead(int pin) { return mock.poked(pin) ? LOW : HIGH; }

/* ---- Serial ----
   Two views of the same traffic, and both are needed.

   `mock.emitted` is the PARSED strobe stream: println(const char*) recognises
   emitStrobe()'s "%03d\t%lu" and records the pair, in the same shape the host's
   IN_SESSION parser accepts. That is what the equivalence gates compare.

   `mock.out` is the raw text, line by line. The upload protocol speaks in lines
   like "TABLE FAIL CRC", which a strobe parser cannot see at all, and a receiver
   test has nothing to assert on without it. print() accumulates; println()
   closes the line -- so a response built from six print() calls arrives as one
   string, exactly as it would at a host reading the port. */
struct _SerialShim
{
  void begin(long) {}
  void flush() {}

  int available() { return (int)(mock.in.size() - mock.inPos); }
  int read() { return mock.inPos < mock.in.size() ? (unsigned char)mock.in[mock.inPos++] : -1; }

  size_t print(const char *s)
  {
    mock.partial += s;
    return std::strlen(s);
  }
  size_t print(char *s) { return print(static_cast<const char *>(s)); }
  size_t print(char c)
  {
    mock.partial += c;
    return 1;
  }

  size_t println(const char *s)
  {
    /*  A strobe is recognised only when it is the WHOLE line, which is what
        emitStrobe() emits. Matching a prefix would let "234\t5 OK" register as a
        strobe, and the receiver's own responses are not strobes. */
    int code = 0;
    unsigned long t = 0;
    char tail = 0;
    if (mock.partial.empty() &&
        std::sscanf(s, "%d\t%lu%c", &code, &t, &tail) == 2)
      mock.emitted.push_back({code, t});
    mock.partial += s;
    mock.out.push_back(mock.partial);
    mock.partial.clear();
    return std::strlen(s);
  }
  /*  BOTH overloads are required, and the non-const one is not redundant.
      emitStrobe() builds its line in a `char buf[16]`, which decays to `char*`.
      Against `char*` the catch-all template below is an EXACT match while
      `const char*` needs a qualification conversion -- so without this the
      template wins and every strobe is silently discarded. The gate would then
      compare two empty streams and pass, which is the worst possible failure for
      a test whose entire job is to catch a difference. */
  size_t println(char *s) { return println(static_cast<const char *>(s)); }

  /*  Numbers. Arduino prints integers in decimal by default; the catch-all
      template that used to stand here returned 0 and printed NOTHING, which is
      how tgAnnounceCapabilities() could have announced an empty line and no test
      would have known. */
  template <class T> size_t print(T v)
  {
    char b[32];
    std::snprintf(b, sizeof(b), "%lld", (long long)v);
    mock.partial += b;
    return std::strlen(b);
  }
  template <class T> size_t println(T v)
  {
    print(v);
    return println("");
  }
  size_t println() { return println(""); }
};
static _SerialShim Serial;

/* Arduino's F() macro is a no-op off-target. */
#ifndef F
#define F(x) x
#endif

#endif // ARDUINO_H_SHIM

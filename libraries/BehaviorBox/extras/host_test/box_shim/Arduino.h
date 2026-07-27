/*
  Arduino.h -- the *instrumented* host shim, for testing a whole sketch off-target.

  The sibling `../Arduino.h` is deliberately inert: it exists so BehaviorBox.h
  parses, and the tests there only exercise pure policy classes. Testing a
  utility sketch needs the opposite — pin writes and serial traffic are exactly
  what is under test — so this shim records them:

    * digitalWrite/digitalRead go through an addressable pin table, so a test
      can assert "F2 is open" or drive an IR beam LOW;
    * Serial.read() drains a queued input string, so a test can feed whole
      command lines through the sketch's real CommandReader;
    * Serial.print/println append to a capture buffer, so STATUS lines and the
      self-test's prose confirmations can both be asserted;
    * millis() advances on every delay(), so timed loops terminate instead of
      spinning forever.

  Only ever compiled by run_box.sh. The Arduino build never sees extras/.
*/
#ifndef ARDUINO_H_BOX_SHIM
#define ARDUINO_H_BOX_SHIM

#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <string>
#include <deque>
// strcasecmp/strncasecmp: avr-libc puts them in <string.h>, POSIX hosts in
// <strings.h>. The sketch uses them, so the shim has to supply them too.
#ifndef _WIN32
#include <strings.h>
#else
#define strcasecmp _stricmp
#define strncasecmp _strnicmp
#endif

// ---- pin table ----
static const int BB_MAX_PIN = 70;
static int bb_pinValue[BB_MAX_PIN];
static int bb_pinMode[BB_MAX_PIN];

inline void pinMode(int pin, int mode)
{
  if (pin >= 0 && pin < BB_MAX_PIN) bb_pinMode[pin] = mode;
}
inline void digitalWrite(int pin, int value)
{
  if (pin >= 0 && pin < BB_MAX_PIN) bb_pinValue[pin] = value;
}
inline int digitalRead(int pin)
{
  return (pin >= 0 && pin < BB_MAX_PIN) ? bb_pinValue[pin] : 1;
}

// ---- timing: delay() is what advances the clock ----
static unsigned long bb_ms = 0;
inline unsigned long millis() { return bb_ms; }
inline void delay(unsigned long ms) { bb_ms += ms; }
inline void delayMicroseconds(unsigned long) {}

// ---- random ----
inline long _bb_random(long lo, long hi) { return lo + (long)(rand() % (hi - lo)); }
#define random(...) _bb_random(__VA_ARGS__)
inline void randomSeed(unsigned long s) { srand((unsigned)s); }

// ---- min/max ----
template <class T> T _bb_min(T a, T b) { return a < b ? a : b; }
template <class T> T _bb_max(T a, T b) { return a > b ? a : b; }
#ifndef min
#define min(a, b) _bb_min(a, b)
#endif
#ifndef max
#define max(a, b) _bb_max(a, b)
#endif

// ---- digital constants ----
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2

// ---- Serial ----
static std::deque<char> bb_serialIn;
static std::string bb_serialOut;

struct _BoxSerialShim
{
  void begin(long) {}
  int available() { return (int)bb_serialIn.size(); }
  int read()
  {
    if (bb_serialIn.empty()) return -1;
    char c = bb_serialIn.front();
    bb_serialIn.pop_front();
    return (int)(unsigned char)c;
  }
  size_t print(const char *s) { bb_serialOut += s; return strlen(s); }
  size_t print(int v) { bb_serialOut += std::to_string(v); return 1; }
  size_t println(const char *s) { bb_serialOut += s; bb_serialOut += "\n"; return strlen(s) + 1; }
  size_t println(int v) { bb_serialOut += std::to_string(v); bb_serialOut += "\n"; return 1; }
  size_t println() { bb_serialOut += "\n"; return 1; }
};
static _BoxSerialShim Serial;

// ---- test helpers ----
inline void bb_feed(const char *line)
{
  for (const char *p = line; *p; ++p) bb_serialIn.push_back(*p);
  bb_serialIn.push_back('\n');
}
inline void bb_resetCapture() { bb_serialOut.clear(); }
inline const std::string &bb_output() { return bb_serialOut; }

#endif // ARDUINO_H_BOX_SHIM

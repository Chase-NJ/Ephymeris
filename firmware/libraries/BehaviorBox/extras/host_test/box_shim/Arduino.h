/*
  Arduino.h -- the *instrumented* host shim, for testing a whole sketch off-target.

  The sibling `../Arduino.h` is deliberately inert: it exists so BehaviorBox.h
  parses, and the tests there only exercise pure policy classes. Testing a
  utility sketch needs the opposite — pin writes and serial traffic are exactly
  what is under test — so this shim records them:

    * digitalWrite/digitalRead go through an addressable pin table, so a test
      can assert "F2 is open" or drive an IR beam LOW, and analogWrite and
      tone/noTone record each pin's duty and pitch;
    * Serial.read() drains a queued input string, so a test can feed whole
      command lines through the sketch's real CommandReader;
    * Serial.print/println append to a capture buffer, so STATUS lines and the
      self-test's prose confirmations can both be asserted;
    * millis() advances on every delay(), so timed loops terminate instead of
      spinning forever.

  bb_realTiming(baud) makes the time the sketch itself spends real: Serial
  writes fill a 64-byte TX buffer that drains at the baud rate, and a write
  into a full one BLOCKS, advancing the clock, as HardwareSerial does on an AVR;
  delayMicroseconds() advances it; and each availableForWrite() costs a few
  microseconds, so a sketch that waits for room makes progress. bb_onPinWrite
  sees every pin write with the microsecond it happened at. Off by default, so
  a test that steps millis() itself sees the same clock as ever.

  Compiled by run_box.sh and run_spine.sh. The Arduino build never sees extras/.
*/
#ifndef ARDUINO_H_BOX_SHIM
#define ARDUINO_H_BOX_SHIM

#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
// Every C++ standard header a test uses must come in here, ahead of the min/max
// macros below. libstdc++ calls std::min inside its own headers, so one included
// after the macros expands it to std::_bb_min and fails to compile. libc++ guards
// its headers against these macros, so a macOS build never shows it.
#include <algorithm>
#include <iostream>
#include <string>
#include <deque>
#include <utility> // test_spine.cpp
#include <vector>  // test_spine.cpp
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
// ---- timing: delay() is what advances the clock ----
// bb_ms is the millisecond a test may set or step itself; bb_us the
// microseconds into it, which only real timing (below) moves.
static unsigned long bb_ms = 0;
static unsigned long bb_us = 0;
static bool bb_real = false;
inline unsigned long millis() { return bb_ms; }
inline unsigned long micros() { return bb_ms * 1000UL + bb_us; }
inline void bb_advanceUs(unsigned long us)
{
  bb_us += us;
  bb_ms += bb_us / 1000UL;
  bb_us %= 1000UL;
}
inline void delay(unsigned long ms) { bb_ms += ms; }
inline void delayMicroseconds(unsigned long us)
{
  if (bb_real) bb_advanceUs(us);
}

// analogWrite()'s duty and tone()'s Hz, per pin: 0 when the pin is not driven
// so. A digitalWrite() ends a PWM, as on an AVR; noTone() ends a tone.
static int bb_pwm[BB_MAX_PIN];
static unsigned bb_tone[BB_MAX_PIN];
// Called on every pin write, with its level and micros(), when a test sets it.
static void (*bb_onPinWrite)(int pin, int value, unsigned long us) = nullptr;

inline void bb_wrote(int pin, int value)
{
  if (bb_onPinWrite) bb_onPinWrite(pin, value, micros());
}
inline void digitalWrite(int pin, int value)
{
  if (pin >= 0 && pin < BB_MAX_PIN) { bb_pinValue[pin] = value; bb_pwm[pin] = 0; bb_wrote(pin, value); }
}
inline void analogWrite(int pin, int duty)
{
  if (pin >= 0 && pin < BB_MAX_PIN) { bb_pwm[pin] = duty; bb_pinValue[pin] = duty > 0 ? 1 : 0; bb_wrote(pin, bb_pinValue[pin]); }
}
inline void tone(unsigned pin, unsigned hz)
{
  if (pin < (unsigned)BB_MAX_PIN) bb_tone[pin] = hz;
}
inline void noTone(unsigned pin)
{
  if (pin < (unsigned)BB_MAX_PIN) { bb_tone[pin] = 0; bb_pinValue[pin] = 0; bb_wrote((int)pin, 0); }
}
inline int digitalRead(int pin)
{
  return (pin >= 0 && pin < BB_MAX_PIN) ? bb_pinValue[pin] : 1;
}

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

// The TX buffer under real timing: HardwareSerial's 64 bytes, each taking ten
// bit times on the wire.
static const int BB_TX_BUFFER = 64;
static double bb_byteUs = 0;       // 0: instant, as when real timing is off
static double bb_txQueued = 0;     // bytes still to go out
static unsigned long bb_txAt = 0;  // micros() the queue was last drained to
static unsigned long bb_txBlockedUs = 0; // total time writes spent blocked

inline void bb_txDrain()
{
  unsigned long now = micros();
  bb_txQueued -= (double)(now - bb_txAt) / bb_byteUs;
  if (bb_txQueued < 0) bb_txQueued = 0;
  bb_txAt = now;
}

/* Real timing from here on, at `baud`. */
inline void bb_realTiming(long baud)
{
  bb_real = true;
  bb_byteUs = 10e6 / (double)baud;
  bb_txQueued = 0;
  bb_txAt = micros();
}

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
  int availableForWrite()
  {
    if (!bb_real) return BB_TX_BUFFER - 1;
    bb_advanceUs(4); // asking costs the CPU a few microseconds
    bb_txDrain();
    int queued = (int)bb_txQueued + (bb_txQueued > (int)bb_txQueued ? 1 : 0);
    return BB_TX_BUFFER - 1 - queued; // as on an AVR, one slot always stays free
  }
  size_t write(uint8_t c)
  {
    if (bb_real) {
      bb_txDrain();
      if (bb_txQueued > BB_TX_BUFFER - 2) { // full: block until a byte goes out
        unsigned long wait = (unsigned long)((bb_txQueued - (BB_TX_BUFFER - 2)) * bb_byteUs) + 1;
        bb_advanceUs(wait);
        bb_txBlockedUs += wait;
        bb_txDrain();
      }
      bb_txQueued += 1;
    }
    bb_serialOut += (char)c;
    return 1;
  }
  size_t write(const char *s, size_t n)
  {
    for (size_t i = 0; i < n; i++) write((uint8_t)s[i]);
    return n;
  }
  size_t print(const char *s) { return write(s, strlen(s)); }
  size_t print(int v) { std::string t = std::to_string(v); return write(t.c_str(), t.size()); }
  size_t println(const char *s) { return print(s) + println(); }
  size_t println(int v) { return print(v) + println(); }
  size_t println() { return write("\n", 1); }
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

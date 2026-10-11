// Minimal host shim so BehaviorBox.h compiles off-target for logic testing.
// It stubs just enough of the Arduino API that the whole header parses. The
// tests exercise the pure policy classes (parseStartCommand, CorrectionPolicy,
// AbstentionPenalty, AntiBiasSelector), plus what emitStrobe writes: the pin
// log and the printed line. Reads drain whatever a test queued in _serialIn,
// so readLineInto() can be fed a line; with nothing queued they are inert.
#ifndef ARDUINO_H_SHIM
#define ARDUINO_H_SHIM

#include <cstdint>
#include <cstdlib>
#include <cstdio>

// ---- timing ----
static unsigned long _ms = 0;
inline unsigned long millis() { return _ms; }
// micros() is _ms plus whatever delayMicroseconds() has been asked to wait, so
// the sync pulse's width and gap are observable. Nothing else advances it: a
// loop that spins on micros() would hang here, which is why emitStrobe doesn't.
static unsigned long _us = 0;
inline unsigned long micros() { return _ms * 1000UL + _us; }
inline void delay(unsigned long) {}
inline void delayMicroseconds(unsigned long us) { _us += us; }

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

// ---- digital I/O ----
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
inline void pinMode(int, int) {}
// Every write is logged with the micros() it happened at, so a test can read
// back the edges a pin actually saw.
struct _PinWrite { int pin; int level; unsigned long us; };
static _PinWrite _pinLog[256];
static int _pinLogCount = 0;
inline void digitalWrite(int pin, int level)
{
  if (_pinLogCount < 256)
    _pinLog[_pinLogCount++] = {pin, level, micros()};
}
inline int digitalRead(int) { return HIGH; }

// ---- Serial ----
// A printed line is kept, with Arduino's "\r\n", so a test can read back what
// the host would receive. Other overloads print nothing.
static char _serialOut[256];
static size_t _serialOutLen = 0;
static const char *_serialIn = "";
struct _SerialShim
{
  void begin(long) {}
  int available() { return *_serialIn ? 1 : 0; }
  int read() { return *_serialIn ? (unsigned char)*_serialIn++ : -1; }
  template <class T> size_t print(T) { return 0; }
  template <class T> size_t println(T) { return 0; }
  size_t println(char *s) { return println((const char *)s); }
  size_t println(const char *s)
  {
    int n = snprintf(_serialOut + _serialOutLen, sizeof(_serialOut) - _serialOutLen, "%s\r\n", s);
    if (n > 0) _serialOutLen = _bb_min(_serialOutLen + (size_t)n, sizeof(_serialOut) - 1);
    return n > 0 ? (size_t)n : 0;
  }
  size_t println() { return 0; }
};
static _SerialShim Serial;

#endif // ARDUINO_H_SHIM

// Minimal host shim so BehaviorBox.h compiles off-target for logic testing.
// It stubs just enough of the Arduino API that the whole header parses; the
// tests only *exercise* the pure policy classes (parseStartCommand,
// CorrectionPolicy, AbstentionPenalty, AntiBiasSelector), never the hardware or
// serial paths -- those just need their symbols declared to compile.
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
struct _SerialShim
{
  void begin(long) {}
  int available() { return 0; }
  int read() { return -1; }
  template <class T> size_t print(T) { return 0; }
  template <class T> size_t println(T) { return 0; }
  size_t println() { return 0; }
};
static _SerialShim Serial;

#endif // ARDUINO_H_SHIM

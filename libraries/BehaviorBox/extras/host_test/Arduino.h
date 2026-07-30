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
inline unsigned long micros() { return _ms * 1000UL; }
inline void delay(unsigned long) {}
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

// ---- digital I/O ----
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
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

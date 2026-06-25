// Minimal host shim so GRGLSession.h compiles off-target for logic testing.
#ifndef ARDUINO_H_SHIM
#define ARDUINO_H_SHIM
#include <cstdint>
#include <cstdlib>
static unsigned long _ms = 0;
inline unsigned long millis() { return _ms; }
inline long _grgl_random(long lo, long hi) { return lo + (long)(rand() % (hi - lo)); }
#define random(...) _grgl_random(__VA_ARGS__)
template<class T> T _grgl_min(T a, T b){return a<b?a:b;}
template<class T> T _grgl_max(T a, T b){return a>b?a:b;}
#ifndef min
#define min(a,b) _grgl_min(a,b)
#endif
#ifndef max
#define max(a,b) _grgl_max(a,b)
#endif
#endif

# Shared Arduino library for the 2-Odor sketches

`GRGLSession/GRGLSession.h` holds the session logic shared by both
`GRGL_2-Odor` and `GRGL_2-Odor_EZ` (per-side correction, anti-bias selection,
the lazy-penalty toggle, plus the `TrialType`/`TrialClock` structs). It is
defined **once** here instead of being copy-pasted into each sketch.

## How it's reached: A Library!

A library is the Arduino-native way to share one source between multiple sketches.

Arduino requires every sketch to live in its own folder, so a shared header has
to come in as a *library*. This is a flat (1.0-style) header-only library: the
header sits at the library root, so a sketch includes it with angle brackets:

```cpp
#include <GRGLSession.h>
```

### Flashing from the recording GUI
`olfactory_behavior/upload_sketch.py` passes this `libraries/` folder to
`arduino-cli compile --libraries <...>/02_Bdisc/libraries`, so the GUI's
flash path finds it automatically. No per-machine install.

### Compiling in the Arduino IDE (optional, for editing/checking)
The IDE won't see this folder by default. Either add
`02_Bdisc/libraries` to the IDE's library search path, or compile via
`arduino-cli` as above.

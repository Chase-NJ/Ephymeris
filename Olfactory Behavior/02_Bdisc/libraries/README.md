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
The IDE won't see this folder by default, and there is no "extra library
path" setting to point at it — IDE 2.x scans exactly one user library
folder, `<sketchbook>/libraries`. Our sketchbook is the repo root
(`.../05_Behavior/Arduino`), so the fix is a symlink from there to this
folder. From the repo root:

```bash
mkdir -p libraries && ln -sfn "../Olfactory Behavior/02_Bdisc/libraries/GRGLSession" libraries/GRGLSession
```

Restart the IDE afterwards so it rescans libraries. The symlink is
relative, so it keeps working wherever the repo is checked out, as long as
the IDE's sketchbook is set to the repo root (File > Preferences >
Sketchbook location).

If you'd rather not touch the IDE, compile from the repo root with the
library path passed explicitly:

```bash
arduino-cli compile --fqbn arduino:avr:mega --libraries "Olfactory Behavior/02_Bdisc/libraries" "Olfactory Behavior/02_Bdisc/GRGL_2-Odor"
```

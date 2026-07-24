# `libraries/` — the shared Arduino library folder

This repo root's `libraries/` folder is the **one** place shared sketch code
lives. The Ephymeris sidecar passes it to `arduino-cli` as
`--libraries <repo>/libraries`, so every sketch can `#include` anything here with
no per-machine setup (`arduino-directory.md` §4). The Arduino IDE finds it too,
as long as its sketchbook is set to this repo root.

> This folder **is** tracked in git. A previous layout kept the shared header in
> a nested `Olfactory Behavior/02_Bdisc/libraries/` and reached the root via a
> symlink — but the sidecar only ever passes the *root* `libraries/` to
> `arduino-cli`, and symlinks are fragile on the Windows lab machines. The real
> folder here replaces both.

## `BehaviorBox/BehaviorBox.h`

The single shared header for **every** sketch — behavior tasks, the simulator,
and the utility/cleaning sketches. It is the one source of truth for:

- the behavior-box **pinout** (IR sensors, trial light, N.O. vacuum, 12 odor +
  4 fluid solenoids) — identical on all 6 boxes;
- the **strobe vocabulary** (`BF_*` host codes) mirrored by each sketch's
  `task.json` `strobes` map;
- the **serial protocol** helpers shared with the app: `emitStrobe`,
  `readLineInto` (await `START`), `checkForStop`, and — for utility sketches —
  `CommandReader` (non-blocking command parse) + `emitStatus` (non-persisted
  `STATUS` telemetry);
- the reusable **trial primitives** (`TrialClock`, `TrialType`, `TrialWeight` +
  `generateTrials`) and the GRGL **session policy** classes (`AntiBiasSelector`,
  `AbstentionPenalty`, `CorrectionPolicy`, `SessionConfig` + `parseStartCommand`);
- the **shaping runner**, so `shaping_GL` and `shaping_GR` differ only in their
  trial pool.

A sketch includes it with angle brackets:

```cpp
#include <BehaviorBox.h>
```

### Compiling in the Arduino IDE (optional, for editing/checking)
IDE 2.x scans exactly one user library folder, `<sketchbook>/libraries`. Set the
sketchbook to this repo root (File > Preferences > Sketchbook location) and the
IDE picks up `BehaviorBox` with no symlink. Restart the IDE afterward so it
rescans.

Or compile from the repo root with the library path passed explicitly:

```bash
arduino-cli compile --fqbn arduino:avr:mega --libraries libraries "Olfactory Behavior/02_Bdisc/GRGL_2-Odor"
```

### Host compile-check (logic only)
`BehaviorBox/extras/host_test/run.sh` compiles the header off-target against a
minimal `Arduino.h` shim and exercises the policy classes
(`parseStartCommand`, `CorrectionPolicy`, `AbstentionPenalty`,
`AntiBiasSelector`, `generateTrials`). It does **not** replace flashing to the
rig — only `arduino-cli` does the full AVR compile.

```bash
sh libraries/BehaviorBox/extras/host_test/run.sh
```

# Ephymeris

Ephymeris runs rodent behaviour sessions on up to six behaviour boxes, each driven by an Arduino Mega2560.
It loads the task onto each box, records every event each animal produces into that animal's data file
as it happens, and keeps track of your cohorts, animals and sessions. Afterwards, Analytics draws
learning curves and per-condition accuracy from the recorded files. A session can also run an Intan
RHX electrophysiology recording alongside the behaviour.

![The Ephymeris Dashboard on a six-box rig: Start a Session and Start a Recording at the top left, the rig's boxes drawn as labelled stars in a 3D sky, the Boxes list with Command all boxes on the right, and the Observatory listing the lab's cohorts](docs/images/dashboard.webp)

*The Dashboard. Each star is a behaviour box; the figure in the sidebar's corner shows the same boxes'
status on every screen.*

**Status.** Every feature has been run on real hardware. A full-length recording from a real animal has
not been done yet ([what to watch for](docs/RECORDING.md#not-yet-verified)). The current version is on
the [Releases](https://github.com/Chase-NJ/Ephymeris/releases) page.

## What you need

- A Windows 10 or 11 PC. No administrator account, Python, Arduino IDE or internet connection is
  needed: everything ships inside the installer.
- One to six Arduino Mega2560 R3 boards, each wired into a behaviour box and connected by USB.
  Genuine boards need no driver; CH340 clones need the CH340 driver.
- Optional: Intan RHX on the same PC, for recordings ([RECORDING.md](docs/RECORDING.md)).

## Install

1. Download `Ephymeris-<version>-setup.exe` from the newest release on the
   [Releases](https://github.com/Chase-NJ/Ephymeris/releases) page.
2. Run it. It installs for your Windows user only, into `%LOCALAPPDATA%\Programs\Ephymeris`.
3. The installer is not code-signed, so Windows shows **"Windows protected your PC"**. Click
   **More info**, then **Run anyway**.
4. Start Ephymeris from the Start menu or the desktop shortcut. On the first start it unpacks its
   Arduino toolchain, so boards take a few extra seconds to appear that once.

## Set up the rig (once)

1. **Rig → Boxes.** Click **Add box** for each behaviour box, give it a **Label**, and pick its board
   under **Bound board** (boards are listed by USB serial number). **Test** opens the box's console and
   waits for its firmware to answer. Boxes are always known by number (1–6), never by COM port, so
   Windows renumbering ports does no harm.
2. **Rig → Wiring.** Check the channel-to-pin map matches how the boxes are wired, and confirm it. A rig
   that records with Intan needs a sync channel here.
3. **Settings → Storage.** Choose the **Data directory** where session files go, and optionally a
   **Backup directory** on another drive or a network share.
4. **Task.** Save at least one task: pick a sketch from the library and set its parameters.
5. **Cohorts.** Create a cohort, add its animals, and assign each animal to a box within a group.

Idle boxes are kept on a utility sketch (`BOX_Utility`) that the app builds from your wiring; that is
what lets it light up a box while you place an animal. You never flash it by hand.

## Run a session

1. On the Dashboard, click **Start a Session**, pick the cohort, the session prefix and number, and the
   group to run.
2. Check each box's task, then let the app flash the boxes. Place each animal when its box lights up.
3. Click **Start All**. Mission Control shows every box live: trials, accuracy and the event stream.
4. A box finishes on its own (trial limit or time limit). **Switch Group** moves on to the next group;
   **End Session** stops any box still running and finishes the session.

Each animal gets `<animal>_<prefix>_<n>_<date>_<time>.tsv`, written event by event as the session runs
(nothing is lost if the PC crashes mid-session), plus `.json` and `.mat` files when its run ends
cleanly. They go into a folder named `<prefix>_<n>_<date>` inside your data directory.

The [user guide](docs/USER-GUIDE.md) covers every screen: cohorts, sessions, Mission Control, Analytics,
Debug Mode and recordings.

## Updates

Ephymeris updates itself. When a newer version is out, a dot appears beside **Settings**;
**Settings → Updates → Install and restart** downloads it, checks it, closes the app, installs and
reopens it. It waits while a session, a recording or any box is busy. A PC without internet never sees
an update: run the newer installer over the old one by hand.

Your data is never touched by installing, updating or uninstalling. Ephymeris keeps its own state (the
cohort database, settings, saved tasks) in `%APPDATA%\edu.hartlab.ephymeris`, and session files wherever
the Data directory points.

### Moving a lab PC to the Electron shell

Copies installed before the Electron shell ([ADR 0006](docs/adr/DECISIONS.md#0006-the-shell-is-electron-not-tauri)) live in
`%LOCALAPPDATA%\Ephymeris`. Their next update installs the Electron build, which removes the old copy,
takes over its shortcuts and keeps all app data. Do it once per PC, with someone there, then check:
settings and cohorts are as they were; the wiring is in force with no RIG108 hold; a session runs on a
real box; a scope window opens; **Settings → Updates** reports the version current; and **Apps →
Installed apps** lists one Ephymeris.

## Troubleshooting

| Symptom | What to do |
|---|---|
| No boards appear | Check the USB cable; install the CH340 driver for clone boards. The app lists what `arduino-cli board list` sees |
| A box will not flash after a failure | The box is in an error state. Acknowledge the fault on the box, then flash again |
| The app opens but shows the sidecar as down | The background process stopped. Restart the app; it never restarts itself, on purpose |
| Sessions and flashes are refused with RIG108 | The wiring is held until confirmed on this PC. Open **Rig → Wiring** and confirm every pin |
| A box shows `ERROR` mid-session | Its board dropped (cable, power). The data up to that moment is safe in the `.tsv`; acknowledge and carry on |

## Documentation

| Document | Read it if you… |
|---|---|
| [USER-GUIDE.md](docs/USER-GUIDE.md) | run sessions: every screen, step by step |
| [RECORDING.md](docs/RECORDING.md) | record with Intan RHX |
| [ANALYTICS.md](sidecar/ephymeris_sidecar/analytics/ANALYTICS.md) | want to know how events become trials and accuracies, e.g. to check the science |
| [TASKS.md](docs/TASKS.md) | write firmware or define tasks, wiring and the strobe vocabulary |
| [DATA.md](docs/DATA.md) | need the file layout, crash safety, the database or backup |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | maintain the app: processes, the wire, the port state machine, sessions, updates |
| [DEVELOPING.md](docs/DEVELOPING.md) | build, test or release it, or contribute |
| [PROTOCOL.md](docs/PROTOCOL.md) | need the list of commands and events (generated) |
| [GLOSSARY.md](GLOSSARY.md) | need the exact meaning of a term |
| [DECISIONS.md](docs/adr/DECISIONS.md) | wonder why a decision was made |
| [LESSONS.md](docs/LESSONS.md) | want the principles, the hard-won lessons and the traps, on one page |

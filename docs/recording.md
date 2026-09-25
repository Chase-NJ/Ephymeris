# Recording

![status](https://img.shields.io/badge/status-built-7CC98F?style=flat-square) ![hardware](https://img.shields.io/badge/real_RHX-partly_verified-CBA23E?style=flat-square) ![protocol](https://img.shields.io/badge/Intan_RHX-TCP_3.5-8B7EC8?style=flat-square) ![deps](https://img.shields.io/badge/new_dependencies-0-16151F?style=flat-square)

> **What this is** · Running an electrophysiology recording on top of a behavior session, by driving a locally-running **Intan RHX** over its TCP protocol.
>
> **Owns** · the subset of RHX's TCP protocol Ephymeris uses, and how it is made trustworthy · **the sync line** and how a box's events are placed on the recording clock · the recording walkthrough · the start/end lifecycle and its failure rules · the four live windows.
>
> **Read with** · [dashboard.md](dashboard.md) (the session flow this extends) · [settings.md](settings.md) (the box→DIN binding and the `sync` wiring kind) · [data.md](data.md) (what a recorded run writes) · [websocket-protocol.md](websocket-protocol.md) §3.9 (the wire).

**Contents** — [1. The rule](#1-the-rule) · [2. Talking to RHX](#2-talking-to-rhx) · [3. **The sync line**](#3-the-sync-line) · [4. The walkthrough](#4-the-walkthrough) · [5. **Start and end**](#5-start-and-end) · [6. What is written](#6-what-is-written) · [7. The live windows](#7-the-live-windows) · [8. Verified, and not](#8-verified-against-a-real-rhx-and-not)

---

## 1. The rule

> **RHX may be slow, absent or dead, and none of that may stall or fail a behavior session.**

It is the Backup mirror's rule (`data.md` §7) restated for a second external system, and it decides almost everything below. Concretely:

| | |
|---|---|
| Nothing on the session path awaits RHX | …**except starting**. `sessions.startAll` and `port.startSession` on a recording session begin the RHX recording *first* and refuse with an `INTAN_*` code if they cannot — **before any box is started**. A behavior session quietly missing its electrophysiology cannot be re-run, so this is the one place a failure must be loud |
| `stop_recording` never raises | By the time it runs the animals are done; a raise could only strand the session as `running`. RHX unreachable → the run is still recorded and `intan.status` says "stop it from RHX" |
| The data sockets are a convenience | Losing them costs the live windows, never the recording. RHX writes to disk on its own |
| A dropped command socket does not stop RHX | So neither a reconnect nor the sidecar exiting ever ends a recording. `IntanService.stop()` closes *our* sockets and nothing else |

It also runs **locally only**. There is no host setting: Ephymeris talks to the RHX on this machine (`127.0.0.1`), which is what the lab does and what removes every networking failure mode from the list.

---

## 2. Talking to RHX

RHX exposes three TCP servers (its **Network → Remote TCP Control** dialog): commands on 5000, waveforms on 5001, spikes on 5002. **The operator's one manual step is pressing Connect on the Commands tab.** The two data sockets are opened by the sidecar over the command socket (`set tcpwaveformdatasocket.status pending`).

> [!NOTE]
> **That click is needed again after every disconnect — observed on the real RHX.** When its command client goes away, RHX's command server returns to *Disconnected*, not *Pending* (its documentation says so; it is easy to read past). So closing Ephymeris, or the sidecar restarting, closes the door behind it: port 5000 stops listening until Connect is pressed in RHX again, while 5001/5002 stay open. The background reconnect (every second) can therefore only succeed after that click, and `INTAN_UNAVAILABLE`'s message — which names the click — is the normal first thing an operator sees each day, not an error state.

### 2.1 What the protocol does not offer

Three things the request for this feature assumed, and RHX's TCP protocol does not have:

- **No command opens RHX's SpikeScope, PSTH or ISI windows.** It exposes their *parameters* only. So the four live windows are Ephymeris' own, computed from RHX's data sockets (§7).
- **No command loads a probe map.** Ephymeris parses the same XML the operator would have loaded in RHX (`intan/probemap.py`).
- **No "pin channel" command.** "Enable and pin a digital input per box" is implemented as a **binding**: each box is bound to one `DIGITAL-IN-n` on the Recording tab (`settings.md` §6), and the recording setup enables, names (`BOX3_EVENTS`) and streams exactly those.

### 2.2 The confirmed write

The protocol is bare text with no framing: a `get` answers `Return: <Name> <value>`; a **`set` or `execute` answers nothing at all on success** and an error sentence on failure. Intan's example clients paper over that with `time.sleep(0.1)` after every command, and copying them would be wrong twice:

- a sleep confirms nothing — a refused `set` looks exactly like an accepted one, and a recording configured on refused commands is saved somewhere else, in some other format;
- two writes with no reply between them can share one TCP segment, which RHX reads as **one command**. That, not slowness, is what the sleeps are really for.

So every write from `intan/client.py` is **one transmission that ends in a `get`** — the *sentinel*. Commands in a transmission are `;`-separated (the documented batching form) and answered in order, so whatever arrives before the sentinel's reply is that transmission's error text, and the reply itself is the receipt. No two transmissions are ever in flight. A 128-channel setup is a few dozen confirmed round trips rather than several hundred sleeps.

> [!CAUTION]
> **The sentinel is an assumption about RHX, and it is fenced.** The documentation shows batching with `set` only. If a build of RHX does not answer a `get` that rides a batch, the first write times out waiting for its receipt; the client then drops to the examples' discipline — one command per transmission, a fixed settle — for the rest of the connection, logs it, and reports `confirmsWrites: false` (the Recording tab says so). Slower and blind to refusals, but correct: *degrade, don't disappear* (`README.md` §6.4).

**The three values a recording cannot be wrong about are read back regardless** — `FileFormat`, `Filename.Path`, `Filename.BaseFilename` (`set(..., verify=True)`). That works in both disciplines, and it is the only thing that catches RHX *accepting* a command and storing something else.

> [!CAUTION]
> **A save location with a space in it.** The lab's data lives under `Hart Lab\`. RHX's documentation says settings-file paths must contain no spaces and says nothing about `Filename.Path`. If RHX splits a `set` value on whitespace it **accepts** `C:/Hart Lab/x` and records into `C:/Hart` — no error, plausible files, wrong place. The read-back sees it and `intan.configure` refuses with a message that says to pick a path without a space; the recording step warns ahead of time. This is the packaged-only class of bug (compare the verbatim-path one in `CLAUDE.md`): nothing looks wrong until the data is looked for. **RHX 3.5.0 was since observed to keep the space (§8)**, so on this build the refusal never fires; the read-back stays because it is cheap and is the only defence on a build that differs.

`set runmode` is the one command RHX documents as *not immediate* — it is polled until it takes, and refused outright while an upload holds the USB bus, so `UploadInProgress` is checked first rather than discovered as a silent no-op.

> [!CAUTION]
> **Nothing may ride behind `set runmode` in a transmission — so it is the one write with no sentinel.** On the real RHX, whatever follows `set runmode run` in the same batch is not processed until acquisition *stops*: the `get` goes unanswered for the whole run and its reply turns up after the next stop, where it would answer some other question. `set_run_mode` therefore writes the command alone and takes its receipt from polling `get runmode`, and `send()` raises on a batch that contains one. This was invisible against a fake that answered at once; the fake now defers the way RHX does (§8).

### 2.3 The data sockets

`intan/streams.py`, pure.

| Socket | Framing |
|---|---|
| **Waveform** | Blocks of **128 frames**, each block led by magic `0x2ef07a08`. A frame is an `int32` timestamp (samples since acquisition began) then one `uint16` per enabled output, **in RHX's order**: every enabled band of every amplifier channel (wide, low, high), aux, board ADCs, and last — **once, however many digital inputs are enabled** — one `uint16` word holding all sixteen. Amplifier samples are offset binary at 0.195 µV/bit |
| **Spike** | 14-byte chunks: magic `0x3ae2710f`, a 5-character native channel name, `uint32` timestamp, `uint8` id |

Nothing in the waveform stream says what a frame holds: `FrameLayout` is the reader's copy of a fact that lives in RHX, and a wrong copy parses garbage without complaint. Two defences:

- **A block is believed only when the next block's magic sits exactly one block-length later.** Intan's example does a single blocking `recv` and checks `len % blockSize`; a real stream splits blocks across reads, so the parser accumulates. The cost is one block (4 ms) of latency.
- **The layout is kept sorted the way RHX writes**, not the way outputs were enabled. A caller-ordered copy would swap two channels' samples and pass every magic check.

The two-ended check is also what makes a **layout change mid-run** safe — opening a SpikeScope adds a column while blocks in the old shape are still in flight. The old layout keeps parsing until it stops confirming; only then does the pending one take over. `discarded` counts bytes thrown away hunting for a boundary: TCP does not corrupt, so a climbing count means the layout is wrong.

**What is streamed is kept small on purpose.** Intan's own guidance is that around ten channels at 30 kS/s is where TCP stops keeping up with acquisition. So: spike output for every recorded channel (cheap — it is event-rate), the digital-input word, and the **highpass band of only the channels with an open SpikeScope, at most four**.

---

## 3. The sync line

The behavioral timestamps that matter are the ones on the **recording's** clock. They come from a wire.

### 3.1 Firmware

`emitStrobe()` (`BehaviorBox.h`) used to print `code\t<ms>` to Serial and do nothing else — there was no electrical link between a box and any acquisition system. It now brackets the print with a pulse on `BOX_PIN_SYNC_OUT`, in this order and for these reasons:

1. wait out the LOW gap **first**, so the wait lands before the timestamp and the edge rather than between them;
2. stamp, then drive HIGH at once — **the rising edge is what the controller timestamps**, so nothing may sit between the two;
3. print while the line is high, spending most of the pulse width on work that had to happen anyway;
4. hold out the remainder, then LOW.

| Macro (`BoxPins.h`, all `#ifndef`-guarded) | Default | Why |
|---|---|---|
| `BOX_PIN_SYNC_OUT` | **49** | Free on the box as built, beside the fluid bank. **Not 13** — the bootloader blinks it on every reset, which a recording logs as events. Not 0/1 (serial) or 50–53 (SPI). **`-1` compiles the pulse out** |
| `BOX_SYNC_PULSE_US` | 500 | 15 samples at 30 kS/s, 10 at 20 kS/s |
| `BOX_SYNC_GAP_US` | 200 | Minimum LOW before the next pulse — see the caution |

> [!CAUTION]
> **Two pulses with no LOW between them are one edge.** Events can be emitted back to back, and a fused pair means every later event is matched one strobe late — which reads as plausible data, not as a failure. The gap is enforced in firmware and pinned by the host tests (`extras/host_test/`), whose shim now logs every pin write with the `micros()` it happened at.

`GRGL_Sim` prints its own strobes, so it pulses through the same three helpers (`syncGap`/`syncRise`/`syncFall`) — the sync line and the controller input can be proven **with no animal**. `BOX_Utility` parks the line LOW via `initBoxHardware()`: a floating input on the controller reads as noise, i.e. as events.

**One line per box, carrying no code.** A single line cannot say *which* event fired, and eight lines per box would leave room for two boxes on a 16-input controller. So the pulse says *when*, the serial line says *what*, and they are paired by order (§3.3).

### 3.2 Wiring and binding

Two different facts, kept in two different places (`settings.md` §5.1, §6):

- **Which Mega pin pulses** is *wiring* — a channel of the new kind **`sync`** in the rig document (`sync_out`, pin 49 as shipped), edited on `/config/wiring` like any other pin and compiled into `TaskPins.h`. `RIG105` refuses a second sync channel: the firmware pulses one line, so a second is a wire believed to carry events that carries nothing.
- **Which controller input that pin reaches** is a *binding* — `BoxBinding.intanDigitalIn`, 1–16, on the Recording tab's Sync inputs table (the value lives in the same box list the Rig tab edits). A cable between two instruments, not a fact about the box; exactly the reasoning that makes `hardwareId` a binding. Two boxes may not share an input (each end enforces it, lower box number wins).

> [!CAUTION]
> **`BOX_PIN_SYNC_OUT` is the one pin that is always emitted.** Every other pin a rig document does not declare is left unmentioned and keeps `BoxPins.h`'s number, so a partial document degrades one pin at a time. That rule is wrong here: the default would pulse pin 49 on a rig whose operator declared no sync channel — and may have put something else there — while the app, reading the same document, reports that the box has no sync line. So absence is *stated*: `-1`.
>
> **This bites on upgrade.** A rig with a saved `<data_dir>/hardware/rig.json` **replaces** the shipped pair rather than merging with it, so it has no `sync_out` until someone adds one. The recording step's readiness list checks for it and links to the wiring page; `intan.configure` refuses without it.

### 3.3 Pairing edges with strobes — `EdgeMatcher`

The firmware pulses once per strobe, so the Nth edge is the Nth strobe — in principle. Matching by count alone is exactly as fragile as that sentence: **one** extra edge (the line twitching as the Mega resets through DTR, a glitch on a long cable) and every later event is attributed to its neighbour, which draws a PSTH that *looks like a PSTH*.

So order proposes and **time disposes**. An edge is accepted for a strobe only if it lands where the strobe's own millisecond timestamp says it should, measured from the last accepted pair:

| The head edge is… | Meaning | Action |
|---|---|---|
| within tolerance | this strobe's pulse | match; it becomes the new anchor |
| **too early** | spurious | drop the edge, count `spuriousEdges` |
| **too late** | this strobe's pulse never came | release the strobe unmatched, count `unmatchedStrobes` |

- **The tolerance is relative** — `max(4 ms, 1.5 % of the gap)`. The Mega's clock is a ceramic resonator good to about half a percent; over a twenty-second inter-trial interval the two clocks honestly disagree by ~100 ms, and a fixed tolerance would call that a missing pulse every long ITI. Measuring from the *last* pair keeps the error from accumulating.
- **The first pair has nothing to be measured from**, so it is the earliest alignment under which two consecutive gaps agree. Strobes are trusted far more than edges — a serial line does not invent events — so at most three leading strobes may be skipped but **any number of leading edges**, which is what lets the reset twitch be discarded instead of anchoring everything.
- **A box gets a fresh matcher at every START**, because the Mega's clock restarts there.
- An unconnected sync line must not queue strobes forever: past 64 pending, the oldest is given up on.

`intan.status.sync` publishes the three counters per box and Mission Control shows them — **it is the wiring check**. `unmatchedStrobes` climbing while `matched` stays at zero is a sync line that is not reaching its input.

> **Synthetic data has no sync line.** RHX's demo mode (`synthetic: true` — no controller attached, the "USB Recording Controller demo") generates its own digital inputs, which no box's pin drives, so the matcher would report every real strobe missed and every generated edge stray: a wiring diagnosis of wiring that does not exist. In synthetic mode the matcher is **bypassed**: `sync` is published **empty**, the rail says why, and a strobe is placed on the recording clock by **arrival** — the newest sample seen when the serial line delivered it, tens of milliseconds late — so the PSTH still draws, and its payload says `alignment: "arrival"` (the window labels it). Real data never takes this path: there, an unmatched strobe is a fact about the wiring and is reported as one.

> **What the matcher is for.** It exists for the *live* views. The durable record needs none of it: RHX saves the digital input at full rate, the `.tsv` holds the strobes, and offline alignment can apply the same algorithm — or a better one — to complete data.

---

## 4. The walkthrough

### 4.0 The Recording tab

Everything about the link to RHX lives on one sidebar tab, `/recording` (`routes/Recording.tsx`), a column of HUD tiles in the order a recording comes up in:

| Tile | Holds |
|---|---|
| **Live** (only while a recording exists) | `RecordingStatus` — the same block Mission Control's rail shows (state chip, elapsed, run name, RHX's message, the graceful end, the sync check) — and a door to Mission Control |
| **Connection** | Connected or not, the controller/version/rate/headstage line, **Connect** / **Disconnect**, the three numbered steps RHX needs when the door is shut, a `synthetic` chip, and the TCP ports |
| **Sync inputs** | Box → `DIGITAL-IN-n`, one row per configured box with the Rig's health dot, and whether the rig's wiring declares a sync channel (with a door to the wiring page) |
| **Defaults** | Save root, file format, what to save, thresholds — `settings.recordingDefaults`, edited outright. The Record step opens with these and writes back what it confirmed |

The Dashboard's **Start a Recording** tile (`RecordingTile`, glass rather than a second solid primary; its subtitle is RHX's live state) opens the ordinary session flow with `?mode=recording`, which creates the session with `recording: true`. From there the flow reads the flag off the sidecar's own session snapshot (`useIsRecordingSession`), not the URL — the flow is re-entered from the dock, from a group switch and from a reload, and a query flag would have to survive every one of those doors.

```
Configure  →  Boxes  →  Record  →  Run  →  Finish
                          ▲
             /session/:id/recording   (SessionRecording.tsx)
```

**After Boxes, not before.** What the step asks is which headstage port each *mapped* box is on, and there is nothing to ask until the mapping exists. It runs **once per group** — animals change between groups, and so do ports and probes — and opens prefilled the second time from `settings.recordingDefaults`.

| Section | Holds |
|---|---|
| **Readiness** | RHX connected · not already recording · a headstage present · the wiring has a sync channel · every recorded box has a DIN. Each failing line is the operator's next step, with a door to where it is fixed |
| **Saving** | The resolved location — `<session folder>/ephys` by default, or the session's folder under the root chosen on the Recording tab (recordings are large and often live on their own drive; the folder name is kept so the two halves match by eye) — always visible, and under it **"Using your defaults"**: one line summarising format, what is saved and how thresholds are set, with **Edit for this session** unfolding the same rows the Recording tab's Defaults tile shows (`RecordingConfigRows`: format, wideband/spikes/snapshots/highpass/lowpass, thresholds). Edits made here become the new defaults on Continue |
| **Boxes** | One card per mapped box: **Record / Behavior only**, a `DIN n` chip (or `no DIN` with a door to the Recording tab), port, channel range, optional probe-map XML with a live preview. Two boxes may share a port on disjoint ranges; an overlap is refused |

**Wideband defaults ON**, and the row says why: it is the one option that cannot lose data. Everything else RHX saves is derived from it, and a threshold picked badly before a session cannot be re-picked afterwards without it.

Nothing talks to RHX until **Continue**. The form is a description; `intan.configure` applies it in one pass (§2.2) and every refusal lands as one sentence. An RHX left in `Run` — for a look at the signals, almost always — is stopped, since it ignores every saving parameter while the board runs; one already in `Record` is refused and not touched.

**Channels nobody claimed are switched off**, so a headstage no box was assigned does not fill the disk. The recording's three notes carry the session, the cohort and group, and the box→animal→port map; `livenotes` stamps each box's start and end into RHX's own notes file.

---

## 5. Start and end

### 5.1 Start

`sessions.startAll`, or the first `port.startSession`:

1. `set runmode record`, polled until it takes.
2. **Wait for samples** — `CurrentTimestamp` advancing. "Record" is a request; samples arriving is the fact.
3. Read `Filename.ActiveFileTimestamp` — RHX's own `YYMMDD_HHMMSS`, which names the folder and files it actually created.
4. **One second of pre-roll**, so every channel has a baseline on disk ahead of the first event.
5. Only now are boxes started.

Any failure in 1–2 is an `INTAN_*` error with no box started.

### 5.2 The graceful end

`sessions.end` / `sessions.endGroup` (Switch Group):

1. `STOP` to every box.
2. **Wait for each box's own `BF_END_SESSION`** — up to 45 s (`Application.RECORDING_GRACE_S`: longer than any trial the lab runs, a 20 s error delay plus ITI plus holds). `intan.status.waitingOn` names who is still out and Mission Control offers **End now** (`intan.forceStop`).
3. One second of post-roll, then `set runmode stop`.
4. The run is appended to `sessions.recording_json`.

> [!IMPORTANT]
> **Behavior-only sessions keep their 100 ms.** `SessionRunner.end_all` always sent `STOP` and then waited a fixed 100 ms before force-finalizing — which cuts the trial in flight. That is the existing contract for a behavior session and is unchanged. A recording cannot afford it: electrophysiology with no behavioral outcome to align to is the expensive half of the experiment with the cheap half missing. `end_all(graceful_timeout_s=…)` is the same code with a real timeout; the default is still 0.1.

**One recording per group run**, not per session: a second group is different animals on, possibly, different ports.

### 5.3 When RHX goes away

| Event | What happens |
|---|---|
| **RHX hangs up** (Disconnect pressed in its Remote TCP Control dialog, or RHX quit) | Seen **within a quarter second, without sending anything**: the transport feeds EOF to the reader the moment the peer closes, and the poll loop sleeps in 250 ms slices watching for it (`RhxCommandClient.peer_closed`). `intan.status` goes `connected: false` at once, and the 1 s reconnect attempt brings the link back by itself as soon as Connect is pressed in RHX again |
| **RHX goes silent with the socket open** | The harder case — nothing about the socket says so. **Two** consecutive unanswered polls (one silence can be RHX busy) and the link is declared lost **and our end is closed**. That close is the fix for a bug reported from the bench: `connected` is the socket's, so a link marked lost while the socket stayed open went on reading *connected* on the Recording tab and the Dashboard |
| Command socket lost mid-recording | `state: error`, "RHX keeps recording on its own; reconnecting". The session is untouched. On reconnect, if RHX is still in `Record`, the run is picked back up and the streams reopened |
| Someone presses Stop in RHX | The 1 s poll sees `runmode ≠ record` → `error`, said plainly. The session is untouched |
| RHX unreachable at End | `stop_recording` swallows it, records the run, and says to stop RHX by hand |
| Data sockets fail to open | `liveStreams: false`; Mission Control says the live views are unavailable and the recording is unaffected |
| The sidecar exits | Its sockets close. RHX keeps recording |

### 5.4 The runner's three taps

`SessionRunner` gained three optional callbacks — `recording_fields`, `on_box_started`, `on_strobe_tap` — all called **on the port's session thread**, so the service's side of each is a `call_soon_threadsafe`. The strobe tap runs *after* the fsync, never before: the strobe is on disk whatever the tap does. Each call site swallows exceptions; a test pins that a tap that throws costs the run nothing.

---

## 6. What is written

**By RHX** — its own files, in its own format, under `Filename.Path` in a directory it timestamps itself (`CreateNewDirectory true`, so two recordings can never overwrite each other). Ephymeris never reads or moves them. Probe-map XMLs are copied beside them as `box<n>_<name>.xml`.

**`sessions.recording_json`** (schema **v10**, `data.md` §6) — `{"runs": [<RecordingRun>]}`, one per group run: path, base filename, RHX's file timestamp, format, sample rate, start/end, and per box its DIN, port, channels and probe-map file. `NULL` = behavior only, which is every session from before the column.

**Each animal's document** gains flat `intan_*` fields, beside the core fields and in the `.tsv` header (so a crash-recovered file keeps them):

| Field | |
|---|---|
| `intan_recording` | base filename + RHX's timestamp — the name to look for |
| `intan_path` | where RHX was told to save |
| `intan_digital_in` · `intan_port` · `intan_channels` | this box's input, port and `A-016:A-031` range |
| `intan_sample_rate` | for converting sample numbers |

> [!IMPORTANT]
> **Core, not config — so they stay out of `params_hash`.** They describe the rig, not the task. Two runs of one tuning are comparable in Analytics whether or not one of them was recorded, so nothing the recording adds may reach `config_metadata`, which is what the hash is taken over. They are in `CORE_METADATA_KEYS` (a profile may not claim them) and the string ones in recovery's `_STRING_FIELDS` (a base filename like `0423_7` must not come back as a number).

---

## 7. The live windows

Real OS windows (`WebviewWindow`, labels `scope-*`), not panels inside Mission Control — because that is how they are used: dragged to a second monitor beside RHX and left open across boxes.

A pop-up is the same bundle at `#/scope/<kind>`; `main.tsx` sees the hash and mounts a **slim tree** — `SidecarProvider` + `IntanProvider` and nothing else. What is left out matters: **no `SettingsProvider`** (its job is pushing settings on every connect, and a scope window must not re-push a stale copy over the main window's), no session/cohort/analytics stores, no 3D canvas. Each window opens its own authenticated WebSocket, so a scope keeps drawing whatever the main window is doing. Everything it needs rides in the URL, including the PSTH's trigger vocabulary — only the main window holds the task profile.

`capabilities/scope.json` grants `scope-*` windows their own frame and the ability to open a window, and nothing else — no store, dialog, filesystem or opener. `lib.rs` closes them when the main window closes, or the app would not exit (and would hold the sidecar, and its serial ports) until each was closed by hand.

| Window | Fed by | Notes |
|---|---|---|
| **Spike Scope** | spike times + that channel's highpass waveform | Snippets are cut sidecar-side at a fixed 2 ms/4 ms window and **sent incrementally**; the window crops to its time scale with the crossing a third of the way across, as RHX does. **The threshold line is live** — drag it and RHX's detector moves, which changes what is being saved — and commits on release, not per pixel. **Changing channel swaps one streamed column for another**, which leaves the frame the same size — so the parser cannot switch on the framing (§2's two-ended check confirms the *old* layout forever, and the new channel never reads as streaming). The service reads `currenttimestamp` after RHX acknowledges the swap and the parser switches at that sample, **dropping** the few blocks it cannot place rather than guessing — a wrong guess draws one channel's waveform as another's |
| **PSTH** | spike times + matched sync edges | **Better than RHX's for this rig.** RHX triggers on a digital input's edge, and here every event pulses the *same* input, so RHX would align to "anything happened". The sidecar knows which event each edge was (§3.3), so the trigger is a **named event** from the box's profile. Only trials whose post-window has **closed** are counted, so the right of the histogram never sags by how recent the last trigger was — and only trials whose pre-window begins **inside the spike ring's coverage** (`SpikeRing.complete_since`, which moves when the oldest spike is evicted or the stream reopens); a trial older than that would be drawn with whichever of its spikes survived, which reads as a unit that fired less back then. Sent only when it **changes** — between trials a PSTH is the same payload for seconds |
| **ISI** | spike times | Intervals past the span are **counted and shown**, not dropped — a histogram that looks complete while most of its intervals fall outside it is how a slow unit reads as a quiet one. A span that is not a whole number of bins gets a **partial last bin**, drawn at its true width (a PSTH's is also normalised by its true width): rounding it away reported every 40–50 ms interval of a 50 ms span as "beyond" |
| **Probe map** | spike times | Each site filled by its firing in the last second (square-root ramp: rates are heavy-tailed), refreshed every publish tick (5 Hz). Clicking a site opens its Spike Scope. **The file's colours are ignored** — they were chosen for RHX's UI; the geometry is the information and is drawn in the app's tokens. **Y is flipped at draw time**: Intan's y points up, and skipping the flip draws the probe tip-up with every site on the right channel in the wrong place. The view's host takes its positioning from the caller: it once set `relative` itself, which Tailwind emits *after* `absolute`, so the pop-up's `absolute inset-0` lost and the map drew into a zero-height box |

RHX's own option sets are offered (scope 50–5000 µV · 2/4/6 ms · 10–500 spikes; PSTH and ISI spans and bins) so the two read the same.

**Canvas, fenced.** The SpikeScope, PSTH and ISI draw on a 2D canvas from refs, with `redraw()` fired straight from the socket handler (`routes/scope/useCanvas.ts`) — routing five snippet updates a second through React state would reconcile a tree to change some pixels. This is the app's first canvas plotting and it stays in the scope windows; the session views are SVG because a sparkline is forty points. The probe map is SVG: a few hundred sites at under 2 Hz, and sites need to be clickable. The arithmetic all four share is pure and tested (`src/lib/intan/scopeMath.ts`).

A scope is kept alive by a 5 s `intan.scope.update`; one untouched for 15 s is swept, which is how a window that was killed rather than closed stops costing RHX a streamed channel.

---

## 8. Verified against a real RHX, and not

`sidecar/tests/test_intan_real_rhx.py` is the probe: opt-in (`EPHYMERIS_REAL_RHX=1`), polite (refuses if RHX is running, only ever enters `run` — never `record`, so nothing is written — and restores every value it touches), and **one connection for every check**, because RHX's command server returns to *Disconnected* the moment its client leaves (§2) and a connection per test gets exactly one test per click. Everything else is tested against the **fake RHX** (`tests/fake_rhx.py` — the three servers on real sockets, each survivable behaviour switchable).

**Run on 2026-09-20 against RHX 3.5.0, `ControllerRecordUSB3`, 30 kS/s, synthetic:**

| Question | Answer | Consequence |
|---|---|---|
| Does RHX answer a `get` that rides a `;` batch? | **Yes** | The confirmed write (§2.2) works as designed; the fallback is not exercised on this build |
| Is a refused `set` reported? | **Yes** — `Unrecognized parameter` | Refusals are caught by the sentinel, as intended |
| Does `Filename.Path` keep a path containing a space? | **Yes** | The lab's `Hart Lab\` data directory is usable as a save location. The read-back stays: it is cheap, and it is the only defence on a build that differs |
| How are digital inputs named on a Recording Controller? | `digital-in-01` — two digits, one-based. `digital-in-1` and `digital-in-00` are *not* channels | Matches `digital_in_name` |
| Reply spelling | `Return: <Name> <value>`, no terminator | Matches the parser |
| **What happens to commands batched behind `set runmode run`?** | **They are not processed until acquisition stops.** Sent `set runmode run;get version`: the mode changed at once, the `get` went unanswered for as long as RHX ran — and its reply arrived ~10 ms after the next `set runmode stop`, a minute later. RHX evidently enters its run loop from inside the batch and finishes the batch on the way out | The sentinel behind a run-mode change timed out as "RHX stopped answering", which would have failed **every Start All on a recording session**, and the late reply would then have answered some unrelated question. `set_run_mode` now sends the command **alone and unconfirmed** and takes its receipt from polling `get runmode` (answered in 1 ms while running); `send()` refuses a batch containing `set runmode`. The fake RHX defers the same way by default, and a test pins the fake's own deferral so the client test cannot pass trivially |
| Are all replies `Return: <Name> <value>`? | **No.** `CurrentTimestamp` and `CurrentTimeSeconds` answer namelessly — `Return: 704383`, `Return: 48.3626` | Read as name-then-value they came back empty and `start_recording` could not parse a sample count. `get()` now returns the lone token as the value; the fake sends them namelessly too |
| Can `TCPDataOutputEnabledHigh` change while RHX is running? | **Yes**, and a batched `get` behind it is answered normally | A SpikeScope can be opened mid-recording, as designed |
| Can `SpikeThresholdMicroVolts` change while running? | **Yes** — read back as set | The SpikeScope's threshold drag works live |
| Does RHX keep the case of what it is given? | **Paths, base filenames and enum values: yes. Notes and custom channel names: no** — `BOX1_EVENTS` is stored as `box1_events`, a note as all lowercase | The recorded `intan_recording` name matches the files on disk. The digital inputs read `box3_events` in RHX and in its saved headers. `verify` compares case-insensitively, so neither trips it |
| Are `intan.configure`'s parameter names all real? | **Yes** — every `set`/`execute` it sends was accepted by name (save flags, snapshot windows, downsample rate, channel enables, spike and digital TCP outputs, custom names, notes, both data-socket statuses) | No `Unrecognized parameter` waiting in the walkthrough |
| Is a `set` that RHX forbids while running reported? | **Yes** — `FileFormat cannot be set while controller is running.`, ahead of the sentinel's reply | Exactly the error path the confirmed write was built for |

**Still open:**

| Question | If the answer is the bad one |
|---|---|
| Does the RMS-relative threshold need the board to have run first? | Thresholds land wrong. Fix: a short `run` before `SetSpikeDetectionThresholds` |
| Digital-input naming on the USB Interface Board (0-based) | Handled in `digital_in_name`; untested on that board |
| A real sync line into a real DIN | The firmware compiles for all three sketches and passes host tests; the electrical link has not been scoped |
| A full recording through the app | Configure → record → live windows → graceful end has only ever run against the fake. The live windows have been driven against RHX's **synthetic** demo (2026-09-21): a single Spike Scope channel streamed; switching channel did not (fixed, §7); the probe map did not draw (fixed, §7) |
| Where a channel swap lands in the waveform stream | The switch is placed at `currenttimestamp` read after RHX acknowledged the swap, on the argument that RHX's TCP output lags acquisition and so cannot have written a block *newer* than that in the old shape. If RHX's output thread can run ahead of its clock reading, a few blocks after the marker would be misfiled — for one channel swap, a snippet or two on the wrong channel, then correct |

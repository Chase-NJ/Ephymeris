---
status: proposed
---

# A run's document is nested and versioned, and a recorded run gets one analysis file

The lab is about to record spikes, and the people reading the data are not programmers. Today a run's
document ([DATA.md](../DATA.md#the-json-document)) is 70 keys at one level, an odor's name, side and reward
are spread over three places, the box and the start time are not in the file at all, and a run flashed
before [stream grammar](../../GLOSSARY.md#stream-grammar) 2 carries no trial table. The lab's own scripts
pair Intan pulses with strobes by row index and find trials by a code's position
(`eeh_6_odor_shell_.m`). We propose:

- The run document becomes **version 2**: a `schema_version`, and its facts grouped under `run`, `task`,
  `params`, `odors`, `recording`, `implant`, `channels`, `trials`, with `ts_data` and `task_profile` kept where and as they are.
- The **trial table** is the thing people read. It gains what analysis asks of it most: the odor's name,
  the reward given, and each event time on the recording's clock.
- A recorded run is **aligned and exported at session end**, not when first viewed.
- Sorting stays in Plexon Offline Sorter. Ephymeris writes the spike file it imports, one per animal, and
  reads the sorted units back into **one analysis file per run**: the trial table and each unit's spike
  times, on one clock.

Nothing recorded so far has neural data, so this is the last cheap moment to change the shape.

## Scope

**In:** the `.json` and `.mat` of runs started after the change; the files written beside a recorded run;
reading version 1 forever.

**Out:** rewriting the 732 recorded version-1 runs; the `.tsv` log's format, which stays the board's own
lines under a `# key: value` header ([DATA.md](../DATA.md#the-tsv-log)); moving GRGL to the spine
([ADR 0003](0003-phase-spine-task-model.md)), which has not run on a wired box; spike sorting itself.

**Done means:** with one animal's analysis file loaded, "mean firing on correct against error trials, per
odor and per reward size" is a table filter, in MATLAB or Python, with no event code and no file path
typed by hand.

## The run document, version 2

The values are remy1's run of 2026-10-30 where that file has them; `box`, `started_at`'s offset, `task.stream`
onward and `recording` are illustrative.

```jsonc
{
  "schema_version": 2,
  "run":  {"animal": "remy1", "cohort": "The Remy's", "box": 2, "session_id": "8O-Bdisc_09",
           "date": "2026-10-30", "run_of_day": 1, "started_at": "2026-10-30T11:29:26-05:00",
           "serial_port": "COM5", "stop_reason": "BF_END_SESSION received", "n_events": 2419},
  "task": {"sketch": "GRGL 8-Odor EZ", "stream": 2, "interp": 1, "free_ram": 5120,
           "trial_seed": 1987552345, "host_seed": 1987552345,
           "channel_set_hash": "…", "channel_set_hash_version": 2},
  "params": {"num_trials": 1000, "error_delay": 20000, "…": "one key per metadataKey, as today"},
  "odors": [{"line": 1, "name": "GR-Sandalwood", "onset_code": 101, "side": "right",
             "reward_ms": 100, "pool_weight": 1}],
  "recording": {"path": "…", "name": "…", "port": "A", "channels": "A-016:A-031",
                "digital_in": 1, "sample_rate": 30000},
  "trials": {"status": "ok", "detail": null, "grammar": 2, "replay_version": 4, "rows": [ … ]},
  "ts_data": [[221, 0], [222, 1001]],
  "task_profile": { … }
}
```

- **`run`** adds `box`, `cohort`, `date`, `run_of_day` and `started_at` (ISO 8601 with its offset). They are known before
  the first strobe, so they go in the `.tsv` header too and a [recovered run](../../GLOSSARY.md#recovered-run)
  keeps them.
- **`params`** holds what was flat. The collision rule on `CORE_METADATA_KEYS`
  ([DATA.md](../DATA.md#the-json-document)) goes away, since a parameter can no longer overwrite a core field.
- **`odors`** is one row per odor line a [trial type](../../GLOSSARY.md#trial-type) presents, built from the
  profile snapshot's `trialTypes` ([TASKS.md](../TASKS.md#trial-types-in-the-profile)) and the merged
  parameters at run start. It is the one home for "which odor, which well, how much".
- **`recording`** replaces the six flat `intan_*` fields ([RECORDING.md](../RECORDING.md#what-is-written)),
  and is absent on a behavior-only run.
- **`trials`** is today's `derived` block ([DATA.md](../DATA.md#the-derived-trial-table)) under the name
  people look for, its rows under `rows`.
- **`ts_data`** keeps its name, place and shape. It stays the record; every other block can be rebuilt
  from it and the header.

In the `.mat`, each block is a struct (`S.run.box`, `S.params.reward_time_5`), `odors` and `trials.rows`
are N×1 struct arrays (`struct2table(S.trials.rows)`), and `task_profile` stays JSON text. The classes
[the mirror](../DATA.md#the-mat-mirror) forces are unchanged.

## The trial table's columns

A grammar-2 run's row is `grammar2.TrialRow`. It keeps every column it has (`index`, `type_slot`,
`odor_line`, `side`, `sampled`, `outcome`, `outcome_class`, `correct`, `response`, `reaction_ms`, `repeat`,
and the `*_ms` times) and gains:

| Column | Meaning |
|---|---|
| `odor_name` | The `odors` row's name for `odor_line`; `''` when no odor was delivered |
| `reward_ms` | How long the valve was held open on this trial; 0 when none was given |
| `reward_on_ms` | When the valve opened |
| `correction` | The trial was a correction trial |
| `*_s` | Each `*_ms` time on the recording's clock, in seconds; NaN when the run was not recorded or the event's pulse never came |

`correct` and `outcome_class` are what "correct against error" filters on; a trial no accuracy counts (an
abort) is neither, as today.

> [!CAUTION]
> **The `*_s` columns are written only after alignment**, so a run's `.json` built at finalization has them
> empty until the session-end pass fills them. A reader must take "all NaN" as "not aligned", never as
> "nothing happened".

## The implant

An animal's implant is entered once, on the animal, and a recorded run copies it as it stood that day.
It serves both kinds of device the lab uses: a probe with a probe-map file, and a custom 32-channel
electrode whose two bundles of 16 sit 3 mm apart in different regions.

```jsonc
"implant": {
  "device": "custom 32-channel electrode", "surgery_date": "2026-11-30", "probe_map": null,
  "targets": [
    {"name": "OFC",  "region": "orbitofrontal cortex", "hemisphere": "left",
     "ap_mm": 3.2, "ml_mm": 2.4, "dv_mm": 4.6, "depth_set_on": "2026-12-14", "channels": "0-15"},
    {"name": "…",    "region": "…", "hemisphere": "left",
     "ap_mm": 0.2, "ml_mm": 2.4, "dv_mm": 4.6, "depth_set_on": "2026-12-14", "channels": "16-31"}
  ]
},
"channels": [{"native": "A-016", "device_channel": 0, "target": "OFC", "x_um": null, "y_um": null}]
```

- A **target** is a group of the device's channels that sit at one place in the brain. Intan's own word
  "site" means one contact, so it is not used for the group.
- **A target's channels are numbered on the device (0 to 31), never by RHX's native name.** The native name
  depends on the port and channel range the box was given that day
  ([RECORDING.md](../RECORDING.md#record-step)); the device's numbering does not.
- **`channels`** is the run's own table, one row per recorded channel: its native name, its number on the
  device, its target, and its position from the probe map when the animal has one. It is the one place
  the two numberings meet, built at run start from the implant and the box's channel range.
- Every unit in the analysis file carries its channel's `target` and `region`, so "units in OFC" is a
  filter.
- A probe's targets are channel ranges too: a shank that crosses two regions is two targets.
- **A custom electrode's device channel is the number printed beside its hole on the lab's 32-channel
  EIB.** The EIB and its Harwin-to-Omnetics adapter reorder the wires, but the board files show each
  printed number is the headstage channel that hole reaches: socket S2 carries 0 to 15 and socket S3
  carries 16 to 31. A bundle loaded into the holes numbered 0 to 15 is the target with channels `0-15`,
  and no separate adapter table is kept. This is traced from the KiCad files, not yet checked on a bench.
- **Depth is a dated history, because the electrodes are on drives.** One drive carries the whole
  electrode, so a lowering is entered once on the implant, as a date and a distance in mm, and moves every
  target's `dv_mm` by that distance. A run copies the depth in force on its date into its
  target's `dv_mm`, with `depth_set_on`, the date of that lowering. Editing the history later never
  changes a run already written.
- A lowering moves the contacts to different neurons, so units are never assumed to be the same across
  one. `depth_set_on` is what lets analysis group sessions recorded at one depth.
- The values above are illustrative; none is a real coordinate.

## A recorded run at session end

Once RHX has closed its files, off the session's critical path and never able to fail a run
([RECORDING.md](../RECORDING.md#the-rule)):

1. **Align** each run with `intan/events.py`'s `align`, as the [event PSTH](../RECORDING.md#event-psth)
   does on first view today, and write its counts (`matched`, `missed`, `stray`) into `recording.sync`.
2. **Fill** the trial table's `*_s` columns and write the events file.
3. **Export spikes** for sorting, one file per animal:
   `sort/<run>.spikes.mat` with `spiketimes` (K×1 cell, seconds), `spikewaves` (K×1 cell, n×S, µV) and
   `unique_ch` (K×1 cell of native names). These are the variables the lab's `save_extracted_spikes.m`
   writes per port, so Offline Sorter's import is set up as it is now. The lab's reader is the reference
   for every detail: each cell of `spiketimes` is n×1 double, each cell of `spikewaves` is n×S double with
   rows as spikes, µV is `0.195 × (count − 32768)`, a channel with no spikes is left out, and `unique_ch`
   holds one whole name per cell.

After sorting, **Import sorted units** reads the `.plx` or `.pl2` and writes
`analysis/<run>.analysis.mat`:

```
run, task, odors, implant, channels    as in the run document
trials                    N×1 struct array, the trial table with its *_s columns
units                     U×1 struct array: channel, target, region, unit, n_spikes, spike_s (seconds), mean_wave (µV)
```

A run that was never sorted has no analysis file. The run document is never rewritten with units.

> [!CAUTION]
> **A recording must save spike snapshots**, or `spike.dat` holds timestamps only and there is nothing to
> sort. Starting a recording with `saveSpikes` on and `saveSpikeSnapshots` off should be refused, not warned.

## Migration

- **Readers take both versions.** `analytics/reader.py` lifts a version-1 document into the version-2
  shape in memory; nothing downstream sees a flat one. No recorded file is rewritten.
- **Hashes do not move.** `params_hash` and `profile_hash` are computed from the same values wherever they
  sit ([TASKS.md](../TASKS.md#profile-and-params-hashes)), so runs before and after stay comparable.
- **The score cache version moves**, since file reading changes ([DATA.md](../DATA.md#caching)).
- **Recovery** (`sessions/recovery.py`) writes version 2 from any `.tsv`; a header without `box` or
  `started_at` leaves them null.
- **The lab's old scripts** that read `S.ts_data` keep working; ones that read `S.reward_time_5` need
  `S.params.reward_time_5`.
- Every board is reflashed with the current trial runner before the first recording, so every recorded
  run announces `STREAM=2` and has a trial table.

## Considered options

| Option | Why not |
|---|---|
| Keep the flat document and add only a trial table | The box, date and odor table would still be missing, and 60 loose parameters beside 10 core fields is what makes the file hard to read |
| Write `.plx` or `.nex` directly | Nothing on the lab's machines does this today, the formats are binary and version-sensitive, and the `.mat` import is the path the PI already uses |
| Sort with Kilosort from the wideband | The PI sorts in Offline Sorter; the wideband is kept so this stays possible later |
| Put sorted units into the run's `.json` | The run document is built once at the end of behavior; units arrive days later and can be re-sorted |
| NWB as the analysis file | The standard answer, but it needs a heavy dependency ([policy](../DEVELOPING.md#dependency-policy)) and a reader the PI has never used |
| Move GRGL to the spine first | Its replayed table is richer, but it has only run with nothing wired and has no per-side correction budgets |

## Consequences

- A version-2 file is not readable by a build older than this change. Two lab machines share one archive,
  so both update before either records.
- `sessions.rederive` rewrites the `trials` block where it rewrote `derived`, and must leave a newer
  build's block alone as it does now ([DATA.md](../DATA.md#re-derive)).
- The events file and the trial table's `*_s` columns say the same thing two ways. The events file stays
  for sorters and scripts that want every strobe; the trial table is the one people are pointed at.
- Reading a `.plx` needs Plexon's reader. If no stdlib-plus-numpy reader is acceptable under the
  dependency policy, the import is a MATLAB function shipped beside the data instead of an app action.

## Open questions

1. ~~Reward volume.~~ **Decided: `reward_ms` only.** The lab compares small against large rewards, and
   sets the valves by eye each day, so no measured volume exists to store. A µL column would need a
   weighed per-valve calibration and is not planned.
2. ~~Wideband.~~ **Decided: saved beside the spikes by default**, with the switch to turn it off kept, as
   RHX has it. Spikes-only fixes the detection threshold at record time; wideband keeps re-detection and
   re-sorting open. Wideband already defaults on ([RECORDING.md](../RECORDING.md#record-step)); a machine
   whose saved defaults turned it off is set back.
3. **Offline Sorter's import settings.** The variable mapping and the alignment sample are set in its GUI,
   not in code. One real import by the PI, or one sorted `.plx`, is needed to pin `sort/` and the import.
4. ~~Snapshot window.~~ **Decided: `sort/` writes samples 25:54 of each snapshot**, the 30 samples the PI has
   always sorted on: 6 before the crossing and 24 after, when the snapshot keeps 30 samples before a
   detection. The recording default becomes 1 ms before and 1 ms after (30 and 30 samples at 30 kS/s), as
   the lab's recording of 2026-04-17 had. The window is counted from the crossing, so a snapshot with a
   different lead-in is clipped at the same part of the spike. Spikes RHX flagged as artifacts (id 128)
   are kept, as the lab's scripts keep them.
5. ~~One row per trial across rounds.~~ **Decided: one analysis file per run, never joined.** A run is one
   animal in one [round](../../GLOSSARY.md#round), so every time in a file is on one clock and its units
   come from one sorting. `run.run_of_day` (1, 2, …) orders an animal's runs of one date, so pooling a day
   is a concatenation the reader chooses to make.
6. ~~Animal facts.~~ **Decided: implant facts only**, entered once per animal and copied into each run
   ([The implant](#the-implant)). Weight, age and water restriction stay out of Ephymeris. The lab's
   electrodes are on drives, so depth is a dated history, and one drive moves every target of an
   electrode together. A lowering is entered in millimetres.

# Data

What lands on disk and in the database, and how it is read back. Metric definitions: [ANALYTICS.md](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md). What triggers the writes: [ARCHITECTURE.md](ARCHITECTURE.md#session-lifecycle). Commands: [PROTOCOL.md](PROTOCOL.md).

> [!IMPORTANT]
> **`.tsv` is not an export format.** It is the write-ahead log, fsync'd per strobe; `.json` and `.mat` are built once, at clean finalization ([Crash safety](#crash-safety)).

## Contents

- [Directory layout and naming](#directory-layout-and-naming)
- [Cohorts and animals](#cohorts-and-animals)
- [Sessions and runs](#sessions-and-runs)
- [The session log](#the-session-log)
- [Per-animal files](#per-animal-files)
- [Crash safety](#crash-safety)
- [Crash recovery](#crash-recovery)
- [Re-derive](#re-derive)
- [SQLite database](#sqlite-database)
- [Backup mirroring](#backup-mirroring)
- [Reading the archive](#reading-the-archive)
- [Analytics views](#analytics-views)

## Directory layout and naming

### Layout

```
<dataDirectory>/<cohort name>/<prefix>/<prefix>_<sessionNumber>_<YYYY-MM-DD>/
    notes.md                                    ← the session log, derived
    behavior.tsv/<animal>_<prefix>_<number>_<date>_<HHMMSS>.tsv     ← written live
    behavior.json/….json  behavior.mat/….mat                         ← built at run end
    events/….events.json  ….events.mat           ← a recorded run's events on RHX's clock, when its recording ends
    sort/….spikes.mat                            ← a recorded run's spikes for Offline Sorter ([RECORDING.md](RECORDING.md#the-sort-export))
```

Built by `sessions/paths.py` (`resolve_session_folder`, `resolve_animal_files`). Reusing a prefix and number on one day is allowed (`sessions.suggestNumber` warns via `sameDayNumbers`); the files land side by side.

### Names

| Element | Format | Example |
|---|---|---|
| Session folder | `<prefix>_<sessionNumber>_<YYYY-MM-DD>` | `2O-Bdisc_25_2026-07-22` |
| Per-animal file | `<animal>_<prefix>_<number>_<date>_<HHMMSS>.<ext>` | `remy1_2O-Bdisc_25_2026-07-22_113123.json` |

`HHMMSS` is when **that animal's run** started. Every name part passes through `cohorts/folders.py`'s `sanitize_name`.

### Why the date is hyphenated

Older folders use `MM_DD_YY`, which does not sort across years. Hyphenated ISO changes the number of `_` tokens, so a positional parser breaks visibly instead of misreading dates. Nothing is renamed; both spellings coexist.

> [!CAUTION]
> **Never sort these names as strings.** Use `sessions/paths.py`'s `parse_name_date`, which reads both formats anchored at the end of the name.

### Reading names other software wrote

Names are read as written: `parse_session_folder` finds the session number by being numeric, trailing or leading (`00_01_shaping_gr_06_17_26`), and separators are never normalized (`2O-Bdisc` and `2O_bdisc` are distinct prefixes).

## Cohorts and animals

### Data model

`cohorts/models.py`; tables `cohorts`, `animals` ([Tables](#tables)).

| Entity | Notes |
|---|---|
| **Cohort** | `name`; `dataFolder` (absolute, resolved once); `archivedAt` (null = active); `appearance` (null = derived from `id`) |
| **Animal** | `boxNumber` (1–6 or null, the **usual box**); `cage` (≥ 1 or null); `sex` (`M`/`F`/`unknown`/null); `idNumber` (free text) |

The usual box is only where session set-up starts: which animals run together, and in which boxes, is chosen per [round](../GLOSSARY.md#round) ([ARCHITECTURE.md](ARCHITECTURE.md#mapping-and-the-placement-walk)), and the box a run used is on its [run record](#run-records). `cage` only changes what the 3D views draw.

### Validation

`cohorts/repository.py`'s `_validate`, per field:

| Rule | Detail |
|---|---|
| Cohort name | Unique among **active** cohorts (`idx_cohorts_active_name`) |
| Animal name | Unique within the roster, case-insensitively; a [former member](#former-members)'s may be reused |
| Animal id | Refused if another cohort holds it; use a [move](#moving-animals-between-cohorts) |
| `boxNumber` | `1`–`6` only. Animals may share a usual box: a clash matters only among the animals of one round, where set-up gives the box to one of them |

> [!IMPORTANT]
> **The box rule is split on purpose.** The sidecar checks only the range, since two machines with different bindings share one data directory; the editor offers only boxes bound here (`src/features/cohorts/boxAvailability.ts`). A stored box this machine can't honour is **kept and reported, never rewritten**, and not reported while the sidecar is disconnected.

### Former members

History keeps `animal_id` with no foreign key ([Indexes](#indexes)), so a **former member** (`cohorts/members.py`) keeps the name of an animal no longer on the roster:

| Source | What it is |
|---|---|
| `removed` | Removed by `cohorts.update` while it had a run, adoption, note or [weigh-in](#weigh-ins); kept in `former_animals` with its name and biography. An animal with no history is just deleted |
| `files` | An id the history names with no row; named at read time from its runs' stored paths, never written back |

On the wire as `Cohort.formerAnimals` (single-cohort loads only); `Cohort.animals` stays the roster. Restoring is posting the id in `animals` again. Analytics lists former members after the roster (`AnalyticsAnimal.former`), so no colour shifts. `former_animals` is its own table because `animals` rows are deleted and re-inserted on every roster save.

### Implants

An animal's **implant** (`cohorts/implants.py`, `Animal.implant` on the wire) is entered once, in the cohort editor's roster: a device, its surgery date, an optional probe-map file, one or more [targets](../GLOSSARY.md#target) and the lowerings of its drive.

| Part | Holds |
|---|---|
| Target | `name`, `region`, `hemisphere` (`left`, `right`, `midline`), `apMm`, `mlMm`, `dvMm` (depth at surgery) and `channels` |
| Lowering | `date` and `mm` (deeper is positive), never before the surgery |

- **Channels are numbered on the device**, never by RHX's native name: a range (`0-15`), a list (`0,2,4`) or both (`parse_channels`). No two targets of one implant may claim a channel. On the lab's custom 32-channel electrode the number is the one printed beside the hole on the EIB.
- **Depth is a dated history.** One drive carries the whole electrode, so a lowering moves every target. `depth_on(implant, target, date)` gives the surgery `dvMm` plus every lowering on or before the date, with the date of the last one (the surgery date when there is none).
- **Its own table, `implants`, keyed by the animal's id with no foreign key**, because a roster save deletes and re-inserts every `animals` row ([Indexes](#indexes)). So it survives a rename and a roster re-save, stays with a [former member](#former-members), and a [move](#moving-animals-between-cohorts) re-keys it to the animal it joins unless that animal has its own. An animal deleted outright takes its implant with it.
- **Posting a roster**: `implant: null` removes it; an animal posted without the key keeps what is stored.
- **The implant is the one home of a probe map.** The Record step shows it and never asks for one ([RECORDING.md](RECORDING.md#record-step)).
- **A recorded run copies it** as it stood on the session's date ([RECORDING.md](RECORDING.md#what-is-written)).

### Data folder

`cohorts/folders.py` sets `dataFolder = <dataDirectory>/<sanitized name>` (suffixed `-2`, `-3`, … if taken) and stores it verbatim: **renaming a cohort never moves its folder.**

`cohorts.setDataFolder` (`cohorts/relocate.py`) with `moveExisting: true` moves the data into an **empty** folder; with `false` it points at data already there (how a pre-Ephymeris archive is attached for [adoption](#orphan-adoption)) and writes nothing.

A move carries every stored absolute path with it (records, adoptions, cache rows with their [freshness keys](#caching), and RHX save locations and impedance CSVs inside the folder; all listed in `cohorts/db.py`'s `DATA_PATHS`, which a test keeps complete), journalled in `folder_moves`:

```mermaid
flowchart LR
    req["setDataFolder<br/>moveExisting: true"] --> same{"Same volume?"}
    same -->|"yes"| rename["Atomic rename<br/>(journal: moving)"] --> rec1["Records in<br/>one transaction"]
    same -->|"no"| copy["Verified copy<br/>(journal: copying)"] --> rec2["Records committed<br/>(journal: committed)"] --> del["Delete originals"]
    rename -.->|"crash"| fwd["Next start rolls<br/>records forward"]
    copy -.->|"crash"| undo["Next start that reaches<br/>both folders undoes"]
    rec2 -.->|"crash"| fin["Next start finishes"]
```

It runs under the [archive lock](#the-cohort-archive) and is refused while any session is set up or running, or the cohort has an open session. An unfinished journal refuses only operations that would collide with it.

> [!CAUTION]
> **A session recorded during a copy keeps its files at the old place**, so `sessions.create` is refused until the originals are deleted, and the commit abandons the move if anything was recorded meanwhile.

A rescan re-points (`rehomed`) records an older relocate left behind, wherever the file exists at the same tail under the cohort's folder.

### Moving animals between cohorts

`cohorts.moveAnimals` (`cohorts/move.py` plans, `cohorts/move_apply.py` applies) moves animals **with their history**: their files go to the destination's folder, and run records, recovered runs and notes follow. Preview with `apply: false`; the apply re-plans.

- **Identity**, by case-folded name: a roster animal or [former member](#former-members) of that name in the destination is **joined**; otherwise the animal is carried under its own id.
- **Files:** every `.json`/`.tsv`/`.mat` of its recorded and [adopted](#orphan-adoption) runs, plus unrecorded files whose stem names it. Never `notes.md`, RHX recordings or AppleDouble files.
- **Sessions** only moved animals ran in move whole; shared ones are **split**, the destination getting its own record (no recording). Notes about moved animals or their boxes move, about staying ones stay, and the rest (whole-session, shared box) are **copied**.
- **Impedance history** ([RECORDING.md](RECORDING.md#impedance-tracking)) and [weigh-ins](#weigh-ins)
  follow the animal into the one it joins; on a day both were weighed, the destination's stands.
- **Caches** follow with their [freshness keys](#caching). An adoption whose run the destination already holds joins that row, which keeps its id and ruling.
- **Refused** with nothing touched when: anything runs; either cohort has an open session; a folder is unreachable, shared or nested; a destination file differs; a run file lies outside the source; two moved animals share a name; the destination is archived; or an earlier move would collide.

```mermaid
flowchart LR
    j["Journal plan in animal_moves<br/>state: copying"] --> c["Verified copy<br/>of each file"] --> m["One transaction: re-plan,<br/>move records, state: committed"] --> d["Delete originals, rmdir empties<br/>state: done"]
    c -.->|"crash: move_apply.resume undoes"| j
    m -.->|"crash: move_apply.resume finishes"| d
```

> [!CAUTION]
> **The other lab machine still points at the source folder**, and a rescan there would [prune](#pruning) the moved runs. **Run the same move there first**; it finds the files moved and re-points its records.

### Verified transfer

A cross-volume [relocate](#data-folder) and a [move](#moving-animals-between-cohorts) copy through `cohorts/transfer.py`: each file via `<name>.part`, fsync, rename, then a SHA-256 check against the original. Undo removes a copy, and the final delete an original, only when the other file is present **with the same content**, read now, never a remembered hash.

A file that can't be seen (`relocate.out_of_reach`: a `stat` failing other than not-found, or no ancestor answering) is never read as deleted: the transfer waits, journal unchanged, for a start that reaches both folders. [Pruning](#pruning) reads absence the same way.

### Archive and delete

**Archive** (`cohorts.archive`) is the everyday delete: hidden, intact, reversible (`cohorts.restore`). **Permanent delete** (`cohorts.delete`) works only on an archived cohort and cascades to its rows. **Neither touches `dataFolder` on disk.**

## Sessions and runs

### Prefixes

A **prefix** names a task and is global (`prefixes.*`, unique case-insensitively). Deleting one only hides it from the dropdown; sessions keep their own `prefix_name`.

### Session records

One `sessions` row per session flow (`sessions/models.py`'s `Session`). `sessionNumber` is free text: never sort by it. `startedAt`/`endedAt` are when the record opened (Step 1) and closed, not when boxes ran ([The session clock](#the-session-clock)). `status` runs `configuring` → `running` → `completed`, or `aborted`. `rounds` lists `{order, startedAt, endedAt, label}` per [round](../GLOSSARY.md#round), `label` being the group's name on a round recorded while cohorts had groups and null since; `durationMinutes` is an optional per-box limit; `recording` is null for behavior only ([RECORDING.md](RECORDING.md#what-is-written)). Listings are ordered by `(date, startedAt)` and carry an `ordinal`.

### Run records

One `session_animal_runs` row per animal per session (`SessionAnimalRun`), the unit Analytics scores. Beyond ids, box, timings and `stopReason`, it stores `filePath` (the `.json`), `profileHash`, `config_json` (merged parameters), `paramsHash`, and, from finalization, `interp` and `channel_set_hash` (as in the [`.tsv` header](#the-tsv-log)). Nothing reads or writes the `diverged` column.

> [!IMPORTANT]
> **`profileHash` records the Task Profile the run used**, since `task.json` can change later; null marks a run from before snapshots ([TASKS.md](TASKS.md#profile-and-params-hashes)).

### Continuing between rounds

Resuming a round mid-run is out of scope. `sessions.resume` re-holds one of *today's* sessions that already ran a round, closes any round left open, and waits between rounds ([ARCHITECTURE.md](ARCHITECTURE.md#between-rounds)).

## The session log

The **Log** tab, a cohort's lab notebook ([ARCHITECTURE.md](ARCHITECTURE.md#the-paper-exception)): notes and free fields per session, the session clock, what changed per run, each day's [weigh-ins](#weigh-ins) and, for a recorded session, how much there is to sort ([RECORDING.md](RECORDING.md#unit-like-sites)). Owned by `logbook/` (`logbook.*`, [PROTOCOL.md](PROTOCOL.md#session-log); [USER-GUIDE.md](USER-GUIDE.md#keeping-the-log)).

> [!IMPORTANT]
> **Notes are user data.** A session with one is never judged empty by [Tidy records](#tidy-records) or [pruned](#pruning); deletes are soft (`deleted_at`).

### The session clock

Derived, never stored (`Session.clock_started_at`, `clock_ended_at`): `clockStartedAt` is the earliest round's start (else the record's), `clockEndedAt` the latest round's end once all are closed (null while open). Elapsed time everywhere uses it. A recovered session (`adopted:…`) runs from its earliest file to its latest stream end (from the [metrics cache](#caching)), shown with `~`. A note's T+ offset (`offsetMs`) is derived on read, and absent outside the clock's span.

> [!CAUTION]
> **The session clock is not a run's clock**: a stream's `t = 0` trails its run's `started_at`, so notes on a [trial tape](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#per-trial-tape) are approximate.

### Notes

`session_notes`: `at` (editable), a tag (`observation`, `intervention`, `hardware`, `animal-health`, `protocol-deviation`), a scope (session, animal or box) and text; no revision history. Operator and summary live in `session_logs`. A recovered-files session takes no notes.

### Carry-forward flags

A **carry forward** note stays open until resolved and shows in Step 1 and Mission Control (`logbook.openFlags`); `resolved_in_session` follows a tidy merge.

### Weigh-ins

`animal_health`: one row per **animal and calendar day**, a body weight in grams and whether it is marked as the animal's **baseline** (`logbook.setHealth`, `LogbookCohort.health`). Never per session: an animal is weighed once a day however often the cohort runs, so two sessions on one day show the same weight, and a day's weight is entered from any session's page of that day.

- **Keyed by the animal's id with no foreign key**, as [implants](#implants) are, because a roster save deletes and re-inserts every `animals` row. It stays with a [former member](#former-members) and follows a [moved](#moving-animals-between-cohorts) animal; [Tidy records](#tidy-records) and [pruning](#pruning) never touch it, since no session owns it.
- **A weight is 1 to 2000 g.** Writing `null` removes the day's weigh-in, its baseline mark with it. The row stays, marked `removed_at`, as a deleted note's does: a removal has to reach the copies other machines hold ([The log file](#the-log-file)). A removed weigh-in is in no reading and never on the wire.
- **A percentage is only ever of a marked baseline**: a weigh-in is read against the latest one marked at or before its day (`features/logbook/health.ts`'s `readWeight`). With none marked the page shows the change since the weigh-in before and no share, since the first weight on record is not assumed to be a free-feeding one. Under 85% of baseline (`LOW_WEIGHT_FRACTION`) the row is marked low: a prompt to look, not a rule the app enforces.
- Other health observations are [notes](#notes) tagged `animal-health` about that animal; the weights table starts one.

### What changed

`logbook/diff.py` compares each run, recorded or [adopted](#orphan-adoption), with the animal's previous one by `(date, started_at)`: task (by profile hash; a new hash under one name is *definition revised*), box (only when both are known; recovered runs' are `null`), and parameters (by `params_hash`, then key by key). Missing parameters report `paramsKnown: false`, **unknown, never "changed"**.

### The notes.md mirror

Each folder with a log (a note, a free field, or a weigh-in on its day) gets a derived `notes.md` for a person to read, the day's weights included, beside the [log file](#the-log-file) a machine reads, rewritten whole about a second after a change (via `.part`, per-folder lock, off every command path) and queued for [backup](#session-files). Never read back, never creates a missing prefix folder, invisible to the archive walk.

### The log file

`log.json`, beside `notes.md`: the same log for a machine to read back, so a session's notes go where its folder goes ([ADR 0011](adr/DECISIONS.md#0011-the-log-travels-in-the-session-folder)). **The database is still where the log is kept and worked on**; the file is how it reaches another machine. Written by the mirror step that writes `notes.md` (`logbook/logfile.py`), and also for a session nobody wrote in, whose record alone goes into a folder that is already there.

| In the file | |
|---|---|
| Each record sharing the folder | Its id, prefix, number, date, start, end, status and rounds; operator, summary and when they were set |
| Each note | Id, every stamp, tag, scope, words, flag state. **An animal by name**, the writing machine's id beside it: ids are each machine's own |
| A deleted note, a removed weigh-in | A marker only: which one and when, never its content |
| The weigh-ins of the folder's days | Animal by name, grams, baseline mark, when recorded |

Nothing in it changes unless the log did (it carries no "written at"), so an unchanged session costs no write and no backup copy.

**Read in two places** (`logbook/intake.py`), always as a merge:

- **By a Rescan**, for every session folder the walk finds a run in and every folder a record points at (`RescanResult.logs`). A session this database has no record of is **recorded** from the file, under its own id; the [recovered runs](../GLOSSARY.md#recovered-run) of that folder then count under it ([Orphan adoption](#orphan-adoption)), so the day is a session like any other and can be written in.
- **Before every rewrite of the file**, since a folder copied in may hold notes this database has never seen. This read never records a session.

| | Rule |
|---|---|
| A note | Known by id. Added if absent here; replaced only by a **newer** one (the latest of its created, edited, resolved and deleted stamps). A marker deletes a note it is newer than |
| Operator and summary | Together, the newer `updated_at` winning; a newer blank clears |
| A weigh-in | Known by animal and day, the newer `recorded_at` winning; a marker removes one it is newer than |
| An animal | Matched by name, roster before [former members](#former-members). A note about one this cohort lacks is kept, under the id it came with, and re-pointed once the animal is added; a weigh-in for one is left in the file. Both are named in the rescan's note |
| A session record | Never changed once here. Recorded from a file as **ended**, whatever the file says, with the folder as it lies on this machine, no recording, and its prefix made if this machine has none of that name |

> [!CAUTION]
> **Absence is never a deletion.** A note the file does not mention is left alone; otherwise the older of two copies would erase everything written since it was made. Only a marker deletes.

> [!CAUTION]
> **A file from a newer build is neither read nor written over** (`log_version`): rewriting it from here would drop what the newer format added. A damaged one is counted unreadable and replaced at the folder's next write.

Limits: "newer" trusts the two machines' clocks; a reopened flag has no time of its own, so a reopening does not travel; and what was measured of a recording ([RECORDING.md](RECORDING.md#unit-like-sites)) stays with the machine that recorded it.

### Exporting a log

**Session PDF** and **Logbook PDF** are rendered by `@react-pdf/renderer` (`features/logbook/pdf/`) from strings built in `features/logbook/document.ts` ([ARCHITECTURE.md](ARCHITECTURE.md#printed-documents)).

> [!CAUTION]
> Keep ligatures off (`fontFeatureSettings`; subset fonts throw), unsupported characters mapped (`printable`), fonts as inlined `.woff`, title heights pinned, and the page footer **pinned from the top** (pinned by `bottom` it grows per page until a long export fails; `features/logbook/pdf.test.ts` renders forty sessions).

## Per-animal files

### The JSON document

A run is written as **version 2**: `"schema_version": 2`, then its facts in blocks, in this order.

| Block | Holds |
|---|---|
| `run` | `animal`, `cohort`, `box`; `session_id` (`<prefix>_<sessionNumber>`); `date` (the session's); `run_of_day`; `started_at` (ISO 8601 with its UTC offset); `serial_port` (the OS port); `stop_reason`; `n_events` |
| `task` | `sketch`; `stream`, `interp`, `free_ram`, `sync` as announced before `READY` ([TASKS.md](TASKS.md#confirming-the-parameters), [stream](TASKS.md#stream-grammar), [sync](RECORDING.md#firmware-pulse)); `trial_seed` (the board's `SEED` line) and `host_seed` (the app's `START` line); `channel_set_hash`, `channel_set_hash_version` ([TASKS.md](TASKS.md#registry-rules)) |
| `params` | The merged parameters, one key per `metadataKey` |
| `odors` | The [odors table](#the-odors-table); `[]` for a task with none |
| `recording` | `path`, `name`, `port`, `channels`, `digital_in`, `sample_rate`, and `sync` once the run is [aligned](RECORDING.md#alignment-at-session-end); recordings only ([RECORDING.md](RECORDING.md#what-is-written)) |
| `implant`, `channels` | The animal's implant as it stood that day, and one row per recorded channel; recordings only ([RECORDING.md](RECORDING.md#what-is-written)) |
| `trials` | The [trial table](#the-trial-table) |
| `ts_data` | `[code, timestamp_ms]` as sent, ms from **that animal's** start |
| `task_profile` | The [profile snapshot](#the-embedded-task-profile) |

- **`run_of_day`** is 1 for an animal's first run of the session's date in its cohort, then 2, …, counted from the [run records](#run-records) when the box starts.
- **`stop_reason`** is `BF_END_SESSION received` (clean), `board disconnected`, `sidecar error: <cause>`, `recovered after crash`, …
- **A field the run does not have is left out**, except the five run facts (`cohort`, `box`, `date`, `run_of_day`, `started_at`), which are `null` when unknown, as in a run recovered from an older `.tsv`.
- **Parameters have their own block**, so a `metadataKey` may be any name: it can never overwrite a field of the run.

**Version 1**, every file written before, is flat and has no `schema_version`: `rat` for `animal`, the `task` fields and the parameters side by side at the top level, six `intan_*` fields for `recording`, and `derived` (rows under `trials`) for `trials`. It has no `cohort`, `box`, `date`, `run_of_day` or `started_at`.

- **Code reads and writes a field through `sessions/run_document.py`, never by key**: it alone knows where each field sits in either version, and `test_run_document.py` enforces it.
- **`analytics/reader.py` regroups a version-1 file into version 2 in memory** (`run_document.lifted`), so both score alike and keep their [hashes](TASKS.md#profile-and-params-hashes). No file is rewritten.
- **A `schema_version` above this build's is `unreadable`, with the reason**, never half-read; [Re-derive](#re-derive) skips it and Recover leaves it.

### The tsv log

```
# schema_version: 2                  ← header, written before the first strobe
# rat: remy1
# box: 2
# …                                  ← one line per field of run, task and recording
# params: {"num_trials":1000,…}      ← the parameters, one JSON line
# implant: {…}  # channels: […]      ← a recorded run only, one JSON line each
# task_profile: {…}                  ← snapshot, always the last header line
221	0
222	1000
# stop_reason: BF_END_SESSION received   ← footer, at finalization
# n_events: 2392
```

Written by `AnimalWriter.open_files` after the handshake and `SEED`. A field's line is named as version 1 named it (`rat`, `intan_path`), and a field with no value has no line. **A `.tsv` cut off mid-session lacks only the footer**, and its header makes a [recovered](#crash-recovery) run the document finalization would have written.

A header with no `schema_version` line is from before version 2: each parameter is a line of its own, and any line that is not a version-1 field is a parameter.

### The mat mirror

`sessions/matwriter.py` writes the same document with `scipy.io.savemat`. `run`, `task`, `params` and `recording` are structs (`S.run.box`, `S.params.reward_time_5`) whose numbers are `double`, bools `logical` and strings `char`; `ts_data` is `N×2` (`0×2` empty), `task_profile` a JSON char array, `odors` a struct array and `trials` a struct. A `null` run fact is `NaN` (`box`, `run_of_day`) or `''`. A version-1 document's fields are top-level variables by the same rules. `sessions/tests/test_matwriter.py` pins it.

> [!CAUTION]
> **scipy is preloaded on the main thread before any other thread starts** (`matwriter.preload`): importing numpy while a thread blocks on stdin deadlocks the frozen sidecar. **A `.mat` that would be wrong is refused** (non-BMP characters, `_` names) and logged; `.tsv` and `.json` carry the run.

### The embedded task profile

The snapshot makes a copied run decode anywhere with **the same `profile_hash`**, which requires `TaskProfile.to_json` to round-trip byte-for-byte through `parse_profile` (tested). It names which keys are parameters, so `params_hash` recomputes; its `strobes` map is the machine's whole [vocabulary](TASKS.md#strobe-vocabulary) at run start, outside the hash. Profile-less sketches write none.

### The odors table

One row per odor line a [trial type](TASKS.md#trial-types) presents: which odor, which well, how much (`analytics/stream/odors.py`).

```jsonc
"odors": [{"line": 1, "name": "GR-Sandalwood", "onset_code": 101, "side": "right",
           "reward_ms": 100, "pool_weight": 1}]
```

- Built from the run's own snapshot (its [`trialTypes`](TASKS.md#trial-types-in-the-profile)) and `params`, never from the stream, so a recovered or copied file has the same table.
- `line` is the number in the odor's onset strobe name, the trial table's `odor_line`; `side` is `left`, `right` or `no_go`; `reward_ms` is 0 for a no-go odor.
- A snapshot without `trialTypes` gives the rows its live metrics' success codes prove (`WATER_POKE_L`, `_R`, `_NONE`), with `reward_ms` and `pool_weight` null; one that proves none gives `[]`.
- `analytics/reader.py` adds the table, in memory, to a file that has none.
- In the `.mat`, `odors` is an **N×1 struct array** (`struct2table(S.odors)`, 0×1 when empty), nulls `NaN` or `''`.

<a id="the-derived-trial-table"></a>
### The trial table

[Stream-grammar-2](TASKS.md#stream-grammar) runs carry their trial table under `trials` (`grammar2.rows_of`, marked `"grammar": 2`; `sessions/derived.py`). It is what people and the lab's scripts read:

```jsonc
"trials": {"status": "ok", "detail": null, "interp": 1, "replay_version": 5, "grammar": 2, "phases": [],
           "rows": [{"index": 0, "odor_line": 1, "odor_name": "GR-Sandalwood", "side": "right",
                     "outcome_class": "correct", "correct": true, "reward_ms": 100, "odor_on_ms": 5300, "odor_on_s": null}]}
```

A grammar-2 row (`grammar2.TrialRow`) is one trial:

| Column | Meaning |
|---|---|
| `index`, `type_slot`, `side` | Its place in the run; its row of the task's table and the side that row rewards (`left`, `right`, `no_go`), from the trial's header |
| `odor_line`, `odor_name`, `sampled` | The odor delivered and its name in the [odors table](#the-odors-table); `''` and `sampled: false` when none was |
| `outcome`, `outcome_class`, `correct` | The outcome code's name, its class, and right or wrong; `correct` is null for a trial no accuracy counts (an abort) |
| `response`, `reaction_ms` | The well first poked; `ODOR_UNPOKE` to that poke |
| `reward_ms`, `reward_on_ms` | How long the valve was open, from its own strobes, never the parameter: 0 when no reward was given; when it opened |
| `repeat`, `correction` | The board will re-present this trial; this trial re-presents an error |
| `start_ms` … `end_ms` | Each event's time, ms from the run's first strobe |
| `start_s` … `end_s` | The same times on the recording's clock, in seconds |

> [!CAUTION]
> **The `*_s` columns are null until a recorded run is aligned**, which happens when its recording ends ([RECORDING.md](RECORDING.md#alignment-at-session-end)). All null means "not aligned", never "nothing happened".

- Columns are the dataclass fields (`grammar2.TrialRow`; `ReplayTrial` for a block with no `grammar`), checked as MATLAB identifiers by `test_derived_trials.py`.
- A grammar-1 run has no block, and neither does a run [another firmware interpreter recorded](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#why-a-run-has-no-numbers).
- `replay_version` (`trial_table.REPLAY_VERSION`) moves with any table change, pinned by `test_the_replay_version_pins_the_trial_table`.
- Written at finalization and recovery; rewritten only by [Re-derive](#re-derive), which keeps the `*_s` columns, and by alignment, which fills them.
- A version-1 file has the same block as `derived`, its rows under `trials`; Re-derive reads and rewrites it there.
- In the `.mat`, `rows` is an **N×1 struct array** (`struct2table(S.trials.rows)`; `S.derived.trials` in version 1).

> [!CAUTION]
> **Nulls are `NaN` (numbers) and `''` (strings) in the `.mat`, never `[]`**, or concatenating a column misaligns every later trial.

> [!IMPORTANT]
> **The app never reads the stored table**: `analytics/reader.py` drops it and Analytics decodes afresh.

## Crash safety

```mermaid
flowchart TD
    opened["Handshake resolved:<br/>.tsv opened exclusively, header written"] --> strobe["A strobe arrives"]
    strobe --> append["Append to .tsv,<br/>flush + fsync"]
    append -->|"run continues"| strobe
    append -->|"run ends: end strobe,<br/>End, or board drop"| footer["Footer appended:<br/>stop_reason, n_events"]
    footer --> built[".json and .mat built once<br/>from memory, best effort"]
    built -->|"write failed, e.g. disk full"| withFooter[".tsv with footer,<br/>no .json"]
    append -->|"app or power dies"| noFooter[".tsv with no footer,<br/>no .json"]
    withFooter -->|"Recover"| recover["sessions.recover rebuilds<br/>.json and .mat"]
    noFooter -->|"Recover"| recover
    recover --> reason["stop_reason: the footer's,<br/>else recovered after crash"]
```

### Written live

`AnimalWriter.record` appends each strobe exactly as sent and fsyncs every line. The file is opened **exclusively (`"x"`)**: a name collision refuses to start the box rather than truncate a log. A failed write is broadcast as `sidecar.error` for that box and the run continues.

### Built once at the end

`AnimalWriter.finalize` writes the footer, derives a grammar-2 run's [trial table](#the-trial-table), then builds `.json` and `.mat`. It is idempotent (first `stop_reason` wins), and the structured writes are best-effort: an `OSError` is logged, not raised. Each is atomic (`write_atomic`: a per-process, per-thread `.part`, fsync, rename), so a power cut leaves a `.part`, never a torn document.

`sweep_parts` removes stale parts once per process, at the first `settings.push`: only `<name>.<pid>-<thread>.part` files from another pid, older (mtime and ctime) than `PART_GRACE_S` before start, outside the backup directory.

### What is guaranteed

After a power loss, every strobe through the last complete line is in the `.tsv`; a dropped board finalizes as `board disconnected`. Resuming a round mid-run is not offered ([Continuing between rounds](#continuing-between-rounds)).

## Crash recovery

`sessions.recover` (`sessions/recovery.py`, the **Recover** button) rebuilds `.json` and `.mat` for each `.tsv` without a parseable `.json` (an unreadable one counts as present). It never talks to a board.

- It uses the archive walker (`walk_orphaned_tsvs`), so it reads every layout [adoption](#orphan-adoption) does and writes into the same one.
- It writes [version 2](#the-json-document) from any `.tsv`. A footer's `stop_reason` wins; otherwise `"recovered after crash"`. `n_events` is recounted; grammar-2 runs get their [table](#the-trial-table).
- Strobe lines must match `^\d{1,3}\t\d+$`, and **an unterminated last line is dropped**, so a torn line never reads as real. A torn `task_profile` line is dropped.
- **Pre-Ephymeris logs** (first line `LEGACY_HEADER`) allow a third name column and an unterminated last line, and record `"recovered from a legacy log"`; header-only ones are refused.
- Refused while a box runs; an [archive write](#the-cohort-archive). Recover then runs a rescan to adopt what it wrote.

## Re-derive

`sessions.rederive` re-derives every grammar-2 run in a cohort's folder and rewrites only the [trial table](#the-trial-table) (in the file's own version), in `.json` then `.mat`, where it differs from this build's; current files are not touched. Every other key is kept and the `.tsv` never opened. A block from a newer `replay_version` or a document of a newer `schema_version` is `skipped`, so an older build never undoes a newer one. A `.mat` is judged by content, not mtime, and its failure is reported apart (`matError`). Refused while a box runs.

## SQLite database

`ephymeris.db` lives in the **app data directory**, not `dataDirectory`. `cohorts/db.py` owns one connection behind a lock, used through [units of work](#transactions) via `asyncio.to_thread`; the version is `SCHEMA_VERSION`.

### Tables

Solid lines are foreign keys; dotted ones deliberately have none ([Indexes](#indexes)).

```mermaid
erDiagram
    cohorts ||--o{ animals : "cascade"
    cohorts ||--o{ former_animals : "cascade"
    cohorts ||--o{ sessions : "cascade"
    sessions ||--o{ session_animal_runs : "cascade"
    cohorts ||--o{ adopted_runs : "cascade"
    sessions ||--o{ session_notes : "cascade"
    cohorts ||--o{ session_notes : "cascade"
    sessions ||--o| session_logs : "cascade"
    prefixes |o..o{ sessions : "prefix_id"
    animals |o..o{ session_animal_runs : "animal_id"
    animals |o..o{ adopted_runs : "animal_id"
    animals |o..o{ electrode_impedances : "animal_id"
    animals |o..o| implants : "animal_id"
    animals |o..o{ animal_health : "animal_id"
    session_animal_runs |o..o| run_spike_counts : "run_id"
    session_animal_runs |o..o| run_site_quality : "run_id"
    task_profiles |o..o{ session_animal_runs : "profile_hash"
    session_animal_runs |o..o| run_metrics_cache : "run_id"
    adopted_runs |o..o| run_metrics_cache : "run_id"
    cohorts {
        TEXT id PK
        TEXT name
        TEXT data_folder
        TEXT created_at
        TEXT updated_at
        TEXT archived_at
        TEXT appearance_json
    }
    animals {
        TEXT id PK
        TEXT cohort_id FK
        TEXT name
        INTEGER box_number
        INTEGER cage
        TEXT sex
        TEXT id_number
        TEXT notes
    }
    former_animals {
        TEXT id PK
        TEXT cohort_id FK
        TEXT name
        INTEGER cage
        TEXT sex
        TEXT id_number
        TEXT notes
        TEXT removed_at
    }
    animal_moves {
        TEXT id PK
        TEXT source_cohort_id
        TEXT dest_cohort_id
        TEXT state
        TEXT plan_json
        TEXT created_at
        TEXT updated_at
        TEXT error
    }
    folder_moves {
        TEXT id PK
        TEXT cohort_id
        TEXT source
        TEXT target
        TEXT state
        TEXT created_at
        TEXT updated_at
        TEXT error
    }
    prefixes {
        TEXT id PK
        TEXT name "UNIQUE NOCASE"
    }
    sessions {
        TEXT id PK
        TEXT cohort_id FK
        TEXT prefix_id
        TEXT prefix_name
        TEXT session_number
        TEXT date
        TEXT started_at
        TEXT ended_at
        TEXT status
        TEXT folder_path
        TEXT rounds
        INTEGER duration_minutes
        TEXT recording_json
    }
    session_animal_runs {
        TEXT id PK
        TEXT session_id FK
        TEXT animal_id
        INTEGER box_number
        TEXT sketch_path
        TEXT file_path
        TEXT started_at
        TEXT ended_at
        TEXT stop_reason
        TEXT profile_hash
        TEXT config_json
        TEXT params_hash
        INTEGER interp
        TEXT channel_set_hash
        INTEGER diverged
    }
    machine_marks {
        TEXT name
        TEXT at
    }
    task_profiles {
        TEXT hash PK
        TEXT task_name
        TEXT kind
        TEXT profile_json
        TEXT first_seen_at
    }
    run_metrics_cache {
        TEXT run_id
        TEXT file_path
        INTEGER file_mtime_ns
        INTEGER file_size
        TEXT profile_hash
        TEXT profile_source
        TEXT scored_profile_hash
        TEXT params_hash
        TEXT config_json
        INTEGER codec_version
        TEXT computed_at
        TEXT status
        TEXT detail
        TEXT summary_json
    }
    adopted_runs {
        TEXT id PK
        TEXT cohort_id FK
        TEXT animal_id
        TEXT file_path
        TEXT prefix_name
        TEXT session_number
        TEXT date
        TEXT started_at
        TEXT sketch_name
        TEXT sketch_path
        TEXT adopted_at
        INTEGER file_mtime_ns
        INTEGER file_size
    }
    electrode_impedances {
        TEXT animal_id PK
        TEXT measured_at PK
        TEXT channel PK
        TEXT session_id
        INTEGER box_number
        REAL frequency_hz
        REAL ohms
        REAL phase_deg
        TEXT csv_file
    }
    implants {
        TEXT animal_id PK
        TEXT implant_json
        TEXT updated_at
    }
    run_spike_counts {
        TEXT run_id PK
        REAL counted_seconds
        REAL run_seconds
        TEXT threshold_json
        TEXT counts_json
    }
    run_site_quality {
        TEXT run_id PK
        TEXT measured_at
        REAL recorded_seconds
        TEXT edges_json
        TEXT sites_json
    }
    animal_health {
        TEXT animal_id PK
        TEXT date PK
        REAL weight_g
        INTEGER baseline
        TEXT recorded_at
        TEXT removed_at
    }
    session_notes {
        TEXT id PK
        TEXT session_id FK
        TEXT cohort_id FK
        TEXT at
        TEXT created_at
        TEXT edited_at
        TEXT deleted_at
        TEXT tag
        TEXT scope_kind
        TEXT animal_id
        INTEGER box_number
        TEXT body
        INTEGER carry_forward
        TEXT resolved_at
        TEXT resolved_in_session
    }
    session_logs {
        TEXT session_id PK
        TEXT operator
        TEXT summary
        TEXT updated_at
    }
    strobe_scan_cache {
        TEXT file_path
        INTEGER file_mtime_ns
        INTEGER file_size
        TEXT codes_json
    }
```

`task_profiles` is **content-addressed**, so comparability is an indexed equality. `run_metrics_cache` and `strobe_scan_cache` are pure caches keyed by file freshness; the former's `profile_hash` is what resolution reached and `scored_profile_hash` what scored the run ([why](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#which-profile-decodes-a-run)), and `codec_version` the [cache version](#caching). `adopted_runs` are files the walk matched, kept apart from `sessions` on purpose.

### Indexes

`INDEXES` is applied after migrations. Notable: `idx_cohorts_active_name` (partial unique name among active cohorts), `idx_runs_profile`/`idx_runs_params` (comparability), `idx_sessions_cohort_dt` (session order), `idx_adopted_file` (one adoption per file), `idx_notes_open_flags` (partial, open flags).

> [!CAUTION]
> **An index on `animal_id`, never a foreign key.** `cohorts.update` re-inserts every animal on each roster edit, so a cascade would wipe the cohort's history on a rename.

### Transactions

All callers share one connection, so writes that belong together go in **one unit of work**:

```python
with db.write() as tx:                 # the lock, then BEGIN IMMEDIATE
    digest = profiles.remember_profile(profile, tx=tx)
    sessions.record_animal_run(run, tx=tx)
# COMMIT here; ROLLBACK if the block raised
```

- A method given `tx=` joins and commits nothing; without it, it is its own unit. Nesting raises `NestedWrite`.
- **No transaction is ever open while the lock is free**; a unit finding one refuses (`WriteInProgress`). After SQLite rolls a unit back, later statements raise `TransactionAborted`.
- `db.read()` holds the lock with the connection `query_only`.
- A commit that changed a row fires the [backup hook](#the-database-copy); `tx.on_commit(fn)` runs after it.

A finalization records its profile and run in one unit; an indexing pass writes once at its end; a [tidy](#tidy-records) is one unit.

### Machine marks

`machine_marks` rows are permanent facts about this machine, read by `has_mark` before `connect` (an unreadable database answers "marked"). The one mark, `wiring_record`, says the start allowed to seed the wiring record has happened ([TASKS.md](TASKS.md#the-channel-set-and-the-pin-map)).

### Changing the schema

> [!CAUTION]
> **A new table** needs only `CREATE TABLE IF NOT EXISTS` in `SCHEMA`. **A new column** needs all three: bump `SCHEMA_VERSION`, update `SCHEMA`, **and** add a `MIGRATIONS` entry keyed by the version it upgrades to; otherwise existing databases claim the version without the column. **Removing** a table or column needs the same three, and a migration that carries what was recorded there first.

1. Make new columns nullable or constant-default; `add_column` is idempotent.
2. Migrations may re-key or repair a cache, never reinterpret data.
3. Add the version you are leaving to `tests/fixtures/schemas/` as `vN.sql`, copied from git; `cohorts/tests/test_migrations.py` upgrades each and compares it with a fresh database.

A database newer than the build still opens, with a loud error, and works as long as every change since was additive. v17 was not (it removed groups), so a build older than it fails on a v17 file's first roster query.

> [!CAUTION]
> **Dropping a table deletes the rows that cascade from it.** A column with a foreign key cannot be dropped in place, so its table is rebuilt without it first, and the referenced table dropped last (`_to_v17`).

## Backup mirroring

The `.tsv` protects against a crash; mirroring to `backupDirectory` (`backup/`) protects against losing the disk.

> [!IMPORTANT]
> **The backup target may be slow or dead, and that must never slow or fail a session.** Finalization only queues, and every copy runs in a worker thread.

```mermaid
flowchart TD
    started["A run's .tsv opens"] -->|"track"| live["Live .tsv set"]
    finalized["A run finalizes"] -->|"untrack, enqueue .tsv .json .mat"| queued["One-shot queue"]
    commit["Any SQLite commit"] -->|"mark dirty"| dirty["Database dirty"]
    queued --> pass["Mirror pass in worker threads,<br/>MIRROR_INTERVAL_S after the last one ended"]
    live --> pass
    dirty -->|"once DB_DEBOUNCE_S old"| pass
    pass -->|"whole-file copy, .part then replace"| target[("backupDirectory")]
    pass -->|"any copy failed"| failedState["backup.status failed,<br/>queued files re-queued"]
```

### Mirror layout

```
<backupDirectory>/<cohort folder basename>/    ← contents unchanged
<backupDirectory>/ephymeris.db
<backupDirectory>/db-snapshots/ephymeris_<YYYY-MM-DD>.db
```

Anchored on each **cohort folder**, not `dataDirectory`; clashing basenames get a suffix (`mirror_segments`). **Additive**: deletions are never mirrored.

### Session files

`.json`, `.mat` and rewritten `notes.md` are queued; a live `.tsv` is copied every `MIRROR_INTERVAL_S` (10 s). Every copy is whole-file via `.part`.

### The database copy

Mirrored after any committed change, debounced `DB_DEBOUNCE_S` (5 s): SQLite's online backup to a local temp file under the lock, then an unlocked copy. It never runs with a write open; if one is (a bug), it defers as `WriteInProgress` and is reported [deferred](#failures). One dated snapshot per day, **first of day wins**, newest `DB_SNAPSHOT_KEEP` kept.

### No automatic backfill

A new backup directory mirrors from then on; `backup.syncNow` copies whatever is missing or stale.

### Failures

Failures show as `state: "failed"` on `backup.status` (Settings, Mission Control), never as toasts, and clear on the next success; a deferred database copy shows `deferred`. **A failed mirror never affects the session.**

## Reading the archive

`analytics/` reads runs back ([map](../sidecar/ephymeris_sidecar/analytics/ANALYTICS.md#the-folder-at-a-glance)): `reader.py` reads files, `walk.py` walks and matches, `archive.py` holds the archive, `scoring.py` and `repository.py` the cache.

### Database first

Run records are the primary source. Files no record names are found only by `analytics.rescan`, and adopted runs never get `sessions` rows: summaries group them under synthetic `adopted:<prefix>_<number>_<date>` sessions.

### The cohort archive

`CohortArchive` (`analytics/archive.py`) is the one read of a cohort's recorded and recovered runs, used by summaries, `sessions.list`, [what changed](#what-changed), [tidy](#tidy-records) and the Dashboard. A recovered run counts under the recorded session owning its folder (`_adoption_owners`), and is dropped when a run record has its path.

**Every archive write** (rescan, tidy, [recover](#crash-recovery), [re-derive](#re-derive), [relocate](#data-folder), [move](#moving-animals-between-cohorts)) goes through `CohortArchive.write` under the archive lock (`ArchiveBusy` otherwise), and asks the rig only once the lock is held. Rescan, Recover and Re-derive are refused while a box runs (`RIG_IN_USE`); relocate and move also while a session is set up; tidy skips the held session. A box runs until its record is committed (`SessionLifecycle.writing`). Afterwards `on_changed` queues backups and publishes updates.

> [!CAUTION]
> **The walk finds format folders by name at any depth**, and a file is data only if it sits **directly inside** one. Never assume a prefix level.

### Orphan adoption

An `adopted_runs` row holds only what a name gives: animal, path, prefix, number, date and start. **Box, stop reason and end stay unknown** (`boxNumber: null`). This is how pre-Ephymeris archives reach Analytics: both format-folder spellings (`reader.FORMAT_DIRS`), `MM_DD_YY` dates, any nesting, [odd names](#reading-names-other-software-wrote), labels resolved by `legacyNames` ([TASKS.md](TASKS.md#task-definitions)), and AppleDouble files skipped.

- **Animal:** the document's `rat`, else the file stem's animal token if the stem has exactly the [Names](#names) shape, else a `removed` [former member](#former-members) of that name.
- **Duplicates are one run** by case-folded stem (`reader.run_identity`); the kept copy is chosen by content (`_prefer`).
- **A missing data folder is reported** (`folderMissing`), never read as empty.
- **Date:** the session folder's, else the file stem's, so a renamed folder's runs still land on the date axis.

> [!WARNING]
> **The adopted run id is keyed on cohort and run identity, never path** (`_orphan_run_id`), and a stored run keeps its id, since rulings and the cache use it.

### Set-aside folders

A folder whose name starts with `_` or `.` (or is `__MACOSX`) is **never walked** (`reader.is_set_aside_dir`): not by adoption, crash recovery or the recent-sessions list. Prefix a folder with `_` to keep it beside the data without it being read, such as a backup copied before a fix (`_backup_8O-Bdisc_23_before_…`). Read as an orphan, such a copy became a session with no date, counting each of its runs a second time. A Rescan also **prunes** adoptions already taken from a set-aside folder (`reader.is_set_aside`).

### Caching

**Summaries persist** in `run_metrics_cache`; series and trial tables never do. The key (`repository.CacheKey`: path, mtime, size, profile hash, version) needs no file open, so a hit reads nothing. The version (`scoring.current_version`) combines `SCORE_VERSION`, a **canary** hash of the scoring code's answers for fixed runs (`scoring._canary_runs`), and this machine's [strobe vocabulary](TASKS.md#strobe-vocabulary).

> [!CAUTION]
> **A hit is served verbatim.** If you change scoring and the pinned canary in `analytics/tests/test_analytics_scoring.py` does not fail, add a canary case or bump `SCORE_VERSION`. Changes to file reading (`reader.stat_run`, `reader.parse_run`), `missing`/`unreadable` rows or reason texts always need the bump.

> [!CAUTION]
> **A relocate or move carries a key only if it was fresh for the original** (`cohorts/freshness.py`). A dropped fresh key re-matches adoptions by name (a renamed animal's runs go astray); a carried stale one vouches for content that changed.

A vanished file never deletes its row on the read path; only [pruning](#pruning) does. A corrupt file caches `unreadable`. `lowConfidence` is applied per request.

### Never at the expense of a session

> [!IMPORTANT]
> **No analytics operation may slow, stall or fail a running session.** One indexing job at a time; reads sequential in one worker, in chunks (`INDEX_CHUNK`); cache writes one transaction per job.

### Pruning

A rescan (unless `adoptOrphans: false`) also deletes records (with their [spike counts](RECORDING.md#active-site-yield)), adoptions and their cache rows whose file is gone, then sessions with no folder, no runs **and** no [log entry](#the-session-log). Records only; never open sessions.

> [!CAUTION]
> **Absence counts only when the storage is reachable**: a path is gone only if some ancestor is readable (`_storage_is_reachable`). A `.json` whose `.tsv` survives is kept for [recovery](#crash-recovery).

### Carrying adoptions forward

A rescan skips a file (`_carry_over`) when its adopted row names **the same path** with the same mtime and size. The path condition is load-bearing: every other copy must still be read for `_prefer` to judge.

### Tidy records

**Tidy records** (`sessions.tidy`) previews, then merges records sharing prefix, number and date into the earliest holding data, and deletes empty ones (no run, file or [log entry](#the-session-log)). Notes and flags follow a merge.

> [!IMPORTANT]
> **Only the database changes**; empty folders go by `rmdir`, never `rmtree`. Held, today's `configuring` and unreachable records are left alone.

## Analytics views

`/analytics` (`features/analytics/Analytics.tsx`, `features/analytics/`, `src/features/analytics/view.ts`). Selecting a session **narrows** every panel; per-animal colour ties them. Rescan, Recover, Re-derive and Tidy are explicit header actions.

> [!CAUTION]
> **The task strip and accuracy trend share x slots** (`sessionOutcomePoints`); anything between them misaligns every boundary.

### Pooling across tasks

No task filter: outcome tallies mean the same on every task, so trends pool every run and **disclose** the task in the task strip. Accuracy draws response and rewarded accuracy pooled by **summed trials**. The session summary lists every animal that ran; an unscorable run shows its reason, never zeroes.

> [!CAUTION]
> **The effort total is the trial light (`presented`)**, not odor onset, so an ignored session reads hollow, not short.

### Session order

> [!CAUTION]
> **Order sessions by the sidecar's `ordinal` (`date`, `started_at`)**, never by `session_number` or names as strings ([why](#why-the-date-is-hyphenated)).

### Strategy plane

One point per run, x and y the accuracy at each well; the anti-diagonal `x + y ≈ 1` is pure side bias.

> [!IMPORTANT]
> **The axes are sides, not conditions** (`stream.strategy_axes`, `view.sideAccuracy`). A condition's side comes only from its own `successCode` (`answer_side_of`); a profile without two opposing answers is listed disabled with its reason.

Across sessions the axes are left and right wells (`SIDE_AXES`); within a session, rolling figures on a counted-trial clock computed sidecar-side (`strategy_trail`).

<img src="images/strategy-space.webp" alt="The Strategy space: one point per animal per session between the corners discriminating, chance, side bias and reversed, its axes labelled right well (up) and left well (right)" width="480">

### Learning curves

Session scope only: rolling P(hit) per counted trial for one condition.

> [!IMPORTANT]
> **The x axis is trial index, never time**: each animal's `timestamp_ms` starts at its own run.

### Colour palette

Animals take `--color-series-1`…`6` by roster position; rates use the diverging `view.HEAT_BINS`.

> [!CAUTION]
> **Don't even out the series ramp's lightness**: it is what keeps it colour-blind safe.

### Drawing lines

> [!WARNING]
> **Lines draw on by wiping (`components/charts/DrawOn.tsx`), never `pathLength`**, which breaks under `non-scaling-stroke`.

### Exporting a sheet

**Export PNG** mounts the existing panels (`features/analytics/report/`) off-screen with a masthead and `summary.warnings` ([export card](ARCHITECTURE.md#export-progress)).

> [!CAUTION]
> Render off-screen (not hidden), force `useRevealOnView` true, use `MotionConfig skipAnimations`, unpin the pinned animal, rasterize at 1×, and turn scrolling off; each mistake yields a plausible wrong picture.

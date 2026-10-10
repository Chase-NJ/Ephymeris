"""The wire schema — the single source of truth for every command, event,
error code and payload shape on the WebSocket between frontend and sidecar.

Everything else is generated from this file: the two code mirrors
(`sidecar/ephymeris_sidecar/protocol.py`, `src/lib/ws/protocol.ts`) and the
human-readable reference `docs/PROTOCOL.md`. Every `doc=` here is rendered into
that reference, so a command's behaviour, refusals and reasons belong in its
`doc=`. The rules that govern the wire (connection lifecycle, the envelope,
replay on connect, box numbers rather than ports) are in
`docs/ARCHITECTURE.md#wire-protocol`.

To change the wire:
    1. Edit this file.
    2. Run `npm run gen:protocol` (or `python protocol/generate.py`).
    3. Commit the regenerated mirrors and reference with your change —
       `sidecar/tests/test_protocol_contract.py` fails if they are stale, or if
       a command, event or error code has no `doc=`.

Shape conventions, matching what the sidecar actually emits:
  - `optional` (key may be absent) is distinct from `nullable` (key present,
    value may be null). The validator enforces the difference.
  - Timestamps are ISO-8601 strings; `ts` on the envelope is float seconds.
  - `box` is always a box number 1–6, never a port address
    (`docs/ARCHITECTURE.md#wire-protocol`).
"""

from __future__ import annotations

from wire_dsl import (
    ANY,
    BOOL,
    Command,
    ErrorCode,
    Event,
    FLOAT,
    INT,
    ListOf,
    MapOf,
    NULL,
    Obj,
    Protocol,
    Ref,
    STR,
    Shape,
    f,
    lit,
    nullable,
    obj,
    union,
)

VERSION = 1

#: A bound/step on a numeric config field, which may be int- or float-typed.
NUMBER = union(INT, FLOAT)


# --- Named payload shapes --------------------------------------------------

SHAPES = (
    # Hardware / discovery
    Shape(
        "PortStateName",
        lit("IDLE", "PASSTHROUGH", "FLASHING", "RESETTING", "IN_SESSION", "ERROR"),
        doc="Per-port state machine names (`ARCHITECTURE.md#port-state-machine`). One owner at a "
        "time: FLASHING, RESETTING and IN_SESSION are each exclusive, and the "
        "first two force-release PASSTHROUGH and auto-resume it afterward.",
    ),
    Shape(
        "OutputLine",
        obj(
            f("dir", lit("rx", "tx"), doc="Sent commands interleave as `tx`, so scrollback stays chronological."),
            f("text", STR),
            f("ts", FLOAT),
        ),
        doc="One passthrough console line. Debug output, never persisted beyond "
        "the sidecar's capped in-memory ring buffer.",
    ),
    Shape(
        "DetectedBoard",
        obj(
            f("hardwareId", STR),
            f("address", STR),
            f("fqbn", nullable(STR)),
            f("boxId", nullable(INT), doc="`null` for a board no box is bound to."),
        ),
        doc="A board the out-of-band `arduino-cli board list` poll has seen.",
    ),
    Shape(
        "LibraryState",
        lit("ok", "empty", "damaged"),
        doc="The three bundled-sketch-library states (`TASKS.md#sketch-library`). There is "
        "no `not_configured`: sketches ship with the app, so there is nothing to "
        "configure and no first-run state to be in.",
    ),
    Shape(
        "SketchLibraryStatus",
        obj(
            f("state", Ref("LibraryState")),
            f("path", nullable(STR)),
            f("message", nullable(STR), doc='Populated when state != "ok".'),
            f(
                "source",
                lit("bundled", "override"),
                doc="`override` when $EPHYMERIS_SKETCH_LIBRARY points elsewhere — a "
                "developer facility, never reachable from the UI.",
            ),
        ),
        doc="Every non-ok state means a broken or partial INSTALL rather than a "
        "wrong setting, which is why the messages point at reinstalling and not "
        "at a picker.",
    ),
    Shape(
        "SketchEntry",
        obj(f("category", STR), f("name", STR), f("path", STR)),
    ),
    Shape(
        "SkippedEntry",
        obj(f("path", STR), f("reason", STR)),
        doc="Carried in full so a missing sketch is inspectable, not silent.",
    ),
    Shape(
        "SketchDiscovery",
        obj(
            f("library", Ref("SketchLibraryStatus")),
            f("sketches", ListOf(Ref("SketchEntry"))),
            f("skipped", ListOf(Ref("SkippedEntry"))),
            f("skippedCount", INT, doc='Drives the "Partial" note (`TASKS.md#sketch-library`).'),
            f("libraries", ListOf(STR)),
            f("librariesPath", nullable(STR)),
        ),
        doc="The full result of a library scan (`TASKS.md#sketch-library`): the "
        "bundled sketches plus this rig's saved task profiles.",
    ),
    # Settings (pushed Tauri → sidecar; the shell owns them — ARCHITECTURE.md#settings)
    Shape(
        "BoxBinding",
        obj(
            f("box", INT),
            f("hardwareId", nullable(STR), doc="USB serial number — stable across COM renumbering."),
            f("label", STR),
            f(
                "intanDigitalIn",
                nullable(INT),
                optional=True,
                doc="Which of the recording controller's digital inputs this box's "
                "sync line is wired to, 1–16 (`RECORDING.md#the-sync-line`). Null = the box is "
                "not wired for recording. A binding like `hardwareId`, and for the "
                "same reason a setting rather than part of the rig document: it "
                "describes a cable between two instruments, not the box.",
            ),
        ),
    ),
    Shape(
        "IntanSettings",
        obj(
            f("commandPort", INT),
            f("waveformPort", INT),
            f("spikePort", INT),
        ),
        doc="Where Intan RHX's three TCP servers listen. The host is not a "
        "setting: Ephymeris only ever talks to an RHX on this machine.",
    ),
    Shape(
        "EphymerisSettings",
        obj(
            f("dataDirectory", nullable(STR)),
            f("backupDirectory", nullable(STR)),
            f("arduinoCliPath", nullable(STR)),
            f("defaultBaud", INT),
            f("boxes", ListOf(Ref("BoxBinding"))),
            f(
                "intan",
                Ref("IntanSettings"),
                optional=True,
                doc="May be absent; both ends then fall back to RHX's default "
                "ports (5000/5001/5002).",
            ),
            f(
                "recordingDefaults",
                MapOf(ANY),
                optional=True,
                doc="The last recording setup the operator confirmed, offered as "
                "the next one's starting point. Shell-only.",
            ),
            f("reducedMotion", BOOL),
            f(
                "constellation",
                nullable(STR),
                doc="Zodiac layout id for the box-status constellation; null = "
                "the fixed default layout. Shell-only — the sidecar ignores it.",
            ),
            f(
                "constellationSlots",
                MapOf(INT),
                doc="Box number (string key, JSON) → star index in the chosen "
                "constellation. Shell-only.",
            ),
            f(
                "taskDefaults",
                MapOf(MapOf(ANY)),
                doc="Sketch folder name → this rig's default task parameters for "
                "it, keyed by `metadataKey` — the middle layer of the "
                "three-layer merge (`TASKS.md#the-start-line`). Keyed by NAME, "
                "not path, because the name is what the session file records. "
                "Shell-only — the frontend merges these under the profile's own "
                "defaults and sends the result as each box's `config` at "
                "`sessions.confirmMapping`, so there is exactly one place a "
                "value can enter a `START` line and the sidecar never reads "
                "these.",
            ),
        ),
        doc="The Tauri-side store's schema; the store is the source of truth "
        "(`ARCHITECTURE.md#settings`). The sidecar reads `dataDirectory`, "
        "`backupDirectory`, `arduinoCliPath`, "
        "`defaultBaud`, `boxes` and `intan`, and ignores the rest — including "
        "keys a stale store still carries — so adding a setting the sidecar "
        "doesn't consume is deliberately a non-event.",
    ),
    # Hardware utility baseline (ARCHITECTURE.md#hardware-utility-baseline)
    Shape(
        "UtilityBaselineState",
        lit("unknown", "restoring", "ready", "busy", "held", "pinned", "unavailable", "failed"),
        doc="What the sidecar believes about one box's baseline firmware. "
        "`busy` (the port has another owner), `held` (a confirmed session "
        "mapping owns the rig) and `pinned` (the operator flashed another "
        "sketch here from Debug Mode, and it stays until they ask for the "
        "baseline back) are all 'not now' rather than 'not working' — "
        "the distinction is the whole reason a restore never fights the user. "
        "Only `failed` is a fault. A pin holds through every AUTOMATIC "
        "restore trigger and is released by any `utility.ensure` naming the "
        "box, a session releasing the rig, the board vanishing, a changed "
        "utility sketch, or flashing the utility sketch by hand.",
    ),
    Shape(
        "UtilityBoxState",
        obj(
            f("box", INT),
            f("state", Ref("UtilityBaselineState")),
            f("detail", nullable(STR), doc="Why, when the state isn't `ready`."),
            f("identifying", BOOL, doc="This box is currently lit by utility.identify."),
        ),
    ),
    Shape(
        "UtilityStatus",
        obj(
            f(
                "configured",
                BOOL,
                doc="The install's library has a box utility. Not a setting: the "
                "app finds it (`TASKS.md#the-box-utility`).",
            ),
            f(
                "sketchPath",
                nullable(STR),
                doc="Where the copy rebuilt for this rig lives — an "
                "install-specific fact, informational only.",
            ),
            f("sketchName", nullable(STR), doc="The box utility's folder name."),
            f(
                "canIdentify",
                BOOL,
                doc="The utility's profile declares an `identify` pair (generated on "
                "the rig's first cue). "
                "False means placement can still run, just without lights.",
            ),
            f(
                "held",
                BOOL,
                doc="Restores are suspended because a confirmed session mapping "
                "owns the boxes — reflashing then would erase the task sketch.",
            ),
            f(
                "message",
                nullable(STR),
                doc="Why the baseline isn't operating at all (no sketch set, a "
                "name not in the bundled library, a non-utility profile).",
            ),
            f("boxes", ListOf(Ref("UtilityBoxState"))),
        ),
        doc="The whole baseline picture — one snapshot, shared by the command "
        "and the event, so a client never merges two shapes.",
    ),
    # Backup Directory mirroring (DATA.md#backup-mirroring)
    Shape(
        "BackupState",
        lit("disabled", "pending", "ok", "failed"),
        doc='`pending` = directory set but no pass has completed yet, distinct '
        "from `ok` (a pass succeeded) and `failed` (the last pass didn't) — a "
        "freshly set, unreachable network path must not read as healthy "
        "before its first pass.",
    ),
    Shape(
        "BackupStatus",
        obj(
            f("configured", BOOL),
            f("directory", nullable(STR)),
            f("state", Ref("BackupState")),
            f("pending", INT, doc="Finalized files queued for their one-shot copy."),
            f("tracking", INT, doc="Live .tsv files mirrored each pass."),
            f("mirroredFiles", INT, doc="Copies made this sidecar lifetime."),
            f("lastSuccessAt", nullable(STR)),
            f("lastError", nullable(STR)),
            f("syncing", BOOL, doc="A backup.syncNow walk is running."),
            f("intervalSeconds", FLOAT),
        ),
    ),
    Shape(
        "SyncResult",
        obj(
            f("copied", INT),
            f("skipped", INT, doc="Already current — not an error."),
            f("failed", INT),
            f("errors", ListOf(STR)),
            f("directory", STR),
        ),
    ),
    # Cohorts (DATA.md#cohorts-animals-and-groups)
    Shape("Sex", lit("M", "F", "unknown")),
    Shape(
        "Group",
        obj(
            f("id", STR),
            f("name", STR),
            f(
                "order",
                INT,
                doc="Display order of the cohort's groups. Not a run order: "
                "any group may run at any time, and more than once.",
            ),
        ),
    ),
    Shape(
        "Animal",
        obj(
            f("id", STR),
            f("name", STR),
            f("groupId", STR, doc="Exactly one group."),
            f("boxNumber", nullable(INT), doc="Abstract slot 1–6, never a live port."),
            f(
                "cage",
                nullable(INT),
                doc="Home-cage number — cagemates share one. A grouping label "
                "validated as ≥ 1 and nothing else; null means unassigned.",
            ),
            f("sex", nullable(Ref("Sex"))),
            f("idNumber", nullable(STR)),
            f("notes", nullable(STR)),
        ),
    ),
    Shape(
        "CohortAppearance",
        obj(
            f(
                "type",
                STR,
                doc="`rocky` | `gas` | `ice` | `ocean` | `lava`. Selects which "
                "surface the planet shader draws; unknown values fall back to "
                "`rocky` rather than rendering nothing.",
            ),
            f("hue", NUMBER, doc="0–360. Rotates the palette, nothing else."),
            f("ring", BOOL),
            f(
                "seed",
                NUMBER,
                doc="Shifts the noise field and only that — a re-roll changes "
                "the world's weather, never its type, hue or size.",
            ),
        ),
        doc="How a cohort's world looks (`ARCHITECTURE.md#frontend`). **Null is the normal "
        "state**: an untouched cohort derives every field from a hash of its "
        "`id`, so it already has a stable, distinct planet and the column that "
        "stores this carries no data for it.",
    ),
    Shape(
        "Cohort",
        obj(
            f("id", STR),
            f("name", STR),
            f(
                "dataFolder",
                STR,
                doc="Resolved once at creation and persisted verbatim; renaming the "
                "cohort never moves it (`DATA.md#cohorts-animals-and-groups`).",
            ),
            f("animals", ListOf(Ref("Animal")), doc="The roster: active members only."),
            f("groups", ListOf(Ref("Group")), doc="Always ≥ 1 — a default group always exists."),
            f("archivedAt", nullable(STR)),
            f("createdAt", STR),
            f("updatedAt", STR),
            f(
                "appearance",
                nullable(Ref("CohortAppearance")),
                doc="Null until the operator tunes it, and null is not a gap: "
                "the whole record is derived from `id` when absent.",
            ),
            f(
                "formerAnimals",
                ListOf(Ref("FormerAnimal")),
                doc="Animals with history in this cohort that are no longer on "
                "its roster (`DATA.md#former-members`). Never posted back: a "
                "former member is restored by posting its id in `animals`.",
            ),
        ),
        doc="The full record, fetched only when a cohort is opened.",
    ),
    Shape(
        "FormerAnimal",
        obj(
            f("id", STR),
            f(
                "name",
                nullable(STR),
                doc="Null only for an id named by notes alone, with no file to "
                "read a name from.",
            ),
            f(
                "source",
                lit("removed", "files"),
                doc="`removed`: taken off the roster and kept. `files`: an id "
                "this cohort's history names with no row anywhere — a removal "
                "from before former members were kept — named from its files' "
                "stems at read time and never stored.",
            ),
            f("removedAt", nullable(STR), doc="Null for `files`: nothing recorded when."),
            f("runCount", INT, doc="Recorded plus adopted runs this cohort holds for it."),
            f("sex", nullable(Ref("Sex"))),
            f("idNumber", nullable(STR)),
            f("cage", nullable(INT)),
            f("notes", nullable(STR)),
            f(
                "groupName",
                nullable(STR),
                doc="The group it was in, by name — groups are rewritten on "
                "every roster edit, so an id would not survive.",
            ),
        ),
        doc="An animal with history in a cohort but no place on its roster "
        "(`DATA.md#former-members`).",
    ),
    Shape(
        "CohortSummary",
        obj(
            f("id", STR),
            f("name", STR),
            f("animalCount", INT),
            f("groupCount", INT),
            f(
                "assignedBoxes",
                ListOf(INT),
                doc="Distinct box numbers this cohort's animals hold. Animal "
                "detail the summary carries so the browser can flag a cohort "
                "whose boxes no longer exist on this machine without fetching "
                "every cohort in full.",
            ),
            f(
                "cageCount",
                INT,
                doc="Distinct home cages, and the second piece of animal detail "
                "the summary carries, on the same argument: the cohort browser "
                "draws one orbiting ship per cage, and deriving that from the "
                "roster would cost a full `cohorts.get` per planet on every "
                "route mount. A count, not the numbers — which animals share a "
                "cage is the editor's business.",
            ),
            f("archived", BOOL),
            f("createdAt", STR),
            f("updatedAt", STR),
            f("appearance", nullable(Ref("CohortAppearance"))),
        ),
        doc="Enough for the cohort browser and the dashboard tile, no "
        "per-animal detail.",
    ),
    Shape(
        "CohortPatch",
        obj(
            f("name", STR, optional=True),
            f("animals", ListOf(Ref("Animal")), optional=True, doc="Replaced wholesale."),
            f("groups", ListOf(Ref("Group")), optional=True, doc="Replaced wholesale."),
            f(
                "appearance",
                nullable(Ref("CohortAppearance")),
                optional=True,
                doc="Replaced wholesale. Explicit null resets the world to the "
                "one derived from the cohort's id.",
            ),
        ),
    ),
    Shape(
        "ProposedAnimal",
        obj(f("animalId", STR), f("boxNumber", INT)),
    ),
    Shape(
        "ProposedGroup",
        obj(f("name", STR), f("order", INT), f("animals", ListOf(Ref("ProposedAnimal")))),
    ),
    Shape(
        "GroupRejection",
        obj(
            f("reason", STR),
            f("minimumGroups", INT, doc="The minimum viable count, so the user can accept it."),
        ),
    ),
    Shape(
        "GroupProposal",
        obj(
            f("groups", ListOf(Ref("ProposedGroup"))),
            f(
                "rejected",
                nullable(Ref("GroupRejection")),
                doc="Set when the request would break the six-animals-per-group "
                "hard constraint (one box each). Guidance rather than a failure, "
                "so not an error reply: `minimumGroups` is the smallest viable "
                "count, which the user can accept.",
            ),
        ),
        doc="An Auto-Balance preview. Nothing is written; apply via cohorts.update.",
    ),
    # Prefixes, sessions, Task Profiles (DATA.md#sessions-and-runs)
    Shape("Prefix", obj(f("id", STR), f("name", STR)), doc="Global — shared across cohorts."),
    Shape("SessionStatus", lit("configuring", "running", "completed", "aborted")),
    Shape(
        "GroupRun",
        obj(
            f("groupId", STR),
            f(
                "order",
                INT,
                doc="0-based position in the session's run sequence. A group "
                "may appear more than once.",
            ),
            f("startedAt", STR),
            f("endedAt", nullable(STR)),
        ),
    ),
    Shape(
        "Session",
        obj(
            f("id", STR),
            f("cohortId", STR),
            f("prefixId", STR),
            f("prefixName", STR),
            f("sessionNumber", STR, doc="Free text, not strictly numeric — never sort by it."),
            f("date", STR, doc="ISO `YYYY-MM-DD`."),
            f("startedAt", STR),
            f("endedAt", nullable(STR)),
            f(
                "clockStartedAt",
                STR,
                doc="When the session actually began running: the first group "
                "run's start, or `startedAt` before any group ran "
                "(`DATA.md#the-session-clock`). `startedAt` is when Step 1 "
                "created the record. Elapsed time and note offsets count from this.",
            ),
            f(
                "clockEndedAt",
                nullable(STR),
                doc="The last group run's end once every run is closed, else "
                "`endedAt`; null while the session is open. For a session "
                "recovered from files, the latest run's start plus its stream's "
                "span, once the index has read the files "
                "(`DATA.md#the-session-clock`) — derived, so shown as `~`.",
            ),
            f("status", Ref("SessionStatus")),
            f("folderPath", STR),
            f("groupRuns", ListOf(Ref("GroupRun"))),
            f(
                "durationMinutes",
                nullable(INT),
                doc="Per-box time limit: the sidecar sends STOP to a box this "
                "many minutes after that box's own start. Null means no limit.",
            ),
            f(
                "recording",
                nullable(Ref("SessionRecording")),
                doc="Set when the session is also an Intan recording "
                "(`RECORDING.md#what-is-written`): one entry per group run "
                "recorded. Null = behavior only.",
            ),
        ),
    ),
    Shape("ConfigFieldType", lit("int", "float", "bool", "string")),
    Shape(
        "ConfigField",
        obj(
            f("metadataKey", STR, doc="The `.json`/`.mat` field name the form collects under."),
            f("wireKey", STR, doc="The `START` command token (`TASKS.md#the-start-line`)."),
            f("label", STR),
            f("type", Ref("ConfigFieldType")),
            f("default", ANY),
            f(
                "group",
                STR,
                optional=True,
                doc="Section heading the form files this field under; absent = "
                "ungrouped. Part of `profile_hash`, so re-filing a field splits "
                "a task's recorded runs from its future ones "
                "(`TASKS.md#profile-and-params-hashes`).",
            ),
            f("unit", STR, optional=True, doc='Suffix shown after the input, e.g. "ms".'),
            f("min", NUMBER, optional=True, doc="Inclusive bound the form clamps to."),
            f("max", NUMBER, optional=True, doc="Inclusive bound the form clamps to."),
            f("step", NUMBER, optional=True, doc="Stepper increment; presentation only."),
            f("help", STR, optional=True, doc="One-line explanation shown with the field."),
            f(
                "advanced",
                BOOL,
                optional=True,
                doc="Collapsed behind a disclosure by default. For fields a "
                "session should rarely need to touch.",
            ),
        ),
        doc="One operator-tunable parameter. Everything past `default` is "
        "optional presentation metadata, so a three-field profile and a "
        "forty-field one share one code path.",
    ),
    Shape(
        "LiveMetric",
        obj(
            f("id", STR),
            f("label", STR),
            f("triggerCode", INT),
            f("successCode", INT),
            f("alternateCode", INT),
            f("windowSize", INT),
        ),
    ),
    Shape(
        "ProfileKind",
        lit("behavior", "utility"),
        doc="A scored IN_SESSION task, or a PASSTHROUGH tool (`TASKS.md#task-profile`). "
        "A behavior profile uses `config`/`strobes`/`liveMetrics`; a utility "
        "profile uses `controls`/`telemetry`/`identify`.",
    ),
    Shape("ControlOption", obj(f("label", STR), f("command", STR))),
    Shape(
        "ControlChannel",
        obj(
            f("label", STR),
            f(
                "state",
                STR,
                optional=True,
                doc="Telemetry key whose 0/1 value lights this row's indicator.",
            ),
            f("toggle", STR, optional=True, doc="Command that latches this channel."),
            f("pulse", STR, optional=True, doc="Command that pulses this channel."),
            f(
                "kind",
                STR,
                optional=True,
                doc="The rig channel kind behind the row (`emitter`, `reward`, `cue`, "
                "`vacuum`). Always set by a generated utility profile.",
            ),
        ),
        doc="One row of a `grid` control — a named piece of hardware with its "
        "own commands and its own live state key.",
    ),
    Shape(
        "Control",
        obj(
            f("id", STR),
            f("label", STR),
            f("type", lit("button", "select", "grid")),
            f("command", STR, optional=True, doc="`button` controls only."),
            f("options", ListOf(Ref("ControlOption")), optional=True, doc="`select` controls only."),
            f(
                "channels",
                ListOf(Ref("ControlChannel")),
                optional=True,
                doc="`grid` controls only — one row per channel. Exists because a "
                "box has 18 controllable outputs, and 36 flat buttons is not a "
                "control surface.",
            ),
        ),
        doc="A utility control rendered in Debug Mode (`TASKS.md#task-profile`). "
        "Sends over `port.send` — no command of its own.",
    ),
    Shape("TelemetryField", obj(f("key", STR), f("label", STR))),
    Shape(
        "TelemetrySpec",
        obj(f("match", STR), f("fields", ListOf(Ref("TelemetryField")))),
        doc="How to parse a utility sketch's non-persisted STATUS lines out of "
        "`port.output` (`TASKS.md#task-profile`). Parsed client-side — nothing "
        "here is stored.",
    ),
    Shape(
        "IdentifySpec",
        obj(f("on", STR), f("off", STR)),
        doc="The two commands that make a box announce itself — a trial light, "
        "a buzzer, whatever the rig has (`ARCHITECTURE.md#hardware-utility-baseline`). "
        "Declared by the sketch so the app never has to know that a Hart-lab "
        "box says `ON trial_light`.",
    ),
    Shape(
        "TaskProfile",
        obj(
            f("taskName", STR),
            f("kind", Ref("ProfileKind")),
            f("config", ListOf(Ref("ConfigField"))),
            f(
                "strobes",
                MapOf(STR),
                doc="code → name, string-keyed to match the authored task.json. "
                "Display/debug only — metrics use raw codes.",
            ),
            f("liveMetrics", ListOf(Ref("LiveMetric"))),
            f("controls", ListOf(Ref("Control")), doc="Utility profiles only."),
            f(
                "legacyNames",
                ListOf(STR),
                doc="Names older software wrote for this same task, so the archive "
                "walk can decode historical runs (`TASKS.md#task-profile`). Declared, "
                "never inferred.",
            ),
            f("telemetry", Ref("TelemetrySpec"), optional=True, doc="Utility profiles only."),
            f(
                "identify",
                Ref("IdentifySpec"),
                optional=True,
                doc="Utility profiles only — absent means this sketch can't be "
                "asked to point at its own box, which the placement walk "
                "degrades around rather than refusing.",
            ),
        ),
        doc="Parsed from the sketch's `task.json` sibling "
        "(`TASKS.md#task-profile`); passed through verbatim — the sidecar "
        "validates shape but doesn't reinterpret.",
    ),
    Shape(
        "SessionBoxMapping",
        obj(
            f("box", INT),
            f("animalId", STR),
            f("sketchPath", STR),
            f("config", MapOf(ANY), doc="Keyed by `metadataKey`, per the Task Profile."),
        ),
        doc="One box's session-local mapping + task config "
        "(`ARCHITECTURE.md#session-lifecycle`).",
    ),
    Shape(
        "SessionBox",
        obj(
            f("box", INT),
            f("animalId", STR),
            f("animalName", STR),
            f("sketchName", STR),
            f("sketchPath", STR),
            f("running", BOOL),
            f(
                "startedAt",
                nullable(STR),
                doc="When this box's current run began; null unless running. "
                "What lets a reloaded Mission Control resume its elapsed clocks.",
            ),
            f(
                "ended",
                BOOL,
                doc="This box's run in the group on the rig has finished and been "
                "recorded, and the box has not been started again. Cleared by a "
                "new mapping and by the box's next start. What lets a reloaded "
                "Mission Control tell a finished group from one never started "
                "(`ARCHITECTURE.md#running-boxes`).",
            ),
        ),
        doc="One box as the runner sees it — the source Mission Control renders.",
    ),
    Shape(
        "TelemetryMetric",
        obj(
            f("id", STR),
            f("value", nullable(FLOAT), doc="P(hit) over the rolling window; null until a trial counts."),
            f("n", INT, doc="Counted (hit-or-miss) trials in the window — a window length, not a trial count."),
        ),
    ),
    Shape(
        "BoxTelemetry",
        obj(f("box", INT), f("animalId", STR), f("metrics", ListOf(Ref("TelemetryMetric")))),
    ),
    Shape(
        "PortTelemetry",
        obj(
            f("box", INT),
            f(
                "running",
                BOOL,
                doc="A task started with `port.sendStart` is still running. Goes "
                "false when the board emits its `END_SESSION` strobe or the port "
                "leaves PASSTHROUGH — observed by the sidecar, never assumed.",
            ),
            f("metrics", ListOf(Ref("TelemetryMetric"))),
        ),
        doc="Debug Mode's counterpart to `BoxTelemetry`. No `animalId`: a task "
        "started by hand from the console is nobody's run and records nothing.",
    ),
    Shape(
        "AnimalEnded",
        obj(
            f("box", INT),
            f("animalId", STR),
            f("stopReason", STR, doc="One of the stop reasons in `ARCHITECTURE.md#session-lifecycle`."),
            f("filePath", nullable(STR)),
        ),
    ),
    Shape(
        "RunnerSession",
        obj(
            f("session", Ref("Session")),
            f(
                "groupId",
                nullable(STR),
                doc="Null when the runner holds no group — before a mapping is "
                "confirmed, and between groups.",
            ),
            f("boxes", ListOf(Ref("SessionBox"))),
        ),
        doc="The runner-held session — the same shape a sessions.status reply carries.",
    ),
    Shape(
        "ActiveSessions",
        obj(
            f(
                "running",
                nullable(Ref("RunnerSession")),
                doc="Keyed off the live runner, never a bare DB status query — a "
                "'running' row with no live runner is a crash orphan. A held session "
                "with `groupId: null` and no boxes is BETWEEN GROUPS, awaiting a choice.",
            ),
            f(
                "configuring",
                ListOf(Ref("Session")),
                doc="Setup never finished; legitimately resumable into the mapping flow.",
            ),
            f(
                "stale",
                ListOf(Ref("Session")),
                doc="DB says 'running' but no runner holds them — a crash or a closed "
                "app. The .tsv on disk is the record; a same-day one can be continued "
                "with another group (`sessions.resume`), never mid-group.",
            ),
        ),
        doc="Everything unfinished, discoverable with no prior knowledge of ids. "
        "Also the session.lifecycle payload — one shape, one emitter.",
    ),
    # Analytics (DATA.md#analytics-views)
    Shape(
        "SessionListItem",
        obj(
            f("id", STR),
            f("cohortId", STR),
            f("prefixName", STR),
            f("sessionNumber", STR),
            f("date", STR),
            f("startedAt", STR),
            f("endedAt", nullable(STR)),
            f(
                "clockStartedAt",
                STR,
                doc="When the session actually began running: the first group "
                "run's start, or `startedAt` before any group ran "
                "(`DATA.md#the-session-clock`). `startedAt` is when Step 1 "
                "created the record. Elapsed time and note offsets count from this.",
            ),
            f(
                "clockEndedAt",
                nullable(STR),
                doc="The last group run's end once every run is closed, else "
                "`endedAt`; null while the session is open. For a session "
                "recovered from files, the latest run's start plus its stream's "
                "span, once the index has read the files "
                "(`DATA.md#the-session-clock`) — derived, so shown as `~`.",
            ),
            f("status", Ref("SessionStatus")),
            f("folderPath", STR),
            f(
                "ordinal",
                INT,
                doc="1-based chronological position from (date, startedAt) — never "
                'from sessionNumber, which is free text and would sort "10" before "9".',
            ),
            f("runCount", INT, optional=True),
            f(
                "groupRuns",
                ListOf(Ref("GroupRun")),
                doc="Which groups ran, so Step 1 can offer to continue one of "
                "today's sessions with another group (`sessions.resume`).",
            ),
        ),
        doc="One session, from sessions.list or inside a summary.",
    ),
    Shape(
        "DiskSession",
        obj(
            f("cohortId", STR),
            f("cohortName", STR),
            f("prefixName", STR),
            f("sessionNumber", STR),
            f("date", STR, doc="ISO YYYY-MM-DD, parsed from the folder name — legacy spellings normalized."),
            f("folderPath", STR),
            f(
                "recorded",
                BOOL,
                doc="True when this machine's database knows the folder — a session row, or "
                "adopted runs from a rescan, which writes no session row on purpose "
                "(`DATA.md#reading-the-archive`). False only "
                "for a folder another Ephymeris machine wrote that no rescan here has adopted.",
            ),
        ),
        doc="One session folder found on disk, identified by name alone (`sessions/paths.py`). "
        "What the archive can assert without opening a file: identity and date, never runs or animals.",
    ),
    Shape(
        "MetricSummary",
        obj(
            f("id", STR),
            f("label", STR),
            f(
                "pSession",
                nullable(FLOAT),
                doc="Whole-session P(hit) — what every panel plots. `null` means "
                "no trials scored, which is a different claim from zero.",
            ),
            f(
                "pWindow",
                nullable(FLOAT),
                doc="Rolling P at the authored window, for continuity with Mission "
                "Control. Not interchangeable with pSession.",
            ),
            f(
                "hits",
                INT,
                doc="Counted trials this metric scored a hit on. Present so two "
                "conditions can be POOLED exactly — sum hits, sum counted — "
                "rather than by averaging their proportions, which would weight "
                "a 20-trial condition like a 200-trial one.",
            ),
            f("counted", INT),
            f("triggered", INT),
            f("excluded", INT),
            f("windowSize", INT),
            f("wilsonLow", nullable(FLOAT)),
            f("wilsonHigh", nullable(FLOAT)),
            f("lowConfidence", BOOL),
            f(
                "answerSide",
                nullable(Ref("AnswerSide")),
                doc="Which answer this condition rewards, read off its metric's "
                "`successCode` (`TASKS.md#derived-state-machine`). Null whenever the profile "
                "cannot prove one — never guessed, and never taken from "
                "`alternateCode`, which on a no-go metric means 'any port will "
                "do'. This is what lets the strategy plane fold N conditions "
                "onto two axes without knowing anything about odors.",
            ),
        ),
        doc="One metric's whole-session result (`DATA.md#derived-metrics`).",
    ),
    Shape(
        "TrialOutcomes",
        obj(
            f("trials", INT, doc="Every trial boundary seen — one per odor onset."),
            f(
                "administered",
                INT,
                doc="Odor sampled to completion; the denominator for both "
                "accuracies. A trial the animal never engaged with is not "
                "evidence about discrimination.",
            ),
            f("rewarded", INT, doc="Fluid actually delivered."),
            f(
                "holdFailed",
                INT,
                doc="Correct well reached, released before the hold cleared — "
                "the right choice, no drop earned.",
            ),
            f("wrongWell", INT),
            f("noResponse", INT, doc="Administered, but no well was ever answered."),
            f("aborted", INT, doc="Never administered — odor port left early, or never poked."),
            f(
                "pRewarded",
                nullable(FLOAT),
                doc="rewarded / administered. Conservative: a hold failure counts against it.",
            ),
            f(
                "pSide",
                nullable(FLOAT),
                doc="(rewarded + holdFailed) / administered — the correct side was "
                "chosen whether or not the hold earned the drop. Always ≥ pRewarded; "
                "the gap between them is the consummatory hold-failure rate.",
            ),
            f("rewardedLow", nullable(FLOAT)),
            f("rewardedHigh", nullable(FLOAT)),
            f("sideLow", nullable(FLOAT)),
            f("sideHigh", nullable(FLOAT)),
        ),
        doc="What actually happened per trial (`DATA.md#derived-metrics`). Distinct "
        "from the declared metrics, which are reward-*unconditional* — they "
        "score a detected poke whether or not the fluid hold cleared.",
    ),
    Shape(
        "TrialEngagement",
        obj(
            f("presented", INT, doc="Every trial the box offered — one per trial light."),
            f("poked", INT, doc="Of those, the ones the animal poked the odor port on."),
            f(
                "odorDelivered",
                INT,
                doc="Of those, the ones that reached odor delivery. Equals "
                "TrialOutcomes.trials on a well-formed stream — the same trials "
                "counted from the other end.",
            ),
            f(
                "noPoke",
                INT,
                doc="presented - poked. The animal never engaged the odor port "
                "(LAZY_RAT), plus at most one window a stop or drop truncated.",
            ),
            f(
                "pokeAborted",
                INT,
                doc="poked - odorDelivered. Engaged, then let go before the "
                "pre-odor hold cleared, so no odor was ever delivered. Distinct "
                "from TrialOutcomes.aborted, which received odor and left during "
                "sampling.",
            ),
            f("pEngaged", nullable(FLOAT), doc="poked / presented."),
            f("pDelivered", nullable(FLOAT), doc="odorDelivered / presented."),
            f("engagedLow", nullable(FLOAT)),
            f("engagedHigh", nullable(FLOAT)),
        ),
        doc="How far each offered trial got before the animal dropped out "
        "(`DATA.md#derived-metrics`). Delimited on the trial light, not on odor "
        "onset — the firmware only strobes odor-on after the animal has poked "
        "and held, so every other count in a run summary is silently "
        "conditioned on engagement and none of them can measure it. A ladder, "
        "not a partition: presented >= poked >= odorDelivered by construction.",
    ),
    Shape(
        "ConditionOutcomes",
        obj(
            f("metricId", STR),
            f("label", STR),
            f(
                "triggerCode",
                INT,
                doc="The code that opens this condition's trials — what splits "
                "the tally. Two metrics sharing one legitimately cover the "
                "same trials.",
            ),
            f("outcomes", Ref("TrialOutcomes")),
        ),
        doc="TrialOutcomes restricted to one declared condition "
        "(`DATA.md#derived-metrics`), in authored liveMetrics order; the "
        "entries partition `RunSummary.outcomes` field for field. Answers 'how many trials of this "
        "kind were administered, and how many of those paid out'.",
    ),
    Shape("RunStatus", lit("ok", "no-metrics", "missing", "unreadable")),
    Shape(
        "ProfileSource",
        lit("snapshot", "sketch-current", "inferred", "unavailable"),
        doc="How much the decoding can be trusted (`DATA.md#reading-the-archive`). Four states — "
        "`sketch-current` means the profile may have changed since the run; "
        "`inferred` means no profile resolved at all and the conditions were "
        "read out of the recorded stream itself, sound because the strobe "
        "registry is append-only but blind to conditions the animal never met.",
    ),
    Shape(
        "RunSummary",
        obj(
            f("runId", STR),
            f("sessionId", STR),
            f("animalId", STR),
            f(
                "boxNumber",
                nullable(INT),
                doc="Null for an adopted orphan (`DATA.md#reading-the-archive`) — a "
                "filename carries no box.",
            ),
            f("startedAt", STR),
            f("endedAt", nullable(STR)),
            f("sketchPath", STR),
            f(
                "sketchName",
                STR,
                doc="The program this run RECORDS having been run on — the "
                "`sketch` field of its own file, falling back to the last "
                "segment of `sketchPath`. Not the same question as "
                "`sketchPath`, which is where THIS machine found a `task.json` "
                "to decode with and is empty for a file copied from another "
                "rig (`DATA.md#reading-the-archive`). Empty only when the file named no "
                "sketch at all.",
            ),
            f("profileHash", nullable(STR)),
            f(
                "paramsHash",
                nullable(STR),
                doc="Hash of the task parameters this run used "
                "(`TASKS.md#profile-and-params-hashes`). Comparability is the PAIR with `profileHash` — that one "
                "covers the profile declaration, which is identical across every "
                "run of a sketch however it was tuned. Null when the run "
                "recorded no parameters.",
            ),
            f("profileSource", Ref("ProfileSource")),
            f("stale", BOOL, doc="The file is gone but this is its last known-good summary."),
            f(
                "falseStart",
                BOOL,
                doc="Set aside as a false start (`DATA.md#false-starts`): restarted "
                "and short, or ruled so by hand. Such a run arrives in "
                "`AnalyticsSummary.falseStarts`, never in `runs`.",
            ),
            f(
                "falseStartSource",
                nullable(lit("automatic", "marked", "restored")),
                doc="Why: `automatic` (the rule), `marked` (a person set it aside), "
                "`restored` (the rule would, a person said count it). Null for an "
                "ordinary run.",
            ),
            f(
                "restartedBy",
                nullable(STR),
                doc="The next run of the same animal in the same session, if any.",
            ),
            f("status", Ref("RunStatus")),
            f("metrics", ListOf(Ref("MetricSummary"))),
            f(
                "overall",
                nullable(Ref("MetricSummary")),
                doc="Accuracy pooled across every metric — the only single number "
                "that can tell learning from a side bias (`DATA.md#derived-metrics`).",
            ),
            f(
                "outcomes",
                nullable(Ref("TrialOutcomes")),
                doc="Null when the profile declares no reward vocabulary "
                "(`DATA.md#derived-metrics`) — "
                "absent rather than zeroed, since 'this task has no notion of a "
                "reward delivery' is not 'this animal earned nothing'.",
            ),
            f(
                "conditions",
                ListOf(Ref("ConditionOutcomes")),
                doc="Empty — not null — whenever `outcomes` is null: there is no "
                "separate claim to make about a task that can't express an "
                "outcome at all.",
            ),
            f(
                "engagement",
                nullable(Ref("TrialEngagement")),
                doc="How many trials the box offered and how far each got "
                "(`DATA.md#derived-metrics`) — the layer above every other count here. Null when "
                "the profile declares no trial light, on the same rule as "
                "`outcomes`: a zeroed ladder would read as an animal that never "
                "engaged rather than as a task that can't say.",
            ),
            f("totalEvents", INT),
            f("durationMs", nullable(FLOAT)),
            f("stopReason", nullable(STR)),
            f("clean", BOOL),
            f("seed", nullable(INT)),
            f("detail", nullable(STR)),
            f("excludedByDefault", BOOL),
        ),
    ),
    Shape(
        "AnalyticsAnimal",
        obj(
            f("id", STR),
            f("name", STR),
            f("groupId", STR),
            f("boxNumber", nullable(INT)),
            f("cage", nullable(INT), doc="Home-cage number, same field as Animal.cage."),
            f(
                "former",
                BOOL,
                doc="A former member (`DATA.md#former-members`), listed after "
                "the roster and only when it has runs in this summary. Its "
                "`groupId` is empty and `boxNumber` null.",
            ),
        ),
    ),
    Shape(
        "AnswerSide",
        lit("left", "right", "withhold", "port"),
        doc="The kind of answer a condition rewards. `port` is a rig whose "
        "response ports carry no side in their strobe names, so it keeps a slot "
        "number instead of being called left or right.",
    ),
    Shape(
        "ProfileMetricInfo",
        obj(
            f("id", STR),
            f("label", STR),
            f("windowSize", INT),
            f(
                "answerSide",
                nullable(Ref("AnswerSide")),
                doc="See `MetricSummary.answerSide`. Carried on the group as "
                "well so a panel can work out its axes before opening a run.",
            ),
        ),
    ),
    Shape(
        "ProfileGroup",
        obj(
            f("hash", STR),
            f("taskName", nullable(STR)),
            f("kind", nullable(STR)),
            f("metrics", ListOf(Ref("ProfileMetricInfo"))),
            f("runCount", INT),
        ),
        doc="A comparability set: two runs share axes only if they share a hash "
        "(`TASKS.md#profile-and-params-hashes`).",
    ),
    Shape("AnalyticsWarning", obj(f("code", STR), f("runId", STR), f("message", STR))),
    Shape(
        "AnalyticsCounts",
        obj(
            f("runs", INT),
            f("decoded", INT),
            f("noProfile", INT),
            f("missing", INT),
            f("unreadable", INT),
            f("falseStarts", INT, doc="Runs set aside; not included in the other counts."),
        ),
    ),
    Shape(
        "AnalyticsSummary",
        obj(
            f("cohortId", STR),
            f(
                "dataFolder",
                STR,
                doc="The cohort's data folder, verbatim. The Observatory's "
                "open-folder button wants exactly this string, and the handler "
                "has the cohort in hand already — fetching the full cohort "
                "(roster and all) client-side for one path would be the wrong "
                "shape of call.",
            ),
            f("sessions", ListOf(Ref("SessionListItem"))),
            f("animals", ListOf(Ref("AnalyticsAnimal"))),
            f("groups", ListOf(Ref("Group"))),
            f(
                "runs",
                ListOf(Ref("RunSummary")),
                doc="Flat, not a matrix — two runs really can share one (animal, "
                "session). False starts excluded: every metric reads this list.",
            ),
            f(
                "falseStarts",
                ListOf(Ref("RunSummary")),
                doc="Runs set aside as false starts (`DATA.md#false-starts`). Listed "
                "where runs are listed, muted; counted nowhere.",
            ),
            f("profileGroups", ListOf(Ref("ProfileGroup"))),
            f("counts", Ref("AnalyticsCounts")),
            f("warnings", ListOf(Ref("AnalyticsWarning"))),
            f("minCountedTrials", INT),
        ),
        doc="The whole cohort table in one call; selections filter it client-side.",
    ),
    Shape(
        "MetricSeries",
        obj(
            f("id", STR),
            f("label", STR),
            f("values", ListOf(FLOAT)),
            f(
                "n",
                ListOf(INT),
                doc="Sample size behind each point — the *window* length, capped at "
                "windowSize, not a cumulative count. What a confidence band must use.",
            ),
            f("windowSize", INT),
        ),
    ),
    Shape(
        "StrategyPoint",
        obj(
            f(
                "trial",
                INT,
                doc="Counted trials resolved across *both* conditions at this "
                "sample — the only shared clock the two metrics have.",
            ),
            f(
                "x",
                FLOAT,
                doc="Rolling P pooled over every condition answered at one "
                "well. The axes are SIDES, not conditions.",
            ),
            f("y", FLOAT, doc="The same for the conditions answered at the other well."),
            f("n", INT, doc="The smaller of the two rolling window lengths."),
        ),
        doc="One sample of the within-session strategy walk (`DATA.md#analytics-views`).",
    ),
    Shape(
        "TrialRecord",
        obj(
            f("index", INT, doc="0-based position in the stream's trial order."),
            f(
                "triggerCode",
                INT,
                doc="The condition code that opened this trial — one of "
                "`boundaries_for`'s union, so a `ConditionOutcomes.triggerCode` "
                "matches it directly.",
            ),
            f(
                "outcome",
                lit("rewarded", "hold-failed", "wrong-well", "no-response", "aborted"),
            ),
            f(
                "atMs",
                nullable(INT),
                doc="Trial open, in ms from the run's first recorded timestamp. "
                "Null when the file carries no usable clock.",
            ),
            f(
                "latencyMs",
                nullable(INT),
                doc="Trial open → the code that settled the outcome. Null for "
                "no-response/aborted trials, which nothing settles.",
            ),
        ),
        doc="One classified trial (`DATA.md#derived-metrics`) — the same classification "
        "pass the outcome tallies come from, kept as a sequence instead of "
        "being summed away.",
    ),
    Shape(
        "RunSeries",
        obj(
            f("runId", STR),
            f("mode", lit("rolling", "cumulative")),
            f("metrics", ListOf(Ref("MetricSeries"))),
            f(
                "trail",
                ListOf(Ref("StrategyPoint")),
                doc="The joint walk through the strategy plane. Always rolling, "
                "whatever `mode` is — 'what strategy is running right now' is a "
                "rolling question. Empty when the profile's conditions can't be "
                "split into two opposing sides (`derive.strategy_axes`). Starts "
                "only once both windows hold enough counted trials, since a "
                "one-trial proportion pins the walk to a corner. Cannot be "
                "assembled client-side from `metrics`: those are indexed by each "
                "metric's own counted trials, which interleave.",
            ),
            f(
                "trials",
                ListOf(Ref("TrialRecord")),
                doc="Every trial in stream order. Empty when the profile can't "
                "express outcomes, on the same rule as `RunSummary.outcomes`. "
                "Tallying this list reproduces the run's `TrialOutcomes` and, "
                "grouped by `triggerCode`, its `ConditionOutcomes` — pinned by "
                "test, so the tape and the tallies can never disagree.",
            ),
        ),
    ),
    Shape(
        "SeriesResult",
        obj(f("series", ListOf(Ref("RunSeries"))), f("warnings", ListOf(Ref("AnalyticsWarning")))),
    ),
    Shape(
        "RescanOrphan",
        obj(
            f("path", STR),
            f(
                "animalId",
                nullable(STR),
                doc="Matched by name against the roster, never guessed "
                "(`DATA.md#reading-the-archive`).",
            ),
            f(
                "animalName",
                nullable(STR),
                doc="The animal name the *document* carries, reported as written "
                "even when it is what failed to match.",
            ),
            f(
                "animalSource",
                nullable(lit("document", "filename")),
                doc="Which recording of the animal `animalId` came from. "
                "`filename` means the document's `rat` field matched no animal "
                "and the file stem did — an exact match against the roster on a "
                "second recording of the same fact, never a guess. Null "
                "when the run is unattributed.",
            ),
            f("date", nullable(STR)),
            f("status", STR),
            f("reason", nullable(STR)),
        ),
    ),
    Shape(
        "RescanPruned",
        obj(
            f("runs", INT, doc="Recorded `session_animal_runs` rows dropped."),
            f(
                "sessions",
                INT,
                doc="Sessions dropped once nothing was left pointing at them — "
                "their folder is gone and no run of theirs survived.",
            ),
            f("adopted", INT, doc="`adopted_runs` rows dropped."),
        ),
        doc="What the rescan removed because the disk no longer has it "
        "(`DATA.md#reading-the-archive`). "
        "Bookkeeping only — the rescan never deletes a file.",
    ),
    Shape(
        "RescanResult",
        obj(
            f("scanned", INT),
            f(
                "adopted",
                INT,
                doc="What this scan **decided** — not how many adopted rows the "
                "cohort has. A file already adopted from that same path and "
                "unchanged since is carried forward unread, so a rescan that "
                "changed nothing reports 0.",
            ),
            f(
                "pruned",
                Ref("RescanPruned"),
                doc="Records reconciled away. Only ever counts paths that are "
                "**reachable and absent** — a path under an unreachable root is "
                "left alone, so an unplugged drive can't erase history.",
            ),
            f(
                "rehomed",
                INT,
                doc="Records re-pointed, before the prune, from a folder this "
                "cohort was moved out of to the files now under its own "
                "(`DATA.md#data-folder`) — the repair for a relocate that once "
                "moved the files and left the records behind.",
            ),
            f(
                "duplicates",
                INT,
                doc="Extra copies of an already-seen run, skipped. A hand-managed "
                "archive often keeps a consolidated copy beside the per-prefix "
                "originals; adopting both would double every animal.",
            ),
            f("orphans", ListOf(Ref("RescanOrphan"))),
            f("cohortId", STR),
            f("dataFolder", STR),
            f(
                "folderMissing",
                BOOL,
                doc="The cohort's data folder isn't on disk — an unplugged drive "
                "or a re-lettered volume. Distinguishes 'nothing there' from "
                "'nowhere to look'.",
            ),
        ),
    ),
    Shape(
        "AnalyticsProgress",
        obj(f("cohortId", STR), f("phase", lit("reading", "walking")), f("done", INT), f("total", INT)),
    ),
    Shape(
        "RecoveredTsv",
        obj(
            f("tsvPath", STR),
            f("jsonPath", nullable(STR), doc="Null when recovery failed."),
            f("status", lit("recovered", "failed")),
            f("nEvents", INT, doc="Recomputed from the lines actually parsed, never copied from a footer."),
            f(
                "stopReason",
                nullable(STR),
                doc="The footer's recorded reason when the .tsv has one (a "
                "finalized run whose best-effort .json write failed); "
                "'recovered after crash' for a footer-less log; 'recovered from a "
                "legacy log' for the pre-Ephymeris dialect, which never had a "
                "footer. Null on failure.",
            ),
            f("reason", nullable(STR), doc="Why recovery failed, when it did."),
        ),
        doc="One orphaned write-ahead log the crash-recovery backfill processed.",
    ),
    Shape(
        "RecoverResult",
        obj(
            f("scanned", INT, doc="Orphaned .tsv files found — write-ahead logs with no .json sibling."),
            f("recovered", INT),
            f("failed", INT),
            f("entries", ListOf(Ref("RecoveredTsv"))),
            f("cohortId", STR),
            f("dataFolder", STR),
            f("folderMissing", BOOL, doc="Same distinction as RescanResult's: 'nothing there' vs 'nowhere to look'."),
        ),
    ),
    Shape(
        "TidySession",
        obj(
            f("sessionId", STR),
            f("label", STR, doc="`<prefix>_<number>`, as the folder names it."),
            f("date", STR),
            f("status", Ref("SessionStatus")),
            f("startedAt", STR),
            f(
                "runCount",
                INT,
                doc="Recorded runs plus recovered files attributed to it. On an "
                "applied merge's `keep`, the merged day's total.",
            ),
            f("groupIds", ListOf(STR), doc="Its group runs, in order; a group may repeat."),
        ),
        doc="One session record as the tidy preview names it "
        "(`DATA.md#reading-the-archive`).",
    ),
    Shape(
        "TidyMerge",
        obj(
            f("keep", Ref("TidySession"), doc="The earliest record holding data — the day's session."),
            f("absorb", ListOf(Ref("TidySession")), doc="Folded into `keep`: runs re-parented, rows deleted."),
        ),
    ),
    Shape(
        "TidyEmpty",
        obj(
            f("session", Ref("TidySession")),
            f(
                "removesFolder",
                BOOL,
                doc="The folder exists and holds no file, so it is removed too. "
                "A folder with any file in it is never touched.",
            ),
        ),
    ),
    Shape(
        "TidySkipped",
        obj(f("session", Ref("TidySession")), f("reason", STR)),
    ),
    Shape(
        "TidyPlan",
        obj(
            f("cohortId", STR),
            f("applied", BOOL, doc="False for a preview; true once the changes are made."),
            f("merges", ListOf(Ref("TidyMerge"))),
            f("empty", ListOf(Ref("TidyEmpty"))),
            f(
                "skipped",
                ListOf(Ref("TidySkipped")),
                doc="Records sharing a folder with the held session or a set-up "
                "started today — left whole, and said so.",
            ),
        ),
    ),
    Shape(
        "AnimalMoveAnimal",
        obj(
            f("animalId", STR, doc="Its id in the source cohort."),
            f("name", STR),
            f(
                "status",
                lit("active", "former", "files"),
                doc="On the source's roster, a former member, or an id known "
                "only from its files (`DATA.md#former-members`).",
            ),
            f(
                "outcome",
                lit("joins", "carried"),
                doc="`joins`: the destination already has an animal of this "
                "name, and its history becomes that animal's. `carried`: it "
                "arrives under its own id — on the roster if it was on one, "
                "else as a former member.",
            ),
            f("destinationAnimalId", STR),
            f("runs", INT, doc="Recorded plus recovered runs that move."),
            f("files", INT),
        ),
    ),
    Shape(
        "AnimalMoveSession",
        obj(
            f("sessionId", STR, doc="The source record."),
            f("label", STR),
            f("date", STR),
            f(
                "kind",
                lit("whole", "split"),
                doc="`whole`: only moved animals ran in it, so the record "
                "itself moves. `split`: animals that stay ran in it too, so "
                "the destination gets a record of its own.",
            ),
            f(
                "joinsExisting",
                BOOL,
                doc="The destination already has this prefix, number and date; "
                "the runs join that record.",
            ),
            f("notesMoved", INT),
            f("notesCopied", INT, doc="Notes about the whole session, or a shared box."),
        ),
    ),
    Shape(
        "AnimalMoveFiles",
        obj(
            f("count", INT, doc="Files that move."),
            f("bytes", INT),
            f(
                "alreadyThere",
                INT,
                doc="An identical copy is already at the destination — moved "
                "on the other lab machine, or by an interrupted move.",
            ),
            f(
                "missing",
                INT,
                doc="Runs whose file is in neither folder. Their records move all "
                "the same; nothing is lost that wasn't already.",
            ),
        ),
    ),
    Shape(
        "AnimalMoveRefusal",
        obj(
            f("code", STR),
            f("message", STR, doc="Says what to do about it."),
        ),
    ),
    Shape(
        "AnimalMovePlan",
        obj(
            f("sourceCohortId", STR),
            f("destinationCohortId", STR),
            f("applied", BOOL, doc="False for a preview; true once the move is made."),
            f("animals", ListOf(Ref("AnimalMoveAnimal"))),
            f("sessions", ListOf(Ref("AnimalMoveSession"))),
            f(
                "recoveredSessions",
                INT,
                doc="Sessions known only from files whose runs move; they need "
                "no record, so they are only counted.",
            ),
            f("files", Ref("AnimalMoveFiles")),
            f(
                "refused",
                ListOf(Ref("AnimalMoveRefusal")),
                doc="Why it can't be done. Empty means an apply would go ahead.",
            ),
        ),
        doc="What moving animals between cohorts does, or did "
        "(`DATA.md#moving-animals-between-cohorts`).",
    ),
    # Event-only envelope payloads
    Shape("ServerHello", obj(f("protocolVersion", INT), f("sidecarVersion", STR))),
    Shape(
        "PortStateData",
        obj(
            f("box", INT),
            f("state", Ref("PortStateName")),
            f("prev", Ref("PortStateName")),
            f("reason", STR),
        ),
    ),
    Shape("PortOutputData", obj(f("box", INT), f("lines", ListOf(Ref("OutputLine"))))),
    Shape("BoardsPresenceData", obj(f("boards", ListOf(Ref("DetectedBoard"))))),
    Shape(
        "FlashProgressData",
        obj(
            f("box", INT),
            f("phase", lit("compile", "upload")),
            f("stream", lit("stdout", "stderr")),
            f("text", STR),
        ),
    ),
    Shape("CohortsUpdatedData", obj(f("cohorts", ListOf(Ref("CohortSummary"))))),
    Shape("PrefixesUpdatedData", obj(f("prefixes", ListOf(Ref("Prefix"))))),
    Shape(
        "SidecarErrorData",
        obj(f("code", STR), f("message", STR), f("detail", ANY)),
        doc="Failures with no command to attribute them to.",
    ),
    # ---------------------------------------------------------------- rig wiring
    Shape(
        "RigProblem",
        obj(
            f("location", STR, doc="`channels.left_well.kind`, `pins.odor_port`, or a rule's registry file."),
            f("message", STR),
            f(
                "code",
                nullable(STR),
                doc="The wiring rule, when one produced it — RIG101 through RIG106. "
                "Null for a schema violation, which has no rule number because it "
                "is caught before the halves are composed.",
            ),
        ),
        doc="One thing wrong with a wiring document, located. Every problem is "
        "reported rather than the first, because fixing new wiring should be one "
        "pass rather than a game of whack-a-mole.",
    ),
    Shape(
        "RigStatus",
        obj(
            f("custom", BOOL, doc="False ⇒ this rig runs the wiring its build shipped with."),
            f("derivedFrom", STR, doc="The shipped pinout this document started as."),
            f("board", STR),
            f("editedAt", nullable(STR)),
            f(
                "pinoutHash",
                STR,
                doc="The composed wiring's hash, over the fields that can change a "
                "compiled byte. Prose and pin notes are excluded: it answers "
                "'could these two produce different firmware?', so a reworded "
                "rationale must not move it.",
            ),
        ),
    ),
    Shape(
        "RigDocument",
        obj(
            f("document", ANY, doc="The rig document itself — `{rig_version, channels, pins}`, validated against rig/schema/rig_hardware.v1.json."),
            f("status", Ref("RigStatus")),
            f("problems", ListOf(Ref("RigProblem"))),
        ),
        doc="The wiring, plus everything wrong with it. `document` is served even "
        "when `problems` is non-empty: an editor that refused to show a broken "
        "document would be refusing to show the one that needs fixing.",
    ),
    Shape(
        "RigImpact",
        obj(
            f("specId", STR),
            f("label", nullable(STR)),
            f(
                "codes",
                ListOf(STR),
                doc="What this wiring would newly break this task profile with. "
                "Empty when the profile was already failing for its own reasons.",
            ),
        ),
        doc="A task this wiring change would break. Computed BEFORE the write.",
    ),
    Shape(
        "RigSaved",
        obj(
            f("status", Ref("RigStatus")),
            f("problems", ListOf(Ref("RigProblem"))),
            f(
                "breaks",
                ListOf(Ref("RigImpact")),
                doc="Task profiles that generate today and would not after this "
                "change. Non-empty does NOT mean the save was refused — see the "
                "command.",
            ),
        ),
    ),
    # --------------------------------------------------------------- task profiles
    #
    # A task profile is the operator's task: the trial table, how the next trial
    # is chosen, the ramp, and the numbers. Saving one WRITES A SKETCH — the
    # generated folder under `<data_dir>/tasks/` is an ordinary discovered
    # sketch from that moment, which is why nothing below has a flashing
    # command of its own. `port.flash` already takes it.
    Shape(
        "TaskDiagnostic",
        obj(
            f("location", STR, doc="`trials[1].rewardChannel`, `stages[2].trials`."),
            f("message", STR),
            f(
                "code",
                STR,
                doc="TSK101–TSK111, TSK113 and TSK114 from the sidecar; TSK112 is derived "
                "on the Task tab. Each names a failure that is silent without it.",
            ),
        ),
    ),
    Shape(
        "TaskEntry",
        obj(
            f("id", STR),
            f("name", STR, doc="Also the generated sketch's folder name."),
            f("category", STR),
            f("path", STR, doc="The generated sketch folder — what `port.flash` takes."),
            f("label", STR),
            f("editedAt", nullable(STR), doc="ISO-8601."),
            f(
                "problems",
                INT,
                doc="How many diagnostics it currently trips. A COUNT, not the "
                "list: this reply is drawn on every route mount and would "
                "otherwise grow with the library.",
            ),
            # The three facts a task card states without opening the document.
            # Counts rather than the arrays themselves, for the same reason
            # `problems` is a count: this reply is drawn on every route mount.
            f("trials", INT, doc="Rows in the trial table — how many conditions it presents."),
            f("stages", INT, doc="Rows in the shaping ramp. 1 means no ramp."),
            f(
                "selectionMode",
                lit("antibias", "pool", "weighted"),
                doc="How the next trial is drawn: a side against recent bias then "
                "a type uniformly; a block-shuffled weighted pool; or the side "
                "draw with a weighted pick within it.",
            ),
        ),
        doc="A row in the profile list, and everything a task card states "
        "before the definition is opened.",
    ),
    Shape(
        "TaskSaved",
        obj(
            f("entry", Ref("TaskEntry")),
            f("diagnostics", ListOf(Ref("TaskDiagnostic"))),
            f(
                "sketchPath",
                nullable(STR),
                doc="The generated folder, or null when the bundled root sketch "
                "could not be read — the profile is stored either way and simply "
                "has nothing to flash yet.",
            ),
        ),
    ),
    Shape(
        "TaskPreview",
        obj(
            f("diagnostics", ListOf(Ref("TaskDiagnostic"))),
            f(
                "startLineLength",
                INT,
                doc="Bytes the built START line would occupy, seed included.",
            ),
            f(
                "startLineMax",
                INT,
                doc="The firmware's cap, so the editor can show headroom without "
                "hardcoding it. Over it is TSK107 and a refused generation — "
                "`readLineInto()` truncates in silence, so this is checked "
                "rather than trusted.",
            ),
            f("profile", Ref("TaskProfile"), doc="What this definition compiles to."),
            f(
                "catalogueDefaults",
                MapOf(ANY),
                doc="`metadataKey` → the value this field has with NO override, "
                "keyed the same way `profile.config[].default` is. The editor "
                "needs both to know which values this profile actually pins: a "
                "definition stores only divergences, so a value merely EQUAL to "
                "the catalogue's must not be written into it — that would freeze "
                "it against a later correction to the range or the default.",
            ),
        ),
        doc="A pure compile of an unsaved definition. Writes nothing.",
    ),
    Shape(
        "TasksUpdatedData",
        obj(f("tasks", ListOf(Ref("TaskEntry")))),
    ),
    # ------------------------------------------------------------ strobe vocabulary
    Shape(
        "StrobeCode",
        obj(
            f("name", STR),
            f("code", INT),
            f(
                "origin",
                STR,
                doc="History, not authority: `firmware` (numbered by the lab's "
                "recorded sessions before the app), `ephymeris` (declared by the "
                "app), `operator` (added on the Strobes page).",
            ),
            f("emittedOn", STR, optional=True),
            f("rationale", STR, optional=True),
            f(
                "portSlot",
                INT,
                optional=True,
                doc="The response-port slot that reports with this code. Such a "
                "code can be neither retired nor removed.",
            ),
        ),
    ),
    Shape(
        "RetiredStrobe",
        obj(
            f("name", STR),
            f("code", INT),
            f("rationale", STR, optional=True),
            f("seenIn", STR, optional=True),
            f("retiredAt", STR, optional=True, doc="ISO-8601 UTC; absent on codes retired before the app recorded it."),
        ),
        doc="A code a recorded session contains and nothing may emit any more. "
        "Reserved forever: reissuing one would merge two unrelated event types "
        "in any analysis spanning the change.",
    ),
    Shape(
        "StrobeVocabulary",
        obj(
            f("version", INT),
            f("codeMin", INT),
            f("codeMax", INT, doc="999 — a wire-format limit. The host parser is ^\\d{1,3}\\t\\d+$."),
            f("reserved", ListOf(ListOf(INT)), doc="Inclusive [lo, hi] pairs inside the bounds that are never issued."),
            f("freeRanges", ListOf(ListOf(INT)), doc="Inclusive [lo, hi] pairs a new code may come from. Derived, never stored."),
            f("nextFree", nullable(INT)),
            f("contentHash", STR, doc="Digest of names, codes and slots — what the generated headers are stamped with."),
            f("codes", ListOf(Ref("StrobeCode"))),
            f("retired", ListOf(Ref("RetiredStrobe"))),
            f("portSlots", MapOf(MapOf(STR)), doc="Slot number → its six per-port code names."),
            f(
                "editable",
                BOOL,
                doc="False when this machine's document is unreadable: the app "
                "decodes with the shipped default and refuses every edit, since "
                "a code issued against the default could reissue one this "
                "machine added.",
            ),
            f("problem", nullable(STR), doc="Why `editable` is false."),
        ),
        doc="This machine's strobe vocabulary (`TASKS.md#strobe-vocabulary`) — "
        "the one source of every code. Codes are never renumbered or "
        "repurposed: recorded sessions carry them, and reissuing one silently "
        "merges two unrelated event types in any analysis spanning the change.",
    ),
    Shape(
        "StrobeFirmwareRef",
        obj(
            f("path", STR, doc="Relative to the root it was found under."),
            f(
                "kind",
                lit("library", "sketch", "task"),
                doc="`library`: a shared library every sketch includes — retiring "
                "or removing the code would stop every sketch compiling, so both "
                "are refused.",
            ),
        ),
    ),
    Shape(
        "StrobeArchiveCoverage",
        obj(
            f("files", INT, doc="Recorded files read (or answered from the scan cache)."),
            f("unreadable", INT),
            f("roots", ListOf(STR), doc="Every cohort data folder the scan was pointed at."),
            f("unreachableRoots", ListOf(STR), doc="Of those, the ones that could not be reached."),
        ),
        doc="What the archive scan could see. Only this machine: another rig's "
        "archive is never checked, and the UI says so.",
    ),
    Shape(
        "StrobeSessions",
        obj(
            f("count", INT, doc="Recorded files containing the code."),
            f("sample", ListOf(STR), doc="Up to five of them."),
            f("scanned", Ref("StrobeArchiveCoverage")),
        ),
    ),
    Shape(
        "StrobeUsage",
        obj(
            f("name", STR),
            f("code", INT),
            f("status", lit("live", "retired")),
            f("firmware", ListOf(Ref("StrobeFirmwareRef"))),
            f("portSlot", nullable(INT)),
            f(
                "breaks",
                ListOf(Ref("RigImpact")),
                doc="Saved tasks that generate today and would not with the "
                "code retired or removed.",
            ),
            f("sessions", nullable(Ref("StrobeSessions")), doc="Null unless `scan` was asked for."),
            f(
                "retireBlocker",
                nullable(STR),
                doc="Why `strobes.retire` would refuse outright; null when it "
                "would proceed (with `confirm` if `breaks` or `firmware` is "
                "non-empty).",
            ),
            f(
                "removeBlocker",
                nullable(STR),
                doc="Why `strobes.remove` would refuse outright. Always set "
                "when `sessions.count` > 0. Null with `sessions` null means "
                "not yet known — the scan decides.",
            ),
        ),
        doc="Everything a retire or remove is judged against, computed by the "
        "sidecar so the page never predicts a refusal.",
    ),
    Shape(
        "StrobeImportPlan",
        obj(
            f("adds", ListOf(obj(f("name", STR), f("code", INT), f("retired", BOOL)))),
            f("retires", ListOf(obj(f("name", STR), f("code", INT))), doc="Live here, retired there — retired here too."),
            f("conflicts", ListOf(obj(f("name", STR), f("code", INT), f("message", STR)))),
            f("onlyHere", ListOf(STR), doc="Codes this machine has and the file does not. Never removed by an import."),
        ),
        doc="What importing another machine's vocabulary would do. A union, "
        "never a replacement; any conflict refuses the whole import.",
    ),
    Shape(
        "StrobeScanProgress",
        obj(f("done", INT), f("total", INT)),
    ),
    # Intan recording (RECORDING.md)
    Shape(
        "RecordingBox",
        obj(
            f("box", INT),
            f("digitalIn", INT, doc="The controller input this box's sync line reaches, 1–16."),
            f("port", STR, doc="Headstage port letter, A–H."),
            f("channels", ListOf(STR), doc="Native channel names recorded for this box."),
            f("probeMap", nullable(STR), doc="File name of the probe map copied beside the data."),
        ),
    ),
    Shape(
        "RecordingRun",
        obj(
            f("groupId", STR),
            f("path", STR, doc="The directory handed to RHX as `Filename.Path`."),
            f("baseFilename", STR),
            f(
                "fileTimestamp",
                nullable(STR),
                doc="RHX's own `YYMMDD_HHMMSS` suffix, read back after the recording "
                "started — it names the folder and files RHX actually created.",
            ),
            f("fileFormat", STR),
            f("sampleRate", INT),
            f("startedAt", nullable(STR)),
            f("endedAt", nullable(STR)),
            f("boxes", ListOf(Ref("RecordingBox"))),
        ),
        doc="One group run's recording. A session records once per group, "
        "because the animals — and so the ports and probes — change between groups.",
    ),
    Shape("SessionRecording", obj(f("runs", ListOf(Ref("RecordingRun"))))),
    Shape(
        "RecordingBoxConfig",
        obj(
            f("box", INT),
            f("port", STR),
            f("firstChannel", INT),
            f("lastChannel", INT),
            f("probeMapPath", nullable(STR), optional=True),
        ),
    ),
    Shape(
        "RecordingThreshold",
        obj(
            f(
                "mode",
                lit("keep", "absolute", "rms"),
                doc="`keep` leaves RHX's thresholds as the operator set them there.",
            ),
            f("microvolts", INT, doc="Absolute threshold, −5000…5000 µV."),
            f("rmsMultiple", FLOAT, doc="3.0…20.0 × each channel's RMS noise."),
            f("negative", BOOL, doc="Polarity of the RMS-relative threshold."),
        ),
    ),
    Shape(
        "RecordingConfig",
        obj(
            f("saveDirectory", STR),
            f("fileFormat", lit("Traditional", "OneFilePerSignalType", "OneFilePerChannel")),
            f("saveWideband", BOOL),
            f("saveSpikes", BOOL),
            f("saveSpikeSnapshots", BOOL),
            f("snapshotPreMs", INT, doc="0…3, stored positive; RHX takes it negated."),
            f("snapshotPostMs", INT, doc="1…6."),
            f("saveLowpass", BOOL),
            f("lowpassDownsample", INT, doc="1, 2, 4 … 128."),
            f("saveHighpass", BOOL),
            f("newFileMinutes", INT, optional=True, doc="Traditional format only; 1…999."),
            f("threshold", Ref("RecordingThreshold")),
            f("boxes", ListOf(Ref("RecordingBoxConfig"))),
        ),
        doc="Everything the recording walkthrough collects "
        "(`RECORDING.md#recording-walkthrough`).",
    ),
    Shape(
        "IntanState",
        lit("disconnected", "idle", "configured", "recording", "stopping", "error"),
    ),
    Shape(
        "IntanSyncStat",
        obj(
            f("box", INT),
            f("matched", INT),
            f("spuriousEdges", INT),
            f("unmatchedStrobes", INT),
        ),
        doc="How well a box's sync edges are pairing with its strobes. A climbing "
        "`unmatchedStrobes` with zero `matched` is a sync line that is not connected.",
    ),
    Shape(
        "IntanStatus",
        obj(
            f("state", Ref("IntanState")),
            f("message", nullable(STR), doc="Why, when the state alone does not say."),
            f("connected", BOOL),
            f("controller", nullable(STR), doc="RHX's `Type`, e.g. ControllerRecordUSB3."),
            f("version", nullable(STR)),
            f("sampleRate", nullable(INT)),
            f("synthetic", BOOL, doc="RHX is generating data; no controller is attached."),
            f("headstagePresent", BOOL),
            f("runMode", nullable(STR)),
            f("ports", MapOf(INT), doc="Port letter → amplifier channels present."),
            f(
                "confirmsWrites",
                nullable(BOOL),
                doc="False when this RHX does not answer a `get` that rides a batch, "
                "so a refused command cannot be detected (`RECORDING.md#talking-to-rhx`). "
                "The values that matter are read back either way.",
            ),
            f("rigHasSync", BOOL, doc="This rig's wiring declares a `sync` channel."),
            f("liveStreams", BOOL, doc="The waveform and spike sockets are both open."),
            f("recording", nullable(Ref("RecordingRun"))),
            f(
                "waitingOn",
                ListOf(INT),
                doc="While `stopping`: boxes still finishing their trial.",
            ),
            f("sync", ListOf(Ref("IntanSyncStat"))),
        ),
    ),
    Shape("ScopeKind", lit("spikescope", "psth", "isi", "probemap")),
    Shape(
        "ScopeData",
        obj(
            f("scopeId", STR),
            f("kind", Ref("ScopeKind")),
            f("box", INT),
            f("channel", nullable(STR)),
            f("data", ANY, doc="Per kind; see `RECORDING.md#live-windows`."),
        ),
    ),
    # The session log (DATA.md#the-session-log)
    Shape(
        "NoteTag",
        lit("observation", "intervention", "hardware", "animal-health", "protocol-deviation"),
        doc="What kind of entry a note is. Closed so the log, its PDF and "
        "`notes.md` can group and colour by it.",
    ),
    Shape(
        "NoteScope",
        obj(
            f("kind", lit("session", "animal", "box")),
            f("animalId", nullable(STR), doc="Set only for `kind: animal`."),
            f("box", nullable(INT), doc="Set only for `kind: box`; 1–6."),
        ),
        doc="What a note is about. A session-wide note marks every animal's "
        "trial tape; an animal or box note marks only that run's.",
    ),
    Shape(
        "SessionNote",
        obj(
            f("id", STR),
            f("sessionId", STR),
            f("cohortId", STR),
            f(
                "at",
                STR,
                doc="The moment the note is about, UTC ISO. Defaults to when it "
                "was written; editable afterwards.",
            ),
            f("createdAt", STR),
            f("editedAt", nullable(STR)),
            f("tag", Ref("NoteTag")),
            f("scope", Ref("NoteScope")),
            f("body", STR),
            f(
                "offsetMs",
                nullable(INT),
                doc="`at` minus the session's `clockStartedAt` "
                "(`DATA.md#the-session-clock`) — the T+ the log shows. Derived "
                "on every read, never stored. Null when `at` falls outside the "
                "session's running window, e.g. a note written the next morning.",
            ),
            f(
                "carryForward",
                BOOL,
                doc="Flagged for the next session: surfaces in Step 1 and on the "
                "running session until resolved.",
            ),
            f("resolvedAt", nullable(STR)),
            f(
                "resolvedInSessionId",
                nullable(STR),
                doc="The session a flag was resolved during. Null when it was "
                "resolved outside one, or that session has since been tidied away.",
            ),
        ),
        doc="One timestamped log entry (`DATA.md#the-session-log`). A deleted "
        "note is never sent.",
    ),
    Shape(
        "SessionLog",
        obj(
            f("sessionId", STR),
            f("operator", nullable(STR)),
            f("summary", nullable(STR)),
            f("updatedAt", nullable(STR)),
        ),
        doc="A session's free fields. Absent from `LogbookCohort.logs` for a "
        "session nobody has filled in.",
    ),
    Shape(
        "ValueChange",
        obj(f("from", ANY), f("to", ANY)),
    ),
    Shape(
        "ParamChange",
        obj(
            f("key", STR, doc="The parameter's `metadataKey`."),
            f("from", ANY, doc="Null when the previous run did not have the key."),
            f("to", ANY, doc="Null when this run does not have the key."),
        ),
    ),
    Shape(
        "RunChange",
        obj(
            f("runId", STR),
            f("sessionId", STR),
            f("animalId", STR),
            f(
                "box",
                nullable(INT),
                doc="Null for a recovered run: its file names only the OS port it "
                "used, and ports renumber, so the box is unknown rather than guessed.",
            ),
            f("task", STR, doc="This run's task name."),
            f(
                "recovered",
                BOOL,
                doc="Adopted from a file this database never recorded "
                "(`DATA.md#orphan-adoption`); compared from what the file records.",
            ),
            f("previousRunId", nullable(STR)),
            f("previousSessionId", nullable(STR)),
            f("first", BOOL, doc="The animal's first run on record; nothing to compare."),
            f(
                "taskChange",
                nullable(Ref("ValueChange")),
                doc="Task names, `from` → `to`. Equal names mean the same task "
                "with a revised definition (a different profile hash).",
            ),
            f(
                "boxChange",
                nullable(Ref("ValueChange")),
                doc="Only between two runs that both know their box.",
            ),
            f("params", ListOf(Ref("ParamChange"))),
            f(
                "paramsKnown",
                BOOL,
                doc="False when either run carries no parameters — a run from "
                "before they were recorded, or a recovered file too old to hold "
                "them, or one the analytics index has not read yet. Unknown, never "
                "reported as changed.",
            ),
            f(
                "falseStart",
                BOOL,
                doc="Set aside (`DATA.md#false-starts`): compared with nothing and "
                "never the previous run of the next one, which is compared with "
                "the run before this instead.",
            ),
            f(
                "falseStartSource",
                nullable(lit("automatic", "marked", "restored")),
                doc="As `RunSummary.falseStartSource`.",
            ),
        ),
        doc="What differs between a run and the same animal's previous run, "
        "recorded and recovered alike (`DATA.md#what-changed`).",
    ),
    Shape(
        "LogbookCohort",
        obj(
            f("cohortId", STR),
            f("logs", ListOf(Ref("SessionLog"))),
            f("notes", ListOf(Ref("SessionNote")), doc="Every live note, oldest first."),
            f("changes", ListOf(Ref("RunChange")), doc="One per run, recorded or recovered."),
        ),
        doc="A cohort's whole session log, flat; the client groups it by "
        "`sessionId`. Sessions themselves come from `sessions.list`.",
    ),
    Shape(
        "LogbookUpdated",
        obj(
            f("cohortId", STR),
            f("sessionIds", ListOf(STR), doc="The sessions whose log changed."),
        ),
    ),
)


# --- Commands (client → server) --------------------------------------------

_STATE = obj(f("state", Ref("PortStateName")))
_COHORT = obj(f("cohort", Ref("Cohort")))
_SESSION = obj(f("session", Ref("Session")))

COMMANDS = (
    # ------------------------------------------------- connection and settings
    Command(
        "auth",
        args=obj(f("token", STR)),
        result=obj(f("authenticated", BOOL)),
        doc="Must be the connection's first frame. A bad or missing token, any "
        "other first message, or `AUTH_TIMEOUT_S` (`server.py`) of silence "
        "closes the connection with code 1008 "
        "(`ARCHITECTURE.md#wire-protocol`). Consumed by the server's "
        "authentication step and never dispatched to a handler.",
        section="Connection and settings",
    ),
    Command(
        "settings.push",
        args=obj(f("settings", Ref("EphymerisSettings"))),
        result=obj(f("library", Ref("SketchLibraryStatus"))),
        doc="Sent on every connect and every change, Tauri → sidecar only; the "
        "sidecar is never the settings source of truth "
        "(`ARCHITECTURE.md#settings`). Each push rescans the sketch library and "
        "re-applies the backup directory, box bindings and utility baseline. "
        "The reply carries the bundled library's state so a client learns it "
        "on connect without a second round trip. "
        "Waits for a rig definition write in progress (`TASKS.md#the-rig-definition`).",
    ),
    Command(
        "sketches.refresh",
        result=Ref("SketchDiscovery"),
        doc="Re-run discovery now (Debug Mode's Refresh, and on its mount) "
        "(`TASKS.md#sketch-library`). Also broadcasts `sketches.updated`. "
        "Long-running; the client raises its reply timeout. "
        "Waits for a rig definition write in progress (`TASKS.md#the-rig-definition`).",
    ),
    # ------------------------------------------------------------------- ports
    Command(
        "port.passthrough.open",
        args=obj(
            f(
                "box",
                INT,
            ),
            f(
                "baud",
                INT,
                optional=True,
                doc="Omitted means the configured `defaultBaud`.",
            ),
        ),
        result=_STATE,
        doc="Open the box's serial console: `IDLE` → `PASSTHROUGH` "
        "(`ARCHITECTURE.md#flashing-reset-and-passthrough`). Output then "
        "arrives as `port.output`. `PORT_NOT_BOUND` for a box with no bound "
        "board, `PORT_OPEN_FAILED` when the board is absent or the port busy.",
        section="Ports",
    ),
    Command(
        "port.passthrough.close",
        args=obj(f("box", INT)),
        result=_STATE,
        doc="Close the console: `PASSTHROUGH` → `IDLE`. An idle port then "
        "becomes eligible for a utility-baseline restore.",
    ),
    Command(
        "port.send",
        args=obj(
            f("box", INT),
            f("text", STR),
            f("lineEnding", lit("none", "lf", "cr", "crlf"), optional=True, doc="Default `lf`."),
        ),
        result=obj(f("bytesWritten", INT)),
        doc="Write one line to the open console. The sent text is echoed into "
        "`port.output` as `dir: \"tx\"`. Rejected with `SEND_NOT_PASSTHROUGH` "
        "unless the port is in `PASSTHROUGH`.",
    ),
    Command(
        "port.sendStart",
        args=obj(
            f("box", INT),
            f("sketchPath", STR, doc="The sketch believed to be on the board; its Task Profile shapes the line."),
            f("config", MapOf(ANY), optional=True, doc="Keyed by `metadataKey`, exactly as in a session mapping."),
        ),
        result=obj(f("command", STR, doc="The line as sent, for the console's record."), f("bytesWritten", INT)),
        doc="Debug Mode's **Send START**: builds the `START` line from the "
        "named sketch's Task Profile exactly as `sessions.confirmMapping` does "
        "(a sketch with no profile gets a bare `START`) and writes it to the "
        "open console, then arms live scoring, reported as `port.telemetry`. "
        "No `SEED` token and nothing recorded: this is not a run. "
        "`SKETCH_UNKNOWN` for an undiscovered path; `TASK_PROFILE_INVALID` "
        "when the line would exceed the firmware's `START_LINE_MAX` "
        "(`TASKS.md#the-start-line`); `SEND_NOT_PASSTHROUGH` unless the port "
        "is in `PASSTHROUGH`. To end the run, send `STOP` with `port.send` and "
        "wait for `port.telemetry.running` to go false — the board ends it. "
        "Waits for a rig definition write in progress (`TASKS.md#the-rig-definition`).",
    ),
    Command(
        "port.flash",
        args=obj(
            f("box", INT),
            f("sketchPath", STR, doc="Must be a path in the current discovery result."),
            f(
                "suppressPassthroughResume",
                BOOL,
                optional=True,
                doc="Default false. The session flash sequence sets it so boxes "
                "land in `IDLE` for the runner to claim "
                "(`ARCHITECTURE.md#session-lifecycle`). It is also what tells "
                "the two kinds of flash apart: without it the flash counts as "
                "a deliberate Debug Mode flash and the box is **pinned** "
                "against automatic baseline restores (`UtilityBaselineState`).",
            ),
        ),
        result=obj(
            f("state", Ref("PortStateName")),
            f(
                "resumedPassthrough",
                BOOL,
                doc="The port was in `PASSTHROUGH` before the flash and was "
                "reopened afterward.",
            ),
        ),
        doc="Compile and upload. Entering `FLASHING` force-releases "
        "`PASSTHROUGH` and resumes it afterward unless suppressed "
        "(`ARCHITECTURE.md#flashing-reset-and-passthrough`). Streams "
        "`flash.progress` events carrying this command's `corr`. "
        "`SKETCH_UNKNOWN` for a path outside discovery — the bundled library "
        "and saved task profiles are the only flashable sketches, enforced "
        "here and not just by the picker. `FLASH_FAILED` carries the parsed "
        "`arduino-cli` output. Long-running; the client raises its reply "
        "timeout, and timing out does not cancel the flash. "
        "Waits for a rig definition write in progress (`TASKS.md#the-rig-definition`).",
    ),
    Command(
        "port.reset",
        args=obj(f("box", INT)),
        result=obj(f("state", Ref("PortStateName")), f("resumedPassthrough", BOOL)),
        doc="DTR toggle through `RESETTING`, with the same passthrough "
        "release-and-resume as a flash "
        "(`ARCHITECTURE.md#flashing-reset-and-passthrough`).",
    ),
    Command(
        "port.error.ack",
        args=obj(f("box", INT)),
        result=_STATE,
        doc="`ERROR` → `IDLE`. The only way out of `ERROR`: a board dropping "
        "mid-session is a hard stop that a person clears, never an automatic "
        "recovery (`ARCHITECTURE.md#port-state-machine`).",
    ),
    Command(
        "port.startSession",
        args=obj(f("box", INT)),
        result=_STATE,
        doc="Start one box of the confirmed mapping: open the port (the Mega "
        "DTR-resets), await `READY`, send the `START` line built at "
        "`sessions.confirmMapping`, capture an optional `SEED`, then parse "
        "strobes (`ARCHITECTURE.md#session-lifecycle`). Requires `IDLE`. On a "
        "recording session RHX recording begins first and an `INTAN_*` "
        "refusal comes before the box starts. Opens the group's run and marks "
        "the session `running` if this is the group's first box. "
        "`SESSION_INVALID` for a box with no confirmed mapping, and, with "
        "`detail.boxes`, for a box whose board does not carry its mapped "
        "sketch's current build (`ARCHITECTURE.md#what-a-board-carries`); "
        "both come before RHX or the box starts. Long-running on a recording "
        "session; the client raises its reply timeout.",
    ),
    Command(
        "port.stopSession",
        args=obj(f("box", INT)),
        result=_STATE,
        doc="Sends the literal `STOP` line and does **not** force the "
        "transition: the firmware ends the run at its next trial boundary with "
        "its own end-of-session strobe, and the port leaves `IN_SESSION` when "
        "the sidecar sees it.",
    ),
    # ----------------------------------------------------- utility baseline
    Command(
        "utility.ensure",
        args=obj(
            f("boxes", ListOf(INT), optional=True, doc="Default: every bound box."),
            f(
                "force",
                BOOL,
                optional=True,
                doc="Reflash even a box already believed to be at baseline. For "
                "the Rig tab's button; the automatic paths never set it.",
            ),
        ),
        result=Ref("UtilityStatus"),
        doc="Restore the baseline now rather than at the next board or session "
        "event (`ARCHITECTURE.md#hardware-utility-baseline`). **Returns as "
        "soon as the work is scheduled** — flashing six boxes outlasts any "
        "reply timeout, so progress arrives on `utility.updated`. Never touches "
        "a box that isn't `IDLE`, nor any box while a confirmed session mapping "
        "holds the rig. Arriving over the wire means a person asked, so it "
        "also **releases the pin** on the boxes it names. `UTILITY_UNAVAILABLE` "
        "when the box utility can't be used at all; a box-level problem is a "
        "`state` in the snapshot, not an error.",
        section="Utility baseline",
    ),
    Command(
        "utility.identify",
        args=obj(f("box", INT), f("on", BOOL)),
        result=obj(f("delivered", BOOL), f("state", Ref("UtilityBoxState"))),
        doc="Make one box point at itself with the utility profile's `identify` "
        "pair, for the placement walk. Opens `PASSTHROUGH` if the box is `IDLE` "
        "and closes it again on the matching `off`; a console the user already "
        "has open keeps it. Delivery is confirmed by waiting for the sketch's "
        "own telemetry line. `delivered: false` is the ordinary answer for a "
        "box not at baseline or a port with another owner — the caller carries "
        "on by box number rather than failing. `off` never raises. "
        "`UTILITY_UNAVAILABLE` when the configured sketch declares no "
        "`identify` pair.",
    ),
    # ------------------------------------------------------------- rig wiring
    #
    # THE WIRING IS NOT A SETTING, and these commands are why. Settings are
    # shell-owned, pushed one-directionally, leniently parsed and silently
    # defaulting to a working value — right for a directory path, catastrophic
    # for a pin number, which has no safe default and fails by firing the wrong
    # valve. So the wiring is a sidecar-owned DOCUMENT instead
    # (`<data_dir>/hardware/rig.json`): validated on the way in, refused when it
    # is the wrong shape, and every problem located on the field that caused it.
    Command(
        "hardware.get",
        result=Ref("RigDocument"),
        doc="This rig's wiring and everything wrong with it "
        "(`TASKS.md#rig-wiring`). A rig never edited gets the shipped pinout "
        "as an editable document, so the editor always opens something real "
        "rather than a blank form.",
        section="Rig wiring",
    ),
    Command(
        "hardware.preview",
        args=obj(f("document", ANY)),
        result=Ref("RigSaved"),
        doc="Validate a wiring document and cost it, writing nothing. The "
        "editor calls it as the operator types, so a schema violation or a "
        "wiring rule (RIG101–RIG106) lands against the field that caused it; "
        "and it is what the save preflight shows, because `breaks` is the "
        "honest form of 'this applies to every task'. A well-formed document "
        "describing an impossible box is a successful reply carrying "
        "`problems`; `RIG_INVALID` only when it is not a document at all.",
    ),
    Command(
        "hardware.save",
        args=obj(
            f("document", ANY),
            f(
                "confirm",
                BOOL,
                doc="False ⇒ refuse with `RIG_WOULD_BREAK_TASKS` if the change "
                "would newly stop a saved task profile generating. True ⇒ write "
                "anyway. Rewiring a box is the operator's call and the app does "
                "not veto it — but it must not let it happen unnoticed.",
            ),
        ),
        result=Ref("RigSaved"),
        doc="Validate, then write: a document that fails validation is never "
        "written, so the file on disk is never one the app refuses. On success "
        "the cached channel map is cleared, **every stored task profile and "
        "every bundled sketch that opts into rig pins is regenerated** before "
        "the reply (pins are compiled into `TaskPins.h`, so a stale folder "
        "would flash the old pins and still compile), and `hardware.updated` "
        "is broadcast, with `sketches.updated` and `tasks.updated` from the "
        "rebuild. "
        "Refused with `RIG_IN_USE` while a session is set up or a box is running. "
        "A rig definition write: it waits for flashes already in progress, and "
        "everything that reads a generated folder waits for it "
        "(`TASKS.md#the-rig-definition`).",
    ),
    Command(
        "hardware.reset",
        result=Ref("RigDocument"),
        doc="Discard this rig's document and go back to the shipped wiring. A "
        "wiring change like any other: regenerates every profile and "
        "broadcasts `hardware.updated`, as `hardware.save` does. Replies in "
        "`hardware.get`'s shape so the editor re-renders from one shape. "
        "Refused with `RIG_IN_USE` while a session is set up or a box is running. "
        "A rig definition write: it waits for flashes already in progress, and "
        "everything that reads a generated folder waits for it "
        "(`TASKS.md#the-rig-definition`).",
    ),
    # ------------------------------------------------------- strobe vocabulary
    #
    # Every mutating command below refuses with `STROBE_SESSION_RUNNING` while
    # a session is set up or a box is running, runs as a rig definition write
    # (`TASKS.md#the-rig-definition`), writes
    # the machine's vocabulary document, regenerates every stored task profile
    # and bundled sketch (their `TaskPins.h` carries the codes), and broadcasts
    # `strobes.updated` with `sketches.updated` / `tasks.updated` from the
    # rebuild. `STROBE_VOCABULARY_UNREADABLE` from any of them while the
    # document is damaged.
    Command(
        "strobes.get",
        result=Ref("StrobeVocabulary"),
        doc="This machine's vocabulary (`TASKS.md#strobe-vocabulary`), for the "
        "Strobes page and the trial table's onset-code picker.",
        section="Strobe vocabulary",
    ),
    Command(
        "strobes.usage",
        args=obj(
            f("name", STR),
            f(
                "scan",
                BOOL,
                optional=True,
                doc="Also scan every recorded session this machine can reach. "
                "Long-running on a cold cache; publishes `strobes.scanProgress`, "
                "and the client raises its reply timeout.",
            ),
        ),
        result=Ref("StrobeUsage"),
        doc="Where a live or retired code is used, and whether retiring or "
        "removing it would be refused. Writes nothing except the scan cache. "
        "`STROBE_INVALID` for a name the vocabulary does not hold.",
    ),
    Command(
        "strobes.add",
        args=obj(
            f("name", STR, doc="Upper snake case, no `BF_` prefix; new across live AND retired."),
            f("code", INT, doc="Must be free: in bounds, unreserved, neither live nor retired."),
            f("rationale", STR, doc="What the code means. Required."),
            f("emittedOn", STR, optional=True),
        ),
        result=Ref("StrobeVocabulary"),
        doc="Issue a new live code. `STROBE_INVALID` when the name or number "
        "cannot be issued.",
    ),
    Command(
        "strobes.edit",
        args=obj(f("name", STR), f("rationale", STR), f("emittedOn", STR, optional=True)),
        result=Ref("StrobeVocabulary"),
        doc="Reword a live code's meaning. The name and number never change.",
    ),
    Command(
        "strobes.retire",
        args=obj(
            f("name", STR),
            f(
                "confirm",
                BOOL,
                doc="False ⇒ `STROBE_WOULD_BREAK_TASKS` if a saved task or a "
                "bundled sketch names the code. True ⇒ retire anyway.",
            ),
        ),
        result=Ref("StrobeVocabulary"),
        doc="Move a live code to `retired`: reserved forever, defined by no "
        "header. `STROBE_REQUIRED` for a port-slot code or one the shared "
        "firmware library names.",
    ),
    Command(
        "strobes.reinstate",
        args=obj(f("name", STR)),
        result=Ref("StrobeVocabulary"),
        doc="A retired code back to live under its own name, number and meaning.",
    ),
    Command(
        "strobes.remove",
        args=obj(
            f("name", STR),
            f("confirm", BOOL, doc="As `strobes.retire`'s."),
        ),
        result=Ref("StrobeVocabulary"),
        doc="Delete a code, returning its number to the free pool. Scans every "
        "recorded session this machine can reach first (publishes "
        "`strobes.scanProgress`; long-running on a cold cache), and refuses "
        "with `STROBE_IN_RECORDED_SESSION` if any contains it — the bar is "
        "not 'unused', it is 'never recorded'. `STROBE_REQUIRED` as for "
        "`strobes.retire`.",
    ),
    Command(
        "strobes.export",
        result=obj(f("document", ANY), f("filename", STR)),
        doc="The vocabulary as it travels to another machine, without this "
        "machine's stamps.",
    ),
    Command(
        "strobes.import",
        args=obj(
            f("document", ANY, doc="Another machine's exported vocabulary (v2 or v3)."),
            f("apply", BOOL, doc="False ⇒ plan only, write nothing."),
        ),
        result=obj(
            f("plan", Ref("StrobeImportPlan")),
            f("vocabulary", nullable(Ref("StrobeVocabulary")), doc="Null unless applied."),
        ),
        doc="Merge another machine's codes into this one. `STROBE_INVALID` for "
        "a file that is not a vocabulary; `STROBE_IMPORT_CONFLICT` when "
        "applying a plan with conflicts (`detail.conflicts`).",
    ),
    # ----------------------------------------------------------------- cohorts
    #
    # All cohort state lives in the sidecar's SQLite database. Every mutating
    # command below broadcasts `cohorts.updated`.
    Command(
        "cohorts.list",
        result=obj(f("cohorts", ListOf(Ref("CohortSummary")))),
        doc="Every cohort, archived included; the client filters.",
        section="Cohorts",
    ),
    Command(
        "cohorts.get",
        args=obj(f("id", STR)),
        result=_COHORT,
        doc="One cohort's full record, roster included — fetched when a cohort "
        "is opened, since `CohortSummary` carries no per-animal detail. "
        "`COHORT_NOT_FOUND` for an unknown id.",
    ),
    Command(
        "cohorts.create",
        args=obj(
            f("name", STR),
            f(
                "dataFolder",
                STR,
                optional=True,
                doc="An explicit folder wins. Omitted, it is derived from the "
                "configured `dataDirectory` and the name, suffixed until unused "
                "(`DATA.md#cohorts-animals-and-groups`).",
            ),
            f(
                "animals",
                ListOf(Ref("Animal")),
                optional=True,
                doc="The roster to create the cohort with, so the editor's "
                "Create is one call rather than a create plus a patch that "
                "could fail on its own and leave a named, empty cohort.",
            ),
            f(
                "groups",
                ListOf(Ref("Group")),
                optional=True,
                doc="Replaces the default group the create would otherwise "
                "mint. Validated together with `animals`, before the data "
                "folder is made — a rejected roster leaves nothing behind.",
            ),
        ),
        result=_COHORT,
        doc="Create a cohort and its data folder. The record is written before "
        "the folder, so a duplicate name (`COHORT_NAME_TAKEN`) or an invalid "
        "roster (`COHORT_INVALID`) creates no directory; a folder that can't "
        "be made (`DATA_FOLDER_INVALID`) rolls the record back.",
    ),
    Command(
        "cohorts.update",
        args=obj(f("id", STR), f("patch", Ref("CohortPatch"))),
        result=_COHORT,
        doc="Patch name, roster, groups or appearance. Also the commit path "
        "for an Auto-Balance preview from `cohorts.suggestGroups` — there is no "
        "separate apply. Renaming never moves the data folder; that is "
        "`cohorts.setDataFolder`.",
    ),
    Command(
        "cohorts.archive",
        args=obj(f("id", STR)),
        result=_COHORT,
        doc="Soft delete: the record and its data folder stay intact, and an "
        "archived cohort no longer reserves its name.",
    ),
    Command(
        "cohorts.restore",
        args=obj(f("id", STR)),
        result=_COHORT,
        doc="Un-archive. `COHORT_NAME_TAKEN` if an active cohort claimed the "
        "name while it was archived.",
    ),
    Command(
        "cohorts.delete",
        args=obj(f("id", STR), f("confirm", BOOL, doc="Must be literally true, or `BAD_MESSAGE`.")),
        result=obj(f("deleted", BOOL)),
        doc="Permanent delete of the bookkeeping only. `COHORT_NOT_ARCHIVED` "
        "unless archived first — the deliberate two-step guard. **Never "
        "touches the data folder on disk.**",
    ),
    Command(
        "cohorts.setDataFolder",
        args=obj(
            f("id", STR),
            f("path", STR),
            f(
                "moveExisting",
                BOOL,
                doc="Selects between two intents. True moves the cohort's data "
                "and refuses (`DATA_FOLDER_INVALID`) a destination that isn't "
                "empty — merging two archives can silently collide filenames. "
                "False writes nothing and re-points the cohort, so a full "
                "destination is expected: that is how a cohort attaches to an "
                "existing archive.",
            ),
        ),
        result=_COHORT,
        doc="The explicit relocate, distinct from renaming "
        "(`DATA.md#data-folder`). Moving the contents moves the records' "
        "stored paths with the files, journalled so a crash is finished or "
        "undone at the next start; refused (`DATA_FOLDER_INVALID`) while a "
        "session is set up or running, and `INTERNAL` while an analytics walk "
        "runs. Long-running; the client raises its reply timeout.",
    ),
    Command(
        "cohorts.moveAnimals",
        args=obj(
            f("cohortId", STR, doc="The source cohort."),
            f(
                "animalIds",
                ListOf(STR),
                doc="Roster animals, former members, or ids known only from "
                "files (`Cohort.formerAnimals`).",
            ),
            f("destinationCohortId", STR),
            f(
                "destinationGroupId",
                STR,
                optional=True,
                doc="Where an animal carried onto the destination's roster "
                "lands. Default: its first group.",
            ),
            f("apply", BOOL, optional=True, doc="Default false: a preview that changes nothing."),
        ),
        result=Ref("AnimalMovePlan"),
        doc="Move animals, their files and their history to another cohort "
        "(`DATA.md#moving-animals-between-cohorts`). The files move into the "
        "destination's data folder; run records, recovered runs and notes "
        "about the animals follow, and notes about a session both cohorts ran "
        "are copied. An apply re-plans rather than replaying the preview, and "
        "is crash-safe: interrupted, it is finished or undone at the next "
        "start. `ANIMAL_MOVE_REFUSED` (with the plan in `detail`) when the "
        "apply's plan has refusals; `INTERNAL` while an analytics walk runs. "
        "Broadcasts `cohorts.updated` and `logbook.updated` after an apply. "
        "Long-running; the client raises its reply timeout.",
    ),
    Command(
        "cohorts.suggestGroups",
        args=obj(
            f("id", STR),
            f("groupCount", INT, optional=True),
            f("maxGroupSize", INT, optional=True),
            f("balanceBySex", BOOL, optional=True),
        ),
        result=Ref("GroupProposal"),
        doc="**Non-mutating** Auto-Balance preview — a balanced round-robin "
        "over the roster (`DATA.md#cohorts-animals-and-groups`). The user "
        "applies it via `cohorts.update`.",
    ),
    # --------------------------------------------------- prefixes and sessions
    #
    # Prefixes and session records live in the same SQLite database as
    # cohorts. The per-strobe file writing happens sidecar-side and is not a
    # command (`DATA.md#crash-safety`).
    Command(
        "prefixes.list",
        result=obj(f("prefixes", ListOf(Ref("Prefix")))),
        doc="Every session prefix. Prefixes are global, shared across all "
        "cohorts (`DATA.md#sessions-and-runs`).",
        section="Prefixes and sessions",
    ),
    Command(
        "prefixes.create",
        args=obj(f("name", STR)),
        result=obj(f("prefix", Ref("Prefix"))),
        doc="Name-unique; rejected with `PREFIX_NAME_TAKEN`. Broadcasts "
        "`prefixes.updated`.",
    ),
    Command(
        "prefixes.delete",
        args=obj(f("id", STR)),
        result=obj(f("deleted", BOOL)),
        doc="Removes the prefix from the list only — never touches folders "
        "already written under the name. Broadcasts `prefixes.updated`.",
    ),
    Command(
        "sessions.suggestNumber",
        args=obj(f("prefixId", STR)),
        result=obj(
            f(
                "suggestion",
                nullable(STR),
                doc="The prefix's highest numeric session number + 1; null when "
                "it has no numeric history.",
            ),
            f(
                "sameDayNumbers",
                ListOf(STR),
                doc="Numbers already used for this prefix today. Drives the "
                "**soft** reuse warning — reuse is legal, never blocked.",
            ),
        ),
        doc="The session-number pre-fill for the setup step. Aborted sessions "
        "count toward neither field: they never wrote data, so their numbers "
        "stay claimable.",
    ),
    Command(
        "sessions.create",
        args=obj(
            f("cohortId", STR),
            f("prefixId", STR),
            f("sessionNumber", STR, doc="Free text; required and non-blank."),
            f(
                "durationMinutes",
                INT,
                optional=True,
                doc="Optional per-box time limit, a positive whole number of "
                "minutes. The sidecar sends `STOP` to each box that long after "
                "*that box's* start — per box, because boxes can be started "
                "individually. Omitted means the session runs until stopped.",
            ),
            f(
                "recording",
                BOOL,
                optional=True,
                doc="True makes the session an Intan recording as well "
                "(`RECORDING.md#start-and-end`): `Session.recording` is then "
                "`{runs: []}` rather than null, and starting a group refuses "
                "unless `intan.configure` has run for it.",
            ),
        ),
        result=_SESSION,
        doc="Create a session in status `configuring` and make its folder. "
        "`SESSION_NOT_READY` if no group in the cohort has a box-assigned "
        "animal; `SESSION_INVALID` for an unknown cohort or prefix, a blank "
        "number, a bad duration, or a folder that can't be created. Broadcasts "
        "`session.lifecycle`.",
    ),
    Command(
        "sessions.abandon",
        args=obj(f("sessionId", STR)),
        result=_SESSION,
        doc="Discard a session still in `configuring` (the mapping step's "
        "Back): marks it `aborted`, clears any confirmed-but-unstarted mapping "
        "from the runner, drops an unstarted recording setup, and hands the "
        "rig back to the utility baseline. Nothing on disk is touched. "
        "`SESSION_INVALID` once a group has run.",
    ),
    Command(
        "sessions.confirmMapping",
        args=obj(f("sessionId", STR), f("groupId", STR), f("boxes", ListOf(Ref("SessionBoxMapping")))),
        result=obj(f("ok", BOOL)),
        doc="Load one group's box → animal → sketch mapping into the runner and "
        "build each box's `START` line from its sketch's Task Profile and "
        "`config`. `TASK_PROFILE_INVALID` when a line would exceed "
        "`START_LINE_MAX` — refused because the board cannot report a "
        "truncated `START` and would run on whichever values fit "
        "(`TASKS.md#the-start-line`). `SESSION_INVALID` for a mapping missing "
        "its box, sketch, or an animal of this cohort. From here until the "
        "session lets go the rig is **held**: no baseline restore runs. "
        "Broadcasts `session.lifecycle`. "
        "Waits for a rig definition write in progress (`TASKS.md#the-rig-definition`).",
    ),
    Command(
        "sessions.status",
        args=obj(f("sessionId", STR)),
        result=obj(
            f("session", Ref("Session")),
            f(
                "groupId",
                nullable(STR),
                doc="The group on the rig. Null unless this is the held session "
                "with a group mapped: before a mapping is confirmed, between groups, "
                "and for any session that does not hold the rig.",
            ),
            f(
                "boxes",
                ListOf(Ref("SessionBox")),
                doc="The rig's boxes; empty unless this is the held session.",
            ),
        ),
        doc="What Mission Control renders. The runner is the authority on the "
        "confirmed mapping and which boxes are live, so a reopened window asks "
        "rather than trusting a stale copy.",
    ),
    Command(
        "sessions.startAll",
        args=obj(f("sessionId", STR)),
        result=_SESSION,
        doc="Enter `IN_SESSION` on every box of the confirmed mapping not "
        "already running, open the group's run, and mark the session "
        "`running`. On a recording session RHX recording begins **before any "
        "box starts**, and an `INTAN_*` refusal (no recording configured for "
        "this group, RHX unreachable) leaves every box untouched — a session "
        "quietly missing its electrophysiology cannot be re-run. Every box not "
        "running must carry its mapped sketch's current build first "
        "(`ARCHITECTURE.md#what-a-board-carries`): otherwise `SESSION_INVALID` "
        "with `detail.boxes` naming each one, before RHX or any box starts. "
        "Broadcasts `session.lifecycle`. Long-running on a recording session; the client "
        "raises its reply timeout.",
    ),
    Command(
        "sessions.endGroup",
        args=obj(f("sessionId", STR)),
        result=_SESSION,
        doc="End the current group's runs, close its `groupRuns` entry, clear "
        "the runner's mapping and hand the rig back to the utility baseline — "
        "leaving the session **between groups**: still `running` and held, "
        "`groupId` null, no boxes. The sidecar never picks the next group and "
        "never finalizes here; the operator picks any group (one that already "
        "ran may run again) or ends the session with `sessions.end`. Stops "
        "boxes as `sessions.end` does, gracefully on a recording.",
    ),
    Command(
        "sessions.resume",
        args=obj(f("sessionId", STR)),
        result=_SESSION,
        doc="Continue one of **today's** sessions with another group — a "
        "crash-orphaned `running` one (the app closed between groups) or a "
        "`completed` one ended too early. Closes any group run a crash left "
        "open, sets `running`, and re-holds the session in the between-groups "
        "state `sessions.endGroup` leaves. Nothing resumes mid-group. "
        "`SESSION_INVALID` for another day's session (its folder is named for "
        "that date), one that never ran a group, or while a different session "
        "is held.",
    ),
    Command(
        "sessions.end",
        args=obj(f("sessionId", STR)),
        result=_SESSION,
        doc="Finish the session: stop every box, finalize files, close the "
        "open group run, mark it `completed`, and release the rig to the "
        "utility baseline. A behavior-only session sends `STOP` and waits only "
        "briefly, cutting the trial in flight; a **recording** waits for each "
        "box's own end strobe (`intan.status.waitingOn`, cut short by "
        "`intan.forceStop`), then post-rolls and stops RHX "
        "(`RECORDING.md#start-and-end`). Only the **held** session's boxes are "
        "stopped: closing out a crash orphan while another session runs marks "
        "the orphan and touches nothing live. The only command that finishes a "
        "session. Long-running on a recording; the client raises its reply "
        "timeout.",
    ),
    Command(
        "sessions.active",
        result=Ref("ActiveSessions"),
        doc="The global 'what is running?' query — argument-free, so a client "
        "with no prior knowledge of ids (the Launch page, a reconnecting "
        "window) can discover the running session. The `running` slot comes "
        "from the live runner; `configuring` and `stale` come from the "
        "database. The same payload is broadcast as `session.lifecycle`.",
    ),
    # ----------------------------------------------------------- task profiles
    #
    # NOTHING HERE FLASHES. Saving generates a sketch folder under
    # `<data_dir>/tasks/` that `discovery` then finds, so `port.flash` takes it
    # by path like any other — which is what keeps the session flow,
    # `taskDefaults` and Analytics free of a special case for a profile-backed
    # run.
    Command(
        "tasks.getProfile",
        args=obj(f("sketchPath", STR)),
        result=union(Ref("TaskProfile"), obj(f("profile", NULL))),
        doc="Read the `task.json` beside a sketch's `.ino` "
        "(`TASKS.md#task-profile`). A sketch with none returns "
        "`{profile: null}` — fully supported (bare `START`, raw strobe log). "
        "`TASK_PROFILE_INVALID` when the file exists but is malformed. Works "
        "the same on a bundled sketch and on one generated from a saved task. "
        "Waits for a rig definition write in progress (`TASKS.md#the-rig-definition`).",
        section="Task profiles",
    ),
    Command(
        "tasks.list",
        result=obj(f("tasks", ListOf(Ref("TaskEntry")))),
        doc="This rig's saved task profiles (`TASKS.md#task-definitions`). "
        "Reads and validates each definition, never generates, so the list "
        "stays cheap however many exist.",
    ),
    Command(
        "tasks.get",
        args=obj(f("taskId", STR)),
        result=obj(
            f("definition", ANY, doc="The definition document, verbatim."),
            f("diagnostics", ListOf(Ref("TaskDiagnostic"))),
        ),
        doc="One definition and everything currently wrong with it. The "
        "diagnostics are recomputed rather than stored, because most of them "
        "depend on the WIRING — a task saved clean can be broken by a rewiring "
        "it never saw. `TASK_NOT_FOUND` for an unknown id.",
    ),
    Command(
        "tasks.preview",
        args=obj(f("definition", ANY)),
        result=Ref("TaskPreview"),
        doc="Compile an unsaved definition and say what is wrong with it, "
        "writing nothing. The editor calls it as the operator types, so a "
        "problem lands against the field that caused it; it also carries the "
        "built `START` line's length, the one budget an operator can exhaust "
        "without noticing. `TASK_INVALID` only when the document is not a "
        "definition.",
    ),
    Command(
        "tasks.save",
        args=obj(f("definition", ANY)),
        result=Ref("TaskSaved"),
        doc="Write the definition and regenerate its sketch. **Always saves, "
        "even with diagnostics** — a half-finished task must be savable, and "
        "the gate is flashing, not saving. Refused with `TASK_INVALID` only "
        "when the name collides with a bundled sketch or another saved task "
        "(case-insensitively): two sketches with one name make the picker "
        "ambiguous, and two tasks would share one folder. Broadcasts "
        "`tasks.updated` and `sketches.updated`, since a saved profile is also "
        "a sketch. "
        "Refused with `RIG_IN_USE` while a session is set up or a box is running. "
        "A rig definition write: it waits for flashes already in progress, and "
        "everything that reads a generated folder waits for it "
        "(`TASKS.md#the-rig-definition`).",
    ),
    Command(
        "tasks.delete",
        args=obj(f("taskId", STR)),
        result=obj(f("deleted", BOOL)),
        doc="Remove the definition and its generated sketch folder. "
        "Idempotent: deleting what is already gone is a successful "
        "`{deleted: false}`, because two clients racing on one task is not an "
        "error. "
        "Refused with `RIG_IN_USE` while a session is set up or a box is running. "
        "A rig definition write: it waits for flashes already in progress, and "
        "everything that reads a generated folder waits for it "
        "(`TASKS.md#the-rig-definition`).",
    ),
    # ------------------------------------------------------------------ backup
    Command(
        "backup.syncNow",
        result=Ref("SyncResult"),
        doc="The explicit backfill (`DATA.md#backup-mirroring`): walks every "
        "cohort data folder, mirrors anything missing or stale, then backs up "
        "`ephymeris.db`. Mirroring itself takes no command — it runs off "
        "`backupDirectory` — and setting a directory deliberately does **not** "
        "backfill, since that could start an unannounced multi-gigabyte copy "
        "to a network share; this is the deliberate version, and the way to "
        "prove a target works. `BACKUP_UNAVAILABLE` with no directory set or "
        "a sync already running. Long-running; the client raises its reply "
        "timeout.",
        section="Backup",
    ),
    # --------------------------------------------------------------- analytics
    #
    # A corrupt or missing file is DATA, NOT AN ERROR: it yields a run with a
    # non-ok status plus a warning, and the command still succeeds. One
    # unreadable `.json` must never blank a year of history.
    Command(
        "sessions.list",
        args=obj(f("cohortId", STR), f("includeAborted", BOOL, optional=True)),
        result=obj(f("sessions", ListOf(Ref("SessionListItem")))),
        doc="A cohort's sessions in chronological order, including the "
        "payload-only sessions that adopted archive runs are grouped under. "
        "**Never touches the filesystem**, so selectors populate instantly "
        "while `analytics.summary` is still reading files.",
        section="Analytics",
    ),
    Command(
        "analytics.summary",
        args=obj(
            f("cohortId", STR),
            f("sessionIds", ListOf(STR), optional=True),
            f("animalIds", ListOf(STR), optional=True),
            f("minCountedTrials", INT, optional=True),
        ),
        result=Ref("AnalyticsSummary"),
        doc="The whole cohort table in **one** call (`DATA.md#analytics-views`): "
        "sessions, animals, run summaries, profile groups, counts and "
        "warnings. Every later session or animal selection filters it "
        "client-side rather than costing a round trip. A cold first index "
        "reads every historical run and publishes `analytics.progress`; "
        "long-running, so the client raises its reply timeout. A corrupt or "
        "missing file is a run with a non-ok `status` plus a warning, never a "
        "failed command. `COHORT_NOT_FOUND` for an unknown cohort.",
    ),
    Command(
        "analytics.setFalseStart",
        args=obj(
            f("cohortId", STR),
            f("runId", STR),
            f(
                "falseStart",
                nullable(BOOL),
                doc="True sets the run aside, false counts it whatever the rule "
                "says, null hands it back to the rule.",
            ),
        ),
        result=obj(f("runId", STR)),
        doc="A person's ruling on one run (`DATA.md#false-starts`), stored in "
        "`run_flags`. Broadcasts `logbook.updated` for the run's session, since "
        "what changed is recomputed around it; the client refetches "
        "`analytics.summary`. `BAD_MESSAGE` for a run the cohort does not hold.",
    ),
    Command(
        "analytics.series",
        args=obj(
            f(
                "runIds",
                ListOf(STR),
                doc="Non-empty. Plural so one session's animals are one call; "
                "more than `MAX_SERIES_RUNS` (`analytics/service.py`) is "
                "`BAD_MESSAGE`.",
            ),
            f("mode", lit("rolling", "cumulative"), optional=True, doc="Default `rolling`."),
            f("metricIds", ListOf(STR), optional=True),
        ),
        result=Ref("SeriesResult"),
        doc="Per-run learning-curve data (`DATA.md#derived-metrics`), plus each "
        "run's strategy-plane `trail` and per-trial `trials` tape, which ride "
        "here because the file is already open and decoded. The x-axis is "
        "the counted-trial index and is implicit.",
    ),
    Command(
        "analytics.rescan",
        args=obj(
            f(
                "cohortId",
                STR,
            ),
            f(
                "adoptOrphans",
                BOOL,
                optional=True,
                doc="Defaults true. False makes the scan **read-only**: nothing "
                "is adopted and nothing is pruned, so a caller can ask what the "
                "walk sees without changing the index.",
            ),
        ),
        result=Ref("RescanResult"),
        doc="The explicit archive walk (`DATA.md#reading-the-archive`) — "
        "expensive reconciliation is a deliberate user action, never a side "
        "effect of opening a view. Reconciles **both ways**: files no record "
        "points at are adopted, and records pointing at files the disk no "
        "longer has are pruned — after records an earlier relocate left at "
        "the old folder are re-pointed (`rehomed`). Publishes "
        "`analytics.progress`. `INTERNAL` "
        "when another analytics walk is already running. Long-running; the "
        "client raises its reply timeout.",
    ),
    Command(
        "analytics.recentSessions",
        args=obj(
            f(
                "limit",
                INT,
                optional=True,
                doc="Default `DEFAULT_RECENT_LIMIT` (`analytics/service.py`).",
            )
        ),
        result=obj(f("sessions", ListOf(Ref("DiskSession")))),
        doc="The N most recent session folders across every active cohort's "
        "archive, by folder-name date. **Directory names only — no file is "
        "ever opened**, which keeps this cheap enough for the Dashboard where "
        "the rescan is not. Sees sessions another Ephymeris machine wrote into "
        "a shared archive, which `sessions.list` (this machine's database) "
        "cannot; `DiskSession.recorded` says which.",
    ),
    Command(
        "sessions.recover",
        args=obj(f("cohortId", STR)),
        result=Ref("RecoverResult"),
        doc="The crash-recovery backfill (`DATA.md#crash-recovery`): rebuilds "
        "`.json`/`.mat` from orphaned write-ahead `.tsv` files, using the same "
        "traversal as `analytics.rescan` and the same explicit-action "
        "discipline. A `.tsv` with a footer keeps its recorded stop reason; a "
        "footer-less (crashed) one gets 'recovered after crash'; a "
        "pre-Ephymeris log, which never had a footer, gets 'recovered from a "
        "legacy log'. "
        "`SESSION_INVALID` while any box is running — a live run's `.tsv` has "
        "no `.json` yet and is not an orphan. Long-running; the client raises "
        "its reply timeout.",
    ),
    Command(
        "sessions.tidy",
        args=obj(
            f("cohortId", STR),
            f("apply", BOOL, optional=True, doc="Default false: a preview that changes nothing."),
        ),
        result=Ref("TidyPlan"),
        doc="Merge session records that share prefix, number and date — one "
        "folder, split by a day that went wrong — into the earliest record "
        "holding data, and delete records with no run, recording or file "
        "behind them (`DATA.md#reading-the-archive`). An apply re-plans rather "
        "than replaying the preview. **Database only**, except the empty "
        "folder of a deleted record. Never touches the held session (or its "
        "folder-mates) nor a set-up from today; those are listed in "
        "`skipped`. Broadcasts `session.lifecycle` after an apply. `INTERNAL` "
        "when another analytics walk is already running.",
    ),
    # --------------------------------------------------------- Intan recording
    #
    # RHX MAY BE SLOW, ABSENT OR DEAD AND NONE OF THAT MAY STALL OR FAIL A
    # BEHAVIOR SESSION -- the Backup mirror's rule, restated. The one exception
    # is starting: a recording that cannot start refuses before any box does.
    Command(
        "intan.status",
        result=Ref("IntanStatus"),
        doc="The current recording snapshot (`RECORDING.md#talking-to-rhx`). "
        "Also replayed on connect and pushed as the `intan.status` event, so "
        "this exists for a window that attaches mid-session — a scope pop-up.",
        section="Intan recording",
    ),
    Command(
        "intan.connect",
        result=Ref("IntanStatus"),
        doc="Open RHX's command socket now rather than at the next background "
        "attempt. `INTAN_UNAVAILABLE` says what to click in RHX: Network → "
        "Remote TCP Control → Connect, on the Commands tab. That is the only "
        "manual step; the sidecar opens the waveform and spike sockets itself.",
    ),
    Command(
        "intan.disconnect",
        result=Ref("IntanStatus"),
        doc="Close the sockets. `INTAN_NOT_READY` while recording: closing "
        "them would not stop RHX, but it would blind the app to it.",
    ),
    Command(
        "intan.configure",
        args=obj(f("sessionId", STR), f("groupId", STR), f("config", Ref("RecordingConfig"))),
        result=Ref("IntanStatus"),
        doc="Apply a recording setup to RHX **for one group run** — animals, "
        "and so ports and probes, change between groups "
        "(`RECORDING.md#recording-walkthrough`). Connects first if needed. The "
        "three values a recording cannot be wrong about — file format, save "
        "path, base filename — are read back and refused on a mismatch "
        "(`INTAN_COMMAND_FAILED`), which is the only thing that catches RHX "
        "accepting a path and storing it cut at its first space. An RHX left "
        "in Run is stopped (saving parameters are ignored while it runs); one "
        "already recording is refused and not touched. `INTAN_NOT_READY` names "
        "the first problem: the rig's wiring declares no `sync` channel, a box "
        "with no digital input, a port with no headstage, two boxes claiming "
        "one channel, or nothing selected to save. `SESSION_INVALID` for a "
        "session that is not a recording. Long-running; the client raises its "
        "reply timeout.",
    ),
    Command(
        "intan.parseProbeMap",
        args=obj(f("path", STR)),
        result=obj(f("probeMap", ANY)),
        doc="Parse an Intan probe-map XML for the setup preview. RHX has no "
        "TCP command to load a probe map, so Ephymeris reads the same file "
        "the operator would have loaded there. Inheriting attributes are "
        "resolved here; coordinates pass through **unflipped** (Intan's y is "
        "up — flipping is the renderer's job). `INTAN_NOT_READY` for a file "
        "that can't be parsed.",
    ),
    Command(
        "intan.probeMap",
        args=obj(f("box", INT)),
        result=obj(f("probeMap", ANY)),
        doc="The probe map configured for this box in the current recording, "
        "or null.",
    ),
    Command(
        "intan.setThreshold",
        args=obj(f("channel", STR), f("microvolts", INT)),
        result=obj(f("channel", STR), f("microvolts", INT)),
        doc="Set one channel's spike threshold, −5000…5000 µV, read back from "
        "RHX. Sent by the SpikeScope's draggable threshold line. The reply's "
        "channel name is upper-cased.",
    ),
    Command(
        "intan.scope.open",
        args=obj(
            f("kind", Ref("ScopeKind")),
            f("box", INT),
            f("channel", nullable(STR), optional=True, doc="Required for every kind but `probemap`."),
            f("params", MapOf(ANY), optional=True),
        ),
        result=obj(f("scopeId", STR)),
        doc="Begin publishing one live view as `intan.scope.data` "
        "(`RECORDING.md#live-windows`). RHX cannot be asked to open its own "
        "SpikeScope/PSTH/ISI windows over TCP, so these are computed here from "
        "RHX's data sockets. A `spikescope` also asks RHX to stream that "
        "channel's highpass band, and at most `MAX_SCOPED_CHANNELS` "
        "(`intan/service.py`) channels may be scoped at once — beyond a "
        "handful, TCP stops keeping up with acquisition. `INTAN_NOT_READY` for "
        "a box not in the configured recording or a channel outside the box's "
        "claimed range.",
    ),
    Command(
        "intan.scope.update",
        args=obj(
            f("scopeId", STR),
            f("channel", nullable(STR), optional=True),
            f("params", MapOf(ANY), optional=True),
        ),
        result=obj(f("ok", BOOL, doc="False when the scope is already gone.")),
        doc="Change a scope's channel or parameters in place, **and its "
        "keepalive**: a scope with no update for `SCOPE_TTL_S` "
        "(`intan/service.py`) is swept, which is how a window that was killed "
        "rather than closed stops costing RHX a streamed channel. A scope "
        "window sends one periodically even when nothing changed.",
    ),
    Command(
        "intan.scope.close",
        args=obj(f("scopeId", STR)),
        result=obj(f("ok", BOOL)),
        doc="Stop publishing a scope. Idempotent.",
    ),
    Command(
        "intan.forceStop",
        result=obj(f("ok", BOOL)),
        doc="Stop waiting for boxes to finish their trials during a graceful "
        "end; the recording is then stopped at once.",
    ),
    # ------------------------------------------------------------ session log
    Command(
        "logbook.cohort",
        args=obj(f("cohortId", STR)),
        result=Ref("LogbookCohort"),
        doc="A cohort's notes, session fields and what-changed entries "
        "(`DATA.md#the-session-log`). **Database only**, like `sessions.list`. "
        "`COHORT_NOT_FOUND` for an unknown cohort.",
        section="Session log",
    ),
    Command(
        "logbook.addNote",
        args=obj(
            f("sessionId", STR),
            f("tag", Ref("NoteTag")),
            f("body", STR),
            f("scope", Ref("NoteScope"), optional=True, doc="Default: the whole session."),
            f("carryForward", BOOL, optional=True),
            f("at", STR, optional=True, doc="ISO with an offset. Default: now."),
        ),
        result=obj(f("note", Ref("SessionNote"))),
        doc="Add a note to a session, running or finished. `SESSION_INVALID` "
        "for an unknown session, a recovered-files session (no record to note "
        "against), an unknown tag, a blank body, or an animal outside the "
        "cohort. Broadcasts `logbook.updated`.",
    ),
    Command(
        "logbook.editNote",
        args=obj(
            f("noteId", STR),
            f("tag", Ref("NoteTag"), optional=True),
            f("body", STR, optional=True),
            f("scope", Ref("NoteScope"), optional=True),
            f("carryForward", BOOL, optional=True),
            f("at", STR, optional=True),
        ),
        result=obj(f("note", Ref("SessionNote"))),
        doc="Change any of a note's fields; an absent field is kept. Stamps "
        "`editedAt`. Same refusals as `logbook.addNote`, plus an unknown or "
        "deleted note. Broadcasts `logbook.updated`.",
    ),
    Command(
        "logbook.deleteNote",
        args=obj(f("noteId", STR)),
        result=obj(),
        doc="Hide a note. A soft delete: the row stays in the database with "
        "`deleted_at` set, and is never sent again. Broadcasts `logbook.updated`.",
    ),
    Command(
        "logbook.resolveFlag",
        args=obj(
            f("noteId", STR),
            f("resolved", BOOL, doc="False reopens a resolved flag."),
            f(
                "sessionId",
                nullable(STR),
                optional=True,
                doc="The session it was dealt with during; null or absent when "
                "outside one (Step 1, before the session exists).",
            ),
        ),
        result=obj(f("note", Ref("SessionNote"))),
        doc="Resolve or reopen a carry-forward flag. `SESSION_INVALID` for a "
        "note that is not flagged. Broadcasts `logbook.updated`.",
    ),
    Command(
        "logbook.setSessionLog",
        args=obj(
            f("sessionId", STR),
            f("operator", nullable(STR), optional=True),
            f("summary", nullable(STR), optional=True),
        ),
        result=obj(f("log", Ref("SessionLog"))),
        doc="Set a session's operator and/or summary; an absent field is kept, "
        "a blank one cleared. Broadcasts `logbook.updated`.",
    ),
    Command(
        "logbook.openFlags",
        args=obj(f("cohortId", STR)),
        result=obj(f("notes", ListOf(Ref("SessionNote")))),
        doc="A cohort's unresolved carry-forward notes, oldest first — what "
        "Step 1 and the running session show.",
    ),
)


# --- Events (server → client) ----------------------------------------------

EVENTS = (
    Event(
        "server.hello",
        Ref("ServerHello"),
        doc="First frame on every connection, before `auth`.",
    ),
    Event(
        "port.state",
        Ref("PortStateData"),
        doc="Emitted on **every** transition, and replayed for all six boxes "
        "on connect (with `prev` equal to `state`). The client renders this and "
        "never predicts a transition.",
    ),
    Event(
        "port.output",
        Ref("PortOutputData"),
        doc="Passthrough console lines, **batched** on a ~20 Hz tick per port "
        "rather than one message per line, with sent commands interleaved as "
        "`tx` so scrollback stays chronological. Never persisted beyond the "
        "sidecar's capped in-memory ring buffer "
        "(`ARCHITECTURE.md#flashing-reset-and-passthrough`).",
    ),
    Event(
        "port.telemetry",
        Ref("PortTelemetry"),
        doc="Live metrics for a task started from Debug Mode with "
        "`port.sendStart`, scored by the **same `MetricSet`** a session uses so "
        "the bench and the session never disagree about what P(hit) means. "
        "Sent when the run is armed, at most once per `port.output` batch "
        "after that, and once more when it ends. Not replayed on connect; "
        "every payload is the whole picture.",
    ),
    Event(
        "boards.presence",
        Ref("BoardsPresenceData"),
        doc="The out-of-band `arduino-cli board list` poll "
        "(`ARCHITECTURE.md#boxes-and-boards`). Never opens a port, so it never "
        "contends with the port state machine. Includes boards bound to no "
        "box (`boxId: null`) so Settings can offer them. Replayed on connect.",
    ),
    Event(
        "flash.progress",
        Ref("FlashProgressData"),
        doc="One line of `arduino-cli` output during `port.flash`, carrying "
        "the causing command's `corr`.",
    ),
    Event(
        "sketches.updated",
        Ref("SketchDiscovery"),
        doc="Pushed whenever discovery re-runs for any reason; replayed on "
        "connect.",
    ),
    Event(
        "cohorts.updated",
        Ref("CohortsUpdatedData"),
        doc="The full cohort list, pushed whenever it changes and replayed on "
        "connect — keeps every window in sync without polling.",
    ),
    Event(
        "prefixes.updated",
        Ref("PrefixesUpdatedData"),
        doc="The full prefix list, pushed after `prefixes.create` or "
        "`prefixes.delete` and replayed on connect — the `cohorts.updated` "
        "pattern.",
    ),
    Event(
        "session.telemetry",
        Ref("BoxTelemetry"),
        doc="Pushed on every strobe that updates a rolling live metric. Not "
        "batched like `port.output`: metric updates are far lower-frequency "
        "than raw strobes.",
    ),
    Event(
        "session.animalEnded",
        Ref("AnimalEnded"),
        doc="One animal's run finalized and recorded.",
    ),
    Event(
        "logbook.updated",
        Ref("LogbookUpdated"),
        doc="A session log changed: a note or session field was written, a run "
        "finalized (its what-changed entry appeared), a session ended (its "
        "clock closed), or a tidy moved notes between records. A pointer, not "
        "the data — the client refetches `logbook.cohort`. Not replayed on connect.",
    ),
    Event(
        "session.lifecycle",
        Ref("ActiveSessions"),
        doc="Broadcast whenever session identity or status changes — create, "
        "abandon, confirmMapping, startAll (or a group's first "
        "`port.startSession`), endGroup, resume, end, and an applied tidy. A "
        "full snapshot, not a delta: a second window learns 'ended' by seeing "
        "`running: null`, with no merge logic to get wrong. Per-box liveness "
        "is deliberately not re-broadcast here — `port.state` is that channel, "
        "and `boxes[].running` in the snapshot is point-in-time.",
    ),
    Event(
        "hardware.updated",
        Ref("RigStatus"),
        doc="Broadcast after a successful `hardware.save` or `hardware.reset`. "
        "Every client must drop any cached copy of the channel map: the wiring "
        "is a fact about this rig that an operator can change between two "
        "reads, not a fact about the build.",
    ),
    Event(
        "strobes.updated",
        Ref("StrobeVocabulary"),
        doc="Broadcast after every successful vocabulary edit. Clients drop any "
        "cached copy; task profiles arrive separately on `tasks.updated`.",
    ),
    Event(
        "strobes.scanProgress",
        Ref("StrobeScanProgress"),
        doc="Progress of an archive scan for `strobes.usage` or `strobes.remove`, "
        "every few dozen files.",
    ),
    Event(
        "utility.updated",
        Ref("UtilityStatus"),
        doc="The utility baseline's whole picture, on connect and whenever any "
        "box's belief changes — a restore starting or finishing, a hold going "
        "on or off, an identify light. The only progress channel "
        "`utility.ensure` has, since that command returns before flashing "
        "starts.",
    ),
    Event(
        "backup.status",
        Ref("BackupStatus"),
        doc="Backup mirroring's state (`DATA.md#backup-mirroring`): on connect, "
        "on a settings push that changes the directory, and when the state "
        "changes or something is actually copied — deliberately not every "
        "quiet tick. An ordinary mirroring failure surfaces only here, as "
        "`state: \"failed\"`; there is no command to attribute it to.",
    ),
    Event(
        "analytics.progress",
        Ref("AnalyticsProgress"),
        doc="Progress of a long analytics read (`walking` during a rescan, "
        "`reading` while indexing runs), so a cold index over a network-mounted "
        "archive reads as working rather than hung. Published on phase change "
        "and every few files — never per file.",
    ),
    Event(
        "sidecar.error",
        Ref("SidecarErrorData"),
        doc="A failure with no command to attribute it to. Emitted by the "
        "session runner when a mid-session `.tsv` write fails (disk full, "
        "permissions) with `code: \"INTERNAL\"`, a message naming the box, and "
        "`detail: {box}` (`DATA.md#crash-safety`).",
    ),
    Event(
        "tasks.updated",
        Ref("TasksUpdatedData"),
        doc="This rig's task profiles changed — saved, deleted, or regenerated "
        "because the wiring moved. Replayed on connect and pushed on change, "
        "the `sketches.updated` pattern. It arrives WITH a `sketches.updated`, "
        "never instead of one: a saved profile is also a new sketch.",
    ),
    Event(
        "intan.status",
        Ref("IntanStatus"),
        doc="The recording subsystem's full snapshot, on every change and on "
        "connect. A lost command socket mid-recording is `state: \"error\"`, "
        "never a session failure — RHX keeps recording on its own when the "
        "socket drops.",
    ),
    Event(
        "intan.scope.data",
        Ref("ScopeData"),
        doc="One live view's payload, only while that scope is open "
        "(`RECORDING.md#live-windows`). A `spikescope` is **incremental** — "
        "the snippets added since the last send; `psth`, `isi` and `probemap` "
        "are whole and sent less often. Never persisted — like `port.output`, "
        "it is a view of data whose durable copy is RHX's own files.",
    ),
)


# --- Error codes ------------------------------------------------------------

ERRORS = (
    ErrorCode("BAD_MESSAGE", "Malformed JSON, a non-object frame, or invalid args."),
    ErrorCode("UNKNOWN_COMMAND", "Unrecognized `cmd`."),
    ErrorCode("UNAUTHORIZED", "Missing or invalid token, or a first message that isn't `auth`."),
    ErrorCode(
        "PROTOCOL_VERSION_MISMATCH",
        "`v` does not match the sidecar's protocol version; rejected rather "
        "than parsed best-effort.",
    ),
    ErrorCode(
        "ILLEGAL_TRANSITION",
        "Operation not permitted from the port's current state "
        "(`ARCHITECTURE.md#port-state-machine`). `detail` carries `from` and "
        "`to`. Disabled buttons are a courtesy; this is the enforcement.",
    ),
    ErrorCode(
        "SEND_NOT_PASSTHROUGH",
        "A console write (`port.send`, `port.sendStart`) to a port not in "
        "`PASSTHROUGH`.",
    ),
    ErrorCode(
        "PORT_NOT_BOUND",
        "No board is bound to that box number. An unbound box still exists on "
        "the wire and reports `IDLE`.",
    ),
    ErrorCode("PORT_OPEN_FAILED", "Serial open failed — board absent, port busy, or permissions."),
    ErrorCode(
        "FLASH_FAILED",
        "Compile or upload failed; `detail` carries the phase and the parsed "
        "`arduino-cli` output.",
    ),
    ErrorCode(
        "SKETCH_UNKNOWN",
        "`port.flash` or `port.sendStart` named a path outside the current "
        "discovery result. The bundled library and saved task profiles are the "
        "only flashable sketches, enforced here and not just by the picker.",
    ),
    ErrorCode("COHORT_NOT_FOUND", "No cohort with that id."),
    ErrorCode(
        "COHORT_NAME_TAKEN",
        "Name already used by an **active** cohort. Archived cohorts don't "
        "reserve names, so this can also reject a `cohorts.restore`.",
    ),
    ErrorCode(
        "COHORT_INVALID",
        "A cohort validation failure (`DATA.md#cohorts-animals-and-groups`). "
        "`detail` carries per-field errors so the editor can show them inline.",
    ),
    ErrorCode(
        "COHORT_NOT_ARCHIVED",
        "`cohorts.delete` on a cohort that wasn't archived first — the "
        "deliberate two-step guard.",
    ),
    ErrorCode(
        "ANIMAL_MOVE_REFUSED",
        "`cohorts.moveAnimals` with `apply` whose fresh plan can't go ahead, "
        "or whose records changed while the files were being copied. Nothing "
        "was moved. `detail` carries the `AnimalMovePlan` with its `refused` "
        "reasons.",
    ),
    ErrorCode(
        "DATA_FOLDER_INVALID",
        "A data folder couldn't be created, or a `cohorts.setDataFolder` "
        "destination isn't empty **while `moveExisting` is true**. A non-empty "
        "destination with `moveExisting: false` is legal and expected.",
    ),
    ErrorCode("PREFIX_NAME_TAKEN", "A prefix with that name already exists."),
    ErrorCode(
        "SESSION_INVALID",
        "A session command that can't apply: unknown session, cohort, prefix "
        "or group; a mapping naming a box or animal outside the session; a box "
        "with no confirmed mapping; or a lifecycle step from the wrong state "
        "(abandoning a session that ran, resuming another day's, recovering "
        "while a box runs).",
    ),
    ErrorCode(
        "SESSION_NOT_READY",
        "`sessions.create` against a cohort with no group holding a "
        "box-assigned animal.",
    ),
    ErrorCode(
        "TASK_PROFILE_INVALID",
        "A sketch's `task.json` exists but is malformed (`detail` carries the "
        "parse error), or a profile's `START` line would exceed "
        "`START_LINE_MAX`.",
    ),
    ErrorCode(
        "BACKUP_UNAVAILABLE",
        "`backup.syncNow` with no `backupDirectory` set, or with a sync "
        "already running. An ordinary mirroring failure is never a command "
        "error; it appears on `backup.status`.",
    ),
    ErrorCode(
        "UTILITY_UNAVAILABLE",
        "A `utility.*` command when the box utility can't be used at all — "
        "the install's sketch library has none, or its profile is unreadable "
        "or not a utility profile; for `utility.identify`, also a profile with no "
        "`identify` pair. A box-level problem never raises this: it is that "
        "box's `state` in the snapshot, because 'box 4 has no board' is a fact "
        "about the rig, not a failure of the command.",
    ),
    ErrorCode(
        "RIG_INVALID",
        "The wiring document is not a wiring document — wrong shape, or too "
        "large. NOT a wiring MISTAKE: a document that is well-formed and "
        "describes an impossible box is a successful `hardware.preview` reply "
        "carrying located problems.",
    ),
    ErrorCode(
        "RIG_IN_USE",
        "`hardware.save`, `hardware.reset`, `tasks.save` or `tasks.delete` while "
        "a session is set up or a box is running. Each regenerates sketch "
        "folders a box was or will be flashed from, under a session whose "
        "profiles were read from the old ones (`TASKS.md#the-rig-definition`).",
    ),
    ErrorCode(
        "RIG_WOULD_BREAK_TASKS",
        "`hardware.save` without `confirm` on a change that would stop a saved "
        "task profile generating. `detail.breaks` lists them. Retry with "
        "`confirm: true` to proceed — the app does not veto a rewiring, it "
        "refuses to let one happen unnoticed.",
    ),
    ErrorCode(
        "STROBE_INVALID",
        "A strobe edit the vocabulary cannot take: a malformed or duplicate "
        "name, a code that is not free, a blank meaning, an unknown name, or "
        "an import file that is not a vocabulary.",
    ),
    ErrorCode(
        "STROBE_REQUIRED",
        "Retiring or removing a code a response-port slot reports with, or one "
        "the shared firmware library names. Never passable with `confirm`.",
    ),
    ErrorCode(
        "STROBE_IN_RECORDED_SESSION",
        "`strobes.remove` on a code a recorded session contains. Never passable: "
        "retire it instead. `detail` carries `count`, `sample` and `scanned`.",
    ),
    ErrorCode(
        "STROBE_WOULD_BREAK_TASKS",
        "`strobes.retire` / `strobes.remove` without `confirm` on a code a saved "
        "task or bundled sketch names. `detail.breaks` and `detail.firmware` "
        "list them.",
    ),
    ErrorCode(
        "STROBE_IMPORT_CONFLICT",
        "`strobes.import` applied with a plan that has conflicts. Nothing was "
        "written; `detail.conflicts` lists them.",
    ),
    ErrorCode(
        "STROBE_VOCABULARY_UNREADABLE",
        "This machine's vocabulary document will not read. Every edit is "
        "refused until it is repaired: one issued against the shipped default "
        "could reissue a code this machine added.",
    ),
    ErrorCode(
        "STROBE_SESSION_RUNNING",
        "A vocabulary edit while a session is set up or a box is running. Every "
        "edit regenerates the sketches a box was or will be flashed from.",
    ),
    ErrorCode(
        "TASK_NOT_FOUND",
        "No task profile with that id on this rig.",
    ),
    ErrorCode(
        "TASK_INVALID",
        "The definition is not a definition — wrong shape, too large, an "
        "unusable id or name, or a name that collides with a bundled sketch "
        "or another saved task. "
        "NOT the same as a task that will not run: a well-formed definition "
        "describing an impossible task is a successful reply carrying located "
        "diagnostics, exactly as a wiring document is.",
    ),
    ErrorCode(
        "INTAN_UNAVAILABLE",
        "RHX is not reachable: not running, its Remote TCP Control command "
        "server not opened, or the socket died. The message says what to click.",
    ),
    ErrorCode(
        "INTAN_NOT_READY",
        "RHX is reachable but this cannot be done now — RHX is already "
        "recording, no recording is configured for this group, a box has no "
        "digital input, the rig's wiring has no sync channel, or a scope asked "
        "for a channel the box does not own. The message is the operator's "
        "next step.",
    ),
    ErrorCode(
        "INTAN_COMMAND_FAILED",
        "RHX refused a command, or **accepted it and stored something else** "
        "(a read-back mismatch — the save-location-with-a-space case). "
        "`detail.command` carries what was sent.",
    ),
    ErrorCode(
        "INTERNAL",
        "Unhandled sidecar exception, a subsystem that isn't running, or an "
        "analytics walk already in progress. Also the code `sidecar.error` "
        "carries for a mid-session write failure.",
    ),
)


PROTOCOL = Protocol(
    version=VERSION,
    shapes=SHAPES,
    commands=COMMANDS,
    events=EVENTS,
    errors=ERRORS,
)

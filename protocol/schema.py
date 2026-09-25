"""The machine-readable wire schema — the single source both mirrors are
generated from.

`docs/websocket-protocol.md` remains the prose authority (rationale,
invariants, lifecycle); this file is the *shape* authority. When they disagree,
fix whichever is wrong — but the generated mirrors always follow this file.

To change the wire:
    1. Edit this file (and the doc).
    2. Run `npm run gen:protocol` (or `python protocol/generate.py`).
    3. Commit the regenerated mirrors with your change —
       `sidecar/tests/test_protocol_contract.py` fails if they are stale.

Shape conventions, matching what the sidecar actually emits:
  - `optional` (key may be absent) is distinct from `nullable` (key present,
    value may be null). The validator enforces the difference.
  - Timestamps are ISO-8601 strings; `ts` on the envelope is float seconds.
  - `box` is always a box number 1–6, never a port address (§5.1).
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
        doc="Per-port state machine names (`dashboard.md` §5.1). One owner at a "
        "time: FLASHING, RESETTING and IN_SESSION are each exclusive, and the "
        "first two force-release PASSTHROUGH and auto-resume it afterward.",
    ),
    Shape(
        "OutputLine",
        obj(
            f("dir", lit("rx", "tx"), doc="Sent commands interleave as `tx` (§5.3)."),
            f("text", STR),
            f("ts", FLOAT),
        ),
        doc="One passthrough console line. Debug output, never persisted (§5.4).",
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
        doc="The three bundled-sketch-library states of `tasks.md` §2.4. There is "
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
            f("skippedCount", INT, doc='Drives the "Partial" note (`tasks.md` §2.4).'),
            f("libraries", ListOf(STR)),
            f("librariesPath", nullable(STR)),
        ),
        doc="The full result of a bundled-library scan (`tasks.md` §2.3).",
    ),
    # Settings (pushed Tauri → sidecar; the shell owns them — §4 of the doc)
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
                "sync line is wired to, 1–16 (`recording.md` §3). Null = the box is "
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
            f(
                "utilitySketchName",
                nullable(STR),
                doc="The hardware utility sketch every idle box is returned to "
                "(`settings.md` §8). Null turns the baseline off. Keyed by sketch "
                "FOLDER NAME rather than by path, matching `taskDefaults` — the "
                "path moved when sketches began shipping with the app, and the "
                "name is what a session file already records.",
            ),
            f("defaultBaud", INT),
            f("boxes", ListOf(Ref("BoxBinding"))),
            f(
                "intan",
                Ref("IntanSettings"),
                optional=True,
                doc="Absent on a store written before recording existed; both "
                "ends fall back to RHX's defaults (5000/5001/5002).",
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
                "the legacy fixed layout. Shell-only — the sidecar ignores it.",
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
                "it, keyed by `metadataKey` (`tasks.md` §6.1). Keyed by "
                "NAME, not path: the two lab machines keep their Arduino "
                "Directories in different places, and the name is what the "
                "session file already records. Shell-only — the frontend merges "
                "these under the profile's own defaults and sends the result at "
                "`sessions.confirmMapping`, so the sidecar never reads them.",
            ),
        ),
        doc="The Tauri-side store's schema. The sidecar reads the keys it needs "
        "and ignores the rest, so adding a setting is deliberately a non-event.",
    ),
    # Hardware utility baseline (settings.md §8)
    Shape(
        "UtilityBaselineState",
        lit("unknown", "restoring", "ready", "busy", "held", "pinned", "unavailable", "failed"),
        doc="What the sidecar believes about one box's baseline firmware. "
        "`busy` (the port has another owner), `held` (a confirmed session "
        "mapping owns the rig) and `pinned` (the operator flashed another "
        "sketch here from Debug Mode, and it stays until they ask for the "
        "baseline back) are all 'not now' rather than 'not working' — "
        "the distinction is the whole reason a restore never fights the user.",
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
            f("configured", BOOL),
            f(
                "sketchPath",
                nullable(STR),
                doc="Resolved from the name against the bundled library — an "
                "install-specific fact, informational only.",
            ),
            f("sketchName", nullable(STR)),
            f(
                "canIdentify",
                BOOL,
                doc="The configured sketch's profile declares an `identify` pair. "
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
                doc="Why the baseline isn't operating at all (unset sketch, a "
                "path no longer in the Arduino Directory, a non-utility profile).",
            ),
            f("boxes", ListOf(Ref("UtilityBoxState"))),
        ),
        doc="The whole baseline picture — one snapshot, shared by the command "
        "and the event, so a client never merges two shapes.",
    ),
    # Backup Directory mirroring (data.md §7)
    Shape(
        "BackupState",
        lit("disabled", "pending", "ok", "failed"),
        doc='`pending` = directory set but no pass has completed yet — a fresh '
        "unreachable network path must not read as healthy for its first 10 s.",
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
    # Cohorts (cohorts.md §1)
    Shape("Sex", lit("M", "F", "unknown")),
    Shape(
        "Group",
        obj(
            f("id", STR),
            f("name", STR),
            f("order", INT, doc="Run order for consecutive execution."),
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
        doc="How a cohort's world looks (cohorts.md §5). **Null is the normal "
        "state**: an untouched cohort derives every field from a hash of its "
        "`id`, so it already has a stable, distinct planet and the column that "
        "stores this carries no data for it.",
    ),
    Shape(
        "Cohort",
        obj(
            f("id", STR),
            f("name", STR),
            f("dataFolder", STR, doc="Resolved once at creation, persisted verbatim (§8)."),
            f("animals", ListOf(Ref("Animal"))),
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
        ),
        doc="The full record, fetched only when a cohort is opened.",
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
                doc="Set when the request would break the six-per-group constraint "
                "(§7.2) — guidance rather than a failure, so not an error reply.",
            ),
        ),
        doc="An Auto-Balance preview. Nothing is written; apply via cohorts.update.",
    ),
    # Prefixes, sessions, Task Profiles (data.md §3.1–§6)
    Shape("Prefix", obj(f("id", STR), f("name", STR)), doc="Global — shared across cohorts."),
    Shape("SessionStatus", lit("configuring", "running", "completed", "aborted")),
    Shape(
        "GroupRun",
        obj(
            f("groupId", STR),
            f("order", INT),
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
            f("sessionNumber", STR, doc="Free text, not strictly numeric (§10)."),
            f("date", STR, doc="ISO `YYYY-MM-DD`."),
            f("startedAt", STR),
            f("endedAt", nullable(STR)),
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
                "(`recording.md` §6). Null = behavior only, which is every "
                "session from before recording existed.",
            ),
        ),
    ),
    Shape("ConfigFieldType", lit("int", "float", "bool", "string")),
    Shape(
        "ConfigField",
        obj(
            f("metadataKey", STR, doc="The `.json`/`.mat` field name the form collects under."),
            f("wireKey", STR, doc="The `START` command token (§6.3)."),
            f("label", STR),
            f("type", Ref("ConfigFieldType")),
            f("default", ANY),
            f(
                "group",
                STR,
                optional=True,
                doc="Section heading the form files this field under. Absent = "
                "ungrouped, which is how every pre-existing profile renders.",
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
        "presentation metadata and optional — a profile that declares none "
        "renders exactly as it did before these keys existed.",
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
        doc="A scored IN_SESSION task, or a PASSTHROUGH tool (§6.2).",
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
        doc="A utility control rendered in Debug Mode (§6.6); sends over port.send.",
    ),
    Shape("TelemetryField", obj(f("key", STR), f("label", STR))),
    Shape(
        "TelemetrySpec",
        obj(f("match", STR), f("fields", ListOf(Ref("TelemetryField")))),
        doc="How to parse a utility sketch's non-persisted STATUS lines out of "
        "port.output (§6.6). Parsed client-side — nothing here is stored.",
    ),
    Shape(
        "IdentifySpec",
        obj(f("on", STR), f("off", STR)),
        doc="The two commands that make a box announce itself — a trial light, "
        "a buzzer, whatever the rig has (`settings.md` §8.3). "
        "Declared by the sketch so the app never has to know that a Hart-lab "
        "box says `ON LIGHT`.",
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
                "walk can decode historical runs (`tasks.md` §3.7). Declared, "
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
        doc="Parsed from the sketch's task.json sibling (§6.1); passed through "
        "verbatim — the sidecar validates shape but doesn't reinterpret.",
    ),
    Shape(
        "SessionBoxMapping",
        obj(
            f("box", INT),
            f("animalId", STR),
            f("sketchPath", STR),
            f("config", MapOf(ANY), doc="Keyed by `metadataKey`, per the Task Profile."),
        ),
        doc="One box's session-local mapping + task config (`dashboard.md` §7.3).",
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
        ),
        doc="One box as the runner sees it — the source Mission Control renders (§5).",
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
            f("stopReason", STR, doc="`dashboard.md` §10.4's stop-reason set."),
            f("filePath", nullable(STR)),
        ),
    ),
    Shape(
        "RunnerSession",
        obj(
            f("session", Ref("Session")),
            f("groupId", nullable(STR), doc="Null only before any mapping was confirmed."),
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
    # Analytics (websocket-protocol.md §3.4)
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
                "adopted runs from a rescan (§8.1 writes no session row on purpose). False only "
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
                "`successCode` (`tasks.md` §4.10). Null whenever the profile "
                "cannot prove one — never guessed, and never taken from "
                "`alternateCode`, which on a no-go metric means 'any port will "
                "do'. This is what lets the strategy plane fold N conditions "
                "onto two axes without knowing anything about odors.",
            ),
        ),
        doc="One metric's whole-session result (`data.md` §9.2, §3.5).",
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
        doc="What actually happened per trial (`data.md` §9.8). Distinct "
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
        "(`data.md` §9.10). Delimited on the trial light, not on odor "
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
        doc="TrialOutcomes restricted to one declared condition (`data.md` "
        "§3.9), in authored liveMetrics order. Answers 'how many trials of this "
        "kind were administered, and how many of those paid out'.",
    ),
    Shape("RunStatus", lit("ok", "no-metrics", "missing", "unreadable")),
    Shape(
        "ProfileSource",
        lit("snapshot", "sketch-current", "inferred", "unavailable"),
        doc="How much the decoding can be trusted (§8.2). Four states — "
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
                doc="Null for an adopted orphan (§8.1) — a filename carries no box.",
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
                "rig (`data.md` §8.2). Empty only when the file named no "
                "sketch at all.",
            ),
            f("profileHash", nullable(STR)),
            f(
                "paramsHash",
                nullable(STR),
                doc="Hash of the task parameters this run used (`data.md` "
                "§6.9). Comparability is the PAIR with `profileHash` — that one "
                "covers the profile declaration, which is identical across every "
                "run of a sketch however it was tuned. Null for a run recorded "
                "before parameters were operator-set.",
            ),
            f("profileSource", Ref("ProfileSource")),
            f("stale", BOOL, doc="The file is gone but this is its last known-good summary."),
            f("status", Ref("RunStatus")),
            f("metrics", ListOf(Ref("MetricSummary"))),
            f(
                "overall",
                nullable(Ref("MetricSummary")),
                doc="Accuracy pooled across every metric — the only single number "
                "that can tell learning from a side bias (§3.7).",
            ),
            f(
                "outcomes",
                nullable(Ref("TrialOutcomes")),
                doc="Null when the profile declares no reward vocabulary (§3.8) — "
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
                "(§3.10) — the layer above every other count here. Null when "
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
        doc="A comparability set: two runs share axes only if they share a hash (§4.3).",
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
                doc="Flat, not a matrix — two runs really can share one (animal, session).",
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
            f("x", FLOAT),
            f("y", FLOAT),
            f("n", INT, doc="The smaller of the two rolling window lengths."),
        ),
        doc="One sample of the within-session strategy walk (`data.md` §11.1).",
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
        doc="One classified trial (`data.md` §9.11) — the same classification "
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
                "rolling question. Empty unless the profile declares exactly two "
                "conditions. Cannot be assembled client-side from `metrics`: "
                "those are indexed by each metric's own counted trials, which "
                "interleave.",
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
            f("animalId", nullable(STR), doc="Matched by name, never guessed (§8.1)."),
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
                "second recording of the same fact, never a guess (§8.1). Null "
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
        doc="What the rescan removed because the disk no longer has it (§8.6). "
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
                "changed nothing reports 0 (§8.7).",
            ),
            f(
                "pruned",
                Ref("RescanPruned"),
                doc="Records reconciled away. Only ever counts paths that are "
                "**reachable and absent** — a path under an unreachable root is "
                "left alone, so an unplugged drive can't erase history (§8.6).",
            ),
            f(
                "duplicates",
                INT,
                doc="Extra copies of an already-seen run, skipped. A hand-managed "
                "archive often keeps a consolidated copy beside the per-prefix "
                "originals; adopting both would double every animal (§8.1).",
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
                "'recovered after crash' for a footer-less log. Null on failure.",
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
        doc="One session record as the tidy preview names it (data.md §8.8).",
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
        doc="Failures with no command to attribute them to (§4).",
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
                doc="The wiring rule, when one produced it — RIG101 through RIG105. "
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
                doc="TSK101–TSK111 and TSK113 from the sidecar; TSK112 is derived "
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
            f("origin", STR, doc="`firmware` (transcribed from BehaviorBox.h) or `ephymeris`."),
            f("emittedOn", STR, optional=True),
            f("rationale", STR, optional=True),
        ),
    ),
    Shape(
        "RetiredStrobe",
        obj(f("name", STR), f("code", INT)),
        doc="Emitted by firmware this repository no longer contains. Reserved "
        "forever: reissuing one would merge two unrelated event types in any "
        "analysis spanning the change.",
    ),
    Shape(
        "StrobeVocabulary",
        obj(
            f("version", INT),
            f("codeMin", INT),
            f("codeMax", INT, doc="999 — a wire-format limit. The host parser is ^\\d{1,3}\\t\\d+$."),
            f("freeRanges", ListOf(ListOf(INT)), doc="Inclusive [lo, hi] pairs a new code may come from."),
            f("codes", ListOf(Ref("StrobeCode"))),
            f("retired", ListOf(Ref("RetiredStrobe"))),
            f("portSlots", MapOf(MapOf(STR)), doc="Slot number → its six per-port code names."),
        ),
        doc="The append-only strobe registry. Codes are never renumbered, never "
        "repurposed and never deleted — four years of recorded sessions carry "
        "them.",
    ),
    # Intan recording (recording.md)
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
        doc="Everything the recording walkthrough collects (`recording.md` §4).",
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
                "so a refused command cannot be detected (`recording.md` §2).",
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
            f("data", ANY, doc="Per kind; see `recording.md` §7."),
        ),
    ),
)


# --- Commands (client → server) --------------------------------------------

_STATE = obj(f("state", Ref("PortStateName")))
_COHORT = obj(f("cohort", Ref("Cohort")))
_SESSION = obj(f("session", Ref("Session")))

COMMANDS = (
    Command(
        "auth",
        args=obj(f("token", STR)),
        result=obj(f("authenticated", BOOL)),
        doc="Must be the connection's first message (§1.1); consumed by the "
        "server's authentication step, never dispatched to a handler.",
        section="Connection & hardware",
    ),
    Command(
        "ping",
        result=obj(f("pong", BOOL), f("sidecarVersion", STR)),
        doc="Liveness probe for the connection indicator.",
    ),
    Command(
        "settings.push",
        args=obj(f("settings", Ref("EphymerisSettings"))),
        result=obj(f("library", Ref("SketchLibraryStatus"))),
        doc="Sent on every connect and change, Tauri → sidecar only. The reply "
        "carries the bundled library's state (`tasks.md` §2.1) — which no longer "
        "depends on the settings being pushed, but is still answered here so a "
        "client learns it on connect without a second round trip.",
    ),
    Command(
        "sketches.refresh",
        result=Ref("SketchDiscovery"),
        doc="Manual Refresh and Debug Mode mount (`tasks.md` §2.3).",
    ),
    Command(
        "port.passthrough.open",
        args=obj(f("box", INT), f("baud", INT, optional=True, doc="Defaults to the configured `defaultBaud`, per box.")),
        result=_STATE,
    ),
    Command("port.passthrough.close", args=obj(f("box", INT)), result=_STATE),
    Command(
        "port.send",
        args=obj(
            f("box", INT),
            f("text", STR),
            f("lineEnding", lit("none", "lf", "cr", "crlf"), optional=True, doc="Default `lf`."),
        ),
        result=obj(f("bytesWritten", INT)),
        doc="Rejected with SEND_NOT_PASSTHROUGH unless the port is in PASSTHROUGH.",
    ),
    Command(
        "port.sendStart",
        args=obj(
            f("box", INT),
            f("sketchPath", STR, doc="The sketch believed to be on the board; its Task Profile shapes the line."),
            f("config", MapOf(ANY), optional=True, doc="Keyed by `metadataKey`, exactly as in a session mapping."),
        ),
        result=obj(f("command", STR, doc="The line as sent, for the console's record."), f("bytesWritten", INT)),
        doc="Debug Mode's way to start a behaviour sketch by hand: builds the "
        "`START` line from the sketch's Task Profile the way a session would "
        "and writes it to the open console. No `SEED` token and no strobe "
        "parsing — this is not a run and nothing it produces is data. "
        "Rejected with SEND_NOT_PASSTHROUGH unless the port is in PASSTHROUGH.",
    ),
    Command(
        "port.flash",
        args=obj(
            f("box", INT),
            f("sketchPath", STR),
            f(
                "suppressPassthroughResume",
                BOOL,
                optional=True,
                doc="Default false. The session flash sequence sets it so boxes "
                "land in IDLE for the runner to claim (`dashboard.md` §7.4).",
            ),
        ),
        result=obj(f("state", Ref("PortStateName")), f("resumedPassthrough", BOOL)),
        doc="Streams flash.progress events carrying this command's `corr`.",
    ),
    Command(
        "port.reset",
        args=obj(f("box", INT)),
        result=obj(f("state", Ref("PortStateName")), f("resumedPassthrough", BOOL)),
        doc="DTR toggle (`dashboard.md` §6.2).",
    ),
    Command(
        "port.error.ack",
        args=obj(f("box", INT)),
        result=_STATE,
        doc="ERROR → IDLE (`dashboard.md` §5.2).",
    ),
    Command(
        "utility.status",
        result=Ref("UtilityStatus"),
        doc="The baseline picture on demand — the same snapshot `utility.updated` "
        "pushes, for a client that just mounted.",
        section="Hardware utility baseline (settings.md §8)",
    ),
    Command(
        "utility.ensure",
        args=obj(
            f("boxes", ListOf(INT), optional=True, doc="Default: every bound box."),
            f(
                "force",
                BOOL,
                optional=True,
                doc="Reflash even a box already believed to be at baseline. For "
                "the Config button; the automatic paths never set it.",
            ),
        ),
        result=Ref("UtilityStatus"),
        doc="Restore the baseline now, rather than waiting for the next board "
        "or session event. Returns as soon as the work is scheduled — progress "
        "arrives on `utility.updated`. Never touches a box that isn't IDLE.",
    ),
    Command(
        "utility.identify",
        args=obj(f("box", INT), f("on", BOOL)),
        result=obj(f("delivered", BOOL), f("state", Ref("UtilityBoxState"))),
        doc="Make one box point at itself, using its profile's `identify` pair "
        "(`dashboard.md` §7.3). `delivered: false` is the ordinary "
        "answer for a box that isn't at baseline — the caller carries on "
        "without the light rather than failing.",
    ),
    # Cohorts
    Command(
        "cohorts.list",
        result=obj(f("cohorts", ListOf(Ref("CohortSummary")))),
        doc="Includes archived; the client filters (cohorts.md §4).",
        section="Cohorts (cohorts.md)",
    ),
    Command("cohorts.get", args=obj(f("id", STR)), result=_COHORT),
    Command(
        "cohorts.create",
        args=obj(
            f("name", STR),
            f("dataFolder", STR, optional=True, doc="Resolved per cohorts.md §8 when omitted."),
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
    ),
    Command(
        "cohorts.update",
        args=obj(f("id", STR), f("patch", Ref("CohortPatch"))),
        result=_COHORT,
        doc="Also the commit path for an Auto-Balance preview — no separate apply.",
    ),
    Command("cohorts.archive", args=obj(f("id", STR)), result=_COHORT),
    Command(
        "cohorts.restore",
        args=obj(f("id", STR)),
        result=_COHORT,
        doc="Rejected with COHORT_NAME_TAKEN if an active cohort claimed the name.",
    ),
    Command(
        "cohorts.delete",
        args=obj(f("id", STR), f("confirm", BOOL, doc="Must be literally true.")),
        result=obj(f("deleted", BOOL)),
        doc="Rejected unless already archived. Never touches dataFolder on disk (§9).",
    ),
    Command(
        "cohorts.setDataFolder",
        args=obj(f("id", STR), f("path", STR), f("moveExisting", BOOL)),
        result=_COHORT,
        doc="The explicit relocate of §8. Refuses a non-empty destination.",
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
        doc="Non-mutating preview; the user applies via cohorts.update.",
    ),
    # Prefixes, Task Profiles, sessions
    Command(
        "prefixes.list",
        result=obj(f("prefixes", ListOf(Ref("Prefix")))),
        section="Prefixes, Task Profiles & sessions",
    ),
    Command(
        "prefixes.create",
        args=obj(f("name", STR)),
        result=obj(f("prefix", Ref("Prefix"))),
        doc="Name-unique; rejected with PREFIX_NAME_TAKEN.",
    ),
    Command(
        "prefixes.delete",
        args=obj(f("id", STR)),
        result=obj(f("deleted", BOOL)),
        doc="Never touches folders already written under the name.",
    ),
    Command(
        "tasks.getProfile",
        args=obj(f("sketchPath", STR)),
        result=union(Ref("TaskProfile"), obj(f("profile", NULL))),
        doc="Reads the task.json sibling of the sketch's .ino. A sketch with "
        "none returns `{profile: null}` — fully supported. Works the same on a "
        "bundled sketch and on one generated from a task profile, which is the "
        "point of generating a real sketch folder.",
    ),
    # ---------------------------------------------------------- task profiles
    #
    # NOTHING HERE FLASHES. Saving generates a sketch folder that `discovery`
    # then finds, so `port.flash` takes it by path like any other — which is
    # what keeps the session flow, `taskDefaults` and Analytics free of a
    # special case for a profile-backed run.
    Command(
        "tasks.list",
        result=obj(f("tasks", ListOf(Ref("TaskEntry")))),
        doc="This rig's saved task profiles. Reads each definition and validates "
        "it, never generates — the list stays cheap however many exist.",
        section="Task profiles (tasks.md §11)",
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
        "it never saw.",
    ),
    Command(
        "tasks.preview",
        args=obj(f("definition", ANY)),
        result=Ref("TaskPreview"),
        doc="Compile an unsaved definition and say what is wrong with it, "
        "writing nothing. The editor calls it as the operator types, so a "
        "problem lands against the field that caused it; it also carries the "
        "built `START` line's length, which is the one budget an operator can "
        "exhaust without noticing.",
    ),
    Command(
        "tasks.save",
        args=obj(f("definition", ANY)),
        result=Ref("TaskSaved"),
        doc="Write the definition and regenerate its sketch. **Always saves, "
        "even with diagnostics** — a half-finished task must be savable, and the "
        "gate is flashing, not saving. Refused only when the name collides with "
        "a bundled sketch, which would make the picker ambiguous. Broadcasts "
        "`tasks.updated` and `sketches.updated`, since a profile is a sketch.",
    ),
    Command(
        "tasks.delete",
        args=obj(f("taskId", STR)),
        result=obj(f("deleted", BOOL)),
        doc="Remove the definition and its generated sketch. Idempotent: "
        "deleting what is already gone is a successful `{deleted: false}`, "
        "because two clients racing on the same task is not an error.",
    ),
    Command(
        "rig.strobes",
        result=Ref("StrobeVocabulary"),
        doc="The whole strobe registry, for the Task tab's viewer and for the "
        "task editor's code picker. Static unless a code is added.",
        section="Strobe vocabulary (tasks.md §3.3)",
    ),
    Command(
        "sessions.suggestNumber",
        args=obj(f("prefixId", STR)),
        result=obj(
            f("suggestion", nullable(STR), doc="Highest numeric number for the prefix +1."),
            f("sameDayNumbers", ListOf(STR), doc="Drives the soft reuse warning — never a block."),
        ),
    ),
    Command(
        "sessions.create",
        args=obj(
            f("cohortId", STR),
            f("prefixId", STR),
            f("sessionNumber", STR),
            f(
                "durationMinutes",
                INT,
                optional=True,
                doc="Optional per-box time limit in whole minutes; omitted "
                "means the session runs until stopped by the operator or board.",
            ),
            f(
                "recording",
                BOOL,
                optional=True,
                doc="True makes the session an Intan recording as well "
                "(`recording.md` §5): `sessions.startAll` then refuses unless "
                "`intan.configure` has run for the group.",
            ),
        ),
        result=_SESSION,
        doc="Rejected with SESSION_NOT_READY if no group has a box-assigned animal.",
    ),
    Command(
        "sessions.abandon",
        args=obj(f("sessionId", STR)),
        result=_SESSION,
        doc="Discards a session still in `configuring`; rejected once running.",
    ),
    Command(
        "sessions.confirmMapping",
        args=obj(f("sessionId", STR), f("groupId", STR), f("boxes", ListOf(Ref("SessionBoxMapping")))),
        result=obj(f("ok", BOOL)),
        doc="Session-local mapping + per-box config; feeds the flash sequence.",
    ),
    Command(
        "sessions.status",
        args=obj(f("sessionId", STR)),
        result=obj(
            f("session", Ref("Session")),
            f("groupId", nullable(STR), doc="Null only before any mapping was confirmed."),
            f("boxes", ListOf(Ref("SessionBox"))),
        ),
        doc="What Mission Control renders — the runner is the authority on the "
        "confirmed mapping, so a reload asks rather than trusting a stale copy.",
    ),
    Command(
        "sessions.startAll",
        args=obj(f("sessionId", STR)),
        result=_SESSION,
        doc="Enters IN_SESSION on every configured box not already running.",
    ),
    Command(
        "sessions.endGroup",
        args=obj(f("sessionId", STR)),
        result=_SESSION,
        doc="Ends the current group's runs and leaves the session BETWEEN GROUPS: "
        "still `running` and held, no boxes, `groupId` null. The operator then "
        "picks any group (or ends the session) — the sidecar never chooses one.",
    ),
    Command(
        "sessions.resume",
        args=obj(f("sessionId", STR)),
        result=_SESSION,
        doc="Re-holds one of TODAY's sessions that already ran a group — a "
        "crash-orphaned `running` one or a `completed` one ended too early — in "
        "the between-groups state, so another group can run under it. Closes a "
        "group run a crash left open. Never resumes a group mid-run.",
    ),
    Command("sessions.end", args=obj(f("sessionId", STR)), result=_SESSION),
    Command(
        "sessions.active",
        result=Ref("ActiveSessions"),
        doc="The global 'what is running?' query — no args, so a client with no "
        "prior knowledge (the Launch page, a reconnect) can discover the running "
        "session's id. The running slot is authoritative from live app state; "
        "configuring/stale come from the DB.",
    ),
    Command(
        "port.startSession",
        args=obj(f("box", INT)),
        result=_STATE,
        doc="Open → DTR reset → await READY → START → optional SEED (§7).",
    ),
    Command(
        "port.stopSession",
        args=obj(f("box", INT)),
        result=_STATE,
        doc="Sends the literal STOP line; the board's own end strobe ends the run.",
    ),
    # Backup
    Command(
        "backup.syncNow",
        result=Ref("SyncResult"),
        doc="The explicit backfill — setting a directory deliberately doesn't "
        "copy what's already on disk. Long-running; client raises its timeout.",
        section="Backup (data.md §7)",
    ),
    # Analytics
    Command(
        "sessions.list",
        args=obj(f("cohortId", STR), f("includeAborted", BOOL, optional=True)),
        result=obj(f("sessions", ListOf(Ref("SessionListItem")))),
        doc="Must never touch the filesystem, so selectors populate instantly.",
        section="Analytics (websocket-protocol.md §3.4)",
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
    ),
    Command(
        "analytics.series",
        args=obj(
            f("runIds", ListOf(STR), doc="Plural so one session is one call; capped server-side."),
            f("mode", lit("rolling", "cumulative"), optional=True),
            f("metricIds", ListOf(STR), optional=True),
        ),
        result=Ref("SeriesResult"),
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
        doc="The explicit archive walk — expensive reconciliation is a "
        "deliberate user action, never a side effect of opening a view. "
        "Reconciliation runs **both ways**: files no record points at are "
        "adopted, and records pointing at files the disk no longer has are "
        "pruned (§8.6).",
    ),
    Command(
        "analytics.recentSessions",
        args=obj(f("limit", INT, optional=True)),
        result=obj(f("sessions", ListOf(Ref("DiskSession")))),
        doc="The N most recent session folders across every active cohort's "
        "archive, by folder-name date — directory names only, no file is ever "
        "opened, which is what keeps this cheap enough for a landing page where "
        "the rescan is not. Sees sessions other Ephymeris machines wrote into "
        "the shared archive, which sessions.list (this machine's database) "
        "cannot.",
    ),
    # Crash recovery
    Command(
        "sessions.recover",
        args=obj(f("cohortId", STR)),
        result=Ref("RecoverResult"),
        doc="The crash-recovery backfill (`data.md` §12, §11): "
        "rebuilds .json/.mat from orphaned write-ahead .tsv files. Same "
        "traversal as analytics.rescan's walk, and same discipline — an "
        "explicit user action, never a side effect. Rejected while any box "
        "is running: a live run's .tsv has no .json yet and is not an orphan.",
        section="Crash recovery (data.md §12, §11)",
    ),
    Command(
        "sessions.tidy",
        args=obj(
            f("cohortId", STR),
            f("apply", BOOL, optional=True, doc="Default false: a preview that changes nothing."),
        ),
        result=Ref("TidyPlan"),
        doc="Merges session records that share prefix, number and date — one "
        "folder, split by a day that went wrong — into the earliest, and "
        "deletes records with no run, recording or file behind them (data.md "
        "§8.8). Database only, except an empty folder of a deleted record. "
        "Never touches the session the runner holds, nor a set-up started "
        "today. An explicit user action with a preview, like recover.",
    ),
    # ---------------------------------------------------------------- rig wiring
    #
    # THE WIRING IS NOT A SETTING, and these four commands are why. Settings are
    # shell-owned, pushed one-directionally, leniently parsed and silently
    # defaulting to a working value — right for a directory path, catastrophic
    # for a pin number, which has no safe default and fails by firing the wrong
    # valve. So the wiring is a sidecar-owned DOCUMENT instead: validated on the
    # way in, refused when it is the wrong shape, and every problem located on
    # the field that caused it.
    Command(
        "hardware.get",
        result=Ref("RigDocument"),
        doc="This rig's wiring, and everything wrong with it. Returns the shipped "
        "pinout as an editable document when the rig has never been edited, so "
        "the editor always has something real to open rather than a blank form.",
    ),
    Command(
        "hardware.preview",
        args=obj(f("document", ANY)),
        result=Ref("RigSaved"),
        doc="Validate a wiring document and say what it would cost, WITHOUT "
        "writing. Two jobs, and it is the same answer for both: the editor calls "
        "it as the operator types, so schema violations and TG226-229 appear "
        "against the field that caused them; and it is what the save preflight "
        "shows, because `breaks` is the honest form of 'this applies to every "
        "task'. A pin change that silently stopped a task compiling would be the "
        "worst version of that promise.",
    ),
    Command(
        "hardware.save",
        args=obj(
            f("document", ANY),
            f(
                "confirm",
                BOOL,
                doc="False ⇒ refuse the write if it would break a task that "
                "compiles today, and return them in `breaks`. True ⇒ write "
                "anyway. Rewiring a box is the operator's call and the app must "
                "not veto it — but it must not let them make it unknowingly.",
            ),
        ),
        result=Ref("RigSaved"),
        doc="Validate, then write. A document that fails validation is never "
        "written at all, so there is no state in which the file on disk is one "
        "the compiler refuses. On success the compiler's channel cache is "
        "cleared and `hardware.updated` is broadcast — every task compiles to "
        "different bytes from that moment, which is the design working (D15) "
        "and the reason the listing carries a pinout hash (D22).",
    ),
    Command(
        "hardware.reset",
        result=Ref("RigDocument"),
        doc="Discard this rig's document and go back to the wiring the build "
        "shipped with. The reply is `hardware.get`'s, so the editor re-renders "
        "from one shape either way.",
    ),
    # ------------------------------------------------------------ Intan recording
    #
    # RHX MAY BE SLOW, ABSENT OR DEAD AND NONE OF THAT MAY STALL OR FAIL A
    # BEHAVIOR SESSION -- the Backup mirror's rule, restated. The one exception
    # is starting: a recording that cannot start refuses before any box does.
    Command(
        "intan.status",
        result=Ref("IntanStatus"),
        doc="The current snapshot; also replayed on connect and pushed as `intan.status`.",
        section="Intan recording (recording.md)",
    ),
    Command(
        "intan.connect",
        result=Ref("IntanStatus"),
        doc="Open RHX's command socket now rather than at the next background "
        "attempt. INTAN_UNAVAILABLE says what to click in RHX.",
    ),
    Command("intan.disconnect", result=Ref("IntanStatus"), doc="Refused while recording."),
    Command(
        "intan.configure",
        args=obj(f("sessionId", STR), f("groupId", STR), f("config", Ref("RecordingConfig"))),
        result=Ref("IntanStatus"),
        doc="Apply a recording setup to RHX for one group run. Every value that "
        "decides WHERE and AS WHAT the data is saved is read back and refused on "
        "a mismatch. INTAN_NOT_READY for a box with no digital input, a rig with "
        "no sync channel, or a controller that is running.",
    ),
    Command(
        "intan.parseProbeMap",
        args=obj(f("path", STR)),
        result=obj(f("probeMap", ANY)),
        doc="Parse an Intan probe-map XML for the setup preview. RHX cannot be "
        "asked to load one over TCP, so Ephymeris reads the same file itself.",
    ),
    Command(
        "intan.probeMap",
        args=obj(f("box", INT)),
        result=obj(f("probeMap", ANY)),
        doc="The probe map configured for this box, or null.",
    ),
    Command(
        "intan.setThreshold",
        args=obj(f("channel", STR), f("microvolts", INT)),
        result=obj(f("channel", STR), f("microvolts", INT)),
        doc="One channel's spike threshold, from the SpikeScope's threshold line.",
    ),
    Command(
        "intan.scope.open",
        args=obj(
            f("kind", Ref("ScopeKind")),
            f("box", INT),
            f("channel", nullable(STR), optional=True),
            f("params", MapOf(ANY), optional=True),
        ),
        result=obj(f("scopeId", STR)),
        doc="Begin publishing one live view as `intan.scope.data`. A SpikeScope "
        "also asks RHX to stream that channel's highpass band, which is why "
        "there is a cap on how many may be open.",
    ),
    Command(
        "intan.scope.update",
        args=obj(
            f("scopeId", STR),
            f("channel", nullable(STR), optional=True),
            f("params", MapOf(ANY), optional=True),
        ),
        result=obj(f("ok", BOOL)),
    ),
    Command(
        "intan.scope.close",
        args=obj(f("scopeId", STR)),
        result=obj(f("ok", BOOL)),
        doc="Idempotent. A window that vanishes without closing its scope is "
        "swept when its connection drops.",
    ),
    Command(
        "intan.forceStop",
        result=obj(f("ok", BOOL)),
        doc="Stop waiting for boxes to finish their trials during a graceful "
        "end; the recording is then stopped at once.",
    ),
)


# --- Events (server → client) ----------------------------------------------

EVENTS = (
    Event("server.hello", Ref("ServerHello"), doc="First frame on every connection."),
    Event("port.state", Ref("PortStateData"), doc="Emitted on every transition."),
    Event("port.output", Ref("PortOutputData"), doc="Batched at ~20Hz per port (§5.3)."),
    Event(
        "port.telemetry",
        Ref("PortTelemetry"),
        doc="Live metrics for a task started from Debug Mode with `port.sendStart`, "
        "scored by the same `MetricSet` a session uses. At most one per "
        "`port.output` batch; every payload is the whole picture.",
    ),
    Event("boards.presence", Ref("BoardsPresenceData"), doc="The out-of-band poll; never opens a port."),
    Event("flash.progress", Ref("FlashProgressData"), doc="Carries the causing command's `corr`."),
    Event("sketches.updated", Ref("SketchDiscovery"), doc="Pushed whenever discovery re-runs."),
    Event("cohorts.updated", Ref("CohortsUpdatedData"), doc="Push-on-change, same pattern as sketches.updated."),
    Event("prefixes.updated", Ref("PrefixesUpdatedData")),
    Event(
        "session.telemetry",
        Ref("BoxTelemetry"),
        doc="Pushed on every strobe that updates a rolling live metric — far "
        "lower-frequency than raw strobes, so not batched.",
    ),
    Event("session.animalEnded", Ref("AnimalEnded"), doc="One animal's run finalized."),
    Event(
        "session.lifecycle",
        Ref("ActiveSessions"),
        doc="Broadcast whenever session identity or status changes (create, "
        "abandon, confirmMapping, startAll, endGroup, resume, end). A full snapshot, "
        "not a delta — clients replace state wholesale. Per-box liveness is not "
        "re-broadcast here; port.state remains that channel.",
    ),
    Event(
        "hardware.updated",
        Ref("RigStatus"),
        doc="Broadcast after a successful save or reset. Every open client must "
        "drop any cached copy of the channel map: it used to be a fact about the "
        "build, fixed for the life of the process, and it is now a fact about "
        "this rig that an operator can change between two reads.",
    ),
    Event(
        "utility.updated",
        Ref("UtilityStatus"),
        doc="Pushed on connect and whenever any box's baseline belief changes — "
        "a restore starting or finishing, a hold, an identify light.",
    ),
    Event(
        "backup.status",
        Ref("BackupStatus"),
        doc="On connect, on directory change, and on state change or actual "
        "copies — deliberately not every quiet 10 s tick.",
    ),
    Event(
        "analytics.progress",
        Ref("AnalyticsProgress"),
        doc="Published on phase change and every N files — never per file.",
    ),
    Event("sidecar.error", Ref("SidecarErrorData"), doc="Failures with no command to attribute to."),
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
        doc="A full snapshot, on every change and on connect.",
    ),
    Event(
        "intan.scope.data",
        Ref("ScopeData"),
        doc="One live view's payload, a few times a second, only while that "
        "scope is open. Never persisted — like `port.output`, it is a view.",
    ),
)


# --- Error codes ------------------------------------------------------------

ERRORS = (
    ErrorCode("BAD_MESSAGE", "Malformed JSON, non-object frame, or invalid args."),
    ErrorCode("UNKNOWN_COMMAND", "Unrecognized `cmd`."),
    ErrorCode("UNAUTHORIZED", "Missing/invalid token, or a non-auth first message."),
    ErrorCode("PROTOCOL_VERSION_MISMATCH", "`v` does not match the sidecar's protocol version."),
    ErrorCode("ILLEGAL_TRANSITION", "Operation not permitted from the port's current state."),
    ErrorCode("SEND_NOT_PASSTHROUGH", "port.send attempted while not in PASSTHROUGH."),
    ErrorCode("PORT_NOT_BOUND", "No board bound to that box number."),
    ErrorCode("PORT_OPEN_FAILED", "Serial open failed (absent, busy, permissions)."),
    ErrorCode("FLASH_FAILED", "Compile or upload failed; detail carries parsed arduino-cli output."),
    ErrorCode("SKETCH_UNKNOWN", "port.flash named a path outside the current discovery result."),
    ErrorCode("COHORT_NOT_FOUND", "No cohort with that id."),
    ErrorCode("COHORT_NAME_TAKEN", "Name already used by an active cohort."),
    ErrorCode("COHORT_INVALID", "A cohorts.md §2 validation failure; detail carries per-field errors."),
    ErrorCode("COHORT_NOT_ARCHIVED", "cohorts.delete on a cohort that wasn't archived first."),
    ErrorCode("DATA_FOLDER_INVALID", "A data folder couldn't be created, or a destination isn't empty."),
    ErrorCode("PREFIX_NAME_TAKEN", "A prefix with that name already exists."),
    ErrorCode("SESSION_INVALID", "Malformed session command — unknown cohort/prefix/group or mapping."),
    ErrorCode("SESSION_NOT_READY", "sessions.create against a cohort with no box-assigned animal."),
    ErrorCode("TASK_PROFILE_INVALID", "A sketch's task.json exists but is malformed."),
    ErrorCode("BACKUP_UNAVAILABLE", "backup.syncNow with no directory set, or a sync already running."),
    ErrorCode(
        "UTILITY_UNAVAILABLE",
        "No hardware utility sketch is configured, or the named one can't be used "
        "(not in the bundled library, or not a utility profile).",
    ),
    ErrorCode(
        "RIG_INVALID",
        "The wiring document is not a wiring document — wrong shape, or too "
        "large. NOT a wiring MISTAKE: a document that is well-formed and "
        "describes an impossible box is a successful hardware.preview reply "
        "carrying located problems.",
    ),
    ErrorCode(
        "RIG_WOULD_BREAK_TASKS",
        "hardware.save without `confirm` on a change that would stop a saved task "
        "profile generating. detail carries them. Retry with confirm: true to "
        "proceed — the app does not veto a rewiring, it refuses to let one happen "
        "unnoticed.",
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
        "server not opened, or the socket died.",
    ),
    ErrorCode(
        "INTAN_NOT_READY",
        "RHX is reachable but this cannot be done now — the controller is "
        "running, no recording is configured, a box has no digital input, or "
        "the rig's wiring has no sync channel.",
    ),
    ErrorCode(
        "INTAN_COMMAND_FAILED",
        "RHX refused a command, or accepted it and stored something else.",
    ),
    ErrorCode("INTERNAL", "Unhandled sidecar exception; also carried by sidecar.error."),
)


PROTOCOL = Protocol(
    version=VERSION,
    shapes=SHAPES,
    commands=COMMANDS,
    events=EVENTS,
    errors=ERRORS,
)

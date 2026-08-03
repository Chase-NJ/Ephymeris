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
        lit("IDLE", "PASSTHROUGH", "FLASHING", "UPLOADING", "RESETTING", "IN_SESSION", "ERROR"),
        doc="Per-port state machine names (`dashboard.md` §5.1). UPLOADING is a "
        "task-spec table transfer (`specs.md`) — exclusive like FLASHING, with "
        "the same passthrough auto-resume.",
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
        ),
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
                "boxSetupComplete",
                BOOL,
                doc="First-run box setup finished or explicitly skipped; gates "
                "the Config wizard. Shell-only.",
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
        lit("unknown", "restoring", "ready", "busy", "held", "unavailable", "failed"),
        doc="What the sidecar believes about one box's baseline firmware. "
        "`busy` (the port has another owner) and `held` (a confirmed session "
        "mapping owns the rig) are both 'not now' rather than 'not working' — "
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
        ),
        doc="The full record, fetched only when a card is opened. The icon is "
        "deliberately absent — derived client-side from `id` (cohorts.md §5).",
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
                doc="Distinct box numbers this cohort's animals hold. The one "
                "piece of animal detail the summary carries, so the browser "
                "grid can flag a cohort whose boxes no longer exist on this "
                "machine without fetching every cohort in full.",
            ),
            f("archived", BOOL),
            f("createdAt", STR),
            f("updatedAt", STR),
        ),
        doc="Enough for the grid and dashboard tile, no per-animal detail.",
    ),
    Shape(
        "CohortPatch",
        obj(
            f("name", STR, optional=True),
            f("animals", ListOf(Ref("Animal")), optional=True, doc="Replaced wholesale."),
            f("groups", ListOf(Ref("Group")), optional=True, doc="Replaced wholesale."),
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
                "'running' row with no live runner is a crash orphan, not resumable.",
            ),
            f(
                "configuring",
                ListOf(Ref("Session")),
                doc="Setup never finished; legitimately resumable into the mapping flow.",
            ),
            f(
                "stale",
                ListOf(Ref("Session")),
                doc="DB says 'running' but no runner holds them — a crash happened. "
                "Surfaced for honesty (the .tsv on disk is the record), never for resume.",
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
                doc="True when this machine's database holds a session row for the folder — "
                "false for a session another Ephymeris machine wrote into the shared archive.",
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
            f("counted", INT),
            f("triggered", INT),
            f("excluded", INT),
            f("windowSize", INT),
            f("wilsonLow", nullable(FLOAT)),
            f("wilsonHigh", nullable(FLOAT)),
            f("lowConfidence", BOOL),
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
        lit("snapshot", "sketch-current", "unavailable"),
        doc="How much the decoding can be trusted (§8.2). Three states, not two "
        "— `sketch-current` means the profile may have changed since the run.",
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
    Shape("ProfileMetricInfo", obj(f("id", STR), f("label", STR), f("windowSize", INT))),
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
        "RescanResult",
        obj(
            f("scanned", INT),
            f("adopted", INT),
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
    # Task specs (specs.md) — the vendored Task-Graph compiler's surface.
    # A spec is a SIBLING artifact to a sketch's task.json, never an extension
    # of it: the two hash differently, and profile_hash is what Analytics
    # groups a sketch's historical runs by.
    Shape(
        "SpecOrigin",
        lit("shipped", "shipped_edited", "user"),
        doc="Where a spec's current bytes come from. `shipped_edited` = a user "
        "copy shadowing a bundled spec of the same id.",
    ),
    Shape(
        "SpecEntry",
        obj(
            f("specId", STR),
            f("label", nullable(STR), doc="meta.label, when the document parses."),
            f("description", nullable(STR)),
            f("origin", Ref("SpecOrigin")),
            f("template", nullable(STR)),
            f("templateVersion", nullable(INT)),
            f(
                "upstreamChanged",
                BOOL,
                doc="A shipped_edited spec whose BUNDLED bytes moved since the "
                "user's copy was made — i.e. an app update changed the shipped "
                "version underneath a local edit. Never merged automatically; "
                "the user chooses Keep mine (specs.acknowledgeUpstream) or Reset "
                "to shipped (specs.delete).",
            ),
            f("editedAt", nullable(STR), doc="ISO-8601; null for a pure shipped spec."),
        ),
        doc="A row in the spec list. Built from a cheap parse — never a compile — "
        "so `specs.list` stays instant however many specs exist.",
    ),
    Shape(
        "SpecDiagnostic",
        obj(
            f("code", STR, doc="TG###; append-only, never reused."),
            f("severity", lit("INFO", "WARN", "ERROR")),
            f("message", STR),
            f(
                "location",
                nullable(STR),
                doc="A dotted YAML path (`contingency.outcome_map.omission.strobe`), "
                "a node id (`S12`), a selector, or a registry filename. Clients "
                "should not parse it — `placement` already says where it lands.",
            ),
            f(
                "placement",
                lit("field", "row", "section", "node", "document"),
                doc="Where this diagnostic belongs on screen, computed by the one "
                "definition in the compiler (taskgraph/presentation.py). `field` "
                "anchors are overlay keys, so mapping onto an input is a "
                "dictionary lookup and never a parse.",
            ),
            f("anchor", nullable(STR), doc="The overlay key, section path or node id."),
            f("detail", nullable(STR)),
            f("help", nullable(STR), doc="Rule-level: what to do about it."),
            f("decision", nullable(STR), doc="e.g. `D4` — a docs/decisions.md pointer."),
        ),
    ),
    Shape(
        "SpecGraphNode",
        obj(
            f("index", INT),
            f("symbol", STR, doc="The template's node id (`engage_win`); `index` "
              "formats to the listing's `S07`."),
            f("label", STR),
            f("band", INT, doc="1 engagement · 2 sampling · 3 response · 4 outcome."),
            f("type", lit("DELAY", "WAIT_ENTRY", "HOLD", "WAIT_EXIT", "PULSE", "TERMINAL")),
            f("durationId", nullable(STR), doc="Timing id, when duration comes from the vector."),
            f("durationMs", nullable(INT)),
            f("strobeName", nullable(STR)),
            f("strobe", nullable(INT)),
            f("silentByDesign", BOOL, doc="An explicit `strobe: null` (D4), not an omission."),
            f("watch", ListOf(STR), doc="Channel names this state watches."),
        ),
    ),
    Shape(
        "SpecGraphEdge",
        obj(
            f("index", INT),
            f("src", INT),
            f("dst", INT),
            f("trigger", lit("TIMEOUT", "ENTER", "HELD", "BROKEN", "EXIT", "DONE", "ADVANCE", "REPEAT")),
            f("guard", nullable(STR), doc="Human-readable guard, or null for the default edge."),
            f("channel", nullable(STR)),
            f("effect", nullable(STR), doc="`score:wrong`, `reward:@target` — the edge's side effect."),
        ),
    ),
    Shape(
        "SpecGraph",
        obj(
            f("nodes", ListOf(Ref("SpecGraphNode"))),
            f("edges", ListOf(Ref("SpecGraphEdge"))),
            f("entry", INT),
        ),
        doc="The compiled machine graph — six node primitives, trigger-keyed edges. "
        "Deliberately NOT the derived TaskGraphModel: that describes what an animal "
        "does; this describes what the interpreter executes.",
    ),
    Shape(
        "SpecTableSummary",
        obj(
            f("specId", STR),
            f("specHash", STR),
            f("specVersion", INT),
            f("vocabVersion", INT),
            f("template", STR),
            f("templateVersion", INT),
            f("templateHash", STR),
            f("nNodes", INT),
            f("nEdges", INT),
            f("nTiming", INT),
            f("nTrialTypes", INT),
            f("sizeBytes", INT, doc="Bytes on the wire to a board — the capacity that matters."),
            f("crc32", STR, doc="Hex, `0x`-prefixed — matches the CLI's own rendering."),
        ),
    ),
    Shape(
        "SpecCompileResult",
        obj(
            f("ok", BOOL),
            f("diagnostics", ListOf(Ref("SpecDiagnostic"))),
            f(
                "table",
                nullable(Ref("SpecTableSummary")),
                doc="Null whenever any diagnostic is an ERROR — the compiler's "
                "structural gate, mirrored onto the wire. There is no code path "
                "from a failing spec to a table summary.",
            ),
            f("graph", nullable(Ref("SpecGraph"))),
            f(
                "listing",
                nullable(STR),
                doc="emit.listing.render verbatim — the review artifact, byte-equal "
                "to the checked-in specs/<id>.table.txt when the spec is unedited.",
            ),
            f("elapsedMs", FLOAT),
        ),
        doc="A spec that doesn't compile is a SUCCESSFUL reply carrying diagnostics, "
        "never a command error — same discipline as Analytics' corrupt-file rule. "
        "SPEC_INVALID is reserved for a document that isn't a document.",
    ),
    Shape(
        "SpecCapabilities",
        obj(
            f("outcomeClasses", ListOf(STR)),
            f(
                "requiredTiming",
                ListOf(STR),
                doc="Ordered — the form renders timing rows in exactly this order.",
            ),
            f("knobs", ListOf(STR)),
            f("template", STR),
            f("templateVersion", INT),
        ),
        doc="What a topology produces (roadmap Phase 6): the palette's validity "
        "model. A pure function of the knobs, so the form re-gates its rows the "
        "instant one moves, before any compile returns.",
    ),
    Shape(
        "SpecsUpdatedData",
        obj(f("specs", ListOf(Ref("SpecEntry")))),
    ),
    Shape(
        "DiffLine",
        obj(f("op", lit(" ", "+", "-")), f("text", STR)),
    ),
    Shape(
        "DiffHunk",
        obj(
            f(
                "section",
                STR,
                doc="The listing section the hunk falls in — STATES, TIMING VECTOR, "
                "TRIAL TYPES, STAGE SCHEDULE, DWELL BUDGET — so a change reads as "
                '"3 states added in the sampling band" rather than "line 71 moved".',
            ),
            f("lines", ListOf(Ref("DiffLine"))),
        ),
    ),
    Shape(
        "SpecListingDiff",
        obj(
            f("specId", STR),
            f("baseline", lit("shipped", "saved", "spec")),
            f("changed", BOOL),
            f(
                "before",
                nullable(Ref("SpecTableSummary")),
                doc="Null when that side does not compile. The summaries carry the "
                "headline (26 → 29 states) and the provenance strip — spec_hash and "
                "template_hash move on EVERY edit, so they are excluded from the "
                "hunks and shown once here instead of topping every diff.",
            ),
            f("after", nullable(Ref("SpecTableSummary"))),
            f("hunks", ListOf(Ref("DiffHunk"))),
            f("added", INT),
            f("removed", INT),
        ),
        doc="A diff of the LISTING — the checked-in review artifact — never of the "
        "YAML. The listing is what a reviewer reads upstream, so it is what a "
        "topology change is reviewed against here (roadmap Phase 6).",
    ),
    Shape(
        "SpecArtifact",
        obj(
            f("kind", lit("spec", "listing", "lint", "table_json", "table_bin", "bench")),
            f("filename", STR),
            f("text", nullable(STR)),
            f("base64", nullable(STR), doc="Only table_bin — the packed wire bytes."),
        ),
    ),
    Shape(
        "BoardCapabilities",
        obj(
            f("box", INT),
            f(
                "present",
                BOOL,
                doc="False when the board announced no CAP line — un-migrated "
                "firmware, the legacy bare-START path. Not an error; it means "
                "'flash the interpreter sketch first' and the UI offers exactly "
                "that.",
            ),
            f("baud", INT, doc="The rate that actually answered (transport detect)."),
            f("values", MapOf(INT), doc="Numeric CAP keys — PROTO, WIRE, MAX_NODES…"),
            f("text", MapOf(STR), doc="Text CAP keys — SKETCH, SPEC…"),
            f("banner", ListOf(STR), doc="Everything the board said up to READY, verbatim."),
        ),
    ),
    Shape(
        "UploadProgressData",
        obj(
            f("box", INT),
            f(
                "phase",
                lit("detect", "probe", "transfer", "verify"),
                doc="detect = finding the baud · probe = reading CAP · transfer = "
                "chunks moving · verify = awaiting TABLE OK.",
            ),
            f("chunk", nullable(INT), doc="Confirmed BY THE BOARD — counted at its ACK."),
            f("chunks", nullable(INT)),
            f("text", nullable(STR)),
        ),
    ),
    Shape(
        "UploadResult",
        obj(
            f("box", INT),
            f("specId", STR),
            f("specHash", STR),
            f("nBytes", INT),
            f("chunks", INT),
            f("crc32", STR),
            f(
                "digest",
                STR,
                doc="The body digest the board echoed. CRC says the bytes arrived; "
                "the digest says they decoded into the right fields — a transfer "
                "can be perfect and a decode wrong, and only this catches it.",
            ),
            f("seconds", FLOAT),
            f("notes", ListOf(STR), doc="Advisory CAP notes — a dimension the board didn't announce."),
            f("caps", Ref("BoardCapabilities")),
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
        "none returns `{profile: null}` — fully supported.",
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
        "sessions.switchGroup",
        args=obj(f("sessionId", STR)),
        result=obj(f("nextGroupId", nullable(STR))),
        doc="Ends current runs, advances to the next populated group by order.",
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
        args=obj(f("cohortId", STR), f("adoptOrphans", BOOL, optional=True)),
        result=Ref("RescanResult"),
        doc="The explicit archive walk — expensive reconciliation is a "
        "deliberate user action, never a side effect of opening a view.",
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
    # Task specs
    Command(
        "specs.list",
        result=obj(f("specs", ListOf(Ref("SpecEntry")))),
        doc="Enumerate the spec library. Reads headers, never compiles.",
        section="Task specs (specs.md)",
    ),
    Command(
        "specs.get",
        args=obj(f("specId", STR)),
        result=obj(
            f("specId", STR),
            f("origin", Ref("SpecOrigin")),
            f("text", STR, doc="The YAML source, verbatim — comments and all."),
            f(
                "raw",
                ANY,
                doc="The parsed document, or null if the text will not parse. The "
                "form binds to this; the text is the escape hatch and the save "
                "payload.",
            ),
        ),
    ),
    Command(
        "specs.schema",
        result=obj(
            f("schema", ANY, doc="schema/task_spec.v1.json, verbatim."),
            f("overlay", ANY, doc="task_spec.presentation.v1.json — labels/widgets/groups."),
            f("strobes", ANY, doc="strobe_vocab.v1.json — codes with their rationale."),
            f("channels", ANY, doc="channels.v1.json — the box pinout, by kind."),
            f("limits", ANY, doc="limits.v1.json — hard ceilings, each with rationale."),
            f(
                "templates",
                ListOf(obj(f("name", STR), f("version", INT), f("sourceHash", STR))),
            ),
        ),
        doc="Everything a form needs, in one call on route mount. Served from the "
        "vendored registry FILES — the same bytes the compiler validates against, "
        "so a picker cannot offer a value the compiler then rejects. The frontend "
        "must never hold its own copy of a registry.",
    ),
    Command(
        "specs.compile",
        args=obj(
            f("text", STR, doc="The document as it would be saved — the LOAD pass "
              "(schema validation, TG1xx, the YAML `on:` trap) checks things that "
              "only exist before parsing, so the wire carries text, not a dict."),
            f("specId", STR, optional=True),
        ),
        result=Ref("SpecCompileResult"),
        doc="Stateless; the live per-edit call. Runs in a worker thread behind a "
        "semaphore of 1 — a synchronous compile on the loop would stall the 20 Hz "
        "output flush and, mid-session, the fsync-per-strobe write path. The "
        "frontend debounces (~120 ms) and discards stale replies by corr.",
    ),
    Command(
        "specs.capabilities",
        args=obj(
            f("topology", ANY, doc="The topology knobs as the form holds them — "
              "may be half-built; unspecified knobs take the schema's defaults."),
        ),
        result=Ref("SpecCapabilities"),
        doc="Pure function of six scalars; no I/O, no debounce, called on every "
        "knob change. This is what re-gates the timing rows and outcome cards "
        "before any compile returns.",
    ),
    Command(
        "specs.save",
        args=obj(
            f("specId", STR, doc="The save target — the frontend passes the "
              "document's own spec_id, so renaming the id and saving creates a "
              "copy rather than moving a file."),
            f("text", STR),
        ),
        result=obj(f("entry", Ref("SpecEntry")), f("result", Ref("SpecCompileResult"))),
        doc="ALWAYS saves, even with ERROR diagnostics — a half-finished spec "
        "must be savable; the gate is upload, not save. Writes go under the "
        "sidecar's own app-data dir, like session files and ephymeris.db — no "
        "Tauri fs capability is involved. Saving over a shipped spec's id "
        "shadows it (origin becomes shipped_edited) after the shipped bytes are "
        "copied to a baseline, which is what Reset to shipped restores — "
        "comments and all, since the shipped file itself is never modified.",
    ),
    Command(
        "specs.delete",
        args=obj(f("specId", STR)),
        result=obj(
            f(
                "entry",
                nullable(Ref("SpecEntry")),
                doc="Null when the spec is gone (a user spec); the now-shipped "
                "entry when deleting a shadow restored the bundled version.",
            ),
        ),
        doc="For a user spec: delete. For shipped_edited: Reset to shipped — "
        "removes the user copy and its baseline. For shipped: SPEC_READONLY.",
    ),
    Command(
        "specs.acknowledgeUpstream",
        args=obj(f("specId", STR)),
        result=obj(f("entry", Ref("SpecEntry"))),
        doc="Keep mine: re-baseline a shipped_edited spec against the CURRENT "
        "bundled bytes, clearing upstreamChanged until the next app update "
        "moves them again. Nothing is merged and nothing is overwritten.",
    ),
    Command(
        "specs.diff",
        args=obj(
            f("specId", STR),
            f(
                "text",
                STR,
                optional=True,
                doc="The AFTER side: the editor's unsaved document. Absent = the "
                "stored file, for reviewing a saved edit.",
            ),
            f(
                "baseline",
                lit("shipped", "saved"),
                optional=True,
                doc="The BEFORE side. Default: shipped for a bundled id, saved "
                "otherwise. `shipped` on a shadow means the CURRENT bundled bytes.",
            ),
            f(
                "againstSpecId",
                STR,
                optional=True,
                doc="Compare against another spec entirely — how the shaping_gr / "
                "shaping_gr_ez 'pure timing delta' claim gets read. Overrides "
                "`baseline`.",
            ),
        ),
        result=Ref("SpecListingDiff"),
        doc="A deliberate Review action, never per-keystroke — the baselines live "
        "server-side and shipping two full listings per edit would be waste.",
    ),
    Command(
        "specs.export",
        args=obj(
            f("specId", STR),
            f("text", STR, optional=True, doc="Export the editor's document instead of the stored file."),
            f("artifacts", ListOf(STR), doc="Which kinds; unknown names are ignored."),
        ),
        result=obj(f("artifacts", ListOf(Ref("SpecArtifact")))),
        doc="Returns bytes IN THE REPLY; the frontend writes them through a "
        "dialog-picked path. That keeps 'no wire command writes an arbitrary "
        "file' intact — the sidecar's own writes stay under its data dir.",
    ),
    # Bench boxes (specs.md) — probe and table upload. NOTE the structural
    # invariant: no command here or anywhere ties a spec to a SESSION.
    # sessions.confirmMapping does not learn a specId and port.startSession is
    # untouched — that door opens at Phase 5's exit criteria, not before.
    Command(
        "board.capabilities",
        args=obj(
            f("box", INT),
            f(
                "baud",
                INT,
                optional=True,
                doc="Skip detection and probe at this rate. Absent = try 115200 "
                "then 9600 — the two the fleet actually contains during the "
                "rollout. NOT settings.defaultBaud, which is the console default.",
            ),
        ),
        result=Ref("BoardCapabilities"),
        doc="Read a board's CAP banner and stop — what a box says about itself, "
        "changing nothing on it. Costs one DTR reset (opening the port is the "
        "reset). Requires the port IDLE or PASSTHROUGH; auto-resumes the latter.",
        section="Bench boxes (specs.md)",
    ),
    Command(
        "board.uploadTable",
        args=obj(
            f("box", INT),
            f("specId", STR),
            f(
                "text",
                STR,
                optional=True,
                doc="Upload the editor's document instead of the stored file. "
                "COMPILED SERVER-SIDE EITHER WAY — a client-supplied table is "
                "never trusted; the structural gate stays in the compiler.",
            ),
        ),
        result=Ref("UploadResult"),
        doc="Compile → detect baud → CAP check → chunked transfer → CRC+digest "
        "verify. The capability check runs BEFORE any byte of table, so a board "
        "that can't hold this task says so in milliseconds and names both "
        "numbers. Progress streams on `upload.progress` with this command's "
        "corr. The port lands back in IDLE (or resumes PASSTHROUGH); the "
        "utility baseline's bench hold decides whether it STAYS there.",
    ),
    Command(
        "utility.benchHold",
        args=obj(f("held", BOOL)),
        result=Ref("UtilityStatus"),
        doc="Suspend baseline restores while the bench panel is open. WITHOUT "
        "this, a table upload ends with the port falling IDLE, the baseline "
        "quietly reflashing BOX_Utility over the interpreter, and the uploaded "
        "table dying with it — a bug no existing test caught because nothing "
        "before this ever flashed a non-baseline sketch outside a session. A "
        "SEPARATE flag from the session hold, so a bench release can never "
        "release a rig a confirmed mapping owns. In-memory only: a client that "
        "crashes leaves it set until app restart, which errs on the side of "
        "not reflashing.",
    ),
)


# --- Events (server → client) ----------------------------------------------

EVENTS = (
    Event("server.hello", Ref("ServerHello"), doc="First frame on every connection."),
    Event("port.state", Ref("PortStateData"), doc="Emitted on every transition."),
    Event("port.output", Ref("PortOutputData"), doc="Batched at ~20Hz per port (§5.3)."),
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
        "abandon, confirmMapping, startAll, switchGroup, end). A full snapshot, "
        "not a delta — clients replace state wholesale. Per-box liveness is not "
        "re-broadcast here; port.state remains that channel.",
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
        "specs.updated",
        Ref("SpecsUpdatedData"),
        doc="Push-on-change and replayed on connect — the sketches.updated pattern.",
    ),
    Event(
        "upload.progress",
        Ref("UploadProgressData"),
        doc="Streamed during board.uploadTable, carrying the causing command's "
        "corr — the flash.progress precedent, verbatim.",
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
    ErrorCode("SPEC_NOT_FOUND", "No spec with that id in the library."),
    ErrorCode(
        "SPEC_INVALID",
        "The document isn't a document — not a string, or too large. NOT a "
        "compile failure: a spec that doesn't compile is a successful "
        "specs.compile reply carrying diagnostics.",
    ),
    ErrorCode(
        "SPEC_COMPILER_UNAVAILABLE",
        "The vendored Task-Graph compiler failed to import (README.md §6.4). "
        "detail carries the ImportError. The legacy task.json path and the "
        "session flow are unaffected.",
    ),
    ErrorCode(
        "SPEC_READONLY",
        "specs.delete on a purely shipped spec. The bundled file is part of the "
        "install; editing it goes through save (which shadows it), not delete.",
    ),
    ErrorCode(
        "UPLOAD_REFUSED",
        "The board cannot take this table and said so before any byte moved: no "
        "CAP line (un-migrated firmware — flash the interpreter sketch first), a "
        "protocol/wire-format mismatch, or a capacity the table exceeds. detail "
        "carries the comparison.",
    ),
    ErrorCode(
        "UPLOAD_FAILED",
        "The transfer itself broke: no rate answered, the board went quiet "
        "mid-transfer, TABLE FAIL, or a CRC/digest mismatch. A partial upload "
        "leaves the board's table invalid, so it will refuse to run it.",
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

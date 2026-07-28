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


# --- Named payload shapes --------------------------------------------------

SHAPES = (
    # Hardware / discovery
    Shape(
        "PortStateName",
        lit("IDLE", "PASSTHROUGH", "FLASHING", "RESETTING", "IN_SESSION", "ERROR"),
        doc="Per-port state machine names (`hardware-interaction.md` §3.1).",
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
        "DirectoryState",
        lit("not_configured", "invalid", "empty", "ok"),
        doc="The four Arduino Directory states of `arduino-directory.md` §6.",
    ),
    Shape(
        "DirectoryStatus",
        obj(
            f("state", Ref("DirectoryState")),
            f("path", nullable(STR)),
            f("message", nullable(STR), doc='Populated when state != "ok".'),
        ),
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
            f("directory", Ref("DirectoryStatus")),
            f("sketches", ListOf(Ref("SketchEntry"))),
            f("skipped", ListOf(Ref("SkippedEntry"))),
            f("skippedCount", INT, doc='Drives the "Partial" note (`arduino-directory.md` §6).'),
            f("libraries", ListOf(STR)),
            f("librariesPath", nullable(STR)),
        ),
        doc="The full result of an Arduino Directory scan (`arduino-directory.md` §4).",
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
            f("arduinoDirectory", nullable(STR)),
            f("arduinoCliPath", nullable(STR)),
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
        ),
        doc="The Tauri-side store's schema. The sidecar reads the keys it needs "
        "and ignores the rest, so adding a setting is deliberately a non-event.",
    ),
    # Backup Directory mirroring (data-saving.md §8)
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
            f("archived", BOOL),
            f("createdAt", STR),
            f("updatedAt", STR),
        ),
        doc="Enough for the grid and dashboard tile, no animal detail.",
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
    # Prefixes, sessions, Task Profiles (data-saving.md §3–§6)
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
        ),
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
                "walk can decode historical runs (`data-saving.md` §6.7). Declared, "
                "never inferred.",
            ),
            f("telemetry", Ref("TelemetrySpec"), optional=True, doc="Utility profiles only."),
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
        doc="One box's session-local mapping + task config (`starting-a-session.md` §3).",
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
            f("stopReason", STR, doc="`starting-a-session.md` §8's stop-reason set."),
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
    # Analytics (analytics.md §9)
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
        doc="One metric's whole-session result (`analytics.md` §3.2, §3.5).",
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
        doc="What actually happened per trial (`analytics.md` §3.8). Distinct "
        "from the declared metrics, which are reward-*unconditional* — they "
        "score a detected poke whether or not the fluid hold cleared.",
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
        doc="TrialOutcomes restricted to one declared condition (`analytics.md` "
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
        obj(f("id", STR), f("name", STR), f("groupId", STR), f("boxNumber", nullable(INT))),
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
        doc="One sample of the within-session strategy walk (`analytics.md` §4.4).",
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
            f("animalName", nullable(STR)),
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
        result=obj(f("arduinoDirectory", Ref("DirectoryStatus"))),
        doc="Sent on every connect and change, Tauri → sidecar only. The reply "
        "carries the immediate directory validation (`arduino-directory.md` §2).",
    ),
    Command(
        "sketches.refresh",
        result=Ref("SketchDiscovery"),
        doc="Manual Refresh and Debug Mode mount (`arduino-directory.md` §4).",
    ),
    Command(
        "port.passthrough.open",
        args=obj(f("box", INT), f("baud", INT, optional=True, doc="Default 115200, per box.")),
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
                "land in IDLE for the runner to claim (`starting-a-session.md` §4).",
            ),
        ),
        result=obj(f("state", Ref("PortStateName")), f("resumedPassthrough", BOOL)),
        doc="Streams flash.progress events carrying this command's `corr`.",
    ),
    Command(
        "port.reset",
        args=obj(f("box", INT)),
        result=obj(f("state", Ref("PortStateName")), f("resumedPassthrough", BOOL)),
        doc="DTR toggle (`hardware-interaction.md` §5).",
    ),
    Command(
        "port.error.ack",
        args=obj(f("box", INT)),
        result=_STATE,
        doc="ERROR → IDLE (`hardware-interaction.md` §3.2).",
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
        section="Prefixes, Task Profiles & sessions (data-saving.md §9, starting-a-session.md §9)",
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
        section="Backup (data-saving.md §8)",
    ),
    # Analytics
    Command(
        "sessions.list",
        args=obj(f("cohortId", STR), f("includeAborted", BOOL, optional=True)),
        result=obj(f("sessions", ListOf(Ref("SessionListItem")))),
        doc="Must never touch the filesystem, so selectors populate instantly.",
        section="Analytics (analytics.md §9)",
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
    ErrorCode("DIR_INVALID", "Defined but never raised — kept in case the reasoning reverses (§6)."),
    ErrorCode("INTERNAL", "Unhandled sidecar exception; also carried by sidecar.error."),
)


PROTOCOL = Protocol(
    version=VERSION,
    shapes=SHAPES,
    commands=COMMANDS,
    events=EVENTS,
    errors=ERRORS,
)

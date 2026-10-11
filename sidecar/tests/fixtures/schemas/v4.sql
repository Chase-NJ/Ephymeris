-- The schema as it shipped at v4: the SCHEMA and INDEXES statements in
-- cohorts/db.py at abf3ce4, the last commit before 02477c1 moved it to
-- v5. Statements verbatim, comments removed; never edit it to match
-- today's schema (`tests/test_migrations.py`).
CREATE TABLE IF NOT EXISTS cohorts (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    data_folder  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    archived_at  TEXT
);
CREATE TABLE IF NOT EXISTS groups (
    id         TEXT PRIMARY KEY,
    cohort_id  TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    "order"    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS animals (
    id          TEXT PRIMARY KEY,
    cohort_id   TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    group_id    TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    box_number  INTEGER,
    sex         TEXT,
    id_number   TEXT,
    notes       TEXT
);
CREATE TABLE IF NOT EXISTS prefixes (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    cohort_id      TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    prefix_id      TEXT NOT NULL,
    prefix_name    TEXT NOT NULL,
    session_number TEXT NOT NULL,
    date           TEXT NOT NULL,
    started_at     TEXT NOT NULL,
    ended_at       TEXT,
    status         TEXT NOT NULL,
    folder_path    TEXT NOT NULL,
    group_runs     TEXT NOT NULL DEFAULT '[]',
    duration_minutes INTEGER
);
CREATE TABLE IF NOT EXISTS session_animal_runs (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    animal_id   TEXT NOT NULL,
    box_number  INTEGER NOT NULL,
    sketch_path TEXT NOT NULL,
    file_path   TEXT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    stop_reason TEXT,
    profile_hash TEXT
);
CREATE TABLE IF NOT EXISTS task_profiles (
    hash          TEXT PRIMARY KEY,
    task_name     TEXT NOT NULL,
    kind          TEXT NOT NULL,
    profile_json  TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_metrics_cache (
    run_id         TEXT PRIMARY KEY,
    file_path      TEXT NOT NULL,
    file_mtime_ns  INTEGER,
    file_size      INTEGER,
    profile_hash   TEXT,
    profile_source TEXT NOT NULL,
    codec_version  INTEGER NOT NULL,
    computed_at    TEXT NOT NULL,
    status         TEXT NOT NULL,
    detail         TEXT,
    summary_json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adopted_runs (
    id             TEXT PRIMARY KEY,
    cohort_id      TEXT NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    animal_id      TEXT NOT NULL,
    file_path      TEXT NOT NULL,
    prefix_name    TEXT NOT NULL,
    session_number TEXT NOT NULL,
    date           TEXT,
    started_at     TEXT NOT NULL,
    sketch_name    TEXT,
    sketch_path    TEXT,
    adopted_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_groups_cohort  ON groups(cohort_id);
CREATE INDEX IF NOT EXISTS idx_animals_cohort ON animals(cohort_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cohorts_active_name
    ON cohorts(name COLLATE NOCASE) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_cohort ON sessions(cohort_id);
CREATE INDEX IF NOT EXISTS idx_runs_session    ON session_animal_runs(session_id);
CREATE INDEX IF NOT EXISTS idx_runs_animal     ON session_animal_runs(animal_id);
CREATE INDEX IF NOT EXISTS idx_runs_profile    ON session_animal_runs(profile_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_cohort_dt ON sessions(cohort_id, date);
CREATE INDEX IF NOT EXISTS idx_adopted_cohort ON adopted_runs(cohort_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_adopted_file ON adopted_runs(cohort_id, file_path);

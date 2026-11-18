/**
 * Session and prefix types — `DATA.md#sessions-and-runs`.
 *
 * The wire shapes live in the generated protocol module (`protocol/schema.py`
 * is their authority) and are re-exported here so callers keep one import
 * site; this file adds the client-side staging types and helpers.
 */

import type { Cohort } from "@/lib/cohorts/types";
import type { CommandResultMap, Session, TaskProfile } from "@/lib/ws/protocol";

export type {
  Prefix,
  SessionStatus,
  Round,
  Session,
  ConfigFieldType,
  ConfigField,
  LiveMetric,
  ProfileKind,
  ControlOption,
  Control,
  TelemetryField,
  TelemetrySpec,
  TaskProfile,
  TelemetryMetric,
  BoxTelemetry,
  AnimalEnded,
  SessionBox,
  RunnerSession,
} from "@/lib/ws/protocol";

/** `sessions.status` — named for the snapshot it is, since `SessionStatus`
 *  is already the record's lifecycle state. */
export type SessionSnapshot = CommandResultMap["sessions.status"];

/**
 * `sessions.active` result and `session.lifecycle` payload — the global
 * "what is running?" answer. Its `running` is a `RunnerSession`: the session
 * and boxes of a `sessions.status` reply.
 */
export type ActiveSessions = CommandResultMap["sessions.active"];

// --- Configuration flow ---------------------------------------------------

/** One box's session-local mapping + task config (`ARCHITECTURE.md#mapping-and-the-placement-walk`). */
export interface BoxMapping {
  box: number;
  animalId: string;
  sketchPath: string | null;
  /**
   * Only the values the operator edited on the mapping step, keyed by
   * `metadataKey` — never a snapshot of the merged config. The full config is
   * rebuilt by `defaultConfig` from the CURRENT profile whenever it is shown
   * or confirmed (`TASKS.md#three-layer-merge`).
   */
  overrides: Record<string, unknown>;
}

/** A cohort is ready to run (`ARCHITECTURE.md#configuration`) once it has an animal. */
export function isReadyToRun(cohort: Pick<Cohort, "animals">): boolean {
  return cohort.animals.length > 0;
}

/**
 * A session the operator can pick back up with another round (`sessions.resume`):
 * today's, one that ran at least one round, and either ended (`completed`) or
 * left `running` by a closed app. Same day only — the folder carries its date.
 */
export function isContinuable(
  session: Pick<Session, "date" | "status" | "rounds">,
  today: string,
): boolean {
  return (
    session.date === today &&
    session.rounds.length > 0 &&
    (session.status === "completed" || session.status === "running")
  );
}

/** Local calendar date as `YYYY-MM-DD` — the sidecar writes `Session.date` this way. */
export function localToday(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/**
 * The values a box starts on, merged across the three layers of
 * `TASKS.md#three-layer-merge`: the profile's own defaults, then this rig's saved
 * defaults for the sketch, then anything already set on the box.
 *
 * The rig layer is filtered through the profile rather than spread over it, so
 * a saved default for a field the sketch no longer declares can't survive an
 * edit to `task.json` and reappear on the wire as a stale token.
 */
export function defaultConfig(
  profile: TaskProfile | null,
  rigDefaults: Record<string, unknown> = {},
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  if (!profile) return {};
  return Object.fromEntries(
    profile.config.map((f) => {
      const key = f.metadataKey;
      if (key in overrides) return [key, overrides[key]];
      if (key in rigDefaults) return [key, rigDefaults[key]];
      return [key, f.default];
    }),
  );
}

/** A sketch's Task Profile as read; `profile` null means the sketch has none. */
export interface ReadProfile {
  sketchPath: string;
  profile: TaskProfile | null;
}

/**
 * What a START sent by hand from Debug Mode carries for `sketchPath`, or null
 * while there is nothing right to send: its profile not read yet, or the one
 * read belongs to the sketch the board carried before.
 *
 * `defaultConfig` without a profile is `{}`, which is right for a sketch that
 * declares none and wrong for one whose profile is still on its way: the
 * sidecar fills each field from the profile's own default, and this rig's
 * `taskDefaults` never reach the board.
 */
export function startConfig(
  sketchPath: string,
  read: ReadProfile | null,
  rigDefaults: Record<string, unknown>,
): Record<string, unknown> | null {
  if (read === null || read.sketchPath !== sketchPath) return null;
  return defaultConfig(read.profile, rigDefaults);
}

/**
 * The overrides after one edit of a form that reports whole configs: every key
 * whose value moved between what was `shown` and the `next` it reported is now
 * the operator's own, even one set to the value underneath.
 *
 * Measured against the form's previous value, never against the baseline.
 * "Differs from the baseline" is what goes stale: once a seeded value was kept,
 * a later change to the profile's default turned the untouched field into an
 * apparent override and the old default reached the wire
 * (`TASKS.md#three-layer-merge`).
 */
export function editedOverrides(
  overrides: Record<string, unknown>,
  shown: Record<string, unknown>,
  next: Record<string, unknown>,
): Record<string, unknown> {
  const out = { ...overrides };
  for (const [key, value] of Object.entries(next)) {
    if (!Object.is(value, shown[key])) out[key] = value;
  }
  return out;
}

/**
 * How many of a box's values differ from what the layers underneath give it:
 * the number a row shows so tuned boxes stand out without opening them. An
 * override set back to the value underneath counts as none.
 */
export function overriddenCount(
  profile: TaskProfile | null,
  rigDefaults: Record<string, unknown>,
  overrides: Record<string, unknown>,
): number {
  if (!profile) return 0;
  const baseline = defaultConfig(profile, rigDefaults);
  const config = defaultConfig(profile, rigDefaults, overrides);
  return profile.config.filter(
    (f) => f.metadataKey in config && !Object.is(config[f.metadataKey], baseline[f.metadataKey]),
  ).length;
}

/** The overrides with these keys dropped, so those fields follow the layers underneath again. */
export function withoutOverrides(
  overrides: Record<string, unknown>,
  keys: readonly string[],
): Record<string, unknown> {
  const out = { ...overrides };
  for (const key of keys) delete out[key];
  return out;
}

/**
 * This rig's saved defaults for one sketch. Keyed by folder name rather than
 * path — the two lab machines keep their Arduino Directories in different
 * places, and the name is what the session file already records.
 */
export function sketchName(sketchPath: string | null): string {
  if (!sketchPath) return "";
  const parts = sketchPath.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? "";
}

/** One row of a `grid` control — re-exported beside `Control` so Debug Mode's
 *  channel grid and Prime read the same shape from the same place. */
export type { ControlChannel } from "@/lib/ws/protocol";

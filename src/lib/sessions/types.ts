/**
 * Session and prefix types — `DATA.md#sessions-and-runs`.
 *
 * The wire shapes live in the generated protocol module (`protocol/schema.py`
 * is their authority) and are re-exported here so callers keep one import
 * site; this file adds the client-side staging types and helpers.
 */

import type { Animal, Cohort, Group } from "@/lib/cohorts/types";
import type { CommandResultMap, GroupRun, Session, TaskProfile } from "@/lib/ws/protocol";

export type {
  Prefix,
  SessionStatus,
  GroupRun,
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
} from "@/lib/ws/protocol";

/** `sessions.status` — named for the snapshot it is, since `SessionStatus`
 *  is already the record's lifecycle state. */
export type SessionSnapshot = CommandResultMap["sessions.status"];

/**
 * `sessions.active` result and `session.lifecycle` payload — the global
 * "what is running?" answer. `running` is the wire's `RunnerSession`, which is
 * structurally the `sessions.status` result, so the existing snapshot type
 * serves both; split only if the shapes ever diverge.
 */
export type ActiveSessions = CommandResultMap["sessions.active"];

// --- Configuration flow ---------------------------------------------------

/** One box's session-local mapping + task config (`ARCHITECTURE.md#mapping-and-the-placement-walk`). */
export interface BoxMapping {
  box: number;
  animalId: string;
  sketchPath: string | null;
  /** Keyed by `metadataKey`, per the sketch's Task Profile. */
  config: Record<string, unknown>;
}

/**
 * A cohort is ready to run (`ARCHITECTURE.md#configuration`) if it has at least one group with at least one
 * animal that has a `boxNumber` assigned. A group with none is skipped rather
 * than blocking the cohort.
 */
export function isReadyToRun(cohort: Cohort): boolean {
  return cohort.animals.some((a) => a.boxNumber !== null);
}

/**
 * Groups that hold at least one box-assigned animal, in the cohort's display
 * order. Not a run order — there is none: the operator picks which group runs,
 * at setup and at every switch (`ARCHITECTURE.md#configuration`).
 */
export function populatedGroups(cohort: Cohort): Group[] {
  const populated = new Set(
    cohort.animals.filter((a) => a.boxNumber !== null).map((a) => a.groupId),
  );
  return [...cohort.groups]
    .filter((g) => populated.has(g.id))
    .sort((a, b) => a.order - b.order);
}

/** Every run of one group in this session, oldest first (a group may run twice). */
export function groupRunsFor(session: Session | null, groupId: string): GroupRun[] {
  return (session?.groupRuns ?? []).filter((run) => run.groupId === groupId);
}

/**
 * How many of the cohort's populated groups have run in this session, the one
 * on the rig included — each group once, however many times it ran.
 */
export function groupsRunCount(cohort: Cohort, session: Session | null): number {
  const done = new Set((session?.groupRuns ?? []).map((r) => r.groupId));
  return populatedGroups(cohort).filter((g) => done.has(g.id)).length;
}

/** Whether every populated group has run in this session. */
export function allGroupsRun(cohort: Cohort, session: Session | null): boolean {
  return groupsRunCount(cohort, session) === populatedGroups(cohort).length;
}

/**
 * A session the operator can pick back up with another group (`sessions.resume`):
 * today's, one that ran at least one group, and either ended (`completed`) or
 * left `running` by a closed app. Same day only — the folder carries its date.
 */
export function isContinuable(
  session: Pick<Session, "date" | "status" | "groupRuns">,
  today: string,
): boolean {
  return (
    session.date === today &&
    session.groupRuns.length > 0 &&
    (session.status === "completed" || session.status === "running")
  );
}

/** Local calendar date as `YYYY-MM-DD` — the sidecar writes `Session.date` this way. */
export function localToday(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Box-assigned animals of one group, ordered by box number. */
export function animalsInGroup(cohort: Cohort, groupId: string): Animal[] {
  return cohort.animals
    .filter((a) => a.groupId === groupId && a.boxNumber !== null)
    .sort((a, b) => (a.boxNumber ?? 0) - (b.boxNumber ?? 0));
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

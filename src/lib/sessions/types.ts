/**
 * Session and prefix types — `data-saving.md` §3–§6.
 *
 * The wire shapes live in the generated protocol module (`protocol/schema.py`
 * is their authority) and are re-exported here so callers keep one import
 * site; this file adds the client-side staging types and helpers.
 */

import type { Animal, Cohort, Group } from "@/lib/cohorts/types";
import type { CommandResultMap, TaskProfile } from "@/lib/ws/protocol";

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

/** One box's session-local mapping + task config (`starting-a-session.md` §3). */
export interface BoxMapping {
  box: number;
  animalId: string;
  sketchPath: string | null;
  /** Keyed by `metadataKey`, per the sketch's Task Profile. */
  config: Record<string, unknown>;
}

/**
 * §1 — a cohort is ready to run if it has at least one group with at least one
 * animal that has a `boxNumber` assigned. A group with none is skipped rather
 * than blocking the cohort (§2.3).
 */
export function isReadyToRun(cohort: Cohort): boolean {
  return cohort.animals.some((a) => a.boxNumber !== null);
}

/** Groups that hold at least one box-assigned animal, in run order. */
export function populatedGroups(cohort: Cohort): Group[] {
  const populated = new Set(
    cohort.animals.filter((a) => a.boxNumber !== null).map((a) => a.groupId),
  );
  return [...cohort.groups]
    .filter((g) => populated.has(g.id))
    .sort((a, b) => a.order - b.order);
}

/** §2.3 — the session begins with the lowest-`order` populated group. */
export function firstGroupToRun(cohort: Cohort): Group | null {
  return populatedGroups(cohort)[0] ?? null;
}

/** Box-assigned animals of one group, ordered by box number. */
export function animalsInGroup(cohort: Cohort, groupId: string): Animal[] {
  return cohort.animals
    .filter((a) => a.groupId === groupId && a.boxNumber !== null)
    .sort((a, b) => (a.boxNumber ?? 0) - (b.boxNumber ?? 0));
}

/** Defaults from a profile's `config`, used to seed the pre-flight form (§3). */
export function defaultConfig(profile: TaskProfile | null): Record<string, unknown> {
  if (!profile) return {};
  return Object.fromEntries(profile.config.map((f) => [f.metadataKey, f.default]));
}

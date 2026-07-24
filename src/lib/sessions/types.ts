/**
 * Session and prefix types — mirrors `data-saving.md` §3–§6 and the payload
 * shapes in `websocket-protocol.md` §4.
 */

import type { Animal, Cohort, Group } from "@/lib/cohorts/types";

export interface Prefix {
  id: string;
  name: string;
}

export type SessionStatus = "configuring" | "running" | "completed" | "aborted";

export interface GroupRun {
  groupId: string;
  order: number;
  startedAt: string;
  endedAt: string | null;
}

export interface Session {
  id: string;
  cohortId: string;
  prefixId: string;
  prefixName: string;
  sessionNumber: string;
  date: string;
  startedAt: string;
  endedAt: string | null;
  status: SessionStatus;
  folderPath: string;
  groupRuns: GroupRun[];
}

// --- Task Profiles (data-saving.md §6) ------------------------------------

export type ConfigFieldType = "int" | "float" | "bool" | "string";

export interface ConfigField {
  /** The `.json`/`.mat` field name, and the key the form collects under. */
  metadataKey: string;
  /** The `START` command token (§6.3). */
  wireKey: string;
  label: string;
  type: ConfigFieldType;
  default: unknown;
}

export interface LiveMetric {
  id: string;
  label: string;
  triggerCode: number;
  successCode: number;
  alternateCode: number;
  windowSize: number;
}

/** Sketch kind (§6.2): a scored IN_SESSION task, or a PASSTHROUGH tool. */
export type ProfileKind = "behavior" | "utility";

/** One choice in a `select` control — a label + the serial command it sends. */
export interface ControlOption {
  label: string;
  command: string;
}

/**
 * A utility control the app renders in Debug Mode (§6.6). `button` carries a
 * single `command`; `select` carries `options`. Both send over `port.send`.
 */
export interface Control {
  id: string;
  label: string;
  type: "button" | "select";
  command?: string;
  options?: ControlOption[];
}

export interface TelemetryField {
  key: string;
  label: string;
}

/**
 * How to parse a utility sketch's non-persisted `STATUS` lines out of
 * `port.output` (§6.6). A line beginning with `match` carries space-separated
 * `key=value` pairs; `fields` names the ones worth labelling. Parsed client-side
 * — nothing here is stored.
 */
export interface TelemetrySpec {
  match: string;
  fields: TelemetryField[];
}

export interface TaskProfile {
  taskName: string;
  /** Defaults to "behavior" when a profile omits it. */
  kind?: ProfileKind;
  config: ConfigField[];
  /** code → human name; display/debug only, metrics use raw codes. */
  strobes: Record<string, string>;
  liveMetrics: LiveMetric[];
  /** Utility profiles only — the Debug-Mode controls (§6.6). */
  controls?: Control[];
  /** Utility profiles only — how to parse `STATUS` telemetry (§6.6). */
  telemetry?: TelemetrySpec;
}

// --- Live telemetry -------------------------------------------------------

export interface TelemetryMetric {
  id: string;
  /** P(hit) over the rolling window; null until a trial counts. */
  value: number | null;
  /** Counted (hit-or-miss) trials in the window. */
  n: number;
}

export interface BoxTelemetry {
  box: number;
  animalId: string;
  metrics: TelemetryMetric[];
}

export interface AnimalEnded {
  box: number;
  animalId: string;
  stopReason: string;
  filePath: string | null;
}

/** One box as the runner sees it — the source Mission Control renders (§5). */
export interface SessionBox {
  box: number;
  animalId: string;
  animalName: string;
  sketchName: string;
  sketchPath: string;
  running: boolean;
}

/** `sessions.status` — named for the snapshot it is, since `SessionStatus`
 *  above is already the record's lifecycle state. */
export interface SessionSnapshot {
  session: Session;
  groupId: string;
  boxes: SessionBox[];
}

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

/**
 * Cohort data model — mirrors `cohorts.md` §1 and the payload shapes in
 * `websocket-protocol.md` §4.
 *
 * The icon is deliberately absent: it is derived client-side from `id`
 * (`cohorts.md` §5), so nothing about it is stored or transmitted.
 */

export const MIN_BOX = 1;
export const MAX_BOX = 6;
/** §7.2 — box numbers only span 1–6, so a larger group can't be assigned. */
export const MAX_GROUP_SIZE = MAX_BOX;

export type Sex = "M" | "F" | "unknown";

export interface Group {
  id: string;
  name: string;
  /** Run order for consecutive execution — consumed by the session doc. */
  order: number;
}

export interface Animal {
  id: string;
  name: string;
  groupId: string;
  /** Abstract slot 1–6, never a live port. `null` = unassigned. */
  boxNumber: number | null;
  sex: Sex | null;
  idNumber: string | null;
  notes: string | null;
}

export interface Cohort {
  id: string;
  name: string;
  /** Resolved once at creation and persisted verbatim (§8). */
  dataFolder: string;
  animals: Animal[];
  /** Always ≥ 1 — a default group exists even when the user never made one. */
  groups: Group[];
  archivedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

/** Enough for the grid and dashboard tile without full animal detail (§10). */
export interface CohortSummary {
  id: string;
  name: string;
  animalCount: number;
  groupCount: number;
  archived: boolean;
  createdAt: string;
  updatedAt: string;
}

// --- Auto-Balance preview (§7) --------------------------------------------

export interface ProposedAnimal {
  animalId: string;
  boxNumber: number;
}

export interface ProposedGroup {
  name: string;
  order: number;
  animals: ProposedAnimal[];
}

export interface GroupProposal {
  groups: ProposedGroup[];
  /**
   * Set when the request would break the §7.2 six-per-group constraint. The
   * tool answers with the minimum viable count rather than a bare failure.
   */
  rejected: { reason: string; minimumGroups: number } | null;
}

/** A `cohorts.update` patch — animals/groups are replaced wholesale. */
export interface CohortPatch {
  name?: string;
  animals?: Animal[];
  groups?: Group[];
}

export function isArchived(cohort: CohortSummary | Cohort): boolean {
  return "archived" in cohort ? cohort.archived : cohort.archivedAt !== null;
}

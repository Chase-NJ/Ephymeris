/**
 * Typed wrappers over the cohort commands (`websocket-protocol.md` §3.1).
 *
 * Keeps command names and payload shapes in one place rather than scattered
 * through components, and gives every caller the same typed result. Mutations
 * intentionally return nothing beyond the affected cohort: the list refreshes
 * through the `cohorts.updated` broadcast, not through a return value.
 */

import type { SidecarClient } from "../ws/client";
import { CMD, ERR, SidecarCommandError } from "../ws/protocol";
import type {
  Animal,
  Cohort,
  CohortPatch,
  CohortSummary,
  Group,
  GroupProposal,
} from "./types";

export async function listCohorts(client: SidecarClient): Promise<CohortSummary[]> {
  const result = (await client.call(CMD.COHORTS_LIST)) as { cohorts: CohortSummary[] };
  return result.cohorts;
}

export async function getCohort(client: SidecarClient, id: string): Promise<Cohort> {
  const result = (await client.call(CMD.COHORTS_GET, { id })) as { cohort: Cohort };
  return result.cohort;
}

/**
 * Create a cohort, roster and all.
 *
 * The roster travels with the create rather than following it in a patch: the
 * editor builds animals and groups client-side with their own ids before the
 * cohort exists, and sending them separately meant a second call that could
 * fail on its own and leave a named, empty cohort behind.
 */
export async function createCohort(
  client: SidecarClient,
  name: string,
  options: { dataFolder?: string; animals?: Animal[]; groups?: Group[] } = {},
): Promise<Cohort> {
  const args: {
    name: string;
    dataFolder?: string;
    animals?: Animal[];
    groups?: Group[];
  } = { name };
  if (options.dataFolder) args.dataFolder = options.dataFolder;
  if (options.animals && options.animals.length > 0) args.animals = options.animals;
  if (options.groups && options.groups.length > 0) args.groups = options.groups;
  const result = (await client.call(CMD.COHORTS_CREATE, args)) as { cohort: Cohort };
  return result.cohort;
}

export async function updateCohort(
  client: SidecarClient,
  id: string,
  patch: CohortPatch,
): Promise<Cohort> {
  const result = (await client.call(CMD.COHORTS_UPDATE, { id, patch })) as {
    cohort: Cohort;
  };
  return result.cohort;
}

export async function archiveCohort(client: SidecarClient, id: string): Promise<Cohort> {
  const result = (await client.call(CMD.COHORTS_ARCHIVE, { id })) as { cohort: Cohort };
  return result.cohort;
}

export async function restoreCohort(client: SidecarClient, id: string): Promise<Cohort> {
  const result = (await client.call(CMD.COHORTS_RESTORE, { id })) as { cohort: Cohort };
  return result.cohort;
}

/** §9 — rejected by the sidecar unless the cohort is already archived. */
export async function deleteCohort(client: SidecarClient, id: string): Promise<void> {
  await client.call(CMD.COHORTS_DELETE, { id, confirm: true });
}

/** §8's explicit relocate — never triggered by a rename. */
export async function setDataFolder(
  client: SidecarClient,
  id: string,
  path: string,
  moveExisting: boolean,
): Promise<Cohort> {
  const result = (await client.call(CMD.COHORTS_SET_DATA_FOLDER, {
    id,
    path,
    moveExisting,
  })) as { cohort: Cohort };
  return result.cohort;
}

/** §7 preview — computes only; the caller applies via `updateCohort`. */
export async function suggestGroups(
  client: SidecarClient,
  id: string,
  options: { groupCount?: number; maxGroupSize?: number; balanceBySex?: boolean },
): Promise<GroupProposal> {
  return (await client.call(CMD.COHORTS_SUGGEST_GROUPS, {
    id,
    ...options,
  })) as GroupProposal;
}

/**
 * Per-field validation errors from a `COHORT_INVALID` rejection, so the editor
 * can render them against the offending row rather than as a detached toast
 * (§6). Any other failure returns null and should surface as a general message.
 */
export function fieldErrors(err: unknown): Record<string, string> | null {
  if (!(err instanceof SidecarCommandError)) return null;

  // `COHORT_NAME_TAKEN` doesn't carry a message map — its detail names the
  // offending *field* (`{field: "name"}`) and the message is on the error
  // itself. Mapping it by hand is what makes it render: taking the detail
  // literally produced `{field: "name"}`, a key nothing displays, and because
  // a non-null return suppresses the fallback message the whole rejection
  // vanished. A duplicate name silently did nothing at all.
  if (err.code === ERR.COHORT_NAME_TAKEN) {
    const field =
      typeof err.detail === "object" &&
      err.detail !== null &&
      typeof (err.detail as Record<string, unknown>)["field"] === "string"
        ? ((err.detail as Record<string, unknown>)["field"] as string)
        : "name";
    return { [field]: err.message };
  }

  if (err.code !== ERR.COHORT_INVALID) return null;
  const detail = err.detail;
  if (typeof detail !== "object" || detail === null) return null;
  const entries = Object.entries(detail as Record<string, unknown>).filter(
    ([, v]) => typeof v === "string",
  );
  return entries.length > 0 ? (Object.fromEntries(entries) as Record<string, string>) : null;
}

export function errorMessage(err: unknown): string {
  if (err instanceof SidecarCommandError) return err.message;
  return err instanceof Error ? err.message : String(err);
}

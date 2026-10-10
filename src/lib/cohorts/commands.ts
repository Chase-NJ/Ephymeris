/**
 * Typed wrappers over the cohort commands (`PROTOCOL.md#cohorts`).
 *
 * Keeps command names and payload shapes in one place rather than scattered
 * through components, and gives every caller the same typed result. Mutations
 * intentionally return nothing beyond the affected cohort: the list refreshes
 * through the `cohorts.updated` broadcast, not through a return value.
 */

import type { SidecarClient } from "../ws/client";
import { CMD, ERR, SidecarCommandError, type AnimalMovePlan } from "../ws/protocol";
import type {
  Animal,
  Cohort,
  CohortPatch,
  Group,
} from "./types";

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

/** Rejected by the sidecar (`DATA.md#archive-and-delete`) unless the cohort is already archived. */
export async function deleteCohort(client: SidecarClient, id: string): Promise<void> {
  await client.call(CMD.COHORTS_DELETE, { id, confirm: true });
}

/** The explicit relocate (`DATA.md#data-folder`) — never triggered by a rename. */
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

/**
 * Move animals, their files and their history to another cohort
 * (`DATA.md#moving-animals-between-cohorts`). `apply: false` is the preview;
 * the sidecar re-plans on apply rather than trusting the preview it sent. A
 * refused apply rejects with `ANIMAL_MOVE_REFUSED` and the fresh plan as its
 * detail — see `refusedPlan`.
 */
export async function moveAnimals(
  client: SidecarClient,
  args: {
    cohortId: string;
    animalIds: string[];
    destinationCohortId: string;
    destinationGroupId?: string;
    apply: boolean;
  },
): Promise<AnimalMovePlan> {
  return (await client.call(CMD.COHORTS_MOVE_ANIMALS, args)) as AnimalMovePlan;
}

/** The plan a refused apply carries, so the dialog can show why. */
export function refusedPlan(err: unknown): AnimalMovePlan | null {
  if (err instanceof SidecarCommandError && err.code === ERR.ANIMAL_MOVE_REFUSED) {
    return (err.detail as AnimalMovePlan | null) ?? null;
  }
  return null;
}

/**
 * Per-field validation errors from a `COHORT_INVALID` rejection, so the editor
 * can render them against the offending row rather than as a detached toast
 * (`DATA.md#validation`). Any other failure returns null and should surface as a general message.
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

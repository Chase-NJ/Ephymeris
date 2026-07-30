/**
 * Typed wrappers over the analytics commands (`websocket-protocol.md` §3.4).
 *
 * Same pattern as `cohorts/commands.ts`: command names and payload shapes in
 * one place rather than scattered through components.
 */

import type { SidecarClient } from "../ws/client";
import { CMD, SidecarCommandError } from "../ws/protocol";
import type {
  AnalyticsSummary,
  DiskSession,
  RecoverResult,
  RescanResult,
  SeriesResult,
  SessionListItem,
} from "./types";

/**
 * A cohort's sessions. Cheap by construction — the sidecar never touches the
 * filesystem for this — so the selectors populate while the summary is still
 * reading files.
 */
export async function listSessions(
  client: SidecarClient,
  cohortId: string,
  includeAborted = false,
): Promise<SessionListItem[]> {
  const result = (await client.call(CMD.SESSIONS_LIST, { cohortId, includeAborted })) as {
    sessions: SessionListItem[];
  };
  return result.sessions;
}

/**
 * The whole cohort table in one call. Every session and animal selection
 * filters this client-side rather than re-querying (§9).
 */
export async function getSummary(
  client: SidecarClient,
  cohortId: string,
): Promise<AnalyticsSummary> {
  return (await client.call(CMD.ANALYTICS_SUMMARY, { cohortId })) as AnalyticsSummary;
}

/** Within-session trajectories. Plural so one session is one call, not six. */
export async function getSeries(
  client: SidecarClient,
  runIds: string[],
  mode: "rolling" | "cumulative" = "rolling",
): Promise<SeriesResult> {
  return (await client.call(CMD.ANALYTICS_SERIES, { runIds, mode })) as SeriesResult;
}

/**
 * The N most recent session folders across every active cohort's archive, by
 * folder-name date — directory names only, so it is cheap enough for the
 * Dashboard. Sees sessions other Ephymeris machines wrote into the shared
 * archive (`recorded: false`), which `sessions.list` cannot.
 */
export async function recentSessions(
  client: SidecarClient,
  limit?: number,
): Promise<DiskSession[]> {
  const result = (await client.call(
    CMD.ANALYTICS_RECENT_SESSIONS,
    limit === undefined ? {} : { limit },
  )) as { sessions: DiskSession[] };
  return result.sessions;
}

/** The explicit archive walk — never a side effect of opening the view. */
export async function rescan(
  client: SidecarClient,
  cohortId: string,
): Promise<RescanResult> {
  return (await client.call(CMD.ANALYTICS_RESCAN, { cohortId })) as RescanResult;
}

/**
 * The crash-recovery backfill (`data-saving.md` §7.3): rebuild `.json`/`.mat`
 * from orphaned write-ahead `.tsv` files. Same explicit-action discipline as
 * the rescan — and its natural follow-up, since a recovered file is an orphan
 * the rescan can then adopt.
 */
export async function recover(
  client: SidecarClient,
  cohortId: string,
): Promise<RecoverResult> {
  return (await client.call(CMD.SESSIONS_RECOVER, { cohortId })) as RecoverResult;
}

export function errorMessage(err: unknown): string {
  if (err instanceof SidecarCommandError) return err.message;
  return err instanceof Error ? err.message : String(err);
}

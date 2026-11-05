import { ERR, SidecarCommandError, type BackupStatus } from "@/lib/ws/protocol";

/**
 * How the sidecar's backup report reads (`DATA.md#failures`), shared by
 * Settings' note, its Storage tile and Mission Control's pill so no two of
 * them can disagree. Pure: it maps what the sidecar said and predicts nothing.
 */
export type BackupTone = "error" | "warning" | "ok" | "neutral";

export const BACKUP_TONE_COLOR: Record<BackupTone, string> = {
  error: "var(--color-status-error)",
  warning: "var(--color-status-warning)",
  ok: "var(--color-status-ok)",
  neutral: "var(--color-static)",
};

/**
 * A "Sync now" that didn't complete. `refused` is the sidecar declining the
 * command (`BACKUP_UNAVAILABLE`: a sync already running, or no directory set),
 * which says nothing about the target; anything else is a sync that failed.
 */
export interface SyncError {
  message: string;
  refused: boolean;
}

export function syncErrorFrom(error: unknown): SyncError {
  return {
    message: error instanceof Error ? error.message : String(error),
    refused: error instanceof SidecarCommandError && error.code === ERR.BACKUP_UNAVAILABLE,
  };
}

/** Whether the backup reads as failing: a failed pass, or a sync that failed. */
function failing(status: BackupStatus, syncError: SyncError | null): boolean {
  return status.state === "failed" || (syncError !== null && !syncError.refused);
}

export function backupTone(status: BackupStatus, syncError: SyncError | null): BackupTone {
  if (failing(status, syncError)) return "error";
  if (status.state === "deferred" || status.state === "pending") return "warning";
  if (status.state === "ok") return "ok";
  return "neutral";
}

/**
 * The Storage tile's phrase for a configured mirror, ordered as `backupTone`
 * is so the phrase and its colour always agree.
 */
export function backupPhrase(status: BackupStatus, syncError: SyncError | null): string {
  if (failing(status, syncError)) return "backup failing";
  if (status.state === "deferred") return "database copy deferred";
  if (status.state === "pending") return "first mirror pass pending";
  return `mirroring every ${Math.round(status.intervalSeconds)}s`;
}

/** What Settings says about a deferred database copy, in full. */
export const DEFERRED_DETAIL =
  "The database copy is waiting for a write to finish; the next pass makes it.";

/**
 * Mission Control's pill: near-silent while healthy, in words when not
 * (`DATA.md#backup-mirroring`).
 */
export function backupPill(status: BackupStatus): { text: string; tone: BackupTone; title: string } {
  if (status.state === "failed") {
    return {
      text: "backup failing",
      tone: "error",
      title: status.lastError ?? "The backup directory isn't writable.",
    };
  }
  if (status.state === "deferred") {
    return { text: "backup deferred", tone: "warning", title: DEFERRED_DETAIL };
  }
  if (status.state === "pending") {
    // Not "ok": a freshly set, unreachable directory hasn't been proven yet.
    return {
      text: "backup pending",
      tone: "warning",
      title: `Waiting for the first mirror pass to ${status.directory}`,
    };
  }
  return { text: "backup ok", tone: "neutral", title: `Mirroring to ${status.directory}` };
}

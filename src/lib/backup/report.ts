import type { BackupStatus } from "@/lib/ws/protocol";

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

export function backupTone(status: BackupStatus, syncError: string | null): BackupTone {
  if (status.state === "failed" || syncError) return "error";
  if (status.state === "deferred" || status.state === "pending") return "warning";
  if (status.state === "ok") return "ok";
  return "neutral";
}

/**
 * The Storage tile's phrase for a configured mirror, ordered as `backupTone`
 * is so the phrase and its colour always agree.
 */
export function backupPhrase(status: BackupStatus, syncError: string | null): string {
  if (status.state === "failed" || syncError) return "backup failing";
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
  return { text: "backup ok", tone: "neutral", title: `Mirroring to ${status.directory}` };
}

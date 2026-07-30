import { motion } from "framer-motion";
import { Check, CircleAlert, FolderOpen, Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/common/controls";
import { springPanel } from "@/lib/motion";
import type { BackupStatus, SyncResult } from "@/lib/backup/useBackupStatus";

/**
 * What the Backup Directory is actually doing (`data.md` §7).
 *
 * The reason this exists at all: a setting that silently does nothing is a
 * promise the app doesn't keep — and so is a backup that silently stopped
 * working. A dead network share has to be visible here, not only in a log.
 */
export function BackupStatusNote({
  status,
  onSync,
  canSync,
  syncError,
  lastSync,
}: {
  status: BackupStatus;
  onSync: () => void;
  canSync: boolean;
  syncError: string | null;
  lastSync: SyncResult | null;
}) {
  const tone =
    status.state === "failed" || syncError
      ? "error"
      : status.state === "ok"
        ? "ok"
        : status.state === "pending"
          ? "warning"
          : "neutral";

  const color = {
    error: "var(--color-status-error)",
    warning: "var(--color-status-warning)",
    ok: "var(--color-status-ok)",
    neutral: "var(--color-static)",
  }[tone];

  return (
    <motion.div
      layout
      transition={springPanel}
      className="mt-2 flex items-start gap-2.5 rounded-sm border border-halo bg-void/40 px-3 py-2.5"
    >
      <span className="mt-px shrink-0" style={{ color }}>
        {status.syncing ? (
          <Loader2 size={14} strokeWidth={1.75} className="animate-spin" />
        ) : !status.configured ? (
          <FolderOpen size={14} strokeWidth={1.75} />
        ) : tone === "ok" ? (
          <Check size={14} strokeWidth={2} />
        ) : (
          <CircleAlert size={14} strokeWidth={1.75} />
        )}
      </span>

      <div className="min-w-0 flex-1 text-[12px] leading-relaxed">
        <Body status={status} syncError={syncError} lastSync={lastSync} />
      </div>

      {status.configured && (
        <Button
          variant="ghost"
          onClick={onSync}
          disabled={!canSync || status.syncing}
          title="Copy anything the mirror is missing"
        >
          <RefreshCw size={13} strokeWidth={1.75} />
        </Button>
      )}
    </motion.div>
  );
}

function Body({
  status,
  syncError,
  lastSync,
}: {
  status: BackupStatus;
  syncError: string | null;
  lastSync: SyncResult | null;
}) {
  if (!status.configured) {
    return (
      <span className="text-static">
        No backup directory set. Session files and the cohort database are
        written to the data directory only — safe against a crash, but not
        against losing that drive.
      </span>
    );
  }

  if (syncError) {
    return <span className="text-starlight">Sync failed: {syncError}</span>;
  }

  if (status.syncing) {
    return <span className="text-static">Copying everything not yet mirrored…</span>;
  }

  if (status.state === "failed") {
    return (
      <span className="text-starlight">
        Mirroring is failing — {status.lastError ?? "the backup directory isn't writable"}.
        <span className="block text-static">
          Session data is still being saved locally. Retrying every{" "}
          {Math.round(status.intervalSeconds)}s.
        </span>
      </span>
    );
  }

  if (status.state === "pending") {
    return <span className="text-static">Waiting for the first mirror pass…</span>;
  }

  return (
    <span className="text-static">
      Mirroring every <span className="font-mono text-starlight">
        {Math.round(status.intervalSeconds)}s
      </span>
      {status.tracking > 0 && (
        <>
          {" · "}
          <span className="font-mono text-starlight">{status.tracking}</span> live{" "}
          {status.tracking === 1 ? "file" : "files"}
        </>
      )}
      {status.pending > 0 && (
        <>
          {" · "}
          <span className="font-mono text-starlight">{status.pending}</span> queued
        </>
      )}
      {lastSync && (
        <>
          {" · "}
          last sync copied{" "}
          <span className="font-mono text-starlight">{lastSync.copied}</span>
          {lastSync.failed > 0 && (
            <span style={{ color: "var(--color-status-warning)" }}>
              , {lastSync.failed} failed
            </span>
          )}
        </>
      )}
    </span>
  );
}

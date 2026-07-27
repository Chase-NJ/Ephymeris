import { useCallback, useEffect, useState } from "react";

import { CMD, EVT, type BackupState, type BackupStatus, type SyncResult } from "@/lib/ws/protocol";
import { useSidecar } from "@/lib/ws/context";

/**
 * Live Backup Directory mirroring state (`data-saving.md` §8).
 *
 * A hook rather than a provider: unlike hardware state, nothing needs this on
 * every screen or needs it to accumulate while unmounted. The sidecar replays
 * `backup.status` on connect, so a component mounting mid-session gets the
 * current picture from the next connect or the next status change rather than
 * having to ask.
 */

export type { BackupState, BackupStatus, SyncResult } from "@/lib/ws/protocol";

const UNKNOWN: BackupStatus = {
  configured: false,
  directory: null,
  state: "disabled",
  pending: 0,
  tracking: 0,
  mirroredFiles: 0,
  lastSuccessAt: null,
  lastError: null,
  syncing: false,
  intervalSeconds: 10,
};

function parse(data: unknown): BackupStatus | null {
  if (typeof data !== "object" || data === null) return null;
  const raw = data as Record<string, unknown>;
  return {
    configured: raw.configured === true,
    directory: typeof raw.directory === "string" ? raw.directory : null,
    state: (["disabled", "pending", "ok", "failed"] as const).includes(
      raw.state as BackupState,
    )
      ? (raw.state as BackupState)
      : "disabled",
    pending: typeof raw.pending === "number" ? raw.pending : 0,
    tracking: typeof raw.tracking === "number" ? raw.tracking : 0,
    mirroredFiles: typeof raw.mirroredFiles === "number" ? raw.mirroredFiles : 0,
    lastSuccessAt: typeof raw.lastSuccessAt === "string" ? raw.lastSuccessAt : null,
    lastError: typeof raw.lastError === "string" ? raw.lastError : null,
    syncing: raw.syncing === true,
    intervalSeconds:
      typeof raw.intervalSeconds === "number" ? raw.intervalSeconds : 10,
  };
}

export function useBackupStatus() {
  const { client } = useSidecar();
  const [status, setStatus] = useState<BackupStatus>(UNKNOWN);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<SyncResult | null>(null);

  useEffect(
    () =>
      client.on(EVT.BACKUP_STATUS, (data) => {
        const next = parse(data);
        if (next) setStatus(next);
      }),
    [client],
  );

  const syncNow = useCallback(async () => {
    setSyncError(null);
    setLastSync(null);
    // Optimistic only for the spinner — the sidecar's own status event is
    // what the badge reads, per the frontend-never-predicts-state rule.
    setStatus((s) => ({ ...s, syncing: true }));
    try {
      // The long reply timeout this needs lives in the client's per-command
      // override table, alongside flashing's.
      setLastSync(await client.call(CMD.BACKUP_SYNC_NOW));
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : String(error));
      setStatus((s) => ({ ...s, syncing: false }));
    }
  }, [client]);

  return { status, syncNow, syncError, lastSync };
}

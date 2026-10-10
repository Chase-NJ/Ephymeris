import { useEffect, useSyncExternalStore } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

/**
 * App updates, app-wide (`ARCHITECTURE.md#updates`).
 *
 * The shell does the work (`src-tauri/src/updater.rs`): it asks the feed,
 * downloads and verifies the signed installer, stops the sidecar and hands
 * over. This store only tracks where that is, so the Settings tile and the
 * sidebar dot agree. Module-level, like `exports/jobs.ts`: a download outlives
 * the route that started it.
 */

export interface UpdateInfo {
  version: string;
  currentVersion: string;
  /** RFC 3339, when the release was published. */
  date: string | null;
}

export type UpdatePhase =
  /** A dev build or a plain-browser preview: there is no installed app to update. */
  | { kind: "unsupported" }
  | { kind: "checking" }
  | { kind: "current" }
  | { kind: "available"; info: UpdateInfo }
  | { kind: "downloading"; info: UpdateInfo; downloaded: number; total: number | null }
  /** The sidecar is stopping and the installer is about to take over. */
  | { kind: "installing"; info: UpdateInfo }
  | { kind: "failed"; error: string; info: UpdateInfo | null };

/** How often a running app looks again. A lab PC can stay open for days. */
const RECHECK_MS = 6 * 60 * 60 * 1000;

const supported = isTauri() && !import.meta.env.DEV;

let phase: UpdatePhase = supported ? { kind: "checking" } : { kind: "unsupported" };
const listeners = new Set<() => void>();

function set(next: UpdatePhase) {
  phase = next;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useUpdate(): UpdatePhase {
  return useSyncExternalStore(subscribe, () => phase);
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export async function checkForUpdate(): Promise<void> {
  if (!supported) return;
  // Never interrupt a download or an install with a fresh check.
  if (phase.kind === "downloading" || phase.kind === "installing") return;
  set({ kind: "checking" });
  try {
    const info = await invoke<UpdateInfo | null>("update_check");
    set(info ? { kind: "available", info } : { kind: "current" });
  } catch (error) {
    // Offline is the usual cause, and not a fault: the tile says so quietly.
    set({ kind: "failed", error: message(error), info: null });
  }
}

/**
 * Download, then hand over to the installer. On Windows the app exits partway
 * through, so a resolved promise means it didn't (any other platform restarts).
 * The caller has already checked `installBlocker`.
 */
export async function installUpdate(): Promise<void> {
  if (phase.kind !== "available") return;
  const info = phase.info;
  set({ kind: "downloading", info, downloaded: 0, total: null });
  let unlisten: (() => void) | null = null;
  let stopListening: (() => void) | null = null;
  try {
    unlisten = await listen<{ downloaded: number; total: number | null }>(
      "update://progress",
      ({ payload }) => {
        if (phase.kind === "downloading") {
          set({ ...phase, downloaded: payload.downloaded, total: payload.total });
        }
      },
    );
    // The shell stops the sidecar once the download is verified, and says so
    // first, so the tile can explain the backend going down.
    stopListening = await listen("update://installing", () => {
      set({ kind: "installing", info });
    });
    await invoke("update_install");
  } catch (error) {
    set({ kind: "failed", error: message(error), info });
  } finally {
    unlisten?.();
    stopListening?.();
  }
}

/** Check at launch and every few hours after. Mount once (`AppShell`). */
export function useUpdateChecks(): void {
  useEffect(() => {
    if (!supported) return;
    void checkForUpdate();
    const timer = window.setInterval(() => void checkForUpdate(), RECHECK_MS);
    return () => window.clearInterval(timer);
  }, []);
}

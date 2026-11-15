/**
 * The Tauri shell (`src-tauri/`) behind `Shell`. The only file in `src/` that
 * may import `@tauri-apps/*` (`boundary.test.ts`).
 *
 * Each method maps onto one plugin or one command of the Rust shell, and the
 * permissions in `src-tauri/capabilities/` are what bound it.
 */

import { getVersion } from "@tauri-apps/api/app";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { open, save } from "@tauri-apps/plugin-dialog";
import { writeFile, writeTextFile } from "@tauri-apps/plugin-fs";
import { openPath } from "@tauri-apps/plugin-opener";
import { load, type Store } from "@tauri-apps/plugin-store";

import type { Shell, SidecarEndpoint, UpdateInfo } from "./types";

/** Whether this webview is running inside the Tauri shell. */
export function inTauri(): boolean {
  return isTauri();
}

const STORE_FILE = "settings.json";
const SETTINGS_KEY = "settings";

let storePromise: Promise<Store> | null = null;

function settingsStore(): Promise<Store> {
  // Never cache a *rejected* promise: a single failed open (a transient IO
  // error) would otherwise make every later save fail for the rest of the
  // session, and the only screen that can fix a bad config is the one that
  // stops saving.
  storePromise ??= load(STORE_FILE, { autoSave: false }).catch((err: unknown) => {
    storePromise = null;
    throw err;
  });
  return storePromise;
}

export const tauriShell: Shell = {
  sidecar: {
    endpoint: () => invoke<SidecarEndpoint | null>("sidecar_endpoint"),
    onReady: (handler) => listen<SidecarEndpoint>("sidecar://ready", (e) => handler(e.payload)),
    onDown: (handler) => listen("sidecar://down", () => handler()),
  },

  dialog: {
    async pickDirectory({ title, defaultPath }) {
      const picked = await open({
        directory: true,
        multiple: false,
        title,
        ...(defaultPath ? { defaultPath } : {}),
      });
      return typeof picked === "string" ? picked : null;
    },

    async pickFile({ title, filters }) {
      const picked = await open({ multiple: false, title, filters });
      return typeof picked === "string" ? picked : null;
    },

    // The dialog plugin adds the chosen path to the fs scope at runtime, which
    // is the only reason the write that follows is allowed at all.
    async saveFile({ defaultPath, filters, onChosen }, contents) {
      const path = await save({ defaultPath, filters });
      if (!path) return null;
      onChosen?.();
      if (typeof contents === "string") await writeTextFile(path, contents);
      else await writeFile(path, contents);
      return path;
    },
  },

  openPath: (path) => openPath(path),

  appVersion: () => getVersion(),

  settings: {
    async load() {
      return (await settingsStore()).get(SETTINGS_KEY);
    },
    async save(settings) {
      const store = await settingsStore();
      await store.set(SETTINGS_KEY, settings);
      await store.save();
    },
  },

  // `getCurrentWindow()` is called per use rather than once at import: touching
  // the Tauri bridge at module scope would throw wherever there is no shell.
  frame: {
    dragRegion: { "data-tauri-drag-region": true },
    minimize: () => getCurrentWindow().minimize(),
    toggleMaximize: () => getCurrentWindow().toggleMaximize(),
    isMaximized: () => getCurrentWindow().isMaximized(),
    onResized: (handler) => getCurrentWindow().onResized(() => handler()),
    close: () => getCurrentWindow().close(),
  },

  updates: {
    // A dev build is not an installed app; the Rust side refuses too.
    supported: isTauri() && !import.meta.env.DEV,

    check: () => invoke<UpdateInfo | null>("update_check"),

    async install({ onProgress, onInstalling }) {
      const unlisteners: Array<() => void> = [];
      try {
        unlisteners.push(
          await listen<{ downloaded: number; total: number | null }>("update://progress", ({ payload }) =>
            onProgress(payload.downloaded, payload.total),
          ),
        );
        unlisteners.push(await listen("update://installing", () => onInstalling()));
        await invoke("update_install");
      } finally {
        for (const unlisten of unlisteners) unlisten();
      }
    },
  },
};

/**
 * No shell at all: a plain-browser preview (`npm run dev` opened in a browser)
 * or a unit test. Everything that needs the OS rejects, which each caller
 * already turns into its own quiet fallback: default settings, a manual
 * sidecar endpoint (`lib/ws/client.ts`), a "couldn't open" on a folder button.
 * Subscriptions succeed and simply never fire.
 */

import type { Shell } from "./types";

function unavailable(): Promise<never> {
  return Promise.reject(new Error("no desktop shell: this is a plain-browser preview"));
}

const never = (): Promise<() => void> => Promise.resolve(() => {});

export const noShell: Shell = {
  sidecar: { endpoint: unavailable, onReady: never, onDown: never },
  dialog: { pickDirectory: unavailable, pickFile: unavailable, saveFile: unavailable },
  openPath: unavailable,
  appVersion: unavailable,
  settings: { load: unavailable, save: unavailable },
  frame: {
    dragRegion: {},
    minimize: unavailable,
    toggleMaximize: unavailable,
    isMaximized: unavailable,
    onResized: never,
    close: unavailable,
  },
  updates: { supported: false, check: unavailable, install: unavailable },
};

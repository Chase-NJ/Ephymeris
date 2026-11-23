/**
 * No shell at all: a plain-browser preview (`npm run dev` opened in a browser)
 * or a unit test. Everything that needs the OS rejects, which each caller
 * already turns into its own quiet fallback: default settings, a manual
 * sidecar endpoint (`lib/ws/client.ts`), a "couldn't open" on a folder button.
 * Subscriptions succeed and simply never fire.
 *
 * Settings are the one thing kept: in the page's `localStorage`, under
 * `ephymeris:settings`, so a preview against a simulated rig keeps its boxes
 * bound across reloads.
 */

import type { Shell } from "./types";

function unavailable(): Promise<never> {
  return Promise.reject(new Error("no desktop shell: this is a plain-browser preview"));
}

const never = (): Promise<() => void> => Promise.resolve(() => {});

const SETTINGS_KEY = "ephymeris:settings";

async function loadSettings(): Promise<unknown> {
  const raw = window.localStorage.getItem(SETTINGS_KEY);
  return raw === null ? undefined : JSON.parse(raw);
}

async function saveSettings(settings: unknown): Promise<void> {
  window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

export const noShell: Shell = {
  sidecar: { endpoint: unavailable, onReady: never, onDown: never },
  dialog: { pickDirectory: unavailable, pickFile: unavailable, saveFile: unavailable },
  openPath: unavailable,
  appVersion: unavailable,
  settings: { load: loadSettings, save: saveSettings },
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

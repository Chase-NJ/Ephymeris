/**
 * Persistence for settings — `tauri-plugin-store`, JSON on disk in the app data
 * dir (ephymeris_v1.0.md §4.5).
 *
 * Shell-owned rather than sidecar-owned on purpose: the fields most likely to
 * be *wrong* when something is misconfigured (save paths, `arduino-cli` path)
 * are exactly the ones that can stop the sidecar from starting. If the sidecar
 * owned settings, a bad config would lock the user out of the one screen that
 * fixes it.
 */

import { load, type Store } from "@tauri-apps/plugin-store";

import { DEFAULT_SETTINGS, normalizeSettings, type EphymerisSettings } from "./schema";

const STORE_FILE = "settings.json";
const SETTINGS_KEY = "settings";

let storePromise: Promise<Store> | null = null;

function getStore(): Promise<Store> {
  // Never cache a *rejected* promise: a single failed open — a transient IO
  // error, or a browser-preview run with no shell — would otherwise make every
  // later save fail for the rest of the session, and the only screen that can
  // fix a bad config is the one that stops saving.
  storePromise ??= load(STORE_FILE, { autoSave: false }).catch((err: unknown) => {
    storePromise = null;
    throw err;
  });
  return storePromise;
}

export async function loadSettings(): Promise<EphymerisSettings> {
  try {
    const store = await getStore();
    return normalizeSettings(await store.get(SETTINGS_KEY));
  } catch (err) {
    // No shell (browser preview) or an unreadable store. Defaults keep the
    // screen usable, which matters more here than anywhere else in the app.
    console.error("could not load settings; using defaults", err);
    return { ...DEFAULT_SETTINGS };
  }
}

export async function saveSettings(settings: EphymerisSettings): Promise<void> {
  try {
    const store = await getStore();
    await store.set(SETTINGS_KEY, settings);
    await store.save();
  } catch (err) {
    console.error("could not persist settings", err);
    throw err;
  }
}

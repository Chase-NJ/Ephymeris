/**
 * Persistence for settings — `settings.json` in the app data dir, kept by the
 * shell (`shell.settings`, `ARCHITECTURE.md#persistence-and-push`).
 *
 * Shell-owned rather than sidecar-owned on purpose: the fields most likely to
 * be *wrong* when something is misconfigured (save paths, `arduino-cli` path)
 * are exactly the ones that can stop the sidecar from starting. If the sidecar
 * owned settings, a bad config would lock the user out of the one screen that
 * fixes it.
 */

import { shell } from "@/lib/shell";

import { DEFAULT_SETTINGS, normalizeSettings, type EphymerisSettings } from "./schema";

export async function loadSettings(): Promise<EphymerisSettings> {
  try {
    return normalizeSettings(await shell.settings.load());
  } catch (err) {
    // No shell (browser preview) or an unreadable store. Defaults keep the
    // screen usable, which matters more here than anywhere else in the app.
    console.error("could not load settings; using defaults", err);
    return { ...DEFAULT_SETTINGS };
  }
}

export async function saveSettings(settings: EphymerisSettings): Promise<void> {
  try {
    await shell.settings.save(settings);
  } catch (err) {
    console.error("could not persist settings", err);
    throw err;
  }
}

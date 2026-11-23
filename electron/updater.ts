/**
 * Checking for and installing app updates (`ARCHITECTURE.md#updates`), on
 * `electron-updater`.
 *
 * The feed is the `generic` provider `electron-builder.yml` names, baked into
 * the installed copy as `resources/app-update.yml`: a `latest.yml` naming the
 * installer and its sha512. The download is refused unless its hash matches
 * (ADR 0006: hash only, over HTTPS from the repository).
 *
 * The webview asks; this does the work, because only the shell can stop the
 * sidecar first. Whether it is safe to install is the webview's call
 * (`features/updates/blocker.ts`), from what the sidecar reports.
 */

import { app } from "electron";
import updaterPackage from "electron-updater";

import type { UpdateInfo } from "./bridge.js";
import type { Sidecar } from "./sidecar.js";

/**
 * Long enough for the sidecar's own shutdown, which waits up to ~8 s for the
 * `arduino-cli` daemon before killing it.
 */
const SIDECAR_STOP_GRACE_MS = 12_000;

export interface InstallEvents {
  progress(downloaded: number, total: number | null): void;
  /** The download is verified and the sidecar is about to stop. */
  installing(): void;
}

/** Only an installed Windows copy updates itself; a dev run or a Mac never does. */
export function updatesSupported(): boolean {
  return app.isPackaged && process.platform === "win32";
}

export class Updater {
  private readonly updater = new updaterPackage.NsisUpdater();
  private available = false;
  private installing = false;

  constructor(private readonly sidecar: Sidecar) {
    const updater = this.updater;
    // Every step is the operator's click, never the updater's own idea.
    updater.autoDownload = false;
    updater.autoInstallOnAppQuit = false;
    // Every build is a prerelease (`1.1.3-alpha.214`); without these the
    // updater would look for `alpha.yml` and ignore newer prereleases.
    // Setting the channel turns downgrades on, so they go back off after it:
    // a bad release is fixed forward, never by installing an older one.
    updater.channel = "latest";
    updater.allowPrerelease = true;
    updater.allowDowngrade = false;
    // The feed names a full installer, never a web installer that fetches the app.
    updater.disableWebInstaller = true;
    updater.logger = console;
  }

  /** Ask the feed. Null when this copy is the newest, and always when updates are unsupported. */
  async check(): Promise<UpdateInfo | null> {
    if (!updatesSupported()) return null;
    const result = await this.updater.checkForUpdates();
    this.available = result?.isUpdateAvailable ?? false;
    if (!result || !this.available) return null;
    const info = result.updateInfo;
    return { version: info.version, currentVersion: app.getVersion(), date: info.releaseDate || null };
  }

  /**
   * Download and verify, stop the sidecar, then hand over to the installer.
   * The order matters: a bad download leaves the app running, and the
   * installer must find `arduino-cli.exe` unlocked, so the sidecar's own
   * shutdown finishes first. Resolving means the app did not exit.
   */
  async install(events: InstallEvents): Promise<void> {
    if (!this.available) throw new Error("no update to install; check first");
    if (this.installing) throw new Error("an update is already being installed");
    this.installing = true;
    const onProgress = (progress: { transferred: number; total: number }) =>
      events.progress(progress.transferred, progress.total || null);
    this.updater.on("download-progress", onProgress);
    try {
      // Rejects on a hash mismatch, before anything is stopped.
      await this.updater.downloadUpdate();
      events.installing();
      await this.sidecar.stop(SIDECAR_STOP_GRACE_MS);
      // Not silent: the installer shows its progress window. Then the new
      // copy starts.
      this.updater.quitAndInstall(false, true);
    } finally {
      this.updater.off("download-progress", onProgress);
      this.installing = false;
    }
  }
}

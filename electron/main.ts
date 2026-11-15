/**
 * The Electron shell's main process (ADR 0006, `ARCHITECTURE.md#the-electron-shell`).
 * Owns exactly what the Tauri shell owns: it starts the sidecar and says where
 * it listens, draws the windows, shows dialogs, writes the file the operator
 * picked, keeps `settings.json`, and installs updates. Every bit of state
 * lives in the sidecar.
 *
 * `npm run electron:dev` sets `EPHYMERIS_DEV_URL` and loads Vite; without it the
 * built `dist/` is served from `app://ephymeris/`.
 */

import { existsSync, statSync } from "node:fs";
import { join } from "node:path";

import { app, session } from "electron";

import type { UpdatesFlag } from "./bridge.js";
import { registerIpc } from "./ipc.js";
import { bundledEnv, resolveLaunch, type LaunchContext } from "./launch.js";
import { appBase } from "./origin.js";
import { SettingsFile } from "./settingsFile.js";
import { Sidecar } from "./sidecar.js";
import { Updater, updatesSupported } from "./updater.js";
import { registerAppScheme, serveApp, Windows } from "./window.js";

/** Tauri's bundle identifier, and the name of the app data folder both shells share. */
const APP_ID = "edu.hartlab.ephymeris";

app.setName("Ephymeris");
if (process.platform === "win32") app.setAppUserModelId(APP_ID);

registerAppScheme();

/**
 * The folder Tauri's `app_data_dir` named: `ephymeris.db`, `settings.json` and
 * the rest already live here. NOT Electron's `userData`, which is a different
 * folder (and fills with Chromium's caches): pointing the sidecar there would
 * make every setting and the database look missing after the switch.
 */
const dataDir = join(app.getPath("appData"), APP_ID);

const updatesFlag: UpdatesFlag = "--ephymeris-updates";
const windows = new Windows(
  // An installed copy never loads a dev server, whatever the environment says.
  appBase(app.isPackaged ? undefined : process.env["EPHYMERIS_DEV_URL"]),
  join(import.meta.dirname, "preload.cjs"),
  updatesSupported() ? [updatesFlag] : [],
);
const sidecar = new Sidecar({
  ready: (endpoint) => windows.broadcast("sidecar:ready", endpoint),
  down: () => windows.broadcast("sidecar:down", null),
});
const settings = new SettingsFile(join(dataDir, "settings.json"));
const updater = new Updater(sidecar);

app.on("web-contents-created", (_event, contents) => windows.lockDown(contents));

// Quit when the last window closes on every platform, macOS included: the app
// owns the sidecar's life, and a dockless shell holding serial ports is not a
// state anyone wants.
app.on("window-all-closed", () => app.quit());
app.on("will-quit", () => sidecar.shutdown());
process.on("exit", () => sidecar.shutdown());

void app.whenReady().then(() => {
  console.info(`Ephymeris ${app.getVersion()}; app data directory: ${dataDir}`);
  // An ordinary path, not Tauri's verbatim `\\?\C:\…`, which arduino-cli
  // silently mishandles (`ARCHITECTURE.md#which-sidecar-runs`).
  console.info(`resources: ${process.resourcesPath}`);

  // The only permission a page asks for is the clipboard (copying a debug log).
  session.defaultSession.setPermissionRequestHandler((_contents, permission, callback) =>
    callback(permission === "clipboard-sanitized-write"),
  );

  if (windows.base.protocol === "app:") serveApp(join(app.getAppPath(), "dist"));
  registerIpc({ windows, sidecar, settings, updater });
  windows.createMain();
  startSidecar();
});

/**
 * A failed spawn is reported to the webview (the sidecar shows as down) rather
 * than aborting startup: Settings must stay reachable when the sidecar will not
 * run, since a bad configuration is the likeliest reason it did not.
 */
function startSidecar(): void {
  const context: LaunchContext = {
    explicitPython: process.env["EPHYMERIS_SIDECAR_PYTHON"],
    packaged: app.isPackaged,
    repoRoot: app.getAppPath(),
    resourcesPath: process.resourcesPath,
    windows: process.platform === "win32",
    isFile: (path) => existsSync(path) && statSync(path).isFile(),
    isDirectory: (path) => existsSync(path) && statSync(path).isDirectory(),
  };
  try {
    sidecar.start(resolveLaunch(context), dataDir, bundledEnv(context));
  } catch (err) {
    console.error(`sidecar failed to start: ${(err as Error).message}`);
    windows.broadcast("sidecar:down", null);
  }
}

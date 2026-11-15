/**
 * The main process's half of the bridge (`bridge.ts`): one handler per channel,
 * each checking who is asking before doing anything.
 *
 * The same split as `src-tauri/capabilities/`: the main window may use every
 * channel, updates included; a recording pop-up only the sidecar's endpoint, its own frame, and
 * opening another pop-up (a probe-map site opens that channel's Spike Scope).
 * A frame that is not the top frame of one of this app's windows, showing one
 * of its pages, gets nothing.
 */

import { stat, writeFile } from "node:fs/promises";

import { app, BrowserWindow, dialog, ipcMain, shell, type IpcMainInvokeEvent } from "electron";

import type { EventChannels, FileFilter, InvokeChannels } from "./bridge.js";
import { isAppUrl } from "./origin.js";
import type { Sidecar } from "./sidecar.js";
import type { SettingsFile } from "./settingsFile.js";
import type { Updater } from "./updater.js";
import type { Windows } from "./window.js";

/** Who may use a channel: the main window only, or any window of this app. */
type Audience = "main" | "any";

type Handler<C extends keyof InvokeChannels> = (
  window: BrowserWindow,
  ...args: InvokeChannels[C]["args"]
) => InvokeChannels[C]["result"] | Promise<InvokeChannels[C]["result"]>;

export interface Services {
  windows: Windows;
  sidecar: Sidecar;
  settings: SettingsFile;
  updater: Updater;
}

export function registerIpc({ windows, sidecar, settings, updater }: Services): void {
  function handle<C extends keyof InvokeChannels>(channel: C, audience: Audience, handler: Handler<C>): void {
    ipcMain.handle(channel, (event: IpcMainInvokeEvent, ...args: unknown[]) => {
      const window = senderWindow(event, audience, windows);
      if (!window) throw new Error(`${channel} is not available to this window`);
      return handler(window, ...(args as InvokeChannels[C]["args"]));
    });
  }

  // The one path each window may write: whatever its last save dialog returned.
  const chosen = new Map<number, string>();

  handle("sidecar:endpoint", "any", () => sidecar.endpoint);

  handle("dialog:pick-directory", "main", async (window, request) => {
    const result = await dialog.showOpenDialog(window, {
      title: text(request.title),
      ...(request.defaultPath ? { defaultPath: text(request.defaultPath) } : {}),
      properties: ["openDirectory", "createDirectory"],
    });
    return result.canceled ? null : (result.filePaths[0] ?? null);
  });

  handle("dialog:pick-file", "main", async (window, request) => {
    const result = await dialog.showOpenDialog(window, {
      title: text(request.title),
      filters: filters(request.filters),
      properties: ["openFile"],
    });
    return result.canceled ? null : (result.filePaths[0] ?? null);
  });

  handle("dialog:choose-save-path", "main", async (window, request) => {
    const id = window.webContents.id;
    chosen.delete(id);
    const result = await dialog.showSaveDialog(window, {
      defaultPath: text(request.defaultPath),
      filters: filters(request.filters),
    });
    if (result.canceled || !result.filePath) return null;
    chosen.set(id, result.filePath);
    return result.filePath;
  });

  handle("dialog:write-chosen", "main", async (window, contents) => {
    const id = window.webContents.id;
    const path = chosen.get(id);
    chosen.delete(id);
    if (!path) throw new Error("no file was chosen to write");
    if (typeof contents !== "string" && !(contents instanceof Uint8Array)) {
      throw new Error("a file's contents must be text or bytes");
    }
    await writeFile(path, contents);
  });

  // Folders only. Electron's `openPath` would also launch a file with its
  // default handler, which no caller needs and an executable makes dangerous.
  handle("shell:open-path", "main", async (_window, path) => {
    if (!(await stat(text(path))).isDirectory()) throw new Error(`not a folder: ${path}`);
    const failure = await shell.openPath(path);
    if (failure) throw new Error(failure);
  });

  handle("app:version", "main", () => app.getVersion());

  handle("settings:load", "main", () => settings.load());
  handle("settings:save", "main", (_window, value) => settings.save(value));

  handle("frame:minimize", "any", (window) => window.minimize());
  handle("frame:toggle-maximize", "any", (window) => {
    if (window.isMaximized()) window.unmaximize();
    else window.maximize();
  });
  handle("frame:is-maximized", "any", (window) => window.isMaximized());
  handle("frame:close", "any", (window) => window.close());

  handle("window:open", "any", (_window, spec) => windows.openScope(spec));

  handle("updates:check", "main", () => updater.check());
  handle("updates:install", "main", (window) => {
    const send = <C extends "updates:progress" | "updates:installing">(channel: C, payload: EventChannels[C]) => {
      if (!window.isDestroyed()) window.webContents.send(channel, payload);
    };
    return updater.install({
      progress: (downloaded, total) => send("updates:progress", { downloaded, total }),
      installing: () => send("updates:installing", null),
    });
  });
}

function senderWindow(event: IpcMainInvokeEvent, audience: Audience, windows: Windows): BrowserWindow | null {
  const frame = event.senderFrame;
  if (!frame || frame.parent !== null || !isAppUrl(frame.url, windows.base)) return null;
  if (!windows.owns(event.sender)) return null;
  if (audience === "main" && !windows.isMain(event.sender)) return null;
  return BrowserWindow.fromWebContents(event.sender);
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("expected a string");
  return value;
}

function filters(value: unknown): FileFilter[] {
  if (!Array.isArray(value)) throw new Error("expected a list of file filters");
  return value.map((filter: FileFilter) => ({
    name: text(filter.name),
    extensions: filter.extensions.map(text),
  }));
}

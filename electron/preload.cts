/**
 * Exposes `window.ephymeris` (`bridge.ts`) to the app's pages and nothing else.
 *
 * Sandboxed: this file may load only `electron` itself, so the channel names
 * are written out here and kept honest by the types in `bridge.ts`. Every
 * check on who may use what is in the main process (`ipc.ts`), never here.
 */

import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";

import type { EphymerisBridge, EventChannels, InvokeChannels, UpdatesFlag } from "./bridge.js";

const UPDATES_FLAG: UpdatesFlag = "--ephymeris-updates";

function invoke<C extends keyof InvokeChannels>(
  channel: C,
  ...args: InvokeChannels[C]["args"]
): Promise<InvokeChannels[C]["result"]> {
  return ipcRenderer.invoke(channel, ...args) as Promise<InvokeChannels[C]["result"]>;
}

function subscribe<C extends keyof EventChannels>(
  channel: C,
  handler: (payload: EventChannels[C]) => void,
): () => void {
  const listener = (_event: IpcRendererEvent, payload: EventChannels[C]) => handler(payload);
  ipcRenderer.on(channel, listener);
  return () => {
    ipcRenderer.removeListener(channel, listener);
  };
}

const bridge: EphymerisBridge = {
  sidecar: {
    endpoint: () => invoke("sidecar:endpoint"),
    onReady: (handler) => subscribe("sidecar:ready", handler),
    onDown: (handler) => subscribe("sidecar:down", () => handler()),
  },
  dialog: {
    pickDirectory: (request) => invoke("dialog:pick-directory", request),
    pickFile: (request) => invoke("dialog:pick-file", request),
    chooseSavePath: (request) => invoke("dialog:choose-save-path", request),
    writeChosen: (contents) => invoke("dialog:write-chosen", contents),
  },
  openPath: (path) => invoke("shell:open-path", path),
  appVersion: () => invoke("app:version"),
  settings: {
    load: () => invoke("settings:load"),
    save: (settings) => invoke("settings:save", settings),
  },
  frame: {
    minimize: () => invoke("frame:minimize"),
    toggleMaximize: () => invoke("frame:toggle-maximize"),
    isMaximized: () => invoke("frame:is-maximized"),
    onResized: (handler) => subscribe("frame:resized", () => handler()),
    close: () => invoke("frame:close"),
  },
  openWindow: (spec) => invoke("window:open", spec),
  updates: {
    supported: process.argv.includes(UPDATES_FLAG),
    check: () => invoke("updates:check"),
    async install({ onProgress, onInstalling }) {
      const unsubscribe = [
        subscribe("updates:progress", ({ downloaded, total }) => onProgress(downloaded, total)),
        subscribe("updates:installing", () => onInstalling()),
      ];
      try {
        await invoke("updates:install");
      } finally {
        for (const off of unsubscribe) off();
      }
    },
  },
};

contextBridge.exposeInMainWorld("ephymeris", bridge);

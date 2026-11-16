/**
 * The contract between the Electron main process and the webview: what the
 * preload exposes as `window.ephymeris`, and every IPC channel behind it with
 * what crosses it (`ARCHITECTURE.md#the-electron-shell`).
 *
 * Types only, on purpose. The preload is sandboxed and cannot load a local
 * module, and the webview must not load main-process code, so this file is
 * shared at type level alone: a channel misspelt on either side fails the
 * typecheck rather than hanging at runtime.
 *
 * The webview never sees this object directly; `src/lib/shell/electron.ts`
 * adapts it to `Shell`.
 */

export interface SidecarEndpoint {
  port: number;
  token: string;
}

export interface FileFilter {
  name: string;
  extensions: string[];
}

export interface UpdateInfo {
  version: string;
  currentVersion: string;
  /** RFC 3339, when the release was published. */
  date: string | null;
}

export interface DirectoryRequest {
  title: string;
  defaultPath?: string;
}

export interface FileRequest {
  title: string;
  filters: FileFilter[];
}

export interface SaveRequest {
  defaultPath: string;
  filters: FileFilter[];
}

/** Request/response channels (`ipcRenderer.invoke` → `ipcMain.handle`). */
export interface InvokeChannels {
  "sidecar:endpoint": { args: []; result: SidecarEndpoint | null };
  "dialog:pick-directory": { args: [DirectoryRequest]; result: string | null };
  "dialog:pick-file": { args: [FileRequest]; result: string | null };
  /** The save dialog. The main process remembers the answer as this window's one writable path. */
  "dialog:choose-save-path": { args: [SaveRequest]; result: string | null };
  /** Writes the path the last save dialog returned, once. There is no channel that names a path to write. */
  "dialog:write-chosen": { args: [string | Uint8Array]; result: void };
  "shell:open-path": { args: [string]; result: void };
  "app:version": { args: []; result: string };
  "settings:load": { args: []; result: unknown };
  "settings:save": { args: [unknown]; result: void };
  "frame:minimize": { args: []; result: void };
  "frame:toggle-maximize": { args: []; result: void };
  "frame:is-maximized": { args: []; result: boolean };
  "frame:close": { args: []; result: void };
  "updates:check": { args: []; result: UpdateInfo | null };
  /** Download, verify, stop the sidecar, hand over. Progress arrives as events to the asking window. */
  "updates:install": { args: []; result: void };
}

/** Pushed from the main process (`webContents.send` → `ipcRenderer.on`). */
export interface EventChannels {
  "sidecar:ready": SidecarEndpoint;
  "sidecar:down": null;
  /** Sent to the one window that resized, maximized or restored. */
  "frame:resized": null;
  "updates:progress": { downloaded: number; total: number | null };
  "updates:installing": null;
}

/**
 * The flag the main process adds to a page's `process.argv` when this copy can
 * update itself (an installed Windows build), so `updates.supported` is known
 * synchronously, at load. A type, so both sides spell it out and the
 * typecheck holds them equal.
 */
export type UpdatesFlag = "--ephymeris-updates";

export interface EphymerisBridge {
  sidecar: {
    endpoint(): Promise<SidecarEndpoint | null>;
    onReady(handler: (endpoint: SidecarEndpoint) => void): () => void;
    onDown(handler: () => void): () => void;
  };
  dialog: {
    pickDirectory(request: DirectoryRequest): Promise<string | null>;
    pickFile(request: FileRequest): Promise<string | null>;
    chooseSavePath(request: SaveRequest): Promise<string | null>;
    writeChosen(contents: string | Uint8Array): Promise<void>;
  };
  openPath(path: string): Promise<void>;
  appVersion(): Promise<string>;
  settings: {
    load(): Promise<unknown>;
    save(settings: unknown): Promise<void>;
  };
  frame: {
    minimize(): Promise<void>;
    toggleMaximize(): Promise<void>;
    isMaximized(): Promise<boolean>;
    onResized(handler: () => void): () => void;
    close(): Promise<void>;
  };
  updates: {
    supported: boolean;
    check(): Promise<UpdateInfo | null>;
    install(events: {
      onProgress: (downloaded: number, total: number | null) => void;
      onInstalling: () => void;
    }): Promise<void>;
  };
}

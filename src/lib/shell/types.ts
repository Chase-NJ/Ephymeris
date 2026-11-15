/**
 * Everything the webview asks of the desktop shell, as one interface
 * (`ARCHITECTURE.md#the-shell-module`).
 *
 * The shell owns little: it starts the sidecar and says where it listens, draws
 * windows, shows the OS's dialogs, writes the one file the operator just
 * picked, keeps `settings.json`, and installs updates. Anything stateful
 * belongs to the sidecar, over the wire, never here.
 *
 * Kept as narrow as the shell's own permissions: no general file access, no URL
 * opening, no arbitrary windows. A wider method here would be a wider hole in
 * every implementation behind it.
 */

/** Where the sidecar listens, from its handshake line (`ARCHITECTURE.md#startup-handshake`). */
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

/** What an app-opened window needs; frameless like the main one, always. */
export interface WindowSpec {
  /** Unique among live windows. Recording pop-ups use `scope-*`, which the shell's permissions key on. */
  label: string;
  /** This same bundle at a hash route, e.g. `index.html#/scope/psth?box=1`. */
  url: string;
  title: string;
  width: number;
  height: number;
  minWidth: number;
  minHeight: number;
  x: number;
  y: number;
  /** Painted before the bundle is, so the frame does not flash white. */
  backgroundColor: string;
}

/**
 * Spread onto an element to make it drag its window: `<header {...frame.dragRegion}>`.
 * A data attribute only, so it never fights the element's own `className`.
 */
export type DragRegionProps = { readonly [attribute: `data-${string}`]: boolean };

export interface Shell {
  sidecar: {
    /** The endpoint if the sidecar is already up (it may beat the webview), else null. */
    endpoint(): Promise<SidecarEndpoint | null>;
    /** The sidecar printed its handshake. Resolves to an unsubscribe. */
    onReady(handler: (endpoint: SidecarEndpoint) => void): Promise<() => void>;
    /** The sidecar's stdout closed: it has exited and will not come back. */
    onDown(handler: () => void): Promise<() => void>;
  };

  dialog: {
    /** A native folder picker. Null when cancelled. */
    pickDirectory(options: { title: string; defaultPath?: string }): Promise<string | null>;
    /** A native single-file picker. Null when cancelled. */
    pickFile(options: { title: string; filters: FileFilter[] }): Promise<string | null>;
    /**
     * A save dialog, then `contents` written to the chosen path. The webview
     * never names a path to write: only the one the operator just picked.
     * `onChosen` runs between the two, for an export's progress steps.
     * Resolves to the path, or null when cancelled.
     */
    saveFile(
      options: { defaultPath: string; filters: FileFilter[]; onChosen?: () => void },
      contents: string | Uint8Array,
    ): Promise<string | null>;
  };

  /** Show a folder the app already knows in the OS file manager. Never a URL. */
  openPath(path: string): Promise<void>;

  /** The installed app's version. */
  appVersion(): Promise<string>;

  /** `settings.json` in the app data directory (`ARCHITECTURE.md#persistence-and-push`). */
  settings: {
    /** The stored settings, unvalidated; undefined when nothing is stored yet. */
    load(): Promise<unknown>;
    save(settings: unknown): Promise<void>;
  };

  /** The current window's frame. The app draws its own title bars. */
  frame: {
    dragRegion: DragRegionProps;
    minimize(): Promise<void>;
    toggleMaximize(): Promise<void>;
    isMaximized(): Promise<boolean>;
    onResized(handler: () => void): Promise<() => void>;
    close(): Promise<void>;
  };

  /** Open another window of this app (`RECORDING.md#live-windows`). */
  openWindow(spec: WindowSpec): void;

  /** App updates (`ARCHITECTURE.md#updates`). */
  updates: {
    /** False in a dev build or with no shell: there is no installed app to update. */
    supported: boolean;
    /** Ask the feed. Null when this is the newest. */
    check(): Promise<UpdateInfo | null>;
    /**
     * Download, verify, stop the sidecar and hand over to the installer. On
     * Windows the app exits partway, so resolving means it did not.
     */
    install(events: {
      onProgress: (downloaded: number, total: number | null) => void;
      /** The download is verified and the sidecar is about to stop. */
      onInstalling: () => void;
    }): Promise<void>;
  };
}

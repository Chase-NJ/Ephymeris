/**
 * The app's windows: the main one and the recording pop-ups
 * (`RECORDING.md#live-windows`), plus the `app://` scheme an installed build
 * loads them from. The window half of `src-tauri/src/lib.rs`.
 *
 * Every window is frameless (the webview draws its own title bars), sandboxed,
 * and reaches the main process only through the preload's bridge.
 */

import { stat } from "node:fs/promises";
import { resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";

import { BrowserWindow, net, protocol, screen, type WebContents } from "electron";

import type { EventChannels, WindowSpec } from "./bridge.js";
import { openingSize, MIN_HEIGHT, MIN_WIDTH } from "./geometry.js";
import { APP_HOST, APP_SCHEME, isAppUrl, scopeUrl } from "./origin.js";

/** The Void: painted before the bundle is, so no window flashes white. */
const BACKGROUND = "#0B0B10";

const SCOPE_LABEL = /^scope-[a-z0-9-]{1,80}$/;

/**
 * Must run before `app` is ready. `fetch` refuses `file://`, and
 * `analytics/report/fonts.ts` fetches the bundled fonts, so an installed build
 * serves its pages from a standard, secure scheme instead.
 */
export function registerAppScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: APP_SCHEME,
      privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true },
    },
  ]);
}

/** Serve `distDir` (the Vite build) at `app://ephymeris/`, and nothing outside it. */
export function serveApp(distDir: string): void {
  const root = resolve(distDir);
  protocol.handle(APP_SCHEME, async (request) => {
    const url = new URL(request.url);
    if (url.host !== APP_HOST) return new Response("not found", { status: 404 });
    const relative = decodeURIComponent(url.pathname).replace(/^\/+/, "") || "index.html";
    const file = resolve(root, relative);
    if (!file.startsWith(root + sep)) return new Response("forbidden", { status: 403 });
    try {
      if (!(await stat(file)).isFile()) return new Response("not found", { status: 404 });
    } catch {
      return new Response("not found", { status: 404 });
    }
    return net.fetch(pathToFileURL(file).href);
  });
}

export class Windows {
  private mainWindow: BrowserWindow | null = null;
  private readonly scopes = new Map<string, BrowserWindow>();

  constructor(
    readonly base: URL,
    private readonly preload: string,
    /** Extra `process.argv` for every page (`bridge.ts`'s `UpdatesFlag`). */
    private readonly pageArguments: string[] = [],
  ) {}

  get main(): BrowserWindow | null {
    return this.mainWindow;
  }

  createMain(): BrowserWindow {
    // Sized against whichever display the cursor is on, at creation, so the
    // window never visibly jumps from a default size.
    const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
    const { width, height } = openingSize(display.size.width, display.size.height);
    console.info(
      `display is ${display.size.width}x${display.size.height} DIP; opening the window at ${width}x${height}`,
    );

    const window = new BrowserWindow({
      title: "Ephymeris",
      width,
      height,
      minWidth: MIN_WIDTH,
      minHeight: MIN_HEIGHT,
      center: true,
      frame: false,
      show: false,
      backgroundColor: BACKGROUND,
      webPreferences: this.webPreferences(),
    });
    this.mainWindow = window;
    this.reportResizes(window);

    // Shown once painted, or once loading has failed: a window that stays
    // invisible is far worse than one that shows an error.
    const show = () => {
      if (!window.isDestroyed() && !window.isVisible()) window.show();
    };
    window.once("ready-to-show", show);
    window.webContents.once("did-fail-load", show);

    // The pop-ups are windows of the app, not of this window: closing main
    // closes them, or the app would not exit until each was closed by hand,
    // holding the sidecar and its serial ports with it.
    window.on("close", () => {
      for (const scope of this.scopes.values()) if (!scope.isDestroyed()) scope.close();
    });
    window.on("closed", () => {
      this.mainWindow = null;
    });

    const page = this.base.protocol === `${APP_SCHEME}:` ? new URL("index.html", this.base) : this.base;
    void window.loadURL(page.href);
    return window;
  }

  /** A recording pop-up, frameless like main. Refuses any spec that is not a scope of this app. */
  openScope(spec: WindowSpec): void {
    if (!SCOPE_LABEL.test(spec.label)) throw new Error(`not a scope window label: ${spec.label}`);
    if (this.scopes.has(spec.label)) throw new Error(`a window labelled ${spec.label} is already open`);
    const url = scopeUrl(spec.url, this.base);
    if (!url) throw new Error(`not a scope page of this app: ${spec.url}`);

    const window = new BrowserWindow({
      title: spec.title,
      width: whole(spec.width),
      height: whole(spec.height),
      minWidth: whole(spec.minWidth),
      minHeight: whole(spec.minHeight),
      x: whole(spec.x),
      y: whole(spec.y),
      frame: false,
      backgroundColor: /^#[0-9a-fA-F]{6}$/.test(spec.backgroundColor) ? spec.backgroundColor : BACKGROUND,
      webPreferences: this.webPreferences(),
    });
    this.scopes.set(spec.label, window);
    this.reportResizes(window);
    // The page's own <title> is "Ephymeris" in every window; the taskbar should
    // say which pop-up this is, as it does under Tauri.
    window.on("page-title-updated", (event) => event.preventDefault());
    window.on("closed", () => this.scopes.delete(spec.label));
    void window.loadURL(url.href);
  }

  /** Whether `contents` belongs to one of this app's windows. */
  owns(contents: WebContents): boolean {
    const window = BrowserWindow.fromWebContents(contents);
    return window !== null && (window === this.mainWindow || [...this.scopes.values()].includes(window));
  }

  isMain(contents: WebContents): boolean {
    return this.mainWindow !== null && contents === this.mainWindow.webContents;
  }

  /** Send an event to every open window. */
  broadcast<C extends keyof EventChannels>(channel: C, payload: EventChannels[C]): void {
    for (const window of BrowserWindow.getAllWindows()) {
      if (!window.isDestroyed() && this.owns(window.webContents)) window.webContents.send(channel, payload);
    }
  }

  /** Keep every web page in this app on the app's own pages. */
  lockDown(contents: WebContents): void {
    contents.setWindowOpenHandler(() => ({ action: "deny" }));
    contents.on("will-navigate", (event, url) => {
      if (!isAppUrl(url, this.base)) {
        event.preventDefault();
        console.warn(`refused to navigate to ${url}`);
      }
    });
    contents.on("will-attach-webview", (event) => event.preventDefault());
  }

  private webPreferences(): Electron.WebPreferences {
    return {
      preload: this.preload,
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      additionalArguments: this.pageArguments,
    };
  }

  private reportResizes(window: BrowserWindow): void {
    const send = () => {
      if (!window.isDestroyed()) window.webContents.send("frame:resized", null);
    };
    window.on("resize", send);
    window.on("maximize", send);
    window.on("unmaximize", send);
  }
}

function whole(value: number): number {
  if (!Number.isFinite(value)) throw new Error("window geometry must be finite numbers");
  return Math.round(value);
}

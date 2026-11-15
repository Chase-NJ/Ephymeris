/**
 * The Electron shell (`electron/`) behind `Shell`. The only file in `src/` that
 * reads `window.ephymeris`, the bridge its preload exposes (`boundary.test.ts`).
 *
 * Each method is one IPC channel (`electron/bridge.ts`), and the main process
 * decides who may use it (`electron/ipc.ts`): the main window gets all of
 * this, a `scope-*` pop-up only its frame, the sidecar's endpoint and
 * `openWindow`.
 */

import type { EphymerisBridge } from "../../../electron/bridge";
import type { Shell } from "./types";

declare global {
  interface Window {
    ephymeris?: EphymerisBridge;
  }
}

/** The preload's bridge, when this page runs inside the Electron shell. */
export function electronBridge(): EphymerisBridge | null {
  return typeof window === "undefined" ? null : (window.ephymeris ?? null);
}

export function electronShell(bridge: EphymerisBridge): Shell {
  return {
    sidecar: {
      endpoint: () => bridge.sidecar.endpoint(),
      onReady: async (handler) => bridge.sidecar.onReady(handler),
      onDown: async (handler) => bridge.sidecar.onDown(handler),
    },

    dialog: {
      pickDirectory: ({ title, defaultPath }) =>
        bridge.dialog.pickDirectory({ title, ...(defaultPath ? { defaultPath } : {}) }),
      pickFile: ({ title, filters }) => bridge.dialog.pickFile({ title, filters }),

      // Two calls, because `onChosen` runs between them. The main process
      // writes only the path its own save dialog just returned to this window.
      async saveFile({ defaultPath, filters, onChosen }, contents) {
        const path = await bridge.dialog.chooseSavePath({ defaultPath, filters });
        if (!path) return null;
        onChosen?.();
        await bridge.dialog.writeChosen(contents);
        return path;
      },
    },

    openPath: (path) => bridge.openPath(path),

    appVersion: () => bridge.appVersion(),

    settings: {
      load: () => bridge.settings.load(),
      save: (settings) => bridge.settings.save(settings),
    },

    // `index.css` turns the attribute into `-webkit-app-region: drag`, with
    // every control inside opting out (a drag region swallows clicks).
    frame: {
      dragRegion: { "data-app-drag": true },
      minimize: () => bridge.frame.minimize(),
      toggleMaximize: () => bridge.frame.toggleMaximize(),
      isMaximized: () => bridge.frame.isMaximized(),
      onResized: async (handler) => bridge.frame.onResized(handler),
      close: () => bridge.frame.close(),
    },

    openWindow(spec) {
      bridge.openWindow(spec).catch((err: unknown) => {
        console.error(`could not open the window ${spec.label}`, err);
      });
    },

    // `supported` only in an installed Windows copy (`electron/updater.ts`).
    updates: {
      supported: bridge.updates.supported,
      check: () => bridge.updates.check(),
      install: (events) => bridge.updates.install(events),
    },
  };
}

/**
 * The webview's one way to the desktop shell (`ARCHITECTURE.md#the-shell-module`).
 *
 * Chosen once, at load: Tauri while `src-tauri/` ships, Electron when its
 * preload exposed a bridge (ADR 0006), and no shell in a plain browser or a
 * unit test.
 */

import { electronBridge, electronShell } from "./electron";
import { noShell } from "./none";
import { inTauri, tauriShell } from "./tauri";
import type { Shell } from "./types";

function pick(): Shell {
  if (inTauri()) return tauriShell;
  const bridge = electronBridge();
  return bridge ? electronShell(bridge) : noShell;
}

export const shell: Shell = pick();

export type { DragRegionProps, FileFilter, Shell, SidecarEndpoint, UpdateInfo } from "./types";

/**
 * Settings schema (ephymeris_v1.0.md §4.5).
 *
 * The shell owns settings and is the source of truth; the sidecar receives a
 * push and reads only the keys it needs. The full schema is still an open item
 * in §6 — these are the starting fields, so `normalizeSettings` is written to
 * tolerate both older stored shapes and unknown extra keys rather than assuming
 * whatever is on disk matches this file exactly.
 */

/** Hardware ceiling: six Mega2560s (`hardware-interaction.md` §1). */
export const BOX_COUNT = 6;
export const DEFAULT_BAUD = 115200;

/** Offered in the picker; Debug Mode also allows a per-box override (§6.4). */
export const BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 250000] as const;

export interface BoxBinding {
  box: number;
  /** The board's USB serial number — stable across COM renumbering (§5). */
  hardwareId: string | null;
  label: string;
}

export interface EphymerisSettings {
  dataDirectory: string | null;
  backupDirectory: string | null;
  arduinoDirectory: string | null;
  arduinoCliPath: string | null;
  defaultBaud: number;
  boxes: BoxBinding[];
  reducedMotion: boolean;
}

/**
 * Boxes are user-managed: the rig might run two boxes or six, so Settings
 * starts empty and the user adds rows. Box *numbers* remain 1–6 and stay the
 * stable key everywhere else (protocol §5.1) — only which of them exist is
 * configurable.
 */
export function newBinding(box: number): BoxBinding {
  return { box, hardwareId: null, label: `Box ${box}` };
}

/** Lowest unused box number, or null when all six are taken. */
export function nextAvailableBox(boxes: BoxBinding[]): number | null {
  const used = new Set(boxes.map((b) => b.box));
  for (let n = 1; n <= BOX_COUNT; n += 1) {
    if (!used.has(n)) return n;
  }
  return null;
}

export const DEFAULT_SETTINGS: EphymerisSettings = {
  dataDirectory: null,
  backupDirectory: null,
  // No default is shipped or assumed — the user sets it explicitly
  // (arduino-directory.md §2).
  arduinoDirectory: null,
  arduinoCliPath: null,
  defaultBaud: DEFAULT_BAUD,
  // No boxes until the user adds them.
  boxes: [],
  reducedMotion: false,
};

function optString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function normalizeBoxes(value: unknown): BoxBinding[] {
  if (!Array.isArray(value)) return [];

  // Keyed by number so a stored file with duplicates collapses cleanly; the
  // list is *not* padded to six — an absent box number means "not configured".
  const byNumber = new Map<number, BoxBinding>();
  for (const raw of value) {
    if (typeof raw !== "object" || raw === null) continue;
    const entry = raw as Record<string, unknown>;
    const box = entry["box"];
    if (typeof box !== "number" || !Number.isInteger(box)) continue;
    if (box < 1 || box > BOX_COUNT) continue;
    byNumber.set(box, {
      box,
      hardwareId: optString(entry["hardwareId"]),
      label: optString(entry["label"]) ?? `Box ${box}`,
    });
  }
  return [...byNumber.values()].sort((a, b) => a.box - b.box);
}

export function normalizeSettings(raw: unknown): EphymerisSettings {
  if (typeof raw !== "object" || raw === null) return { ...DEFAULT_SETTINGS };
  const value = raw as Record<string, unknown>;

  const baud = value["defaultBaud"];
  return {
    dataDirectory: optString(value["dataDirectory"]),
    backupDirectory: optString(value["backupDirectory"]),
    arduinoDirectory: optString(value["arduinoDirectory"]),
    arduinoCliPath: optString(value["arduinoCliPath"]),
    defaultBaud: typeof baud === "number" && baud > 0 ? baud : DEFAULT_BAUD,
    boxes: normalizeBoxes(value["boxes"]),
    reducedMotion: value["reducedMotion"] === true,
  };
}

/** The four Arduino Directory states from `arduino-directory.md` §6. */
export type DirectoryState = "not_configured" | "invalid" | "empty" | "ok";

export interface DirectoryStatus {
  state: DirectoryState;
  path: string | null;
  message: string | null;
}

export interface SketchEntry {
  category: string;
  name: string;
  path: string;
}

export interface SkippedEntry {
  path: string;
  reason: string;
}

export interface SketchDiscovery {
  directory: DirectoryStatus;
  sketches: SketchEntry[];
  skipped: SkippedEntry[];
  skippedCount: number;
  libraries: string[];
  librariesPath: string | null;
}

export const EMPTY_DISCOVERY: SketchDiscovery = {
  directory: { state: "not_configured", path: null, message: null },
  sketches: [],
  skipped: [],
  skippedCount: 0,
  libraries: [],
  librariesPath: null,
};

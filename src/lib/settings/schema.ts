/**
 * Settings schema (settings.md §2).
 *
 * The shell owns settings and is the source of truth; the sidecar receives a
 * push and reads only the keys it needs. The wire shapes themselves live in
 * the generated protocol module (`protocol/schema.py` is their authority) and
 * are re-exported here so callers keep one import site. The full schema is
 * still an open item in §6, so `normalizeSettings` is written to tolerate both
 * older stored shapes and unknown extra keys rather than assuming whatever is
 * on disk matches the schema exactly.
 */

import { zodiacById } from "@/lib/constellations/zodiac";
import type { BoxBinding, EphymerisSettings, SketchDiscovery } from "@/lib/ws/protocol";

export type {
  BoxBinding,
  EphymerisSettings,
  DirectoryState,
  DirectoryStatus,
  SketchEntry,
  SkippedEntry,
  SketchDiscovery,
} from "@/lib/ws/protocol";

/** Hardware ceiling: six Mega2560s (`dashboard.md` §5). */
export const BOX_COUNT = 6;
/**
 * Every sketch in the lab's Arduino Directory opens at 9600 (each declares its
 * own `baudRate`, and they all agree), so 115200 was a default that was wrong
 * for every box on both machines — silently, since a mismatched console just
 * prints nothing readable.
 */
export const DEFAULT_BAUD = 9600;

/** Offered in the picker; Debug Mode also allows a per-box override (§6.4). */
export const BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 250000] as const;

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
  // (tasks.md §2.1).
  arduinoDirectory: null,
  arduinoCliPath: null,
  // No baseline until the user names a utility sketch (`dashboard.md`
  // §8) — there is no safe sketch to guess, and guessing would flash the rig.
  utilitySketchPath: null,
  defaultBaud: DEFAULT_BAUD,
  // No boxes until the user adds them.
  boxes: [],
  reducedMotion: false,
  // Null = the legacy fixed layout, until the user picks a zodiac (§4.6).
  constellation: null,
  constellationSlots: {},
  boxSetupComplete: false,
  // No rig defaults until someone sets one on Config; every sketch starts on
  // the values its own task.json declares (`tasks.md` §6.1).
  taskDefaults: {},
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

function normalizeSlots(value: unknown): Record<string, number> {
  if (typeof value !== "object" || value === null) return {};
  const slots: Record<string, number> = {};
  const taken = new Set<number>();
  // Box-number order, so duplicate star claims dedupe deterministically
  // (first-wins) — the same rule `reconcileSlots` applies.
  for (let box = 1; box <= BOX_COUNT; box += 1) {
    const star = (value as Record<string, unknown>)[String(box)];
    if (typeof star !== "number" || !Number.isInteger(star) || star < 0) continue;
    if (taken.has(star)) continue;
    slots[String(box)] = star;
    taken.add(star);
  }
  // Star-index range depends on the chosen constellation, which this function
  // deliberately doesn't know — `reconcileSlots` owns that half.
  return slots;
}

/**
 * `{sketchName: {metadataKey: value}}` — this rig's saved task parameters
 * (`tasks.md` §6.1).
 *
 * Values are carried through unexamined on purpose: what a key means is the
 * sketch's `task.json` to say, and this file has never seen one. A stored key
 * the profile no longer declares is dropped later, at the merge, where the
 * profile is actually in hand.
 */
function normalizeTaskDefaults(value: unknown): Record<string, Record<string, unknown>> {
  if (typeof value !== "object" || value === null) return {};
  const out: Record<string, Record<string, unknown>> = {};
  for (const [sketch, config] of Object.entries(value as Record<string, unknown>)) {
    if (!sketch || typeof config !== "object" || config === null || Array.isArray(config)) {
      continue;
    }
    out[sketch] = { ...(config as Record<string, unknown>) };
  }
  return out;
}

export function normalizeSettings(raw: unknown): EphymerisSettings {
  if (typeof raw !== "object" || raw === null) return { ...DEFAULT_SETTINGS };
  const value = raw as Record<string, unknown>;

  const baud = value["defaultBaud"];
  const constellation = value["constellation"];
  return {
    dataDirectory: optString(value["dataDirectory"]),
    backupDirectory: optString(value["backupDirectory"]),
    arduinoDirectory: optString(value["arduinoDirectory"]),
    arduinoCliPath: optString(value["arduinoCliPath"]),
    utilitySketchPath: optString(value["utilitySketchPath"]),
    defaultBaud: typeof baud === "number" && baud > 0 ? baud : DEFAULT_BAUD,
    boxes: normalizeBoxes(value["boxes"]),
    reducedMotion: value["reducedMotion"] === true,
    // Validated against the catalogue so a corrupt store can never select a
    // nonexistent map — it degrades to the legacy layout instead.
    constellation:
      typeof constellation === "string" && zodiacById(constellation)
        ? constellation
        : null,
    constellationSlots: normalizeSlots(value["constellationSlots"]),
    boxSetupComplete: value["boxSetupComplete"] === true,
    taskDefaults: normalizeTaskDefaults(value["taskDefaults"]),
  };
}

export const EMPTY_DISCOVERY: SketchDiscovery = {
  directory: { state: "not_configured", path: null, message: null },
  sketches: [],
  skipped: [],
  skippedCount: 0,
  libraries: [],
  librariesPath: null,
};

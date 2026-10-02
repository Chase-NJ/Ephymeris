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
import {
  DEFAULT_RECORDING_DEFAULTS,
  normalizeRecordingDefaults,
} from "@/lib/intan/defaults";
import type {
  BoxBinding,
  EphymerisSettings,
  IntanSettings,
  SketchDiscovery,
} from "@/lib/ws/protocol";

export type {
  BoxBinding,
  EphymerisSettings,
  IntanSettings,
  LibraryState,
  SketchLibraryStatus,
  SketchEntry,
  SkippedEntry,
  SketchDiscovery,
} from "@/lib/ws/protocol";
export type { RecordingDefaults } from "@/lib/intan/defaults";

/** Hardware ceiling: six Mega2560s (`dashboard.md` §5). */
export const BOX_COUNT = 6;
/**
 * Every bundled sketch opens at 115200 — each declares its own `baudRate` and
 * they all agree. The sidecar declares the same number in Python (`settings.py`); nothing keeps the
 * two in step, so they must be changed together.
 *
 * **This is only the default for a fresh install.** `defaultBaud` is persisted,
 * so a machine that already has a settings file keeps whatever is in it —
 * changing this constant does not migrate it. A box flashed at 115200 whose
 * host is still on 9600 is *mute*, and mute reads as dead hardware rather than
 * as a mismatch. Set it in Config → Hardware, per machine.
 */
export const DEFAULT_BAUD = 115200;

/** Offered in the picker; Debug Mode also allows a per-box override (§6.4). */
export const BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 250000] as const;

/**
 * Boxes are user-managed: the rig might run two boxes or six, so Settings
 * starts empty and the user adds rows. Box *numbers* remain 1–6 and stay the
 * stable key everywhere else (protocol §5.1) — only which of them exist is
 * configurable.
 */
export function newBinding(box: number): BoxBinding {
  return { box, hardwareId: null, label: `Box ${box}`, intanDigitalIn: null };
}

/** The recording controller has sixteen digital inputs (`recording.md` §3). */
export const INTAN_DIGITAL_INPUTS = 16;

/** Intan RHX's own defaults (Network → Remote TCP Control). */
export const DEFAULT_INTAN: IntanSettings = {
  commandPort: 5000,
  waveformPort: 5001,
  spikePort: 5002,
};

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
  arduinoCliPath: null,
  // No baseline until the user names a utility sketch (`dashboard.md`
  // §8) — there is no safe sketch to guess, and guessing would flash the rig.
  utilitySketchName: null,
  defaultBaud: DEFAULT_BAUD,
  // No boxes until the user adds them.
  boxes: [],
  intan: { ...DEFAULT_INTAN },
  // Shell-only and fully shaped client-side (`lib/intan/defaults.ts`): the
  // sidecar never reads it, so the wire carries it as a loose record.
  recordingDefaults: { ...DEFAULT_RECORDING_DEFAULTS },
  reducedMotion: false,
  // Null = the legacy fixed layout, until the user picks a zodiac (§4.6).
  constellation: null,
  constellationSlots: {},
  // No rig defaults until someone sets one on Config; every sketch starts on
  // the values its own task.json declares (`tasks.md` §6.1).
  taskDefaults: {},
};

function optString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

/**
 * The baseline sketch, healing the retired path-valued key.
 *
 * `utilitySketchPath` stored an absolute path into the old user-configured
 * Arduino Directory; the setting is now a sketch folder NAME resolved against
 * the bundled library, matching `taskDefaults`' key. The basename of the old
 * path IS that name — arduino-cli requires `<folder>/<folder>.ino` — so a lab
 * machine's stored `BOX_Utility` path heals on first load and the migrated
 * value is written back on the next save.
 */
function normalizeUtilitySketch(value: Record<string, unknown>): string | null {
  const name = optString(value["utilitySketchName"]);
  if (name !== null) return name;
  const legacy = optString(value["utilitySketchPath"]);
  if (legacy === null) return null;
  const base = legacy.split(/[\\/]/).filter(Boolean).pop() ?? "";
  return base || null;
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
      intanDigitalIn: normalizeDigitalIn(entry["intanDigitalIn"]),
    });
  }
  // Two boxes on one digital input are indistinguishable in the recording. The
  // lower box number keeps the claim — the same rule the sidecar applies, so
  // the two ends never disagree about which box is wired.
  const claimed = new Set<number>();
  return [...byNumber.values()]
    .sort((a, b) => a.box - b.box)
    .map((binding) => {
      const din = binding.intanDigitalIn ?? null;
      if (din === null) return binding;
      if (claimed.has(din)) return { ...binding, intanDigitalIn: null };
      claimed.add(din);
      return binding;
    });
}

function normalizeDigitalIn(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isInteger(value)) return null;
  return value >= 1 && value <= INTAN_DIGITAL_INPUTS ? value : null;
}

function normalizePort(value: unknown, fallback: number): number {
  if (typeof value !== "number" || !Number.isInteger(value)) return fallback;
  return value >= 1 && value <= 65535 ? value : fallback;
}

function normalizeIntan(value: unknown): IntanSettings {
  if (typeof value !== "object" || value === null) return { ...DEFAULT_INTAN };
  const entry = value as Record<string, unknown>;
  return {
    commandPort: normalizePort(entry["commandPort"], DEFAULT_INTAN.commandPort),
    waveformPort: normalizePort(entry["waveformPort"], DEFAULT_INTAN.waveformPort),
    spikePort: normalizePort(entry["spikePort"], DEFAULT_INTAN.spikePort),
  };
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
    // `arduinoDirectory` was retired when sketches began shipping with the app
    // (tasks.md §2). A stored value is dropped here — silently on purpose: the
    // key configured a directory that nothing reads any more, so there is
    // nothing to migrate it INTO. Don't reintroduce it.
    arduinoCliPath: optString(value["arduinoCliPath"]),
    utilitySketchName: normalizeUtilitySketch(value),
    defaultBaud: typeof baud === "number" && baud > 0 ? baud : DEFAULT_BAUD,
    boxes: normalizeBoxes(value["boxes"]),
    intan: normalizeIntan(value["intan"]),
    recordingDefaults: normalizeRecordingDefaults(value["recordingDefaults"]),
    reducedMotion: value["reducedMotion"] === true,
    // Validated against the catalogue so a corrupt store can never select a
    // nonexistent map — it degrades to the legacy layout instead.
    constellation:
      typeof constellation === "string" && zodiacById(constellation)
        ? constellation
        : null,
    constellationSlots: normalizeSlots(value["constellationSlots"]),
    taskDefaults: normalizeTaskDefaults(value["taskDefaults"]),
  };
}

// Pre-first-report placeholder. "ok with nothing in it" rather than a
// pessimistic guess: the real scan arrives with the first settings.push reply,
// and flashing an "install damaged" banner during the connection handshake
// would alarm every launch.
export const EMPTY_DISCOVERY: SketchDiscovery = {
  library: { state: "ok", path: null, message: null, source: "bundled" },
  sketches: [],
  skipped: [],
  skippedCount: 0,
  libraries: [],
  librariesPath: null,
};

/**
 * The recording defaults — `settings.recordingDefaults`, fully shaped.
 *
 * Everything the Record step collects that is NOT per session (the save
 * directory) or per group (the box list). The Recording tab edits them
 * outright; the Record step opens prefilled from them and writes back what
 * the operator confirmed. Shell-only on the wire (`Record<string, unknown>`;
 * the sidecar never reads the key), which is why the shape can live here in
 * full and why `RecordingDefaults` is a type ALIAS: an alias stays assignable
 * to the wire's record type, an interface would not.
 *
 * Normalization heals per key, never all-or-nothing — the tolerance
 * `normalizeBoxes` applies in `settings/schema.ts`. A stored file from an
 * older build, or one hand-edited into partial nonsense, keeps every value
 * that is still legal and falls back for the one that is not.
 */

import type { RecordingConfig } from "@/lib/ws/protocol";

import { FILE_FORMATS, defaultRecordingConfig } from "./types";

export type RecordingConfigDefaults = Omit<RecordingConfig, "saveDirectory" | "boxes">;

/**
 * One box's memory from the last Record step: whether it recorded, and its
 * wiring (which port, which range). Never a probe map, which follows the
 * animal (`RecordingDefaults.probeMaps`).
 */
export type RecordingBoxMemory = {
  record: boolean;
  /** "" = unassigned; otherwise a single upper-case port letter. */
  port: string;
  firstChannel: number;
  /** -1 = the whole port, resolved once RHX reports the port's channel count. */
  lastChannel: number;
};

export type RecordingDefaults = {
  /** null = beside each session's behavior data, in `<session>/ephys`. */
  saveRoot: string | null;
  config: RecordingConfigDefaults;
  /** Keyed by box number, "1"…"6". */
  boxes: Record<string, RecordingBoxMemory>;
  /**
   * The probe map last used for each animal, keyed by animal id. A probe map
   * describes the animal's implant, so it follows the animal from box to box;
   * the box keeps only its wiring (port and range).
   */
  probeMaps: Record<string, string>;
};

const DOWNSAMPLE = [1, 2, 4, 8, 16, 32, 64, 128];
const THRESHOLD_MODES = ["keep", "absolute", "rms"] as const;
const BOX_KEYS = ["1", "2", "3", "4", "5", "6"];

function baseConfig(): RecordingConfigDefaults {
  const { saveDirectory: _dir, boxes: _boxes, ...rest } = defaultRecordingConfig("");
  return rest;
}

export const DEFAULT_RECORDING_DEFAULTS: RecordingDefaults = {
  saveRoot: null,
  config: baseConfig(),
  boxes: {},
  probeMaps: {},
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function int(value: unknown, lo: number, hi: number, fallback: number): number {
  if (typeof value !== "number" || !Number.isInteger(value)) return fallback;
  return value >= lo && value <= hi ? value : fallback;
}

function num(value: unknown, lo: number, hi: number, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return value >= lo && value <= hi ? value : fallback;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback;
}

function normalizeConfig(raw: unknown): RecordingConfigDefaults {
  const base = baseConfig();
  if (!isRecord(raw)) return base;
  const threshold = isRecord(raw["threshold"]) ? raw["threshold"] : {};
  const out: RecordingConfigDefaults = {
    fileFormat: oneOf(
      raw["fileFormat"],
      FILE_FORMATS.map((f) => f.value),
      base.fileFormat,
    ),
    saveWideband: bool(raw["saveWideband"], base.saveWideband),
    saveSpikes: bool(raw["saveSpikes"], base.saveSpikes),
    saveSpikeSnapshots: bool(raw["saveSpikeSnapshots"], base.saveSpikeSnapshots),
    snapshotPreMs: int(raw["snapshotPreMs"], 0, 3, base.snapshotPreMs),
    snapshotPostMs: int(raw["snapshotPostMs"], 1, 6, base.snapshotPostMs),
    saveLowpass: bool(raw["saveLowpass"], base.saveLowpass),
    lowpassDownsample:
      typeof raw["lowpassDownsample"] === "number" && DOWNSAMPLE.includes(raw["lowpassDownsample"])
        ? raw["lowpassDownsample"]
        : base.lowpassDownsample,
    saveHighpass: bool(raw["saveHighpass"], base.saveHighpass),
    threshold: {
      mode: oneOf(threshold["mode"], THRESHOLD_MODES, base.threshold.mode),
      microvolts: int(threshold["microvolts"], -5000, 5000, base.threshold.microvolts),
      rmsMultiple: num(threshold["rmsMultiple"], 3, 20, base.threshold.rmsMultiple),
      negative: bool(threshold["negative"], base.threshold.negative),
    },
  };
  const minutes = raw["newFileMinutes"];
  if (typeof minutes === "number" && Number.isInteger(minutes) && minutes >= 1 && minutes <= 999) {
    out.newFileMinutes = minutes;
  }
  // The invariant the Record step's Wideband toggle keeps: a recording that
  // saves nothing is not a default anyone meant, and wideband is the one
  // option that cannot lose data.
  if (!out.saveWideband && !out.saveSpikes && !out.saveHighpass && !out.saveLowpass) {
    out.saveWideband = true;
  }
  return out;
}

function normalizeBoxMemory(raw: unknown): RecordingBoxMemory | null {
  if (!isRecord(raw)) return null;
  const port = typeof raw["port"] === "string" ? raw["port"].trim().toUpperCase() : "";
  return {
    record: bool(raw["record"], true),
    port: /^[A-H]$/.test(port) ? port : "",
    firstChannel: int(raw["firstChannel"], 0, 127, 0),
    lastChannel: int(raw["lastChannel"], -1, 127, -1),
    // An older build's per-box `probeMapPath` is ignored, not migrated: it was
    // whichever animal last recorded on the box, and nothing says which.
  };
}

export function normalizeRecordingDefaults(raw: unknown): RecordingDefaults {
  if (!isRecord(raw)) return { ...DEFAULT_RECORDING_DEFAULTS, config: baseConfig() };
  const boxes: Record<string, RecordingBoxMemory> = {};
  if (isRecord(raw["boxes"])) {
    for (const key of BOX_KEYS) {
      const memory = normalizeBoxMemory(raw["boxes"][key]);
      if (memory) boxes[key] = memory;
    }
  }
  // Absent from a file written before probe maps followed the animal: none remembered.
  const probeMaps: Record<string, string> = {};
  if (isRecord(raw["probeMaps"])) {
    for (const [animalId, path] of Object.entries(raw["probeMaps"])) {
      const kept = optString(path);
      if (animalId !== "" && kept) probeMaps[animalId] = kept;
    }
  }
  return {
    saveRoot: optString(raw["saveRoot"]),
    config: normalizeConfig(raw["config"]),
    boxes,
    probeMaps,
  };
}

/**
 * One line saying what a recording setup saves — the Defaults tile's header
 * fact and the Record step's collapsed summary. Lower case, mono-friendly:
 * `per signal type · wideband + spikes · keep rhx's`.
 */
export function summarizeRecordingConfig(config: RecordingConfigDefaults): string {
  const format = FILE_FORMATS.find((f) => f.value === config.fileFormat)?.label ?? config.fileFormat;
  const saved: string[] = [];
  if (config.saveWideband) saved.push("wideband");
  if (config.saveSpikes) saved.push(config.saveSpikeSnapshots ? "spikes + snapshots" : "spikes");
  if (config.saveHighpass) saved.push("highpass");
  if (config.saveLowpass) {
    saved.push(config.lowpassDownsample > 1 ? `lowpass ÷${config.lowpassDownsample}` : "lowpass");
  }
  const threshold =
    config.threshold.mode === "keep"
      ? "keep rhx's thresholds"
      : config.threshold.mode === "absolute"
        ? `threshold ${config.threshold.microvolts} µv`
        : `threshold ${config.threshold.rmsMultiple}× rms`;
  return [format.toLowerCase(), saved.join(" + ") || "nothing", threshold].join(" · ");
}

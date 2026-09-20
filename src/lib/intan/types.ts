/**
 * The recording domain's shapes (`docs/recording.md`).
 *
 * Wire shapes are re-exported from the generated mirror, never re-declared. The
 * per-kind scope payloads are declared here because the wire carries them as
 * `any` on purpose — four views, four shapes, one event — and this is the one
 * place their fields are written down for the frontend.
 */

import type { RecordingConfig } from "@/lib/ws/protocol";

export type {
  IntanState,
  IntanStatus,
  IntanSyncStat,
  RecordingBox,
  RecordingBoxConfig,
  RecordingConfig,
  RecordingRun,
  RecordingThreshold,
  ScopeData,
  ScopeKind,
  SessionRecording,
} from "@/lib/ws/protocol";

export interface SpikeSnippet {
  /** Recording sample the threshold crossing fell on. */
  sample: number;
  microvolts: number[];
}

export interface SpikeScopePayload {
  /** True when the client should drop what it holds (channel changed). */
  reset: boolean;
  added: SpikeSnippet[];
  sampleRate: number;
  /** The window every snippet was cut at; the scope crops to its time scale. */
  preMs: number;
  postMs: number;
  thresholdMicrovolts: number | null;
  /** False until RHX is actually streaming this channel's waveform. */
  streaming: boolean;
}

export interface IsiPayload {
  binMs: number;
  counts: number[];
  /** Intervals at or past the span — shown, never silently dropped. */
  beyond: number;
  intervals: number;
  meanIsiMs: number | null;
}

export interface PsthPayload {
  preMs: number;
  postMs: number;
  binMs: number;
  trials: number;
  counts: number[];
  rateHz: number[];
  /** One row per trial: spike times in ms relative to the trigger. */
  rasters: number[][];
}

export interface ProbeRatesPayload {
  /** Native channel name → spikes in the last second. */
  rates: Record<string, number>;
}

export interface ProbeSite {
  channel: string;
  x: number;
  y: number;
  shape: "ellipse" | "rectangle";
  width: number;
  height: number;
  outline: string;
}

export interface ProbePage {
  name: string;
  background: string;
  lines: { x1: number; y1: number; x2: number; y2: number; color: string }[];
  texts: {
    x: number;
    y: number;
    text: string;
    height: number;
    color: string;
    alignment: string;
    rotation: number;
  }[];
  ports: { port: string; sites: ProbeSite[] }[];
}

export interface ProbeMap {
  name: string;
  pages: ProbePage[];
  siteCount: number;
}

/** RHX's own option sets, so the scope windows offer what RHX's would. */
export const SCOPE_SCALES_UV = [50, 100, 200, 500, 1000, 2000, 5000] as const;
export const SCOPE_TIME_SCALES_MS = [2, 4, 6] as const;
export const SCOPE_SPIKE_COUNTS = [10, 20, 30, 50, 100, 200, 500] as const;
export const ISI_SPANS_MS = [50, 100, 200, 500, 1000] as const;
export const ISI_BINS_MS = [1, 2, 5, 10, 20] as const;
export const PSTH_PRE_MS = [50, 100, 200, 500, 1000, 2000] as const;
export const PSTH_POST_MS = [50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000] as const;
export const PSTH_BINS_MS = [1, 2, 5, 10, 20, 50, 100] as const;
export const PSTH_MAX_TRIALS = [10, 20, 50, 100, 200, 500] as const;

export const FILE_FORMATS: { value: RecordingConfig["fileFormat"]; label: string; hint: string }[] = [
  { value: "Traditional", label: "Traditional", hint: "One .rhd file holding everything" },
  {
    value: "OneFilePerSignalType",
    label: "Per signal type",
    hint: "amplifier.dat, digitalin.dat, … — the usual choice for spike sorting",
  },
  { value: "OneFilePerChannel", label: "Per channel", hint: "One .dat per channel" },
];

/**
 * A recording setup with nothing chosen yet.
 *
 * Wideband ON is the default because it is the only option that cannot lose
 * data: everything else RHX can save is derived from it, and a threshold picked
 * badly before a session cannot be re-picked afterwards without it.
 */
export function defaultRecordingConfig(saveDirectory: string): RecordingConfig {
  return {
    saveDirectory,
    fileFormat: "OneFilePerSignalType",
    saveWideband: true,
    saveSpikes: false,
    saveSpikeSnapshots: false,
    snapshotPreMs: 1,
    snapshotPostMs: 2,
    saveLowpass: false,
    lowpassDownsample: 1,
    saveHighpass: false,
    threshold: { mode: "keep", microvolts: -70, rmsMultiple: 4, negative: true },
    boxes: [],
  };
}

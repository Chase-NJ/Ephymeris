/**
 * The recording domain's shapes (`docs/RECORDING.md`).
 *
 * Wire shapes are re-exported from the generated mirror, never re-declared. The
 * probe map is declared here because the wire carries it as `any` (it is
 * Intan's XML, parsed), and this is the one place its fields are written down
 * for the frontend.
 */

import type { RecordingConfig } from "@/lib/ws/protocol";

export type {
  IntanSpikes,
  IntanState,
  IntanStatus,
  IntanSyncStat,
  RecordingBox,
  RecordingBoxConfig,
  RecordingConfig,
  RecordingRun,
  RecordingThreshold,
  SessionRecording,
} from "@/lib/ws/protocol";

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
    // On, so turning Save spikes on saves something Offline Sorter can sort
    // (`RECORDING.md#record-step`); 1 ms each side of the crossing.
    saveSpikeSnapshots: true,
    snapshotPreMs: 1,
    snapshotPostMs: 1,
    saveLowpass: false,
    lowpassDownsample: 1,
    saveHighpass: false,
    threshold: { mode: "keep", microvolts: -70, rmsMultiple: 4, negative: true },
    boxes: [],
  };
}

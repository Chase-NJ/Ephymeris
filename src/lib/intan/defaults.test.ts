import { describe, expect, it } from "vitest";

import {
  DEFAULT_RECORDING_DEFAULTS,
  normalizeRecordingDefaults,
  summarizeRecordingConfig,
} from "./defaults";

/** Exactly what the Record step wrote before the shape was declared. */
const STORED_BY_THE_STEP = {
  saveRoot: "D:/ephys",
  config: {
    fileFormat: "OneFilePerSignalType",
    saveWideband: true,
    saveSpikes: true,
    saveSpikeSnapshots: true,
    snapshotPreMs: 1,
    snapshotPostMs: 2,
    saveLowpass: false,
    lowpassDownsample: 1,
    saveHighpass: false,
    threshold: { mode: "rms", microvolts: -70, rmsMultiple: 4.5, negative: true },
  },
  boxes: {
    "1": { record: true, port: "A", firstChannel: 0, lastChannel: -1, probeMapPath: "C:/maps/a.xml" },
    "3": { record: false, port: "", firstChannel: 0, lastChannel: -1, probeMapPath: null },
  },
};

describe("normalizeRecordingDefaults", () => {
  it("falls back to the defaults for anything that is not an object", () => {
    for (const raw of [undefined, null, 4, "x", []]) {
      expect(normalizeRecordingDefaults(raw)).toEqual(DEFAULT_RECORDING_DEFAULTS);
    }
    expect(DEFAULT_RECORDING_DEFAULTS.config.saveWideband).toBe(true);
    expect(DEFAULT_RECORDING_DEFAULTS.saveRoot).toBeNull();
  });

  it("round-trips what the Record step stored before the shape existed", () => {
    expect(normalizeRecordingDefaults(STORED_BY_THE_STEP)).toEqual(STORED_BY_THE_STEP);
  });

  it("heals per key, keeping every value that is still legal", () => {
    const out = normalizeRecordingDefaults({
      saveRoot: "   ",
      config: {
        ...STORED_BY_THE_STEP.config,
        fileFormat: "xml",
        snapshotPostMs: 99,
        lowpassDownsample: 3,
        newFileMinutes: 30,
        threshold: { mode: "auto", microvolts: 9000, rmsMultiple: 4.5, negative: "yes" },
      },
      boxes: {
        "1": { record: "no", port: "a", firstChannel: 4, lastChannel: 200, probeMapPath: "" },
        "7": { record: true, port: "B", firstChannel: 0, lastChannel: -1, probeMapPath: null },
        "2": "not a box",
      },
    });
    expect(out.saveRoot).toBeNull();
    expect(out.config.fileFormat).toBe("OneFilePerSignalType");
    expect(out.config.snapshotPostMs).toBe(2);
    expect(out.config.lowpassDownsample).toBe(1);
    expect(out.config.newFileMinutes).toBe(30);
    expect(out.config.saveSpikeSnapshots).toBe(true); // untouched neighbour survives
    expect(out.config.threshold).toEqual({ mode: "keep", microvolts: -70, rmsMultiple: 4.5, negative: true });
    expect(Object.keys(out.boxes)).toEqual(["1"]);
    expect(out.boxes["1"]).toEqual({
      record: true,
      port: "A",
      firstChannel: 4,
      lastChannel: -1,
      probeMapPath: null,
    });
  });

  it("never lets a default save nothing", () => {
    const out = normalizeRecordingDefaults({
      config: { saveWideband: false, saveSpikes: false, saveHighpass: false, saveLowpass: false },
    });
    expect(out.config.saveWideband).toBe(true);
  });
});

describe("summarizeRecordingConfig", () => {
  const base = DEFAULT_RECORDING_DEFAULTS.config;

  it("names the format, what is saved and how thresholds are set", () => {
    expect(summarizeRecordingConfig(base)).toBe("per signal type · wideband · keep rhx's thresholds");
    expect(
      summarizeRecordingConfig({
        ...base,
        saveSpikes: true,
        saveSpikeSnapshots: true,
        threshold: { ...base.threshold, mode: "rms", rmsMultiple: 4 },
      }),
    ).toBe("per signal type · wideband + spikes + snapshots · threshold 4× rms");
    expect(
      summarizeRecordingConfig({
        ...base,
        fileFormat: "Traditional",
        saveWideband: false,
        saveSpikes: true,
        saveLowpass: true,
        lowpassDownsample: 8,
        threshold: { ...base.threshold, mode: "absolute", microvolts: -60 },
      }),
    ).toBe("traditional · spikes + lowpass ÷8 · threshold -60 µv");
  });
});

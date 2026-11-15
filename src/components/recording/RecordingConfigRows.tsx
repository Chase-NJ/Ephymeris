import { NumberInput, Segmented, Toggle } from "@/components/common/controls";
import { Dropdown } from "@/components/common/Dropdown";
import { DirectoryField } from "@/components/settings/DirectoryField";
import { SettingRow } from "@/components/settings/SettingRow";
import type { RecordingConfigDefaults } from "@/lib/intan/defaults";
import { FILE_FORMATS } from "@/lib/intan/types";

/**
 * The rows that describe what a recording saves and how spikes are detected.
 *
 * Shared by the Recording tab's Defaults tile and the Record step, as row
 * groups rather than a form: the tile wraps them in a `HudTile`, the step in
 * its collapsible section, and the container is the only thing that differs.
 * Controlled and stateless — the tile writes every change straight to
 * settings, the step holds the values until Continue — so the ranges here
 * (snapshot 0–3 / 1–6 ms, thresholds ±5000 µV, 3–20× RMS) exist exactly once
 * and cannot drift by one number between the two surfaces.
 */

export function SavingRows({
  value,
  onChange,
  saveRoot,
  onSaveRoot,
  resolvedDirectory,
}: {
  value: RecordingConfigDefaults;
  onChange: (patch: Partial<RecordingConfigDefaults>) => void;
  saveRoot: string | null;
  onSaveRoot: (root: string | null) => void;
  /**
   * The Record step only: the per-session directory the root resolves to,
   * shown under the row with the space warning. The tab has no session to
   * resolve against and omits it.
   */
  resolvedDirectory?: string | null;
}) {
  const savesSomething = value.saveWideband || value.saveSpikes || value.saveLowpass || value.saveHighpass;
  return (
    <>
      <SettingRow
        label="Save location"
        description={
          saveRoot
            ? "Each session's folder, under the directory you chose."
            : "Beside each session's behavior data. Choose a directory to keep recordings elsewhere — they are large."
        }
      >
        <DirectoryField value={saveRoot} onChange={onSaveRoot} title="Where recordings are saved" />
      </SettingRow>
      {resolvedDirectory !== undefined && (
        <div className="border-b border-halo px-4 py-2.5">
          <div className="font-mono text-[11px] break-all text-static" data-selectable>
            {resolvedDirectory || "—"}
          </div>
          {resolvedDirectory && /\s/.test(resolvedDirectory) && (
            <p className="mt-1 text-[11px] leading-relaxed" style={{ color: "var(--color-status-warning)" }}>
              This path contains a space. If RHX does not keep it exactly as given, Ephymeris refuses
              to start rather than let RHX record somewhere else.
            </p>
          )}
        </div>
      )}
      <SettingRow
        label="File format"
        description={FILE_FORMATS.find((f) => f.value === value.fileFormat)?.hint ?? ""}
      >
        <Segmented
          label="File format"
          value={value.fileFormat}
          options={FILE_FORMATS.map((f) => ({ value: f.value, label: f.label }))}
          onChange={(fileFormat) => onChange({ fileFormat })}
        />
      </SettingRow>
      <SettingRow
        label="Save wideband"
        description="The raw amplifier signal. The one option that cannot lose data: everything else RHX saves is derived from it, and a threshold picked badly today cannot be re-picked later without it."
      >
        <Toggle
          label="Save wideband"
          checked={value.saveWideband}
          onChange={(saveWideband) =>
            // Turning wideband off with nothing else on would save nothing at
            // all; spikes are what is wanted instead.
            onChange({
              saveWideband,
              ...(!saveWideband && !value.saveSpikes && !value.saveHighpass && !value.saveLowpass
                ? { saveSpikes: true }
                : {}),
            })
          }
        />
      </SettingRow>
      <SettingRow
        label="Save spikes"
        description="Threshold crossings detected by RHX, per channel. Only as good as the thresholds."
      >
        <Toggle
          label="Save spikes"
          checked={value.saveSpikes}
          onChange={(saveSpikes) => onChange({ saveSpikes })}
        />
      </SettingRow>
      {value.saveSpikes && (
        <SettingRow
          label="Spike snapshots"
          description="A short waveform around every spike, from before to after the crossing."
        >
          <span className="flex items-center gap-2">
            <Toggle
              label="Save spike snapshots"
              checked={value.saveSpikeSnapshots}
              onChange={(saveSpikeSnapshots) => onChange({ saveSpikeSnapshots })}
            />
            {value.saveSpikeSnapshots && (
              <>
                <NumberInput
                  label="Milliseconds before the spike"
                  value={value.snapshotPreMs}
                  fallback={1}
                  integer
                  min={0}
                  max={3}
                  className="w-14"
                  onChange={(v) => onChange({ snapshotPreMs: Number(v) })}
                />
                <span className="text-[11px] text-static">ms before ·</span>
                <NumberInput
                  label="Milliseconds after the spike"
                  value={value.snapshotPostMs}
                  fallback={2}
                  integer
                  min={1}
                  max={6}
                  className="w-14"
                  onChange={(v) => onChange({ snapshotPostMs: Number(v) })}
                />
                <span className="text-[11px] text-static">ms after</span>
              </>
            )}
          </span>
        </SettingRow>
      )}
      <SettingRow label="Save highpass" description="The spike band, as RHX filters it.">
        <Toggle
          label="Save highpass"
          checked={value.saveHighpass}
          onChange={(saveHighpass) => onChange({ saveHighpass })}
        />
      </SettingRow>
      <SettingRow label="Save lowpass" description="The LFP band, optionally downsampled.">
        <span className="flex items-center gap-2">
          <Toggle
            label="Save lowpass"
            checked={value.saveLowpass}
            onChange={(saveLowpass) => onChange({ saveLowpass })}
          />
          {value.saveLowpass && (
            <Dropdown
              label="Lowpass downsample"
              value={String(value.lowpassDownsample)}
              placeholder="1×"
              options={[1, 2, 4, 8, 16, 32, 64, 128].map((n) => ({
                value: String(n),
                label: n === 1 ? "no downsampling" : `every ${n}th sample`,
              }))}
              onChange={(v) => onChange({ lowpassDownsample: Number(v) })}
            />
          )}
        </span>
      </SettingRow>
      {!savesSomething && (
        <p className="px-4 py-2.5 text-[12px]" style={{ color: "var(--color-status-warning)" }}>
          Nothing would be saved. Turn on wideband, spikes, highpass or lowpass.
        </p>
      )}
    </>
  );
}

export function ThresholdRows({
  value,
  onChange,
}: {
  value: RecordingConfigDefaults;
  onChange: (patch: Partial<RecordingConfigDefaults>) => void;
}) {
  const threshold = value.threshold;
  return (
    <>
      <SettingRow
        label="Set thresholds"
        description={
          threshold.mode === "keep"
            ? "Leave every channel's threshold as it is set in RHX."
            : threshold.mode === "absolute"
              ? "One voltage for every recorded channel."
              : "A multiple of each channel's own RMS noise, so a quiet channel and a noisy one are held to the same standard."
        }
      >
        <Segmented
          label="Threshold mode"
          value={threshold.mode}
          options={[
            { value: "keep", label: "Keep RHX's" },
            { value: "absolute", label: "Absolute" },
            { value: "rms", label: "× RMS" },
          ]}
          onChange={(mode) => onChange({ threshold: { ...threshold, mode } })}
        />
      </SettingRow>
      {threshold.mode === "absolute" && (
        <SettingRow label="Threshold" description="−5000 to 5000 µV. Negative for the usual extracellular spike.">
          <span className="flex items-center gap-2">
            <NumberInput
              label="Threshold in microvolts"
              value={threshold.microvolts}
              fallback={-70}
              integer
              min={-5000}
              max={5000}
              className="w-24"
              onChange={(v) => onChange({ threshold: { ...threshold, microvolts: Number(v) } })}
            />
            <span className="text-[11px] text-static">µV</span>
          </span>
        </SettingRow>
      )}
      {threshold.mode === "rms" && (
        <SettingRow label="Multiple" description="3.0 to 20.0 × RMS.">
          <span className="flex items-center gap-3">
            <NumberInput
              label="RMS multiple"
              value={threshold.rmsMultiple}
              fallback={4}
              min={3}
              max={20}
              className="w-20"
              onChange={(v) => onChange({ threshold: { ...threshold, rmsMultiple: Number(v) } })}
            />
            <Segmented
              label="Threshold polarity"
              value={threshold.negative ? "neg" : "pos"}
              options={[
                { value: "neg", label: "Negative" },
                { value: "pos", label: "Positive" },
              ]}
              onChange={(v) => onChange({ threshold: { ...threshold, negative: v === "neg" } })}
            />
          </span>
        </SettingRow>
      )}
      <p className="px-4 py-2.5 text-[11px] leading-relaxed text-static">
        A single channel can be adjusted live, by dragging the threshold line in its Spike Scope.
      </p>
    </>
  );
}

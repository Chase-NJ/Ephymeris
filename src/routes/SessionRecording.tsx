import { open } from "@tauri-apps/plugin-dialog";
import { motion } from "framer-motion";
import { ArrowRight, Check, CircleAlert, FileUp, Minus, PlugZap, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { Button, NumberInput, Segmented, Toggle } from "@/components/common/controls";
import { Dropdown } from "@/components/common/Dropdown";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { ProbeMapView } from "@/components/recording/ProbeMapView";
import { SessionJourney } from "@/components/sessions/SessionJourney";
import { DirectoryField } from "@/components/settings/DirectoryField";
import { SettingGroup, SettingRow } from "@/components/settings/SettingRow";
import { errorMessage } from "@/lib/cohorts/commands";
import { useIntanStatus } from "@/lib/intan/context";
import { channelRange } from "@/lib/intan/scopeMath";
import {
  FILE_FORMATS,
  defaultRecordingConfig,
  type ProbeMap,
  type RecordingBoxConfig,
  type RecordingConfig,
} from "@/lib/intan/types";
import { CASCADE, RISE, springPanel } from "@/lib/motion";
import { sessionStatus } from "@/lib/sessions/commands";
import type { SessionSnapshot } from "@/lib/sessions/types";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

/**
 * The recording step (`recording.md` §4) — between Boxes and Run, on a session
 * created from the Dashboard's Start Recording tile.
 *
 * AFTER the mapping on purpose: what this screen asks is which headstage port
 * each MAPPED box is on, and there is nothing to ask until the mapping exists.
 * It runs once per group, because the animals — and so the ports and probes —
 * change between groups; the second time it opens prefilled.
 *
 * Nothing here talks to RHX until Continue. The form is a description of a
 * recording; `intan.configure` applies it in one pass, reading back the three
 * values a recording cannot be wrong about, and every refusal lands in the
 * error strip as the operator's next step.
 */

/** A box's row in the form. `record: false` runs the box behavior-only. */
interface BoxRow {
  box: number;
  animalName: string;
  record: boolean;
  port: string;
  firstChannel: number;
  lastChannel: number;
  probeMapPath: string | null;
  probeMap: ProbeMap | null;
  probeError: string | null;
}

interface StoredDefaults {
  saveRoot?: string;
  config?: Partial<RecordingConfig>;
  boxes?: Record<string, Partial<RecordingBoxConfig> & { record?: boolean }>;
}

export function SessionRecording() {
  const { id: sessionId } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const groupId = params.get("group") ?? "";
  const cohortId = params.get("cohort") ?? "";
  const navigate = useNavigate();
  const { client, status: link } = useSidecar();
  const { settings, update } = useSettings();
  const intan = useIntanStatus();

  const stored = settings.recordingDefaults as StoredDefaults;
  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [config, setConfig] = useState<RecordingConfig | null>(null);
  const [saveRoot, setSaveRoot] = useState<string | null>(stored.saveRoot ?? null);
  const [rows, setRows] = useState<BoxRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // The mapped boxes and the session's own folder come from the sidecar.
  useEffect(() => {
    if (link !== "connected" || !sessionId) return;
    let cancelled = false;
    void sessionStatus(client, sessionId)
      .then((s) => !cancelled && setSnapshot(s))
      .catch((err: unknown) => !cancelled && setError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, [client, link, sessionId]);

  const sessionFolder = snapshot?.session.folderPath ?? null;
  const folderName = sessionFolder ? (sessionFolder.split(/[\\/]/).filter(Boolean).pop() ?? "") : "";
  // Beside the behavior data by default; under a root of the operator's
  // choosing otherwise — electrophysiology is large and often lives on its own
  // drive. Either way the session's folder name is kept, so the two halves of
  // one session can be matched by eye.
  const saveDirectory = sessionFolder
    ? saveRoot
      ? `${saveRoot.replace(/[\\/]+$/, "")}/${folderName}`
      : `${sessionFolder.replace(/[\\/]+$/, "")}/ephys`
    : "";

  const presentPorts = useMemo(
    () =>
      Object.entries(intan.ports)
        .filter(([, count]) => count > 0)
        .map(([letter]) => letter)
        .sort(),
    [intan.ports],
  );

  // Seed the form once the snapshot is in. Re-seeded when the group changes,
  // never on an `intan.status` tick — that would discard what was typed.
  useEffect(() => {
    if (!snapshot) return;
    setConfig((current) => current ?? { ...defaultRecordingConfig(""), ...(stored.config ?? {}) });
    setRows((current) => {
      if (current.length > 0) return current;
      return snapshot.boxes.map((b) => {
        const memory = stored.boxes?.[String(b.box)] ?? {};
        return {
          box: b.box,
          animalName: b.animalName,
          record: memory.record ?? true,
          port: memory.port ?? "",
          firstChannel: memory.firstChannel ?? 0,
          lastChannel: memory.lastChannel ?? -1,
          probeMapPath: memory.probeMapPath ?? null,
          probeMap: null,
          probeError: null,
        };
      });
    });
    // `stored` is read once, as a starting point.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshot]);

  // Once RHX reports its ports, give each unassigned box the next free one
  // with its whole range. A guess the operator can see and change, which beats
  // a blank they must fill for every box every session.
  useEffect(() => {
    if (presentPorts.length === 0) return;
    setRows((current) => {
      const taken = new Set(current.filter((r) => r.port).map((r) => r.port));
      let changed = false;
      const next = current.map((row) => {
        let { port, lastChannel } = row;
        if (!port || !presentPorts.includes(port)) {
          port = presentPorts.find((p) => !taken.has(p)) ?? presentPorts[0] ?? "";
          taken.add(port);
          lastChannel = -1;
        }
        const count = intan.ports[port] ?? 0;
        if (lastChannel < 0 || lastChannel >= count) lastChannel = Math.max(0, count - 1);
        if (port === row.port && lastChannel === row.lastChannel) return row;
        changed = true;
        return { ...row, port, lastChannel, firstChannel: Math.min(row.firstChannel, lastChannel) };
      });
      return changed ? next : current;
    });
  }, [presentPorts, intan.ports]);

  // Re-parse a remembered probe map, so the preview is there on arrival.
  useEffect(() => {
    if (link !== "connected") return;
    for (const row of rows) {
      if (row.probeMapPath && !row.probeMap && !row.probeError) void loadProbeMap(row.box, row.probeMapPath);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [link, rows.length]);

  function patchRow(box: number, changes: Partial<BoxRow>) {
    setRows((current) => current.map((r) => (r.box === box ? { ...r, ...changes } : r)));
  }

  function patchConfig(changes: Partial<RecordingConfig>) {
    setConfig((current) => (current ? { ...current, ...changes } : current));
  }

  async function loadProbeMap(box: number, path: string) {
    try {
      const reply = await client.call(CMD.INTAN_PARSE_PROBE_MAP, { path });
      patchRow(box, { probeMapPath: path, probeMap: reply.probeMap as ProbeMap, probeError: null });
    } catch (err) {
      patchRow(box, { probeMapPath: path, probeMap: null, probeError: errorMessage(err) });
    }
  }

  async function chooseProbeMap(box: number) {
    const picked = await open({
      multiple: false,
      title: `Probe map for box ${box}`,
      filters: [{ name: "Intan probe map", extensions: ["xml"] }],
    });
    if (typeof picked === "string") await loadProbeMap(box, picked);
  }

  // --- readiness --------------------------------------------------------

  const recorded = rows.filter((r) => r.record);
  const unbound = recorded.filter(
    (r) => !settings.boxes.find((b) => b.box === r.box)?.intanDigitalIn,
  );
  const overlap = useMemo(() => {
    const seen = new Map<string, number>();
    for (const row of recorded) {
      for (const name of channelRange(row.port, row.firstChannel, row.lastChannel)) {
        const other = seen.get(name);
        if (other !== undefined && other !== row.box) return `${name} is claimed by box ${other} and box ${row.box}`;
        seen.set(name, row.box);
      }
    }
    return null;
  }, [recorded]);
  const savesSomething =
    !!config && (config.saveWideband || config.saveSpikes || config.saveLowpass || config.saveHighpass);

  const checks: { ok: boolean; label: string; fix?: { label: string; to: string } }[] = [
    {
      ok: intan.connected,
      label: intan.connected
        ? `RHX ${intan.version ?? ""} · ${intan.controller ?? "controller"} · ${
            intan.sampleRate ? `${intan.sampleRate / 1000} kS/s` : "—"
          }${intan.synthetic ? " · synthetic" : ""}`
        : "RHX is not connected — in RHX: Network → Remote TCP Control → Connect (Commands tab)",
    },
    {
      ok: intan.connected && intan.runMode !== "record" && intan.runMode !== "trigger",
      label:
        intan.runMode === "record" || intan.runMode === "trigger"
          ? "RHX is already recording — stop it in RHX first"
          : "RHX is not recording",
    },
    {
      ok: intan.connected && presentPorts.length > 0,
      label:
        presentPorts.length > 0
          ? `Headstage on port ${presentPorts.join(", ")}`
          : "No headstage detected on any port",
    },
    {
      ok: intan.rigHasSync,
      label: intan.rigHasSync
        ? "This rig's wiring has a sync channel"
        : "This rig's wiring has no sync channel, so no box pulses on its events",
      fix: { label: "Open wiring", to: "/config/wiring" },
    },
    {
      ok: recorded.length > 0 && unbound.length === 0,
      label:
        recorded.length === 0
          ? "No box is set to record"
          : unbound.length === 0
            ? "Every recorded box has an Intan digital input"
            : `Box ${unbound.map((r) => r.box).join(", ")} has no Intan digital input bound`,
      fix: { label: "Open Rig", to: "/config" },
    },
  ];
  const ready = checks.every((c) => c.ok) && !overlap && savesSomething && saveDirectory !== "";

  const hint = !intan.connected
    ? "Connect Ephymeris to Intan RHX."
    : !ready
      ? "Finish the recording setup."
      : "Ready — continue to Mission Control.";

  async function applyAndContinue() {
    if (!config || !sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const boxes: RecordingBoxConfig[] = recorded.map((r) => ({
        box: r.box,
        port: r.port,
        firstChannel: r.firstChannel,
        lastChannel: r.lastChannel,
        probeMapPath: r.probeMap ? r.probeMapPath : null,
      }));
      const full: RecordingConfig = { ...config, saveDirectory, boxes };
      await client.call(CMD.INTAN_CONFIGURE, { sessionId, groupId, config: full });

      // Remembered as the next recording's starting point — not the save
      // directory (it is per session) and not the boxes list (it is per group).
      const { saveDirectory: _dir, boxes: _boxes, ...remembered } = full;
      update({
        recordingDefaults: {
          ...(saveRoot ? { saveRoot } : {}),
          config: remembered,
          boxes: Object.fromEntries(
            rows.map((r) => [
              String(r.box),
              {
                record: r.record,
                port: r.port,
                firstChannel: r.firstChannel,
                lastChannel: r.lastChannel,
                probeMapPath: r.probeMapPath,
              },
            ]),
          ),
        },
      });
      navigate(`/session/${sessionId}/control?cohort=${cohortId}&group=${groupId}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function connect() {
    setError(null);
    try {
      await client.call(CMD.INTAN_CONNECT, {});
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const portOptions = presentPorts.map((p) => ({
    value: p,
    label: `Port ${p}`,
    detail: `${intan.ports[p] ?? 0} ch`,
  }));

  return (
    <div className="relative h-full">
      <SkyBackdrop />
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        // Owns its own exit (`AppShell`): nothing else will fade this route.
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        <section className="pointer-events-auto mx-auto max-w-4xl px-8 py-8">
          <SessionJourney step="record" hint={hint} recording />
          <h1 className="font-display text-[22px] text-starlight">Set Up the Recording</h1>

          {error && (
            <div
              className="mt-4 flex items-start gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
              style={{ color: "var(--color-status-error)" }}
            >
              <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
              {error}
            </div>
          )}

          <motion.div variants={CASCADE} initial="hidden" animate="shown">
            <motion.div variants={RISE}>
              <SettingGroup title="Readiness" variant="hud">
                <ul className="px-4 py-3">
                  {checks.map((check) => (
                    <li key={check.label} className="flex items-center gap-2.5 py-1 text-[12px]">
                      <span
                        className="flex size-4 shrink-0 items-center justify-center rounded-full"
                        style={{
                          color: check.ok ? "var(--color-ion)" : "var(--color-status-warning)",
                        }}
                      >
                        {check.ok ? <Check size={13} strokeWidth={2} /> : <Minus size={13} strokeWidth={2} />}
                      </span>
                      <span className={check.ok ? "text-static" : "text-starlight"}>{check.label}</span>
                      {!check.ok && check.fix && (
                        <Button variant="ghost" onClick={() => navigate(check.fix!.to)}>
                          {check.fix.label}
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
                {!intan.connected && (
                  <div className="border-t border-halo px-4 py-3">
                    <Button variant="outline" onClick={() => void connect()}>
                      <PlugZap size={13} strokeWidth={1.75} />
                      Connect to RHX
                    </Button>
                  </div>
                )}
              </SettingGroup>
            </motion.div>

            {config && (
              <motion.div variants={RISE}>
                <SettingGroup title="Saving" variant="hud">
                  <SettingRow
                    label="Save location"
                    description={
                      saveRoot
                        ? "This session's folder, under the directory you chose."
                        : "Beside this session's behavior data. Choose a directory to keep recordings elsewhere — they are large."
                    }
                  >
                    <DirectoryField
                      value={saveRoot}
                      onChange={setSaveRoot}
                      title="Where recordings are saved"
                    />
                  </SettingRow>
                  <div className="border-b border-halo px-4 py-2.5">
                    <div className="font-mono text-[11px] break-all text-static" data-selectable>
                      {saveDirectory || "—"}
                    </div>
                    {/\s/.test(saveDirectory) && (
                      <p className="mt-1 text-[11px] leading-relaxed" style={{ color: "var(--color-status-warning)" }}>
                        This path contains a space. If RHX does not keep it exactly as given, Ephymeris
                        refuses to start rather than let RHX record somewhere else.
                      </p>
                    )}
                  </div>
                  <SettingRow
                    label="File format"
                    description={FILE_FORMATS.find((f) => f.value === config.fileFormat)?.hint ?? ""}
                  >
                    <Segmented
                      label="File format"
                      value={config.fileFormat}
                      options={FILE_FORMATS.map((f) => ({ value: f.value, label: f.label }))}
                      onChange={(fileFormat) => patchConfig({ fileFormat })}
                    />
                  </SettingRow>
                  <SettingRow
                    label="Save wideband"
                    description="The raw amplifier signal. The one option that cannot lose data: everything else RHX saves is derived from it, and a threshold picked badly today cannot be re-picked later without it."
                  >
                    <Toggle
                      label="Save wideband"
                      checked={config.saveWideband}
                      onChange={(saveWideband) =>
                        // Turning wideband off with nothing else on would save
                        // nothing at all; spikes are what is wanted instead.
                        patchConfig({
                          saveWideband,
                          ...(!saveWideband && !config.saveSpikes && !config.saveHighpass
                            ? { saveSpikes: true }
                            : {}),
                        })
                      }
                    />
                  </SettingRow>
                  <SettingRow
                    label="Save spikes"
                    description="Threshold crossings detected by RHX, per channel. Only as good as the thresholds below."
                  >
                    <Toggle
                      label="Save spikes"
                      checked={config.saveSpikes}
                      onChange={(saveSpikes) => patchConfig({ saveSpikes })}
                    />
                  </SettingRow>
                  {config.saveSpikes && (
                    <SettingRow
                      label="Spike snapshots"
                      description="A short waveform around every spike, from before to after the crossing."
                    >
                      <span className="flex items-center gap-2">
                        <Toggle
                          label="Save spike snapshots"
                          checked={config.saveSpikeSnapshots}
                          onChange={(saveSpikeSnapshots) => patchConfig({ saveSpikeSnapshots })}
                        />
                        {config.saveSpikeSnapshots && (
                          <>
                            <NumberInput
                              label="Milliseconds before the spike"
                              value={config.snapshotPreMs}
                              fallback={1}
                              integer
                              min={0}
                              max={3}
                              className="w-14"
                              onChange={(v) => patchConfig({ snapshotPreMs: Number(v) })}
                            />
                            <span className="text-[11px] text-static">ms before ·</span>
                            <NumberInput
                              label="Milliseconds after the spike"
                              value={config.snapshotPostMs}
                              fallback={2}
                              integer
                              min={1}
                              max={6}
                              className="w-14"
                              onChange={(v) => patchConfig({ snapshotPostMs: Number(v) })}
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
                      checked={config.saveHighpass}
                      onChange={(saveHighpass) => patchConfig({ saveHighpass })}
                    />
                  </SettingRow>
                  <SettingRow label="Save lowpass" description="The LFP band, optionally downsampled.">
                    <span className="flex items-center gap-2">
                      <Toggle
                        label="Save lowpass"
                        checked={config.saveLowpass}
                        onChange={(saveLowpass) => patchConfig({ saveLowpass })}
                      />
                      {config.saveLowpass && (
                        <Dropdown
                          label="Lowpass downsample"
                          value={String(config.lowpassDownsample)}
                          placeholder="1×"
                          options={[1, 2, 4, 8, 16, 32, 64, 128].map((n) => ({
                            value: String(n),
                            label: n === 1 ? "no downsampling" : `every ${n}th sample`,
                          }))}
                          onChange={(v) => patchConfig({ lowpassDownsample: Number(v) })}
                        />
                      )}
                    </span>
                  </SettingRow>
                  {!savesSomething && (
                    <p className="px-4 py-2.5 text-[12px]" style={{ color: "var(--color-status-warning)" }}>
                      Nothing would be saved. Turn on wideband, spikes, highpass or lowpass.
                    </p>
                  )}
                </SettingGroup>
              </motion.div>
            )}

            {config && (
              <motion.div variants={RISE}>
                <SettingGroup title="Spike thresholds" variant="hud">
                  <SettingRow
                    label="Set thresholds"
                    description={
                      config.threshold.mode === "keep"
                        ? "Leave every channel's threshold as it is set in RHX."
                        : config.threshold.mode === "absolute"
                          ? "One voltage for every recorded channel."
                          : "A multiple of each channel's own RMS noise, so a quiet channel and a noisy one are held to the same standard."
                    }
                  >
                    <Segmented
                      label="Threshold mode"
                      value={config.threshold.mode}
                      options={[
                        { value: "keep", label: "Keep RHX's" },
                        { value: "absolute", label: "Absolute" },
                        { value: "rms", label: "× RMS" },
                      ]}
                      onChange={(mode) => patchConfig({ threshold: { ...config.threshold, mode } })}
                    />
                  </SettingRow>
                  {config.threshold.mode === "absolute" && (
                    <SettingRow label="Threshold" description="−5000 to 5000 µV. Negative for the usual extracellular spike.">
                      <span className="flex items-center gap-2">
                        <NumberInput
                          label="Threshold in microvolts"
                          value={config.threshold.microvolts}
                          fallback={-70}
                          integer
                          min={-5000}
                          max={5000}
                          className="w-24"
                          onChange={(v) =>
                            patchConfig({ threshold: { ...config.threshold, microvolts: Number(v) } })
                          }
                        />
                        <span className="text-[11px] text-static">µV</span>
                      </span>
                    </SettingRow>
                  )}
                  {config.threshold.mode === "rms" && (
                    <SettingRow label="Multiple" description="3.0 to 20.0 × RMS.">
                      <span className="flex items-center gap-3">
                        <NumberInput
                          label="RMS multiple"
                          value={config.threshold.rmsMultiple}
                          fallback={4}
                          min={3}
                          max={20}
                          className="w-20"
                          onChange={(v) =>
                            patchConfig({ threshold: { ...config.threshold, rmsMultiple: Number(v) } })
                          }
                        />
                        <Segmented
                          label="Threshold polarity"
                          value={config.threshold.negative ? "neg" : "pos"}
                          options={[
                            { value: "neg", label: "Negative" },
                            { value: "pos", label: "Positive" },
                          ]}
                          onChange={(v) =>
                            patchConfig({ threshold: { ...config.threshold, negative: v === "neg" } })
                          }
                        />
                      </span>
                    </SettingRow>
                  )}
                  <p className="px-4 py-2.5 text-[11px] leading-relaxed text-static">
                    A single channel can be adjusted live, by dragging the threshold line in its SpikeScope.
                  </p>
                </SettingGroup>
              </motion.div>
            )}

            <motion.div variants={RISE}>
              <SettingGroup title="Boxes" variant="hud">
                {rows.length === 0 && (
                  <p className="px-4 py-3 text-[12px] text-static">Waiting for this group's mapping…</p>
                )}
                {rows.map((row) => {
                  const count = intan.ports[row.port] ?? 0;
                  const din = settings.boxes.find((b) => b.box === row.box)?.intanDigitalIn ?? null;
                  return (
                    <div key={row.box} className="border-b border-halo px-4 py-3.5 last:border-b-0">
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-[12px] text-static">Box {row.box}</span>
                        <span className="text-[13px] font-medium text-starlight">{row.animalName}</span>
                        <span className="font-mono text-[11px] text-static">
                          {din ? `DIN ${din}` : "no DIN"}
                        </span>
                        <span className="ml-auto flex items-center gap-2 text-[11px] text-static">
                          {row.record ? "Recording" : "Behavior only"}
                          <Toggle
                            label={`Record box ${row.box}`}
                            checked={row.record}
                            onChange={(record) => patchRow(row.box, { record })}
                          />
                        </span>
                      </div>

                      {row.record && (
                        <div className="mt-3 grid grid-cols-[1fr_220px] gap-4">
                          <div className="flex flex-col gap-2.5">
                            <div className="flex items-center gap-2">
                              <Dropdown
                                label={`Headstage port for box ${row.box}`}
                                size="regular"
                                value={row.port}
                                options={portOptions}
                                placeholder="— port —"
                                className="w-40"
                                onChange={(port) =>
                                  patchRow(row.box, {
                                    port,
                                    firstChannel: 0,
                                    lastChannel: Math.max(0, (intan.ports[port] ?? 1) - 1),
                                  })
                                }
                              />
                              <span className="text-[11px] text-static">channels</span>
                              <NumberInput
                                label="First channel"
                                value={row.firstChannel}
                                fallback={0}
                                integer
                                min={0}
                                max={Math.max(0, row.lastChannel)}
                                className="w-16"
                                onChange={(v) => patchRow(row.box, { firstChannel: Number(v) })}
                              />
                              <span className="text-[11px] text-static">to</span>
                              <NumberInput
                                label="Last channel"
                                value={row.lastChannel}
                                fallback={Math.max(0, count - 1)}
                                integer
                                min={row.firstChannel}
                                max={Math.max(0, count - 1)}
                                className="w-16"
                                onChange={(v) => patchRow(row.box, { lastChannel: Number(v) })}
                              />
                            </div>
                            <div className="flex items-center gap-2">
                              <Button variant="outline" onClick={() => void chooseProbeMap(row.box)}>
                                <FileUp size={13} strokeWidth={1.75} />
                                {row.probeMapPath ? "Change probe map" : "Add probe map"}
                              </Button>
                              {row.probeMapPath && (
                                <>
                                  <span className="truncate font-mono text-[11px] text-static">
                                    {row.probeMapPath.split(/[\\/]/).pop()}
                                    {row.probeMap ? ` · ${row.probeMap.siteCount} sites` : ""}
                                  </span>
                                  <Button
                                    variant="ghost"
                                    shape="icon"
                                    title="Remove the probe map"
                                    onClick={() =>
                                      patchRow(row.box, { probeMapPath: null, probeMap: null, probeError: null })
                                    }
                                  >
                                    <X size={13} strokeWidth={1.75} />
                                  </Button>
                                </>
                              )}
                            </div>
                            {row.probeError && (
                              <p className="text-[11px]" style={{ color: "var(--color-status-error)" }}>
                                {row.probeError}
                              </p>
                            )}
                          </div>
                          <div className="surface-inset h-[150px] rounded-sm">
                            {row.probeMap ? (
                              <ProbeMapView
                                map={row.probeMap}
                                channels={channelRange(row.port, row.firstChannel, row.lastChannel)}
                                className="h-full"
                              />
                            ) : (
                              <div className="flex h-full items-center justify-center px-4 text-center text-[11px] text-static">
                                Optional. With a probe map, this box's sites light up live as they fire.
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
                {overlap && (
                  <p className="px-4 py-2.5 text-[12px]" style={{ color: "var(--color-status-error)" }}>
                    {overlap}.
                  </p>
                )}
              </SettingGroup>
            </motion.div>

            <motion.div variants={RISE} className="mt-6 flex items-center gap-2">
              <Button variant="primary" onClick={() => void applyAndContinue()} disabled={!ready || busy}>
                {busy ? "Configuring RHX…" : "Continue"}
                <ArrowRight size={13} strokeWidth={2} />
              </Button>
              <Button
                variant="ghost"
                onClick={() => navigate(`/session/${sessionId}/mapping?cohort=${cohortId}&group=${groupId}`)}
              >
                Back to boxes
              </Button>
            </motion.div>
          </motion.div>
        </section>
      </motion.div>
    </div>
  );
}

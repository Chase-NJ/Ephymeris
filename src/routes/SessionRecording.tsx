import { open } from "@tauri-apps/plugin-dialog";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  Check,
  CircleAlert,
  FileUp,
  HardDrive,
  ListChecks,
  PlugZap,
  Radio,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { HudTile } from "@/components/common/HudTile";
import { Button, NumberInput, Segmented } from "@/components/common/controls";
import { Dropdown } from "@/components/common/Dropdown";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { ProbeMapView } from "@/components/recording/ProbeMapView";
import { SavingRows, ThresholdRows } from "@/components/recording/RecordingConfigRows";
import { SessionJourney } from "@/components/sessions/SessionJourney";
import { SettingRow } from "@/components/settings/SettingRow";
import { errorMessage } from "@/lib/cohorts/commands";
import { useIntanStatus } from "@/lib/intan/context";
import { summarizeRecordingConfig, type RecordingConfigDefaults } from "@/lib/intan/defaults";
import { channelRange } from "@/lib/intan/scopeMath";
import { FILE_FORMATS, type ProbeMap, type RecordingBoxConfig, type RecordingConfig } from "@/lib/intan/types";
import { CASCADE, RISE, springPanel } from "@/lib/motion";
import { sessionStatus } from "@/lib/sessions/commands";
import { getSetupDraft, setSetupDraft } from "@/lib/sessions/setupResume";
import type { SessionSnapshot } from "@/lib/sessions/types";
import { useSettings } from "@/lib/settings/context";
import { useRecordingDefaults } from "@/lib/settings/useRecordingDefaults";
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
 * The policy — what to save, how to set thresholds — has a home of its own on
 * the Recording tab now, so here it is a collapsed summary with an Edit door:
 * this step's job is the per-group facts (which port, which range, which
 * probe). Whatever is confirmed here is written back as the new defaults.
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

interface RecordingDraft {
  config: RecordingConfigDefaults | null;
  saveRoot: string | null;
  editing: boolean;
  rows: BoxRow[];
}

export function SessionRecording() {
  const { id: sessionId } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const groupId = params.get("group") ?? "";
  const cohortId = params.get("cohort") ?? "";
  const navigate = useNavigate();
  const { client, status: link } = useSidecar();
  const { settings } = useSettings();
  const { defaults, save } = useRecordingDefaults();
  const intan = useIntanStatus();

  // The form as it was left for another tab (`setupResume.ts`). Seeding below
  // only fills what is still empty, so a restored draft wins over the defaults.
  const draftKey = `record:${sessionId ?? ""}:${groupId}`;
  const [draft] = useState(() => getSetupDraft<RecordingDraft>(draftKey));

  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [config, setConfig] = useState<RecordingConfigDefaults | null>(draft?.config ?? null);
  const [saveRoot, setSaveRoot] = useState<string | null>(
    draft ? draft.saveRoot : defaults.saveRoot,
  );
  const [editing, setEditing] = useState(draft?.editing ?? false);
  const [rows, setRows] = useState<BoxRow[]>(draft?.rows ?? []);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (config === null && rows.length === 0) return;
    setSetupDraft<RecordingDraft>(draftKey, { config, saveRoot, editing, rows });
  }, [draftKey, config, saveRoot, editing, rows]);

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
    setConfig((current) => current ?? { ...defaults.config });
    setRows((current) => {
      if (current.length > 0) return current;
      return snapshot.boxes.map((b) => {
        const memory = defaults.boxes[String(b.box)];
        return {
          box: b.box,
          animalName: b.animalName,
          record: memory?.record ?? true,
          port: memory?.port ?? "",
          firstChannel: memory?.firstChannel ?? 0,
          lastChannel: memory?.lastChannel ?? -1,
          probeMapPath: memory?.probeMapPath ?? null,
          probeMap: null,
          probeError: null,
        };
      });
    });
    // The defaults are read once, as a starting point.
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

  function patchConfig(changes: Partial<RecordingConfigDefaults>) {
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
      fix: { label: "Open Recording", to: "/recording" },
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
      fix: { label: "Open Recording", to: "/recording" },
    },
  ];
  const okCount = checks.filter((c) => c.ok).length;
  const firstProblem = checks.find((c) => !c.ok)?.label ?? overlap ?? (!savesSomething ? "Nothing would be saved" : null);
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
      void save({
        saveRoot,
        config,
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
  const formatLabel = config ? (FILE_FORMATS.find((f) => f.value === config.fileFormat)?.label ?? "") : "";

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

          <motion.div variants={CASCADE} initial="hidden" animate="shown" className="mt-6 flex flex-col gap-5">
            <motion.div variants={RISE}>
              <HudTile
                icon={ListChecks}
                label="Readiness"
                status={
                  <span style={okCount === checks.length ? { color: "var(--color-ion)" } : undefined}>
                    {okCount}/{checks.length} ready
                  </span>
                }
              >
                <ul className="px-4 py-2.5">
                  {checks.map((check, index) => (
                    <li key={check.label} className="flex items-center gap-2.5 py-1.5 text-[12px]">
                      <span
                        className="flex size-4 shrink-0 items-center justify-center"
                        style={{ color: check.ok ? "var(--color-ion)" : "var(--color-status-warning)" }}
                      >
                        {check.ok ? (
                          <Check size={13} strokeWidth={2} />
                        ) : (
                          <CircleAlert size={13} strokeWidth={2} />
                        )}
                      </span>
                      <span className={check.ok ? "text-static" : "text-starlight"}>{check.label}</span>
                      {/* The first line is the link itself: its repair is a
                          click here, not a trip to another tab. */}
                      {!check.ok && index === 0 && (
                        <Button variant="outline" className="ml-auto" onClick={() => void connect()}>
                          <PlugZap size={13} strokeWidth={1.75} />
                          Connect
                        </Button>
                      )}
                      {!check.ok && check.fix && (
                        <Button
                          variant="ghost"
                          className={index === 0 ? "" : "ml-auto"}
                          onClick={() => navigate(check.fix!.to)}
                        >
                          {check.fix.label}
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              </HudTile>
            </motion.div>

            {config && (
              <motion.div variants={RISE}>
                <HudTile icon={HardDrive} label="Saving" status={formatLabel}>
                  {/* The one per-session fact, always visible. */}
                  <div className="border-b border-halo px-4 py-3">
                    <div className="text-[13px] font-medium text-starlight">Save location</div>
                    <div className="mt-1 font-mono text-[11px] break-all text-static" data-selectable>
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
                    label="Using your defaults"
                    description={summarizeRecordingConfig(config)}
                  >
                    <Button variant="ghost" onClick={() => setEditing((e) => !e)}>
                      {editing ? "Done" : "Edit for this session"}
                    </Button>
                  </SettingRow>

                  <AnimatePresence initial={false}>
                    {(editing || !savesSomething) && (
                      <motion.div
                        key="edit"
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={springPanel}
                        className="overflow-hidden"
                      >
                        <SavingRows
                          value={config}
                          onChange={patchConfig}
                          saveRoot={saveRoot}
                          onSaveRoot={setSaveRoot}
                        />
                        <div className="border-b border-halo px-4 py-2 text-[11px] font-medium text-static">
                          Spike thresholds
                        </div>
                        <ThresholdRows value={config} onChange={patchConfig} />
                        <p className="border-t border-halo px-4 py-2.5 text-[11px] leading-relaxed text-static">
                          Edits here become the new defaults when you continue.
                        </p>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </HudTile>
              </motion.div>
            )}

            <motion.div variants={RISE}>
              <HudTile
                icon={Radio}
                label="Boxes"
                status={
                  rows.length === 0
                    ? "waiting for the mapping"
                    : `${recorded.length} of ${rows.length} recording`
                }
              >
                {rows.length === 0 && (
                  <p className="px-4 py-6 text-center text-[12px] text-static">Waiting for this group's mapping…</p>
                )}
                <div className={rows.length > 0 ? "flex flex-col gap-2.5 p-3" : ""}>
                  {rows.map((row) => {
                    const count = intan.ports[row.port] ?? 0;
                    const din = settings.boxes.find((b) => b.box === row.box)?.intanDigitalIn ?? null;
                    return (
                      <div
                        key={row.box}
                        className={`surface-inset rounded-sm px-3.5 py-3 transition-opacity ${
                          row.record ? "" : "opacity-60"
                        }`}
                      >
                        <div className="flex items-center gap-2.5">
                          <span className="font-mono text-[12px] text-static">Box {row.box}</span>
                          <span className="truncate text-[13px] font-medium text-starlight">{row.animalName}</span>
                          {row.record && (
                            <span
                              className="shrink-0 rounded-sm border border-halo px-1.5 py-0.5 font-mono text-[10px]"
                              style={{ color: din ? "var(--color-static)" : "var(--color-status-warning)" }}
                              title={
                                din
                                  ? "The recording controller's digital input this box's sync line is on"
                                  : "No digital input is bound to this box"
                              }
                            >
                              {din ? `DIN ${din}` : "no DIN"}
                            </span>
                          )}
                          {row.record && !din && (
                            <Button variant="ghost" onClick={() => navigate("/recording")}>
                              Bind one
                            </Button>
                          )}
                          <span className="ml-auto">
                            <Segmented
                              label={`Box ${row.box}: record, or behavior only`}
                              value={row.record ? "record" : "behavior"}
                              options={[
                                { value: "record", label: "Record" },
                                { value: "behavior", label: "Behavior only" },
                              ]}
                              onChange={(v) => patchRow(row.box, { record: v === "record" })}
                            />
                          </span>
                        </div>

                        {row.record && (
                          <div className="mt-3 grid grid-cols-[1fr_200px] gap-4">
                            <div className="flex flex-col gap-2.5">
                              <div className="flex items-center gap-2">
                                <Dropdown
                                  label={`Headstage port for box ${row.box}`}
                                  size="regular"
                                  value={row.port}
                                  options={portOptions}
                                  placeholder={intan.connected && presentPorts.length === 0 ? "no headstage" : "— port —"}
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
                                  <Button
                                    variant="ghost"
                                    shape="icon"
                                    label="Remove the probe map"
                                    title="Remove the probe map"
                                    onClick={() =>
                                      patchRow(row.box, { probeMapPath: null, probeMap: null, probeError: null })
                                    }
                                  >
                                    <X size={13} strokeWidth={1.75} />
                                  </Button>
                                )}
                              </div>
                              {row.probeError && (
                                <p className="text-[11px]" style={{ color: "var(--color-status-error)" }}>
                                  {row.probeError}
                                </p>
                              )}
                            </div>
                            <div className="flex flex-col gap-1">
                              <div className="h-[180px] overflow-hidden rounded-sm border border-halo bg-void/40">
                                {row.probeMap ? (
                                  <ProbeMapView
                                    map={row.probeMap}
                                    channels={channelRange(row.port, row.firstChannel, row.lastChannel)}
                                    className="h-full"
                                  />
                                ) : (
                                  <div className="flex h-full items-center justify-center px-4 text-center text-[11px] leading-relaxed text-static">
                                    Optional — a probe map lights this box's sites live as they fire.
                                  </div>
                                )}
                              </div>
                              {row.probeMap && row.probeMapPath && (
                                <div className="truncate font-mono text-[10px] text-static" title={row.probeMapPath}>
                                  {row.probeMapPath.split(/[\\/]/).pop()} · {row.probeMap.siteCount} sites
                                  {row.probeMap.pages.length > 1 ? ` · ${row.probeMap.pages.length} pages` : ""}
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
                {overlap && (
                  <p className="border-t border-halo px-4 py-2.5 text-[12px]" style={{ color: "var(--color-status-error)" }}>
                    {overlap}.
                  </p>
                )}
              </HudTile>
            </motion.div>

            <motion.div variants={RISE} className="mt-1 flex items-center gap-2">
              <Button
                variant="primary"
                onClick={() => void applyAndContinue()}
                disabled={!ready || busy}
                {...(!ready && firstProblem ? { title: firstProblem } : {})}
              >
                {busy ? "Configuring RHX…" : "Configure RHX and continue"}
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

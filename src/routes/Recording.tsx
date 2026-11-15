import { motion } from "framer-motion";
import { ArrowRight, AudioWaveform, CircleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";

import { PanelTitle } from "@/components/charts/PanelTitle";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { Button } from "@/components/common/controls";
import { IntanConnectionPanel } from "@/components/recording/IntanConnectionPanel";
import { SavingRows, ThresholdRows } from "@/components/recording/RecordingConfigRows";
import { RecChip, RecordingStatus } from "@/components/recording/RecordingStatus";
import { SyncInputsTable } from "@/components/recording/SyncInputsTable";
import { SettingRowDensityContext } from "@/components/settings/SettingRow";
import { useIntanStatus } from "@/lib/intan/context";
import { summarizeRecordingConfig } from "@/lib/intan/defaults";
import { CASCADE, RISE, springPanel } from "@/lib/motion";
import { useRunningSession } from "@/lib/sessions/context";
import { sessionDoor } from "@/lib/sessions/flow";
import { useSettings } from "@/lib/settings/context";
import { useRecordingDefaults } from "@/lib/settings/useRecordingDefaults";

/**
 * Recording — everything about the link to Intan RHX, on one screen
 * (`ARCHITECTURE.md#where-each-setting-is-edited`, `RECORDING.md#recording-tab`).
 *
 * Drawn as a telemetry display (`ARCHITECTURE.md#telemetry-panels`), the same
 * surface Analytics is: a **readout strip** across the top says what RHX is
 * and whether the boxes are wired to it; under it, while a recording exists,
 * the **Live** panel and the way back to Mission Control. Then two columns in
 * the order a recording comes up in — the **link** (Connection, then which of
 * the controller's digital inputs each box's sync line is on) on the left, the
 * **defaults** (what a recording saves, how spikes are detected — what the
 * Record step opens with) on the right. Rows are compact, their explanations
 * one hover away, so the page fits without scrolling.
 */
export function Recording() {
  const { loaded, saveError, settings } = useSettings();
  const intan = useIntanStatus();
  const { defaults, save } = useRecordingDefaults();
  const running = useRunningSession();
  const navigate = useNavigate();

  const wired = settings.boxes.filter((b) => b.intanDigitalIn !== null && b.intanDigitalIn !== undefined).length;
  const boxCount = settings.boxes.length;
  const headstage = Object.entries(intan.ports)
    .filter(([, count]) => count > 0)
    .map(([letter, count]) => `${letter}:${count}`)
    .join(" ");

  const link = intan.connected
    ? { text: "connected", color: "var(--color-ion)" }
    : intan.state === "error"
      ? { text: "problem", color: "var(--color-status-error)" }
      : { text: "not connected", color: "var(--color-static)" };

  return (
    // Every route sits on the rig's sky (`SkyBackdrop`): a route that mounts
    // no constellation is the only thing that releases the shared canvas.
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
        <section className="pointer-events-auto mx-auto max-w-[1280px] px-8 py-8">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
                <AudioWaveform size={18} strokeWidth={1.75} className="text-pulsar" />
              </span>
              <div className="min-w-0">
                <h1 className="font-display text-[22px] text-starlight">Recording</h1>
                <p className="text-[12px] text-static">
                  The link to Intan RHX, which input each box pulses, and what a recording saves.
                </p>
              </div>
            </div>
            {/* The display names itself and shows the link, as Analytics' does. */}
            <div className="flex items-center gap-2 pt-1 font-mono text-[9px] tracking-[0.18em] text-static/70 uppercase">
              <span>Telemetry · Intan RHX</span>
              <span
                aria-hidden
                className={`size-1.5 rounded-full ${intan.connected ? "bg-ion" : "bg-halo"}`}
              />
              <span>{intan.connected ? "link" : "no link"}</span>
            </div>
          </div>

          {saveError && (
            <div
              className="mt-4 flex items-center gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
              style={{ color: "var(--color-status-error)" }}
            >
              <CircleAlert size={14} strokeWidth={1.75} />
              {saveError}
            </div>
          )}

          <SettingRowDensityContext value="compact">
            <fieldset disabled={!loaded} className="contents">
              <motion.div
                variants={CASCADE}
                initial="hidden"
                animate="shown"
                className="mt-6 flex flex-col gap-5"
              >
                <motion.div variants={RISE}>
                  <section className="telemetry grid grid-cols-3 xl:grid-cols-6">
                    <Readout label="Link">
                      <span className="flex items-center gap-1.5" style={{ color: link.color }}>
                        <span aria-hidden className="size-[7px] rounded-full bg-current" />
                        {link.text}
                      </span>
                    </Readout>
                    <Readout label="Controller">
                      {intan.connected ? (intan.controller ?? "—") : "—"}
                      {intan.connected && intan.synthetic && (
                        <span className="ml-1.5 text-[10px] text-static">synthetic</span>
                      )}
                    </Readout>
                    <Readout label="RHX">{intan.connected ? (intan.version ?? "—") : "—"}</Readout>
                    <Readout label="Sample rate">
                      {intan.connected && intan.sampleRate ? `${intan.sampleRate / 1000} kS/s` : "—"}
                    </Readout>
                    <Readout label="Headstage">{intan.connected ? headstage || "none" : "—"}</Readout>
                    <Readout label="Sync">
                      <span
                        style={
                          boxCount > 0 && wired === boxCount ? { color: "var(--color-ion)" } : undefined
                        }
                      >
                        {boxCount === 0 ? "no boxes" : `${wired}/${boxCount} wired`}
                      </span>
                      {!intan.rigHasSync && (
                        <span className="ml-1.5 text-[10px]" style={{ color: "var(--color-status-warning)" }}>
                          no channel
                        </span>
                      )}
                    </Readout>
                  </section>
                </motion.div>

                {intan.recording && (
                  <motion.div variants={RISE}>
                    <Panel name="Live" note={<RecChip state={intan.state} />}>
                      <div className="px-4 py-3">
                        <RecordingStatus />
                      </div>
                      {running && (
                        <div className="border-t border-halo/70 px-4 py-2">
                          <Button
                            variant="ghost"
                            className="w-full justify-between"
                            onClick={() => navigate(sessionDoor(running))}
                          >
                            Open Mission Control
                            <ArrowRight size={13} strokeWidth={2} />
                          </Button>
                        </div>
                      )}
                    </Panel>
                  </motion.div>
                )}

                <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-2">
                  <motion.div variants={RISE} className="flex flex-col gap-3">
                    <h2 className="telemetry-section">Link</h2>
                    <Panel name="Connection" note="the one click in RHX that opens it, and its ports">
                      <IntanConnectionPanel />
                    </Panel>
                    <Panel name="Sync inputs" note="which digital input each box's sync line is on">
                      <SyncInputsTable />
                    </Panel>
                  </motion.div>

                  <motion.div variants={RISE} className="flex flex-col gap-3">
                    <h2 className="telemetry-section">Defaults</h2>
                    <Panel name="Saving" note={summarizeRecordingConfig(defaults.config)}>
                      <SavingRows
                        value={defaults.config}
                        onChange={(patch) => void save({ config: { ...defaults.config, ...patch } })}
                        saveRoot={defaults.saveRoot}
                        onSaveRoot={(saveRoot) => void save({ saveRoot })}
                      />
                    </Panel>
                    <Panel name="Spike thresholds">
                      <ThresholdRows
                        value={defaults.config}
                        onChange={(patch) => void save({ config: { ...defaults.config, ...patch } })}
                      />
                    </Panel>
                    <p className="px-1 text-[11px] leading-relaxed text-static/80">
                      The Record step opens with these, and what you confirm there becomes the new defaults.
                    </p>
                  </motion.div>
                </div>
              </motion.div>
            </fieldset>
          </SettingRowDensityContext>
        </section>
      </motion.div>
    </div>
  );
}

/** One telemetry panel: its name in the display's mono capitals, then rows. */
function Panel({ name, note, children }: { name: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="telemetry">
      <div className="border-b border-halo/70 px-4 py-2.5">
        <PanelTitle name={name} note={note} />
      </div>
      {children}
    </section>
  );
}

/** One cell of the readout strip: a tracked caption over a mono value. */
function Readout({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 border-r border-b border-halo/50 px-4 py-3 last:border-r-0 xl:border-b-0">
      <div className="font-mono text-[9px] tracking-[0.18em] text-static/70 uppercase">{label}</div>
      <div className="mt-1 flex items-baseline truncate font-mono text-[13px] text-starlight tabular-nums">
        {children}
      </div>
    </div>
  );
}

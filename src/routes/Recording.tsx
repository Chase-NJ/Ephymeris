import { motion } from "framer-motion";
import { ArrowRight, AudioWaveform, Cable, CircleAlert, Disc, PlugZap, SlidersHorizontal } from "lucide-react";
import { useNavigate } from "react-router";

import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { HudTile } from "@/components/common/HudTile";
import { Button } from "@/components/common/controls";
import { IntanConnectionPanel } from "@/components/recording/IntanConnectionPanel";
import { SavingRows, ThresholdRows } from "@/components/recording/RecordingConfigRows";
import { RecChip, RecordingStatus } from "@/components/recording/RecordingStatus";
import { SyncInputsTable } from "@/components/recording/SyncInputsTable";
import { useIntanStatus } from "@/lib/intan/context";
import { summarizeRecordingConfig } from "@/lib/intan/defaults";
import { CASCADE, RISE, springPanel } from "@/lib/motion";
import { useRunningSession } from "@/lib/sessions/context";
import { sessionDoor } from "@/lib/sessions/types";
import { useSettings } from "@/lib/settings/context";
import { useRecordingDefaults } from "@/lib/settings/useRecordingDefaults";

/**
 * Recording — everything about the link to Intan RHX, on one screen
 * (`ARCHITECTURE.md#where-each-setting-is-edited`, `RECORDING.md#recording-tab`).
 *
 * The same column of HUD tiles as Rig and Settings, in the order a recording
 * comes up in: **Connection** (is RHX reachable, and the one click in RHX
 * that makes it so), **Sync inputs** (which of the controller's digital
 * inputs each box's sync line is on — a binding, like the board binding on
 * Rig, edited here because its far end is the recording controller), and
 * **Defaults** (what a recording saves and how spikes are detected — the
 * values the Record step opens with). While a recording exists a **Live**
 * tile comes first: what RHX is doing, and the way back to Mission Control.
 */
export function Recording() {
  const { loaded, saveError, settings } = useSettings();
  const intan = useIntanStatus();
  const { defaults, save } = useRecordingDefaults();
  const running = useRunningSession();
  const navigate = useNavigate();

  const wired = settings.boxes.filter((b) => b.intanDigitalIn !== null && b.intanDigitalIn !== undefined).length;
  const boxCount = settings.boxes.length;

  const connectionFact = intan.connected ? (
    <span style={{ color: "var(--color-ion)" }}>
      RHX {intan.version ?? ""} · {intan.sampleRate ? `${intan.sampleRate / 1000} kS/s` : "—"}
      {intan.synthetic ? " · synthetic" : ""}
    </span>
  ) : intan.state === "error" ? (
    <span style={{ color: "var(--color-status-error)" }}>problem</span>
  ) : (
    "not connected"
  );

  const syncFact = (
    <>
      <span style={boxCount > 0 && wired === boxCount ? { color: "var(--color-ion)" } : undefined}>
        {boxCount === 0 ? "no boxes" : `${wired}/${boxCount} boxes wired`}
      </span>
      {!intan.rigHasSync && <span style={{ color: "var(--color-status-warning)" }}>· no sync channel</span>}
    </>
  );

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
        <section className="pointer-events-auto mx-auto max-w-4xl px-10 py-9">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
              <AudioWaveform size={18} strokeWidth={1.75} className="text-pulsar" />
            </span>
            <div className="min-w-0">
              <h1 className="font-display text-[22px] text-starlight">Recording</h1>
              <p className="font-mono text-[10px] text-static/70">
                the link to intan rhx, which input each box pulses, and what a recording saves by default
              </p>
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

          <fieldset disabled={!loaded} className="contents">
            <motion.div
              variants={CASCADE}
              initial="hidden"
              animate="shown"
              className="mt-7 flex flex-col gap-5"
            >
              {intan.recording && (
                <motion.div variants={RISE}>
                  <HudTile icon={Disc} label="Live" status={<RecChip state={intan.state} />}>
                    <div className="px-4 py-3.5">
                      <RecordingStatus />
                    </div>
                    {running && (
                      <div className="border-t border-halo px-4 py-2">
                        <Button
                          variant="ghost"
                          className="w-full justify-between"
                          onClick={() =>
                            navigate(sessionDoor(running))
                          }
                        >
                          Open Mission Control
                          <ArrowRight size={13} strokeWidth={2} />
                        </Button>
                      </div>
                    )}
                  </HudTile>
                </motion.div>
              )}

              <motion.div variants={RISE}>
                <HudTile icon={PlugZap} label="Connection" status={connectionFact}>
                  <IntanConnectionPanel />
                </HudTile>
              </motion.div>

              <motion.div variants={RISE}>
                <HudTile icon={Cable} label="Sync inputs" status={syncFact}>
                  <SyncInputsTable />
                </HudTile>
              </motion.div>

              <motion.div variants={RISE}>
                <HudTile
                  icon={SlidersHorizontal}
                  label="Defaults"
                  status={summarizeRecordingConfig(defaults.config)}
                >
                  <SavingRows
                    value={defaults.config}
                    onChange={(patch) => void save({ config: { ...defaults.config, ...patch } })}
                    saveRoot={defaults.saveRoot}
                    onSaveRoot={(saveRoot) => void save({ saveRoot })}
                  />
                  <div className="border-b border-halo px-4 py-2 text-[11px] font-medium text-static">
                    Spike thresholds
                  </div>
                  <ThresholdRows
                    value={defaults.config}
                    onChange={(patch) => void save({ config: { ...defaults.config, ...patch } })}
                  />
                  <p className="border-t border-halo px-4 py-2.5 text-[11px] leading-relaxed text-static">
                    The Record step opens with these, and what you confirm there becomes the new defaults.
                  </p>
                </HudTile>
              </motion.div>
            </motion.div>
          </fieldset>
        </section>
      </motion.div>
    </div>
  );
}

import { motion } from "framer-motion";
import { CircleAlert, Radio, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { useBoxHealth } from "@/components/chrome/ConstellationStatus";
import { Button, Select, TextInput } from "@/components/common/controls";
import { ConstellationBoard } from "@/components/config/ConstellationBoard";
import { ConstellationPicker } from "@/components/config/ConstellationPicker";
import { HandshakeList } from "@/components/config/HandshakeList";
import { SetupWizard } from "@/components/config/SetupWizard";
import { UtilitySketchPanel } from "@/components/config/UtilitySketchPanel";
import { BoxBindingsTable } from "@/components/settings/BoxBindingsTable";
import { DirectoryField } from "@/components/settings/DirectoryField";
import { DirectoryStatusNote } from "@/components/settings/DirectoryStatusNote";
import { SettingGroup, SettingRow } from "@/components/settings/SettingRow";
import { reconcileSlots } from "@/lib/constellations/slots";
import { zodiacById } from "@/lib/constellations/zodiac";
import { useUtilityStatus } from "@/lib/hardware/context";
import { useHandshakeTest } from "@/lib/hardware/useHandshakeTest";
import { springPanel } from "@/lib/motion";
import { useSettings } from "@/lib/settings/context";
import { BAUD_RATES, type BoxBinding } from "@/lib/settings/schema";
import { CMD } from "@/lib/ws/protocol";
import { useSidecar } from "@/lib/ws/context";

/**
 * Config — everything box-related in one place (ephymeris_v1.0.md §4.6).
 *
 * Hardware config moved here from Settings: box→board bindings, the zodiac
 * constellation layout, the handshake test, default baud, the Arduino
 * Directory, and the arduino-cli path. Settings keeps storage and interface.
 *
 * First visit runs the setup wizard, gated on the persisted
 * `boxSetupComplete` flag — and on `loaded`, because before the store loads
 * every flag reads false and the wizard would flash for everyone.
 */
export function Config() {
  const { settings, update, discovery, refreshSketches, loaded, saveError } = useSettings();
  const { client, status } = useSidecar();
  const health = useBoxHealth();
  const handshake = useHandshakeTest();
  const utility = useUtilityStatus();
  const [wizardOpen, setWizardOpen] = useState(false);
  const [reflashing, setReflashing] = useState(false);
  const connected = status === "connected";

  const bound = useMemo(
    () => settings.boxes.filter((b) => b.hardwareId !== null),
    [settings.boxes],
  );
  const boundNumbers = useMemo(() => bound.map((b) => b.box), [bound]);
  const labels = useMemo(
    () => Object.fromEntries(settings.boxes.map((b) => [b.box, b.label])),
    [settings.boxes],
  );
  const chosen = zodiacById(settings.constellation);

  if (!loaded) return null;
  if (!settings.boxSetupComplete || wizardOpen) {
    return <SetupWizard onExit={() => setWizardOpen(false)} />;
  }

  /** Box edits keep the slot map honest in the same settings write. */
  function onBoxesChange(boxes: BoxBinding[]) {
    const nextBound = boxes.filter((b) => b.hardwareId !== null).map((b) => b.box);
    const constellation = zodiacById(settings.constellation);
    void update(
      constellation
        ? {
            boxes,
            constellationSlots: reconcileSlots(
              constellation,
              settings.constellationSlots,
              nextBound,
            ),
          }
        : { boxes },
    );
  }

  /**
   * The one manual restore. `force` is what makes it useful: the automatic
   * paths skip a box already believed to be at baseline, and the reason to
   * press this is usually that the belief is wrong.
   */
  async function reflashBaseline() {
    setReflashing(true);
    try {
      await client.call(CMD.UTILITY_ENSURE, { force: true });
    } catch (err) {
      console.error("utility baseline reflash failed", err);
    } finally {
      setReflashing(false);
    }
  }

  function onPickConstellation(id: string) {
    const constellation = zodiacById(id);
    if (!constellation) return;
    void update({
      constellation: id,
      constellationSlots: reconcileSlots(
        constellation,
        settings.constellationSlots,
        boundNumbers,
      ),
    });
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="mx-auto max-w-3xl px-10 py-9"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
            <Radio size={18} strokeWidth={1.75} className="text-pulsar" />
          </span>
          <h1 className="font-display text-[22px] text-starlight">Config</h1>
        </div>
        <Button variant="ghost" onClick={() => setWizardOpen(true)}>
          <RefreshCw size={13} strokeWidth={1.75} />
          Run setup again
        </Button>
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
        <SettingGroup title="Constellation">
          <div className="px-4 py-3.5">
            {chosen ? (
              <>
                <div className="mx-auto max-w-[460px]">
                  <ConstellationBoard
                    constellation={chosen}
                    slots={settings.constellationSlots}
                    boxes={boundNumbers}
                    labels={labels}
                    health={health}
                    onSlotsChange={(constellationSlots) => void update({ constellationSlots })}
                  />
                </div>
                <p className="mt-1 text-center text-[11px] text-static">
                  {chosen.name} — drag a box to a different star to rearrange.
                </p>
              </>
            ) : (
              <p className="pb-2 text-[12px] leading-relaxed text-static">
                No constellation chosen yet — the status display uses the plain
                layout. Pick one below.
              </p>
            )}
            <div className="mt-3">
              <ConstellationPicker
                selected={settings.constellation}
                boxCount={boundNumbers.length}
                onSelect={onPickConstellation}
              />
            </div>
          </div>
        </SettingGroup>

        <SettingGroup title="Boxes">
          <BoxBindingsTable boxes={settings.boxes} onChange={onBoxesChange} />
          <div className="border-t border-halo px-4 py-3.5">
            <div className="pb-2 text-[13px] font-medium text-starlight">Handshake test</div>
            <HandshakeList bound={bound} handshake={handshake} connected={connected} />
          </div>
        </SettingGroup>

        <SettingGroup title="Hardware">
          <div className="border-b border-halo px-4 py-3.5">
            <div className="flex items-start justify-between gap-8">
              <div className="min-w-0 pt-0.5">
                <div className="text-[13px] font-medium text-starlight">Arduino Directory</div>
                <p className="mt-0.5 text-[12px] leading-relaxed text-static">
                  Root folder holding your sketch categories and a shared{" "}
                  <code className="font-mono">libraries/</code> folder. Each machine
                  configures its own.
                </p>
              </div>
              <DirectoryField
                value={settings.arduinoDirectory}
                onChange={(next) => void update({ arduinoDirectory: next })}
                title="Choose the Arduino Directory"
              />
            </div>
            <DirectoryStatusNote
              discovery={discovery}
              onRefresh={() => void refreshSketches()}
              canRefresh={connected}
            />
          </div>

          <UtilitySketchPanel
            sketches={discovery.sketches}
            boxes={settings.boxes}
            value={settings.utilitySketchPath}
            status={utility}
            busy={reflashing}
            connected={connected}
            onChange={(utilitySketchPath) => void update({ utilitySketchPath })}
            onReflash={() => void reflashBaseline()}
          />

          <SettingRow
            label="Default baud rate"
            description="Starting value for each console. Debug Mode allows a per-box override."
          >
            <Select
              label="Default baud rate"
              value={settings.defaultBaud}
              options={BAUD_RATES.map((b) => ({ value: b, label: String(b) }))}
              onChange={(defaultBaud) => void update({ defaultBaud })}
            />
          </SettingRow>

          <SettingRow
            label="arduino-cli path"
            description="Leave empty to use the bundled binary. Override only if you need a specific install."
          >
            <TextInput
              label="arduino-cli path override"
              mono
              value={settings.arduinoCliPath ?? ""}
              placeholder="bundled"
              onChange={(v) => void update({ arduinoCliPath: v.trim() === "" ? null : v })}
              className="w-[280px]"
            />
          </SettingRow>
        </SettingGroup>
      </fieldset>

      <p className="mt-6 px-1 text-[11px] leading-relaxed text-static/70">
        Hardware settings are stored by the app shell and pushed to the backend
        whenever they change, so this screen keeps working even when the backend
        doesn&rsquo;t. Only the handshake test and directory scan need it.
      </p>
    </motion.section>
  );
}

import { motion } from "framer-motion";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { CircleAlert, Settings as SettingsIcon } from "lucide-react";
import { useMemo } from "react";

import { useBoxHealth } from "@/components/chrome/ConstellationStatus";
import { Toggle } from "@/components/common/controls";
import { ConstellationBoard } from "@/components/config/ConstellationBoard";
import { ConstellationPicker } from "@/components/config/ConstellationPicker";
import { BackupStatusNote } from "@/components/settings/BackupStatusNote";
import { DirectoryField } from "@/components/settings/DirectoryField";
import { SettingGroup, SettingRow } from "@/components/settings/SettingRow";
import { useBackupStatus } from "@/lib/backup/useBackupStatus";
import { reconcileSlots } from "@/lib/constellations/slots";
import { zodiacById } from "@/lib/constellations/zodiac";
import { springPanel } from "@/lib/motion";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";

/**
 * Settings (settings.md §4) — storage and interface.
 *
 * Everything hardware-shaped (boxes, baud, arduino-cli, wiring)
 * lives on the Rig tab (§4.6); this screen is what's left. Deliberately usable
 * while the sidecar is down — that's the whole reason settings are
 * shell-owned. Nothing here is gated on the WebSocket; only the backup
 * readout goes quiet.
 *
 * **The constellation moved here from the Rig screen**, and the move is the
 * argument: which zodiac the status display draws, and which star a box sits
 * on, style how the rig is *shown* — the sidebar widget and the Dashboard sky —
 * and never touch how it is wired. Interface, filed under Interface. The slot
 * map still follows box add/remove automatically (`Config.onBoxesChange`
 * reconciles it), so this section can be ignored forever and stay honest.
 */
export function Settings() {
  const { settings, update, loaded, saveError } = useSettings();
  const { status } = useSidecar();
  const backup = useBackupStatus();
  const health = useBoxHealth();
  const connected = status === "connected";

  const boundNumbers = useMemo(
    () =>
      settings.boxes.filter((b) => b.hardwareId !== null).map((b) => b.box),
    [settings.boxes],
  );
  const labels = useMemo(
    () => Object.fromEntries(settings.boxes.map((b) => [b.box, b.label])),
    [settings.boxes],
  );
  const chosen = zodiacById(settings.constellation);

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
    // Every route sits on the rig's sky. Not decoration: a route that mounts no
    // constellation is the only thing that releases the shared canvas, and that
    // teardown is what made a sidebar round trip snap (`SkyBackdrop`).
    <div className="relative h-full">
      <SkyBackdrop />

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        // Owns its own exit: the shell holds every page opaque on the way out
        // now, so anything that should fade has to say so (`AppShell`).
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        <section className="pointer-events-auto mx-auto max-w-3xl px-10 py-9">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
              <SettingsIcon
                size={18}
                strokeWidth={1.75}
                className="text-pulsar"
              />
            </span>
            <h1 className="font-display text-[22px] text-starlight">
              Settings
            </h1>
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
            <SettingGroup title="Storage">
              <SettingRow
                label="Data directory"
                description="Where session data is written."
              >
                <DirectoryField
                  value={settings.dataDirectory}
                  onChange={(next) => void update({ dataDirectory: next })}
                  title="Choose the data directory"
                />
              </SettingRow>

              <div className="px-4 py-3.5">
                <div className="flex items-start justify-between gap-8">
                  <div className="min-w-0 pt-0.5">
                    <div className="text-[13px] font-medium text-starlight">
                      Backup directory
                    </div>
                    <p className="mt-0.5 text-[12px] leading-relaxed text-static">
                      A second copy of session files and the cohort database, on
                      a different drive or share. Setting one doesn't copy
                      what's already on disk — use the refresh button for that.
                    </p>
                  </div>
                  <DirectoryField
                    value={settings.backupDirectory}
                    onChange={(next) => void update({ backupDirectory: next })}
                    title="Choose the backup directory"
                  />
                </div>
                <BackupStatusNote
                  status={backup.status}
                  onSync={() => void backup.syncNow()}
                  canSync={connected}
                  syncError={backup.syncError}
                  lastSync={backup.lastSync}
                />
              </div>
            </SettingGroup>

            <SettingGroup title="Interface">
              <SettingRow
                label="Reduce motion"
                description="Stops the ambient starfield and shortens transitions. Your system setting is always respected; this forces it on regardless."
              >
                <Toggle
                  label="Reduce motion"
                  checked={settings.reducedMotion}
                  onChange={(reducedMotion) => void update({ reducedMotion })}
                />
              </SettingRow>
            </SettingGroup>

            <SettingGroup title="Constellation">
              <div className="px-4 py-3.5">
                <p className="pb-2 text-[12px] leading-relaxed text-static">
                  How the status display draws your boxes — the widget at the
                  foot of the sidebar and the Dashboard&rsquo;s sky. Pure
                  presentation: nothing here changes how the rig is wired.
                </p>
                {chosen ? (
                  <>
                    <div className="mx-auto max-w-[460px]">
                      <ConstellationBoard
                        constellation={chosen}
                        slots={settings.constellationSlots}
                        boxes={boundNumbers}
                        labels={labels}
                        health={health}
                        onSlotsChange={(constellationSlots) =>
                          void update({ constellationSlots })
                        }
                      />
                    </div>
                    <p className="mt-1 text-center text-[11px] text-static">
                      {chosen.name} — drag a box to a different star to
                      rearrange.
                    </p>
                  </>
                ) : (
                  <p className="pb-2 text-[12px] leading-relaxed text-static">
                    No constellation chosen yet — the status display uses the
                    plain layout. Pick one below.
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
          </fieldset>

          <p className="mt-6 px-1 text-[11px] leading-relaxed text-static/70">
            Settings are stored by the app shell and pushed to the backend
            whenever they change, so this screen keeps working even when the
            backend doesn't.
          </p>
        </section>
      </motion.div>
    </div>
  );
}

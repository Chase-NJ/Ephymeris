import { motion } from "framer-motion";
import { CircleAlert, Settings as SettingsIcon } from "lucide-react";

import { Toggle } from "@/components/common/controls";
import { BackupStatusNote } from "@/components/settings/BackupStatusNote";
import { DirectoryField } from "@/components/settings/DirectoryField";
import { SettingGroup, SettingRow } from "@/components/settings/SettingRow";
import { useBackupStatus } from "@/lib/backup/useBackupStatus";
import { springPanel } from "@/lib/motion";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";

/**
 * Settings (ephymeris_v1.0.md §4.5) — storage and interface.
 *
 * Everything hardware-shaped (boxes, baud, Arduino Directory, arduino-cli)
 * lives in Config (§4.6); this screen is what's left. Deliberately usable
 * while the sidecar is down — that's the whole reason settings are
 * shell-owned. Nothing here is gated on the WebSocket; only the backup
 * readout goes quiet.
 */
export function Settings() {
  const { settings, update, loaded, saveError } = useSettings();
  const { status } = useSidecar();
  const backup = useBackupStatus();
  const connected = status === "connected";

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="mx-auto max-w-3xl px-10 py-9"
    >
      <div className="flex items-center gap-3">
        <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
          <SettingsIcon size={18} strokeWidth={1.75} className="text-pulsar" />
        </span>
        <h1 className="font-display text-[22px] text-starlight">Settings</h1>
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
                  A second copy of session files and the cohort database, on a
                  different drive or share. Setting one doesn't copy what's
                  already on disk — use the refresh button for that.
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
      </fieldset>

      <p className="mt-6 px-1 text-[11px] leading-relaxed text-static/70">
        Settings are stored by the app shell and pushed to the backend whenever
        they change, so this screen keeps working even when the backend doesn't.
      </p>
    </motion.section>
  );
}

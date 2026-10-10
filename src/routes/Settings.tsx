import { motion } from "framer-motion";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { CircleAlert, HardDrive, MonitorCog, Settings as SettingsIcon } from "lucide-react";

import { Toggle } from "@/components/common/controls";
import { HudTile } from "@/components/common/HudTile";
import { BackupStatusNote } from "@/components/settings/BackupStatusNote";
import { DirectoryField } from "@/components/settings/DirectoryField";
import { SettingRow } from "@/components/settings/SettingRow";
import { UpdatesTile } from "@/components/settings/UpdatesTile";
import { useBackupStatus, type BackupStatus } from "@/lib/backup/useBackupStatus";
import { CASCADE, RISE, springPanel } from "@/lib/motion";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";

/**
 * Settings (`ARCHITECTURE.md#where-each-setting-is-edited`) — storage and interface.
 *
 * Everything hardware-shaped (boxes, baud, arduino-cli, wiring)
 * lives on the Rig tab; this screen is what's left. Deliberately usable
 * while the sidecar is down — that's the whole reason settings are
 * shell-owned. Nothing here is gated on the WebSocket; only the backup
 * readout goes quiet.
 *
 * **A column of HUD tiles, in the Rig tab's idiom.** Each subject is a tile
 * with an icon header and one live fact on the glass — and the fact is the
 * point: the Storage tile's corner says whether the mirror is alive before
 * the row that configures it is read. `SettingGroup`'s title
 * used to sit above its card and read as a document heading; a settings
 * screen that is one of five glass pages over the sky should look like the
 * other four.
 *
 * The constellation lives on the Rig tab, beside the boxes it draws
 * (`components/config/ConstellationTile.tsx`).
 */
export function Settings() {
  const { settings, update, loaded, saveError } = useSettings();
  const { status } = useSidecar();
  const backup = useBackupStatus();
  const connected = status === "connected";

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
        {/* A step wider than the old form (max-w-3xl): a directory row is a
            description beside a path, and at 3xl the path field wrapped under
            its own label on any real Windows path. */}
        <section className="pointer-events-auto mx-auto max-w-4xl px-10 py-9">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
              <SettingsIcon
                size={18}
                strokeWidth={1.75}
                className="text-pulsar"
              />
            </span>
            <div className="min-w-0">
              <h1 className="font-display text-[22px] text-starlight">
                Settings
              </h1>
              <p className="font-mono text-[10px] text-static/70">
                where the data lands, where its copy goes, and how the app
                moves
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
            {/* The tiles arrive as a cascade, top-down — the Rig and Task tabs'
                entrance, for the same reason: a page assembling beats a page
                slamming in as one frame. */}
            <motion.div
              variants={CASCADE}
              initial="hidden"
              animate="shown"
              className="mt-7 flex flex-col gap-5"
            >
              <motion.div variants={RISE}>
                <HudTile
                  icon={HardDrive}
                  label="Storage"
                  status={
                    <StorageFact
                      dataDirectory={settings.dataDirectory}
                      backup={backup.status}
                      syncError={backup.syncError}
                    />
                  }
                >
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
                          A second copy of session files and the cohort
                          database, on a different drive or share. Setting one
                          doesn&rsquo;t copy what&rsquo;s already on disk — use
                          the refresh button for that.
                        </p>
                      </div>
                      <DirectoryField
                        value={settings.backupDirectory}
                        onChange={(next) =>
                          void update({ backupDirectory: next })
                        }
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
                </HudTile>
              </motion.div>

              <motion.div variants={RISE}>
                <HudTile
                  icon={MonitorCog}
                  label="Interface"
                  status={
                    <span
                      className={
                        settings.reducedMotion ? "text-starlight" : undefined
                      }
                    >
                      {settings.reducedMotion ? "motion reduced" : "full motion"}
                    </span>
                  }
                >
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
                </HudTile>
              </motion.div>

              <motion.div variants={RISE}>
                <UpdatesTile />
              </motion.div>
            </motion.div>
          </fieldset>

          <p className="mt-6 px-1 font-mono text-[10px] leading-relaxed text-static/70">
            settings are stored by the app shell and pushed to the backend
            whenever they change — this screen keeps working when the backend
            doesn&rsquo;t
          </p>
        </section>
      </motion.div>
    </div>
  );
}

/**
 * The Storage tile's fact: is the data safe, in one phrase, coloured by the
 * answer.
 *
 * Ordered by what would hurt most. No data directory means nothing is being
 * written anywhere and takes the error tone outright; a failing mirror is the
 * next worst thing (`DATA.md#backup-mirroring` — a backup that silently stopped is a promise
 * the app isn't keeping); a live mirror earns Ion; no mirror at all is quiet
 * static, because it is a choice rather than a fault. Same tones
 * `BackupStatusNote` uses in the row below, so the corner and the row can
 * never disagree.
 */
function StorageFact({
  dataDirectory,
  backup,
  syncError,
}: {
  dataDirectory: string | null;
  backup: BackupStatus;
  syncError: string | null;
}) {
  if (!dataDirectory) {
    return (
      <span style={{ color: "var(--color-status-error)" }}>
        no data directory
      </span>
    );
  }
  if (!backup.configured) return <span>no backup</span>;
  if (backup.state === "failed" || syncError) {
    return (
      <span style={{ color: "var(--color-status-error)" }}>
        backup failing
      </span>
    );
  }
  if (backup.syncing) return <span className="text-starlight">syncing…</span>;
  if (backup.state === "pending") {
    return (
      <span style={{ color: "var(--color-status-warning)" }}>
        first mirror pass pending
      </span>
    );
  }
  return (
    <span style={{ color: "var(--color-status-ok)" }}>
      mirroring every {Math.round(backup.intervalSeconds)}s
    </span>
  );
}

import { useEffect, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { CloudDownload } from "lucide-react";

import { Button } from "@/components/common/controls";
import { HudTile } from "@/components/common/HudTile";
import { Modal } from "@/components/common/Modal";
import { SettingRow } from "@/components/settings/SettingRow";
import { useAllPortStatuses } from "@/lib/hardware/context";
import { useIntanStatus } from "@/lib/intan/context";
import { useActiveLoaded, useRunningSession } from "@/lib/sessions/context";
import { installBlocker } from "@/lib/updates/blocker";
import {
  checkForUpdate,
  installUpdate,
  useUpdate,
  type UpdatePhase,
} from "@/lib/updates/store";
import { useSidecar } from "@/lib/ws/context";

/**
 * Settings' Updates tile (`ARCHITECTURE.md#updates`): this copy's version,
 * whether a newer one is published, and the button that installs it.
 *
 * Installing closes the app, so the button waits for whatever the sidecar
 * reports as in progress and says what it is waiting for, rather than
 * greying out without a reason.
 */
export function UpdatesTile() {
  const update = useUpdate();
  const version = useAppVersion();
  const blocker = useInstallBlocker();
  const [confirming, setConfirming] = useState(false);

  return (
    <HudTile icon={CloudDownload} label="Updates" status={<UpdateFact phase={update} />}>
      <SettingRow label="Version" description="The version of Ephymeris running now.">
        <span className="font-mono text-[12px] text-starlight">{version ?? "—"}</span>
      </SettingRow>

      {update.kind === "unsupported" ? (
        <SettingRow
          label="Automatic updates"
          description="Only an installed copy updates itself. This is a development build."
        >
          <span className="font-mono text-[11px] text-static">off</span>
        </SettingRow>
      ) : update.kind === "available" ? (
        <SettingRow
          label={`Ephymeris ${update.info.version}`}
          description={`${published(update.info.date)}Installing closes Ephymeris, runs the installer, and opens the new version. Your data, settings and saved tasks stay where they are.`}
        >
          <div className="flex max-w-[260px] flex-col items-end gap-1.5">
            <Button variant="primary" disabled={blocker !== null} onClick={() => setConfirming(true)}>
              Install and restart
            </Button>
            {blocker && (
              <span
                className="text-right text-[11px] leading-snug"
                style={{ color: "var(--color-status-warning)" }}
              >
                {blocker}
              </span>
            )}
          </div>
        </SettingRow>
      ) : update.kind === "downloading" || update.kind === "installing" ? (
        <SettingRow
          label={`Ephymeris ${update.info.version}`}
          description="Ephymeris will close and reopen on its own. Leave it to finish."
        >
          <span className="font-mono text-[11px] text-starlight">
            {update.kind === "installing" ? "closing to install…" : downloadText(update)}
          </span>
        </SettingRow>
      ) : (
        <SettingRow
          label="Check for updates"
          description={failureText(update) ?? "Ephymeris looks for a newer version when it starts and every few hours while it runs."}
        >
          <Button
            variant="secondary"
            disabled={update.kind === "checking"}
            onClick={() => void checkForUpdate()}
          >
            {update.kind === "checking" ? "Checking…" : "Check now"}
          </Button>
        </SettingRow>
      )}

      <Modal
        open={confirming && update.kind === "available"}
        onClose={() => setConfirming(false)}
        title="Install the update now?"
      >
        <div className="px-5 py-4">
          <p className="text-[13px] leading-relaxed text-static">
            Ephymeris will download{" "}
            {update.kind === "available" ? `version ${update.info.version}` : "the update"}, close,
            and run its installer. It reopens on its own when the installer finishes, usually
            within a minute. Nothing is recorded while it is closed.
          </p>
          <div className="mt-4 flex gap-2">
            <Button
              variant="primary"
              disabled={blocker !== null}
              onClick={() => {
                setConfirming(false);
                void installUpdate();
              }}
            >
              Install and restart
            </Button>
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Not now
            </Button>
          </div>
        </div>
      </Modal>
    </HudTile>
  );
}

/** The header's one fact, coloured by whether it asks for anything. */
function UpdateFact({ phase }: { phase: UpdatePhase }) {
  switch (phase.kind) {
    case "unsupported":
      return <span>dev build</span>;
    case "checking":
      return <span>checking…</span>;
    case "current":
      return <span>up to date</span>;
    case "available":
      return <span className="text-starlight">{phase.info.version} available</span>;
    case "downloading":
    case "installing":
      return <span className="text-starlight">installing {phase.info.version}</span>;
    case "failed":
      return (
        <span style={{ color: "var(--color-status-warning)" }}>
          {phase.info ? "install failed" : "couldn't check"}
        </span>
      );
  }
}

function useInstallBlocker(): string | null {
  const { status } = useSidecar();
  return installBlocker({
    connection: status,
    activeLoaded: useActiveLoaded(),
    sessionRunning: useRunningSession() !== null,
    recording: ["recording", "stopping"].includes(useIntanStatus().state),
    ports: useAllPortStatuses(),
  });
}

function useAppVersion(): string | null {
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    // Rejects in a plain-browser preview, which has no shell to ask.
    getVersion().then(setVersion, () => setVersion(null));
  }, []);
  return version;
}

function failureText(phase: UpdatePhase): string | null {
  if (phase.kind !== "failed") return null;
  if (phase.info) {
    // The download and its signature check come before the sidecar stops, so
    // a failure there leaves everything running; one after it does not.
    return `Installing ${phase.info.version} failed: ${phase.error}. If the backend is down, restart Ephymeris, then try again.`;
  }
  return `The last check didn't finish: ${phase.error}. A lab PC without internet access never finds updates; install a new version by hand instead.`;
}

function published(date: string | null): string {
  if (!date) return "";
  const when = new Date(date);
  if (Number.isNaN(when.getTime())) return "";
  return `Published ${when.toLocaleDateString(undefined, { dateStyle: "medium" })}. `;
}

function downloadText(phase: Extract<UpdatePhase, { kind: "downloading" }>): string {
  const mb = (bytes: number) => `${Math.round(bytes / 1024 / 1024)} MB`;
  return phase.total
    ? `downloading ${mb(phase.downloaded)} of ${mb(phase.total)}`
    : `downloading ${mb(phase.downloaded)}`;
}

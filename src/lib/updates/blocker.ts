import type { ConnectionStatus } from "@/lib/ws/client";
import { BOX_IDS, type PortStatus } from "@/lib/hardware/store";

/**
 * Why an update can't be installed right now, or null when it can
 * (`ARCHITECTURE.md#updates`).
 *
 * Installing closes the app and its sidecar, so it waits for everything the
 * sidecar reports as in progress: a session, a recording, and any box that
 * isn't idle (a flash or reset mid-way, a Debug console holding the port).
 * The frontend decides only from what the sidecar reported — it never guesses
 * at a state it hasn't been told.
 *
 * A sidecar that is **down** holds nothing, so it blocks nothing: a release
 * whose sidecar won't start must still be able to update itself out of it.
 */
export interface InstallContext {
  connection: ConnectionStatus;
  /** The sidecar has answered `sessions.active` since connecting. */
  activeLoaded: boolean;
  sessionRunning: boolean;
  recording: boolean;
  ports: Readonly<Record<number, PortStatus | undefined>>;
}

const BUSY: Partial<Record<PortStatus["state"], string>> = {
  PASSTHROUGH: "open in Debug",
  FLASHING: "flashing",
  RESETTING: "resetting",
  IN_SESSION: "in a session",
};

export function installBlocker(ctx: InstallContext): string | null {
  if (ctx.connection === "down") return null;
  if (ctx.connection !== "connected" || !ctx.activeLoaded) {
    return "Waiting for the backend to report what is running.";
  }
  if (ctx.sessionRunning) return "A session is running. Install once it has ended.";
  if (ctx.recording) return "A recording is in progress. Install once it has stopped.";
  for (const box of BOX_IDS) {
    const state = ctx.ports[box]?.state;
    const doing = state ? BUSY[state] : undefined;
    if (doing) return `Box ${box} is ${doing}. Install once it is idle.`;
  }
  return null;
}

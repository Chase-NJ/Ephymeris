import { describe, expect, it } from "vitest";

import type { PortStatus } from "@/lib/hardware/store";
import { installBlocker, type InstallContext } from "./blocker";

const idle: PortStatus = { state: "IDLE", prev: "IDLE", reason: "" };

function ctx(over: Partial<InstallContext> = {}): InstallContext {
  return {
    connection: "connected",
    activeLoaded: true,
    sessionRunning: false,
    recording: false,
    ports: { 1: idle, 2: idle, 3: idle, 4: idle, 5: idle, 6: idle },
    ...over,
  };
}

describe("installBlocker", () => {
  it("allows an install when nothing is happening", () => {
    expect(installBlocker(ctx())).toBeNull();
  });

  it("waits for a running session or recording", () => {
    expect(installBlocker(ctx({ sessionRunning: true }))).toMatch(/session is running/);
    expect(installBlocker(ctx({ recording: true }))).toMatch(/recording/);
  });

  it("names the first box that isn't idle", () => {
    const ports = { ...ctx().ports, 3: { ...idle, state: "FLASHING" as const } };
    expect(installBlocker(ctx({ ports }))).toBe("Box 3 is flashing. Install once it is idle.");
  });

  it("treats a box in ERROR as holding nothing", () => {
    const ports = { ...ctx().ports, 2: { ...idle, state: "ERROR" as const } };
    expect(installBlocker(ctx({ ports }))).toBeNull();
  });

  it("does not guess before the sidecar has reported", () => {
    expect(installBlocker(ctx({ connection: "reconnecting" }))).toMatch(/Waiting/);
    expect(installBlocker(ctx({ activeLoaded: false }))).toMatch(/Waiting/);
  });

  it("lets a dead sidecar's app update itself", () => {
    // Even with stale reports of a session: a sidecar that is down holds nothing.
    expect(installBlocker(ctx({ connection: "down", sessionRunning: true }))).toBeNull();
  });
});

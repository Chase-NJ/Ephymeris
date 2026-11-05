import { describe, expect, it } from "vitest";

import type { BackupState, BackupStatus } from "@/lib/ws/protocol";

import { backupPill, backupTone } from "./report";

const status = (state: BackupState, lastError: string | null = null): BackupStatus => ({
  configured: true,
  directory: "/mnt/backup",
  state,
  pending: 0,
  tracking: 0,
  mirroredFiles: 0,
  lastSuccessAt: null,
  lastError,
  syncing: false,
  intervalSeconds: 10,
});

describe("backupTone", () => {
  // A database copy deferred behind an open write is owed, not a fault of the
  // target: it must never take the error tone a dead share does.
  it("warns, rather than errs, on a deferred database copy", () => {
    expect(backupTone(status("deferred"), null)).toBe("warning");
  });

  it("errs on a real failure", () => {
    expect(backupTone(status("failed", "a.json: denied"), null)).toBe("error");
  });

  it("errs on a sync the sidecar refused, whatever the state", () => {
    expect(backupTone(status("deferred"), "A sync is already running.")).toBe("error");
  });

  it.each([
    ["ok", "ok"],
    ["pending", "warning"],
    ["disabled", "neutral"],
  ] as const)("reads %s as %s", (state, tone) => {
    expect(backupTone(status(state), null)).toBe(tone);
  });
});

describe("backupPill", () => {
  it("says deferred, in the warning tone, for a deferred copy", () => {
    expect(backupPill(status("deferred"))).toMatchObject({
      text: "backup deferred",
      tone: "warning",
    });
  });

  it("says failing, with the sidecar's error, for a real failure", () => {
    expect(backupPill(status("failed", "a.json: denied"))).toEqual({
      text: "backup failing",
      tone: "error",
      title: "a.json: denied",
    });
  });

  it("stays quiet while healthy", () => {
    expect(backupPill(status("ok"))).toMatchObject({ text: "backup ok", tone: "neutral" });
  });
});

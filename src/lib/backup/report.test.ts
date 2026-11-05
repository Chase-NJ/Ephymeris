import { describe, expect, it } from "vitest";

import { ERR, SidecarCommandError, type BackupState, type BackupStatus } from "@/lib/ws/protocol";

import { backupPhrase, backupPill, backupTone, syncErrorFrom } from "./report";

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

const refused = syncErrorFrom(
  new SidecarCommandError({
    code: ERR.BACKUP_UNAVAILABLE,
    message: "A sync is already running.",
    detail: null,
  }),
);
const failedSync = syncErrorFrom(new Error("command timed out: backup.syncNow"));

describe("syncErrorFrom", () => {
  it("reads BACKUP_UNAVAILABLE as a refusal", () => {
    expect(refused).toEqual({ message: "A sync is already running.", refused: true });
  });

  it("reads any other error as a failed sync", () => {
    expect(failedSync.refused).toBe(false);
    const internal = new SidecarCommandError({ code: ERR.INTERNAL, message: "boom", detail: null });
    expect(syncErrorFrom(internal).refused).toBe(false);
  });
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

  it("errs on a sync that failed, whatever the state", () => {
    expect(backupTone(status("deferred"), failedSync)).toBe("error");
  });

  // A refused command says nothing about the target (`DATA.md#failures`).
  it.each([
    ["ok", "ok"],
    ["deferred", "warning"],
    ["failed", "error"],
  ] as const)("keeps %s's tone through a refused sync", (state, tone) => {
    expect(backupTone(status(state), refused)).toBe(tone);
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

  // A freshly set, unreachable directory must not read as healthy before its
  // first pass (`BackupState`'s doc in protocol/schema.py).
  it("warns, rather than says ok, before the first pass", () => {
    expect(backupPill(status("pending"))).toEqual({
      text: "backup pending",
      tone: "warning",
      title: "Waiting for the first mirror pass to /mnt/backup",
    });
  });

  it("stays quiet while healthy", () => {
    expect(backupPill(status("ok"))).toMatchObject({ text: "backup ok", tone: "neutral" });
  });
});

describe("backupPhrase", () => {
  it("names a deferred database copy, not a failing backup", () => {
    expect(backupPhrase(status("deferred"), null)).toBe("database copy deferred");
  });

  it("says failing on a real failure", () => {
    expect(backupPhrase(status("failed", "a.json: denied"), null)).toBe("backup failing");
  });

  it("states the cadence while healthy", () => {
    expect(backupPhrase(status("ok"), null)).toBe("mirroring every 10s");
  });

  it("says failing on a sync that failed", () => {
    expect(backupPhrase(status("ok"), failedSync)).toBe("backup failing");
  });

  it("keeps a healthy mirror's phrase through a refused sync", () => {
    expect(backupPhrase(status("ok"), refused)).toBe("mirroring every 10s");
  });
});

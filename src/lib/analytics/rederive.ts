/**
 * The note Re-derive leaves in the Analytics header (`DATA.md#re-derive`).
 */

import type { RederiveResult } from "./types";

/**
 * What a Re-derive did, in one line. Failures are named per file, as
 * Recover's are: "1 failed" with no path would send the operator to the log.
 */
export function describeRederive(result: RederiveResult): string {
  if (result.folderMissing) {
    return `Can't reach ${result.dataFolder} — nothing was re-derived. Reconnect the drive, or change this cohort's data folder.`;
  }
  if (result.scanned === 0) {
    return "No spine runs in this cohort — nothing to re-derive.";
  }
  const runs = (n: number) => `${n} spine run${n === 1 ? "" : "s"}`;
  const parts = [
    result.rewritten === 0
      ? `Every trial table is current (${runs(result.scanned)})`
      : `Rewrote the trial table of ${result.rewritten} of ${runs(result.scanned)}`,
  ];
  for (const entry of result.entries) {
    if (entry.status === "failed") {
      parts.push(`${entry.jsonPath}: ${entry.reason ?? "failed"}`);
    }
  }
  return `${parts.join("; ")}.`;
}

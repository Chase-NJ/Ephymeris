/**
 * The note a Rescan leaves (`DATA.md#reading-the-archive`), in one place for
 * every screen that offers one: Analytics and the Log.
 */

import type { RescanPruned, RescanResult } from "./types";

/**
 * What the archive walk found, in the order that matters to the reader.
 *
 * An unreachable folder comes first and alone: every other number is zero
 * *because* of it, so reporting "scanned 0 files" as though the archive were
 * empty would be actively misleading. Duplicates are reported rather than
 * quietly dropped — a hand-managed archive that keeps a consolidated copy
 * beside the originals is normal, and silently halving a file count is the
 * kind of thing that makes someone doubt the whole panel.
 */
export function describeRescan(result: RescanResult): string {
  if (result.folderMissing) {
    return `Can't reach ${result.dataFolder} — nothing was scanned. Reconnect the drive, or change this cohort's data folder.`;
  }
  const parts = [
    `Scanned ${result.scanned} file${result.scanned === 1 ? "" : "s"}`,
  ];
  // Records a past data-folder move left at the old folder, found and
  // re-pointed rather than pruned (`DATA.md#data-folder`).
  if (result.rehomed > 0) {
    parts.push(
      `re-pointed ${result.rehomed} record${result.rehomed === 1 ? "" : "s"} still naming the folder this cohort was moved out of`,
    );
  }
  if (result.adopted > 0) {
    parts.push(`adopted ${result.adopted} that no run record pointed at`);
  }
  if (result.duplicates > 0) {
    parts.push(
      `skipped ${result.duplicates} duplicate cop${result.duplicates === 1 ? "y" : "ies"} of runs already found`,
    );
  }
  // Deletions are stated, always. A reconciliation that quietly dropped rows
  // is indistinguishable from a walk that failed to find them, and this is the
  // one number in the note that the operator can't recover by clicking again.
  const pruned = prunedRecords(result.pruned);
  if (pruned) parts.push(pruned);
  const unmatched = result.orphans.filter((o) => o.animalId === null).length;
  if (unmatched > 0) {
    parts.push(
      `${unmatched} matched no animal on the roster and were left alone`,
    );
  }
  // A correction the operator can't see is one they can't check.
  const byName = result.orphans.filter(
    (o) => o.animalSource === "filename",
  ).length;
  if (byName > 0) {
    parts.push(
      `${byName} named an animal the roster doesn't have and ${byName === 1 ? "was" : "were"} matched on ${byName === 1 ? "its" : "their"} filename instead`,
    );
  }
  if (parts.length === 1)
    return `${parts[0]} — everything on disk is already indexed.`;
  return `${parts.join("; ")}.`;
}

/**
 * The prune clause of the rescan note (`DATA.md#pruning`), or null when nothing
 * was removed — which is the overwhelmingly common case and doesn't deserve a
 * sentence.
 *
 * Says **records**, and says it about the files rather than about the data: the
 * rescan removes this app's bookkeeping and has never touched the archive, and
 * an operator reading "removed 4 sessions" with no qualifier has every reason
 * to wonder which of the two just happened.
 */
function prunedRecords(pruned: RescanPruned): string | null {
  const parts: string[] = [];
  if (pruned.runs > 0) parts.push(`${pruned.runs} run${plural(pruned.runs)}`);
  if (pruned.adopted > 0) parts.push(`${pruned.adopted} adopted run${plural(pruned.adopted)}`);
  if (pruned.sessions > 0) {
    parts.push(`${pruned.sessions} session${plural(pruned.sessions)}`);
  }
  if (parts.length === 0) return null;
  return `dropped the records of ${joinList(parts)} whose files are no longer on disk`;
}

function plural(n: number): string {
  return n === 1 ? "" : "s";
}

function joinList(parts: string[]): string {
  if (parts.length <= 1) return parts[0] ?? "";
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/**
 * A what-changed entry in words (`DATA.md#what-changed`) — one definition for
 * the Log, its PDF and anything else that prints one.
 */

import type { RunChange } from "./types";

export interface ChangePart {
  text: string;
  /** A parameter, set in mono like every other value. */
  mono: boolean;
}

export function changeParts(change: RunChange): ChangePart[] {
  if (change.first) return [{ text: `first run · ${change.task}`, mono: false }];
  const parts: ChangePart[] = [];
  if (change.taskChange) {
    const from = String(change.taskChange.from);
    const to = String(change.taskChange.to);
    parts.push({
      text: from === to ? `${to} definition revised` : `task ${from} → ${to}`,
      mono: false,
    });
  }
  if (change.boxChange) {
    parts.push({
      text: `box ${String(change.boxChange.from)} → ${String(change.boxChange.to)}`,
      mono: false,
    });
  }
  // A value that changed is printed in full; a setting only one side has is
  // counted, not listed. Across a task change most settings are of the second
  // kind, and listing each "→ —" buries the handful that actually moved.
  const added = change.params.filter((p) => p.from === null && p.to !== null);
  const dropped = change.params.filter((p) => p.from !== null && p.to === null);
  for (const param of change.params) {
    if (added.includes(param) || dropped.includes(param)) continue;
    parts.push({ text: `${param.key} ${show(param.from)} → ${show(param.to)}`, mono: true });
  }
  const counted = [
    countPhrase(added.map((p) => p.key), "new"),
    countPhrase(dropped.map((p) => p.key), "dropped"),
  ].filter((text): text is string => text !== null);
  if (counted.length > 0) parts.push({ text: counted.join(", "), mono: false });
  return parts;
}

/** "holdMs new", or "4 settings new" past three — names while they fit. */
function countPhrase(keys: string[], what: string): string | null {
  if (keys.length === 0) return null;
  if (keys.length <= 3) return `${keys.join(", ")} ${what}`;
  return `${keys.length} settings ${what}`;
}

/**
 * Of these runs, how many could only have their task compared — a file too
 * old to carry its parameters, or a recovered run the analytics index has not
 * read yet. Said once per session (`unknownParamsNote`), not on every row: a
 * cohort of old files would otherwise print the same phrase for every animal.
 */
export function unknownParams(changes: readonly RunChange[]): number {
  return changes.filter((change) => !change.first && !change.paramsKnown).length;
}

export function unknownParamsNote(count: number): string | null {
  if (count === 0) return null;
  return `Parameters aren't on record for ${count} of these run${count === 1 ? "" : "s"} — files written before they were saved, or not read yet — so only the task is compared for ${count === 1 ? "it" : "them"}.`;
}

/** Where the box is printed: a recovered run names none (`DATA.md#what-changed`). */
export function boxText(box: number | null): string {
  return box === null ? "recovered" : `box ${box}`;
}

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

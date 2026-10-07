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
  for (const param of change.params) {
    parts.push({ text: `${param.key} ${show(param.from)} → ${show(param.to)}`, mono: true });
  }
  if (!change.paramsKnown) parts.push({ text: "parameters not recorded", mono: false });
  return parts;
}

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

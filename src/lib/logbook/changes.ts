/**
 * A what-changed entry in words (`DATA.md#what-changed`) — one definition for
 * the Log, its PDF and anything else that prints one.
 *
 * `changeFacts` is the structured reading the Log lays out; `changeParts` is
 * the same facts as flat text, for the PDF and the tests. Both derive from one
 * place so the screen and the page can never disagree about what moved.
 */

import type { RunChange } from "./types";

export interface ChangePart {
  text: string;
  /** A parameter, set in mono like every other value. */
  mono: boolean;
}

export interface ValueFact {
  from: string;
  to: string;
}

export interface ParamFact extends ValueFact {
  key: string;
}

export interface ChangeFacts {
  /** The animal's first run on record: nothing to compare, only the task. */
  first: boolean;
  task: (ValueFact & { revised: boolean }) | null;
  box: ValueFact | null;
  /** Values that moved, in full. */
  params: ParamFact[];
  /** Settings only one side has, counted: "holdMs new, 4 settings dropped". */
  counted: string | null;
  /** Anything at all to show. */
  any: boolean;
}

export function changeFacts(change: RunChange): ChangeFacts {
  if (change.first) {
    return { first: true, task: null, box: null, params: [], counted: null, any: true };
  }
  const task = change.taskChange
    ? {
        from: String(change.taskChange.from),
        to: String(change.taskChange.to),
        revised: String(change.taskChange.from) === String(change.taskChange.to),
      }
    : null;
  const box = change.boxChange
    ? { from: String(change.boxChange.from), to: String(change.boxChange.to) }
    : null;
  // A value that changed is printed in full; a setting only one side has is
  // counted, not listed. Across a task change most settings are of the second
  // kind, and listing each "→ —" buries the handful that actually moved.
  const added = change.params.filter((p) => p.from === null && p.to !== null);
  const dropped = change.params.filter((p) => p.from !== null && p.to === null);
  const params = change.params
    .filter((p) => !added.includes(p) && !dropped.includes(p))
    .map((p) => ({ key: p.key, from: show(p.from), to: show(p.to) }));
  const counted = [
    countPhrase(added.map((p) => p.key), "new"),
    countPhrase(dropped.map((p) => p.key), "dropped"),
  ].filter((text): text is string => text !== null);
  return {
    first: false,
    task,
    box,
    params,
    counted: counted.length > 0 ? counted.join(", ") : null,
    any: task !== null || box !== null || params.length > 0 || counted.length > 0,
  };
}

export function changeParts(change: RunChange): ChangePart[] {
  if (change.first) return [{ text: `first run · ${change.task}`, mono: false }];
  const facts = changeFacts(change);
  const parts: ChangePart[] = [];
  if (facts.task) {
    parts.push({
      text: facts.task.revised
        ? `${facts.task.to} definition revised`
        : `task ${facts.task.from} → ${facts.task.to}`,
      mono: false,
    });
  }
  if (facts.box) parts.push({ text: `box ${facts.box.from} → ${facts.box.to}`, mono: false });
  for (const param of facts.params) {
    parts.push({ text: `${param.key} ${param.from} → ${param.to}`, mono: true });
  }
  if (facts.counted) parts.push({ text: facts.counted, mono: false });
  return parts;
}

/** "holdMs new", or "4 settings new" past three — names while they fit. */
function countPhrase(keys: string[], what: string): string | null {
  if (keys.length === 0) return null;
  if (keys.length <= 3) return `${keys.join(", ")} ${what}`;
  return `${keys.length} settings ${what}`;
}

export interface ChangeSummary {
  /** Runs in the session. */
  animals: number;
  /** Runs with anything to show, first runs included. */
  changed: number;
  first: number;
  tasks: number;
  boxes: number;
  /** Values that moved, across every animal. */
  settings: number;
}

/** The session's changes counted, for the tile header and the PDF. */
export function changeSummary(changes: readonly RunChange[]): ChangeSummary {
  const summary: ChangeSummary = { animals: changes.length, changed: 0, first: 0, tasks: 0, boxes: 0, settings: 0 };
  for (const change of changes) {
    const facts = changeFacts(change);
    if (facts.any) summary.changed += 1;
    if (facts.first) summary.first += 1;
    if (facts.task) summary.tasks += 1;
    if (facts.box) summary.boxes += 1;
    summary.settings += facts.params.length;
  }
  return summary;
}

/** "2 of 6 changed · 1 task · 3 settings", or what there is instead. */
export function changeSummaryText(summary: ChangeSummary): string {
  if (summary.animals === 0) return "no runs yet";
  if (summary.changed === 0) return `all ${summary.animals} unchanged`;
  // A first session: nothing "changed", every animal simply began.
  if (summary.first === summary.changed) {
    return `${summary.first} first run${summary.first === 1 ? "" : "s"}`;
  }
  const parts = [
    plural(summary.tasks, "task"),
    plural(summary.boxes, "box", "boxes"),
    plural(summary.settings, "setting"),
    summary.first > 0 ? `${summary.first} first run${summary.first === 1 ? "" : "s"}` : null,
  ].filter((text): text is string => text !== null);
  const head =
    summary.changed === summary.animals
      ? `all ${summary.animals} changed`
      : `${summary.changed} of ${summary.animals} changed`;
  return [head, ...parts].join(" · ");
}

function plural(count: number, one: string, many = `${one}s`): string | null {
  if (count === 0) return null;
  return `${count} ${count === 1 ? one : many}`;
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

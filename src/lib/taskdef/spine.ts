import type { SpineRam, TaskDiagnostic, TaskTarget } from "@/lib/ws/protocol";

import type { TaskDocument } from "./types";

/**
 * A phase-spine task as the editor holds it (`TASKS.md#what-a-spine-task-holds`),
 * and the edits the spine editor makes to it (`TASKS.md#the-spine-editor`).
 *
 * THE EDITOR COMPUTES NOTHING ABOUT THE TASK. It holds the unsaved document and
 * changes only what the operator asked; what each slot can bind, whether a block
 * sequence ends, the RAM it takes and everything wrong with it come back from
 * `tasks.preview` (`SpineView`, `TaskDiagnostic.target`). The edits here are the
 * ones that touch more than one place in the document, so each keeps the
 * document's own cross-references whole: a removed row leaves its blocks, a
 * moved phase moves every block's override of it, a removed block leaves every
 * `next` that named it.
 *
 * Pure: no React, no wire.
 */

export interface SpineSlot {
  id: string;
  /** `digital_in`, `digital_out`, `pwm_out` or `tone_out`. */
  type: string;
  /** `train` on a pulse-train `digital_out`. */
  mode?: string;
}

/** One phase from the palette. Fields a phase does not use are left out. */
export interface SpinePhase {
  phase: string;
  on?: string;
  outputs?: string[];
  ms?: number;
  timeoutMs?: number;
  edge?: string;
  abortOnRelease?: string;
  abortOnEnter?: string;
  line?: string;
  responses?: string[];
  holdMs?: number;
  count?: number;
  countMax?: number;
  ratios?: number[];
  endsSession?: boolean;
}

export interface MapEntry {
  outcome: string;
  line?: string;
  rewardPermille?: number;
  hold?: boolean;
}

export interface SpineRow {
  /** Stable and neutral (`row_1`): it names the row's parameters and never shows. */
  id: string;
  name: string;
  /** Slot → channel name. */
  bind: Record<string, string>;
  rewardMs: number;
  rewardPermille: number;
  map?: Record<string, MapEntry>;
  /** Driven output slot → its values (`duty`, `hz`, `widthMs`, `ms`). */
  drive?: Record<string, Record<string, number>>;
}

export interface SpineBlock {
  id: string;
  rows: string[];
  select?: string;
  weights?: number[];
  trials?: number;
  trialsMax?: number;
  criterion?: { correct: number; of: number };
  next?: string;
  correction?: number;
  correctionAfter?: string[];
  biasWindow?: number;
  /** Phase index → ms while the block runs. */
  phaseMs?: Record<string, number>;
}

export interface SpineDefinition {
  id: string;
  name: string;
  category: string;
  slots: SpineSlot[];
  spine: SpinePhase[];
  rows: SpineRow[];
  blocks: SpineBlock[];
  sessionTrials?: number;
  params: Record<string, unknown>;
  legacyNames: string[];
  notes: string;
}

/** A definition with a top-level `spine` is a spine task (`taskdef/model.py`). */
export function isSpine(doc: TaskDocument): doc is SpineDefinition {
  return Array.isArray((doc as { spine?: unknown }).spine);
}

/** The phases that last a set time, and so take `ms` (`lowering._TIMED`). */
const TIMED = new Set(["hold", "present", "delay", "response", "outcome", "iti"]);

/** What a newly inserted phase carries: the fields its kind cannot do without,
 *  watching the spine's first input slot where it watches one. The operator
 *  sets the rest; a wrong guess is a diagnostic on the phase, never silent. */
function freshPhase(def: SpineDefinition, kind: string): SpinePhase {
  const input = def.slots.find((s) => s.type === "digital_in")?.id;
  switch (kind) {
    case "wait":
      return input ? { phase: kind, on: input } : { phase: kind };
    case "hold":
      return input ? { phase: kind, on: input, ms: 200 } : { phase: kind, ms: 200 };
    case "counter":
      return input ? { phase: kind, on: input, count: 5 } : { phase: kind, count: 5 };
    case "response":
      return { phase: kind, responses: [], ms: 3000 };
    case "outcome":
      return { phase: kind, ms: 0 };
    default:
      return TIMED.has(kind) ? { phase: kind, ms: 1000 } : { phase: kind };
  }
}

/** Each block's `phaseMs`, with every key run through `move` (null drops it). */
function moveOverrides(def: SpineDefinition, move: (i: number) => number | null): SpineBlock[] {
  return def.blocks.map((block) => {
    if (!block.phaseMs) return block;
    const phaseMs: Record<string, number> = {};
    for (const [key, ms] of Object.entries(block.phaseMs)) {
      const to = /^\d+$/.test(key) ? move(Number(key)) : null;
      if (to !== null) phaseMs[String(to)] = ms;
    }
    return { ...block, phaseMs };
  });
}

export function insertPhase(def: SpineDefinition, at: number, kind: string): SpineDefinition {
  const spine = [...def.spine];
  spine.splice(at, 0, freshPhase(def, kind));
  return { ...def, spine, blocks: moveOverrides(def, (i) => (i >= at ? i + 1 : i)) };
}

export function removePhase(def: SpineDefinition, at: number): SpineDefinition {
  return {
    ...def,
    spine: def.spine.filter((_, i) => i !== at),
    blocks: moveOverrides(def, (i) => (i === at ? null : i > at ? i - 1 : i)),
  };
}

export function setPhase(def: SpineDefinition, at: number, phase: SpinePhase): SpineDefinition {
  return { ...def, spine: def.spine.map((p, i) => (i === at ? phase : p)) };
}

/** The first `<prefix><n>` no item holds, from 1. */
function freeId(prefix: string, taken: readonly string[]): string {
  for (let n = 1; ; n++) if (!taken.includes(`${prefix}${n}`)) return `${prefix}${n}`;
}

/**
 * A new row: the next free neutral id, NO name, seeded from the last row's
 * bindings and map so the operator changes the one thing that differs, and
 * drawn by every block that draws the row it was copied from, at weight 1.
 */
export function addRow(def: SpineDefinition): SpineDefinition {
  const last = def.rows[def.rows.length - 1];
  const id = freeId("row_", def.rows.map((r) => r.id));
  const row: SpineRow = last
    ? { ...structuredClone(last), id, name: "" }
    : { id, name: "", bind: {}, rewardMs: 100, rewardPermille: 1000 };
  const blocks = def.blocks.map((block) => {
    if (last ? !block.rows.includes(last.id) : block !== def.blocks[0]) return block;
    const next: SpineBlock = { ...block, rows: [...block.rows, id] };
    if (block.weights) next.weights = [...block.weights, 1];
    return next;
  });
  return { ...def, rows: [...def.rows, row], blocks };
}

/** Remove a row, and it (with its weight) from every block that draws it. */
export function removeRow(def: SpineDefinition, at: number): SpineDefinition {
  const id = def.rows[at]?.id;
  if (id === undefined) return def;
  const blocks = def.blocks.map((block) => {
    const e = block.rows.indexOf(id);
    if (e < 0) return block;
    const next: SpineBlock = { ...block, rows: block.rows.filter((_, i) => i !== e) };
    if (block.weights) next.weights = block.weights.filter((_, i) => i !== e);
    return next;
  });
  return { ...def, rows: def.rows.filter((_, i) => i !== at), blocks };
}

export function setRow(def: SpineDefinition, at: number, row: SpineRow): SpineDefinition {
  return { ...def, rows: def.rows.map((r, i) => (i === at ? row : r)) };
}

/** Bind one slot of one row; an empty channel unbinds it. */
export function setBinding(def: SpineDefinition, at: number, slot: string, channel: string): SpineDefinition {
  const row = def.rows[at];
  if (!row) return def;
  const bind = { ...row.bind };
  if (channel) bind[slot] = channel;
  else delete bind[slot];
  return setRow(def, at, { ...row, bind });
}

/** Set one entry of a row's contingency map (a response slot or `timeout`); null removes it. */
export function setMapEntry(def: SpineDefinition, at: number, key: string, entry: MapEntry | null): SpineDefinition {
  const row = def.rows[at];
  if (!row) return def;
  const map = { ...(row.map ?? {}) };
  if (entry) map[key] = entry;
  else delete map[key];
  return setRow(def, at, { ...row, map });
}

/** A new block drawing every row, for a trial count: a fresh id, `b<n>`. */
export function addBlock(def: SpineDefinition): SpineDefinition {
  const id = freeId("b", def.blocks.map((b) => b.id));
  return { ...def, blocks: [...def.blocks, { id, rows: def.rows.map((r) => r.id), trials: 100 }] };
}

/** Remove a block, and every `next` that named it (those blocks then run on to the following one). */
export function removeBlock(def: SpineDefinition, at: number): SpineDefinition {
  const id = def.blocks[at]?.id;
  const blocks = def.blocks
    .filter((_, i) => i !== at)
    .map((block) => {
      if (block.next !== id) return block;
      const { next: _gone, ...rest } = block;
      return rest;
    });
  return { ...def, blocks };
}

export function setBlock(def: SpineDefinition, at: number, block: SpineBlock): SpineDefinition {
  return { ...def, blocks: def.blocks.map((b, i) => (i === at ? block : b)) };
}

/** Add a slot of a type (and mode); its id is the first free `<type>_<n>`-style one given. */
export function addSlot(def: SpineDefinition, slot: SpineSlot): SpineDefinition {
  return { ...def, slots: [...def.slots, slot] };
}

/** Remove a slot and every row's binding, map entry and drive values for it.
 *  A phase still naming it is left for the diagnostics to point at. */
export function removeSlot(def: SpineDefinition, at: number): SpineDefinition {
  const id = def.slots[at]?.id;
  if (id === undefined) return def;
  const rows = def.rows.map((row) => {
    const { [id]: _b, ...bind } = row.bind;
    const next: SpineRow = { ...row, bind };
    if (row.map) {
      const { [id]: _m, ...map } = row.map;
      next.map = map;
    }
    if (row.drive) {
      const { [id]: _d, ...drive } = row.drive;
      next.drive = drive;
    }
    return next;
  });
  return { ...def, slots: def.slots.filter((_, i) => i !== at), rows };
}

/** The diagnostics the sidecar placed on one target. */
export function diagnosticsOn(
  diagnostics: readonly TaskDiagnostic[],
  kind: TaskTarget["kind"],
  index: number | null = null,
): TaskDiagnostic[] {
  return diagnostics.filter((d) => d.target.kind === kind && d.target.index === index);
}

export interface MeterSegment {
  label: string;
  bytes: number;
  /** Where it starts and how wide it is, as fractions of the bar. */
  start: number;
  width: number;
}

export interface Meter {
  bytes: number;
  budget: number;
  over: boolean;
  /** What the full bar stands for: the budget, or the bytes when they pass it. */
  scale: number;
  /** Where the budget's mark sits on the bar, as a fraction. */
  budgetAt: number;
  segments: MeterSegment[];
}

/**
 * The RAM meter's geometry from the sidecar's count (`SpineRam`). Only layout:
 * the bytes and their parts are the sidecar's `ram_parts`. Over budget the bar
 * stretches to the bytes, so the overflow is drawn past the budget's mark
 * rather than clipped at it. Null when the spine cannot be lowered.
 */
export function meterOf(ram: SpineRam): Meter | null {
  if (ram.bytes === null) return null;
  const scale = Math.max(ram.bytes, ram.budget);
  let at = 0;
  const segments = ram.parts.map((part) => {
    const segment = { label: part.label, bytes: part.bytes, start: at / scale, width: part.bytes / scale };
    at += part.bytes;
    return segment;
  });
  return {
    bytes: ram.bytes,
    budget: ram.budget,
    over: ram.bytes > ram.budget,
    scale,
    budgetAt: ram.budget / scale,
    segments,
  };
}

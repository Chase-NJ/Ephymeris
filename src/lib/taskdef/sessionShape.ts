import type { SpineBlock, SpineDefinition, SpineRow } from "./spine";

/**
 * The shapes a session usually takes (`TASKS.md#the-spine-editor`), read off
 * the blocks and written back to them: one block of N trials; a reversal,
 * where a second block of reversed trial types starts once k of the last n
 * were right; or two blocks that alternate until a cap. Anything else is
 * custom, and the block panel edits it as it is.
 *
 * Words and document edits only. What follows each block, whether the
 * session ends by itself and every problem with the blocks are the preview's
 * (`SpineView.blocks`, `sessionEnds`, SPN106).
 */

export type SessionShape =
  | { kind: "single"; trials: number }
  | { kind: "reversal"; correct: number; of: number; trials: number }
  | { kind: "alternate"; trials: number; cap: number }
  | { kind: "custom" };

export type ShapeKind = SessionShape["kind"];

export const SHAPES: ReadonlyArray<{ kind: ShapeKind; label: string; help: string }> = [
  { kind: "single", label: "One block", help: "Every trial type, drawn at random, for N trials." },
  {
    kind: "reversal",
    label: "Reversal",
    help: "The trial types until k of the last n are right, then the same trial types with their answers reversed, for N trials.",
  },
  { kind: "alternate", label: "Two blocks that alternate", help: "Two blocks of N trials each, looping, until the session's cap." },
  { kind: "custom", label: "Custom", help: "Any number of blocks, each with its own trial types, selection and end rule." },
];

const REVERSED = "_rev";

/** Whether a row is the reversed copy `applyShape` makes of another. */
export function isReversed(row: SpineRow): boolean {
  return row.id.endsWith(REVERSED);
}

/** The key a map marks `correct`, or null. */
function correctKey(row: SpineRow): string | null {
  return Object.entries(row.map ?? {}).find(([, e]) => e.outcome === "correct")?.[0] ?? null;
}

/**
 * A row's map with its answers reversed: the map of a row whose correct
 * answer differs, which for a 2AFC pair swaps the two maps (left pays, then
 * right pays), for go/no-go swaps go and no-go, and for DNMS makes a match
 * row answer as a non-match row does. Null when no row answers differently,
 * so there is nothing to reverse to.
 */
export function reversedMap(row: SpineRow, rows: readonly SpineRow[]): SpineRow["map"] | null {
  const mine = correctKey(row);
  const other = rows.find((r) => r !== row && !isReversed(r) && correctKey(r) !== mine);
  return other?.map ? structuredClone(other.map) : null;
}

/** Whether every original row has a reversal to go to. */
export function canReverse(def: SpineDefinition): boolean {
  const originals = def.rows.filter((r) => !isReversed(r));
  return originals.length > 0 && originals.every((r) => reversedMap(r, originals) !== null);
}

/** The reversed copy of each original row: `<id>_rev`, "<name> (reversed)", the same bindings, the other answer. */
function reversedRows(def: SpineDefinition): SpineRow[] {
  const originals = def.rows.filter((r) => !isReversed(r));
  return originals.map((row) => {
    const existing = def.rows.find((r) => r.id === row.id + REVERSED);
    const map = reversedMap(row, originals);
    const copy: SpineRow = existing ?? { ...structuredClone(row), id: row.id + REVERSED, name: row.name ? `${row.name} (reversed)` : "" };
    if (map) copy.map = map;
    else delete copy.map;
    return copy;
  });
}

/** The session's shape, when the blocks have one of the three. */
export function shapeOf(def: SpineDefinition): SessionShape {
  const [a, b, ...rest] = def.blocks;
  if (!a || rest.length) return { kind: "custom" };
  if (!b) {
    return a.trials !== undefined && a.trialsMax === undefined && !a.criterion && a.next === undefined
      ? { kind: "single", trials: a.trials }
      : { kind: "custom" };
  }
  const aOn = a.next === undefined || a.next === b.id;
  if (a.criterion && a.trials === undefined && aOn && b.trials !== undefined && !b.criterion && b.next === undefined) {
    return { kind: "reversal", correct: a.criterion.correct, of: a.criterion.of, trials: b.trials };
  }
  if (
    aOn &&
    b.next === a.id &&
    a.trials !== undefined &&
    b.trials === a.trials &&
    !a.criterion &&
    !b.criterion &&
    a.trialsMax === undefined &&
    b.trialsMax === undefined
  ) {
    return { kind: "alternate", trials: a.trials, cap: def.sessionTrials ?? 0 };
  }
  return { kind: "custom" };
}

/** The shape's starting values when it is chosen, from what the blocks have now. */
export function defaultShape(def: SpineDefinition, kind: ShapeKind): SessionShape {
  const first = def.blocks[0];
  const trials = first?.trials ?? 200;
  switch (kind) {
    case "single":
      return { kind, trials };
    case "reversal":
      return { kind, correct: first?.criterion?.correct ?? 8, of: first?.criterion?.of ?? 10, trials };
    case "alternate":
      return { kind, trials: Math.max(1, Math.round(trials / 2)), cap: def.sessionTrials ?? trials * 2 };
    default:
      return { kind: "custom" };
  }
}

/** The block's fields no shape keeps: its selection and weights survive, its end rules and `next` do not. */
function base(block: SpineBlock | undefined, id: string, rows: string[]): SpineBlock {
  const kept: SpineBlock = { id, rows };
  if (block?.select) kept.select = block.select;
  if (block?.weights && block.rows.length === rows.length) kept.weights = block.weights;
  if (block?.correction !== undefined) kept.correction = block.correction;
  if (block?.correctionAfter) kept.correctionAfter = block.correctionAfter;
  if (block?.biasWindow !== undefined) kept.biasWindow = block.biasWindow;
  if (block?.phaseMs) kept.phaseMs = block.phaseMs;
  if (block?.holdMs) kept.holdMs = block.holdMs;
  return kept;
}

/**
 * Write a shape over the blocks. The first block keeps its id, selection,
 * weights, correction and phase overrides; a reversal adds the reversed rows
 * it needs (and drops them when another shape replaces it); the alternating
 * pair sets the session cap, since only the cap ends it.
 */
export function applyShape(def: SpineDefinition, shape: SessionShape): SpineDefinition {
  if (shape.kind === "custom") return def;
  const [first, second] = def.blocks;
  const originals = def.rows.filter((r) => !isReversed(r));
  const ids = originals.map((r) => r.id);
  const a = first?.id ?? "b1";
  const b = second?.id && second.id !== a ? second.id : a === "b2" ? "b3" : "b2";
  const next: SpineDefinition = { ...def, rows: originals };
  switch (shape.kind) {
    case "single":
      next.blocks = [{ ...base(first, a, ids), trials: shape.trials }];
      break;
    case "reversal": {
      const reversed = reversedRows(def);
      next.rows = [...originals, ...reversed];
      next.blocks = [
        { ...base(first, a, ids), criterion: { correct: shape.correct, of: shape.of } },
        { ...base(second, b, reversed.map((r) => r.id)), trials: shape.trials },
      ];
      break;
    }
    case "alternate":
      next.blocks = [
        { ...base(first, a, ids), trials: shape.trials },
        { ...base(second, b, ids), trials: shape.trials, next: a },
      ];
      next.sessionTrials = shape.cap;
      break;
  }
  if (shape.kind !== "alternate" && def.sessionTrials === undefined) delete next.sessionTrials;
  return next;
}

/** "Block 1", with the id for anyone who needs it. */
export function blockLabel(index: number): string {
  return `Block ${index + 1}`;
}

/** A block's end rule in words: "200 trials", "40–60 trials", "8 of the last 10 right", or "never ends". */
export function endRuleWords(block: SpineBlock): string {
  const parts: string[] = [];
  if (block.trials !== undefined) {
    parts.push(block.trialsMax !== undefined ? `${block.trials}–${block.trialsMax} trials` : `${block.trials} trials`);
  }
  if (block.criterion) parts.push(`${block.criterion.correct} of the last ${block.criterion.of} right`);
  return parts.length ? parts.join(", or ") : "never ends";
}

/**
 * The session as a sentence, block by block, with what follows each as the
 * preview resolved it (`SpineView.blocks[].next`; null is the end, undefined
 * is not known yet): "Block 1 (Odor 1, Odor 2): until 8 of the last 10 are
 * right, then Block 2. Block 2 (…): 100 trials, then the session ends."
 */
export function sessionSentence(def: SpineDefinition, nexts: ReadonlyArray<number | null | undefined>): string {
  const names = new Map(def.rows.map((r, i) => [r.id, r.name || `trial type ${i + 1}`]));
  return def.blocks
    .map((block, i) => {
      const rows = block.rows.map((id) => names.get(id) ?? id).join(", ");
      const next = nexts[i];
      const then =
        next === undefined ? "" : next === null ? ", then the session ends" : next === i + 1 ? `, then ${blockLabel(next)}` : `, then back to ${blockLabel(next)}`;
      return `${blockLabel(i)} (${rows || "no trial types"}): ${endRuleWords(block)}${then}.`;
    })
    .join(" ");
}

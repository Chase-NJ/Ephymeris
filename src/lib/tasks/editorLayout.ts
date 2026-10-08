import { EDITOR_MIN_W } from "./graphLayout";

/**
 * How the task editor arranges its three regions for a page this wide
 * (`TASKS.md#editor`).
 *
 * The state machine has a floor (`EDITOR_MIN_W`) and the page bends around it
 * rather than the reverse: first the section spine folds to a strip of marks,
 * then the parameter rail leaves the side and docks under the diagram. Each
 * step is the next-least-costly thing to give up — the spine is navigation the
 * scroll also provides, the rail's side position only saves a scroll.
 *
 * - `wide` — full spine, rail at the side, the diagram card running under it.
 * - `medium` — the spine as a strip of marks, a narrower rail at the side.
 * - `stacked` — strip spine; the rail docked under the diagram, in front of it.
 */
export type EditorMode = "wide" | "medium" | "stacked";

export interface EditorLayout {
  mode: EditorMode;
  /** Left region's width. */
  spine: number;
  /** Side rail's width; 0 when the rail is docked in the column. */
  rail: number;
}

export const SPINE_FULL = 300;
export const SPINE_COMPACT = 72;
export const RAIL_WIDE = 400;
export const RAIL_MEDIUM = 352;
/** Gap between the centre column's blocks and the side rail's panel. */
export const RAIL_GAP = 12;
/** The centre scroller's padding (16 + 16) and the diagram card's (16 + 16). */
export const CHROME = 64;

/**
 * How far the centre column's blocks stop short of the page's right edge for a
 * side rail this wide. The rail column carries 16px of right padding, so its
 * panel starts `rail` from the edge; the blocks stop `RAIL_GAP` before that.
 */
export function railInset(rail: number): number {
  return rail > 0 ? rail - 16 + RAIL_GAP : 0;
}

/** The diagram host's width under a given spine and side rail. */
export function diagramWidth(page: number, spine: number, rail: number): number {
  return page - spine - CHROME - railInset(rail);
}

export function editorLayout(page: number | null): EditorLayout {
  // Unmeasured: assume room, as the page did before it measured anything. The
  // first measurement lands before paint.
  if (page === null) return { mode: "wide", spine: SPINE_FULL, rail: RAIL_WIDE };
  if (diagramWidth(page, SPINE_FULL, RAIL_WIDE) >= EDITOR_MIN_W) {
    return { mode: "wide", spine: SPINE_FULL, rail: RAIL_WIDE };
  }
  if (diagramWidth(page, SPINE_COMPACT, RAIL_MEDIUM) >= EDITOR_MIN_W) {
    return { mode: "medium", spine: SPINE_COMPACT, rail: RAIL_MEDIUM };
  }
  return { mode: "stacked", spine: SPINE_COMPACT, rail: 0 };
}

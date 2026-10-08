import { EDITOR_MIN_W } from "./graphLayout";

/**
 * How the task editor arranges itself for a page this wide
 * (`TASKS.md#editor`).
 *
 * The state machine has a floor (`EDITOR_MIN_W`) and the page bends around it,
 * never the reverse. **Split**: the machine and the trial types in the main
 * column, the parameter dial and trial generation in an aside beside them —
 * everything in one frame. **Stacked**: when the aside would squeeze the
 * machine below its floor, the aside's two panels move under the trial types
 * and the page scrolls.
 */
export type EditorMode = "split" | "stacked";

export interface EditorLayout {
  mode: EditorMode;
  /** The aside's width in split mode; 0 when stacked. */
  aside: number;
}

export const ASIDE = 360;
export const ASIDE_WIDE = 400;
/** Pages at least this wide get the wider aside. */
export const WIDE_PAGE = 1280;
/** The page's side padding (16 + 16) and the gap between the columns. */
export const PAGE_CHROME = 32 + 12;
/** The machine panel's own padding (16 + 16). */
export const PANEL_PAD = 32;

/** The machine's drawing width beside an aside this wide (0 = none). */
export function machineWidth(page: number, aside: number): number {
  return page - PAGE_CHROME - aside - PANEL_PAD + (aside === 0 ? 12 : 0);
}

export function editorLayout(page: number | null): EditorLayout {
  // Unmeasured: assume room. The first measurement lands before paint.
  if (page === null) return { mode: "split", aside: ASIDE };
  const aside = page >= WIDE_PAGE ? ASIDE_WIDE : ASIDE;
  return machineWidth(page, aside) >= EDITOR_MIN_W
    ? { mode: "split", aside }
    : { mode: "stacked", aside: 0 };
}

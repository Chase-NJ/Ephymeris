import { createContext, useContext } from "react";

/**
 * How a labelled row arranges itself — set by the surface, read by the leaf.
 *
 * `"inline"` is the form's layout and the default: label and help on the left,
 * the control and its unit on the right. It assumes a column wide enough for
 * both, which the Parameters view has and a 320px inspector rail does not.
 *
 * `"stacked"` puts the label on its own line with the control full-width
 * beneath. It exists because the arithmetic in the rail was hopeless rather
 * than merely tight: 320px minus the aside's and the group's padding leaves
 * ~274px of content, of which a `SelectRow` spent 190 on the select, 24 on the
 * unit slot and 18 on gaps — leaving 42px for the label, whatever the label
 * said. Widening the rail moves that number; stacking makes it structurally
 * impossible.
 *
 * A CONTEXT RATHER THAN A PROP, so `SpecField` — which sits between the
 * surface and the row and dispatches sixteen widgets — needs no changes at
 * all. Threading a prop through it would mean touching every branch, and the
 * one that got missed would be the bug.
 */
export type RowDensity = "inline" | "stacked";

export const RowDensityContext = createContext<RowDensity>("inline");

export function useRowDensity(): RowDensity {
  return useContext(RowDensityContext);
}

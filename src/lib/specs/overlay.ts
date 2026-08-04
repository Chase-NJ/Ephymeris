/**
 * Overlay lookups: concrete path → overlay key.
 *
 * The normalisation rule itself lives in the COMPILER
 * (taskgraph/presentation.py) and diagnostics arrive with their placement and
 * anchor precomputed, so nothing here parses a location. What the form needs
 * locally is the forward direction — "I am rendering one row of
 * `contingency.ports`; which overlay entry describes its `channel`?" — kept
 * here so no component wildcards a path inline.
 *
 * Indexed sections need no helper: their overlay keys (`timing[].ms`) are
 * constants the form writes out, so only the keyed collections' `.*.` form is
 * built at runtime.
 */

import type { Overlay, OverlayField } from "./types";

/** The overlay key for one field of a keyed collection's row. */
export function keyedKey(sectionPath: string, field: string): string {
  return `${sectionPath}.*.${field}`;
}

/** The overlay entries belonging to one group, in `order`. */
export function groupFields(
  overlay: Overlay,
  groupId: string,
): Array<[string, OverlayField]> {
  return Object.entries(overlay.fields)
    .filter(([, meta]) => meta.group === groupId)
    .sort(([, a], [, b]) => (a.order ?? 0) - (b.order ?? 0));
}

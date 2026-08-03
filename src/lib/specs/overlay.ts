/**
 * Overlay lookups: concrete path → overlay key → field metadata.
 *
 * The normalisation rule itself lives in the COMPILER
 * (taskgraph/presentation.py) and diagnostics arrive with their placement and
 * anchor precomputed, so nothing here parses a location. What the form needs
 * locally is the forward direction — "I am rendering `timing[3].ms`; which
 * overlay entry describes me?" — which is a mechanical wildcarding of indices
 * and instance names, kept in one place so no component does it inline.
 */

import type { Overlay, OverlayField } from "./types";

/**
 * `timing[3].ms` → `timing[].ms`;
 * `contingency.ports.left_well.channel` → `contingency.ports.*.channel`.
 *
 * The caller says which segment is an instance name by construction — the form
 * knows it is rendering the rows of a keyed collection — so this only has to
 * wildcard indices. For keyed collections use `overlayKey(section, field)`.
 */
export function indexedKey(path: string): string {
  return path.replace(/\[\d+\]/g, "[]");
}

/** The overlay key for one field of a keyed collection's row. */
export function keyedKey(sectionPath: string, field: string): string {
  return `${sectionPath}.*.${field}`;
}

export function fieldMeta(overlay: Overlay, key: string): OverlayField | undefined {
  return overlay.fields[key];
}

/** Groups in declared order, ready to render. */
export function orderedGroups(overlay: Overlay) {
  return [...overlay.groups].sort((a, b) => a.order - b.order);
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

/**
 * Diagnostics → where they render.
 *
 * The hard half — classifying a location into field/row/section/node/document
 * and normalising it to an anchor — happened in the sidecar, computed by the
 * compiler's own `placement()`. What remains here is fan-out: group the
 * arrived diagnostics by placement so each consumer (an input, a section
 * header, the graph pane, the panel) can look itself up.
 *
 * The invariant this file serves: A DIAGNOSTIC THAT REACHES NOBODY IS THE
 * FAILURE MODE. Everything lands somewhere, and the panel below the form
 * additionally lists all of them, so even a diagnostic whose anchor names a
 * row the form isn't currently showing is still visible.
 */

import type { SpecDiagnostic } from "./types";

export interface PlacedDiagnostics {
  /** Overlay key (`timing[].ms`) → diagnostics for inputs matching that key. */
  byField: Map<string, SpecDiagnostic[]>;
  /** Concrete location (`timing[3].ms`) → diagnostics for exactly that row's input. */
  byLocation: Map<string, SpecDiagnostic[]>;
  /** Section path (`timing`, `contingency.outcome_map`) → header-level diagnostics. */
  bySection: Map<string, SpecDiagnostic[]>;
  /** Row anchor (`contingency.outcome_map` + instance) → row-header diagnostics. */
  byRow: Map<string, SpecDiagnostic[]>;
  /** Node id (`S12`) → graph-pane diagnostics. */
  byNode: Map<string, SpecDiagnostic[]>;
  /** Nothing to anchor to — the document-level banner. */
  document: SpecDiagnostic[];
}

function push<K>(map: Map<K, SpecDiagnostic[]>, key: K, d: SpecDiagnostic) {
  const existing = map.get(key);
  if (existing) existing.push(d);
  else map.set(key, [d]);
}

export function placeDiagnostics(diagnostics: SpecDiagnostic[]): PlacedDiagnostics {
  const out: PlacedDiagnostics = {
    byField: new Map(),
    byLocation: new Map(),
    bySection: new Map(),
    byRow: new Map(),
    byNode: new Map(),
    document: [],
  };
  for (const d of diagnostics) {
    switch (d.placement) {
      case "field":
        if (d.anchor) push(out.byField, d.anchor, d);
        // The concrete location distinguishes WHICH row of a repeated field —
        // `timing[3].ms` must not light every timing row's ms input.
        if (d.location) push(out.byLocation, d.location, d);
        if (!d.anchor && !d.location) out.document.push(d);
        break;
      case "row":
        if (d.location) push(out.byRow, d.location, d);
        else out.document.push(d);
        break;
      case "section":
        if (d.anchor) push(out.bySection, d.anchor, d);
        else out.document.push(d);
        break;
      case "node":
        if (d.anchor) push(out.byNode, d.anchor, d);
        else out.document.push(d);
        break;
      default:
        out.document.push(d);
    }
  }
  return out;
}

/**
 * The message(s) for one concrete input. Prefers an exact concrete-location
 * match (the common case for indexed rows); falls back to the wildcard key
 * only when the diagnostic couldn't be pinned to an index.
 */
export function errorsFor(
  placed: PlacedDiagnostics,
  concretePath: string,
  overlayKey: string,
): SpecDiagnostic[] {
  const exact = placed.byLocation.get(concretePath);
  if (exact && exact.length > 0) return exact;
  // A wildcard-only hit applies when its own concrete location wasn't a
  // renderable row — e.g. a map-keyed field. Avoid double-reporting: only
  // return wildcard matches whose location is this path or unset.
  const wild = placed.byField.get(overlayKey) ?? [];
  return wild.filter((d) => !d.location || d.location === concretePath);
}

export function firstError(diags: SpecDiagnostic[]): string | undefined {
  const error = diags.find((d) => d.severity === "ERROR") ?? diags[0];
  return error?.message;
}

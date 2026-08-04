/**
 * What produced this piece of the graph?
 *
 * The Task Designer draws the compiled machine and lets the operator click it.
 * Clicking cannot EDIT the graph — `topology` is knobs and a versioned template
 * emits the nodes (D1; a spec carrying a `nodes:` key is rejected
 * outright by TG103) — so what a click has to do instead is answer "which
 * fields, if I changed them, would change this?" and put those fields in front
 * of the operator. This module is that answer, and nothing else: pure, no
 * React, no fetch.
 *
 * EVERY RULE HERE JOINS ON DATA, NOT ON NAMES. The compiler's own
 * `Provenance(template, line, band, knobs)` does not survive lowering into the
 * StateTable, so the mapping is reconstructed here — but from values both sides
 * genuinely share, never from the shape of a template's symbol strings:
 *
 *   node.durationId  → the `timing` row declaring that id
 *   edge.effect      → `score:<class>` names an outcome class outright; the
 *                      compiler wrote it, so this is authoritative
 *   node.durationId  → an outcome whose `delay` is that same id — which is how
 *                      a penalty node finds the outcome it serves
 *   node.watch       → the `contingency.ports` entry bound to that channel
 *   node.strobeName  → every field currently holding that strobe name
 *   node.band        → the topology knobs that shape that band
 *
 * `symbol` is deliberately not consulted. It is stable within a template
 * version and meaningless across one, and a UI that silently mis-attributes a
 * field after a template bump is worse than one that shows fewer fields.
 */

import type { SpecDocument, SpecGraph, SpecGraphEdge, SpecGraphNode } from "./types";

export type Selection =
  | { kind: "node"; index: number }
  | { kind: "edge"; index: number }
  | { kind: "band"; band: number }
  | null;

/** One document path plus the overlay key describing how to render it. */
export interface Anchor {
  /** Concrete path — `timing[3].ms` — for `getAt`/`setAt` and diagnostics. */
  path: string;
  /** Overlay key — `timing[].ms` — for the label and widget. */
  overlayKey: string;
}

export interface AnchorGroup {
  /** Section heading in the inspector. */
  title: string;
  /** One line saying why these fields are here. */
  why?: string | undefined;
  anchors: Anchor[];
}

export interface SelectionView {
  title: string;
  subtitle: string | null;
  /** Fields that produced the selection — the reason the inspector opened. */
  groups: AnchorGroup[];
  /** Topology knobs, when the selection is a band (or a node's band). */
  knobs: string[];
}

/**
 * The knobs that shape each band, in the order the band card reads them.
 *
 * This map is a PRESENTATION choice — which lane a knob belongs beside — and
 * the compiler's `capabilities().knobs` is the authority on which knobs exist.
 * They agree today; if a future template version adds one, `orphanKnobs()`
 * below is what stops it being silently uneditable.
 */
export const BAND_KNOBS: Record<number, string[]> = {
  1: ["topology.commit_hold"],
  2: ["topology.n_sampling_stages", "topology.retention_delay"],
  3: ["topology.response_mode", "topology.response_ports"],
  // Band 4 has no knobs of its own: which outcome classes exist is a
  // CONSEQUENCE of the other three, which is capabilities()'s whole argument
  // for being a function rather than a table.
  4: [],
};

/**
 * Knobs the compiler reports that no band claims.
 *
 * A template is versioned by file and a new version may declare a knob this
 * build's `BAND_KNOBS` has never heard of. Without this the knob would exist
 * in the schema, be required by the topology, and have no editing surface
 * anywhere — an invisible field is worse than a misplaced one, so it surfaces
 * on the outcome lane rather than nowhere.
 */
export function orphanKnobs(knobs: readonly string[]): string[] {
  const claimed = new Set(Object.values(BAND_KNOBS).flat());
  return knobs.filter((knob) => !claimed.has(`topology.${knob}`));
}

export const BAND_TITLES: Record<number, string> = {
  1: "Engagement",
  2: "Sampling",
  3: "Response",
  4: "Outcome",
};

/* --- the individual joins ------------------------------------------------ */

function timingRows(doc: SpecDocument): Array<{ id: string; index: number }> {
  const timing = doc["timing"];
  if (!Array.isArray(timing)) return [];
  return timing.flatMap((row, index) =>
    row !== null && typeof row === "object" && typeof (row as { id?: unknown }).id === "string"
      ? [{ id: (row as { id: string }).id, index }]
      : [],
  );
}

function record(doc: SpecDocument, path: readonly string[]): Record<string, unknown> {
  let node: unknown = doc;
  for (const step of path) {
    if (node === null || typeof node !== "object") return {};
    node = (node as Record<string, unknown>)[step];
  }
  return node !== null && typeof node === "object" && !Array.isArray(node)
    ? (node as Record<string, unknown>)
    : {};
}

/** The `timing` row declaring `id`, as its two editable fields. */
function timingAnchors(doc: SpecDocument, id: string | null): Anchor[] {
  if (!id) return [];
  const row = timingRows(doc).find((t) => t.id === id);
  if (!row) return [];
  return [
    { path: `timing[${row.index}].ms`, overlayKey: "timing[].ms" },
    { path: `timing[${row.index}].note`, overlayKey: "timing[].note" },
  ];
}

/** Every field of one outcome class. */
function outcomeAnchors(cls: string): Anchor[] {
  return ["trigger", "reward", "terminal", "delay", "strobe", "note"].map((field) => ({
    path: `contingency.outcome_map.${cls}.${field}`,
    overlayKey: `contingency.outcome_map.*.${field}`,
  }));
}

/** Every field of one port binding. */
function portAnchors(name: string): Anchor[] {
  return [
    "channel",
    "enter_code",
    "exit_code",
    "break_code",
    "error_code",
    "reward_line",
    "reward_duration",
    "reward_code",
    "reward_stop_code",
  ].map((field) => ({
    path: `contingency.ports.${name}.${field}`,
    overlayKey: `contingency.ports.*.${field}`,
  }));
}

/**
 * Outcome classes attributable to a node, by two independent joins.
 *
 * An outcome branch is several nodes long — a marker, a cue-off, a penalty
 * delay, a terminal — and only the last carries the `score:` edge. The delay
 * join is what reaches the rest of the chain: a penalty node's duration id IS
 * the outcome's `delay`, so the node that makes an operator wait 20 s and the
 * field setting that 20 s find each other through the document.
 */
function outcomeClassesFor(
  node: SpecGraphNode,
  graph: SpecGraph,
  doc: SpecDocument,
): string[] {
  const found = new Set<string>();
  for (const edge of graph.edges) {
    if (edge.src !== node.index) continue;
    const cls = scoredClass(edge);
    if (cls) found.add(cls);
  }
  if (node.durationId) {
    for (const cls of Object.keys(record(doc, ["contingency", "outcome_map"]))) {
      if (record(doc, ["contingency", "outcome_map", cls])["delay"] === node.durationId) {
        found.add(cls);
      }
    }
  }
  return [...found].sort();
}

/** `score:no_engage` → `no_engage`. Anything else is structural, not scoring. */
export function scoredClass(edge: SpecGraphEdge): string | null {
  const effect = edge.effect;
  return effect && effect.startsWith("score:") ? effect.slice("score:".length) : null;
}

/** Port bindings whose channel is one this node watches. */
function portsWatching(doc: SpecDocument, channels: readonly string[]): string[] {
  if (channels.length === 0) return [];
  return Object.keys(record(doc, ["contingency", "ports"])).filter((name) => {
    const channel = record(doc, ["contingency", "ports", name])["channel"];
    return typeof channel === "string" && channels.includes(channel);
  });
}

/**
 * Every field currently holding this strobe name.
 *
 * Deliberately a *search of the document*, and deliberately allowed to return
 * several: `WATER_POKE_L` is a port's `enter_code` and, through
 * `@ports[$ch].enter_code`, an outcome's strobe as well. Both are true, so both
 * are offered — as related fields, never as "the" field that caused the node.
 */
function strobeAnchors(doc: SpecDocument, strobeName: string | null): Anchor[] {
  if (!strobeName) return [];
  const out: Anchor[] = [];

  for (const [cls] of Object.entries(record(doc, ["contingency", "outcome_map"]))) {
    if (record(doc, ["contingency", "outcome_map", cls])["strobe"] === strobeName) {
      out.push({
        path: `contingency.outcome_map.${cls}.strobe`,
        overlayKey: "contingency.outcome_map.*.strobe",
      });
    }
  }

  for (const [name] of Object.entries(record(doc, ["contingency", "ports"]))) {
    const binding = record(doc, ["contingency", "ports", name]);
    for (const field of [
      "enter_code",
      "exit_code",
      "break_code",
      "error_code",
      "reward_code",
      "reward_stop_code",
    ]) {
      if (binding[field] === strobeName) {
        out.push({
          path: `contingency.ports.${name}.${field}`,
          overlayKey: `contingency.ports.*.${field}`,
        });
      }
    }
  }

  // Stimuli are a LIST addressed by index, even though the overlay keys them
  // `.*.` — the same split `SpecForm` already lives with (`by_id` rows over an
  // array). The concrete path has to be the index or `setAt` writes a new key.
  const stimuli = record(doc, ["contingency"])["stimuli"];
  if (Array.isArray(stimuli)) {
    for (const [index, entry] of stimuli.entries()) {
      if (entry === null || typeof entry !== "object") continue;
      if ((entry as Record<string, unknown>)["on_code"] === strobeName) {
        out.push({
          path: `contingency.stimuli[${index}].on_code`,
          overlayKey: "contingency.stimuli.*.on_code",
        });
      }
    }
  }

  return out;
}

/* --- the public entry point ---------------------------------------------- */

/**
 * The inspector's whole content for one selection.
 *
 * Empty groups are dropped rather than rendered as headings with nothing under
 * them: a node genuinely can be produced by no editable field — a zero-duration
 * marker node exists because the template pairs strobes (D2), and no amount of
 * spec editing moves it. Saying so honestly is better than an empty accordion.
 */
export function selectionView(
  selection: Selection,
  graph: SpecGraph | null,
  doc: SpecDocument,
): SelectionView | null {
  if (!selection) return null;

  if (selection.kind === "band") {
    return {
      title: `${selection.band} · ${BAND_TITLES[selection.band] ?? "Band"}`,
      subtitle: "Epoch",
      groups: [],
      knobs: BAND_KNOBS[selection.band] ?? [],
    };
  }

  if (!graph) return null;

  if (selection.kind === "edge") {
    const edge = graph.edges[selection.index];
    if (!edge) return null;
    const cls = scoredClass(edge);
    const from = graph.nodes[edge.src];
    const to = graph.nodes[edge.dst];
    return {
      title: `${edge.trigger}${edge.channel ? ` (${edge.channel})` : ""}`,
      subtitle:
        from && to ? `${sid(from.index)} ${from.label} → ${sid(to.index)} ${to.label}` : null,
      groups: cls
        ? [
            {
              title: `Outcome · ${cls}`,
              why: "This transition scores the trial. Scoring is an edge effect — inverting what an outcome means is a field here, never a different node.",
              anchors: outcomeAnchors(cls),
            },
          ]
        : [],
      knobs: [],
    };
  }

  const node = graph.nodes[selection.index];
  if (!node) return null;

  const groups: AnchorGroup[] = [];

  const timing = timingAnchors(doc, node.durationId);
  if (timing.length > 0) {
    groups.push({
      title: `Duration · ${node.durationId}`,
      why:
        node.durationMs === 0
          ? // A zero-duration node is not a state anyone waits in: it exists so
            // that two strobes emitted at one instant each get their own entry
            // and their own timestamp (D2). Raising this duration would insert
            // a real pause into every paired emission in the task.
            "This state exists to carry a second strobe at the same instant, not to take time. Its duration is shared by every such marker — raising it inserts a pause across the whole task."
          : "How long this state lasts. The id is shared, so editing it here moves every state that waits on it.",
      anchors: timing,
    });
  }

  for (const cls of outcomeClassesFor(node, graph, doc)) {
    groups.push({ title: `Outcome · ${cls}`, anchors: outcomeAnchors(cls) });
  }

  for (const port of portsWatching(doc, node.watch)) {
    groups.push({
      title: `Port · ${port}`,
      why: "This state is watching that channel, so its bindings decide what an entry here reports.",
      anchors: portAnchors(port),
    });
  }

  const strobe = strobeAnchors(doc, node.strobeName);
  if (strobe.length > 0) {
    groups.push({
      title: `Strobe · ${node.strobeName}`,
      why:
        strobe.length > 1
          ? "Several fields carry this code — the physical event is one thing reported from more than one place."
          : undefined,
      anchors: strobe,
    });
  }

  return {
    title: `${sid(node.index)} · ${node.label}`,
    subtitle: `${node.type}${node.silentByDesign ? " · silent by design" : ""}`,
    groups: dedupe(groups),
    knobs: BAND_KNOBS[node.band] ?? [],
  };
}

/**
 * The inverse: which nodes does this document path touch?
 *
 * Hovering a timing row lights every state that waits on it — which is the one
 * thing the graph can say that a form cannot, since a single `t_iti_correct`
 * may govern four states scattered across two bands.
 */
export function nodesForPath(
  path: string,
  graph: SpecGraph | null,
  doc: SpecDocument,
): Set<number> {
  const lit = new Set<number>();
  if (!graph) return lit;

  const timingMatch = /^timing\[(\d+)\]/.exec(path);
  if (timingMatch) {
    const row = timingRows(doc).find((t) => t.index === Number(timingMatch[1]));
    if (row) {
      for (const node of graph.nodes) if (node.durationId === row.id) lit.add(node.index);
    }
    return lit;
  }

  const outcomeMatch = /^contingency\.outcome_map\.([a-z_]+)/.exec(path);
  if (outcomeMatch) {
    const cls = outcomeMatch[1]!;
    for (const node of graph.nodes) {
      if (outcomeClassesFor(node, graph, doc).includes(cls)) lit.add(node.index);
    }
    return lit;
  }

  const portMatch = /^contingency\.ports\.([a-z_0-9]+)/.exec(path);
  if (portMatch) {
    const channel = record(doc, ["contingency", "ports", portMatch[1]!])["channel"];
    for (const node of graph.nodes) {
      if (typeof channel === "string" && node.watch.includes(channel)) lit.add(node.index);
    }
    return lit;
  }

  return lit;
}

/** `S07` — the id the listing prints and a node-placed diagnostic anchors on. */
export function sid(index: number): string {
  return `S${String(index).padStart(2, "0")}`;
}

function dedupe(groups: AnchorGroup[]): AnchorGroup[] {
  const seen = new Set<string>();
  return groups.filter((g) => {
    if (seen.has(g.title)) return false;
    seen.add(g.title);
    return true;
  });
}

/**
 * How every trial ends, read off the compiled machine.
 *
 * WHY THIS IS NOT "BAND 4". The four bands are descriptive, and the outcome
 * band is the one whose membership is an accident of emission order rather than
 * of meaning: `four_epoch`'s `outcome_chain`/`_sink`/`_score` memoise per class
 * and stamp whatever band was current when a class was FIRST referenced. So on
 * a plain 2AFC the no-engage penalty, the invalid score node and the
 * `TRIAL_REPEAT` terminal are all band 1, `TRIAL_ADVANCE` and the incorrect
 * score node are band 3, and band 4 holds only the reward path. Worse, a
 * go/no-go task has NO band 4 at all — `b.band(Band.OUTCOME)` sits inside the
 * `if correct.reward:` branch it never enters.
 *
 * Filtering on `band === 4` therefore draws a different, wrong picture for
 * every topology. What is stable is the compiler's own `score:<class>` edge
 * effect, so that is what this walks.
 *
 * PURE, AND `SpecGraph`-ONLY. No document, no React. A structural route is
 * strictly stronger than the document join `selection.ts` uses for the inverse
 * question: `wrong` and `omission` both delay through `t_pen_error`, so joining
 * a node's `durationId` against `outcome_map.*.delay` returns BOTH classes for
 * either node — right for "which fields relate to this node", wrong for "draw
 * this class's chain".
 */

import { scoredClass } from "./selection";
import type { SpecGraph, SpecGraphEdge } from "./types";

export interface OutcomeRoute {
  cls: string;
  /** The spine node this branch leaves from; null when several feed it. */
  origin: number | null;
  originEdge: SpecGraphEdge | null;
  /** mark → cue off → penalty, in flow order. Last element is `penalty`. */
  chain: number[];
  /** The node the trial actually waits in before closing. */
  penalty: number;
  scoreEdge: SpecGraphEdge;
  /** The zero-duration node carrying the trial's scoring strobe; null when the
   * class routes straight to a terminal (the TRIAL_INVALID case). */
  scoreNode: number | null;
  terminal: number;
  terminalKind: "advance" | "repeat";
  /** The guarded second edge out of the score node — the correction budget. */
  correctionEdge: SpecGraphEdge | null;
}

const isReturn = (e: SpecGraphEdge) => e.trigger === "ADVANCE" || e.trigger === "REPEAT";

/** Every outcome class the compiled machine produces, in class order. */
export function outcomeRoutes(graph: SpecGraph): OutcomeRoute[] {
  const out = (i: number) =>
    graph.edges.filter((e) => !isReturn(e) && e.src === i);
  const into = (i: number) =>
    graph.edges.filter((e) => !isReturn(e) && e.dst === i);

  const routes: OutcomeRoute[] = [];
  const seen = new Set<string>();

  for (const scoreEdge of graph.edges) {
    const cls = scoredClass(scoreEdge);
    // One `score:` edge per class, guaranteed by `outcome_chain`'s own memo.
    // If a future template emits two, the first wins and the rest are ignored
    // rather than silently drawn on top of each other.
    if (cls === null || seen.has(cls)) continue;
    seen.add(cls);

    const penalty = scoreEdge.src;

    /*
     * Walk BACKWARDS to the head of the branch.
     *
     * Structural only — never a symbol prefix, which `selection.ts` forbids
     * for the reason that a symbol is stable within a template version and
     * meaningless across one. The stop condition is "the predecessor forks, or
     * is not a zero-duration DELAY", which is exactly what distinguishes a
     * relay in the chain from the state the branch hangs off.
     */
    const chain = [penalty];
    let cur = penalty;
    for (;;) {
      const preds = into(cur);
      if (preds.length !== 1) break;
      const p = preds[0]!.src;
      const node = graph.nodes[p];
      if (!node) break;
      if (out(p).length !== 1) break;
      if (node.type !== "DELAY" || (node.durationMs ?? 0) !== 0) break;
      chain.unshift(p);
      cur = p;
    }
    // `hold_break` legitimately has several predecessors — one chain serves the
    // commitment hold, every sampling hold and every gap — so a null origin is
    // honest rather than a failure, and those edges surface as inbound stubs.
    const preds = into(chain[0]!);
    const origin = preds.length === 1 ? preds[0]!.src : null;
    const originEdge = preds.length === 1 ? preds[0]! : null;

    /*
     * The score node, then the terminal.
     *
     * A class whose terminal is TRIAL_INVALID routes STRAIGHT to the repeat
     * sink — `_score` returns `_sink("repeat")` directly, because an aborted
     * trial has no score of its own to strobe.
     */
    const d = scoreEdge.dst;
    let scoreNode: number | null = null;
    let terminal = d;
    let correctionEdge: SpecGraphEdge | null = null;
    if (graph.nodes[d]?.type !== "TERMINAL") {
      scoreNode = d;
      const outs = out(d);
      // Keyed on the GUARD rather than on edge order. The order is a firmware
      // requirement (tgResolveEdge is first-match-wins, so the default must be
      // last), but keying on position would break the day anything reorders.
      correctionEdge = outs.find((e) => e.guard !== null) ?? null;
      terminal = (outs.find((e) => e.guard === null) ?? outs[0])?.dst ?? d;
    }

    routes.push({
      cls,
      origin,
      originEdge,
      chain,
      penalty,
      scoreEdge,
      scoreNode,
      terminal,
      terminalKind: "advance",
      correctionEdge,
    });
  }

  const kind = terminalKinds(graph, routes);
  return routes
    .map((r) => ({ ...r, terminalKind: kind.get(r.terminal) ?? "advance" }))
    .sort((a, b) => a.cls.localeCompare(b.cls));
}

/**
 * Which terminal is ADVANCE and which is REPEAT, structurally.
 *
 * The guarded edge out of a score node is the correction branch and goes to the
 * repeat sink; the unguarded default goes to advance. `node.label` says
 * "TRIAL_REPEAT"/"TRIAL_ADVANCE" and is the right thing to PRINT, but a name
 * join is not the right thing to classify on — so the label is only consulted
 * when no score node forks anywhere, which is the all-invalid graph.
 */
function terminalKinds(
  graph: SpecGraph,
  routes: OutcomeRoute[],
): Map<number, "advance" | "repeat"> {
  const kinds = new Map<number, "advance" | "repeat">();
  for (const route of routes) {
    if (route.correctionEdge !== null) {
      kinds.set(route.correctionEdge.dst, "repeat");
      kinds.set(route.terminal, "advance");
    }
  }
  for (const node of graph.nodes) {
    if (node.type !== "TERMINAL" || kinds.has(node.index)) continue;
    kinds.set(node.index, node.strobeName === "INVALID_TRIAL" ? "repeat" : "advance");
  }
  return kinds;
}

/**
 * Every node the outcome picture draws.
 *
 * The ORIGINS are deliberately excluded — they are the response window, the
 * engagement window, the sampling hold, and pulling them in would drag most of
 * the machine along. They arrive as inbound stubs instead ("TIMEOUT ← response
 * · S14"), which is the sentence the Score step actually wants.
 */
export function outcomeScope(graph: SpecGraph): Set<number> {
  const scope = new Set<number>();
  for (const route of outcomeRoutes(graph)) {
    for (const i of route.chain) scope.add(i);
    if (route.scoreNode !== null) scope.add(route.scoreNode);
    scope.add(route.terminal);
    if (route.correctionEdge !== null) scope.add(route.correctionEdge.dst);
  }
  return scope;
}

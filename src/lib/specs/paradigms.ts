/**
 * The paradigm catalogue — what kind of task this is, as opposed to which
 * file it came from.
 *
 * A PARADIGM IS A SHAPE, NOT A SPEC ID. `grgl_2odor` is not its own paradigm;
 * it is the canonical variant of two-alternative forced choice, and so are
 * `shaping_gr` and `shaping_gr_ez` — all three compile to the same 26-state
 * machine, and `specs.diff` between them shows NO structural hunks, which §6
 * already names as the test of a `derived_from` claim. Listing them as three
 * paradigms would teach an operator that a timing ramp is a different kind of
 * task, which is exactly the misconception the four-layer model exists to
 * remove.
 *
 * MATCHING IS BY FINGERPRINT, NEVER BY SPEC ID. That is what lets a user's own
 * `my_task_3` be labelled 2AFC without anyone registering it, and lets a spec
 * that matches nothing read honestly as "Custom" instead of being forced into
 * the nearest name.
 *
 * RECIPES are the other half. The bundled specs live in the vendored tree,
 * which is byte-identical to Task-Graph and drift-tested, so a genuinely new
 * paradigm cannot arrive as a new file here. A recipe is a bundled base plus a
 * fixed sequence of the SAME structural ops the editor exposes — which is not
 * the blank-skeleton generator docs/specs.md §3 forbids, because it is a
 * sequence of edits to a spec that already compiled, not a second definition
 * of what a minimal legal spec is. Every step maintains the ops' invariants
 * and the live compile confirms each one on screen.
 */

import { topologyOf } from "./document";
import type { OpInvocation } from "./operations";
import type { SpecDocument, SpecEntry } from "./types";

export interface Fingerprint {
  nSamplingStages: number;
  retentionDelay: boolean;
  responseMode: string;
  nResponsePorts: number;
  commitHold: boolean;
  /** `outcome_map.correct.reward` is non-null — the one contingency field
   * that changes the graph's shape (it adds or removes the delivery PULSE and
   * the consumption WAIT_EXIT). */
  rewarded: boolean;
}

export interface ParadigmVariant {
  specId: string;
  label: string;
  note: string;
}

export interface Paradigm {
  id: string;
  name: string;
  /** One line: what this paradigm lets you ask an animal that the others don't. */
  affords: string;
  fingerprint: Fingerprint;
  variants: ParadigmVariant[];
}

export interface ParadigmRecipe {
  id: string;
  name: string;
  affords: string;
  /** A bundled spec id — the recipe never starts from nothing. */
  base: string;
  steps: OpInvocation[];
  /** What the steps change, in the operator's words, for the card. */
  changes: string;
}

const AFC2: Fingerprint = {
  nSamplingStages: 1,
  retentionDelay: false,
  responseMode: "n_alternative",
  nResponsePorts: 2,
  commitHold: true,
  rewarded: true,
};

export const PARADIGMS: Paradigm[] = [
  {
    id: "two_afc",
    name: "Two-alternative forced choice",
    affords:
      "One stimulus, two ports, reward at the correct one. The discriminandum is which stimulus was presented.",
    fingerprint: AFC2,
    variants: [
      {
        specId: "grgl_2odor",
        label: "GRGL 2-odor (canonical)",
        note: "The equivalence target — every value traced to its firmware source.",
      },
      {
        specId: "shaping_gr",
        label: "Shaping, go right",
        note: "Same machine, different timings: a 5-row ramp from a 10 ms hold to the full task.",
      },
      {
        specId: "shaping_gr_ez",
        label: "Shaping, go right (eased)",
        note: "Same machine again — the ramp stretched for an animal struggling with the standard one.",
      },
    ],
  },
  {
    id: "go_nogo",
    name: "Go / no-go",
    affords:
      "One stimulus; success is withholding for the whole window, and any port entry is a false alarm. Measures impulse control, not discrimination between ports.",
    fingerprint: {
      nSamplingStages: 1,
      retentionDelay: false,
      responseMode: "go_nogo",
      nResponsePorts: 2,
      commitHold: true,
      rewarded: false,
    },
    variants: [
      {
        specId: "gonogo",
        label: "Go/no-go withhold",
        note: "Window expiry scores correct — the inversion is one edge, and both wells stay live.",
      },
    ],
  },
  {
    id: "sequence_retention",
    name: "Sequence with retention",
    affords:
      "Two stimuli in order with an unfilled gap, then a delay before the response window. Order is the discriminandum and the delay is the working-memory load.",
    fingerprint: {
      nSamplingStages: 2,
      retentionDelay: true,
      responseMode: "n_alternative",
      nResponsePorts: 2,
      commitHold: true,
      rewarded: true,
    },
    variants: [
      {
        specId: "seq2_retention",
        label: "Two-odor sequence",
        note: "A→B goes right, B→A goes left; the sampling band unrolls per stage.",
      },
    ],
  },
];

export const RECIPES: ParadigmRecipe[] = [
  {
    id: "unrewarded_2afc",
    name: "Unrewarded two-alternative choice",
    affords:
      "The same discrimination with no fluid: the choice is recorded but nothing is delivered. For probe blocks and extinction.",
    base: "grgl_2odor",
    steps: [{ op: "setCorrectRewarded", on: false }],
    changes: "Drops the reward delivery and consumption states from the outcome epoch.",
  },
  {
    id: "seq3_retention",
    name: "Three-stimulus sequence",
    affords:
      "A third element in the chain, so the sequence is longer than working memory comfortably holds.",
    base: "seq2_retention",
    steps: [{ op: "addStimulus" }, { op: "addSamplingStage" }],
    changes: "Adds a stimulus and unrolls the sampling band to three stages with a second gap.",
  },
  {
    id: "shaping_no_stimulus",
    name: "Pure shaping, no stimulus",
    affords:
      "Engagement and responding with nothing to discriminate — the first thing a naive animal learns.",
    base: "shaping_gr",
    steps: [{ op: "removeSamplingStage" }],
    changes: "Removes the sampling stage entirely; the trial goes engagement → response.",
  },
];

export function fingerprintOf(doc: SpecDocument): Fingerprint {
  const t = topologyOf(doc) ?? {};
  const ports = t["response_ports"];
  const contingency = doc["contingency"];
  const om =
    contingency !== null && typeof contingency === "object"
      ? (contingency as Record<string, unknown>)["outcome_map"]
      : null;
  const correct =
    om !== null && typeof om === "object"
      ? (om as Record<string, unknown>)["correct"]
      : null;
  const reward =
    correct !== null && typeof correct === "object"
      ? (correct as Record<string, unknown>)["reward"]
      : null;

  return {
    nSamplingStages: typeof t["n_sampling_stages"] === "number" ? t["n_sampling_stages"] : 0,
    retentionDelay: t["retention_delay"] === true,
    responseMode: typeof t["response_mode"] === "string" ? t["response_mode"] : "",
    nResponsePorts: Array.isArray(ports) ? ports.length : 0,
    commitHold: t["commit_hold"] !== false,
    rewarded: reward !== null && reward !== undefined,
  };
}

function sameShape(a: Fingerprint, b: Fingerprint): boolean {
  return (
    a.nSamplingStages === b.nSamplingStages &&
    a.retentionDelay === b.retentionDelay &&
    a.responseMode === b.responseMode &&
    a.nResponsePorts === b.nResponsePorts &&
    a.commitHold === b.commitHold &&
    a.rewarded === b.rewarded
  );
}

/** The paradigm this document's SHAPE belongs to, or null for a custom one. */
export function paradigmFor(doc: SpecDocument): Paradigm | null {
  const fp = fingerprintOf(doc);
  return PARADIGMS.find((p) => sameShape(p.fingerprint, fp)) ?? null;
}

/**
 * The library's entries grouped by paradigm, canonical variant first, with
 * anything unrecognised collected under "Custom".
 *
 * Entries carry no topology beyond `template`/`templateVersion` on the wire,
 * so grouping the LIST uses the catalogue's declared variant ids; a document
 * in hand is fingerprinted instead. Both agree for the bundled corpus, and
 * the fingerprint is the authority when they could differ.
 */
export function groupByParadigm(
  specs: SpecEntry[],
): Array<{ paradigm: Paradigm | null; entries: SpecEntry[] }> {
  const byId = new Map(specs.map((s) => [s.specId, s]));
  const claimed = new Set<string>();
  const groups: Array<{ paradigm: Paradigm | null; entries: SpecEntry[] }> = [];

  for (const paradigm of PARADIGMS) {
    const entries: SpecEntry[] = [];
    for (const variant of paradigm.variants) {
      const entry = byId.get(variant.specId);
      if (entry) {
        entries.push(entry);
        claimed.add(entry.specId);
      }
    }
    if (entries.length > 0) groups.push({ paradigm, entries });
  }

  const rest = specs.filter((s) => !claimed.has(s.specId));
  if (rest.length > 0) groups.push({ paradigm: null, entries: rest });
  return groups;
}

/** The catalogue's own note for a bundled variant, when it has one. */
export function variantNote(specId: string): string | null {
  for (const paradigm of PARADIGMS) {
    const variant = paradigm.variants.find((v) => v.specId === specId);
    if (variant) return variant.note;
  }
  return null;
}

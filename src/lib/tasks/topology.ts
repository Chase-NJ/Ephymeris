/**
 * The task's state machine, derived from a Task Profile's declared strobe names.
 *
 * WHY DERIVED RATHER THAN AUTHORED. Every behaviour sketch in this lab shares
 * one `runTrial()` in `BehaviorBox.h`, so the topology is genuinely identical
 * across them; what differs is which branches exist, and the strobe names a
 * profile declares say exactly that. Deriving is the accurate model, not a
 * shortcut. It also costs nothing: a `states` block in `task.json` would change
 * that profile's `profile_hash`, which is the key Analytics groups runs by
 * (`analytics/view.ts`'s `runsInProfile`), so adding one would split every
 * sketch's historical runs from its future runs on every plot — with nothing to
 * recompute the old hashes. A visualization must not cost that.
 *
 * Keyed off strobe **names**, never raw codes — the same rule `liveTrials.ts`,
 * `metrics.py` and `derive.py` already follow. A code number means nothing
 * without the map that names it.
 *
 * The shape, for a two-odor discrimination task:
 *
 *   Light → Poke →┬ Odor 1 ┬→ Unpoke → Light off → Answer →┬ Reward
 *                 └ Odor 3 ┘                               ├ No hold
 *                                                          ├ Wrong well
 *                                                          └ No answer  → ITI
 *
 * **Left-to-right is real time, not narrative order.** The condition fan-out
 * sits at odor delivery because that is where the firmware strobes the odor-on
 * code — after `ODOR_POKE` and after the pre-odor hold verifies, when the vacuum
 * closes and odor reaches the nose (`BehaviorBox.h`'s `runTrial()`). The odor is
 * primed well before that and silently, so there is nothing earlier to draw.
 *
 * Pure: no React, no store, no fetch. `TaskGraph` draws what this returns, and
 * `TaskRail` draws the same nodes as a strip.
 *
 * NOT to be confused with `lib/specs/` and its `SpecGraph`: that is the
 * compiled MACHINE graph a task spec produces — what the interpreter executes.
 * This one describes what an animal does. Two models, no shared code, on
 * purpose (`docs/specs.md` §5).
 */

import type { TaskProfile } from "@/lib/ws/protocol";

// --- the model -------------------------------------------------------------

/**
 * `state` — somewhere the trial passes through.
 * `outcome` — how an administered trial resolved; coloured to match the
 *   analytics outcome palette so the graph and `OutcomeMix` agree at a glance.
 * `abort` — the trial ended without an answer, and is re-presented.
 */
export type NodeKind = "state" | "outcome" | "abort";

export type EdgeKind = "advance" | "choice" | "abort" | "error" | "reward" | "return";

/*
 * THE MODEL CARRIES NO COUNTS, DELIBERATELY.
 *
 * An earlier version tagged each edge with the `derive.py` bucket that would
 * fill it, so a run's figures could be drawn onto the diagram. Nothing ever
 * passed them, because the only place a graph and a live run coexist is
 * Mission Control — and a partial mid-session tally is exactly the number that
 * must not be shown: it reads as a result while the trials it summarises are
 * still arriving. Analytics owns recorded figures, on panels built to caveat
 * them.
 *
 * So the machinery is gone rather than dormant. If per-edge figures are ever
 * wanted, they belong to a finished run and should arrive as a separate
 * overlay, not as an optional field every edge in this file has to think about.
 */

export interface TaskNode {
  id: string;
  label: string;
  kind: NodeKind;
  /** Left-to-right progression through a trial. Authored — see the layout note. */
  column: number;
  /** Vertical slot within the column. Authored for the spine, computed for fan-outs. */
  row: number;
  /** One line of detail, shown on hover. */
  detail?: string;
  /**
   * Where the label sits. Layout intent, so it lives with the layout data
   * rather than being re-derived from a node's kind at render time — the
   * outcome column stacks too tightly for labels underneath, and the ITI sits
   * beside that stack with no room to its right.
   */
  labelAnchor?: "below" | "right" | "above";
  /** Config groups whose parameters govern this state — drives the tile↔graph link. */
  governedBy: readonly string[];
  /** Strobe names that put the live token here. */
  entryNames: readonly string[];
  /**
   * True when the firmware's own post-outcome delay starts at this node's
   * strobe and nothing else is emitted until that delay ends.
   *
   * The live token advances itself to the ITI shortly after landing here
   * (`useLiveNode`), because otherwise it sits on the outcome for the whole
   * timeout — twenty seconds of "Wrong well" on a trial that is long over and
   * a box that is, in fact, serving its intertrial delay.
   */
  settlesToIti?: boolean;
}

export interface TaskEdge {
  id: string;
  from: string;
  to: string;
  label?: string;
  kind: EdgeKind;
}

export interface TaskGraphModel {
  nodes: TaskNode[];
  edges: TaskEdge[];
  /** One per odor condition the profile declares. Empty on a profile with none. */
  conditions: Array<{
    id: string;
    label: string;
    /** The `liveMetrics` label, when one scores this condition. */
    metricLabel: string | null;
    strobeName: string;
  }>;
  /** False when the profile declares too little to draw anything honest. */
  usable: boolean;
}

// --- layout ----------------------------------------------------------------

/**
 * Columns are authored constants, rows are computed for the fan-outs.
 *
 * A trial's progression is fixed and known, so a layout engine could only find
 * a worse arrangement of a shape we already have — the same call `zodiac.ts`
 * makes for the constellations ("Data, not code, on purpose"). Only the
 * condition fan-out varies (one row for shaping, two for a discrimination
 * task), and that is arithmetic rather than layout.
 *
 * Coordinates are in a 100-wide frame; `frameFor()` refits the viewBox, so only
 * proportions matter here.
 */
const COL = {
  start: 6,
  awaitPoke: 24,
  odor: 42,
  sample: 60,
  respond: 78,
  choice: 96,
  outcome: 116,
  iti: 140,
} as const;

/**
 * Aborts sit below the spine, outcomes fan around it.
 *
 * The three aborts step progressively deeper so that the edges collecting them
 * into `Repeat` — which sits back at the shallowest row — pass *over* the aborts
 * they don't touch. On one shared row those edges ran straight through the
 * intervening nodes, drawing what looked like a chain (no poke → let go → left
 * early → repeat) out of three independent branches.
 */
const ABORT_ROW = 2.4;
const ABORT_STEP = 0.5;

/** Vertical centre of the spine, and the gap between stacked branch rows. */
const SPINE_ROW = 0;
const ROW_GAP = 1;

// --- config groups ---------------------------------------------------------

/**
 * Parameter tiles, ordered the way the parameters take effect during a trial
 * rather than by authored order — which is what makes the tiles "build off each
 * other" instead of being an arbitrary list. A group absent from a profile is
 * skipped; a group this list doesn't know appends at the end, so a future
 * profile inventing one still renders.
 *
 * These strings are the `group` values authored in `task.json`. They must stay
 * in step with the `governedBy` entries below, which is why both live here.
 */
export const GROUP_ORDER: readonly string[] = [
  "Session",
  "Trial pool",
  "Trial timing",
  "Holds & windows",
  "Stage 0",
  "Stage 1",
  "Stage 2",
  "Stage 3",
  "Stage 4",
  "Correction trials",
  "Abstention penalty",
  "Reward volume",
  "Anti-bias selection",
];

/**
 * The groups the mapping step promotes to the top of per-box tuning.
 *
 * These are the values the lab actually turns on the fly, animal by animal,
 * session by session — a correction budget opened for a rat that has started
 * side-biasing, the lazy-penalty escalation armed for one that has stopped
 * initiating. Everything else in a profile is set once on the Sketches page
 * and then left alone, so "first" here is decided by frequency of change,
 * not by trial order.
 *
 * An app-level registry (like `GROUP_ORDER` above) rather than a `task.json`
 * flag, deliberately: any new key in a profile changes its `profile_hash` and
 * permanently splits a sketch's historical runs from its future ones in
 * Analytics. A profile that declares neither group simply gets no quick-tune
 * section.
 */
export const QUICK_TUNE_GROUPS: readonly string[] = [
  "Correction trials",
  "Abstention penalty",
];

/** Sort a profile's declared groups into trial order, unknown ones last. */
export function orderGroups(groups: Iterable<string>): string[] {
  const rank = new Map(GROUP_ORDER.map((name, index) => [name, index]));
  return [...groups].sort((a, b) => {
    const ra = rank.get(a) ?? Number.MAX_SAFE_INTEGER;
    const rb = rank.get(b) ?? Number.MAX_SAFE_INTEGER;
    return ra !== rb ? ra - rb : a.localeCompare(b);
  });
}

/** The stage groups govern the four ramped holds, so they follow them around. */
const STAGES = ["Holds & windows", "Stage 0", "Stage 1", "Stage 2", "Stage 3", "Stage 4"];

// --- derivation ------------------------------------------------------------

/** Uppercased strobe names a profile declares. */
function declaredNames(profile: TaskProfile | null): Set<string> {
  const names = new Set<string>();
  for (const name of Object.values(profile?.strobes ?? {})) {
    names.add(String(name).toUpperCase());
  }
  return names;
}

/**
 * The odor conditions the task presents, in authored order.
 *
 * `liveMetrics` is the only ordered structure in a profile and its order is
 * already load-bearing elsewhere (`data.md` §11.1), so it names the
 * conditions when present. A profile with strobes but no metrics still draws
 * its odor rows, just labelled by strobe name.
 */
function conditionsOf(
  profile: TaskProfile | null,
  names: Set<string>,
): TaskGraphModel["conditions"] {
  const odorNames = [...names]
    .filter((name) => /^ODOR_\d+_ON$/.test(name))
    .sort((a, b) => odorIndex(a) - odorIndex(b));
  if (odorNames.length === 0) return [];

  const byCode = new Map(
    Object.entries(profile?.strobes ?? {}).map(([code, name]) => [
      String(name).toUpperCase(),
      Number(code),
    ]),
  );
  const labelled = new Map<string, string>();
  for (const metric of profile?.liveMetrics ?? []) {
    for (const [name, code] of byCode) {
      if (code === metric.triggerCode) labelled.set(name, metric.label);
    }
  }

  // Only the odors a metric actually names, when any are named. A sketch
  // declares the whole six-odor vocabulary and presents two of them; drawing
  // all six would invent four branches the animal never sees.
  const declared = labelled.size > 0 ? odorNames.filter((n) => labelled.has(n)) : odorNames;
  return declared.map((name) => ({
    id: `odor-${odorIndex(name)}`,
    // The odor, not the metric's formula. "P(R | Odor 1)" is what the metric is
    // called; on the graph it is a node the animal passes through, and the
    // formula belongs in the hover detail where there is room for it.
    label: `Odor ${odorIndex(name)}`,
    metricLabel: labelled.get(name) ?? null,
    strobeName: name,
  }));
}

/**
 * Strobe names a `liveMetrics` entry actually scores.
 *
 * The strobes map is the *shared* vocabulary every sketch mirrors, not a
 * statement of what this one presents; `liveMetrics` is the closest thing to
 * that statement the profile has.
 */
function scoredNames(profile: TaskProfile | null): Set<string> {
  const nameOf = new Map(
    Object.entries(profile?.strobes ?? {}).map(([code, name]) => [
      Number(code),
      String(name).toUpperCase(),
    ]),
  );
  const out = new Set<string>();
  for (const metric of profile?.liveMetrics ?? []) {
    for (const code of [metric.triggerCode, metric.successCode, metric.alternateCode]) {
      const name = nameOf.get(code);
      if (name) out.add(name);
    }
  }
  return out;
}

function odorIndex(name: string): number {
  return Number(/^ODOR_(\d+)_ON$/.exec(name)?.[1] ?? 0);
}

/** Rows centred on the spine: 1 → [0], 2 → [-0.5, +0.5], 3 → [-1, 0, +1]. */
function centredRows(count: number, gap = ROW_GAP): number[] {
  return Array.from({ length: count }, (_, i) => (i - (count - 1) / 2) * gap);
}

/**
 * Build the graph for one profile.
 *
 * Every node and edge is gated on the names the profile declares, so a profile
 * that never presents a no-go trial simply has no withhold arm, and a utility
 * profile with no behavioural vocabulary at all comes back `usable: false`
 * rather than as a broken skeleton.
 */
export function taskGraph(profile: TaskProfile | null): TaskGraphModel {
  const names = declaredNames(profile);
  const has = (name: string) => names.has(name);
  const conditions = conditionsOf(profile, names);
  const scored = scoredNames(profile);

  const nodes: TaskNode[] = [];
  const edges: TaskEdge[] = [];
  const node = (n: TaskNode) => {
    nodes.push(n);
    return n.id;
  };
  const edge = (e: TaskEdge) => edges.push(e);

  // A profile needs at least a trial light and one well to describe a trial.
  const usable =
    has("LIGHTS_ON") && (has("WATER_POKE_L") || has("WATER_POKE_R") || has("WATER_POKE_NONE"));
  if (!usable) return { nodes: [], edges: [], conditions, usable: false };

  // --- the spine -----------------------------------------------------------
  node({
    id: "start",
    label: "Light",
    kind: "state",
    column: COL.start,
    row: SPINE_ROW,
    detail: "Odor primed, then the trial light comes on.",
    governedBy: ["Trial timing", "Session", "Trial pool"],
    entryNames: ["LIGHTS_ON"],
  });

  node({
    id: "await-poke",
    label: "Poke",
    kind: "state",
    column: COL.awaitPoke,
    row: SPINE_ROW,
    detail: "The animal breaks the odor-port beam and holds.",
    governedBy: STAGES,
    entryNames: ["ODOR_POKE"],
  });
  edge({
    id: "e-start-poke",
    from: "start",
    to: "await-poke",
    label: "pokes",
    kind: "advance",
  });

  // --- failure to initiate -------------------------------------------------
  if (has("LAZY_RAT")) {
    node({
      id: "lazy",
      label: "No poke",
      kind: "abort",
      column: COL.awaitPoke,
      row: ABORT_ROW,
      detail: "The odor-port window elapsed with no poke. The trial is re-presented.",
      governedBy: ["Abstention penalty", ...STAGES],
      entryNames: ["LAZY_RAT"],
    });
    edge({
      id: "e-start-lazy",
      from: "start",
      to: "lazy",
      label: "window elapses",
      kind: "abort",
    });
  }

  // --- odor delivery + the condition fan-out -------------------------------
  /*
   * The fan-out is HERE, at delivery, not at the choice. The odor-on code is
   * strobed once the pre-odor hold clears and the vacuum closes, so this is the
   * moment the condition becomes a fact about the trial — drawing the conditions
   * to the right of the withdrawal would put them after an event they precede.
   *
   * Each arm claims its own strobe name, so the live token names which odor is
   * being delivered right now. (Nothing is ambiguous about that: one name, one
   * node.) A profile with no odor conditions at all — no `ODOR_<n>_ON` scored by
   * a metric — keeps a single generic node instead, and a shaping task with one
   * condition is a fan-out of one, which is why `singleArm` is `<= 1`.
   */
  const odorArms: string[] = [];
  const singleArm = conditions.length <= 1;
  if (conditions.length > 0) {
    const armRows = centredRows(conditions.length, 1.6);
    conditions.forEach((condition, index) => {
      odorArms.push(
        node({
          id: condition.id,
          label: condition.label,
          kind: "state",
          column: COL.odor,
          row: armRows[index] ?? SPINE_ROW,
          detail: condition.metricLabel
            ? `${condition.metricLabel} — trials opened by ${condition.strobeName}.`
            : `Trials opened by ${condition.strobeName}.`,
          // Which odor is presented is the selection policies' doing; getting
          // this far is the holds'.
          governedBy: ["Trial pool", "Anti-bias selection", "Correction trials", ...STAGES],
          entryNames: [condition.strobeName],
        }),
      );
    });
  } else {
    odorArms.push(
      node({
        id: "odor",
        label: "Odor",
        kind: "state",
        column: COL.odor,
        row: SPINE_ROW,
        detail: "Pre-odor hold cleared: the vacuum closes and odor reaches the port.",
        governedBy: STAGES,
        entryNames: [],
      }),
    );
  }
  /*
   * A fan-out edge is labelled only when there is one arm: N copies of "holds"
   * stacked around a fan-out is clutter, and it collided with the lower arm's
   * own name. What the transition means is on the node it arrives at.
   */
  const fanEdge = (label: string) => (singleArm ? { label } : {});
  for (const arm of odorArms) {
    edge({
      id: `e-poke-${arm}`,
      from: "await-poke",
      to: arm,
      kind: "advance",
      ...fanEdge("holds"),
    });
  }

  /*
   * ODOR_UNPOKE_EARLY is ONE code for TWO firmware edges — releasing before
   * odor delivery, and releasing during sampling. They are distinguishable only
   * by whether an odor-on code preceded them, which is exactly how `derive.py`
   * separates them: the engagement ladder's two gaps. Both edges are drawn, and
   * each takes its count from the matching gap.
   */
  if (has("ODOR_UNPOKE_EARLY")) {
    node({
      id: "abort-pre-odor",
      label: "Let go",
      kind: "abort",
      column: COL.odor,
      row: ABORT_ROW + ABORT_STEP,
      detail: "Released before the pre-odor hold cleared — no odor was delivered.",
      governedBy: STAGES,
      entryNames: [],
    });
    edge({
      id: "e-poke-abort",
      from: "await-poke",
      to: "abort-pre-odor",
      label: "releases early",
      kind: "abort",
    });

    node({
      id: "abort-sampling",
      label: "Left early",
      kind: "abort",
      column: COL.sample,
      row: ABORT_ROW + ABORT_STEP * 2,
      detail: "Odor was delivered, but the animal left before sampling completed.",
      governedBy: STAGES,
      entryNames: [],
    });
    for (const arm of odorArms) {
      edge({
        id: `e-${arm}-abort`,
        from: arm,
        to: "abort-sampling",
        kind: "abort",
        ...fanEdge("leaves early"),
      });
    }
  }

  node({
    id: "sample",
    label: "Unpoke",
    kind: "state",
    column: COL.sample,
    row: SPINE_ROW,
    detail: "Odor sampled to completion and the animal withdraws from the port.",
    governedBy: STAGES,
    entryNames: ["ODOR_UNPOKE"],
  });
  for (const arm of odorArms) {
    edge({
      id: `e-${arm}-sample`,
      from: arm,
      to: "sample",
      kind: "advance",
      ...fanEdge("samples"),
    });
  }

  // --- the response window -------------------------------------------------
  /*
   * The trial light going out is what separates presentation from response: the
   * firmware writes it low immediately after the withdrawal, and only then does
   * `checkResponse()` start watching the wells for the poll window's duration.
   * Without this node the graph had nowhere to say "the animal is answering",
   * and the live token spent that whole stretch on Unpoke.
   *
   * The code is emitted on all four paths through a trial, which is why it
   * claimed no node before. It can safely claim this one: `liveNodeId` walks
   * newest-first, and each abort strobes ODOR_UNPOKE_EARLY or LAZY_RAT and then
   * INVALID_TRIAL straight after its LIGHTS_OFF, so an aborted trial resolves to
   * `repeat`. The administered path is the only one where LIGHTS_OFF stays the
   * newest code for any length of time — and that length is the response window
   * this node names.
   */
  const answerFrom = has("LIGHTS_OFF") ? "lights-off" : "sample";
  if (has("LIGHTS_OFF")) {
    node({
      id: "lights-off",
      label: "Light off",
      kind: "state",
      column: COL.respond,
      row: SPINE_ROW,
      detail: "The trial light goes out: the presentation window closes and the response window opens.",
      // The response window (fluidWellPoll) is one of the four ramped values.
      governedBy: STAGES,
      entryNames: ["LIGHTS_OFF"],
    });
    edge({ id: "e-sample-lights-off", from: "sample", to: "lights-off", kind: "advance" });
  }

  // --- the choice ----------------------------------------------------------
  node({
    id: "choice",
    label: "Answer",
    kind: "state",
    column: COL.choice,
    row: SPINE_ROW,
    detail: "The animal answers at one of the fluid wells.",
    governedBy: [...STAGES, "Correction trials"],
    entryNames: ["WATER_POKE_L", "WATER_POKE_R"],
  });
  edge({ id: "e-respond-choice", from: answerFrom, to: "choice", kind: "choice" });

  // --- outcomes ------------------------------------------------------------
  // Ordered best-to-worst so the column reads as a gradient, matching the stack
  // order `OutcomeMix` uses.
  interface OutcomeSpec {
    id: string;
    label: string;
    detail: string;
    needs: () => boolean;
    governedBy: readonly string[];
    entryNames: readonly string[];
    /**
     * What the branch to this outcome required, when the outcome's own name
     * doesn't already say it. "Reward" doesn't state that the animal was both
     * correct and held; "Wrong well" says everything its edge could.
     */
    edgeLabel?: string;
    kind: EdgeKind;
    /**
     * Which state the outcome leaves from. "Answer" means a well was poked, so
     * the two outcomes that mean *no* well was poked branch off the response
     * window instead — drawing them out of Answer would say the animal answered
     * and then didn't.
     */
    from: "answer" | "window";
    /** See `TaskNode.settlesToIti` — whether the firmware's delay starts here. */
    settlesToIti: boolean;
  }

  /*
   * A reward is the one outcome the firmware does NOT start delaying after
   * immediately: it waits for the animal to leave the well, and the ITI runs
   * from that withdrawal. So a real strobe moves the token on, and only a
   * profile that fails to declare one needs the timer to rescue it.
   */
  const rewardSettles = !(has("WATER_UNPOKE_L") || has("WATER_UNPOKE_R"));
  const allOutcomes: OutcomeSpec[] = [
    {
      id: "reward",
      label: "Reward",
      detail: "Correct well, held to the end — fluid delivered.",
      needs: () => has("FLUID_L") || has("FLUID_R"),
      governedBy: ["Reward volume", ...STAGES],
      entryNames: ["FLUID_L", "FLUID_R"],
      settlesToIti: rewardSettles,
      edgeLabel: "correct, held",
      kind: "reward",
      from: "answer",
    },
    {
      id: "withheld",
      label: "Withheld",
      detail: "No-go trial answered correctly by withholding a response.",
      /*
       * Declaring a code is not presenting it. Every task.json in the lab lists
       * WATER_POKE_NONE because they all mirror the one shared BF_* vocabulary,
       * yet no sketch here builds a no-go TrialType — so gating on the strobe
       * alone would draw a branch the animal can never take, on every profile.
       * A metric that SCORES the withhold is the declaration that it is real;
       * this is the same reason the odor rows filter through liveMetrics.
       *
       */
      needs: () => has("WATER_POKE_NONE") && scored.has("WATER_POKE_NONE"),
      governedBy: ["Trial timing"],
      entryNames: ["WATER_POKE_NONE"],
      settlesToIti: true,
      edgeLabel: "withholds",
      kind: "reward",
      from: "window",
    },
    {
      id: "hold-fail",
      label: "No hold",
      detail: "Correct well reached, released before the hold cleared — no drop earned.",
      needs: () => has("WATER_UNPOKE_EARLY_L") || has("WATER_UNPOKE_EARLY_R"),
      governedBy: STAGES,
      entryNames: ["WATER_UNPOKE_EARLY_L", "WATER_UNPOKE_EARLY_R"],
      settlesToIti: true,
      kind: "error",
      from: "answer",
    },
    {
      id: "wrong-well",
      label: "Wrong well",
      detail: "The other well was answered.",
      needs: () => has("WATER_POKE_ERROR_L") || has("WATER_POKE_ERROR_R"),
      governedBy: ["Correction trials", "Trial timing"],
      entryNames: ["WATER_POKE_ERROR_L", "WATER_POKE_ERROR_R"],
      settlesToIti: true,
      kind: "error",
      from: "answer",
    },
    {
      id: "no-response",
      label: "No answer",
      detail: "The response window elapsed with no well answered. Emits no strobe of its own.",
      needs: () => true,
      governedBy: STAGES,
      entryNames: [],
      // Moot: nothing puts the token here, since a response window that simply
      // elapsed emits no strobe of its own.
      settlesToIti: true,
      kind: "error",
      from: "window",
    },
  ];
  const outcomes = allOutcomes.filter((o) => o.needs());

  const outcomeRows = centredRows(outcomes.length, 1.35);
  outcomes.forEach((outcome, index) => {
    node({
      id: outcome.id,
      label: outcome.label,
      kind: "outcome",
      column: COL.outcome,
      row: outcomeRows[index] ?? SPINE_ROW,
      detail: outcome.detail,
      labelAnchor: "right",
      governedBy: outcome.governedBy,
      entryNames: outcome.entryNames,
      settlesToIti: outcome.settlesToIti,
    });
    // One edge per outcome rather than one per condition: every outcome is
    // reachable whichever odor was presented, so a cross product would be N
    // unlabelled lines per outcome saying nothing. Which well is *correct* for
    // a given odor is the condition node's business — its metric label
    // ("P(R | Odor 1)") says so in words, where there is room to.
    edge({
      id: `e-${outcome.id}-in`,
      from: outcome.from === "answer" ? "choice" : answerFrom,
      to: outcome.id,
      // Omitted rather than set to undefined: `exactOptionalPropertyTypes`
      // treats a present-but-undefined key as a different thing from absence.
      ...(outcome.edgeLabel ? { label: outcome.edgeLabel } : {}),
      kind: outcome.kind,
    });
  });

  // --- the returns ---------------------------------------------------------
  /*
   * Two convergence points, not one return per leaf. Eight curves sweeping back
   * across the diagram is a knot; two are structure you can read past. Both are
   * real states rather than drawing conveniences:
   *
   *   ITI    — every administered trial ends by serving its delay and then
   *            emitting END_CORRECT_ITI or END_INCORRECT_ITI. (The strobe marks
   *            the END of the delay: the firmware delays first, then strobes.)
   *   Repeat — every abort emits INVALID_TRIAL and re-presents the SAME trial,
   *            which is why it is a distinct return and not folded into the ITI.
   */
  node({
    id: "iti",
    label: "ITI",
    kind: "state",
    column: COL.iti,
    row: SPINE_ROW,
    detail: "The outcome's delay is served, then the next trial begins.",
    labelAnchor: "above",
    governedBy: ["Trial timing"],
    /*
     * WATER_UNPOKE_* as well as the two ITI codes: the firmware waits for the
     * animal to leave the well after a reward, and the delay runs from that
     * moment — so the token should move here when it withdraws, not linger on
     * the reward until the ITI code lands a whole standardITI later.
     */
    entryNames: [
      "WATER_UNPOKE_L",
      "WATER_UNPOKE_R",
      "END_CORRECT_ITI",
      "END_INCORRECT_ITI",
    ],
  });
  for (const outcome of outcomes) {
    edge({ id: `e-${outcome.id}-iti`, from: outcome.id, to: "iti", kind: "advance" });
  }
  edge({ id: "e-iti-start", from: "iti", to: "start", kind: "return" });

  const aborts = ["lazy", "abort-pre-odor", "abort-sampling"].filter((id) =>
    nodes.some((n) => n.id === id),
  );
  if (aborts.length > 0) {
    node({
      id: "repeat",
      label: "Repeat",
      kind: "abort",
      column: COL.respond,
      row: ABORT_ROW,
      detail: "The trial is aborted and the same one is presented again.",
      governedBy: ["Abstention penalty"],
      entryNames: ["INVALID_TRIAL"],
    });
    for (const abort of aborts) {
      edge({ id: `e-${abort}-repeat`, from: abort, to: "repeat", kind: "abort" });
    }
    edge({ id: "e-repeat-start", from: "repeat", to: "start", kind: "return" });
  }

  return { nodes, edges, conditions, usable: true };
}

/**
 * The states one config group's parameters govern.
 *
 * One implementation for both halves of the tile↔graph link — the tile's own
 * subtitle and the set of nodes its hover lights. Two would drift, and the
 * drift would be invisible: a tile claiming to govern a state the graph doesn't
 * light looks like a highlighting bug rather than a disagreement.
 */
export function nodesGovernedBy(model: TaskGraphModel, group: string | null): TaskNode[] {
  if (!group) return [];
  return model.nodes.filter((node) => node.governedBy.includes(group));
}

// --- live mode -------------------------------------------------------------

/**
 * Which node a strobe stream has arrived at.
 *
 * Deliberately a fold over codes rather than over `liveTrials`' trial records:
 * a trial record only exists once the trial has *closed*, and the whole point
 * of the live graph is to show where the animal is right now. `LIGHTS_ON`
 * resets to the top — `vocabFrom` has always resolved it and nothing consumed
 * it until this.
 */
export function nodeIndexByName(model: TaskGraphModel): Map<string, string> {
  const index = new Map<string, string>();
  for (const node of model.nodes) {
    for (const name of node.entryNames) index.set(name, node.id);
  }
  return index;
}

/**
 * The node the last recognised strobe puts the token on, or `null` before the
 * first one. `strobes` is the profile's code→name map; `codes` are the raw
 * codes as they arrived, oldest first.
 */
export function liveNodeId(
  model: TaskGraphModel,
  strobes: Record<string, string>,
  codes: readonly string[],
): string | null {
  const byName = nodeIndexByName(model);
  for (let i = codes.length - 1; i >= 0; i -= 1) {
    const name = strobes[codes[i]!];
    if (!name) continue;
    const nodeId = byName.get(name.toUpperCase());
    if (nodeId) return nodeId;
  }
  return null;
}

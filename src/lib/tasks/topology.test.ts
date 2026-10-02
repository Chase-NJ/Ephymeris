/**
 * The derived state machine's decoding — `docs/tasks.md` §4.10.
 *
 * Everything here fails QUIETLY without a check, which is the whole reason
 * these functions are pure and this file exists. A wrong condition looks
 * exactly like a right one; a fabricated contingency is a confident mono chip
 * in a screenshot that outlives the session that made it. None of it throws.
 */

import { describe, expect, it } from "vitest";

import type { TaskProfile } from "@/lib/ws/protocol";

import {
  armsCongruent,
  correctWellOf,
  groupsOfTab,
  liveConditionId,
  nodesGovernedByTab,
  orderGroups,
  tabOf,
  taskGraph,
  type Condition,
  QUICK_TUNE_GROUPS,
} from "./topology";

/** The shared BF_* vocabulary, as every profile in the lab mirrors it. */
const STROBES: Record<string, string> = {
  "220": "LIGHTS_ON",
  "221": "LAZY_RAT",
  "222": "ODOR_POKE",
  "223": "ODOR_UNPOKE_EARLY",
  "224": "ODOR_UNPOKE",
  "225": "LIGHTS_OFF",
  "226": "INVALID_TRIAL",
  "227": "END_CORRECT_ITI",
  "228": "END_INCORRECT_ITI",
  "244": "WATER_POKE_NONE",
  "246": "END_SESSION",
  "248": "WATER_POKE_L",
  "249": "WATER_POKE_R",
  "250": "WATER_POKE_ERROR_L",
  "251": "WATER_POKE_ERROR_R",
  "252": "WATER_UNPOKE_EARLY_L",
  "253": "WATER_UNPOKE_EARLY_R",
  "254": "FLUID_L",
  "255": "FLUID_R",
  "101": "ODOR_1_ON",
  "102": "ODOR_2_ON",
  "103": "ODOR_3_ON",
  "104": "ODOR_4_ON",
};

/** A profile presenting `n` conditions; `noGo` makes the LAST one a withhold. */
function profile(n: number, { noGo = false } = {}): TaskProfile {
  const onsets = [101, 102, 103, 104];
  return {
    taskName: `GRGL ${n}-Odor`,
    kind: "behavior",
    config: [],
    strobes: STROBES,
    liveMetrics: onsets.slice(0, n).map((code, i) => ({
      id: `p_correct_${i + 1}`,
      label: `P(x | odor ${i + 1})`,
      triggerCode: code,
      // Alternating sides, so "differing wells" is the normal case rather than
      // a contrived one.
      successCode: noGo && i === n - 1 ? 244 : i % 2 ? 248 : 249,
      alternateCode: i % 2 ? 249 : 248,
      windowSize: 20,
    })),
    controls: [],
    legacyNames: [],
  } as unknown as TaskProfile;
}

const conditionsOf = (n: number, opts?: { noGo?: boolean }) =>
  taskGraph(profile(n, opts)).conditions;

// --- the contingency -------------------------------------------------------

describe("correctWellOf", () => {
  it("reads the side off the historical suffix", () => {
    expect(correctWellOf("WATER_POKE_L")).toEqual({ kind: "well", side: "left" });
    expect(correctWellOf("WATER_POKE_R")).toEqual({ kind: "well", side: "right" });
  });

  it("calls a withhold a withhold", () => {
    expect(correctWellOf("WATER_POKE_NONE")).toEqual({ kind: "withhold" });
  });

  it("keeps a slot number when the rig's ports carry no side", () => {
    expect(correctWellOf("WATER_POKE_PORT_3")).toEqual({ kind: "port", slot: 3 });
  });

  it("returns null rather than guessing, for everything it cannot prove", () => {
    // The success code resolved to nothing (a strobes map missing the entry),
    // or to a code that is not an answer at all.
    expect(correctWellOf(undefined)).toBeNull();
    expect(correctWellOf("")).toBeNull();
    expect(correctWellOf("ODOR_1_ON")).toBeNull();
    expect(correctWellOf("FLUID_R")).toBeNull();
    expect(correctWellOf("WATER_UNPOKE_EARLY_R")).toBeNull();
  });

  it("NEVER answers a no-go condition with a well", () => {
    /*
     * THE ONE THAT WOULD PRINT A LIE. A no-go type's `alternateCode` is set by
     * the generator to "any port will do" (`_first_enter_code`), and `infer.py`
     * does the same with `slots[0]` — so a `successCode → alternateCode`
     * fallback renders "Odor 4 → left well" for a condition whose correct
     * answer is to poke nothing. This pins the whole path, not just the helper:
     * the withhold condition's alternate here IS a well.
     */
    const withhold = conditionsOf(2, { noGo: true })[1]!;
    expect(withhold.correctAnswer).toEqual({ kind: "withhold" });
  });

  it("stays null when the success code is unreadable and the ALTERNATE is a well", () => {
    /*
     * The mutation the test above does not catch, and the one that actually
     * ships a lie. A withhold's success code is readable, so a
     * `successCode ?? alternateCode` fallback is inert there — it fires when the
     * success code resolves to nothing (a strobes map missing the entry, an
     * older profile, a code that is not an answer) while the alternate happens
     * to be a perfectly readable well. The answer then looks authoritative and
     * is the OPPOSITE side, since an alternate is by definition the other one.
     */
    const odd = {
      taskName: "Odd",
      kind: "behavior",
      config: [],
      strobes: STROBES,
      liveMetrics: [
        {
          id: "m",
          label: "P(? | odor 1)",
          triggerCode: 101,
          successCode: 254, // FLUID_L — a real code, but not an answer
          alternateCode: 249, // WATER_POKE_R — very readable, and wrong
          windowSize: 20,
        },
        {
          id: "m2",
          label: "P(? | odor 2)",
          triggerCode: 102,
          successCode: 9999, // not in the strobes map at all
          alternateCode: 248,
          windowSize: 20,
        },
      ],
      controls: [],
      legacyNames: [],
    } as unknown as TaskProfile;

    for (const condition of taskGraph(odd).conditions) {
      expect(condition.correctAnswer).toBeNull();
    }
  });
});

// --- the congruence guard --------------------------------------------------

describe("armsCongruent", () => {
  it("is true for the tasks this lab actually runs", () => {
    expect(armsCongruent(conditionsOf(2))).toBe(true);
    expect(armsCongruent(conditionsOf(4))).toBe(true);
  });

  it("treats differing correct wells as congruent", () => {
    // The topology is identical — same in-edge, same two out-edges, same
    // downstream — and the rail carries the difference. Every fixture above
    // already alternates sides; this states it as the rule it is.
    const conditions = conditionsOf(4);
    const sides = new Set(
      conditions.map((c) =>
        c.correctAnswer?.kind === "well" ? c.correctAnswer.side : "?",
      ),
    );
    expect(sides).toEqual(new Set(["left", "right"]));
    expect(armsCongruent(conditions)).toBe(true);
  });

  it("is false for a go/no-go mix, which really is two shapes", () => {
    expect(armsCongruent(conditionsOf(3, { noGo: true }))).toBe(false);
  });

  it("is vacuously true below two arms", () => {
    expect(armsCongruent([])).toBe(true);
    expect(armsCongruent(conditionsOf(1))).toBe(true);
  });
});

// --- the collapse ----------------------------------------------------------

describe("taskGraph", () => {
  it("draws one odor node however many conditions there are", () => {
    for (const n of [1, 2, 3, 4]) {
      const model = taskGraph(profile(n));
      const odor = model.nodes.filter((node) => node.column === 42);
      // One odor node, plus the `Let go` abort that shares its column.
      expect(odor.filter((node) => node.kind === "state")).toHaveLength(1);
      expect(model.conditions).toHaveLength(n);
    }
  });

  it("gives the collapsed node every condition's entry name", () => {
    // Or `liveNodeId` loses the token the moment the firmware announces an
    // odor other than the first.
    const model = taskGraph(profile(4));
    const odor = model.nodes.find((node) => node.id === "odor")!;
    expect([...odor.entryNames]).toEqual([
      "ODOR_1_ON",
      "ODOR_2_ON",
      "ODOR_3_ON",
      "ODOR_4_ON",
    ]);
    expect(odor.multiplicity).toBe(4);
    expect(odor.variants).toHaveLength(4);
  });

  it("names itself generically only when it stands for several", () => {
    expect(taskGraph(profile(1)).nodes.find((n) => n.id === "odor")?.label).toBe(
      "Odor 1",
    );
    expect(taskGraph(profile(4)).nodes.find((n) => n.id === "odor")?.label).toBe(
      "Odor",
    );
  });

  it("gives the three collapsed edges their labels back", () => {
    // They were dropped for colliding around a fan-out, not for being
    // uninformative — so a collapse has to return them.
    const labels = taskGraph(profile(4))
      .edges.filter((e) => e.from === "odor" || e.to === "odor")
      .map((e) => e.label);
    expect(labels).toContain("holds");
    expect(labels).toContain("samples");
    expect(labels).toContain("leaves early");
  });

  it("falls back to a fan when the arms are not congruent", () => {
    const model = taskGraph(profile(3, { noGo: true }));
    expect(model.congruent).toBe(false);
    const arms = model.nodes.filter((node) => node.lane === "fan");
    expect(arms).toHaveLength(3);
    // And the aborts stay in the band the renderer will re-place.
    expect(model.nodes.filter((n) => n.lane === "floor").length).toBeGreaterThan(0);
  });
});

// --- the live condition ----------------------------------------------------

describe("liveConditionId", () => {
  const model = taskGraph(profile(4));
  const read = (...codes: string[]) => liveConditionId(model, STROBES, codes);

  it("names the condition the current trial opened", () => {
    expect(read("220", "222", "103")).toEqual({ kind: "condition", id: "odor-3" });
  });

  it("keeps naming it for the rest of the trial", () => {
    // The condition is a fact about the whole trial, not only about the moment
    // the odor arrives — the answer window is still an odor-3 trial.
    expect(read("220", "222", "103", "224", "225", "248")).toEqual({
      kind: "condition",
      id: "odor-3",
    });
  });

  it("stops at the trial boundary instead of inheriting the last odor", () => {
    // THE LEAK THIS EXISTS TO PREVENT: without the boundary, the pre-odor phase
    // of every trial would state the condition of the trial before it.
    expect(read("103", "224", "227", "220", "222")).toBeNull();
    expect(read("103", "226", "220")).toBeNull();
    expect(read("103", "228", "220", "222")).toBeNull();
  });

  it("is null before the first odor, and on an abort that never got one", () => {
    expect(read()).toBeNull();
    expect(read("220")).toBeNull();
    expect(read("220", "222", "223", "226")).toBeNull();
  });

  it("never falls back to the first condition", () => {
    // A wrong condition looks exactly like a right one, so there is no safe
    // default to reach for.
    expect(read("220", "222", "224")).toBeNull();
  });

  it("reports an odor the profile does not declare, rather than swallowing it", () => {
    /*
     * Collapsing the fan turned a structural absence — a missing ARM — into a
     * nameless presence. This is the state that keeps it visible, and it is
     * almost always the `liveMetrics` gate having silently dropped a trial
     * type, which is the most useful thing this readout can catch.
     */
    const twoOdor = taskGraph(profile(2));
    expect(liveConditionId(twoOdor, STROBES, ["220", "222", "104"])).toEqual({
      kind: "unlisted",
      strobeName: "ODOR_4_ON",
    });
  });

  it("ignores codes the profile's strobe map cannot name", () => {
    expect(read("220", "222", "999", "103")).toEqual({
      kind: "condition",
      id: "odor-3",
    });
  });
});

// --- the shape of a Condition ----------------------------------------------

describe("conditions", () => {
  it("carries a 1-based index matching the trial table's slot order", () => {
    const conditions: Condition[] = conditionsOf(3);
    expect(conditions.map((c) => c.index)).toEqual([1, 2, 3]);
  });
});

// --- the rail's fold -------------------------------------------------------

/**
 * `tabOf` is presentation, and it has to STAY presentation.
 *
 * The temptation it exists to resist is re-filing these fields in `fields.py`,
 * which is two lines and would be wrong: `group` rides in `ConfigField.to_json`
 * and therefore inside `profile_hash`, so every regenerated `task.json` would
 * land under a new hash and each task's recorded runs would stop being
 * comparable to its future ones — with no error anywhere.
 */
describe("quick tune", () => {
  it("promotes the four groups the lab turns per animal, in that order", () => {
    // Reward volume and Trial pool joined when reward time and the weighted
    // selector made them per-condition knobs that change over days. A group
    // added here changes nothing in any profile hash; that is the point.
    expect([...QUICK_TUNE_GROUPS]).toEqual([
      "Correction trials",
      "Abstention penalty",
      "Reward volume",
      "Trial pool",
    ]);
  });
});

describe("parameter tabs", () => {
  it("folds correction trials and reward volume under Session", () => {
    expect(tabOf("Correction trials")).toBe("Session");
    expect(tabOf("Reward volume")).toBe("Session");
  });

  it("leaves every other group as its own tab", () => {
    for (const group of [
      "Session",
      "Trial pool",
      "Trial timing",
      "Holds & windows",
      "Stage 3",
      "Abstention penalty",
      "Anti-bias selection",
      "Something a future profile invents",
    ]) {
      expect(tabOf(group)).toBe(group);
    }
  });

  it("orders a folded tab's members the way the trial takes them", () => {
    // Declaration order is the profile's; the rail renders them stacked, and
    // "the session, then the correction budget, then the volumes" is the order
    // they take effect in — which is what GROUP_ORDER already encodes.
    const declared = ["Reward volume", "Correction trials", "Session", "Trial timing"];
    expect(groupsOfTab("Session", declared)).toEqual([
      "Session",
      "Correction trials",
      "Reward volume",
    ]);
    expect(groupsOfTab("Trial timing", declared)).toEqual(["Trial timing"]);
  });

  it("keeps Session first once the folded names are ordered as tabs", () => {
    const tabs = orderGroups(
      new Set(
        ["Reward volume", "Anti-bias selection", "Correction trials", "Trial timing"].map(
          tabOf,
        ),
      ),
    );
    expect(tabs).toEqual(["Session", "Trial timing", "Anti-bias selection"]);
  });

  it("lights a folded tab from any of the groups it swallowed", () => {
    // The machine→rail half of the highlight link: a tab lights every state
    // governed by any group folded into it, which is more than its own group.
    const model = taskGraph(profile(2));
    const exact = (group: string) =>
      model.nodes.filter((n) => n.governedBy.includes(group)).map((n) => n.id);
    const byTab = nodesGovernedByTab(model, "Session").map((n) => n.id);
    const correction = exact("Correction trials");
    const session = exact("Session");

    expect(correction.length).toBeGreaterThan(0);
    expect(session.length).toBeGreaterThan(0);
    for (const id of [...correction, ...session]) expect(byTab).toContain(id);
    // And the fold adds something: at least one correction-governed state is
    // NOT a Session-governed state.
    expect(correction.some((id) => !session.includes(id))).toBe(true);
    expect(byTab.length).toBeGreaterThan(session.length);
  });
});

import { describe, expect, it } from "vitest";

import type { TaskProfile } from "@/lib/ws/protocol";

import { rowName, spineGraph } from "./spineGraph";

function profile(spine: Record<string, unknown> | undefined, strobes = {}): TaskProfile {
  return {
    taskName: "Spine Go No-Go",
    kind: "behavior",
    config: [],
    strobes,
    liveMetrics: [],
    controls: [],
    legacyNames: [],
    spine,
  } as unknown as TaskProfile;
}

const GO_NO_GO = {
  interp: 5,
  spine: [
    { phase: "wait", on: "port", outputs: ["cue"] },
    { phase: "present", outputs: ["cue", "sample"], ms: 1000 },
    { phase: "response", responses: ["resp"], ms: 3000 },
    { phase: "outcome", ms: 0 },
    { phase: "iti", ms: 3000 },
  ],
  rows: [
    { id: "go", name: "Go" },
    { id: "no_go", name: "No-go" },
  ],
};

describe("a spine task's trial flow, from its snapshot", () => {
  it("is the phases in spine order, indexed as the sidecar names them", () => {
    const graph = spineGraph(profile(GO_NO_GO))!;
    expect(graph.phases.map((p) => [p.index, p.label])).toEqual([
      [0, "Wait"],
      [1, "Present"],
      [2, "Response window"],
      [3, "Outcome"],
      [4, "ITI"],
    ]);
    expect(graph.phases[2]!.detail).toBe("watching resp · 3000 ms");
    expect(graph.rows).toEqual(GO_NO_GO.rows);
  });

  it("is nothing for a profile with no spine", () => {
    expect(spineGraph(profile(undefined))).toBeNull();
    expect(spineGraph(null)).toBeNull();
  });

  it("names a row by the snapshot, and an unknown one by its id", () => {
    const graph = spineGraph(profile(GO_NO_GO))!;
    expect(rowName(graph, "no_go")).toBe("No-go");
    expect(rowName(graph, "later")).toBe("later");
    expect(rowName(graph, null)).toBeNull();
  });

  it("does not depend on the strobe vocabulary at all", () => {
    const bare = spineGraph(profile(GO_NO_GO, {}));
    const named = spineGraph(profile(GO_NO_GO, { "221": "START_SESSION", "1": "TRIAL_START" }));
    expect(bare).toEqual(named);
  });
});

/** Sources as text, through Vite's own glob: no Node types needed. */
const SOURCES = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("nothing on the live spine path matches strobe names (#100)", () => {
  const SPINE_PATH = [
    "/src/lib/tasks/spineGraph.ts",
    "/src/lib/sessions/liveReplay.ts",
    "/src/components/sessions/LiveSpine.tsx",
  ];
  it.each(SPINE_PATH)("%s reads no strobe and no legacy token", (path) => {
    const text = SOURCES[path];
    if (text === undefined) throw new Error(`${path} is not in the source glob`);
    const source = text
      // Comments may say what the module refuses to do.
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/\/\/.*$/gm, "");
    for (const banned of [".strobes", "liveNodeId", "entryNames", "useLiveNode", "useLiveTrials", "getStrobes"]) {
      expect(source, `${path} uses ${banned}`).not.toContain(banned);
    }
  });
});

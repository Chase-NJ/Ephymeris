import { describe, expect, it } from "vitest";

/**
 * A recording pop-up mounts a SLIM provider tree — `SidecarProvider` +
 * `IntanProvider` + `ScopeApp`, and deliberately no `SettingsProvider`
 * (`main.tsx`): a scope window must never re-push a stale copy of the
 * settings over the main window's. So nothing a scope window renders may
 * call `useSettings`, or anything built on it. The hook throws outside its
 * provider, React unmounts the tree, and every window opens blank — which is
 * exactly how the title-bar dot's `useReduceMotion` broke all four at once
 * with no error anywhere but the pop-up's own console.
 *
 * This walks the scope tree's static import graph from its three roots and
 * fails on any path that reaches the settings domain. A component test would
 * need a DOM and a WebSocket to show the same thing; the import graph shows
 * it without either. Sources come in through Vite's own glob, as text, so the
 * test needs no Node types the app's tsconfig does not have.
 */

const SOURCES = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const ROOTS = [
  "/src/routes/scope/ScopeApp.tsx",
  "/src/lib/intan/IntanProvider.tsx",
  "/src/lib/ws/SidecarProvider.tsx",
];

/** Modules that exist to read settings. Anything reaching them is a bug. */
const FORBIDDEN = [/^\/src\/lib\/settings\//, /^\/src\/lib\/useReduceMotion\.ts$/];

const EXTENSIONS = [".ts", ".tsx"];
const IMPORT = /(?:^|\n)\s*(?:import|export)\s[^;]*?from\s+["']([^"']+)["']/g;

function normalize(path: string): string {
  const parts: string[] = [];
  for (const part of path.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") parts.pop();
    else parts.push(part);
  }
  return "/" + parts.join("/");
}

function resolveImport(from: string, specifier: string): string | null {
  let base: string;
  if (specifier.startsWith("@/")) base = "/src/" + specifier.slice(2);
  else if (specifier.startsWith(".")) base = normalize(from.slice(0, from.lastIndexOf("/")) + "/" + specifier);
  else return null; // a package, not ours
  base = normalize(base);
  for (const candidate of [base, ...EXTENSIONS.map((e) => base + e), ...EXTENSIONS.map((e) => `${base}/index${e}`)]) {
    if (candidate in SOURCES) return candidate;
  }
  return null;
}

/** Every source file reachable from the roots, with what each one imports. */
function walk(roots: string[]): Map<string, string[]> {
  const seen = new Map<string, string[]>();
  const queue = [...roots];
  while (queue.length > 0) {
    const file = queue.pop()!;
    if (seen.has(file)) continue;
    const text = SOURCES[file];
    if (text === undefined) throw new Error(`${file} is not in the source glob`);
    const imports: string[] = [];
    for (const match of text.matchAll(IMPORT)) {
      const target = resolveImport(file, match[1]!);
      if (target) {
        imports.push(target);
        queue.push(target);
      }
    }
    seen.set(file, imports);
  }
  return seen;
}

/** The chain of imports from a root to `target`, for the failure message. */
function pathTo(graph: Map<string, string[]>, target: string): string[] {
  const parent = new Map<string, string>();
  const queue = ROOTS.filter((r) => graph.has(r));
  const visited = new Set(queue);
  while (queue.length > 0) {
    const node = queue.shift()!;
    if (node === target) {
      const chain = [node];
      while (parent.has(chain[0]!)) chain.unshift(parent.get(chain[0]!)!);
      return chain;
    }
    for (const next of graph.get(node) ?? []) {
      if (visited.has(next)) continue;
      visited.add(next);
      parent.set(next, node);
      queue.push(next);
    }
  }
  return [target];
}

describe("the scope window's import graph", () => {
  const graph = walk(ROOTS);

  it("reaches the frame every pop-up renders (or this test is walking nothing)", () => {
    expect(graph.has("/src/routes/scope/ScopeFrame.tsx")).toBe(true);
    expect(graph.has("/src/routes/scope/SpikeScopeWindow.tsx")).toBe(true);
    expect(graph.has("/src/lib/intan/context.ts")).toBe(true);
  });

  it("never reaches the settings domain, which has no provider in that window", () => {
    const offenders = [...graph.keys()].filter((key) => FORBIDDEN.some((rule) => rule.test(key)));
    const explained = offenders.map((key) => pathTo(graph, key).join("\n    → "));
    expect(explained, `settings reached from the scope tree:\n  ${explained.join("\n  ")}`).toEqual([]);
  });

  it("would catch the hook that blanked every window", () => {
    // The main app's tree reaches it; the check is what tells the two apart.
    const app = walk(["/src/App.tsx"]);
    expect(app.has("/src/lib/useReduceMotion.ts")).toBe(true);
    expect(FORBIDDEN.some((rule) => rule.test("/src/lib/useReduceMotion.ts"))).toBe(true);
  });
});

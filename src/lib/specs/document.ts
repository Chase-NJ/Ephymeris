/**
 * Pure helpers over the parsed spec document: path get/set and serialization.
 *
 * Paths here are CONCRETE — `timing[3].ms`, `contingency.ports.left_well.channel`
 * — the same grammar diagnostics use, so a field knows its own path and can
 * look its errors up without translation. The wildcard form (`timing[].ms`)
 * belongs to the overlay and never appears here.
 */

import { stringify } from "yaml";

import type { SpecDocument } from "./types";

type Step = string | number;

function steps(path: string): Step[] {
  const out: Step[] = [];
  for (const chunk of path.split(".")) {
    let rest = chunk;
    while (rest.includes("[")) {
      const head = rest.slice(0, rest.indexOf("["));
      if (head) out.push(head);
      const close = rest.indexOf("]");
      out.push(Number(rest.slice(rest.indexOf("[") + 1, close)));
      rest = rest.slice(close + 1);
    }
    if (rest) out.push(rest);
  }
  return out;
}

export function getAt(doc: SpecDocument, path: string): unknown {
  let node: unknown = doc;
  for (const step of steps(path)) {
    if (node === null || typeof node !== "object") return undefined;
    node = (node as Record<Step, unknown>)[step];
  }
  return node;
}

/**
 * Immutable set — returns a new document sharing unchanged branches, so React
 * state comparisons stay cheap and an aborted edit can't corrupt the original.
 * Intermediate containers are created as the path implies (object for a string
 * step, array for a numeric one).
 */
export function setAt(doc: SpecDocument, path: string, value: unknown): SpecDocument {
  const parts = steps(path);

  function assign(node: unknown, index: number): unknown {
    const step = parts[index]!;
    const isLast = index === parts.length - 1;
    if (typeof step === "number") {
      const arr = Array.isArray(node) ? [...node] : [];
      arr[step] = isLast ? value : assign(arr[step], index + 1);
      return arr;
    }
    const obj =
      node !== null && typeof node === "object" && !Array.isArray(node)
        ? { ...(node as Record<string, unknown>) }
        : {};
    obj[step] = isLast ? value : assign(obj[step], index + 1);
    return obj;
  }

  return assign(doc, 0) as SpecDocument;
}

/** Delete the key/element at `path`, immutably. */
export function deleteAt(doc: SpecDocument, path: string): SpecDocument {
  const parts = steps(path);

  function remove(node: unknown, index: number): unknown {
    const step = parts[index]!;
    if (node === null || typeof node !== "object") return node;
    if (index === parts.length - 1) {
      if (Array.isArray(node) && typeof step === "number") {
        return node.filter((_, i) => i !== step);
      }
      const { [step as string]: _dropped, ...rest } = node as Record<string, unknown>;
      return rest;
    }
    if (Array.isArray(node) && typeof step === "number") {
      const arr = [...node];
      arr[step] = remove(arr[step], index + 1);
      return arr;
    }
    const obj = { ...(node as Record<string, unknown>) };
    obj[step as string] = remove(obj[step as string], index + 1);
    return obj;
  }

  return remove(doc, 0) as SpecDocument;
}

/**
 * The document as the bytes that would be saved — what `specs.compile` checks.
 *
 * One serializer, used by both the live compile and (later) the save, so the
 * editor can never validate different bytes than it writes. Key order follows
 * the document's own insertion order, which for a loaded spec is the authored
 * order — `spec_hash` covers the parsed dict, not the text, so formatting
 * differences don't move provenance either way.
 */
export function toYaml(doc: SpecDocument): string {
  return stringify(doc, {
    // A spec is a machine artifact with prose in `note` fields; block style
    // keeps those readable and diffs line-oriented.
    lineWidth: 100,
    defaultStringType: "PLAIN",
    defaultKeyType: "PLAIN",
  });
}

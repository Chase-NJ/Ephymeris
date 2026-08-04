/**
 * Creating a spec is RENAME-AND-SAVE, and this is the one definition of it.
 *
 * `specs.save` targets the document's own `spec_id`, and a save under an id
 * with no user file creates one — the source is untouched because nothing
 * wrote to it. There is deliberately no wire command for "make me a new spec"
 * (docs/specs.md §3): a blank-skeleton generator would be a second definition
 * of what a minimal legal spec is, competing with the schema.
 *
 * Three surfaces take this path — the paradigm gallery, Duplicate on a library
 * card, and the design wizard — and they were on their way to being three
 * near-copies, which is how the id-rewrite rule below gets forgotten in one of
 * them. The id names the file, the compiled table and what a board reports
 * after an upload, so it is rewritten IN the document rather than only passed
 * as the save target; the sidecar refuses the two disagreeing.
 */

import { saveSpec } from "./commands";
import { toYaml } from "./document";
import type { SpecDocument } from "./types";
import type { SidecarClient } from "@/lib/ws/client";

/** A spec id is a filename: `^[a-z][a-z0-9_]{0,39}$`, enforced sidecar-side
 * too, where it dies before any path join. */
export const SPEC_ID_RE = /^[a-z][a-z0-9_]{0,39}$/;

export interface CreateOptions {
  id: string;
  label?: string | undefined;
  description?: string | undefined;
  /**
   * Clear `meta.reproduces_sketch` and `meta.derived_from`. The wizard sets
   * this: a task designed from scratch reproduces no sketch, and leaving the
   * claim in place turns TG231's severity (which keys on it) into an error
   * for the wrong reason.
   */
  clearProvenance?: boolean;
}

/** The document as it would be saved under `opts.id` — pure, so a caller can
 * compile or diff it before committing to the save. */
export function rename(source: SpecDocument, opts: CreateOptions): SpecDocument {
  const next: SpecDocument = { ...source, spec_id: opts.id };

  const existing = next["meta"];
  const meta: Record<string, unknown> =
    existing !== null && typeof existing === "object" && !Array.isArray(existing)
      ? { ...(existing as Record<string, unknown>) }
      : {};

  if (opts.label !== undefined && opts.label.trim() !== "") meta["label"] = opts.label.trim();
  if (opts.description !== undefined && opts.description.trim() !== "") {
    meta["description"] = opts.description.trim();
  }
  if (opts.clearProvenance) {
    delete meta["reproduces_sketch"];
    delete meta["derived_from"];
  }
  if (Object.keys(meta).length > 0) next["meta"] = meta;

  return next;
}

export async function createSpecFrom(
  client: SidecarClient,
  source: SpecDocument,
  opts: CreateOptions,
): Promise<void> {
  await saveSpec(client, opts.id, toYaml(rename(source, opts)));
}

/** `gonogo` → `gonogo_2`, skipping ids already in the library. */
export function suggestId(source: string, taken: ReadonlySet<string>): string {
  const stem = source.slice(0, 37);
  for (let n = 2; n < 100; n++) {
    const candidate = `${stem}_${n}`;
    if (!taken.has(candidate)) return candidate;
  }
  return "";
}

/** The client-side id check the gallery and the wizard share. Null when the
 * id is fine (or still empty). */
export function idError(id: string, taken: ReadonlySet<string>): string | null {
  if (id === "") return null;
  if (!SPEC_ID_RE.test(id)) {
    return "Lower-case letters, digits and underscores; starts with a letter.";
  }
  return taken.has(id) ? "A spec with that id already exists." : null;
}

import type { RigChannel } from "./types";

/**
 * The channel set's edits, for the Rig page (`TASKS.md#the-channel-set-and-the-pin-map`).
 *
 * Mirrors of `rig/registry.py`'s `EDGES` and `KIND_DEFAULTS`, used only to keep
 * the draft self-consistent while the operator edits it. The sidecar remains
 * the judge: RIG107 reports anything these miss, and the codes themselves are
 * only ever issued by a save, never written here.
 */

export const CHANNEL_TYPES = ["digital_in", "digital_out"] as const;
export const ROLES = ["port", "stimulus", "reward", "cue", "routing", "sync"] as const;

const EDGES: Record<string, readonly string[]> = {
  digital_in: ["enter", "exit"],
  digital_out: ["on", "off"],
};

const KIND_DEFAULTS: Record<string, { type: string; role: string }> = {
  engagement: { type: "digital_in", role: "port" },
  response: { type: "digital_in", role: "port" },
  emitter: { type: "digital_out", role: "stimulus" },
  reward: { type: "digital_out", role: "reward" },
  cue: { type: "digital_out", role: "cue" },
  vacuum: { type: "digital_out", role: "routing" },
  sync: { type: "digital_out", role: "sync" },
};

/** The edges a channel of this type has, in the order a save issues their codes. */
export function edgesOf(type: string | undefined): readonly string[] {
  return (type && EDGES[type]) || [];
}

/** Type and role for a channel of this kind, as a new channel starts. */
export function kindDefaults(kind: string): { type: string; role: string } {
  return KIND_DEFAULTS[kind] ?? { type: "digital_out", role: "stimulus" };
}

/**
 * Apply an edit to one channel entry, keeping it self-consistent.
 *
 * - A KIND change carries type and role with it, since the kind still decides
 *   the direction the generator drives.
 * - A TYPE change drops the edge codes: an output's `on`/`off` are not an
 *   input's `enter`/`exit`, and a save issues the new ones. The old codes stay
 *   in the vocabulary, as every code does.
 * - Input-only fields go when the channel stops being an input, and an input
 *   starts with a level and a debounce.
 *
 * A rename is NOT an edit here: the entry moves to a new key with its `edges`
 * inside it, which is why renaming never renames a code.
 */
export function patchChannel(current: RigChannel, patch: Partial<RigChannel>): RigChannel {
  const next: RigChannel = { ...current, ...patch };
  if (patch.kind !== undefined && patch.kind !== current.kind) {
    const defaults = kindDefaults(patch.kind);
    next.type = defaults.type;
    next.role = defaults.role;
  }
  if (next.type !== current.type) {
    delete next.edges;
  }
  if (next.type === "digital_in") {
    next.active_level ??= "low";
    next.debounce_ms ??= 0;
  } else {
    delete next.active_level;
    delete next.debounce_ms;
  }
  return next;
}

/**
 * Plumb a reward line to a port, or unplumb it with "". `well` and `serves`
 * say the same thing while both exist, so they move together; absent means
 * "not plumbed", so clearing DELETES the keys (the schema forbids null).
 */
export function servePort(current: RigChannel, port: string): RigChannel {
  const next: RigChannel = { ...current };
  if (port) {
    next.well = port;
    next.serves = port;
  } else {
    delete next.well;
    delete next.serves;
  }
  return next;
}

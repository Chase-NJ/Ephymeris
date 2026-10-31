import type { RigAllocation, RigImpact, RigProblem, RigStatus } from "./types";

/**
 * What a rig-wiring editing session shows, and how a reply changes it.
 *
 * Two kinds of "wrong" with different owners, kept apart on purpose:
 *
 * - `problems` are the DRAFT's (schema and RIG101–RIG107). Every preview
 *   replaces them, and any of them blocks Save.
 * - `status.notices` are the RIG's: stored wiring that did not load, or a file
 *   changed on disk since it was installed (`TASKS.md#the-channel-set-and-the-pin-map`).
 *   They describe the wiring in force, so no edit can make them go away; only
 *   a save or a reset does, and they never block either.
 *
 * Folding the second into the first made them vanish on the first keystroke,
 * which is the moment the operator is about to act on them.
 */
export interface RigView {
  status: RigStatus | null;
  problems: RigProblem[];
  breaks: RigImpact[];
  allocations: RigAllocation[];
}

export interface PreviewReply {
  status?: RigStatus;
  problems: RigProblem[];
  breaks: RigImpact[];
  allocations: RigAllocation[];
}

export function applyPreview(view: RigView, reply: PreviewReply): RigView {
  return {
    status: reply.status ?? view.status,
    problems: reply.problems,
    breaks: reply.breaks,
    allocations: reply.allocations,
  };
}

/**
 * The draft has no problems, and saving it would change something: it was
 * edited, or the rig carries a notice that a save of this draft clears (the
 * stored document served for repair, or a file that differs from the wiring
 * in force).
 */
export function canSave(view: RigView, { dirty, saving }: { dirty: boolean; saving: boolean }): boolean {
  const notices = view.status?.notices.length ?? 0;
  return !saving && view.problems.length === 0 && (dirty || notices > 0);
}

/** The sidecar decides; a refusal that names Reset always leaves it usable. */
export function canReset(status: RigStatus | null, saving: boolean): boolean {
  return !saving && status?.canReset === true;
}

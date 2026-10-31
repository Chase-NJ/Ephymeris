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
 * Whether Save is offered: the sidecar's `status.canSave` for the draft it
 * last described, never worked out here. It knows what the draft is measured
 * against (the served draft), the rig's state (nothing to repair, pins to
 * confirm) and the draft's problems; a guess here once enabled a save that put
 * a mismatched pin map in force.
 */
export function canSave(
  view: RigView,
  { saving, checking }: { saving: boolean; checking: boolean },
): boolean {
  // Held while a preview is in flight: the answer on screen is for the draft
  // before the last edit. The sidecar refuses a bad save regardless.
  return !saving && !checking && view.status?.canSave === true;
}

/**
 * The view for a draft no preview will describe: back at the served draft
 * (Revert, or an edit undone by hand) with no confirmation to send. Then the
 * served draft's own reply is the sidecar's answer, and the last preview's --
 * for a draft that no longer exists -- must not stay up. Null when a preview
 * will run and answer instead.
 */
export function servedView(
  { dirty, confirmedPins }: { dirty: boolean; confirmedPins: boolean },
  baseline: RigView,
): RigView | null {
  return !dirty && !confirmedPins ? baseline : null;
}

/** The sidecar decides; a refusal that names Reset always leaves it usable. */
export function canReset(status: RigStatus | null, saving: boolean): boolean {
  return !saving && status?.canReset === true;
}

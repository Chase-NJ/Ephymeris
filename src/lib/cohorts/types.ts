/**
 * Cohort data model — `DATA.md#data-model`.
 *
 * The wire shapes live in the generated protocol module (`protocol/schema.py`
 * is their authority) and are re-exported here so callers keep one import
 * site; this file adds the client-side constants and helpers.
 *
 * A cohort's world is derived client-side from `id` unless the operator tunes
 * it (`ARCHITECTURE.md#cohort-browser`), so `appearance: null` is the normal
 * state rather than a gap.
 */

export type {
  Sex,
  Group,
  Animal,
  Cohort,
  CohortSummary,
  CohortPatch,
  ProposedAnimal,
  ProposedGroup,
  GroupProposal,
} from "@/lib/ws/protocol";

export const MIN_BOX = 1;
export const MAX_BOX = 6;
/** Box numbers only span 1–6, so a larger group can't be assigned. */
export const MAX_GROUP_SIZE = MAX_BOX;

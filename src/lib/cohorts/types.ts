/**
 * Cohort data model — `cohorts.md` §1.
 *
 * The wire shapes live in the generated protocol module (`protocol/schema.py`
 * is their authority) and are re-exported here so callers keep one import
 * site; this file adds the client-side constants and helpers.
 *
 * The icon is deliberately absent from every payload: it is derived
 * client-side from `id` (`cohorts.md` §5), so nothing about it is stored or
 * transmitted.
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
/** §7.2 — box numbers only span 1–6, so a larger group can't be assigned. */
export const MAX_GROUP_SIZE = MAX_BOX;

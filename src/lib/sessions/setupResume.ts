import { useSyncExternalStore } from "react";

/**
 * Where an unfinished session set-up was left — so the Dashboard tab can take
 * the operator back to it (`dashboard.md` §2.2).
 *
 * The guided steps (`/session/new` → group → mapping → recording) live under
 * the Dashboard tab, and every other tab unmounts them outright. Checking the
 * Rig or a task mid-setup is a normal thing to need, and it used to cost the
 * whole set-up: the step's URL, and everything typed into it, went with the
 * unmount. So two things are remembered here, both in module state for the
 * same reason `unsavedGuard` is (persistent chrome and a route deep in the tree
 * share no provider):
 *
 * - **the step** — the last setup URL visited, which the sidebar's Dashboard
 *   row opens instead of `/` while it holds one;
 * - **drafts** — each step's form, keyed by the step and (past Step 1) the
 *   session and group it belongs to, so a draft can never seed another
 *   session's form.
 *
 * Memory only, never storage: a set-up is today's, and a restart already has
 * the Dashboard dock's "Set-up in progress" rows as its way back in. The
 * sidecar stays the authority on whether the session still exists — the
 * sidebar checks `sessions.active` before offering to resume one.
 */

export type SetupStep = "configure" | "group" | "boxes" | "record";

export interface SetupResume {
  /** Pathname and search, exactly as the step was left. */
  url: string;
  step: SetupStep;
  /** Null at Step 1, which creates the session only when it is left forward. */
  sessionId: string | null;
}

/** The label a step carries on the progress rail (`SessionJourney`). */
export const SETUP_STEP_LABEL: Record<SetupStep, string> = {
  configure: "Configure",
  group: "Group",
  boxes: "Boxes",
  record: "Record",
};

/**
 * Which setup step a path is, or `"control"` for Mission Control (where a
 * set-up is over), or null for anywhere else. Pure, for the tests.
 */
export function setupStepOf(
  pathname: string,
): { step: SetupStep; sessionId: string | null } | "control" | null {
  if (pathname === "/session/new") return { step: "configure", sessionId: null };
  const match = /^\/session\/([^/]+)\/(group|mapping|recording|control)$/.exec(pathname);
  if (!match) return null;
  const [, sessionId, page] = match;
  if (page === "control") return "control";
  const step: SetupStep = page === "group" ? "group" : page === "mapping" ? "boxes" : "record";
  return { step, sessionId: sessionId! };
}

let resume: SetupResume | null = null;
const drafts = new Map<string, unknown>();
const subscribers = new Set<() => void>();

function notify(): void {
  for (const cb of subscribers) cb();
}

function subscribe(cb: () => void): () => void {
  subscribers.add(cb);
  return () => {
    subscribers.delete(cb);
  };
}

/**
 * Called on every navigation. A setup step is remembered; reaching Mission
 * Control ends the set-up; anywhere else leaves the memory alone — that is
 * the whole point of it.
 */
export function noteLocation(pathname: string, search: string): void {
  const where = setupStepOf(pathname);
  if (where === null) return;
  if (where === "control") {
    clearSetupResume();
    return;
  }
  const url = pathname + search;
  if (resume?.url === url) return;
  resume = { url, ...where };
  notify();
}

/**
 * The operator left the set-up on purpose (Cancel, Back to the start, ending
 * the session): nothing to resume, and no draft to come back to.
 */
export function clearSetupResume(): void {
  drafts.clear();
  if (resume === null) return;
  resume = null;
  notify();
}

export function getSetupResume(): SetupResume | null {
  return resume;
}

export function useSetupResume(): SetupResume | null {
  return useSyncExternalStore(subscribe, getSetupResume, () => null);
}

/** A step's saved form, if the operator left it with one. */
export function getSetupDraft<T>(key: string): T | undefined {
  return drafts.get(key) as T | undefined;
}

export function setSetupDraft<T>(key: string, value: T): void {
  drafts.set(key, value);
}

export function clearSetupDraft(key: string): void {
  drafts.delete(key);
}

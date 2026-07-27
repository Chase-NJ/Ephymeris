/**
 * Client-side analytics cache and selection state (`analytics.md` §2.1).
 *
 * Unlike the other slices this is request/response rather than event-mirrored,
 * but the *consumption* problem is identical — five panels, one shared cache,
 * one hot-changing field — so it gets the same keyed-subscription treatment as
 * `HardwareStore` and `SessionStore`, plus `useSyncExternalStore` in
 * `context.ts`.
 *
 * App-level rather than route-scoped on purpose: a cold summary can be an
 * index of an entire archive, and navigating away to check a cohort and back
 * should not pay that twice.
 */

import type { SidecarClient } from "../ws/client";
import { EVT } from "../ws/protocol";
import { getSummary, listSessions } from "./commands";
import type {
  AnalyticsProgress,
  AnalyticsSummary,
  SessionListItem,
} from "./types";

/** Module-scope so identity is stable and `useSyncExternalStore` can bail. */
const NO_SESSIONS: SessionListItem[] = [];

/** The whole-cohort scope, as opposed to one session. */
export const ALL_SESSIONS = "all";

export type LoadState = "idle" | "loading" | "ready" | "error";

export class AnalyticsStore {
  private sessions = new Map<string, SessionListItem[]>();
  private summaries = new Map<string, AnalyticsSummary>();
  private states = new Map<string, LoadState>();
  private errors = new Map<string, string>();
  /** In-flight requests, so StrictMode's double-effect and a fast A→B→A
   *  cohort switch both coalesce onto one call rather than racing. */
  private inflight = new Map<string, Promise<unknown>>();
  private progress: AnalyticsProgress | null = null;

  private cohortId: string | null = null;
  private sessionId: string = ALL_SESSIONS;
  private pinnedAnimal: string | null = null;
  private hoveredAnimal: string | null = null;

  private subscribers = new Map<string, Set<() => void>>();

  // --- subscription ------------------------------------------------------

  subscribe(key: string, callback: () => void): () => void {
    let set = this.subscribers.get(key);
    if (!set) {
      set = new Set();
      this.subscribers.set(key, set);
    }
    set.add(callback);
    return () => set!.delete(callback);
  }

  private notify(key: string): void {
    this.subscribers.get(key)?.forEach((callback) => callback());
  }

  attach(client: SidecarClient): () => void {
    const off = client.on(EVT.ANALYTICS_PROGRESS, (data) => {
      const next = data as AnalyticsProgress | null;
      // Bucketed by cohort so switching mid-scan can't paint the wrong
      // panel's progress.
      if (next && next.cohortId === this.cohortId) {
        this.progress = next;
        this.notify("progress");
      }
    });
    return off;
  }

  // --- selection ---------------------------------------------------------

  getCohortId(): string | null {
    return this.cohortId;
  }

  selectCohort(cohortId: string | null): void {
    if (this.cohortId === cohortId) return;
    this.cohortId = cohortId;
    this.sessionId = ALL_SESSIONS;
    this.pinnedAnimal = null;
    this.hoveredAnimal = null;
    this.progress = null;
    this.notify("cohort");
    this.notify("selection");
    this.notify("highlight");
    this.notify("data");
  }

  getSessionId(): string {
    return this.sessionId;
  }

  selectSession(sessionId: string): void {
    if (this.sessionId === sessionId) return;
    this.sessionId = sessionId;
    this.notify("selection");
  }

  /** Click pins; a second click on the same animal releases it. */
  selectAnimal(animalId: string | null): void {
    const next = this.pinnedAnimal === animalId ? null : animalId;
    if (this.pinnedAnimal === next) return;
    this.pinnedAnimal = next;
    this.notify("selection");
    this.notify("highlight");
  }

  hoverAnimal(animalId: string | null): void {
    if (this.hoveredAnimal === animalId) return;
    this.hoveredAnimal = animalId;
    this.notify("highlight");
  }

  getPinnedAnimal(): string | null {
    return this.pinnedAnimal;
  }

  /** Hover previews, click pins — hover wins while it lasts (§2.3). */
  getHighlightedAnimal(): string | null {
    return this.hoveredAnimal ?? this.pinnedAnimal;
  }

  // --- data --------------------------------------------------------------

  getSessions(cohortId: string | null): SessionListItem[] {
    if (!cohortId) return NO_SESSIONS;
    return this.sessions.get(cohortId) ?? NO_SESSIONS;
  }

  getSummary(cohortId: string | null): AnalyticsSummary | null {
    if (!cohortId) return null;
    return this.summaries.get(cohortId) ?? null;
  }

  getState(cohortId: string | null): LoadState {
    if (!cohortId) return "idle";
    return this.states.get(cohortId) ?? "idle";
  }

  getError(cohortId: string | null): string | null {
    if (!cohortId) return null;
    return this.errors.get(cohortId) ?? null;
  }

  getProgress(): AnalyticsProgress | null {
    return this.progress;
  }

  /**
   * Fetch a cohort's sessions and summary, once.
   *
   * The summary object is then treated as frozen: every session and animal
   * selection filters it client-side (§9). That reference stability is what
   * lets each panel's `useMemo` depend on `[summary, selection]` and stay
   * cheap.
   */
  async load(client: SidecarClient, cohortId: string, force = false): Promise<void> {
    if (!force && this.summaries.has(cohortId)) return;
    const existing = this.inflight.get(cohortId);
    if (existing) {
      await existing;
      return;
    }

    this.states.set(cohortId, "loading");
    this.errors.delete(cohortId);
    this.notify("data");

    const work = (async () => {
      // Sessions first and separately: the sidecar never touches disk for
      // them, so the rail can render while the summary is still reading files.
      const sessions = await listSessions(client, cohortId);
      this.sessions.set(cohortId, sessions);
      this.notify("data");
      const summary = await getSummary(client, cohortId);
      this.summaries.set(cohortId, summary);
    })();

    this.inflight.set(cohortId, work);
    try {
      await work;
      this.states.set(cohortId, "ready");
    } catch (error) {
      this.states.set(cohortId, "error");
      this.errors.set(cohortId, error instanceof Error ? error.message : String(error));
    } finally {
      this.inflight.delete(cohortId);
      this.progress = null;
      this.notify("progress");
      this.notify("data");
    }
  }

  /** Drop a cohort's cache so the next load refetches — after a rescan. */
  invalidate(cohortId: string): void {
    this.summaries.delete(cohortId);
    this.sessions.delete(cohortId);
    this.states.delete(cohortId);
    this.notify("data");
  }
}

/**
 * Client-side analytics cache and selection state (`DATA.md#analytics-views`).
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
  /** Each cohort's `updatedAt` as last broadcast — what tells a roster edit
   *  apart from a broadcast about some other cohort. */
  private stamps = new Map<string, string>();
  /** In-flight requests, so StrictMode's double-effect and a fast A→B→A
   *  cohort switch both coalesce onto one call rather than racing. */
  private inflight = new Map<string, Promise<unknown>>();
  private progress: AnalyticsProgress | null = null;
  /**
   * Bumped on every invalidation, so a *mounted* dashboard refetches.
   *
   * Without it, dropping a cached summary leaves the route staring at nothing:
   * its load effect keys on the cohort id, which invalidation doesn't change,
   * so nothing ever asks again. Reading this in that effect's deps is what
   * turns "the cache is gone" into "go and get it".
   */
  private version = 0;

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
    const offProgress = client.on(EVT.ANALYTICS_PROGRESS, (data) => {
      const next = data as AnalyticsProgress | null;
      // Bucketed by cohort so switching mid-scan can't paint the wrong
      // panel's progress.
      if (next && next.cohortId === this.cohortId) {
        this.progress = next;
        this.notify("progress");
      }
    });
    // A run finishing writes a file and a run record, so some cohort's summary
    // is now behind. The event says which animal and which box, but not which
    // cohort — so this drops all of them rather than guessing at one. That is
    // affordable precisely because the cache is only ever an optimisation and
    // invalidation is lazy: nothing refetches until a view asks.
    const offEnded = client.on(EVT.SESSION_ANIMAL_ENDED, () => this.invalidateAll());
    // A roster edit changes who a summary names — a removal makes a former
    // member (`DATA.md#former-members`), a move takes runs to another cohort —
    // so a cached summary of a cohort that changed is stale. Only that
    // cohort's: the broadcast carries every cohort's `updatedAt`.
    const offCohorts = client.on(EVT.COHORTS_UPDATED, (data) => {
      const cohorts = (data as { cohorts?: Array<{ id: string; updatedAt: string }> } | null)
        ?.cohorts;
      for (const cohort of cohorts ?? []) {
        const seen = this.stamps.get(cohort.id);
        this.stamps.set(cohort.id, cohort.updatedAt);
        if (seen !== cohort.updatedAt && this.summaries.has(cohort.id)) {
          this.invalidate(cohort.id);
        }
      }
    });
    return () => {
      offProgress();
      offEnded();
      offCohorts();
    };
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

  /** Hover previews, click pins — hover wins while it lasts. */
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
   * selection filters it client-side. That reference stability is what
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

    // Stamped at the start and re-checked before each write. A request that
    // was already in the air when something invalidated the cache is carrying
    // an answer to the older question — writing it would put exactly the data
    // the invalidation was meant to discard back into the cache, and leave the
    // route with no reason to ask again.
    const started = this.version;

    const work = (async () => {
      // Sessions first and separately: the sidecar never touches disk for
      // them, so the rail can render while the summary is still reading files.
      const sessions = await listSessions(client, cohortId);
      if (this.version !== started) return;
      this.sessions.set(cohortId, sessions);
      this.notify("data");
      const summary = await getSummary(client, cohortId);
      if (this.version !== started) return;
      this.summaries.set(cohortId, summary);
    })();

    this.inflight.set(cohortId, work);
    try {
      await work;
      // A superseded load leaves the state alone rather than claiming "ready"
      // over an empty cache — the reload the version bump triggers sets
      // "loading" again, so the route shows the notice, not a blank.
      if (this.version === started) this.states.set(cohortId, "ready");
    } catch (error) {
      this.states.set(cohortId, "error");
      this.errors.set(cohortId, error instanceof Error ? error.message : String(error));
    } finally {
      // Only clean up if this is still the current request. A superseded load
      // that tore down the map entry or the progress readout would be doing it
      // to whichever load replaced it.
      if (this.inflight.get(cohortId) === work) {
        this.inflight.delete(cohortId);
        this.progress = null;
        this.notify("progress");
      }
      this.notify("data");
    }
  }

  /**
   * Replace a loaded summary in place, without passing through "loading" —
   * after a false-start ruling, which changes which list a run is in but not
   * whether the cohort is readable. A blank page between two near-identical
   * summaries would be the larger change on screen.
   */
  async refreshSummary(client: SidecarClient, cohortId: string): Promise<void> {
    const started = this.version;
    const summary = await getSummary(client, cohortId);
    if (this.version !== started) return;
    this.summaries.set(cohortId, summary);
    this.notify("data");
  }

  /** Drop a cohort's cache so the next load refetches — after a rescan. */
  invalidate(cohortId: string): void {
    this.summaries.delete(cohortId);
    this.sessions.delete(cohortId);
    this.states.delete(cohortId);
    // Forget the in-flight request too. Its writes are already fenced off by
    // the version check, so leaving it here would only let the next load
    // coalesce onto an answer to the question just invalidated — and then
    // nothing would fetch at all.
    this.inflight.delete(cohortId);
    this.version += 1;
    this.notify("data");
  }

  /** Every cohort at once, for a change whose blast radius isn't known. */
  invalidateAll(): void {
    this.summaries.clear();
    this.sessions.clear();
    this.states.clear();
    this.inflight.clear();
    this.version += 1;
    this.notify("data");
  }

  getVersion(): number {
    return this.version;
  }

  /**
   * Drop a cohort's cache and fetch it again.
   *
   * Dropping *before* fetching is the point, not tidiness: the route renders
   * its panels behind `summary &&`, so clearing first shows the reading
   * notice instead of last time's numbers. When data can't be trusted, show
   * nothing rather than something stale.
   */
  async refresh(client: SidecarClient, cohortId: string): Promise<void> {
    this.invalidate(cohortId);
    await this.load(client, cohortId, true);
  }
}

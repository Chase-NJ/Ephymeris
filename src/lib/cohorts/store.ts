/**
 * Client-side mirror of the sidecar's cohort list.
 *
 * Holds only `CohortSummary` — the grid and the dashboard tile need nothing
 * more, and full detail is fetched per-cohort when one is opened.
 * Fed by `cohorts.updated`, which the sidecar pushes on every mutation and
 * replays on connect, so nothing here polls.
 *
 * Same shape as `HardwareStore`: keyed subscriptions over an immutable
 * snapshot, so `useSyncExternalStore` can bail out on unchanged references.
 */

import type { SidecarClient } from "../ws/client";
import { EVT } from "../ws/protocol";
import type { CohortSummary } from "./types";

const NO_COHORTS: CohortSummary[] = [];

export class CohortStore {
  private cohorts: CohortSummary[] = NO_COHORTS;
  private loaded = false;
  private subs = new Set<() => void>();

  attach(client: SidecarClient): () => void {
    return client.on(EVT.COHORTS_UPDATED, (data) => {
      const payload = data as { cohorts?: CohortSummary[] } | null;
      this.cohorts = payload?.cohorts ?? NO_COHORTS;
      this.loaded = true;
      this.notify();
    });
  }

  getAll(): CohortSummary[] {
    return this.cohorts;
  }

  /**
   * Whether the list reflects the sidecar yet.
   *
   * Distinguishes "no cohorts" from "haven't heard back" — the difference
   * between an honest empty state and a premature one.
   */
  isLoaded(): boolean {
    return this.loaded;
  }

  subscribe(callback: () => void): () => void {
    this.subs.add(callback);
    return () => {
      this.subs.delete(callback);
    };
  }

  /** Clear on disconnect: a stale roster is worse than an empty one. */
  reset(): void {
    if (!this.loaded && this.cohorts === NO_COHORTS) return;
    this.cohorts = NO_COHORTS;
    this.loaded = false;
    this.notify();
  }

  private notify(): void {
    for (const callback of this.subs) callback();
  }
}

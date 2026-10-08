import { useSyncExternalStore } from "react";

/**
 * Exports in flight, app-wide (`ARCHITECTURE.md#export-progress`).
 *
 * Every file the app writes for the operator — a report PNG, a log PDF, the
 * strobe vocabulary — reports here, and `ExportProgress` (mounted once in
 * `AppShell`) draws the card. Module-level rather than a provider's: an export
 * outlives the route that started it, and a card that vanished because the
 * operator clicked to another tab would hide exactly the thing still running.
 *
 * A job is a fixed list of STEPS, declared up front, so the card can say
 * "2 of 4" honestly and draw one segment per step. A step may report a
 * fraction of itself (`progress`) when its worker can say; otherwise its
 * segment breathes instead of filling.
 */

export type ExportKind = "image" | "pdf" | "json";

export interface ExportJob {
  id: number;
  /** What is being written — "Cohort PNG", "Logbook PDF". */
  title: string;
  kind: ExportKind;
  steps: readonly string[];
  /** Index into `steps` of the step under way. */
  step: number;
  /** The current step's own fraction, or null when it cannot say. */
  progress: number | null;
  state: "running" | "done" | "failed";
  /** Where it was written, once done. */
  path: string | null;
  error: string | null;
}

export interface ExportTracker {
  /** Move to a named step (one of the declared ones), optionally part-way. */
  step(name: string, progress?: number | null): void;
  /** The current step's fraction, 0–1. */
  progress(fraction: number): void;
  /** Written to `path`; null means the operator cancelled, which is not news. */
  done(path: string | null): void;
  fail(error: unknown): void;
}

/** The two steps every export ends with — `saveFile` reports them. */
export const SAVE_STEPS = ["Choosing where to save", "Writing"] as const;

/** How long a finished card stays before it leaves on its own. Failures stay. */
export const DONE_LINGER_MS = 5000;

type Listener = () => void;

class ExportJobs {
  private jobs: readonly ExportJob[] = [];
  private listeners = new Set<Listener>();
  private nextId = 1;

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  snapshot = (): readonly ExportJob[] => this.jobs;

  start(title: string, kind: ExportKind, steps: readonly string[]): ExportTracker {
    const id = this.nextId++;
    this.jobs = [
      ...this.jobs,
      { id, title, kind, steps, step: 0, progress: null, state: "running", path: null, error: null },
    ];
    this.emit();

    const patch = (change: Partial<ExportJob>) => {
      let found = false;
      this.jobs = this.jobs.map((job) => {
        if (job.id !== id || job.state !== "running") return job;
        found = true;
        return { ...job, ...change };
      });
      if (found) this.emit();
    };

    return {
      step: (name, progress = null) => {
        const index = steps.indexOf(name);
        patch({ step: index < 0 ? 0 : index, progress });
      },
      progress: (fraction) => patch({ progress: Math.min(Math.max(fraction, 0), 1) }),
      done: (path) => {
        if (path === null) {
          this.dismiss(id);
          return;
        }
        patch({ state: "done", path, step: steps.length - 1, progress: 1 });
      },
      fail: (error) => {
        patch({ state: "failed", error: error instanceof Error ? error.message : String(error) });
      },
    };
  }

  dismiss(id: number): void {
    const next = this.jobs.filter((job) => job.id !== id);
    if (next.length === this.jobs.length) return;
    this.jobs = next;
    this.emit();
  }

  private emit() {
    for (const listener of this.listeners) listener();
  }
}

export const exportJobs = new ExportJobs();

export function useExportJobs(): readonly ExportJob[] {
  return useSyncExternalStore(exportJobs.subscribe, exportJobs.snapshot);
}

/**
 * Run `work` as a tracked export: failures land on the card (and are re-thrown
 * only to callers that ask), a cancelled dialog clears it.
 */
export async function trackExport(
  title: string,
  kind: ExportKind,
  steps: readonly string[],
  work: (tracker: ExportTracker) => Promise<string | null>,
): Promise<string | null> {
  const tracker = exportJobs.start(title, kind, steps);
  try {
    const path = await work(tracker);
    tracker.done(path);
    return path;
  } catch (error) {
    tracker.fail(error);
    throw error;
  }
}

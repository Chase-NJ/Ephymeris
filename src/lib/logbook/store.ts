/**
 * Client-side cache of each cohort's session log (`DATA.md#the-session-log`).
 *
 * The sidecar owns every note; this mirrors what it reports and refetches on
 * `logbook.updated` rather than patching its own copy after a write — a write
 * the sidecar refused or reshaped (a trimmed operator, a normalized time)
 * would otherwise show something the database doesn't hold. Both reads are
 * database-only (`sessions.list`, `logbook.cohort`), so refetching a whole
 * cohort is cheap.
 *
 * Stale data stays on screen while a refetch is in the air: a note appearing
 * should not blank the page under the operator's cursor.
 */

import type { SessionListItem } from "../analytics/types";
import { listSessions } from "../analytics/commands";
import type { SidecarClient } from "../ws/client";
import { EVT } from "../ws/protocol";
import { getLogbook } from "./commands";
import type { LogbookCohort, LogbookUpdated, RunChange, SessionLog, SessionNote } from "./types";

export type LogbookState = "idle" | "loading" | "ready" | "error";

export interface LogbookEntry {
  state: LogbookState;
  error: string | null;
  /** Every session, aborted ones included — the log covers what happened. */
  sessions: SessionListItem[];
  notesBySession: Map<string, SessionNote[]>;
  logs: Map<string, SessionLog>;
  changesBySession: Map<string, RunChange[]>;
  /** Unresolved carry-forward notes, oldest first. */
  openFlags: SessionNote[];
}

const EMPTY: LogbookEntry = {
  state: "idle",
  error: null,
  sessions: [],
  notesBySession: new Map(),
  logs: new Map(),
  changesBySession: new Map(),
  openFlags: [],
};

export function indexLogbook(
  sessions: SessionListItem[],
  data: LogbookCohort,
): Omit<LogbookEntry, "state" | "error"> {
  const notesBySession = new Map<string, SessionNote[]>();
  for (const note of data.notes) {
    const list = notesBySession.get(note.sessionId) ?? [];
    list.push(note);
    notesBySession.set(note.sessionId, list);
  }
  const changesBySession = new Map<string, RunChange[]>();
  for (const change of data.changes) {
    const list = changesBySession.get(change.sessionId) ?? [];
    list.push(change);
    changesBySession.set(change.sessionId, list);
  }
  return {
    sessions,
    notesBySession,
    logs: new Map(data.logs.map((log) => [log.sessionId, log])),
    changesBySession,
    openFlags: data.notes.filter((n) => n.carryForward && n.resolvedAt === null),
  };
}

export class LogbookStore {
  private entries = new Map<string, LogbookEntry>();
  private inflight = new Map<string, Promise<void>>();
  /** A refetch asked for while one was already running — run once more after. */
  private again = new Set<string>();
  private client: SidecarClient | null = null;
  private cohortId: string | null = null;
  private sessionId: string | null = null;
  private subscribers = new Map<string, Set<() => void>>();

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
    this.client = client;
    const refetch = (cohortId: string) => {
      if (this.entries.has(cohortId)) void this.load(cohortId, true);
    };
    const offUpdated = client.on(EVT.LOGBOOK_UPDATED, (data) => {
      refetch((data as LogbookUpdated).cohortId);
    });
    // Lifecycle events don't say which cohort; the reads are database-only,
    // so refetching the one or two cached cohorts is cheaper than guessing.
    const everyCached = () => {
      for (const cohortId of this.entries.keys()) refetch(cohortId);
    };
    const offLifecycle = client.on(EVT.SESSION_LIFECYCLE, everyCached);
    const offEnded = client.on(EVT.SESSION_ANIMAL_ENDED, everyCached);
    return () => {
      offUpdated();
      offLifecycle();
      offEnded();
      this.client = null;
    };
  }

  // --- selection ---------------------------------------------------------

  getCohortId(): string | null {
    return this.cohortId;
  }

  selectCohort(cohortId: string | null): void {
    if (this.cohortId === cohortId) return;
    this.cohortId = cohortId;
    this.sessionId = null;
    this.notify("selection");
  }

  getSessionId(): string | null {
    return this.sessionId;
  }

  selectSession(sessionId: string | null): void {
    if (this.sessionId === sessionId) return;
    this.sessionId = sessionId;
    this.notify("selection");
  }

  // --- data --------------------------------------------------------------

  getEntry(cohortId: string | null): LogbookEntry {
    if (!cohortId) return EMPTY;
    return this.entries.get(cohortId) ?? EMPTY;
  }

  async load(cohortId: string, force = false): Promise<void> {
    const client = this.client;
    if (!client) return;
    if (!force && this.entries.get(cohortId)?.state === "ready") return;
    const running = this.inflight.get(cohortId);
    if (running) {
      if (force) this.again.add(cohortId);
      return running;
    }
    const previous = this.entries.get(cohortId);
    if (!previous) {
      this.entries.set(cohortId, { ...EMPTY, state: "loading" });
      this.notify("data");
    }
    const work = (async () => {
      try {
        const [sessions, data] = await Promise.all([
          listSessions(client, cohortId, true),
          getLogbook(client, cohortId),
        ]);
        this.entries.set(cohortId, { state: "ready", error: null, ...indexLogbook(sessions, data) });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        this.entries.set(cohortId, {
          ...(previous ?? EMPTY),
          state: previous?.state === "ready" ? "ready" : "error",
          error: message,
        });
      } finally {
        this.inflight.delete(cohortId);
        this.notify("data");
      }
      if (this.again.delete(cohortId)) await this.load(cohortId, true);
    })();
    this.inflight.set(cohortId, work);
    return work;
  }
}

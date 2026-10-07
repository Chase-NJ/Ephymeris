/**
 * The session log as a printable document — a plain-data model the PDF
 * renders (`DATA.md#exporting-a-log`). Pure, so what a page says is tested
 * here and the renderer only lays it out; and built from the same helpers the
 * screen uses, so the PDF can't drift from the Log it was exported from.
 */

import { conditionColumns, conditionFor, conditionName, sessionRunsOf } from "../analytics/session";
import type { AnalyticsSummary, SessionListItem, TrialOutcomes } from "../analytics/types";
import { changeParts } from "./changes";
import { elapsedSeconds, formatDuration, formatOffset, longDate, wallClock } from "./clock";
import { newestFirst } from "./rail";
import type { LogbookEntry } from "./store";
import type { NoteScope, NoteTag, SessionNote } from "./types";

export const TAG_LABEL: Record<NoteTag, string> = {
  observation: "Observation",
  intervention: "Intervention",
  hardware: "Hardware",
  "animal-health": "Animal health",
  "protocol-deviation": "Protocol deviation",
};

const STATUS_LABEL: Record<SessionListItem["status"], string> = {
  running: "Running",
  configuring: "Setting up",
  completed: "Completed",
  aborted: "Abandoned",
};

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

export interface DocNote {
  offset: string;
  time: string;
  tag: string;
  scope: string;
  body: string;
  flag: string | null;
}

export interface DocCell {
  sampled: string;
  rate: string;
  /** Under the cohort's minimum — printed, and marked as thin. */
  thin: boolean;
}

export interface DocPerformance {
  /** Condition names after the pooled "all trials" group. */
  conditions: string[];
  rows: Array<{ animal: string; start: string; end: string; cells: DocCell[]; note: string | null }>;
}

export interface DocSession {
  id: string;
  title: string;
  date: string;
  longDate: string;
  status: string;
  start: string;
  end: string;
  elapsed: string;
  setup: string | null;
  operator: string | null;
  summary: string | null;
  notes: DocNote[];
  performance: DocPerformance | null;
  changes: Array<{ animal: string; box: number; parts: string[] }>;
}

export interface DocCohort {
  cohortName: string;
  exportedAt: string;
  span: string;
  sessions: DocSession[];
  noteCount: number;
  openFlags: Array<{ body: string; tag: string; scope: string; from: string }>;
}

/**
 * Text the PDF's embedded faces can actually draw (`DATA.md#exporting-a-log`).
 *
 * The faces are Inter and JetBrains Mono's latin subsets, with Inter's
 * latin-ext and Greek as fallbacks. A character none of them has does not
 * fail: the engine falls through to a built-in face and prints *some other
 * glyph* — "≥ 3" came out "ꞓ3", legible enough to pass a glance and wrong.
 * So the common ones are spelled out, and anything else uncovered prints as a
 * visible "?" rather than as a plausible wrong character.
 */
const PRINT_MAP: Record<string, string> = {
  "→": "->",
  "←": "<-",
  "⇒": "=>",
  "≈": "~",
  "≥": ">=",
  "≤": "<=",
  "≠": "!=",
  "−": "-",
  "✓": "(ok)",
  "✗": "(x)",
};

/** What the embedded faces cover: latin, latin-ext, Greek, general punctuation. */
const COVERED =
  /[\u0000-\u02FF\u0370-\u03FF\u1E00-\u1EFF\u2000-\u206F\u20A0-\u20C0\u2113\u2122\u2191\u2193\u2212\u2215]/u;

export function printable(text: string): string {
  let out = "";
  for (const char of text) {
    const mapped = PRINT_MAP[char];
    if (mapped !== undefined) out += mapped;
    else out += COVERED.test(char) ? char : "?";
  }
  return out;
}

/** Every string in a document model, made printable. */
export function forPrint<T>(value: T): T {
  if (typeof value === "string") return printable(value) as T;
  if (Array.isArray(value)) return value.map(forPrint) as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, forPrint(v)]),
    ) as T;
  }
  return value;
}

export function scopeText(scope: NoteScope, names: Map<string, string>): string {
  if (scope.kind === "animal" && scope.animalId) return names.get(scope.animalId) ?? "unknown animal";
  if (scope.kind === "box" && scope.box !== null) return `Box ${scope.box}`;
  return "Session";
}

function noteRows(notes: readonly SessionNote[], names: Map<string, string>): DocNote[] {
  return [...notes]
    .sort((a, b) => a.at.localeCompare(b.at) || a.createdAt.localeCompare(b.createdAt))
    .map((note) => ({
      offset: formatOffset(note.offsetMs) || "—",
      time: wallClock(note.at),
      tag: TAG_LABEL[note.tag] ?? note.tag,
      scope: scopeText(note.scope, names),
      body: note.body,
      flag: note.carryForward
        ? note.resolvedAt
          ? `resolved ${wallClock(note.resolvedAt)}`
          : "carry forward"
        : null,
    }));
}

function cell(outcomes: TrialOutcomes | null, minCounted: number): DocCell {
  if (!outcomes) return { sampled: "—", rate: "—", thin: false };
  const p = outcomes.pRewarded;
  return {
    sampled: String(outcomes.administered),
    rate: p === null ? "—" : `${Math.round(p * 100)}%`,
    thin: outcomes.administered < minCounted,
  };
}

export function performanceOf(
  summary: AnalyticsSummary,
  sessionId: string,
  names: Map<string, string>,
): DocPerformance | null {
  const runs = sessionRunsOf(summary, sessionId);
  if (runs.length === 0) return null;
  const columns = conditionColumns(runs, summary.profileGroups);
  const min = summary.minCountedTrials;
  const animalNames = new Map(summary.animals.map((a) => [a.id, a.name]));
  return {
    conditions: columns.map((c) => conditionName(c.label)),
    rows: runs.map((run) => ({
      animal: names.get(run.animalId) ?? animalNames.get(run.animalId) ?? run.animalId,
      start: wallClock(run.startedAt),
      end: wallClock(run.endedAt),
      cells: [
        cell(run.outcomes, min),
        ...columns.map((column) => cell(conditionFor(run, column)?.outcomes ?? null, min)),
      ],
      note: run.status === "ok" ? null : (run.detail ?? "not scored"),
    })),
  };
}

export function buildSession(
  session: SessionListItem,
  entry: LogbookEntry,
  summary: AnalyticsSummary | null,
  names: Map<string, string>,
  now: Date,
): DocSession {
  return forPrint(sessionModel(session, entry, summary, names, now));
}

function sessionModel(
  session: SessionListItem,
  entry: LogbookEntry,
  summary: AnalyticsSummary | null,
  names: Map<string, string>,
  now: Date,
): DocSession {
  const live = session.status === "running";
  const open = session.clockEndedAt === null;
  const elapsed = elapsedSeconds(session.clockStartedAt, session.clockEndedAt, now);
  const log = entry.logs.get(session.id) ?? null;
  const changes = (entry.changesBySession.get(session.id) ?? [])
    .map((change) => ({
      animal: names.get(change.animalId) ?? change.animalId,
      box: change.box,
      parts: changeParts(change).map((p) => p.text),
    }))
    .sort((a, b) => collator.compare(a.animal, b.animal));
  return {
    id: session.id,
    title: `${session.prefixName}_${session.sessionNumber}`,
    date: session.date,
    longDate: longDate(session.date),
    status: session.id.startsWith("adopted:") ? "Recovered from files" : STATUS_LABEL[session.status],
    start: wallClock(session.clockStartedAt),
    end: open ? (live ? "running" : "—") : wallClock(session.clockEndedAt),
    elapsed: elapsed === null || (open && !live) ? "—" : formatDuration(elapsed),
    setup:
      session.startedAt !== session.clockStartedAt
        ? `Set-up began ${wallClock(session.startedAt)}`
        : null,
    operator: log?.operator ?? null,
    summary: log?.summary ?? null,
    notes: noteRows(entry.notesBySession.get(session.id) ?? [], names),
    performance: summary ? performanceOf(summary, session.id, names) : null,
    changes,
  };
}

/** The whole cohort, oldest session first — a notebook reads forwards. */
export function buildCohort(
  cohortName: string,
  entry: LogbookEntry,
  summary: AnalyticsSummary | null,
  names: Map<string, string>,
  now: Date,
): DocCohort {
  const ordered = newestFirst(entry.sessions).reverse();
  const byId = new Map(entry.sessions.map((s) => [s.id, s]));
  const first = ordered[0];
  const last = ordered[ordered.length - 1];
  return forPrint({
    cohortName,
    exportedAt: now.toLocaleString("en-GB", { hour12: false }),
    span: first && last ? `${first.date} – ${last.date}` : "no sessions",
    sessions: ordered.map((s) => buildSession(s, entry, summary, names, now)),
    noteCount: [...entry.notesBySession.values()].reduce((n, list) => n + list.length, 0),
    openFlags: entry.openFlags.map((flag) => {
      const origin = byId.get(flag.sessionId);
      return {
        body: flag.body,
        tag: TAG_LABEL[flag.tag] ?? flag.tag,
        scope: scopeText(flag.scope, names),
        from: origin ? `${origin.prefixName}_${origin.sessionNumber} · ${origin.date}` : "an earlier session",
      };
    }),
  });
}

/**
 * Pure helpers for the session summary panel (`DATA.md#pooling-across-tasks`).
 *
 * Kept free of React and of the store, like `view.ts`, and kept separate from
 * it because these answer a different question: `view.ts` serves the
 * across-session panels, all of which are scoped to one task profile; the
 * session summary deliberately is not. It shows **every animal that ran**,
 * whatever sketch its box carried and whether or not its file could be
 * decoded — a session that looks complete when it isn't is the failure these
 * helpers exist to prevent.
 */

import type {
  AnalyticsSummary,
  ConditionOutcomes,
  ProfileGroup,
  RunSummary,
  TrialOutcomes,
} from "./types";
import { OUTCOME_STYLE, type OutcomeKey } from "./view";

/**
 * Numeric-aware and case-insensitive, so `remy2` precedes `remy10` — a plain
 * `localeCompare` sorts them the other way, and a rack of animals named
 * `name<number>` is the common case, not the edge case.
 */
const collator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

/**
 * Every run in the session — **no profile filter, no status filter** — sorted
 * by animal name, then start time so a restart pair keeps its own order.
 *
 * The strategy planes stay profile-scoped internally, because metrics from
 * different tasks are not comparable. This panel is a roll call, not a
 * comparison of metrics: an animal that ran a different sketch that morning,
 * or whose file can't be read, still *ran*, and dropping it silently is how a
 * session looks complete when it isn't.
 */
export function sessionRunsOf(
  summary: AnalyticsSummary,
  sessionId: string,
): RunSummary[] {
  const names = new Map(summary.animals.map((animal) => [animal.id, animal.name]));
  return summary.runs
    .filter((run) => run.sessionId === sessionId)
    .sort((a, b) => {
      const byName = collator.compare(
        names.get(a.animalId) ?? a.animalId,
        names.get(b.animalId) ?? b.animalId,
      );
      return byName !== 0 ? byName : a.startedAt.localeCompare(b.startedAt);
    });
}

/** One condition column of the session table — Go-R, Go-L, or whatever the
 *  session's tasks declare. */
export interface ConditionColumn {
  metricId: string;
  label: string;
  triggerCode: number | null;
}

/**
 * The union of conditions across the session's runs, in first-seen authored
 * order — **derived from the task profiles, never written down**. On the
 * shipped tasks this yields exactly Go-R and Go-L; a run whose task doesn't
 * declare a column simply dashes it.
 *
 * `run.conditions` is the source of truth (it carries id, label and trigger
 * together); `ProfileGroup.metrics` fills in for a run whose outcomes are
 * null, since its `conditions` is empty exactly then and its declared metrics
 * still name real columns.
 */
export function conditionColumns(
  runs: RunSummary[],
  profileGroups: ProfileGroup[],
): ConditionColumn[] {
  const seen = new Map<string, ConditionColumn>();
  for (const run of runs) {
    for (const condition of run.conditions) {
      if (!seen.has(condition.metricId)) {
        seen.set(condition.metricId, {
          metricId: condition.metricId,
          label: condition.label,
          triggerCode: condition.triggerCode,
        });
      }
    }
    if (run.conditions.length === 0 && run.profileHash !== null) {
      const group = profileGroups.find((g) => g.hash === run.profileHash);
      for (const metric of group?.metrics ?? []) {
        if (!seen.has(metric.id)) {
          seen.set(metric.id, {
            metricId: metric.id,
            label: metric.label,
            triggerCode: null,
          });
        }
      }
    }
  }
  return [...seen.values()];
}

/**
 * The condition's own name, out of the metric label that carries it.
 *
 * A metric label is a sentence about a probability — `P(right well | Go
 * right)` — because that is what it titles on a chart axis. A *column group*
 * is not a probability; it is the condition, and the two numbers under it are
 * its count and its rate. So the header wants the operator's own name for the
 * trial type, which is the conditioning half of that sentence.
 *
 * **Display only, never identity.** `metricId` remains what a column is keyed
 * and matched on; this only decides what is printed above it, and the full
 * label stays on hover. Every label the app builds — generated (`generate.py`)
 * and inferred (`infer.py`) alike — has this shape; an authored `task.json`
 * carrying something else keeps its label whole rather than being cut wrongly.
 */
export function conditionName(label: string): string {
  const trimmed = label.trim();
  const bar = trimmed.indexOf("|");
  if (bar < 0 || !trimmed.endsWith(")")) return trimmed;
  // To the LAST paren, not the first: a condition may well be called
  // "Go left (odor 4)", and cutting at the first would drop half its name.
  return trimmed.slice(bar + 1, -1).trim() || trimmed;
}

/**
 * Local wall-clock time of an ISO instant, or an em-dash. The stored strings
 * are UTC-offset ISO (`sessions/repository.py`), so `Date` renders them in
 * this machine's zone — which is what "when did remy1 start" means to the
 * person who was in the room. Same convention as the session dock and
 * Mission Control clocks.
 */
export function formatClock(iso: string | null): string {
  if (!iso) return "—";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "—";
  return when.toLocaleTimeString("en-GB", { hour12: false });
}

/** A clock reading and whether it had to be derived. */
export interface RunClock {
  text: string;
  /** True when the time is start + recorded span rather than a stored end. */
  derived: boolean;
  title: string;
}

/**
 * When this animal's run ended.
 *
 * An adopted archive run carries no `endedAt` — the folder name records when
 * a session started and nothing records when it stopped
 * (`DATA.md#orphan-adoption`). But the file itself does: `durationMs` is the
 * span of the recorded stream, so start plus span *is* the end of recording.
 * Derived rather than dashed, and marked `~` with the reason on hover, because
 * "the archive predates end times" is a fact about the record and an empty
 * column is not the honest way to say it.
 */
export function runEnd(run: RunSummary): RunClock {
  if (run.endedAt) {
    return { text: formatClock(run.endedAt), derived: false, title: "recorded end" };
  }
  const start = run.startedAt ? new Date(run.startedAt) : null;
  if (start && !Number.isNaN(start.getTime()) && run.durationMs !== null) {
    return {
      text: formatClock(new Date(start.getTime() + run.durationMs).toISOString()),
      derived: true,
      title:
        "No end time was recorded — this is the start plus the recorded stream's own span",
    };
  }
  return { text: "—", derived: false, title: "no end time recorded" };
}

/** One stacked-bar segment, in the fixed order of
 *  `DATA.md#rewarded-and-response-accuracy`. */
export interface OutcomePart {
  key: OutcomeKey;
  value: number;
  fill: string;
  label: string;
}

/**
 * The four outcome classes as bar segments, zero-width entries dropped. One
 * definition shared by the per-odor bars, the run-level bar and the detail
 * views, so "the odor rows sum to the run bar" is true by construction.
 */
export function outcomeParts(outcomes: TrialOutcomes): OutcomePart[] {
  return (
    [
      { key: "rewarded" as const, value: outcomes.rewarded },
      { key: "holdFailed" as const, value: outcomes.holdFailed },
      { key: "wrongWell" as const, value: outcomes.wrongWell },
      { key: "noResponse" as const, value: outcomes.noResponse },
    ]
      .filter((part) => part.value > 0)
      .map((part) => ({
        ...part,
        fill: OUTCOME_STYLE[part.key].fill,
        label: OUTCOME_STYLE[part.key].label,
      }))
  );
}

/**
 * Why a run can't be scored, in words an operator can act on. `run.detail`
 * carries the reader's own message for a damaged file; `no-metrics` means the
 * sketch has no task profile, which is a fact about the task rather than a
 * fault in the data.
 */
export function unscoredReason(run: RunSummary): string | null {
  if (run.status === "ok") return null;
  if (run.detail) return run.detail;
  if (run.status === "no-metrics") return "no task profile — nothing to score";
  if (run.status === "missing") return "session file is missing";
  return "session file could not be read";
}

/** The condition entry a table cell reads, or null for a dashed cell. */
export function conditionFor(
  run: RunSummary,
  column: ConditionColumn,
): ConditionOutcomes | null {
  return run.conditions.find((c) => c.metricId === column.metricId) ?? null;
}

/* `programOf` moved to `view.ts`: the across-session panels label their tasks
 * with the same name this panel prints, and one definition is what keeps the
 * two from drifting. Re-exported so the session components' imports still read
 * from the module that owns the rest of their helpers. */
export { programOf } from "./view";

/**
 * The session table's columns (`DATA.md#analytics-views`), as one CSS grid
 * template shared by the header and every row.
 *
 * **One column per condition**, its cell stacking the rewarded share over the
 * sampled count, and the animal's clock and program folded into its own cell —
 * so the table grows by one narrow column per condition instead of a pair of
 * wide ones. Ten conditions fit the Log's readout (about 770px) and Analytics'
 * session panel without a horizontal scroll (`TABLE_FITS_CONDITIONS`); fewer
 * get roomier columns, never wider than reads well.
 */
export const TABLE_COLUMNS = {
  animal: { min: 136, max: "1fr" },
  pooled: { min: 54, max: 72 },
  condition: { min: 46, max: 76 },
  gap: 6,
} as const;

/** The design target the widths are chosen for — pinned by a test. */
export const TABLE_FITS_CONDITIONS = 10;

export function tableTemplate(conditionCount: number): string {
  const { animal, pooled, condition } = TABLE_COLUMNS;
  return [
    `minmax(${animal.min}px,${animal.max})`,
    `minmax(${pooled.min}px,${pooled.max}px)`,
    ...Array.from({ length: conditionCount }, () => `minmax(${condition.min}px,${condition.max}px)`),
  ].join(" ");
}

/** The narrowest the table can be before its wrapper has to scroll. */
export function tableMinWidth(conditionCount: number): number {
  const { animal, pooled, condition, gap } = TABLE_COLUMNS;
  return animal.min + pooled.min + conditionCount * condition.min + (conditionCount + 1) * gap;
}

/** `09:00:00` → `09:00`, for the compact clock under an animal's name. */
export function shortClock(text: string): string {
  return /^\d{2}:\d{2}:\d{2}$/.test(text) ? text.slice(0, 5) : text;
}

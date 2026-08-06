import { motion } from "framer-motion";

import { useIsHighlighted, useAnalyticsStore } from "@/lib/analytics/context";
import {
  conditionFor,
  formatClock,
  programOf,
  runEnd,
  unscoredReason,
  type ConditionColumn,
} from "@/lib/analytics/session";
import type { RunSummary } from "@/lib/analytics/types";
import { OUTCOME_STYLE } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";

/**
 * The session at a glance, one row per animal (`data.md` §11.4) — the
 * comparison the cards cannot give without reading six of them.
 *
 * Columns: animal · start · end · sampled · one *sampled* and one
 * *P(correct)* column per condition · program. The condition columns are the
 * union of what the session's runs declare, in authored order — derived from
 * the task profiles, never written down, so a four-odor task grows the table
 * instead of breaking it (the wrapper scrolls).
 *
 * **P(correct) here is `pRewarded` — reward delivered, the animal held.**
 * That is deliberately stricter than the app's response accuracy (`pSide`,
 * §9.8), which credits a correct well whether or not the hold cleared. The
 * header and legend both say so, because the two look interchangeable and are
 * not.
 */
export function SessionTable({
  runs,
  columns,
  names,
  colors,
  minCounted,
  selectedRunId = null,
  onSelect,
}: {
  runs: RunSummary[];
  columns: ConditionColumn[];
  names: Map<string, string>;
  colors: Map<string, string>;
  minCounted: number;
  /** The run whose card is open in the focus slot — its row stays lit so the
      table says which animal the card below belongs to. */
  selectedRunId?: string | null;
  /** Toggles a card open/closed. Null renders the rows inert — the export
      sheet cannot be clicked. */
  onSelect: ((runId: string) => void) | null;
}) {
  // One template shared by the header and every row — the app's table idiom.
  // Inline rather than a Tailwind class because the condition count is data.
  const template = [
    "minmax(104px,1.2fr)", // animal
    "56px", // start
    "56px", // end
    "62px", // sampled
    ...columns.map(() => "72px"), // per-condition sampled
    ...columns.map(() => "88px"), // per-condition P(correct)
    "minmax(96px,1fr)", // program
  ].join(" ");

  return (
    <div className="scrollbar-none overflow-x-auto">
      <div className="min-w-[560px]">
        <div
          className="grid items-end gap-x-2 border-b border-halo pb-1 font-mono text-[9px] text-static/70"
          style={{ gridTemplateColumns: template }}
        >
          <span>animal</span>
          <span className="text-right">start</span>
          <span className="text-right">end</span>
          <span className="text-right" title="Trials whose odor was sampled to completion — the denominator of every rate here">
            sampled
          </span>
          {columns.map((column) => (
            <span key={`n-${column.metricId}`} className="flex min-w-0 flex-col items-end">
              <span className="w-full truncate text-right text-static/50" title={column.label}>
                {column.label}
              </span>
              <span>sampled</span>
            </span>
          ))}
          {columns.map((column) => (
            <span
              key={`p-${column.metricId}`}
              className="flex min-w-0 flex-col items-end"
              title={`Of the administered ${column.label} trials, how many ended with the reward delivered — the animal chose the correct well and held`}
            >
              <span className="w-full truncate text-right text-static/50">{column.label}</span>
              <span>P(correct)</span>
            </span>
          ))}
          <span className="text-right">program</span>
        </div>

        {runs.map((run, index) => (
          <TableRow
            key={run.runId}
            run={run}
            name={names.get(run.animalId) ?? run.animalId}
            color={colors.get(run.animalId) ?? "var(--color-series-1)"}
            columns={columns}
            template={template}
            minCounted={minCounted}
            index={index}
            selected={selectedRunId === run.runId}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * One animal's row. A separate component per animal because that is what the
 * cross-panel highlight scheme requires (`context.ts`'s `useIsHighlighted`
 * invariant) — a single component looping over animals would silently lose it.
 */
function TableRow({
  run,
  name,
  color,
  columns,
  template,
  minCounted,
  index,
  selected,
  onSelect,
}: {
  run: RunSummary;
  name: string;
  color: string;
  columns: ConditionColumn[];
  template: string;
  minCounted: number;
  index: number;
  selected: boolean;
  onSelect: ((runId: string) => void) | null;
}) {
  const store = useAnalyticsStore();
  const highlighted = useIsHighlighted(run.animalId);
  const reason = unscoredReason(run);
  // An unscored run's card has nothing to expand into (`AnimalCard` withholds
  // its own toggle for the same reason), so its row offers no click either —
  // a row that "opens" an unexpandable card reads as a broken click.
  const toggle = reason ? null : onSelect;

  return (
    <motion.div
      className={`grid items-center gap-x-2 border-b border-halo/50 py-1.5 transition-colors ${
        selected ? "bg-halo/60" : highlighted ? "bg-halo/40" : ""
      } ${reason ? "opacity-60" : ""} ${toggle ? "cursor-pointer" : ""}`}
      style={{ gridTemplateColumns: template }}
      onPointerEnter={() => store.hoverAnimal(run.animalId)}
      onPointerLeave={() => store.hoverAnimal(null)}
      onClick={toggle ? () => toggle(run.runId) : undefined}
      role={toggle ? "button" : undefined}
      tabIndex={toggle ? 0 : undefined}
      onKeyDown={
        toggle
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                toggle(run.runId);
              }
            }
          : undefined
      }
      aria-expanded={toggle ? selected : undefined}
      title={
        toggle
          ? selected
            ? `Close ${name}'s card`
            : `Open ${name}'s card`
          : undefined
      }
      initial={{ opacity: 0, y: 3 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...springSnappy, delay: index * 0.03 }}
    >
      <span className="flex min-w-0 items-center gap-1.5">
        <span
          className="size-2 shrink-0 rounded-full"
          style={{ background: color, opacity: highlighted || selected ? 1 : 0.85 }}
        />
        <span
          className={`truncate text-[11px] ${
            highlighted || selected ? "text-starlight" : "text-static"
          }`}
        >
          {name}
        </span>
      </span>
      <span
        className="text-right font-mono text-[10px] tabular-nums text-static/80"
        title="when this animal's run began"
      >
        {formatClock(run.startedAt)}
      </span>
      <EndClock run={run} />
      <span className="text-right font-mono text-[11px] tabular-nums text-starlight">
        {run.outcomes ? run.outcomes.administered : "—"}
      </span>
      {columns.map((column) => {
        const condition = conditionFor(run, column);
        return (
          <span
            key={`n-${column.metricId}`}
            className="text-right font-mono text-[11px] tabular-nums text-starlight"
          >
            {condition ? condition.outcomes.administered : "—"}
          </span>
        );
      })}
      {columns.map((column) => (
        <PCell
          key={`p-${column.metricId}`}
          condition={conditionFor(run, column)}
          label={column.label}
          minCounted={minCounted}
        />
      ))}
      <span
        className="truncate text-right font-mono text-[10px] text-static/80"
        title={reason ? `${run.sketchPath}\nnot scored — ${reason}` : run.sketchPath}
      >
        {reason && (
          <span style={{ color: "var(--color-status-warning)" }} title={reason}>
            ⚠{" "}
          </span>
        )}
        {programOf(run)}
      </span>
    </motion.div>
  );
}

/** A derived end reads `~hh:mm:ss` — the tilde is the whole disclosure, and
 *  the title says what it was derived from. */
function EndClock({ run }: { run: RunSummary }) {
  const end = runEnd(run);
  return (
    <span
      className={`text-right font-mono text-[10px] tabular-nums ${
        end.derived ? "text-static/60" : "text-static/80"
      }`}
      title={end.title}
    >
      {end.derived && "~"}
      {end.text}
    </span>
  );
}

/**
 * One `P(correct | condition)` cell: the percentage over a thin bar of the
 * same width, so a column of rows reads as a bar chart without leaving the
 * table. Below `minCounted` administered trials the cell dims and carries its
 * n — flagged, never suppressed (§3.5).
 */
function PCell({
  condition,
  label,
  minCounted,
}: {
  condition: ReturnType<typeof conditionFor>;
  label: string;
  minCounted: number;
}) {
  const p = condition?.outcomes.pRewarded ?? null;
  if (condition === null || p === null) {
    return (
      <span className="text-right font-mono text-[11px] tabular-nums text-static/50">—</span>
    );
  }
  const administered = condition.outcomes.administered;
  const thin = administered < minCounted;
  return (
    <span
      className="flex min-w-0 flex-col items-end"
      title={`${condition.outcomes.rewarded} of ${administered} administered ${label} trials rewarded${
        thin ? ` — under ${minCounted} trials, read loosely` : ""
      }`}
    >
      <span
        className={`font-mono text-[11px] tabular-nums ${
          thin ? "text-static/60" : "text-starlight"
        }`}
      >
        {Math.round(p * 100)}%
        {thin && <span className="text-[9px] text-static/50"> ({administered})</span>}
      </span>
      <span className="h-[2px] w-full max-w-[72px] rounded-full bg-halo/60">
        <span
          className="block h-full rounded-full"
          style={{
            width: `${p * 100}%`,
            background: OUTCOME_STYLE.rewarded.fill,
            opacity: thin ? 0.45 : 1,
          }}
        />
      </span>
    </span>
  );
}

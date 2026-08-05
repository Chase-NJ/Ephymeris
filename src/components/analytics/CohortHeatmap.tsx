import { motion } from "framer-motion";
import { useId, useMemo } from "react";

import { useRevealOnView } from "@/components/charts/reveal";
import { useAnalyticsStore, useIsHighlighted } from "@/lib/analytics/context";
import type { AnalyticsSummary } from "@/lib/analytics/types";
import {
  binFor,
  cellAt,
  labelColor,
  pivotRuns,
  taskLabels,
  type Cell,
} from "@/lib/analytics/view";

/**
 * Animals × sessions (`data.md` §11.3).
 *
 * The fastest way to see a whole cohort: who is learning, who is stuck. Also
 * the navigator — clicking a cell selects that animal *and* that session.
 *
 * Uses `preserveAspectRatio="xMidYMid meet"`, deliberately unlike the trend
 * charts: cells carry their value as SVG text, and the `"none"` stretch those
 * charts rely on would distort glyphs. `ConstellationStatus` already
 * establishes `meet` as the house choice for grid-like SVG.
 */

const CELL = 1;
const GAP = 0.12;
const GROUP_GAP = 0.5;
const MIN_PX_PER_COLUMN = 34;
/** The task header strip's height, in cell units — room for one line of
 *  task labels above the grid, marking where the cohort changed task. */
const HEADER_H = 0.55;

/** Label gutter, in the same unit space as the cells.
 *
 *  Row labels live *inside* the SVG rather than in an HTML column beside it:
 *  group gaps make row offsets irregular, and keeping two layout systems in
 *  agreement about them is a bug waiting to happen. `meet` scaling keeps the
 *  glyphs undistorted, so there is no reason to pay that cost. */
const LABEL_W = 2.6;

export function CohortHeatmap(props: {
  summary: AnalyticsSummary;
  sessionScope: string;
  /** Changes when the data does — replays the column-by-column reveal. */
  revealKey: string;
  /**
   * Whether the grid may scroll sideways when it outgrows its column.
   *
   * On the dashboard it must — the SVG is sized in fixed pixels per column
   * (see `MIN_PX_PER_COLUMN`) because `meet` scaling would otherwise turn a
   * five-session, twenty-animal cohort into a chart thousands of pixels tall.
   * A report sheet passes `false` instead and grows to fit: a scroll container
   * rasterizes to whatever was visible, which would silently crop the most
   * recent sessions — the ones the reader is looking for (`data.md` §10.6).
   */
  scroll?: boolean;
}) {
  // Keyed on the reveal, so new data remounts the body and its visibility
  // gate re-arms — the column fill waits to be seen all over again (§2.7).
  return <HeatmapBody key={props.revealKey} {...props} />;
}

function HeatmapBody({
  summary,
  sessionScope,
  revealKey,
  scroll = true,
}: {
  summary: AnalyticsSummary;
  sessionScope: string;
  revealKey: string;
  scroll?: boolean;
}) {
  const store = useAnalyticsStore();
  const { ref, seen } = useRevealOnView();
  // Per instance, because a report sheet is mounted alongside the live
  // dashboard: two `<pattern>`s sharing one id in a document means every
  // `url(#…)` resolves to whichever came first.
  const patternId = `analytics-too-few-${useId()}`;

  const rows = useMemo(() => layoutRows(summary), [summary]);

  // Every session, every task. The cell value is each run's **overall pooled
  // accuracy** — fraction correct at whatever that animal was doing that day
  // (§3.7) — so a shaping cell and a discrimination cell are the same kind of
  // number at different difficulty. The task header row is the disclosure: a
  // column of suddenly-worse cells under a new task label is a task change,
  // not a cohort forgetting. Runs that failed to decode are kept: "ran but
  // scored nothing" is a distinction §6.1 exists to preserve.
  const sessions = summary.sessions;
  const labels = useMemo(() => taskLabels(summary), [summary]);
  // Dominant task per session column, for the header strip and boundaries.
  const columnTasks = useMemo(
    () =>
      sessions.map((session) => {
        const counts = new Map<string, number>();
        for (const run of summary.runs) {
          if (run.sessionId !== session.id) continue;
          const hash = run.profileHash ?? "";
          counts.set(hash, (counts.get(hash) ?? 0) + 1);
        }
        let best = "";
        let most = -1;
        for (const [hash, count] of counts) {
          if (count > most) [best, most] = [hash, count];
        }
        return { hash: best, mixed: counts.size > 1 };
      }),
    [summary, sessions],
  );

  const pivot = useMemo(
    // metricId null → each run's pooled overall (§3.7), the honest default.
    () => pivotRuns(summary.runs, null, summary.minCountedTrials),
    [summary],
  );

  if (summary.sessions.length === 0) {
    return (
      <div className="surface rounded-md p-4">
        <p className="text-[12px] leading-relaxed text-static">
          This cohort has no recorded sessions yet.
        </p>
      </div>
    );
  }

  const columns = sessions.length;
  const width = LABEL_W + columns * (CELL + GAP);
  const body = rows.length === 0 ? CELL : rows[rows.length - 1]!.y + CELL;
  const height = HEADER_H + body;

  return (
    <div className="surface rounded-md p-4" ref={ref}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[11px] text-static">
          Animals × sessions
          <span className="ml-2 text-static/70">
            fraction correct at that day&rsquo;s task — labels above mark the
            task changes
          </span>
        </span>
        <Scale />
      </div>

      <div className="mt-2">
        <div className={scroll ? "min-w-0 overflow-x-auto" : "min-w-0"}>
          <svg
            viewBox={`0 0 ${width} ${height}`}
            width={Math.max(LABEL_W * MIN_PX_PER_COLUMN + columns * MIN_PX_PER_COLUMN, 200)}
            height={(height / width) * (LABEL_W + columns) * MIN_PX_PER_COLUMN}
            preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-label="Per-animal performance by session"
          >
            <defs>
              {/* One pattern, referenced by every too-few cell. */}
              <pattern
                id={patternId}
                width={0.3}
                height={0.3}
                patternUnits="userSpaceOnUse"
                patternTransform="rotate(45)"
              >
                <line
                  x1={0}
                  y1={0}
                  x2={0}
                  y2={0.3}
                  stroke="var(--color-halo)"
                  strokeWidth={0.09}
                />
              </pattern>
            </defs>
            <TaskHeader
              columnTasks={columnTasks}
              labels={labels}
              gridHeight={body}
            />
            {rows.map((row) => (
              <RowLabel key={`label-${row.animalId}`} row={row} />
            ))}
            {rows.map((row) =>
              sessions.map((session, column) => {
                const cell = cellAt(pivot, row.animalId, session.id);
                return (
                <HeatCell
                  key={`${row.animalId}-${session.id}`}
                  cell={cell}
                  x={LABEL_W + column * (CELL + GAP)}
                  y={HEADER_H + row.y}
                  taskLabel={
                    cell.run ? (labels.get(cell.run.profileHash ?? "") ?? null) : null
                  }
                  patternId={patternId}
                  // The surface fills in the order the sessions happened, so
                  // the reveal reads as history being laid down rather than as
                  // a grid switching on.
                  reveal={`${revealKey}:${column}`}
                  seen={seen}
                  delay={column * 0.022}
                  emphasised={sessionScope === session.id}
                  animalName={row.name}
                  sessionLabel={`${session.prefixName} ${session.sessionNumber} · ${session.date}`}
                  onSelect={() => {
                    store.selectAnimal(row.animalId);
                    store.selectSession(session.id);
                  }}
                  onHover={(on) => store.hoverAnimal(on ? row.animalId : null)}
                />
                );
              }),
            )}
          </svg>
        </div>
      </div>
    </div>
  );
}

/**
 * The task strip above the grid: a label where a run of columns starts a new
 * dominant task, and a dashed rule down the grid at each boundary. This is
 * what lets every session share one surface honestly — the colour scale is
 * "fraction correct", and the header says at what.
 */
function TaskHeader({
  columnTasks,
  labels,
  gridHeight,
}: {
  columnTasks: Array<{ hash: string; mixed: boolean }>;
  labels: Map<string, string>;
  gridHeight: number;
}) {
  const starts: Array<{ column: number; hash: string }> = [];
  columnTasks.forEach((task, column) => {
    if (column === 0 || task.hash !== columnTasks[column - 1]!.hash) {
      starts.push({ column, hash: task.hash });
    }
  });
  // A single-task archive needs no header — the panel title already says
  // what the numbers are, and one label over everything would be noise.
  if (starts.length <= 1) return null;

  return (
    <g>
      {starts.map(({ column, hash }, index) => {
        const x = LABEL_W + column * (CELL + GAP);
        const label = labels.get(hash) ?? "unknown";
        const until = index + 1 < starts.length ? starts[index + 1]!.column : columnTasks.length;
        const mixed = columnTasks
          .slice(column, until)
          .some((task) => task.mixed);
        // A label only where it fits inside its own segment — two-column
        // alternations would otherwise print labels through each other, and
        // an overlapped label is worse than none: the boundary rule still
        // marks the change, and any cell's hover names its task. ~0.16 units
        // per glyph at this font size, measured, not guessed.
        const room = until * (CELL + GAP) - column * (CELL + GAP) - 0.1;
        const fits = (label.length + (mixed ? 2 : 0)) * 0.16 <= room;
        return (
          <g key={`${hash}-${column}`}>
            {fits && (
              <text
                x={x}
                y={HEADER_H - 0.18}
                fontFamily="var(--font-mono)"
                fontSize={0.26}
                fill="var(--color-static)"
                opacity={0.8}
              >
                {label}
                {mixed ? " +" : ""}
              </text>
            )}
            {column > 0 && (
              <line
                x1={x - GAP / 2}
                y1={0}
                x2={x - GAP / 2}
                y2={HEADER_H + gridHeight}
                stroke="var(--color-halo)"
                strokeWidth={0.03}
                strokeDasharray="0.12 0.12"
              />
            )}
          </g>
        );
      })}
    </g>
  );
}

/**
 * One instance per animal, so a hover re-renders two labels rather than the
 * whole grid — the memoization the "am I highlighted" hook exists for.
 */
function RowLabel({ row }: { row: Row }) {
  const highlighted = useIsHighlighted(row.animalId);
  return (
    <text
      x={LABEL_W - 0.2}
      y={HEADER_H + row.y + CELL / 2}
      textAnchor="end"
      dominantBaseline="central"
      fontFamily="var(--font-mono)"
      fontSize={0.32}
      fill={highlighted ? "var(--color-starlight)" : "var(--color-static)"}
    >
      {row.name}
    </text>
  );
}

function HeatCell({
  cell,
  x,
  y,
  taskLabel,
  patternId,
  reveal,
  seen,
  delay,
  emphasised,
  animalName,
  sessionLabel,
  onSelect,
  onHover,
}: {
  cell: Cell;
  x: number;
  y: number;
  /** The task the cell's run was on — the per-cell half of the disclosure the
   *  header strip makes per column. Null when nothing ran. */
  taskLabel: string | null;
  /** This grid's own hatch pattern — see `HeatmapBody`. */
  patternId: string;
  reveal: string;
  /** The grid is on screen — until then the fill holds at nothing (§2.7). */
  seen: boolean;
  delay: number;
  emphasised: boolean;
  animalName: string;
  sessionLabel: string;
  onSelect: () => void;
  onHover: (on: boolean) => void;
}) {
  const shared = {
    onClick: onSelect,
    onPointerEnter: () => onHover(true),
    onPointerLeave: () => onHover(false),
    style: { cursor: "pointer" as const },
    // `key` on the motion group restarts the reveal when the data changes;
    // without it a cohort swap would repaint silently.
    key: reveal,
    initial: { opacity: 0 },
    animate: { opacity: seen ? 1 : 0 },
    transition: { duration: 0.28, delay },
  };

  const title = `${animalName} · ${sessionLabel}${
    taskLabel ? ` · ${taskLabel}` : ""
  }\n${describe(cell)}`;

  // Absent is an outline and never a fill: a pale cell would read as "got
  // everything wrong" rather than "didn't run" (§6.1).
  if (cell.kind === "absent") {
    return (
      <motion.g {...shared}>
        <title>{title}</title>
        <rect
          x={x}
          y={y}
          width={CELL}
          height={CELL}
          fill="none"
          stroke="var(--color-halo)"
          strokeWidth={0.04}
          rx={0.1}
        />
      </motion.g>
    );
  }

  if (cell.kind === "tooFew") {
    return (
      <motion.g {...shared}>
        <title>{title}</title>
        <rect
          x={x}
          y={y}
          width={CELL}
          height={CELL}
          fill={`url(#${patternId})`}
          stroke="var(--color-halo)"
          strokeWidth={0.04}
          rx={0.1}
        />
        <text
          x={x + CELL / 2}
          y={y + CELL / 2}
          textAnchor="middle"
          dominantBaseline="central"
          fontFamily="var(--font-mono)"
          fontSize={0.26}
          fill="var(--color-static)"
        >
          n={cell.counted}
        </text>
      </motion.g>
    );
  }

  const bin = binFor(cell.value ?? 0);
  return (
    <motion.g {...shared}>
      <title>{title}</title>
      <rect
        x={x}
        y={y}
        width={CELL}
        height={CELL}
        fill={bin.fill}
        rx={0.1}
        stroke={emphasised ? "var(--color-starlight)" : "none"}
        strokeWidth={emphasised ? 0.06 : 0}
      />
      <text
        x={x + CELL / 2}
        y={y + CELL / 2}
        textAnchor="middle"
        dominantBaseline="central"
        fontFamily="var(--font-mono)"
        fontSize={0.3}
        fill={labelColor(bin)}
      >
        {cell.value!.toFixed(2)}
      </text>
    </motion.g>
  );
}

function describe(cell: Cell): string {
  if (cell.kind === "absent") {
    if (!cell.run) return "did not run";
    if (cell.run.status === "missing") return `no data file — ${cell.run.detail ?? ""}`;
    if (cell.run.status === "unreadable") return `file unreadable — ${cell.run.detail ?? ""}`;
    return "ran, but produced no scored metrics";
  }
  if (cell.kind === "tooFew") {
    return cell.counted === 0
      ? "ran, but no trial scored"
      : `only ${cell.counted} scored trials — too few to read`;
  }
  const parts = [`P = ${cell.value!.toFixed(3)} over ${cell.counted} trials`];
  if (cell.run?.profileSource === "sketch-current") {
    parts.push("decoded with the current task.json, which may have changed");
  }
  if (cell.run?.stale) parts.push("file missing — showing the last known value");
  if (cell.hasSiblings) parts.push("another run exists for this animal and session");
  return parts.join("\n");
}

function Scale() {
  return (
    <span className="flex items-center gap-1 font-mono text-[9px] text-static/80">
      <span>0</span>
      {[0.1, 0.3, 0.4, 0.5, 0.6, 0.75, 0.95].map((value) => (
        <span
          key={value}
          className="inline-block size-2.5 rounded-[2px]"
          style={{ backgroundColor: binFor(value).fill }}
        />
      ))}
      <span>1</span>
      <span className="ml-1 text-static/60">chance at 0.5</span>
    </span>
  );
}

interface Row {
  animalId: string;
  name: string;
  y: number;
}

/** Numeric-aware, so `remy2` sorts before `remy10` — the session summary's
 *  ordering rule, applied to the rows here too. */
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/** Rows grouped by group, with a gap between groups. */
function layoutRows(summary: AnalyticsSummary): Row[] {
  const order = new Map(summary.groups.map((group) => [group.id, group.order]));
  const animals = [...summary.animals].sort((a, b) => {
    const byGroup = (order.get(a.groupId) ?? 0) - (order.get(b.groupId) ?? 0);
    return byGroup !== 0 ? byGroup : collator.compare(a.name, b.name);
  });

  let y = 0;
  let previousGroup: string | null = null;
  return animals.map((animal) => {
    if (previousGroup !== null && animal.groupId !== previousGroup) y += GROUP_GAP;
    const row = { animalId: animal.id, name: animal.name, y };
    previousGroup = animal.groupId;
    y += CELL + GAP;
    return row;
  });
}

import { motion } from "framer-motion";
import { useMemo } from "react";

import { useAnalyticsStore, useIsHighlighted } from "@/lib/analytics/context";
import type { AnalyticsSummary, ProfileGroup } from "@/lib/analytics/types";
import { binFor, cellAt, labelColor, pivotRuns, type Cell } from "@/lib/analytics/view";

/**
 * Animals × sessions (`analytics.md` §6).
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
/** Label gutter, in the same unit space as the cells.
 *
 *  Row labels live *inside* the SVG rather than in an HTML column beside it:
 *  group gaps make row offsets irregular, and keeping two layout systems in
 *  agreement about them is a bug waiting to happen. `meet` scaling keeps the
 *  glyphs undistorted, so there is no reason to pay that cost. */
const LABEL_W = 2.6;

export function CohortHeatmap({
  summary,
  profile,
  metricId,
  sessionScope,
  revealKey,
}: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  metricId: string | null;
  sessionScope: string;
  /** Changes when the data does — replays the column-by-column reveal. */
  revealKey: string;
}) {
  const store = useAnalyticsStore();

  const rows = useMemo(() => layoutRows(summary), [summary]);

  // Scoped to one task profile, like every other panel (§4.3). A shaping
  // column beside a discrimination column shares a colour scale while the two
  // numbers mean different things — the surface would read as a performance
  // collapse where the task simply changed. Runs that failed to decode are
  // kept: their profile is still known, and "ran but scored nothing" is a
  // distinction §6.1 exists to preserve.
  const runs = useMemo(
    () => (profile ? summary.runs.filter((run) => run.profileHash === profile.hash) : summary.runs),
    [summary, profile],
  );
  const sessions = useMemo(() => {
    if (!profile) return summary.sessions;
    const inProfile = new Set(runs.map((run) => run.sessionId));
    return summary.sessions.filter((session) => inProfile.has(session.id));
  }, [summary, profile, runs]);
  const omitted = summary.sessions.length - sessions.length;

  const pivot = useMemo(
    () => pivotRuns(runs, metricId, summary.minCountedTrials),
    [runs, metricId, summary.minCountedTrials],
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

  if (sessions.length === 0) {
    return (
      <div className="surface rounded-md p-4">
        <p className="text-[12px] leading-relaxed text-static">
          No sessions ran{" "}
          <span className="text-starlight">{profile?.taskName ?? "this task"}</span>. Pick
          another task to see its sessions.
        </p>
      </div>
    );
  }

  const columns = sessions.length;
  const width = LABEL_W + columns * (CELL + GAP);
  const height = rows.length === 0 ? CELL : rows[rows.length - 1]!.y + CELL;

  return (
    <div className="surface rounded-md p-4">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[11px] text-static">
          Animals × sessions
          {profile ? <span className="ml-2 text-static/70">{profile.taskName}</span> : null}
          {/* Say what was left out — a filter that silently drops columns is
              indistinguishable from an archive that never had them. */}
          {omitted > 0 && (
            <span className="ml-2 text-static/60">
              · {omitted} session{omitted === 1 ? "" : "s"} on another task hidden
            </span>
          )}
        </span>
        <Scale />
      </div>

      <div className="mt-2">
        <div className="min-w-0 overflow-x-auto">
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
                id="analytics-too-few"
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
            {rows.map((row) => (
              <RowLabel key={`label-${row.animalId}`} row={row} />
            ))}
            {rows.map((row) =>
              sessions.map((session, column) => (
                <HeatCell
                  key={`${row.animalId}-${session.id}`}
                  cell={cellAt(pivot, row.animalId, session.id)}
                  x={LABEL_W + column * (CELL + GAP)}
                  y={row.y}
                  scoped={profile !== null}
                  // The surface fills in the order the sessions happened, so
                  // the reveal reads as history being laid down rather than as
                  // a grid switching on.
                  reveal={`${revealKey}:${column}`}
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
              )),
            )}
          </svg>
        </div>
      </div>
    </div>
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
      y={row.y + CELL / 2}
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
  scoped,
  reveal,
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
  /** Whether the grid is filtered to one task profile. */
  scoped: boolean;
  reveal: string;
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
    animate: { opacity: 1 },
    transition: { duration: 0.28, delay },
  };

  const title = `${animalName} · ${sessionLabel}\n${describe(cell, scoped)}`;

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
          fill="url(#analytics-too-few)"
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

function describe(cell: Cell, scoped: boolean): string {
  if (cell.kind === "absent") {
    // Scoped to a task, an empty cell means "not on *this* task" — the animal
    // may well have run something else that day, and one session really can
    // hold shaping and discrimination side by side across a cohort.
    if (!cell.run) return scoped ? "no run on this task" : "did not run";
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

/** Rows grouped by group, with a gap between groups. */
function layoutRows(summary: AnalyticsSummary): Row[] {
  const order = new Map(summary.groups.map((group) => [group.id, group.order]));
  const animals = [...summary.animals].sort((a, b) => {
    const byGroup = (order.get(a.groupId) ?? 0) - (order.get(b.groupId) ?? 0);
    return byGroup !== 0 ? byGroup : a.name.localeCompare(b.name);
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

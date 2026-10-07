import { ClipboardList } from "lucide-react";
import { motion } from "framer-motion";
import { useMemo, useState } from "react";

import { AnimalCard } from "@/components/analytics/session/AnimalCard";
import { SessionTable, TableKey } from "@/components/analytics/session/SessionTable";
import { PanelTitle } from "@/components/charts/PanelTitle";
import { FolderButton } from "@/components/common/FolderButton";
import { conditionColumns } from "@/lib/analytics/session";
import type {
  AnalyticsSummary,
  RunSeries,
  RunSummary,
  SessionListItem,
} from "@/lib/analytics/types";
import { OUTCOME_STYLE, poolOutcomes } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";

/**
 * One session, per animal (`DATA.md#pooling-across-tasks`,
 * `DATA.md#rewarded-and-response-accuracy`).
 *
 * The panel answers "what happened in this session" at a glance, which the
 * cohort-scale views deliberately cannot: they compare sessions, this one
 * opens a single one up.
 *
 * **Every animal that ran is here**, in name order — whatever sketch its box
 * carried (named on its tile and in the table) and whether or not its file
 * decoded (muted, with the reason). The across-session panels stay scoped to
 * one task profile because their metrics must be comparable; this one is a
 * roll call, and an animal missing from it reads as "didn't run", which is
 * the one thing the panel must never say wrongly.
 *
 * Reads top to bottom as: the headline, the comparison table (one row per
 * animal), then one card per animal — effort, each condition's counts with
 * how its trials resolved, the whole run's resolution — and clicking a card
 * opens the per-animal detail views.
 */
export function SessionSummary({
  summary,
  colors,
  session,
  runs,
  series,
  revealKey,
  columns = "auto",
  interactive = true,
}: {
  summary: AnalyticsSummary;
  colors: Map<string, string>;
  session: SessionListItem;
  runs: RunSummary[];
  series: RunSeries[];
  revealKey: string;
  /**
   * How many animal cards sit side by side.
   *
   * `"auto"` is the dashboard's `xl:` breakpoint, which is a **viewport**
   * query — fine on screen, wrong for a report sheet, whose own width has
   * nothing to do with the window's. Left on auto, an export taken from a
   * narrow window would silently come out one card wide
   * (`DATA.md#exporting-a-sheet`).
   */
  columns?: 1 | 2 | "auto";
  /** False renders everything inert — the export sheet cannot be clicked. */
  interactive?: boolean;
}) {
  const names = useMemo(
    () => new Map(summary.animals.map((animal) => [animal.id, animal.name])),
    [summary],
  );
  const tableColumns = useMemo(
    () => conditionColumns(runs, summary.profileGroups),
    [runs, summary],
  );
  // Which card is open. Single-open: two expanded tape views on one screen
  // compete for a reading nobody asked for.
  const [expanded, setExpanded] = useState<string | null>(null);

  // The open card is **promoted to a focus slot** — the first cell of the
  // grid, full width, directly under the table — rather than expanding in
  // place. In place, "which card grew" depended on where that animal happened
  // to sit, so clicking down the table meant chasing the expansion around the
  // grid (and scrolling after it). One slot means every row click lands the
  // card in the same spot; the layout spring on each card makes the promotion
  // legible as movement rather than a cut.
  const ordered = useMemo(() => {
    const focus = runs.find((run) => run.runId === expanded);
    return focus ? [focus, ...runs.filter((run) => run !== focus)] : runs;
  }, [runs, expanded]);

  function toggleCard(runId: string) {
    const next = expanded === runId ? null : runId;
    setExpanded(next);
    if (next !== null) {
      // Nudge the focus slot into view when opening — `nearest` so it is a
      // no-op in the common case where the slot already sits right under the
      // table the user just clicked. The anchor is the grid container, whose
      // top edge doesn't move during the reorder, not the travelling card.
      requestAnimationFrame(() => {
        document
          .getElementById("session-animal-cards")
          ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    }
  }

  if (runs.length === 0) {
    return (
      <div className="telemetry flex flex-wrap items-center justify-between gap-3 p-4">
        <p className="text-[12px] leading-relaxed text-static">
          No runs recorded in{" "}
          <span className="font-mono text-starlight">
            {session.prefixName}_{session.sessionNumber}
          </span>
          .
        </p>
        {/* Still offered: a session with no readable runs is exactly the one
            whose folder someone wants to look inside. */}
        {interactive && session.folderPath && (
          <FolderButton
            path={session.folderPath}
            label="Session folder"
            size="sm"
          />
        )}
      </div>
    );
  }

  return (
    <motion.div
      className="telemetry p-4"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springSnappy}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-[11px] text-static">
          <ClipboardList size={13} strokeWidth={1.75} className="shrink-0 text-pulsar" />
          <PanelTitle
            name="Session summary"
            note={
              <>
                <span className="font-mono text-starlight">
                  {session.prefixName}_{session.sessionNumber}
                </span>
                <span className="ml-2">{session.date}</span>
              </>
            }
          />
          {/* Gated on `interactive`: this panel is also the export sheet
              (`DATA.md#exporting-a-sheet`), and a button in a PNG is a lie. */}
          {interactive && session.folderPath && (
            <FolderButton
              path={session.folderPath}
              label="Session folder"
              size="sm"
            />
          )}
        </span>
        <Headline runs={runs} />
      </div>

      <div className="mt-3">
        <SessionTable
          runs={runs}
          columns={tableColumns}
          names={names}
          colors={colors}
          minCounted={summary.minCountedTrials}
          selectedRunId={expanded}
          onSelect={interactive ? toggleCard : null}
        />
        <TableKey />
      </div>

      <div
        id="session-animal-cards"
        className={`mt-3 grid scroll-mt-3 gap-2 ${CARD_GRID[columns]}`}
      >
        {ordered.map((run, index) => (
          <AnimalCard
            key={run.runId}
            run={run}
            name={names.get(run.animalId) ?? run.animalId}
            color={colors.get(run.animalId) ?? "var(--color-series-1)"}
            series={series.find((entry) => entry.runId === run.runId) ?? null}
            index={index}
            revealKey={revealKey}
            expanded={expanded === run.runId}
            onToggle={interactive ? toggleCard : null}
          />
        ))}
      </div>

      <Legend />
    </motion.div>
  );
}

/**
 * The pooled figures, shown only when they are honest. Pooling across
 * different tasks mixes denominators that mean different things, so a
 * mixed-task session states the mix and points at the table instead of
 * printing a number that looks comparable and isn't.
 */
function Headline({ runs }: { runs: RunSummary[] }) {
  const animals = new Set(runs.map((run) => run.animalId)).size;
  const scored = runs.filter((run) => run.outcomes !== null);
  const profiles = new Set(scored.map((run) => run.profileHash));
  const pooled = poolOutcomes(runs);

  return (
    <span className="font-mono text-[10px] tabular-nums text-static/80">
      {animals} animal{animals === 1 ? "" : "s"} · {pooled.administered} administered
      {scored.length > 0 && profiles.size === 1 ? (
        <>
          {" "}
          ·{" "}
          <span style={{ color: OUTCOME_STYLE.rewarded.fill }}>
            {pooled.pRewarded === null ? "—" : pct(pooled.pRewarded)} rewarded
          </span>{" "}
          ·{" "}
          <span style={{ color: "var(--color-starlight)" }}>
            {pooled.pSide === null ? "—" : pct(pooled.pSide)} correct side
          </span>
        </>
      ) : profiles.size > 1 ? (
        <span className="text-static/60"> · {profiles.size} tasks — see the table</span>
      ) : null}
    </span>
  );
}

/** Card columns per `SessionSummary`'s `columns` prop. Spelled out as whole
 *  literals so Tailwind's scanner can see them. */
const CARD_GRID = {
  1: "grid-cols-1",
  2: "grid-cols-2",
  auto: "grid-cols-1 xl:grid-cols-2",
} as const;

function Legend() {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-halo pt-2 font-mono text-[9px] text-static/70">
      {Object.entries(OUTCOME_STYLE).map(([key, style]) => (
        <span key={key} className="flex items-center gap-1">
          <span
            className="inline-block size-2 rounded-[2px]"
            style={{ background: style.fill }}
          />
          {style.label}
        </span>
      ))}
    </div>
  );
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

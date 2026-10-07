import { motion } from "framer-motion";

import { useIsHighlighted, useAnalyticsStore } from "@/lib/analytics/context";
import {
  TABLE_COLUMNS,
  conditionFor,
  conditionName,
  formatClock,
  programOf,
  runEnd,
  shortClock,
  tableMinWidth,
  tableTemplate,
  unscoredReason,
  type ConditionColumn,
} from "@/lib/analytics/session";
import type { ProfileSource, RunSummary, TrialOutcomes } from "@/lib/analytics/types";
import { binFor, labelColor } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";

/**
 * The session at a glance, one row per animal (`DATA.md#pooling-across-tasks`)
 * — the comparison the cards cannot give without reading six of them.
 *
 * **One narrow column per condition.** Each cell stacks the two numbers that
 * belong together: the share of sampled trials that paid out, as a chip, over
 * how many trials were sampled. They used to be a pair of side-by-side columns,
 * which made every condition cost two columns — a four-odor task already
 * scrolled sideways. The animal's start, end and program fold into its own
 * cell for the same reason, so the table grows by one column per condition and
 * fits ten of them before its wrapper scrolls (`lib/analytics/session.ts`
 * `tableTemplate`, pinned by a test). The pooled "all" column leads, set apart,
 * because it is the figure a row is scanned for.
 *
 * The conditions are the union of what the session's runs declare — derived
 * from the task profiles, never written down — so the table grows with the
 * task instead of breaking.
 *
 * **`rewarded` is `pRewarded` — reward delivered, the animal held.** That is
 * deliberately stricter than the app's response accuracy (`pSide`,
 * `DATA.md#rewarded-and-response-accuracy`), which credits a correct well
 * whether or not the hold cleared. The key says so, because the two look
 * interchangeable and are not.
 *
 * **Colour carries the rate and nothing else.** The chips use the dashboard's
 * diverging ramp (`DATA.md#colour-palette`), centred on chance, so a rate means
 * the same colour here as everywhere else and a row reads as a pattern before
 * it reads as numbers. The only other colour on a row is the identity dot.
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
  const template = tableTemplate(columns.length);

  return (
    // Scrolls only past the design target — ten conditions on the narrower of
    // the table's two homes — never for an ordinary task.
    <div className="scrollbar-none overflow-x-auto">
      <div style={{ minWidth: tableMinWidth(columns.length) }}>
        <Header columns={columns} template={template} />
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

/** What a cell holds, in one line — shown under the table wherever it sits. */
export function TableKey() {
  return (
    <p className="mt-2 font-mono text-[9px] text-static/70">
      chip = rewarded: the reward was delivered and the animal held · number under it = trials
      sampled to completion · outlined = under the cohort&rsquo;s minimum, read loosely
    </p>
  );
}

function Header({ columns, template }: { columns: ConditionColumn[]; template: string }) {
  return (
    <div
      className="grid items-end border-b border-halo pb-1 font-mono text-[10px] leading-tight text-static/70"
      style={{ gridTemplateColumns: template, columnGap: TABLE_COLUMNS.gap }}
    >
      <span className="text-static">animal</span>
      <span
        className="border-l border-halo/70 pl-1 text-right text-starlight"
        title="Every condition pooled — this animal's whole run"
      >
        all
      </span>
      {columns.map((column) => (
        <span
          key={column.metricId}
          // Two lines, then clipped: the operator's own name for the condition,
          // wrapping rather than truncating, with the full label on hover.
          className="line-clamp-2 text-right break-words"
          title={column.label}
        >
          {conditionName(column.label)}
        </span>
      ))}
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
      className={`grid items-center border-b border-halo/50 py-1.5 transition-colors ${
        selected ? "bg-halo/60" : highlighted ? "bg-halo/40" : ""
      } ${reason ? "opacity-60" : ""} ${toggle ? "cursor-pointer" : ""}`}
      style={{ gridTemplateColumns: template, columnGap: TABLE_COLUMNS.gap }}
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
      title={toggle ? (selected ? `Close ${name}'s card` : `Open ${name}'s card`) : undefined}
      initial={{ opacity: 0, y: 3 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...springSnappy, delay: index * 0.03 }}
    >
      <Identity run={run} name={name} color={color} lit={highlighted || selected} reason={reason} />

      <span className="border-l border-halo/70 pl-1">
        <Cell outcomes={run.outcomes} what="all conditions" minCounted={minCounted} emphasis />
      </span>
      {columns.map((column) => (
        <Cell
          key={column.metricId}
          outcomes={conditionFor(run, column)?.outcomes ?? null}
          what={conditionName(column.label)}
          minCounted={minCounted}
        />
      ))}
    </motion.div>
  );
}

/**
 * Who, when and on what — the columns that used to be three, as one cell:
 * the name, then the run's clock and program in small mono under it.
 */
function Identity({
  run,
  name,
  color,
  lit,
  reason,
}: {
  run: RunSummary;
  name: string;
  color: string;
  lit: boolean;
  reason: string | null;
}) {
  const end = runEnd(run);
  return (
    <span className="flex min-w-0 items-start gap-1.5">
      <span
        className="mt-1 size-2 shrink-0 rounded-full"
        style={{ background: color, opacity: lit ? 1 : 0.85 }}
      />
      <span className="min-w-0">
        <span className={`block truncate text-[11px] ${lit ? "text-starlight" : "text-static"}`}>
          {name}
        </span>
        <span className="flex min-w-0 items-center gap-1 font-mono text-[9px] tabular-nums text-static/70">
          <span
            className="shrink-0"
            title={`started ${formatClock(run.startedAt)} · ${end.title} ${end.derived ? "~" : ""}${end.text}`}
          >
            {shortClock(formatClock(run.startedAt))}–{end.derived && "~"}
            {shortClock(end.text)}
          </span>
          <span aria-hidden>·</span>
          <Program run={run} reason={reason} />
        </span>
      </span>
    </span>
  );
}

/**
 * One condition's numbers: the rewarded share as a chip on the diverging
 * ramp (`DATA.md#colour-palette`), and under it how many trials were sampled
 * — the denominator, kept beside the rate it qualifies. Below `minCounted`
 * sampled trials the chip drops to an outline: flagged, never suppressed
 * (`DATA.md#uncertainty`). A condition this run's task doesn't declare is a
 * dash, never a zero.
 */
function Cell({
  outcomes,
  what,
  minCounted,
  emphasis = false,
}: {
  outcomes: TrialOutcomes | null;
  what: string;
  minCounted: number;
  emphasis?: boolean;
}) {
  if (outcomes === null) {
    return (
      <span
        className="text-right font-mono text-[11px] text-static/50"
        title={`this run's task declares no ${what} trials`}
      >
        —
      </span>
    );
  }
  const sampled = outcomes.administered;
  const p = outcomes.pRewarded;
  const thin = sampled < minCounted;
  const bin = p === null ? null : binFor(p);
  const title =
    p === null
      ? `no ${what} trials were sampled to completion`
      : `${outcomes.rewarded} of ${sampled} sampled ${what} trials ended with the reward ` +
        `delivered` +
        (thin ? ` — under ${minCounted} trials, read loosely` : "");

  return (
    <span className="flex flex-col items-end gap-0.5" title={title}>
      {bin === null || p === null ? (
        <span className="font-mono text-[11px] text-static/50">—</span>
      ) : (
        <span
          className="rounded-sm px-1 py-px font-mono text-[11px] whitespace-nowrap tabular-nums"
          style={
            thin
              ? {
                  // An outline rather than a fill: a thin cell's colour would
                  // read as a finding at a glance, and the whole point of the
                  // flag is that it isn't one yet.
                  border: `1px solid ${bin.fill}`,
                  color: "var(--color-static)",
                }
              : { background: bin.fill, color: labelColor(bin) }
          }
        >
          {Math.round(p * 100)}%
        </span>
      )}
      <span
        className={`font-mono text-[9px] tabular-nums ${
          emphasis ? "text-starlight/80" : "text-static/70"
        }`}
      >
        {sampled}
      </span>
    </span>
  );
}

/**
 * What this animal ran, and how confident the app is that it knows.
 *
 * The name is the one the *file* recorded (`programOf`), not the folder this
 * machine happened to resolve — a session copied over from the other rig names
 * a task profile this install has never seen, and it still says what it ran.
 * What that costs is fidelity of *decoding*, not of identity, so the provenance
 * mark carries it: an inferred run was scored from its own strobes rather than
 * from the task's declaration (`DATA.md#which-profile-decodes-a-run`).
 */
function Program({ run, reason }: { run: RunSummary; reason: string | null }) {
  const mark = PROVENANCE[run.profileSource];
  return (
    <span
      className="flex min-w-0 items-center gap-1 font-mono text-[9px] text-static/70"
      title={
        reason
          ? `${run.sketchPath || programOf(run)}\nnot scored — ${reason}`
          : `${run.sketchPath || "not found on this machine"}\n${mark.title}`
      }
    >
      {reason && (
        <span style={{ color: "var(--color-status-warning)" }} aria-hidden>
          ⚠
        </span>
      )}
      <span className="truncate">{programOf(run)}</span>
      {!reason && mark.glyph && (
        <span className="shrink-0 text-static/50" aria-hidden>
          {mark.glyph}
        </span>
      )}
    </span>
  );
}

/**
 * How the run was decoded, as one character
 * (`DATA.md#which-profile-decodes-a-run`).
 *
 * A snapshot is the good case and carries no mark — a glyph on every row would
 * say nothing. The other two are worth a mark precisely because they look
 * identical to a snapshot on the row: `†` is "scored with whatever that
 * sketch's `task.json` says *today*", `≈` is "no profile resolved at all, so
 * the conditions were read out of the recorded stream".
 */
const PROVENANCE: Record<ProfileSource, { glyph: string; title: string }> = {
  snapshot: {
    glyph: "",
    title: "scored with the task profile recorded at the time of the run",
  },
  "sketch-current": {
    glyph: "†",
    title:
      "† scored with this sketch's task.json as it stands today — it may have " +
      "changed since the run",
  },
  inferred: {
    glyph: "≈",
    title:
      "≈ no task profile for this program on this machine, so the conditions " +
      "were read out of the recorded strobes themselves",
  },
  unavailable: {
    glyph: "",
    title: "no task profile could be resolved for this run",
  },
};

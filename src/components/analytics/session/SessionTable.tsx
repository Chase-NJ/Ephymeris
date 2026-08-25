import { motion } from "framer-motion";

import { useIsHighlighted, useAnalyticsStore } from "@/lib/analytics/context";
import {
  conditionFor,
  conditionName,
  formatClock,
  programOf,
  runEnd,
  unscoredReason,
  type ConditionColumn,
} from "@/lib/analytics/session";
import type { ProfileSource, RunSummary, TrialOutcomes } from "@/lib/analytics/types";
import { binFor, labelColor } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";

/**
 * The session at a glance, one row per animal (`data.md` §11.4) — the
 * comparison the cards cannot give without reading six of them.
 *
 * **Read as groups of two, not as a strip of numbers.** Every tally on the row
 * is one of a pair — how many trials this animal sampled, and what fraction of
 * those paid out — so the header is two tiers: a *group* title naming what the
 * pair is about (`all trials`, then one per condition, in authored order), and
 * under it the two columns themselves. A four-odor task adds four groups, and
 * the reason that stays readable where eight bare columns did not is that the
 * name sits over the pair with room to wrap rather than being truncated into a
 * 72px cell.
 *
 * The condition groups are the union of what the session's runs declare —
 * derived from the task profiles, never written down — so the table grows with
 * the task instead of breaking; the wrapper scrolls when the rig runs more
 * conditions than the window is wide.
 *
 * **`rewarded` is `pRewarded` — reward delivered, the animal held.** That is
 * deliberately stricter than the app's response accuracy (`pSide`, §9.8),
 * which credits a correct well whether or not the hold cleared. The legend
 * says so, because the two look interchangeable and are not.
 *
 * **Colour carries the rate and nothing else.** The rate cells use the
 * heatmap's own diverging ramp (§11.8) — the same bins, centred on chance —
 * so a rate means the same colour here as it does in the cohort heatmap, and
 * a row of four conditions can be read as a pattern before it is read as
 * numbers. Everything structural stays in the neutral stack; the only other
 * colour on the row is the animal's identity dot.
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
  // A group is always `sampled | rewarded`, so the pairs line up under their
  // titles by construction.
  const template = [
    "minmax(112px,1.4fr)", // animal
    "62px", // start
    "62px", // end
    "58px", // all trials — sampled
    "66px", // all trials — rewarded
    ...columns.flatMap(() => ["58px", "66px"]), // one pair per condition
    "minmax(104px,1fr)", // program
  ].join(" ");

  return (
    <div className="scrollbar-none overflow-x-auto">
      <div className="min-w-[620px]">
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

/**
 * Two tiers: the group titles, then the columns.
 *
 * One grid rather than two, so the tiers cannot drift apart — the group title
 * spans exactly the two cells it names, and both rows read the same template.
 */
function Header({
  columns,
  template,
}: {
  columns: ConditionColumn[];
  template: string;
}) {
  return (
    <div
      className="grid gap-x-2 border-b border-halo pb-1 font-mono text-[10px] text-static/70"
      style={{ gridTemplateColumns: template }}
    >
      {/* Tier 1 — what each pair is about. The leading and trailing identity
          columns have nothing to group, so they sit empty here and label
          themselves below. */}
      <span />
      <span />
      <span />
      <GroupTitle
        title="all trials"
        detail="Every condition pooled — this animal's whole run"
        emphasis
      />
      {columns.map((column) => (
        <GroupTitle
          key={`g-${column.metricId}`}
          title={conditionName(column.label)}
          detail={column.label}
        />
      ))}
      <span />

      {/* Tier 2 — the columns themselves. */}
      <span className="text-static">animal</span>
      <span className="text-right" title="when this animal's run began">
        start
      </span>
      <span
        className="text-right"
        title="when its recording ended — `~` marks an end derived from the recorded stream's own span"
      >
        end
      </span>
      <PairLabels what="all conditions" />
      {columns.map((column) => (
        <PairLabels key={`c-${column.metricId}`} what={conditionName(column.label)} />
      ))}
      <span className="text-right">program</span>
    </div>
  );
}

/** A group title, bracketing the pair it names. Wraps rather than truncates —
 *  the condition's name is the operator's own, and half of it is no name. */
function GroupTitle({
  title,
  detail,
  emphasis = false,
}: {
  title: string;
  detail: string;
  emphasis?: boolean;
}) {
  return (
    <span
      className="col-span-2 mb-1 border-b border-halo/70 px-1 pb-0.5 text-center leading-tight"
      style={{ color: emphasis ? "var(--color-starlight)" : undefined }}
      title={detail}
    >
      {title}
    </span>
  );
}

/** The two column labels under one group title. */
function PairLabels({ what }: { what: string }) {
  return (
    <>
      <span
        className="text-right"
        title={`${what}: trials whose odor was sampled to completion — the denominator of the rate beside it`}
      >
        sampled
      </span>
      <span
        className="text-right"
        title={`${what}: of those sampled trials, the share that ended with the reward delivered — the animal chose the correct well and held`}
      >
        rewarded
      </span>
    </>
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

      {/* The pooled pair, then one per condition — how much this animal did,
          then how that splits. The total leads because it is the figure the
          row is scanned for; the conditions after it are the breakdown. */}
      <Pair
        outcomes={run.outcomes}
        what="all conditions"
        minCounted={minCounted}
        emphasis
      />
      {columns.map((column) => {
        const condition = conditionFor(run, column);
        return (
          <Pair
            key={`p-${column.metricId}`}
            outcomes={condition?.outcomes ?? null}
            what={conditionName(column.label)}
            minCounted={minCounted}
          />
        );
      })}

      <Program run={run} reason={reason} />
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
 * One group's two cells: how many trials were sampled, and what share of them
 * paid out.
 *
 * The count is deliberately the quieter of the two — it is a denominator, and
 * the rate beside it is what the row is read for — except in the pooled group,
 * where the count *is* the headline figure for the run.
 */
function Pair({
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
  const sampled = outcomes?.administered ?? null;
  return (
    <>
      <span
        className={`text-right font-mono text-[11px] tabular-nums ${
          emphasis ? "text-starlight" : sampled ? "text-static" : "text-static/50"
        }`}
        title={
          sampled === null
            ? `this run's task declares no ${what} trials`
            : `${sampled} ${what} trial${sampled === 1 ? "" : "s"} sampled to completion`
        }
      >
        {sampled ?? "—"}
      </span>
      <RateCell outcomes={outcomes} what={what} minCounted={minCounted} />
    </>
  );
}

/**
 * The rewarded share, as a chip on the heatmap's own diverging ramp (§11.8).
 *
 * A bar was here before, which encoded the same number twice and still needed
 * the reader to compare lengths across a row; the ramp is quantized around
 * chance, so "at chance", "learning" and "solid" are three colours rather than
 * three lengths — and it is the colour language the cohort heatmap already
 * taught. Below `minCounted` sampled trials the chip drops to an outline:
 * flagged, never suppressed (§9.5). It used to print its n in parentheses too,
 * which is what the flag meant in the old flat table — in a paired layout the
 * `sampled` cell immediately to its left **is** that n, so the number was on
 * the row twice and only the wrapping was new.
 */
function RateCell({
  outcomes,
  what,
  minCounted,
}: {
  outcomes: TrialOutcomes | null;
  what: string;
  minCounted: number;
}) {
  const p = outcomes?.pRewarded ?? null;
  if (outcomes === null || p === null) {
    return (
      <span className="text-right font-mono text-[11px] tabular-nums text-static/50">
        —
      </span>
    );
  }
  const sampled = outcomes.administered;
  const thin = sampled < minCounted;
  const bin = binFor(p);
  const title =
    `${outcomes.rewarded} of ${sampled} sampled ${what} trials ended with the ` +
    `reward delivered` +
    (thin ? ` — under ${minCounted} trials, read loosely` : "");

  return (
    <span className="flex justify-end" title={title}>
      <span
        className="whitespace-nowrap rounded-sm px-1.5 py-0.5 font-mono text-[11px] tabular-nums"
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
 * from the task's declaration (`data.md` §8.2).
 */
function Program({ run, reason }: { run: RunSummary; reason: string | null }) {
  const mark = PROVENANCE[run.profileSource];
  return (
    <span
      className="flex min-w-0 items-center justify-end gap-1 text-right font-mono text-[10px] text-static/80"
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
 * How the run was decoded, as one character (§8.2).
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

import { useEffect, useState } from "react";

import { errorMessage } from "@/features/analytics/commands";
import {
  conditionFor,
  conditionName,
  formatClock,
  programOf,
  runEnd,
  shortClock,
  unscoredReason,
  type ConditionColumn,
} from "@/features/analytics/session";
import type { RunSummary, TrialOutcomes } from "@/features/analytics/types";
import { shortDate } from "../clock";
import {
  LOW_WEIGHT_FRACTION,
  formatDelta,
  formatGrams,
  formatShare,
  parseWeight,
  readWeight,
  weightTrend,
} from "../health";
import {
  GRADE_LABEL,
  UNIT_MIN_HZ,
  UNIT_SNR,
  type Grade,
  type RunVerdict,
} from "../signal";
import type { HealthEntry } from "../types";

import { AnimalMark, Caption, Footnote, SiteStrip, Sparkline } from "./parts";

/** A page's tables, each ruled like `booktabs` (`ARCHITECTURE.md#the-paper-exception`). */

// --- Table: performance ---------------------------------------------------

/**
 * How each animal did (`DATA.md#pooling-across-tasks`): one row per counted
 * run, one column per condition the session's tasks declare, each cell the
 * share of sampled trials that paid out over how many were sampled. The same
 * numbers, from the same summary, as Analytics' session table.
 *
 * A rate from fewer trials than the cohort's minimum is printed and daggered,
 * never hidden; a run that could not be scored says why in place of numbers.
 */
export function PerformanceTable({
  label,
  runs,
  setAside,
  columns,
  names,
  colors,
  minCounted,
}: {
  label: string;
  runs: RunSummary[];
  /** False starts: named under the table, counted nowhere. */
  setAside: RunSummary[];
  columns: ConditionColumn[];
  names: Map<string, string>;
  colors: Map<string, string>;
  minCounted: number;
}) {
  const thin = runs.some(
    (run) =>
      isThin(run.outcomes, minCounted) ||
      columns.some((column) => isThin(conditionFor(run, column)?.outcomes ?? null, minCounted)),
  );
  return (
    <div>
      <Caption label={label}>
        Share of sampled trials rewarded, over the number sampled.
      </Caption>
      <div className="table-frame">
        <table className="booktabs text-[14.5px]">
          <thead>
            <tr>
              <th scope="col">Animal</th>
              <th scope="col" className="num">
                All trials
              </th>
              {columns.map((column) => (
                <th key={column.metricId} scope="col" className="num" title={column.label}>
                  {conditionName(column.label)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const reason = unscoredReason(run);
              const end = runEnd(run);
              return (
                <tr key={run.runId}>
                  <td>
                    <AnimalMark
                      name={names.get(run.animalId) ?? run.animalId}
                      color={colors.get(run.animalId)}
                    />
                    <div className="pl-[15px] text-[12.5px] leading-tight text-ink-soft">
                      {run.boxNumber !== null && `Box ${run.boxNumber} · `}
                      {programOf(run)} · {shortClock(formatClock(run.startedAt))}–
                      <span title={end.title}>
                        {end.derived ? "~" : ""}
                        {shortClock(end.text)}
                      </span>
                    </div>
                  </td>
                  {reason ? (
                    <td colSpan={columns.length + 1} className="text-[13.5px] text-ink-soft italic">
                      Not scored: {reason}.
                    </td>
                  ) : (
                    <>
                      <RateCell outcomes={run.outcomes} minCounted={minCounted} strong />
                      {columns.map((column) => (
                        <RateCell
                          key={column.metricId}
                          outcomes={conditionFor(run, column)?.outcomes ?? null}
                          minCounted={minCounted}
                        />
                      ))}
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {thin && (
        <Footnote>
          <sup>†</sup> Fewer than {minCounted} trials sampled: a rate to read with care.
        </Footnote>
      )}
      {setAside.length > 0 && (
        <Footnote>
          Set aside as false start{setAside.length === 1 ? "" : "s"} and counted nowhere:{" "}
          {setAside
            .map(
              (run) =>
                `${names.get(run.animalId) ?? run.animalId} (${shortClock(formatClock(run.startedAt))}${
                  run.falseStartSource === "marked" ? ", by hand" : ""
                })`,
            )
            .join(", ")}
          .
        </Footnote>
      )}
    </div>
  );
}

function isThin(outcomes: TrialOutcomes | null, minCounted: number): boolean {
  return outcomes !== null && outcomes.pRewarded !== null && outcomes.administered < minCounted;
}

function RateCell({
  outcomes,
  minCounted,
  strong = false,
}: {
  outcomes: TrialOutcomes | null;
  minCounted: number;
  strong?: boolean;
}) {
  if (!outcomes || outcomes.pRewarded === null) {
    return <td className="num text-ink-faint">—</td>;
  }
  return (
    <td className="num whitespace-nowrap" data-selectable>
      <span className={strong ? "font-bold" : ""}>{Math.round(outcomes.pRewarded * 100)}%</span>
      {isThin(outcomes, minCounted) && <sup>†</sup>}
      <div className="text-[12.5px] leading-tight text-ink-soft">{outcomes.administered}</div>
    </td>
  );
}

// --- Table: weights -------------------------------------------------------

export interface WeighRow {
  id: string;
  name: string;
  /** Ran in this session; the rest of the roster follows under a rule. */
  ran: boolean;
}

/**
 * The day's weigh-ins, as a ledger (`DATA.md#weigh-ins`): a weight is typed
 * into its animal's row and kept when the cell is left; Enter moves down a
 * row, so a rack is entered without the mouse. Each row reads its weight
 * against the weigh-in before it and, once one has been marked, against the
 * animal's baseline, with the last dozen weigh-ins as a trend.
 *
 * Nothing is shown before the sidecar has kept it: the cell returns to what
 * the database holds, so a refused weight is seen to be refused.
 */
export function WeighInTable({
  label,
  date,
  rows,
  health,
  colors,
  onSet,
  onNote,
}: {
  label: string;
  date: string;
  rows: WeighRow[];
  health: Map<string, HealthEntry[]>;
  colors: Map<string, string>;
  onSet: (animalId: string, fields: { weightG: number | null; baseline?: boolean }) => Promise<void>;
  /** Start a health note about an animal; absent where the session takes none. */
  onNote?: ((animalId: string) => void) | undefined;
}) {
  const ran = rows.filter((row) => row.ran);
  const rest = rows.filter((row) => !row.ran);
  const anyLow = rows.some((row) => readWeight(health.get(row.id) ?? [], date).low);
  const line = (row: WeighRow) => (
    <WeighLine
      key={row.id}
      row={row}
      date={date}
      history={health.get(row.id) ?? NO_HISTORY}
      color={colors.get(row.id)}
      onSet={onSet}
      onNote={onNote}
    />
  );
  return (
    <div>
      <Caption label={label}>
        Body weight, in grams. The change is since the weigh-in before; the share is of the
        weight marked as the animal's baseline.
      </Caption>
      <div className="table-frame">
        <table className="booktabs text-[14.5px]">
          <thead>
            <tr>
              <th scope="col">Animal</th>
              <th scope="col" className="num">
                Weight
              </th>
              <th scope="col" className="num">
                Change
              </th>
              <th scope="col">Of baseline</th>
              <th scope="col" className={NARROW_HIDES}>
                Trend
              </th>
              <th scope="col" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {ran.map(line)}
            {rest.length > 0 && (
              <tr className={ran.length > 0 ? "midrule" : ""}>
                <td colSpan={6} className="smallcaps pb-0 text-[10.5px] text-ink-faint">
                  {ran.length > 0
                    ? "not run in this session"
                    : "nobody has run in this session yet"}
                </td>
              </tr>
            )}
            {rest.map(line)}
          </tbody>
        </table>
      </div>
      {anyLow && (
        <Footnote>
          <span className="text-ink-red">▼ low</span>: under{" "}
          {Math.round(LOW_WEIGHT_FRACTION * 100)}% of baseline, the dashed line on the trend.
        </Footnote>
      )}
    </div>
  );
}

const NO_HISTORY: HealthEntry[] = [];
/** A trend is the first thing a narrow page gives up: the numbers beside it say the same. */
const NARROW_HIDES = "@max-[440px]:hidden";
/** What a row can do, shown when the hand or the focus is on it. */
const ON_ROW = "opacity-0 group-focus-within:opacity-100 group-hover:opacity-100";

function WeighLine({
  row,
  date,
  history,
  color,
  onSet,
  onNote,
}: {
  row: WeighRow;
  date: string;
  history: HealthEntry[];
  color: string | undefined;
  onSet: (animalId: string, fields: { weightG: number | null; baseline?: boolean }) => Promise<void>;
  onNote?: ((animalId: string) => void) | undefined;
}) {
  const reading = readWeight(history, date);
  const kept = reading.entry ? formatGrams(reading.entry.weightG) : "";
  const [text, setText] = useState(kept);
  const [error, setError] = useState<string | null>(null);
  // Follow the sidecar: what it kept is what the cell shows.
  useEffect(() => setText(kept), [kept]);

  async function send(fields: { weightG: number | null; baseline?: boolean }) {
    try {
      await onSet(row.id, fields);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
      setText(kept);
    }
  }

  function commit() {
    const parsed = parseWeight(text);
    if (parsed.kind === "invalid") {
      setError(parsed.reason);
      return;
    }
    setError(null);
    if (parsed.kind === "clear") {
      if (reading.entry) void send({ weightG: null });
      return;
    }
    if (reading.entry && parsed.grams === reading.entry.weightG) {
      setText(kept);
      return;
    }
    void send({ weightG: parsed.grams });
  }

  const trend = weightTrend(history, date, 12);
  const isReference = reading.entry !== null && reading.reference?.date === reading.entry.date;

  return (
    <tr className="group">
      <td>
        <AnimalMark name={row.name} color={color} />
      </td>
      <td className="num whitespace-nowrap">
        <input
          type="text"
          inputMode="decimal"
          data-weigh-in
          value={text}
          placeholder="—"
          aria-label={`${row.name}'s weight in grams`}
          aria-invalid={error !== null}
          title={error ?? undefined}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              const cells = [
                ...document.querySelectorAll<HTMLInputElement>("input[data-weigh-in]"),
              ].filter((cell) => !cell.closest("[inert]"));
              const next = cells[cells.indexOf(e.currentTarget) + 1];
              if (next) next.focus();
              else e.currentTarget.blur();
            }
            if (e.key === "Escape") {
              setText(kept);
              setError(null);
              e.currentTarget.blur();
            }
          }}
          className={`ink-field w-[58px] text-right ${error ? "border-b-ink-red" : ""}`}
        />
        <span className="ml-1 text-[12.5px] text-ink-faint">g</span>
      </td>
      <td
        className="num whitespace-nowrap text-ink-soft"
        title={
          reading.previous
            ? `since ${formatGrams(reading.previous.weightG)} g on ${shortDate(reading.previous.date)}`
            : undefined
        }
        data-selectable
      >
        {reading.deltaG !== null ? (
          formatDelta(reading.deltaG)
        ) : reading.entry ? (
          <span className="text-[12.5px] text-ink-faint italic">first</span>
        ) : (
          <span className="text-ink-faint">—</span>
        )}
      </td>
      <td className="whitespace-nowrap">
        {!reading.entry ? (
          <span className="text-ink-faint">—</span>
        ) : isReference ? (
          <button
            type="button"
            className="smallcaps text-[11.5px] font-bold text-ink-teal"
            title="This weigh-in is the animal's baseline. Click to unmark it."
            onClick={() => void send({ weightG: reading.entry!.weightG, baseline: false })}
          >
            ★ baseline
          </button>
        ) : reading.ofReference !== null && reading.reference ? (
          <span
            title={`of ${formatGrams(reading.reference.weightG)} g, the baseline of ${shortDate(reading.reference.date)}`}
            data-selectable
          >
            {formatShare(reading.ofReference)}
            {reading.low && <span className="ml-1.5 text-[12.5px] text-ink-red">▼ low</span>}
          </span>
        ) : (
          // No baseline yet: the way to set one is in plain sight.
          <button
            type="button"
            className="ink-link text-[12.5px]"
            title="Read later weigh-ins against this one"
            onClick={() => void send({ weightG: reading.entry!.weightG, baseline: true })}
          >
            set as baseline
          </button>
        )}
      </td>
      <td className={NARROW_HIDES}>
        {trend.length > 0 && (
          <Sparkline
            values={trend.map((item) => item.weightG)}
            color={color}
            floor={
              reading.reference ? reading.reference.weightG * LOW_WEIGHT_FRACTION : undefined
            }
            title={`${row.name}: ${trend
              .map((item) => `${shortDate(item.date)} ${formatGrams(item.weightG)} g`)
              .join(", ")}`}
          />
        )}
      </td>
      <td className="text-right text-[12.5px] whitespace-nowrap">
        {reading.entry && reading.reference && !isReference && (
          <button
            type="button"
            className={`ink-link ${ON_ROW}`}
            aria-label={`Make this ${row.name}'s baseline`}
            title="Make this the baseline: later weigh-ins are read against it instead"
            onClick={() => void send({ weightG: reading.entry!.weightG, baseline: true })}
          >
            ☆
          </button>
        )}
        {onNote && (
          <button
            type="button"
            className={`ink-link ml-2 ${ON_ROW}`}
            title={`Write a health note about ${row.name}`}
            onClick={() => onNote(row.id)}
          >
            note
          </button>
        )}
      </td>
    </tr>
  );
}

// --- Table: recording -----------------------------------------------------

export interface SignalRow {
  animalId: string;
  name: string;
  verdict: RunVerdict;
  /** The animal's unit-like counts over its recorded sessions, this one last. */
  trend: Array<{ unitLike: number; total: number }>;
  /** No earlier recorded session of this animal had more. */
  best: boolean;
}

const GRADE_INK: Record<Grade, string> = {
  "sort-first": "text-ink-plum font-bold",
  "worth-sorting": "text-ink",
  "low-yield": "text-ink-soft",
  none: "text-ink-faint",
};

/**
 * What there is to sort, animal by animal (`RECORDING.md#unit-like-sites`):
 * each electrode site as a square, how many of them carried unit-like signal,
 * and what that says about sorting this day's recording first.
 *
 * An estimate from spike amplitude over noise, and the caption says so on
 * every page it appears: it ranks days, it does not count neurons.
 */
export function SignalTable({
  label,
  rows,
  colors,
}: {
  label: string;
  rows: SignalRow[];
  colors: Map<string, string>;
}) {
  const waveforms = rows.some((row) => row.verdict.basis === "waveforms");
  const crossingsOnly = rows.some((row) => row.verdict.basis === "crossings");
  const partial = rows.some((row) => row.verdict.partial);
  return (
    <div>
      <Caption label={label}>
        Unit-like sites: an estimate of what there is to sort, from spike amplitude over each
        site's noise. Not sorted units.
      </Caption>
      <div className="table-frame">
        <table className="booktabs text-[14.5px]">
          <thead>
            <tr>
              <th scope="col">Animal</th>
              <th scope="col">Sites</th>
              <th scope="col" className="num">
                Unit-like
              </th>
              <th scope="col">For sorting</th>
              <th scope="col" className={NARROW_HIDES}>
                Trend
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const { verdict } = row;
              const measured = verdict.basis === "waveforms";
              return (
                <tr key={row.animalId}>
                  <td>
                    <AnimalMark name={row.name} color={colors.get(row.animalId)} />
                  </td>
                  <td>
                    <SiteStrip sites={verdict.sites} />
                  </td>
                  <td className="num whitespace-nowrap" data-selectable>
                    {measured ? (
                      <>
                        <span className="font-bold">{verdict.unitLike}</span>
                        <span className="text-ink-soft"> / {verdict.total}</span>
                      </>
                    ) : (
                      <span className="text-ink-faint">—</span>
                    )}
                  </td>
                  <td className="leading-tight">
                    {verdict.grade ? (
                      <>
                        <span className={`smallcaps text-[11px] whitespace-nowrap ${GRADE_INK[verdict.grade]}`}>
                          {GRADE_LABEL[verdict.grade]}
                        </span>
                        {row.best && verdict.unitLike > 0 && row.trend.length > 1 && (
                          <div className="text-[12.5px] whitespace-nowrap text-ink-soft italic">
                            its best day yet
                          </div>
                        )}
                      </>
                    ) : (
                      <span className="text-[13.5px] whitespace-nowrap text-ink-soft italic">
                        {verdict.active} / {verdict.total} active
                        {verdict.partial && <sup>‡</sup>}
                      </span>
                    )}
                  </td>
                  <td className={NARROW_HIDES}>
                    {row.trend.length > 1 && (
                      <Sparkline
                        values={row.trend.map((point) => point.unitLike)}
                        width={52}
                        color={colors.get(row.animalId)}
                        title={`${row.name}, unit-like sites by recorded session: ${row.trend
                          .map((point) => `${point.unitLike}/${point.total}`)
                          .join(", ")}`}
                      />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Footnote>
        <SiteKey />
        {waveforms &&
          ` Unit-like: spikes of at least ${UNIT_SNR} noise SDs at ${UNIT_MIN_HZ} Hz or more, artifacts set aside.`}
      </Footnote>
      {crossingsOnly && (
        <Footnote>
          Where no count is given the recording's waveforms were not measured, and the sites are
          judged on threshold crossings alone, which cannot tell a neuron from an artifact.
        </Footnote>
      )}
      {partial && (
        <Footnote>
          <sup>‡</sup> The live count covered only part of the run, so every site reads quieter
          than it was.
        </Footnote>
      )}
    </div>
  );
}

/** The site strip's key: three steps of one ink, named. */
function SiteKey() {
  const swatch = "mr-1 inline-block size-[7px] translate-y-[0.5px] rounded-[1.5px]";
  return (
    <span className="whitespace-nowrap">
      <span aria-hidden className={`${swatch} bg-ink-plum`} />
      unit-like
      <span
        aria-hidden
        className={`${swatch} ml-2.5`}
        style={{
          backgroundColor: "color-mix(in srgb, var(--color-ink-plum) 38%, var(--color-paper))",
        }}
      />
      active
      <span aria-hidden className={`${swatch} ml-2.5 border border-rule`} />
      quiet.
    </span>
  );
}

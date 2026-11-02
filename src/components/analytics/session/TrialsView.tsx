import { ChartFrame } from "@/components/charts/ChartFrame";
import { classParts, rateRows, trialRows } from "@/lib/analytics/trialTable";
import type { MetricSeries, ReplayScore, TrialTable } from "@/lib/analytics/types";
import { colorForIndex } from "@/lib/analytics/view";

/**
 * A spine run's trials as replay read them (`ANALYTICS.md#the-trial-table`):
 * each row's outcome classes, P(outcome | row), then its phase-window rates
 * when the task counts an input it never acts on (a Pavlovian task's licks,
 * `ANALYTICS.md#phase-window-rates`), above one line per trial — when it
 * started, its row, how it ended, what paid, the response and its latency,
 * and when each phase began. Every value is the sidecar's; nothing here
 * decides an outcome.
 */
export function TrialsView({
  replay,
  table,
  rates: showRates = true,
}: {
  replay: ReplayScore;
  table: TrialTable | null;
  /** False leaves out the phase-window rates, for a run whose counted inputs nothing touched. */
  rates?: boolean;
}) {
  const rows = table ? trialRows(table) : [];
  const phases = table?.phases ?? [];
  const showPhases = rows.some((row) => row.phases.length > 0);
  const rates = rateRows(replay.rates);

  return (
    <div className="flex flex-col gap-2">
      {replay.rows.map((row) => {
        const parts = classParts(row.classes, row.unclassified);
        return (
          <div key={row.rowId ?? "unattributed"}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-[11px] text-static">{row.name ?? "no row"}</span>
              <span className="shrink-0 font-mono text-[10px] tabular-nums text-static/80">
                {parts.map((part) => `${part.n} ${part.label}`).join(" · ") || "no trials"}
              </span>
            </div>
            {row.trials > 0 && (
              <div className="mt-1 flex h-2.5 overflow-hidden rounded-[2px]">
                {parts.map((part) => (
                  <span
                    key={part.key}
                    title={`${part.n} ${part.label}`}
                    style={{ width: `${(part.n / row.trials) * 100}%`, background: part.fill }}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}

      {showRates && rates.length > 0 && (
        <div className="border-t border-halo pt-1.5">
          <table className="w-full font-mono text-[10px] tabular-nums text-static/80">
            <thead className="text-left text-[9px] text-static/60">
              <tr>
                <th className="pr-2 font-normal">row</th>
                <th className="pr-2 font-normal" title="the phase, numbered from 1, and its kind">phase</th>
                <th className="pr-2 font-normal">input</th>
                <th className="pr-2 font-normal" title="mean per-trial rate, 95% t interval over trials">rate</th>
                <th className="pr-2 font-normal" title="paired within each trial against the row's first phase counting the same input, named in each cell">
                  difference
                </th>
                <th className="pr-2 font-normal">n</th>
              </tr>
            </thead>
            <tbody>
              {rates.map((rate) => (
                <tr key={rate.key} className={rate.lowConfidence ? "text-static/40" : ""}>
                  <td className="max-w-[96px] truncate pr-2">{rate.row}</td>
                  <td className="pr-2">{rate.window}</td>
                  <td className="pr-2">{rate.channel}</td>
                  <td className="pr-2">{rate.rate}</td>
                  <td className="pr-2">{rate.versus}</td>
                  <td className="pr-2">{rate.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!table ? (
        <Fallback>The trial table could not be read for this run.</Fallback>
      ) : (
        <div className="max-h-64 overflow-auto border-t border-halo pt-1.5">
          <table className="w-full font-mono text-[10px] tabular-nums text-static/80">
            <thead className="text-left text-[9px] text-static/60">
              <tr>
                <th className="pr-2 font-normal">#</th>
                <th className="pr-2 font-normal">at</th>
                <th className="pr-2 font-normal">row</th>
                <th className="pr-2 font-normal">outcome</th>
                <th className="pr-2 font-normal">reward</th>
                <th className="pr-2 font-normal">response</th>
                {showPhases &&
                  phases.map((phase, i) => (
                    <th key={i} className="pr-2 font-normal" title={`ms after the trial began that it entered phase ${i + 1}`}>
                      {phase}
                    </th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className={row.complete ? "" : "text-static/40"}>
                  <td className="pr-2">{row.number}</td>
                  <td className="pr-2">{row.at}</td>
                  <td className="max-w-[96px] truncate pr-2">{row.row}</td>
                  <td className="pr-2" style={{ color: row.fill }}>
                    {row.outcome}
                  </td>
                  <td className="pr-2">{row.reward}</td>
                  <td className="pr-2">{row.response}</td>
                  {showPhases && row.phases.map((cell, i) => <td key={i} className="pr-2">{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[10px] leading-relaxed text-static/80">
        Read off a replay of the run&rsquo;s own state table. A greyed trial is one the run was cut off
        during, and is left out of every count; a greyed rate rests on too few trials to trust.
      </p>
    </div>
  );
}

/**
 * Each metric's accuracy over a run's counted trials, one line per metric,
 * dashed while its window is still filling (never, for a cumulative curve). Every value is the sidecar's
 * (`MetricSeries`); the caller says what the lines score.
 */
export function AccuracyChart({
  metrics,
  label,
  cumulative = false,
}: {
  metrics: MetricSeries[];
  label: string;
  /** A spine row's curve, the running whole-session figure: no window fills, so none is dashed. */
  cumulative?: boolean;
}) {
  return (
    <ChartFrame
      yTop="1.0"
      yBottom="0.0"
      xLeft="first counted trial"
      xRight="last"
      footer={
        <span className="flex items-center gap-2 truncate">
          {metrics.map((metric, index) => (
            <span key={metric.id} className="flex items-center gap-1">
              <span
                className="inline-block h-[2px] w-3"
                style={{ background: colorForIndex(index) }}
              />
              {metric.label}
            </span>
          ))}
        </span>
      }
    >
      <svg
        viewBox="0 0 100 36"
        preserveAspectRatio="none"
        className="h-[120px] w-full"
        role="img"
        aria-label={label}
      >
        <line
          x1={0}
          y1={18}
          x2={100}
          y2={18}
          stroke="var(--color-halo)"
          strokeWidth={0.5}
          strokeDasharray="2 2"
          vectorEffect="non-scaling-stroke"
        />
        {metrics.map((metric, index) => {
          const stroke = colorForIndex(index);
          // Inset by a stroke's worth top and bottom. A perfect side bias
          // pins one line at 1.0 and the other at 0.0 — exactly the shape
          // this view most needs to show — and an un-inset unit range draws
          // both of them half outside the frame.
          const point = (value: number, i: number) =>
            `${(i / (metric.values.length - 1)) * 100},${1 + (1 - value) * 34}`;
          // The warm-up ends where the window first fills.
          const settled = metric.n.findIndex((n) => n >= metric.windowSize);
          const cut = cumulative ? 0 : settled === -1 ? metric.values.length - 1 : settled;
          const warmup = metric.values.slice(0, cut + 1).map(point).join(" ");
          const steady = metric.values
            .slice(cut)
            .map((value, i) => point(value, i + cut))
            .join(" ");
          return (
            <g key={metric.id}>
              <polyline
                points={warmup}
                fill="none"
                stroke={stroke}
                strokeWidth={1}
                strokeDasharray="3 3"
                opacity={0.5}
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
              <polyline
                points={steady}
                fill="none"
                stroke={stroke}
                strokeWidth={1.4}
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}

function Fallback({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] leading-relaxed text-static">{children}</p>;
}

import { useEffect, useMemo, useState } from "react";

import { UnitChart } from "@/components/charts/UnitChart";
import {
  accuracy,
  outcomeMix,
  pacePerMinute,
  progressLines,
  type Tally,
} from "@/lib/sessions/boxProgress";
import { useBoxProgress } from "@/lib/sessions/context";

/** The tab's width; Mission Control's rail grows by this and the gap beside it. */
export const INSIGHT_TAB_WIDTH = 232;

const COMPLETED = "var(--color-static)";
const CORRECT = "var(--color-ion)";
const WRONG = "var(--color-status-error)";
const UNANSWERED = "var(--color-halo)";

/**
 * The tab beside a box's tile on Mission Control: the run in counts, readable
 * from across the room (`ARCHITECTURE.md#live-session-views`).
 *
 * The tile says what state the box is in and how the animal is doing lately
 * (its rolling metrics). This says how far the run has got: trials offered,
 * completed and correct as three figures, the same three as a cumulative
 * record, and how the offered trials divide. Every figure is the sidecar's
 * running total (`boxProgress.ts`), so a tab and Analytics cannot disagree
 * about a finished run.
 *
 * **Reading the record.** x is trials offered and both lines share its scale,
 * so the dashed diagonal is a run where every trial is completed and correct.
 * The grey line falling away from it is trials going unanswered; the green
 * line falling away from the grey is wrong answers. A flat stretch is an
 * animal that has stopped working, visible before any rolling figure moves.
 *
 * Matte (`ARCHITECTURE.md#theme`): two 1.5px lines, a segmented bar with
 * surface gaps, text in text tokens. Outcome colours are the ones the live
 * outcome panel uses, and each sits beside its count, never alone.
 */
export function BoxInsightTab({
  box,
  startedAt,
  live,
}: {
  box: number;
  /** When this box's run began, for the pace; null before it starts. */
  startedAt: string | null;
  /** The box is running: the pace keeps counting. */
  live: boolean;
}) {
  const series = useBoxProgress(box);
  const latest = series[series.length - 1] ?? null;
  const lines = useMemo(() => progressLines(series), [series]);
  const elapsed = useElapsedSeconds(startedAt, live);

  return (
    <aside
      aria-label={`Box ${box} progress`}
      // The connector: a hairline tick from the tab to its tile, so six tabs
      // beside six tiles read as six pairs and not as two columns.
      className="hud relative shrink-0 rounded-md rounded-tr-none p-3 after:absolute after:top-4 after:-right-2 after:h-px after:w-2 after:bg-halo"
      style={{ width: INSIGHT_TAB_WIDTH }}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-[9px] tracking-[0.18em] text-static uppercase">Trials</span>
        <Pace tally={latest} elapsed={elapsed} />
      </div>

      {latest === null || latest.offered === 0 ? (
        <p className="mt-2 text-[11px] leading-relaxed text-static">
          Counts appear with the first trial.
        </p>
      ) : (
        <>
          <Figures tally={latest} />
          <Record lines={lines} offered={latest.offered} />
          <Mix tally={latest} />
        </>
      )}
    </aside>
  );
}

/** Seconds since the run began, ticking while the box runs; null before a start. */
function useElapsedSeconds(startedAt: string | null, live: boolean): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live || !startedAt) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 5000);
    return () => window.clearInterval(timer);
  }, [live, startedAt]);
  if (!startedAt) return null;
  return Math.max(0, (now - new Date(startedAt).getTime()) / 1000);
}

function Pace({ tally, elapsed }: { tally: Tally | null; elapsed: number | null }) {
  const pace = tally ? pacePerMinute(tally, elapsed) : null;
  if (pace === null) return null;
  return (
    <span
      className="font-mono text-[10px] tabular-nums text-static"
      title="Trials completed per minute, over the run so far"
    >
      {pace.toFixed(1)}/min
    </span>
  );
}

/** The three counts, largest first in the order a trial goes through them. */
function Figures({ tally }: { tally: Tally }) {
  const p = accuracy(tally);
  return (
    <dl className="mt-2 grid grid-cols-3 gap-2">
      <Figure label="offered" value={tally.offered} title="Trials that began, the open one included" />
      <Figure
        label="completed"
        value={tally.completed}
        mark={COMPLETED}
        title="Trials that ended in a scored response, right or wrong"
      />
      <Figure
        label="correct"
        value={tally.correct}
        mark={CORRECT}
        note={p === null ? null : `${Math.round(p * 100)}%`}
        title="Completed trials the animal got right, and their share of the completed"
      />
    </dl>
  );
}

function Figure({
  label,
  value,
  mark,
  note,
  title,
}: {
  label: string;
  value: number;
  /** The colour this count is drawn in on the record below: its legend. */
  mark?: string;
  note?: string | null;
  title: string;
}) {
  return (
    <div title={title}>
      <dd className="font-mono text-[19px] leading-none tabular-nums text-starlight">
        {value}
        {note && <span className="ml-1 text-[10px] text-static">{note}</span>}
      </dd>
      <dt className="mt-1 flex items-center gap-1 text-[10px] text-static">
        {mark && (
          <span aria-hidden className="inline-block h-[2px] w-2.5" style={{ background: mark }} />
        )}
        {label}
      </dt>
    </div>
  );
}

/** The cumulative record: completed and correct against trials offered. */
function Record({
  lines,
  offered,
}: {
  lines: ReturnType<typeof progressLines>;
  offered: number;
}) {
  return (
    <figure className="mt-3" title="Completed (grey) and correct (green) trials against trials offered. The dashed diagonal is every trial completed and correct.">
      <div className="border-b border-l border-halo/80">
        <UnitChart
          height={34}
          className="block h-[58px] w-full"
          references={[{ from: { x: 0, y: 0 }, to: { x: 1, y: 1 } }]}
          series={[
            { segments: [{ points: lines.completed }], stroke: COMPLETED, strokeWidth: 1.5 },
            { segments: [{ points: lines.correct }], stroke: CORRECT, strokeWidth: 1.5 },
          ]}
        />
      </div>
      <figcaption className="mt-0.5 flex justify-between font-mono text-[9px] tabular-nums text-static/70">
        <span>0</span>
        <span>trials offered</span>
        <span>{offered}</span>
      </figcaption>
    </figure>
  );
}

/** How the offered trials divide: one bar, three parts, each with its count. */
function Mix({ tally }: { tally: Tally }) {
  const mix = outcomeMix(tally);
  const parts = [
    { key: "correct", n: mix.correct, fill: CORRECT, label: "correct" },
    { key: "wrong", n: mix.wrong, fill: WRONG, label: "wrong" },
    { key: "unanswered", n: mix.unanswered, fill: UNANSWERED, label: "no answer" },
  ];
  return (
    <div className="mt-2.5">
      <div className="flex h-[6px] gap-[2px]" role="img" aria-label="How the trials offered divide">
        {parts
          .filter((part) => part.n > 0)
          .map((part) => (
            <span
              key={part.key}
              className="h-full min-w-[2px] rounded-[1px]"
              style={{ flexGrow: part.n, flexBasis: 0, background: part.fill }}
              title={`${part.n} ${part.label}`}
            />
          ))}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-2.5 gap-y-0.5 font-mono text-[9px] tabular-nums text-static">
        {parts.map((part) => (
          <span key={part.key} className="flex items-center gap-1">
            <span
              aria-hidden
              className="inline-block size-[6px] rounded-[1px]"
              style={{ background: part.fill }}
            />
            <span className="text-starlight">{part.n}</span> {part.label}
          </span>
        ))}
      </div>
    </div>
  );
}

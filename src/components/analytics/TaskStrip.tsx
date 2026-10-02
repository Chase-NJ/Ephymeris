import { Layers } from "lucide-react";
import { useMemo } from "react";

import {
  colorForIndex,
  describeTaskMix,
  sessionSlot,
  type SessionOutcomePoint,
} from "@/lib/analytics/view";

/**
 * Which task the cohort was on, session by session — the strip that makes the
 * unfiltered trends below readable (`DATA.md#pooling-across-tasks`).
 *
 * The trends pool every run because their measurements are vocabulary-defined
 * and identical across tasks (`DATA.md#rewarded-and-response-accuracy`); what
 * changes across tasks is *difficulty*. This strip is that disclosure: an
 * accuracy cliff that lines up with a boundary here is a task change, not a
 * cohort forgetting. It shares the trends' session slots, so a boundary sits
 * exactly above the dashed rule the charts draw at the same x.
 *
 * Segments are the **dominant** task per session (chips borrowed from the
 * session summary); a session that mixed tasks says so on hover, and the
 * session summary's table is where the mix is spelled out per animal.
 */
export function TaskStrip({
  points,
  labels,
}: {
  points: SessionOutcomePoint[];
  labels: Map<string, string>;
}) {
  const segments = useMemo(() => buildSegments(points), [points]);
  if (points.length < 2 || segments.length === 0) return null;

  return (
    <div className="surface rounded-md px-4 pt-3 pb-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="flex items-center gap-1.5 text-[11px] text-static">
          <Layers size={13} strokeWidth={1.75} className="shrink-0 text-pulsar" />
          <span>
            Task
            <span className="ml-2 text-static/70">
              what each session below was running — the trends pool every task
              and this is where they change
            </span>
          </span>
        </span>
      </div>
      {/* The same 26px + 6px y-axis gutter the ChartFrames below carry, so a
          boundary here is vertically above its dashed rule in the charts. */}
      <div className="mt-1.5 pl-[32px]">
        <div className="relative h-[22px]">
          {segments.map((segment) => (
            <StripSegment
              key={`${segment.hash}-${segment.start}`}
              segment={segment}
              labels={labels}
              points={points}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

interface Segment {
  hash: string;
  /** Point indices, inclusive. */
  start: number;
  end: number;
  /** Track extent, 0–100. */
  left: number;
  width: number;
  mixed: boolean;
}

/**
 * Consecutive sessions sharing a dominant task, with edges at the midpoints
 * between slots — the same halfway line `taskChanges` puts its rules on, so
 * the strip and the charts cannot disagree about where a boundary is.
 */
function buildSegments(points: SessionOutcomePoint[]): Segment[] {
  if (points.length === 0) return [];
  const edge = (index: number): number => {
    if (index <= 0) return 0;
    if (index >= points.length) return 100;
    return (
      ((sessionSlot(index - 1, points.length) + sessionSlot(index, points.length)) / 2) *
      100
    );
  };

  const out: Segment[] = [];
  let start = 0;
  for (let index = 1; index <= points.length; index += 1) {
    const here = index < points.length ? (points[index]!.tasks[0]?.hash ?? "") : null;
    const current = points[start]!.tasks[0]?.hash ?? "";
    if (here === current) continue;
    out.push({
      hash: current,
      start,
      end: index - 1,
      left: edge(start),
      width: edge(index) - edge(start),
      mixed: points.slice(start, index).some((point) => point.tasks.length > 1),
    });
    start = index;
  }
  return out;
}

function StripSegment({
  segment,
  labels,
  points,
}: {
  segment: Segment;
  labels: Map<string, string>;
  points: SessionOutcomePoint[];
}) {
  const label = labels.get(segment.hash) ?? "unknown";
  // A task's colour is its place in the archive's order of first appearance —
  // `taskLabels` lists them that way — on the same series ramp the animals
  // use. Identity, not state: two segments of one task match across a gap,
  // and a return to shaping after discrimination reads as a return.
  const taskIndex = Math.max(0, [...labels.keys()].indexOf(segment.hash));
  const color = colorForIndex(taskIndex);
  const first = points[segment.start]!.session;
  const last = points[segment.end]!.session;
  const count = segment.end - segment.start + 1;
  const title = [
    `${label} · ${count} session${count === 1 ? "" : "s"}`,
    `${first.prefixName}_${first.sessionNumber} (${first.date}) → ${last.prefixName}_${last.sessionNumber} (${last.date})`,
    ...(segment.mixed
      ? [
          "some sessions mixed tasks — the segment names the dominant one; " +
            "hover a point below or open the session for the full mix",
        ]
      : []),
    ...points
      .slice(segment.start, segment.end + 1)
      .filter((point) => point.tasks.length > 1)
      .slice(0, 4)
      .map(
        (point) =>
          `  ${point.session.prefixName}_${point.session.sessionNumber}: ${describeTaskMix(point.tasks, labels)}`,
      ),
  ].join("\n");

  return (
    <span
      className={`absolute inset-y-0 flex min-w-0 items-center overflow-hidden border-halo bg-halo/30 px-1.5 first:rounded-l-[3px] last:rounded-r-[3px] ${
        segment.start > 0 ? "border-l border-dashed" : ""
      }`}
      style={{ left: `${segment.left}%`, width: `${segment.width}%` }}
      title={title}
    >
      {/* The task's colour as a hairline along the top edge — a tint of the
          whole segment would fight the labels and the chart under it. */}
      <span
        aria-hidden
        className="absolute inset-x-0 top-0 h-[2px] opacity-80"
        style={{ background: color }}
      />
      {/* Below ~4% a truncated label is one letter and an ellipsis — noise.
          The segment itself and its hover still carry the task. */}
      {segment.width >= 4 && (
        <span className="truncate font-mono text-[9px] text-static/80">
          {label}
          {segment.mixed && <span className="text-static/50"> +</span>}
        </span>
      )}
    </span>
  );
}

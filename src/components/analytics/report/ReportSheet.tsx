import { MotionConfig } from "framer-motion";
import { useMemo, type Ref } from "react";

import { Footnote } from "@/components/analytics/Footnote";
import { ALL_SESSIONS } from "@/lib/analytics/store";
import type {
  AnalyticsSummary,
  ProfileGroup,
  RunSeries,
  RunSummary,
  SessionListItem,
} from "@/lib/analytics/types";

import { CohortReport } from "./CohortReport";
import { ReportContext } from "./context";
import { SessionReport } from "./SessionReport";

/**
 * A composed, printable page of the panels the dashboard is already showing
 * (`data.md` §10.6).
 *
 * The sheet never re-implements a chart. It mounts the same components the
 * route mounts, with the same props, and only decides how they sit together —
 * which is what stops an exported figure from drifting away from the screen it
 * claims to be a picture of.
 *
 * **Authored at a fixed width**, because the panels do not all respond to width
 * the same way: the four trend charts pin their plot height in pixels while the
 * learning curves and both strategy planes are aspect-driven. Widen the sheet
 * and the trends flatten while the curves balloon, so the same data reads
 * differently on paper than it did on screen. 1280 is the app window's own
 * default width, which makes the sheet a faithful copy rather than a re-layout.
 */

/** Everything a sheet needs. Assembled once by the route, which already has it
 *  all in hand for the live panels. */
export interface ReportInput {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  colors: Map<string, string>;
  metricId: string | null;
  cohortName: string;
  revealKey: string;
  /** `null` exports the cohort; a session exports that session. */
  session: SessionListItem | null;
  sessionRuns: RunSummary[];
  sessionSeries: RunSeries[];
}

export const SHEET_WIDTH = 1280;

/**
 * Theme tokens copied onto the sheet as literal values.
 *
 * Belt and braces for the rasterizer. Chart colours here are overwhelmingly
 * `var(--color-…)` used as SVG presentation attributes (`binFor` returns one,
 * so does `OUTCOME_STYLE`, so do the axis strokes in `UnitChart`), and the
 * serialized clone is rendered as a detached document with no access to this
 * one's stylesheets. Copying computed styles *should* resolve them all; pinning
 * the tokens on the root means it doesn't matter if one slips through.
 */
const PINNED_TOKENS = [
  "--color-void",
  "--color-nebula",
  "--color-halo",
  "--color-pulsar",
  "--color-ion",
  "--color-starlight",
  "--color-static",
  "--color-status-ok",
  "--color-status-warning",
  "--color-status-error",
  "--color-series-1",
  "--color-series-2",
  "--color-series-3",
  "--color-series-4",
  "--color-series-5",
  "--color-series-6",
  "--color-heat-1",
  "--color-heat-2",
  "--color-heat-3",
  "--color-heat-4",
  "--color-heat-5",
  "--color-heat-6",
  "--color-heat-7",
  "--font-display",
  "--font-sans",
  "--font-mono",
] as const;

function pinnedTokens(): Record<string, string> {
  const root = getComputedStyle(document.documentElement);
  const out: Record<string, string> = {};
  for (const token of PINNED_TOKENS) {
    const value = root.getPropertyValue(token).trim();
    if (value) out[token] = value;
  }
  return out;
}

export function ReportSheet({
  input,
  ref,
}: {
  input: ReportInput;
  /** The node to rasterize. React 19 takes `ref` as an ordinary prop. */
  ref?: Ref<HTMLDivElement>;
}) {
  const style = useMemo(
    () => ({
      ...pinnedTokens(),
      // A definite width, not `max-content`: the panel grids use
      // `minmax(0,1fr)` tracks whose intrinsic contribution is undefined for
      // aspect-ratio SVGs, so an intrinsically-sized sheet resolves to
      // something arbitrary. A cohort wide enough to outgrow this is handled
      // at capture time by widening this node once, after measuring it.
      width: SHEET_WIDTH,
      backgroundColor: "var(--color-void)",
      fontFamily: "var(--font-sans)",
    }),
    [],
  );

  const scope = input.session ? input.session.id : ALL_SESSIONS;

  return (
    <ReportContext.Provider value={true}>
      {/*
        `skipAnimations` rather than a `transition` default, and this is the
        whole reason the export isn't a race.

        Every reveal in `components/charts` and `components/analytics` sets its
        transition *inline* — the heatmap staggers each column, `ChartDots`
        delays each dot by its x position, `DrawOn` runs a 0.9s wipe — and an
        inline transition wins the merge against `MotionConfig transition`. So
        that lever cannot make the sheet settle. `skipAnimations` is checked at
        the animation driver, after transitions resolve, and it zeroes `delay`
        as well as duration; nothing is left in flight for a capture to catch
        half-drawn. It also merges with the parent config, so `AppShell`'s
        `reducedMotion` survives.

        Forcing `useRevealOnView` (see `ReportContext`) is the other half and
        not a substitute: that picks *what* to animate towards, this collapses
        how long getting there takes.
      */}
      <MotionConfig skipAnimations>
        <div data-report ref={ref} className="p-8 text-starlight" style={style}>
          <Masthead input={input} />

          {input.session ? (
            <SessionReport input={input} session={input.session} />
          ) : (
            <CohortReport input={input} />
          )}

          <div className="mt-4 border-t border-halo pt-3">
            {/* Warnings travel with the figure. A sheet generated while the
                cohort's data folder was unreachable is showing the last good
                read, and a PNG that doesn't say so is a lie on paper. */}
            {input.summary.warnings.length > 0 && (
              <p className="mb-1.5 px-1 font-mono text-[10px] leading-relaxed"
                 style={{ color: "var(--color-status-warning)" }}>
                {input.summary.warnings.map((w) => w.message).join(" · ")}
              </p>
            )}
            <Footnote
              summary={input.summary}
              cohortName={input.cohortName}
              scope={scope}
            />
          </div>
        </div>
      </MotionConfig>
    </ReportContext.Provider>
  );
}

/**
 * Who, what task, which metric, and when — the provenance a screenshot loses.
 *
 * The date range is here rather than implied by the panels because the sheet
 * has no `SessionRail`: the heatmap's x axis is evenly spaced by session index,
 * so nothing else on the page carries calendar time, and "twelve sessions" over
 * a fortnight is a different experiment from twelve over three months.
 */
function Masthead({ input }: { input: ReportInput }) {
  const { summary, profile, session, metricId, cohortName } = input;

  const metricLabel =
    profile?.metrics.find((metric) => metric.id === metricId)?.label ?? null;

  const span = useMemo(() => {
    const dates = [...summary.sessions]
      // `ordinal` is the sidecar's chronological rank from (date, startedAt).
      // Sorting the dates as strings would be wrong for the legacy `MM_DD_YY`
      // names the archive still holds (`data.md` §8.1).
      .sort((a, b) => a.ordinal - b.ordinal)
      .map((s) => s.date);
    if (dates.length === 0) return null;
    const first = dates[0]!;
    const last = dates[dates.length - 1]!;
    return first === last ? first : `${first} → ${last}`;
  }, [summary]);

  const facts = [
    profile?.taskName ?? "Unnamed task",
    metricLabel,
    span ? `${summary.sessions.length} sessions · ${span}` : null,
    `exported ${new Date().toISOString().slice(0, 16).replace("T", " ")}`,
  ].filter(Boolean);

  return (
    <div className="mb-4 flex items-baseline justify-between gap-4 border-b border-halo pb-3">
      <div className="flex items-baseline gap-3">
        <h1 className="font-display text-[20px] text-starlight">{cohortName}</h1>
        <span className="font-mono text-[12px] text-static">
          {session
            ? `${session.prefixName}_${session.sessionNumber} · ${session.date}`
            : "All sessions"}
        </span>
      </div>
      <span className="font-mono text-[10px] text-static/70">{facts.join(" · ")}</span>
    </div>
  );
}

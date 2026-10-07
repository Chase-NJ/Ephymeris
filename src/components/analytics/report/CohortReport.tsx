import { CohortTrends } from "@/components/analytics/CohortTrends";

import type { ReportInput } from "./ReportSheet";

/**
 * The across-session sheet — the cohort compared with itself over time.
 *
 * The dashboard's `ALL_SESSIONS` scope exactly, because it is the same
 * component (`CohortTrends`) in its `sheet` form: fixed grids rather than the
 * route's `xl:` ones, since Tailwind's breakpoints are *viewport* queries and
 * the sheet's authored width has nothing to do with the window's; and an
 * unbounded animal rail, since a PNG cannot scroll.
 *
 * `SessionRail` is left out: it is a control, not a reading, and it wraps a
 * horizontal scroller that would rasterize to whatever happened to be in view.
 * The masthead carries its date range instead.
 */
export function CohortReport({ input }: { input: ReportInput }) {
  // Distinct from the live tree's, because both are mounted at once and
  // `SessionStrategy` builds SVG gradient ids out of it — two identical ids in
  // one document and every `url(#…)` resolves to the first.
  return (
    <CohortTrends
      summary={input.summary}
      colors={input.colors}
      revealKey={`${input.revealKey}:report`}
      sheet
    />
  );
}

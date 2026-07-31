import { createContext, useContext } from "react";

/**
 * True inside a report sheet being rendered for export (`data.md` §10.6).
 *
 * Its own module, deliberately: `charts/reveal.ts` consumes this, and putting
 * it beside `ReportSheet` would make every chart primitive import the sheet
 * that imports every chart.
 */
export const ReportContext = createContext(false);

export function useIsReport(): boolean {
  return useContext(ReportContext);
}

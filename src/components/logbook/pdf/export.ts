/**
 * Exporting the log as a PDF (`DATA.md#exporting-a-log`).
 *
 * Everything heavy is behind `import()`: react-pdf, its layout engine and the
 * embedded fonts load on the first export and never on the way to a session.
 * A failure to load them costs the export and nothing else
 * (`ARCHITECTURE.md#dependency-policy`).
 */

import { createElement } from "react";

import { saveFile, slug } from "@/components/analytics/report/capture";
import type { ExportTracker } from "@/lib/exports/jobs";
import type { DocCohort, DocSession } from "@/lib/logbook/document";

const PDF = { name: "PDF document", extensions: ["pdf"] };

/** Render to bytes without saving — what the save path and a check both use. */
export async function renderSessionPdf(
  session: DocSession,
  cohortName: string,
  exportedAt: string,
): Promise<Blob> {
  const [{ pdf }, { SessionLogDocument }] = await Promise.all([
    import("@react-pdf/renderer"),
    import("./documents"),
  ]);
  return pdf(createElement(SessionLogDocument, { session, cohortName, exportedAt }) as never).toBlob();
}

export async function renderCohortPdf(cohort: DocCohort): Promise<Blob> {
  const [{ pdf }, { CohortLogbookDocument }] = await Promise.all([
    import("@react-pdf/renderer"),
    import("./documents"),
  ]);
  return pdf(createElement(CohortLogbookDocument, { cohort }) as never).toBlob();
}

/** Resolves to the saved path, or null if the operator cancelled. */
export async function exportSessionPdf(
  session: DocSession,
  cohortName: string,
  exportedAt: string,
  tracker?: ExportTracker,
): Promise<string | null> {
  const blob = await renderSessionPdf(session, cohortName, exportedAt);
  return saveFile(blob, `${slug(cohortName)}_${slug(session.title)}_${session.date}_log.pdf`, PDF, tracker);
}

export async function exportCohortPdf(cohort: DocCohort, tracker?: ExportTracker): Promise<string | null> {
  const blob = await renderCohortPdf(cohort);
  return saveFile(blob, `${slug(cohort.cohortName)}_logbook.pdf`, PDF, tracker);
}

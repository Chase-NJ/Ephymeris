import { FileDown } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/common/controls";
import { useAnalyticsStore } from "@/lib/analytics/context";
import { SAVE_STEPS, trackExport } from "@/lib/exports/jobs";
import type { SessionListItem } from "@/lib/analytics/types";
import { buildCohort, buildSession } from "@/lib/logbook/document";
import type { LogbookEntry } from "@/lib/logbook/store";
import { useSidecar } from "@/lib/ws/context";

/**
 * Save the log as a PDF (`USER-GUIDE.md#saving-the-log-as-a-pdf`): the
 * session on screen, or the cohort's whole logbook. The performance table
 * needs the Analytics summary, so it is fetched first — usually already
 * cached, because the Log has been showing it. Progress, the saved file and
 * any failure are on the export card (`ARCHITECTURE.md#export-progress`).
 */
const READING = "Reading sessions";
const LOADING = "Loading the PDF engine";

export function LogExport({
  cohortId,
  cohortName,
  entry,
  session,
  names,
}: {
  cohortId: string;
  cohortName: string;
  entry: LogbookEntry;
  session: SessionListItem | null;
  names: Map<string, string>;
}) {
  const { client } = useSidecar();
  const analytics = useAnalyticsStore();
  const [busy, setBusy] = useState<"session" | "cohort" | null>(null);

  async function run(kind: "session" | "cohort") {
    setBusy(kind);
    const sessions = kind === "session" ? 1 : entry.sessions.length;
    const laying = `Laying out ${sessions} session${sessions === 1 ? "" : "s"}`;
    try {
      await trackExport(
        kind === "session" ? "Session PDF" : "Logbook PDF",
        "pdf",
        [READING, LOADING, laying, ...SAVE_STEPS],
        async (tracker) => {
          await analytics.load(client, cohortId).catch(() => undefined);
          const summary = analytics.getSummary(cohortId);
          const now = new Date();
          const exportedAt = now.toLocaleString("en-GB", { hour12: false });
          tracker.step(LOADING);
          const pdf = await import("./pdf/export");
          tracker.step(laying);
          return kind === "session" && session
            ? pdf.exportSessionPdf(
                buildSession(session, entry, summary, names, now),
                cohortName,
                exportedAt,
                tracker,
              )
            : pdf.exportCohortPdf(buildCohort(cohortName, entry, summary, names, now), tracker);
        },
      );
    } catch {
      // On the card already.
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          disabled={busy !== null || !session}
          onClick={() => void run("session")}
          title="Save the selected session's log as a PDF"
        >
          <FileDown size={13} strokeWidth={1.75} />
          Session PDF
        </Button>
        <Button
          variant="outline"
          disabled={busy !== null || entry.sessions.length === 0}
          onClick={() => void run("cohort")}
          title="Save every session's log for this cohort as one PDF"
        >
          <FileDown size={13} strokeWidth={1.75} />
          Logbook PDF
        </Button>
      </div>
    </div>
  );
}

import { FileDown, Loader2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/common/controls";
import { errorMessage } from "@/lib/analytics/commands";
import { useAnalyticsStore } from "@/lib/analytics/context";
import type { SessionListItem } from "@/lib/analytics/types";
import { buildCohort, buildSession } from "@/lib/logbook/document";
import type { LogbookEntry } from "@/lib/logbook/store";
import { useSidecar } from "@/lib/ws/context";

/**
 * Save the log as a PDF (`USER-GUIDE.md#saving-the-log-as-a-pdf`): the
 * session on screen, or the cohort's whole logbook. The performance table
 * needs the Analytics summary, so it is fetched first — usually already
 * cached, because the Log has been showing it.
 */
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
  const [result, setResult] = useState<{ text: string; error: boolean } | null>(null);

  async function run(kind: "session" | "cohort") {
    setBusy(kind);
    setResult(null);
    try {
      await analytics.load(client, cohortId).catch(() => undefined);
      const summary = analytics.getSummary(cohortId);
      const now = new Date();
      const exportedAt = now.toLocaleString("en-GB", { hour12: false });
      const pdf = await import("./pdf/export");
      const path =
        kind === "session" && session
          ? await pdf.exportSessionPdf(
              buildSession(session, entry, summary, names, now),
              cohortName,
              exportedAt,
            )
          : await pdf.exportCohortPdf(buildCohort(cohortName, entry, summary, names, now));
      if (path) setResult({ text: `Saved ${path.split(/[\\/]/).pop()}`, error: false });
    } catch (err) {
      setResult({ text: `Couldn't export: ${errorMessage(err)}`, error: true });
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
          {busy === "session" ? (
            <Loader2 size={13} strokeWidth={1.75} className="animate-spin" />
          ) : (
            <FileDown size={13} strokeWidth={1.75} />
          )}
          Session PDF
        </Button>
        <Button
          variant="outline"
          disabled={busy !== null || entry.sessions.length === 0}
          onClick={() => void run("cohort")}
          title="Save every session's log for this cohort as one PDF"
        >
          {busy === "cohort" ? (
            <Loader2 size={13} strokeWidth={1.75} className="animate-spin" />
          ) : (
            <FileDown size={13} strokeWidth={1.75} />
          )}
          Logbook PDF
        </Button>
      </div>
      {result && (
        <span
          role={result.error ? "alert" : "status"}
          className={`font-mono text-[10px] ${result.error ? "text-status-error" : "text-static"}`}
        >
          {result.text}
        </span>
      )}
    </div>
  );
}

import { ChartLine, CircleCheck } from "lucide-react";
import { useLocation } from "react-router";

import { PlaceholderView } from "@/components/common/PlaceholderView";

export function Analytics() {
  // Set when a session's end navigated here (`MissionControl`) — the guided
  // flow's landing acknowledges the session actually closed and saved.
  const location = useLocation();
  const ended = (location.state as { endedSession?: string | null } | null)
    ?.endedSession;

  return (
    <PlaceholderView title="Analytics" icon={ChartLine}>
      {ended && (
        <span
          className="mb-3 flex items-center gap-1.5 font-mono text-[12px]"
          style={{ color: "var(--color-status-ok)" }}
        >
          <CircleCheck size={14} strokeWidth={1.75} className="shrink-0" />
          {ended} ended — its data files are in the session folder.
        </span>
      )}
      Nothing to analyze yet. Within-session, across-session, and per-cohort
      views will live here once sessions are recording data.
    </PlaceholderView>
  );
}

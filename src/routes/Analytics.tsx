import { ChartLine } from "lucide-react";

import { PlaceholderView } from "@/components/common/PlaceholderView";

export function Analytics() {
  return (
    <PlaceholderView title="Analytics" icon={ChartLine}>
      Nothing to analyze yet. Within-session, across-session, and per-cohort
      views will live here once sessions are recording data.
    </PlaceholderView>
  );
}

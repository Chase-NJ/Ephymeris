import { Route, Routes } from "react-router";

import { AppShell } from "./components/chrome/AppShell";
import { Analytics } from "./routes/Analytics";
import { Config } from "./routes/Config";
import { CohortEditor } from "./routes/CohortEditor";
import { Cohorts } from "./routes/Cohorts";
import { Dashboard } from "./routes/Dashboard";
import { DebugMode } from "./routes/DebugMode";
import { Launch } from "./routes/Launch";
import { MissionControl } from "./routes/MissionControl";
import { SessionConfig } from "./routes/SessionConfig";
import { SessionMapping } from "./routes/SessionMapping";
import { Settings } from "./routes/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Dashboard />} />
        <Route path="/launch" element={<Launch />} />
        <Route path="/cohorts" element={<Cohorts />} />
        <Route path="/cohorts/new" element={<CohortEditor />} />
        <Route path="/cohorts/:id" element={<CohortEditor />} />
        <Route path="/debug" element={<DebugMode />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/config" element={<Config />} />
        <Route path="/settings" element={<Settings />} />
        {/* Two-step session setup (`starting-a-session.md` §2–§4); the runner
            takes over at /session/:id/control. */}
        <Route path="/session/new" element={<SessionConfig />} />
        <Route path="/session/:id/mapping" element={<SessionMapping />} />
        <Route path="/session/:id/control" element={<MissionControl />} />
        {/* Unknown routes fall back to the dashboard rather than a blank pane. */}
        <Route path="*" element={<Dashboard />} />
      </Route>
    </Routes>
  );
}

import { Route, Routes } from "react-router";

import { AppShell } from "./components/chrome/AppShell";
import { Analytics } from "./routes/Analytics";
import { Config } from "./routes/Config";
import { CohortEditor } from "./routes/CohortEditor";
import { Cohorts } from "./routes/Cohorts";
import { Dashboard } from "./routes/Dashboard";
import { DebugMode } from "./routes/DebugMode";
import { MissionControl } from "./routes/MissionControl";
import { SessionConfig } from "./routes/SessionConfig";
import { SessionMapping } from "./routes/SessionMapping";
import { Settings } from "./routes/Settings";
import { Task } from "./routes/Task";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Dashboard />} />
        {/* /launch is retired (dashboard.md §2.2) — the Dashboard's hero
            and session dock absorbed it, and old paths fall through to `*`. */}
        <Route path="/cohorts" element={<Cohorts />} />
        <Route path="/cohorts/new" element={<CohortEditor />} />
        <Route path="/cohorts/:id" element={<CohortEditor />} />
        <Route path="/debug" element={<DebugMode />} />
        <Route path="/task" element={<Task />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/config" element={<Config />} />
        <Route path="/settings" element={<Settings />} />
        {/* Two-step session setup (`dashboard.md` §7.2–§4); the runner
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

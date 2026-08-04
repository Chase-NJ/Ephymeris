import { Navigate, Route, Routes } from "react-router";

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
import { TaskBench } from "./routes/TaskBench";
import { TaskDesigner } from "./routes/TaskDesigner";
import { TaskNew } from "./routes/TaskNew";
import { TaskSketches } from "./routes/TaskSketches";

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
        {/* The Task family. Flat, like every other route here — `AppShell` is
            the one layout route, and its `RouteTransition` keys on pathname
            through `useOutlet()`, which a second nested outlet would confuse.
            `Sidebar` prefix-matches, so the nav pill stays lit across all five. */}
        <Route path="/task" element={<Task />} />
        <Route path="/task/new" element={<TaskNew />} />
        <Route path="/task/designer/:specId" element={<TaskDesigner />} />
        <Route path="/task/bench" element={<TaskBench />} />
        <Route path="/task/sketches" element={<TaskSketches />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/config" element={<Config />} />
        <Route path="/settings" element={<Settings />} />
        {/* Two-step session setup (`dashboard.md` §7.2–§4); the runner
            takes over at /session/:id/control. */}
        <Route path="/session/new" element={<SessionConfig />} />
        <Route path="/session/:id/mapping" element={<SessionMapping />} />
        <Route path="/session/:id/control" element={<MissionControl />} />
        {/* Unknown routes **redirect** to the dashboard rather than rendering
            it under a foreign URL. Rendering it in place left the URL, the
            route and the sidebar disagreeing: `Sidebar`'s Dashboard match is
            `pathname === "/"`, so no tab lit — and the selection pill is a
            shared `layoutId`, so it didn't just move, it unmounted. `replace`
            keeps the dead URL out of history. */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

import { Navigate, Route, Routes } from "react-router";

import { AppShell } from "./components/chrome/AppShell";
import { Analytics } from "./routes/Analytics";
import { Config } from "./routes/Config";
import { CohortEditor } from "./routes/CohortEditor";
import { Cohorts } from "./routes/Cohorts";
import { Dashboard } from "./routes/Dashboard";
import { DebugMode } from "./routes/DebugMode";
import { MissionControl } from "./routes/MissionControl";
import { RigStrobes } from "./routes/RigStrobes";
import { RigWiring } from "./routes/RigWiring";
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
        {/* Task is the task-profile editor (`tasks.md` §11): the trial table,
            the ramp, the parameters. Saving one generates a sketch that
            discovery finds, so `port.flash` takes it like any other. */}
        <Route path="/task" element={<Task />} />
        {/* Rig wiring is a subpage of the Rig screen — box↔board and
            channel↔pin are different wirings but one subject, so the editor
            lives at `/config/wiring` behind the landing's Wiring door. Old
            addresses redirect rather than fall to the catch-all: a stale link
            landing on the Dashboard reads as the page having been deleted. */}
        <Route path="/task/hardware" element={<Navigate to="/config/wiring" replace />} />
        <Route path="/task/sketches" element={<Navigate to="/task" replace />} />
        <Route path="/sketches" element={<Navigate to="/task" replace />} />
        <Route path="/analytics" element={<Analytics />} />
        {/* The route spelling stays `/config` while the tab reads **Rig**. The
            name is the user's word for the screen; the path is an internal
            address that every doc, and this app's own history, already spells
            this way — renaming it would churn both to no one's benefit, since a
            desktop app never shows its URL. `routes/Config.tsx` likewise. */}
        <Route path="/config" element={<Config />} />
        <Route path="/config/wiring" element={<RigWiring />} />
        {/* Strobes sit beside wiring, not under Task: a code is a fact about
            what this hardware can report, true of every task on it. Which
            codes a task DECLARES is decided by its trial table. */}
        <Route path="/config/strobes" element={<RigStrobes />} />
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

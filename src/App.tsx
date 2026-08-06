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
            `Sidebar` prefix-matches, so the nav pill stays lit across all six. */}
        <Route path="/task" element={<Task />} />
        <Route path="/task/new" element={<TaskNew />} />
        <Route path="/task/designer/:specId" element={<TaskDesigner />} />
        {/* Rig wiring lives on the Rig screen now (`RigWiringEditor` inside
            `routes/Config.tsx`) — box↔board and channel↔pin are different
            wirings but one subject. The old route redirects like `/sketches`
            does, and for the same reason. */}
        <Route path="/task/hardware" element={<Navigate to="/config" replace />} />
        <Route path="/task/bench" element={<TaskBench />} />
        {/* The sketch library joined the Task family and gave up its sidebar
            tab: it is one of the things a task can be made of, so it belongs
            behind the tab that asks what the animal does rather than beside it.
            **The page itself is unchanged and must stay reachable** — it is the
            only editor for `settings.taskDefaults` (`tasks.md` §10), which the
            mapping step merges into every `START` line whether or not anything
            can show it. */}
        <Route path="/task/sketches" element={<TaskSketches />} />
        {/* Its old address, kept as a redirect rather than left to the `*`
            catch-all: a stale link landing on the Dashboard reads as the page
            having been deleted. */}
        <Route path="/sketches" element={<Navigate to="/task/sketches" replace />} />
        <Route path="/analytics" element={<Analytics />} />
        {/* The route spelling stays `/config` while the tab reads **Rig**. The
            name is the user's word for the screen; the path is an internal
            address that every doc, and this app's own history, already spells
            this way — renaming it would churn both to no one's benefit, since a
            desktop app never shows its URL. `routes/Config.tsx` likewise. */}
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

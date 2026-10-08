import { Navigate, Route, Routes } from "react-router";

import { AppShell } from "./components/chrome/AppShell";
import { Analytics } from "./routes/Analytics";
import { Config } from "./routes/Config";
import { CohortEditor } from "./routes/CohortEditor";
import { Cohorts } from "./routes/Cohorts";
import { Dashboard } from "./routes/Dashboard";
import { DebugMode } from "./routes/DebugMode";
import { Log } from "./routes/Log";
import { MissionControl } from "./routes/MissionControl";
import { Recording } from "./routes/Recording";
import { RigWiring } from "./routes/RigWiring";
import { SessionConfig } from "./routes/SessionConfig";
import { SessionGroup } from "./routes/SessionGroup";
import { SessionMapping } from "./routes/SessionMapping";
import { SessionRecording } from "./routes/SessionRecording";
import { Settings } from "./routes/Settings";
import { Task } from "./routes/Task";
import { TaskEditor } from "./routes/TaskEditor";
import { TaskStrobes } from "./routes/TaskStrobes";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Dashboard />} />
        {/* /launch is retired (`ARCHITECTURE.md#routes`) — the Dashboard's hero
            and session dock absorbed it, and old paths fall through to `*`. */}
        <Route path="/cohorts" element={<Cohorts />} />
        <Route path="/cohorts/new" element={<CohortEditor />} />
        <Route path="/cohorts/:id" element={<CohortEditor />} />
        <Route path="/debug" element={<DebugMode />} />
        {/* Task is a landing over an editor. `/task` lists this rig's saved
            profiles; the editor (`TASKS.md#editor` — the trial types, the ramp,
            the parameters) opens on one of them, or on nothing at `/task/new`.
            Saving generates a sketch that discovery finds, so `port.flash`
            takes it like any other.

            `/task/new` is declared BEFORE `/task/:taskId` for readability
            only — the router ranks a static segment above a dynamic one
            regardless of order, so there is no task whose id shadows it. */}
        <Route path="/task" element={<Task />} />
        {/* The strobe vocabulary, where codes are added and retired. A Task
            page and not a Rig one: a pin is compile-time input to the firmware
            a task generates, while a code is what a condition is NAMED by, and
            the trial table's onset picker one page away is its main reader. */}
        <Route path="/task/strobes" element={<TaskStrobes />} />
        <Route path="/task/new" element={<TaskEditor />} />
        <Route path="/task/:taskId" element={<TaskEditor />} />
        {/* Rig wiring is a subpage of the Rig screen — box↔board and
            channel↔pin are different wirings but one subject, so the editor
            lives at `/config/wiring` behind the landing's Wiring door. */}
        <Route path="/analytics" element={<Analytics />} />
        {/* The lab notebook (`DATA.md#the-session-log`): a cohort's sessions
            on a time rail, each with its notes, clock and what changed. */}
        <Route path="/log" element={<Log />} />
        {/* The route spelling stays `/config` while the tab reads **Rig**. The
            name is the user's word for the screen; the path is an internal
            address that every doc, and this app's own history, already spells
            this way — renaming it would churn both to no one's benefit, since a
            desktop app never shows its URL. `routes/Config.tsx` likewise. */}
        <Route path="/config" element={<Config />} />
        <Route path="/config/wiring" element={<RigWiring />} />
        {/* Recording: the link to Intan RHX, the box->digital-input bindings
            and the recording defaults. */}
        <Route path="/recording" element={<Recording />} />
        <Route path="/settings" element={<Settings />} />
        {/* Two-step session setup (`ARCHITECTURE.md#the-flow`); the runner
            takes over at /session/:id/control. */}
        <Route path="/session/new" element={<SessionConfig />} />
        <Route path="/session/:id/group" element={<SessionGroup />} />
        <Route path="/session/:id/mapping" element={<SessionMapping />} />
        <Route path="/session/:id/recording" element={<SessionRecording />} />
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

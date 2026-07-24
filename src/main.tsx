import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";

import App from "./App";
import { CohortsProvider } from "./lib/cohorts/CohortsProvider";
import { HardwareProvider } from "./lib/hardware/HardwareProvider";
import { SessionsProvider } from "./lib/sessions/SessionsProvider";
import { SettingsProvider } from "./lib/settings/SettingsProvider";
import { SidecarProvider } from "./lib/ws/SidecarProvider";
import "./styles/fonts";
import "./styles/index.css";

const container = document.getElementById("root");
if (!container) throw new Error("#root is missing from index.html");

createRoot(container).render(
  <StrictMode>
    {/* Hash routing: the app is served from a file:// origin in production
        builds, where history-based routing has no server to fall back on. */}
    <HashRouter>
      {/* Settings sit inside the sidecar provider because pushing settings to
          the sidecar on every connect is their job, not the socket's. */}
      <SidecarProvider>
        <SettingsProvider>
          <HardwareProvider>
            <CohortsProvider>
              {/* App-level so telemetry keeps accumulating even if the user
                  navigates away from Mission Control mid-run. */}
              <SessionsProvider>
                <App />
              </SessionsProvider>
            </CohortsProvider>
          </HardwareProvider>
        </SettingsProvider>
      </SidecarProvider>
    </HashRouter>
  </StrictMode>,
);

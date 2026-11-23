import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router";

import App from "./App";
import { AnalyticsProvider } from "@/features/analytics/AnalyticsProvider";
import { CohortsProvider } from "@/features/cohorts/CohortsProvider";
import { HardwareProvider } from "@/features/hardware/HardwareProvider";
import { IntanProvider } from "@/features/intan/IntanProvider";
import { LogbookProvider } from "@/features/logbook/LogbookProvider";
import { SessionsProvider } from "@/features/sessions/SessionsProvider";
import { SettingsProvider } from "@/features/settings/SettingsProvider";
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
            {/* App-level: the Dashboard's Start Recording tile and Mission
                Control's REC pill both read it. */}
            <IntanProvider>
              <CohortsProvider>
                {/* App-level so telemetry keeps accumulating even if the user
                    navigates away from Mission Control mid-run. */}
                <SessionsProvider>
                  {/* App-level too: a cold summary can index an entire archive,
                      and navigating away and back shouldn't pay that twice. */}
                  <AnalyticsProvider>
                    {/* App-level for the same reason, and because Mission
                        Control and the session wrap-up take notes too. */}
                    <LogbookProvider>
                      <App />
                    </LogbookProvider>
                  </AnalyticsProvider>
                </SessionsProvider>
              </CohortsProvider>
            </IntanProvider>
          </HardwareProvider>
        </SettingsProvider>
      </SidecarProvider>
    </HashRouter>
  </StrictMode>,
);

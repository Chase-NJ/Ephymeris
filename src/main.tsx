import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router";

import App from "./App";
import { AnalyticsProvider } from "./lib/analytics/AnalyticsProvider";
import { CohortsProvider } from "./lib/cohorts/CohortsProvider";
import { HardwareProvider } from "./lib/hardware/HardwareProvider";
import { IntanProvider } from "./lib/intan/IntanProvider";
import { SessionsProvider } from "./lib/sessions/SessionsProvider";
import { SettingsProvider } from "./lib/settings/SettingsProvider";
import { SidecarProvider } from "./lib/ws/SidecarProvider";
import { ScopeApp } from "./routes/scope/ScopeApp";
import "./styles/fonts";
import "./styles/index.css";

const container = document.getElementById("root");
if (!container) throw new Error("#root is missing from index.html");

/**
 * A recording pop-up (`ARCHITECTURE.md#scope-windows`) is this same bundle in a second OS
 * window, opened at `#/scope/<kind>`. It gets a SLIM tree, and what is left out
 * matters more than what is in:
 *
 *   - no `SettingsProvider` — its job is pushing settings to the sidecar on
 *     every connect, and a scope window connecting must not re-push a copy of
 *     the settings it loaded at some earlier moment over the main window's;
 *   - no sessions / cohorts / analytics stores, no `AppShell`, no 3D canvas —
 *     a second WebGL context and a second copy of every subscription, to draw a
 *     histogram.
 *
 * It opens its own authenticated WebSocket (the sidecar serves any number of
 * clients), so a scope keeps drawing whatever the main window is doing.
 */
const isScopeWindow = window.location.hash.startsWith("#/scope/");

createRoot(container).render(
  <StrictMode>
    {/* Hash routing: the app is served from a file:// origin in production
        builds, where history-based routing has no server to fall back on. */}
    <HashRouter>
      {isScopeWindow ? (
        <SidecarProvider>
          <IntanProvider>
            <ScopeApp />
          </IntanProvider>
        </SidecarProvider>
      ) : (
        /* Settings sit inside the sidecar provider because pushing settings to
           the sidecar on every connect is their job, not the socket's. */
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
                      <App />
                    </AnalyticsProvider>
                  </SessionsProvider>
                </CohortsProvider>
              </IntanProvider>
            </HardwareProvider>
          </SettingsProvider>
        </SidecarProvider>
      )}
    </HashRouter>
  </StrictMode>,
);

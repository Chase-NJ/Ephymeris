import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { CMD, EVT } from "../ws/protocol";
import { useSidecar } from "../ws/context";
import { SettingsContext } from "./context";
import { loadSettings, saveSettings } from "./store";
import {
  DEFAULT_SETTINGS,
  EMPTY_DISCOVERY,
  type EphymerisSettings,
  type SketchDiscovery,
} from "./schema";

/**
 * Owns settings state and the one-directional Tauri → sidecar sync.
 *
 * Per `ARCHITECTURE.md#persistence-and-push` the shell is the source of truth and pushes the
 * full payload **on every connect/reconnect and on every change**. The failure
 * mode is deliberately mild: worst case the sidecar runs briefly on stale
 * values until the next push, rather than being unreachable.
 */
export function SettingsProvider({ children }: { children: ReactNode }) {
  const { client, status } = useSidecar();

  const [settings, setSettings] = useState<EphymerisSettings>(DEFAULT_SETTINGS);
  const [discovery, setDiscovery] = useState<SketchDiscovery>(EMPTY_DISCOVERY);
  const [loaded, setLoaded] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Read by the reconnect handler, which would otherwise close over whatever
  // settings existed when it was registered.
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  useEffect(() => {
    let active = true;
    void loadSettings().then((stored) => {
      if (!active) return;
      setSettings(stored);
      setLoaded(true);
    });
    return () => {
      active = false;
    };
  }, []);

  const push = useCallback(
    async (next: EphymerisSettings) => {
      if (client.getStatus() !== "connected") return;
      try {
        await client.call(CMD.SETTINGS_PUSH, { settings: next });
      } catch (err) {
        console.error("settings push failed", err);
      }
    },
    [client],
  );

  // The one push path: fires when the socket reaches `connected` (initial
  // connect and every reconnect, since status leaves and re-enters that state)
  // and when settings finish loading after the socket was already up. Driving
  // this off status rather than a separate ready callback keeps it to a single
  // trigger — two paths meant two pushes per connect.
  useEffect(() => {
    if (loaded && status === "connected") void push(settingsRef.current);
  }, [loaded, status, push]);

  // Discovery results arrive unsolicited whenever the sidecar rescans.
  useEffect(() => {
    return client.on(EVT.SKETCHES_UPDATED, (data) => {
      setDiscovery(data as SketchDiscovery);
    });
  }, [client]);

  const update = useCallback(
    async (patch: Partial<EphymerisSettings>) => {
      const next = { ...settingsRef.current, ...patch };
      settingsRef.current = next;
      setSettings(next);
      setSaveError(null);
      try {
        await saveSettings(next);
      } catch {
        setSaveError("Couldn't save to disk — your change may not survive a restart.");
      }
      await push(next);
    },
    [push],
  );

  const refreshSketches = useCallback(async () => {
    if (client.getStatus() !== "connected") return;
    try {
      const result = await client.call(CMD.SKETCHES_REFRESH);
      setDiscovery(result as SketchDiscovery);
    } catch (err) {
      console.error("sketch refresh failed", err);
    }
  }, [client]);

  const value = useMemo(
    () => ({ settings, update, discovery, refreshSketches, loaded, saveError }),
    [settings, update, discovery, refreshSketches, loaded, saveError],
  );

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

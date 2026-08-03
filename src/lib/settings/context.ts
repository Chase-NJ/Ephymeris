import { createContext, useContext, useMemo } from "react";

import type { EphymerisSettings, SketchDiscovery } from "./schema";

export interface SettingsContextValue {
  settings: EphymerisSettings;
  /** Merge a partial change, persist it, and push to the sidecar. */
  update: (patch: Partial<EphymerisSettings>) => Promise<void>;
  /** Latest bundled-library scan, from sketches.updated or a refresh. */
  discovery: SketchDiscovery;
  /** Re-run discovery on demand (`tasks.md` §2.3). */
  refreshSketches: () => Promise<void>;
  loaded: boolean;
  saveError: string | null;
}

export const SettingsContext = createContext<SettingsContextValue | null>(null);

export function useSettings(): SettingsContextValue {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings must be used inside <SettingsProvider>");
  return ctx;
}

/**
 * Box numbers bound to a board — the single definition of "this box is real".
 *
 * Decides which boxes get a console panel, which get a constellation node, and
 * what the dashboard tile counts. Kept in one place because it was previously
 * three: the tile's count drifted out of sync the moment boxes became
 * user-managed.
 *
 * "Bound" means *configured with a board*, not *currently detected* — an
 * unplugged box still counts, since it still has a panel and a node.
 */
export function useBoundBoxes(): number[] {
  const { settings } = useSettings();
  return useMemo(
    () => settings.boxes.filter((b) => b.hardwareId !== null).map((b) => b.box),
    [settings.boxes],
  );
}

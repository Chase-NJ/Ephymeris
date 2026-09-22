import { useCallback, useMemo } from "react";

import {
  normalizeRecordingDefaults,
  type RecordingDefaults,
} from "@/lib/intan/defaults";

import { useSettings } from "./context";

/**
 * The recording defaults, read and written through one door.
 *
 * Both the Recording tab's Defaults tile and the Record step go through this
 * hook, so a default can enter or leave the store in exactly one place.
 * Normalizing again on read is idempotent and cheap, and it means no consumer
 * ever sees the loose `Record<string, unknown>` the wire carries.
 */
export function useRecordingDefaults(): {
  defaults: RecordingDefaults;
  save: (patch: Partial<RecordingDefaults>) => Promise<void>;
} {
  const { settings, update } = useSettings();
  const defaults = useMemo(
    () => normalizeRecordingDefaults(settings.recordingDefaults),
    [settings.recordingDefaults],
  );
  const save = useCallback(
    (patch: Partial<RecordingDefaults>) =>
      update({ recordingDefaults: { ...defaults, ...patch } }),
    [defaults, update],
  );
  return { defaults, save };
}

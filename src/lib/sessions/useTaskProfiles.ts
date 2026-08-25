import { useEffect, useMemo, useState } from "react";

import { getTaskProfile } from "./commands";
import type { TaskProfile } from "./types";
import { useSidecar } from "@/lib/ws/context";

/**
 * The separator joining the fetched paths into one effect-dependency string.
 *
 * NUL rather than a space: a sketch folder is named by the operator and
 * routinely contains spaces ("GRGL 4-Odor"), so a space would let two
 * different path sets collapse to the same key and skip a refetch. Spelled as
 * an escape rather than typed as a literal control character — an actual NUL
 * byte in the source makes git treat the whole file as binary, so it stops
 * producing diffs and grep skips it entirely.
 */
const PATH_SEP = "\u0000";

/**
 * The Task Profiles behind a set of sketch paths, fetched once each.
 *
 * KEYED BY SKETCH PATH, NOT BY BOX. A group usually runs one sketch across all
 * six boxes, so a per-box fetch would ask the sidecar the same question six
 * times for one answer; and the answer is a property of the sketch on disk, not
 * of the box carrying it.
 *
 * `null` is a real value here and means "this sketch has no profile", which is
 * fully supported (`tasks.md` §3) — bare `START`, raw strobe log, no charts.
 * `undefined` is the different thing: not fetched yet.
 */
export function useTaskProfiles(
  sketchPaths: string[],
): Record<string, TaskProfile | null | undefined> {
  const { client } = useSidecar();
  const [profiles, setProfiles] = useState<Record<string, TaskProfile | null>>({});

  // Sorted + deduped so a re-render that reorders the boxes doesn't refetch.
  const key = useMemo(() => [...new Set(sketchPaths)].sort().join(PATH_SEP), [sketchPaths]);

  useEffect(() => {
    const paths = key ? key.split(PATH_SEP) : [];
    let active = true;
    void Promise.all(
      paths.map((path) =>
        getTaskProfile(client, path)
          .then((profile) => [path, profile] as const)
          .catch(() => [path, null] as const),
      ),
    ).then((entries) => {
      if (active) setProfiles(Object.fromEntries(entries));
    });
    return () => {
      active = false;
    };
  }, [client, key]);

  return profiles;
}

/** One sketch's profile — the single-path spelling of `useTaskProfiles`. */
export function useTaskProfile(sketchPath: string): TaskProfile | null {
  const paths = useMemo(() => [sketchPath], [sketchPath]);
  return useTaskProfiles(paths)[sketchPath] ?? null;
}

/**
 * `liveMetrics` id → the operator's own title for it, for the readouts that
 * receive metric VALUES rather than the profile.
 *
 * A metric's `id` is a slot number (`p_correct_2`) — it exists so the sidecar's
 * telemetry and the profile can refer to the same metric across the wire, and
 * it says nothing about which condition it scores. The `label` is the sentence
 * built from the trial type's name, which is what an operator watching a box
 * needs to read.
 */
export function metricLabels(profile: TaskProfile | null | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const metric of profile?.liveMetrics ?? []) out[metric.id] = metric.label;
  return out;
}

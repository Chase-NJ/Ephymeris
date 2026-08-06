import { motion } from "framer-motion";
import { CircleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { ParameterInspector } from "@/components/task/ParameterInspector";
import {
  SketchExplainProvider,
  SketchExplainTile,
} from "@/components/task/SketchExplain";
import { SketchLibrary } from "@/components/task/SketchLibrary";
import { SketchStateMachine } from "@/components/task/SketchStateMachine";
import { errorMessage } from "@/lib/cohorts/commands";
import { PANEL_TRAVEL, springPanel } from "@/lib/motion";
import { getTaskProfile } from "@/lib/sessions/commands";
import { defaultConfig, sketchName, type TaskProfile } from "@/lib/sessions/types";
import { useSettings } from "@/lib/settings/context";
import { taskGraph, type TaskNode } from "@/lib/tasks/topology";
import { useSidecar } from "@/lib/ws/context";

/**
 * Task — the sketch viewer, in the Dashboard's HUD idiom (`dashboard.md` §3).
 *
 * The rig's sky is the page and everything floats over it in fixed columns:
 * the library and the explain tile on the left, the **state machine tile** as
 * the centrepiece, and the **parameter rail** docked right. Nothing scrolls
 * the page — the rail reaches every group by *selection* (pills, the
 * machine's chips, or a state click all land on the same group), so the
 * machine and the fields being tuned are always on screen together. That is
 * what the tile↔machine highlight was for, and the old long-scroll layout put
 * one end of it below the fold whenever the other was in use.
 *
 * The spec-creator surfaces that used to share this tab are removed pending a
 * fresh build; the sidecar spec system is untouched (`specs.md`).
 *
 * This is the pre-spec path and it is still the one that runs animals, and it
 * remains the only editor for `settings.taskDefaults` — the MIDDLE layer of
 * the three-layer merge (`tasks.md` §6.1). The mapping step reads that map on
 * every session, so a version of this app without this page would keep
 * applying saved overrides with nothing able to see or clear them.
 */
export function TaskSketches() {
  const { settings, update, discovery, refreshSketches, loaded } = useSettings();
  const { client, status } = useSidecar();
  const connected = status === "connected";

  const [sketchPath, setSketchPath] = useState<string | null>(null);
  const [profile, setProfile] = useState<TaskProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoverGroup, setHoverGroup] = useState<string | null>(null);
  const [hoverNode, setHoverNode] = useState<TaskNode | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);

  const name = sketchName(sketchPath);
  const saved = useMemo(() => settings.taskDefaults[name] ?? {}, [settings.taskDefaults, name]);
  // The layer underneath these defaults is the sketch author's own, so that is
  // what "changed" and "reset" are measured against.
  const authored = useMemo(() => defaultConfig(profile), [profile]);
  const current = useMemo(() => defaultConfig(profile, saved), [profile, saved]);
  const model = useMemo(() => taskGraph(profile), [profile]);

  /** Which sketches carry rig overrides — the library list's `tuned` chips. */
  const tuned = useMemo(
    () =>
      new Map(
        Object.entries(settings.taskDefaults).map(([sketch, overrides]) => [
          sketch,
          Object.keys(overrides).length,
        ]),
      ),
    [settings.taskDefaults],
  );

  /** Pills the hovered state lights — the machine→rail half of the link. */
  const litGroups = useMemo(
    () => new Set(hoverNode?.governedBy ?? []),
    [hoverNode],
  );

  /** A state click selects the first declared group that tunes it. */
  const declaredGroups = useMemo(() => {
    const declared = new Set<string>();
    for (const field of profile?.config ?? []) {
      if (field.group) declared.add(field.group);
    }
    return declared;
  }, [profile]);
  const selectGroupOf = useCallback(
    (node: TaskNode) => {
      const group = node.governedBy.find((g) => declaredGroups.has(g));
      if (group) setSelectedGroup(group);
    },
    [declaredGroups],
  );

  const load = useCallback(
    async (path: string | null) => {
      setProfile(null);
      setError(null);
      // A highlight belongs to what is under the cursor, and switching
      // sketches replaces all of it; the selected group resets to the new
      // profile's first (the inspector falls back on its own).
      setHoverGroup(null);
      setHoverNode(null);
      setSelectedGroup(null);
      if (!path) return;
      setLoading(true);
      try {
        setProfile(await getTaskProfile(client, path));
      } catch (err) {
        // A malformed task.json is surfaced, not swallowed: this page is where
        // someone would come to fix it.
        setError(errorMessage(err));
      } finally {
        setLoading(false);
      }
    },
    [client],
  );

  const choose = useCallback(
    (path: string) => {
      setSketchPath(path);
      window.localStorage.setItem(LAST_SKETCH_KEY, path);
      void load(path);
    },
    [load],
  );

  /*
   * A viewer opens showing something. With no selection, reopen the sketch
   * viewed last time (per machine — it is a property of the rig someone is
   * standing at), falling back to the first *behaviour* sketch — the library
   * also lists the bench interpreter and the utility sketch, and a viewer
   * whose whole point is the state machine must not open on "this sketch has
   * no task.json".
   */
  useEffect(() => {
    if (sketchPath !== null || !connected || discovery.sketches.length === 0) return;
    const remembered = window.localStorage.getItem(LAST_SKETCH_KEY);
    const entry =
      discovery.sketches.find((s) => s.path === remembered) ??
      discovery.sketches.find(
        (s) => !["BENCH", "UTILITY"].includes(s.category.toUpperCase()),
      ) ??
      discovery.sketches[0]!;
    setSketchPath(entry.path);
    void load(entry.path);
  }, [discovery.sketches, sketchPath, connected, load]);

  // A directory rescan can retire the chosen sketch out from under the page.
  useEffect(() => {
    if (sketchPath && !discovery.sketches.some((s) => s.path === sketchPath)) {
      setSketchPath(null);
      setProfile(null);
    }
  }, [discovery.sketches, sketchPath]);

  /** Store only what diverges from the profile — the middle merge layer. */
  function save(next: Record<string, unknown>) {
    const diverging = Object.fromEntries(
      Object.entries(next).filter(([key, value]) => !Object.is(value, authored[key])),
    );
    const rest = { ...settings.taskDefaults };
    if (Object.keys(diverging).length === 0) delete rest[name];
    else rest[name] = diverging;
    void update({ taskDefaults: rest });
  }

  const savedCount = Object.keys(saved).length;
  const hasParams = (profile?.config.length ?? 0) > 0;

  if (!loaded) return null;

  return (
    // No `overflow-hidden`: the shared canvas reaches under the sidebar
    // (`Scene.tsx`), exactly as on the Dashboard.
    <div className="relative h-full">
      <SkyBackdrop />

      <SketchExplainProvider key={sketchPath ?? ""}>
        {/* The pointer-events split is the Dashboard's: columns ignore the
            pointer so the sky between tiles still orbits; tiles take it back. */}
        <div className="pointer-events-none absolute inset-0">
          {/* Left: identity and the library. Title metrics match the
              Dashboard's command column, so the two pages read as one idiom. */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={springPanel}
            className="scrollbar-none pointer-events-none absolute inset-y-0 left-0 w-[300px] overflow-y-auto p-4 pl-8"
          >
            <h1 className="pb-4 pt-3 font-display text-[22px] text-starlight">Task</h1>
            <div className="pointer-events-auto flex flex-col gap-3">
              <SketchLibrary
                discovery={discovery}
                selected={sketchPath}
                tuned={tuned}
                onSelect={choose}
                onRefresh={() => void refreshSketches()}
                canRefresh={connected}
              />
              <SketchExplainTile
                profile={profile}
                model={model}
                authored={authored}
                hoverGroup={hoverGroup}
                sketchName={name}
              />
            </div>
          </motion.div>

          {/* Centre: the machine, vertically centred in what the columns
              leave. It is the page's hero the way the constellation is the
              Dashboard's — the columns are furniture around it. */}
          <div className="absolute inset-y-0 left-[300px] right-[384px] flex items-center px-4 xl:right-[416px]">
            {error ? (
              <div
                className="pointer-events-auto flex items-center gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
                style={{ color: "var(--color-status-error)" }}
              >
                <CircleAlert size={14} strokeWidth={1.75} />
                {error}
              </div>
            ) : !sketchPath ? (
              <p className="pointer-events-auto max-w-prose text-[13px] leading-relaxed text-static">
                {connected
                  ? "Choose a sketch from the library."
                  : "Waiting for the backend — the sketch library comes from it."}
              </p>
            ) : loading ? (
              <p className="pointer-events-auto text-[13px] text-static">
                Reading the task profile…
              </p>
            ) : (
              <motion.section
                key={`${sketchPath}-machine`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={springPanel}
                className="hud pointer-events-auto w-full rounded-md p-4"
              >
                <div className="mb-1 flex items-baseline justify-between gap-3">
                  <span className="text-[11px] text-static">
                    State machine
                    {profile && (
                      <span className="ml-2 text-static/70">{profile.taskName}</span>
                    )}
                  </span>
                  {model.usable && (
                    <span className="font-mono text-[10px] text-static/70">
                      {model.conditions.length} condition
                      {model.conditions.length === 1 ? "" : "s"} · derived from
                      its strobe vocabulary
                    </span>
                  )}
                </div>

                {model.usable ? (
                  <SketchStateMachine
                    model={model}
                    profile={profile}
                    hoverGroup={hoverGroup}
                    onHoverGroup={setHoverGroup}
                    onHoverNode={setHoverNode}
                    onNodeClick={selectGroupOf}
                    onSelectGroup={setSelectedGroup}
                  />
                ) : (
                  <p className="text-[12px] leading-relaxed text-static">
                    {profile
                      ? `${profile.taskName} declares no behavioural strobes, so there is no machine to draw. Utility sketches are driven from Debug Mode instead.`
                      : "This sketch has no task.json, so it runs a bare START and reports nothing the app can chart."}
                  </p>
                )}
              </motion.section>
            )}
          </div>

          {/* Right: the parameter rail. Travels in like the Dashboard's
              overview column — same distance, same spring. */}
          <motion.div
            initial={{ opacity: 0, x: PANEL_TRAVEL }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0 }}
            transition={springPanel}
            className="scrollbar-none pointer-events-none absolute inset-y-0 right-0 flex w-[384px] flex-col overflow-y-auto p-4 pl-0 xl:w-[416px]"
          >
            {sketchPath && !loading && !error && hasParams && (
              <div className="pointer-events-auto flex min-h-0 flex-col gap-2">
                <div className="flex items-baseline justify-between gap-3 px-1">
                  <h2 className="font-display text-[13px] font-medium tracking-wide text-static uppercase">
                    Parameters
                  </h2>
                  {savedCount > 0 && (
                    <button
                      type="button"
                      onClick={() => save({})}
                      className="text-[11px] text-static transition-colors hover:text-starlight"
                    >
                      Reset all {savedCount}
                    </button>
                  )}
                </div>
                <ParameterInspector
                  profile={profile}
                  model={model}
                  config={current}
                  baseline={authored}
                  selected={selectedGroup}
                  onSelect={setSelectedGroup}
                  onChange={save}
                  onHoverGroup={setHoverGroup}
                  litGroups={litGroups}
                />
              </div>
            )}
          </motion.div>
        </div>
      </SketchExplainProvider>
    </div>
  );
}

/** Per machine, not per store: which sketch is open is a property of the rig
 *  someone is standing at. */
const LAST_SKETCH_KEY = "ephymeris:lastSketch";

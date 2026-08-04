import { motion } from "framer-motion";
import { ArrowLeft, ChevronUp, CircleAlert, FileCode2 } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useNavigate } from "react-router";

import { Button } from "@/components/common/controls";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { SketchPicker } from "@/components/sessions/TaskConfigForm";
import { LibraryStatusNote } from "@/components/task/LibraryStatusNote";
import { ParameterTiles } from "@/components/task/ParameterTiles";
import { TaskGraph } from "@/components/task/TaskGraph";
import { TaskRail } from "@/components/task/TaskRail";
import { errorMessage } from "@/lib/cohorts/commands";
import { springPanel } from "@/lib/motion";
import { getTaskProfile } from "@/lib/sessions/commands";
import { defaultConfig, sketchName, type TaskProfile } from "@/lib/sessions/types";
import { useSettings } from "@/lib/settings/context";
import { nodesGovernedBy, taskGraph, type TaskNode } from "@/lib/tasks/topology";
import { useSidecar } from "@/lib/ws/context";

/**
 * Sketches — the firmware library, its trial flow, and this rig's parameters.
 *
 * This is the pre-spec path and it is still the one that runs animals. Every
 * behaviour sketch compiles its own `runTrial()`; a task spec is a SIBLING
 * artifact whose interpreter has never driven a pin. Until Phase 7
 * retires `runTrial()`, both are real, and this page owning the sketch half is
 * what lets the Designer own the other half without either pretending to be the
 * whole story.
 *
 * It is also the only editor for `settings.taskDefaults` — the MIDDLE layer of
 * the three-layer merge (`tasks.md` §6.1). The mapping step reads that map on
 * every session, so a version of this app without this page would keep applying
 * saved overrides with nothing able to see or clear them. That is the reason it
 * exists as its own route rather than being deleted with the rest of the old
 * Task page.
 *
 * The three parts build on each other. Choose a sketch; see the state machine it
 * will actually run, derived from its own declared strobe vocabulary
 * (`lib/tasks/topology.ts`); then set this rig's defaults for it, in tiles
 * ordered the way the parameters take effect during a trial. Hovering a tile
 * lights the states it governs; clicking a state scrolls to the tile that sets
 * it. The mapping step still overrides any of them per animal.
 *
 * That hover link is why the flow is drawn twice. The diagram is ~450px tall and
 * the tiles run well past one screen, so on the way to the tile you care about
 * the states it lights scroll off — the connection was invisible for every tile
 * but the first row. So a compact strip of the same nodes sits beneath the
 * diagram and pins itself to the top of the scroll region once the diagram
 * leaves, lit by the same set (`TaskRail`). It is a second rendering rather than
 * the card collapsing into itself deliberately: a sticky card that changed
 * height would pull several hundred pixels of tiles up under the operator's
 * cursor mid-scroll.
 */
export function TaskSketches() {
  const navigate = useNavigate();
  const { settings, update, discovery, refreshSketches, loaded } = useSettings();
  const { client, status } = useSidecar();
  const connected = status === "connected";

  const [sketchPath, setSketchPath] = useState<string | null>(null);
  const [profile, setProfile] = useState<TaskProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoverGroup, setHoverGroup] = useState<string | null>(null);

  const tiles = useRef(new Map<string, HTMLElement>());
  const registerTile = useCallback((group: string, el: HTMLElement | null) => {
    if (el) tiles.current.set(group, el);
    else tiles.current.delete(group);
  }, []);

  const graphCard = useRef<HTMLElement | null>(null);
  const sentinel = useRef<HTMLDivElement | null>(null);
  const rail = useRef<HTMLDivElement | null>(null);
  const [pinned, setPinned] = useState(false);
  const [railHeight, setRailHeight] = useState(0);

  const name = sketchName(sketchPath);
  const saved = useMemo(() => settings.taskDefaults[name] ?? {}, [settings.taskDefaults, name]);
  // The layer underneath these defaults is the sketch author's own, so that is
  // what "changed" is measured against and what Reset returns to.
  const authored = useMemo(() => defaultConfig(profile), [profile]);
  const current = useMemo(() => defaultConfig(profile, saved), [profile, saved]);
  const model = useMemo(() => taskGraph(profile), [profile]);

  /** Nodes the hovered tile's parameters govern. Empty = nothing dimmed. */
  const highlighted = useMemo(
    () => new Set(nodesGovernedBy(model, hoverGroup).map((n) => n.id)),
    [hoverGroup, model],
  );

  /** Scroll to the tile a clicked state's parameters live in. */
  const revealTile = useCallback((node: TaskNode) => {
    const group = node.governedBy.find((g) => tiles.current.has(g));
    if (!group) return;
    // "nearest" rather than "center": a tile already in view shouldn't jump,
    // and the tiles' own scroll-margin clears the pinned rail for one that is
    // scrolled to. Centring a tile taller than the viewport hides its header.
    tiles.current.get(group)!.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setHoverGroup(group);
  }, []);

  /*
   * Whether the rail is currently pinned to the top of the scroll region — it
   * has left its resting place under the diagram, so it owes the operator the
   * opaque background and the way back up.
   *
   * A sentinel above the rail rather than watching the rail itself: a sticky
   * element never stops intersecting its scroller, so it cannot report its own
   * stuck-ness. The root is `AppShell`'s `<main>`, which is the thing that
   * actually scrolls — the window never does.
   */
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => setPinned(!entry?.isIntersecting),
      { root: el.closest("main"), threshold: 0 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [sketchPath, loading, error, model]);

  /*
   * The rail's own height, published to the tiles as `--task-rail-h` so their
   * `scroll-margin-top` clears it exactly.
   *
   * Measured rather than a constant because the strip is content-sized: how tall
   * it gets depends on the deepest column (four outcomes here, five on a task
   * with a withhold arm) and on whether it wraps at this window width. A guessed
   * constant that comes out short doesn't look like a spacing problem — it
   * scrolls a tile's own heading underneath the thing that sent you to it.
   */
  useEffect(() => {
    const el = rail.current;
    if (!el) {
      setRailHeight(0);
      return;
    }
    const observer = new ResizeObserver(() => setRailHeight(el.offsetHeight));
    observer.observe(el);
    setRailHeight(el.offsetHeight);
    return () => observer.disconnect();
  }, [sketchPath, loading, error, model]);

  const load = useCallback(
    async (path: string | null) => {
      setProfile(null);
      setError(null);
      // A highlight belongs to the tile that is under the cursor, and switching
      // sketches replaces every tile — leaving it set dims the new graph on
      // arrival, against a group name nothing is pointing at any more.
      setHoverGroup(null);
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

  // A directory rescan can retire the chosen sketch out from under the page.
  useEffect(() => {
    if (sketchPath && !discovery.sketches.some((s) => s.path === sketchPath)) {
      setSketchPath(null);
      setProfile(null);
    }
  }, [discovery.sketches, sketchPath]);

  /** Store only what diverges from the profile — see the note under the tiles. */
  function save(next: Record<string, unknown>) {
    const diverging = Object.fromEntries(
      Object.entries(next).filter(([key, value]) => !Object.is(value, authored[key])),
    );
    const rest = { ...settings.taskDefaults };
    if (Object.keys(diverging).length === 0) delete rest[name];
    else rest[name] = diverging;
    void update({ taskDefaults: rest });
  }

  if (!loaded) return null;

  return (
    <div className="relative h-full">
      <SkyBackdrop />

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        <section className="pointer-events-auto mx-auto max-w-5xl px-8 py-8">
          <div className="flex items-center gap-3">
            <Button variant="ghost" onClick={() => navigate("/task")} title="Back to Task">
              <ArrowLeft size={13} strokeWidth={1.75} />
            </Button>
            <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
              <FileCode2 size={18} strokeWidth={1.75} className="text-pulsar" />
            </span>
            <h1 className="font-display text-[22px] text-starlight">Sketches</h1>
          </div>

          <section className="surface mt-6 rounded-md">
            <div className="border-b border-halo px-4 py-3.5">
              <div className="flex items-start justify-between gap-8">
                <div className="min-w-0 pt-0.5">
                  <div className="text-[13px] font-medium text-starlight">Sketch</div>
                  <p className="mt-0.5 text-[12px] leading-relaxed text-static">
                    Its task profile drives the flow below and the parameters this
                    rig runs it with.
                  </p>
                </div>
                <SketchPicker
                  label="Sketch to inspect"
                  sketches={discovery.sketches}
                  value={sketchPath}
                  onChange={(path) => {
                    setSketchPath(path);
                    void load(path);
                  }}
                  disabled={!connected}
                  className="w-[260px] shrink-0"
                />
              </div>
              <LibraryStatusNote
                discovery={discovery}
                onRefresh={() => void refreshSketches()}
                canRefresh={connected}
              />
            </div>
          </section>

          {error && (
            <div
              className="mt-4 flex items-center gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
              style={{ color: "var(--color-status-error)" }}
            >
              <CircleAlert size={14} strokeWidth={1.75} />
              {error}
            </div>
          )}

          {!sketchPath && !error && (
            <p className="mt-6 max-w-prose text-[13px] leading-relaxed text-static">
              Choose a sketch to see the trial it runs and the parameters it exposes.
            </p>
          )}

          {loading && (
            <p className="mt-6 text-[13px] text-static">Reading the task profile…</p>
          )}

          {sketchPath && !loading && !error && (
            <>
              <motion.section
                key={`${sketchPath}-graph`}
                ref={graphCard}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={springPanel}
                className="surface mt-4 rounded-md p-4"
              >
                <div className="mb-1 flex items-baseline justify-between gap-3">
                  <span className="text-[11px] text-static">
                    Trial flow
                    {profile && (
                      <span className="ml-2 text-static/70">{profile.taskName}</span>
                    )}
                  </span>
                  {model.usable && (
                    <span className="font-mono text-[10px] text-static/70">
                      {model.conditions.length} condition
                      {model.conditions.length === 1 ? "" : "s"}
                    </span>
                  )}
                </div>

                {model.usable ? (
                  <>
                    <TaskGraph
                      model={model}
                      highlighted={highlighted}
                      onNodeClick={revealTile}
                      className="max-h-[42vh]"
                    />
                    <p className="mt-2 text-[11px] leading-relaxed text-static/70">
                      Derived from this sketch&rsquo;s declared strobe vocabulary —
                      the branches it draws are the ones the firmware can actually
                      report. Left to right is the order the firmware strobes them.
                    </p>
                  </>
                ) : (
                  <p className="text-[12px] leading-relaxed text-static">
                    {profile
                      ? `${profile.taskName} declares no behavioural strobes, so there is no trial flow to draw. Utility sketches are driven from Debug Mode instead.`
                      : "This sketch has no task.json, so it runs a bare START and reports nothing the app can chart."}
                  </p>
                )}
              </motion.section>

              {/* One wrapper for the rail and the tiles: a sticky element can only
              travel inside its own containing block, so this is what lets the
              rail stay pinned for the whole length of the tiles. It also carries
              the measured rail height for their scroll-margin. */}
              <div style={{ "--task-rail-h": `${railHeight + 12}px` } as CSSProperties}>
                {model.usable && (
                  <>
                    {/* Watched, not drawn — see the observer above. */}
                    <div ref={sentinel} aria-hidden className="h-px" />
                    {/* Opaque at rest as well as pinned: the tiles scroll underneath
                    it, and fading a background in on pin left the strip briefly
                    see-through with tile text reading through the node names. */}
                    <div
                      ref={rail}
                      className={`surface sticky top-0 z-10 mt-3 rounded-md px-4 py-2.5 ${
                        pinned ? "shadow-[0_4px_12px_rgb(0_0_0/0.45)]" : ""
                      }`}
                    >
                      <div className="mb-1.5 flex items-baseline justify-between gap-3">
                        <span className="text-[10px] text-static">
                          {hoverGroup ? (
                            <>
                              <span className="text-starlight">{hoverGroup}</span> governs
                            </>
                          ) : (
                            "Hover a parameter group to light the states it governs"
                          )}
                        </span>
                        {pinned && (
                          <button
                            type="button"
                            onClick={() =>
                              graphCard.current?.scrollIntoView({
                                behavior: "smooth",
                                block: "start",
                              })
                            }
                            className="flex shrink-0 items-center gap-1 text-[10px] text-static transition-colors hover:text-starlight"
                          >
                            <ChevronUp size={11} strokeWidth={1.75} />
                            Diagram
                          </button>
                        )}
                      </div>
                      <TaskRail
                        model={model}
                        highlighted={highlighted}
                        onNodeClick={revealTile}
                      />
                    </div>
                  </>
                )}

                {profile && profile.config.length > 0 && (
                  <>
                    <div className="mt-6 mb-2 flex items-baseline justify-between gap-3 px-1">
                      <h2 className="font-display text-[13px] font-medium tracking-wide text-static uppercase">
                        Parameters
                      </h2>
                      {Object.keys(saved).length > 0 && (
                        <Button variant="ghost" onClick={() => save({})}>
                          Reset all {Object.keys(saved).length}
                        </Button>
                      )}
                    </div>
                    <ParameterTiles
                      profile={profile}
                      model={model}
                      config={current}
                      baseline={authored}
                      onChange={save}
                      onHoverGroup={setHoverGroup}
                      registerTile={registerTile}
                    />
                    <p className="mt-4 px-1 text-[11px] leading-relaxed text-static/70">
                      These are this rig&rsquo;s defaults. Only values that differ
                      from the sketch&rsquo;s own are stored, so editing{" "}
                      <code className="font-mono">task.json</code> later still moves
                      everything you haven&rsquo;t deliberately changed here — and
                      the mapping step can still override any of them for one animal.
                    </p>
                  </>
                )}
              </div>
            </>
          )}
        </section>
      </motion.div>
    </div>
  );
}

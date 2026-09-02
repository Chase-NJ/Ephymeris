import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, CircleAlert, Workflow } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { Button } from "@/components/common/controls";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { ParameterInspector } from "@/components/task/ParameterInspector";
import { StageRamp } from "@/components/task/StageRamp";
import { TaskDetails } from "@/components/task/TaskDetails";
import { TaskGlyph } from "@/components/task/TaskGlyph";
import { TaskGuide, type GuideStep } from "@/components/task/TaskGuide";
import { TrialTypeTable } from "@/components/task/TrialTypeTable";
import { SketchStateMachine } from "@/components/task/SketchStateMachine";
import { colorForIndex } from "@/lib/analytics/view";
import { errorMessage } from "@/lib/cohorts/commands";
import { getRig } from "@/lib/hardware/commands";
import type { RigDocument } from "@/lib/hardware/types";
import { CASCADE, PANEL_TRAVEL, RISE, springPanel } from "@/lib/motion";
import { getStrobes, idFromName, listTasks } from "@/lib/taskdef/commands";
import { blankTrial, isRampGroup, nextStage } from "@/lib/taskdef/types";
import type { TaskDefinition, TaskDiagnostic, TaskEntry } from "@/lib/taskdef/types";
import { useTask } from "@/lib/taskdef/useTask";
import { taskGraph, type TaskNode } from "@/lib/tasks/topology";
import { useSidecar } from "@/lib/ws/context";
import { EVT, type StrobeVocabulary } from "@/lib/ws/protocol";

/**
 * The task-profile editor — one task, open.
 *
 * It was `/task` itself until the library grew a landing of its own. What
 * changed here is the left rail: it used to be the profile list plus the five
 * presets a new task started from, and it is the SECTION SPINE now. Both halves
 * of that had to move. The list belongs on the landing because "what have I
 * got" is a different question from "what is this one"; the presets are gone
 * because a task is built from scratch, and the one thing a preset supplied
 * that nothing else could — `legacyNames` — is a field in `TaskDetails` now.
 *
 * The Dashboard's HUD layout survives, and so does its point: the machine and
 * the thing being edited stay on screen together, because the diagram is the
 * fastest check that an edit did what was meant. Three regions —
 *
 *   left    the way back, this task's mark, and its sections
 *   centre  details, the derived state machine, the trial table, the ramp
 *   right   the parameter rail
 *
 * — and the CENTRE column scrolls rather than the page, because there are four
 * editors in it and only the first is a hero.
 *
 * EVERY REDRAW COMES FROM `tasks.preview`. The state machine is derived from
 * the profile the current definition COMPILES TO, not from a saved file, so an
 * added trial type grows an arm before the save. That round trip is also what
 * validates: most of the eleven rules depend on the wiring, and the frontend
 * holds no copy of it.
 */
export function TaskEditor() {
  const navigate = useNavigate();
  const { taskId } = useParams();
  const [search] = useSearchParams();
  const { client, status } = useSidecar();
  const connected = status === "connected";

  const [tasks, setTasks] = useState<TaskEntry[]>([]);
  const [tasksLoaded, setTasksLoaded] = useState(false);
  const [rig, setRig] = useState<RigDocument | null>(null);
  const [vocabulary, setVocabulary] = useState<StrobeVocabulary | null>(null);
  const [hoverGroup, setHoverGroup] = useState<string | null>(null);
  const [hoverNode, setHoverNode] = useState<TaskNode | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  /** A brand-new task, built here rather than fetched.
   *
   *  Held in state and seeded ONCE: `useTask` treats a change of `seed` object
   *  as a fresh open and would throw away every edit made since the last render
   *  if this were rebuilt inline. One trial row and one stage row, because a
   *  table with no rows has no Add button worth pointing at and an empty ramp
   *  is not "no ramp" — it is a task with no holds, which the firmware cannot
   *  express. */
  const [seed] = useState<TaskDefinition | null>(() =>
    taskId === undefined ? freshTask() : null,
  );

  const session = useTask(taskId ?? null, seed);
  const { definition, setDefinition } = session;

  useEffect(() => {
    if (!connected) return;
    void listTasks(client)
      .then((r) => setTasks(r.tasks))
      .catch((err) => setListError(errorMessage(err)))
      .finally(() => setTasksLoaded(true));
    // The wiring and the vocabulary are what the trial table's dropdowns offer.
    // Fetched here rather than per-row so a rig with twelve odor lines costs one
    // round trip, and so the two can never disagree within one render.
    void getRig(client).then((r) => setRig(r.document as RigDocument));
    void getStrobes(client).then(setVocabulary);
  }, [client, connected]);

  // A rewiring changes what the dropdowns may offer, and can break a task that
  // never saw it.
  useEffect(
    () =>
      client.on(EVT.HARDWARE_UPDATED, () => {
        void getRig(client).then((r) => setRig(r.document as RigDocument));
      }),
    [client],
  );

  /* An UNSAVED task's id follows its name.
   *
   * The id is derived rather than asked for (`idFromName`) — it names a file
   * and never appears on screen. The seed has to carry some id to be a
   * definition at all, so it carries the placeholder's; without this every task
   * built from scratch would be saved as `new_task`, and the second one would
   * overwrite the first. Only while unsaved: an id is a filename, so renaming a
   * SAVED task must leave its document where it is. */
  useEffect(() => {
    if (taskId !== undefined || !definition) return;
    const want = idFromName(
      definition.name,
      tasks.map((t) => t.id),
    );
    if (want !== definition.id) setDefinition({ ...definition, id: want });
  }, [taskId, definition, tasks, setDefinition]);

  const model = useMemo(() => taskGraph(session.profile), [session.profile]);

  /* The rail's three inputs. `config` is what the profile compiles with today;
   * `catalogueDefaults` is what it would compile with if this profile pinned
   * nothing, so the difference between them is exactly what this task PINS —
   * which is what the Pulsar dots mark and what a reset drops. */
  const config = useMemo(() => {
    const out: Record<string, unknown> = {};
    for (const field of session.profile?.config ?? []) out[field.metadataKey] = field.default;
    return out;
  }, [session.profile]);

  /** Rail edits land in `params`, and only where they diverge. Storing a value
   *  merely equal to the catalogue's would freeze the field against a later
   *  correction to its range or default. */
  const onParams = useCallback(
    (next: Record<string, unknown>) => {
      if (!definition) return;
      const params: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(next)) {
        if (value === undefined) continue; // a reset
        if (Object.is(value, session.catalogueDefaults[key])) continue;
        params[key] = value;
      }
      setDefinition({ ...definition, params });
    },
    [definition, session.catalogueDefaults, setDefinition],
  );

  const litGroups = useMemo(() => new Set(hoverNode?.governedBy ?? []), [hoverNode]);

  /**
   * Trial types the state machine cannot see, said on the row that causes it.
   *
   * `conditionsOf` filters a profile's odor codes through `liveMetrics`, and the
   * generator's `_live_metrics` silently `continue`s past a trial type with a
   * missing onset code or an unbound response channel. So a row can be typed,
   * saved, flashed — and never appear as a condition anywhere: not on the
   * diagram, not in the live metrics, not in Analytics.
   *
   * The fan used to catch this by accident (four rows typed, three arms drawn),
   * and collapsing it would have taken that away. This is the same finding made
   * deliberately: located on the row, in words, and impossible to read past.
   * Derived here rather than in the sidecar because it is a statement about the
   * definition on screen against the profile it just compiled to — both of
   * which this page is holding.
   */
  const unscoredTrials = useMemo<TaskDiagnostic[]>(() => {
    if (!definition || !session.profile) return [];
    const scored = new Set<string>();
    const nameOf = new Map(
      Object.entries(session.profile.strobes).map(([code, name]) => [
        Number(code),
        String(name).toUpperCase(),
      ]),
    );
    for (const metric of session.profile.liveMetrics) {
      const name = nameOf.get(metric.triggerCode);
      if (name) scored.add(name);
    }
    if (scored.size === 0) return [];
    return definition.trials.flatMap((trial, index) =>
      trial.onsetStrobe && !scored.has(trial.onsetStrobe.toUpperCase())
        ? [
            {
              location: `trials[${index}].onsetStrobe`,
              message:
                "no live metric scores this onset code, so the state machine " +
                "cannot see this trial type — it will not appear as a condition " +
                "on the diagram, in the live metrics, or in Analytics.",
              code: "TSK112",
            },
          ]
        : [],
    );
  }, [definition, session.profile]);

  /* Saving a NEW task moves it to its own address. `replace`, so Back from the
   * saved task returns to the landing rather than to the empty form that no
   * longer exists — and only once, since after the swap `taskId` is set and
   * `useTask` is loading the saved document. */
  const save = useCallback(async () => {
    if (!definition) return;
    const ok = await session.save();
    if (ok && taskId === undefined) {
      navigate(`/task/${definition.id}`, { replace: true });
    }
  }, [definition, navigate, session, taskId]);

  // --- the guide ---------------------------------------------------------- #

  const nameRef = useRef<HTMLDivElement>(null);
  const trialsRef = useRef<HTMLDivElement>(null);
  const rampRef = useRef<HTMLDivElement>(null);
  const paramsRef = useRef<HTMLDivElement>(null);
  const detailsRef = useRef<HTMLDivElement>(null);

  /* Shown unasked exactly once: on a rig with no tasks, opening a new one. The
   * `?guide=1` escape hatch is the landing's Walkthrough door, which is the only
   * way back in after a dismissal — and it ignores both conditions, because
   * somebody asking for it has answered the question the conditions ask. */
  const forced = search.get("guide") === "1";
  const [guiding, setGuiding] = useState(forced);
  useEffect(() => {
    if (forced || taskId !== undefined || !tasksLoaded) return;
    if (tasks.length > 0) return;
    if (window.localStorage.getItem(GUIDE_SEEN_KEY) === "1") return;
    setGuiding(true);
  }, [forced, taskId, tasksLoaded, tasks.length]);

  const dismissGuide = useCallback(() => {
    window.localStorage.setItem(GUIDE_SEEN_KEY, "1");
    setGuiding(false);
  }, []);

  const steps = useMemo<GuideStep[]>(
    () => guideSteps({ definition, saved: taskId !== undefined || !session.dirty, refs: {
      nameRef, trialsRef, rampRef, paramsRef,
    } }),
    [definition, taskId, session.dirty],
  );

  const categories = useMemo(
    () => [...new Set(tasks.map((t) => t.category))].sort((a, b) => a.localeCompare(b)),
    [tasks],
  );

  const errorCount = session.diagnostics.length;

  return (
    // No `overflow-hidden`: the shared canvas reaches under the sidebar
    // (`Scene.tsx`), exactly as on the Dashboard.
    <div className="relative h-full">
      <SkyBackdrop />

      <div className="pointer-events-none absolute inset-0">
        {/* Left: the way back, this task's mark, and its sections. */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={springPanel}
          className="scrollbar-none pointer-events-none absolute inset-y-0 left-0 w-[300px] overflow-y-auto p-4 pl-8"
        >
          <div className="pointer-events-auto flex flex-col gap-3 pt-1">
            <Button variant="ghost" onClick={() => navigate("/task")}>
              <ArrowLeft size={13} strokeWidth={1.75} />
              Task
            </Button>

            {definition && (
              <>
                <div className="flex items-center gap-3 px-1">
                  {/* The shared element from the landing's card: the mark the
                      eye picked out of the grid is still on screen after the
                      route changes, so the two pages read as one gesture. */}
                  <motion.span layoutId={`task-glyph-${definition.id}`} className="flex">
                    <TaskGlyph
                      size={44}
                      task={{
                        id: definition.id,
                        trials: definition.trials.length,
                        stages: definition.stages.length,
                        selectionMode: definition.selectionMode,
                        problems: errorCount,
                      }}
                    />
                  </motion.span>
                  <div className="min-w-0">
                    <div className="truncate font-display text-[15px] text-starlight">
                      {definition.name || "Untitled"}
                    </div>
                    <div className="truncate font-mono text-[10px] text-static/70">
                      {taskId === undefined ? "unsaved" : definition.category}
                    </div>
                  </div>
                </div>

                <SectionSpine
                  sections={[
                    { id: "details", label: "Details", ref: detailsRef },
                    {
                      id: "trials",
                      label: "Conditions",
                      ref: trialsRef,
                      count: definition.trials.length,
                      // One dot per condition in its own colour — the spine
                      // shows the same set the glyph above it draws and the
                      // trial table below numbers.
                      swatches: definition.trials.map((_, i) => colorForIndex(i)),
                    },
                    { id: "ramp", label: "Shaping ramp", ref: rampRef, count: definition.stages.length },
                    { id: "params", label: "Parameters", ref: paramsRef },
                  ]}
                  problems={errorCount}
                />
              </>
            )}

            {listError && <p className="px-1 text-[11px] text-status-error">{listError}</p>}
          </div>
        </motion.div>

        {/* Centre: the machine, then the editors. THIS column scrolls — the
            page still does not, which is what keeps the rails in place. */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={springPanel}
          className="scrollbar-none absolute inset-y-0 left-[300px] right-[384px] overflow-y-auto px-4 py-4 xl:right-[416px]"
        >
          {session.loadError ? (
            <div
              className="pointer-events-auto flex items-center gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
              style={{ color: "var(--color-status-error)" }}
            >
              <CircleAlert size={14} strokeWidth={1.75} />
              {session.loadError}
            </div>
          ) : !definition ? (
            // While the document is on its way in, show NOTHING. A prompt here
            // used to flash for a frame and then have the whole editor pop in
            // over it, which read as a broken render rather than a load.
            connected ? null : (
              <p className="pointer-events-auto max-w-prose pt-8 text-[13px] leading-relaxed text-static">
                Waiting for the backend — the task library comes from it.
              </p>
            )
          ) : (
            // The editor stack arrives as a CASCADE — each panel rising on the
            // panel spring a beat after the one above it — so a finished page
            // assembles top-down instead of slamming in as one frame.
            <motion.div
              variants={CASCADE}
              initial="hidden"
              animate="shown"
              className="pointer-events-auto flex flex-col gap-3"
            >
              <motion.div variants={RISE} ref={nameRef}>
                <Header session={session} onSave={() => void save()} />
              </motion.div>

              <motion.div variants={RISE} ref={detailsRef}>
                <TaskDetails
                  definition={definition}
                  categories={categories}
                  startOpen={taskId === undefined}
                  onChange={setDefinition}
                />
              </motion.div>

              <motion.section variants={RISE} className="hud rounded-md p-4">
                <div className="mb-2 flex items-center gap-3">
                  <Workflow size={18} strokeWidth={1.75} className="shrink-0 text-pulsar" />
                  <span className="min-w-0 flex-1 text-[12px] font-medium text-starlight">
                    State machine
                    <span className="ml-2 font-normal text-static/70">{definition.name}</span>
                  </span>
                  {model.usable && (
                    <span className="font-mono text-[10px] text-static/70">
                      {model.conditions.length} condition
                      {model.conditions.length === 1 ? "" : "s"} · derived from
                      what this task presents
                    </span>
                  )}
                </div>
                {model.usable ? (
                  <SketchStateMachine
                    model={model}
                    profile={session.profile}
                    hoverGroup={hoverGroup}
                    onHoverGroup={setHoverGroup}
                    onHoverNode={setHoverNode}
                    onNodeClick={() => undefined}
                    onSelectGroup={setSelectedGroup}
                  />
                ) : (
                  <p className="text-[12px] leading-relaxed text-static">
                    {session.profile === null
                      ? "Deriving the machine from what this task presents…"
                      : "Nothing to draw yet — a trial type with an odor, a response port and an onset code gives the machine its first arm."}
                  </p>
                )}
              </motion.section>

              <motion.div variants={RISE} ref={trialsRef}>
                <TrialTypeTable
                  trials={definition.trials}
                  mode={definition.selectionMode}
                  rig={rig}
                  vocabulary={vocabulary}
                  diagnostics={[...session.diagnostics, ...unscoredTrials]}
                  onChange={(trials) => setDefinition({ ...definition, trials })}
                  onModeChange={(selectionMode) =>
                    setDefinition({ ...definition, selectionMode })
                  }
                />
              </motion.div>

              <motion.div variants={RISE} ref={rampRef}>
                <StageRamp
                  stages={definition.stages}
                  diagnostics={session.diagnostics}
                  onChange={(stages) => setDefinition({ ...definition, stages })}
                />
              </motion.div>
            </motion.div>
          )}
        </motion.div>

        {/* Right: the parameter rail. */}
        <motion.div
          initial={{ opacity: 0, x: PANEL_TRAVEL }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0 }}
          transition={springPanel}
          className="scrollbar-none pointer-events-none absolute inset-y-0 right-0 flex w-[384px] flex-col overflow-y-auto p-4 pl-0 xl:w-[416px]"
        >
          <AnimatePresence>
            {definition && session.profile && (
              // The rail's content needs the COMPILED profile, which lands one
              // preview round trip after the definition — so it mounts a beat
              // after the centre column. Animated for that reason: without an
              // entrance of its own, this is the last tile to pop in.
              <motion.div
                ref={paramsRef}
                initial={{ opacity: 0, x: 12 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                transition={springPanel}
                className="pointer-events-auto flex min-h-0 flex-col gap-2"
              >
                <div className="flex items-baseline justify-between gap-3 px-1">
                  <h2 className="font-display text-[13px] font-medium uppercase tracking-wide text-static">
                    Parameters
                  </h2>
                  {errorCount > 0 && (
                    <span className="font-mono text-[10px] text-status-error">
                      {errorCount} problem{errorCount === 1 ? "" : "s"}
                    </span>
                  )}
                </div>
                <ParameterInspector
                  profile={session.profile}
                  model={model}
                  config={config}
                  baseline={session.catalogueDefaults}
                  selected={selectedGroup}
                  // The four ramped holds are the StageRamp's, and a ramp only
                  // reads as a table. Offering them here too would be a second
                  // surface for one field.
                  exclude={isRampGroup}
                  onSelect={setSelectedGroup}
                  onChange={onParams}
                  onHoverGroup={setHoverGroup}
                  litGroups={litGroups}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      </div>

      {guiding && definition && <TaskGuide steps={steps} onClose={dismissGuide} />}
    </div>
  );
}

/**
 * A task with nothing decided yet.
 *
 * Built in the frontend rather than fetched, because there is nothing to fetch:
 * every value here is either empty or the shape the firmware needs at minimum.
 * `params` is empty on purpose — a definition stores only what DIVERGES from
 * the field catalogue, so a new task pins nothing and inherits every default,
 * corrections included.
 */
function freshTask(): TaskDefinition {
  return {
    id: idFromName("New task", []),
    name: "New task",
    category: "Tasks",
    selectionMode: "antibias",
    trials: [blankTrial()],
    stages: [nextStage(undefined)],
    params: {},
    legacyNames: [],
    notes: "",
  };
}

/**
 * The steps, and what makes each one done.
 *
 * A step's `done` is a statement about the DOCUMENT, never about whether the
 * operator clicked through — which is what lets the coach be ignored and still
 * be right: doing the work in a different order ticks the steps behind you.
 */
function guideSteps({
  definition,
  saved,
  refs,
}: {
  definition: TaskDefinition | null;
  saved: boolean;
  refs: {
    nameRef: React.RefObject<HTMLDivElement | null>;
    trialsRef: React.RefObject<HTMLDivElement | null>;
    rampRef: React.RefObject<HTMLDivElement | null>;
    paramsRef: React.RefObject<HTMLDivElement | null>;
  };
}): GuideStep[] {
  const named =
    definition !== null &&
    definition.name.trim().length > 0 &&
    definition.name.trim() !== "New task";

  /** A row that will actually present something. The same conditions
   *  `_live_metrics` applies before it will score a type — a row missing any of
   *  them compiles and then never appears as a condition anywhere. */
  const usableRows =
    definition?.trials.filter(
      (t) =>
        t.odorChannel &&
        t.onsetStrobe &&
        t.label.trim() &&
        (!t.isGo || (t.responseChannel && t.rewardChannel)),
    ).length ?? 0;

  return [
    {
      id: "name",
      title: "Name the task",
      body: "This becomes the sketch folder and the name every recorded session stores — so it wants to say what the animal does, not which cohort runs it.",
      target: refs.nameRef,
      done: named,
    },
    {
      id: "trials",
      title: "Add a condition for each stimulus",
      body: "One row per odor you present: which line carries it, which port answers it, which reward line pays, and what you call it. The name is the only one you cannot derive — every chart downstream is titled from it.",
      target: refs.trialsRef,
      done: usableRows > 0,
    },
    {
      id: "mode",
      title: "Choose how the next trial is drawn",
      body: "Anti-bias picks a side against the animal's recent bias and then a type from that side. Pool draws from a weighted, block-shuffled bag — pick it if you want the proportions fixed, and a weight column appears on every row.",
      target: refs.trialsRef,
      done: usableRows > 0,
      optional: true,
    },
    {
      id: "ramp",
      title: "Ease it in, if the animal needs it",
      body: "Most tasks start with one row and stay there. Add stages only to shorten the holds early and grow them as the animal settles — each row takes over at its trial count.",
      target: refs.rampRef,
      done: (definition?.stages.length ?? 0) > 1,
      optional: true,
    },
    {
      id: "params",
      title: "Set the numbers",
      body: "Session holds the trial count, the correction budget and the reward volume for each fluid line. The rest are grouped by when they take effect during a trial — hover a state on the diagram and the groups that tune it light up.",
      target: refs.paramsRef,
      done: true,
      optional: true,
    },
    {
      id: "save",
      title: "Check the problems, then save",
      body: "A task saves with problems outstanding — the gate is flashing, not saving. But the three worth reading first are a reward line serving the other well, two conditions sharing an onset code, and an all-zero pool: each of those runs and produces wrong data rather than an error.",
      target: refs.nameRef,
      done: saved,
    },
  ];
}

/**
 * The section spine — where the centre column's four editors are.
 *
 * A scroll target list rather than tabs: all four are one document and one
 * scroll, and hiding three of them behind tabs would make "does this ramp match
 * that trial table" a navigation problem. The counts are the useful part —
 * "Conditions 4" answers at a glance what scrolling answers slowly.
 */
function SectionSpine({
  sections,
  problems,
}: {
  sections: Array<{
    id: string;
    label: string;
    ref: React.RefObject<HTMLElement | null>;
    count?: number;
    /** One colour per item in the section — the conditions' series slots. */
    swatches?: string[];
  }>;
  problems: number;
}) {
  return (
    <nav className="hud flex flex-col rounded-md py-1">
      {sections.map((section) => (
        <button
          key={section.id}
          type="button"
          onClick={() =>
            section.ref.current?.scrollIntoView({ behavior: "smooth", block: "start" })
          }
          className="flex items-center gap-2 px-3.5 py-1.5 text-left text-[12px] text-static transition-colors hover:text-starlight"
        >
          <span className="min-w-0 flex-1 truncate">{section.label}</span>
          {section.swatches && section.swatches.length > 0 && (
            <span className="flex shrink-0 items-center gap-0.5" aria-hidden>
              {section.swatches.slice(0, 8).map((colour, i) => (
                <span
                  key={i}
                  className="size-1.5 rounded-full"
                  style={{ background: colour }}
                />
              ))}
            </span>
          )}
          {section.count !== undefined && (
            <span className="shrink-0 font-mono text-[10px] text-static/60">
              {section.count}
            </span>
          )}
        </button>
      ))}
      {problems > 0 && (
        <div className="mt-1 border-t border-halo px-3.5 pb-1 pt-1.5 font-mono text-[10px] text-status-error">
          {problems} problem{problems === 1 ? "" : "s"} — it will still flash
        </div>
      )}
    </nav>
  );
}

/**
 * Name, save state, and the `START` line meter.
 *
 * THE METER IS NOT DECORATION. `START_LINE_MAX` is the one budget an operator
 * can exhaust without noticing: the firmware truncates an overlong line in
 * silence and runs the session on whichever values happened to fit. Adding a
 * stage costs five tokens, so the number is worth watching while the ramp
 * grows rather than being explained afterward.
 *
 * There is no delete here any more. It was a trash icon reachable only from
 * inside the thing being deleted, and only while it had no unsaved edits;
 * deleting is a library gesture and lives on the landing's cards.
 */
function Header({
  session,
  onSave,
}: {
  session: ReturnType<typeof useTask>;
  onSave: () => void;
}) {
  const { definition, setDefinition, startLine } = session;
  if (!definition) return null;
  const used = startLine ? startLine.length / startLine.max : 0;

  return (
    <div className="hud flex items-center gap-3 rounded-md px-3.5 py-2.5">
      <input
        value={definition.name}
        onChange={(e) => setDefinition({ ...definition, name: e.target.value })}
        aria-label="Task name"
        className="min-w-0 flex-1 rounded-sm border border-transparent bg-transparent px-1.5 py-0.5 font-display text-[15px] text-starlight transition-colors hover:border-halo focus:border-pulsar focus:outline-none"
      />

      {startLine && (
        <span
          title={`The START line is ${startLine.length} of ${startLine.max} bytes. Over the cap, the firmware truncates it without saying so.`}
          className="flex shrink-0 items-center gap-1.5 font-mono text-[10px] text-static/70"
        >
          <span className="h-1 w-16 overflow-hidden rounded-full bg-nebula">
            <span
              className="block h-full rounded-full"
              style={{
                width: `${Math.min(100, used * 100)}%`,
                background:
                  used > 0.9 ? "var(--color-status-error)" : "var(--color-pulsar)",
              }}
            />
          </span>
          {startLine.length}/{startLine.max}
        </span>
      )}

      {session.checking && (
        <span className="shrink-0 text-[10px] text-static/60">checking…</span>
      )}

      {session.dirty && (
        <>
          {session.baseline && (
            <button
              type="button"
              onClick={session.revert}
              className="shrink-0 text-[11px] text-static transition-colors hover:text-starlight"
            >
              Revert
            </button>
          )}
          {/* The page's ONE primary control — matte Pulsar fill, per the
              Button primary variant. Everything else on the header is quiet,
              which is what lets "there are unsaved edits" read at a glance. */}
          <button
            type="button"
            onClick={onSave}
            disabled={session.saving}
            className="shrink-0 rounded-sm bg-pulsar px-3 py-1 text-[11px] font-medium text-void transition-[filter] hover:brightness-108 disabled:opacity-50"
          >
            {session.saving ? "Saving…" : "Save"}
          </button>
        </>
      )}

      {session.actionError && (
        <span className="shrink-0 text-[11px] text-status-error">
          {session.actionError}
        </span>
      )}
    </div>
  );
}

/** Per machine, not per store: whether someone has been walked through this
 *  rig's task editor is a fact about the person at the bench. */
const GUIDE_SEEN_KEY = "ephymeris:taskGuideSeen";

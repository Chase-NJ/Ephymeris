import { LayoutGroup, motion } from "framer-motion";
import { CircleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router";

import { DENSE_SKY_OPACITY, SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { SketchStateMachine } from "@/components/task/SketchStateMachine";
import { EditorHeader, homeOf, type EditorShared } from "@/components/task/editor/EditorHeader";
import { GenerationPanel } from "@/components/task/editor/GenerationPanel";
import { Panel } from "@/components/task/editor/Panel";
import { SeedChooser } from "@/components/task/spine/SeedChooser";
import { SpineEditor } from "@/components/task/spine/SpineEditor";
import { ParameterOrrery } from "@/components/task/editor/ParameterOrrery";
import { TrialTypes } from "@/components/task/editor/TrialTypes";
import { errorMessage } from "@/lib/cohorts/commands";
import { getRig } from "@/lib/hardware/commands";
import type { RigDocument } from "@/lib/hardware/types";
import { CASCADE, RISE, springPanel } from "@/lib/motion";
import { useStrobeVocabulary } from "@/lib/strobes/useStrobeVocabulary";
import { idFromName, listTasks } from "@/lib/taskdef/commands";
import { isRowOwnedField } from "@/lib/taskdef/lines";
import { isSpine } from "@/lib/taskdef/spine";
import type { TaskDefinition, TaskDiagnostic, TaskDocument, TaskEntry } from "@/lib/taskdef/types";
import { useTask } from "@/lib/taskdef/useTask";
import { editorLayout } from "@/lib/tasks/editorLayout";
import {
  GENERATION_TAB,
  HOLDS_TAB,
  ROWS_TAB,
  dialTabs,
  tabOf,
  taskGraph,
  type TaskNode,
} from "@/lib/tasks/topology";
import { useElementWidth } from "@/lib/useElementWidth";
import { useSidecar } from "@/lib/ws/context";
import { EVT } from "@/lib/ws/protocol";

/** How long a row or panel a jump landed on stays marked. */
const MARK_MS = 2400;

/**
 * The task editor — one task, open.
 *
 * The route loads, saves and names the document, and hands it to the body for
 * its kind: a phase-spine task to `SpineEditor` (`TASKS.md#the-spine-editor`),
 * a trial-table task to `TrialTableEditor` (`TASKS.md#editor`). `/task/new`
 * with nothing handed over is the seed chooser: a new task starts from a seed
 * spine, and a trial-table task is only ever opened, or duplicated.
 *
 * The trial-table body is a telemetry display (`ARCHITECTURE.md#telemetry-panels`) in one frame: the
 * derived state machine front and centre with every trial type beneath it,
 * and beside them the parameter dial and the trial-generation panel. The
 * machine has a floor and the page bends around it (`editorLayout`): when the
 * aside would squeeze it, the aside's panels move under the trial types and
 * the page scrolls.
 *
 * ONE LINK, READ FROM EVERY END. A planet, the generation panel or a machine
 * chip lights the states it tunes; a state lights its planet; a trial row or a
 * composition segment lights its condition's tick. The drawing is the fastest
 * check that an edit did what was meant, so it is never off screen.
 *
 * EVERY REDRAW COMES FROM `tasks.preview`. The machine is derived from the
 * profile the current definition COMPILES TO, so an added trial type grows an
 * arm before the save — and that round trip is also what validates, because
 * most rules depend on the wiring and the frontend holds no copy of it.
 */
export function TaskEditor() {
  const navigate = useNavigate();
  const { taskId } = useParams();
  const { client, status } = useSidecar();
  const connected = status === "connected";

  const [tasks, setTasks] = useState<TaskEntry[]>([]);
  const [rig, setRig] = useState<RigDocument | null>(null);
  const [problemsOpen, setProblemsOpen] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  /** A brand-new task: a seed spine picked here (`SeedChooser`), or a
   *  DUPLICATE handed over in router state by the landing. Seeded ONCE:
   *  `useTask` treats a new seed object as a fresh open and would discard every
   *  edit since. Null on `/task/new` until a seed is picked. */
  const location = useLocation();
  const [seed, setSeed] = useState<TaskDocument | null>(() =>
    taskId === undefined ? seedFrom(location.state) : null,
  );
  // Opened once on a new task: its category decides where the sketch folder
  // is written.
  const [detailsOpen, setDetailsOpen] = useState(taskId === undefined);

  const session = useTask(taskId ?? null, seed);
  const { definition, setDefinition } = session;

  useEffect(() => {
    if (!connected) return;
    void listTasks(client)
      .then((r) => setTasks(r.tasks))
      .catch((err) => setListError(errorMessage(err)));
    // The wiring is what the trial-table pickers offer and where each line's
    // onset code is declared. A spine's pickers come from its preview.
    void getRig(client).then((r) => setRig(r.document as RigDocument));
  }, [client, connected]);

  // A rewiring changes what the pickers offer, and can break a task that never
  // saw it.
  useEffect(
    () =>
      client.on(EVT.HARDWARE_UPDATED, () => {
        void getRig(client).then((r) => setRig(r.document as RigDocument));
      }),
    [client],
  );

  /* An UNSAVED task's id follows its name (`idFromName`); a saved task's id is
   * a filename and stays put when it is renamed. */
  useEffect(() => {
    if (taskId !== undefined || !definition) return;
    const want = idFromName(
      definition.name,
      tasks.map((t) => t.id),
    );
    if (want !== definition.id) setDefinition({ ...definition, id: want });
  }, [taskId, definition, tasks, setDefinition]);

  /* Saving a NEW task moves it to its own address, with `replace` so Back
   * returns to the landing rather than to a form that no longer exists. */
  const save = useCallback(async () => {
    if (!definition) return;
    const ok = await session.save();
    if (ok && taskId === undefined) navigate(`/task/${definition.id}`, { replace: true });
  }, [definition, navigate, session, taskId]);

  const categories = useMemo(
    () => [...new Set(tasks.map((t) => t.category))].sort((a, b) => a.localeCompare(b)),
    [tasks],
  );

  const shared: EditorShared = {
    session,
    saved: taskId !== undefined,
    categories,
    detailsOpen,
    onDetailsOpen: setDetailsOpen,
    problemsOpen,
    onProblemsOpen: setProblemsOpen,
    onBack: () => navigate("/task"),
    onSave: () => void save(),
    listError,
  };

  let body;
  if (taskId === undefined && seed === null) {
    body = <SeedChooser onPick={setSeed} onBack={() => navigate("/task")} />;
  } else if (session.loadError || !definition) {
    body = (
      <Frame scrolls>
        {session.loadError ? (
          <div
            className="flex items-center gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
            style={{ color: "var(--color-status-error)" }}
          >
            <CircleAlert size={14} strokeWidth={1.75} />
            {session.loadError}
          </div>
        ) : // While the document is on its way in, show NOTHING — a prompt here
        // flashed for a frame before the editor popped in over it.
        connected ? null : (
          <p className="max-w-prose pt-8 text-[13px] leading-relaxed text-static">
            Waiting for the backend — the task library comes from it.
          </p>
        )}
      </Frame>
    );
  } else if (isSpine(definition)) {
    body = <SpineEditor shared={shared} definition={definition} />;
  } else {
    body = <TrialTableEditor shared={shared} definition={definition} rig={rig} />;
  }

  return (
    // Every route sits on the rig's sky, dimmed here as on Analytics: this is
    // a display surface, and the sky must not compete with the drawing.
    <div className="relative h-full">
      <SkyBackdrop opacity={DENSE_SKY_OPACITY} />
      {body}
    </div>
  );
}

/**
 * A trial-table task, open: the derived state machine front and centre with
 * every trial type beneath it, and beside them the parameter dial and the
 * trial-generation panel (`TASKS.md#editor`).
 */
function TrialTableEditor({
  shared,
  definition,
  rig,
}: {
  shared: EditorShared;
  definition: TaskDefinition;
  rig: RigDocument | null;
}) {
  const { session } = shared;
  const { setDefinition } = session;
  // Kept current across edits on the Strobes page.
  const { vocabulary } = useStrobeVocabulary();
  const [hoverGroup, setHoverGroup] = useState<string | null>(null);
  const [hoverNode, setHoverNode] = useState<TaskNode | null>(null);
  const [hoverCondition, setHoverCondition] = useState<string | null>(null);
  const [selectedTab, setSelectedTab] = useState<string | null>(null);
  const [flashGeneration, setFlashGeneration] = useState(false);
  const [markedRow, setMarkedRow] = useState<number | null>(null);

  const model = useMemo(() => taskGraph(session.profile), [session.profile]);

  /* `config` is what the profile compiles with today; `catalogueDefaults` is
   * what it would compile with if this task pinned nothing — the difference is
   * exactly what this task PINS. */
  const config = useMemo(() => {
    const out: Record<string, unknown> = {};
    for (const field of session.profile?.config ?? []) out[field.metadataKey] = field.default;
    return out;
  }, [session.profile]);

  /** Parameter edits land in `params`, and only where they diverge — and never
   *  a row-owned field, which the generator reads off the row and would ignore
   *  in `params` (`lib/taskdef/lines.ts`). */
  const onParams = useCallback(
    (next: Record<string, unknown>) => {
      if (!definition) return;
      const params: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(next)) {
        if (value === undefined) continue; // a reset
        if (isRowOwnedField(key)) continue;
        if (Object.is(value, session.catalogueDefaults[key])) continue;
        params[key] = value;
      }
      setDefinition({ ...definition, params });
    },
    [definition, session.catalogueDefaults, setDefinition],
  );

  const litGroups = useMemo(() => new Set(hoverNode?.governedBy ?? []), [hoverNode]);

  /**
   * Trial types the state machine cannot see (TSK112), said on the row.
   *
   * The generator's `_live_metrics` silently skips a trial type with a missing
   * onset code or an unbound response channel, so a row can be typed, saved,
   * flashed — and never appear as a condition anywhere. Derived here because it
   * is a statement about the definition on screen against the profile it just
   * compiled to, both of which this page is holding.
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
              target: { kind: "row" as const, index },
            },
          ]
        : [],
    );
  }, [definition, session.profile]);

  const diagnostics = useMemo(
    () => [...session.diagnostics, ...unscoredTrials],
    [session.diagnostics, unscoredTrials],
  );

  const conditionOfRow = useCallback(
    (row: number) => {
      const onset = definition?.trials[row]?.onsetStrobe;
      return onset ? (model.conditions.find((c) => c.strobeName === onset)?.id ?? null) : null;
    },
    [definition, model],
  );

  // --- jumps: a chip, a state, a problem ---------------------------------- #

  const generationRef = useRef<HTMLDivElement>(null);
  const flashTimer = useRef<number | undefined>(undefined);
  const markTimer = useRef<number | undefined>(undefined);
  useEffect(
    () => () => {
      window.clearTimeout(flashTimer.current);
      window.clearTimeout(markTimer.current);
    },
    [],
  );

  const showGeneration = useCallback(() => {
    setFlashGeneration(true);
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlashGeneration(false), MARK_MS);
    generationRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, []);

  /** Open a tab wherever it lives: the dial, the generation panel or the rows. */
  const openTab = useCallback(
    (tab: string) => {
      if (tab === GENERATION_TAB) showGeneration();
      else if (tab !== ROWS_TAB) setSelectedTab(tab);
    },
    [showGeneration],
  );

  const onNodeClick = useCallback(
    (node: TaskNode) => {
      const declared = new Set((session.profile?.config ?? []).map((f) => f.group ?? ""));
      const dial = dialTabs(declared);
      const homes = node.governedBy.map(tabOf);
      const tab = homes.find((h) => dial.includes(h)) ?? homes.find((h) => h === GENERATION_TAB);
      if (tab) openTab(tab);
    },
    [openTab, session.profile],
  );

  const onJump = useCallback(
    (diagnostic: TaskDiagnostic) => {
      const home = homeOf(diagnostic);
      if (home.kind === "row") {
        setMarkedRow(home.row);
        window.clearTimeout(markTimer.current);
        markTimer.current = window.setTimeout(() => setMarkedRow(null), MARK_MS);
      } else if (home.kind === "holds") setSelectedTab(HOLDS_TAB);
      else if (home.kind === "generation") showGeneration();
    },
    [showGeneration],
  );

  // --- layout -------------------------------------------------------------- #

  const [pageRef, pageWidth] = useElementWidth<HTMLDivElement>();
  const layout = editorLayout(pageWidth);
  const split = layout.mode === "split";

  const generationLit =
    flashGeneration ||
    hoverGroup === GENERATION_TAB ||
    [...litGroups].some((g) => tabOf(g) === GENERATION_TAB);

  const machine = definition && (
    <Panel
      id="machine"
      name="State machine"
      note={
        model.usable
          ? `${model.conditions.length} condition${model.conditions.length === 1 ? "" : "s"} · derived from what this task presents`
          : "derived from what this task presents"
      }
      className="shrink-0"
    >
      {model.usable ? (
        <SketchStateMachine
          model={model}
          profile={session.profile}
          hoverGroup={hoverGroup}
          onHoverGroup={setHoverGroup}
          onHoverNode={setHoverNode}
          onNodeClick={onNodeClick}
          onSelectGroup={openTab}
          hoverCondition={hoverCondition}
          onHoverCondition={setHoverCondition}
          conditionRail={false}
        />
      ) : (
        <p className="py-6 text-[12px] leading-relaxed text-static">
          {session.profile === null
            ? "Deriving the machine from what this task presents…"
            : "Nothing to draw yet — a trial type with an odor line, a response port and a reward line gives the machine its first arm."}
        </p>
      )}
    </Panel>
  );

  const trials = definition && (
    <TrialTypes
      trials={definition.trials}
      mode={definition.selectionMode}
      rig={rig}
      vocabulary={vocabulary}
      diagnostics={diagnostics}
      conditionOfRow={conditionOfRow}
      litReward={hoverGroup === ROWS_TAB}
      activeRow={markedRow}
      onHoverRow={setHoverCondition}
      onChange={(next) => setDefinition({ ...definition, trials: next })}
    />
  );

  const params = definition && (
    <ParameterOrrery
      profile={session.profile}
      model={model}
      config={config}
      baseline={session.catalogueDefaults}
      mode={definition.selectionMode}
      stages={definition.stages}
      diagnostics={diagnostics}
      selected={selectedTab}
      litGroups={litGroups}
      onSelect={setSelectedTab}
      onParams={onParams}
      onStages={(stages) => setDefinition({ ...definition, stages })}
      onHoverGroup={setHoverGroup}
    />
  );

  const generation = definition && (
    <div ref={generationRef} className="flex min-h-0 flex-1 flex-col">
      <GenerationPanel
        profile={session.profile}
        config={config}
        baseline={session.catalogueDefaults}
        trials={definition.trials}
        mode={definition.selectionMode}
        rig={rig}
        diagnostics={diagnostics}
        lit={generationLit}
        onMode={(selectionMode) => setDefinition({ ...definition, selectionMode })}
        onParams={onParams}
        onHover={setHoverGroup}
        onHoverCondition={setHoverCondition}
        conditionOfRow={conditionOfRow}
      />
    </div>
  );

  return (
    <div ref={pageRef} className="absolute inset-0">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        // Owns its own exit (`AppShell`): nothing else will fade this route.
        exit={{ opacity: 0 }}
        transition={springPanel}
        className={`scrollbar-none absolute inset-0 flex flex-col gap-3 px-4 py-4 ${
          split ? "overflow-hidden" : "overflow-y-auto"
        }`}
      >
        {definition && (
          <>
            <EditorHeader
              session={session}
              saved={shared.saved}
              diagnostics={diagnostics}
              categories={shared.categories}
              detailsOpen={shared.detailsOpen}
              onDetailsOpen={shared.onDetailsOpen}
              problemsOpen={shared.problemsOpen}
              onProblemsOpen={shared.onProblemsOpen}
              onJump={onJump}
              onBack={shared.onBack}
              onSave={shared.onSave}
            />
            {shared.listError && <p className="text-[11px] text-status-error">{shared.listError}</p>}

            {/* The panels assemble as a CASCADE, and move between the split
                and stacked homes on their shared layout ids. */}
            <LayoutGroup>
              <motion.div
                variants={CASCADE}
                initial="hidden"
                animate="shown"
                className={split ? "flex min-h-0 flex-1 gap-3" : "flex flex-col gap-3"}
              >
                <motion.div
                  variants={RISE}
                  className={split ? "flex min-h-0 min-w-0 flex-1 flex-col gap-3" : "flex flex-col gap-3"}
                >
                  {machine}
                  <div className={split ? "flex min-h-0 flex-1 flex-col" : "flex min-h-[260px] flex-col"}>
                    {trials}
                  </div>
                </motion.div>
                <motion.div
                  variants={RISE}
                  className={
                    split
                      ? "flex min-h-0 shrink-0 flex-col gap-3"
                      : "grid grid-cols-2 items-stretch gap-3 pb-2"
                  }
                  style={split ? { width: layout.aside } : {}}
                >
                  {/* Generation gets the larger share: it is the core choice and
                      its panel carries more; the dial's fields scroll. */}
                  <div className={split ? "flex min-h-[240px] flex-1 basis-0 flex-col" : "flex min-h-[460px] flex-col"}>
                    {params}
                  </div>
                  <div className={split ? "flex min-h-0 flex-[1.3] basis-0 flex-col" : "flex min-h-[460px] flex-col"}>
                    {generation}
                  </div>
                </motion.div>
              </motion.div>
            </LayoutGroup>
          </>
        )}
      </motion.div>
    </div>
  );
}

/** A duplicated task handed over by the Task landing, if that is how we got here. */
function seedFrom(state: unknown): TaskDocument | null {
  if (typeof state !== "object" || state === null || !("seed" in state)) return null;
  const seed = (state as { seed: unknown }).seed;
  return typeof seed === "object" && seed !== null ? (seed as TaskDocument) : null;
}

/** The motion frame every editor state sits in. */
function Frame({ scrolls, children }: { scrolls: boolean; children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={springPanel}
      className={`scrollbar-none absolute inset-0 flex flex-col gap-3 px-4 py-4 ${scrolls ? "overflow-y-auto" : "overflow-hidden"}`}
    >
      {children}
    </motion.div>
  );
}

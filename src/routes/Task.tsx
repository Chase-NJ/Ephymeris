import { AnimatePresence, motion } from "framer-motion";
import { CircleAlert, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { ParameterInspector } from "@/components/task/ParameterInspector";
import { StageRamp } from "@/components/task/StageRamp";
import { LibraryStatusNote } from "@/components/task/LibraryStatusNote";
import { TaskLibrary } from "@/components/task/TaskLibrary";
import { TrialTypeTable } from "@/components/task/TrialTypeTable";
import { SketchStateMachine } from "@/components/task/SketchStateMachine";
import { errorMessage } from "@/lib/cohorts/commands";
import { getRig } from "@/lib/hardware/commands";
import type { RigDocument } from "@/lib/hardware/types";
import { CASCADE, PANEL_TRAVEL, RISE, springPanel } from "@/lib/motion";
import {
  deleteTask,
  getStrobes,
  idFromName,
  listPresets,
  listTasks,
  taskFromPreset,
} from "@/lib/taskdef/commands";
import { isRampGroup } from "@/lib/taskdef/types";
import type {
  TaskDefinition,
  TaskDiagnostic,
  TaskEntry,
  TaskPreset,
} from "@/lib/taskdef/types";
import { useTask } from "@/lib/taskdef/useTask";
import { taskGraph, type TaskNode } from "@/lib/tasks/topology";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import { EVT, type StrobeVocabulary } from "@/lib/ws/protocol";

/**
 * Task — the task-profile editor.
 *
 * It replaced the sketch VIEWER. The viewer could show what a sketch declared;
 * this decides it. What changed underneath is that there is one behaviour
 * sketch now (`Olfactory Behavior/GRGL`), and everything six sketches used to
 * differ in — the trial table, the ramp, the selection mode, every number —
 * arrives from here instead: at compile time in two generated headers, or at
 * `START` time on the wire (`tasks.md` §1.1 and §11).
 *
 * The Dashboard's HUD layout survives, and so does its point: the machine and
 * the thing being edited stay on screen together, because the diagram is the
 * fastest check that an edit did what was meant. Three regions —
 *
 *   left    the rig's profiles, and the presets a new one starts from
 *   centre  the derived state machine, the trial table, the ramp
 *   right   the parameter rail, unchanged from the viewer
 *
 * — and the CENTRE column scrolls rather than the page, because there are three
 * editors in it now and only the first is a hero.
 *
 * EVERY REDRAW COMES FROM `tasks.preview`. The state machine is derived from
 * the profile the current definition COMPILES TO, not from a saved file, so an
 * added trial type grows an arm before the save. That round trip is also what
 * validates: most of the eight rules depend on the wiring, and the frontend
 * holds no copy of it.
 */
export function Task() {
  const { client, status } = useSidecar();
  const { discovery, refreshSketches } = useSettings();
  const connected = status === "connected";

  const [tasks, setTasks] = useState<TaskEntry[]>([]);
  /** False until the first `tasks.list` answers. What separates "nothing to
   *  open yet" (show nothing) from "nothing exists" (show the prompt) — the
   *  prompt used to flash for the instant before the list arrived, right
   *  before the editor popped in over it. */
  const [tasksLoaded, setTasksLoaded] = useState(false);
  const [presets, setPresets] = useState<TaskPreset[]>([]);
  const [rig, setRig] = useState<RigDocument | null>(null);
  const [vocabulary, setVocabulary] = useState<StrobeVocabulary | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [seed, setSeed] = useState<TaskDefinition | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [hoverGroup, setHoverGroup] = useState<string | null>(null);
  const [hoverNode, setHoverNode] = useState<TaskNode | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);

  const session = useTask(selected, seed);
  const { definition, setDefinition } = session;

  const refresh = useCallback(async () => {
    try {
      const reply = await listTasks(client);
      setTasks(reply.tasks);
      setListError(null);
    } catch (err) {
      setListError(errorMessage(err));
    } finally {
      // Either way the question "is there anything to open?" has an answer.
      setTasksLoaded(true);
    }
  }, [client]);

  useEffect(() => {
    if (!connected) return;
    void refresh();
    void listPresets(client).then((r) => setPresets(r.presets));
    // The wiring and the vocabulary are what the trial table's dropdowns offer.
    // Fetched here rather than per-row so a rig with twelve odor lines costs one
    // round trip, and so the two can never disagree within one render.
    void getRig(client).then((r) => setRig(r.document as RigDocument));
    void getStrobes(client).then(setVocabulary);
  }, [client, connected, refresh]);

  useEffect(
    () =>
      client.on(EVT.TASKS_UPDATED, (data) =>
        setTasks((data as { tasks: TaskEntry[] }).tasks),
      ),
    [client],
  );
  // A rewiring changes what the dropdowns may offer, and can break a task that
  // never saw it.
  useEffect(
    () => client.on(EVT.HARDWARE_UPDATED, () => {
      void getRig(client).then((r) => setRig(r.document as RigDocument));
    }),
    [client],
  );

  /* Open something. Reopen the task edited last on this machine — which task is
   * open is a property of the rig someone is standing at, not of the store. */
  useEffect(() => {
    if (selected !== null || seed !== null || tasks.length === 0) return;
    const remembered = window.localStorage.getItem(LAST_TASK_KEY);
    const entry = tasks.find((t) => t.id === remembered) ?? tasks[0]!;
    setSelected(entry.id);
  }, [tasks, selected, seed]);

  // A delete elsewhere can retire the open task out from under the page.
  useEffect(() => {
    if (selected && tasks.length > 0 && !tasks.some((t) => t.id === selected)) {
      setSelected(null);
    }
  }, [tasks, selected]);

  const choose = useCallback((taskId: string) => {
    setSeed(null);
    setSelected(taskId);
    window.localStorage.setItem(LAST_TASK_KEY, taskId);
  }, []);

  const create = useCallback(
    async (presetId: string) => {
      const preset = presets.find((p) => p.id === presetId);
      const taken = tasks.map((t) => t.id);
      const taskId = idFromName(preset?.name ?? presetId, taken);
      try {
        // PURE — it writes nothing, so a preset browsed and abandoned leaves no
        // task behind. Creating stays `tasks.save`, which is the one definition
        // of what saving means.
        const reply = await taskFromPreset(client, presetId, taskId);
        setSelected(null);
        setSeed(reply.definition as TaskDefinition);
      } catch (err) {
        setListError(errorMessage(err));
      }
    },
    [client, presets, tasks],
  );

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
        if (value === undefined) continue;                    // a reset
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

  const remove = useCallback(async () => {
    if (!selected) return;
    await deleteTask(client, selected);
    setSelected(null);
    await refresh();
  }, [client, selected, refresh]);

  const errorCount = session.diagnostics.length;

  return (
    // No `overflow-hidden`: the shared canvas reaches under the sidebar
    // (`Scene.tsx`), exactly as on the Dashboard.
    <div className="relative h-full">
      <SkyBackdrop />

      <div className="pointer-events-none absolute inset-0">
        {/* Left: identity and the profile list. Title metrics match the
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
            <TaskLibrary
              tasks={tasks}
              presets={presets}
              selected={selected}
              onSelect={choose}
              onCreate={(id) => void create(id)}
            />
            {/* The library's health, kept from the old viewer. A profile is
                generated FROM the bundled root sketch, so "the install is
                damaged" is the one thing that stops a task existing at all —
                and with the sketch list gone this is the only place it shows. */}
            <LibraryStatusNote
              discovery={discovery}
              onRefresh={() => void refreshSketches()}
              canRefresh={connected}
            />
            {listError && (
              <p className="px-1 text-[11px] text-status-error">{listError}</p>
            )}
          </div>
        </motion.div>

        {/* Centre: the machine, then the two editors. THIS column scrolls —
            the page still does not, which is what keeps the rail in place. */}
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
            // While a task is on its way in — the list still loading, or a
            // selection whose document hasn't landed — show NOTHING. The
            // prompt used to flash here for a frame and then have the whole
            // editor pop in over it, which read as a broken render rather
            // than a load.
            connected && (!tasksLoaded || selected !== null || seed !== null) ? null : (
              <p className="pointer-events-auto max-w-prose pt-8 text-[13px] leading-relaxed text-static">
                {connected
                  ? "Choose a task, or start a new one from a preset."
                  : "Waiting for the backend — the task library comes from it."}
              </p>
            )
          ) : (
            // The editor stack arrives as a CASCADE — each panel rising on the
            // panel spring a beat after the one above it — so a finished page
            // assembles top-down instead of slamming in as one frame. The
            // stagger is short enough to read as one entrance, not a slideshow.
            <motion.div
              variants={CASCADE}
              initial="hidden"
              animate="shown"
              className="pointer-events-auto flex flex-col gap-3"
            >
              <motion.div variants={RISE}>
                <Header session={session} onDelete={() => void remove()} saved={selected !== null} />
              </motion.div>

              <motion.section variants={RISE} className="hud rounded-md p-4">
                <div className="mb-1 flex items-baseline justify-between gap-3">
                  <span className="text-[11px] text-static">
                    State machine
                    <span className="ml-2 text-static/70">{definition.name}</span>
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

              <motion.div variants={RISE}>
                <TrialTypeTable
                  trials={definition.trials}
                  mode={definition.selectionMode}
                  rig={rig}
                  vocabulary={vocabulary}
                  diagnostics={[...session.diagnostics, ...unscoredTrials]}
                  onChange={(trials) => setDefinition({ ...definition, trials })}
                />
              </motion.div>

              <motion.div variants={RISE}>
                <StageRamp
                  stages={definition.stages}
                  diagnostics={session.diagnostics}
                  onChange={(stages) => setDefinition({ ...definition, stages })}
                />
              </motion.div>
            </motion.div>
          )}
        </motion.div>

        {/* Right: the parameter rail, unchanged from the viewer. */}
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
    </div>
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
 */
function Header({
  session,
  saved,
  onDelete,
}: {
  session: ReturnType<typeof useTask>;
  saved: boolean;
  onDelete: () => void;
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
            onClick={() => void session.save()}
            disabled={session.saving}
            className="shrink-0 rounded-sm bg-pulsar px-3 py-1 text-[11px] font-medium text-void transition-[filter] hover:brightness-108 disabled:opacity-50"
          >
            {session.saving ? "Saving…" : "Save"}
          </button>
        </>
      )}

      {saved && !session.dirty && (
        <button
          type="button"
          onClick={onDelete}
          title="Delete this task and its generated sketch"
          className="shrink-0 text-static transition-colors hover:text-status-error"
        >
          <Trash2 size={13} strokeWidth={1.75} />
        </button>
      )}

      {session.actionError && (
        <span className="shrink-0 text-[11px] text-status-error">
          {session.actionError}
        </span>
      )}
    </div>
  );
}

/** Per machine, not per store: which task is open is a property of the rig
 *  someone is standing at. */
const LAST_TASK_KEY = "ephymeris:lastTask";

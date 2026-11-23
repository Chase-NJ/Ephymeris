import { useEffect, useMemo, useRef, useState } from "react";

import { Segmented, Toggle } from "@/components/common/controls";
import { Panel } from "@/features/tasks/editor/Panel";
import { LiveStateMachine } from "@/features/tasks/SketchStateMachine";
import { type Animal } from "./animals";
import {
  flowOf,
  liveAt,
  readStrobes,
  shownCount,
  stageStarts,
  telemetryAt,
  trialAt,
  trialTicks,
  waterBy,
} from "./playback";
import { usePlayback } from "./usePlayback";
import { advance, EMPTY_LIVE_TRIALS, vocabFrom, type LiveTrials } from "@/features/sessions/liveTrials";
import type { StrobeEvent } from "@/features/sessions/store";
import { simulateTask } from "@/features/tasks/commands";
import type { TaskDefinition } from "@/features/tasks/types";
import type { TaskGraphModel } from "@/features/tasks/topology";
import { useSidecar } from "@/lib/ws/context";
import type { TaskProfile, TaskSimulation } from "@/lib/ws/protocol";

import { AnimalPanel } from "./AnimalPanel";
import { Performance } from "./Performance";
import { StressTest } from "./StressTest";
import { StrobeFeed } from "./StrobeFeed";
import { Transport } from "./Transport";

/** What the Simulate view is set to; kept by the editor so a look at Design does not lose it. */
export interface SimSettings {
  animal: Animal;
  limitMinutes: number;
  /** The seed the session shown ran on; null until one has run, and after the dice. */
  seed: number | null;
  /** Bumped by the dice: a rerun the settings alone would not ask for. */
  deal: number;
}

/** How long a setting must rest before the session reruns: a slider drag is many changes. */
const RERUN_AFTER_MS = 250;

type Below = "session" | "stress";
const BELOW: ReadonlyArray<{ value: Below; label: string }> = [
  { value: "session", label: "This session" },
  { value: "stress", label: "Stress test" },
];

/**
 * The task run off the rig (`TASKS.md#simulating-a-task`): the sidecar runs the
 * working definition's firmware against the animal on the right, and this plays
 * the session back, drawn as a running box is.
 */
export function SimulateView({
  definition,
  profile,
  model,
  split,
  settings,
  onSettings,
}: {
  definition: TaskDefinition;
  profile: TaskProfile;
  model: TaskGraphModel;
  /** The editor's layout: side by side when the page is wide enough. */
  split: boolean;
  settings: SimSettings;
  onSettings: (next: SimSettings) => void;
}) {
  const { client, status } = useSidecar();
  const [simulation, setSimulation] = useState<TaskSimulation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [showFlow, setShowFlow] = useState(true);
  const [below, setBelow] = useState<Below>("session");
  const asked = useRef(0);
  const latest = useRef(settings);
  latest.current = settings;

  const { animal, limitMinutes, deal } = settings;
  const limitMs = limitMinutes * 60_000;

  useEffect(() => {
    if (status !== "connected") return;
    const id = ++asked.current;
    const timer = window.setTimeout(() => {
      setRunning(true);
      const seed = latest.current.seed;
      simulateTask(client, definition, animal, { limitMs, ...(seed === null ? {} : { seed }) })
        .then((result) => {
          if (id !== asked.current) return;
          setSimulation(result);
          setError(null);
          if (latest.current.seed !== result.seed) onSettings({ ...latest.current, seed: result.seed });
        })
        .catch((cause: unknown) => {
          if (id !== asked.current) return;
          setSimulation(null);
          setError(cause instanceof Error ? cause.message : String(cause));
        })
        .finally(() => {
          if (id === asked.current) setRunning(false);
        });
    }, RERUN_AFTER_MS);
    return () => window.clearTimeout(timer);
    // The seed is an outcome of a run, not a reason for one: the dice bump `deal`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, status, definition, animal, limitMs, deal]);

  const strobes = useMemo(() => readStrobes(simulation?.strobes ?? []), [simulation]);
  const durationMs = simulation?.durationMs ?? 0;
  const names = profile.strobes;
  const playback = usePlayback(durationMs, simulation);
  const { atMs } = playback;

  const count = useMemo(() => shownCount(strobes, atMs), [strobes, atMs]);
  const live = liveAt(model, names, strobes, count, atMs);
  const flow = useMemo(() => flowOf(model, names, strobes, count), [model, names, strobes, count]);
  const ticks = useMemo(() => trialTicks(simulation?.trialTable ?? null, durationMs), [simulation, durationMs]);
  const stages = useMemo(
    () => stageStarts(strobes, names, definition.stages.map((stage) => stage.trials)),
    [strobes, names, definition.stages],
  );
  const metrics = useMemo(() => telemetryAt(simulation?.telemetry ?? [], count), [simulation, count]);
  const water = useMemo(() => waterBy(ticks, atMs), [ticks, atMs]);

  const events = useMemo<StrobeEvent[]>(
    () => strobes.map(({ code, at }) => ({ code: String(code), at })),
    [strobes],
  );
  const vocab = useMemo(() => vocabFrom(names), [names]);
  const folded = useRef<{ events: StrobeEvent[]; count: number; state: LiveTrials } | null>(null);
  const liveTrials = useMemo(() => {
    const before = folded.current;
    const base = before && before.events === events && before.count <= count ? before.state : EMPTY_LIVE_TRIALS;
    const state = advance(base, events.slice(0, count), vocab);
    folded.current = { events, count, state };
    return state;
  }, [events, count, vocab]);

  const observed = useMemo(() => {
    const seen = new Set(liveTrials.odorCodes.map((code) => (names[code] ?? "").toUpperCase()));
    return new Set(model.conditions.filter((c) => seen.has(c.strobeName)).map((c) => c.id));
  }, [liveTrials.odorCodes, names, model]);

  const stage = stages.filter((mark) => mark.atMs <= atMs).length;
  const trial = trialAt(ticks, atMs);

  const machine = (
    <Panel
      id="sim-machine"
      name="Trial flow"
      note={
        simulation
          ? `${definition.stages.length > 1 ? `stage ${stage + 1} of ${definition.stages.length} · ` : ""}${
              trial < 0 ? "session starting" : `${flow.trials} trial${flow.trials === 1 ? "" : "s"} so far`
            }`
          : running
            ? "running the firmware…"
            : undefined
      }
      right={
        <span className="flex items-center gap-2 text-[11px] text-static">
          Share of trials
          <Toggle checked={showFlow} onChange={setShowFlow} label="Show the share of trials through each state" />
        </span>
      }
    >
      {model.usable ? (
        <LiveStateMachine
          model={model}
          liveNode={live.node}
          liveCondition={live.condition}
          observedConditions={observed}
          shares={showFlow && flow.trials > 0 ? flow.shares : null}
        />
      ) : (
        <p className="text-[11px] leading-relaxed text-static">
          This task presents nothing yet, so there is no trial to draw. Add a trial type in Design.
        </p>
      )}
    </Panel>
  );

  const transport = simulation && (
    <Panel id="sim-transport" name="Session" note={`seed ${simulation.seed}`}>
      <Transport playback={playback} durationMs={durationMs} ticks={ticks} stages={stages} />
    </Panel>
  );

  const lower = (
    <Panel
      id="sim-lower"
      name={below === "session" ? "Strobes and performance" : "Stress test"}
      note={below === "session" ? "at the playhead" : "does a strategy that ignores the odor pay?"}
      right={<Segmented label="What to show" value={below} options={BELOW} onChange={setBelow} />}
      className={split ? "min-h-0 flex-1" : "min-h-[320px]"}
      bodyClassName="scrollbar-slim min-h-0 flex-1 overflow-y-auto"
    >
      {below === "stress" ? (
        <StressTest definition={definition} limitMs={limitMs} />
      ) : simulation ? (
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] gap-4">
          <StrobeFeed strobes={strobes} count={count} names={names} onSeek={playback.seek} />
          <Performance
            profile={profile}
            live={liveTrials}
            metrics={metrics}
            water={water}
            simulation={simulation}
            ended={playback.ended}
          />
        </div>
      ) : (
        <p className="text-[11px] leading-relaxed text-static">
          {error ?? (running ? "Running the task's firmware against the animal…" : "Nothing simulated yet.")}
        </p>
      )}
    </Panel>
  );

  return (
    <div className={split ? "flex min-h-0 flex-1 gap-3" : "flex flex-col gap-3 pb-2"}>
      <div className={split ? "flex min-h-0 min-w-0 flex-1 flex-col gap-3" : "flex flex-col gap-3"}>
        {machine}
        {error && simulation === null && below === "stress" && (
          <p className="text-[11px] text-status-error">{error}</p>
        )}
        {transport}
        {lower}
      </div>
      <div className={split ? "flex min-h-0 w-[340px] shrink-0 flex-col" : "flex min-h-[420px] flex-col"}>
        <AnimalPanel
          animal={animal}
          onAnimal={(next) => onSettings({ ...latest.current, animal: next })}
          seed={settings.seed}
          onNewSeed={() => onSettings({ ...latest.current, seed: null, deal: latest.current.deal + 1 })}
          limitMinutes={limitMinutes}
          onLimitMinutes={(minutes) => onSettings({ ...latest.current, limitMinutes: minutes })}
          running={running}
        />
      </div>
    </div>
  );
}

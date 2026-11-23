/**
 * Reading a simulated session at a moment of its own clock
 * (`TASKS.md#playing-a-simulation-back`).
 *
 * A simulation arrives whole. Everything the Simulate view shows is the session
 * cut at the playhead: the strobes sent by then, and what a running box's panel
 * would have drawn from them. All pure, so a scrub backwards is the same
 * question as playing forwards.
 */
import {
  liveConditionId,
  liveNodeId,
  nodeIndexByName,
  type LiveCondition,
  type TaskGraphModel,
} from "@/features/tasks/topology";
import type { SimulationTelemetry, TelemetryMetric, TrialTable } from "@/lib/ws/protocol";

/** One strobe of a simulated session: this machine's code, and ms since `START_SESSION`. */
export interface Strobe {
  code: number;
  at: number;
}

/** `TaskSimulation.strobes`' `[code, ms]` pairs, named. */
export function readStrobes(pairs: ReadonlyArray<readonly number[]>): Strobe[] {
  return pairs.map(([code = 0, at = 0]) => ({ code, at }));
}

export const SPEEDS = [1, 4, 16, 64] as const;
export type Speed = (typeof SPEEDS)[number];

/** As `useLiveNode`: how many trailing strobes say where the box is, and which condition. */
const NODE_TAIL = 24;
const CONDITION_TAIL = 160;
/** As `useLiveNode`: how long an outcome holds the token before the ITI takes it. */
export const OUTCOME_SETTLE_MS = 1200;

/** How many strobes had been sent by `atMs`. */
export function shownCount(strobes: readonly Strobe[], atMs: number): number {
  let low = 0;
  let high = strobes.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (strobes[mid]!.at <= atMs) low = mid + 1;
    else high = mid;
  }
  return low;
}

export interface LiveAt {
  node: string | null;
  condition: LiveCondition;
}

/** Where the token sits at `atMs`, read as Mission Control reads a running box. */
export function liveAt(
  model: TaskGraphModel,
  names: Record<string, string>,
  strobes: readonly Strobe[],
  count: number,
  atMs: number,
): LiveAt {
  if (!model.usable || count === 0) return { node: null, condition: null };
  const codes = (tail: number) =>
    strobes.slice(Math.max(0, count - tail), count).map((strobe) => String(strobe.code));
  const arrived = liveNodeId(model, names, codes(NODE_TAIL));
  const node = model.nodes.find((n) => n.id === arrived);
  const settled =
    node?.settlesToIti === true &&
    atMs - strobes[count - 1]!.at >= OUTCOME_SETTLE_MS &&
    model.nodes.some((n) => n.id === "iti");
  return {
    node: settled ? "iti" : arrived,
    condition: liveConditionId(model, names, codes(CONDITION_TAIL)),
  };
}

/** The live metrics as they stood once `count` strobes had been sent. */
export function telemetryAt(telemetry: readonly SimulationTelemetry[], count: number): TelemetryMetric[] {
  let low = 0;
  let high = telemetry.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (telemetry[mid]!.strobe < count) low = mid + 1;
    else high = mid;
  }
  return low === 0 ? [] : telemetry[low - 1]!.metrics;
}

export interface Flow {
  /** Trials opened among the strobes counted. */
  trials: number;
  /** Node id → the share of those trials that reached it. */
  shares: Map<string, number>;
}

/** How many of the trials so far passed through each node of the graph. */
export function flowOf(
  model: TaskGraphModel,
  names: Record<string, string>,
  strobes: readonly Strobe[],
  count: number,
): Flow {
  const nodeOf = nodeIndexByName(model);
  const reached = new Map<string, number>();
  let trials = 0;
  let seen = new Set<string>();
  const close = () => {
    for (const id of seen) reached.set(id, (reached.get(id) ?? 0) + 1);
    seen = new Set();
  };
  for (let i = 0; i < count; i++) {
    const name = names[String(strobes[i]!.code)]?.toUpperCase();
    if (name === "TRIAL_START") {
      close();
      trials += 1;
    }
    const id = name === undefined ? undefined : nodeOf.get(name);
    if (id !== undefined && trials > 0) seen.add(id);
  }
  close();
  const shares = new Map<string, number>();
  if (trials > 0) for (const [id, n] of reached) shares.set(id, n / trials);
  return { trials, shares };
}

export type TickTone = "earned" | "hold" | "wrong" | "silent" | "abort";

const TONE_OF: Record<string, TickTone> = {
  correct: "earned",
  withheld: "earned",
  hold_broken: "hold",
  wrong_response: "wrong",
  false_alarm: "wrong",
  omission: "silent",
};

export interface TrialTick {
  index: number;
  atMs: number;
  /** The next trial's start, or the session's end. */
  endMs: number;
  tone: TickTone;
  outcome: string | null;
  rewardMs: number;
}

/** One tick per trial of the session, for the timeline. */
export function trialTicks(table: TrialTable | null, durationMs: number): TrialTick[] {
  const trials = (table?.trials ?? []).filter((trial) => trial.atMs !== null);
  return trials.map((trial, i) => ({
    index: trial.index,
    atMs: trial.atMs as number,
    endMs: i + 1 < trials.length ? (trials[i + 1]!.atMs as number) : durationMs,
    tone: trial.outcome === null ? "abort" : (TONE_OF[trial.outcome] ?? "abort"),
    outcome: trial.outcome,
    rewardMs: trial.rewarded ? (trial.rewardMs ?? 0) : 0,
  }));
}

/** The index in `ticks` of the trial running at `atMs`; -1 before the first. */
export function trialAt(ticks: readonly TrialTick[], atMs: number): number {
  let low = 0;
  let high = ticks.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (ticks[mid]!.atMs <= atMs) low = mid + 1;
    else high = mid;
  }
  return low - 1;
}

/** Where a step to the next (`1`) or the previous (`-1`) trial lands. */
export function stepTrial(ticks: readonly TrialTick[], atMs: number, by: 1 | -1, durationMs: number): number {
  const here = trialAt(ticks, atMs);
  if (by === 1) return here + 1 < ticks.length ? ticks[here + 1]!.atMs : durationMs;
  if (here < 0) return 0;
  const startedJustNow = atMs - ticks[here]!.atMs < 500;
  return ticks[Math.max(0, startedJustNow ? here - 1 : here)]!.atMs;
}

export interface Water {
  rewards: number;
  ms: number;
}

/** What had been paid by `atMs`: a trial counts once the next has begun. */
export function waterBy(ticks: readonly TrialTick[], atMs: number): Water {
  let rewards = 0;
  let ms = 0;
  for (const tick of ticks) {
    if (tick.endMs > atMs) break;
    if (tick.rewardMs > 0) {
      rewards += 1;
      ms += tick.rewardMs;
    }
  }
  return { rewards, ms };
}

/**
 * When each later ramp row took over: the session time of the completed trial
 * that reached its count. A trial completes when its footer carries no
 * `INVALID_TRIAL`, as the firmware counts them.
 */
export function stageStarts(
  strobes: readonly Strobe[],
  names: Record<string, string>,
  stageTrials: readonly number[],
): Array<{ stage: number; atMs: number }> {
  const starts: Array<{ stage: number; atMs: number }> = [];
  let completed = 0;
  let repeats = false;
  for (const { code, at } of strobes) {
    const name = names[String(code)]?.toUpperCase();
    if (name === "TRIAL_START") repeats = false;
    else if (name === "INVALID_TRIAL") repeats = true;
    else if (name === "END_TRIAL" && !repeats) {
      completed += 1;
      stageTrials.forEach((engagesAt, stage) => {
        if (stage > 0 && engagesAt === completed) starts.push({ stage, atMs: at });
      });
    }
  }
  return starts;
}

/** `754000` → `12:34`; an hour or more → `1:02:34`. */
export function clockLabel(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const s = String(total % 60).padStart(2, "0");
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600);
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

import { useState } from "react";

import { Button, Segmented } from "@/components/common/controls";
import { PRESETS, TRAINED_PRESET } from "./animals";
import { clockLabel } from "./playback";
import { stressTestTask } from "@/features/tasks/commands";
import type { TaskDefinition } from "@/features/tasks/types";
import { useSidecar } from "@/lib/ws/context";
import type { StressAnimal, TaskStressTest } from "@/lib/ws/protocol";

const SESSION_CHOICES = [
  { value: "5", label: "5" },
  { value: "10", label: "10" },
  { value: "25", label: "25" },
] as const;

/** An animal that ignores the odor and still earns this share of a trained one's rewards is flagged. */
export const EXPLOIT_SHARE = 0.5;

const EXPLOITS = new Set(PRESETS.filter((p) => p.exploit).map((p) => p.label));

/** What `row` earns as a share of what the trained animal earns; null with nothing to compare. */
export function shareOfBaseline(row: StressAnimal, baseline: StressAnimal | undefined): number | null {
  if (!baseline || !baseline.meanRewards || row.meanRewards === null) return null;
  return row.meanRewards / baseline.meanRewards;
}

const fixed = (value: number | null, digits: number) => (value === null ? "—" : value.toFixed(digits));

/**
 * Every preset animal through the same sessions of this task
 * (`TASKS.md#the-stress-test`): what each earns, and whether one that never
 * uses the odor earns enough to make the task worth gaming.
 */
export function StressTest({ definition, limitMs }: { definition: TaskDefinition; limitMs: number }) {
  const { client } = useSidecar();
  const [sessions, setSessions] = useState<(typeof SESSION_CHOICES)[number]["value"]>("10");
  const [result, setResult] = useState<TaskStressTest | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = () => {
    setRunning(true);
    setError(null);
    stressTestTask(
      client,
      definition,
      PRESETS.map((p) => ({ label: p.label, animal: p.animal })),
      { sessions: Number(sessions), limitMs },
    )
      .then(setResult)
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)))
      .finally(() => setRunning(false));
  };

  const baseline = result?.animals.find((row) => row.label === TRAINED_PRESET.label);
  const flagged = (result?.animals ?? []).filter((row) => {
    const share = shareOfBaseline(row, baseline);
    return EXPLOITS.has(row.label) && share !== null && share >= EXPLOIT_SHARE;
  });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="text-[11px] text-static">Sessions per animal</span>
        <Segmented label="Sessions per animal" value={sessions} options={SESSION_CHOICES} onChange={setSessions} />
        <Button variant="secondary" onClick={run} disabled={running}>
          {running ? "Running…" : result ? "Run again" : "Run stress test"}
        </Button>
        <span className="text-[11px] text-static/80">
          {PRESETS.length} animals, each over the same seeds, at this task's own values.
        </span>
      </div>

      {error && <p className="text-[11px] text-status-error">{error}</p>}

      {result && (
        <>
          <table className="w-full border-collapse text-[11px]">
            <thead>
              <tr className="font-mono text-[9px] tracking-[0.14em] text-static/80 uppercase">
                <th className="py-1 text-left font-normal">Animal</th>
                <th className="py-1 text-right font-normal">Accuracy</th>
                <th className="py-1 text-right font-normal">Trials</th>
                <th className="py-1 text-right font-normal">Rewards</th>
                <th className="py-1 text-right font-normal">Per hour</th>
                <th className="py-1 text-right font-normal">Session</th>
                <th className="w-[26%] py-1 pl-3 text-left font-normal">Of trained</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {result.animals.map((row) => {
                const share = shareOfBaseline(row, baseline);
                const warn = flagged.includes(row);
                return (
                  <tr key={row.label} className="border-t border-halo/50">
                    <td className={`py-1.5 pr-2 font-sans ${warn ? "text-status-warning" : "text-starlight"}`}>
                      {row.label}
                    </td>
                    <td className="py-1.5 text-right text-static">{fixed(row.meanAccuracy, 2)}</td>
                    <td className="py-1.5 text-right text-static">{fixed(row.meanPresented, 0)}</td>
                    <td className="py-1.5 text-right text-starlight">{fixed(row.meanRewards, 1)}</td>
                    <td className="py-1.5 text-right text-static">{fixed(row.rewardsPerHour, 0)}</td>
                    <td className="py-1.5 text-right text-static">
                      {row.meanDurationMs === null ? "—" : clockLabel(row.meanDurationMs)}
                    </td>
                    <td className="py-1.5 pl-3">
                      <span className="flex items-center gap-2">
                        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-halo/60">
                          <span
                            className="block h-full rounded-full"
                            style={{
                              width: `${Math.round(Math.min(1, share ?? 0) * 100)}%`,
                              background: warn ? "var(--color-status-warning)" : "var(--color-pulsar)",
                            }}
                          />
                        </span>
                        <span className={`w-9 text-right ${warn ? "text-status-warning" : "text-static"}`}>
                          {share === null ? "—" : `${Math.round(share * 100)}%`}
                        </span>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {flagged.length > 0 ? (
            <ul className="m-0 flex list-none flex-col gap-1 p-0 text-[11px] leading-snug text-status-warning">
              {flagged.map((row) => (
                <li key={row.label}>
                  A {row.label.toLowerCase()} animal earns{" "}
                  {Math.round((shareOfBaseline(row, baseline) ?? 0) * 100)}% of a trained animal's rewards without
                  using the odor.
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[11px] leading-snug text-static">
              No animal that ignores the odor earns half of what a trained one does.
            </p>
          )}
          <p className="text-[10px] leading-snug text-static/70">
            Means over {result.seeds.length} sessions of up to {clockLabel(result.limitMs)} each. Rewards and trials are per
            session; trials count repeats.
          </p>
        </>
      )}
    </div>
  );
}

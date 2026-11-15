import { useState } from "react";

import { AccuracyChart, TrialsView } from "@/components/analytics/session/TrialsView";
import { Button, Select, TextInput } from "@/components/common/controls";
import { errorMessage } from "@/lib/cohorts/commands";
import { simulateTask } from "@/lib/taskdef/commands";
import {
  ANIMALS,
  DEFAULT_FORM,
  absentLabels,
  endedLabel,
  responsesOf,
  simulateArgs,
  switchLabels,
  verdict,
  type AnimalKind,
  type SimulateForm,
} from "@/lib/taskdef/simulate";
import type { SpineDefinition } from "@/lib/taskdef/spine";
import { useSidecar } from "@/lib/ws/context";
import type { TaskDiagnostic, TaskSimulation } from "@/lib/ws/protocol";

import { Field, Note } from "./bits";

/**
 * Simulate (`TASKS.md#simulating-a-spine-task`): the unsaved task run against
 * a simulated animal through replay, before anything is compiled or flashed.
 * The sidecar runs and scores it as Analytics scores a run, so what this draws
 * is Analytics' own trial view, under a verdict in plain words
 * (`simulate.verdict`). It runs on demand only; once the document changes, the
 * last result is dimmed until it is run again.
 */
export function SimulatePanel({
  definition,
  diagnostics,
}: {
  definition: SpineDefinition;
  diagnostics: readonly TaskDiagnostic[];
}) {
  const { client, status } = useSidecar();
  const [form, setForm] = useState<SimulateForm>(DEFAULT_FORM);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ sim: TaskSimulation; ranFor: string; animal: string } | null>(null);

  const responses = responsesOf(definition);
  const problems = diagnostics.length;
  const stale = result !== null && result.ranFor !== JSON.stringify(definition);
  const blocked =
    status !== "connected"
      ? "The sidecar isn't connected."
      : problems > 0
        ? `Fix the task's ${problems} problem${problems === 1 ? "" : "s"} first.`
        : null;

  function set(patch: Partial<SimulateForm>) {
    setForm((f) => ({ ...f, ...patch }));
  }

  async function run() {
    const built = simulateArgs(definition, form);
    if ("error" in built) {
      setError(built.error);
      return;
    }
    const ranFor = JSON.stringify(definition);
    setRunning(true);
    setError(null);
    try {
      const sim = await simulateTask(client, definition, built.args);
      setResult({ sim, ranFor, animal: ANIMALS.find((a) => a.kind === form.kind)?.label ?? form.kind });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <Note>
        A whole session against a pretend animal, scored as Analytics scores a real run. Try Always correct first, then Random. Nothing is
        compiled, flashed or saved.
      </Note>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Animal">
          <Select<AnimalKind>
            value={form.kind}
            label="Simulated animal"
            options={ANIMALS.map((a) => ({ value: a.kind, label: a.label }))}
            onChange={(kind) => set({ kind, response: form.response || (responses[0] ?? "") })}
          />
        </Field>
        {form.kind === "biased" && (
          <>
            <Field label="Favours">
              <Select<string>
                value={form.response}
                label="The response a biased animal favours"
                options={responses.map((slot) => ({ value: slot, label: slot }))}
                onChange={(response) => set({ response })}
              />
            </Field>
            <Field label="How often %">
              <TextInput mono value={form.percent} label="How often it takes it, in percent" onChange={(percent) => set({ percent })} className="w-16" />
            </Field>
          </>
        )}
        <Field label="Seed">
          <TextInput mono value={form.seed} placeholder="fresh" label="Seed; blank draws a fresh one" onChange={(seed) => set({ seed })} onSubmit={() => void run()} className="w-28" />
        </Field>
        <Field label="Time limit, min">
          <TextInput mono value={form.limitMin} label="Session time limit in minutes" onChange={(limitMin) => set({ limitMin })} className="w-16" />
        </Field>
        <Button variant="primary" onClick={() => void run()} disabled={running || blocked !== null} {...(blocked ? { title: blocked } : {})}>
          {running ? "Running…" : "Run"}
        </Button>
      </div>
      <p className="text-[10px] leading-relaxed text-static/80">{ANIMALS.find((a) => a.kind === form.kind)?.help}.</p>
      {blocked && <p className="text-[11px] text-static">{blocked}</p>}
      {error && <p className="text-[11px] text-status-error">{error}</p>}
      {result && <SimulationResult sim={result.sim} animal={result.animal} stale={stale} />}
    </div>
  );
}

function SimulationResult({ sim, animal, stale }: { sim: TaskSimulation; animal: string; stale: boolean }) {
  const trials = sim.trialTable?.trials.length ?? 0;
  const absent = absentLabels(sim);
  const curves = sim.series.filter((m) => m.values.length >= 2);
  const said = verdict(sim, animal);
  return (
    <div className={`flex flex-col gap-2.5 border-t border-halo pt-2.5 transition-opacity ${stale ? "opacity-40" : ""}`}>
      {stale && <p className="text-[11px] text-static">The task has changed since this run. Run it again.</p>}
      <div className="flex flex-col gap-0.5">
        {said.map((line, i) => (
          <p key={i} className={`text-[12px] leading-relaxed ${i === 0 ? "text-starlight" : absent.length && line.startsWith("Never presented") ? "text-status-warning" : "text-static"}`}>
            {line}
          </p>
        ))}
      </div>
      <p className="font-mono text-[10px] tabular-nums text-static/80">
        seed {sim.seed} · {trials} trial{trials === 1 ? "" : "s"} · {endedLabel(sim)} · type the seed in the Seed box to run this session again
      </p>
      {sim.status !== "ok" && (
        <p className="text-[11px] text-status-error">The simulated run could not be scored: {sim.detail}</p>
      )}
      {sim.switches.length > 0 && (
        <p className="text-[11px] text-static">
          <span className="text-static/70">Blocks: </span>
          {switchLabels(sim).join(" → ")}
        </p>
      )}
      {sim.replay && <TrialsView replay={sim.replay} table={sim.trialTable} rates={false} />}
      {sim.replay && sim.replay.rates.length > 0 && (
        <p className="text-[10px] leading-relaxed text-static/80">
          Phase-window rates are not simulated: the animal never touches an input the task only counts, such as licks.
        </p>
      )}
      {curves.length > 0 && (
        <>
          <AccuracyChart cumulative metrics={curves} label="Cumulative P(correct) per row over the simulated session" />
          <p className="text-[10px] leading-relaxed text-static/80">P(correct | row) so far, trial by trial.</p>
        </>
      )}
    </div>
  );
}

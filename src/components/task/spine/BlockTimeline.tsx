import { Plus, Trash2 } from "lucide-react";
import { Fragment } from "react";

import { NumberInput, Segmented, Select } from "@/components/common/controls";
import {
  SHAPES,
  applyShape,
  blockLabel,
  canReverse,
  defaultShape,
  endRuleWords,
  sessionSentence,
  shapeOf,
  type SessionShape,
  type ShapeKind,
} from "@/lib/taskdef/sessionShape";
import {
  addBlock,
  diagnosticsOn,
  removeBlock,
  setBlock,
  type SpineBlock,
  type SpineDefinition,
} from "@/lib/taskdef/spine";
import { PHASE_LABEL, classLabel } from "@/lib/taskdef/spineLabels";
import { targetLines } from "@/lib/taskdef/spineProblems";
import { diagnosticsAt } from "@/lib/taskdef/types";
import type { SpineStoredValue, SpineView, TaskDiagnostic } from "@/lib/ws/protocol";

import { Field, Note, OptionalNumber, ProblemLines, SlotSet, StoredValues, problemTitle } from "./bits";

/**
 * The session (`TASKS.md#blocks`): its shape, chosen from the three a first
 * task takes or custom (`lib/taskdef/sessionShape.ts`); the blocks in the
 * order they run, said as a sentence and drawn as a strip; the session cap;
 * and the selected block's fields. What follows each block is the preview's
 * (`SpineView.blocks[].next`), so a loop is drawn as the sidecar resolves it:
 * an arrow on to the next, an arc back to an earlier one, or the end.
 */
export function BlockTimeline({
  def,
  view,
  selections,
  weightedSelections,
  outcomeClasses,
  diagnostics,
  stored,
  selected,
  onSelect,
  onChange,
  onClearStored,
}: {
  def: SpineDefinition;
  view: SpineView | null;
  selections: readonly string[];
  /** The selections that read each row's weight (`lowering.WEIGHTED`), from the palette. */
  weightedSelections: readonly string[];
  outcomeClasses: readonly string[];
  diagnostics: readonly TaskDiagnostic[];
  stored: readonly SpineStoredValue[];
  selected: number | null;
  onSelect: (b: number) => void;
  onChange: (next: SpineDefinition) => void;
  onClearStored: (key: string) => void;
}) {
  const session = targetLines(diagnostics, def, "session", null);
  const nexts = view ? def.blocks.map((b, i) => (view.blocks[i]?.id === b.id ? view.blocks[i]!.next : undefined)) : [];
  return (
    <div className="flex flex-col gap-3">
      <ShapeControl def={def} onChange={onChange} />

      <div className="flex flex-col gap-1">
        <div className="scrollbar-slim flex items-stretch gap-1.5 overflow-x-auto pb-1">
          {def.blocks.map((block, b) => {
            const problems = diagnosticsOn(diagnostics, "block", b);
            const next = nexts[b];
            return (
              <Fragment key={`${block.id}-${b}`}>
                <button
                  type="button"
                  onClick={() => onSelect(b)}
                  aria-pressed={selected === b}
                  title={problemTitle(problems)}
                  className={`flex min-w-[160px] flex-col items-start gap-0.5 rounded-sm border px-2.5 py-1.5 text-left transition-colors ${
                    selected === b ? "border-pulsar/70 bg-pulsar/10" : "border-halo hover:border-static/50"
                  } ${problems.length ? "!border-status-error" : ""}`}
                >
                  <span className="text-[11px] text-starlight">
                    {blockLabel(b)} <span className="font-mono text-[9px] text-static/60">{block.id}</span>
                    {problems.length > 0 && <span className="ml-1.5 font-mono text-status-error">{problems.length}</span>}
                  </span>
                  <span className="text-[11px] text-static">
                    {block.rows.length} trial type{block.rows.length === 1 ? "" : "s"} · {block.select ?? "uniform"}
                  </span>
                  <span className="text-[10px] text-static/80">{endRuleWords(block)}</span>
                </button>
                <span className="flex shrink-0 items-center px-1 font-mono text-[11px] text-static">
                  {next === undefined ? "…" : next === null ? "end" : next === b + 1 ? "→" : `↺ ${blockLabel(next)}`}
                </span>
              </Fragment>
            );
          })}
          <button
            type="button"
            onClick={() => onChange(addBlock(def))}
            className="flex shrink-0 items-center gap-1 self-center text-[11px] text-static transition-colors hover:text-starlight"
          >
            <Plus size={12} strokeWidth={1.75} /> block
          </button>
        </div>
        <Note className="text-static">
          {sessionSentence(def, nexts)}
          {selected === null && <span className="text-static/60"> Click a block to edit its trial types, draw and end rule.</span>}
        </Note>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-[11px] text-static">
        <span className="font-mono text-[9px] tracking-[0.14em] text-static/70 uppercase">Session cap</span>
        <OptionalNumber
          value={def.sessionTrials}
          initial={400}
          label="Session cap, in trials"
          min={1}
          invalid={session.length > 0}
          unit="trials"
          onChange={(sessionTrials) => {
            const next = { ...def };
            if (sessionTrials === undefined) delete next.sessionTrials;
            else next.sessionTrials = sessionTrials;
            onChange(next);
          }}
        />
        <label className="flex items-center gap-1" title="An aborted trial repeats its trial type and counts toward no block's trials or the cap, as GRGL's did">
          <input
            type="checkbox"
            checked={def.repeatAborts === true}
            onChange={(e) => {
              const next = { ...def };
              if (e.target.checked) next.repeatAborts = true;
              else delete next.repeatAborts;
              onChange(next);
            }}
            className="accent-[var(--color-pulsar)]"
          />
          aborted trials repeat, uncounted
        </label>
        <span>
          {view === null
            ? ""
            : view.sessionEnds
              ? "the blocks end the session by themselves"
              : "the blocks loop, or one never ends: only this cap or End Session ends the session"}
        </span>
      </div>
      <ProblemLines lines={session} onFix={(apply) => onChange(apply(def))} />

      {selected !== null && def.blocks[selected] && (
        <BlockPanel
          def={def}
          at={selected}
          selections={selections}
          overridable={view?.overridable ?? []}
          weightedSelections={weightedSelections}
          outcomeClasses={outcomeClasses}
          diagnostics={diagnostics}
          stored={stored}
          onChange={onChange}
          onClearStored={onClearStored}
        />
      )}
      <ProblemLines lines={targetLines(diagnostics, def, "block", null)} onFix={(apply) => onChange(apply(def))} />
    </div>
  );
}

/**
 * The session's shape: one block of N, a reversal after k of n right, two
 * blocks that alternate, or custom. Choosing one writes the blocks
 * (`applyShape`); its numbers edit them in place. Custom is whatever the
 * blocks are, edited in the panel below.
 */
export function ShapeControl({ def, onChange }: { def: SpineDefinition; onChange: (next: SpineDefinition) => void }) {
  const shape = shapeOf(def);
  const reversible = canReverse(def);
  const pick = (kind: ShapeKind) => {
    if (kind === shape.kind) return;
    onChange(applyShape(def, defaultShape(def, kind)));
  };
  const retune = (next: SessionShape) => onChange(applyShape(def, next));
  const help = SHAPES.find((s) => s.kind === shape.kind)?.help ?? "";
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[9px] tracking-[0.14em] text-static/70 uppercase">Shape</span>
        <Segmented
          value={shape.kind}
          label="The session's shape"
          options={SHAPES.filter((s) => s.kind !== "reversal" || reversible || shape.kind === "reversal").map((s) => ({ value: s.kind, label: s.label }))}
          onChange={pick}
        />
        {shape.kind === "single" && (
          <span className="flex items-center gap-1 text-[11px] text-static">
            of
            <NumberInput value={shape.trials} fallback={200} integer min={1} label="Trials in the block" className="w-[64px] !py-0.5 text-[11px]" onChange={(trials) => retune({ kind: "single", trials })} />
            trials
          </span>
        )}
        {shape.kind === "reversal" && (
          <span className="flex flex-wrap items-center gap-1 text-[11px] text-static">
            once
            <NumberInput value={shape.correct} fallback={8} integer min={1} label="Right answers needed" className="w-[48px] !py-0.5 text-[11px]" onChange={(correct) => retune({ ...shape, correct })} />
            of the last
            <NumberInput value={shape.of} fallback={10} integer min={1} max={32} label="Of the last n trials" className="w-[48px] !py-0.5 text-[11px]" onChange={(of) => retune({ ...shape, of })} />
            are right, then the reversed trial types for
            <NumberInput value={shape.trials} fallback={60} integer min={1} label="Trials after the reversal" className="w-[64px] !py-0.5 text-[11px]" onChange={(trials) => retune({ ...shape, trials })} />
            trials
          </span>
        )}
        {shape.kind === "alternate" && (
          <span className="flex flex-wrap items-center gap-1 text-[11px] text-static">
            of
            <NumberInput value={shape.trials} fallback={40} integer min={1} label="Trials per block" className="w-[64px] !py-0.5 text-[11px]" onChange={(trials) => retune({ ...shape, trials })} />
            trials each, until
            <NumberInput value={shape.cap} fallback={400} integer min={1} label="Session cap" className="w-[64px] !py-0.5 text-[11px]" onChange={(cap) => retune({ ...shape, cap })} />
            trials in all
          </span>
        )}
      </div>
      <Note>
        {help}
        {!reversible && shape.kind !== "reversal" && " A reversal needs trial types whose right answers differ, so each can take the other's."}
        {shape.kind === "alternate" && " Pick each block's trial types below: a bandit swaps which side pays."}
      </Note>
    </div>
  );
}

function BlockPanel({
  def,
  at,
  selections,
  overridable,
  weightedSelections,
  outcomeClasses,
  diagnostics,
  stored,
  onChange,
  onClearStored,
}: {
  def: SpineDefinition;
  at: number;
  selections: readonly string[];
  /** The phases a block can override (`SpineView.overridable`, from the preview). */
  overridable: readonly number[];
  weightedSelections: readonly string[];
  outcomeClasses: readonly string[];
  diagnostics: readonly TaskDiagnostic[];
  stored: readonly SpineStoredValue[];
  onChange: (next: SpineDefinition) => void;
  onClearStored: (key: string) => void;
}) {
  const block = def.blocks[at];
  if (!block) return null;
  const field = (key: string) => diagnosticsAt([...diagnostics], `blocks[${at}].${key}`);
  const update = (patch: { [K in keyof SpineBlock]?: SpineBlock[K] | undefined }) => {
    const next = { ...block, ...patch } as Record<string, unknown>;
    for (const [k, v] of Object.entries(patch)) if (v === undefined) delete next[k];
    onChange(setBlock(def, at, next as unknown as SpineBlock));
  };
  const select = block.select ?? "uniform";
  const weighted = weightedSelections.includes(select);

  const toggleRow = (id: string) => {
    const e = block.rows.indexOf(id);
    if (e >= 0) {
      update({
        rows: block.rows.filter((_, i) => i !== e),
        weights: block.weights?.filter((_, i) => i !== e),
      });
    } else {
      update({ rows: [...block.rows, id], weights: block.weights ? [...block.weights, 1] : undefined });
    }
  };
  const setWeight = (e: number, w: number) => {
    const weights = block.rows.map((_, i) => block.weights?.[i] ?? 1);
    weights[e] = w;
    update({ weights });
  };

  return (
    <div className="flex flex-col gap-2 border-t border-halo/60 pt-2">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[10px] tracking-[0.14em] text-static uppercase">
          {blockLabel(at)} <span className="text-static/60 normal-case tracking-normal">{block.id}</span>
        </span>
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => onChange(removeBlock(def, at))}
          className="flex items-center gap-1 text-[11px] text-static transition-colors hover:text-status-error"
        >
          <Trash2 size={11} strokeWidth={1.75} /> Remove block
        </button>
      </div>

      <Field label={weighted ? "Trial types it presents, and their weights" : "Trial types it presents"}>
        <span className="flex flex-wrap gap-1.5" title={problemTitle(field("rows"))}>
          {def.rows.map((row, r) => {
            const e = block.rows.indexOf(row.id);
            const on = e >= 0;
            return (
              <span
                key={row.id}
                className={`flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] ${
                  on ? "border-pulsar/70 bg-pulsar/10" : "border-halo"
                } ${field("rows").length ? "!border-status-error" : ""}`}
              >
                <button type="button" aria-pressed={on} onClick={() => toggleRow(row.id)} className="text-starlight">
                  {row.name || `trial type ${r + 1}`}
                </button>
                {on && weighted && (
                  <NumberInput
                    value={block.weights?.[e] ?? 1}
                    fallback={1}
                    integer
                    min={0}
                    label={`Weight of ${row.name || row.id}`}
                    invalid={field("weights").length > 0}
                    className="w-[52px] !py-0.5 text-[11px]"
                    onChange={(w) => setWeight(e, w)}
                  />
                )}
              </span>
            );
          })}
        </span>
      </Field>

      <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-x-4 gap-y-2">
        <Field label="How the next trial is drawn">
          <Select
            value={select}
            label="Selection"
            tone={field("select").length ? "error" : "normal"}
            options={selections.map((s) => ({ value: s, label: s }))}
            onChange={(s) => update({ select: s === "uniform" ? undefined : s, weights: weightedSelections.includes(s) ? block.weights : undefined })}
          />
        </Field>
        <Field label="Ends after N trials (or at least)">
          <OptionalNumber value={block.trials} initial={100} label="Trials" min={1} invalid={field("trials").length > 0} onChange={(trials) => update({ trials })} />
        </Field>
        <Field label="…at most, N drawn between">
          <OptionalNumber value={block.trialsMax} initial={(block.trials ?? 40) + 20} label="Most trials" min={1} invalid={field("trialsMax").length > 0} onChange={(trialsMax) => update({ trialsMax })} />
        </Field>
        <Field label="Or once k of the last n are right">
          {block.criterion ? (
            <span className="flex items-center gap-1 text-[11px] text-static">
              <NumberInput value={block.criterion.correct} fallback={8} integer min={1} label="Right answers needed" invalid={field("criterion").length > 0} className="w-[52px]" onChange={(correct) => update({ criterion: { ...block.criterion!, correct } })} />
              of
              <NumberInput value={block.criterion.of} fallback={10} integer min={1} label="Of the last" invalid={field("criterion").length > 0} className="w-[52px]" onChange={(of) => update({ criterion: { ...block.criterion!, of } })} />
              <button type="button" aria-label="Remove the criterion" onClick={() => update({ criterion: undefined })} className="hover:text-starlight">×</button>
            </span>
          ) : (
            <OptionalNumber value={undefined} initial={8} label="Criterion" onChange={() => update({ criterion: { correct: 8, of: 10 } })} />
          )}
        </Field>
        <Field label="Then">
          <Select
            value={block.next ?? ""}
            label="Next block"
            tone={field("next").length ? "error" : "normal"}
            options={[{ value: "", label: at + 1 < def.blocks.length ? `${blockLabel(at + 1)}, the following block` : "the session ends" }, ...def.blocks.map((b, i) => ({ value: b.id, label: i <= at ? `back to ${blockLabel(i)}` : blockLabel(i) }))]}
            onChange={(next) => update({ next: next || undefined })}
          />
        </Field>
        <Field label="Repeat an error, up to">
          <OptionalNumber value={block.correction} initial={1} label="Correction repeats" min={0} invalid={field("correction").length > 0} unit="times" onChange={(correction) => update({ correction, correctionAfter: correction === undefined ? undefined : block.correctionAfter })} />
        </Field>
        {select === "antibias" && (
          <>
            <Field label="Bias window">
              <OptionalNumber value={block.biasWindow} initial={10} label="Bias window" min={1} invalid={field("biasWindow").length > 0} unit="answers" onChange={(biasWindow) => update({ biasWindow })} />
            </Field>
            <Field label="Bias strength (GRGL)">
              <OptionalNumber value={block.biasStrength} initial={500} label="Bias strength" min={0} max={1000} invalid={field("biasStrength").length > 0} unit="‰" onChange={(biasStrength) => update({ biasStrength })} />
            </Field>
            <Field label="Least chance of a side">
              <OptionalNumber value={block.biasMin} initial={20} label="Least chance of a side" min={0} max={1000} invalid={field("biasMin").length > 0} unit="‰" onChange={(biasMin) => update({ biasMin })} />
            </Field>
            <Field label="Most chance of a side">
              <OptionalNumber value={block.biasMax} initial={980} label="Most chance of a side" min={0} max={1000} invalid={field("biasMax").length > 0} unit="‰" onChange={(biasMax) => update({ biasMax })} />
            </Field>
            <Field label="Most in a row on one side">
              <OptionalNumber value={block.maxRun} initial={10} label="Most draws in a row on one side" min={1} invalid={field("maxRun").length > 0} unit="draws" onChange={(maxRun) => update({ maxRun })} />
            </Field>
          </>
        )}
      </div>

      {block.correction !== undefined && (
        <Field label="An error is (none chosen: wrong response, false alarm)">
          <SlotSet
            options={outcomeClasses.filter((c) => c !== "correct")}
            value={block.correctionAfter ?? []}
            label="Repeat after"
            invalid={field("correctionAfter").length > 0}
            onChange={(after) => update({ correctionAfter: after.length ? after.map((c) => c) : undefined })}
          />
          <Note>{outcomeClasses.filter((c) => c !== "correct").map(classLabel).join(", ")} are the classes a block can repeat after.</Note>
        </Field>
      )}

      <Field label="Step timings while this block runs">
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          {def.spine.map((p, i) =>
            overridable.includes(i) ? (
              <span key={i} className="flex items-center gap-1.5 text-[11px] text-static">
                {i + 1}. {PHASE_LABEL[p.phase] ?? p.phase}
                <OptionalNumber
                  value={block.phaseMs?.[String(i)]}
                  initial={p.ms ?? p.timeoutMs ?? 1000}
                  label={`Step ${i + 1} in ${blockLabel(at)}`}
                  min={0}
                  unit="ms"
                  invalid={field(`phaseMs.${i}`).length > 0}
                  onChange={(ms) => {
                    const phaseMs = { ...(block.phaseMs ?? {}) };
                    if (ms === undefined) delete phaseMs[String(i)];
                    else phaseMs[String(i)] = ms;
                    update({ phaseMs: Object.keys(phaseMs).length ? phaseMs : undefined });
                  }}
                />
              </span>
            ) : null,
          )}
          {def.spine.map((p, i) =>
            p.phase === "response" && p.holdMs !== undefined ? (
              <span key={`hold-${i}`} className="flex items-center gap-1.5 text-[11px] text-static">
                {i + 1}. answer held
                <OptionalNumber
                  value={block.holdMs?.[String(i)]}
                  initial={p.holdMs}
                  label={`Step ${i + 1}'s hold in ${blockLabel(at)}`}
                  min={0}
                  unit="ms"
                  invalid={field(`holdMs.${i}`).length > 0}
                  onChange={(ms) => {
                    const holdMs = { ...(block.holdMs ?? {}) };
                    if (ms === undefined) delete holdMs[String(i)];
                    else holdMs[String(i)] = ms;
                    update({ holdMs: Object.keys(holdMs).length ? holdMs : undefined });
                  }}
                />
              </span>
            ) : null,
          )}
        </span>
      </Field>

      <StoredValues stored={stored} target={{ kind: "block", index: at }} onClear={onClearStored} />
      <ProblemLines lines={targetLines(diagnostics, def, "block", at)} onFix={(apply) => onChange(apply(def))} />
    </div>
  );
}

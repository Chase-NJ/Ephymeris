import { Plus, Trash2 } from "lucide-react";
import { Fragment } from "react";

import { NumberInput, Select } from "@/components/common/controls";
import {
  addBlock,
  diagnosticsOn,
  removeBlock,
  setBlock,
  type SpineBlock,
  type SpineDefinition,
} from "@/lib/taskdef/spine";
import { PHASE_LABEL } from "@/lib/taskdef/spineLabels";
import { diagnosticsAt } from "@/lib/taskdef/types";
import type { SpineStoredValue, SpineView, TaskDiagnostic } from "@/lib/ws/protocol";

import { Field, OptionalNumber, ProblemLines, SlotSet, StoredValues, problemTitle } from "./bits";

/** The selections that read each row's weight (`lowering.WEIGHTED`). */
const WEIGHTED = new Set(["weighted", "bag", "antibias"]);
/** The phases a block can override (`lowering._TIMED`, and a Wait's or Counter's limit). */
const TIMED = new Set(["hold", "present", "delay", "response", "outcome", "iti"]);

/** A block's end rule in words. */
function endRule(block: SpineBlock): string {
  const parts: string[] = [];
  if (block.trials !== undefined) {
    parts.push(block.trialsMax !== undefined ? `${block.trials}–${block.trialsMax} trials` : `${block.trials} trials`);
  }
  if (block.criterion) parts.push(`${block.criterion.correct} of ${block.criterion.of} correct`);
  return parts.length ? parts.join(" or ") : "never ends";
}

/**
 * The session's blocks in the order they run, and the selected block's fields
 * (`TASKS.md#blocks`). What follows each block is the preview's
 * (`SpineView.blocks[].next`), so a loop is drawn as the sidecar resolves it:
 * an arrow on to the next, an arc back to an earlier one, or the end.
 */
export function BlockTimeline({
  def,
  view,
  selections,
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
  outcomeClasses: readonly string[];
  diagnostics: readonly TaskDiagnostic[];
  stored: readonly SpineStoredValue[];
  selected: number | null;
  onSelect: (b: number) => void;
  onChange: (next: SpineDefinition) => void;
  onClearStored: (key: string) => void;
}) {
  const session = diagnosticsOn(diagnostics, "session");
  return (
    <div className="flex flex-col gap-3">
      <div className="scrollbar-slim flex items-stretch gap-1.5 overflow-x-auto pb-1">
        {def.blocks.map((block, b) => {
          const problems = diagnosticsOn(diagnostics, "block", b);
          const next = view?.blocks[b]?.id === block.id ? view.blocks[b].next : undefined;
          return (
            <Fragment key={`${block.id}-${b}`}>
              <button
                type="button"
                onClick={() => onSelect(b)}
                aria-pressed={selected === b}
                title={problemTitle(problems)}
                className={`flex min-w-[150px] flex-col items-start gap-0.5 rounded-sm border px-2.5 py-1.5 text-left transition-colors ${
                  selected === b ? "border-pulsar/70 bg-pulsar/10" : "border-halo hover:border-static/50"
                } ${problems.length ? "!border-status-error" : ""}`}
              >
                <span className="font-mono text-[11px] text-starlight">
                  {block.id}
                  {problems.length > 0 && <span className="ml-1.5 text-status-error">{problems.length}</span>}
                </span>
                <span className="text-[11px] text-static">
                  {block.select ?? "uniform"} · {block.rows.length} row{block.rows.length === 1 ? "" : "s"}
                </span>
                <span className="font-mono text-[10px] text-static/80">{endRule(block)}</span>
              </button>
              <span className="flex shrink-0 items-center px-1 font-mono text-[11px] text-static">
                {next === undefined
                  ? "…"
                  : next === null
                    ? "end"
                    : next === b + 1
                      ? "→"
                      : `↺ ${def.blocks[next]?.id ?? next}`}
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

      <div className="flex flex-wrap items-center gap-2 text-[11px] text-static">
        <span className="font-mono text-[9px] tracking-[0.14em] text-static/70 uppercase">Session cap</span>
        <OptionalNumber
          value={def.sessionTrials}
          initial={400}
          label="Session trials"
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
        <span>
          {view === null
            ? ""
            : view.sessionEnds
              ? "the blocks end the session by themselves"
              : "the blocks loop or one never ends: only this cap or End Session ends the session"}
        </span>
      </div>
      <ProblemLines diagnostics={session} />

      {selected !== null && def.blocks[selected] && (
        <BlockPanel
          def={def}
          at={selected}
          selections={selections}
          outcomeClasses={outcomeClasses}
          diagnostics={diagnostics}
          stored={stored}
          onChange={onChange}
          onClearStored={onClearStored}
        />
      )}
      <ProblemLines diagnostics={diagnosticsOn(diagnostics, "block")} />
    </div>
  );
}

function BlockPanel({
  def,
  at,
  selections,
  outcomeClasses,
  diagnostics,
  stored,
  onChange,
  onClearStored,
}: {
  def: SpineDefinition;
  at: number;
  selections: readonly string[];
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
  const weighted = WEIGHTED.has(select);

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
        <span className="font-mono text-[10px] tracking-[0.14em] text-static uppercase">Block {block.id}</span>
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => onChange(removeBlock(def, at))}
          className="flex items-center gap-1 text-[11px] text-static transition-colors hover:text-status-error"
        >
          <Trash2 size={11} strokeWidth={1.75} /> Remove block
        </button>
      </div>

      <Field label={weighted ? "Rows and weights" : "Rows"}>
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
                  {row.name || `row ${r + 1}`}
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

      <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-x-4 gap-y-2">
        <Field label="Selection">
          <Select
            value={select}
            label="Selection"
            tone={field("select").length ? "error" : "normal"}
            options={selections.map((s) => ({ value: s, label: s }))}
            onChange={(s) => update({ select: s === "uniform" ? undefined : s, weights: WEIGHTED.has(s) ? block.weights : undefined })}
          />
        </Field>
        <Field label="Trials (or fewest)">
          <OptionalNumber value={block.trials} initial={100} label="Trials" min={1} invalid={field("trials").length > 0} onChange={(trials) => update({ trials })} />
        </Field>
        <Field label="Most trials (drawn)">
          <OptionalNumber value={block.trialsMax} initial={(block.trials ?? 40) + 20} label="Most trials" min={1} invalid={field("trialsMax").length > 0} onChange={(trialsMax) => update({ trialsMax })} />
        </Field>
        <Field label="Criterion: correct of last">
          {block.criterion ? (
            <span className="flex items-center gap-1 text-[11px] text-static">
              <NumberInput value={block.criterion.correct} fallback={8} integer min={1} label="Correct" invalid={field("criterion").length > 0} className="w-[52px]" onChange={(correct) => update({ criterion: { ...block.criterion!, correct } })} />
              of
              <NumberInput value={block.criterion.of} fallback={10} integer min={1} label="Of the last" invalid={field("criterion").length > 0} className="w-[52px]" onChange={(of) => update({ criterion: { ...block.criterion!, of } })} />
              <button type="button" onClick={() => update({ criterion: undefined })} className="hover:text-starlight">×</button>
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
            options={[{ value: "", label: "the following block" }, ...def.blocks.map((b) => ({ value: b.id, label: b.id }))]}
            onChange={(next) => update({ next: next || undefined })}
          />
        </Field>
        <Field label="Correction repeats">
          <OptionalNumber value={block.correction} initial={1} label="Correction" min={0} invalid={field("correction").length > 0} onChange={(correction) => update({ correction, correctionAfter: correction === undefined ? undefined : block.correctionAfter })} />
        </Field>
        {select === "antibias" && (
          <Field label="Bias window">
            <OptionalNumber value={block.biasWindow} initial={10} label="Bias window" min={1} invalid={field("biasWindow").length > 0} unit="responses" onChange={(biasWindow) => update({ biasWindow })} />
          </Field>
        )}
      </div>

      {block.correction !== undefined && (
        <Field label="Repeat after (none chosen: wrong response, false alarm)">
          <SlotSet
            options={outcomeClasses.filter((c) => c !== "correct")}
            value={block.correctionAfter ?? []}
            label="Repeat after"
            invalid={field("correctionAfter").length > 0}
            onChange={(after) => update({ correctionAfter: after.length ? after : undefined })}
          />
        </Field>
      )}

      <Field label="Phase durations in this block">
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          {def.spine.map((p, i) =>
            TIMED.has(p.phase) || p.timeoutMs !== undefined ? (
              <span key={i} className="flex items-center gap-1.5 text-[11px] text-static">
                {i + 1}. {PHASE_LABEL[p.phase] ?? p.phase}
                <OptionalNumber
                  value={block.phaseMs?.[String(i)]}
                  initial={p.ms ?? p.timeoutMs ?? 1000}
                  label={`Phase ${i + 1} in block ${block.id}`}
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
        </span>
      </Field>

      <StoredValues stored={stored} target={{ kind: "block", index: at }} onClear={onClearStored} />
      <ProblemLines diagnostics={diagnosticsOn(diagnostics, "block", at)} />
    </div>
  );
}

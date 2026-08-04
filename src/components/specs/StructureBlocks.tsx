import { useState } from "react";

import { Button } from "@/components/common/controls";
import { FieldRow } from "@/components/common/FieldRow";
import type { PlacedDiagnostics } from "@/lib/specs/diagnostics";
import { topologyOf } from "@/lib/specs/document";
import type { OpInvocation } from "@/lib/specs/operations";
import type {
  ChannelRegistry,
  SpecCapabilities,
  SpecDocument,
  SpecSchema,
  StrobeRegistry,
} from "@/lib/specs/types";
import { useOperation } from "@/lib/specs/useOperation";
import { SpecField } from "./SpecField";
import { SelectRow } from "./rows";

/**
 * The structural blocks for one epoch, and the preflight card that runs one.
 *
 * WHY THIS LIVES IN THE INSPECTOR. docs/specs.md §5 says the Inspector owns
 * the topology knobs outright and that two editing surfaces for one field
 * eventually disagree. A block is a compound edit of exactly those knobs plus
 * the fields that must move with them, so it belongs in the same place or the
 * rule is already broken. The canvas offers a selector for it and nothing
 * more.
 *
 * WHY A CARD RATHER THAN A MODAL. The whole point of a preflight is to see
 * what the machine is about to become; a dialog over the canvas would cover
 * the one thing the operator is deciding from. Apply hands the document back
 * and the 120 ms compile redraws the graph — so the confirmation is the
 * picture, not a toast.
 */
export function StructureBlocks({
  band,
  doc,
  baseline,
  caps,
  schema,
  placed,
  onChange,
}: {
  band: number;
  doc: SpecDocument;
  baseline: SpecDocument;
  caps: SpecCapabilities | null;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  onChange: (next: SpecDocument) => void;
}) {
  const [active, setActive] = useState<OpInvocation | null>(null);

  const blocks = blocksFor(band, doc);
  if (blocks.length === 0) return null;

  if (active !== null) {
    return (
      <Preflight
        invocation={active}
        doc={doc}
        baseline={baseline}
        caps={caps}
        schema={schema}
        placed={placed}
        onCancel={() => setActive(null)}
        onApply={(next) => {
          onChange(next);
          setActive(null);
        }}
      />
    );
  }

  return (
    <section className="flex flex-col gap-1.5 rounded-sm border border-halo px-2.5 py-2">
      <div className="border-b border-halo pb-1">
        <div className="font-mono text-[10px] tracking-wider text-static uppercase">
          Structure
        </div>
        <p className="mt-0.5 text-[10px] leading-relaxed text-static/70">
          Each block moves the knob and everything that must move with it, so the
          machine is never half-changed. You see what it will do before it does it.
        </p>
      </div>
      {blocks.map((block) => (
        <button
          key={block.key}
          type="button"
          onClick={() => setActive(block.invocation)}
          className="rounded-sm border border-halo px-2 py-1.5 text-left transition-colors hover:border-static/60"
        >
          <div className="text-[11px] text-starlight">{block.label}</div>
          <div className="mt-0.5 text-[10px] leading-snug text-static/70">{block.why}</div>
        </button>
      ))}
    </section>
  );
}

interface Block {
  key: string;
  label: string;
  why: string;
  invocation: OpInvocation;
}

/**
 * Which blocks an epoch affords. Read off the document's own knobs so a block
 * that would be a no-op never appears — the op would refuse it anyway, and an
 * offer that always fails is worse than no offer.
 */
function blocksFor(band: number, doc: SpecDocument): Block[] {
  const t = topologyOf(doc) ?? {};
  const gonogo = t["response_mode"] === "go_nogo";
  const stages = typeof t["n_sampling_stages"] === "number" ? t["n_sampling_stages"] : 1;
  const commitHold = t["commit_hold"] !== false;
  const retention = t["retention_delay"] === true;
  const ports = Array.isArray(t["response_ports"]) ? t["response_ports"].map(String) : [];

  const contingency = doc["contingency"];
  const om =
    contingency !== null && typeof contingency === "object"
      ? (contingency as Record<string, unknown>)["outcome_map"]
      : null;
  const correct =
    om !== null && typeof om === "object" ? (om as Record<string, unknown>)["correct"] : null;
  const rewarded =
    correct !== null && typeof correct === "object"
      ? (correct as Record<string, unknown>)["reward"] != null
      : false;

  switch (band) {
    case 1:
      return [
        {
          key: "commit",
          label: commitHold ? "Drop the commitment hold" : "Require a commitment hold",
          why: commitHold
            ? "Entry alone would initiate the trial; an incidental beam-break costs a stimulus."
            : "Separates an incidental beam-break from a committed initiation, before any stimulus is delivered.",
          invocation: { op: "setCommitHold", on: !commitHold },
        },
      ];

    case 2: {
      const blocks: Block[] = [
        {
          key: "add-stim",
          label: "Add a stimulus",
          why: "A new emitter line and its onset strobe — what a stage can present.",
          invocation: { op: "addStimulus" },
        },
        {
          key: "add-stage",
          label: "Add a sampling stage",
          why: "Unrolls the sampling epoch: another hold, a gap before it, and one more stimulus per trial type.",
          invocation: { op: "addSamplingStage" },
        },
      ];
      if (stages > 0) {
        blocks.push({
          key: "remove-stage",
          label: "Remove the last sampling stage",
          why:
            stages === 1
              ? "Leaves engagement running straight into the response window — nothing to discriminate."
              : "Shortens the chain by one stimulus and its gap.",
          invocation: { op: "removeSamplingStage" },
        });
      }
      blocks.push({
        key: "retention",
        label: retention ? "Remove the retention delay" : "Insert a retention delay",
        why: retention
          ? "The response window opens as soon as the animal withdraws."
          : "An unfilled delay between sampling and responding — the working-memory load.",
        invocation: { op: "setRetentionDelay", on: !retention },
      });
      return blocks;
    }

    case 3: {
      const blocks: Block[] = [
        {
          key: "mode",
          label: gonogo ? "Switch to n-alternative choice" : "Switch to go/no-go",
          why: gonogo
            ? "Restores the response hold and the wrong/omission/hold-fail branches; every trial type needs a target again."
            : "Success becomes withholding for the whole window, and any port entry is a false alarm.",
          invocation: {
            op: "setResponseMode",
            mode: gonogo ? "n_alternative" : "go_nogo",
          },
        },
        {
          key: "add-port",
          label: "Add a response option",
          why: "Another port the animal can answer at.",
          invocation: { op: "addResponseOption" },
        },
        {
          key: "add-tt",
          label: "Add a trial type",
          why: "Another stimulus-to-target mapping in the pool.",
          invocation: { op: "addTrialType" },
        },
      ];
      for (const port of ports) {
        if (ports.length <= 1) break;
        blocks.push({
          key: `remove-${port}`,
          label: `Remove ${port} from the response window`,
          why: "Trial types targeting it will need a new target.",
          invocation: { op: "removeResponseOption", port },
        });
      }
      return blocks;
    }

    case 4:
      // Not a knob and not a capability — `outcome_map.correct.reward` is a
      // contingency field, and it is the one of those that changes the graph's
      // SHAPE: null omits the delivery PULSE and the consumption WAIT_EXIT
      // from this epoch entirely.
      return [
        {
          key: "reward",
          label: rewarded ? "Stop rewarding a correct trial" : "Reward a correct trial",
          why: rewarded
            ? "Removes the delivery and consumption states — the choice is still recorded, nothing is delivered."
            : "Adds the delivery PULSE and the consumption wait to this epoch, through each port's own line.",
          invocation: { op: "setCorrectRewarded", on: !rewarded },
        },
      ];

    default:
      return [];
  }
}

function Preflight({
  invocation,
  doc,
  baseline,
  caps,
  schema,
  placed,
  onCancel,
  onApply,
}: {
  invocation: OpInvocation;
  doc: SpecDocument;
  baseline: SpecDocument;
  caps: SpecCapabilities | null;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  onCancel: () => void;
  onApply: (next: SpecDocument) => void;
}) {
  const session = useOperation(
    invocation,
    doc,
    caps,
    schema.channels as ChannelRegistry,
    schema.strobes as StrobeRegistry,
  );
  const preflight = session.result?.preflight ?? null;

  return (
    <section className="flex flex-col gap-2 rounded-sm border border-pulsar/60 px-2.5 py-2">
      <div className="border-b border-halo pb-1">
        <div className="font-mono text-[10px] tracking-wider text-starlight uppercase">
          {preflight?.title ?? "…"}
        </div>
      </div>

      {session.error && (
        <p className="text-[10px] leading-relaxed" style={{ color: "var(--color-status-error)" }}>
          {session.error}
        </p>
      )}

      {preflight === null && !session.error && (
        <p className="text-[10px] text-static/70">Working out what this would change…</p>
      )}

      {preflight?.blocked != null && (
        <p className="text-[11px] leading-relaxed text-static">{preflight.blocked}</p>
      )}

      {preflight !== null && preflight.blocked === null && (
        <>
          {preflight.questions.length > 0 && (
            <div className="flex flex-col gap-1.5">
              {preflight.questions.map((q) => {
                const value = session.answers[q.id] ?? q.suggested;
                const unanswered =
                  q.mandatory && (value === null || value === undefined);
                return (
                  <div key={q.id} className="flex flex-col gap-0.5">
                    {q.options !== null ? (
                      <SelectRow
                        label={q.label}
                        help={q.why}
                        value={typeof value === "string" ? value : null}
                        baseline={null}
                        options={q.options}
                        error={unanswered ? "Pick a value to continue." : undefined}
                        onChange={(next) => session.answer(q.id, next)}
                      />
                    ) : (
                      /* Free values render through the presentation overlay
                      when it describes them, so a millisecond field here is
                      the same field it is in the form — label, unit and help
                      included. */
                      <OverlayQuestion
                        overlayKey={q.overlayKey}
                        label={q.label}
                        help={q.why}
                        schema={schema}
                        doc={doc}
                        baseline={baseline}
                        placed={placed}
                        value={value}
                        error={unanswered ? "Enter a value to continue." : undefined}
                        onChange={(next) => session.answer(q.id, next)}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="flex flex-col gap-0.5 border-t border-halo pt-1.5">
            <div className="font-mono text-[9.5px] tracking-wide text-static/60 uppercase">
              This will
            </div>
            {preflight.changes.length === 0 && (
              <p className="text-[10px] text-static/70">— nothing yet</p>
            )}
            {preflight.changes.map((change, i) => (
              <p
                key={`${change.path}:${i}`}
                className="text-[10px] leading-snug text-static"
              >
                <span
                  className={
                    change.kind === "delete"
                      ? "text-[var(--color-status-error)]"
                      : change.kind === "keep-greyed"
                        ? "text-static/50"
                        : "text-pulsar"
                  }
                >
                  {change.kind === "delete" ? "−" : change.kind === "keep-greyed" ? "·" : "+"}
                </span>{" "}
                {change.label}
              </p>
            ))}
          </div>

          {preflight.warnings.map((warning) => (
            <p key={warning} className="text-[10px] leading-snug text-static/80">
              {warning}
            </p>
          ))}
        </>
      )}

      <div className="flex justify-end gap-2 pt-0.5">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          variant="primary"
          disabled={!session.ready || session.result === null}
          onClick={() => session.result && onApply(session.result.doc)}
        >
          Apply
        </Button>
      </div>
    </section>
  );
}

/** A free-valued question rendered by the overlay's own widget when it knows
 * the key, and as a plain number/text row when it doesn't. */
function OverlayQuestion({
  overlayKey,
  label,
  help,
  schema,
  doc,
  baseline,
  placed,
  value,
  error,
  onChange,
}: {
  overlayKey: string;
  label: string;
  help: string;
  schema: SpecSchema;
  doc: SpecDocument;
  baseline: SpecDocument;
  placed: PlacedDiagnostics | null;
  value: unknown;
  error?: string | undefined;
  onChange: (next: unknown) => void;
}) {
  const meta = schema.overlay.fields[overlayKey];
  if (meta) {
    return (
      <SpecField
        // The answer is not in the document yet, so there is no path to anchor
        // diagnostics to — an empty one is correct rather than a placeholder.
        path=""
        overlayKey={overlayKey}
        meta={{ ...meta, label, help }}
        value={value}
        baseline={null}
        schema={schema}
        doc={doc}
        placed={placed}
        onChange={onChange}
      />
    );
  }
  void baseline;
  return (
    <FieldRow
      label={label}
      help={help}
      type={typeof value === "number" ? "int" : "string"}
      value={value}
      fallback={value ?? ""}
      baseline={null}
      error={error}
      onChange={onChange}
    />
  );
}

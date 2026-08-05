import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/common/controls";
import type { PlacedDiagnostics } from "@/lib/specs/diagnostics";
import { getAt, setAt } from "@/lib/specs/document";
import { runOp } from "@/lib/specs/operations";
import type {
  ChannelRegistry,
  SpecCapabilities,
  SpecDocument,
  SpecSchema,
  StrobeRegistry,
} from "@/lib/specs/types";
import { SpecField } from "../SpecField";
import { ChipsRow } from "../rows";

const POLICY_FIELDS = [
  { path: "policy.selection.mode", overlayKey: "policy.selection.mode" },
  { path: "policy.n_trials", overlayKey: "policy.n_trials" },
  { path: "policy.seed", overlayKey: "policy.seed" },
];

/**
 * How the session runs: how trials are drawn, how many, and what ramps.
 *
 * None of this changes the machine — layer 4 only — which is why it is the last
 * step rather than one interleaved with the epochs.
 */
export function SessionStep({
  doc,
  caps,
  schema,
  placed,
  suggestedRamp,
  onChange,
}: {
  doc: SpecDocument;
  caps: SpecCapabilities | null;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  /** The timing ids this paradigm says a ramp moves — a suggestion, never
   * applied on arrival. See `ParadigmSummary.ramped`. */
  suggestedRamp: readonly string[];
  onChange: (next: SpecDocument) => void;
}) {
  return (
    <>
      <div className="flex flex-col gap-1.5">
        {POLICY_FIELDS.map(({ path, overlayKey }) => {
          const meta = schema.overlay.fields[overlayKey];
          if (!meta) return null;
          return (
            <SpecField
              key={path}
              path={path}
              overlayKey={overlayKey}
              meta={meta}
              value={getAt(doc, path)}
              baseline={getAt(doc, path)}
              schema={schema}
              doc={doc}
              placed={placed}
              onChange={(next) => onChange(setAt(doc, path, next))}
            />
          );
        })}
      </div>
      <RampStep
        doc={doc}
        caps={caps}
        schema={schema}
        placed={placed}
        suggestedRamp={suggestedRamp}
        onChange={onChange}
      />
    </>
  );
}

/**
 * The trial a stage row takes over at.
 *
 * COMMITS ON BLUR, not per keystroke, and that is not a preference. The op
 * re-sorts the schedule so the document is never out of order — which means a
 * row physically moves as its number changes, remounting the input. Committing
 * per keystroke made "100" impossible to type: after the `1` the row sorted to
 * the front and took the focus with it.
 */
function StageTrialInput({
  index,
  value,
  onCommit,
}: {
  index: number;
  value: number;
  onCommit: (at: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  // The document is the authority — an op elsewhere (adding a row, removing
  // one) can move this row's number without the input being touched.
  useEffect(() => setDraft(String(value)), [value]);

  function commit() {
    const n = Number(draft);
    if (draft.trim() === "" || !Number.isInteger(n) || n < 0) {
      setDraft(String(value));
      return;
    }
    if (n !== value) onCommit(n);
  }

  return (
    <label className="flex items-center gap-1.5">
      <span className="font-mono text-[10px] whitespace-nowrap text-static">
        from trial
      </span>
      <input
        aria-label={`Stage ${index + 1} starts at trial`}
        className="w-16 rounded-sm border border-halo bg-nebula px-1.5 py-0.5 font-mono text-[10px] text-starlight"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") setDraft(String(value));
        }}
      />
    </label>
  );
}

/**
 * The shaping ramp, as two questions rather than a nested array.
 *
 * WHICH durations move, then WHEN they move. Splitting it that way is what
 * makes the invariant enforceable: every row has to carry every ramped id,
 * because the firmware rewrites the whole set at a boundary and a row that
 * omits one does not leave it alone — it reverts to whatever the row before
 * left. Editing a raw array of objects would make that trap reachable in one
 * keystroke; here it is unreachable, because the ops fill the rows.
 */
function RampStep({
  doc,
  caps,
  schema,
  placed,
  suggestedRamp,
  onChange,
}: {
  doc: SpecDocument;
  caps: SpecCapabilities | null;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  suggestedRamp: readonly string[];
  onChange: (next: SpecDocument) => void;
}) {
  const rows = useMemo(() => {
    const raw = (doc["policy"] as { stage_schedule?: unknown })?.stage_schedule;
    return Array.isArray(raw) ? (raw as Array<Record<string, unknown>>) : [];
  }, [doc]);

  const rampable = useMemo(
    () =>
      (Array.isArray(doc["timing"]) ? (doc["timing"] as Array<Record<string, unknown>>) : [])
        .map((r) => String(r["id"]))
        .filter((id) => id !== "t_zero" && id !== "t_poll_interval"),
    [doc],
  );

  const ramped = useMemo(() => {
    const seen = new Set<string>();
    for (const row of rows) {
      for (const id of Object.keys((row["set"] as Record<string, unknown>) ?? {})) {
        seen.add(id);
      }
    }
    return rampable.filter((id) => seen.has(id));
  }, [rows, rampable]);

  const ctx = {
    doc,
    caps: caps ?? EMPTY_CAPS,
    next: caps ?? EMPTY_CAPS,
    channels: (schema.channels ?? {}) as ChannelRegistry,
    strobes: (schema.strobes ?? {}) as StrobeRegistry,
  };

  return (
    <div className="flex flex-col gap-2">
      <ChipsRow
        label="Durations that ramp"
        help="Chosen once and carried by every row — a row that omits one reverts it."
        values={ramped}
        baseline={[]}
        options={rampable.map((id) => ({ value: id, label: id }))}
        onChange={(ids) => onChange(runOp(ctx, { op: "setRampedIds", ids }, {}).doc)}
      />

      {/*
       * THE PARADIGM'S OWN SUGGESTION, offered rather than applied.
       *
       * A paradigm names which durations a shaping ramp moves and deliberately
       * declares neither the boundaries nor the per-stage values, because those
       * are the operator's. So this cannot be pre-applied without inventing
       * them — and it was doing nothing at all until now, which meant `shaping`
       * named five ramped ids and opened this step blank.
       */}
      {ramped.length === 0 && suggestedRamp.length > 0 && (
        <div className="flex flex-col gap-1 rounded-sm border border-halo px-2.5 py-2">
          <p className="text-[10.5px] leading-relaxed text-static">
            This shape usually ramps{" "}
            <span className="font-mono text-static/80">
              {suggestedRamp.filter((id) => rampable.includes(id)).join(", ")}
            </span>{" "}
            — you still choose the trials each stage takes over at.
          </p>
          <Button
            variant="ghost"
            onClick={() =>
              onChange(
                runOp(
                  ctx,
                  { op: "setRampedIds", ids: suggestedRamp.filter((id) => rampable.includes(id)) },
                  {},
                ).doc,
              )
            }
          >
            Ramp these
          </Button>
        </div>
      )}

      {ramped.length > 0 && (
        <div className="flex flex-col gap-1.5 rounded-sm border border-halo px-2.5 py-2">
          <div className="font-mono text-[10px] tracking-wider text-static uppercase">
            Stages
          </div>
          {rows.length === 0 && <p className="text-[10px] text-static/70">No stages yet.</p>}
          {rows.map((row, i) => (
            <div
              key={i}
              className="flex flex-col gap-1 border-t border-halo pt-1.5 first:border-0"
            >
              <div className="flex items-center justify-between gap-2">
                {/*
                 * `at_trial` IS EDITABLE, and it has to be. The step's own blurb
                 * promises "which durations move, then the trials they move at";
                 * seeding a row and then rendering its trial number as static
                 * text delivers half of that. The seeded spacing is a guess at a
                 * schedule, not the schedule — the lab's real shaping ramp
                 * switches at 0/20/25/50/100, which the even spacing never hits.
                 *
                 * The op re-sorts on every edit, so typing a number that lands a
                 * row out of order fixes the order rather than tripping TG205 —
                 * which does not fail, it applies the wrong row.
                 */}
                <StageTrialInput
                  index={i}
                  value={Number(row["at_trial"]) || 0}
                  onCommit={(at) =>
                    onChange(runOp(ctx, { op: "setStageTrial", index: i }, { at_trial: at }).doc)
                  }
                />
                <Button
                  variant="ghost"
                  onClick={() => onChange(runOp(ctx, { op: "removeStageRow", index: i }, {}).doc)}
                >
                  Remove
                </Button>
              </div>
              {ramped.map((id) => {
                const path = `policy.stage_schedule[${i}].set.${id}`;
                const meta = schema.overlay.fields["timing[].ms"];
                if (!meta) return null;
                return (
                  <SpecField
                    key={id}
                    path={path}
                    overlayKey="timing[].ms"
                    meta={{ ...meta, label: id }}
                    value={getAt(doc, path)}
                    baseline={getAt(doc, path)}
                    schema={schema}
                    doc={doc}
                    placed={placed}
                    onChange={(next) => onChange(setAt(doc, path, next))}
                  />
                );
              })}
            </div>
          ))}
          <Button
            variant="ghost"
            onClick={() => onChange(runOp(ctx, { op: "addStageRow" }, {}).doc)}
          >
            Add a stage
          </Button>
        </div>
      )}
    </div>
  );
}

//: A stand-in while `capabilities()` is in flight. The ramp ops read neither
//: field — they touch layer 4 only — so this cannot change what they produce.
const EMPTY_CAPS: SpecCapabilities = {
  outcomeClasses: [],
  requiredTiming: [],
  knobs: [],
  template: "four_epoch",
  templateVersion: 2,
  timingHelp: {},
  outcomeHelp: {},
};

import { Plus, Trash2 } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/common/controls";
import type { PlacedDiagnostics } from "@/lib/specs/diagnostics";
import { deleteAt, getAt, setAt } from "@/lib/specs/document";
import { groupFields, keyedKey } from "@/lib/specs/overlay";
import type {
  OverlayField,
  SpecCapabilities,
  SpecDocument,
  SpecSchema,
} from "@/lib/specs/types";
import { SpecField } from "./SpecField";

/**
 * The schema-driven spec editor (Stage 1 of the roadmap's Phase 6).
 *
 * Structure comes from three places and nothing is hardcoded per-task:
 * the OVERLAY says what a field is called and which widget edits it; the
 * DOCUMENT says which rows exist; and CAPABILITIES says which rows this
 * topology needs. The rule that keeps responsibilities straight:
 * `capabilities()` decides which rows EXIST; the compiler decides which are
 * VALID. The form never re-implements a lint rule.
 *
 * Two gating behaviours worth naming (both from the roadmap, both load-bearing):
 * - Timing rows render in `requiredTiming` order. A row the document carries
 *   but the topology no longer needs moves to a greyed "no longer used" block
 *   with a Remove button — NEVER hidden, because hiding silently orphans a
 *   value the operator typed.
 * - Outcome cards are exactly `outcomeClasses`. A class the topology produces
 *   but the document lacks renders as an empty required card — the compiler's
 *   own TG302 lands on the section to say so.
 */
export function SpecForm({
  doc,
  baseline,
  schema,
  caps,
  placed,
  onChange,
}: {
  doc: SpecDocument;
  /** The document as loaded — drives every changed-dot. */
  baseline: SpecDocument;
  schema: SpecSchema;
  caps: SpecCapabilities | null;
  placed: PlacedDiagnostics | null;
  onChange: (next: SpecDocument) => void;
}) {
  const overlay = schema.overlay;

  const field = (path: string, overlayKey: string, meta: OverlayField | undefined) => {
    if (!meta) return null;
    return (
      <SpecField
        key={path}
        path={path}
        overlayKey={overlayKey}
        meta={meta}
        value={getAt(doc, path)}
        baseline={getAt(baseline, path)}
        schema={schema}
        doc={doc}
        placed={placed}
        onChange={(next) => onChange(setAt(doc, path, next))}
      />
    );
  };

  /** Fields of one overlay group whose keys are concrete paths (no wildcard). */
  const objectSection = (groupId: string) => {
    const rows = groupFields(overlay, groupId).filter(([key]) => !key.includes("*"));
    return rows.map(([key, meta]) => field(key, key, meta));
  };

  const section = (groupId: string, children: ReactNode) => {
    const group = overlay.groups.find((g) => g.id === groupId);
    const sectionPath = Object.entries(overlay.sections).find(
      ([, s]) => s.group === groupId,
    )?.[0];
    const sectionDiags = sectionPath ? placed?.bySection.get(sectionPath) : undefined;
    return (
      <section key={groupId} className="flex flex-col gap-1.5">
        <header className="border-b border-halo pb-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-mono text-[10px] uppercase tracking-wider text-static">
              {group?.label ?? groupId}
            </span>
          </div>
          {group?.help && (
            <p className="mt-0.5 text-[10px] leading-snug text-static/70">{group.help}</p>
          )}
          {sectionDiags?.map((d) => (
            <p
              key={`${d.code}-${d.message}`}
              className="mt-1 text-[10px] leading-snug"
              style={{ color: "var(--color-status-error)" }}
              title={d.help ?? undefined}
            >
              {d.code} · {d.message}
            </p>
          ))}
        </header>
        {children}
      </section>
    );
  };

  // --- timing, gated by requiredTiming ------------------------------------

  const timing = Array.isArray(doc["timing"]) ? (doc["timing"] as unknown[]) : [];
  const timingIds = timing.map((t) =>
    t !== null && typeof t === "object" ? String((t as Record<string, unknown>)["id"] ?? "") : "",
  );
  const required = caps?.requiredTiming ?? null;
  // Required order first (the template's own), then declared-but-unrequired in
  // document order. With no capabilities answer yet, everything is "required".
  const requiredRows = required
    ? required.map((id) => timingIds.indexOf(id)).filter((i) => i >= 0)
    : timing.map((_, i) => i);
  const extraRows = required
    ? timing.map((_, i) => i).filter((i) => !required.includes(timingIds[i] ?? ""))
    : [];
  const missingIds = required ? required.filter((id) => !timingIds.includes(id)) : [];

  const timingRow = (index: number, dimmed: boolean) => (
    <div
      key={`timing-${index}`}
      className={`rounded-sm border border-halo px-2.5 py-2 ${dimmed ? "opacity-55" : ""}`}
    >
      <div className="flex items-center justify-between gap-2 pb-1">
        <span className="font-mono text-[10px] text-static/70">[{index}]</span>
        {dimmed && (
          <Button
            variant="ghost"
            onClick={() => onChange(deleteAt(doc, `timing[${index}]`))}
            title="Remove — this topology no longer uses it"
          >
            <Trash2 size={12} strokeWidth={1.75} />
          </Button>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        {(["id", "ms", "wire_key", "note"] as const).map((sub) =>
          field(`timing[${index}].${sub}`, `timing[].${sub}`, overlay.fields[`timing[].${sub}`]),
        )}
      </div>
    </div>
  );

  // --- keyed collections ---------------------------------------------------

  /** Rows addressed by map key or by their `id` — the diagnostics grammar. */
  const keyedRows = (
    sectionPath: string,
    subfields: string[],
    rows: Array<{ anchor: string; title: string; basePath: string; missing?: boolean }>,
    extra?: (row: { anchor: string; basePath: string }) => ReactNode,
  ) =>
    rows.map((row) => {
      const rowDiags = placed?.byRow.get(`${sectionPath}.${row.anchor}`);
      return (
        <div
          key={row.anchor}
          className={`rounded-sm border border-halo px-2.5 py-2 ${row.missing ? "border-dashed" : ""}`}
        >
          <div className="flex items-baseline justify-between gap-2 pb-1">
            <span className="font-mono text-[11px] text-starlight">{row.title}</span>
            {row.missing && (
              <span className="text-[10px]" style={{ color: "var(--color-status-warning)" }}>
                required by this topology
              </span>
            )}
          </div>
          {rowDiags?.map((d) => (
            <p
              key={`${d.code}-${d.message}`}
              className="pb-1 text-[10px] leading-snug"
              style={{ color: "var(--color-status-error)" }}
              title={d.help ?? undefined}
            >
              {d.code} · {d.message}
            </p>
          ))}
          <div className="flex flex-col gap-1.5">
            {subfields.map((sub) =>
              field(
                `${row.basePath}.${sub}`,
                keyedKey(sectionPath, sub),
                overlay.fields[keyedKey(sectionPath, sub)],
              ),
            )}
            {extra?.(row)}
          </div>
        </div>
      );
    });

  const stimuli = Array.isArray(getAt(doc, "contingency.stimuli"))
    ? (getAt(doc, "contingency.stimuli") as unknown[])
    : [];
  const trialTypes = Array.isArray(getAt(doc, "contingency.trial_types"))
    ? (getAt(doc, "contingency.trial_types") as unknown[])
    : [];
  const ports = ((getAt(doc, "contingency.ports") ?? {}) as Record<string, unknown>) || {};
  const outcomes = ((getAt(doc, "contingency.outcome_map") ?? {}) as Record<string, unknown>) || {};

  const outcomeClasses = caps?.outcomeClasses ?? Object.keys(outcomes);
  const staleOutcomes = Object.keys(outcomes).filter((k) => !outcomeClasses.includes(k));

  const idOf = (row: unknown, fallback: string) =>
    row !== null && typeof row === "object" && "id" in (row as Record<string, unknown>)
      ? String((row as Record<string, unknown>)["id"])
      : fallback;

  return (
    <div className="flex flex-col gap-5">
      {section("identity", objectSection("identity"))}
      {section("meta", objectSection("meta"))}
      {section("topology", objectSection("topology"))}

      {section(
        "timing",
        <>
          {requiredRows.map((i) => timingRow(i, false))}
          {missingIds.map((id) => (
            <div
              key={`missing-${id}`}
              className="flex items-center justify-between rounded-sm border border-dashed border-halo px-2.5 py-2"
            >
              <span className="font-mono text-[11px] text-static">
                {id}
                <span className="ml-2 text-[10px]" style={{ color: "var(--color-status-warning)" }}>
                  required by this topology
                </span>
              </span>
              <Button
                onClick={() =>
                  onChange(setAt(doc, `timing[${timing.length}]`, { id, ms: 0 }))
                }
              >
                <Plus size={12} strokeWidth={1.75} />
                Add
              </Button>
            </div>
          ))}
          {extraRows.length > 0 && (
            <>
              <p className="pt-1 text-[10px] uppercase tracking-wider text-static/60">
                No longer used by this topology
              </p>
              {extraRows.map((i) => timingRow(i, true))}
            </>
          )}
        </>,
      )}

      {section(
        "stimuli",
        <>
          {keyedRows(
            "contingency.stimuli",
            ["id", "emitter", "on_code", "note"],
            stimuli.map((row, i) => ({
              anchor: idOf(row, `[${i}]`),
              title: idOf(row, `stimulus ${i}`),
              basePath: `contingency.stimuli[${i}]`,
            })),
          )}
          <AddRow
            label="Add stimulus"
            onClick={() =>
              onChange(
                setAt(doc, `contingency.stimuli[${stimuli.length}]`, {
                  id: `stim${stimuli.length + 1}`,
                  emitter: null,
                  on_code: null,
                }),
              )
            }
          />
        </>,
      )}

      {section(
        "ports",
        <>
          {keyedRows(
            "contingency.ports",
            [
              "channel",
              "enter_code",
              "error_code",
              "break_code",
              "exit_code",
              "reward_line",
              "reward_duration",
              "reward_code",
              "reward_stop_code",
              "note",
            ],
            Object.keys(ports).map((name) => ({
              anchor: name,
              title: name,
              basePath: `contingency.ports.${name}`,
            })),
          )}
          <AddRow
            label="Add port"
            onClick={() => {
              const name = nextName("port", Object.keys(ports));
              onChange(setAt(doc, `contingency.ports.${name}`, { channel: null }));
            }}
          />
        </>,
      )}

      {section(
        "trial_types",
        <>
          {keyedRows(
            "contingency.trial_types",
            ["id", "stages", "target", "weight", "note"],
            trialTypes.map((row, i) => ({
              anchor: idOf(row, `[${i}]`),
              title: idOf(row, `trial type ${i}`),
              basePath: `contingency.trial_types[${i}]`,
            })),
          )}
          <AddRow
            label="Add trial type"
            onClick={() =>
              onChange(
                setAt(doc, `contingency.trial_types[${trialTypes.length}]`, {
                  id: `tt${trialTypes.length + 1}`,
                  stages: [],
                  target: null,
                }),
              )
            }
          />
        </>,
      )}

      {section(
        "outcomes",
        <>
          {keyedRows(
            "contingency.outcome_map",
            ["trigger", "terminal", "delay", "reward", "strobe", "note"],
            outcomeClasses.map((name) => ({
              anchor: name,
              title: name,
              basePath: `contingency.outcome_map.${name}`,
              missing: !(name in outcomes),
            })),
          )}
          {staleOutcomes.length > 0 && (
            <>
              <p className="pt-1 text-[10px] uppercase tracking-wider text-static/60">
                No longer produced by this topology
              </p>
              {keyedRows(
                "contingency.outcome_map",
                ["trigger", "terminal", "delay", "reward", "strobe", "note"],
                staleOutcomes.map((name) => ({
                  anchor: name,
                  title: name,
                  basePath: `contingency.outcome_map.${name}`,
                })),
                (row) => (
                  <div className="pt-1">
                    <Button
                      variant="ghost"
                      onClick={() => onChange(deleteAt(doc, row.basePath))}
                      title="Remove — this topology cannot produce it"
                    >
                      <Trash2 size={12} strokeWidth={1.75} />
                      Remove
                    </Button>
                  </div>
                ),
              )}
            </>
          )}
        </>,
      )}

      {(() => {
        const contextRows = Array.isArray(getAt(doc, "contingency.context_schedule"))
          ? (getAt(doc, "contingency.context_schedule") as unknown[])
          : [];
        // Reversals are rare; an empty schedule doesn't earn a section, and
        // TG230 (context schedules are unsupported on-board today) lands on
        // the section header when one exists.
        if (contextRows.length === 0) return null;
        return section(
          "context",
          contextRows.map((row, i) => (
            <div key={`context-${i}`} className="rounded-sm border border-halo px-2.5 py-2">
              <div className="flex items-center justify-between gap-2 pb-1">
                <span className="font-mono text-[10px] text-static/70">row {i}</span>
                <Button
                  variant="ghost"
                  onClick={() => onChange(deleteAt(doc, `contingency.context_schedule[${i}]`))}
                  title="Remove this reversal"
                >
                  <Trash2 size={12} strokeWidth={1.75} />
                </Button>
              </div>
              <div className="flex flex-col gap-1.5">
                {field(
                  `contingency.context_schedule[${i}].at_trial`,
                  "contingency.context_schedule[].at_trial",
                  overlay.fields["contingency.context_schedule[].at_trial"],
                )}
                {field(
                  `contingency.context_schedule[${i}].context`,
                  "contingency.context_schedule[].context",
                  overlay.fields["contingency.context_schedule[].context"],
                )}
                {Object.keys(
                  (row !== null && typeof row === "object"
                    ? ((row as Record<string, unknown>)["targets"] ?? {})
                    : {}) as Record<string, unknown>,
                ).map((tt) =>
                  field(
                    `contingency.context_schedule[${i}].targets.${tt}`,
                    "contingency.context_schedule[].targets.*",
                    withLabel(overlay.fields["contingency.context_schedule[].targets.*"], tt),
                  ),
                )}
              </div>
            </div>
          )),
        );
      })()}

      {section("selection", objectSection("selection"))}

      {section(
        "correction",
        Object.keys(ports).map((name) =>
          field(
            `policy.correction.budgets.${name}`,
            "policy.correction.budgets.*",
            withLabel(overlay.fields["policy.correction.budgets.*"], name),
          ),
        ),
      )}

      {section("penalty", objectSection("penalty"))}

      {section(
        "schedule",
        <>
          {(Array.isArray(getAt(doc, "policy.stage_schedule"))
            ? (getAt(doc, "policy.stage_schedule") as unknown[])
            : []
          ).map((row, i) => (
            <div key={`stage-${i}`} className="rounded-sm border border-halo px-2.5 py-2">
              <div className="flex items-center justify-between gap-2 pb-1">
                <span className="font-mono text-[10px] text-static/70">row {i}</span>
                <Button
                  variant="ghost"
                  onClick={() => onChange(deleteAt(doc, `policy.stage_schedule[${i}]`))}
                  title="Remove this stage row"
                >
                  <Trash2 size={12} strokeWidth={1.75} />
                </Button>
              </div>
              <div className="flex flex-col gap-1.5">
                {field(
                  `policy.stage_schedule[${i}].at_trial`,
                  "policy.stage_schedule[].at_trial",
                  overlay.fields["policy.stage_schedule[].at_trial"],
                )}
                {Object.keys(
                  (row !== null && typeof row === "object"
                    ? ((row as Record<string, unknown>)["set"] ?? {})
                    : {}) as Record<string, unknown>,
                ).map((tid) =>
                  field(
                    `policy.stage_schedule[${i}].set.${tid}`,
                    "policy.stage_schedule[].set.*",
                    withLabel(overlay.fields["policy.stage_schedule[].set.*"], tid),
                  ),
                )}
              </div>
            </div>
          ))}
        </>,
      )}

      {section("session", objectSection("session"))}
    </div>
  );
}

function AddRow({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <div>
      <Button variant="ghost" onClick={onClick}>
        <Plus size={12} strokeWidth={1.75} />
        {label}
      </Button>
    </div>
  );
}

function withLabel(
  meta: OverlayField | undefined,
  label: string,
): OverlayField | undefined {
  return meta ? { ...meta, label: `${label} — ${meta.label}` } : undefined;
}

function nextName(prefix: string, taken: string[]): string {
  let n = taken.length + 1;
  while (taken.includes(`${prefix}_${n}`)) n += 1;
  return `${prefix}_${n}`;
}

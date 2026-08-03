import { useMemo } from "react";

import { FieldRow } from "@/components/common/FieldRow";
import { errorsFor, firstError, type PlacedDiagnostics } from "@/lib/specs/diagnostics";
import type { SpecDocument } from "@/lib/specs/types";
import type { OverlayField, SpecSchema } from "@/lib/specs/types";
import { ChipsRow, SelectRow } from "./rows";

/**
 * One spec field, dispatched by the overlay's `widget`.
 *
 * The rule that shapes everything here: PICKER OPTIONS COME FROM THE
 * REGISTRIES OR THE DOCUMENT, NEVER FROM A LIST IN THIS FILE. A strobe the
 * vocabulary doesn't name or a channel the pinout doesn't carry would compile
 * to a TG210/TG223 anyway — offering it would be manufacturing an error.
 */
export function SpecField({
  path,
  overlayKey,
  meta,
  value,
  baseline,
  schema,
  doc,
  placed,
  onChange,
}: {
  /** Concrete path — `timing[3].ms` — for diagnostics lookup. */
  path: string;
  /** Overlay key — `timing[].ms`. */
  overlayKey: string;
  meta: OverlayField;
  value: unknown;
  baseline: unknown;
  schema: SpecSchema;
  doc: SpecDocument;
  placed: PlacedDiagnostics | null;
  onChange: (next: unknown) => void;
}) {
  const error = placed ? firstError(errorsFor(placed, path, overlayKey)) : undefined;

  const strobeOptions = useMemo(() => {
    const codes = (schema.strobes as { codes?: Record<string, { code: number }> }).codes ?? {};
    return Object.entries(codes)
      .sort(([, a], [, b]) => a.code - b.code)
      .map(([name, entry]) => ({ value: name, label: `${name} (${entry.code})` }));
  }, [schema.strobes]);

  const channelOptions = useMemo(() => {
    const channels =
      (schema.channels as { channels?: Record<string, { kind: string; index: number }> })
        .channels ?? {};
    return Object.entries(channels)
      .filter(([, c]) => !meta.channelKind || c.kind === meta.channelKind)
      .sort(([, a], [, b]) => a.index - b.index)
      .map(([name, c]) => ({ value: name, label: `${name} (pin ${c.index})` }));
  }, [schema.channels, meta.channelKind]);

  const timingIds = useMemo(() => {
    const timing = doc["timing"];
    if (!Array.isArray(timing)) return [];
    return timing
      .filter((t): t is { id: string } => t !== null && typeof t === "object" && "id" in t)
      .map((t) => ({ value: String(t.id), label: String(t.id) }));
  }, [doc]);

  const portNames = useMemo(() => {
    const contingency = doc["contingency"];
    const ports =
      contingency !== null && typeof contingency === "object"
        ? (contingency as Record<string, unknown>)["ports"]
        : null;
    if (ports === null || typeof ports !== "object") return [];
    return Object.keys(ports as Record<string, unknown>).map((name) => ({
      value: name,
      label: name,
    }));
  }, [doc]);

  const stimulusIds = useMemo(() => {
    const contingency = doc["contingency"];
    const stimuli =
      contingency !== null && typeof contingency === "object"
        ? (contingency as Record<string, unknown>)["stimuli"]
        : null;
    if (!Array.isArray(stimuli)) return [];
    return stimuli
      .filter((s): s is { id: string } => s !== null && typeof s === "object" && "id" in s)
      .map((s) => ({ value: String(s.id), label: String(s.id) }));
  }, [doc]);

  switch (meta.widget) {
    case "number":
    case "stepper":
      return (
        <FieldRow
          label={meta.label}
          help={meta.help}
          unit={meta.unit}
          type={Number.isInteger(meta.step) || meta.step === undefined ? "int" : "float"}
          value={value}
          fallback={baseline ?? 0}
          baseline={baseline}
          error={error}
          onChange={onChange}
        />
      );

    case "bool":
      return (
        <FieldRow
          label={meta.label}
          help={meta.help}
          type="bool"
          value={value}
          fallback={baseline ?? false}
          baseline={baseline}
          error={error}
          onChange={onChange}
        />
      );

    case "text":
    case "textarea":
    case "seed":
      return (
        <FieldRow
          label={meta.label}
          help={meta.help}
          type="string"
          value={value}
          fallback={baseline ?? ""}
          baseline={baseline}
          error={error}
          width={meta.widget === "textarea" ? "w-[260px]" : undefined}
          onChange={(next) => onChange(coerceSeed(meta, next))}
        />
      );

    case "enum":
      return (
        <SelectRow
          label={meta.label}
          help={meta.help}
          value={typeof value === "string" ? value : null}
          baseline={baseline}
          options={(meta.options ?? []).map((o) => ({
            value: o.value,
            label: o.label,
            help: o.help,
          }))}
          error={error}
          onChange={onChange}
        />
      );

    case "strobe":
      return (
        <SelectRow
          label={meta.label}
          help={meta.help}
          value={typeof value === "string" ? value : null}
          baseline={baseline}
          options={strobeOptions}
          error={error}
          nullable={meta.nullable === true}
          nullLabel="— silent (no strobe) —"
          onChange={onChange}
        />
      );

    case "channel":
      return (
        <SelectRow
          label={meta.label}
          help={meta.help}
          value={typeof value === "string" ? value : null}
          baseline={baseline}
          options={channelOptions}
          error={error}
          nullable={meta.nullable === true}
          onChange={onChange}
        />
      );

    case "timing_ref":
      return (
        <SelectRow
          label={meta.label}
          help={meta.help}
          value={typeof value === "string" ? value : null}
          baseline={baseline}
          options={timingIds}
          error={error}
          nullable={meta.nullable === true}
          onChange={onChange}
        />
      );

    case "port_ref":
      if (meta.multiple) {
        return (
          <ChipsRow
            label={meta.label}
            help={meta.help}
            values={Array.isArray(value) ? value.map(String) : []}
            baseline={baseline}
            options={portNames}
            error={error}
            onChange={onChange}
          />
        );
      }
      return (
        <SelectRow
          label={meta.label}
          help={meta.help}
          value={typeof value === "string" ? value : null}
          baseline={baseline}
          options={portNames}
          error={error}
          nullable={meta.nullable === true}
          nullLabel="— none (withhold) —"
          onChange={onChange}
        />
      );

    case "stimulus_ref":
      if (meta.multiple) {
        // Positional, not a set: stage i samples stages[i], and a sequence may
        // legitimately repeat a stimulus (an AA trial). One select per sampling
        // stage, with the count taken from the topology knob so the row grows
        // and shrinks with it — TG221 confirms the agreement either way.
        const topology = doc["topology"];
        const declared =
          topology !== null && typeof topology === "object"
            ? (topology as Record<string, unknown>)["n_sampling_stages"]
            : undefined;
        const values = Array.isArray(value) ? value.map(String) : [];
        const count = Math.max(
          typeof declared === "number" && declared >= 0 ? declared : values.length,
          values.length,
        );
        return (
          <>
            {Array.from({ length: count }, (_, i) => (
              <SelectRow
                key={`${path}[${i}]`}
                label={`${meta.label} — stage ${i}`}
                help={i === 0 ? meta.help : undefined}
                value={values[i] ?? null}
                baseline={Array.isArray(baseline) ? (baseline[i] ?? null) : null}
                options={stimulusIds}
                error={i === 0 ? error : undefined}
                onChange={(next) => {
                  const out = [...values];
                  if (next === null) out.splice(i, 1);
                  else out[i] = next;
                  onChange(out.slice(0, count));
                }}
              />
            ))}
          </>
        );
      }
      return (
        <SelectRow
          label={meta.label}
          help={meta.help}
          value={typeof value === "string" ? value : null}
          baseline={baseline}
          options={stimulusIds}
          error={error}
          onChange={onChange}
        />
      );

    case "reward_ref":
      return (
        <SelectRow
          label={meta.label}
          help={meta.help}
          value={typeof value === "string" ? value : null}
          baseline={baseline}
          options={[{ value: "@target", label: "@target (this trial's port)" }, ...portNames]}
          error={error}
          nullable
          nullLabel="— no reward —"
          onChange={onChange}
        />
      );

    case "template":
      return (
        <SelectRow
          label={meta.label}
          help={meta.help}
          value={typeof value === "string" ? value : null}
          baseline={baseline}
          options={[...new Set(schema.templates.map((t) => t.name))].map((name) => ({
            value: name,
            label: name,
          }))}
          error={error}
          onChange={onChange}
        />
      );

    case "template_version": {
      const template = (doc["topology"] as Record<string, unknown> | undefined)?.["template"];
      return (
        <SelectRow
          label={meta.label}
          help={meta.help}
          value={value === null || value === undefined ? null : String(value)}
          baseline={baseline === null || baseline === undefined ? null : String(baseline)}
          options={schema.templates
            .filter((t) => t.name === template)
            .map((t) => ({ value: String(t.version), label: `v${t.version} (${t.sourceHash})` }))}
          error={error}
          onChange={(next) => onChange(next === null ? null : Number(next))}
        />
      );
    }

    default:
      // An overlay widget this build doesn't know renders as text rather than
      // vanishing — same principle as the unknown-strobe console line.
      return (
        <FieldRow
          label={meta.label}
          help={meta.help}
          type="string"
          value={typeof value === "string" || typeof value === "number" ? value : ""}
          fallback=""
          baseline={baseline}
          error={error}
          onChange={onChange}
        />
      );
  }
}

/** `policy.seed` holds `"host"` or an integer; the input is one text box. */
function coerceSeed(meta: OverlayField, next: unknown): unknown {
  if (meta.widget !== "seed" || typeof next !== "string") return next;
  const trimmed = next.trim();
  if (/^\d+$/.test(trimmed)) return Number(trimmed);
  return trimmed;
}

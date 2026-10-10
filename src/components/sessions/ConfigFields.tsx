import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";

import { FieldRow } from "@/components/common/FieldRow";
import { springSnappy } from "@/lib/motion";
import type { ConfigField, TaskProfile } from "@/lib/sessions/types";

/**
 * The one renderer for a Task Profile's `config` array
 * (`TASKS.md#config-fields`), shared by this rig's per-sketch defaults on the
 * Task tab and the per-box override on the mapping step — the middle and outer
 * layers of the three-layer merge, rendered by the same component so they
 * cannot disagree about what a field is.
 *
 * It exists because a profile is no longer three fields. The lab's behaviour
 * sketches declare forty-odd — every timing, hold, window, penalty, reward
 * volume, pool weight and stage threshold — and a flat list of forty unlabelled
 * numbers is not a form anyone can safely use at 8am with six rats waiting.
 *
 * All of the structure comes from optional metadata on the fields themselves,
 * so a profile that declares none renders as a plain list exactly as it did
 * before any of this existed. There is no second code path for "simple"
 * profiles to fall out of sync with.
 *
 * The LEAF lives in `common/FieldRow.tsx`, so any other form over a different
 * document shape can share exactly the behaviour that must never diverge —
 * clamp-never-reject, and the mid-typing "not a number" escape hatch — without
 * this file's grouping/reset/advanced logic growing a second mode.
 */
export function ConfigFields({
  profile,
  config,
  baseline,
  onChange,
  onReset,
  disabled = false,
  only,
  exclude,
  quiet = false,
  fieldFilter,
  inactive,
  isAdvanced,
}: {
  profile: TaskProfile | null;
  config: Record<string, unknown>;
  /**
   * What each field would be if untouched — the profile's own defaults on the
   * Config page, the rig's saved defaults on the mapping step. Drives the
   * changed-marker and the reset buttons, so "reset" always means "back to the
   * layer underneath this one" rather than "back to the sketch author's value".
   */
  baseline: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  /**
   * Report a reset as the keys reset rather than as values. The mapping step
   * keeps only the operator's own edits, and a reset there has to DROP them so
   * the field follows the layer underneath; written back as the baseline's
   * value it would pin today's default (`TASKS.md#three-layer-merge`). Without
   * it, a reset is an `onChange` with the baseline's values.
   */
  onReset?: (keys: string[]) => void;
  disabled?: boolean;
  /**
   * Render these groups only. ONE group renders with no section header — the
   * Task tab gives it a heading of its own; SEVERAL keep their headers, because
   * the rail folds a few groups into one pill (`topology.tabOf`) and the
   * sub-headings are then the only thing saying which values are which.
   *
   * Kept as a filter on the one renderer rather than a second component: a form
   * that splits its fields two ways is a form that will eventually disagree
   * with itself about validation, clamping or the changed-marker.
   */
  only?: string | readonly string[];
  /**
   * Skip these groups entirely — the mapping step renders them separately as
   * its quick-tune strip (`TaskConfigForm`), and a field that appears twice
   * in one form is a field whose two rows will eventually disagree in the
   * reader's head even while the state keeps them honest.
   */
  exclude?: readonly string[];
  /**
   * Drop the inline help captions — for the Task tab's parameter inspector,
   * where forty captioned rows would be a wall. The label keeps its `title`
   * tooltip. The mapping step stays captioned.
   */
  quiet?: boolean;
  /**
   * Drop individual fields. The task editor uses it to keep row-owned fields
   * (`pool_weight_N`) off every surface but the row they belong to.
   */
  fieldFilter?: (field: ConfigField) => boolean;
  /**
   * Why a field does nothing right now, or null — drawn dimmed with the note
   * beside it, and still editable, so its value survives the change that made
   * it inert (a switch of selection mode, `lib/taskdef/selection.ts`).
   */
  inactive?: (field: ConfigField) => string | null;
  /**
   * Which fields go behind the "N advanced" disclosure; the field's own flag
   * by default. The task editor promotes the block size while the pool is
   * the mode that reads it.
   */
  isAdvanced?: (field: ConfigField) => boolean;
}) {
  const [openAdvanced, setOpenAdvanced] = useState<Record<string, boolean>>({});

  // Sections in first-declared order. The profile's authored order is
  // load-bearing elsewhere and there is no reason for the form to disagree
  // with it.
  /** `only` as a list, whatever it arrived as. Undefined stays undefined —
   *  "every group" is not the same request as "these zero groups". */
  const wanted = useMemo(
    () => (only === undefined ? undefined : typeof only === "string" ? [only] : [...only]),
    [only],
  );

  const sections = useMemo(() => {
    const bySection = new Map<string, ConfigField[]>();
    for (const field of profile?.config ?? []) {
      if (fieldFilter && !fieldFilter(field)) continue;
      const key = field.group ?? "";
      const existing = bySection.get(key);
      if (existing) existing.push(field);
      else bySection.set(key, [field]);
    }
    const all = [...bySection.entries()];
    // Ordered by `wanted` rather than by declaration when it is given: the
    // caller folded these groups into one pill and decided their order there.
    if (wanted !== undefined) {
      return wanted.flatMap((name) => {
        const fields = bySection.get(name);
        return fields ? [[name, fields] as [string, ConfigField[]]] : [];
      });
    }
    if (exclude !== undefined) return all.filter(([name]) => !exclude.includes(name));
    return all;
  }, [profile, wanted, exclude, fieldFilter]);

  if (!profile || profile.config.length === 0) return null;

  function set(key: string, value: unknown) {
    onChange({ ...config, [key]: value });
  }

  function resetKeys(keys: string[]) {
    if (onReset) {
      onReset(keys);
      return;
    }
    const next = { ...config };
    for (const key of keys) next[key] = baseline[key];
    onChange(next);
  }

  return (
    // A native fieldset rather than a `disabled` prop threaded through every
    // control: it covers the inputs, the reset buttons and the disclosures in
    // one place, and it is the pattern the Config page already uses.
    <fieldset disabled={disabled} className="flex flex-col gap-3">
      {sections.map(([section, fields]) => {
        const behind = (f: ConfigField) => (isAdvanced ? isAdvanced(f) : Boolean(f.advanced));
        const plain = fields.filter((f) => !behind(f));
        const advanced = fields.filter(behind);
        const changed = fields.filter(
          (f) => f.metadataKey in config && !Object.is(config[f.metadataKey], baseline[f.metadataKey]),
        );
        const expanded = openAdvanced[section] === true;

        return (
          <section key={section || "__ungrouped"} className="flex flex-col gap-1.5">
            {section && (wanted === undefined || wanted.length > 1) && (
              <header className="flex items-center justify-between gap-2 border-b border-halo pb-1">
                <span className="font-mono text-[10px] uppercase tracking-wider text-static">
                  {section}
                </span>
                {changed.length > 0 && (
                  <button
                    type="button"
                    onClick={() => resetKeys(changed.map((f) => f.metadataKey))}
                    className="flex items-center gap-1 text-[10px] text-static transition-colors hover:text-starlight"
                  >
                    <RotateCcw size={10} strokeWidth={1.75} />
                    Reset {changed.length}
                  </button>
                )}
              </header>
            )}

            {plain.map((field) => (
              <Field
                key={field.metadataKey}
                field={field}
                value={config[field.metadataKey] ?? field.default}
                baseline={baseline[field.metadataKey]}
                quiet={quiet}
                inactive={inactive?.(field) ?? null}
                onChange={(v) => set(field.metadataKey, v)}
              />
            ))}

            {advanced.length > 0 && (
              <>
                <button
                  type="button"
                  onClick={() =>
                    setOpenAdvanced((prev) => ({ ...prev, [section]: !expanded }))
                  }
                  className="flex w-fit items-center gap-1 text-[10px] text-static transition-colors hover:text-starlight"
                >
                  <motion.span
                    animate={{ rotate: expanded ? 90 : 0 }}
                    transition={springSnappy}
                    className="flex"
                  >
                    <ChevronRight size={11} strokeWidth={1.75} />
                  </motion.span>
                  {advanced.length} advanced
                </button>
                <AnimatePresence initial={false}>
                  {expanded && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={springSnappy}
                      className="flex flex-col gap-1.5 overflow-hidden"
                    >
                      {advanced.map((field) => (
                        <Field
                          key={field.metadataKey}
                          field={field}
                          value={config[field.metadataKey] ?? field.default}
                          baseline={baseline[field.metadataKey]}
                          quiet={quiet}
                          inactive={inactive?.(field) ?? null}
                          onChange={(v) => set(field.metadataKey, v)}
                        />
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </>
            )}
          </section>
        );
      })}
    </fieldset>
  );
}

function Field({
  field,
  value,
  baseline,
  quiet,
  inactive,
  onChange,
}: {
  field: ConfigField;
  value: unknown;
  baseline: unknown;
  quiet: boolean;
  inactive: string | null;
  onChange: (next: unknown) => void;
}) {
  const row = (
    <FieldRow
      label={field.label}
      help={quiet ? undefined : field.help}
      unit={field.unit}
      type={field.type}
      value={value}
      fallback={field.default}
      baseline={baseline}
      min={field.min}
      max={field.max}
      onChange={onChange}
    />
  );
  if (!inactive) return row;
  return (
    <div className="flex flex-col gap-0.5">
      <div className="opacity-45 transition-opacity focus-within:opacity-100 hover:opacity-80">{row}</div>
      <span className="self-end font-mono text-[9px] tracking-wide text-static/70">{inactive}</span>
    </div>
  );
}

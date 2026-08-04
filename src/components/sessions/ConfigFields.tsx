import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";

import { FieldRow } from "@/components/common/FieldRow";
import { springSnappy } from "@/lib/motion";
import type { ConfigField, TaskProfile } from "@/lib/sessions/types";

/**
 * The one renderer for a Task Profile's `config` array (`tasks.md` §3.2),
 * shared by this rig's per-sketch defaults on the Task tab and the per-box
 * override on the mapping step — the middle and outer layers of the three-layer
 * merge, rendered by the same component so they cannot disagree about what a
 * field is.
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
 * The LEAF lives in `common/FieldRow.tsx` and is shared with the spec editor
 * (`components/specs/`). That split is deliberate and has a boundary: the two
 * forms serve different document shapes — a flat `config[]` keyed by
 * `metadataKey` here, a nested spec document there — and must not converge
 * above the leaf, or this file's grouping/reset/advanced logic grows a second
 * mode. What IS shared is exactly the behaviour that must never diverge:
 * clamp-never-reject, and the mid-typing "not a number" escape hatch.
 */
export function ConfigFields({
  profile,
  config,
  baseline,
  onChange,
  disabled = false,
  only,
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
  disabled?: boolean;
  /**
   * Render one group only, with no section header — the Task tab gives each
   * group its own tile and supplies the heading itself. Kept as a filter on the
   * one renderer rather than a second component: a form that splits its fields
   * two ways is a form that will eventually disagree with itself about
   * validation, clamping or the changed-marker.
   */
  only?: string;
}) {
  const [openAdvanced, setOpenAdvanced] = useState<Record<string, boolean>>({});

  // Sections in first-declared order. The profile's authored order is
  // load-bearing elsewhere (`data.md` §11.8) and there is no reason for the
  // form to disagree with it.
  const sections = useMemo(() => {
    const bySection = new Map<string, ConfigField[]>();
    for (const field of profile?.config ?? []) {
      const key = field.group ?? "";
      const existing = bySection.get(key);
      if (existing) existing.push(field);
      else bySection.set(key, [field]);
    }
    const all = [...bySection.entries()];
    return only === undefined ? all : all.filter(([name]) => name === only);
  }, [profile, only]);

  if (!profile || profile.config.length === 0) return null;

  function set(key: string, value: unknown) {
    onChange({ ...config, [key]: value });
  }

  function resetKeys(keys: string[]) {
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
        const plain = fields.filter((f) => !f.advanced);
        const advanced = fields.filter((f) => f.advanced);
        const changed = fields.filter(
          (f) => f.metadataKey in config && !Object.is(config[f.metadataKey], baseline[f.metadataKey]),
        );
        const expanded = openAdvanced[section] === true;

        return (
          <section key={section || "__ungrouped"} className="flex flex-col gap-1.5">
            {section && only === undefined && (
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
  onChange,
}: {
  field: ConfigField;
  value: unknown;
  baseline: unknown;
  onChange: (next: unknown) => void;
}) {
  return (
    <FieldRow
      label={field.label}
      help={field.help}
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
}

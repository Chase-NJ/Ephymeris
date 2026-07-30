import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";

import { TextInput, Toggle } from "@/components/common/controls";
import { springSnappy } from "@/lib/motion";
import type { ConfigField, TaskProfile } from "@/lib/sessions/types";

/**
 * The one renderer for a Task Profile's `config` array (`tasks.md` §3.2),
 * shared by the Config page's rig defaults and the per-box override on the
 * mapping step.
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

/**
 * Clamp a parsed number into the field's declared range.
 *
 * Clamping rather than rejecting: these bounds exist to keep a typo from
 * reaching the firmware (a zero polling rate is a hang, a bias window past the
 * ring buffer is an overrun), and silently refusing a keystroke mid-edit is
 * worse than landing on the nearest legal value.
 */
function clamp(field: ConfigField, value: number): number {
  if (field.min !== undefined && value < field.min) return field.min;
  if (field.max !== undefined && value > field.max) return field.max;
  return value;
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
  // A number the user is mid-typing ("-", "0.") isn't a number yet, so it is
  // held as text and reported rather than silently swallowed. The old form
  // stored the raw string in `config`, and the START builder then quietly
  // substituted the profile default — the operator saw their value on screen
  // and the board ran on a different one.
  const numeric = field.type === "int" || field.type === "float";
  const invalid = numeric && typeof value === "string" && value.trim() !== "";
  const changed = !Object.is(value, baseline);

  return (
    <label className="flex items-start justify-between gap-3">
      <span className="min-w-0 pt-1">
        <span
          className={`block truncate text-[11px] ${changed ? "text-starlight" : "text-static"}`}
          title={field.help ?? field.label}
        >
          {changed && <span className="mr-1 text-pulsar">•</span>}
          {field.label}
        </span>
        {field.help && (
          <span className="mt-0.5 block text-[10px] leading-snug text-static/70">
            {field.help}
          </span>
        )}
        {invalid && (
          <span
            className="mt-0.5 block text-[10px]"
            style={{ color: "var(--color-status-error)" }}
          >
            Not a number — the box would run on {String(field.default)}.
          </span>
        )}
      </span>

      <span className="flex shrink-0 items-center gap-1.5">
        {field.type === "bool" ? (
          <Toggle
            label={field.label}
            checked={value === true}
            onChange={onChange}
          />
        ) : numeric ? (
          <TextInput
            label={field.label}
            mono
            value={String(value ?? "")}
            onChange={(raw) => {
              if (raw.trim() === "") return onChange(field.default);
              const parsed = field.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
              // Keep the raw text on a partial entry so the caret doesn't jump;
              // `invalid` above is what makes that state visible.
              onChange(Number.isNaN(parsed) ? raw : clamp(field, parsed));
            }}
            className="w-[76px]"
          />
        ) : (
          <TextInput
            label={field.label}
            value={String(value ?? "")}
            onChange={onChange}
            className="w-[120px]"
          />
        )}
        <span className="w-6 shrink-0 font-mono text-[10px] text-static/70">
          {field.unit ?? ""}
        </span>
      </span>
    </label>
  );
}

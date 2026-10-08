import { Plus, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { TextInput } from "@/components/common/controls";
import type { TaskDefinition } from "@/lib/taskdef/types";

/**
 * The three things about a task that are not its trials, its ramp or its
 * numbers — and had nowhere to be edited until the presets were retired.
 *
 * A preset used to arrive with a category, a set of `legacyNames` and a note
 * already filled in, so nothing in the app ever offered a field for them. Built
 * from scratch, a task would otherwise be stuck in the default category forever
 * and could never claim a historical sketch name at all.
 *
 * `legacyNames` IS THE ONE THAT MATTERS, and it is the least obvious. A
 * pre-Ephymeris archive records `sketch` as a human label — `Shape - R`,
 * `GRGL_2-Odor` — and the archive walk (`DATA.md#which-profile-decodes-a-run`)
 * resolves that to a task by matching this list. A name typed here is what
 * makes those runs decode against the profile that actually ran them instead of
 * falling through to inference. Declared rather than guessed on purpose:
 * matching "Shape - L" to a task by resemblance is a guess, and a wrong guess
 * decodes real data with the wrong strobe map.
 *
 * The body only: the task editor shows it in its header's Details popover,
 * opened once on a new task because the category decides where the sketch
 * folder is written (`TASKS.md#editor`).
 */
export function TaskDetailsBody({
  definition,
  categories,
  onChange,
}: {
  definition: TaskDefinition;
  /** Categories already in use on this rig, offered as a hint rather than as a
   *  closed list — a category is a folder name, and inventing one is allowed. */
  categories: readonly string[];
  onChange: (next: TaskDefinition) => void;
}) {
  const [draftLegacy, setDraftLegacy] = useState("");

  const addLegacy = (raw: string) => {
    const name = raw.trim();
    // Silently ignoring a duplicate rather than refusing it: the list is a set,
    // and an error over a name that is already there would be pedantry.
    if (!name || definition.legacyNames.includes(name)) {
      setDraftLegacy("");
      return;
    }
    onChange({ ...definition, legacyNames: [...definition.legacyNames, name] });
    setDraftLegacy("");
  };

  return (
    <div className="flex flex-col gap-4">
      <Field
        label="Category"
        help="Groups the task in the library, and is the folder its sketch is written into."
      >
        <TextInput
          label="Category"
          value={definition.category}
          onChange={(category) => onChange({ ...definition, category })}
          className="w-full"
        />
        {categories.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {categories.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => onChange({ ...definition, category: name })}
                className="rounded-md border border-halo px-1.5 py-0.5 font-mono text-[10px] text-static transition-colors hover:border-pulsar hover:text-starlight"
              >
                {name}
              </button>
            ))}
          </div>
        )}
      </Field>

      <Field
        label="Legacy names"
        help="Names an older archive recorded for this same task. Analytics matches a run's `sketch` field against these, so a run recorded as `Shape - R` decodes against this profile instead of being inferred from its strobes."
      >
        {definition.legacyNames.length > 0 && (
          <div className="mb-1.5 flex flex-wrap gap-1">
            {definition.legacyNames.map((name) => (
              <span
                key={name}
                className="flex items-center gap-1 rounded-md border border-halo bg-nebula px-1.5 py-0.5 font-mono text-[10px] text-starlight"
              >
                {name}
                <button
                  type="button"
                  aria-label={`Remove ${name}`}
                  onClick={() =>
                    onChange({
                      ...definition,
                      legacyNames: definition.legacyNames.filter((n) => n !== name),
                    })
                  }
                  className="text-static transition-colors hover:text-status-error"
                >
                  <X size={10} strokeWidth={2} />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex items-center gap-1.5">
          <TextInput
            label="Add a legacy name"
            value={draftLegacy}
            placeholder="Shape - R"
            onChange={setDraftLegacy}
            onSubmit={() => addLegacy(draftLegacy)}
            mono
            className="min-w-0 flex-1"
          />
          <button
            type="button"
            onClick={() => addLegacy(draftLegacy)}
            className="flex shrink-0 items-center gap-1 rounded-md border border-halo px-2 py-1 text-[10px] text-static transition-colors hover:border-pulsar hover:text-starlight"
          >
            <Plus size={11} strokeWidth={1.75} />
            Add
          </button>
        </div>
      </Field>

      <Field label="Notes" help="For whoever opens this next. Never read by the firmware.">
        <textarea
          value={definition.notes}
          onChange={(e) => onChange({ ...definition, notes: e.target.value })}
          rows={2}
          aria-label="Notes"
          className="scrollbar-slim w-full resize-y rounded-sm border border-halo bg-void/40 px-2 py-1.5 text-[12px] text-starlight transition-colors focus:border-pulsar focus:outline-none"
        />
      </Field>
    </div>
  );
}

/** The Details button's one-line label: the category, and the legacy count. */
export function detailsSummary(definition: TaskDefinition): string {
  const n = definition.legacyNames.length;
  return n > 0 ? `${definition.category} · ${n} legacy name${n === 1 ? "" : "s"}` : definition.category;
}

function Field({
  label,
  help,
  children,
}: {
  label: string;
  help: string;
  children: ReactNode;
}) {
  return (
    <div>
      <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-static">
        {label}
      </div>
      {children}
      <p className="mt-1 max-w-prose text-[10px] leading-relaxed text-static/70">{help}</p>
    </div>
  );
}

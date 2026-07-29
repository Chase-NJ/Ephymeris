import { motion } from "framer-motion";
import { Minus, Plus } from "lucide-react";
import { useState } from "react";

import { Button, Select, TextInput } from "@/components/common/controls";
import { parseRoster, rosterPreview } from "@/lib/cohorts/roster";
import type { Animal } from "@/lib/cohorts/types";
import { springSnappy } from "@/lib/motion";

/**
 * The editable animal roster — `cohorts.md` §6.
 *
 * Biographical data only: name, sex, ID number, notes. Group membership and
 * box number are deliberately not here — box uniqueness is scoped *per group*
 * (§2), so it isn't a property of an animal in isolation, it's a property of
 * an animal's membership in a particular group. Both live in `GroupsPanel`
 * instead, where an animal's whole group is visible at once and a duplicate
 * box is obvious on sight.
 *
 * **Bulk entry is the primary way in.** A roster already exists somewhere —
 * a spreadsheet column, a naming scheme — and retyping it one blank row at a
 * time was the slowest part of setting a cohort up. The single-row button
 * stays for the afterthought animal.
 *
 * Validation errors arrive keyed `animal:<id>` from the sidecar and render
 * inline against the offending row, not as a toast after the fact (§6).
 */

const SEX_OPTIONS = [
  { value: "", label: "—" },
  { value: "M", label: "M" },
  { value: "F", label: "F" },
  { value: "unknown", label: "Unknown" },
] as const;

let localSeq = 0;
/** Client-side id for a new row; the sidecar keeps whatever it's given. */
function newAnimalId(): string {
  localSeq += 1;
  return `new-${Date.now().toString(36)}-${localSeq}`;
}

function blankAnimal(name: string, groupId: string): Animal {
  return {
    id: newAnimalId(),
    name,
    groupId,
    boxNumber: null,
    sex: null,
    idNumber: null,
    notes: null,
  };
}

export function AnimalTable({
  animals,
  defaultGroupId,
  errors,
  attention = false,
  onChange,
}: {
  animals: Animal[];
  /** Where a freshly-added animal lands; the user places it properly in Groups. */
  defaultGroupId: string;
  errors: Record<string, string>;
  /** Pulses the bulk field when it's the one thing the create flow waits on. */
  attention?: boolean;
  onChange: (next: Animal[]) => void;
}) {
  const [bulk, setBulk] = useState("");

  function patch(id: string, changes: Partial<Animal>) {
    onChange(animals.map((a) => (a.id === id ? { ...a, ...changes } : a)));
  }

  function addAnimal() {
    onChange([...animals, blankAnimal("", defaultGroupId)]);
  }

  function addBulk() {
    const { names } = parseRoster(
      bulk,
      animals.map((a) => a.name),
    );
    if (names.length === 0) {
      setBulk("");
      return;
    }
    onChange([...animals, ...names.map((name) => blankAnimal(name, defaultGroupId))]);
    setBulk("");
  }

  const preview = rosterPreview(
    bulk,
    animals.map((a) => a.name),
  );
  const columns = "grid-cols-[1.3fr_72px_1fr_1.4fr_28px]";

  return (
    <div className="px-4 py-3.5">
      {/* The fast path, above the table it fills. */}
      <div className="mb-3">
        <div className="flex items-center gap-2">
          <TextInput
            label="Add animals in bulk"
            value={bulk}
            placeholder="Paste names, or type R- × 8"
            attention={attention && animals.length === 0}
            onChange={setBulk}
            onSubmit={addBulk}
            className="min-w-0 flex-1"
          />
          <Button variant="primary" onClick={addBulk} disabled={bulk.trim() === ""}>
            <Plus size={13} strokeWidth={1.75} />
            Add
          </Button>
        </div>
        <motion.p
          key={preview ?? "hint"}
          initial={{ opacity: 0, y: -2 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springSnappy}
          className="mt-1 text-[11px] leading-relaxed text-static"
        >
          {preview ??
            "Separate names with commas or new lines — a spreadsheet column pastes straight in. Or give a prefix and a count."}
        </motion.p>
      </div>

      {animals.length > 0 && (
        <div className={`grid ${columns} items-center gap-x-2 pb-1.5 text-[11px] text-static`}>
          <span>Name</span>
          <span>Sex</span>
          <span>ID number</span>
          <span>Notes</span>
          <span />
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        {animals.map((animal) => {
          const error = errors[`animal:${animal.id}`];
          return (
            <div key={animal.id}>
              <div className={`grid ${columns} items-center gap-x-2`}>
                <TextInput
                  label={`Name for ${animal.name || "new animal"}`}
                  value={animal.name}
                  placeholder="Animal name"
                  onChange={(name) => patch(animal.id, { name })}
                  className="w-full"
                />
                <Select
                  label={`Sex for ${animal.name || "new animal"}`}
                  value={animal.sex ?? ""}
                  options={SEX_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                  onChange={(v) =>
                    patch(animal.id, { sex: v === "" ? null : (v as Animal["sex"]) })
                  }
                />
                <TextInput
                  label={`ID number for ${animal.name || "new animal"}`}
                  mono
                  value={animal.idNumber ?? ""}
                  placeholder="tag / RFID"
                  onChange={(v) => patch(animal.id, { idNumber: v.trim() === "" ? null : v })}
                  className="w-full"
                />
                <TextInput
                  label={`Notes for ${animal.name || "new animal"}`}
                  value={animal.notes ?? ""}
                  placeholder="notes"
                  onChange={(v) => patch(animal.id, { notes: v.trim() === "" ? null : v })}
                  className="w-full"
                />
                <Button
                  variant="outline"
                  shape="icon"
                  onClick={() => onChange(animals.filter((a) => a.id !== animal.id))}
                  title={`Remove ${animal.name || "this animal"}`}
                >
                  <Minus size={14} strokeWidth={2} />
                </Button>
              </div>
              {error && (
                <p
                  className="mt-0.5 pl-1 text-[11px]"
                  style={{ color: "var(--color-status-error)" }}
                >
                  {error}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {animals.length === 0 && (
        <p className="text-[12px] leading-relaxed text-static">
          No animals yet — a cohort can also be created empty and populated over
          the following days.
        </p>
      )}

      <div className="mt-3">
        <Button variant="ghost" onClick={addAnimal}>
          <Plus size={13} strokeWidth={1.75} />
          Add a blank row
        </Button>
      </div>
    </div>
  );
}

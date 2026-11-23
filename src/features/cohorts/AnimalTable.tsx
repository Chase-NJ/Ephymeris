import { motion } from "framer-motion";
import { ArrowRightLeft, CircuitBoard, Minus, Plus } from "lucide-react";
import { useState } from "react";

import { Button, Select, TextInput } from "@/components/common/controls";
import { ImplantEditor } from "./ImplantEditor";
import { boxLabel, useBoxAvailability } from "./boxAvailability";
import { summarizeImplant } from "./implant";
import { parseRoster, rosterPreview } from "./roster";
import type { Animal } from "./types";
import { springSnappy } from "@/lib/motion";

/**
 * The editable animal roster — `DATA.md#data-model`.
 *
 * Name, sex, ID number, notes, the animal's **implant** (`ImplantEditor`,
 * `DATA.md#implants`) and the **usual box**: the box session set-up
 * offers first for the animal, and nothing more (`DATA.md#data-model`). Which
 * animals run together, and in which boxes, is chosen per round at set-up, so
 * animals may share a usual box and none is required. Only boxes this machine
 * has are offered (`boxAvailability.ts`); a stored box it lacks stays
 * selected and says so.
 *
 * **Bulk entry is the primary way in.** A roster already exists somewhere —
 * a spreadsheet column, a naming scheme — and retyping it one blank row at a
 * time was the slowest part of setting a cohort up. The single-row button
 * stays for the afterthought animal.
 *
 * Validation errors arrive keyed `animal:<id>` from the sidecar and render
 * inline against the offending row, not as a toast after the fact
 * (`DATA.md#validation`).
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

function blankAnimal(name: string): Animal {
  return {
    id: newAnimalId(),
    name,
    boxNumber: null,
    cage: null,
    sex: null,
    idNumber: null,
    notes: null,
    implant: null,
  };
}

export function AnimalTable({
  animals,
  errors,
  attention = false,
  onChange,
  onMove,
}: {
  animals: Animal[];
  errors: Record<string, string>;
  /** Pulses the bulk field when it's the one thing the create flow waits on. */
  attention?: boolean;
  onChange: (next: Animal[]) => void;
  /**
   * Move a saved animal, with its history, to another cohort
   * (`DATA.md#moving-animals-between-cohorts`). Absent hides the column (a
   * cohort not yet created); null shows it disabled while edits are unsaved,
   * so the row doesn't reflow as the operator types.
   */
  onMove?: ((animal: Animal) => void) | null | undefined;
}) {
  const [bulk, setBulk] = useState("");
  /** The animal whose implant dialog is open, by id. */
  const [implantFor, setImplantFor] = useState<string | null>(null);
  const implanting = animals.find((a) => a.id === implantFor) ?? null;
  const { offers, statusOf } = useBoxAvailability();

  /** "—", every box this machine has, and the animal's own box if it is not one of them. */
  function boxOptions(current: number | null) {
    const options: Array<{ value: number; label: string }> = [
      { value: 0, label: "—" },
      ...offers.map((offer) => ({ value: offer.box, label: offer.label })),
    ];
    if (current !== null && !offers.some((offer) => offer.box === current)) {
      options.push({ value: current, label: boxLabel(current, statusOf(current)) });
    }
    return options;
  }

  function patch(id: string, changes: Partial<Animal>) {
    onChange(animals.map((a) => (a.id === id ? { ...a, ...changes } : a)));
  }

  function addAnimal() {
    onChange([...animals, blankAnimal("")]);
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
    onChange([...animals, ...names.map((name) => blankAnimal(name))]);
    setBulk("");
  }

  const preview = rosterPreview(
    bulk,
    animals.map((a) => a.name),
  );
  const columns =
    onMove === undefined
      ? "grid-cols-[1.3fr_72px_132px_1fr_1.4fr_28px_28px]"
      : "grid-cols-[1.3fr_72px_132px_1fr_1.4fr_28px_28px_28px]";

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
          <span title="The box session set-up offers first for this animal. Animals may share one.">
            Usual box
          </span>
          <span>ID number</span>
          <span>Notes</span>
          <span />
          <span />
          {onMove !== undefined && <span />}
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
                <Select
                  label={`Usual box for ${animal.name || "new animal"}`}
                  value={animal.boxNumber ?? 0}
                  options={boxOptions(animal.boxNumber)}
                  tone={
                    animal.boxNumber !== null && statusOf(animal.boxNumber) !== "available"
                      ? "warning"
                      : "normal"
                  }
                  onChange={(box) => patch(animal.id, { boxNumber: box === 0 ? null : box })}
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
                  variant={animal.implant ? "primary" : "outline"}
                  shape="icon"
                  onClick={() => setImplantFor(animal.id)}
                  title={`${summarizeImplant(animal.implant)} — ${animal.implant ? "edit" : "add"} ${
                    animal.name || "this animal"
                  }'s implant`}
                >
                  <CircuitBoard size={13} strokeWidth={1.75} />
                </Button>
                <Button
                  variant="outline"
                  shape="icon"
                  onClick={() => onChange(animals.filter((a) => a.id !== animal.id))}
                  // A removal keeps the animal's history under its name
                  // (`DATA.md#former-members`); saying so is what stops a
                  // removal being mistaken for a deletion, or avoided as one.
                  title={`Remove ${animal.name || "this animal"} from the roster — any sessions it ran stay in this cohort's history`}
                >
                  <Minus size={14} strokeWidth={2} />
                </Button>
                {onMove !== undefined && (
                  <Button
                    variant="outline"
                    shape="icon"
                    onClick={() => onMove?.(animal)}
                    disabled={onMove === null}
                    title={
                      onMove === null
                        ? "Save your changes first, then move"
                        : `Move ${animal.name || "this animal"} and its history to another cohort`
                    }
                  >
                    <ArrowRightLeft size={13} strokeWidth={1.75} />
                  </Button>
                )}
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

      <ImplantEditor
        open={implanting !== null}
        animalName={implanting?.name ?? ""}
        implant={implanting?.implant ?? null}
        onSave={(implant) => {
          if (implantFor !== null) patch(implantFor, { implant });
        }}
        onClose={() => setImplantFor(null)}
      />
    </div>
  );
}

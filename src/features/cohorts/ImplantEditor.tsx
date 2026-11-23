import { Minus, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { Button, NumberInput, Select, TextInput } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import {
  HEMISPHERES,
  blankImplant,
  blankTarget,
  cleanImplant,
  depthOn,
  implantProblem,
  isDate,
  twoBundleImplant,
  type Implant,
  type ImplantLowering,
  type ImplantTarget,
} from "./implant";

/**
 * One animal's implant — `DATA.md#implants`.
 *
 * Entered once, on the animal: the device, its targets (each a group of the
 * device's channels at one place in the brain) and the dated lowerings of
 * its drive. Edits a draft; Done hands the roster the cleaned implant, which
 * the cohort's own Save posts. Every rule the sidecar applies is shown here
 * first (`features/cohorts/implant.ts`).
 */

const HEMISPHERE_OPTIONS = HEMISPHERES.map((value) => ({ value, label: value }));

/** Today, in the machine's own calendar. */
function today(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const TARGET_COLUMNS = "grid-cols-[1fr_1.4fr_92px_64px_64px_64px_1fr_28px]";
const LOWERING_COLUMNS = "grid-cols-[132px_96px_28px]";

export function ImplantEditor({
  open,
  animalName,
  implant,
  onSave,
  onClose,
}: {
  open: boolean;
  animalName: string;
  /** The animal's implant as the roster holds it; null for none. */
  implant: Implant | null;
  /** The cleaned implant, or null to remove it. */
  onSave: (next: Implant | null) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<Implant | null>(implant);
  // A fresh draft each time the dialog opens: an abandoned edit is not kept.
  useEffect(() => {
    if (open) setDraft(implant);
  }, [open, implant]);

  const problem = draft ? implantProblem(draft) : null;

  function setTarget(index: number, changes: Partial<ImplantTarget>) {
    if (!draft) return;
    setDraft({
      ...draft,
      targets: draft.targets.map((t, i) => (i === index ? { ...t, ...changes } : t)),
    });
  }

  function setLowering(index: number, changes: Partial<ImplantLowering>) {
    if (!draft) return;
    setDraft({
      ...draft,
      lowerings: draft.lowerings.map((l, i) => (i === index ? { ...l, ...changes } : l)),
    });
  }

  return (
    <Modal open={open} onClose={onClose} title={`Implant — ${animalName || "new animal"}`} size="xl">
      {!draft ? (
        <div className="flex flex-col gap-3">
          <p className="text-[12px] leading-relaxed text-static">
            No implant yet. An implant is entered once, here, and every recorded run copies it as it stood
            that day.
          </p>
          <div className="flex items-center gap-2">
            <Button variant="primary" onClick={() => setDraft(twoBundleImplant(today()))}>
              <Plus size={13} strokeWidth={1.75} />
              Two bundles of 16
            </Button>
            <Button variant="outline" onClick={() => setDraft(blankImplant(today()))}>
              <Plus size={13} strokeWidth={1.75} />
              Other device
            </Button>
          </div>
          <p className="text-[11px] leading-relaxed text-static">
            Two bundles of 16 is the lab's custom 32-channel electrode: one target on channels 0-15 and one
            on 16-31, the numbers printed beside the holes of the EIB.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          <section className="grid grid-cols-[1.4fr_132px_1.6fr] gap-x-2 gap-y-1">
            <span className="text-[11px] text-static">Device</span>
            <span className="text-[11px] text-static">Surgery date</span>
            <span className="text-[11px] text-static">Probe map, if the device has one</span>
            <TextInput
              label="Device"
              value={draft.device}
              placeholder="custom 32-channel electrode"
              onChange={(device) => setDraft({ ...draft, device })}
              className="w-full"
            />
            <TextInput
              label="Surgery date"
              mono
              value={draft.surgeryDate}
              placeholder="YYYY-MM-DD"
              onChange={(surgeryDate) => setDraft({ ...draft, surgeryDate })}
              className="w-full"
            />
            <TextInput
              label="Probe map file"
              mono
              value={draft.probeMapPath ?? ""}
              placeholder="path to the probe-map XML"
              onChange={(path) => setDraft({ ...draft, probeMapPath: path === "" ? null : path })}
              className="w-full"
            />
          </section>

          <section>
            <h3 className="mb-1 font-display text-[13px] font-semibold text-starlight">Targets</h3>
            <p className="mb-2 text-[11px] leading-relaxed text-static">
              A target is a group of the device's channels at one place in the brain. Channels are numbered
              on the device (a range such as 0-15, or a list such as 0,2,4), never by RHX's names.
            </p>
            <div className={`grid ${TARGET_COLUMNS} items-center gap-x-2 pb-1 text-[11px] text-static`}>
              <span>Name</span>
              <span>Region</span>
              <span>Hemisphere</span>
              <span>AP mm</span>
              <span>ML mm</span>
              <span title="Depth at surgery. Lowerings below are added to it.">DV mm</span>
              <span>Channels</span>
              <span />
            </div>
            <div className="flex flex-col gap-1.5">
              {draft.targets.map((target, index) => {
                const label = target.name || `target ${index + 1}`;
                return (
                  // Index keys: a target has no id, and rows are only appended or removed.
                  // eslint-disable-next-line react/no-array-index-key
                  <div key={index} className={`grid ${TARGET_COLUMNS} items-center gap-x-2`}>
                    <TextInput
                      label={`Name of ${label}`}
                      value={target.name}
                      placeholder="OFC"
                      onChange={(name) => setTarget(index, { name })}
                      className="w-full"
                    />
                    <TextInput
                      label={`Region of ${label}`}
                      value={target.region}
                      placeholder="orbitofrontal cortex"
                      onChange={(region) => setTarget(index, { region })}
                      className="w-full"
                    />
                    <Select
                      label={`Hemisphere of ${label}`}
                      value={target.hemisphere}
                      options={HEMISPHERE_OPTIONS}
                      onChange={(hemisphere) => setTarget(index, { hemisphere })}
                    />
                    <NumberInput
                      label={`AP of ${label}, mm`}
                      value={target.apMm}
                      fallback={0}
                      className="w-full"
                      onChange={(apMm) => setTarget(index, { apMm })}
                    />
                    <NumberInput
                      label={`ML of ${label}, mm`}
                      value={target.mlMm}
                      fallback={0}
                      className="w-full"
                      onChange={(mlMm) => setTarget(index, { mlMm })}
                    />
                    <NumberInput
                      label={`DV of ${label}, mm`}
                      value={target.dvMm}
                      fallback={0}
                      className="w-full"
                      onChange={(dvMm) => setTarget(index, { dvMm })}
                    />
                    <TextInput
                      label={`Channels of ${label}`}
                      mono
                      value={target.channels}
                      placeholder="0-15"
                      onChange={(channels) => setTarget(index, { channels })}
                      className="w-full"
                    />
                    <Button
                      variant="outline"
                      shape="icon"
                      disabled={draft.targets.length === 1}
                      onClick={() =>
                        setDraft({ ...draft, targets: draft.targets.filter((_, i) => i !== index) })
                      }
                      title={`Remove ${label}`}
                    >
                      <Minus size={14} strokeWidth={2} />
                    </Button>
                  </div>
                );
              })}
            </div>
            <div className="mt-2">
              <Button variant="ghost" onClick={() => setDraft({ ...draft, targets: [...draft.targets, blankTarget()] })}>
                <Plus size={13} strokeWidth={1.75} />
                Add a target
              </Button>
            </div>
          </section>

          <section>
            <h3 className="mb-1 font-display text-[13px] font-semibold text-starlight">Lowerings</h3>
            <p className="mb-2 text-[11px] leading-relaxed text-static">
              Each time the drive is turned: the date and how far, in mm (deeper is positive). One drive
              carries the whole electrode, so every target moves by that distance.
            </p>
            {draft.lowerings.length > 0 && (
              <div className={`grid ${LOWERING_COLUMNS} items-center gap-x-2 pb-1 text-[11px] text-static`}>
                <span>Date</span>
                <span>Distance mm</span>
                <span />
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              {draft.lowerings.map((lowering, index) => (
                // eslint-disable-next-line react/no-array-index-key
                <div key={index} className={`grid ${LOWERING_COLUMNS} items-center gap-x-2`}>
                  <TextInput
                    label={`Date of lowering ${index + 1}`}
                    mono
                    value={lowering.date}
                    placeholder="YYYY-MM-DD"
                    onChange={(date) => setLowering(index, { date })}
                    className="w-full"
                  />
                  <NumberInput
                    label={`Distance of lowering ${index + 1}, mm`}
                    value={lowering.mm}
                    fallback={0.25}
                    className="w-full"
                    onChange={(mm) => setLowering(index, { mm })}
                  />
                  <Button
                    variant="outline"
                    shape="icon"
                    onClick={() =>
                      setDraft({ ...draft, lowerings: draft.lowerings.filter((_, i) => i !== index) })
                    }
                    title={`Remove lowering ${index + 1}`}
                  >
                    <Minus size={14} strokeWidth={2} />
                  </Button>
                </div>
              ))}
            </div>
            <div className="mt-2">
              <Button
                variant="ghost"
                onClick={() =>
                  setDraft({ ...draft, lowerings: [...draft.lowerings, { date: today(), mm: 0.25 }] })
                }
              >
                <Plus size={13} strokeWidth={1.75} />
                Add a lowering
              </Button>
            </div>
            {isDate(draft.surgeryDate) && (
              <p className="mt-2 font-mono text-[11px] text-static">
                Depth today:{" "}
                {draft.targets
                  .map((target, index) => {
                    const { dvMm, setOn } = depthOn(draft, target, today());
                    return `${target.name.trim() || `target ${index + 1}`} ${dvMm} mm (since ${setOn})`;
                  })
                  .join(" · ")}
              </p>
            )}
          </section>

          {problem && (
            <p className="text-[12px]" style={{ color: "var(--color-status-warning)" }}>
              {problem}
            </p>
          )}

          <footer className="flex items-center justify-between">
            <Button
              variant="ghost"
              onClick={() => {
                onSave(null);
                onClose();
              }}
              title="Take the implant off this animal. Runs already recorded keep their own copy."
            >
              Remove implant
            </Button>
            <span className="flex items-center gap-2">
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={problem !== null}
                onClick={() => {
                  onSave(cleanImplant(draft));
                  onClose();
                }}
                {...(problem ? { title: problem } : {})}
              >
                Done
              </Button>
            </span>
          </footer>
        </div>
      )}
    </Modal>
  );
}

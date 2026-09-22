import { Check, Minus } from "lucide-react";
import { useNavigate } from "react-router";

import { NODE_FILL, useBoxHealth, type BoxHealth } from "@/components/chrome/ConstellationStatus";
import { Button } from "@/components/common/controls";
import { Dropdown, type DropdownOption } from "@/components/common/Dropdown";
import { useIntanStatus } from "@/lib/intan/context";
import { useSettings } from "@/lib/settings/context";
import { INTAN_DIGITAL_INPUTS } from "@/lib/settings/schema";

/**
 * Box → recording-controller digital input (`recording.md` §3).
 *
 * A box has a USB lead to this machine and, if it records, a sync line to one
 * of the controller's sixteen digital inputs. Both are bindings between two
 * instruments rather than facts about the box, and both live in
 * `settings.boxes` — this table edits `intanDigitalIn` there, beside the
 * board binding the Rig tab edits. The editor is on the Recording tab because
 * the far end of this cable is the recording controller and the person
 * plugging it in is setting up a recording, not the rig.
 *
 * An input another box holds is not offered: two boxes on one input are
 * indistinguishable in the recording. The lower box number keeps a duplicate
 * on load (`normalizeBoxes`), the same rule the sidecar applies.
 */

const HEALTH_TITLE: Record<BoxHealth, string> = {
  nominal: "active",
  idle: "connected",
  absent: "not detected",
  fault: "error",
};

export function SyncInputsTable() {
  const { settings, update } = useSettings();
  const intan = useIntanStatus();
  const health = useBoxHealth();
  const navigate = useNavigate();
  const boxes = settings.boxes;

  const dinElsewhere = (din: number, box: number) =>
    boxes.some((b) => b.box !== box && b.intanDigitalIn === din);

  function setDin(box: number, din: number | null) {
    void update({ boxes: boxes.map((b) => (b.box === box ? { ...b, intanDigitalIn: din } : b)) });
  }

  return (
    <div>
      {boxes.length === 0 ? (
        <div className="flex items-center justify-between gap-3 px-4 py-3.5">
          <p className="text-[12px] leading-relaxed text-static">
            No boxes yet — add them on the Rig tab, then choose each one's input here.
          </p>
          <Button variant="ghost" onClick={() => navigate("/config")}>
            Open Rig
          </Button>
        </div>
      ) : (
        <div className="px-4 py-3.5">
          <div className="grid grid-cols-[38px_1fr_150px] items-center gap-x-3 pb-1.5 text-[11px] text-static">
            <span>Box</span>
            <span>Label</span>
            <span title="The recording controller's digital input this box's sync line is wired to">
              Digital input
            </span>
          </div>
          <div className="flex flex-col gap-1.5">
            {boxes.map((binding) => {
              const options: DropdownOption[] = [
                { value: "", label: "— none —" },
                ...Array.from({ length: INTAN_DIGITAL_INPUTS }, (_, i) => i + 1)
                  .filter((n) => n === binding.intanDigitalIn || !dinElsewhere(n, binding.box))
                  .map((n) => ({ value: String(n), label: `DIN ${n}` })),
              ];
              const state = health[binding.box] ?? "absent";
              return (
                <div key={binding.box} className="grid grid-cols-[38px_1fr_150px] items-center gap-x-3">
                  <span className="flex items-center gap-1.5 font-mono text-[12px] text-static">
                    <span
                      aria-hidden
                      title={HEALTH_TITLE[state]}
                      className="size-[7px] shrink-0 rounded-full"
                      style={{ background: NODE_FILL[state] }}
                    />
                    {binding.box}
                  </span>
                  <span className="truncate text-[13px] text-starlight">{binding.label}</span>
                  <Dropdown
                    label={`Intan digital input for box ${binding.box}`}
                    size="regular"
                    value={binding.intanDigitalIn ? String(binding.intanDigitalIn) : ""}
                    options={options}
                    placeholder="— none —"
                    onChange={(v) => setDin(binding.box, v === "" ? null : Number(v))}
                  />
                </div>
              );
            })}
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-static">
            The other end of the cable — which Mega pin pulses — is wiring, on the Rig tab.
          </p>
        </div>
      )}

      {/* The sync channel is the box's half of the link: without one in the
          rig's wiring, no box pulses on its events and no input has anything
          to hear. */}
      <div className="flex items-center gap-2.5 border-t border-halo px-4 py-3 text-[12px]">
        <span
          className="flex size-4 shrink-0 items-center justify-center"
          style={{ color: intan.rigHasSync ? "var(--color-ion)" : "var(--color-status-warning)" }}
        >
          {intan.rigHasSync ? <Check size={13} strokeWidth={2} /> : <Minus size={13} strokeWidth={2} />}
        </span>
        <span className={intan.rigHasSync ? "text-static" : "text-starlight"}>
          {intan.rigHasSync
            ? "This rig's wiring has a sync channel"
            : "This rig's wiring declares no sync channel, so no box pulses on its events"}
        </span>
        <Button variant="ghost" className="ml-auto" onClick={() => navigate("/config/wiring")}>
          Open wiring
        </Button>
      </div>
    </div>
  );
}

import { motion } from "framer-motion";
import { Minus, Plus } from "lucide-react";

import { Button, Select, TextInput } from "@/components/common/controls";
import { useBoardPresence } from "@/lib/hardware/context";
import { springPanel } from "@/lib/motion";
import { BOX_COUNT, nextAvailableBox, newBinding, type BoxBinding } from "@/lib/settings/schema";

/**
 * Box → board bindings (ephymeris_v1.0.md §5).
 *
 * Bound by `hardware_id` — the board's USB serial number — rather than port
 * address, because Windows renumbers COM ports across reboots and
 * re-enumeration. Binding by address would silently re-point a box at the wrong
 * physical board, which for a rig where box number means cage position is a
 * data-integrity problem, not a cosmetic one.
 *
 * The list is user-managed and starts empty: a rig may run two boxes or six,
 * and six rows of "not bound" is a worse starting point than none. Box numbers
 * stay 1–6 (the stable protocol key); only which of them exist is configurable.
 */
export function BoxBindingsTable({
  boxes,
  onChange,
}: {
  boxes: BoxBinding[];
  onChange: (next: BoxBinding[]) => void;
}) {
  const detected = useBoardPresence();
  const nextBox = nextAvailableBox(boxes);

  function patch(box: number, changes: Partial<BoxBinding>) {
    onChange(boxes.map((b) => (b.box === box ? { ...b, ...changes } : b)));
  }

  function addBox() {
    if (nextBox === null) return;
    onChange([...boxes, newBinding(nextBox)].sort((a, b) => a.box - b.box));
  }

  function removeBox(box: number) {
    onChange(boxes.filter((b) => b.box !== box));
  }

  const boundElsewhere = (hardwareId: string, box: number) =>
    boxes.some((b) => b.box !== box && b.hardwareId === hardwareId);

  return (
    <div className="px-4 py-3.5">
      {boxes.length > 0 && (
        <div className="grid grid-cols-[38px_1fr_1.4fr_28px] items-center gap-x-3 pb-1.5 text-[11px] text-static">
          <span>Box</span>
          <span>Label</span>
          <span>Bound board</span>
          <span />
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        {boxes.map((binding) => {
            const options = [
              { value: "", label: binding.hardwareId ? "— unbind —" : "— not bound —" },
              ...detected
                .filter(
                  (d) =>
                    d.hardwareId === binding.hardwareId ||
                    !boundElsewhere(d.hardwareId, binding.box),
                )
                .map((d) => ({ value: d.hardwareId, label: `${d.hardwareId} (${d.address})` })),
              // Keep a binding visible even when its board is currently unplugged.
              ...(binding.hardwareId &&
              !detected.some((d) => d.hardwareId === binding.hardwareId)
                ? [{ value: binding.hardwareId, label: `${binding.hardwareId} (not detected)` }]
                : []),
            ];

            return (
              // Enter-only motion, deliberately. An exit animation here has to
              // collapse a CSS grid row, and if it ever fails to complete the
              // row you just deleted stays on screen — a bad trade for polish
              // on a settings form.
              <motion.div
                key={binding.box}
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={springPanel}
                className="grid grid-cols-[38px_1fr_1.4fr_28px] items-center gap-x-3"
              >
                <span className="font-mono text-[12px] text-static">{binding.box}</span>

                <TextInput
                  label={`Label for box ${binding.box}`}
                  value={binding.label}
                  placeholder={`Box ${binding.box}`}
                  onChange={(label) => patch(binding.box, { label })}
                  className="w-full"
                />

                <Select
                  label={`Board bound to box ${binding.box}`}
                  value={binding.hardwareId ?? ""}
                  options={options}
                  onChange={(v) =>
                    patch(binding.box, { hardwareId: v === "" ? null : String(v) })
                  }
                />

                <Button
                  variant="outline"
                  shape="icon"
                  onClick={() => removeBox(binding.box)}
                  title={`Remove box ${binding.box}`}
                >
                  <Minus size={14} strokeWidth={2} />
                </Button>
            </motion.div>
          );
        })}
      </div>

      {boxes.length === 0 && (
        <p className="text-[12px] leading-relaxed text-static">
          No boxes configured yet. Add one for each behavior box in the rig, then
          bind it to a connected board.
        </p>
      )}

      <div className="mt-3 flex items-center gap-3">
        <Button
          onClick={addBox}
          disabled={nextBox === null}
          title={nextBox === null ? `All ${BOX_COUNT} boxes are configured` : "Add a box"}
        >
          <Plus size={13} strokeWidth={1.75} />
          Add box
        </Button>

        {boxes.length > 0 && detected.length === 0 && (
          <span className="text-[11px] text-static">
            No boards detected — connected Arduinos appear here for binding.
          </span>
        )}
      </div>
    </div>
  );
}

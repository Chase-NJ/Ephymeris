import { motion } from "framer-motion";
import { Check, CheckCheck } from "lucide-react";

import { Button } from "@/components/common/controls";
import { springSnappy } from "@/lib/motion";

/**
 * The way back out of the boxes, ticked off — one row per box, and one button
 * for the operator who has already emptied the rig and does not want to be
 * walked through it.
 *
 * The placement walk (`SessionMapping`) goes one animal at a time because a
 * mis-placed animal is a silently mislabelled file. Removal has no such
 * failure: an animal carried to the wrong home cage is noticed at the cage,
 * not in the data. So this is a checklist, not a walk — it keeps count, and
 * **All animals are out** answers the whole thing in one press. The two
 * prompts that use it (the group swap and the session wrap-up) gate their
 * action on every row being ticked, so the shortcut is what makes that gate
 * a courtesy rather than a chore.
 */
export function ReturnChecklist({
  boxes,
  returned,
  onToggle,
  onAll,
  disabled = false,
}: {
  boxes: ReadonlyArray<{ box: number; animalName: string }>;
  returned: ReadonlySet<number>;
  onToggle: (box: number) => void;
  onAll: () => void;
  disabled?: boolean;
}) {
  const ordered = [...boxes].sort((a, b) => a.box - b.box);
  const allOut = ordered.length > 0 && ordered.every((b) => returned.has(b.box));
  const count = ordered.filter((b) => returned.has(b.box)).length;

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-[10px] text-static/70">
          {allOut ? (
            <span style={{ color: "var(--color-ion)" }}>every animal is home</span>
          ) : (
            `${count} of ${ordered.length} back in their cages`
          )}
        </span>
        {!allOut && (
          <Button variant="outline" disabled={disabled} onClick={onAll}>
            <CheckCheck size={13} strokeWidth={1.75} />
            All animals are out
          </Button>
        )}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
        {ordered.map(({ box, animalName }) => {
          const done = returned.has(box);
          return (
            <motion.button
              key={box}
              type="button"
              disabled={disabled}
              onClick={() => onToggle(box)}
              whileTap={{ scale: 0.98 }}
              transition={springSnappy}
              aria-pressed={done}
              className={`flex items-center gap-2 rounded-sm border px-2.5 py-1.5 text-left text-[12px] transition-colors ${
                done
                  ? "border-halo bg-halo/30 text-static"
                  : "border-halo bg-nebula text-starlight hover:border-static/50"
              }`}
            >
              <span
                aria-hidden
                className="flex size-4 shrink-0 items-center justify-center rounded-full border"
                style={{
                  borderColor: done ? "var(--color-ion)" : "var(--color-halo)",
                  background: done ? "var(--color-ion)" : "transparent",
                }}
              >
                {done && <Check size={11} strokeWidth={2.5} className="text-void" />}
              </span>
              <span className="shrink-0 font-mono text-[11px] text-static">Box {box}</span>
              <span className={`min-w-0 flex-1 truncate ${done ? "line-through" : ""}`}>
                {animalName}
              </span>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}

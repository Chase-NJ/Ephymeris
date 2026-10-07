import { AnimatePresence, motion } from "framer-motion";
import { Check, ChartLine, Home } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/common/controls";
import { RatPlacementBanner } from "@/components/sessions/RatPlacementBanner";
import { ReturnChecklist } from "@/components/sessions/ReturnChecklist";
import { springModal } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The end of the line — the last group has run, every box has finished, and
 * the operator's next act is to carry the animals home and close the session
 * (`USER-GUIDE.md#ending-the-session`).
 *
 * A pop-up rather than another centre-stage card, because this is the one
 * moment in the flow that is genuinely *over*: nothing on the rails is the
 * next step any more, and a prompt that shares the screen with six Start
 * buttons reads as one option among seven. It takes the screen, says what
 * happened, shows the placement scene played backwards (the same drawing the
 * group swap uses), keeps count of the animals going home, and ends the
 * session — landing on Analytics with this run already open.
 *
 * Still dismissable. "Not yet" puts the rails back for the operator who wants
 * to restart a box or read a tile before closing out; the End Session button
 * in the left rail is the same action and stays where it was.
 *
 * Matte throughout (`ARCHITECTURE.md#theme`): the flourish is three flat rings
 * expanding from the Ion check — the constellation's arrival rings, on a
 * surface instead of a star — and it stands still under reduced motion.
 */
export function SessionWrapUp({
  open,
  sessionName,
  boxes,
  facts,
  returned,
  busy,
  onToggle,
  onAll,
  onEnd,
  onAnotherGroup,
  onDismiss,
  log,
}: {
  open: boolean;
  sessionName: string;
  boxes: ReadonlyArray<{ box: number; animalName: string }>;
  /** The session in numbers — animals, groups, elapsed — as one mono line. */
  facts: string;
  returned: ReadonlySet<number>;
  busy: boolean;
  onToggle: (box: number) => void;
  onAll: () => void;
  onEnd: () => void;
  /** Every group has run, but one may be run again — offered on a multi-group
   *  cohort only, since groups no longer run in a fixed order to a fixed end. */
  onAnotherGroup?: (() => void) | undefined;
  onDismiss: () => void;
  /** The session log's corner (`USER-GUIDE.md#ending-the-session`) —
   *  optional, and never a step between the operator and End session. */
  log?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onDismiss]);

  const allOut = boxes.length > 0 && boxes.every((b) => returned.has(b.box));

  // Portalled to `body` for `Modal`'s reason: every card in the app carries a
  // backdrop-filter, and `fixed` is only viewport-relative outside one.
  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-8">
          <motion.div
            className="absolute inset-0 bg-void/70"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onDismiss}
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Session complete"
            className="vibrancy relative flex max-h-full w-full max-w-[640px] flex-col overflow-hidden rounded-lg border border-halo shadow-xl"
            initial={{ opacity: 0, scale: 0.96, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 8 }}
            transition={springModal}
          >
            <div className="min-h-0 overflow-y-auto p-6">
              <div className="flex items-center gap-4">
                <Flourish />
                <div className="min-w-0">
                  <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-static/70">
                    every group has run
                  </p>
                  <h2 className="font-display text-[24px] leading-tight text-starlight">
                    That&rsquo;s a wrap
                  </h2>
                  <p className="mt-0.5 font-mono text-[11px] text-static">
                    <span className="text-starlight">{sessionName}</span> · {facts}
                  </p>
                </div>
              </div>

              <p className="mt-4 text-[13px] leading-relaxed text-static">
                Every box has finished. Carry each animal back to its home cage,
                tick it off as you go, then end the session — the files are
                already on disk, and Analytics opens on this run.
              </p>

              {/* The same scene the group swap plays, for the same reason: the
                  drawing IS the instruction. Its own top margin is the gap. */}
              <RatPlacementBanner
                mode="return"
                boxes={boxes.map((b) => b.box)}
                caption="Home cages, not the next group — this was the last one."
              />

              <div className="mt-4">
                <ReturnChecklist
                  boxes={boxes}
                  returned={returned}
                  onToggle={onToggle}
                  onAll={onAll}
                  disabled={busy}
                />
              </div>

              {log}
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-halo px-6 py-4">
              <Button variant="ghost" disabled={busy} onClick={onDismiss}>
                Not yet
              </Button>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] text-static/70">
                  {allOut ? "ready to close out" : "tick every animal first"}
                </span>
                {onAnotherGroup && (
                  <Button disabled={busy || !allOut} onClick={onAnotherGroup}>
                    Run another group
                  </Button>
                )}
                <Button
                  variant="primary"
                  disabled={busy || !allOut}
                  onClick={onEnd}
                  {...(allOut
                    ? {}
                    : { title: "Every animal needs to be back in its cage first" })}
                >
                  <Home size={13} strokeWidth={1.75} />
                  {busy ? "Ending…" : "End session"}
                  <ChartLine size={13} strokeWidth={1.75} />
                </Button>
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

/**
 * The arrival rings, grounded: an Ion check with three flat rings breathing
 * outward from it. Rings are strokes, never blur — the pulsing journey star
 * and the constellation's arrival flourish are drawn the same way.
 */
function Flourish() {
  const reduceMotion = useReduceMotion();
  return (
    <span className="relative flex size-14 shrink-0 items-center justify-center" aria-hidden>
      {!reduceMotion &&
        [0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="absolute inset-0 rounded-full border"
            style={{ borderColor: "var(--color-ion)" }}
            initial={{ scale: 0.55, opacity: 0 }}
            animate={{ scale: [0.55, 1.35], opacity: [0, 0.55, 0] }}
            transition={{
              duration: 2.6,
              repeat: Infinity,
              delay: i * 0.85,
              ease: "easeOut",
            }}
          />
        ))}
      <span
        className="flex size-9 items-center justify-center rounded-full"
        style={{ background: "var(--color-ion)" }}
      >
        <Check size={20} strokeWidth={2.5} className="text-void" />
      </span>
    </span>
  );
}

import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useLayoutEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/common/controls";
import { springPanel, springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The walkthrough — a spotlight over the editor's OWN controls.
 *
 * A coach and not a wizard, deliberately. A wizard would be a second form over
 * the same document: two places that both have to agree about what a trial type
 * is, what clamps, and which values are legal — and the one that is used twice
 * a year is the one that drifts. It is also the shape this app already retired
 * once, when the five-step rig setup went. So the overlay
 * never collects anything. It dims the page, cuts a hole around the thing the
 * current step is about, and says what to do there; the operator edits the real
 * table underneath and the step ticks itself off when the document satisfies it.
 *
 * NOTHING IS BLOCKED. The scrim is `pointer-events-none` and only the step card
 * takes clicks, so every control stays live at every moment — including the ones
 * the spotlight is not on. That is the whole reason to prefer this shape: a
 * coach can be ignored, argued with, or worked around, and can never trap
 * someone in a step they cannot satisfy.
 *
 * The hole is measured, never modelled. `getBoundingClientRect` on a ref the
 * editor hands down, re-measured on scroll, on resize and on any layout change
 * the observer sees — because the centre column scrolls under a fixed overlay
 * and a remembered rectangle would drift off its target within one wheel click.
 */
export interface GuideStep {
  id: string;
  title: string;
  body: string;
  /** What the spotlight sits on. A step whose ref is empty is skipped. */
  target: RefObject<HTMLElement | null>;
  /** Whether the document already satisfies this step. Ticks it, and is what
   *  the last step's Finish waits on. */
  done: boolean;
  /** A step that is informational or genuinely optional — Next never waits. */
  optional?: boolean;
}

/** Breathing room around the cut-out, in px. */
const PAD = 8;
/** The step card's width, and how far it stands off the hole. */
const CARD_W = 268;
const GAP = 16;

export function TaskGuide({
  steps,
  onClose,
}: {
  steps: GuideStep[];
  onClose: () => void;
}) {
  const reduceMotion = useReduceMotion();
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);

  const step = steps[Math.min(index, steps.length - 1)];
  const target = step?.target.current ?? null;

  /* Measure. `useLayoutEffect` so the hole is placed in the same frame the step
   * changes — measuring in a passive effect showed the spotlight on the
   * PREVIOUS step's rectangle for a frame, which reads as a misfire. */
  useLayoutEffect(() => {
    if (!target) {
      setRect(null);
      return;
    }
    const measure = () => setRect(target.getBoundingClientRect());
    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(target);
    // The centre column scrolls under a fixed overlay, so this has to be the
    // capturing window listener rather than one on a container: the scroller is
    // whichever ancestor happens to have overflow, and this page has two.
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [target]);

  /* Bring the step's target into view when it becomes the step. `center`
   * rather than `nearest`: the card sits beside the hole, and a target flush
   * against the viewport edge leaves nowhere to put it. */
  useEffect(() => {
    target?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "center",
    });
  }, [target, reduceMotion]);

  /* The active control also takes the app's existing "the flow is waiting on
   * this" cue, so the spotlight is not the only signal — it is the one that is
   * invisible to anyone reading the page rather than looking at it. */
  useEffect(() => {
    if (!target) return;
    target.classList.add("attention-border");
    return () => target.classList.remove("attention-border");
  }, [target]);

  const close = useCallback(() => onClose(), [onClose]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  if (!step) return null;

  const last = index === steps.length - 1;
  const canAdvance = step.optional === true || step.done;

  /* The card goes to whichever side of the hole has room, and falls back to
   * pinning against the viewport when neither does — a card half off-screen is
   * worse than one overlapping the thing it describes. */
  const viewport = { w: window.innerWidth, h: window.innerHeight };
  const spaceRight = rect ? viewport.w - rect.right : 0;
  const onLeft = rect !== null && spaceRight < CARD_W + GAP * 2;
  const cardLeft = rect
    ? onLeft
      ? Math.max(GAP, rect.left - CARD_W - GAP)
      : Math.min(viewport.w - CARD_W - GAP, rect.right + GAP)
    : viewport.w - CARD_W - GAP * 2;
  const cardTop = rect
    ? Math.min(Math.max(GAP, rect.top), viewport.h - 220)
    : viewport.h / 2 - 110;

  // Portalled to the body: `.hud` and `.surface` carry `backdrop-filter`, which
  // creates a containing block and would make `fixed` resolve against a tile
  // rather than the viewport. `Modal` documents the same trap.
  return createPortal(
    <>
      {/* The scrim. One rect with a hole punched by a mask, rather than four
          rects around the target: a mask animates as one shape, so the
          spotlight TRAVELS between steps instead of four edges racing. */}
      <svg
        className="pointer-events-none fixed inset-0 z-40 h-full w-full"
        aria-hidden
      >
        <defs>
          <mask id="task-guide-hole">
            <rect x="0" y="0" width="100%" height="100%" fill="white" />
            {rect && (
              <motion.rect
                initial={false}
                animate={{
                  x: rect.left - PAD,
                  y: rect.top - PAD,
                  width: rect.width + PAD * 2,
                  height: rect.height + PAD * 2,
                }}
                transition={reduceMotion ? { duration: 0 } : springPanel}
                rx={10}
                fill="black"
              />
            )}
          </mask>
        </defs>
        <rect
          x="0"
          y="0"
          width="100%"
          height="100%"
          fill="var(--color-void)"
          opacity={0.72}
          mask="url(#task-guide-hole)"
        />
      </svg>

      <AnimatePresence mode="wait">
        <motion.aside
          key={step.id}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={springSnappy}
          style={{ left: cardLeft, top: cardTop, width: CARD_W }}
          className="vibrancy pointer-events-auto fixed z-50 flex flex-col gap-3 rounded-lg border border-halo p-4 shadow-xl"
        >
          <StepRail steps={steps} index={index} />

          <div>
            <h2 className="font-display text-[14px] font-semibold text-starlight">
              {step.title}
            </h2>
            <p className="mt-1.5 text-[12px] leading-relaxed text-static">{step.body}</p>
          </div>

          <div className="flex items-center justify-between gap-2">
            <Button variant="ghost" onClick={close}>
              Skip
            </Button>
            <div className="flex items-center gap-2">
              {index > 0 && (
                <Button variant="ghost" onClick={() => setIndex((i) => i - 1)}>
                  Back
                </Button>
              )}
              <Button
                variant="primary"
                disabled={!canAdvance}
                {...(canAdvance
                  ? {}
                  : {
                      title:
                        "Finish this step on the page behind — it ticks itself.",
                    })}
                onClick={() => (last ? close() : setIndex((i) => i + 1))}
              >
                {last ? "Finish" : "Next"}
              </Button>
            </div>
          </div>
        </motion.aside>
      </AnimatePresence>
    </>,
    document.body,
  );
}

/**
 * The step rail — `SessionJourney`'s vocabulary at card scale.
 *
 * Filled Pulsar for a step the document already satisfies, Starlight for the
 * one in hand, a Halo outline ahead. Reusing that grammar rather than inventing
 * a second progress idiom is the point: an operator has already learned it on
 * the session flow, and two dialects of "where am I" in one app is one too many.
 */
function StepRail({ steps, index }: { steps: GuideStep[]; index: number }) {
  return (
    <div className="flex items-center gap-1.5" aria-hidden>
      {steps.map((step, i) => {
        const active = i === index;
        const complete = step.done && !active;
        return (
          <span
            key={step.id}
            className="h-[3px] flex-1 rounded-full transition-colors"
            style={{
              background: active
                ? "var(--color-starlight)"
                : complete
                  ? "var(--color-pulsar)"
                  : "var(--color-halo)",
            }}
          />
        );
      })}
      <span className="ml-1 shrink-0 font-mono text-[10px] text-static/70">
        {index + 1}/{steps.length}
      </span>
    </div>
  );
}

import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { useRef } from "react";
import { Outlet, useLocation, useOutlet } from "react-router";

import { Sidebar } from "./Sidebar";
import { Starfield } from "./Starfield";
import { SvgDefs } from "./SvgDefs";
import { Titlebar } from "./Titlebar";
import { ConstellationStageProvider } from "@/components/constellation3d/SharedCanvas";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * Two-region layout per dashboard.md §2.1: custom titlebar across the top,
 * persistent sidebar on the left, content on the right. The starfield sits
 * behind the content region only — not behind the sidebar, whose frosted
 * surface would blur it into noise.
 */
export function AppShell() {
  const reduceMotion = useReduceMotion();

  return (
    <MotionConfig reducedMotion={reduceMotion ? "always" : "never"}>
      {/* One WebGL canvas for every constellation view, mounted here so it
          outlives route changes — the views adopt it in turn rather than each
          building (and tearing down) a renderer of their own
          (`constellation3d/SharedCanvas.tsx`). */}
      <ConstellationStageProvider>
        <div className="flex h-full flex-col bg-void">
          <SvgDefs />
          <Titlebar />
          <div className="flex min-h-0 flex-1">
            <Sidebar />
            <div className="relative min-w-0 flex-1">
              <Starfield />
              {/* overflow-x hidden explicitly: with only overflow-y set, CSS
                  computes overflow-x to auto, and the route transition's small
                  horizontal travel would flash a bottom scrollbar on every
                  guided-flow step. */}
              <main className="relative h-full overflow-x-hidden overflow-y-auto">
                <RouteTransition />
              </main>
            </div>
          </div>
        </div>
      </ConstellationStageProvider>
    </MotionConfig>
  );
}

/**
 * The guided flow's steps are a sequence, so moving between them travels
 * (`dashboard.md` §8.6): a step slides in from the side it came from
 * and leaves toward the side you're going, which makes Back read as going
 * back rather than as another arrival. Everything outside the flow crossfades
 * instead — a lateral slide between unrelated destinations would imply an
 * order the sidebar doesn't have.
 *
 * Only the **travel** lives here. Each route already fades its own content in
 * on mount; animating opacity here too would double every entrance.
 */
function RouteTransition() {
  const location = useLocation();
  // The element for the *current* match, captured per render. `<Outlet />`
  // reads live context, so an exiting copy of it would already be showing the
  // incoming page — the one thing a transition must not do.
  const outlet = useOutlet();
  const previousStep = useRef<number | null>(null);

  const step = flowStep(location.pathname);
  const from = previousStep.current;
  previousStep.current = step;

  // Direction only means something when both ends are in the flow.
  const direction = step !== null && from !== null ? Math.sign(step - from) : 0;
  const travel = direction * TRAVEL;

  return (
    // `popLayout`, never `wait`: `wait` holds the incoming page until the
    // outgoing one finishes exiting, so anything that stalls an exit animation
    // stalls navigation itself — the app would look broken rather than
    // unpolished. Here the new page mounts immediately and the old one is
    // lifted out of layout flow to leave, so a transition can slow down but
    // can never block.
    <AnimatePresence mode="popLayout" initial={false}>
      <motion.div
        key={location.pathname}
        initial={{ x: travel }}
        animate={{ x: 0 }}
        exit={{ x: -travel, opacity: 0 }}
        transition={springSnappy}
        className="h-full"
      >
        {outlet ?? <Outlet />}
      </motion.div>
    </AnimatePresence>
  );
}

/** How far a step slides, in px. Small on purpose — this is a hint of travel,
 *  not a carousel. */
const TRAVEL = 26;

/**
 * Where a path sits in the guided sequence, or null if it isn't part of it.
 * Analytics is the flow's last step (§2.5's landing), so ending a session
 * travels forward into it rather than cutting.
 */
function flowStep(pathname: string): number | null {
  // The Dashboard is the flow's start now that /launch is retired (§3.2) —
  // its hero CTA and session dock are where every session journey begins.
  if (pathname === "/") return 0;
  if (pathname === "/session/new") return 1;
  if (/^\/session\/[^/]+\/mapping$/.test(pathname)) return 2;
  if (/^\/session\/[^/]+\/control$/.test(pathname)) return 3;
  if (pathname === "/analytics") return 4;
  return null;
}

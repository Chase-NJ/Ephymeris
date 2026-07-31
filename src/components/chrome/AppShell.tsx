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
 * persistent sidebar on the left, content on the right.
 *
 * **The sidebar floats over the content region rather than sitting beside it.**
 * Its glass is thin enough to read the sky through (§2.4), which is only worth
 * anything if there is sky behind it — so the content region spans the full
 * width and the sidebar is an overlay on top of it. `main` carries a matching
 * left padding, so every ordinary in-flow route clears the sidebar without
 * knowing it exists; the three constellation views reach back underneath with a
 * negative offset on their sky layer alone (their chrome stays put). All three
 * numbers are the one `--spacing-sidebar` token.
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
          <div className="relative min-h-0 flex-1">
            {/* Full-bleed, including behind the sidebar — the drifting 2D sky
                is the backdrop the sidebar's glass has to sit on when no
                constellation view is mounted. */}
            <Starfield />
            {/* overflow-x hidden explicitly: with only overflow-y set, CSS
                computes overflow-x to auto, and the route transition's small
                horizontal travel would flash a bottom scrollbar on every
                guided-flow step. It clips to the *padding* box, so a sky layer
                reaching left under the sidebar survives it. */}
            {/* The scrollbar's track is reserved whether or not it is showing.
                Without that, a page briefly taller than the frame — which every
                route transition is, since the outgoing and incoming pages
                overlap — pops a scrollbar into existence and takes it away
                again, and every element in the content area shifts sideways and
                back with it. **Including the stars**: the sky's canvas is sized
                by this element's content box (`Scene.tsx`), so 10px there is a
                renderer resize and a new `camera.aspect`, and the whole
                constellation moves.

                Reserved **twice**, and the belt matters more than the braces.
                `scrollbar-gutter` is the property for this, but it only shipped
                in Safari 18.2 and the macOS shell is a WKWebView — on anything
                older it is simply ignored and the shift is back. `overflow-y:
                scroll` reserves the track in every engine, and costs nothing
                visible here because the track is already transparent
                (`index.css`) and the thumb only paints when there is something
                to scroll. */}
            <main
              className="relative h-full overflow-x-hidden overflow-y-scroll pl-sidebar"
              style={{ scrollbarGutter: "stable" }}
            >
              <RouteTransition />
            </main>
            {/* Last, and above both: the overlay is what makes the sky read
                through the glass. */}
            <Sidebar />
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
 *
 * The exit fade has one exception: **every view of the rig's sky**. They are the
 * same constellation with different chrome around it, and the shared canvas is
 * *handed over* rather than redrawn (`SharedCanvas.tsx`), so a page-wide fade
 * dissolves a page that is mostly still on screen — and it washes out the one
 * thing that should read: one chrome leaving as another arrives in its place.
 * Between two of them, each page fades its own chrome and the sky carries on.
 *
 * > [!IMPORTANT]
 * > **A sky route must own its `exit`.** Nothing else will fade it, because this
 * > holds the page at `opacity: 1` on the way out. Every route named here has an
 * > `exit` on its chrome wrapper; adding one without is how a page ends up
 * > sitting fully opaque over its successor for the length of the transition.
 */
const isSkyRoute = (pathname: string): boolean =>
  pathname === "/" || pathname === "/debug" || pathname.startsWith("/session/");

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
  // This element's *own* path, closed over so the exit variant below can name
  // the page that is leaving. `location.pathname` is no use for that at exit
  // time: AnimatePresence re-renders the cached previous element, but hooks
  // inside it read live context and would report the page that replaced it.
  const path = location.pathname;

  return (
    // `popLayout`, never `wait`: `wait` holds the incoming page until the
    // outgoing one finishes exiting, so anything that stalls an exit animation
    // stalls navigation itself — the app would look broken rather than
    // unpolished. Here the new page mounts immediately and the old one is
    // lifted out of layout flow to leave, so a transition can slow down but
    // can never block.
    //
    // `custom` carries the **incoming** pathname to exiting children. That is
    // what `custom` is for: an exiting child's own props are frozen at the
    // render that mounted it, so a plain `exit` object could only ever describe
    // the navigation that brought the page *in*, not the one taking it out.
    <AnimatePresence mode="popLayout" initial={false} custom={location.pathname}>
      <motion.div
        key={location.pathname}
        initial={{ x: travel }}
        animate={{ x: 0 }}
        exit="exit"
        variants={{
          exit: (incoming: string) => ({
            x: -travel,
            // Held opaque only when both ends are the rig's sky; every other
            // navigation still crossfades.
            opacity: isSkyRoute(path) && isSkyRoute(incoming) ? 1 : 0,
          }),
        }}
        // Deliberately only animatable values. The exiting page also has to
        // stop taking clicks — `popLayout` pins it absolutely, so it paints
        // *above* the page that replaced it and its `pointer-events-auto` tiles
        // would stay hit-testable while they fade. That belongs in CSS, off
        // framer's own `[data-motion-pop-id]` (`index.css`), rather than as a
        // non-animatable value smuggled into an animation target.
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

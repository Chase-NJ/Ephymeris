import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { useRef } from "react";
import { Outlet, useLocation, useOutlet } from "react-router";

import { ExportProgress } from "./ExportProgress";
import { Sidebar } from "./Sidebar";
import { Starfield } from "./Starfield";
import { SvgDefs } from "./SvgDefs";
import { Titlebar } from "./Titlebar";
import { ConstellationStageProvider } from "@/components/constellation3d/SharedCanvas";
import { springSnappy } from "@/lib/motion";
import { useUpdateChecks } from "@/lib/updates/store";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * Two-region layout: custom titlebar across the top, persistent sidebar on
 * the left, content on the right.
 *
 * **The sidebar floats over the content region rather than sitting beside it.**
 * Its glass is thin enough to read the sky through, which is only worth
 * anything if there is sky behind it — so the content region spans the full
 * width and the sidebar is an overlay on top of it. `main` carries a matching
 * left padding, so every ordinary in-flow route clears the sidebar without
 * knowing it exists; the three constellation views reach back underneath with a
 * negative offset on their sky layer alone (their chrome stays put). All three
 * numbers are the one `--spacing-sidebar` token.
 */
export function AppShell() {
  const reduceMotion = useReduceMotion();
  // Here because the shell outlives every route: the check runs at launch
  // whichever screen opens first (`ARCHITECTURE.md#updates`).
  useUpdateChecks();

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
            {/* Above every route, and outliving them: an export started on
                one tab is still reporting when the operator is on another. */}
            <ExportProgress />
          </div>
        </div>
      </ConstellationStageProvider>
    </MotionConfig>
  );
}

/**
 * The guided flow's steps are a sequence, so moving between them travels
 * (`ARCHITECTURE.md#the-flow`): a step slides in from the side it came from
 * and leaves toward the side you're going, which makes Back read as going
 * back rather than as another arrival. Everything outside the flow crossfades
 * instead — a lateral slide between unrelated destinations would imply an
 * order the sidebar doesn't have.
 *
 * Only the **travel** lives here. Each route already fades its own content in
 * on mount; animating opacity here too would double every entrance.
 *
 * **The page is never faded here, only moved.** Every route now sits on the rig's
 * sky (`SkyBackdrop`), and the shared canvas physically lives in the active
 * route's subtree — so a page-wide opacity animation fades the constellation
 * along with the chrome, and since every route shows the same sky that made it
 * blink out and back on every single navigation. It also washes out the one
 * thing that should read: one chrome leaving as another arrives in its place.
 *
 * > [!IMPORTANT]
 * > **Every route must own its `exit`.** Nothing else will fade it. This used to
 * > be conditional — a `SKY_ROUTES` set, holding only the constellation views
 * > opaque — and the condition disappeared when the sky went behind everything.
 * > A route added without an `exit` on its chrome wrapper sits fully opaque over
 * > its successor for the length of the transition.
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
    //
    <AnimatePresence mode="popLayout" initial={false}>
      <motion.div
        key={location.pathname}
        initial={{ x: travel }}
        animate={{ x: 0 }}
        // Travel only — never opacity. See the note above: the sky lives in this
        // subtree, and fading the page fades the constellation with it.
        exit={{ x: -travel }}
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
 * Analytics is the flow's last step, so ending a session
 * travels forward into it rather than cutting.
 */
function flowStep(pathname: string): number | null {
  // The Dashboard is the flow's start now that /launch is retired —
  // its hero CTA and session dock are where every session journey begins.
  if (pathname === "/") return 0;
  if (pathname === "/session/new") return 1;
  if (/^\/session\/[^/]+\/mapping$/.test(pathname)) return 2;
  // A recording session's extra step (`RECORDING.md#record-step`). Fractional
  // so the steps either side keep their numbers — what matters is only the
  // ORDER, which decides which way a transition travels.
  if (/^\/session\/[^/]+\/recording$/.test(pathname)) return 2.5;
  if (/^\/session\/[^/]+\/control$/.test(pathname)) return 3;
  if (pathname === "/analytics") return 4;
  return null;
}

/**
 * Shared motion constants.
 *
 * `ARCHITECTURE.md#theme` specifies Framer Motion **spring physics**, not
 * duration/easing curves, for nav selection, panel transitions, and modal
 * open/close — the closest web equivalent to UIKit/SwiftUI transitions. Import
 * these rather than hand-tuning a transition at the call site, so the app keeps
 * one physical feel.
 */

import type { Transition } from "framer-motion";

/** Nav selection and other small, frequent movements. Quick, barely overshoots. */
export const springSnappy: Transition = {
  type: "spring",
  stiffness: 520,
  damping: 38,
  mass: 0.8,
};

/** Panel and view transitions. */
export const springPanel: Transition = {
  type: "spring",
  stiffness: 320,
  damping: 34,
  mass: 0.9,
};

/** Modals and larger surfaces entering. Softer, more deliberate. */
export const springModal: Transition = {
  type: "spring",
  stiffness: 260,
  damping: 30,
  mass: 1,
};

/**
 * How far a right-docked panel travels as it enters or leaves, in px.
 *
 * Shared so a panel and whatever it *replaces* move the same distance on the
 * same spring — the Dashboard's overview column leaving toward +x while Debug's
 * `NodeDetail` arrives from +x is what makes a star click read as one panel
 * being swapped rather than one thing blinking out and another appearing.
 */
export const PANEL_TRAVEL = 24;

/**
 * A page's tile stack arriving as a cascade — parent takes `CASCADE`, each
 * tile takes `RISE`, and the panels assemble top-down 55 ms apart instead of
 * slamming in on one frame. One clock here rather than one per page, so every
 * tab's entrance carries the same rhythm; the whole cascade stays under a
 * quarter second, which reads as one entrance rather than a slideshow.
 */
export const CASCADE = {
  hidden: {},
  shown: { transition: { staggerChildren: 0.055 } },
};

export const RISE = {
  hidden: { opacity: 0, y: 10 },
  shown: { opacity: 1, y: 0, transition: springPanel },
};

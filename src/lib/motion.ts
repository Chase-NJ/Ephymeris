/**
 * Shared motion constants.
 *
 * dashboard.md §1.5 specifies Framer Motion **spring physics**, not
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

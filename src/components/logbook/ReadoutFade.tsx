import { motion } from "framer-motion";
import type { ReactNode } from "react";

import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * A session page's contents changing channel: keyed by the caller on the
 * session, it fades and lifts the *contents* of a glass tile in, while the
 * tile itself stays mounted.
 *
 * Never put this, or any opacity animation, on an ancestor of the `.hud`
 * glass. An element below full opacity is a backdrop root, so while it fades
 * every tile inside it blurs only the transparent group instead of the sky —
 * the frosting drops out and snaps back when the fade lands, on every switch.
 * Remounting the glass also re-creates its blur layers, which WebKit (the
 * macOS shell) pays for dearly. Fading what is *on* the glass has neither cost.
 *
 * Entering only, no exit: stepping the rail quickly must never show an empty
 * tile between two sessions.
 */
export function ReadoutFade({ children }: { children: ReactNode }) {
  const reduce = useReduceMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springSnappy}
    >
      {children}
    </motion.div>
  );
}

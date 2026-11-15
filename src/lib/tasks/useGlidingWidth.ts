import { useMotionValueEvent, useSpring } from "framer-motion";
import { useEffect, useRef, useState } from "react";

import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The state machine's layout width, carried on a spring.
 *
 * `frameFor` is pure and cheap, so the drawing re-lays itself out at every
 * frame of the spring: nodes, edge curves, labels and chips all slide together
 * to their new places, because each is still positioned by the same `Frame`.
 * Nothing per element animates; the geometry does.
 *
 * Until the host is measured, and on that first measurement, the width jumps
 * (there is nothing on screen to move from); under reduced motion every
 * change does.
 */
export function useGlidingWidth(target: number, measured: boolean): number {
  const reduceMotion = useReduceMotion();
  // `springPanel`'s constants: the page's columns move on the same spring, so
  // the drawing and the tiles around it arrive together.
  const spring = useSpring(target, { stiffness: 320, damping: 34, mass: 0.9 });
  const [width, setWidth] = useState(target);
  const settled = useRef(false);

  useMotionValueEvent(spring, "change", (w) => setWidth(Math.round(w)));

  useEffect(() => {
    if (!measured || !settled.current || reduceMotion) {
      spring.jump(target);
      setWidth(target);
      if (measured) settled.current = true;
      return;
    }
    spring.set(target);
  }, [spring, target, measured, reduceMotion]);

  return width;
}

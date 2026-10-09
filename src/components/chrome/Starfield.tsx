import { useMemo } from "react";

import { mulberry32 } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";
import { useWindowFocus } from "@/lib/useWindowFocus";

/**
 * Ambient drifting starfield (`ARCHITECTURE.md#theme`).
 *
 * Deliberately constrained: a very slow loop at very low opacity, sitting
 * behind content. Two rules from the spec are load-bearing rather than polish —
 * it respects `prefers-reduced-motion`, and it **pauses when the window loses
 * focus**, because this app is watched during live data collection and ambient
 * effects must never compete for attention.
 *
 * It drifts the way the 3D sky's stars do from the default view — left and a
 * little up (`skyDrift.ts`) — because the sidebar shows this beside the canvas,
 * and two skies flowing different ways would read as two places.
 *
 * Plain CSS rather than Framer Motion: the spring physics of the theme govern
 * UI transitions, whereas this is a continuous linear drift, and a CSS
 * animation costs nothing per frame in JS.
 */

interface Star {
  x: number;
  y: number;
  r: number;
  o: number;
}

function makeStars(count: number, seed: number): Star[] {
  const rand = mulberry32(seed);
  return Array.from({ length: count }, () => ({
    x: rand() * 100,
    y: rand() * 100,
    r: 0.35 + rand() * 0.75,
    o: 0.2 + rand() * 0.45,
  }));
}

function StarLayer({ stars, opacity }: { stars: Star[]; opacity: number }) {
  return (
    <svg
      className="absolute inset-x-0 top-0 h-full w-full"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      style={{ opacity }}
      aria-hidden
    >
      {stars.map((s, i) => (
        <circle
          key={i}
          cx={s.x}
          cy={s.y}
          r={s.r / 10}
          fill="var(--color-starlight)"
          opacity={s.o}
        />
      ))}
    </svg>
  );
}

/**
 * One parallax layer. The stars are tiled 2×2 and the two axes loop on their
 * own periods — the vertical about three times slower, which on a landscape
 * frame tilts the flow about twelve degrees above leftward — so each axis
 * wraps seamlessly whatever the direction.
 */
function DriftLayer({
  stars,
  opacity,
  periodX,
  periodY,
  playState,
}: {
  stars: Star[];
  opacity: number;
  periodX: number;
  periodY: number;
  playState: "running" | "paused";
}) {
  return (
    <div
      className="absolute inset-x-0 top-0 h-[200%]"
      style={{ animation: `ephymeris-drift-y ${periodY}s linear infinite`, animationPlayState: playState }}
    >
      {[0, 1].map((row) => (
        <div key={row} className="relative h-1/2 w-full">
          <div
            className="absolute inset-y-0 left-0 flex w-[200%]"
            style={{ animation: `ephymeris-drift-x ${periodX}s linear infinite`, animationPlayState: playState }}
          >
            <div className="relative h-full w-1/2">
              <StarLayer stars={stars} opacity={opacity} />
            </div>
            <div className="relative h-full w-1/2">
              <StarLayer stars={stars} opacity={opacity} />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function Starfield() {
  const reduceMotion = useReduceMotion();
  const focused = useWindowFocus();

  const far = useMemo(() => makeStars(90, 0x5eed1), []);
  const near = useMemo(() => makeStars(38, 0x5eed2), []);

  // Paused rather than unmounted: the sky shouldn't visibly disappear when the
  // user tabs away and reappear when they come back.
  const playState = focused && !reduceMotion ? "running" : "paused";

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
      <style>{`
        @keyframes ephymeris-drift-x {
          from { transform: translate3d(0, 0, 0); }
          to   { transform: translate3d(-50%, 0, 0); }
        }
        @keyframes ephymeris-drift-y {
          from { transform: translate3d(0, 0, 0); }
          to   { transform: translate3d(0, -50%, 0); }
        }
      `}</style>

      <DriftLayer stars={far} opacity={0.3} periodX={240} periodY={720} playState={playState} />
      <DriftLayer stars={near} opacity={0.45} periodX={160} periodY={480} playState={playState} />
    </div>
  );
}

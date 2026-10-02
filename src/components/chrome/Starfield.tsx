import { useEffect, useMemo, useState } from "react";

import { mulberry32 } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * Ambient drifting starfield (`ARCHITECTURE.md#theme`).
 *
 * Deliberately constrained: a very slow loop at very low opacity, sitting
 * behind content. Two rules from the spec are load-bearing rather than polish —
 * it respects `prefers-reduced-motion`, and it **pauses when the window loses
 * focus**, because this app is watched during live data collection and ambient
 * effects must never compete for attention.
 *
 * Plain CSS rather than Framer Motion: the spring physics of the theme govern
 * UI transitions, whereas this is a continuous linear drift, and a 90s CSS
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

export function Starfield() {
  const reduceMotion = useReduceMotion();
  const [focused, setFocused] = useState(true);

  useEffect(() => {
    const onFocus = () => setFocused(true);
    const onBlur = () => setFocused(false);
    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", onBlur);
    };
  }, []);

  const far = useMemo(() => makeStars(90, 0x5eed1), []);
  const near = useMemo(() => makeStars(38, 0x5eed2), []);

  // Paused rather than unmounted: the sky shouldn't visibly disappear when the
  // user tabs away and reappear when they come back.
  const playState = focused && !reduceMotion ? "running" : "paused";

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
      <style>{`
        @keyframes ephymeris-drift {
          from { transform: translate3d(0, 0, 0); }
          to   { transform: translate3d(0, -50%, 0); }
        }
      `}</style>

      {/* Each layer renders its stars twice, stacked, so the -50% translate
          loops seamlessly. */}
      <div
        className="absolute inset-x-0 top-0 h-[200%]"
        style={{ animation: "ephymeris-drift 140s linear infinite", animationPlayState: playState }}
      >
        <div className="relative h-1/2 w-full">
          <StarLayer stars={far} opacity={0.3} />
        </div>
        <div className="relative h-1/2 w-full">
          <StarLayer stars={far} opacity={0.3} />
        </div>
      </div>

      <div
        className="absolute inset-x-0 top-0 h-[200%]"
        style={{ animation: "ephymeris-drift 90s linear infinite", animationPlayState: playState }}
      >
        <div className="relative h-1/2 w-full">
          <StarLayer stars={near} opacity={0.45} />
        </div>
        <div className="relative h-1/2 w-full">
          <StarLayer stars={near} opacity={0.45} />
        </div>
      </div>
    </div>
  );
}

import { motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";

import {
  NODE_FILL,
  frameFor,
  isLinkLive,
  resolveLayout,
  useBoxHealth,
  type BoxHealth,
} from "@/components/chrome/ConstellationStatus";
import {
  LINK_OPACITY_DIM,
  LINK_OPACITY_LIVE,
  LINK_STROKE,
  LINK_WIDTH,
  NODE_RADIUS,
} from "@/components/chrome/constellationStyle";
import { mulberry32 } from "@/lib/prng";
import { springSnappy } from "@/lib/motion";
import { useBoundBoxes, useSettings } from "@/lib/settings/context";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The Debug landing constellation (ephymeris_v1.0.md §4.3): the user's chosen
 * zodiac layout as the mode's front door. Each configured box is a clickable
 * node at its assigned star, nicknamed; selecting one opens the node detail
 * view.
 *
 * Ambient animation follows the Starfield's rules, not Framer's: continuous
 * motion is plain CSS (a spring is a transition, not an orbit), it pauses when
 * the window blurs — this app is watched during live data collection — and
 * reduced motion stills everything. What moves says something true:
 *
 *  - a detected box has a mote in orbit (it's alive on the bus);
 *  - an *open* box (passthrough / in session) adds a slow dashed ring — the
 *    instrument-HUD read, never a glow (§2.2);
 *  - a configured-but-undetected box sits still in Halo, and a faulted box
 *    still in Error red — stillness is the status.
 */

const TWINKLE_SEED = 0xdeb06;

export function DebugConstellation({ onSelect }: { onSelect: (box: number) => void }) {
  const { settings } = useSettings();
  const bound = useBoundBoxes();
  const health = useBoxHealth();
  const reduceMotion = useReduceMotion();
  const focused = useWindowFocused();
  const [hovered, setHovered] = useState<number | null>(null);

  const layout = useMemo(
    () => resolveLayout(settings.constellation, settings.constellationSlots, bound),
    [settings.constellation, settings.constellationSlots, bound],
  );
  const labels = useMemo(
    () => Object.fromEntries(settings.boxes.map((b) => [b.box, b.label])),
    [settings.boxes],
  );

  const at = (box: number): BoxHealth => health[box] ?? "absent";
  const starAt = useMemo(() => {
    const map = new Map<number, { x: number; y: number; box: number | null }>();
    for (const s of layout.emptyStars) map.set(s.star, { x: s.x, y: s.y, box: null });
    for (const n of layout.nodes) map.set(n.star, { x: n.x, y: n.y, box: n.box });
    return map;
  }, [layout]);

  const allPoints = [...layout.nodes, ...layout.emptyStars];
  const { viewBox, scale } = frameFor(allPoints);
  const frameCenterX = useMemo(() => {
    const xs = allPoints.map((p) => p.x);
    return (Math.min(...xs) + Math.max(...xs)) / 2;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewBox]);

  // Deterministic twinkle phases, so the sky doesn't reshuffle on re-render.
  const twinklePhase = useMemo(() => {
    const rand = mulberry32(TWINKLE_SEED);
    return layout.emptyStars.map(() => rand() * 6);
  }, [layout.emptyStars]);

  const playState = focused && !reduceMotion ? "running" : "paused";

  return (
    <div className="mx-auto w-full max-w-3xl">
      <style>{`
        @keyframes ephy-orbit {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
        @keyframes ephy-twinkle {
          0%, 100% { opacity: 0.22; }
          50%      { opacity: 0.55; }
        }
      `}</style>

      <svg
        viewBox={viewBox}
        className="w-full overflow-visible"
        preserveAspectRatio="xMidYMid meet"
        role="list"
        aria-label="Configured boxes"
      >
        {layout.edges.map(([a, b]) => {
          const from = starAt.get(a);
          const to = starAt.get(b);
          if (!from || !to) return null;
          const live =
            from.box !== null && to.box !== null && isLinkLive(at(from.box), at(to.box));
          return (
            <motion.line
              key={`${a}-${b}`}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={LINK_STROKE}
              strokeWidth={LINK_WIDTH * scale * 0.8}
              animate={{ opacity: live ? LINK_OPACITY_LIVE : LINK_OPACITY_DIM }}
              transition={springSnappy}
            />
          );
        })}

        {/* Unclaimed stars twinkle gently — scenery, not status. */}
        {layout.emptyStars.map((s, index) => (
          <circle
            key={`empty-${s.star}`}
            cx={s.x}
            cy={s.y}
            r={NODE_RADIUS * 0.5 * scale}
            fill="var(--color-starlight)"
            style={{
              animation: reduceMotion
                ? undefined
                : `ephy-twinkle ${5 + (index % 3)}s ease-in-out infinite`,
              animationDelay: `${twinklePhase[index] ?? 0}s`,
              animationPlayState: playState,
              opacity: 0.3,
            }}
          />
        ))}

        {layout.nodes.map((n) => {
          const h = at(n.box);
          const detected = h === "nominal" || h === "idle";
          const open = h === "nominal";
          const isHovered = hovered === n.box;
          const labelRight = n.x <= frameCenterX;
          const r = NODE_RADIUS * scale;

          return (
            <g
              key={n.box}
              transform={`translate(${n.x} ${n.y})`}
              role="listitem"
              aria-label={`${labels[n.box] ?? `Box ${n.box}`} — ${h}`}
              className="cursor-pointer"
              onClick={() => onSelect(n.box)}
              onPointerEnter={() => setHovered(n.box)}
              onPointerLeave={() => setHovered(null)}
            >
              {/* Generous invisible hit area. */}
              <circle r={r * 3.2} fill="transparent" />

              {/* Open box: slow dashed instrument ring. */}
              {open && (
                <g
                  style={{
                    animation: "ephy-orbit 24s linear infinite",
                    animationPlayState: playState,
                  }}
                >
                  <circle
                    r={r * 2.1}
                    fill="none"
                    stroke={LINK_STROKE}
                    strokeWidth={LINK_WIDTH * scale * 0.6}
                    strokeDasharray={`${r * 0.9} ${r * 0.7}`}
                    opacity={0.45}
                  />
                </g>
              )}

              {/* Detected box: a mote in orbit — alive on the bus. */}
              {detected && (
                <g
                  style={{
                    animation: `ephy-orbit ${open ? 6 : 11}s linear infinite`,
                    animationPlayState: playState,
                  }}
                >
                  <circle
                    cx={r * 2.6}
                    r={r * 0.28}
                    fill="var(--color-starlight)"
                    opacity={0.85}
                  />
                </g>
              )}

              <motion.circle
                r={r}
                animate={{ fill: NODE_FILL[h], scale: isHovered ? 1.25 : 1 }}
                transition={springSnappy}
              />

              {/* Nickname, set in the data face (§2.3), on the roomy side. */}
              <text
                x={labelRight ? r * 3.9 : -r * 3.9}
                textAnchor={labelRight ? "start" : "end"}
                dominantBaseline="middle"
                pointerEvents="none"
                className="font-mono"
                style={{
                  fontSize: 3.1 * scale,
                  fill: isHovered ? "var(--color-starlight)" : "var(--color-static)",
                  transition: "fill 150ms",
                }}
              >
                {labels[n.box] ?? `Box ${n.box}`}
              </text>
              <line
                x1={labelRight ? r * 1.6 : -r * 1.6}
                x2={labelRight ? r * 3.4 : -r * 3.4}
                stroke="var(--color-halo)"
                strokeWidth={LINK_WIDTH * scale * 0.5}
                opacity={0.8}
              />
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function useWindowFocused(): boolean {
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
  return focused;
}

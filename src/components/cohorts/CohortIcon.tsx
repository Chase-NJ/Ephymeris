import { motion } from "framer-motion";
import { useMemo } from "react";

import {
  LINK_OPACITY_DIM,
  LINK_OPACITY_LIVE,
  LINK_STROKE,
  LINK_WIDTH,
  NODE_ACCENT,
  NODE_PRIMARY,
} from "@/components/chrome/constellationStyle";
import { seededRandom } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * Procedurally generated cohort icon — `cohorts.md` §5.
 *
 * **Derived, not stored.** Computed from the cohort's `id` on every render, so
 * nothing about the icon needs a database column and it can never fall out of
 * sync with the record it represents.
 *
 * Group membership is deliberately *not* encoded (§5): this stays a "how many
 * animals" glyph rather than becoming a dense infographic. Group count lives in
 * the card's text stat line instead.
 */

/** §5.2 — above this, individual nodes stop being legible. */
const MAX_NODES = 8;

const VIEW = 100;
const CENTER = VIEW / 2;
/** Keeps the outermost node and its radius inside the viewBox. */
const MAX_ORBIT = 34;

interface Node {
  x: number;
  y: number;
  r: number;
  opacity: number;
  hero: boolean;
  /** Seeded twinkle timing, so nodes don't pulse in lockstep. */
  period: number;
  delay: number;
}

interface Generated {
  nodes: Node[];
  links: Array<[number, number]>;
  cluster: boolean;
}

function generate(id: string, animalCount: number): Generated {
  const rand = seededRandom(id);
  // An empty cohort still needs a mark — one lone star reads as "nothing here
  // yet" without a special-case empty glyph.
  const count = Math.max(1, Math.min(animalCount, MAX_NODES));
  const cluster = animalCount > MAX_NODES;

  // §5.5 — exactly one hero star per icon, seeded.
  const heroIndex = Math.floor(rand() * count);

  const nodes: Node[] = [];
  for (let i = 0; i < count; i += 1) {
    // §5.3 — even angular spacing plus jitter, so it doesn't look mechanical.
    const step = (Math.PI * 2) / count;
    const angle = i * step + (rand() - 0.5) * step * 0.55;
    const orbit = count === 1 ? 0 : MAX_ORBIT * (0.45 + rand() * 0.55);

    nodes.push({
      x: CENTER + Math.cos(angle) * orbit,
      y: CENTER + Math.sin(angle) * orbit,
      // §5.5 — seeded size/opacity variation for texture.
      r: 3.4 + rand() * 2.6,
      opacity: 0.62 + rand() * 0.38,
      hero: i === heroIndex,
      period: 2.6 + rand() * 3.4,
      delay: rand() * 3,
    });
  }

  // §5.4 — each node links to its nearest neighbour. Deduped by ordered pair,
  // since A's nearest being B and B's nearest being A is the common case.
  const seen = new Set<string>();
  const links: Array<[number, number]> = [];
  for (let i = 0; i < nodes.length; i += 1) {
    let best = -1;
    let bestDistance = Infinity;
    for (let j = 0; j < nodes.length; j += 1) {
      if (i === j) continue;
      const a = nodes[i]!;
      const b = nodes[j]!;
      const distance = (a.x - b.x) ** 2 + (a.y - b.y) ** 2;
      if (distance < bestDistance) {
        bestDistance = distance;
        best = j;
      }
    }
    if (best < 0) continue;
    const key = i < best ? `${i}-${best}` : `${best}-${i}`;
    if (seen.has(key)) continue;
    seen.add(key);
    links.push([i, best]);
  }

  return { nodes, links, cluster };
}

export function CohortIcon({
  cohortId,
  animalCount,
  size = 56,
  /** Cards accelerate the twinkle on hover (§4, Motion). */
  lively = false,
  className = "",
}: {
  cohortId: string;
  animalCount: number;
  size?: number;
  lively?: boolean;
  className?: string;
}) {
  const reduceMotion = useReduceMotion();
  const { nodes, links, cluster } = useMemo(
    () => generate(cohortId, animalCount),
    [cohortId, animalCount],
  );

  return (
    <svg
      viewBox={`0 0 ${VIEW} ${VIEW}`}
      width={size}
      height={size}
      className={className}
      aria-hidden
    >
      {links.map(([a, b]) => {
        const from = nodes[a]!;
        const to = nodes[b]!;
        return (
          <line
            key={`${a}-${b}`}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
            stroke={LINK_STROKE}
            strokeWidth={LINK_WIDTH * 1.6}
            opacity={LINK_OPACITY_LIVE}
          />
        );
      })}

      {nodes.map((node, index) => {
        const fill = node.hero ? NODE_ACCENT : NODE_PRIMARY;
        // §5.7 — static render under reduced motion, same as every other
        // ambient animation in the app.
        if (reduceMotion) {
          return (
            <circle
              key={index}
              cx={node.x}
              cy={node.y}
              r={node.r}
              fill={fill}
              opacity={node.opacity}
            />
          );
        }
        return (
          <motion.circle
            key={index}
            cx={node.x}
            cy={node.y}
            r={node.r}
            fill={fill}
            animate={{ opacity: [node.opacity, node.opacity * 0.45, node.opacity] }}
            transition={{
              duration: node.period / (lively ? 2.2 : 1),
              delay: node.delay,
              repeat: Infinity,
              ease: "easeInOut",
            }}
          />
        );
      })}

      {/* §5.2 — past the node cap, a denser cluster glyph rather than a
          crowd of individually-placed dots. */}
      {cluster && (
        <g opacity={LINK_OPACITY_LIVE}>
          {[0, 1, 2, 3, 4, 5].map((i) => {
            const angle = (i / 6) * Math.PI * 2;
            return (
              <circle
                key={`c${i}`}
                cx={CENTER + Math.cos(angle) * 9}
                cy={CENTER + Math.sin(angle) * 9}
                r={1.7}
                fill={NODE_PRIMARY}
                opacity={LINK_OPACITY_DIM * 4}
              />
            );
          })}
        </g>
      )}
    </svg>
  );
}

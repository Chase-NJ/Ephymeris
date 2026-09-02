import { colorForIndex } from "@/lib/analytics/view";
import { LINK_OPACITY_DIM, LINK_STROKE } from "@/components/chrome/constellationStyle";
import { seededRandom } from "@/lib/prng";
import type { TaskEntry } from "@/lib/taskdef/types";

/**
 * A task's mark — what it IS, drawn small enough to sit on a card.
 *
 * The same idea as a cohort's world (`PlanetDisc`) and the same generator
 * (`prng.seededRandom`):
 * derived from the id, so nothing is stored and a task's mark never drifts
 * between renders, sessions or machines. What differs is that this one is not
 * only decorative — three of its four dimensions are read off the task:
 *
 *   one node per CONDITION, in the series ramp   what the animal is shown
 *   concentric rings = STAGES                    whether it eases in
 *   the arrangement = SELECTION MODE             how the next trial is drawn
 *
 * so a shelf of cards is scannable before a single name is read: two dots and
 * one ring is a plain two-odor discrimination, six dots and five rings is a
 * shaped pool task.
 *
 * THE SERIES RAMP, NOT NEW COLOURS. `colorForIndex` is already the app's
 * per-item identity ramp (`data.md` §7.1) — it colours an animal across the
 * heatmap, its curve and its trail. A condition is the same kind of thing, so
 * it borrows the same six rather than introducing a seventh idea of "colourful".
 * Emitted as `var(--…)` strings and never as templated Tailwind classes, which
 * the v4 scanner cannot see (`analytics/view.ts`).
 *
 * The seed's whole job is JITTER — a few degrees of rotation and a little
 * radial wobble, so two tasks with the same shape are still telling apart. It
 * never decides the counts, because those are facts.
 */
export function TaskGlyph({
  task,
  size = 56,
  className = "",
}: {
  task: Pick<TaskEntry, "id" | "trials" | "stages" | "selectionMode" | "problems">;
  size?: number;
  className?: string;
}) {
  const random = seededRandom(task.id);
  const spin = random() * Math.PI * 2;

  // Rings read as the ramp's depth. Capped at the five stages the firmware
  // allows, and floored at one — a task always has a stage 0.
  const rings = Math.max(1, Math.min(task.stages, 5));
  // A card is 56px. Past eight the dots stop being countable and the glyph is
  // saying "many" either way, which is the honest reading.
  const count = Math.max(0, Math.min(task.trials, 8));

  /**
   * Anti-bias draws a SIDE first and then a type from it, so its conditions
   * are two opposed groups; a pool is one bag, evenly weighted until the
   * weights say otherwise. The arrangement says which without a legend.
   */
  const nodes = Array.from({ length: count }, (_, i) => {
    const wobble = 0.9 + random() * 0.2;
    const angle =
      task.selectionMode === "antibias"
        ? // Two opposed arcs: even indices to one side, odd to the other.
          spin + (i % 2 === 0 ? -0.55 : Math.PI - 0.55) + Math.floor(i / 2) * 0.55
        : spin + (i / Math.max(1, count)) * Math.PI * 2;
    const radius = 34 * wobble;
    return {
      x: 50 + Math.cos(angle) * radius,
      y: 50 + Math.sin(angle) * radius,
      fill: colorForIndex(i),
    };
  });

  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={className}
      aria-hidden
      // A count, not a picture, for anyone reading the tree.
      data-conditions={task.trials}
    >
      {/* The ramp. Faint, and behind everything: it is the task's context, not
          its subject. */}
      {Array.from({ length: rings }, (_, i) => (
        <circle
          key={i}
          cx={50}
          cy={50}
          r={14 + i * 8}
          fill="none"
          stroke={
            // Status as state, never decoration — the one place this glyph
            // leaves the accent palette, and only on the outermost ring so a
            // healthy task never shows it at all.
            task.problems > 0 && i === rings - 1
              ? "var(--color-status-error)"
              : "var(--color-halo)"
          }
          strokeWidth={1}
          opacity={task.problems > 0 && i === rings - 1 ? 0.85 : 0.7}
        />
      ))}

      {/* The links, at the constellation's own dim weight: they are structure,
          and the conditions are the reading. */}
      {nodes.map((node, i) => {
        const next = nodes[(i + 1) % nodes.length];
        if (!next || nodes.length < 2) return null;
        return (
          <line
            key={`l${i}`}
            x1={node.x}
            y1={node.y}
            x2={next.x}
            y2={next.y}
            stroke={LINK_STROKE}
            strokeWidth={0.7}
            opacity={LINK_OPACITY_DIM}
          />
        );
      })}

      {nodes.map((node, i) => (
        <circle key={`n${i}`} cx={node.x} cy={node.y} r={4} fill={node.fill} />
      ))}

      {/* A task with no trial table yet. An empty ring reads as unfinished,
          which is exactly what it is — and a glyph that drew nothing would
          read as a loading state. */}
      {nodes.length === 0 && (
        <circle cx={50} cy={50} r={3} fill="var(--color-static)" opacity={0.5} />
      )}
    </svg>
  );
}

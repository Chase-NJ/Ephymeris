import { motion } from "framer-motion";

import type { HandshakeState, HandshakeTier } from "@/lib/hardware/useHandshakeTest";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The animated handshake status dot (settings.md §5).
 *
 * Flat matte fills only — no glow, no gradient (§2.2). While a test runs the
 * dot breathes on a mirrored spring (springs-only rule, §2.5); results settle
 * with a snap. Reduced motion renders a static dot.
 */

const TIER_FILL: Record<HandshakeTier, string> = {
  ready: "var(--color-ion)",
  output: "var(--color-pulsar)",
  silent: "var(--color-status-warning)",
  failed: "var(--color-status-error)",
};

const TIER_LABEL: Record<HandshakeTier, string> = {
  ready: "speaks Ephymeris",
  output: "responded",
  silent: "silent",
  failed: "failed",
};

export function HandshakeIndicator({ state }: { state: HandshakeState }) {
  const reduceMotion = useReduceMotion();
  const running = state.phase === "running";
  const fill =
    state.phase === "done" && state.tier ? TIER_FILL[state.tier] : "var(--color-pulsar)";

  return (
    <span className="flex items-center gap-2">
      <svg viewBox="0 0 12 12" className="size-3 shrink-0" aria-hidden>
        {state.phase === "idle" ? (
          <circle cx={6} cy={6} r={4} fill="none" stroke="var(--color-halo)" strokeWidth={1.25} />
        ) : (
          <motion.circle
            cx={6}
            cy={6}
            fill={fill}
            initial={{ r: 3, opacity: 0.5 }}
            animate={
              running && !reduceMotion
                ? { r: 4.4, opacity: 1 }
                : { r: 4, opacity: 1 }
            }
            transition={
              running && !reduceMotion
                ? { ...springSnappy, repeat: Infinity, repeatType: "mirror" }
                : springSnappy
            }
          />
        )}
      </svg>
      <span className="text-[12px] text-static">
        {state.phase === "idle" && "not tested"}
        {running && "listening…"}
        {state.phase === "done" && state.tier && (
          <>
            <span
              className="font-medium"
              style={{
                color:
                  state.tier === "output"
                    ? "var(--color-starlight)"
                    : TIER_FILL[state.tier],
              }}
            >
              {TIER_LABEL[state.tier]}
            </span>
            {state.detail && <span className="text-static"> — {state.detail}</span>}
          </>
        )}
      </span>
    </span>
  );
}

/**
 * Shared visual language for constellation-style graphics.
 *
 * `cohorts.md` §5 requires the generated cohort icon to reuse "the exact line
 * treatment already established for the hardware constellation status widget",
 * so the two read as one visual family. Both import these rather than each
 * carrying its own literals, which is the only way that stays true over time.
 *
 * Flat, matte fills only — no glow, no gradients (`ephymeris_v1.0.md` §2.2).
 */

/** Links between nodes are always Pulsar, only their opacity varies. */
export const LINK_STROKE = "var(--color-pulsar)";

/** A link between two healthy/present endpoints. */
export const LINK_OPACITY_LIVE = 0.55;

/** A link with a missing or unhealthy endpoint — dimmed, not removed. */
export const LINK_OPACITY_DIM = 0.1;

/** Stroke width in a 100-unit-wide viewBox; scale with the frame when zoomed. */
export const LINK_WIDTH = 0.7;

/** Node radius in the same 100-unit space. */
export const NODE_RADIUS = 3;

/**
 * The single accent permitted alongside Pulsar. In the status widget this means
 * "connected and nominal"; in a cohort icon it's the seeded hero star (§5.5).
 * Either way it stays inside the six-token palette.
 */
export const NODE_ACCENT = "var(--color-ion)";

/** The ordinary node fill. */
export const NODE_PRIMARY = "var(--color-pulsar)";

/**
 * Literal values of the same tokens, for WebGL.
 *
 * three.js materials take colors, not CSS custom properties, so the 3D
 * constellation (`starting-a-session.md` §6) can't read the variables above.
 * These are declared here, beside them, so the duplication is visible and the
 * two can't quietly diverge — they must match `styles/index.css` §2.2.
 */
export const GL = {
  void: "#0b0b10",
  halo: "#2c2a3a",
  pulsar: "#8b7ec8",
  ion: "#7cc98f",
  starlight: "#edebf6",
} as const;

/**
 * Box health as a WebGL colour — the 3D counterpart of `NODE_FILL`.
 *
 * Debug's constellation now shares Mission Control's temperature ramp for the
 * star surfaces themselves (revised 2026-07-29, `ephymeris_v1.0.md` §4.3), so
 * of these only `fault` still reaches the 3D scene — the error ring around a
 * faulted box's star, the one status that must keep its colour.
 *
 * Keys match `BoxHealth`; values must track `NODE_FILL`'s tokens.
 */
export const GL_HEALTH = {
  nominal: GL.ion,
  idle: GL.pulsar,
  absent: GL.halo,
  fault: "#c96c6c", // --color-status-error's literal, matte
} as const;

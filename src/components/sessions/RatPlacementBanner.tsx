import { motion, type Variants } from "framer-motion";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The box-placement instruction as a drawing instead of a paragraph
 * (mapping step): a lab member lifts a rat out of its home cage and places it
 * through the front door of an operant chamber, looping over the boxes
 * actually mapped below. The chamber's number lights Ion once the animal is
 * inside.
 *
 * `mode="return"` plays the same scene backwards — the group-swap prompt in
 * Mission Control: the animal is lifted back *out* of the chamber and
 * carried home to its cage, because that is literally the operator's next
 * physical act before the next group runs. Same scenery, same performers;
 * only the choreography and which lid opens are mirrored.
 *
 * **Deliberately off-theme in style, not in palette.** The rest of the app is
 * schematic and flat; this one illustration is filled, rounded and drawn in
 * 3/4 perspective on purpose — it's the only moment in the flow about
 * handling an animal rather than reading data, and it should feel warm. Every
 * fill still comes from the six tokens (white rat = Starlight, gloves =
 * Pulsar, equipment = Nebula/Halo, depth = Void, success = Ion) and stays
 * flat and matte — depth comes from face shading and a travelling ground
 * shadow, never from gradients or glow (`ARCHITECTURE.md#theme`).
 *
 * Under reduced motion the scene is a still of the finished move — placed in
 * the chamber, or home in the cage, by mode.
 */

/** One beat of the loop, with how long it holds before the next. */
const SEQUENCE = [
  { phase: "rest", ms: 1000 },
  { phase: "reach", ms: 700 },
  { phase: "grab", ms: 450 },
  { phase: "lift", ms: 750 },
  { phase: "carry", ms: 1500 },
  { phase: "insert", ms: 800 },
  { phase: "release", ms: 500 },
  { phase: "settled", ms: 1500 },
] as const;

type Phase = (typeof SEQUENCE)[number]["phase"] | "still";

/**
 * The single projection every solid in the scene obeys: a face's back edge
 * sits `DEPTH` up and to the right of its front edge. One shared vector is
 * what keeps the cage, chamber and bench looking like the same room.
 */
const DEPTH = { x: 26, y: -16 };
/** The bench plane's front edge — everything stands on it. */
const FLOOR = 101;

const FUR = "var(--color-starlight)";
const GLOVE = "var(--color-pulsar)";
const EQUIP = "var(--color-nebula)";
const EDGE = "var(--color-halo)";
const DEEP = "var(--color-void)";

/** Front edge (x1..x2 at y) extruded back along DEPTH — a top or floor face. */
function slab(x1: number, x2: number, y: number): string {
  return `M ${x1} ${y} L ${x2} ${y} L ${x2 + DEPTH.x} ${y + DEPTH.y} L ${x1 + DEPTH.x} ${y + DEPTH.y} Z`;
}

/** The right-hand face of a box whose front-right edge runs y1..y2 at x. */
function sideFace(x: number, y1: number, y2: number): string {
  return `M ${x} ${y1} L ${x + DEPTH.x} ${y1 + DEPTH.y} L ${x + DEPTH.x} ${y2 + DEPTH.y} L ${x} ${y2} Z`;
}

export function RatPlacementBanner({
  boxes,
  mode = "place",
  caption,
  footer,
}: {
  boxes: number[];
  /** `place` walks cage → chamber (mapping step); `return` walks it back. */
  mode?: "place" | "return";
  caption?: string;
  /** Rendered under the caption — the prompt's call to action, when one fits. */
  footer?: ReactNode;
}) {
  const reduceMotion = useReduceMotion();
  const order = useMemo(() => [...new Set(boxes)].sort((a, b) => a - b), [boxes]);
  const [step, setStep] = useState(0);
  const [trip, setTrip] = useState(0);

  useEffect(() => {
    if (reduceMotion) return;
    const beat = SEQUENCE[step];
    if (!beat) return;
    const timer = window.setTimeout(() => {
      const next = (step + 1) % SEQUENCE.length;
      // A completed placement moves the demonstration to the next box.
      if (next === 0) setTrip((n) => n + 1);
      setStep(next);
    }, beat.ms);
    return () => window.clearTimeout(timer);
  }, [step, reduceMotion]);

  if (order.length === 0) return null;

  const returning = mode === "return";
  const phase: Phase = reduceMotion ? "still" : (SEQUENCE[step]?.phase ?? "rest");
  const boxNumber = order[trip % order.length] ?? 1;
  // Mirrored choreography: the same beats walk the opposite direction, so the
  // source's lid opens where the destination's did and the chamber is lit
  // while the animal is still inside it rather than once it arrives.
  const travel = returning ? TRAVEL_RETURN : TRAVEL;
  const shadow = returning ? SHADOW_RETURN : SHADOW;
  const inside = returning
    ? ["rest", "reach", "grab"].includes(phase)
    : phase === "settled" || phase === "still";
  const lidOpen = (
    returning ? ["carry", "insert", "release"] : ["reach", "grab", "lift", "carry"]
  ).includes(phase);
  const doorOpen = (
    returning ? ["reach", "grab", "lift", "carry"] : ["carry", "insert", "release"]
  ).includes(phase);

  return (
    <div className="hud mt-5 rounded-md px-4 pb-2.5 pt-2">
      <svg
        viewBox="0 -72 640 185"
        className="mx-auto block h-[132px] w-full max-w-[560px]"
        aria-hidden
      >
        <Bench />
        {/* Interiors first — everything the animal can stand inside of. The
            lid lives back here too: it hinges along the cage's far edge, so
            an animal rising out of the opening passes in front of it. */}
        <CageBody lidOpen={lidOpen} />
        <ChamberBody
          number={boxNumber}
          lit={inside}
          // The flourish celebrates an arrival; leaving deserves none.
          celebrateKey={returning ? null : trip}
        />

        {/* The ground shadow keeps the travel readable in depth. Two stacked
            ellipses — a wide faint penumbra under a tight dark core — read as
            a soft shadow without ever needing a gradient. */}
        <motion.g
          initial={false}
          animate={phase}
          variants={shadow}
          style={{ transformBox: "fill-box", transformOrigin: "50% 50%" }}
        >
          <ellipse cx={0} cy={99} rx={24} ry={5.5} fill={DEEP} opacity={0.55} />
          <ellipse cx={0} cy={99} rx={14} ry={3.4} fill={DEEP} opacity={0.85} />
        </motion.g>

        {/*
          The animal and the hand travel as one, but are drawn on either side
          of the cage front: the animal stays *behind* the bars so it emerges
          from inside the cage as it rises, while the handler's arm passes in
          *front* of the opened lid — which is what sells the animal being
          drawn forward, out of the box and toward the viewer. Both groups run
          the same variants off the same phase, so they never drift apart.
        */}
        <motion.g initial={false} animate={phase} variants={travel}>
          <motion.g initial={false} animate={phase} variants={RAT_STATE}>
            {/* Held at the scruff, so every reaction pivots there. */}
            <motion.g
              initial={false}
              animate={phase}
              variants={RAT_MOOD}
              style={{ transformBox: "fill-box", originX: 0.5, originY: 0.15 }}
            >
              <Rat />
            </motion.g>
          </motion.g>
        </motion.g>

        <CageFront />

        <motion.g initial={false} animate={phase} variants={travel}>
          <motion.g initial={false} animate={phase} variants={HAND_STATE}>
            <Hand />
          </motion.g>
        </motion.g>

        {/* Glass last, so a placed animal reads as being inside the chamber. */}
        <ChamberFront doorOpen={doorOpen} />
      </svg>
      <p className="text-center text-[11px] text-static">
        {caption ??
          (returning
            ? "Return each animal to its home cage before the next group runs."
            : "Lift each animal into the box shown on its card, then confirm and flash.")}
      </p>
      {footer && <div className="flex justify-center pb-1.5 pt-2.5">{footer}</div>}
    </div>
  );
}

// --- choreography ---------------------------------------------------------

/** Where the carried pair sits at each beat. */
const TRAVEL: Variants = {
  rest: { x: 40, y: 0, transition: { duration: 0 } },
  reach: { x: 40, y: 0, transition: { duration: 0.2 } },
  grab: { x: 40, y: 0, transition: { duration: 0.2 } },
  lift: { x: 40, y: -70, transition: { duration: 0.7, ease: "easeOut" } },
  carry: { x: 455, y: -70, transition: { duration: 1.45, ease: "easeInOut" } },
  insert: { x: 512, y: 0, transition: { duration: 0.75, ease: "easeInOut" } },
  release: { x: 512, y: 0, transition: { duration: 0.2 } },
  settled: { x: 512, y: 0, transition: { duration: 0 } },
  still: { x: 512, y: 0, transition: { duration: 0 } },
};

/** The same journey walked backwards — chamber to home cage (`mode="return"`). */
const TRAVEL_RETURN: Variants = {
  rest: { x: 512, y: 0, transition: { duration: 0 } },
  reach: { x: 512, y: 0, transition: { duration: 0.2 } },
  grab: { x: 512, y: 0, transition: { duration: 0.2 } },
  lift: { x: 512, y: -70, transition: { duration: 0.7, ease: "easeOut" } },
  carry: { x: 40, y: -70, transition: { duration: 1.45, ease: "easeInOut" } },
  insert: { x: 40, y: 0, transition: { duration: 0.75, ease: "easeInOut" } },
  release: { x: 40, y: 0, transition: { duration: 0.2 } },
  settled: { x: 40, y: 0, transition: { duration: 0 } },
  still: { x: 40, y: 0, transition: { duration: 0 } },
};

/**
 * The chamber front is glass, so the animal stays visible once placed — it
 * only blinks out to restart the loop back in its cage.
 */
const RAT_STATE: Variants = {
  rest: { opacity: [0, 1], transition: { duration: 0.35 } },
  reach: { opacity: 1 },
  grab: { opacity: 1 },
  lift: { opacity: 1 },
  carry: { opacity: 1 },
  insert: { opacity: 1 },
  release: { opacity: 1 },
  settled: { opacity: 1 },
  still: { opacity: 1, transition: { duration: 0 } },
};

/**
 * The animal's own performance: an idle bob in the cage, a startle as it's
 * grasped, a dangling sway while carried, a squash as it's set down, and a
 * contented bob once it's home.
 */
const RAT_MOOD: Variants = {
  rest: {
    y: [0, -1.6, 0],
    rotate: 0,
    scaleY: 1,
    transition: { y: { duration: 1.7, repeat: Infinity, ease: "easeInOut" } },
  },
  reach: { y: 0, rotate: 0, scaleY: 1, transition: { duration: 0.3 } },
  grab: {
    y: 0,
    rotate: 0,
    scaleY: [1, 0.9, 1],
    transition: { scaleY: { duration: 0.35, times: [0, 0.45, 1] } },
  },
  lift: { y: 0, rotate: -5, scaleY: 1, transition: { duration: 0.5 } },
  carry: {
    y: 0,
    scaleY: 1,
    rotate: [-6, 4, -6],
    transition: { rotate: { duration: 1.15, repeat: Infinity, ease: "easeInOut" } },
  },
  insert: {
    y: 0,
    rotate: 0,
    scaleY: [1, 0.86, 1],
    transition: { rotate: { duration: 0.35 }, scaleY: { duration: 0.5, times: [0, 0.6, 1] } },
  },
  release: { y: 0, rotate: 0, scaleY: 1 },
  settled: {
    y: [0, -1.4, 0],
    rotate: 0,
    scaleY: 1,
    transition: { y: { duration: 1.6, repeat: Infinity, ease: "easeInOut" } },
  },
  still: { y: 0, rotate: 0, scaleY: 1, transition: { duration: 0 } },
};

/** Shrinks and fades as the animal leaves the bench — the main depth cue. */
const SHADOW: Variants = {
  rest: { x: 60, scaleX: 1, scaleY: 1, opacity: [0, 0.45], transition: { duration: 0.35 } },
  reach: { x: 60, scaleX: 1, scaleY: 1, opacity: 0.45 },
  grab: { x: 60, scaleX: 1, scaleY: 1, opacity: 0.45 },
  lift: { x: 60, scaleX: 0.6, scaleY: 0.6, opacity: 0.2, transition: { duration: 0.7 } },
  carry: {
    x: 475,
    scaleX: 0.6,
    scaleY: 0.6,
    opacity: 0.2,
    transition: { duration: 1.45, ease: "easeInOut" },
  },
  insert: { x: 532, scaleX: 0.95, scaleY: 0.95, opacity: 0.4, transition: { duration: 0.75 } },
  release: { x: 532, scaleX: 0.95, scaleY: 0.95, opacity: 0.4 },
  settled: { x: 532, scaleX: 0.95, scaleY: 0.95, opacity: 0.4 },
  still: { x: 532, scaleX: 0.95, scaleY: 0.95, opacity: 0.4, transition: { duration: 0 } },
};

/** `SHADOW` mirrored for the walk home. */
const SHADOW_RETURN: Variants = {
  rest: { x: 532, scaleX: 0.95, scaleY: 0.95, opacity: [0, 0.4], transition: { duration: 0.35 } },
  reach: { x: 532, scaleX: 0.95, scaleY: 0.95, opacity: 0.4 },
  grab: { x: 532, scaleX: 0.95, scaleY: 0.95, opacity: 0.4 },
  lift: { x: 532, scaleX: 0.6, scaleY: 0.6, opacity: 0.2, transition: { duration: 0.7 } },
  carry: {
    x: 60,
    scaleX: 0.6,
    scaleY: 0.6,
    opacity: 0.2,
    transition: { duration: 1.45, ease: "easeInOut" },
  },
  insert: { x: 60, scaleX: 1, scaleY: 1, opacity: 0.45, transition: { duration: 0.75 } },
  release: { x: 60, scaleX: 1, scaleY: 1, opacity: 0.45 },
  settled: { x: 60, scaleX: 1, scaleY: 1, opacity: 0.45 },
  still: { x: 60, scaleX: 1, scaleY: 1, opacity: 0.45, transition: { duration: 0 } },
};

/** The hand reaches in, holds through the carry, then withdraws. */
const HAND_STATE: Variants = {
  rest: { y: -36, opacity: 0, transition: { duration: 0 } },
  reach: { y: 0, opacity: 1, transition: { duration: 0.62, ease: "easeOut" } },
  grab: { y: 0, opacity: 1 },
  lift: { y: 0, opacity: 1 },
  carry: { y: 0, opacity: 1 },
  insert: { y: 0, opacity: 1 },
  release: { y: -38, opacity: 0, transition: { duration: 0.45, ease: "easeIn" } },
  settled: { y: -38, opacity: 0, transition: { duration: 0 } },
  still: { y: -38, opacity: 0, transition: { duration: 0 } },
};

/**
 * The wrist's own performance, layered under the finger curls: cocked
 * slightly up on the way in, a dip into the grab as the hand takes the
 * animal's weight, level through the carry, and a tip forward while lowering
 * into the chamber. The origin sits at the wrist joint, so positive angles
 * drop the finger side of the hand.
 */
const WRIST: Variants = {
  rest: { rotate: 0, transition: { duration: 0 } },
  reach: { rotate: -4, transition: { duration: 0.55, ease: "easeOut" } },
  grab: { rotate: 4, transition: { duration: 0.4, ease: "easeOut" } },
  lift: { rotate: -2, transition: { duration: 0.55 } },
  carry: { rotate: -2 },
  insert: { rotate: 5, transition: { duration: 0.65, ease: "easeInOut" } },
  release: { rotate: 0, transition: { duration: 0.3 } },
  settled: { rotate: 0, transition: { duration: 0 } },
  still: { rotate: 0, transition: { duration: 0 } },
};

/**
 * The palm's pressure shadow on the animal's back — a hint of it as the hand
 * hovers in, full weight while gripping, gone the moment it lets go.
 */
const CONTACT: Variants = {
  rest: { opacity: 0, transition: { duration: 0 } },
  reach: { opacity: 0.06, transition: { duration: 0.5 } },
  grab: { opacity: 0.15, transition: { duration: 0.3 } },
  lift: { opacity: 0.15 },
  carry: { opacity: 0.15 },
  insert: { opacity: 0.15 },
  release: { opacity: 0, transition: { duration: 0.25 } },
  settled: { opacity: 0, transition: { duration: 0 } },
  still: { opacity: 0, transition: { duration: 0 } },
};

// --- scenery --------------------------------------------------------------

/** The bench top receding along DEPTH, with a lip for thickness. */
function Bench() {
  return (
    <g>
      <path d={slab(16, 600, FLOOR)} fill={EDGE} opacity={0.28} />
      <rect x={16} y={FLOOR} width={584} height={5} rx={2} fill={EDGE} opacity={0.6} />
      {/* ambient occlusion pooling on the bench at each box's base — cast
          along the same depth axis as everything else, so it reads as the
          boxes sitting on the surface rather than floating over it */}
      <path d={slab(112, 130, FLOOR)} fill={DEEP} opacity={0.22} />
      <path d={slab(468, 486, FLOOR)} fill={DEEP} opacity={0.22} />
    </g>
  );
}

/** Cage interior — drawn behind the animal, seen through the bars in front. */
function CageBody({ lidOpen }: { lidOpen: boolean }) {
  return (
    <g>
      {/* far wall and floor */}
      <rect x={24 + DEPTH.x} y={46 + DEPTH.y} width={88} height={55} fill={EQUIP} />
      <path d={slab(24, 112, FLOOR)} fill={DEEP} opacity={0.55} />
      {/* bedding scattered on the floor plane */}
      {[
        [40, 97],
        [58, 93],
        [76, 97],
        [94, 93],
      ].map(([cx, cy]) => (
        <ellipse key={cx} cx={cx} cy={cy} rx={7} ry={2.6} fill={EDGE} opacity={0.5} />
      ))}
      {/* lid: the top face, hinged along its far edge — drawn behind the
          animal, which exits through the opening toward the viewer */}
      <motion.path
        d={slab(24, 112, 46)}
        fill={EDGE}
        stroke={DEEP}
        strokeWidth={1}
        initial={false}
        animate={{ rotate: lidOpen ? -26 : 0 }}
        transition={{ duration: 0.5, ease: "easeInOut" }}
        // Hinged along the lid's far edge. Offsets are measured inside the
        // lid's own box (`fill-box`), since Framer overwrites a CSS
        // `transform-origin` — see the note on `Finger`.
        style={{ transformBox: "fill-box", originX: `${DEPTH.x}px`, originY: "0px" }}
      />
    </g>
  );
}

/** Cage bars and frame — the faces nearest the viewer. */
function CageFront() {
  return (
    <g>
      <path d={sideFace(112, 46, FLOOR)} fill={DEEP} opacity={0.75} />
      {[40, 55, 70, 85, 100].map((x) => (
        <rect key={x} x={x} y={50} width={2.5} height={47} rx={1.25} fill={EDGE} />
      ))}
      {/* front frame */}
      <rect x={24} y={46} width={4} height={55} fill={EDGE} />
      <rect x={108} y={46} width={4} height={55} fill={EDGE} />
      <rect x={24} y={46} width={88} height={4} fill={EDGE} />
      <rect x={24} y={97} width={88} height={4} fill={EDGE} />
    </g>
  );
}

/** Chamber shell and interior — everything behind the glass front. */
function ChamberBody({
  number,
  lit,
  celebrateKey,
}: {
  number: number;
  lit: boolean;
  /** Null suppresses the arrival flourish (the return walk celebrates nothing). */
  celebrateKey: number | null;
}) {
  return (
    <g>
      {/* top and right faces read as the solid outside of the box */}
      <path d={slab(486, 596, 36)} fill={EDGE} opacity={0.9} />
      <path d={sideFace(596, 36, FLOOR)} fill={DEEP} opacity={0.8} />
      {/* far wall, then the floor plane */}
      <rect x={486 + DEPTH.x} y={36 + DEPTH.y} width={110} height={65} fill={EQUIP} />
      <path d={slab(486, 596, FLOOR)} fill={DEEP} opacity={0.5} />

      {/* odor panel on the far wall: manifold block with three ports */}
      <rect x={566} y={30} width={40} height={38} rx={4} fill={EDGE} />
      {[38, 48, 58].map((cy) => (
        <circle
          key={cy}
          cx={586}
          cy={cy}
          r={4.2}
          fill={DEEP}
          stroke={GLOVE}
          strokeWidth={1.5}
        />
      ))}

      <motion.text
        x={534}
        y={58}
        textAnchor="middle"
        className="font-mono"
        fontSize={21}
        initial={false}
        animate={{
          fill: lit ? "var(--color-ion)" : "var(--color-static)",
          opacity: lit ? 1 : 0.8,
          scale: lit ? [1, 1.18, 1] : 1,
        }}
        transition={{ duration: 0.45 }}
        style={{ transformBox: "fill-box", transformOrigin: "50% 50%" }}
      >
        {number}
      </motion.text>

      {/* a small flourish the moment the animal is in */}
      {lit && celebrateKey !== null && (
        <g key={celebrateKey}>
          {[
            [520, 34, 0],
            [545, 26, 0.12],
            [562, 36, 0.22],
          ].map(([cx, cy, delay]) => (
            <motion.circle
              key={cx}
              cx={cx}
              cy={cy}
              r={2.6}
              fill="var(--color-ion)"
              initial={{ scale: 0, opacity: 0 }}
              animate={{ scale: [0, 1, 0], opacity: [0, 1, 0] }}
              transition={{ duration: 0.85, delay: delay as number, ease: "easeOut" }}
              style={{ transformBox: "fill-box", transformOrigin: "50% 50%" }}
            />
          ))}
        </g>
      )}
    </g>
  );
}

/**
 * The chamber's glass front and its large door. The door opens by collapsing
 * toward its hinge — the flat-art way to read a panel swinging away from the
 * viewer — so the animal can be lowered straight in.
 */
function ChamberFront({ doorOpen }: { doorOpen: boolean }) {
  return (
    <g>
      {/* glass: a faint tint, so what's inside stays legible */}
      <rect x={486} y={36} width={110} height={65} fill={DEEP} opacity={0.16} />
      {/* frame */}
      <rect x={486} y={36} width={110} height={3.5} fill={EDGE} />
      <rect x={486} y={97.5} width={110} height={3.5} fill={EDGE} />
      <rect x={486} y={36} width={3.5} height={65} fill={EDGE} />
      <rect x={592.5} y={36} width={3.5} height={65} fill={EDGE} />

      <motion.g
        initial={false}
        animate={{ scaleX: doorOpen ? 0.12 : 1, rotate: doorOpen ? -6 : 0 }}
        transition={{ duration: 0.7, ease: "easeInOut" }}
        // Hinged at the door's own bottom-left corner, so it collapses
        // toward the jamb rather than toward its middle.
        style={{ transformBox: "fill-box", originX: "0px", originY: "46px" }}
      >
        <rect x={490} y={52} width={30} height={46} fill={DEEP} opacity={0.3} />
        <rect
          x={490}
          y={52}
          width={30}
          height={46}
          fill="none"
          stroke={EDGE}
          strokeWidth={2.5}
        />
        {/* handle */}
        <rect x={513} y={72} width={3} height={9} rx={1.5} fill={EDGE} />
      </motion.g>
    </g>
  );
}

// --- performers -----------------------------------------------------------

/** How much a phalanx foreshortens as it curls under the palm, away from us. */
const CURL = 0.7;

/**
 * One articulated digit: two capsules — a proximal and a distal phalanx —
 * each swinging about its own joint. The proximal rotates at the knuckle
 * (MCP); the distal rotates further at the mid-finger joint (PIP) *and*
 * translates so its base stays seated on the proximal tip.
 *
 * The seat offsets are precomputed per pose instead of nesting rotation
 * groups, because a group's `fill-box` shifts as its children swing, which
 * would drag the rotation origin around with it. Framer interpolates the two
 * transforms independently between poses; the deep overlap of the round caps
 * absorbs that slack, so the joint never visibly separates.
 *
 * Angles are signed for SVG's y-down space: a digit hangs *below* its
 * knuckle, so a positive rotation carries its tip to the **left**. Splaying
 * a digit outward therefore means rotating away from the side it sits on —
 * getting this backwards opens the hand on the grab instead of closing it.
 * Each digit gets its own delay so the grasp rolls across the hand, and the
 * PIP lags the MCP by a further beat so each finger unrolls tip-last.
 */
function Finger({
  kx,
  ky,
  w,
  lp,
  ld,
  open,
  closedM,
  closedP,
  delay,
  depth,
}: {
  /** Knuckle position. */
  kx: number;
  ky: number;
  /** Width, proximal length, distal length. */
  w: number;
  lp: number;
  ld: number;
  /** MCP angle when splayed; MCP and *relative* PIP angles when gripping. */
  open: number;
  closedM: number;
  closedP: number;
  delay: number;
  depth: number;
}) {
  // Knuckle → PIP distance; the distal's cap nests this deep into the
  // proximal so the hinge is never a visible gap.
  const reach = lp - w * 0.45;
  /** Where the distal's base sits (relative to straight-down) for an MCP angle. */
  const seat = (deg: number, squash: number) => {
    const r = (deg * Math.PI) / 180;
    return {
      x: -Math.sin(r) * reach * squash,
      y: Math.cos(r) * reach * squash - reach,
    };
  };
  const openPose = { ...seat(open, 1), rotate: open, scaleY: 1 };
  // The hand splays a touch wider on the way in — anticipation before the grab.
  const splayPose = { ...seat(open * 1.3, 1), rotate: open * 1.3, scaleY: 1 };
  // The distal squashes harder than the proximal: the fingertip curls the
  // furthest under, so it foreshortens the most.
  const heldPose = { ...seat(closedM, CURL), rotate: closedM + closedP, scaleY: CURL * 0.8 };

  const proximal: Variants = {
    rest: { rotate: open, scaleY: 1, transition: { duration: 0 } },
    reach: { rotate: open * 1.3, scaleY: 1, transition: { duration: 0.3 } },
    grab: { rotate: closedM, scaleY: CURL, transition: { duration: 0.32, delay, ease: "easeOut" } },
    lift: { rotate: closedM, scaleY: CURL },
    carry: { rotate: closedM, scaleY: CURL },
    insert: { rotate: closedM, scaleY: CURL },
    release: { rotate: open, scaleY: 1, transition: { duration: 0.3, delay } },
    settled: { rotate: open, scaleY: 1, transition: { duration: 0 } },
    still: { rotate: open, scaleY: 1, transition: { duration: 0 } },
  };
  const distal: Variants = {
    rest: { ...openPose, transition: { duration: 0 } },
    reach: { ...splayPose, transition: { duration: 0.3 } },
    grab: {
      ...heldPose,
      transition: {
        duration: 0.32,
        delay,
        ease: "easeOut",
        rotate: { duration: 0.32, delay: delay + 0.07, ease: "easeOut" },
      },
    },
    lift: heldPose,
    carry: heldPose,
    insert: heldPose,
    release: { ...openPose, transition: { duration: 0.3, delay } },
    settled: { ...openPose, transition: { duration: 0 } },
    still: { ...openPose, transition: { duration: 0 } },
  };

  const wd = w * 0.86;
  return (
    <g opacity={depth}>
      <motion.rect
        x={kx - w / 2}
        y={ky}
        width={w}
        height={lp}
        rx={w / 2}
        fill={GLOVE}
        stroke={DEEP}
        strokeWidth={0.9}
        variants={proximal}
        // `originX`/`originY` rather than a `transformOrigin` string: Framer
        // owns transform-origin and silently overwrites the CSS one, which
        // would swing each digit about its middle instead of its knuckle.
        style={{ transformBox: "fill-box", originX: 0.5, originY: 0.07 }}
      />
      <motion.rect
        x={kx - wd / 2}
        y={ky + reach}
        width={wd}
        height={ld + w * 0.45}
        rx={wd / 2}
        fill={GLOVE}
        stroke={DEEP}
        strokeWidth={0.9}
        variants={distal}
        style={{ transformBox: "fill-box", originX: 0.5, originY: 0.12 }}
      />
    </g>
  );
}

/** The scene's depth direction as an angle, for anything lying along it. */
const DEPTH_ANGLE = (Math.atan2(DEPTH.y, DEPTH.x) * 180) / Math.PI;

/**
 * The handler's hand, reaching in from the back of the scene: the forearm
 * runs along the same depth axis every solid here is extruded on, so it
 * recedes away from the viewer rather than lying flat in the picture plane.
 * Foreshortening does the work — the sleeve is short and steeply angled, and
 * we look almost straight into its mouth, which is why the inside of the
 * sleeve reads as a dark ellipse.
 *
 * The glove is **pronated — palm down**, the way an animal is actually
 * picked up: what faces us is the back of the hand, with the knuckles along
 * its near edge and the digits reaching down past them to curl underneath
 * and take the scruff.
 */
function Hand() {
  return (
    <g>
      {/* pressure shadow the palm casts on the animal's back while gripping */}
      <motion.ellipse cx={26} cy={77} rx={12} ry={3.2} fill={DEEP} variants={CONTACT} />

      {/* forearm + sleeve, laid along the depth axis and seen end-on. The
          sleeve tapers from its open mouth down to the wrist the way a coat
          sleeve actually hangs off a reaching arm. */}
      <g transform={`rotate(${DEPTH_ANGLE} 34 54)`}>
        <path
          d="M 39 46.5 C 35.5 48.5 35.5 59.5 39 61.5 C 51 64.5 63 65.5 76 65.8 L 76 42.2 C 63 42.5 51 43.5 39 46.5 Z"
          fill={FUR}
        />
        {/* the underside of the tube catches less light — shading follows the taper */}
        <path
          d="M 39.5 58 C 51.5 61 63 62.3 76 62.6 L 76 65.8 C 63 65.5 51 64.5 39 61.5 Z"
          fill={DEEP}
          opacity={0.18}
        />
        {/* the mouth: fabric rim, lit far wall inside, then the shadow */}
        <ellipse cx={76} cy={54} rx={4.5} ry={12} fill={FUR} />
        <ellipse cx={75.5} cy={54} rx={3.4} ry={9.6} fill={EDGE} opacity={0.6} />
        <ellipse cx={76.6} cy={54} rx={3.2} ry={9} fill={DEEP} />
        {/* rolled coat cuff, with the nitrile glove's cuff pulled up over it */}
        <rect x={40} y={44.5} width={7.5} height={19} rx={3.6} fill={EDGE} />
        <rect
          x={33.5}
          y={45.5}
          width={7.5}
          height={17}
          rx={3.4}
          fill={GLOVE}
          stroke={DEEP}
          strokeWidth={0.9}
        />
      </g>

      {/* Everything past the cuff tilts as one piece about the wrist joint. */}
      <motion.g
        variants={WRIST}
        style={{ transformBox: "fill-box", originX: "44px", originY: "10.5px" }}
      >
        {/* Invisible anchor: it strictly contains every finger pose, pinning
            the group's `fill-box` — and so the wrist origin above — in place
            while the digits swing. Remove it and the hand wobbles. */}
        <rect x={-4} y={42} width={52} height={50} fill="none" />

        {/* pinky and ring curl in from the far side of the palm */}
        <Finger kx={36.5} ky={62.5} w={5} lp={8} ld={6} open={-26} closedM={10} closedP={10} delay={0.1} depth={0.72} />
        <Finger kx={31.5} ky={65} w={5.8} lp={9.5} ld={7.5} open={-12} closedM={5} closedP={8} delay={0.075} depth={0.84} />

        {/* back of the hand — broad and shallow because we're above it, wide
            at the knuckle ridge and tapering back to the wrist */}
        <path
          d="M 41 48.5 C 43.5 52 43.5 56.5 40 59.5 C 35.5 65 30 68 24 67.5 C 19 67 14.5 64 12 60 C 9.5 56.5 10.5 51.5 15 49 C 23 45.5 34 45.5 41 48.5 Z"
          fill={GLOVE}
        />
        {/* thenar bulge at the thumb's base */}
        <ellipse cx={15} cy={55.5} rx={4.2} ry={5.6} fill={GLOVE} transform="rotate(-18 15 55.5)" />
        {/* the back plane turns down toward the knuckles and the ulnar edge */}
        <ellipse cx={26.5} cy={64.5} rx={10} ry={3} fill={DEEP} opacity={0.08} transform="rotate(-4 26.5 64.5)" />
        <ellipse cx={40.5} cy={55} rx={2} ry={5} fill={DEEP} opacity={0.12} />
        {/* extensor tendons fanning from the wrist to the knuckles */}
        <g stroke={DEEP} strokeWidth={1} strokeLinecap="round" opacity={0.08}>
          <line x1={36.5} y1={54} x2={21} y2={61.5} />
          <line x1={36.5} y1={54.5} x2={26.5} y2={62.5} />
          <line x1={37} y1={55} x2={32} y2={61} />
        </g>
        {/* knuckle bumps sit exactly where the fingers root */}
        {[
          [18.5, 63],
          [25.5, 65],
          [32, 63],
        ].map(([cx, cy]) => (
          <ellipse key={cx} cx={cx} cy={cy} rx={3.2} ry={2.3} fill={DEEP} opacity={0.14} />
        ))}

        <Finger kx={25.5} ky={66.5} w={6.2} lp={10.5} ld={8} open={0} closedM={-2} closedP={-8} delay={0.05} depth={0.95} />
        <Finger kx={18.5} ky={64.5} w={6} lp={9.5} ld={7.5} open={13} closedM={-6} closedP={-8} delay={0.025} depth={1} />
        {/* thumb, coming across underneath last */}
        <Finger kx={10} ky={57.5} w={7} lp={8.5} ld={7} open={46} closedM={-4} closedP={-12} delay={0.12} depth={1} />
      </motion.g>
    </g>
  );
}

/** The animal: a white lab rat, nose to the right, feet on the bench. */
function Rat() {
  return (
    <g>
      {/* tail: one tapered ribbon — thick at the rump, curling to a point */}
      <path
        d="M 5 89.5 C -3 92.8 -9.8 92.6 -12.4 88.4 C -14 85.6 -13 81.8 -10.2 80.5 C -9 80 -7.8 80.6 -7.6 81.7 C -9.7 82.7 -10.4 84.9 -9.3 86.9 C -7.6 89.8 -2.2 89.2 4.4 86.6 Z"
        fill={FUR}
        opacity={0.95}
      />
      {/* far pair of feet, set back and dimmer */}
      <ellipse cx={14.5} cy={97} rx={4} ry={2.4} fill={FUR} opacity={0.55} />
      <ellipse cx={34.5} cy={97} rx={4} ry={2.4} fill={FUR} opacity={0.55} />
      {/* near feet */}
      <ellipse cx={11.5} cy={100} rx={4.6} ry={2.8} fill={FUR} />
      <ellipse cx={32} cy={100} rx={4.6} ry={2.8} fill={FUR} />
      {/* one continuous silhouette: snout → brow → crown → back arch over the
          shoulder → rump → around the haunch → belly → chest → chin */}
      <path
        d="M 52.5 89.5 C 51.5 86.5 49 84 45.5 82.5 C 42.5 80.2 39 78.6 35 78.2 C 29 77.6 24 78.4 19.5 80.2 C 12 83.2 6 87.5 4.5 92 C 3.2 96 6 99.3 11 100.2 C 17 101.1 25 100.7 31 99 C 37 97.2 42.5 94.8 46.5 92.8 C 50 91.1 52.8 90.6 52.5 89.5 Z"
        fill={FUR}
      />
      {/* the haunch reads as a crease, the underside as caught shadow */}
      <path
        d="M 20.5 84.5 C 14.5 86.6 11.6 91.5 13.2 97.4"
        stroke={DEEP}
        strokeWidth={1.2}
        strokeLinecap="round"
        opacity={0.14}
        fill="none"
      />
      <ellipse cx={22} cy={96.8} rx={14} ry={3.4} fill={DEEP} opacity={0.12} />
      {/* cheek line separates head from shoulder */}
      <path
        d="M 35.5 83.5 C 37.3 86.8 37.6 89.8 36.2 92.4"
        stroke={DEEP}
        strokeWidth={1}
        strokeLinecap="round"
        opacity={0.1}
        fill="none"
      />
      {/* far ear behind the head, near ear in front */}
      <circle cx={37.5} cy={74.5} r={5} fill={FUR} opacity={0.6} />
      <circle cx={31} cy={75.5} r={6.3} fill={FUR} />
      <circle cx={31} cy={75.8} r={3.1} fill={GLOVE} opacity={0.55} />
      {/* face: eye with a glint, pink nose, whiskers */}
      <circle cx={40.5} cy={84.5} r={1.9} fill={DEEP} />
      <circle cx={41.2} cy={83.8} r={0.6} fill={FUR} />
      <circle cx={51.6} cy={89.3} r={1.9} fill={GLOVE} />
      <g stroke={EDGE} strokeWidth={0.9} strokeLinecap="round" opacity={0.9}>
        <line x1={49.5} y1={86.5} x2={56.5} y2={83.5} />
        <line x1={50.5} y1={89.5} x2={57.5} y2={89.5} />
        <line x1={49.5} y1={92} x2={56.5} y2={95} />
      </g>
    </g>
  );
}

import { Billboard, Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { motion } from "framer-motion";
import { Crosshair, Move } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";
import { OrbiterBelt, type SceneOrbiter } from "./Orbiters";
import {
  clearSceneIntent,
  panView,
  recenterView,
  setSceneIntent,
} from "./sceneIntent";
import { useConstellationView } from "./SharedCanvas";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The shared 3D constellation browser — camera, controls, and the animation
 * grammar (`dashboard.md` §9.2–§6.3, `dashboard.md` §4).
 *
 * Two views use it and they are deliberately the *same instrument*: Mission
 * Control browses a cohort's animals, Debug Mode browses the rig's boxes. Both
 * orbit, pan and zoom identically at the overview, both narrow to **orbit
 * alone** once a star is focused, both hover with the same reticle, both fly to
 * a star on selection and dock a panel over the still-rendering scene. An
 * operator who learns one has learned the other.
 *
 * What the two do **not** share is what a star *says*. That is the `body` of
 * each node, supplied by the caller: Mission Control renders a stellar surface
 * whose temperature is the animal's rolling accuracy; Debug renders a matte
 * core whose colour is the box's health. Colour means different things in the
 * two views on purpose, so it is the one thing this module refuses to own.
 */

/**
 * One drawable point.
 *
 * An unoccupied star of the asterism is not a special case — it is simply a
 * node with `active: false` and no name, which is why the scene needs no
 * separate concept for scenery.
 */
export interface SceneNode {
  /** Stable React key, and the id `focusedId`/`onFocus` speak in. */
  id: string;
  position: [number, number, number];
  radius: number;
  /** Interactive: hover swell, reticle, nameplate, click-to-focus. */
  active: boolean;
  /** Nameplate text. Omitted entirely when absent. */
  name?: string | null;
  /** A small mono prefix on the plate — a box number. */
  badge?: number | null;
  /** The star's own visual, and the caller's whole say over colour. */
  body: ReactNode;
  /** Animal satellites in orbit around this star — see `Orbiters.tsx`. */
  orbiters?: SceneOrbiter[] | undefined;
}

/** Indices into `nodes`. `live` decides the link's opacity, nothing else. */
export interface SceneLink {
  a: number;
  b: number;
  live: boolean;
}

export function ConstellationScene({
  nodes,
  links,
  focusedId,
  onFocus,
  docksPanel = true,
  interactive = true,
}: {
  nodes: SceneNode[];
  links: SceneLink[];
  focusedId: string | null;
  onFocus: (id: string | null) => void;
  /**
   * Whether this view docks a detail panel over the scene when a star is
   * focused. Every focused-state *restriction* exists to protect the frame that
   * panel is composed against — so a view that docks nothing has no composition
   * to protect, and keeps the full control set and a centred star.
   *
   * The Dashboard is the one such view: selecting a star there navigates to
   * Debug rather than opening anything in place.
   */
  docksPanel?: boolean;
  /** False where the sky is backdrop, not instrument — see `SceneIntent`. */
  interactive?: boolean;
}) {
  /*
   * **Tell the permanent camera what this view is** (`sceneIntent.ts`).
   *
   * Published in a layout effect rather than during render so it lands with the
   * commit, and torn down on unmount so the rig knows when nothing is on screen
   * — the false → true edge of `attached` is its whole arrival rule.
   *
   * `focusKey` is derived here because this is where both halves live: the
   * focused id and the node it names. Folding them into one primitive is what
   * keeps a 20 Hz telemetry rebuild of `nodes` from re-triggering a flight.
   */
  const focused =
    focusedId === null ? undefined : nodes.find((n) => n.id === focusedId);
  const focusKey = focused ? `${focusedId}@${focused.position.join(",")}` : "";

  useLayoutEffect(() => {
    setSceneIntent(
      { attached: true, focusKey, focusedId, docksPanel, interactive },
      nodes,
    );
  });
  useLayoutEffect(() => clearSceneIntent, []);

  // The scene graph this view wants on the shared stage (`SharedCanvas.tsx`).
  // Neither the backdrop nor the camera is here — both are permanent, and
  // outlive every navigation between views.
  const content = (
    <>
      {links.map(({ a, b, live }) => (
        <Link
          key={`${a}-${b}`}
          from={nodes[a]!.position}
          to={nodes[b]!.position}
          live={live}
        />
      ))}

      {nodes.map((node) => (
        <StarNode
          key={node.id}
          node={node}
          focused={focusedId === node.id}
          onSelect={() => onFocus(node.id)}
        />
      ))}

      {/* Click-through on empty space returns to the overview, which is the
          gesture people try before finding the Back control. */}
      <mesh onPointerMissed={() => onFocus(null)} visible={false}>
        <boxGeometry args={[0.01, 0.01, 0.01]} />
      </mesh>
    </>
  );

  const trackRef = useConstellationView(content);

  return (
    <>
      {/* Where the shared canvas lives while this view owns it — the stage's
          host div is adopted into this element, so the canvas sits in this
          view's own layout and stacking context, exactly as an owned canvas
          did.

          **Reaches left under the sidebar** (`-left-sidebar`, cancelling the
          shell's matching padding): the sidebar is translucent glass floating
          over the sky, so the sky has to exist behind it. This is the one place
          that knows the shell overlays the sidebar — every consumer of this
          component is a full-bleed backdrop view (Dashboard, Debug, Mission
          Control), so the canvas is always the page's background. Deliberately
          the *canvas* and not the view's whole sky layer: `ViewControls` below
          is chrome, and it stays in the content region where it can be seen. */}
      <div
        ref={trackRef}
        className="absolute inset-y-0 right-0 -left-sidebar"
      />

      {/* The pad stands down while a star is focused — it drives pan and
          recentre, and neither is on offer there — but the orbit gesture
          survives arrival, so its half of the legend stays. A gesture with no
          standing sign is a gesture this app's infrequent users don't find,
          which is the whole reason the legend exists. Gated on `docksPanel` for
          the same reason the controls are: the pad stands down because the panel
          took over the frame, so a view with no panel keeps it.

          Gone entirely where the sky is a backdrop: a pan pad over a scene that
          does not pan is an offer the view cannot keep. */}
      {interactive && (
        <ViewControls
          focused={focusedId !== null && docksPanel}
          onPan={panView}
          onRecenter={recenterView}
        />
      )}
    </>
  );
}

/**
 * On-screen pan controls (§6.2).
 *
 * The mouse bindings alone would not do: this app is run by lab members who
 * use it infrequently, and right-drag-to-pan is not something an infrequent
 * user discovers. The pad states the capability and the legend names the
 * gestures for anyone who would rather use them.
 *
 * Held-to-repeat rather than click-once — panning to the far side of the
 * asterism is a dozen steps, and a dozen clicks to get there is a worse control
 * than none.
 */
function ViewControls({
  focused,
  onPan,
  onRecenter,
}: {
  focused: boolean;
  onPan: (dx: number, dy: number) => void;
  onRecenter: () => void;
}) {
  return (
    // Owns its own exit: this chrome lives in the *sky* layer, which no route
    // fades — and between Dashboard and Debug the route no longer fades the
    // page either (`AppShell`). Without this the pad and its legend would sit
    // fully opaque over the incoming page for the length of the transition,
    // doubled against that page's own legend.
    <motion.div
      exit={{ opacity: 0 }}
      transition={springSnappy}
      className="pointer-events-none absolute bottom-3 left-3 flex items-end gap-2"
    >
      {!focused && (
        <div
          className="pointer-events-auto grid grid-cols-3 grid-rows-3 gap-px rounded-md border border-halo p-1"
          style={{
            background:
              "color-mix(in srgb, var(--color-void) 82%, transparent)",
          }}
        >
          <span className="col-start-2 row-start-1">
            <PanButton label="Pan up" onPan={() => onPan(0, 1)}>
              ↑
            </PanButton>
          </span>
          <span className="col-start-1 row-start-2">
            <PanButton label="Pan left" onPan={() => onPan(-1, 0)}>
              ←
            </PanButton>
          </span>
          <span className="col-start-2 row-start-2">
            <button
              type="button"
              title="Recentre the view"
              aria-label="Recentre the view"
              onClick={onRecenter}
              className="flex size-6 items-center justify-center rounded-sm text-static transition-colors hover:bg-halo hover:text-starlight"
            >
              <Crosshair size={12} strokeWidth={1.75} />
            </button>
          </span>
          <span className="col-start-3 row-start-2">
            <PanButton label="Pan right" onPan={() => onPan(1, 0)}>
              →
            </PanButton>
          </span>
          <span className="col-start-2 row-start-3">
            <PanButton label="Pan down" onPan={() => onPan(0, -1)}>
              ↓
            </PanButton>
          </span>
        </div>
      )}
      <span className="flex items-center gap-1 pb-1 font-mono text-[10px] leading-none text-static/70">
        <Move size={11} strokeWidth={1.75} />
        {focused
          ? "drag to orbit"
          : "drag to orbit · right-drag to pan · scroll to zoom"}
      </span>
    </motion.div>
  );
}

/** Fires once on press, then repeats while held. */
function PanButton({
  label,
  onPan,
  children,
}: {
  label: string;
  onPan: () => void;
  children: ReactNode;
}) {
  const timers = useRef<{ delay?: number; repeat?: number }>({});

  const stop = useCallback(() => {
    window.clearTimeout(timers.current.delay);
    window.clearInterval(timers.current.repeat);
    timers.current = {};
  }, []);

  // A held button whose component unmounts — focusing a star hides this pad —
  // would otherwise leave its interval panning a camera nobody is driving.
  useEffect(() => stop, [stop]);

  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onPointerDown={(event) => {
        // Clear first: a second press without an intervening release would
        // otherwise overwrite the handles and strand the old interval running
        // forever, with nothing left able to cancel it.
        stop();
        try {
          event.currentTarget.setPointerCapture(event.pointerId);
        } catch {
          // Capture is a nicety — it keeps the repeat alive if the pointer
          // slides off the button. Never let losing it cost us the pan itself.
        }
        onPan();
        timers.current.delay = window.setTimeout(() => {
          timers.current.repeat = window.setInterval(onPan, 60);
        }, 300);
      }}
      onPointerUp={stop}
      onPointerCancel={stop}
      onPointerLeave={stop}
      onLostPointerCapture={stop}
      className="flex size-6 items-center justify-center rounded-sm font-mono text-[11px] leading-none text-static transition-colors hover:bg-halo hover:text-starlight"
    >
      {children}
    </button>
  );
}

function StarNode({
  node,
  focused,
  onSelect,
}: {
  node: SceneNode;
  focused: boolean;
  onSelect: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const visual = useRef<THREE.Group>(null);
  const reduceMotion = useReduceMotion();
  const { active, radius } = node;

  useEffect(() => {
    if (!hovered) return;
    document.body.style.cursor = "pointer";
    return () => {
      document.body.style.cursor = "";
    };
  }, [hovered]);

  // The swell is eased rather than snapped — a star that jumps size on
  // pointer-over reads as a glitch, and the cursor crossing a 4×-radius hit
  // sphere makes that jump frequent. Frame-rate independent, so it feels the
  // same on a 60Hz lab monitor as on a 144Hz one.
  const scaleTo = active && hovered ? 1.5 : 1;
  useFrame((_state, delta) => {
    const group = visual.current;
    if (!group) return;
    if (reduceMotion) {
      group.scale.setScalar(scaleTo);
      return;
    }
    const k = 1 - Math.exp(-delta * 14);
    group.scale.lerp(SCALE_TARGET.setScalar(scaleTo), k);
  });

  return (
    <group position={node.position}>
      <group ref={visual}>{node.body}</group>

      {/* Assigned-animal satellites, when the caller sent any. Outside the
          hover-swell group on purpose: the swell announces the *star* under
          the pointer, and satellites lurching outward with it would read as
          part of the star rather than the annotation they are. */}
      {node.orbiters && node.orbiters.length > 0 && (
        <OrbiterBelt orbiters={node.orbiters} starRadius={radius} />
      )}

      {/* A wider invisible hit area — a 0.2-unit sphere is a hard click target
          at overview distance. All interaction lives here, and it only exists
          for an active star, so an inert one is inert by construction rather
          than by a disabled handler (§6.2). */}
      {active && (
        <mesh
          visible={false}
          onClick={onSelect}
          onPointerOver={() => setHovered(true)}
          onPointerOut={() => setHovered(false)}
        >
          <sphereGeometry args={[radius * 4, 8, 8]} />
        </mesh>
      )}

      {active && <HoverReticle radius={radius} active={hovered && !focused} />}

      {/* Persistent, because "which star is which" is a question the overview
          should never make you hover to answer. */}
      {active && node.name && (
        <Nameplate
          name={node.name}
          badge={node.badge ?? null}
          radius={radius}
          hovered={hovered}
        />
      )}

      {focused && <ArrivalRings radius={radius} />}
    </group>
  );
}

/** Scratch vector for the hover lerp — allocating one per frame per star adds
 *  up to real garbage at 60fps × six stars. */
const SCALE_TARGET = new THREE.Vector3();

/**
 * The hover treatment: a billboarded targeting reticle — four short arcs at
 * the quadrants, the way an instrument marks the thing it is tracking.
 *
 * Deliberately *not* another full ring: `ArrivalRings` already owns concentric
 * rings for the focused state, and two ring treatments a few frames apart
 * would read as one confused animation. Billboarded so it faces the camera
 * from any orbit angle, which a flat ring in the XY plane does not.
 */
function HoverReticle({ radius, active }: { radius: number; active: boolean }) {
  const group = useRef<THREE.Group>(null);
  const materials = useRef<THREE.MeshBasicMaterial[]>([]);
  const reduceMotion = useReduceMotion();

  useFrame((_state, delta) => {
    const g = group.current;
    if (!g) return;
    const k = reduceMotion ? 1 : 1 - Math.exp(-delta * 16);
    // Sweeps inward as it appears — the arcs closing on the star is what makes
    // it read as acquiring a target rather than merely fading in.
    const scaleTo = active ? 1 : 1.35;
    g.scale.lerp(SCALE_TARGET.setScalar(scaleTo), k);
    const opacityTo = active ? 0.9 : 0;
    for (const material of materials.current) {
      if (material) material.opacity += (opacityTo - material.opacity) * k;
    }
  });

  return (
    <Billboard>
      <group ref={group}>
        {[0, 1, 2, 3].map((quadrant) => (
          <mesh key={quadrant} rotation={[0, 0, (quadrant * Math.PI) / 2]}>
            {/* A short arc centred on its quadrant, with a hair of thickness —
                thin enough to stay an annotation at overview distance. */}
            <ringGeometry
              args={[
                radius * 2.1,
                radius * 2.1 + 0.02,
                24,
                1,
                -Math.PI / 12,
                Math.PI / 6,
              ]}
            />
            <meshBasicMaterial
              ref={(material) => {
                if (material) materials.current[quadrant] = material;
              }}
              color={GL.pulsar}
              transparent
              opacity={0}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </mesh>
        ))}
      </group>
    </Billboard>
  );
}

/**
 * The callout: an optional badge and a name on a small matte plate, hung under
 * its star with a short leader.
 *
 * Rendered as DOM rather than in-scene text, so it stays crisp and uses the
 * app's own type (JetBrains Mono — this is an identifier, §2.3). No
 * `distanceFactor`: a plate that grew as the camera closed in would be
 * enormous on arrival at a star. Constant screen size is also what makes it a
 * HUD annotation rather than a floating object in the scene.
 */
function Nameplate({
  name,
  badge,
  radius,
  hovered,
}: {
  name: string;
  badge: number | null;
  radius: number;
  hovered: boolean;
}) {
  return (
    <Html
      center
      position={[0, -(radius * 3.5), 0]}
      // Never steals the pointer from the star's hit sphere behind it.
      style={{ pointerEvents: "none", userSelect: "none" }}
      // Kept below the docked detail panels, which sit at `z-20`. These plates
      // are crisp opaque DOM, not part of the scene the translucent panel is
      // meant to show through — one drifting over a button would be a plate
      // sitting on a control, which is worse than the star being hidden.
      zIndexRange={[10, 0]}
    >
      <div className="flex flex-col items-center">
        <span
          className="w-px transition-colors duration-200"
          style={{
            height: 9,
            background: hovered ? "var(--color-pulsar)" : "var(--color-halo)",
          }}
        />
        <span
          className="flex items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 py-[1px] transition-colors duration-200"
          style={{
            borderColor: hovered ? "var(--color-pulsar)" : "var(--color-halo)",
            background:
              "color-mix(in srgb, var(--color-void) 82%, transparent)",
          }}
        >
          {badge !== null && (
            <span className="font-mono text-[9px] leading-none text-pulsar">
              {badge}
            </span>
          )}
          <span className="font-mono text-[10px] leading-none text-starlight">
            {name}
          </span>
        </span>
      </div>
    </Html>
  );
}

/**
 * §6.3's arrival treatment — thin concentric rings that animate outward and
 * settle into a slowly rotating decorative ring. An instrument/HUD read rather
 * than a glow, which §2.2 forbids outright.
 */
function ArrivalRings({ radius }: { radius: number }) {
  const group = useRef<THREE.Group>(null);
  const rings = useRef<THREE.Mesh[]>([]);
  const elapsed = useRef(0);
  const reduceMotion = useReduceMotion();

  useFrame((_state, delta) => {
    if (reduceMotion) return;
    elapsed.current += delta;
    if (group.current) group.current.rotation.z += delta * 0.25;

    rings.current.forEach((ring, index) => {
      if (!ring) return;
      // Each ring expands from the star and settles, staggered.
      const t = Math.min(
        1,
        Math.max(0, (elapsed.current - index * 0.18) / 0.9),
      );
      const eased = 1 - (1 - t) ** 3;
      ring.scale.setScalar(0.25 + eased * 0.75);
      const material = ring.material as THREE.MeshBasicMaterial;
      material.opacity = 0.5 * eased;
    });
  });

  return (
    <group ref={group} rotation={[Math.PI / 2.6, 0, 0]}>
      {[2.6, 3.6, 4.8].map((scale, index) => (
        <mesh
          key={scale}
          ref={(mesh) => {
            if (mesh) rings.current[index] = mesh;
          }}
        >
          <ringGeometry args={[radius * scale, radius * scale + 0.012, 96]} />
          <meshBasicMaterial
            color={index === 1 ? GL.pulsar : GL.halo}
            transparent
            opacity={0}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
    </group>
  );
}

/**
 * One edge of the asterism.
 *
 * The geometry is memoized on the endpoint *arrays*, which is only safe because
 * placement is memoized upstream: both scenes rebuild their node list solely
 * when the layout genuinely changes, never on the health or telemetry updates
 * that arrive several times a second.
 */
function Link({
  from,
  to,
  live,
}: {
  from: [number, number, number];
  to: [number, number, number];
  live: boolean;
}) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute(
      "position",
      new THREE.Float32BufferAttribute([...from, ...to], 3),
    );
    return g;
  }, [from, to]);

  useEffect(() => () => geometry.dispose(), [geometry]);

  return (
    <line>
      <primitive object={geometry} attach="geometry" />
      <lineBasicMaterial
        color={GL.pulsar}
        transparent
        opacity={live ? 0.55 : 0.1}
      />
    </line>
  );
}

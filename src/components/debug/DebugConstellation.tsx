import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

import {
  resolveLayout,
  useBoxHealth,
  type BoxHealth,
} from "@/components/chrome/ConstellationStatus";
import { GL, GL_HEALTH } from "@/components/chrome/constellationStyle";
import {
  ConstellationScene,
  type SceneLink,
  type SceneNode,
} from "@/components/constellation3d/Scene";
import type { SceneOrbiter } from "@/components/constellation3d/Orbiters";
import { useRunningSession } from "@/lib/sessions/context";
import { buildSky } from "@/lib/sessions/stars";
import { useBoundBoxes, useSettings } from "@/lib/settings/context";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The Debug landing constellation (`ephymeris_v1.0.md` §4.3).
 *
 * The same 3D browser as Mission Control — same camera, same orbit/pan/zoom,
 * same hover reticle, nameplates and arrival flight, all from
 * `constellation3d/Scene` — pointed at the rig instead of at a cohort. Every
 * bound box is a star at its assigned slot, nicknamed; selecting one flies the
 * camera in and docks the box's detail panel over the still-running scene.
 *
 * **Colour here is status, not performance.** Mission Control tints a star by
 * the animal's rolling accuracy; that would be meaningless on a box, and this
 * view exists to answer "is this box alive and what is it doing". So the core
 * takes `GL_HEALTH`, and the motion says the rest — the same grammar the 2D
 * widget established, lifted into three dimensions:
 *
 *  - a detected box has a mote in orbit (it's alive on the bus);
 *  - an *open* box (passthrough / in session) adds a slow dashed ring — the
 *    instrument-HUD read, never a glow (§2.2);
 *  - a configured-but-undetected box sits still in Halo, and a faulted box
 *    still in Error red — stillness is the status.
 *
 * Unlike Mission Control there is no seeded fallback: `resolveLayout` answers
 * with the pre-zodiac `legacyLayout` when no constellation has been chosen, and
 * that already pins a position per box number.
 */
export function DebugConstellation({
  selected,
  onSelect,
}: {
  selected: number | null;
  onSelect: (box: number | null) => void;
}) {
  const { settings } = useSettings();
  const bound = useBoundBoxes();
  const health = useBoxHealth();

  const layout = useMemo(
    () => resolveLayout(settings.constellation, settings.constellationSlots, bound),
    [settings.constellation, settings.constellationSlots, bound],
  );

  // Boxes are their own occupants here — a star *is* a box, so the two ids are
  // the same fact. Keyed on the bound set alone: health arrives from the
  // presence poll and the port state machine and must never move a star.
  const boundKey = bound.join(",");
  const sky = useMemo(
    () =>
      buildSky(
        "debug",
        bound.map((box) => ({ occupantId: String(box), box })),
        layout,
        settings.constellation ?? "legacy",
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [boundKey, layout, settings.constellation],
  );

  const labels = useMemo(
    () => new Map(settings.boxes.map((b) => [b.box, b.label])),
    [settings.boxes],
  );

  // When a session is live, its box → animal mapping shows here too: the
  // assigned animal rides the box's star as a named satellite, so the rig
  // view answers "who is in box 3 right now" without leaving Debug. No
  // session, no satellites — the mote already says "alive on the bus".
  const running = useRunningSession();
  const crews = useMemo(() => {
    const map = new Map<number, SceneOrbiter[]>();
    for (const b of running?.boxes ?? []) {
      const crew = map.get(b.box) ?? [];
      crew.push({ id: b.animalId, name: b.animalName, active: b.running });
      map.set(b.box, crew);
    }
    return map;
  }, [running]);

  const nodes: SceneNode[] = sky.points.map((point, index) => {
    if (point.occupantId === null) {
      return {
        id: `star-${point.star ?? index}`,
        position: point.position,
        radius: point.radius,
        active: false,
        body: <EmptyStar radius={point.radius} />,
      };
    }
    const box = Number(point.occupantId);
    const state = health[box] ?? "absent";
    const crew = crews.get(box);
    return {
      id: point.occupantId,
      position: point.position,
      radius: point.radius,
      // Every bound box is inspectable, however sick — an absent or faulted box
      // is precisely the one you came here to open. This is the deliberate
      // difference from Mission Control, where an unlit star has no live view
      // to show and is inert by construction.
      active: true,
      name: labels.get(box) ?? `Box ${box}`,
      badge: box,
      // The anonymous mote stands down while a named satellite is up — two
      // craft in crossing orbits would read as noise, and a box with a crewed
      // run is self-evidently alive on the bus.
      body: <BoxStar radius={point.radius} health={state} crewed={!!crew?.length} />,
      orbiters: crew,
    };
  });

  const links: SceneLink[] = sky.links.map(([a, b]) => ({
    a,
    b,
    live: isLive(nodes[a], health) && isLive(nodes[b], health),
  }));

  return (
    <ConstellationScene
      nodes={nodes}
      links={links}
      focusedId={selected === null ? null : String(selected)}
      onFocus={(id) => onSelect(id === null ? null : Number(id))}
    />
  );
}

/** A link is live only when both endpoints are boxes that are present and
 *  healthy — the same rule the 2D widget's `isLinkLive` applies. */
function isLive(
  node: SceneNode | undefined,
  health: Partial<Record<number, BoxHealth>>,
): boolean {
  if (!node || node.badge === null || node.badge === undefined) return false;
  const state = health[node.badge];
  return state === "nominal" || state === "idle";
}

/**
 * One box, as a star. Matte and faceted — flat triangles catch nothing, which
 * is exactly right under §2.2's no-glow rule — with the motion carrying what
 * the colour alone can't.
 */
function BoxStar({
  radius,
  health,
  crewed = false,
}: {
  radius: number;
  health: BoxHealth;
  /** A named animal satellite is in orbit — the anonymous mote stands down. */
  crewed?: boolean;
}) {
  const reduceMotion = useReduceMotion();
  const core = useRef<THREE.Group>(null);
  const mote = useRef<THREE.Group>(null);
  const ring = useRef<THREE.Group>(null);

  const detected = health === "nominal" || health === "idle";
  const open = health === "nominal";

  useFrame((_state, delta) => {
    if (reduceMotion) return;
    // A slow turn, so the facets read as a solid rather than a disc. Stillness
    // is the status for an absent or faulted box, so neither turns.
    if (core.current && detected) core.current.rotation.y += delta * 0.35;
    if (mote.current) mote.current.rotation.y += delta * (open ? 0.9 : 0.45);
    if (ring.current) ring.current.rotation.z += delta * 0.26;
  });

  return (
    <group>
      <group ref={core}>
        <mesh>
          <icosahedronGeometry args={[radius, 1]} />
          <meshBasicMaterial color={GL_HEALTH[health]} />
        </mesh>
      </group>

      {/* Open box: the slow dashed instrument ring. Built from short arc
          segments rather than a dashed material, which needs line distances
          computed per geometry and reads inconsistently across drivers. */}
      {open && (
        <group ref={ring} rotation={[Math.PI / 2.4, 0, 0]}>
          {[0, 1, 2, 3, 4, 5].map((segment) => (
            <mesh key={segment} rotation={[0, 0, (segment * Math.PI) / 3]}>
              <ringGeometry
                args={[radius * 2.2, radius * 2.2 + 0.02, 16, 1, 0, Math.PI / 4.6]}
              />
              <meshBasicMaterial
                color={GL.pulsar}
                transparent
                opacity={0.45}
                side={THREE.DoubleSide}
              />
            </mesh>
          ))}
        </group>
      )}

      {/* Detected box: a mote in orbit — alive on the bus.
          Sized as a compromise between two distances that pull opposite ways:
          the mote does its work at overview range, where anything much smaller
          disappears, but the camera also arrives within a few units of it, and
          at that range a large one reads as a second star rather than an
          annotation. */}
      {detected && !crewed && (
        <group ref={mote} rotation={[0.4, 0, 0.15]}>
          <mesh position={[radius * 2.5, 0, 0]}>
            <sphereGeometry args={[radius * 0.2, 10, 10]} />
            <meshBasicMaterial color={GL.starlight} transparent opacity={0.85} />
          </mesh>
        </group>
      )}
    </group>
  );
}

/** An unclaimed star of the asterism — scenery, so the chosen constellation
 *  still reads on a rig that binds two boxes out of twelve stars. */
function EmptyStar({ radius }: { radius: number }) {
  return (
    <mesh>
      <sphereGeometry args={[radius, 12, 12]} />
      <meshBasicMaterial color={GL.halo} transparent opacity={0.55} />
    </mesh>
  );
}

import { useFrame } from "@react-three/fiber";
import { MAX_FRAME_SECONDS } from "@/components/constellation3d/CameraRig";
import { useMemo, useRef } from "react";
import * as THREE from "three";

import {
  useBoxHealth,
  type BoxHealth,
} from "@/components/chrome/ConstellationStatus";
import { GL, GL_HEALTH } from "@/components/chrome/constellationStyle";
import {
  ConstellationScene,
  type SceneLink,
  type SceneNode,
} from "@/components/constellation3d/Scene";
import { StellarSurface } from "@/components/constellation3d/StellarSurface";
import { useRigSky } from "@/components/constellation3d/useRigSky";
import { assignShips } from "@/lib/constellations/ships";
import { useBoxStellar } from "./useBoxStellar";
import { useRunningSession } from "@/lib/sessions/context";
import { useBoundBoxes, useSettings } from "@/lib/settings/context";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The Debug landing constellation (`dashboard.md` §4).
 *
 * The same 3D browser as Mission Control — same camera, same orbit/pan/zoom,
 * same hover reticle, nameplates and arrival flight, all from
 * `constellation3d/Scene` — pointed at the rig instead of at a cohort. Every
 * bound box is a star at its assigned slot, nicknamed; selecting one flies the
 * camera in and docks the box's detail panel over the still-running scene.
 *
 * **Colour is temperature here too** (revised 2026-07-29 — this view
 * originally kept colour for status). A box's star takes Mission Control's
 * stellar ramp (`StellarSurface`), tinted by the **mean recorded accuracy of
 * the animals assigned to that box** across all scored sessions
 * (`useBoxStellar`), so the rig view answers "which boxes house working
 * animals" with the same vocabulary the session view taught. The assigned
 * animals themselves ride the star as named satellites, running or not.
 *
 * Status still animates, it just no longer colours the photosphere — the 2D
 * widget's grammar, lifted into three dimensions:
 *
 *  - a *detected* box's surface churns and carries a mote in orbit (alive on
 *    the bus); an undetected box's surface is frozen — stillness is the
 *    status, carried into the star itself;
 *  - an *open* box (passthrough / in session) adds the slow dashed instrument
 *    ring — the instrument-HUD read, never a glow (§2.2);
 *  - a *faulted* box wears a thin steady ring in Error red — the one place
 *    status still owns a colour, because a fault must not be mistakable for a
 *    cool star.
 *
 * Unlike Mission Control there is no seeded fallback: `resolveLayout` answers
 * with the pre-zodiac `legacyLayout` when no constellation has been chosen, and
 * that already pins a position per box number.
 */
export function DebugConstellation({
  selected,
  onSelect,
  docksPanel = true,
  interactive = true,
}: {
  selected: number | null;
  onSelect: (box: number | null) => void;
  /**
   * False on the Dashboard, which shows this same sky but opens no panel —
   * selecting a star there navigates to Debug instead. See
   * `ConstellationScene`: it gates the focused-state restrictions, which all
   * exist to protect a frame composed around a panel.
   */
  docksPanel?: boolean;
  /**
   * False where the sky is **backdrop only** — the guided session steps, which
   * show the rig behind their frosted panels so the flow reads as one continuous
   * scene rather than three screens.
   *
   * Every bound box is normally inspectable, so without this a star there would
   * offer a hover reticle and a click that goes nowhere. Inert is not the same
   * as hidden: the constellation still draws, still turns, still carries its
   * temperatures. It just isn't a control.
   */
  interactive?: boolean;
}) {
  const { settings } = useSettings();
  const bound = useBoundBoxes();
  const health = useBoxHealth();
  const stellar = useBoxStellar();

  // Boxes are their own occupants here — a star *is* a box, so the two ids are
  // the same fact. Everything about placement comes from `useRigSky`, which
  // Mission Control also goes through: same asterism, same seed, same sizes.
  const boundKey = bound.join(",");
  const occupants = useMemo(
    () => bound.map((box) => ({ occupantId: String(box), box })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [boundKey],
  );
  const sky = useRigSky(occupants);

  const labels = useMemo(
    () => new Map(settings.boxes.map((b) => [b.box, b.label])),
    [settings.boxes],
  );

  // Cagemates ride as one ship (`ships.ts`): each crew orbits the box of its
  // currently running member — the live session's mapping wins over standing
  // assignment — else the box its most recently ran member actually ran on.
  // So the rig view answers "where is this cage" with where the operator last
  // saw it, and a live run reads as motion against the parked fleet.
  const running = useRunningSession();
  const ships = useMemo(() => {
    const members = stellar.members.map((m) => ({ ...m }));
    for (const b of running?.boxes ?? []) {
      const known = members.find((m) => m.id === b.animalId);
      if (known) {
        known.box = b.box;
        known.running = b.running;
      } else {
        // Analytics hasn't caught up with this cohort yet — the live mapping
        // is still a fact worth a ship, solo until its cage is known.
        members.push({
          id: b.animalId,
          name: b.animalName,
          cohortId: running?.session.cohortId ?? null,
          cage: null,
          box: b.box,
          running: b.running,
        });
      }
    }
    return assignShips(members);
  }, [stellar, running]);

  const nodes: SceneNode[] = sky.points.map((point) => {
    if (point.occupantId === null) {
      return {
        id: `star-${point.star}`,
        position: point.position,
        radius: point.radius,
        active: false,
        body: <EmptyStar radius={point.radius} />,
      };
    }
    const box = Number(point.occupantId);
    const state = health[box] ?? "absent";
    const crew = ships.get(box);
    return {
      id: point.occupantId,
      position: point.position,
      radius: point.radius,
      // Every bound box is inspectable, however sick — an absent or faulted box
      // is precisely the one you came here to open. This is the deliberate
      // difference from Mission Control, where an unlit star has no live view
      // to show and is inert by construction. `interactive` is the other
      // exception: on the guided steps the sky is backdrop, not instrument.
      active: interactive,
      name: labels.get(box) ?? `Box ${box}`,
      badge: box,
      // The anonymous mote stands down while any satellite is up — crossing
      // craft would read as noise, and a crewed box's liveness still shows in
      // the churn of its surface.
      body: (
        <BoxStar
          radius={point.radius}
          health={state}
          accuracy={stellar.boxes[box]?.accuracy ?? null}
          crewed={!!crew?.length}
          // Keyed the same way Mission Control keys it, so box 3's star turns
          // the same way in both — see the note on `seed` there.
          seed={`box:${box}`}
        />
      ),
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
      docksPanel={docksPanel}
      interactive={interactive}
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
 * One box, as a star. The photosphere is Mission Control's shared
 * `StellarSurface`, tinted by the box's earned temperature; the hardware
 * status rides on top as motion and instrument rings, never as surface
 * colour — except the fault ring, which is the one status that must not be
 * readable as anything else.
 */
function BoxStar({
  radius,
  health,
  accuracy,
  crewed = false,
  seed,
}: {
  radius: number;
  health: BoxHealth;
  /** Mean recorded accuracy of the box's assigned animals (`useBoxStellar`). */
  accuracy: number | null;
  /** A named animal satellite is in orbit — the anonymous mote stands down. */
  crewed?: boolean;
  /** Seeds this star's rotation (`StellarSurface`) — the box number here. */
  seed?: string | undefined;
}) {
  const reduceMotion = useReduceMotion();
  const mote = useRef<THREE.Group>(null);
  const ring = useRef<THREE.Group>(null);

  const detected = health === "nominal" || health === "idle";
  const open = health === "nominal";

  useFrame((_state, raw) => {
    // Bounded like every other time-integrated animation: an unclamped
    // `delta` is wall-clock, so one stalled frame jumps this forward by the
    // whole stall (`CameraRig`'s `MAX_FRAME_SECONDS`).
    const delta = Math.min(raw, MAX_FRAME_SECONDS);
    if (reduceMotion) return;
    if (mote.current) mote.current.rotation.y += delta * (open ? 0.9 : 0.45);
    if (ring.current) ring.current.rotation.z += delta * 0.26;
  });

  return (
    <group>
      {/* An undetected box's star is **dark and still**: burned down to a
          fraction of its earned brightness, its surface frozen. Two readings of
          one fact on purpose — the dim carries at overview range where a
          stopped churn is too subtle to notice, the churn carries up close
          where every star fills the frame — and neither is a colour, so a cool
          star and a dark one never trade places. This is where hardware state
          lives now; the cage-ships overhead orbit regardless (`Orbiters.tsx`). */}
      <StellarSurface
        radius={radius}
        accuracy={accuracy}
        churn={detected}
        dim={!detected}
        seed={seed}
      />

      {/* Open box: the slow dashed instrument ring. Built from short arc
          segments rather than a dashed material, which needs line distances
          computed per geometry and reads inconsistently across drivers. */}
      {open && (
        <group ref={ring} rotation={[Math.PI / 2.4, 0, 0]}>
          {[0, 1, 2, 3, 4, 5].map((segment) => (
            <mesh key={segment} rotation={[0, 0, (segment * Math.PI) / 3]}>
              <ringGeometry
                args={[
                  radius * 2.2,
                  radius * 2.2 + 0.02,
                  16,
                  1,
                  0,
                  Math.PI / 4.6,
                ]}
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

      {/* Faulted box: a thin steady Error-red ring. Status colour's last
          holdout — a fault has to be unmistakable at overview range, and a
          cool-red star alone could be an innocently unscored box. */}
      {health === "fault" && (
        <mesh rotation={[Math.PI / 2.4, 0, 0]}>
          <ringGeometry args={[radius * 1.7, radius * 1.7 + 0.045, 40]} />
          <meshBasicMaterial
            color={GL_HEALTH.fault}
            transparent
            opacity={0.85}
            side={THREE.DoubleSide}
          />
        </mesh>
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
            <meshBasicMaterial
              color={GL.starlight}
              transparent
              opacity={0.85}
            />
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

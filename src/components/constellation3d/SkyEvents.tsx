import { Billboard } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { GL } from "@/components/chrome/constellationStyle";
import { mulberry32 } from "@/lib/prng";
import { useReduceMotion } from "@/lib/useReduceMotion";

import { MAX_FRAME_SECONDS } from "./CameraRig";
import { makeFlashTexture, makeStreakTexture } from "./skyTextures";

/**
 * The things that happen. A supernova now and then, meteors more often, a
 * comet rarely — one at a time, on a seeded schedule, so the sky is *active*
 * without ever being a light show, and the same sky shows the same events in
 * the same order on every machine. Only the clock is live.
 *
 * One scheduler owns all of them, which is what keeps them from overlapping:
 * a meteor cannot fire under a supernova, and the lull after each is drawn
 * from the same stream as the site. Under reduced motion nothing here fires;
 * the field stays, the theatre goes (`Backdrop.tsx`).
 *
 * **Local time, not `clock.elapsedTime`.** Every event compares `now` against
 * a `startedAt` and a `nextAt` recorded on earlier frames, and r3f zeroes
 * `elapsedTime` on every `frameloop` transition — which stranded the original
 * supernova permanently (the note that used to live on it is now the note on
 * this scheduler).
 */
export function SkyEvents({
  seed,
  shellNear,
  shellFar,
  paused,
}: {
  seed: number;
  shellNear: number;
  shellFar: number;
  /** The window is unfocused: a running event plays out, but the lull's
   *  clock holds, so nothing new ignites behind it. */
  paused: boolean;
}) {
  const reduceMotion = useReduceMotion();

  const flashTexture = useMemo(() => makeFlashTexture(), []);
  const streakTexture = useMemo(() => makeStreakTexture(), []);
  useEffect(() => () => {
    flashTexture.dispose();
    streakTexture.dispose();
  }, [flashTexture, streakTexture]);

  const nova = useRef<THREE.Group>(null);
  const novaFlash = useRef<THREE.Mesh>(null);
  const novaRing = useRef<THREE.Mesh>(null);
  const meteor = useRef<THREE.Group>(null);
  const meteorMesh = useRef<THREE.Mesh>(null);
  const comet = useRef<THREE.Group>(null);
  const cometMesh = useRef<THREE.Mesh>(null);

  const state = useRef<Scheduler>({
    rand: mulberry32(seed ^ 0x5f),
    elapsed: 0,
    nextAt: 5,
    current: null,
  });

  useFrame((_state, raw) => {
    const delta = Math.min(raw, MAX_FRAME_SECONDS);
    const s = state.current;
    if (!(paused && s.current === null)) s.elapsed += delta;
    const now = s.elapsed;

    const hide = () => {
      if (nova.current) nova.current.visible = false;
      if (meteor.current) meteor.current.visible = false;
      if (comet.current) comet.current.visible = false;
    };

    if (reduceMotion) {
      hide();
      s.current = null;
      return;
    }

    // Ignite the next event when its time comes.
    if (s.current === null) {
      if (paused || now < s.nextAt) return;
      s.current = ignite(s.rand, now, shellNear, shellFar);
    }

    const ev = s.current;
    const t = (now - ev.startedAt) / ev.seconds;
    if (t >= 1) {
      hide();
      s.current = null;
      s.nextAt = now + lullAfter(ev.kind, s.rand);
      return;
    }

    if (ev.kind === "nova") {
      const g = nova.current;
      if (!g) return;
      g.visible = true;
      g.position.copy(ev.from);
      // Fast attack, long exponential decay — the shape of a real light curve.
      const attack = Math.min(1, t / 0.06);
      const decay = Math.exp(-t * 4.2);
      if (novaFlash.current) {
        novaFlash.current.scale.setScalar(2.5 + t * 9);
        (novaFlash.current.material as THREE.MeshBasicMaterial).opacity = attack * decay;
      }
      if (novaRing.current) {
        novaRing.current.scale.setScalar(0.5 + t * 16);
        (novaRing.current.material as THREE.MeshBasicMaterial).opacity =
          0.5 * attack * (1 - t) ** 2;
      }
      return;
    }

    // Meteor and comet: a streak travelling from `from` to `to`, its head at
    // the leading end, fading in fast and out slow.
    const g = ev.kind === "meteor" ? meteor.current : comet.current;
    const mesh = ev.kind === "meteor" ? meteorMesh.current : cometMesh.current;
    if (!g || !mesh) return;
    g.visible = true;
    const eased = ev.kind === "meteor" ? t : t; // linear travel for both
    g.position.lerpVectors(ev.from, ev.to, eased);
    // Aim the streak along its travel: the quad's +x is its head.
    const dir = SCRATCH.copy(ev.to).sub(ev.from).normalize();
    g.quaternion.setFromUnitVectors(X_AXIS, dir);
    const fade = Math.min(1, t / 0.12) * (1 - Math.max(0, (t - 0.7) / 0.3));
    (mesh.material as THREE.MeshBasicMaterial).opacity = fade * ev.brightness;
  });

  return (
    <group>
      {/* Supernova: a flash that blooms and dies while a shell ring expands. */}
      <group ref={nova} visible={false}>
        <Billboard>
          <mesh ref={novaFlash} renderOrder={-1}>
            <planeGeometry args={[1, 1]} />
            <meshBasicMaterial map={flashTexture} transparent opacity={0} depthWrite={false} />
          </mesh>
          <mesh ref={novaRing} renderOrder={-1}>
            <ringGeometry args={[0.94, 1, 48]} />
            <meshBasicMaterial
              color={GL.starlight}
              transparent
              opacity={0}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </mesh>
        </Billboard>
      </group>

      {/* Meteor: a short bright streak, gone in under a second. Not a
          billboard — it has a direction, and it lies along it. */}
      <group ref={meteor} visible={false}>
        <mesh ref={meteorMesh} renderOrder={-1} scale={[METEOR_LENGTH, METEOR_LENGTH * 0.12, 1]}>
          <planeGeometry args={[1, 1]} />
          <meshBasicMaterial
            map={streakTexture}
            transparent
            opacity={0}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            side={THREE.DoubleSide}
          />
        </mesh>
      </group>

      {/* Comet: the same streak, long and slow, with a faint violet cast — the
          one event that lasts long enough to be pointed at. */}
      <group ref={comet} visible={false}>
        <mesh ref={cometMesh} renderOrder={-1} scale={[COMET_LENGTH, COMET_LENGTH * 0.1, 1]}>
          <planeGeometry args={[1, 1]} />
          <meshBasicMaterial
            map={streakTexture}
            color={new THREE.Color(GL.pulsar).lerp(new THREE.Color(GL.starlight), 0.6)}
            transparent
            opacity={0}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            side={THREE.DoubleSide}
          />
        </mesh>
      </group>
    </group>
  );
}

type Kind = "nova" | "meteor" | "comet";

interface Event {
  kind: Kind;
  startedAt: number;
  seconds: number;
  from: THREE.Vector3;
  to: THREE.Vector3;
  brightness: number;
}

interface Scheduler {
  rand: () => number;
  elapsed: number;
  nextAt: number;
  current: Event | null;
}

/** A seeded point on the star shell, flattened like the field. */
function onShell(rand: () => number, near: number, far: number): THREE.Vector3 {
  const theta = rand() * Math.PI * 2;
  const phi = Math.acos(2 * rand() - 1);
  const r = near + rand() * (far - near);
  return new THREE.Vector3(
    Math.sin(phi) * Math.cos(theta) * r,
    Math.cos(phi) * r * 0.72,
    Math.sin(phi) * Math.sin(theta) * r,
  );
}

/** Choose and place the next event. Meteors are common, novae occasional,
 *  comets rare — the mix that reads as a live sky rather than a fireworks
 *  loop. */
function ignite(rand: () => number, now: number, near: number, far: number): Event {
  const roll = rand();
  const kind: Kind = roll < 0.62 ? "meteor" : roll < 0.92 ? "nova" : "comet";
  const from = onShell(rand, near, far);
  if (kind === "nova") {
    return { kind, startedAt: now, seconds: NOVA_SECONDS, from, to: from, brightness: 1 };
  }
  // A streak travels a short arc across the shell: pick a second point a
  // little way along, at the same depth.
  const arc = kind === "meteor" ? 0.18 + rand() * 0.14 : 0.6 + rand() * 0.4;
  const axis = new THREE.Vector3(rand() - 0.5, rand() - 0.5, rand() - 0.5).normalize();
  const to = from.clone().applyAxisAngle(axis, arc);
  return {
    kind,
    startedAt: now,
    seconds: kind === "meteor" ? 0.55 + rand() * 0.5 : COMET_SECONDS,
    from,
    to,
    brightness: kind === "meteor" ? 0.55 + rand() * 0.45 : 0.7,
  };
}

/** The quiet after each kind — long after the big ones, short after a meteor. */
function lullAfter(kind: Kind, rand: () => number): number {
  if (kind === "nova") return 24 + rand() * 30;
  if (kind === "comet") return 60 + rand() * 60;
  return 6 + rand() * 14;
}

const NOVA_SECONDS = 4.5;
const COMET_SECONDS = 28;
/** World units, on a shell ~60–90 out. */
const METEOR_LENGTH = 7;
const COMET_LENGTH = 26;

const X_AXIS = new THREE.Vector3(1, 0, 0);
const SCRATCH = new THREE.Vector3();

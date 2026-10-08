import { OrbitControls } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useRef } from "react";
import * as THREE from "three";

import {
  getSceneNodes,
  setFlying,
  setViewApi,
  useFlying,
  useSceneIntent,
} from "./sceneIntent";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The camera, its controls, and the eased move between framings.
 *
 * Split out of `Scene.tsx` for one concrete reason: these two components are
 * mounted by `SharedCanvas.tsx` as permanent scene children, and `Scene.tsx`
 * imports `useConstellationView` back out of `SharedCanvas.tsx`. Keeping them
 * together would make that a cycle — survivable today, since every binding in it
 * is a hoisted function declaration, and a trap the first time someone converts
 * one to a `const`.
 */

/** Where the camera sits when nothing is focused. */
export const OVERVIEW_POSITION = new THREE.Vector3(0, 4, 18);
export const OVERVIEW_TARGET = new THREE.Vector3(0, 0, 0);
/**
 * Where the camera sits when the whole asterism is the subject — Debug's
 * all-boxes view, whose panel docks along the bottom (`SceneIntent.frameAll`).
 * The overview's own heading, pulled back, and aimed below the asterism so it
 * rises into the open sky above the panel rather than sitting behind it.
 */
export const ALL_TARGET = new THREE.Vector3(0, -6.4, 0);
export const ALL_POSITION = ALL_TARGET.clone().add(
  OVERVIEW_POSITION.clone().sub(OVERVIEW_TARGET).multiplyScalar(1.95),
);
/**
 * How close to the overview counts as *being* at the overview, in world units.
 *
 * The scene spans roughly ±10, so this is a small fraction of a star's spacing —
 * loose enough that a camera nobody has touched reads as "unmoved", tight enough
 * that any orbit or zoom an operator meant to make is one the next arrival
 * animates back out of rather than silently snapping.
 */
const OVERVIEW_EPSILON = 0.05;
/** How far from a star the camera settles on arrival. */
const ARRIVAL_DISTANCE = 3.6;
/**
 * Ceiling on the framing bias, as a fraction of a half-frame. The views publish
 * where the star should sit in px (`SceneIntent.frameShift`); on a window
 * narrow enough that the panel covers most of it, the px request would push the
 * star under the sidebar's glass — the clamp keeps it on screen instead
 * (`ARCHITECTURE.md#one-sky`).
 */
const STAR_FRAME_BIAS_MAX = 0.6;
/** The fly takes this long; short enough not to feel like waiting. */
const FLIGHT_SECONDS = 1.5;
/** Longest `delta` any time-integrated animation will honour — see the frame
 *  callback in `CameraRig`. Two frames at 60fps. */
export const MAX_FRAME_SECONDS = 1 / 30;
/** How far one arrow press moves the camera, as a fraction of the visible
 *  half-frame. Small enough to nudge, large enough to be worth a click. */
const PAN_STEP = 0.22;

interface FlightMove {
  fromPosition: THREE.Vector3;
  fromTarget: THREE.Vector3;
  toPosition: THREE.Vector3;
  toTarget: THREE.Vector3;
  elapsed: number;
}

/**
 * The one camera, mounted for the app's lifetime (`SharedCanvas.tsx`).
 *
 * The eased cinematic move, and the one acknowledged exception to the
 * app's spring-physics convention: a camera flythrough reads as cinematic
 * rather than mechanical, and a spring would fight that.
 *
 * > [!IMPORTANT]
 * > **This component never unmounts, and that is the design.** It used to live
 * > inside each view's swapped scene content, which made the camera a baton:
 * > a mounting rig claimed it, saved the outgoing view's pose under a key,
 * > banked any move still in the air, and restored a pose on arrival. All of
 * > that was correct only if mounts and unmounts interleaved in an assumed
 * > order — *across two React roots*, the DOM tree and r3f's own, joined by a
 * > `useSyncExternalStore` and a portal. Four separate attempts to stop the
 * > camera snapping on a sidebar round trip each fixed a real defect and none
 * > fixed that one, because each was a prediction about that interleaving.
 * >
 * > There is no interleaving now. A route change is a prop change on a live
 * > component; views only *declare* what they want (`sceneIntent.ts`). If the
 * > camera ever needs to know something new, add it to that snapshot — do not
 * > reach for a mount effect.
 */
export function CameraRig() {
  const { attached, focusKey, focusedId, docksPanel, frameShift, frameAll } = useSceneIntent();
  const { camera, controls, size } = useThree();
  const reduceMotion = useReduceMotion();

  // The live viewport, readable from effects that must not re-run on resize.
  const sizeRef = useRef(size);
  sizeRef.current = size;

  const flight = useRef<FlightMove | null>(null);
  const target = useRef(OVERVIEW_TARGET.clone());
  const biasMove = useRef<{ from: number; to: number; elapsed: number } | null>(
    null,
  );
  /** The camera's framing bias, as a fraction of a half-frame. A plain ref now
   *  that one component owns the camera for the whole session. */
  const frameBias = useRef(0);

  const focusedIdRef = useRef(focusedId);
  focusedIdRef.current = focusedId;
  const frameAllRef = useRef(frameAll);
  frameAllRef.current = frameAll;

  // The orbit controls, readable from effects that must not re-run when drei
  // swaps them in — `makeDefault` publishes them from a *passive* effect, so
  // they are still null through the first commit.
  const controlsRef = useRef(controls);
  controlsRef.current = controls;

  /**
   * The single writer of `camera.view`. Clears below an epsilon rather than
   * setting a zero-width offset, so the resting state stays `camera.view ===
   * null` exactly as it was before the bias was animated.
   *
   * Always uses the *live* viewport size: `setViewOffset` assigns
   * `camera.aspect` as a side effect, so a stale size would silently desync the
   * aspect from the one r3f maintains.
   */
  const applyFrameBias = useCallback(
    (bias: number) => {
      frameBias.current = bias;
      const perspective = camera as THREE.PerspectiveCamera;
      if (!perspective.isPerspectiveCamera) return;
      const { width, height } = sizeRef.current;
      if (Math.abs(bias) < 0.001) {
        perspective.clearViewOffset();
      } else {
        perspective.setViewOffset(
          width,
          height,
          (width / 2) * bias,
          0,
          width,
          height,
        );
      }
      perspective.updateProjectionMatrix();
    },
    [camera],
  );

  /** Start an eased move to `toPosition`/`toTarget`, or snap under reduced
   *  motion. The one place a flight is created. */
  const flyTo = useCallback(
    (toPosition: THREE.Vector3, toTarget: THREE.Vector3) => {
      if (reduceMotion) {
        camera.position.copy(toPosition);
        target.current.copy(toTarget);
        camera.lookAt(toTarget);
        // The pivot handoff the end of a flight does, for the path that has no
        // flight to end. Without it the controls are re-enabled still pivoting
        // on wherever they were last told, and their next frame aims the camera
        // back there — so reduced motion would snap *to* a star and then swing
        // off it. Before `setFlying`, so no frame can land in between.
        const orbit = controlsRef.current as unknown as {
          target?: THREE.Vector3;
          update?: () => void;
        } | null;
        orbit?.target?.copy(target.current);
        orbit?.update?.();
        setFlying(false);
        return;
      }
      flight.current = {
        fromPosition: camera.position.clone(),
        fromTarget: target.current.clone(),
        toPosition,
        toTarget,
        elapsed: 0,
      };
      setFlying(true);
    },
    [camera, reduceMotion],
  );

  /*
   * **The arrival rule, and the only thing that hangs off a view appearing.**
   *
   * `attached` going false → true is the one fact the snapshot cannot otherwise
   * carry: `focusKey` is `""` both before and after an unfocused view arrives,
   * so nothing else changes when a view opens on the same state the last one
   * left. Everything the old placement effect did — claim, restore, classify,
   * suppress — collapses into this:
   *
   * > A view that arrives with nothing focused, on a camera that is not at the
   * > overview, eases it there. Otherwise nothing happens at all.
   *
   * The camera is simply wherever the last view left it, because it is the same
   * object and nothing tore it down. There is no pose to restore and no "was
   * that a close-up or a pan" to get wrong — a distance answers it outright.
   *
   * A focused arrival is not handled here: publishing a focus changes
   * `focusKey`, which the flight effect below already reacts to.
   */
  const wasAttached = useRef(false);
  const everAttached = useRef(false);
  useEffect(() => {
    const arrived = attached && !wasAttached.current;
    wasAttached.current = attached;
    if (!arrived || focusedIdRef.current !== null) return;
    // The all-boxes view has a home of its own, which its `focusKey` ("all")
    // already flies to — the overview is not where it should arrive.
    if (frameAllRef.current) {
      everAttached.current = true;
      return;
    }

    if (!everAttached.current) {
      // **Cold start.** The camera is still on r3f's default pose, which is not
      // a view anyone chose — it is just where the `Canvas` put it. Easing out
      // of it would open the app on a 1.5 s dolly nobody asked for, so the very
      // first attach places the camera outright.
      everAttached.current = true;
      camera.position.copy(OVERVIEW_POSITION);
      target.current.copy(OVERVIEW_TARGET);
      camera.lookAt(target.current);
      return;
    }

    const atOverview =
      camera.position.distanceTo(OVERVIEW_POSITION) < OVERVIEW_EPSILON &&
      target.current.distanceTo(OVERVIEW_TARGET) < OVERVIEW_EPSILON;
    if (atOverview) return;

    flyTo(OVERVIEW_POSITION.clone(), OVERVIEW_TARGET.clone());
  }, [attached, camera, flyTo]);

  /*
   * Composing the focused frame: slide the rendered window right, which puts
   * the scene — and the star the camera is aimed at — left of centre.
   *
   * **Eased, not snapped.** This used to be one projection write on the commit
   * where `focusedId` changed, so the entire scene jumped 10% of the window
   * width on frame 1 while the camera was still 1.5 s from the star — a hard
   * cut laid over a smooth move, and the thing that made selecting a star read
   * as jarring. The bias now runs on the same curve and duration as the flight
   * (see `useFrame` below), so the framing and the camera arrive together.
   *
   * The target is 0 unless a star is focused **and** this view docks a panel:
   * the bias exists solely to clear that panel, so a view without one is
   * centred.
   *
   * Applied as a **projection shift** (`setViewOffset`), not by aiming the
   * camera past the star. That distinction is the whole trick: the orbit pivot
   * stays exactly on the star, so dragging turns the view around it and the
   * star holds its place in the frame at every angle. Aiming off-target —
   * which is what the old world-unit `PANEL_OFFSET` did — puts the pivot
   * beside the star instead, and since that offset is fixed in world space
   * rather than to the camera, half an orbit swings the star across the frame
   * and behind the panel.
   *
   * The geometry: `setViewOffset`'s x is `(width / 2) · bias`, so a bias of
   * `2 · frameShift / width` lands the star exactly `frameShift` px left of
   * centre — the midpoint of the uncovered strip when the view published
   * `(panelOuter − leftChrome) / 2`. Recomputed on resize because `size` is
   * reactive; the restatement effect below keeps the *animated* value pinned
   * to pixels through the resize itself.
   */
  // `frameAll` composes the whole asterism the same way a focused star is
  // composed — and may shift either way, since its panel docks along the
  // bottom and the only chrome to clear sideways is the sidebar on the left.
  const biasTarget =
    frameAll && docksPanel
      ? Math.min(STAR_FRAME_BIAS_MAX, Math.max(-STAR_FRAME_BIAS_MAX, (2 * frameShift) / size.width))
      : focusedId !== null && docksPanel
        ? Math.min(STAR_FRAME_BIAS_MAX, Math.max(0, (2 * frameShift) / size.width))
        : 0;

  useEffect(() => {
    if (reduceMotion) {
      biasMove.current = null;
      applyFrameBias(biasTarget);
      return;
    }
    // Guarded so a re-render that doesn't change the target can't restart a
    // move that is already heading there.
    if (biasMove.current?.to === biasTarget) return;
    if (Math.abs(frameBias.current - biasTarget) < 0.001) return;
    biasMove.current = { from: frameBias.current, to: biasTarget, elapsed: 0 };
  }, [biasTarget, reduceMotion, applyFrameBias]);

  /*
   * Resize restates the **current animated value**, never the target — a window
   * resize mid-ease must not teleport the composition to where it is heading.
   * The shift is in pixels and r3f updates `aspect` on its own while leaving
   * `camera.view` alone, so without this the framing drifts as the window
   * changes.
   */
  useEffect(() => {
    applyFrameBias(frameBias.current);
  }, [size.width, size.height, applyFrameBias]);

  // drei builds its controls in a passive effect and starts them pivoting on the
  // origin; hand them the camera's real pivot the moment they exist. Once only
  // now — the controls are as permanent as this rig is (`SharedCanvas.tsx`), so
  // there is no fresh instance on every navigation to re-seed.
  useEffect(() => {
    const orbit = controls as unknown as {
      target?: THREE.Vector3;
      update?: () => void;
    } | null;
    if (!orbit?.target) return;
    orbit.target.copy(target.current);
    orbit.update?.();
    camera.lookAt(target.current);
  }, [controls, camera]);

  // Panning moves the camera and its orbit target by the same vector, so the
  // view slides without the constellation swinging around a moved pivot.
  useEffect(() => {
    const orbit = controls as unknown as {
      target?: THREE.Vector3;
      update?: () => void;
    } | null;

    setViewApi({
      pan(dx, dy) {
        // A press supersedes an in-progress flight rather than being swallowed
        // by it. Ignoring the press while flying was the obvious reading, and
        // it is wrong twice: the operator asking to move now means now, and a
        // flight only advances while frames are being delivered — a window left
        // in the background stops receiving them mid-move, and the controls
        // would stay dead until it was focused again.
        flight.current = null;
        setFlying(false);
        const perspective = camera as THREE.PerspectiveCamera;
        const pivot = orbit?.target ?? target.current;
        // Half-height of the frustum at the pivot's distance — the unit that
        // makes one press cover the same visible fraction at any zoom.
        const reach =
          camera.position.distanceTo(pivot) *
          Math.tan(((perspective.fov ?? 45) / 2) * (Math.PI / 180));
        const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0);
        const up = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 1);
        const move = new THREE.Vector3()
          .addScaledVector(right, dx * PAN_STEP * reach)
          .addScaledVector(up, dy * PAN_STEP * reach);
        camera.position.add(move);
        target.current.add(move);
        orbit?.target?.copy(target.current);
        orbit?.update?.();
      },
      recenter() {
        if (frameAllRef.current) flyTo(ALL_POSITION.clone(), ALL_TARGET.clone());
        else flyTo(OVERVIEW_POSITION.clone(), OVERVIEW_TARGET.clone());
      },
    });
    return () => setViewApi(null);
  }, [camera, controls, flyTo]);

  /*
   * The flight is triggered by *where we are going*, not by the array it was
   * read out of — `nodes` is rebuilt whenever the roster or health changes, and
   * a camera that re-flew on array identity would fight every orbit and pan the
   * operator made. `focusKey` is that destination as a primitive, derived by
   * whichever view is publishing (`sceneIntent.ts`), so this fires on a real
   * change and nothing else.
   */
  useEffect(() => {
    const star =
      focusedIdRef.current === null
        ? undefined
        : getSceneNodes().find((n) => n.id === focusedIdRef.current);
    const starPoint = star ? new THREE.Vector3(...star.position) : null;

    // Approach along the current view direction, so the move never swings the
    // constellation around behind the camera.
    const approach = starPoint
      ? camera.position.clone().sub(starPoint).normalize()
      : null;
    const home = frameAllRef.current ? ALL_POSITION : OVERVIEW_POSITION;
    const toPosition =
      starPoint && approach
        ? starPoint
            .clone()
            .add(approach.clone().multiplyScalar(ARRIVAL_DISTANCE))
        : home.clone();

    // Aim at the star itself. The star is placed left of frame by shifting the
    // *projection* instead (see the view-offset effect above), which is what
    // lets the orbit pivot stay exactly on it.
    const toTarget = starPoint
      ? starPoint.clone()
      : (frameAllRef.current ? ALL_TARGET : OVERVIEW_TARGET).clone();

    flyTo(toPosition, toTarget);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusKey, camera, flyTo]);

  useFrame((_state, raw) => {
    /*
     * > [!CAUTION]
     * > **Clamp before integrating.** Neither r3f nor three bounds `delta` — it
     * > is wall-clock time since the last frame, so a single stalled frame
     * > advances an eased move by however long the stall was. Against a 1.5 s
     * > cubic ease-out that is not a stutter, it is a teleport: a 300 ms stall
     * > yields `1 − (1 − 0.2)³ ≈ 49%` of the move in one frame, and an ease-out
     * > spends its distance early, so the camera visibly lurches half way and
     * > then glides the rest.
     * >
     * > That was the "focused star lingers, then jumps" report. Its cause is
     * > fixed elsewhere — the shared canvas is no longer torn down and rebuilt
     * > on routes without a constellation (`SkyBackdrop`), which is what
     * > produced the stall — but stalls have other sources this cannot fix:
     * > a backgrounded window, a GC pause, a driver hiccup. So the integration
     * > is bounded regardless of who stalled it.
     *
     * Two frames' worth at 60fps: long enough to absorb ordinary jitter without
     * slowing the move, short enough that nothing perceptible survives it.
     */
    const delta = Math.min(raw, MAX_FRAME_SECONDS);

    /*
     * The framing bias, advanced **independently of the flight**. It shares the
     * flight's curve and duration so the two arrive together, but not its ref:
     * `pan()` nulls `flight.current` outright so a press can supersede a move,
     * and `recenter()` starts a flight with no focus change at all. A bias
     * riding on that ref would be stranded mid-ease by either, with nothing
     * left able to finish it.
     */
    const bias = biasMove.current;
    if (bias) {
      bias.elapsed += delta;
      const bt = Math.min(1, bias.elapsed / FLIGHT_SECONDS);
      const beased = 1 - (1 - bt) ** 3; // cubic ease-out, as below
      applyFrameBias(bias.from + (bias.to - bias.from) * beased);
      if (bt >= 1) biasMove.current = null;
    }

    const move = flight.current;
    if (!move) return;

    move.elapsed += delta;
    const t = Math.min(1, move.elapsed / FLIGHT_SECONDS);
    const eased = 1 - (1 - t) ** 3; // cubic ease-out

    camera.position.lerpVectors(move.fromPosition, move.toPosition, eased);
    target.current.lerpVectors(move.fromTarget, move.toTarget, eased);
    camera.lookAt(target.current);

    if (t >= 1) {
      flight.current = null;
      // Hand the orbit controls the target we arrived at, so re-enabling them
      // doesn't snap the view back to the origin. On a focused arrival that
      // target *is* the star, which is what makes the orbit pivot on it.
      const orbit = controlsRef.current as unknown as {
        target?: THREE.Vector3;
        update?: () => void;
      } | null;
      orbit?.target?.copy(target.current);
      orbit?.update?.();
      setFlying(false);
    }
  });

  return null;
}

/**
 * The orbit controls, permanent for the same reason the rig is.
 *
 * drei builds a **fresh** `OrbitControls` on every mount, whose `target` starts
 * at the origin, and `update()` ends in an unconditional `lookAt(target)` driven
 * from a `useFrame` at priority −1 — ahead of the rig's own frame. Mounted per
 * view, that meant every arrival got one frame in which the camera was re-aimed
 * at (0, 0, 0): harmless while arrivals were snapped to `OVERVIEW_TARGET`, which
 * *is* the origin, and a visible whip once they were not. Mounted once, there is
 * no fresh instance and no reset pivot, ever.
 */
export function SceneControls() {
  const { focusedId, docksPanel, interactive } = useSceneIntent();
  const flying = useFlying();

  return (
    <OrbitControls
      makeDefault
      // Pan along the screen plane rather than the ground plane: the scene
      // is a sky with no floor, so "up" means up the screen.
      screenSpacePanning
      minDistance={1.5}
      maxDistance={40}
      // Off while an eased move owns the camera — otherwise drei's per-frame
      // `update()` fights the lerp — and off entirely where the sky is a
      // backdrop rather than an instrument (the guided session steps).
      enabled={interactive && !flying}
      // **Focused is orbit-only — but only where a panel docks.** Arrival
      // composes a frame: the star biased off-centre at a fixed distance,
      // panel docked beside it. Orbiting turns the view around that star and
      // preserves the composition; panning and zooming exist only to break
      // it — sliding the star back under the sidebar, or pushing it out of
      // the frame the panel was placed against. So the two gestures that
      // can't help are not offered there.
      //
      // A view that docks nothing (`docksPanel={false}` — the Dashboard) has
      // no composition to protect, so it keeps the full control set even if
      // a selection is somehow live.
      enablePan={focusedId === null || !docksPanel}
      enableZoom={focusedId === null || !docksPanel}
      mouseButtons={{
        LEFT: THREE.MOUSE.ROTATE,
        MIDDLE: THREE.MOUSE.DOLLY,
        RIGHT: THREE.MOUSE.PAN,
      }}
      touches={{ ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN }}
    />
  );
}

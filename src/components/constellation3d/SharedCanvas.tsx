import { Canvas } from "@react-three/fiber";
import {
  createContext,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { SceneBackdrop } from "./Backdrop";
import { CameraRig, SceneControls } from "./CameraRig";

/**
 * The shared constellation stage: **one** WebGL canvas for the whole app.
 *
 * Every view that shows a constellation — the Dashboard's full-bleed sky,
 * Debug Mode, Mission Control — used to mount its own `<Canvas>`, which meant
 * every navigation between them created a fresh WebGL context, recompiled
 * every shader, and regenerated the whole deep-sky backdrop, just to draw the
 * same instrument somewhere else. This module mounts the canvas once, at the
 * app shell, and the views take it in turns.
 *
 * The handoff is physical rather than geometric: the stage owns a plain host
 * `<div>` containing the canvas, and the active view *adopts* it into its own
 * tracking element (`appendChild` — a reparented `<canvas>` keeps its GL
 * context and its listeners). That sidesteps every hard problem a
 * fixed-position canvas would have — scroll tracking, z-index against docked
 * panels, the edge-fade mask — because the canvas is simply *in* the page,
 * wherever the view put it, exactly as it was when each view owned one.
 *
 * Rules of the stage:
 *  - **Last attach wins.** Route transitions overlap mounts (`AnimatePresence`
 *    keeps the outgoing page alive while it exits), so an incoming view steals
 *    the stage and the outgoing view's release becomes a no-op. The sky
 *    jumping to the incoming page instantly is the point — between the two
 *    rig views it reads as the sky holding still while the chrome changes.
 *  - **The backdrop lives here, not in the views.** It is deterministic
 *    scenery, identical in every view, and by mounting it beside (not inside)
 *    the swapped content its point-field geometry, nebula textures and
 *    shaders survive every navigation.
 *  - **The release path exists but is not meant to run.** With no view attached
 *    the host div comes out of the document and the frameloop parks
 *    (`frameloop="never"`), which was once a saving on pages without a
 *    constellation. Every route now mounts one (`SkyBackdrop`), so the only
 *    release that ever fires is the no-op kind above, and that is deliberate:
 *
 *    > [!CAUTION]
 *    > A **genuine** release is expensive in a way that is invisible until it
 *    > isn't. It unmounts the whole scene graph, which disposes every material,
 *    > which drops three's refcounted shader programs to zero and destroys them
 *    > — so coming back recompiles the star shader, the corona, and
 *    > `MeshStandardMaterial`'s entire physical chain, blocking the first frame.
 *    > It also regenerates ~1.2 MB of sphere geometry and a drei React root per
 *    > nameplate. Worse, r3f gates its configure/render on a measured width, a
 *    > detached host measures 0, and the ResizeObserver that reports otherwise
 *    > is debounced 50 ms — during which the canvas is blank and the frameloop
 *    > stays parked.
 *    >
 *    > The visible symptom was none of that directly. It was the *next* frame's
 *    > `delta` carrying the compile stall into whatever was mid-animation: a
 *    > 300 ms stall spends half of a 1.5 s cubic ease-out in one frame, which is
 *    > the camera "lingering, then jumping" that took five attempts to place.
 *    > `CameraRig` now clamps delta as a second line of defence, but the first
 *    > is simply never releasing.
 *
 *    The canvas is still created lazily on first use, so the app never builds a
 *    GL context it hasn't needed yet.
 */

/** What a view holds while it owns the stage. Opaque outside this module. */
export interface StageToken {
  id: number;
}

interface StageSnapshot {
  /** The active view's scene graph, rendered inside the shared canvas. */
  content: ReactNode;
  /** Whether any view currently owns the stage — drives the frameloop. */
  attached: boolean;
  /** Once true, the canvas exists forever; false means never yet needed. */
  everAttached: boolean;
}

export class ConstellationStage {
  /** The movable home of the canvas. Styled once; adopted by tracking divs. */
  readonly host: HTMLDivElement;

  private current: StageToken | null = null;
  private nextId = 1;
  private snapshot: StageSnapshot = {
    content: null,
    attached: false,
    everAttached: false,
  };
  private listeners = new Set<() => void>();

  constructor() {
    this.host = document.createElement("div");
    this.host.style.position = "absolute";
    this.host.style.inset = "0";
  }

  /**
   * Adopt the stage into `container`, with the scene graph it should render.
   *
   * **`content` is not optional, and must not be deferred to `setContent`.**
   * Attaching with an empty stage produces a live canvas whose scene has no
   * `CameraRig` in it — so it renders the backdrop from whatever pose the
   * *previous* view left the shared camera in, for however many frames it takes
   * the content to arrive. What that looks like is the last view's close-up
   * lingering on screen and then snapping to the new view's framing; it reads
   * as a camera jump, and nothing inside the scene can fix it because the code
   * that places the camera is precisely the code that isn't mounted yet.
   *
   * Passing the content here collapses that to a single update, so the first
   * frame the canvas draws after re-attaching is already this view's.
   */
  acquire(container: HTMLElement, content: ReactNode): StageToken {
    const token: StageToken = { id: this.nextId++ };
    this.current = token;
    container.appendChild(this.host);
    this.update({ attached: true, everAttached: true, content });
    return token;
  }

  /** Render `content` inside the canvas — only honoured for the owner. */
  setContent(token: StageToken, content: ReactNode): void {
    if (this.current !== token) return;
    this.update({ content });
  }

  /** Give the stage up. A no-op unless `token` still owns it (see steal). */
  release(token: StageToken): void {
    if (this.current !== token) return;
    this.current = null;
    this.host.remove();
    this.update({ content: null, attached: false });
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): StageSnapshot => this.snapshot;

  private update(patch: Partial<StageSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    for (const listener of this.listeners) listener();
  }
}

const StageContext = createContext<ConstellationStage | null>(null);

export function useConstellationStage(): ConstellationStage {
  const stage = useContext(StageContext);
  if (!stage) {
    throw new Error(
      "constellation views must be used inside <ConstellationStageProvider>",
    );
  }
  return stage;
}

/**
 * A view's half of the handoff. Returns a ref callback for the tracking
 * element; while that element is mounted, the stage lives inside it and
 * renders `content`. Attach/steal/release are layout effects, so the canvas
 * has moved before the frame paints.
 */
export function useConstellationView(
  content: ReactNode,
): (el: HTMLDivElement | null) => void {
  const stage = useConstellationStage();
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const token = useRef<StageToken | null>(null);

  // The live content, so `acquire` below can attach *with* it. Read through a
  // ref rather than taken as a dependency: the acquire effect must fire on
  // gaining the container and nothing else, or every render would re-steal the
  // stage from itself.
  const contentRef = useRef(content);
  contentRef.current = content;

  useLayoutEffect(() => {
    if (!container) return;
    token.current = stage.acquire(container, contentRef.current);
    return () => {
      if (token.current) stage.release(token.current);
      token.current = null;
    };
  }, [stage, container]);

  // Every render, after the acquire above on the first one: the content
  // closes over the view's live props (nodes, focus callbacks), so it must be
  // re-tunnelled whenever the view renders.
  useLayoutEffect(() => {
    if (token.current) stage.setContent(token.current, content);
  });

  return setContainer;
}

/**
 * Fades the canvas (and the nameplates portalled into its wrapper) out over
 * its last few dozen pixels on every side. Two gradients intersected rather
 * than one radial: a radial mask would hollow out the corners of a wide
 * frame, and the fade must hug the rectangle the scene actually occupies.
 */
const EDGE_FADE_MASK = [
  "linear-gradient(to right, transparent, black 56px, black calc(100% - 56px), transparent)",
  "linear-gradient(to bottom, transparent, black 44px, black calc(100% - 44px), transparent)",
].join(", ");

/**
 * Mount once, above everything that might show a constellation. Renders the
 * children untouched plus the stage's canvas, portalled into the movable host.
 */
export function ConstellationStageProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [stage] = useState(() => new ConstellationStage());
  return (
    <StageContext.Provider value={stage}>
      {children}
      <StageCanvas stage={stage} />
    </StageContext.Provider>
  );
}

function StageCanvas({ stage }: { stage: ConstellationStage }) {
  const snapshot = useSyncExternalStore(stage.subscribe, stage.getSnapshot);

  // No view has ever wanted the stage — don't build a GL context on spec.
  if (!snapshot.everAttached) return null;

  return createPortal(
    <Canvas
      // The camera is shared across views; each view's CameraRig places it on
      // mount (Scene.tsx), so only the lens is configured here.
      camera={{ fov: 45 }}
      dpr={[1, 2]}
      // Parked, not unmounted, while no view owns the stage: the context and
      // every compiled program stay warm for the next attach.
      frameloop={snapshot.attached ? "always" : "never"}
      // Transparent, deliberately: the scene composites over the app's own
      // Void background and drifting 2D starfield, so the browser reads as a
      // window onto the app's sky rather than a separate framed tile. The
      // mask below fades the canvas out at its edges for the same reason —
      // in-scene backdrop stars must dissolve into the page, not hit a wall.
      gl={{ antialias: true, alpha: true }}
      style={{
        maskImage: EDGE_FADE_MASK,
        maskComposite: "intersect",
        WebkitMaskImage: EDGE_FADE_MASK,
        WebkitMaskComposite: "source-in",
      }}
    >
      {/* Permanent scenery: identical in every view, and expensive to build —
          seeded point fields and painted nebula textures. Living beside the
          swapped content, it survives every navigation. */}
      <SceneBackdrop />

      {/* **The camera and its controls are permanent too**, and for a stronger
          reason than cost. Mounted inside the swapped content, the camera was a
          baton — claimed, banked, restored — whose correctness depended on how
          mounts and unmounts interleaved across this portal, i.e. across two
          reconcilers. Four attempts to stop it snapping on a sidebar round trip
          each fixed something real and none fixed that, because each was a
          prediction about that interleaving. Here there is nothing to hand over:
          views declare a subject (`sceneIntent.ts`) and the camera reacts. */}
      <CameraRig />
      <SceneControls />

      {snapshot.content}
    </Canvas>,
    stage.host,
  );
}

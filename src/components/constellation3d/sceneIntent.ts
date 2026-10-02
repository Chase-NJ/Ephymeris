import { useSyncExternalStore } from "react";

import type { SceneNode } from "./Scene";

/**
 * What the active constellation view wants the shared camera to be doing.
 *
 * **The camera is not something a view owns.** There is one of it, mounted for
 * the app's lifetime beside the backdrop (`SharedCanvas.tsx`), and views only
 * ever *declare* a subject and a focus. This module is that declaration.
 *
 * > [!IMPORTANT]
 * > The design this replaced made the camera a baton passed between views, with
 * > a module-level holder, a banked in-flight move, and a pose saved on unmount
 * > and restored on mount. Its correctness condition was the **ordering of
 * > mounts and unmounts across two React roots** — the DOM tree and r3f's own,
 * > joined by a `useSyncExternalStore` and a portal. Four separate attempts to
 * > fix a camera that snapped on a sidebar round trip each corrected a real
 * > defect and none fixed that one, because every fix was a prediction about
 * > that ordering and the ordering is not something you can read off the source.
 * >
 * > A permanent rig has no ordering to get wrong. Keep it that way: if the
 * > camera ever needs to know something new, it belongs in this snapshot, not in
 * > a mount effect somewhere.
 *
 * Deliberately not React context: the rig lives inside the `Canvas` reconciler
 * and the views live outside it, so there is no shared provider between them —
 * the same reason `viewMemory` and `ConstellationStage` are module state.
 */

export interface SceneIntent {
  /**
   * Whether any view is currently showing the constellation.
   *
   * The rig's one arrival rule hangs off this going false → true. It cannot be
   * inferred from the rest of the snapshot: `focusKey` is `""` both before and
   * after an unfocused view attaches, so nothing else in here changes when a
   * view arrives at the overview-with-nothing-focused state it left in.
   */
  attached: boolean;
  /**
   * The focused star **and where it is**, as one primitive.
   *
   * A flight is triggered by a real change of destination, never by the identity
   * of the `nodes` array — that is rebuilt whenever the roster or health or
   * telemetry changes, at up to 20 Hz, and a camera that re-flew on array
   * identity would fight every orbit and pan the operator made. Empty string
   * means nothing is focused.
   */
  focusKey: string;
  focusedId: string | null;
  /**
   * Whether the active view docks a detail panel over the scene. Drives the
   * framing bias and the focused-state control restrictions, both of which exist
   * only to protect a frame composed against that panel.
   */
  docksPanel: boolean;
  /**
   * How far left of screen centre the focused star should sit, in px, so it
   * lands centred in the strip of sky the chrome leaves visible. Half the
   * difference between the right-docked chrome's width and the left chrome's
   * (`frameShift = (panelOuter − leftChrome) / 2`) — the views publish it from
   * their own panel geometry rather than the camera hardcoding one bias for
   * every panel width. Ignored unless a star is focused and `docksPanel`.
   */
  frameShift: number;
  /**
   * Whether the sky is an instrument or a backdrop.
   *
   * False on the guided session steps, which show the rig behind their frosted
   * panels so the flow reads as one continuous scene. There the constellation
   * still draws and still turns, but it offers nothing: no orbit, no zoom, no
   * pan pad, no clickable stars. A backdrop that moves when you drag it is a
   * control, and the operator is meant to be looking at the form.
   */
  interactive: boolean;
}

const EMPTY: SceneIntent = {
  attached: false,
  focusKey: "",
  focusedId: null,
  docksPanel: true,
  frameShift: 0,
  interactive: true,
};

let intent: SceneIntent = EMPTY;

/**
 * The live node list, held **outside** the snapshot on purpose.
 *
 * The rig reads it only when it starts a flight, to find where a star is. Put it
 * in the snapshot and every telemetry batch would re-render the rig for a value
 * no render of it ever displays.
 */
let nodes: SceneNode[] = [];

const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

/** Publish the active view's intent. A no-op when nothing actually changed, so a
 *  view may call it on every render. */
export function setSceneIntent(next: SceneIntent, liveNodes: SceneNode[]): void {
  nodes = liveNodes;
  if (
    intent.attached === next.attached &&
    intent.focusKey === next.focusKey &&
    intent.focusedId === next.focusedId &&
    intent.docksPanel === next.docksPanel &&
    intent.frameShift === next.frameShift &&
    intent.interactive === next.interactive
  ) {
    return;
  }
  intent = next;
  notify();
}

/** Stand down — no view is showing the constellation. */
export function clearSceneIntent(): void {
  if (!intent.attached) return;
  intent = { ...intent, attached: false };
  notify();
}

export function getSceneNodes(): SceneNode[] {
  return nodes;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): SceneIntent {
  return intent;
}

export function useSceneIntent(): SceneIntent {
  return useSyncExternalStore(subscribe, getSnapshot, () => EMPTY);
}

/**
 * The camera's answer back: whether an eased move currently owns it.
 *
 * The orbit controls have to stand down for exactly that window — drei drives
 * `controls.update()` every frame, which recomputes the camera from the
 * controls' own spherical and would fight the lerp — and they have to come back
 * on arrival, which is what lets a focused star still be orbited.
 *
 * A separate store from the intent above because it flows the other way, and
 * mixing the two would have the rig re-render on its own output.
 */
let flying = false;
const flyingListeners = new Set<() => void>();

export function setFlying(next: boolean): void {
  if (flying === next) return;
  flying = next;
  for (const listener of flyingListeners) listener();
}

function subscribeFlying(listener: () => void): () => void {
  flyingListeners.add(listener);
  return () => {
    flyingListeners.delete(listener);
  };
}

export function useFlying(): boolean {
  return useSyncExternalStore(
    subscribeFlying,
    () => flying,
    () => false,
  );
}

/**
 * Pan and recentre, as an imperative handle.
 *
 * Imperative rather than lifted state because the camera lives inside the
 * `Canvas` reconciler and the pan pad lives outside it: passing target
 * coordinates down as props would make every press a React render of the whole
 * scene, for a value only three.js ever reads.
 */
export interface ViewApi {
  /** Pan by a fraction of the visible frame; +x right, +y up. */
  pan: (dx: number, dy: number) => void;
  /** Return to the pulled-back overview on the same eased move as a focus. */
  recenter: () => void;
}

let viewApi: ViewApi | null = null;

export function setViewApi(api: ViewApi | null): void {
  viewApi = api;
}

export function panView(dx: number, dy: number): void {
  viewApi?.pan(dx, dy);
}

export function recenterView(): void {
  viewApi?.recenter();
}

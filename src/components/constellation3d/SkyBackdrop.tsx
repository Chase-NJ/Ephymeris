import { DebugConstellation } from "@/components/debug/DebugConstellation";

/**
 * The rig's sky, as scenery — behind every route that isn't browsing it.
 *
 * > [!IMPORTANT]
 * > **Every route mounts a constellation, and that is a correctness requirement,
 * > not a look.** `ConstellationStage.release()` pulls the shared canvas host out
 * > of the document, parks the frameloop and unmounts the whole scene graph, and
 * > it only ever fires on a route that mounts *no* constellation — between two
 * > sky routes the incoming view steals the stage first and the outgoing release
 * > is a no-op. So a round trip through a bare route was the one path that paid
 * > for a full teardown and rebuild:
 * >
 * > - **~50 ms of blank canvas.** r3f gates its configure/render on a measured
 * >   width, a detached host measures 0, and the ResizeObserver that reports the
 * >   new size is debounced 50 ms. `frameloop` is not restored until then either.
 * > - **A GLSL recompile on the first frame back.** three refcounts programs, so
 * >   disposing every star at once destroys them; `ShaderMaterial` also drops its
 * >   shader-cache entry, so the next mount gets a new cache key. The link stall
 * >   lands on the first rendered frame.
 * > - **~1.2 MB of sphere geometry regenerated**, ~30–80 materials, and one drei
 * >   React root per nameplate and crew tag.
 * >
 * > The visible symptom was not the blank gap but what came *after* it: frame 2's
 * > `delta` carries the compile stall, and the camera flight integrates against a
 * > 1.5 s cubic ease-out, so a 300 ms stall consumes half the move in a single
 * > frame. That is the "focused star lingers, then jumps" this removes — by
 * > making the teardown unreachable rather than merely cheaper.
 * >
 * > If a new route ever needs a plain background, give it this at `opacity: 0`
 * > rather than omitting it.
 *
 * Inert by construction: `interactive={false}` stands the orbit controls down and
 * marks every star inactive, so there is no hover reticle, no click that goes
 * nowhere, and no pan pad over a scene that does not pan.
 */
export function SkyBackdrop({ opacity = 1 }: { opacity?: number }) {
  return (
    /*
     * **Must not sit inside the route's entrance animation.** The shared canvas
     * physically lives in this element, so a view-level opacity animation fades
     * the constellation with the chrome — and since every route now shows the
     * same sky, that made it blink out and back on every arrival. Chrome
     * crossfades, sky holds still.
     */
    <div className="absolute inset-0" style={{ opacity }}>
      <DebugConstellation
        selected={null}
        docksPanel={false}
        interactive={false}
        onSelect={NO_SELECTION}
      />
    </div>
  );
}

/** Stable identity, so the scene isn't handed a new callback every render. */
const NO_SELECTION = (): void => {};

/**
 * How far the sky is turned down behind a screen that is mostly data.
 *
 * `dashboard.md` §2.5: ambient motion must never compete with live data
 * collection. A drifting nebula behind a learning curve is exactly that, so
 * Analytics and the cohort editor keep the sky as texture rather than as
 * subject — present enough that the app is one continuous scene, faint enough
 * that nothing moves under a chart the operator is reading.
 */
export const DENSE_SKY_OPACITY = 0.35;

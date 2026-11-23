import { useEffect, useRef, useState } from "react";

import { useIntanStatus, useIntanStore } from "./context";
import { FiringModel, quantile } from "./firing";
import type { ProbeMap } from "./types";
import { useRecordingDefaults } from "@/features/settings/useRecordingDefaults";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

import { ProbeMapView } from "./ProbeMapView";

/** Latency samples kept for the footer's p95: a few seconds of batches. */
const SAMPLES_KEPT = 150;

/**
 * One recorded box's probe, each site flashing as it spikes
 * (`RECORDING.md#live-firing-map`).
 *
 * React draws the probe ONCE (`ProbeMapView`); after that, one animation
 * frame loop sets each site's fill straight on the DOM from `FiringModel`.
 * `intan.spikes` batches never become React state — at 30 a second per box,
 * re-rendering on each would be exactly the clunkiness this replaces.
 *
 * The footer counts the sites active since the map opened, judged as a
 * stored run is (`RECORDING.md#active-site-yield`), then says how live it is:
 * the sidecar's measured lag from RHX, the lag from the sidecar to the frame
 * that drew it, and the frame rate.
 */
export function LiveProbeMap({ box, className = "" }: { box: number; className?: string }) {
  const intan = useIntanStatus();
  const store = useIntanStore();
  const mine = intan.recording?.boxes.find((b) => b.box === box) ?? null;
  const map = useBoxProbeMap(box, mine?.probeMap ?? null);
  const { defaults } = useRecordingDefaults();
  const activeSiteHz = defaults.activeSiteHz;
  // Read by the frame loop, so editing it re-judges without restarting the loop
  // (which would throw away every count so far).
  const activeHzRef = useRef(activeSiteHz);
  activeHzRef.current = activeSiteHz;
  const host = useRef<HTMLDivElement>(null);
  const footer = useRef<HTMLSpanElement>(null);
  // Keyed by content: every status snapshot is a new array, and restarting the
  // loop on each would throw away the rate history.
  const channelKey = mine?.channels.join(",") ?? "";

  useEffect(() => {
    if (!channelKey || !map) return;
    const channels = channelKey.split(",");
    const model = new FiringModel(channels);
    const rhxLags: number[] = [];
    const appLags: number[] = [];
    let unpainted: number[] = [];
    const keep = (into: number[], value: number) => {
      into.push(value);
      if (into.length > SAMPLES_KEPT) into.shift();
    };
    const off = store.onSpikes(box, (batch) => {
      model.add(batch.counts, performance.now());
      if (batch.lagMs !== null) keep(rhxLags, batch.lagMs);
      unpainted.push(batch.sentAt);
    });

    let svg: SVGSVGElement | null = null;
    let sites: (Element | null)[] = [];
    let frames = 0;
    let since = performance.now();
    let raf = 0;
    const frame = () => {
      const now = performance.now();
      model.advance(now);
      // The SVG is replaced when the probe is re-fitted (a resize): re-find the sites then.
      const current = host.current?.querySelector("svg") ?? null;
      if (current !== svg) {
        svg = current;
        sites = channels.map((c) => svg?.querySelector(`[data-channel="${c}"]`) ?? null);
      }
      for (let i = 0; i < sites.length; i++) {
        sites[i]?.setAttribute("fill-opacity", (0.08 + 0.92 * model.strength(i)).toFixed(3));
      }
      if (unpainted.length > 0) {
        const wall = Date.now();
        for (const sent of unpainted) keep(appLags, wall - sent);
        unpainted = [];
      }
      frames += 1;
      if (now - since >= 1000) {
        const fps = (frames * 1000) / (now - since);
        frames = 0;
        since = now;
        if (footer.current) {
          const active = model.activeCount(activeHzRef.current, now);
          const yieldText = active === null ? "counting active sites…" : `${active}/${channels.length} active`;
          footer.current.textContent = `${yieldText} · ${describe(rhxLags, appLags, fps)}`;
        }
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      off();
    };
  }, [store, box, channelKey, map]);

  if (!mine) return null;
  const first = mine.channels[0];
  const last = mine.channels[mine.channels.length - 1];
  const wiring = (
    <div className="font-mono text-[10px] text-static">
      port {mine.port} · DIN {mine.digitalIn}
      {first ? ` · ${first}${last && last !== first ? `…${last}` : ""}` : ""}
    </div>
  );
  if (!mine.probeMap) {
    return (
      <div className="mt-3 border-t border-halo pt-2.5">
        {wiring}
        <p className="font-mono text-[10px] text-static">No probe map was added for box {box}.</p>
      </div>
    );
  }
  return (
    <div className={`flex flex-col gap-1 border-t border-halo pt-2.5 ${className}`}>
      {wiring}
      <div ref={host} className="relative min-h-0 flex-1">
        {map && (
          <ProbeMapView map={map} live channels={mine.channels} className="absolute inset-0" />
        )}
      </div>
      <span
        ref={footer}
        className="font-mono text-[10px] text-static"
        title={`Active: a mean of at least ${activeSiteHz} Hz since this map opened`}
      >
        {intan.liveStreams ? "waiting for spikes…" : "live data unavailable — RHX's data sockets did not open"}
      </span>
    </div>
  );
}

function describe(rhxLags: number[], appLags: number[], fps: number): string {
  const ms = (v: number | null) => (v === null ? "–" : `${Math.round(v)} ms`);
  return `RHX→app ${ms(quantile(rhxLags, 0.95))} · app→screen ${ms(quantile(appLags, 0.95))} (p95) · ${Math.round(fps)} fps`;
}

/** The probe map parsed at the Record step for this box, fetched once per recording. */
function useBoxProbeMap(box: number, file: string | null): ProbeMap | null {
  const { client, status } = useSidecar();
  const [map, setMap] = useState<ProbeMap | null>(null);
  useEffect(() => {
    if (status !== "connected" || !file) {
      setMap(null);
      return;
    }
    let cancelled = false;
    void client
      .call(CMD.INTAN_PROBE_MAP, { box })
      .then((reply) => !cancelled && setMap((reply.probeMap as ProbeMap | null) ?? null))
      .catch(() => !cancelled && setMap(null));
    return () => {
      cancelled = true;
    };
  }, [client, status, box, file]);
  return map;
}

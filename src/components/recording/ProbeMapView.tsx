import { useLayoutEffect, useMemo, useRef, useState } from "react";

import { fitProbeMap } from "@/lib/intan/probeMath";
import type { ProbeMap } from "@/lib/intan/types";

/**
 * One page of an Intan probe map, drawn from the JSON the sidecar parsed.
 *
 * Shared by the recording setup's preview (the geometry alone, so the
 * operator can see they picked the right file) and Mission Control's live
 * firing map (`LiveProbeMap`), which draws this once and then sets each
 * site's fill itself, every frame, by its `data-channel`.
 *
 * SVG, not canvas: a probe is tens to a few hundred sites, and changing one
 * attribute per site per frame costs well under a millisecond
 * (`RECORDING.md#live-firing-map`).
 *
 * THE FILE'S COLOURS ARE IGNORED, deliberately. A probe map carries its own
 * background, outline and text colours, chosen for RHX's UI. Honouring them
 * would put an arbitrary palette in the middle of the app's six tokens; the
 * geometry is the information, and it is drawn in ours.
 */
export function ProbeMapView({
  map,
  page = 0,
  channels,
  live = false,
  className = "",
}: {
  map: ProbeMap;
  page?: number;
  /** The channels this box actually records; others are drawn hollow. */
  channels?: readonly string[] | undefined;
  /** Recorded sites start dim rather than half-lit: their fill is the caller's. */
  live?: boolean;
  className?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useLayoutEffect(() => {
    const el = host.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const { width, height } = entry.contentRect;
      setSize({ width: Math.floor(width), height: Math.floor(height) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const current = map.pages[Math.min(page, map.pages.length - 1)];
  const fit = useMemo(
    () => (current && size.width > 0 ? fitProbeMap(current, size.width, size.height, 18) : null),
    [current, size.width, size.height],
  );
  const recorded = useMemo(() => (channels ? new Set(channels) : null), [channels]);

  // Positioning is the caller's: the live map passes `absolute inset-0`,
  // and a `relative` here would win over it (Tailwind emits `.relative` after
  // `.absolute`), leaving a host with no height and a map that never draws.
  return (
    <div ref={host} className={`min-h-0 overflow-hidden ${className}`}>
      {current && fit && (
        <svg width={size.width} height={size.height} className="block">
          {current.lines.map((line, i) => (
            <line
              key={i}
              x1={fit.toX(line.x1)}
              y1={fit.toY(line.y1)}
              x2={fit.toX(line.x2)}
              y2={fit.toY(line.y2)}
              stroke="var(--color-halo)"
              strokeWidth={1}
            />
          ))}
          {current.ports.flatMap((port) =>
            port.sites.map((site) => {
              const isRecorded = recorded === null || recorded.has(site.channel);
              // A floor on the drawn size: a 15 µm site on an 800 µm shank is
              // under two pixels, which can be neither seen nor clicked.
              const w = Math.max(site.width * fit.scale, 7);
              const h = Math.max(site.height * fit.scale, 7);
              const common = {
                // The live firing map finds its sites by this and sets their
                // fill itself, once a frame, outside React.
                "data-channel": isRecorded ? site.channel : undefined,
                fill: "var(--color-pulsar)",
                fillOpacity: !isRecorded ? 0 : live ? 0.08 : 0.35,
                stroke: "var(--color-static)",
                strokeOpacity: isRecorded ? 1 : 0.35,
                strokeWidth: 1,
              };
              const title = `${site.channel}${isRecorded ? "" : " · not recorded"}`;
              return site.shape === "ellipse" ? (
                <ellipse
                  key={site.channel}
                  cx={fit.toX(site.x)}
                  cy={fit.toY(site.y)}
                  rx={w / 2}
                  ry={h / 2}
                  {...common}
                >
                  <title>{title}</title>
                </ellipse>
              ) : (
                <rect
                  key={site.channel}
                  x={fit.toX(site.x) - w / 2}
                  y={fit.toY(site.y) - h / 2}
                  width={w}
                  height={h}
                  {...common}
                >
                  <title>{title}</title>
                </rect>
              );
            }),
          )}
          {current.texts.map((text, i) => (
            <text
              key={i}
              x={fit.toX(text.x)}
              y={fit.toY(text.y)}
              fill="var(--color-static)"
              fontSize={Math.max(9, Math.min(13, text.height * fit.scale))}
              fontFamily="var(--font-mono)"
              textAnchor={
                text.alignment.includes("Right")
                  ? "end"
                  : text.alignment.includes("Left")
                    ? "start"
                    : "middle"
              }
            >
              {text.text}
            </text>
          ))}
        </svg>
      )}
    </div>
  );
}

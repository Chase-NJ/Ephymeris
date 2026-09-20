import { useLayoutEffect, useMemo, useRef, useState } from "react";

import { fitProbeMap, rateStrength } from "@/lib/intan/scopeMath";
import type { ProbeMap } from "@/lib/intan/types";

/**
 * One page of an Intan probe map, drawn from the JSON the sidecar parsed.
 *
 * Shared by the recording setup's preview (no rates — the geometry alone, so
 * the operator can see they picked the right file) and the live probe window
 * (each site filled by how much it fired in the last second).
 *
 * SVG, not canvas: a probe is tens to a few hundred sites and the rates arrive
 * under twice a second, so there is nothing here a retained scene cannot keep
 * up with — and sites need to be hoverable and clickable, which SVG gives for
 * free. The SpikeScope is the canvas; this is not.
 *
 * THE FILE'S COLOURS ARE IGNORED, deliberately. A probe map carries its own
 * background, outline and text colours, chosen for RHX's UI. Honouring them
 * would put an arbitrary palette in the middle of the app's six tokens; the
 * geometry is the information, and it is drawn in ours.
 */
export function ProbeMapView({
  map,
  page = 0,
  rates,
  channels,
  selected,
  onSelect,
  className = "",
}: {
  map: ProbeMap;
  page?: number;
  /** Native channel → spikes in the last second. Omit for a static preview. */
  rates?: Record<string, number> | undefined;
  /** The channels this box actually records; others are drawn hollow. */
  channels?: readonly string[] | undefined;
  selected?: string | null | undefined;
  onSelect?: ((channel: string) => void) | undefined;
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
  const maxRate = rates ? Math.max(0, ...Object.values(rates)) : 0;

  return (
    <div ref={host} className={`relative min-h-0 ${className}`}>
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
              const live = recorded === null || recorded.has(site.channel);
              const strength = live && rates ? rateStrength(rates[site.channel] ?? 0, maxRate) : 0;
              const isSelected = selected === site.channel;
              // A floor on the drawn size: a 15 µm site on an 800 µm shank is
              // under two pixels, which can be neither seen nor clicked.
              const w = Math.max(site.width * fit.scale, 7);
              const h = Math.max(site.height * fit.scale, 7);
              const common = {
                fill: "var(--color-pulsar)",
                fillOpacity: rates ? 0.08 + 0.92 * strength : live ? 0.35 : 0,
                stroke: isSelected ? "var(--color-starlight)" : "var(--color-static)",
                strokeOpacity: live ? 1 : 0.35,
                strokeWidth: isSelected ? 1.75 : 1,
                className: onSelect && live ? "cursor-pointer" : undefined,
                onClick: onSelect && live ? () => onSelect(site.channel) : undefined,
              };
              const rate = rates?.[site.channel];
              const title = `${site.channel}${rate !== undefined ? ` · ${rate} Hz` : ""}${
                live ? "" : " · not recorded"
              }`;
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

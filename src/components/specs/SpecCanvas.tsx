import { useEffect, useMemo, useRef, useState } from "react";

import {
  LINK_OPACITY_DIM,
  LINK_STROKE,
  NODE_PRIMARY,
} from "@/components/chrome/constellationStyle";
import type { PlacedDiagnostics } from "@/lib/specs/diagnostics";
import {
  fitMono,
  graphSignature,
  layoutSpecGraph,
  GUTTER_X,
  LABEL_BUDGET,
  type SpecLayout,
} from "@/lib/specs/layout";
import { BAND_TITLES, sid, type Selection } from "@/lib/specs/selection";
import type { SpecGraph as SpecGraphData, SpecGraphNode } from "@/lib/specs/types";

/**
 * The compiled machine, as the Designer's primary surface — read top to
 * bottom, the way the listing reads.
 *
 * WHAT A CLICK MEANS HERE. Nothing on this canvas can be dragged, added or
 * rewired, and that is the design rather than an unfinished state: `topology`
 * is six knobs and a versioned template emits the nodes, so the set of
 * representable graphs is exactly the image of those templates (Task-Graph D1,
 * and TG103 rejects a spec that declares `nodes:` at all). A node canvas would
 * make invalid state machines representable and pull graph validation into the
 * UI, which is the ordering error the whole epoch model exists to forbid.
 *
 * So selection is the interaction. Clicking a node, an edge or a band lane
 * asks "what produced this?", and `lib/specs/selection.ts` answers with the
 * fields that did — which the Inspector then renders. THE LANE'S BLOCK GLYPH
 * IS A SELECTOR AND NOTHING MORE: it selects the lane and asks the Inspector
 * to reveal that band's structural blocks. It deliberately opens no menu here
 * — a menu on the canvas is the first step toward editing on the canvas.
 *
 * The shape vocabulary is unchanged from the readout this replaces — circle
 * DELAY, ring WAIT_ENTRY, square HOLD, open square WAIT_EXIT, bar PULSE,
 * hexagon TERMINAL, filled by band — because the primitives are the one
 * distinction a topology editor exists to show, and collapsing them onto the
 * derived graph's three node kinds would destroy it.
 */
export function SpecCanvas({
  graph,
  placed,
  selection,
  onSelect,
  onRevealStructure,
  lit,
  stale,
  bandReadouts,
}: {
  graph: SpecGraphData;
  placed: PlacedDiagnostics | null;
  selection: Selection;
  onSelect: (next: Selection) => void;
  /** The lane's block glyph: select the band AND ask the Inspector to show
   * that band's structural blocks. */
  onRevealStructure?: (band: number) => void;
  /** Node indices to light — the field the operator is hovering in the form. */
  lit: ReadonlySet<number>;
  /** The last graph that compiled, shown while the current document doesn't. */
  stale: boolean;
  /** One line per band, from the topology knobs — the lane headers' subtitle. */
  bandReadouts: Record<number, string>;
}) {
  const layout = useMemo(() => layoutSpecGraph(graph), [graph]);
  const signature = useMemo(() => graphSignature(graph), [graph]);
  const [hover, setHover] = useState<number | null>(null);
  const [frameSize, setFrameSize] = useState({ w: 0, h: 0 });
  const frame = useRef<HTMLDivElement | null>(null);
  const drag = useRef<{
    x: number;
    y: number;
    panX: number;
    panY: number;
    moved: boolean;
  } | null>(null);
  /** Set by a drag that actually moved, so the click closing it is swallowed. */
  const panned = useRef(false);

  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const observer = new ResizeObserver(() =>
      setFrameSize({ w: el.clientWidth, h: el.clientHeight }),
    );
    observer.observe(el);
    setFrameSize({ w: el.clientWidth, h: el.clientHeight });
    return () => observer.disconnect();
  }, []);

  /*
   * THE RESTING ZOOM FILLS THE PANE HORIZONTALLY, NOT ENTIRELY.
   *
   * A vertical task is a tall, narrow picture — 21 states over four bands is
   * roughly 1:1.3 with three or four lanes — so an SVG left to `meet` fits by
   * height and renders a thin unreadable column down the middle of a wide
   * pane. Scaling until the graph's width fills the frame instead makes the
   * primitives and their labels legible at rest, at the cost of having to pan
   * vertically, which is the trade every top-to-bottom flowchart makes.
   *
   * Capped at 3× so a two-state graph doesn't arrive absurdly magnified, and
   * floored at 1× so this never zooms *out* past what `meet` already fits.
   */
  const restingZoom = useMemo(() => {
    if (frameSize.w === 0 || frameSize.h === 0) return 1;
    const fitted = (frameSize.w * layout.height) / (layout.width * frameSize.h);
    return Math.min(3, Math.max(1, Number(fitted.toFixed(2))));
  }, [frameSize, layout.width, layout.height]);

  /*
   * At rest the graph starts at its TOP edge, not its middle.
   *
   * The scale transform is about the frame's centre, so magnifying by z leaves
   * the content's top edge at (h/2)(1 − z) — off-screen, and the operator
   * arrives somewhere in the middle of a trial. A trial reads top to bottom
   * (band 1 is engagement), so the beginning is where you start reading.
   */
  const restingPan = useMemo(
    () => ({ x: 0, y: (frameSize.h / 2) * (restingZoom - 1) }),
    [frameSize.h, restingZoom],
  );

  const [zoom, setZoom] = useState<number | null>(null);
  const [pan, setPan] = useState<{ x: number; y: number } | null>(null);

  /*
   * A new PICTURE is a reason to go home; a new compile is not.
   *
   * This keys on the graph's structural signature rather than on the payload's
   * identity: every 120 ms compile returns a fresh object, so keying on the
   * object meant that typing a duration snapped the operator back to the top
   * of a graph they were reading halfway down. Durations, labels and strobe
   * names change the picture's text, not its shape.
   */
  useEffect(() => {
    setZoom(null);
    setPan(null);
  }, [signature]);

  const effectiveZoom = zoom ?? restingZoom;
  const effectivePan = pan ?? restingPan;

  const hovered = hover !== null ? layout.nodes[hover] : null;
  const outEdges = useMemo(
    () => (hover === null ? [] : graph.edges.filter((e) => e.src === hover)),
    [graph, hover],
  );

  const selectedNode = selection?.kind === "node" ? selection.index : null;
  const selectedEdge = selection?.kind === "edge" ? selection.index : null;
  const selectedBand = selection?.kind === "band" ? selection.band : null;

  /* Panning is a plain pointer drag on the frame rather than a scroll
   * container: a scrollbar under the pane is most of what the operator would
   * see on a short graph.
   *
   * THE POINTER IS CAPTURED ONLY ONCE A DRAG REALLY STARTS. Capturing on
   * pointerdown retargets the whole gesture — including the click that ends it
   * — to the frame, so every click on a node arrived at the background handler
   * instead and selection silently did nothing. Past the threshold the capture
   * is what keeps a fast drag from escaping the pane; below it, the gesture is
   * a click and must reach whatever it was aimed at. */
  function onPointerDown(e: React.PointerEvent) {
    if (e.button !== 0) return;
    drag.current = {
      x: e.clientX,
      y: e.clientY,
      panX: effectivePan.x,
      panY: effectivePan.y,
      moved: false,
    };
  }
  function onPointerMove(e: React.PointerEvent) {
    const start = drag.current;
    if (!start) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    if (!start.moved) {
      if (Math.abs(dx) + Math.abs(dy) < DRAG_SLOP) return;
      start.moved = true;
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    }
    setPan({ x: start.panX + dx, y: start.panY + dy });
  }
  function onPointerUp(e: React.PointerEvent) {
    const start = drag.current;
    drag.current = null;
    if (start?.moved) {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
      // The click that closes a drag is not a click on the background.
      panned.current = true;
    }
  }

  /*
   * THE WHEEL PANS, IT DOES NOT ZOOM.
   *
   * The canvas fills the Designer route and the page behind it does not
   * scroll, so the old objection — a canvas that ate the wheel would trap the
   * scroll on the way past it — no longer applies here. What does apply is
   * that a tall graph is read by scrolling down it, and binding the wheel to
   * zoom would make the natural gesture the wrong one. The event is only
   * consumed when there is somewhere to go.
   */
  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const scaledHeight = layout.height * (zoom ?? restingZoom) * (frameSize.w / layout.width);
      if (scaledHeight <= frameSize.h) return;
      e.preventDefault();
      const base = pan ?? restingPan;
      setPan({ x: base.x, y: base.y - e.deltaY });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [layout.height, layout.width, zoom, restingZoom, pan, restingPan, frameSize]);

  const dimmed = (i: number) => lit.size > 0 && !lit.has(i);

  return (
    <div className="relative flex h-full flex-col">
      <div
        ref={frame}
        className="relative flex-1 cursor-grab overflow-hidden active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        // Clicking the background is how you get back to "nothing selected" —
        // otherwise the inspector is a mode with no exit.
        onClick={() => {
          if (panned.current) {
            panned.current = false;
            return;
          }
          onSelect(null);
        }}
      >
        <svg
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          className="h-full w-full"
          style={{
            transform: `translate(${effectivePan.x}px, ${effectivePan.y}px) scale(${effectiveZoom})`,
            transformOrigin: "center center",
            opacity: stale ? 0.45 : 1,
            transition: "opacity 180ms ease",
          }}
          role="img"
          aria-label="Compiled state machine"
        >
          <defs>
            <marker
              id="spec-arrow"
              viewBox="0 0 8 8"
              refX={7}
              refY={4}
              markerWidth={7}
              markerHeight={7}
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 8 4 L 0 8 z" fill={LINK_STROKE} opacity={0.55} />
            </marker>
          </defs>

          <BandLanes
            layout={layout}
            selectedBand={selectedBand}
            readouts={bandReadouts}
            counts={countByBand(graph)}
            onSelect={(band) => onSelect({ kind: "band", band })}
            onReveal={onRevealStructure}
          />

          {/* Edges under nodes. Returns are the faintest thing on the canvas
          and are never labelled — the derived graph's convention, kept. */}
          {layout.edges.map((laid) => {
            const { edge, from, to, isReturn, bow } = laid;
            const related =
              selectedNode !== null && (edge.src === selectedNode || edge.dst === selectedNode);
            const isSelected = selectedEdge === edge.index;
            const faded =
              (hover !== null && edge.src !== hover && edge.dst !== hover) ||
              (selectedNode !== null && !related);

            if (isReturn) {
              // Up the reserved right-hand rail: a return crosses the whole
              // picture, and routing it through the lanes would draw a line
              // over every state it does not concern.
              const rail = layout.returnRailX;
              return (
                <path
                  key={edge.index}
                  d={`M ${from.x + 9} ${from.y} C ${rail} ${from.y}, ${rail} ${to.y}, ${to.x} ${to.y - 10}`}
                  fill="none"
                  stroke={LINK_STROKE}
                  strokeWidth={0.7}
                  opacity={LINK_OPACITY_DIM}
                />
              );
            }

            const midY = (from.y + to.y) / 2;
            const d =
              from.x === to.x
                ? bow === 0
                  ? `M ${from.x} ${from.y + 9} L ${to.x} ${to.y - 11}`
                  : `M ${from.x} ${from.y + 9} C ${from.x + bow} ${midY}, ${to.x + bow} ${midY}, ${to.x} ${to.y - 11}`
                : `M ${from.x} ${from.y + 9} C ${from.x + bow} ${midY}, ${to.x + bow} ${midY}, ${to.x} ${to.y - 11}`;

            return (
              <g key={edge.index} opacity={faded ? 0.18 : 1}>
                {/* A 0.9-wide stroke is an unhittable target; this invisible
                twin is what the pointer actually finds. */}
                <path
                  d={d}
                  fill="none"
                  stroke="transparent"
                  strokeWidth={12}
                  className="cursor-pointer"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelect({ kind: "edge", index: edge.index });
                  }}
                />
                <path
                  d={d}
                  fill="none"
                  stroke={isSelected ? "var(--color-starlight)" : LINK_STROKE}
                  strokeWidth={isSelected ? 1.6 : 0.9}
                  opacity={isSelected ? 0.9 : 0.45}
                  markerEnd="url(#spec-arrow)"
                  pointerEvents="none"
                />
                {laid.label !== null && (
                  <text
                    x={laid.labelX}
                    y={laid.labelY}
                    textAnchor={laid.labelAnchor}
                    className="font-mono"
                    fontSize={7.5}
                    fill={isSelected ? "var(--color-starlight)" : "var(--color-static)"}
                    pointerEvents="none"
                  >
                    {fitMono(laid.label, LABEL_BUDGET - 14, 7.5)}
                    <title>{laid.label}</title>
                  </text>
                )}
              </g>
            );
          })}

          {layout.nodes.map(({ node, x, y }, i) => {
            const diags = placed?.byNode.get(sid(node.index));
            const isSelected = selectedNode === i;
            return (
              <g
                key={node.index}
                transform={`translate(${x}, ${y})`}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect({ kind: "node", index: i });
                }}
                className="cursor-pointer"
                opacity={dimmed(node.index) ? 0.3 : 1}
              >
                <circle r={17} fill="transparent" />
                {isSelected && (
                  <circle
                    r={13}
                    fill="none"
                    stroke="var(--color-starlight)"
                    strokeWidth={1.2}
                    opacity={0.8}
                  />
                )}
                <NodeShape node={node} flagged={Boolean(diags?.length)} />
                {/* Left-anchored BESIDE the node, not centred under it. A
                vertical flow gives every node its own row, so the label has a
                whole lane's width to itself — which is what makes the
                truncation budget generous enough to almost never bite. */}
                <text
                  x={13}
                  y={node.strobeName ? -1 : 3}
                  fontSize={8.5}
                  fill={
                    isSelected || hover === i
                      ? "var(--color-starlight)"
                      : "var(--color-static)"
                  }
                  pointerEvents="none"
                >
                  {fitMono(node.label, LABEL_BUDGET, 8.5)}
                  <title>{node.label}</title>
                </text>
                {node.strobeName && (
                  <text
                    x={13}
                    y={9}
                    className="font-mono"
                    fontSize={7}
                    fill="var(--color-static)"
                    opacity={0.7}
                    pointerEvents="none"
                  >
                    {fitMono(node.strobeName, LABEL_BUDGET, 7)}
                    <title>{node.strobeName}</title>
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {hovered && (
          <div className="pointer-events-none absolute top-2 right-2 w-[240px] rounded-sm border border-halo bg-void/90 px-2.5 py-2 font-mono text-[10px] leading-relaxed text-static">
            <div className="text-starlight">
              {sid(hovered.node.index)} {hovered.node.type}
              {"  "}
              <span className="text-static">{hovered.node.label}</span>
            </div>
            {hovered.node.durationId && (
              <div>
                {hovered.node.durationId} = {hovered.node.durationMs} ms
              </div>
            )}
            {hovered.node.watch.length > 0 && (
              <div>watches {hovered.node.watch.join(", ")}</div>
            )}
            {hovered.node.silentByDesign && <div>— silent by design (D4)</div>}
            {outEdges.map((e) => (
              <div key={e.index}>
                {e.trigger}
                {e.channel ? `(${e.channel})` : ""}
                {e.guard ? ` [${e.guard}]` : ""} → {sid(e.dst)}
                {e.effect ? `  ${e.effect}` : ""}
              </div>
            ))}
          </div>
        )}
      </div>

      <ZoomBar
        zoom={effectiveZoom}
        onZoom={setZoom}
        onReset={() => {
          setZoom(null);
          setPan(null);
        }}
      />
    </div>
  );
}

function countByBand(graph: SpecGraphData): Record<number, number> {
  const out: Record<number, number> = {};
  for (const node of graph.nodes) out[node.band] = (out[node.band] ?? 0) + 1;
  return out;
}

/**
 * The four epochs as full-width lanes, stacked down the page.
 *
 * This is where the band cards went. They were a row of four above the graph
 * restating what the graph's own rows already said; as lanes they are the same
 * information in the place it describes, and the header is the click target
 * for that band's knobs.
 *
 * THE HEADER TEXT LIVES IN A FIXED LEFT GUTTER, which is not a cosmetic
 * choice: SVG text does not wrap and does not clip, so a header drawn across
 * the lane simply ran over the next one. Given a column of its own it cannot,
 * and `fitMono` handles the rest.
 */
function BandLanes({
  layout,
  selectedBand,
  readouts,
  counts,
  onSelect,
  onReveal,
}: {
  layout: SpecLayout;
  selectedBand: number | null;
  readouts: Record<number, string>;
  counts: Record<number, number>;
  onSelect: (band: number) => void;
  onReveal?: ((band: number) => void) | undefined;
}) {
  return (
    <>
      {layout.bands.map((band, i) => {
        const next = layout.bands[i + 1];
        const y0 = band.y0;
        const y1 = next ? next.y0 : layout.height;
        const active = selectedBand === band.band;
        const n = counts[band.band] ?? 0;
        const title = `${band.band} · ${BAND_TITLES[band.band]?.toLowerCase() ?? band.label}`;
        // Three short lines rather than one long one. The gutter is ~110px of
        // usable width; "10 states · commitment hold on" is 30 characters and
        // truncated to nonsense on one line, while its two halves each fit.
        const count = `${n} state${n === 1 ? "" : "s"}`;
        const readout = readouts[band.band] ?? "";
        return (
          <g
            key={band.band}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(band.band);
            }}
            className="cursor-pointer"
          >
            <rect
              x={0}
              y={y0}
              width={layout.width}
              height={Math.max(0, y1 - y0)}
              fill={active ? "var(--color-halo)" : "transparent"}
              opacity={active ? 0.35 : 1}
            />
            {i > 0 && (
              <line
                x1={0}
                y1={y0}
                x2={layout.width}
                y2={y0}
                stroke="var(--color-halo)"
                strokeWidth={1}
              />
            )}
            <text
              x={10}
              y={y0 + 13}
              className="font-mono"
              fontSize={9}
              fill={active ? "var(--color-starlight)" : "var(--color-static)"}
              opacity={0.9}
            >
              {/* Budgeted to stop short of the block glyph on the same line. */}
              {fitMono(title, GUTTER_X - 38, 9)}
              <title>{title}</title>
            </text>
            <text
              x={10}
              y={y0 + 23}
              className="font-mono"
              fontSize={7.5}
              fill="var(--color-static)"
              opacity={0.6}
            >
              {count}
            </text>
            {readout !== "" && (
              <text
                x={10}
                y={y0 + 32}
                className="font-mono"
                fontSize={7.5}
                fill="var(--color-static)"
                opacity={0.6}
              >
                {fitMono(readout, GUTTER_X - 16, 7.5)}
                <title>{readout}</title>
              </text>
            )}
            {onReveal && (
              /* A SELECTOR, NOT A MENU. It selects the lane and asks the
              Inspector to reveal that band's structural blocks — the same
              place the knobs already live. Opening a menu here would be the
              first step toward editing on the canvas. */
              <g
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(band.band);
                  onReveal(band.band);
                }}
                className="cursor-pointer"
              >
                <circle
                  cx={GUTTER_X - 18}
                  cy={y0 + 10}
                  r={7}
                  fill="transparent"
                  stroke="var(--color-halo)"
                  strokeWidth={0.8}
                />
                <text
                  x={GUTTER_X - 18}
                  y={y0 + 13}
                  textAnchor="middle"
                  fontSize={9}
                  fill="var(--color-static)"
                  pointerEvents="none"
                >
                  +<title>Structural blocks for this epoch</title>
                </text>
              </g>
            )}
          </g>
        );
      })}
    </>
  );
}

function ZoomBar({
  zoom,
  onZoom,
  onReset,
}: {
  zoom: number;
  onZoom: (next: number) => void;
  /** Back to the resting zoom AND the resting pan — one control, since a
   * half-reset (zoomed home but panned away) is not a state anyone wants. */
  onReset: () => void;
}) {
  return (
    <div className="flex shrink-0 items-center justify-end gap-2 px-2 py-1 font-mono text-[10px] text-static">
      <button
        type="button"
        className="px-1 transition-colors hover:text-starlight"
        onClick={() => onZoom(Math.max(0.5, Number((zoom - 0.25).toFixed(2))))}
      >
        −
      </button>
      <span className="w-9 text-center">{Math.round(zoom * 100)}%</span>
      <button
        type="button"
        className="px-1 transition-colors hover:text-starlight"
        onClick={() => onZoom(Math.min(3, Number((zoom + 0.25).toFixed(2))))}
      >
        +
      </button>
      <button
        type="button"
        className="px-1 transition-colors hover:text-starlight"
        onClick={onReset}
      >
        fit
      </button>
    </div>
  );
}

/**
 * Shape by primitive — the distinction the derived graph cannot draw:
 * circle DELAY · ring WAIT_ENTRY · square HOLD · open square WAIT_EXIT ·
 * bar PULSE · hexagon TERMINAL. Fill by band, so the rows read as the
 * listing's own sections.
 */
function NodeShape({ node, flagged }: { node: SpecGraphNode; flagged: boolean }) {
  const fill = BAND_FILL[node.band] ?? NODE_PRIMARY;
  const stroke = flagged ? "var(--color-status-error)" : "var(--color-halo)";
  const r = 7;
  switch (node.type) {
    case "WAIT_ENTRY":
      return (
        <>
          <circle r={r} fill="var(--color-void)" stroke={fill} strokeWidth={2} />
          <circle r={2.2} fill={fill} />
          {flagged && <circle r={r + 3} fill="none" stroke={stroke} strokeWidth={1} />}
        </>
      );
    case "HOLD":
      return (
        <rect x={-6.5} y={-6.5} width={13} height={13} rx={2} fill={fill} stroke={stroke} />
      );
    case "WAIT_EXIT":
      return (
        <rect
          x={-6.5}
          y={-6.5}
          width={13}
          height={13}
          rx={2}
          fill="var(--color-void)"
          stroke={fill}
          strokeWidth={2}
        />
      );
    case "PULSE":
      return (
        <rect x={-8} y={-3.5} width={16} height={7} rx={1.5} fill={fill} stroke={stroke} />
      );
    case "TERMINAL":
      return (
        <path
          d="M 0 -8 L 7 -4 L 7 4 L 0 8 L -7 4 L -7 -4 Z"
          fill={fill}
          stroke={stroke}
          strokeWidth={1}
        />
      );
    default: // DELAY
      return <circle r={r} fill={fill} stroke={stroke} strokeWidth={1} />;
  }
}

/** How far a pointer must travel before the gesture stops being a click. */
const DRAG_SLOP = 4;

const BAND_FILL: Record<number, string> = {
  1: "var(--color-pulsar)",
  2: "var(--color-series-2, #7ea8c8)",
  3: "var(--color-series-3, #c8b57e)",
  4: "var(--color-ion)",
};

import { motion } from "framer-motion";
import { useMemo, useRef, useState } from "react";

import { springSnappy } from "@/lib/motion";
import { kindColor, type RigDocument } from "@/lib/hardware/types";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The board, with a channel on each pin it uses.
 *
 * LAID OUT LIKE THE ACTUAL MEGA, not as an abstract grid, and that earns its
 * keep immediately: the double header runs 22/23, 24/25 … 52/53 in two rows,
 * so the odor lines — 22,24,26,28,30,32 on one row and 23,25,27,29,31,33 on the
 * other — are visibly two rows rather than a sequence. That interleaving is
 * what made `of_kind()` (which sorts by pin) return `odor_line_7` as the first
 * emitter, a trap `paradigms.py` carries a comment about. A picture of the
 * board is the shortest explanation of it.
 *
 * THE MAP SELECTS AND MOVES; THE RAIL EDITS. Same division as `SpecCanvas`
 * (`docs/specs.md` §5): clicking a pin selects its channel, dragging one moves
 * it to another pin, and everything else about a channel — its kind, its label,
 * its strobe slot — is a field in the inspector. Two surfaces for one field
 * eventually disagree.
 *
 * Drag is raw pointer events, ported from `ConstellationBoard`: snapping needs
 * viewBox-space hit-testing anyway, and pointer capture on the SVG keeps the
 * gesture alive outside the element.
 *
 * CLICK-TO-CARRY IS NOT A COURTESY. `CageAssignment.tsx` documents that HTML5
 * drag only works here because `dragDropEnabled: false` is set in
 * tauri.conf.json; pointer-event drag has its own hazards on a webview, and the
 * lab runs Windows where none of this has been exercised. A rig that cannot be
 * wired because a gesture does not land is a dead app, so every drag has a
 * click-click equivalent that uses no gesture at all.
 */

/** Rendering geometry, in viewBox units. */
const CELL = 13;
const GAP = 2.2;
const PITCH = CELL + GAP;
const SNAP_RADIUS = CELL * 0.9;

/**
 * Room for a rotated channel name.
 *
 * LABELS ARE VERTICAL, which is what a printed pinout does and for the same
 * reason: `odor_line_12` is twelve characters against a 13-unit cell, so
 * horizontal labels overlap their neighbours into an unreadable smear the
 * moment more than every third pin is used. Rotating removes the collision
 * entirely rather than managing it, and nothing has to be truncated — a
 * channel name is the operator's only description of what a pin will do.
 */
const LABEL_BAND = 30;
/** A left gutter for the header titles, so they never sit over a pin — the
 * same arrangement `SpecCanvas` uses for its band names. */
const GUTTER = 30;
/** Between the single header and the double one, as on the board. */
const SEP = 10;

/** Pins 0–21: the single header down one edge. */
const SINGLE = Array.from({ length: 22 }, (_, i) => i);
/** Pins 22–53: the 2×16 double header, in the pairs the board actually has. */
const DOUBLE_TOP = Array.from({ length: 16 }, (_, i) => 22 + i * 2);
const DOUBLE_BOTTOM = Array.from({ length: 16 }, (_, i) => 23 + i * 2);

const ROW1_Y = LABEL_BAND;
const ROW2_Y = ROW1_Y + PITCH + SEP + LABEL_BAND;
const ROW3_Y = ROW2_Y + PITCH;

const WIDTH = GUTTER + PITCH * 22;
const HEIGHT = ROW3_Y + PITCH + LABEL_BAND;

interface Placed {
  pin: number;
  x: number;
  y: number;
  /** Which side of the cell its label hangs off. The bottom row of the double
   * header labels downward; everything else labels upward. */
  below: boolean;
}

function geometry(): Map<number, Placed> {
  const map = new Map<number, Placed>();
  SINGLE.forEach((pin, i) =>
    map.set(pin, { pin, x: GUTTER + i * PITCH, y: ROW1_Y, below: false }),
  );
  DOUBLE_TOP.forEach((pin, i) =>
    map.set(pin, { pin, x: GUTTER + i * PITCH + PITCH * 3, y: ROW2_Y, below: false }),
  );
  DOUBLE_BOTTOM.forEach((pin, i) =>
    map.set(pin, { pin, x: GUTTER + i * PITCH + PITCH * 3, y: ROW3_Y, below: true }),
  );
  return map;
}

/**
 * How far a pointer must travel before this is a drag and not a click.
 *
 * WITHOUT IT, SELECTION DOES NOT WORK. Capturing the pointer on `pointerdown`
 * retargets the click that follows, so `onClick` never reaches the cell — the
 * exact bug `SpecCanvas` carries a comment about, reproduced here by porting
 * the half of `ConstellationBoard` that captures and not the half that waits.
 * Capture happens once the gesture is real; before that a press is a click.
 *
 * MEASURED IN SCREEN PIXELS, not viewBox units. The board scales to fill its
 * pane, so a viewBox threshold means a different physical distance at every
 * window size — and the first version of this used one, which made a plain
 * click read as a drag on a wide window and silently swallow the selection.
 */
const DRAG_SLOP_PX = 4;

interface DragState {
  channel: string;
  fromPin: number;
  x: number;
  y: number;
  /** Where the press landed IN SCREEN PIXELS, so the slop is a physical
   * distance rather than one that shrinks as the board grows. */
  originClientX: number;
  originClientY: number;
  /** False until the pointer has travelled past the slop. */
  live: boolean;
}

export function BoardMap({
  doc,
  selected,
  carried,
  onSelect,
  onCarry,
  onMove,
  problemPins,
}: {
  doc: RigDocument;
  selected: string | null;
  /** Click-to-carry: the channel picked up by click, awaiting a destination. */
  carried: string | null;
  onSelect: (channel: string | null) => void;
  onCarry: (channel: string | null) => void;
  onMove: (channel: string, pin: number) => void;
  /** Pins a diagnostic points at, lit so a message has somewhere to land. */
  problemPins: ReadonlySet<number>;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragged = useRef(false);
  const [drag, setDrag] = useState<DragState | null>(null);
  const reduceMotion = useReduceMotion();
  const pins = useMemo(geometry, []);

  /** pin → the channel on it. Two channels on one pin is TG228; the map shows
   * the later one and the diagnostic names both, rather than the map silently
   * choosing. */
  const occupant = useMemo(() => {
    const map = new Map<number, string>();
    for (const [name, entry] of Object.entries(doc.pins ?? {})) {
      if (typeof entry?.index === "number") map.set(entry.index, name);
    }
    return map;
  }, [doc.pins]);

  function toLocal(event: React.PointerEvent): { x: number; y: number } | null {
    const svg = svgRef.current;
    const ctm = svg?.getScreenCTM();
    if (!svg || !ctm) return null;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse());
    return { x: point.x, y: point.y };
  }

  function nearestPin(x: number, y: number): number | null {
    let best: number | null = null;
    let bestDistance = SNAP_RADIUS;
    for (const p of pins.values()) {
      const distance = Math.hypot(p.x + CELL / 2 - x, p.y + CELL / 2 - y);
      if (distance < bestDistance) {
        best = p.pin;
        bestDistance = distance;
      }
    }
    return best;
  }

  function beginDrag(event: React.PointerEvent, channel: string, fromPin: number) {
    // Clear on PRESS, not on the click that consumes it. A drag that ends
    // without a following click — released outside a cell, say — would
    // otherwise leave the flag set and swallow the next selection instead.
    dragged.current = false;
    const local = toLocal(event);
    if (!local) return;
    // NO CAPTURE YET — see DRAG_SLOP.
    setDrag({
      channel,
      fromPin,
      ...local,
      originClientX: event.clientX,
      originClientY: event.clientY,
      live: false,
    });
  }

  function moveDrag(event: React.PointerEvent) {
    if (!drag) return;
    const local = toLocal(event);
    if (!local) return;
    const travelled =
      Math.hypot(
        event.clientX - drag.originClientX,
        event.clientY - drag.originClientY,
      ) > DRAG_SLOP_PX;
    if (travelled && !drag.live) {
      // The gesture is real now, so take the pointer — this keeps it alive
      // outside the element, which is the half of capture that is wanted.
      (event.currentTarget as Element).setPointerCapture(event.pointerId);
    }
    setDrag({ ...drag, ...local, live: drag.live || travelled });
  }

  function endDrag() {
    if (!drag) return;
    if (drag.live) {
      const target = nearestPin(drag.x, drag.y);
      // ONE WRITE PER COMPLETED DRAG, never per move — each one costs a
      // preview round trip that recompiles every stored task.
      if (target !== null && target !== drag.fromPin) onMove(drag.channel, target);
      // Swallow the click that closes a drag, or releasing over the origin
      // would toggle the selection the drag just made.
      dragged.current = true;
    }
    setDrag(null);
  }

  const dropTarget = drag?.live ? nearestPin(drag.x, drag.y) : null;

  function activate(pin: number) {
    if (dragged.current) {
      dragged.current = false;
      return;
    }
    const here = occupant.get(pin);
    if (carried !== null) {
      // The click-click half of a drag: a carried channel lands wherever the
      // next click is, occupied or not — TG228 reports a collision rather than
      // the map refusing a move the operator may be part-way through.
      onMove(carried, pin);
      onCarry(null);
      return;
    }
    if (here) onSelect(here === selected ? null : here);
  }

  return (
    <svg
      ref={svgRef}
      viewBox={`-2 -2 ${WIDTH + 4} ${HEIGHT + 4}`}
      className="w-full select-none"
      style={{ touchAction: "none" }}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={`${doc.board ?? "board"} pin map`}
      onPointerMove={moveDrag}
      onPointerUp={endDrag}
      onPointerCancel={() => setDrag(null)}
    >
      {/* Titles in the left gutter, right-aligned to the pin columns, so they
          cannot land on a cell or on a label however long a name gets. */}
      <text
        x={GUTTER - 6}
        y={ROW1_Y + CELL / 2 + 1.6}
        textAnchor="end"
        className="fill-static font-mono"
        style={{ fontSize: 4.5 }}
      >
        0–21
      </text>
      <text
        x={GUTTER - 6}
        y={ROW2_Y + PITCH / 2 + 1.6}
        textAnchor="end"
        className="fill-static font-mono"
        style={{ fontSize: 4.5 }}
      >
        22–53
      </text>

      {[...pins.values()].map(({ pin, x, y }) => {
        const channel = occupant.get(pin);
        const entry = channel ? doc.channels?.[channel] : undefined;
        const isDragging = drag?.live === true && drag.channel === channel;
        const isTarget = dropTarget === pin && drag !== null;
        const isCarryTarget = carried !== null && !isDragging;
        const colour = kindColor(entry?.kind);
        const lit = problemPins.has(pin);

        return (
          <g key={pin}>
            <rect
              x={x}
              y={y}
              width={CELL}
              height={CELL}
              rx={2}
              fill={channel && !isDragging ? colour : "transparent"}
              fillOpacity={channel && !isDragging ? 0.22 : 1}
              stroke={
                lit
                  ? "var(--color-status-error)"
                  : isTarget
                    ? "var(--color-pulsar)"
                    : channel
                      ? colour
                      : "var(--color-halo)"
              }
              strokeWidth={isTarget || lit ? 1 : 0.5}
              className={
                channel || isCarryTarget ? "cursor-pointer" : "cursor-default"
              }
              onPointerDown={(e) => {
                if (channel && carried === null) beginDrag(e, channel, pin);
              }}
              onClick={() => activate(pin)}
            />
            <text
              x={x + CELL / 2}
              y={y + CELL / 2 + 1.4}
              textAnchor="middle"
              className="pointer-events-none fill-static font-mono"
              style={{ fontSize: 4.2 }}
            >
              {pin}
            </text>
            {channel && !isDragging && (
              <title>{`pin ${pin} — ${channel} (${entry?.kind ?? "?"})`}</title>
            )}
          </g>
        );
      })}

      {/* Labels ride above the cells rather than inside them: a channel name is
          the operator's only description of what a pin will do, and nothing
          here truncates one (the rule `UtilityControls` states). */}
      {[...pins.values()].map(({ pin, x, y, below }) => {
        const channel = occupant.get(pin);
        if (!channel || (drag?.live && drag.channel === channel)) return null;
        const entry = doc.channels?.[channel];
        // rotate(-90) sends +x upward, so `start` runs a label up off the top
        // of its cell and `end` runs it down off the bottom.
        const cx = x + CELL / 2;
        const cy = below ? y + CELL + 2.5 : y - 2.5;
        return (
          <text
            key={`l${pin}`}
            x={cx}
            y={cy}
            transform={`rotate(-90 ${cx} ${cy})`}
            textAnchor={below ? "end" : "start"}
            dominantBaseline="middle"
            className="pointer-events-none font-mono"
            style={{
              fontSize: 3.6,
              fill: kindColor(entry?.kind),
              opacity: selected === null || selected === channel ? 1 : 0.3,
              fontWeight: selected === channel ? 700 : 400,
            }}
          >
            {channel}
          </text>
        );
      })}

      {/* The dragged chip. A `motion.g` animating a TRANSFORM, never x/y
          attributes — springs on transforms are dependable across framer
          versions (the note ConstellationBoard carries). */}
      {drag?.live && (
        <motion.g
          animate={{ x: drag.x - CELL / 2, y: drag.y - CELL / 2 }}
          transition={reduceMotion ? { duration: 0 } : springSnappy}
          className="pointer-events-none"
        >
          <rect
            width={CELL}
            height={CELL}
            rx={2}
            fill={kindColor(doc.channels?.[drag.channel]?.kind)}
            fillOpacity={0.45}
            stroke={kindColor(doc.channels?.[drag.channel]?.kind)}
            strokeWidth={0.8}
          />
        </motion.g>
      )}
    </svg>
  );
}

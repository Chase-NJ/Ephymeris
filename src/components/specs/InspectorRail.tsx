import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The Inspector's column, with a drag handle on its left edge.
 *
 * Resizable because the rail holds two things with opposite appetites: a knob
 * with a two-word label, and a strobe picker whose options are twenty
 * characters of SCREAMING_SNAKE. Stacking the rows (see `rowDensity.ts`) is
 * what makes the narrow case legible at all; this is what lets an operator
 * who wants the long names to just have them.
 *
 * The width is persisted per machine rather than per spec — it is a property
 * of the display someone is sitting at, not of the task they opened.
 */
const KEY = "specs.inspectorWidth";
const MIN = 280;
const MAX = 560;
const DEFAULT = 360;

function stored(): number {
  if (typeof window === "undefined") return DEFAULT;
  const raw = window.localStorage.getItem(KEY);
  const parsed = raw === null ? NaN : Number(raw);
  return Number.isFinite(parsed) ? clamp(parsed) : DEFAULT;
}

function clamp(value: number): number {
  return Math.min(MAX, Math.max(MIN, Math.round(value)));
}

export function InspectorRail({ children }: { children: React.ReactNode }) {
  const [width, setWidth] = useState(stored);
  const drag = useRef<{ x: number; width: number } | null>(null);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0) return;
      e.preventDefault();
      drag.current = { x: e.clientX, width };
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    },
    [width],
  );

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const start = drag.current;
    if (!start) return;
    // The rail is on the RIGHT, so dragging its handle left widens it.
    setWidth(clamp(start.width - (e.clientX - start.x)));
  }, []);

  const onPointerUp = useCallback(
    (e: React.PointerEvent) => {
      if (!drag.current) return;
      drag.current = null;
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
      window.localStorage.setItem(KEY, String(width));
    },
    [width],
  );

  // A width stored by a wider window must not strand the rail off-screen on a
  // narrower one.
  useEffect(() => {
    const onResize = () => setWidth((w) => Math.min(w, Math.max(MIN, window.innerWidth - 420)));
    window.addEventListener("resize", onResize);
    onResize();
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return (
    <div className="flex shrink-0" style={{ width }}>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize the inspector"
        className="w-1 shrink-0 cursor-col-resize transition-colors hover:bg-pulsar/40"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

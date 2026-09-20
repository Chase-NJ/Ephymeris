import { useCallback, useLayoutEffect, useRef } from "react";

/**
 * A canvas that tracks its box and the display's pixel ratio, with a draw
 * function the caller can fire from OUTSIDE React.
 *
 * That last part is the point. A SpikeScope receives snippets five times a
 * second and a PSTH a raster of hundreds of points; routing either through
 * React state would reconcile a tree to change some pixels. So the data lives
 * in refs, `redraw()` is called straight from the socket handler, and React
 * only hears about the things that change what is *around* the canvas.
 *
 * This is the app's first canvas plotting — the session views are SVG because a
 * sparkline is forty points. It is fenced to the scope windows for that reason,
 * not adopted as a second house style.
 */
export type Draw = (ctx: CanvasRenderingContext2D, width: number, height: number) => void;

export function useCanvas(draw: Draw) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawRef = useRef(draw);
  drawRef.current = draw;
  const frame = useRef<number | null>(null);

  const redraw = useCallback(() => {
    if (frame.current !== null) return; // already queued for this frame
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (!canvas || !ctx) return;
      const ratio = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
      }
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, width, height);
      drawRef.current(ctx, width, height);
    });
  }, []);

  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(redraw);
    observer.observe(canvas);
    redraw();
    return () => {
      observer.disconnect();
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
    };
  }, [redraw]);

  return { canvasRef, redraw };
}

/** The theme's tokens, read once — a canvas cannot take `var(--…)`. */
let cached: Record<string, string> | null = null;

export function palette(): Record<"void" | "nebula" | "halo" | "pulsar" | "ion" | "starlight" | "static" | "warning", string> {
  if (!cached) {
    const style = getComputedStyle(document.documentElement);
    const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
    cached = {
      void: read("--color-void", "#0b0b10"),
      nebula: read("--color-nebula", "#16151f"),
      halo: read("--color-halo", "#2c2a3a"),
      pulsar: read("--color-pulsar", "#8b7ec8"),
      ion: read("--color-ion", "#7cc98f"),
      starlight: read("--color-starlight", "#edebf6"),
      static: read("--color-static", "#948fa8"),
      warning: read("--color-status-warning", "#cba23e"),
    };
  }
  return cached as ReturnType<typeof palette>;
}

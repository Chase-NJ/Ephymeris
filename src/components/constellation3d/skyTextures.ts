import * as THREE from "three";

import { mulberry32 } from "@/lib/prng";

/**
 * The backdrop's painted textures — every one a 2D canvas drawn once, seeded,
 * and uploaded as a `CanvasTexture`. Procedural because the app ships no image
 * assets; seeded so the same clouds and galaxies hang in the same sky forever
 * (`Backdrop.tsx`'s contract). Each painter takes its seed rather than sharing
 * a stream, so adding a texture cannot re-roll the ones after it.
 *
 * Everything is drawn on a transparent canvas with `lighter` compositing and
 * faded to nothing at the rim, so a quad has no visible edge however it is
 * scaled or rolled. Sizes are small (≤256²): these are soft shapes seen at a
 * distance, and a sharp texture would only cost upload and cache.
 */

function canvas(size: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  return [c, c.getContext("2d")!];
}

function upload(c: HTMLCanvasElement): THREE.CanvasTexture {
  const texture = new THREE.CanvasTexture(c);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** Fade a finished painting to nothing at the rim. */
function rimFade(ctx: CanvasRenderingContext2D, size: number, inner = 0.1) {
  ctx.globalCompositeOperation = "destination-in";
  const fade = ctx.createRadialGradient(
    size / 2, size / 2, size * inner,
    size / 2, size / 2, size * 0.5,
  );
  fade.addColorStop(0, "rgba(255,255,255,1)");
  fade.addColorStop(0.7, "rgba(255,255,255,0.6)");
  fade.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = fade;
  ctx.fillRect(0, 0, size, size);
}

/**
 * A nebula bank: clustered translucent blobs, a few bright filaments laid
 * across them, then the rim fade. The filaments are what the first version
 * lacked — without them a bank is fog, and fog does not read as a place where
 * stars are being made.
 */
export function makeNebulaTexture(seed: number, core: string, edge: string): THREE.CanvasTexture {
  const size = 256;
  const [c, ctx] = canvas(size);
  const rand = mulberry32(seed);

  ctx.globalCompositeOperation = "lighter";
  for (let i = 0; i < 30; i += 1) {
    const angle = rand() * Math.PI * 2;
    const spread = rand() ** 1.6 * size * 0.34;
    const x = size / 2 + Math.cos(angle) * spread;
    const y = size / 2 + Math.sin(angle) * spread * 0.7;
    const radius = size * (0.08 + rand() * 0.22) * (1 - spread / size);
    const g = ctx.createRadialGradient(x, y, 0, x, y, radius);
    const hue = rand() > 0.4 ? core : edge;
    g.addColorStop(0, `${hue}1a`);
    g.addColorStop(0.55, `${hue}0d`);
    g.addColorStop(1, `${hue}00`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
  }
  // Filaments: a handful of soft strokes along seeded curves.
  ctx.lineCap = "round";
  for (let i = 0; i < 6; i += 1) {
    const x0 = size * (0.25 + rand() * 0.5);
    const y0 = size * (0.25 + rand() * 0.5);
    const len = size * (0.15 + rand() * 0.25);
    const a = rand() * Math.PI * 2;
    const bend = (rand() - 0.5) * 60;
    ctx.strokeStyle = `${core}14`;
    ctx.lineWidth = 2 + rand() * 5;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.quadraticCurveTo(
      x0 + Math.cos(a + 0.5) * len * 0.5 + bend,
      y0 + Math.sin(a + 0.5) * len * 0.5,
      x0 + Math.cos(a) * len,
      y0 + Math.sin(a) * len,
    );
    ctx.stroke();
  }
  rimFade(ctx, size);
  return upload(c);
}

/**
 * A distant spiral galaxy, seen at some inclination: a bright bulge, two or
 * three log-spiral arms dotted with knots, and a faint disc haze.
 *
 * Drawn face-on and rolled/tilted by the mesh that carries it, so one texture
 * serves many sightings. `arms` and `tightness` are the two numbers that make
 * a galaxy look like a different galaxy.
 */
export function makeSpiralTexture(
  seed: number,
  tint: string,
  arms: number,
  tightness: number,
): THREE.CanvasTexture {
  const size = 256;
  const [c, ctx] = canvas(size);
  const rand = mulberry32(seed);
  const cx = size / 2;
  const cy = size / 2;

  ctx.globalCompositeOperation = "lighter";
  // Disc haze.
  const haze = ctx.createRadialGradient(cx, cy, 0, cx, cy, size * 0.42);
  haze.addColorStop(0, `${tint}22`);
  haze.addColorStop(0.5, `${tint}0c`);
  haze.addColorStop(1, `${tint}00`);
  ctx.fillStyle = haze;
  ctx.fillRect(0, 0, size, size);

  // Arms: knots along r = a·e^(b·θ).
  for (let arm = 0; arm < arms; arm += 1) {
    const offset = (arm / arms) * Math.PI * 2;
    for (let i = 0; i < 90; i += 1) {
      const theta = (i / 90) * Math.PI * 2.4;
      const r = 6 * Math.exp(tightness * theta);
      if (r > size * 0.46) break;
      const jitter = (rand() - 0.5) * 6;
      const x = cx + Math.cos(theta + offset) * (r + jitter);
      const y = cy + Math.sin(theta + offset) * (r + jitter);
      const knot = 2 + rand() * 4;
      const g = ctx.createRadialGradient(x, y, 0, x, y, knot);
      const bright = rand() > 0.8 ? "#f4f0ff" : tint;
      g.addColorStop(0, `${bright}55`);
      g.addColorStop(1, `${bright}00`);
      ctx.fillStyle = g;
      ctx.fillRect(x - knot, y - knot, knot * 2, knot * 2);
    }
  }

  // Bulge: warm and bright, on top.
  const bulge = ctx.createRadialGradient(cx, cy, 0, cx, cy, size * 0.11);
  bulge.addColorStop(0, "#fff3dcff");
  bulge.addColorStop(0.35, "#f1dcb8aa");
  bulge.addColorStop(1, "#f1dcb800");
  ctx.fillStyle = bulge;
  ctx.fillRect(0, 0, size, size);

  rimFade(ctx, size, 0.2);
  return upload(c);
}

/** An elliptical galaxy: a smooth, warm, featureless glow. The cheap one. */
export function makeEllipticalTexture(seed: number, tint: string): THREE.CanvasTexture {
  const size = 128;
  const [c, ctx] = canvas(size);
  const rand = mulberry32(seed);
  const cx = size / 2;
  const cy = size / 2;
  const squash = 0.55 + rand() * 0.4;
  ctx.globalCompositeOperation = "lighter";
  ctx.save();
  ctx.translate(cx, cy);
  ctx.scale(1, squash);
  const g = ctx.createRadialGradient(0, 0, 0, 0, 0, size * 0.45);
  g.addColorStop(0, "#fff0d8ee");
  g.addColorStop(0.2, `${tint}66`);
  g.addColorStop(0.6, `${tint}18`);
  g.addColorStop(1, `${tint}00`);
  ctx.fillStyle = g;
  ctx.fillRect(-size, -size, size * 2, size * 2);
  ctx.restore();
  return upload(c);
}

/** A small radial flash, shared by every supernova. */
export function makeFlashTexture(): THREE.CanvasTexture {
  const size = 64;
  const [c, ctx] = canvas(size);
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.25, "rgba(237,235,246,0.7)");
  g.addColorStop(1, "rgba(237,235,246,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  return upload(c);
}

/**
 * A streak: a bright head fading down a long tail along +x. One texture for
 * meteors and comets alike; the mesh decides the length and the pace.
 */
export function makeStreakTexture(): THREE.CanvasTexture {
  const w = 256;
  const h = 32;
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d")!;
  // Tail: brightest at the head (right), gone at the left.
  const tail = ctx.createLinearGradient(0, 0, w, 0);
  tail.addColorStop(0, "rgba(237,235,246,0)");
  tail.addColorStop(0.7, "rgba(237,235,246,0.35)");
  tail.addColorStop(1, "rgba(255,255,255,0.9)");
  ctx.fillStyle = tail;
  // Thin the tail vertically toward its end.
  for (let x = 0; x < w; x += 2) {
    const t = x / w;
    const thickness = h * (0.12 + 0.88 * t * t);
    ctx.fillRect(x, (h - thickness) / 2, 2, thickness);
  }
  // Soften the vertical edge.
  ctx.globalCompositeOperation = "destination-in";
  const soft = ctx.createLinearGradient(0, 0, 0, h);
  soft.addColorStop(0, "rgba(255,255,255,0)");
  soft.addColorStop(0.5, "rgba(255,255,255,1)");
  soft.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = soft;
  ctx.fillRect(0, 0, w, h);
  // The head.
  ctx.globalCompositeOperation = "lighter";
  const head = ctx.createRadialGradient(w - 10, h / 2, 0, w - 10, h / 2, 10);
  head.addColorStop(0, "rgba(255,255,255,1)");
  head.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = head;
  ctx.fillRect(w - 20, 0, 20, h);
  return upload(c);
}

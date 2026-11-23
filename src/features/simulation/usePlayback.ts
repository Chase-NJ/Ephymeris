/**
 * The playhead of a simulated session: a clock that runs at a chosen multiple of
 * the session's own, and can be put anywhere in it.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { Speed } from "./playback";

/**
 * A gap between frames longer than this is a window that was hidden, not time
 * to play through. Anything shorter is played in full, so a slow or throttled
 * display still runs at the chosen speed, in bigger steps.
 */
const LONGEST_FRAME_MS = 1000;

export interface Playback {
  atMs: number;
  playing: boolean;
  speed: Speed;
  ended: boolean;
  play: () => void;
  pause: () => void;
  seek: (ms: number) => void;
  setSpeed: (speed: Speed) => void;
}

/** `session` is whatever identifies the simulation: a new one rewinds and plays. */
export function usePlayback(durationMs: number, session: unknown): Playback {
  const at = useRef(0);
  const [atMs, setAtMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>(16);

  useEffect(() => {
    at.current = 0;
    setAtMs(0);
    setPlaying(durationMs > 0);
    // The duration belongs to the session; a new session is the only trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const elapsed = Math.min(LONGEST_FRAME_MS, now - last);
      last = now;
      at.current = Math.min(durationMs, at.current + elapsed * speed);
      setAtMs(at.current);
      if (at.current >= durationMs) setPlaying(false);
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, speed, durationMs]);

  const seek = useCallback(
    (ms: number) => {
      at.current = Math.max(0, Math.min(durationMs, ms));
      setAtMs(at.current);
    },
    [durationMs],
  );

  const play = useCallback(() => {
    if (at.current >= durationMs) {
      at.current = 0;
      setAtMs(0);
    }
    setPlaying(durationMs > 0);
  }, [durationMs]);

  const pause = useCallback(() => setPlaying(false), []);

  return { atMs, playing, speed, ended: durationMs > 0 && atMs >= durationMs, play, pause, seek, setSpeed };
}

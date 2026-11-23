import { Pause, Play, SkipBack, SkipForward, StepForward } from "lucide-react";
import { useRef } from "react";

import { Button, Segmented } from "@/components/common/controls";
import { clockLabel, SPEEDS, stepTrial, trialAt, type Speed, type TrialTick } from "./playback";
import type { Playback } from "./usePlayback";

const TONE_FILL: Record<TrialTick["tone"], string> = {
  earned: "var(--color-ion)",
  hold: "var(--color-status-warning)",
  wrong: "var(--color-status-error)",
  silent: "var(--color-static)",
  abort: "var(--color-halo)",
};

const TONE_LABEL: Array<[TrialTick["tone"], string]> = [
  ["earned", "earned"],
  ["hold", "hold failed"],
  ["wrong", "wrong"],
  ["silent", "no answer"],
  ["abort", "aborted"],
];

const SPEED_OPTIONS = SPEEDS.map((speed) => ({ value: String(speed), label: `${speed}×` }));

/** The ribbon is drawn in these units and stretched to its column. */
const RIBBON_W = 1000;
const RIBBON_H = 20;

/**
 * Play, pause, step and speed, over the session's timeline: one tick per trial
 * in its outcome's colour, a mark where each ramp row took over, and the
 * playhead. Press or drag anywhere on it to go there.
 */
export function Transport({
  playback,
  durationMs,
  ticks,
  stages,
}: {
  playback: Playback;
  durationMs: number;
  ticks: readonly TrialTick[];
  stages: ReadonlyArray<{ stage: number; atMs: number }>;
}) {
  const ribbon = useRef<HTMLDivElement>(null);
  const { atMs, playing, speed } = playback;
  const here = trialAt(ticks, atMs);
  const x = (ms: number) => (durationMs > 0 ? (ms / durationMs) * RIBBON_W : 0);

  const seekTo = (clientX: number) => {
    const box = ribbon.current?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    playback.seek(((clientX - box.left) / box.width) * durationMs);
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="flex items-center gap-1">
          <Button variant="outline" shape="icon" onClick={() => playback.seek(0)} title="Back to the start" label="Back to the start">
            <SkipBack size={13} strokeWidth={1.75} />
          </Button>
          <Button
            variant="outline"
            shape="icon"
            onClick={playing ? playback.pause : playback.play}
            title={playing ? "Pause" : "Play"}
            label={playing ? "Pause" : "Play"}
          >
            {playing ? <Pause size={13} strokeWidth={1.75} /> : <Play size={13} strokeWidth={1.75} />}
          </Button>
          <Button
            variant="outline"
            shape="icon"
            onClick={() => playback.seek(stepTrial(ticks, atMs, 1, durationMs))}
            title="To the next trial"
            label="To the next trial"
          >
            <StepForward size={13} strokeWidth={1.75} />
          </Button>
          <Button
            variant="outline"
            shape="icon"
            onClick={() => {
              playback.pause();
              playback.seek(durationMs);
            }}
            title="To the end of the session"
            label="To the end of the session"
          >
            <SkipForward size={13} strokeWidth={1.75} />
          </Button>
        </span>

        <span className="font-mono text-[11px] tabular-nums text-static">
          <span className="text-starlight">{clockLabel(atMs)}</span> / {clockLabel(durationMs)}
          <span className="mx-1.5 text-halo">·</span>
          {here < 0 ? "before the first trial" : `trial ${here + 1} of ${ticks.length}`}
        </span>

        <span className="ml-auto">
          <Segmented
            label="Playback speed"
            value={String(speed)}
            options={SPEED_OPTIONS}
            onChange={(next) => playback.setSpeed(Number(next) as Speed)}
          />
        </span>
      </div>

      <div
        ref={ribbon}
        role="slider"
        tabIndex={0}
        aria-label="Session timeline"
        aria-valuemin={0}
        aria-valuemax={Math.round(durationMs / 1000)}
        aria-valuenow={Math.round(atMs / 1000)}
        aria-valuetext={clockLabel(atMs)}
        onPointerDown={(e) => seekTo(e.clientX)}
        onPointerMove={(e) => {
          if (e.buttons & 1) seekTo(e.clientX);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") playback.seek(stepTrial(ticks, atMs, 1, durationMs));
          if (e.key === "ArrowLeft") playback.seek(stepTrial(ticks, atMs, -1, durationMs));
          if (e.key === " ") {
            e.preventDefault();
            if (playing) playback.pause();
            else playback.play();
          }
        }}
        className="cursor-pointer touch-none rounded-sm border border-halo/70 bg-void/40 focus:border-pulsar focus:outline-none"
      >
        <svg viewBox={`0 0 ${RIBBON_W} ${RIBBON_H}`} preserveAspectRatio="none" className="block h-6 w-full">
          {ticks.map((tick) => (
            <rect
              key={tick.index}
              x={x(tick.atMs)}
              y={3}
              width={Math.max(0.6, x(tick.endMs) - x(tick.atMs) - 0.4)}
              height={RIBBON_H - 6}
              fill={TONE_FILL[tick.tone]}
              opacity={tick.atMs <= atMs ? 0.9 : 0.28}
            />
          ))}
          {stages.map((mark) => (
            <line
              key={mark.stage}
              x1={x(mark.atMs)}
              x2={x(mark.atMs)}
              y1={0}
              y2={RIBBON_H}
              stroke="var(--color-starlight)"
              strokeWidth={1}
              strokeDasharray="2 2"
              vectorEffect="non-scaling-stroke"
            />
          ))}
          <line
            x1={x(atMs)}
            x2={x(atMs)}
            y1={0}
            y2={RIBBON_H}
            stroke="var(--color-pulsar)"
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-static">
        {TONE_LABEL.map(([tone, label]) => (
          <span key={tone} className="flex items-center gap-1">
            <span aria-hidden className="size-2 rounded-[1px]" style={{ background: TONE_FILL[tone] }} />
            {label}
          </span>
        ))}
        {stages.length > 0 && (
          <span className="flex items-center gap-1">
            <span aria-hidden className="h-2 border-l border-dashed border-starlight" />
            ramp stage
          </span>
        )}
      </div>
    </div>
  );
}

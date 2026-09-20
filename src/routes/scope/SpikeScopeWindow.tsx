import { useCallback, useEffect, useRef, useState } from "react";

import { messageOf, useScope } from "@/lib/intan/context";
import { cropSnippet, voltageToY, yToVoltage } from "@/lib/intan/scopeMath";
import {
  SCOPE_SCALES_UV,
  SCOPE_SPIKE_COUNTS,
  SCOPE_TIME_SCALES_MS,
  type ScopeData,
  type SpikeScopePayload,
  type SpikeSnippet,
} from "@/lib/intan/types";
import { scopeTitle } from "@/lib/intan/windows";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

import { useScopeContext } from "./ScopeApp";
import { ChannelPick, NumberPick, ScopeFrame } from "./ScopeFrame";
import { palette, useCanvas } from "./useCanvas";

/** How close to the threshold line a press must land to grab it, in px. */
const GRAB_PX = 7;
/** Snippets held client-side — the largest count RHX's own scope offers. */
const KEEP = 500;

/**
 * Spike Scope: the last N threshold crossings on one channel, overlaid and
 * aligned on the crossing, with the threshold drawn across them.
 *
 * RHX has this window and cannot be asked to open it over TCP, so it is rebuilt
 * from RHX's two data sockets: spike times from one, the channel's highpass
 * waveform from the other, cut sidecar-side. RHX's own option sets are offered
 * so the two scopes read the same.
 *
 * The threshold line is LIVE: drag it and RHX's detector moves, which changes
 * what is being saved. It commits on release, not on every pixel — each commit
 * is a command to RHX and a change to the recording.
 */
export function SpikeScopeWindow() {
  const ctx = useScopeContext();
  const [channel, setChannel] = useState<string | null>(ctx.initialChannel);
  // The recorded channels arrive with `intan.status`, a moment after mount.
  useEffect(() => {
    if (channel === null && ctx.channels.length > 0) setChannel(ctx.channels[0] ?? null);
  }, [channel, ctx.channels]);

  if (channel === null) {
    return (
      <ScopeFrame title={scopeTitle("spikescope", ctx.box, ctx.animal)}>
        <Waiting>Waiting for this box's recorded channels…</Waiting>
      </ScopeFrame>
    );
  }
  return <Live channel={channel} onChannel={setChannel} />;
}

function Live({ channel, onChannel }: { channel: string; onChannel: (c: string) => void }) {
  const ctx = useScopeContext();
  const { client } = useSidecar();
  const [scaleUv, setScaleUv] = useState(500);
  const [timeScaleMs, setTimeScaleMs] = useState(2);
  const [shown, setShown] = useState(20);
  const [threshold, setThreshold] = useState<number | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [total, setTotal] = useState(0);
  const [commitError, setCommitError] = useState<string | null>(null);

  const snippets = useRef<SpikeSnippet[]>([]);
  const meta = useRef({ sampleRate: ctx.sampleRate, preMs: 2 });
  const view = useRef({ scaleUv, timeScaleMs, shown, threshold });
  view.current = { scaleUv, timeScaleMs, shown, threshold };
  const dragging = useRef<number | null>(null);

  const { canvasRef, redraw } = useCanvas((g, width, height) => {
    const colors = palette();
    const { scaleUv: scale, timeScaleMs: span, shown: count } = view.current;

    // The zero line, and the crossing a third of the way across.
    g.strokeStyle = colors.halo;
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(0, Math.round(height / 2) + 0.5);
    g.lineTo(width, Math.round(height / 2) + 0.5);
    g.moveTo(Math.round(width / 3) + 0.5, 0);
    g.lineTo(Math.round(width / 3) + 0.5, height);
    g.stroke();

    const recent = snippets.current.slice(-count);
    recent.forEach((snippet, index) => {
      const { values } = cropSnippet(snippet.microvolts, meta.current.sampleRate, meta.current.preMs, span);
      if (values.length < 2) return;
      const newest = index === recent.length - 1;
      // Older sweeps recede; the newest is the one the eye should find.
      g.strokeStyle = newest ? colors.starlight : colors.pulsar;
      g.globalAlpha = newest ? 1 : 0.18 + 0.5 * (index / Math.max(1, recent.length - 1));
      g.lineWidth = newest ? 1.4 : 1;
      g.beginPath();
      values.forEach((uv, i) => {
        const x = (i / (values.length - 1)) * width;
        const y = voltageToY(uv, scale, height);
        if (i === 0) g.moveTo(x, y);
        else g.lineTo(x, y);
      });
      g.stroke();
    });
    g.globalAlpha = 1;

    const level = dragging.current ?? view.current.threshold;
    if (level !== null) {
      const y = voltageToY(level, scale, height);
      g.strokeStyle = colors.warning;
      g.setLineDash([5, 4]);
      g.lineWidth = 1.2;
      g.beginPath();
      g.moveTo(0, y);
      g.lineTo(width, y);
      g.stroke();
      g.setLineDash([]);
    }
  });

  useEffect(redraw, [redraw, scaleUv, timeScaleMs, shown, threshold]);

  const onData = useCallback(
    (message: ScopeData) => {
      const data = message.data as SpikeScopePayload;
      if (data.reset) snippets.current = [];
      if (data.added.length > 0) {
        snippets.current = [...snippets.current, ...data.added].slice(-KEEP);
        setTotal((n) => (data.reset ? data.added.length : n + data.added.length));
      } else if (data.reset) {
        setTotal(0);
      }
      meta.current = { sampleRate: data.sampleRate, preMs: data.preMs };
      setStreaming(data.streaming);
      if (dragging.current === null) setThreshold(data.thresholdMicrovolts);
      redraw();
    },
    [redraw],
  );
  const scope = useScope("spikescope", ctx.box, channel, {}, onData);

  // --- the threshold drag ------------------------------------------------

  function levelAt(event: React.PointerEvent<HTMLCanvasElement>): number {
    const rect = event.currentTarget.getBoundingClientRect();
    const uv = yToVoltage(event.clientY - rect.top, view.current.scaleUv, rect.height);
    return Math.max(-5000, Math.min(5000, uv));
  }

  function onPointerDown(event: React.PointerEvent<HTMLCanvasElement>) {
    if (threshold === null) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const lineY = voltageToY(threshold, scaleUv, rect.height);
    if (Math.abs(event.clientY - rect.top - lineY) > GRAB_PX) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragging.current = threshold;
  }

  function onPointerMove(event: React.PointerEvent<HTMLCanvasElement>) {
    if (dragging.current === null) return;
    dragging.current = levelAt(event);
    redraw();
  }

  function onPointerUp(event: React.PointerEvent<HTMLCanvasElement>) {
    const level = dragging.current;
    if (level === null) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    dragging.current = null;
    setThreshold(level);
    setCommitError(null);
    void client
      .call(CMD.INTAN_SET_THRESHOLD, { channel, microvolts: level })
      .then((reply) => setThreshold(reply.microvolts))
      .catch((err: unknown) => setCommitError(messageOf(err)));
  }

  return (
    <ScopeFrame
      title={scopeTitle("spikescope", ctx.box, ctx.animal)}
      subtitle={channel}
      error={scope.error ?? commitError}
      options={
        <>
          <ChannelPick channels={ctx.channels} value={channel} onChange={onChannel} />
          <NumberPick label="Scale" value={scaleUv} options={SCOPE_SCALES_UV} unit="µV" onChange={setScaleUv} />
          <NumberPick label="Time" value={timeScaleMs} options={SCOPE_TIME_SCALES_MS} unit="ms" onChange={setTimeScaleMs} />
          <NumberPick label="Spikes" value={shown} options={SCOPE_SPIKE_COUNTS} onChange={setShown} />
        </>
      }
      status={
        <>
          <span>{total} spikes</span>
          <span>threshold {threshold === null ? "—" : `${threshold} µV`}</span>
          {!streaming && <span style={{ color: "var(--color-status-warning)" }}>waiting for RHX to stream this channel</span>}
          <span className="ml-auto">±{scaleUv / 2} µV · {timeScaleMs} ms</span>
        </>
      }
    >
      <canvas
        ref={canvasRef}
        className="absolute inset-0 size-full touch-none"
        style={{ cursor: threshold === null ? "default" : "ns-resize" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      />
    </ScopeFrame>
  );
}

export function Waiting({ children }: { children: React.ReactNode }) {
  return (
    <div className="absolute inset-0 flex items-center justify-center px-8 text-center text-[12px] text-static">
      {children}
    </div>
  );
}

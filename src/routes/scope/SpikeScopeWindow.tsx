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
import { ChannelPick, NumberPick, ScopeFrame, Waiting } from "./ScopeFrame";
import { monoFont, palette, useCanvas } from "./useCanvas";

/** How close to the threshold line a press must land to grab it, in px. */
const GRAB_PX = 7;
/** Snippets held client-side — the largest count RHX's own scope offers. */
const KEEP = 500;
/**
 * How long the discarded-byte count must go on rising before it is called a
 * mismatch, in ms.
 *
 * The count is cumulative for the whole recording and is never reset, so a
 * nonzero value is not a fault: every deliberate layout change — opening this
 * window, swapping its channel — resyncs the parser and throws away whatever
 * was in flight. That is one burst, then silence. A real disagreement never
 * stops. Waiting out a burst is what separates the two, and it is why the
 * banner is spelled from `climbing` rather than from `discarded > 0`.
 */
const DISCARD_GRACE_MS = 2000;

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
  const [discarded, setDiscarded] = useState(0);
  const [climbing, setClimbing] = useState(false);
  const [commitError, setCommitError] = useState<string | null>(null);
  const [nearLine, setNearLine] = useState(false);
  const [dragged, setDragged] = useState(false);

  const snippets = useRef<SpikeSnippet[]>([]);
  /** Last count seen, and when this run of rises began (0 = not rising). */
  const discards = useRef({ seen: 0, risingSince: 0 });
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

    // The scale, said on the canvas: ±half the full height.
    g.font = monoFont(10);
    g.fillStyle = colors.static;
    g.textBaseline = "top";
    g.textAlign = "left";
    g.fillText(`+${scale / 2} µV`, 6, 5);
    g.textBaseline = "bottom";
    g.fillText(`−${scale / 2} µV`, 6, height - 5);

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
      // The level, at the line's right end — live while dragging, so the
      // number being committed is the number being looked at.
      g.font = monoFont(10);
      g.fillStyle = colors.warning;
      g.textAlign = "right";
      g.textBaseline = y > height / 2 ? "bottom" : "top";
      g.fillText(`${level} µV`, width - 6, y > height / 2 ? y - 3 : y + 3);
      g.textAlign = "left";
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
      // A rise that outlasts the grace window is a mismatch; one that stops is
      // the resync a deliberate layout change is entitled to. The sidecar
      // sends on a change in this count alone, so a layout that parses NOTHING
      // — no snippets, nothing else to report — still gets us here.
      const bytes = data.discardedBytes ?? 0;
      const runs = discards.current;
      if (bytes > runs.seen) {
        if (runs.risingSince === 0) runs.risingSince = performance.now();
        setClimbing(performance.now() - runs.risingSince >= DISCARD_GRACE_MS);
      } else {
        runs.risingSince = 0;
        setClimbing(false);
      }
      runs.seen = bytes;
      setDiscarded(bytes);
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

  function isNear(event: React.PointerEvent<HTMLCanvasElement>): boolean {
    if (threshold === null) return false;
    const rect = event.currentTarget.getBoundingClientRect();
    const lineY = voltageToY(threshold, scaleUv, rect.height);
    return Math.abs(event.clientY - rect.top - lineY) <= GRAB_PX;
  }

  function onPointerDown(event: React.PointerEvent<HTMLCanvasElement>) {
    if (!isNear(event) || threshold === null) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragging.current = threshold;
  }

  function onPointerMove(event: React.PointerEvent<HTMLCanvasElement>) {
    if (dragging.current === null) {
      const near = isNear(event);
      if (near !== nearLine) setNearLine(near);
      return;
    }
    dragging.current = levelAt(event);
    redraw();
  }

  function onPointerUp(event: React.PointerEvent<HTMLCanvasElement>) {
    const level = dragging.current;
    if (level === null) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    dragging.current = null;
    setThreshold(level);
    setDragged(true);
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
          {streaming && threshold !== null && !dragged && (
            <span className="text-static/70">drag the line to set RHX's threshold</span>
          )}
          {/* A frame shape RHX and the sidecar disagree on parses as nothing
              and looks like a quiet channel; the count is the tell. Only while
              it is STILL rising, though — see DISCARD_GRACE_MS. */}
          {climbing && (
            <span style={{ color: "var(--color-status-warning)" }}>
              stream shape mismatch · {discarded} bytes discarded
            </span>
          )}
          <span className="ml-auto">±{scaleUv / 2} µV · {timeScaleMs} ms · last {shown}</span>
        </>
      }
    >
      <canvas
        ref={canvasRef}
        className="absolute inset-0 size-full touch-none"
        style={{ cursor: nearLine || dragging.current !== null ? "ns-resize" : "default" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      />
      {!streaming ? (
        <Waiting overlay detail={channel}>Waiting for RHX to stream this channel…</Waiting>
      ) : (
        total === 0 && (
          <Waiting overlay detail="the waveform is arriving; the threshold has not been crossed">
            No threshold crossings yet
          </Waiting>
        )
      )}
    </ScopeFrame>
  );
}

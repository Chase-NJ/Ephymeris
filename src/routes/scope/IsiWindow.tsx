import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Toggle } from "@/components/common/controls";
import { useScope } from "@/lib/intan/context";
import { barHeights, binRects } from "@/lib/intan/scopeMath";
import { ISI_BINS_MS, ISI_SPANS_MS, type IsiPayload, type ScopeData } from "@/lib/intan/types";
import { scopeTitle } from "@/lib/intan/windows";

import { useScopeContext } from "./ScopeApp";
import { ChannelPick, NumberPick, ScopeFrame, ScopeOption, Waiting } from "./ScopeFrame";
import { monoFont, palette, useCanvas } from "./useCanvas";

/**
 * Inter-spike interval histogram for one channel.
 *
 * Computed sidecar-side over the channel's recent spikes; the span and bin are
 * sent as scope params, so changing them re-bins the same spikes rather than
 * starting a new count.
 */
export function IsiWindow() {
  const ctx = useScopeContext();
  const [channel, setChannel] = useState<string | null>(ctx.initialChannel);
  useEffect(() => {
    if (channel === null && ctx.channels.length > 0) setChannel(ctx.channels[0] ?? null);
  }, [channel, ctx.channels]);

  if (channel === null) {
    return (
      <ScopeFrame title={scopeTitle("isi", ctx.box, ctx.animal)}>
        <Waiting>Waiting for this box's recorded channels…</Waiting>
      </ScopeFrame>
    );
  }
  return <Live channel={channel} onChannel={setChannel} />;
}

function Live({ channel, onChannel }: { channel: string; onChannel: (c: string) => void }) {
  const ctx = useScopeContext();
  const [spanMs, setSpanMs] = useState(200);
  const [binMs, setBinMs] = useState(5);
  const [logY, setLogY] = useState(false);
  const [summary, setSummary] = useState<Pick<IsiPayload, "intervals" | "beyond" | "meanIsiMs"> | null>(null);

  const payload = useRef<IsiPayload | null>(null);
  const logRef = useRef(logY);
  logRef.current = logY;

  const { canvasRef, redraw } = useCanvas((g, width, height) => {
    const data = payload.current;
    const colors = palette();
    g.strokeStyle = colors.halo;
    g.beginPath();
    g.moveTo(0, height - 0.5);
    g.lineTo(width, height - 0.5);
    g.stroke();
    if (!data || data.counts.length === 0) return;

    const heights = barHeights(data.counts, logRef.current);
    // Bars sit where their bin is in time; a partial last bin is narrower.
    const rects = binRects(heights.length, data.binMs, data.spanMs ?? data.binMs * heights.length, width);
    g.fillStyle = colors.pulsar;
    heights.forEach((h, i) => {
      const rect = rects[i];
      if (h <= 0 || !rect) return;
      const barHeight = Math.max(1, h * (height - 8));
      g.fillRect(rect.x + 0.5, height - barHeight, rect.w, barHeight);
    });

    // The tallest bar's count, and whether the axis is log — said on the
    // canvas, where a bar half the height of its neighbour can mean 2× or 10×.
    const max = Math.max(...data.counts);
    g.font = monoFont(10);
    g.fillStyle = colors.static;
    g.textBaseline = "top";
    g.textAlign = "left";
    g.fillText(`${max}${logRef.current ? " · log" : ""}`, 6, 4);
  });

  useEffect(redraw, [redraw, logY]);

  const onData = useCallback(
    (message: ScopeData) => {
      const data = message.data as IsiPayload;
      payload.current = data;
      setSummary((current) =>
        current &&
        current.intervals === data.intervals &&
        current.beyond === data.beyond &&
        current.meanIsiMs === data.meanIsiMs
          ? current
          : { intervals: data.intervals, beyond: data.beyond, meanIsiMs: data.meanIsiMs },
      );
      redraw();
    },
    [redraw],
  );
  const params = useMemo(() => ({ spanMs, binMs }), [spanMs, binMs]);
  const scope = useScope("isi", ctx.box, channel, params, onData);

  const rate = summary?.meanIsiMs ? 1000 / summary.meanIsiMs : null;

  return (
    <ScopeFrame
      title={scopeTitle("isi", ctx.box, ctx.animal)}
      subtitle={channel}
      error={scope.error}
      options={
        <>
          <ChannelPick channels={ctx.channels} value={channel} onChange={onChannel} />
          <NumberPick label="Span" value={spanMs} options={ISI_SPANS_MS} unit="ms" onChange={setSpanMs} />
          <NumberPick label="Bin" value={binMs} options={ISI_BINS_MS} unit="ms" onChange={setBinMs} />
          <ScopeOption label="Log">
            <Toggle label="Logarithmic y axis" checked={logY} onChange={setLogY} />
          </ScopeOption>
        </>
      }
      status={
        <>
          <span>{summary?.intervals ?? 0} intervals</span>
          <span>mean {summary?.meanIsiMs ? `${summary.meanIsiMs.toFixed(1)} ms` : "—"}</span>
          <span>{rate ? `${rate.toFixed(1)} Hz` : "—"}</span>
          {/* Said out loud: a histogram that looks complete while most of its
              intervals fall past the span is how a slow unit reads as quiet. */}
          {!!summary?.beyond && (
            <span style={{ color: "var(--color-status-warning)" }}>
              {summary.beyond} beyond {spanMs} ms
            </span>
          )}
          <span className="ml-auto">{binMs} ms bins{logY ? " · log y" : ""}</span>
        </>
      }
    >
      <div className="absolute inset-0 flex flex-col px-3 pt-3 pb-1">
        <div className="relative min-h-0 w-full flex-1">
          <canvas ref={canvasRef} className="absolute inset-0 size-full" />
          {(summary?.intervals ?? 0) === 0 && (
            <Waiting overlay detail="two spikes make the first interval">
              No spikes on {channel} yet
            </Waiting>
          )}
        </div>
        <div className="flex justify-between pt-1 font-mono text-[10px] text-static">
          <span>0</span>
          <span>inter-spike interval</span>
          <span>{spanMs} ms</span>
        </div>
      </div>
    </ScopeFrame>
  );
}

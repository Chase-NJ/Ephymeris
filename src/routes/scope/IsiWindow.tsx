import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Toggle } from "@/components/common/controls";
import { useScope } from "@/lib/intan/context";
import { barHeights } from "@/lib/intan/scopeMath";
import { ISI_BINS_MS, ISI_SPANS_MS, type IsiPayload, type ScopeData } from "@/lib/intan/types";
import { scopeTitle } from "@/lib/intan/windows";

import { useScopeContext } from "./ScopeApp";
import { ChannelPick, NumberPick, ScopeFrame, ScopeOption } from "./ScopeFrame";
import { Waiting } from "./SpikeScopeWindow";
import { palette, useCanvas } from "./useCanvas";

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
    const step = width / heights.length;
    g.fillStyle = colors.pulsar;
    heights.forEach((h, i) => {
      if (h <= 0) return;
      const barHeight = Math.max(1, h * (height - 8));
      g.fillRect(i * step + 0.5, height - barHeight, Math.max(1, step - 1), barHeight);
    });
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
        </>
      }
    >
      <div className="absolute inset-0 flex flex-col px-3 pt-3 pb-1">
        <canvas ref={canvasRef} className="min-h-0 w-full flex-1" />
        <div className="flex justify-between pt-1 font-mono text-[10px] text-static">
          <span>0</span>
          <span>inter-spike interval</span>
          <span>{spanMs} ms</span>
        </div>
      </div>
    </ScopeFrame>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Dropdown } from "@/components/common/Dropdown";
import { useScope } from "@/lib/intan/context";
import { binRects, niceCeiling } from "@/lib/intan/scopeMath";
import {
  PSTH_BINS_MS,
  PSTH_MAX_TRIALS,
  PSTH_POST_MS,
  PSTH_PRE_MS,
  type PsthPayload,
  type ScopeData,
} from "@/lib/intan/types";
import { scopeTitle } from "@/lib/intan/windows";

import { useScopeContext } from "./ScopeApp";
import { ChannelPick, NumberPick, ScopeFrame, ScopeOption } from "./ScopeFrame";
import { Waiting } from "./SpikeScopeWindow";
import { palette, useCanvas } from "./useCanvas";

/**
 * Peri-stimulus time histogram: one channel's spikes around one kind of event.
 *
 * WHERE THIS DIFFERS FROM RHX'S, and why it is better for this rig. RHX's PSTH
 * triggers on a digital input's edge — and here every event a box emits pulses
 * the SAME input, so RHX would align to "anything happened". The sidecar knows
 * which event each edge was (it matches the edges to the box's serial strobes,
 * `recording.md` §3), so the trigger here is a NAMED event: odor onset, a poke,
 * a reward. The alignment is still the electrical edge on the recording's own
 * clock; only the choice of which edges comes from the strobe stream.
 */
export function PsthWindow() {
  const ctx = useScopeContext();
  const [channel, setChannel] = useState<string | null>(ctx.initialChannel);
  useEffect(() => {
    if (channel === null && ctx.channels.length > 0) setChannel(ctx.channels[0] ?? null);
  }, [channel, ctx.channels]);

  if (channel === null) {
    return (
      <ScopeFrame title={scopeTitle("psth", ctx.box, ctx.animal)}>
        <Waiting>Waiting for this box's recorded channels…</Waiting>
      </ScopeFrame>
    );
  }
  return <Live channel={channel} onChannel={setChannel} />;
}

function Live({ channel, onChannel }: { channel: string; onChannel: (c: string) => void }) {
  const ctx = useScopeContext();
  const [preMs, setPreMs] = useState(500);
  const [postMs, setPostMs] = useState(500);
  const [binMs, setBinMs] = useState(10);
  const [maxTrials, setMaxTrials] = useState(50);
  // The first odor onset if the task has one — the event a PSTH is usually for.
  const [triggerCode, setTriggerCode] = useState<number | null>(
    () => (ctx.triggers.find((t) => /ODOR.*ON/i.test(t.name)) ?? ctx.triggers[0])?.code ?? null,
  );
  const [trials, setTrials] = useState(0);
  const [peak, setPeak] = useState(0);
  const [alignment, setAlignment] = useState<PsthPayload["alignment"]>("sync");

  const payload = useRef<PsthPayload | null>(null);

  const { canvasRef, redraw } = useCanvas((g, width, height) => {
    const data = payload.current;
    const colors = palette();
    // Raster above, histogram below — the two share one time axis, so the
    // trigger line runs through both.
    const rasterHeight = Math.round(height * 0.55);
    const histTop = rasterHeight + 10;
    const histHeight = height - histTop;
    const span = (data?.preMs ?? preMs) + (data?.postMs ?? postMs);
    const zeroX = Math.round(((data?.preMs ?? preMs) / span) * width) + 0.5;

    g.strokeStyle = colors.halo;
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(0, rasterHeight + 0.5);
    g.lineTo(width, rasterHeight + 0.5);
    g.moveTo(0, height - 0.5);
    g.lineTo(width, height - 0.5);
    g.stroke();

    if (data && data.trials > 0) {
      const rowHeight = Math.min(8, rasterHeight / data.rasters.length);
      const tick = Math.max(1, Math.min(6, rowHeight - 1));
      g.fillStyle = colors.starlight;
      data.rasters.forEach((row, index) => {
        // Newest trial at the bottom, nearest the histogram it feeds.
        const y = rasterHeight - (data.rasters.length - index) * rowHeight;
        for (const ms of row) {
          const x = ((ms + data.preMs) / span) * width;
          g.fillRect(Math.round(x), Math.round(y), 1, tick);
        }
      });

      const ceiling = niceCeiling(Math.max(...data.rateHz));
      // Bars sit where their bin is in time; a partial last bin is narrower.
      const rects = binRects(data.rateHz.length, data.binMs, span, width);
      g.fillStyle = colors.pulsar;
      data.rateHz.forEach((hz, i) => {
        const rect = rects[i];
        if (hz <= 0 || !rect) return;
        const barHeight = Math.max(1, (hz / ceiling) * (histHeight - 4));
        g.fillRect(rect.x + 0.5, height - barHeight, rect.w, barHeight);
      });
    }

    g.strokeStyle = colors.warning;
    g.setLineDash([4, 4]);
    g.beginPath();
    g.moveTo(zeroX, 0);
    g.lineTo(zeroX, height);
    g.stroke();
    g.setLineDash([]);
  });

  useEffect(redraw, [redraw, preMs, postMs]);

  const onData = useCallback(
    (message: ScopeData) => {
      const data = message.data as PsthPayload;
      payload.current = data;
      setTrials(data.trials);
      setPeak(data.rateHz.length ? niceCeiling(Math.max(...data.rateHz)) : 0);
      setAlignment(data.alignment ?? "sync");
      redraw();
    },
    [redraw],
  );
  const params = useMemo(
    () => ({ preMs, postMs, binMs, maxTrials, triggerCodes: triggerCode === null ? [] : [triggerCode] }),
    [preMs, postMs, binMs, maxTrials, triggerCode],
  );
  const scope = useScope("psth", ctx.box, channel, params, onData);

  const triggerName = ctx.triggers.find((t) => t.code === triggerCode)?.name ?? null;

  return (
    <ScopeFrame
      title={scopeTitle("psth", ctx.box, ctx.animal)}
      subtitle={`${channel}${triggerName ? ` · ${triggerName}` : ""}`}
      error={scope.error}
      options={
        <>
          <ChannelPick channels={ctx.channels} value={channel} onChange={onChannel} />
          <ScopeOption label="Align to">
            <Dropdown
              label="Trigger event"
              value={triggerCode === null ? "" : String(triggerCode)}
              placeholder="— event —"
              options={ctx.triggers.map((t) => ({ value: String(t.code), label: t.name, detail: String(t.code) }))}
              onChange={(v) => setTriggerCode(Number(v))}
            />
          </ScopeOption>
          <NumberPick label="Pre" value={preMs} options={PSTH_PRE_MS} unit="ms" onChange={setPreMs} />
          <NumberPick label="Post" value={postMs} options={PSTH_POST_MS} unit="ms" onChange={setPostMs} />
          <NumberPick label="Bin" value={binMs} options={PSTH_BINS_MS} unit="ms" onChange={setBinMs} />
          <NumberPick label="Trials" value={maxTrials} options={PSTH_MAX_TRIALS} onChange={setMaxTrials} />
        </>
      }
      status={
        <>
          <span>{trials} trials</span>
          <span>peak axis {peak} Hz</span>
          {ctx.triggers.length === 0 && (
            <span style={{ color: "var(--color-status-warning)" }}>
              this box's task declares no strobe names to align to
            </span>
          )}
          {/* Synthetic data has no sync line: each event sits where the
              recording clock stood when its strobe ARRIVED, tens of ms late.
              Said out loud, because the histogram looks the same either way. */}
          {alignment === "arrival" && (
            <span style={{ color: "var(--color-status-warning)" }}>
              aligned by strobe arrival · synthetic data
            </span>
          )}
          {/* Only trials whose post-window has CLOSED are counted, so the right
              of the histogram never sags by how recent the last trigger was. */}
          <span className="ml-auto">complete trials only</span>
        </>
      }
    >
      <div className="absolute inset-0 flex flex-col px-3 pt-3 pb-1">
        <canvas ref={canvasRef} className="min-h-0 w-full flex-1" />
        <div className="flex justify-between pt-1 font-mono text-[10px] text-static">
          <span>−{preMs} ms</span>
          <span>{triggerName ?? "event"}</span>
          <span>+{postMs} ms</span>
        </div>
      </div>
    </ScopeFrame>
  );
}

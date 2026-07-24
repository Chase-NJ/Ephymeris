import { motion } from "framer-motion";
import { ArrowLeft, Play, RotateCcw, Square } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/common/controls";
import { MetricChart } from "@/components/sessions/MetricChart";
import { useBoxOutput, usePortStatus } from "@/lib/hardware/context";
import { springPanel } from "@/lib/motion";
import { getTaskProfile } from "@/lib/sessions/commands";
import { useBoxEnded, useBoxTelemetry, useMetricHistory } from "@/lib/sessions/context";
import type {
  LiveMetric,
  SessionBox,
  TaskProfile,
  TelemetryMetric,
} from "@/lib/sessions/types";
import { useSidecar } from "@/lib/ws/context";

/**
 * The zoomed-in star view (`starting-a-session.md` §6.4).
 *
 * Docked and translucent over the still-rendering scene rather than replacing
 * it — arrival means the camera is close to that star with an instrument panel
 * open, not a cut to a different screen (§6.3).
 */
export function StarPanel({
  box,
  onStart,
  onStop,
  onReset,
  onBack,
  busy,
}: {
  box: SessionBox;
  onStart: () => void;
  onStop: () => void;
  onReset: () => void;
  onBack: () => void;
  busy: boolean;
}) {
  const { client } = useSidecar();
  const port = usePortStatus(box.box);
  const metrics = useBoxTelemetry(box.box);
  const ended = useBoxEnded(box.box);
  const [profile, setProfile] = useState<TaskProfile | null>(null);

  const live = port.state === "IN_SESSION";

  useEffect(() => {
    let active = true;
    void getTaskProfile(client, box.sketchPath)
      .then((p) => active && setProfile(p))
      .catch(() => active && setProfile(null));
    return () => {
      active = false;
    };
  }, [client, box.sketchPath]);

  return (
    <motion.aside
      initial={{ x: 24, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: 24, opacity: 0 }}
      transition={springPanel}
      className="pointer-events-auto absolute right-4 top-4 bottom-4 w-[340px] overflow-y-auto rounded-lg border border-halo bg-nebula/80 p-4 backdrop-blur-xl"
    >
      <Button variant="ghost" onClick={onBack}>
        <ArrowLeft size={13} strokeWidth={2} />
        Back to overview
      </Button>

      <h2 className="mt-3 font-display text-[18px] text-starlight">{box.animalName}</h2>
      <p className="font-mono text-[11px] text-static">
        Box {box.box} · {box.sketchName}
      </p>
      {profile && <p className="mt-0.5 text-[11px] text-static">{profile.taskName}</p>}

      <div className="mt-3 flex items-center gap-2">
        <Button variant="primary" disabled={busy || live} onClick={onStart}>
          <Play size={12} strokeWidth={2} />
          Start
        </Button>
        <Button disabled={busy || !live} onClick={onStop}>
          <Square size={12} strokeWidth={2} />
          Stop
        </Button>
        <Button variant="outline" disabled={busy} onClick={onReset} title="DTR reset">
          <RotateCcw size={12} strokeWidth={2} />
          Reset
        </Button>
      </div>

      {ended && (
        <p className="mt-3 text-[11px] text-static">
          Finished — <span className="text-starlight">{ended.stopReason}</span>
        </p>
      )}

      <div className="mt-4 border-t border-halo pt-3">
        {profile && profile.liveMetrics.length > 0 ? (
          <div className="flex flex-col gap-4">
            {profile.liveMetrics.map((metric) => (
              <LiveChart
                key={metric.id}
                box={box.box}
                metric={metric}
                current={metrics.find((m) => m.id === metric.id) ?? null}
              />
            ))}
          </div>
        ) : (
          // §6.4 — a sketch with no Task Profile degrades to the raw strobe
          // log, exactly as the pre-flight config form does (§3).
          <StrobeLog box={box.box} />
        )}
      </div>
    </motion.aside>
  );
}

/** Subscribes to one metric's history — a hook can't be called inside a map. */
function LiveChart({
  box,
  metric,
  current,
}: {
  box: number;
  metric: LiveMetric;
  current: TelemetryMetric | null;
}) {
  return (
    <MetricChart
      metric={metric}
      current={current}
      history={useMetricHistory(box, metric.id)}
    />
  );
}

function StrobeLog({ box }: { box: number }) {
  const lines = useBoxOutput(box);
  const tail = lines.slice(-80);

  return (
    <>
      <div className="text-[11px] text-static">
        No Task Profile for this sketch — raw strobes instead.
      </div>
      <div className="mt-2 flex max-h-[320px] flex-col-reverse overflow-y-auto rounded-sm border border-halo bg-void/60 p-2 font-mono text-[10px] text-static">
        <div>
          {tail.map((line) => (
            <div key={line.id} className={line.dir === "tx" ? "text-pulsar" : ""}>
              {line.text}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

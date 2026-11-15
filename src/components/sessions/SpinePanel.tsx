import { useMemo } from "react";

import { LiveSpine } from "./LiveSpine";
import { MetricStrip } from "./MetricStrip";
import { PanelFrame, Readout, type PanelProps } from "./StarPanelFrame";
import { usePortStatus } from "@/lib/hardware/context";
import { useBoxReplay } from "@/lib/sessions/context";
import { replayNote, replayStrip, replayWarns } from "@/lib/sessions/liveReplay";
import type { TaskProfile } from "@/lib/sessions/types";

/**
 * A spine task's panel: everything on it is what the sidecar's live replay
 * reports (`session.replay`), the same replay Analytics scores the finished run
 * with (`ANALYTICS.md#live-scoring`). Nothing here decodes a strobe.
 */
export function SpineStarPanel({ profile, ...props }: PanelProps & { profile: TaskProfile }) {
  const { box } = props;
  const port = usePortStatus(box.box);
  const replay = useBoxReplay(box.box);
  const strip = useMemo(() => replayStrip(replay), [replay]);
  const tally = replay?.replay?.classes ?? [];
  return (
    <PanelFrame
      {...props}
      profile={profile}
      live={port.state === "IN_SESSION"}
      readout={
        <Readout
          title="P(correct)"
          value={replay?.overall?.pSession ?? null}
          count={replay && !replayWarns(replay) ? replay.trials : 0}
        />
      }
      flow={<LiveSpine profile={profile} replay={replay} />}
      charts={
        tally.length > 0 ? (
          <div>
            <div className="mb-1 text-[11px] text-static">Outcomes so far</div>
            <ul className="flex flex-col gap-1">
              {tally.map((c) => (
                <li key={c.outcomeClass} className="flex items-center gap-3 font-mono text-[11px]">
                  <span className="min-w-0 flex-1 truncate text-starlight">
                    {c.outcomeClass.replace(/_/g, " ")}
                  </span>
                  <span className="tabular-nums text-static">
                    {c.n} of {c.of}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-[11px] leading-relaxed text-static">{replayNote(replay)}</p>
        )
      }
      metrics={
        <MetricStrip
          box={box.box}
          metrics={strip.metrics}
          labels={strip.labels}
          intervals={strip.intervals}
          note={replayNote(replay)}
          bare
        />
      }
    />
  );
}

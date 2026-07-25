import { motion } from "framer-motion";
import { ArrowLeft, Play, RotateCcw, Square } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/common/controls";
import { useBoxOutput, usePortStatus } from "@/lib/hardware/context";
import { springPanel, springSnappy } from "@/lib/motion";
import { getTaskProfile } from "@/lib/sessions/commands";
import { useBoxEnded } from "@/lib/sessions/context";
import type { SessionBox, TaskProfile } from "@/lib/sessions/types";
import { useSidecar } from "@/lib/ws/context";

/**
 * The zoomed-in star view (`starting-a-session.md` §6.4).
 *
 * Docked and translucent over the still-rendering scene rather than replacing
 * it — arrival means the camera is close to that star with an instrument panel
 * open, not a cut to a different screen (§6.3).
 *
 * Live-metric charts are deliberately out of this panel for now; in their
 * place, a fixed five-row feed of the box's most recent strobes, decoded via
 * the sketch's Task Profile strobe map when it has one.
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
        <StrobeFeed box={box.box} strobeNames={profile?.strobes ?? {}} />
      </div>
    </motion.aside>
  );
}

/** How many strobes the feed holds — a fixed frame, not a growing log. */
const FEED_ROWS = 5;

/** Newest row full strength, older ones receding. */
const ROW_OPACITY = [1, 0.8, 0.62, 0.48, 0.36];

const STROBE_LINE = /^(\d{1,3})\t(\d+)$/;

/**
 * The five most recent strobes from this box, newest first, decoded to the
 * profile's human names (`data-saving.md` §6.4); a sketch with no profile
 * gets the raw code labeled as such. Rows arrive from the top with the
 * app's snappy spring and dim as they age down the frame.
 */
function StrobeFeed({
  box,
  strobeNames,
}: {
  box: number;
  strobeNames: Record<string, string>;
}) {
  const lines = useBoxOutput(box);

  const recent = useMemo(() => {
    const out: Array<{ id: number; code: string; at: number }> = [];
    for (let i = lines.length - 1; i >= 0 && out.length < FEED_ROWS; i--) {
      const line = lines[i];
      if (!line || line.dir !== "rx") continue;
      const match = STROBE_LINE.exec(line.text);
      if (!match) continue;
      out.push({ id: line.id, code: match[1]!, at: Number(match[2]) });
    }
    return out;
  }, [lines]);

  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-wider text-static">
        Recent strobes
      </div>
      <ul className="mt-2 flex flex-col gap-1">
        {Array.from({ length: FEED_ROWS }, (_, slot) => {
          const strobe = recent[slot];
          if (!strobe) {
            return (
              <li
                key={`empty-${slot}`}
                className="rounded-sm border border-dashed border-halo/50 px-2 py-1.5 font-mono text-[10px] text-static/40"
                aria-hidden
              >
                —
              </li>
            );
          }
          return (
            <motion.li
              key={strobe.id}
              layout
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: ROW_OPACITY[slot] ?? 0.36, y: 0 }}
              transition={springSnappy}
              className="flex items-center gap-2 rounded-sm border border-halo/70 bg-void/40 px-2 py-1.5"
            >
              <span className="w-8 shrink-0 rounded-sm border border-halo px-1 text-center font-mono text-[10px] text-pulsar">
                {strobe.code}
              </span>
              <span className="min-w-0 flex-1 truncate text-[12px] text-starlight">
                {strobeNames[strobe.code] ?? `Strobe ${strobe.code}`}
              </span>
              <span className="shrink-0 font-mono text-[10px] tabular-nums text-static">
                {formatBoardTime(strobe.at)}
              </span>
            </motion.li>
          );
        })}
      </ul>
      {recent.length === 0 && (
        <p className="mt-2 text-[11px] text-static">
          Strobes will appear here as the box reports them.
        </p>
      )}
    </div>
  );
}

/** Board `millis()` → `m:ss.t` (hours prefixed only once a run gets there). */
function formatBoardTime(ms: number): string {
  const tenths = Math.floor((ms % 1000) / 100);
  const totalSeconds = Math.floor(ms / 1000);
  const seconds = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600);
  const mmss = `${minutes}:${String(seconds).padStart(2, "0")}.${tenths}`;
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}` : mmss;
}

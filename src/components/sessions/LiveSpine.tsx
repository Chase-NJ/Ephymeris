import { motion } from "framer-motion";
import { useMemo } from "react";

import { useReduceMotion } from "@/lib/useReduceMotion";
import { springSnappy } from "@/lib/motion";
import { replayWarns } from "@/lib/sessions/liveReplay";
import { rowName, spineGraph, type SpineGraph } from "@/lib/tasks/spineGraph";
import type { LiveReplay, TaskProfile } from "@/lib/ws/protocol";

/**
 * A running spine task's trial flow, live (`ARCHITECTURE.md#live-session-views`).
 *
 * The spine's phases left to right, from the profile's snapshot
 * (`spineGraph`), with the ITI leading back to the start. The token sits on
 * the phase **the sidecar's replay says the board is in** (`session.replay`'s
 * `phase`), and nowhere else; a phase the sidecar reached by a timer alone is
 * captioned as its estimate (`provisional`): this component computes no transition and reads
 * no strobe. A run whose stream replay does not reproduce has no token, and
 * says why in the warning colour, since its numbers are withdrawn too.
 *
 * The token is the trial flow's grammar (`LiveStateMachine`): a steady flat
 * ring and, motion allowing, a pulse. No glow (`ARCHITECTURE.md#theme`).
 */
export function LiveSpine({
  profile,
  replay,
}: {
  profile: TaskProfile;
  replay: LiveReplay | null;
}) {
  const graph = useMemo(() => spineGraph(profile), [profile]);
  if (!graph || graph.phases.length === 0) return null;
  return (
    <div>
      <SpineDrawing graph={graph} phase={replay?.status === "replaying" ? replay.phase : null} />
      <Caption graph={graph} replay={replay} />
    </div>
  );
}

const STEP = 96;
const PAD = 40;
const R = 9;
const Y = 26;
const LOOP_Y = 58;

function SpineDrawing({ graph, phase }: { graph: SpineGraph; phase: number | null }) {
  const reduceMotion = useReduceMotion();
  const n = graph.phases.length;
  const width = PAD * 2 + STEP * (n - 1);
  const x = (i: number) => PAD + STEP * i;
  const last = x(n - 1);
  return (
    <svg
      viewBox={`0 0 ${width} 78`}
      className="mx-auto block"
      style={{ width, maxWidth: "100%" }}
      role="img"
      aria-label="The task's phases, with the phase the box is in lit"
    >
      {graph.phases.slice(1).map((p) => (
        <line
          key={`edge-${p.index}`}
          x1={x(p.index - 1) + R + 3}
          y1={Y}
          x2={x(p.index) - R - 3}
          y2={Y}
          stroke="var(--color-halo)"
          strokeWidth={1.2}
        />
      ))}
      {/* The ITI leads back to the start: the trial loop. */}
      <path
        d={`M ${last} ${Y + R + 3} V ${LOOP_Y} H ${x(0)} V ${Y + R + 3}`}
        fill="none"
        stroke="var(--color-halo)"
        strokeWidth={1}
        strokeDasharray="4 4"
      />
      {graph.phases.map((p) => {
        const live = p.index === phase;
        return (
          <g key={p.index}>
            <title>{p.detail ? `${p.label} — ${p.detail}` : p.label}</title>
            {live && !reduceMotion && (
              <motion.circle
                cx={x(p.index)}
                cy={Y}
                fill="none"
                stroke="var(--color-starlight)"
                strokeWidth={1}
                initial={false}
                animate={{ r: [R + 2, R + 13], opacity: [0.5, 0] }}
                transition={{ duration: 1.6, repeat: Infinity, ease: "easeOut" }}
                pointerEvents="none"
              />
            )}
            {live && (
              <circle
                cx={x(p.index)}
                cy={Y}
                r={R + 4.5}
                fill="none"
                stroke="var(--color-starlight)"
                strokeWidth={0.8}
                opacity={0.55}
              />
            )}
            <motion.circle
              cx={x(p.index)}
              cy={Y}
              r={R}
              animate={{ fill: live ? "var(--color-starlight)" : "var(--color-nebula)" }}
              transition={springSnappy}
              stroke="var(--color-starlight)"
              strokeOpacity={0.8}
              strokeWidth={1}
            />
            <text
              x={x(p.index)}
              y={Y + R + 16}
              textAnchor="middle"
              className={live ? "fill-starlight" : "fill-static"}
              style={{ fontSize: 11 }}
            >
              {p.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function Caption({ graph, replay }: { graph: SpineGraph; replay: LiveReplay | null }) {
  const line = "mt-1.5 truncate border-t border-halo/60 pt-1.5 font-mono text-[11px] leading-snug";
  if (replay === null) {
    return <p className={`${line} text-static`}>Waiting for the board&apos;s first strobe.</p>;
  }
  if (replayWarns(replay)) {
    return (
      <p className={line} style={{ color: "var(--color-status-warning)" }} title={replay.detail ?? undefined}>
        ⚠ {replay.status === "diverged" ? "Diverged" : "Not replayable"} — {replay.detail}
      </p>
    );
  }
  if (replay.status === "ended") {
    return (
      <p className={`${line} text-static`}>
        Ended · <span className="text-starlight">{replay.trials}</span> complete trial
        {replay.trials === 1 ? "" : "s"}
      </p>
    );
  }
  const phase = replay.phase === null ? null : graph.phases[replay.phase];
  const row = rowName(graph, replay.row ?? replay.current?.row ?? null);
  const trial = replay.current ? replay.current.index + 1 : null;
  return (
    <p className={`${line} text-static`}>
      <span className="text-starlight">{phase?.label ?? "Between phases"}</span>
      {/* Reached by a timer alone since the last strobe: the sidecar's estimate
          on the board's clock, which the next strobe confirms or replaces. */}
      {replay.provisional && <span title="No strobe has confirmed this yet"> (by the board&apos;s clock)</span>}
      {row && <> · {row}</>}
      {trial !== null && <> · trial {trial}</>}
      {replay.last?.outcome && (
        <> · last: {replay.last.outcome.replace(/_/g, " ")}</>
      )}
    </p>
  );
}

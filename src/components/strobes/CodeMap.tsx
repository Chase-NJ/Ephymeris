import { useMemo, useRef, useState } from "react";

import type { StrobeVocabulary } from "@/lib/ws/protocol";

import { inRanges } from "./StrobeTable";

/**
 * Every code the wire can carry, 0–999, as one band.
 *
 * WHY A PICTURE AND NOT A LIST OF RANGES. The numbering is the hazard: the odor
 * onsets run 101–109 and then 114–116 because 110–113 are retired, and a list
 * of free ranges ("117–220, 227–232, …") hides exactly that. On the band the
 * retired block is a visible gap in the onset run, and a free stretch is a
 * place you can point at. Clicking one opens Add with that number filled in.
 *
 * Four states, four fills, no gradients: live codes in pulsar (the one accent),
 * retired in static (still reserved, no longer emitted), the reserved range in
 * halo, and free as the faint ground everything else sits on.
 */
type State = "live" | "retired" | "reserved" | "free";

interface Run {
  state: State;
  lo: number;
  hi: number;
}

const HEIGHT = 22;

export function CodeMap({
  vocabulary,
  selected,
  onSelectCode,
  onPickFree,
}: {
  vocabulary: StrobeVocabulary;
  /** The code the table has selected, marked on the band. */
  selected: number | null;
  onSelectCode: (code: number) => void;
  onPickFree: (code: number) => void;
}) {
  const { codeMin, codeMax } = vocabulary;
  const span = codeMax - codeMin + 1;
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const byCode = useMemo(() => {
    const out = new Map<number, { state: State; name: string }>();
    for (const c of vocabulary.codes) out.set(c.code, { state: "live", name: c.name });
    for (const c of vocabulary.retired) out.set(c.code, { state: "retired", name: c.name });
    return out;
  }, [vocabulary]);

  const stateOf = (code: number): State => {
    const hit = byCode.get(code);
    if (hit) return hit.state;
    if (inRanges(vocabulary.reserved, code)) return "reserved";
    return "free";
  };

  /** Contiguous runs, so the band is a few dozen rects rather than a thousand. */
  const runs = useMemo(() => {
    const out: Run[] = [];
    for (let code = codeMin; code <= codeMax; code++) {
      const state = stateOf(code);
      const last = out[out.length - 1];
      if (last && last.state === state && last.hi === code - 1) last.hi = code;
      else out.push({ state, lo: code, hi: code });
    }
    return out;
    // stateOf closes over byCode and reserved, both derived from vocabulary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vocabulary]);

  const codeAt = (clientX: number): number | null => {
    const box = ref.current?.getBoundingClientRect();
    if (!box || box.width === 0) return null;
    const t = (clientX - box.left) / box.width;
    return Math.min(codeMax, Math.max(codeMin, codeMin + Math.floor(t * span)));
  };

  const runAt = (code: number) => runs.find((r) => code >= r.lo && code <= r.hi) ?? null;

  const readout = (() => {
    if (hover === null) {
      return (
        <span className="text-static/60">
          Point at the band to read a code; click a free stretch to issue one.
        </span>
      );
    }
    const run = runAt(hover);
    const hit = byCode.get(hover);
    if (hit) {
      return (
        <>
          <span className="text-starlight">{hover}</span>{" "}
          <span className={hit.state === "live" ? "text-starlight" : "text-static"}>
            {hit.name}
          </span>
          {hit.state === "retired" && <span className="text-static"> · retired, reserved</span>}
        </>
      );
    }
    if (run?.state === "reserved") {
      return (
        <>
          <span className="text-starlight">{hover}</span>
          <span className="text-static">
            {" "}· reserved {run.lo}–{run.hi}, never issued
          </span>
        </>
      );
    }
    return (
      <>
        <span className="text-starlight">{hover}</span>
        <span className="text-static">
          {" "}· free{run && run.lo !== run.hi ? ` (${run.lo}–${run.hi})` : ""} — click to issue
        </span>
      </>
    );
  })();

  const ticks = [0, 100, 200, 300, 400, 500, 600, 700, 800, 900, codeMax];
  const x = (code: number) => ((code - codeMin) / span) * 1000;

  return (
    <div className="flex flex-col gap-1.5">
      <svg
        ref={ref}
        viewBox={`0 0 1000 ${HEIGHT}`}
        preserveAspectRatio="none"
        className="block h-[22px] w-full cursor-crosshair"
        role="img"
        aria-label={`Strobe codes ${codeMin} to ${codeMax}: ${vocabulary.codes.length} live, ${vocabulary.retired.length} retired`}
        onMouseMove={(e) => setHover(codeAt(e.clientX))}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => {
          const code = codeAt(e.clientX);
          if (code === null) return;
          const state = stateOf(code);
          if (state === "free") onPickFree(code);
          else if (state === "live" || state === "retired") onSelectCode(code);
        }}
      >
        {runs.map((run) => (
          <rect
            key={`${run.state}-${run.lo}`}
            x={x(run.lo)}
            y={run.state === "free" ? 6 : 0}
            width={Math.max(x(run.hi + 1) - x(run.lo), 1.2)}
            height={run.state === "free" ? HEIGHT - 12 : HEIGHT}
            shapeRendering="crispEdges"
            style={{ fill: FILL[run.state], opacity: OPACITY[run.state] }}
          />
        ))}
        {hover !== null && (
          <rect
            x={x(hover)}
            y={0}
            width={1.2}
            height={HEIGHT}
            shapeRendering="crispEdges"
            style={{ fill: "var(--color-starlight)", opacity: 0.55 }}
          />
        )}
        {selected !== null && (
          <rect
            x={x(selected) - 0.6}
            y={0}
            width={2.4}
            height={HEIGHT}
            shapeRendering="crispEdges"
            style={{ fill: "var(--color-starlight)" }}
          />
        )}
      </svg>
      <div className="relative h-3 font-mono text-[9px] text-static/60">
        {ticks.map((t) => (
          <span
            key={t}
            className="absolute -translate-x-1/2 first:translate-x-0 last:-translate-x-full"
            style={{ left: `${(x(t) / 1000) * 100}%` }}
          >
            {t}
          </span>
        ))}
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="min-h-[16px] font-mono text-[11px]">{readout}</div>
        <Legend />
      </div>
    </div>
  );
}

const FILL: Record<State, string> = {
  live: "var(--color-pulsar)",
  retired: "var(--color-static)",
  reserved: "var(--color-halo)",
  free: "var(--color-halo)",
};

const OPACITY: Record<State, number> = {
  live: 1,
  retired: 0.75,
  reserved: 0.9,
  free: 0.35,
};

function Legend() {
  return (
    <div className="flex items-center gap-3 font-mono text-[10px] text-static">
      {(["live", "retired", "reserved", "free"] as const).map((state) => (
        <span key={state} className="flex items-center gap-1.5">
          <span
            className="inline-block h-2 w-2.5 rounded-[1px]"
            style={{ background: FILL[state], opacity: OPACITY[state] }}
          />
          {state}
        </span>
      ))}
    </div>
  );
}

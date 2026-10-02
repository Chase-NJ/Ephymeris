import { AnimatePresence, motion } from "framer-motion";
import { Plus, Trash2, TrendingUp, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { NumberInput } from "@/components/common/controls";
import { springSnappy } from "@/lib/motion";
import { diagnosticsAt, nextStage } from "@/lib/taskdef/types";
import type { StageRow, TaskDiagnostic } from "@/lib/taskdef/types";

/**
 * The shaping ramp — how strictness arrives, and over how many trials.
 *
 * FOUR VALUES, DECLARED PER ROW, NEVER ONCE. The firmware rewrites all four
 * from `stage[]` on every completed trial, so a single field per value would
 * appear to work and then be silently overwritten around trial 15–20. That is
 * the trap this table exists to make visible: the whole schedule is on screen
 * at once, and a row that engages is a row you can see.
 *
 * THE TIMELINE ABOVE THE TABLE is the session as the animal will meet it: one
 * segment per stage, width proportional to how long it holds, deepening in
 * tint as the ramp tightens. It is the same data as the rows — a ramp is only
 * legible as a sequence, and the strip is the sequence read at a glance while
 * the table is where it is edited. Hovering either lights the other. On an
 * out-of-order schedule the strip falls back to equal widths: a duration that
 * is not ascending has no honest proportional drawing, and TSK106 is already
 * saying so in words.
 *
 * ROW 0 HAS NO "ENGAGES AT". It is live from trial 0 by construction —
 * `liveStage()` scans down and falls through to it — so offering a count there
 * would be a field with no effect. A one-row ramp is a task that does not ramp,
 * which is the common case and the reason "Add stage" rather than a fixed five.
 *
 * A NEW ROW IS SEEDED FROM THE ONE BEFORE IT, never from a defaults table, and
 * focus lands in its "engages at" cell with the seeded count selected — the
 * one value every new stage certainly changes, ready to be typed over. A stage
 * that appeared carrying numbers nobody chose reads as deliberate, and the
 * operator's job is then to spot which of four values is wrong rather than to
 * change the one they meant to.
 */
export function StageRamp({
  stages,
  diagnostics,
  onChange,
}: {
  stages: StageRow[];
  diagnostics: TaskDiagnostic[];
  onChange: (next: StageRow[]) => void;
}) {
  const ramped = stages.length > 1;
  /** Timeline ↔ table hover link. */
  const [hot, setHot] = useState<number | null>(null);
  /** Rows at or past this index were just added — their first cell takes focus. */
  const addedAt = useRef<number | null>(null);

  // Consumed at mount, cleared after every commit. A stale flag would hand
  // focus to an unrelated row the next time one happens to mount at that
  // index — switching to a longer task, say.
  useEffect(() => {
    addedAt.current = null;
  });

  const update = (index: number, patch: Partial<StageRow>) =>
    onChange(stages.map((s, i) => (i === index ? { ...s, ...patch } : s)));

  // Row 0 is the task's own holds; removing it would leave the runner with no
  // values at all. Every later row is optional.
  const remove = (index: number) =>
    index > 0 && onChange(stages.filter((_, i) => i !== index));

  const add = () => {
    addedAt.current = stages.length;
    onChange([...stages, nextStage(stages[stages.length - 1])]);
  };

  return (
    <div className="hud flex min-h-0 flex-col rounded-md">
      <header className="flex items-center justify-between gap-3 border-b border-halo px-3.5 py-2.5">
        <TrendingUp size={18} strokeWidth={1.75} className="shrink-0 text-pulsar" />
        <div className="min-w-0 flex-1">
          <div className="text-[12px] font-medium text-starlight">
            {ramped ? `Shaping ramp — ${stages.length} stages` : "Holds & windows"}
          </div>
          <div className="mt-0.5 text-[10px] text-static/70">
            {ramped
              ? "Each row takes over at its trial count and stays until the next one does."
              : "One row: the task starts at full strictness and never eases."}
          </div>
        </div>
        <button
          type="button"
          onClick={add}
          className="flex shrink-0 items-center gap-1 rounded-md border border-halo px-2.5 py-1 text-[10px] text-static transition-colors hover:border-pulsar hover:text-starlight"
        >
          <Plus size={11} strokeWidth={1.75} />
          Add stage
        </button>
      </header>

      {ramped && <Timeline stages={stages} hot={hot} onHot={setHot} />}

      <div className="scrollbar-none min-h-0 overflow-y-auto px-2 pb-1 pt-2">
        <div className={GRID}>
          <span className="px-1.5 text-[10px] text-static/70">stage</span>
          <span className="px-1 text-[10px] text-static/70">engages at</span>
          <ColumnHead label="odor hold" />
          <ColumnHead label="well hold" />
          <ColumnHead label="response window" />
          <ColumnHead label="odor port window" />
          <span />
        </div>

        <AnimatePresence initial={false}>
          {stages.map((stage, index) => {
            const problems = diagnosticsAt(diagnostics, `stages[${index}]`);
            const fresh = addedAt.current !== null && index >= addedAt.current;
            return (
              <motion.div
                key={index}
                layout
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, transition: { duration: 0.12 } }}
                transition={springSnappy}
                onMouseEnter={() => setHot(index)}
                onMouseLeave={() => setHot(null)}
                className={`${GRID} group rounded-md py-1 transition-colors ${
                  hot === index ? "bg-halo/25" : ""
                }`}
              >
                <span className="px-1.5 font-mono text-[10px] text-static/60">
                  {index}
                </span>
                {index === 0 ? (
                  <span
                    className="px-1 text-[10px] text-static/60"
                    title="Row 0 is live from trial 0 — the firmware never reads its count"
                  >
                    trial 0
                  </span>
                ) : (
                  <Cell
                    value={stage.trials}
                    label={`Stage ${index} engages at trial`}
                    invalid={problems.some((p) => p.location.endsWith(".trials"))}
                    autoFocus={fresh}
                    onChange={(trials) => update(index, { trials })}
                  />
                )}
                <Cell
                  value={stage.odorPokeHold}
                  label={`Stage ${index} odor hold`}
                  onChange={(odorPokeHold) => update(index, { odorPokeHold })}
                />
                <Cell
                  value={stage.fluidWellHold}
                  label={`Stage ${index} well hold`}
                  onChange={(fluidWellHold) => update(index, { fluidWellHold })}
                />
                <Cell
                  value={stage.fluidWellPoll}
                  label={`Stage ${index} response window`}
                  onChange={(fluidWellPoll) => update(index, { fluidWellPoll })}
                />
                <Cell
                  value={stage.odorPortTimeout}
                  label={`Stage ${index} odor port window`}
                  onChange={(odorPortTimeout) => update(index, { odorPortTimeout })}
                />
                <span className="flex justify-end pr-1">
                  {index > 0 && (
                    <button
                      type="button"
                      onClick={() => remove(index)}
                      title="Remove this stage"
                      className="text-static/40 transition-colors hover:text-status-error group-hover:text-static"
                    >
                      <Trash2 size={12} strokeWidth={1.75} />
                    </button>
                  )}
                </span>
              </motion.div>
            );
          })}
        </AnimatePresence>

        {diagnosticsAt(diagnostics, "stages").map((problem, i) => (
          <p
            key={i}
            className="flex items-start gap-1.5 px-1.5 py-2 text-[10px] text-status-error"
          >
            <TriangleAlert size={11} strokeWidth={1.75} className="mt-px shrink-0" />
            <span>
              <span className="font-mono opacity-70">{problem.code}</span>{" "}
              {problem.message}
            </span>
          </p>
        ))}
      </div>

      <p className="border-t border-halo px-3.5 py-2 text-[10px] text-static/70">
        All four are milliseconds. Every value here also travels on the{" "}
        <span className="font-mono">START</span> line, so tuning one per box at
        mapping costs no rebuild — only the number of stages does.
      </p>
    </div>
  );
}

/** One row's shape, shared by the header and every stage. */
const GRID =
  "grid grid-cols-[2.5rem_5.5rem_repeat(4,minmax(0,1fr))_2rem] items-center gap-x-2 px-1.5";

function ColumnHead({ label }: { label: string }) {
  return (
    <span className="px-1 text-[10px] text-static/70">
      {label} <span className="font-mono text-[9px] text-static/40">ms</span>
    </span>
  );
}

/**
 * The session as a strip: one segment per stage, width proportional to how
 * long it holds, tint deepening as the ramp tightens. The last stage has no
 * end, so it takes a fixed tail. Tints are stepped per segment — data
 * encoding, not a gradient (`ARCHITECTURE.md#theme` keeps Pulsar matte).
 */
function Timeline({
  stages,
  hot,
  onHot,
}: {
  stages: StageRow[];
  hot: number | null;
  onHot: (index: number | null) => void;
}) {
  const starts = stages.map((s, i) => (i === 0 ? 0 : s.trials));
  const ascending = starts.every((v, i) => i === 0 || v > (starts[i - 1] ?? 0));
  const lastStart = starts[starts.length - 1] ?? 0;
  const tail = Math.max(20, Math.round(lastStart * 0.35));
  const total = lastStart + tail;

  const widths = stages.map((_, i) => {
    if (!ascending || total === 0) return 1 / stages.length;
    const end = i === stages.length - 1 ? total : (starts[i + 1] ?? total);
    return (end - (starts[i] ?? 0)) / total;
  });

  return (
    <div className="border-b border-halo/60 px-3.5 pb-2.5 pt-2">
      <div className="flex h-[30px] gap-px overflow-hidden rounded-sm">
        {stages.map((stage, index) => {
          // 12% → 34% Pulsar across the ramp: later is stricter is deeper.
          const tint =
            12 + (stages.length === 1 ? 0 : (22 * index) / (stages.length - 1));
          return (
            <button
              key={index}
              type="button"
              tabIndex={-1}
              onMouseEnter={() => onHot(index)}
              onMouseLeave={() => onHot(null)}
              title={
                `Stage ${index} — from trial ${starts[index]}: ` +
                `odor hold ${stage.odorPokeHold} ms, well hold ${stage.fluidWellHold} ms, ` +
                `response window ${stage.fluidWellPoll} ms, odor port window ${stage.odorPortTimeout} ms`
              }
              style={{
                flexBasis: `${(widths[index] ?? 0) * 100}%`,
                backgroundColor: `color-mix(in srgb, var(--color-pulsar) ${tint}%, transparent)`,
              }}
              className={`flex min-w-0 shrink-0 grow-0 flex-col items-start justify-center px-1.5 transition-[outline-color] ${
                hot === index ? "outline outline-1 -outline-offset-1 outline-pulsar" : "outline-none"
              }`}
            >
              <span className="font-mono text-[9px] leading-tight text-starlight/90">
                S{index}
              </span>
              <span className="truncate font-mono text-[8px] leading-tight text-static/70">
                {index === 0 ? "trial 0" : `${starts[index]}`}
              </span>
            </button>
          );
        })}
      </div>
      {!ascending && (
        <p className="mt-1 text-[9px] text-static/60">
          drawn with equal widths — the schedule is out of order
        </p>
      )}
    </div>
  );
}

function Cell({
  value,
  label,
  invalid,
  autoFocus,
  onChange,
}: {
  value: number;
  label: string;
  invalid?: boolean;
  autoFocus?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <NumberInput
      label={label}
      value={value}
      // An emptied cell means "none", which for a hold or a window is 0. There
      // is no lower layer here to fall back to — the row IS the declaration.
      fallback={0}
      integer
      min={0}
      align="right"
      invalid={invalid ?? false}
      autoFocus={autoFocus ?? false}
      className="w-full px-2 py-1 text-[11px]"
      onChange={onChange}
    />
  );
}

import { AnimatePresence, motion } from "framer-motion";
import { Check, Minus, TriangleAlert } from "lucide-react";
import { useRef, type KeyboardEvent } from "react";

import { colorForIndex } from "@/lib/analytics/view";
import type { RigDocument } from "@/lib/hardware/types";
import { springPanel, springSnappy } from "@/lib/motion";
import { SELECTION_MODES, compositionOf, modeInfo } from "@/lib/taskdef/selection";
import { channelLabel, diagnosticsAt } from "@/lib/taskdef/types";
import type { SelectionMode, TaskDiagnostic, TrialTypeDef } from "@/lib/taskdef/types";
import { GENERATION_TAB } from "@/lib/tasks/topology";

import { Panel } from "./Panel";

/**
 * How the next trial is chosen (`TASKS.md#trial-generation`) — a core choice,
 * so it has a panel of its own rather than a switch in a table header.
 *
 * The mode, a sentence on how it draws, what it does and does not do, and the
 * session it would deal — the composition strip, each condition in its own
 * colour. The settings that belong to selection (the anti-bias side draw, the
 * pool's block size, the correction budgets) are parameters like any other:
 * exposed through the Parameters panel's picker, where a field the mode never
 * reads is dimmed with a note (`TASKS.md#parameters`).
 */
export function GenerationPanel({
  trials,
  mode,
  rig,
  diagnostics,
  lit,
  onMode,
  onHover,
  onHoverCondition,
  conditionOfRow,
}: {
  trials: TrialTypeDef[];
  mode: SelectionMode;
  rig: RigDocument | null;
  diagnostics: TaskDiagnostic[];
  lit: boolean;
  onMode: (mode: SelectionMode) => void;
  onHover: (tab: string | null) => void;
  onHoverCondition: (conditionId: string | null) => void;
  conditionOfRow: (row: number) => string | null;
}) {
  const info = modeInfo(mode);
  const tableProblems = diagnosticsAt(diagnostics, "trials").filter(
    (d) => d.location === "trials" && d.code === "TSK109",
  );

  return (
    <Panel
      id="generation"
      name="Trial generation"
      note="how the next trial is chosen"
      lit={lit}
      onPointerEnter={() => onHover(GENERATION_TAB)}
      onPointerLeave={() => onHover(null)}
      bodyClassName="gap-2.5"
    >
      <ModeSwitch mode={mode} onMode={onMode} />

      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={mode}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={springSnappy}
          className="flex flex-col gap-1.5"
        >
          <p className="text-[11.5px] leading-relaxed text-static">{info.hint}</p>
          <ul className="flex flex-wrap gap-x-2.5 gap-y-0.5">
            {info.facts.map((fact) => (
              <li
                key={fact.label}
                className={`flex items-center gap-0.5 font-mono text-[9.5px] ${
                  fact.on ? "text-starlight/85" : "text-static/45"
                }`}
              >
                {fact.on ? (
                  <Check size={10} strokeWidth={2} className="text-ion" />
                ) : (
                  <Minus size={10} strokeWidth={2} />
                )}
                {fact.label}
              </li>
            ))}
          </ul>
        </motion.div>
      </AnimatePresence>

      <CompositionStrip
        trials={trials}
        mode={mode}
        rig={rig}
        onHoverRow={(row) => onHoverCondition(row === null ? null : conditionOfRow(row))}
      />
      {tableProblems.map((problem, i) => (
        <p key={i} className="flex items-start gap-1.5 text-[10px] text-status-error">
          <TriangleAlert size={11} strokeWidth={1.75} className="mt-px shrink-0" />
          <span>
            <span className="font-mono opacity-70">{problem.code}</span> {problem.message}
          </span>
        </p>
      ))}
    </Panel>
  );
}

/**
 * The three modes as one control. The indicator travels between them on a
 * shared `layoutId`; arrow keys move the choice, as in any radio group.
 */
function ModeSwitch({ mode, onMode }: { mode: SelectionMode; onMode: (mode: SelectionMode) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const index = SELECTION_MODES.findIndex((m) => m.value === mode);

  function onKey(event: KeyboardEvent) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = (index + step + SELECTION_MODES.length) % SELECTION_MODES.length;
    const target = SELECTION_MODES[next];
    if (!target) return;
    onMode(target.value);
    refs.current[next]?.focus();
  }

  return (
    <div
      role="radiogroup"
      aria-label="How the next trial is chosen"
      onKeyDown={onKey}
      className="relative grid grid-cols-3 rounded-sm border border-halo bg-void/30 p-0.5"
    >
      {SELECTION_MODES.map((m, i) => {
        const active = m.value === mode;
        return (
          <button
            key={m.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onMode(m.value)}
            className={`relative z-10 py-1 text-[11px] font-medium transition-colors ${
              active ? "text-starlight" : "text-static hover:text-starlight"
            }`}
          >
            {active && (
              <motion.span
                layoutId="mode-pill"
                transition={springSnappy}
                className="absolute inset-0 -z-10 rounded-[2px] border border-pulsar/50 bg-pulsar/15"
              />
            )}
            {m.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * The session this mode would deal: each condition's share, in its colour.
 * Side-balanced modes draw two halves (the sides, as the draw balances them);
 * the pool draws one bar. A condition the mode never presents is an outline
 * after the bar, so its absence is on screen rather than implied.
 */
function CompositionStrip({
  trials,
  mode,
  rig,
  onHoverRow,
}: {
  trials: TrialTypeDef[];
  mode: SelectionMode;
  rig: RigDocument | null;
  onHoverRow: (row: number | null) => void;
}) {
  const shares = compositionOf(trials, mode);
  const presented = shares.filter((s) => s.share > 0);
  const absent = shares.filter((s) => s.share === 0 || !s.presented);
  const sides = mode === "pool" ? [] : [...new Set(presented.map((s) => s.side))];

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1.5">
        <div className="flex h-[14px] min-w-0 flex-1 gap-px overflow-hidden rounded-sm bg-halo/30">
          {presented.map((s) => (
            <motion.button
              key={s.row}
              type="button"
              tabIndex={-1}
              aria-label={`Trial type ${s.row + 1}: ${Math.round(s.share * 100)}% of trials`}
              title={`${trials[s.row]?.label || `Trial type ${s.row + 1}`} — ${Math.round(s.share * 100)}% of trials`}
              initial={false}
              animate={{ flexGrow: s.share, opacity: s.presented ? 1 : 0.35 }}
              transition={springPanel}
              onPointerEnter={() => onHoverRow(s.row)}
              onPointerLeave={() => onHoverRow(null)}
              style={{ flexBasis: 0, background: colorForIndex(s.row) }}
              className="min-w-[3px]"
            />
          ))}
        </div>
        {absent.map((s) => (
          <span
            key={s.row}
            title={`${trials[s.row]?.label || `Trial type ${s.row + 1}`} — never presented under ${modeInfo(mode).label.toLowerCase()}`}
            className="size-[10px] shrink-0 rounded-[2px] border border-dashed"
            style={{ borderColor: colorForIndex(s.row) }}
          />
        ))}
      </div>
      <div className="flex justify-between font-mono text-[9px] text-static/60">
        {sides.length === 2 ? (
          <>
            <span>{channelLabel(rig, sides[0] ?? "")} ½</span>
            <span>{channelLabel(rig, sides[1] ?? "")} ½</span>
          </>
        ) : (
          <span>{mode === "pool" ? "the whole session, by row weight" : "share of trials"}</span>
        )}
      </div>
    </div>
  );
}

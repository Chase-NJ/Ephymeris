import { AnimatePresence, motion } from "framer-motion";
import { Check, Droplets, Square } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button, NumberInput, Segmented } from "@/components/common/controls";
import { KIND_COLOR } from "@/lib/hardware/types";
import { springSnappy } from "@/lib/motion";
import type { ControlChannel } from "@/lib/sessions/types";

/**
 * Prime — open a chosen set of fluid lines, each for a chosen time, in turn.
 *
 * The thing a tech does before every session and used to do with the
 * PRIME_Lines sketch: run water through each line until it reaches the well,
 * so the first reward of the day is a reward and not air. It is built entirely
 * on the utility sketch's existing verbs — `SET PULSE=<ms>` then one
 * `PULSE <ch>` per line — sent over `port.send`, so it needs no new wire
 * command and no firmware change.
 *
 * **Sequential, and paced from here.** The sketch's `PULSE` is a blocking
 * `delay()`: the board opens the valve, waits, closes it, and only then reads
 * the next line. Firing every command at once would work — the serial buffer
 * holds them — but the app would have no idea which line was open. So each
 * pulse is sent when the previous one's time is up, plus a little slack, and
 * the board's own `STATUS` lines (`f1=1` … `f1=0`) light the row underneath as
 * the truth of what is happening.
 *
 * **Long primes are chunked.** The sketch caps a pulse at 5 s. A 12 s prime is
 * three 4 s pulses back to back on the same line — the valve closes and reopens
 * within a millisecond between them, which for pushing water down a tube is
 * the same as staying open.
 *
 * **The pulse width goes back when we are done.** `SET PULSE` is the sketch's
 * one global, shared with the grid's Pulse buttons; a prime that left it at
 * 4000 ms would turn the next "Pulse" click into a four-second flood.
 *
 * **Stop is `ALLOFF`.** The pulse in flight cannot be interrupted — the sketch
 * says so — but `ALLOFF` is always safe and always honoured the moment the
 * board is listening again, and the queue behind it is dropped here.
 */
export function PrimeControls({
  channels,
  canSend,
  currentPulseMs,
  isOpen,
  onSend,
}: {
  /** The fluid lines — rows of the profile's fluid grid that can pulse. */
  channels: ControlChannel[];
  canSend: boolean;
  /** The sketch's current pulse width from telemetry, to restore afterward. */
  currentPulseMs: number | null;
  /** Whether a channel's telemetry key currently reads open. */
  isOpen: (stateKey: string | undefined) => boolean;
  onSend: (command: string) => void;
}) {
  const primable = useMemo(() => channels.filter((c) => c.pulse), [channels]);

  const [seconds, setSeconds] = useState(3);
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(primable.map((c) => c.label)),
  );
  const [run, setRun] = useState<Run | null>(null);
  const [now, setNow] = useState(() => Date.now());

  // A row that is not in the selection is not queued; a selection that is
  // empty has nothing to prime. Kept as a set of LABELS because a channel's
  // label is its identity in the grid too.
  const toggleSelected = (label: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });

  const queue = useMemo(
    () => primable.filter((c) => selected.has(c.label)),
    [primable, selected],
  );

  const durationMs = Math.round(Math.min(MAX_SECONDS, Math.max(MIN_SECONDS, seconds)) * 1000);

  /* --- the run ----------------------------------------------------------- */

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearTimer = () => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  };

  const start = useCallback(() => {
    if (!canSend || queue.length === 0) return;
    // Equal chunks under the sketch's 5 s cap, so every pulse on a line is the
    // same length and the total is what was asked for.
    const chunks = Math.max(1, Math.ceil(durationMs / MAX_PULSE_MS));
    const chunkMs = Math.round(durationMs / chunks);
    const steps: Step[] = queue.flatMap((channel) =>
      Array.from({ length: chunks }, (_, i) => ({
        label: channel.label,
        state: channel.state,
        command: channel.pulse!,
        chunk: i,
        chunks,
      })),
    );
    onSend(`SET PULSE=${chunkMs}`);
    setRun({
      steps,
      index: 0,
      chunkMs,
      stepStartedAt: Date.now(),
      previousPulseMs: currentPulseMs,
      stopped: false,
    });
  }, [canSend, queue, durationMs, currentPulseMs, onSend]);

  const finish = useCallback(
    (current: Run, stopped: boolean) => {
      clearTimer();
      if (stopped) onSend("ALLOFF");
      // The sketch's one global, put back where the grid's Pulse buttons
      // expect it. Unknown (no telemetry yet) means leave it — we would only
      // be guessing at a number.
      if (current.previousPulseMs !== null) onSend(`SET PULSE=${current.previousPulseMs}`);
      setRun(null);
    },
    [onSend],
  );

  // Send the current step, then schedule the next when its time is up. The
  // slack covers serial latency and the sketch's own status report; without it
  // the next PULSE would land while the board is still inside its delay and
  // simply wait in the buffer — harmless, but the app's idea of "which line is
  // open" would drift ahead of the board's.
  useEffect(() => {
    if (!run || run.stopped) return;
    const step = run.steps[run.index];
    if (!step) {
      finish(run, false);
      return;
    }
    onSend(step.command);
    timer.current = setTimeout(() => {
      setRun((prev) =>
        prev && !prev.stopped
          ? { ...prev, index: prev.index + 1, stepStartedAt: Date.now() }
          : prev,
      );
    }, run.chunkMs + STEP_SLACK_MS);
    return clearTimer;
    // `run.index` is the thing that advances; the rest of `run` is stable for
    // the life of one prime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.index, run?.stopped]);

  // Losing passthrough mid-prime: the board will finish the pulse it is in and
  // close on its own; the queue here is meaningless without a port to send to.
  useEffect(() => {
    if (!canSend && run) {
      clearTimer();
      setRun(null);
    }
  }, [canSend, run]);

  // A clock for the countdown while priming, and only then.
  useEffect(() => {
    if (!run) return;
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, [run]);

  const stop = () => {
    if (!run) return;
    finish({ ...run, stopped: true }, true);
  };

  /* --- readouts ---------------------------------------------------------- */

  const total = run ? run.steps.length * run.chunkMs : queue.length * durationMs;
  const elapsed = run
    ? run.index * run.chunkMs + Math.min(run.chunkMs, now - run.stepStartedAt)
    : 0;
  const remaining = Math.max(0, total - elapsed);
  const current = run ? run.steps[run.index] : undefined;

  const stateOf = (label: string): "queued" | "priming" | "done" | "idle" => {
    if (!run) return "idle";
    const first = run.steps.findIndex((s) => s.label === label);
    const last = run.steps.map((s) => s.label).lastIndexOf(label);
    if (first === -1) return "idle";
    if (run.index > last) return "done";
    if (run.index >= first) return "priming";
    return "queued";
  };

  if (primable.length === 0) return null;

  return (
    <section
      className="mt-2 overflow-hidden rounded-md border"
      style={{
        // The section wears the reward family's colour on its rule — the same
        // colour these lines have on the board map and in every trial table —
        // and wears it brighter while a prime is running.
        borderColor: run ? REWARD : "var(--color-halo)",
        transition: "border-color 200ms",
      }}
    >
      <header className="flex items-center gap-2 border-b border-halo px-2.5 py-2">
        <Droplets size={15} strokeWidth={1.75} style={{ color: REWARD }} className="shrink-0" />
        <span className="text-[12px] font-medium text-starlight">Prime</span>
        <span className="min-w-0 flex-1 truncate text-[10px] text-static/70">
          run water down each line until it reaches the well
        </span>
      </header>

      {/* THE STATUS. While a prime runs this is the loudest thing in the tile:
          which line, how far through, how long is left, and the one control
          that matters. It replaces the form rather than sitting above it, so
          nothing can be re-armed mid-run. */}
      <AnimatePresence initial={false} mode="wait">
        {run && current ? (
          <motion.div
            key="running"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={springSnappy}
            className="px-2.5 py-2.5"
          >
            <div className="flex items-center gap-2">
              <motion.span
                aria-hidden
                className="size-2 shrink-0 rounded-full"
                style={{ background: REWARD }}
                animate={{ opacity: [1, 0.35, 1] }}
                transition={{ duration: 1.1, repeat: Infinity, ease: "easeInOut" }}
              />
              <span className="min-w-0 flex-1 truncate text-[12px] text-starlight">
                Priming <span className="font-medium">{current.label}</span>
                {current.chunks > 1 && (
                  <span className="font-mono text-[10px] text-static">
                    {" "}
                    · pass {current.chunk + 1}/{current.chunks}
                  </span>
                )}
              </span>
              <span className="shrink-0 font-mono text-[11px] tabular-nums text-starlight">
                {(remaining / 1000).toFixed(1)} s left
              </span>
              <Button variant="outline" onClick={stop} title="Close every line now (ALLOFF)">
                <Square size={11} strokeWidth={2} />
                Stop
              </Button>
            </div>
            {/* The bar: one segment per line, filling in turn. A single bar
                would say "how far"; segments also say "which". */}
            <div className="mt-2 flex gap-1" aria-hidden>
              {queueOf(run).map((label) => {
                const state = stateOf(label);
                const fraction =
                  state === "done"
                    ? 1
                    : state === "priming"
                      ? progressWithin(run, label, now)
                      : 0;
                return (
                  <span
                    key={label}
                    className="h-1.5 flex-1 overflow-hidden rounded-sm bg-halo/60"
                  >
                    <span
                      className="block h-full rounded-sm"
                      style={{
                        width: `${fraction * 100}%`,
                        background: REWARD,
                        transition: "width 100ms linear",
                      }}
                    />
                  </span>
                );
              })}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
              {queueOf(run).map((label) => (
                <LineChip
                  key={label}
                  label={label}
                  state={stateOf(label)}
                  lit={isOpen(run.steps.find((s) => s.label === label)?.state)}
                />
              ))}
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="form"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={springSnappy}
            className="flex flex-col gap-2.5 px-2.5 py-2.5"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[10px] uppercase tracking-wider text-static">
                for
              </span>
              <Segmented<string>
                label="Prime duration"
                value={PRESETS.includes(seconds) ? String(seconds) : "custom"}
                options={[
                  ...PRESETS.map((s) => ({ value: String(s), label: `${s} s` })),
                  { value: "custom", label: "…" },
                ]}
                onChange={(v) => {
                  if (v !== "custom") setSeconds(Number(v));
                }}
              />
              <NumberInput
                label="Prime duration in seconds"
                value={seconds}
                fallback={3}
                min={MIN_SECONDS}
                max={MAX_SECONDS}
                onChange={(n) => setSeconds(Math.min(MAX_SECONDS, Math.max(MIN_SECONDS, n)))}
                className="w-14"
                align="right"
              />
              <span className="font-mono text-[10px] text-static">s each</span>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <span className="mr-0.5 font-mono text-[10px] uppercase tracking-wider text-static">
                lines
              </span>
              {primable.map((channel) => {
                const on = selected.has(channel.label);
                return (
                  <button
                    key={channel.label}
                    type="button"
                    onClick={() => toggleSelected(channel.label)}
                    aria-pressed={on}
                    className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] transition-colors ${
                      on
                        ? "text-starlight"
                        : "border-halo text-static hover:text-starlight"
                    }`}
                    style={on ? { borderColor: REWARD, background: `color-mix(in srgb, ${REWARD} 16%, transparent)` } : undefined}
                  >
                    <span
                      aria-hidden
                      className="size-1.5 rounded-full"
                      style={{ background: on ? REWARD : "var(--color-halo)" }}
                    />
                    {channel.label}
                  </button>
                );
              })}
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="primary"
                onClick={start}
                disabled={!canSend || queue.length === 0}
                title={
                  !canSend
                    ? "Open passthrough to prime"
                    : queue.length === 0
                      ? "Pick at least one line"
                      : `Prime ${queue.length} line${queue.length === 1 ? "" : "s"}, ${seconds} s each`
                }
              >
                <Droplets size={13} strokeWidth={1.75} />
                Prime {queue.length} line{queue.length === 1 ? "" : "s"}
              </Button>
              <span className="font-mono text-[10px] text-static/70">
                {queue.length > 0 && `${((queue.length * durationMs) / 1000).toFixed(0)} s in all`}
                {durationMs > MAX_PULSE_MS &&
                  ` · in ${Math.ceil(durationMs / MAX_PULSE_MS)} passes per line`}
              </span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

/** One line's place in the run, as a chip: queued, priming (lit by the
 *  board's own telemetry, not by our timer), or done. */
function LineChip({
  label,
  state,
  lit,
}: {
  label: string;
  state: "queued" | "priming" | "done" | "idle";
  lit: boolean;
}) {
  return (
    <span
      className={`flex items-center gap-1 font-mono text-[10px] ${
        state === "priming" ? "text-starlight" : state === "done" ? "text-static" : "text-static/60"
      }`}
    >
      {state === "done" ? (
        <Check size={10} strokeWidth={2.25} style={{ color: "var(--color-status-ok)" }} />
      ) : (
        <motion.span
          aria-hidden
          className="size-1.5 rounded-full"
          animate={{
            background: state === "priming" && lit ? REWARD : "var(--color-halo)",
            scale: state === "priming" && lit ? 1.35 : 1,
          }}
          transition={springSnappy}
        />
      )}
      {label}
    </span>
  );
}

interface Step {
  label: string;
  state: string | undefined;
  command: string;
  chunk: number;
  chunks: number;
}

interface Run {
  steps: Step[];
  index: number;
  chunkMs: number;
  stepStartedAt: number;
  previousPulseMs: number | null;
  stopped: boolean;
}

function queueOf(run: Run): string[] {
  return [...new Set(run.steps.map((s) => s.label))];
}

/** How far through ALL of a line's chunks the run is, 0..1. */
function progressWithin(run: Run, label: string, now: number): number {
  const mine = run.steps.filter((s) => s.label === label);
  const first = run.steps.findIndex((s) => s.label === label);
  const done = run.index - first;
  const inStep = Math.min(1, Math.max(0, (now - run.stepStartedAt) / run.chunkMs));
  return Math.min(1, (done + inStep) / mine.length);
}

/** The reward family's colour — what these lines wear everywhere else. */
const REWARD = KIND_COLOR["reward"] ?? "var(--color-pulsar)";

/** The sketch's own cap on one pulse (`PULSE_MAX_MS`). */
const MAX_PULSE_MS = 5000;
/** Slack after each pulse before the next is sent: serial latency plus the
 *  sketch's status report. */
const STEP_SLACK_MS = 120;

const PRESETS = [1, 3, 5, 10];
const MIN_SECONDS = 0.5;
const MAX_SECONDS = 60;

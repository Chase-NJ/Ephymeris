import { motion } from "framer-motion";
import { ArrowRight, AudioWaveform } from "lucide-react";

import { useIntanStatus } from "@/lib/intan/context";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The Dashboard's second way in: a session that is also an Intan recording
 * (`recording.md` §4).
 *
 * A `.hud` tile, NOT a second solid button. The solid Pulsar tile above it is
 * the primary action and the one opaque thing in the column on purpose
 * (`LaunchButton`); two of them would be two primaries. This one is glass like
 * everything else over the sky, and earns its place with what it knows: the
 * line under the title is RHX's live state, so whether a recording can start
 * is answered before the operator commits to the walkthrough.
 *
 * The footer link to the Recording tab appears only while RHX is NOT
 * connected — exactly when the tile's own click cannot repair the situation,
 * and the Boxes readout's rule for a link (`dashboard.md` §3.2). A sibling of
 * the button rather than inside it: a link in a button is invalid HTML.
 *
 * Hidden while a session runs — the tile above has become Resume, and a second
 * door into a flow that is already open would only be a way to get lost.
 */
export function RecordingTile({
  disabled,
  onOpen,
  onSettings,
}: {
  disabled: boolean;
  onOpen: () => void;
  onSettings: () => void;
}) {
  const intan = useIntanStatus();
  const reduceMotion = useReduceMotion();

  const fact = intan.connected
    ? `RHX ${intan.version ?? ""} · ${intan.sampleRate ? `${intan.sampleRate / 1000} kS/s` : "—"}${
        intan.synthetic ? " · synthetic" : ""
      }`
    : "RHX not connected — press Connect in RHX";

  return (
    <motion.div
      initial="idle"
      animate="idle"
      whileHover={disabled ? "idle" : "hover"}
      variants={{ idle: { y: 0 }, hover: { y: -2 } }}
      transition={springSnappy}
      className={`hud group flex flex-col rounded-lg transition-colors ${
        disabled ? "" : "hover:border-static/40"
      }`}
    >
      <motion.button
        type="button"
        whileTap={disabled ? {} : { scale: 0.985 }}
        disabled={disabled}
        title={disabled ? "Create a cohort first" : undefined}
        onClick={onOpen}
        // Only the button dims when there is nothing to start: the footer's
        // link to the Recording tab is exactly as live as before.
        className="flex w-full items-center gap-4 py-3.5 pl-5 pr-5 text-left disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span className="relative flex h-6 w-6 shrink-0 items-center justify-center" aria-hidden>
          <AudioWaveform size={22} strokeWidth={1.6} className="text-pulsar" />
          {/* The trace's sync pulse: one flat tick that steps across on hover.
              Matte, no glow — the accent's rule holds here too. */}
          {!reduceMotion && (
            <motion.span
              variants={{
                idle: { opacity: 0, x: -8 },
                hover: {
                  opacity: [0, 1, 1, 0],
                  x: [-8, 8],
                  transition: { duration: 1.1, repeat: Infinity, ease: "linear" },
                },
              }}
              transition={springSnappy}
              className="absolute bottom-[-3px] h-[3px] w-[3px] rounded-full bg-ion"
            />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-display text-[15px] font-semibold text-starlight">
            Start a Recording
          </span>
          <span className="mt-0.5 flex items-center gap-1.5 text-[12px] text-static">
            <span
              aria-hidden
              className="size-[6px] shrink-0 rounded-full"
              style={{ background: intan.connected ? "var(--color-ion)" : "var(--color-static)" }}
            />
            <span className="truncate">{fact}</span>
          </span>
        </span>
        <ArrowRight
          size={16}
          strokeWidth={2}
          className="shrink-0 text-static transition-transform group-hover:translate-x-0.5 group-hover:text-starlight"
        />
      </motion.button>

      {!intan.connected && (
        <div className="border-t border-halo px-5 py-1.5">
          <button
            type="button"
            onClick={onSettings}
            className="flex items-center gap-1 font-mono text-[10px] text-static/80 transition-colors hover:text-starlight"
          >
            Recording settings
            <ArrowRight size={10} strokeWidth={2} />
          </button>
        </div>
      )}
    </motion.div>
  );
}

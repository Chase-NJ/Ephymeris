import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { useMemo, useState } from "react";

import { springSnappy } from "@/lib/motion";
import { setAt, topologyOf } from "@/lib/specs/document";
import { BAND_LABELS, bandReadouts } from "@/lib/specs/layout";
import type { SpecDocument } from "@/lib/specs/types";

/**
 * What the task is, so far — the thing being built, kept in view while it is.
 *
 * THIS IS NOT THE MACHINE GRAPH, and the distinction is the point. `SpecCanvas`
 * draws the compiled state machine: twenty-six nodes, thirty-six edges, every
 * penalty branch and paired strobe. That is the right picture for the Designer,
 * where the subject IS the machine — and the wrong one for someone who has not
 * yet decided how many odours there are, because the answer to "what have I got"
 * is buried in a diagram that restructures itself on every keystroke.
 *
 * So this draws the four things an operator is actually choosing between: what
 * begins a trial, what is presented, where it can be answered, and what each
 * ending is worth. Three of those are a line of text. The fourth — which
 * stimulus means which port — is the whole task, and gets the room.
 */
export function TaskShape({
  doc,
  pins,
  focus,
  onChange,
}: {
  doc: SpecDocument;
  /** Channel name → pin, from the rig. Empty until `hardware.get` lands. */
  pins: Record<string, number>;
  /** The band the current step edits, lit so the picture tracks the walk. */
  focus: number | null;
  onChange: (next: SpecDocument) => void;
}) {
  const knobs = topologyOf(doc);
  const readouts = bandReadouts(knobs);
  const ports = portsOf(doc);
  const trials = trialTypesOf(doc);
  const goNoGo = knobs?.["response_mode"] === "go_nogo";

  return (
    <div className="hud rounded-md px-4 py-3.5">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <div className="font-display text-[13px] tracking-wide text-static uppercase">
          The task so far
        </div>
        <div className="font-mono text-[10px] text-static/70">
          {trials.length} trial type{trials.length === 1 ? "" : "s"} ·{" "}
          {stimuliOf(doc).length} stimul{stimuliOf(doc).length === 1 ? "us" : "i"} ·{" "}
          {Object.keys(ports).length} port{Object.keys(ports).length === 1 ? "" : "s"}
        </div>
      </div>

      {/* The four epochs, in trial order, each one line. Lit when the current
          step is the one that edits it — so the walk has a place on the map
          rather than only a number in the rail. */}
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        {[1, 2, 3, 4].map((band) => (
          <motion.div
            key={band}
            animate={{
              borderColor:
                focus === band ? "var(--color-pulsar)" : "var(--color-halo)",
            }}
            transition={springSnappy}
            className="min-w-0 rounded-[3px] border px-2 py-1.5"
          >
            <div
              className={`truncate font-mono text-[10px] ${
                focus === band ? "text-starlight" : "text-static"
              }`}
            >
              {band} · {BAND_LABELS[band]}
            </div>
            <div className="mt-0.5 truncate text-[10px] text-static/80">
              {band === 4 ? outcomeReadout(doc) : readouts[band] || "—"}
            </div>
          </motion.div>
        ))}
      </div>

      {/* THE MAPPING, which is the task. Everything above is a caption for it. */}
      <div className="mt-3">
        {trials.length === 0 ? (
          <p className="text-[11px] leading-relaxed text-static">
            No trial types yet — nothing to present. Add one on the{" "}
            <span className="text-starlight">How does it answer?</span> step.
          </p>
        ) : (
          <TrialTypeMap
            doc={doc}
            trials={trials}
            ports={ports}
            pins={pins}
            goNoGo={goNoGo}
            onChange={onChange}
          />
        )}
      </div>
    </div>
  );
}

/**
 * One row per trial type: what is presented, then where that means to answer.
 *
 * The stages are DRAGGABLE when there is more than one, which is the same
 * affordance the old standalone "Presentation order" block carried — folded in
 * here because a chain of stimuli and the target it points at are one fact, and
 * showing them in two places invites them to disagree. One stage means nothing
 * to order, so the chips render without the drag chrome rather than inviting a
 * gesture that cannot do anything.
 *
 * Hand-rolled, because there is no drag library in this repo and adding one for
 * this would be the wrong trade. It copies `CrewChip`'s arrangement exactly: a
 * plain `<button draggable>` INSIDE a `motion.span layout`, because on a motion
 * component `onDragStart` is framer's pan-gesture prop and the native event is
 * never heard. Click-to-carry is a fallback and not a nicety, for the reason the
 * board map gives — HTML5 drag works here only because `dragDropEnabled: false`
 * is set in tauri.conf.json, and the lab runs Windows.
 */
function TrialTypeMap({
  doc,
  trials,
  ports,
  pins,
  goNoGo,
  onChange,
}: {
  doc: SpecDocument;
  trials: Record<string, unknown>[];
  ports: Record<string, Record<string, unknown>>;
  pins: Record<string, number>;
  goNoGo: boolean;
  onChange: (next: SpecDocument) => void;
}) {
  const [carried, setCarried] = useState<{ trial: number; at: number } | null>(null);
  const [over, setOver] = useState<{ trial: number; at: number } | null>(null);

  const orderable = useMemo(
    () => trials.some((t) => ((t["stages"] as string[]) ?? []).length > 1),
    [trials],
  );

  function move(trial: number, from: number, to: number) {
    const order = [...((trials[trial]?.["stages"] as string[]) ?? [])];
    if (from === to || from < 0 || to < 0 || from >= order.length || to >= order.length) {
      setCarried(null);
      setOver(null);
      return;
    }
    const [lifted] = order.splice(from, 1);
    order.splice(to, 0, lifted as string);
    onChange(setAt(doc, `contingency.trial_types[${trial}].stages`, order));
    setCarried(null);
    setOver(null);
  }

  return (
    <div className="flex flex-col gap-1">
      {orderable && (
        <p className="mb-0.5 text-[10px] leading-relaxed text-static/80">
          Drag a stimulus to reorder it, or click one and then click where it
          goes. Order is the discriminandum in a sequence task — A then B and B
          then A are different trials, not the same trial shuffled.
        </p>
      )}

      {trials.map((row, ti) => {
        const id = String(row["id"] ?? ti);
        const stages = (row["stages"] as string[]) ?? [];
        const target = typeof row["target"] === "string" ? row["target"] : null;
        const weight = row["weight"];
        const binding = target ? ports[target] : undefined;
        const channel = binding ? String(binding["channel"] ?? target) : null;
        const pin = channel === null ? undefined : pins[channel];

        return (
          <div
            key={id}
            className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-[3px] border border-halo px-2 py-1.5"
          >
            <span className="w-[150px] shrink-0 truncate font-mono text-[10px] text-static/70">
              {id}
            </span>

            <div className="flex flex-wrap items-center gap-1">
              {stages.length === 0 ? (
                <span className="text-[10.5px] text-static/60">nothing presented</span>
              ) : (
                stages.map((stim, si) => (
                  <motion.span
                    key={`${id}-${si}-${stim}`}
                    layout
                    transition={springSnappy}
                    onDragOver={(e: React.DragEvent) => {
                      if (!orderable) return;
                      e.preventDefault();
                      setOver({ trial: ti, at: si });
                    }}
                    onDragLeave={() => setOver(null)}
                    onDrop={(e: React.DragEvent) => {
                      if (!orderable) return;
                      e.preventDefault();
                      const from = Number(e.dataTransfer.getData("text/plain"));
                      if (Number.isInteger(from)) move(ti, from, si);
                    }}
                  >
                    <button
                      type="button"
                      draggable={orderable}
                      disabled={!orderable}
                      onDragStart={(e) =>
                        e.dataTransfer.setData("text/plain", String(si))
                      }
                      onClick={() =>
                        carried === null || carried.trial !== ti
                          ? setCarried({ trial: ti, at: si })
                          : move(ti, carried.at, si)
                      }
                      title={
                        !orderable
                          ? stim
                          : carried === null
                            ? "Drag to reorder, or click to pick up"
                            : "Click to drop here"
                      }
                      className={`rounded-sm border px-2 py-0.5 font-mono text-[10.5px] transition-colors ${
                        orderable ? "cursor-grab active:cursor-grabbing" : "cursor-default"
                      }`}
                      style={{
                        borderColor:
                          (carried?.trial === ti && carried.at === si) ||
                          (over?.trial === ti && over.at === si)
                            ? "var(--color-pulsar)"
                            : "var(--color-halo)",
                        color:
                          carried?.trial === ti && carried.at === si
                            ? "var(--color-starlight)"
                            : "var(--color-static)",
                        background:
                          carried?.trial === ti && carried.at === si
                            ? "color-mix(in srgb, var(--color-pulsar) 18%, transparent)"
                            : "var(--color-void)",
                      }}
                    >
                      {stages.length > 1 && (
                        <span className="mr-1 text-[9px] opacity-60">{si + 1}</span>
                      )}
                      {stim}
                    </button>
                  </motion.span>
                ))
              )}
            </div>

            <ArrowRight
              size={12}
              strokeWidth={1.75}
              className="shrink-0 text-static/50"
            />

            {/* WHAT COUNTS AS CORRECT. A withhold task declares no target at
                all — success is the response window expiring — so naming a port
                here would be inventing one. */}
            {goNoGo ? (
              <span className="font-mono text-[10.5px] text-static">withhold</span>
            ) : target === null ? (
              <span className="font-mono text-[10.5px] text-static/60">no target</span>
            ) : (
              <span className="min-w-0 truncate font-mono text-[10.5px] text-starlight">
                {target}
                <span className="ml-1.5 text-[9.5px] text-static/70">
                  {pin === undefined ? "not wired" : `pin ${pin}`}
                </span>
              </span>
            )}

            {typeof weight === "number" && weight !== 1 && (
              <span
                className="ml-auto shrink-0 font-mono text-[9.5px]"
                style={{
                  color:
                    weight === 0 ? "var(--color-static)" : "var(--color-pulsar)",
                }}
                title={
                  weight === 0
                    ? "Never drawn — in the pool but weighted out, which is how a shaping ramp turns an arm on later"
                    : `Drawn ${weight}× as often as a weight-1 type`
                }
              >
                ×{weight}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Band 4's one line. `bandReadouts` leaves it blank — the outcome epoch's
 *  shape is the contingency's outcome map rather than a topology knob. */
function outcomeReadout(doc: SpecDocument): string {
  const map = asRec(asRec(doc["contingency"])?.["outcome_map"]);
  if (map === null) return "—";
  const classes = Object.keys(map).length;
  const rewarded = asRec(map["correct"])?.["reward"] != null;
  return `${classes} outcome${classes === 1 ? "" : "s"} · ${rewarded ? "rewarded" : "no reward"}`;
}

function asRec(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function portsOf(doc: SpecDocument): Record<string, Record<string, unknown>> {
  const ports = asRec(asRec(doc["contingency"])?.["ports"]);
  const out: Record<string, Record<string, unknown>> = {};
  for (const [name, binding] of Object.entries(ports ?? {})) {
    const rec = asRec(binding);
    if (rec) out[name] = rec;
  }
  return out;
}

function stimuliOf(doc: SpecDocument): Record<string, unknown>[] {
  const list = asRec(doc["contingency"])?.["stimuli"];
  return Array.isArray(list) ? list.filter((s): s is Record<string, unknown> => asRec(s) !== null) : [];
}

function trialTypesOf(doc: SpecDocument): Record<string, unknown>[] {
  const list = asRec(doc["contingency"])?.["trial_types"];
  return Array.isArray(list) ? list.filter((t): t is Record<string, unknown> => asRec(t) !== null) : [];
}

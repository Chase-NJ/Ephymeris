import { AnimatePresence, motion } from "framer-motion";
import { Plus, X } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/common/controls";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";
import type { PlacedDiagnostics } from "@/lib/specs/diagnostics";
import { getAt, setAt, topologyOf } from "@/lib/specs/document";
import { runOp, type OpContext, type OpResult } from "@/lib/specs/operations";
import type {
  ChannelRegistry,
  SpecCapabilities,
  SpecDocument,
  SpecSchema,
  StrobeRegistry,
} from "@/lib/specs/types";
import { SpecField } from "./SpecField";

/**
 * The answer space, as the hardware it is — and the mapping onto it, as a drag.
 *
 * WHAT THIS REPLACES AND WHY. Answering used to be three buttons ("Add a
 * response option", "Add a trial type", "Remove <port>") over a read-only pad
 * list, with the stimulus→port mapping shown somewhere else entirely, in
 * `TaskShape`'s rows. Two surfaces for one fact, and neither of them looked
 * like the box. Here the tiles ARE the response channels the rig declares, and
 * dropping a stimulus on one is what creates the trial type that says so.
 *
 * THE PALETTE IS THE REGISTRY, NOT THE DOCUMENT. Every `kind: response`
 * channel gets a tile whether or not this task uses it, because "which ports
 * could this box answer at" is a fact about the rig and the operator is
 * choosing among them. That is also what makes the ceiling honest: there is no
 * number here saying how many response ports are allowed — the registry has as
 * many as Rig wiring says, and a rig with a third one grows a third tile with
 * no edit to this file.
 *
 * EVERY GESTURE HAS A CLICK TWIN. HTML5 drag works in this app only because
 * `dragDropEnabled: false` is set in tauri.conf.json, and the lab runs Windows
 * where none of it has been tried — so click-to-carry is the supported path and
 * dragging is the nicety, not the other way round. Same recipe as
 * `CageAssignment`: a plain `<button draggable>` INSIDE a `motion.span layout`,
 * because on a motion component `onDragStart` is framer's pan gesture and the
 * native event is never heard.
 *
 * STRUCTURE STILL GOES THROUGH THE OPS. Binding a port is `addResponseOption`,
 * unbinding is `removeResponseOption`, a drop is `addTrialType`, a drag-off is
 * `removeTrialType` — the same pure functions the Designer's blocks run, so
 * this surface cannot invent an edit the editor would not make. Only re-aiming
 * an existing trial type is a plain `setAt`, because a target moving between
 * two ports that both already exist crosses no invariant.
 */
export function ResponseMap({
  doc,
  caps,
  schema,
  placed,
  pins,
  onChange,
}: {
  doc: SpecDocument;
  caps: SpecCapabilities | null;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  pins: Record<string, number>;
  onChange: (next: SpecDocument) => void;
}) {
  const [carried, setCarried] = useState<Carried | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);
  const still = useReduceMotion();

  const knobs = topologyOf(doc) ?? {};
  const goNoGo = knobs["response_mode"] === "go_nogo";
  const stimuli = stimuliOf(doc);
  const trials = trialTypesOf(doc);
  const ports = portsOf(doc);
  const boundPorts = responsePortsOf(doc);

  const channels = useMemo(() => {
    const reg = (schema.channels ?? {}) as ChannelRegistry;
    return Object.entries(reg.channels ?? {})
      .filter(([, c]) => c.kind === "response")
      .sort(([, a], [, b]) => a.index - b.index);
  }, [schema.channels]);

  const ctx: OpContext | null =
    caps === null
      ? null
      : {
          doc,
          caps,
          next: caps,
          channels: (schema.channels ?? {}) as ChannelRegistry,
          strobes: (schema.strobes ?? {}) as StrobeRegistry,
        };

  /** Run an op, adopting its document — or surface why it refused. */
  function apply(result: OpResult | null): void {
    if (result === null) return;
    if (result.preflight.blocked !== null) {
      setBlocked(result.preflight.blocked);
      return;
    }
    setBlocked(null);
    onChange(result.doc);
  }

  /** Which port a channel is bound through, if any. */
  function portOn(channel: string): string | null {
    for (const [name, binding] of Object.entries(ports)) {
      if (String(binding["channel"] ?? name) === channel && boundPorts.includes(name)) {
        return name;
      }
    }
    return null;
  }

  function drop(port: string | null): void {
    if (carried === null || ctx === null) return;
    const landing = carried;
    setCarried(null);
    setOver(null);

    if (landing.kind === "stimulus") {
      // A drop CREATES the trial type, and the gesture answers the two
      // questions `addTrialType` would otherwise ask; everything else it asks
      // falls back to its own sibling-seeded suggestion.
      apply(
        runOp(ctx, { op: "addTrialType" }, {
          trial_type_stage_0: landing.id,
          ...(port === null ? {} : { trial_type_target: port }),
        }),
      );
      return;
    }
    // Re-aiming an existing trial type: both ports already exist, so no
    // invariant crosses and this is one path write.
    const index = trials.findIndex((t) => String(t["id"] ?? "") === landing.id);
    if (index < 0 || port === null) return;
    if (String(trials[index]?.["target"] ?? "") === port) return;
    setBlocked(null);
    onChange(setAt(doc, `contingency.trial_types[${index}].target`, port));
  }

  const unmapped = stimuli.filter(
    (s) =>
      !trials.some((t) =>
        ((t["stages"] as unknown[]) ?? []).some((x) => String(x) === String(s["id"] ?? "")),
      ),
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <div className="font-mono text-[10px] tracking-wider text-static uppercase">
          Where it can answer
        </div>
        <div className="font-mono text-[10px] text-static/70">
          {carried
            ? "click a port to drop it there"
            : goNoGo
              ? "withholding is correct — no port is a target"
              : `${trials.length} mapping${trials.length === 1 ? "" : "s"}`}
        </div>
      </div>

      {stimuli.length === 0 && (
        <p className="rounded-sm border border-halo px-2.5 py-2 text-[10.5px] leading-relaxed text-static">
          No stimuli yet — go back a step and add what the animal samples. There
          is nothing to map onto a port until something can be presented.
        </p>
      )}

      {/* THE TILES. One per response channel the rig declares, bound or not. */}
      <div className="grid gap-1.5 sm:grid-cols-2">
        {channels.map(([channel]) => {
          const port = portOn(channel);
          const mine = port === null ? [] : trials.filter((t) => t["target"] === port);
          const isOver = over === channel;
          return (
            <div
              key={channel}
              onDragOver={(e: React.DragEvent) => {
                if (port === null || goNoGo) return;
                e.preventDefault();
                setOver(channel);
              }}
              onDragLeave={() => setOver(null)}
              onDrop={(e: React.DragEvent) => {
                e.preventDefault();
                if (port !== null && !goNoGo) drop(port);
              }}
              onClick={() => {
                if (carried !== null && port !== null && !goNoGo) drop(port);
              }}
              className="flex min-w-0 flex-col gap-1 rounded-[3px] border px-2 py-1.5 transition-colors"
              style={{
                borderColor: isOver ? "var(--color-pulsar)" : "var(--color-halo)",
                background: isOver
                  ? "color-mix(in srgb, var(--color-pulsar) 10%, transparent)"
                  : "transparent",
                opacity: port === null ? 0.75 : 1,
                cursor: carried !== null && port !== null && !goNoGo ? "pointer" : "default",
              }}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 truncate font-mono text-[11px] text-starlight">
                  {port ?? channel}
                </span>
                <span className="shrink-0 font-mono text-[9.5px] text-static/70">
                  {pins[channel] === undefined ? "not wired" : `pin ${pins[channel]}`}
                </span>
              </div>
              <div className="truncate font-mono text-[9.5px] text-static">
                {channel}
                {port !== null && rewardLine(ports[port]) !== null && (
                  <> · {rewardLine(ports[port])}</>
                )}
              </div>

              {port === null ? (
                <Button
                  variant="ghost"
                  onClick={() =>
                    apply(ctx && runOp(ctx, { op: "addResponseOption", channel }, {}))
                  }
                >
                  <Plus size={11} strokeWidth={2} />
                  Answer here too
                </Button>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-1">
                    {mine.length === 0 ? (
                      <span className="text-[10px] text-static/60">
                        {goNoGo ? "watched, never correct" : "nothing maps here yet"}
                      </span>
                    ) : (
                      mine.map((t) => {
                        const id = String(t["id"] ?? "");
                        return (
                          <TrialChip
                            key={id}
                            id={id}
                            stages={((t["stages"] as unknown[]) ?? []).map(String)}
                            carried={carried?.kind === "trial" && carried.id === id}
                            onCarry={() =>
                              setCarried((c) =>
                                c?.kind === "trial" && c.id === id
                                  ? null
                                  : { kind: "trial", id },
                              )
                            }
                            onExpand={() => setExpanded((e) => (e === id ? null : id))}
                            expanded={expanded === id}
                            onRemove={() =>
                              apply(ctx && runOp(ctx, { op: "removeTrialType", id }, {}))
                            }
                          />
                        );
                      })
                    )}
                  </div>
                  {boundPorts.length > 1 && (
                    <Button
                      variant="ghost"
                      onClick={() =>
                        apply(ctx && runOp(ctx, { op: "removeResponseOption", port }, {}))
                      }
                    >
                      Stop answering here
                    </Button>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>

      {/* THE STIMULI, as things to pick up. Every one of them, not only the
      unmapped: presenting the same odour on two trial types is a legitimate
      task (a reversal declares exactly that), so the palette does not hide a
      stimulus once it has been used once. */}
      {stimuli.length > 0 && !goNoGo && (
        <div className="flex flex-col gap-1 rounded-sm border border-halo px-2.5 py-2">
          <div className="font-mono text-[10px] tracking-wider text-static uppercase">
            What it can be shown
          </div>
          <p className="text-[10px] leading-relaxed text-static/80">
            Drag a stimulus onto the port it should mean, or click it and then
            click the port. That is what creates a trial type.
          </p>
          <div className="flex flex-wrap items-center gap-1">
            {stimuli.map((s) => {
              const id = String(s["id"] ?? "");
              const isCarried = carried?.kind === "stimulus" && carried.id === id;
              const isUnmapped = unmapped.some((u) => String(u["id"] ?? "") === id);
              return (
                <motion.span key={id} layout transition={springSnappy}>
                  <button
                    type="button"
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData("text/plain", id);
                      setCarried({ kind: "stimulus", id });
                    }}
                    onDragEnd={() => setCarried(null)}
                    onClick={() =>
                      setCarried((c) =>
                        c?.kind === "stimulus" && c.id === id
                          ? null
                          : { kind: "stimulus", id },
                      )
                    }
                    title={
                      isCarried
                        ? "Click a port to drop it there"
                        : "Drag to a port, or click to pick up"
                    }
                    className="cursor-grab rounded-sm border px-2 py-0.5 font-mono text-[10.5px] transition-colors active:cursor-grabbing"
                    style={{
                      borderColor: isCarried
                        ? "var(--color-pulsar)"
                        : isUnmapped
                          ? "var(--color-status-warning)"
                          : "var(--color-halo)",
                      color: isCarried ? "var(--color-starlight)" : "var(--color-static)",
                      background: isCarried
                        ? "color-mix(in srgb, var(--color-pulsar) 18%, transparent)"
                        : "var(--color-void)",
                    }}
                  >
                    {id}
                  </button>
                </motion.span>
              );
            })}
          </div>
          {unmapped.length > 0 && (
            <p className="text-[10px] leading-relaxed text-static/70">
              {unmapped.map((s) => String(s["id"] ?? "")).join(", ")} —{" "}
              {unmapped.length === 1 ? "is" : "are"} never presented. A stimulus
              no trial type names is delivered by nothing.
            </p>
          )}
        </div>
      )}

      {blocked !== null && (
        <p
          className="rounded-sm border px-2.5 py-2 text-[10.5px] leading-relaxed"
          style={{
            color: "var(--color-status-warning)",
            borderColor: "var(--color-status-warning)",
          }}
        >
          {blocked}
        </p>
      )}

      {/* THE EXPANDED MAPPING. Its own row rather than inside the tile: the
      tiles are a grid, and growing one cell would push its neighbour's tile
      down and make the row jump. */}
      <ExpandedTrial
        id={expanded}
        still={still}
        doc={doc}
        schema={schema}
        placed={placed}
        onChange={onChange}
      />
    </div>
  );
}

type Carried = { kind: "stimulus" | "trial"; id: string };

/**
 * One mapping, on the port it points at.
 *
 * Draggable so it can be re-aimed at another port, clickable to expand, and
 * carrying its own remove — the three things you can do to a mapping, on the
 * thing itself rather than in a list somewhere else.
 */
function TrialChip({
  id,
  stages,
  carried,
  expanded,
  onCarry,
  onExpand,
  onRemove,
}: {
  id: string;
  stages: string[];
  carried: boolean;
  expanded: boolean;
  onCarry: () => void;
  onExpand: () => void;
  onRemove: () => void;
}) {
  return (
    <motion.span layout transition={springSnappy} className="inline-flex items-stretch">
      <button
        type="button"
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData("text/plain", id);
          onCarry();
        }}
        onDragEnd={() => carried && onCarry()}
        onClick={(e) => {
          e.stopPropagation();
          onExpand();
        }}
        title={`${stages.join(" → ") || "nothing presented"} — click to tune, drag to re-aim`}
        className="cursor-grab rounded-l-sm border py-0.5 pl-2 pr-1.5 font-mono text-[10.5px] transition-colors active:cursor-grabbing"
        style={{
          borderColor:
            carried || expanded ? "var(--color-pulsar)" : "var(--color-halo)",
          color: expanded ? "var(--color-starlight)" : "var(--color-static)",
          background: carried
            ? "color-mix(in srgb, var(--color-pulsar) 18%, transparent)"
            : "var(--color-void)",
        }}
      >
        {stages.join(" → ") || id}
      </button>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        title={`Remove ${id}`}
        className="rounded-r-sm border border-l-0 px-1 text-static transition-colors hover:text-starlight"
        style={{ borderColor: carried || expanded ? "var(--color-pulsar)" : "var(--color-halo)" }}
      >
        <X size={9} strokeWidth={2} />
      </button>
    </motion.span>
  );
}

/**
 * A mapping's own parameters, revealed in place.
 *
 * The port's strobes and reward line sit here beside the trial type's weight
 * because from the operator's side they are one fact — "what happens when the
 * animal answers HERE" — even though the document keeps them in two blocks.
 * Rendered through `SpecField` so labels, widgets and diagnostic placement stay
 * the presentation overlay's job rather than this file's.
 */
function ExpandedTrial({
  id,
  still,
  doc,
  schema,
  placed,
  onChange,
}: {
  id: string | null;
  /** Reduced motion: the panel appears rather than growing. */
  still: boolean;
  doc: SpecDocument;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  onChange: (next: SpecDocument) => void;
}) {
  const trials = trialTypesOf(doc);
  const index = id === null ? -1 : trials.findIndex((t) => String(t["id"] ?? "") === id);
  const trial = index < 0 ? null : trials[index];
  const port = typeof trial?.["target"] === "string" ? trial["target"] : null;

  return (
    <AnimatePresence initial={false}>
      {trial !== null && (
        <motion.div
          key={id}
          initial={still ? false : { height: 0, opacity: 0 }}
          animate={still ? { height: "auto", opacity: 1 } : { height: "auto", opacity: 1 }}
          exit={still ? { opacity: 0 } : { height: 0, opacity: 0 }}
          transition={still ? { duration: 0 } : springSnappy}
          className="overflow-hidden"
        >
          <div className="flex flex-col gap-1.5 rounded-sm border border-pulsar/40 px-2.5 py-2">
            <div className="font-mono text-[10px] tracking-wider text-static uppercase">
              {id} {port === null ? "· withhold" : `→ ${port}`}
            </div>

            <Row
              path={`contingency.trial_types[${index}].weight`}
              overlayKey="contingency.trial_types.*.weight"
              {...{ doc, schema, placed, onChange }}
            />

            {port !== null &&
              PORT_FIELDS.map((field) => (
                <Row
                  key={field}
                  path={`contingency.ports.${port}.${field}`}
                  overlayKey={`contingency.ports.*.${field}`}
                  {...{ doc, schema, placed, onChange }}
                />
              ))}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** In the order a trial passes through them, not the schema's order. */
const PORT_FIELDS = [
  "enter_code",
  "error_code",
  "break_code",
  "exit_code",
  "reward_line",
  "reward_duration",
  "reward_code",
  "reward_stop_code",
];

function Row({
  path,
  overlayKey,
  doc,
  schema,
  placed,
  onChange,
}: {
  path: string;
  overlayKey: string;
  doc: SpecDocument;
  schema: SpecSchema;
  placed: PlacedDiagnostics | null;
  onChange: (next: SpecDocument) => void;
}) {
  const meta = schema.overlay.fields[overlayKey];
  if (!meta) return null;
  // A field the document does not carry is not rendered blank — an absent
  // `reward_line` MEANS this port never rewards, and offering an empty input
  // for it would invite someone to think it was unset rather than declared.
  if (getAt(doc, path) === undefined) return null;
  return (
    <SpecField
      path={path}
      overlayKey={overlayKey}
      meta={meta}
      value={getAt(doc, path)}
      baseline={getAt(doc, path)}
      schema={schema}
      doc={doc}
      placed={placed}
      onChange={(next) => onChange(setAt(doc, path, next))}
    />
  );
}

/* ---- document accessors, loose like everywhere else in this domain ------ */

function asRec(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function stimuliOf(doc: SpecDocument): Record<string, unknown>[] {
  const list = asRec(doc["contingency"])?.["stimuli"];
  return Array.isArray(list) ? list.flatMap((s) => (asRec(s) ? [asRec(s)!] : [])) : [];
}

function trialTypesOf(doc: SpecDocument): Record<string, unknown>[] {
  const list = asRec(doc["contingency"])?.["trial_types"];
  return Array.isArray(list) ? list.flatMap((t) => (asRec(t) ? [asRec(t)!] : [])) : [];
}

function portsOf(doc: SpecDocument): Record<string, Record<string, unknown>> {
  const ports = asRec(asRec(doc["contingency"])?.["ports"]) ?? {};
  const out: Record<string, Record<string, unknown>> = {};
  for (const [name, binding] of Object.entries(ports)) {
    const rec = asRec(binding);
    if (rec) out[name] = rec;
  }
  return out;
}

function responsePortsOf(doc: SpecDocument): string[] {
  const rp = topologyOf(doc)?.["response_ports"];
  return Array.isArray(rp) ? rp.map(String) : [];
}

function rewardLine(binding: Record<string, unknown> | undefined): string | null {
  const line = binding?.["reward_line"];
  return typeof line === "string" ? line : null;
}

import { motion } from "framer-motion";
import {
  ArrowRight,
  CircleAlert,
  Copy,
  CpuIcon,
  FileCode2,
  Plus,
  Waypoints,
  Workflow,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { Button } from "@/components/common/controls";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { errorMessage } from "@/lib/cohorts/commands";
import { PANEL_TRAVEL, springPanel } from "@/lib/motion";
import { getSpec } from "@/lib/specs/commands";
import { createSpecFrom, suggestId } from "@/lib/specs/create";
import type { ParadigmSummary, SpecEntry } from "@/lib/specs/types";
import { originChip } from "@/lib/specs/useSpecDocument";
import { useParadigms, useSpecs } from "@/lib/specs/useSpecs";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";

/**
 * Task — the landing page for everything the animal is asked to do.
 *
 * The tab used to be one scrolling page carrying two whole systems: the spec
 * workbench and, beneath it, the sketch library with its derived trial-flow
 * graph and forty-odd parameter tiles. Everything was visible at once and
 * nothing was the front door, which is the specific failure a landing page
 * fixes — this one leads with the Task Designer and files the rest behind two
 * plainly-labelled cards.
 *
 * The sky is the page, as it is on the Dashboard: the rig's own constellation
 * with the library docked over it. That is not decoration — see `SkyBackdrop`
 * for why a route that mounts no constellation is the expensive case.
 */
export function Task() {
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const connected = status === "connected";
  const { specs, schema, unavailable, loading } = useSpecs();
  const { paradigms } = useParadigms();
  const { discovery } = useSettings();
  const { settings } = useSettings();

  const [error, setError] = useState<string | null>(null);

  /* Counted from the composed channel map the compiler serves, so the tile
   * reports this rig's wiring rather than the shipped pinout's size. */
  const channelCount = useMemo(() => {
    const channels = (schema?.channels as { channels?: object } | undefined)?.channels;
    return channels ? Object.keys(channels).length : 0;
  }, [schema]);


  // Every spec belongs to this rig now, so there is no origin to rank by.
  // Most-recently-touched first: the task someone is working on is the one they
  // came back for.
  const ordered = useMemo(
    () =>
      [...specs].sort(
        (a, b) =>
          (b.editedAt ?? "").localeCompare(a.editedAt ?? "") ||
          a.specId.localeCompare(b.specId),
      ),
    [specs],
  );

  const boundBoxes = settings.boxes.filter((b) => b.hardwareId !== null).length;

  /** Duplicate: the same rename-and-save the gallery and the wizard use, one
   * click deep and with the id chosen for you. `createSpecFrom` is that path's
   * single definition — three surfaces, one place the id-rewrite rule lives. */
  async function duplicate(specId: string) {
    setError(null);
    try {
      const reply = await getSpec(client, specId);
      if (!reply.raw) {
        setError(`${specId} won't parse, so there is nothing to copy.`);
        return;
      }
      const id = suggestId(specId, new Set(specs.map((s) => s.specId)));
      if (id === "") return;
      await createSpecFrom(client, reply.raw, { id });
      navigate(`/task/designer/${id}`);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="relative h-full">
      <SkyBackdrop />

      <motion.div
        initial={{ opacity: 0, y: PANEL_TRAVEL }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        <section className="pointer-events-auto mx-auto max-w-5xl px-8 py-8">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
              <Workflow size={18} strokeWidth={1.75} className="text-pulsar" />
            </span>
            <h1 className="font-display text-[22px] text-starlight">Task</h1>
          </div>

          {unavailable ? (
            <div
              className="hud mt-6 flex items-start gap-2 rounded-md px-4 py-3.5 text-[12px] leading-relaxed"
              style={{ color: "var(--color-status-warning)" }}
            >
              <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
              <span>
                {unavailable} Everything else — sketches, sessions, flashing — is
                unaffected.
              </span>
            </div>
          ) : (
            <>
              {/* The hero. One affordance, stated as what it is for rather than
              what it opens: a task is a state machine, and this is where you
              build one. */}
              <div className="hud mt-6 rounded-md px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h2 className="font-display text-[16px] text-starlight">
                      Task Designer
                    </h2>
                    <p className="mt-1 max-w-prose text-[12px] leading-relaxed text-static">
                      A task is a state machine, and here it is data: declare the
                      epochs, the contingencies and the timings, and the compiler
                      builds the byte table a box walks. Every edit is checked by
                      the same compiler that produces the table.
                    </p>
                  </div>
                  <Button
                    variant="primary"
                    disabled={!connected}
                    onClick={() => navigate("/task/new")}
                  >
                    <Plus size={13} strokeWidth={1.75} />
                    New task
                  </Button>
                </div>

                <div className="mt-4 border-t border-halo pt-3">
                  {loading ? (
                    <p className="text-[12px] text-static">Reading the library…</p>
                  ) : ordered.length === 0 ? (
                    <EmptyLibrary
                      paradigms={paradigms}
                      onPick={(id) => navigate(`/task/new?paradigm=${id}`)}
                    />
                  ) : (
                    <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                      {ordered.map((spec) => (
                        <SpecCard
                          key={spec.specId}
                          spec={spec}
                          onOpen={() => navigate(`/task/designer/${spec.specId}`)}
                          onDuplicate={() => void duplicate(spec.specId)}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {error && (
                <p
                  className="mt-2 text-[11px]"
                  style={{ color: "var(--color-status-error)" }}
                >
                  {error}
                </p>
              )}
            </>
          )}

          <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {/* RIG WIRING SITS WITH TASK, not Config, even though Config owns
                "how is this rig wired" (settings.md §1). Every hardware value in
                task creation comes from here — response ports, reward lines,
                stimulus lines — and filing it a tab away from the thing that
                consumes it would be filing by category rather than by use. */}
            <LinkCard
              icon={Waypoints}
              title="Rig wiring"
              onClick={() => navigate("/task/hardware")}
              detail={`${channelCount} channels`}
            >
              Which pin each channel is on, and what it means. Everything a task
              can reach — the ports, the reward lines, the stimulus lines — is
              what this says it is.
            </LinkCard>

            <LinkCard
              icon={CpuIcon}
              title="Bench"
              onClick={() => navigate("/task/bench")}
              detail={`${boundBoxes} box${boundBoxes === 1 ? "" : "es"} bound`}
            >
              Put a compiled table on a board and read back what it says about
              itself.{" "}
              <span style={{ color: "var(--color-status-warning)" }}>
                Bench only — a box carrying the interpreter runs no trial and
                delivers no reward.
              </span>
            </LinkCard>

            <LinkCard
              icon={FileCode2}
              title="Sketches"
              onClick={() => navigate("/task/sketches")}
              detail={`${discovery.sketches.length} in the library`}
            >
              The firmware sketches that run today&rsquo;s sessions, their trial
              flow, and this rig&rsquo;s default parameters for each.
            </LinkCard>
          </div>
        </section>
      </motion.div>

    </div>
  );
}

function SpecCard({
  spec,
  onOpen,
  onDuplicate,
}: {
  spec: SpecEntry;
  onOpen: () => void;
  onDuplicate: () => void;
}) {
  const chip = originChip(spec.origin);
  return (
    <div className="group relative rounded-sm border border-halo px-2.5 py-2 transition-colors hover:border-static/60">
      <button type="button" onClick={onOpen} className="w-full text-left">
        <div className="flex items-baseline gap-2">
          <span className="truncate text-[12px] text-starlight">
            {spec.label ?? spec.specId}
          </span>
          <span
            className="shrink-0 font-mono text-[8.5px] tracking-wider"
            style={{ color: chip.color }}
          >
            {chip.label}
          </span>
        </div>
        <div className="mt-0.5 font-mono text-[9.5px] text-static/70">
          {spec.specId}
          {spec.template && ` · ${spec.template} v${spec.templateVersion}`}
          {spec.editedAt && ` · edited ${shortDate(spec.editedAt)}`}
        </div>
        {spec.description && (
          <p className="mt-1 line-clamp-2 text-[10.5px] leading-relaxed text-static">
            {spec.description}
          </p>
        )}
      </button>
      <button
        type="button"
        onClick={onDuplicate}
        title={`Duplicate ${spec.specId}`}
        aria-label={`Duplicate ${spec.specId}`}
        className="absolute top-1.5 right-1.5 rounded-sm p-1 text-static opacity-0 transition-opacity group-hover:opacity-100 hover:text-starlight focus-visible:opacity-100"
      >
        <Copy size={12} strokeWidth={1.75} />
      </button>
    </div>
  );
}

function LinkCard({
  icon: Icon,
  title,
  detail,
  onClick,
  children,
}: {
  icon: typeof Workflow;
  title: string;
  detail: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="hud group rounded-md px-4 py-3 text-left transition-colors hover:border-static/50"
    >
      <div className="flex items-center gap-2">
        <Icon size={14} strokeWidth={1.75} className="text-static" />
        <span className="text-[13px] font-medium text-starlight">{title}</span>
        <span className="ml-auto flex items-center gap-1 font-mono text-[9.5px] text-static/70">
          {detail}
          <ArrowRight
            size={11}
            strokeWidth={1.75}
            className="transition-transform group-hover:translate-x-0.5"
          />
        </span>
      </div>
      <p className="mt-1 text-[11px] leading-relaxed text-static">{children}</p>
    </button>
  );
}

/** ISO-8601 → `2026-08-03`. The timestamp's date half is all a card needs. */
function shortDate(iso: string): string {
  return iso.slice(0, 10);
}

/**
 * The first thing a new rig sees, so it is the front door rather than a footnote.
 *
 * Nothing ships as a spec any more: an install has zero tasks until somebody
 * makes one. The old copy — one grey line reading "start one from a paradigm" —
 * was written for a library that already had five in it, and pointed at a button
 * instead of being the thing itself.
 */
function EmptyLibrary({
  paradigms,
  onPick,
}: {
  paradigms: ParadigmSummary[];
  onPick: (paradigmId: string) => void;
}) {
  if (paradigms.length === 0) {
    return <p className="text-[12px] text-static">Reading the paradigms…</p>;
  }
  return (
    <div>
      <p className="max-w-prose text-[12px] leading-relaxed text-static">
        <span className="text-starlight">No tasks on this rig yet.</span> Every task
        starts from a paradigm — the shape of an experiment, which the compiler and
        the linter already agree on. Pick one and answer the questions; the machine
        is drawn beside you the whole way.
      </p>
      <div className="mt-3 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
        {paradigms.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => onPick(p.id)}
            className="min-w-0 rounded-sm border border-halo px-2.5 py-2 text-left transition-colors hover:border-pulsar"
          >
            <div className="text-[12px] text-starlight">{p.name}</div>
            <p className="mt-1 line-clamp-2 text-[10.5px] leading-relaxed text-static">
              {p.affords}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}

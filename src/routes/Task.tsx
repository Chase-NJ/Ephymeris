import { motion } from "framer-motion";
import {
  ArrowRight,
  CircleAlert,
  Copy,
  CpuIcon,
  FileCode2,
  Plus,
  Rocket,
  Waypoints,
  Workflow,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { ParadigmCard } from "@/components/specs/ParadigmCard";

import {
  CardFooterNote,
  SummaryCard,
} from "@/components/common/SummaryCard";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { errorMessage } from "@/lib/cohorts/commands";
import { PANEL_TRAVEL, springPanel, springSnappy } from "@/lib/motion";
import { getSpec } from "@/lib/specs/commands";
import { createSpecFrom, suggestId } from "@/lib/specs/create";
import type { SpecEntry } from "@/lib/specs/types";
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
  /* `hidden` keeps `blank` out: it is what the hero above already does, not one
   * of the alternatives to it. */
  const templates = useMemo(() => paradigms.filter((p) => !p.hidden), [paradigms]);
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
            <div className="min-w-0">
              <h1 className="font-display text-[22px] text-starlight">Task</h1>
              <p className="font-mono text-[10px] text-static/70">
                what the animal does, and what the box is built out of
              </p>
            </div>
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
              {/* THE HERO, and the only thing on this page that is a button
                  rather than a tile. A task is a state machine, and this is
                  where one gets built; everything below is where the parts of
                  it live. */}
              <HeroButton
                disabled={!connected}
                onClick={() => navigate("/task/new")}
                title={ordered.length === 0 ? "Design your first task" : "Design a task"}
                subtitle={
                  connected
                    ? "One question at a time, in the order a trial happens — and it compiles at every step"
                    : "Waiting for the sidecar"
                }
              />

              {error && (
                <p
                  className="mt-2 text-[11px]"
                  style={{ color: "var(--color-status-error)" }}
                >
                  {error}
                </p>
              )}

              {/* Two columns of tiles over the sky, the Dashboard's shape. The
                  library is the tall one and leads, because a rig that has
                  tasks came here to open one. */}
              <div className="mt-4 grid grid-cols-1 items-start gap-3 lg:grid-cols-2">
                <div className="flex flex-col gap-3">
                  <SummaryCard
                    icon={Workflow}
                    label="Tasks"
                    status={
                      loading
                        ? "reading…"
                        : `${ordered.length} on this rig`
                    }
                    empty={
                      !loading && ordered.length === 0
                        ? "Nothing ships as a task — every one on a rig is that rig's own. Design one above, or start from a template below."
                        : null
                    }
                  >
                    {ordered.map((spec) => (
                      <SpecRow
                        key={spec.specId}
                        spec={spec}
                        onOpen={() => navigate(`/task/designer/${spec.specId}`)}
                        onDuplicate={() => void duplicate(spec.specId)}
                      />
                    ))}
                  </SummaryCard>

                  {/* Templates, only while there is nothing to open. Once a rig
                      has tasks the wizard's own quiet link is the way in, and a
                      permanent gallery here would compete with the library it
                      sits under. */}
                  {!loading && ordered.length === 0 && templates.length > 0 && (
                    <SummaryCard
                      icon={Rocket}
                      label="Start from a template"
                      status={`${templates.length} shapes`}
                      empty={null}
                    >
                      <div className="mt-1 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                        {templates.map((p) => (
                          <ParadigmCard
                            key={p.id}
                            paradigm={p}
                            compact
                            onClick={() => navigate(`/task/new?paradigm=${p.id}`)}
                          />
                        ))}
                      </div>
                    </SummaryCard>
                  )}
                </div>

                <div className="flex flex-col gap-3">
                  {/* Rig wiring lives on the Rig screen now — box↔board and
                      channel↔pin are one subject there. This card stays
                      because every hardware value in task creation comes from
                      the channel map, and the flow that consumes it deserves a
                      door to it; the door just crosses a tab, like the
                      Dashboard's tiles do. */}
                  <SummaryCard
                    icon={Waypoints}
                    label="Rig wiring"
                    status={`${channelCount} channels`}
                    onOpen={() => navigate("/config")}
                    empty="Which pin each channel is on. Everything a task can reach — the ports, the reward lines, the stimulus lines — is what this says it is. On the Rig tab, with the rest of the rig."
                  />

                  {/* The sketch library, which used to be its own sidebar tab.
                      It sits with Rig wiring and the Bench rather than beside
                      the spec library on the left, because those three are the
                      *parts* a task is assembled from while the left column is
                      the tasks themselves. It is deliberately not a count of
                      sketches: the library list is `settings.discovery`, which
                      this page doesn't otherwise read, and the tile's job is to
                      be a door rather than a readout. */}
                  <SummaryCard
                    icon={FileCode2}
                    label="Sketches"
                    status="shipped firmware"
                    onOpen={() => navigate("/task/sketches")}
                    empty="The behaviour sketches that ship with Ephymeris, each one's trial flow, and this rig's parameters for them — the path that runs animals today."
                  />

                  <SummaryCard
                    icon={CpuIcon}
                    label="Bench"
                    status={`${boundBoxes} box${boundBoxes === 1 ? "" : "es"} bound`}
                    onOpen={() => navigate("/task/bench")}
                    empty={null}
                  >
                    <p className="py-1 text-[12px] leading-relaxed text-static">
                      Put a compiled table on a board and read back what it says
                      about itself.
                    </p>
                    <CardFooterNote>
                      <span style={{ color: "var(--color-status-warning)" }}>
                        bench only — no trial runs, no reward is delivered
                      </span>
                    </CardFooterNote>
                  </SummaryCard>
                </div>
              </div>
            </>
          )}
        </section>
      </motion.div>
    </div>
  );
}

/**
 * The page's one primary action, in the Dashboard's hero idiom — a filled
 * Pulsar slab rather than a tile, so there is never a question about which
 * thing on this page is the thing to press.
 */
function HeroButton({
  title,
  subtitle,
  disabled,
  onClick,
}: {
  title: string;
  subtitle: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <motion.button
      type="button"
      disabled={disabled}
      onClick={onClick}
      {...(disabled ? {} : { whileHover: { scale: 1.006 }, whileTap: { scale: 0.997 } })}
      transition={springSnappy}
      className="group mt-6 flex w-full items-center gap-3 rounded-md bg-pulsar px-5 py-4 text-left disabled:opacity-50"
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-void/15">
        <Plus size={18} strokeWidth={2} className="text-void" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-display text-base font-semibold text-void">
          {title}
        </span>
        <span className="mt-0.5 block text-[12px] text-void/70">{subtitle}</span>
      </span>
      <ArrowRight
        size={18}
        strokeWidth={2}
        className="shrink-0 text-void transition-transform group-hover:translate-x-0.5"
      />
    </motion.button>
  );
}



/** ISO-8601 → `2026-08-03`. The timestamp's date half is all a card needs. */
function shortDate(iso: string): string {
  return iso.slice(0, 10);
}

/**
 * One task in the library tile.
 *
 * A row rather than a card: the library is now a `SummaryCard`'s row list like
 * every other tile on the page, so a task reads at the same weight as a cohort
 * does on the Dashboard. Not `CardRow` itself, because the duplicate action
 * needs its own button and a button inside a button is invalid — so this is the
 * same metrics with the hover treatment on the wrapper.
 */
function SpecRow({
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
    <div className="group -mx-1.5 flex items-center gap-2 rounded-sm px-1.5 py-1.5 transition-colors hover:bg-halo/50">
      <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left">
        <span className="flex items-baseline gap-2">
          <span className="min-w-0 truncate text-[13px] text-starlight">
            {spec.label ?? spec.specId}
          </span>
          <span
            className="shrink-0 font-mono text-[8.5px] tracking-wider"
            style={{ color: chip.color }}
          >
            {chip.label}
          </span>
        </span>
        <span className="mt-0.5 block truncate font-mono text-[9.5px] text-static/70">
          {spec.specId}
          {spec.editedAt && ` · edited ${shortDate(spec.editedAt)}`}
        </span>
      </button>
      <button
        type="button"
        onClick={onDuplicate}
        title={`Duplicate ${spec.specId}`}
        aria-label={`Duplicate ${spec.specId}`}
        className="shrink-0 rounded-sm p-1 text-static opacity-0 transition-opacity group-hover:opacity-100 hover:text-starlight focus-visible:opacity-100"
      >
        <Copy size={12} strokeWidth={1.75} />
      </button>
    </div>
  );
}

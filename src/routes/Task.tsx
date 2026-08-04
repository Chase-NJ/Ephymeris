import { motion } from "framer-motion";
import {
  ArrowRight,
  CircleAlert,
  Copy,
  CpuIcon,
  FileCode2,
  Plus,
  Workflow,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { Button } from "@/components/common/controls";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { NewSpecGallery } from "@/components/specs/NewSpecGallery";
import { errorMessage } from "@/lib/cohorts/commands";
import { PANEL_TRAVEL, springPanel } from "@/lib/motion";
import { getSpec } from "@/lib/specs/commands";
import { createSpecFrom, suggestId } from "@/lib/specs/create";
import type { SpecEntry } from "@/lib/specs/types";
import { originChip } from "@/lib/specs/useSpecDocument";
import { useSpecs } from "@/lib/specs/useSpecs";
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
  const { specs, unavailable, loading } = useSpecs();
  const { discovery } = useSettings();
  const { settings } = useSettings();

  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ordered = useMemo(
    () =>
      [...specs].sort((a, b) => {
        // A rig's own tasks first — those are the ones someone here made a
        // decision about. Shipped paradigms are reference material below them.
        const rank = (s: SpecEntry) => (s.origin === "user" ? 0 : s.origin === "shipped_edited" ? 1 : 2);
        return rank(a) - rank(b) || a.specId.localeCompare(b.specId);
      }),
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
                    onClick={() => setCreating(true)}
                  >
                    <Plus size={13} strokeWidth={1.75} />
                    New task
                  </Button>
                </div>

                <div className="mt-4 border-t border-halo pt-3">
                  {loading ? (
                    <p className="text-[12px] text-static">Reading the library…</p>
                  ) : ordered.length === 0 ? (
                    <p className="text-[12px] text-static">
                      No task specs yet. Start one from a paradigm.
                    </p>
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

      <NewSpecGallery
        open={creating}
        onClose={() => setCreating(false)}
        specs={specs}
        onCreated={(id) => {
          setCreating(false);
          navigate(`/task/designer/${id}`);
        }}
        onDesign={(recipeId) =>
          navigate(recipeId ? `/task/new?recipe=${recipeId}` : "/task/new")
        }
      />
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

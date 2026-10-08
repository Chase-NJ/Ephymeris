import { AnimatePresence, motion } from "framer-motion";
import { Braces, Check, CircleAlert, FileImage, FileText, X, type LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { FolderButton } from "@/components/common/FolderButton";
import { DONE_LINGER_MS, exportJobs, useExportJobs, type ExportJob, type ExportKind } from "@/lib/exports/jobs";
import { springPanel, springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";

const ICON: Record<ExportKind, LucideIcon> = { image: FileImage, pdf: FileText, json: Braces };

/**
 * The export cards (`ARCHITECTURE.md#export-progress`): one per export in
 * flight, stacked in the bottom-right corner above every route.
 *
 * Mounted once in `AppShell` and portalled to `body` — fixed positioning is
 * relative to the nearest transformed ancestor, and the route transition
 * transforms. A card rises in when an export starts, its segmented bar fills
 * step by step, and it settles to the saved file before sliding out on its
 * own; a failure stays until dismissed. A cancelled save dialog simply takes
 * the card away — not choosing a place is an outcome, not news.
 */
export function ExportProgress() {
  const jobs = useExportJobs();
  return createPortal(
    <div
      aria-live="polite"
      className="pointer-events-none fixed right-5 bottom-5 z-40 flex w-[320px] flex-col gap-2"
    >
      <AnimatePresence initial={false}>
        {jobs.map((job) => (
          <ExportCard key={job.id} job={job} />
        ))}
      </AnimatePresence>
    </div>,
    document.body,
  );
}

function ExportCard({ job }: { job: ExportJob }) {
  const [hovered, setHovered] = useState(false);
  const Icon = job.state === "done" ? Check : job.state === "failed" ? CircleAlert : ICON[job.kind];
  const tone =
    job.state === "done"
      ? "var(--color-ion)"
      : job.state === "failed"
        ? "var(--color-status-error)"
        : "var(--color-pulsar)";

  // A finished card leaves on its own, but not from under the pointer.
  useEffect(() => {
    if (job.state !== "done" || hovered) return;
    const timer = window.setTimeout(() => exportJobs.dismiss(job.id), DONE_LINGER_MS);
    return () => window.clearTimeout(timer);
  }, [job.state, job.id, hovered]);

  const file = job.path?.split(/[\\/]/).pop() ?? null;
  const folder = job.path ? job.path.slice(0, job.path.length - (file?.length ?? 0)) : null;

  return (
    <motion.section
      layout
      role={job.state === "failed" ? "alert" : "status"}
      initial={{ opacity: 0, y: 18, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 28, scale: 0.98, transition: springSnappy }}
      transition={springPanel}
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
      className="hud-front pointer-events-auto rounded-md px-3.5 pt-3 pb-3"
    >
      <div className="flex items-center gap-2.5">
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span
            key={job.state}
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.6 }}
            transition={springSnappy}
            className="flex shrink-0"
            style={{ color: tone }}
          >
            <Icon size={15} strokeWidth={1.75} />
          </motion.span>
        </AnimatePresence>
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-starlight">
          {job.title}
          {job.state === "done" && <span className="font-normal text-static"> saved</span>}
        </span>
        {job.state === "running" ? (
          <span className="shrink-0 font-mono text-[10px] text-static/70 tabular-nums">
            {job.step + 1} / {job.steps.length}
          </span>
        ) : (
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => exportJobs.dismiss(job.id)}
            className="flex size-5 shrink-0 items-center justify-center rounded-sm text-static transition-colors hover:bg-halo/60 hover:text-starlight"
          >
            <X size={12} strokeWidth={1.75} />
          </button>
        )}
      </div>

      <div className="mt-1.5 min-h-[18px] pl-[25px]">
        {job.state === "running" && (
          <motion.p
            key={job.step}
            initial={{ opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            transition={springSnappy}
            className="font-mono text-[11px] text-static"
          >
            {job.steps[job.step]}
            {job.progress !== null && job.progress > 0 && job.progress < 1 && (
              <span className="text-static/60 tabular-nums"> · {Math.round(job.progress * 100)}%</span>
            )}
          </motion.p>
        )}
        {job.state === "done" && (
          <div className="flex items-center justify-between gap-2">
            <span className="min-w-0 truncate font-mono text-[11px] text-static" title={job.path ?? undefined}>
              {file}
            </span>
            {folder && <FolderButton path={folder} label="Show" title={folder} size="sm" />}
          </div>
        )}
        {job.state === "failed" && (
          <p className="text-[12px] leading-relaxed" style={{ color: "var(--color-status-error)" }}>
            {job.error}
          </p>
        )}
      </div>

      <StepBar job={job} tone={tone} />
    </motion.section>
  );
}

/** One segment per declared step: done ones full, the current one filling to
 *  its fraction — or breathing, when its worker cannot say how far it is. */
function StepBar({ job, tone }: { job: ExportJob; tone: string }) {
  const reduceMotion = useReduceMotion();
  return (
    <div className="mt-2.5 flex gap-1" aria-hidden>
      {job.steps.map((name, i) => {
        // Done fills every segment; a failure fills up to the step that
        // failed and no further, so the bar says how far it got.
        const fill =
          job.state === "done" || i < job.step
            ? 1
            : i > job.step
              ? 0
              : job.state === "failed"
                ? 1
                : (job.progress ?? null);
        return (
          <span key={name} className="relative h-[3px] flex-1 overflow-hidden rounded-full bg-halo/80">
            {fill === null ? (
              <motion.span
                className="absolute inset-0 rounded-full"
                style={{ background: tone }}
                initial={{ opacity: 0.25 }}
                animate={reduceMotion ? { opacity: 0.6 } : { opacity: [0.25, 0.85, 0.25] }}
                transition={reduceMotion ? springSnappy : { duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
              />
            ) : (
              <motion.span
                className="absolute inset-y-0 left-0 rounded-full"
                style={{ background: tone }}
                initial={false}
                animate={{ width: `${fill * 100}%` }}
                transition={springPanel}
              />
            )}
          </span>
        );
      })}
    </div>
  );
}

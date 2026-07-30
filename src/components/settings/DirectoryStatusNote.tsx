import { Check, CircleAlert, FolderOpen, RefreshCw } from "lucide-react";
import { motion } from "framer-motion";

import { Button } from "@/components/common/controls";
import { springPanel } from "@/lib/motion";
import type { SketchDiscovery } from "@/lib/settings/schema";

/**
 * Surfaces the four Arduino Directory states from `tasks.md` §2.4 as
 * four distinct treatments rather than one generic "error".
 *
 * "Partial" is derived: state `ok` with a non-zero skipped count. It's
 * non-blocking by design — the sketch list still populates, with a note so a
 * misnamed folder is discoverable rather than mysteriously absent.
 */
export function DirectoryStatusNote({
  discovery,
  onRefresh,
  canRefresh,
}: {
  discovery: SketchDiscovery;
  onRefresh: () => void;
  canRefresh: boolean;
}) {
  const { directory, sketches, skippedCount, libraries } = discovery;

  const tone =
    directory.state === "invalid"
      ? "error"
      : directory.state === "ok"
        ? skippedCount > 0
          ? "warning"
          : "ok"
        : "neutral";

  const color = {
    error: "var(--color-status-error)",
    warning: "var(--color-status-warning)",
    ok: "var(--color-status-ok)",
    neutral: "var(--color-static)",
  }[tone];

  return (
    <motion.div
      layout
      transition={springPanel}
      className="mt-2 flex items-start gap-2.5 rounded-sm border border-halo bg-void/40 px-3 py-2.5"
    >
      <span className="mt-px shrink-0" style={{ color }}>
        {directory.state === "ok" && skippedCount === 0 ? (
          <Check size={14} strokeWidth={2} />
        ) : directory.state === "not_configured" ? (
          <FolderOpen size={14} strokeWidth={1.75} />
        ) : (
          <CircleAlert size={14} strokeWidth={1.75} />
        )}
      </span>

      <div className="min-w-0 flex-1 text-[12px] leading-relaxed">
        <Body
          state={directory.state}
          message={directory.message}
          sketchCount={sketches.length}
          skippedCount={skippedCount}
          libraryCount={libraries.length}
        />
      </div>

      {directory.state !== "not_configured" && (
        <Button variant="ghost" onClick={onRefresh} disabled={!canRefresh} title="Rescan">
          <RefreshCw size={13} strokeWidth={1.75} />
        </Button>
      )}
    </motion.div>
  );
}

function Body({
  state,
  message,
  sketchCount,
  skippedCount,
  libraryCount,
}: {
  state: SketchDiscovery["directory"]["state"];
  message: string | null;
  sketchCount: number;
  skippedCount: number;
  libraryCount: number;
}) {
  // Expected on first run, not an error.
  if (state === "not_configured") {
    return (
      <span className="text-static">
        No Arduino Directory set yet. Choose the folder holding your sketch
        categories and shared <code className="font-mono">libraries/</code>.
      </span>
    );
  }

  if (state === "invalid") {
    return (
      <span className="text-starlight">
        {message ?? "Can't find your configured Arduino Directory."}
      </span>
    );
  }

  if (state === "empty") {
    return (
      <span className="text-static">
        {message ??
          "No valid sketches found. A sketch folder must contain a .ino file with the same name as the folder."}
      </span>
    );
  }

  return (
    <span className="text-static">
      <span className="font-mono text-starlight">{sketchCount}</span>{" "}
      {sketchCount === 1 ? "sketch" : "sketches"} found
      {libraryCount > 0 && (
        <>
          {" · "}
          <span className="font-mono text-starlight">{libraryCount}</span>{" "}
          {libraryCount === 1 ? "library" : "libraries"}
        </>
      )}
      {skippedCount > 0 && (
        <>
          {" · "}
          <span style={{ color: "var(--color-status-warning)" }}>
            {skippedCount} {skippedCount === 1 ? "item" : "items"} couldn't be read
          </span>
        </>
      )}
    </span>
  );
}

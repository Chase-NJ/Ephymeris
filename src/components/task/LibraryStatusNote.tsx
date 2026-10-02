import { Check, CircleAlert, RefreshCw } from "lucide-react";
import { motion } from "framer-motion";

import { Button } from "@/components/common/controls";
import { springPanel } from "@/lib/motion";
import type { SketchDiscovery } from "@/lib/settings/schema";

/**
 * The bundled sketch library's state (`TASKS.md#library-states`) — three
 * states, each with its own treatment rather than one generic "error".
 *
 * Every non-ok state means a broken or partial install, never a wrong setting:
 * sketches ship with the app, so there is no picker to send anyone to and no
 * "not configured yet". The copy therefore points at reinstalling — a genuine
 * inversion of the note this replaced, which offered a directory field.
 *
 * "Partial" is derived: state `ok` with a non-zero skipped count. Non-blocking
 * by design — the sketch list still populates, with a note so a misnamed folder
 * is discoverable rather than mysteriously absent.
 */
export function LibraryStatusNote({
  discovery,
  onRefresh,
  canRefresh,
}: {
  discovery: SketchDiscovery;
  onRefresh: () => void;
  canRefresh: boolean;
}) {
  const { library, sketches, skippedCount, libraries } = discovery;

  const tone =
    library.state === "damaged"
      ? "error"
      : library.state === "empty"
        ? "error"
        : skippedCount > 0
          ? "warning"
          : "ok";

  const color = {
    error: "var(--color-status-error)",
    warning: "var(--color-status-warning)",
    ok: "var(--color-status-ok)",
  }[tone];

  return (
    <motion.div
      layout
      transition={springPanel}
      className="mt-2 flex items-start gap-2.5 rounded-sm border border-halo bg-void/40 px-3 py-2.5"
    >
      <span className="mt-px shrink-0" style={{ color }}>
        {library.state === "ok" && skippedCount === 0 ? (
          <Check size={14} strokeWidth={2} />
        ) : (
          <CircleAlert size={14} strokeWidth={1.75} />
        )}
      </span>

      <div className="min-w-0 flex-1 text-[12px] leading-relaxed">
        {library.state !== "ok" ? (
          <span className="text-starlight">
            {library.message ??
              "Ephymeris couldn't find the sketches it ships with. The install " +
                "looks incomplete — reinstalling should fix it."}
          </span>
        ) : (
          <span className="text-static">
            <span className="font-mono text-starlight">{sketches.length}</span>{" "}
            {sketches.length === 1 ? "sketch ships" : "sketches ship"} with this
            version of Ephymeris
            {libraries.length > 0 && (
              <>
                {" · "}
                <span className="font-mono text-starlight">
                  {libraries.length}
                </span>{" "}
                {libraries.length === 1 ? "library" : "libraries"}
              </>
            )}
            {skippedCount > 0 && (
              <>
                {" · "}
                <span style={{ color: "var(--color-status-warning)" }}>
                  {skippedCount} {skippedCount === 1 ? "item" : "items"} couldn't
                  be read
                </span>
              </>
            )}
            {". Adding or changing a sketch needs a new build — talk to whoever "}
            maintains the app.
          </span>
        )}
      </div>

      <Button variant="ghost" onClick={onRefresh} disabled={!canRefresh} title="Rescan">
        <RefreshCw size={13} strokeWidth={1.75} />
      </Button>
    </motion.div>
  );
}

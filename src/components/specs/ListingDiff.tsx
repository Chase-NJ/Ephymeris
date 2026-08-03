import { useEffect, useState } from "react";

import { Modal } from "@/components/common/Modal";
import { Select } from "@/components/common/controls";
import { errorMessage } from "@/lib/cohorts/commands";
import { diffSpec } from "@/lib/specs/commands";
import type { SpecEntry, SpecListingDiff } from "@/lib/specs/types";
import type { SidecarClient } from "@/lib/ws/client";

/**
 * The listing diff, presented as a REVIEW rather than a wall of lines.
 *
 * Headline first — `26 → 29 states · 462 → 508 bytes` — because that is what a
 * reviewer wants before any hunk. Then hunks grouped by the listing's own
 * sections, so a change reads as "in STATES". The provenance strip carries the
 * two hashes that move on every edit and are deliberately not hunks.
 *
 * The baseline selector is how the shaping_gr / shaping_gr_ez claim gets read:
 * pick "another spec" and the diff of an eased variant against its base shows
 * value sections only — no STATES hunks — which is the layer-3 promise made
 * visible.
 */
export function ListingDiff({
  open,
  onClose,
  client,
  specId,
  text,
  specs,
  hasShipped,
}: {
  open: boolean;
  onClose: () => void;
  client: SidecarClient;
  specId: string;
  /** The editor's current document, serialized — the AFTER side. */
  text: string;
  specs: SpecEntry[];
  hasShipped: boolean;
}) {
  const [against, setAgainst] = useState<string>(hasShipped ? "@shipped" : "@saved");
  const [diff, setDiff] = useState<SpecListingDiff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    const args =
      against === "@shipped"
        ? { baseline: "shipped" as const }
        : against === "@saved"
          ? { baseline: "saved" as const }
          : { againstSpecId: against };
    void diffSpec(client, specId, text, args)
      .then((reply) => {
        if (!cancelled) setDiff(reply);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, against, client, specId, text]);

  return (
    <Modal open={open} onClose={onClose} title={`Review ${specId}`}>
      <div className="flex items-center justify-between gap-3 pb-2">
        <span className="text-[12px] text-static">Compare against</span>
        <Select
          label="Baseline"
          value={against}
          options={[
            ...(hasShipped ? [{ value: "@shipped", label: "the shipped version" }] : []),
            { value: "@saved", label: "the saved file" },
            ...specs
              .filter((s) => s.specId !== specId)
              .map((s) => ({ value: s.specId, label: `spec: ${s.specId}` })),
          ]}
          onChange={(v) => setAgainst(String(v))}
          className="w-[220px]"
        />
      </div>

      {loading && <p className="text-[12px] text-static">comparing…</p>}
      {error && (
        <p className="text-[12px]" style={{ color: "var(--color-status-error)" }}>
          {error}
        </p>
      )}

      {diff && !loading && (
        <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto pr-1">
          <Headline diff={diff} />

          {!diff.changed && (
            <p className="text-[12px] text-static">
              No differences — the compiled table is identical.
            </p>
          )}

          {(diff.before === null || diff.after === null) && (
            <p className="text-[12px]" style={{ color: "var(--color-status-warning)" }}>
              {diff.after === null
                ? "The current document doesn't compile, so there is no listing to compare — see the diagnostics below the form."
                : "The baseline doesn't compile; nothing to compare against."}
            </p>
          )}

          {diff.hunks.map((hunk) => (
            <section key={hunk.section}>
              <header className="border-b border-halo pb-0.5 font-mono text-[10px] uppercase tracking-wider text-static">
                {hunk.section}
              </header>
              <pre
                data-selectable
                className="mt-1 overflow-x-auto font-mono text-[10.5px] leading-[1.55]"
              >
                {hunk.lines.map((line, i) => (
                  <div
                    key={i}
                    style={{
                      color:
                        line.op === "+"
                          ? "var(--color-ion)"
                          : line.op === "-"
                            ? "var(--color-status-error)"
                            : "var(--color-static)",
                      opacity: line.op === " " ? 0.55 : 1,
                    }}
                  >
                    {line.op}
                    {line.text}
                  </div>
                ))}
              </pre>
            </section>
          ))}
        </div>
      )}
    </Modal>
  );
}

function Headline({ diff }: { diff: SpecListingDiff }) {
  const { before, after } = diff;
  if (!before || !after) return null;
  const pair = (a: number, b: number, unit: string) =>
    a === b ? `${b} ${unit}` : `${a} → ${b} ${unit}`;
  return (
    <div className="rounded-sm border border-halo px-2.5 py-2">
      <div className="font-mono text-[11px] text-starlight">
        {pair(before.nNodes, after.nNodes, "states")} ·{" "}
        {pair(before.nEdges, after.nEdges, "edges")} ·{" "}
        {pair(before.nTiming, after.nTiming, "timing")} ·{" "}
        {pair(before.sizeBytes, after.sizeBytes, "bytes")}
      </div>
      {/* The provenance strip: the hashes that move on every edit, shown once
      here and excluded from the hunks so they can't top every diff. */}
      <div className="mt-1 font-mono text-[9.5px] text-static/70">
        spec {before.specHash} → {after.specHash} · template {after.template} v
        {after.templateVersion} ({after.templateHash})
      </div>
    </div>
  );
}
